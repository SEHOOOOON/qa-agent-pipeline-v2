"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_existing_test_selection_accepts_versioned_official_tc_id():
    selection = ExistingTestSelection(
        tc_id="TC-V2-001",
        source_condition_ids=["COND-001"],
        selection_reason="승인된 V2 공식 TC를 영향 회귀 대상으로 재사용한다.",
    )

    assert selection.tc_id == "TC-V2-001"

def test_request_diff_recognizes_repeated_existing_clause_as_unchanged():
    request = ChangeRequest(
        request_id="CR-FAN-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-FAN-001",
        before_value="HIGH는 장비 카드에 강풍으로 표시됩니다.",
        after_value="MED는 장비 카드에 중풍으로, HIGH는 강풍으로 표시됩니다.",
        description="MED 표시 규칙을 추가합니다.",
    )
    existing_high = ConfirmedCondition(
        condition_id="COND-001",
        statement="HIGH는 장비 카드에 강풍으로 표시되어야 한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=request.after_value,
        requirement_ids=["REQ-FAN-001"],
        change_role=ConditionChangeRole.UNCHANGED,
    )
    changed_medium = ConfirmedCondition(
        condition_id="COND-002",
        statement="MED는 장비 카드에 중풍으로 표시되어야 한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=request.after_value,
        requirement_ids=["REQ-FAN-001"],
        change_role=ConditionChangeRole.CHANGED,
    )

    assert _is_unchanged_condition_for_request(existing_high, request) is True
    assert _is_unchanged_condition_for_request(changed_medium, request) is False

def test_request_diff_treats_mapping_or_order_change_as_changed_without_explicit_role():
    request = ChangeRequest(
        request_id="CR-MAPPING-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-FAN-001",
        before_value="LOW 다음은 MED, MED 다음은 HIGH다.",
        after_value="LOW 다음은 HIGH, HIGH 다음은 MED다.",
        description="풍량 전환 순서를 변경한다.",
    )
    swapped_mapping = ConfirmedCondition(
        condition_id="COND-003",
        statement="LOW 다음 풍량은 HIGH다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=request.after_value,
        requirement_ids=["REQ-FAN-001"],
    )

    assert swapped_mapping.change_role == ConditionChangeRole.CHANGED
    assert _is_unchanged_condition_for_request(swapped_mapping, request) is False

def test_agent2_uses_structured_responses_api() -> None:
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
    )
    analysis = Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        change_summary="AUTO 모드 하한 변경",
        before_condition="16~30°C",
        after_condition="18~30°C",
        confirmed_conditions=[
            ConfirmedCondition(
                condition_id="COND-001",
                statement="18°C 미만 요청은 차단한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="18°C 미만 요청은 차단한다.",
                requirement_ids=["REQ-TEMP-001"],
            )
        ],
        requirement_effects=[
            RequirementEffect(
                requirement_id="REQ-TEMP-001",
                relation=RequirementRelation.MODIFIED,
                reason="하한 변경",
            )
        ],
        decision=AnalysisDecision.PROCEED,
    )

    response = agent.design(cp1_request(), analysis, {})

    assert response.response_id == "resp_agent2"
    assert response.usage["total_tokens"] == 300
    assert responses.kwargs["text_format"] is Agent2TestDesign
    assert responses.kwargs["store"] is False
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent2-2-18"
    agent2_input = responses.kwargs["input"][1]["content"]
    assert "[기존 사람 작성·자동화 TC 카탈로그]" in agent2_input
    assert "TC-TEMP-001" in agent2_input
    assert "TC-MODE-002" in agent2_input
    assert "검증 동작" in agent2_input
    assert "30°C 초과 요청 차단" in agent2_input
    assert "제품 기능 테스트케이스 후보" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Playwright 코드" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 confirmed_condition" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Requirement ID만 같고 검증 동작이 다르면" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "내부 필드 식별자" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "target_role=PRIMARY_TEST_DEVICE" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "V1의 3단계 QA 기준" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "independent_execution=true" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 실행 TC는 control_path=CENTRAL" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "TC 분리 단위는 입력값 하나가 아니라 하나의 업무 규칙" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "INDEPENDENT_VARIANTS" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "verify_after_step" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "제외된_정보_부족" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "전체 test_cases와 관련_기존_TC를 완전한 결과로 반환" in Path(
        "src/qa_pipeline_agent2.py"
    ).read_text(encoding="utf-8")

    agent.design(
        cp1_request(),
        analysis,
        {},
        previous_design=agent2_design(),
        checkpoint_feedback=[
            "CP2-001 PASS: 요청 ID 일치",
            "CP2-002 FAIL: 중복 ID",
        ],
    )
    rework_input = responses.kwargs["input"][1]["content"]
    assert "Checkpoint 2 전체 판정" in rework_input
    assert "CP2-001 PASS" in rework_input
    assert "PASS인 규칙과 그 근거를 보존" in rework_input
    assert "최종_확인_사항" in rework_input
    assert "중단_확인_사항" in rework_input

def test_agent2_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent2Error, match="OPENAI_API_KEY"):
        OpenAIAgent2()

def test_valid_design_passes_checkpoint2() -> None:
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), cp2_valid_design(), cp2_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 17
    assert all(item.status == CheckStatus.PASS for item in result.checks)

def test_checkpoint2_allows_existing_tc_only_when_behavior_covers_change() -> None:
    analysis = cp2_analysis()
    existing_spec = pipeline.ExistingRegressionSpec(
        tc_id="TC-V2-999",
        test_function="test_tc_v2_999",
        requirement_ids=("REQ-TEMP-001", "REQ-STATE-001", "REQ-NOTIFY-001"),
        covered_behaviors=("AUTO 18°C 미만 차단, 상태 유지, 차단 안내를 함께 검증",),
        source="APPROVED",
    )
    design = Agent2TestDesign(
        request_id=analysis.request_id,
        existing_tc_comparison_completed=True,
        related_existing_tests=[
            ExistingTestSelection(
                tc_id=existing_spec.tc_id,
                source_condition_ids=["COND-001", "COND-002", "COND-003"],
                selection_reason="변경 후 차단 동작과 유지 상태·안내를 이미 동일하게 검증한다.",
            )
        ],
        test_cases=[],
        coverage_summary="변경 후 동작을 기존 공식 TC 한 건으로 전부 재검증한다.",
    )

    result = evaluate_checkpoint2(
        cp1_request(),
        analysis,
        design,
        cp2_requirements(),
        existing_catalog=(*pipeline.EXISTING_REGRESSION_CATALOG, existing_spec),
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-008").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_checkpoint2_requires_grounded_srs_revision_proposal_for_modified_requirement() -> None:
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="범위 밖 차단",
        proposed_acceptance_criteria="AUTO 모드는 18~30°C를 허용하고 범위 밖 요청을 차단",
        reason="AUTO 모드 하한 변경을 기준 문서에 반영한다.",
    )
    design = cp2_valid_design().model_copy(
        update={"srs_revision_proposals": [proposal]}
    )

    passed = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design,
        cp2_requirements(),
        require_srs_revision_proposals=True,
    )
    missing = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        cp2_valid_design(),
        cp2_requirements(),
        require_srs_revision_proposals=True,
    )

    assert cp2_check(passed, "CP2-018").status == CheckStatus.PASS
    assert cp2_check(missing, "CP2-018").status == CheckStatus.FAIL
    assert "개정 제안 누락=REQ-TEMP-001" in cp2_check(missing, "CP2-018").message

def test_srs_revision_preview_apply_and_conflict_detection(tmp_path: Path) -> None:
    srs_file = tmp_path / "SRS.md"
    srs_file.write_text(
        "# SRS\n\n| ID | 요구사항 | 인수 기준 |\n"
        "|---|---|---|\n"
        "| REQ-TEMP-001 | 온도 범위 | 기존 기준 |\n",
        encoding="utf-8",
    )
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="기존 기준",
        proposed_acceptance_criteria="변경 기준",
        reason="승인된 변경을 반영한다.",
    )

    preview = pipeline.apply_srs_revision_proposals(
        srs_file, [proposal], write=False
    )
    assert preview["changed_requirement_ids"] == ["REQ-TEMP-001"]
    assert "기존 기준" in srs_file.read_text(encoding="utf-8")

    applied = pipeline.apply_srs_revision_proposals(srs_file, [proposal], write=True)
    repeated = pipeline.apply_srs_revision_proposals(srs_file, [proposal], write=True)
    assert applied["changed_requirement_ids"] == ["REQ-TEMP-001"]
    assert repeated["already_applied_requirement_ids"] == ["REQ-TEMP-001"]
    assert "변경 기준" in srs_file.read_text(encoding="utf-8")

    conflicting = proposal.model_copy(
        update={
            "current_acceptance_criteria": "다른 기준",
            "proposed_acceptance_criteria": "또 다른 기준",
        }
    )
    with pytest.raises(ValueError, match="기준 원문과 다릅니다"):
        pipeline.apply_srs_revision_proposals(srs_file, [conflicting], write=True)

def test_checkpoint2_routes_unchanged_condition_to_existing_tc() -> None:
    maintained = ConfirmedCondition(
        condition_id="COND-004",
        statement="기존 30°C 상한 차단 정책을 유지한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text="기존 30°C 상한 차단 정책을 유지한다.",
        requirement_ids=["REQ-TEMP-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *cp2_analysis().confirmed_conditions,
                maintained,
            ]
        }
    )
    design = cp2_valid_design().model_copy(
        update={
            "related_existing_tests": [
                ExistingTestSelection(
                    tc_id="TC-TEMP-001",
                    source_condition_ids=["COND-001", "COND-004"],
                    selection_reason="유지되는 상한 정책은 기존 TC로 회귀 확인한다.",
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_checkpoint2_rejects_existing_regression_regenerated_as_candidate() -> None:
    design = cp2_valid_design()
    regenerated = design.test_cases[0].model_copy(
        update={"purpose": TcPurpose.RELATED_REGRESSION}
    )

    result = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [regenerated]}),
        cp2_requirements(),
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-016").status == CheckStatus.FAIL
    assert "신규 후보로 재작성" in cp2_check(result, "CP2-016").message

def test_checkpoint2_allows_incompatible_target_regression_to_be_omitted() -> None:
    design = cp2_valid_design().model_copy(update={"related_existing_tests": []})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_checkpoint2_rejects_compound_ui_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    compound_result = test_case.expected_results[0].model_copy(
        update={"statement": "화면 모드는 AUTO이고 설정 온도는 18°C로 유지된다."}
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            compound_result,
                            *test_case.expected_results[1:],
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL
    assert "관찰값별로 분리" in cp2_check(result, "CP2-006").message

    for contextual_statement in (
        "AUTO 모드에서 화면의 온도 조작 버튼은 비활성화된다.",
        "AUTO 모드에서 화면의 설정 온도 표시는 ---이다.",
    ):
        contextual_result = test_case.expected_results[0].model_copy(
            update={"statement": contextual_statement}
        )
        contextual_design = design.model_copy(
            update={
                "test_cases": [
                    test_case.model_copy(
                        update={
                            "expected_results": [
                                contextual_result,
                                *test_case.expected_results[1:],
                            ]
                        }
                    )
                ]
            }
        )
        contextual_checkpoint = evaluate_checkpoint2(
            cp1_request(), cp2_analysis(), contextual_design, cp2_requirements()
        )
        assert cp2_check(contextual_checkpoint, "CP2-006").status == CheckStatus.PASS

def test_checkpoint2_rejects_procedural_selection_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    selection_result = ExpectedResult(
        result_id="ER-004",
        statement="PRIMARY_TEST_DEVICE가 단일 선택된다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            selection_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "준비용 장비 선택" in cp2_check(result, "CP2-017").message

def test_checkpoint2_rejects_action_success_as_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    procedural_result = ExpectedResult(
        result_id="ER-004",
        statement="AUTO 모드를 선택하고 적용할 수 있다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            procedural_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "Condition 원문에 없는 실행 행동 성공" in cp2_check(result, "CP2-017").message

def test_checkpoint2_keeps_grounded_product_capability_result() -> None:
    analysis = cp2_analysis()
    grounded_condition = analysis.confirmed_conditions[0].model_copy(
        update={
            "statement": "AUTO 모드를 선택하고 적용할 수 있다.",
            "source_text": "AUTO 모드를 선택하고 적용할 수 있다.",
        }
    )
    analysis = analysis.model_copy(
        update={
            "confirmed_conditions": [
                grounded_condition,
                *analysis.confirmed_conditions[1:],
            ]
        }
    )
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    grounded_result = ExpectedResult(
        result_id="ER-004",
        statement="AUTO 모드를 선택하고 적용할 수 있다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            grounded_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-017").status == CheckStatus.PASS

def test_checkpoint2_rejects_ui_display_not_present_in_condition_source() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    invented_display = ExpectedResult(
        result_id="ER-004",
        statement="사용자 화면의 잠금 상태가 잠금으로 표시된다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            invented_display,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "Condition 원문에 없는 UI 표시" in cp2_check(result, "CP2-017").message

def test_checkpoint2_accepts_related_boundaries_as_one_grouped_tc() -> None:
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), grouped_boundary_design(), cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-015").status == CheckStatus.PASS

def test_checkpoint2_rejects_grouped_tc_without_reset_or_result_timing() -> None:
    design = grouped_boundary_design()
    test_case = design.test_cases[0]
    broken_results = [
        result.model_copy(update={"verify_after_step": None})
        for result in test_case.expected_results
    ]
    broken = test_case.model_copy(
        update={
            "intermediate_reset_steps": [],
            "expected_results": broken_results,
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(),
        design.model_copy(update={"test_cases": [broken]}),
        cp2_requirements(),
    )

    assert result.status == CheckStatus.FAIL
    check = cp2_check(result, "CP2-015")
    assert check.status == CheckStatus.FAIL
    assert "초기화 절차 누락" in check.message
    assert "판정 단계 누락" in check.message

def test_checkpoint2_requires_explicit_runtime_restore_for_unknown_grouped_hvac_baseline() -> None:
    design = grouped_boundary_design()
    test_case = design.test_cases[0]
    restore_step = "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다."
    unknown_baseline = test_case.model_copy(
        update={
            "test_data": test_case.test_data.model_copy(
                update={
                    "initial_mode": None,
                    "initial_temperature_c": None,
                    "restore_observed_hvac_state": False,
                }
            ),
            "restore_required": True,
            "restore_steps": [restore_step],
        }
    )

    rejected = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [unknown_baseline]}),
        cp2_requirements(),
    )
    accepted_case = unknown_baseline.model_copy(
        update={
            "test_data": unknown_baseline.test_data.model_copy(
                update={"restore_observed_hvac_state": True}
            )
        }
    )
    accepted = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [accepted_case]}),
        cp2_requirements(),
    )

    assert cp2_check(rejected, "CP2-015").status == CheckStatus.FAIL
    assert "실행 전 상태 저장·복원 표시 누락" in cp2_check(
        rejected, "CP2-015"
    ).message
    assert cp2_check(accepted, "CP2-015").status == CheckStatus.PASS

def test_human_review_note_pauses_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"human_review_notes": ["기획 확인이 필요한 의미 범위"]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.REVIEW
    assert cp2_check(result, "CP2-011").status == CheckStatus.REVIEW

def test_coverage_note_does_not_pause_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"coverage_notes": ["정확한 Toast 문구는 정의되지 않아 표시 여부만 검증한다."]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-011").status == CheckStatus.PASS

def test_final_review_note_does_not_pause_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"final_review_notes": ["운영 적용 시점은 최종 보고에서 확인한다."]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-011").status == CheckStatus.PASS
    assert "후속 자동 실행을 막지 않는 참고·최종 검토 사항 1건" in cp2_check(result, "CP2-011").message
    schema_properties = pipeline.Agent2TestDesign.model_json_schema()["properties"]
    assert "최종_확인_사항" in schema_properties
    assert "중단_확인_사항" in schema_properties
    assert "제외_범위" in schema_properties
    assert "제외된_정보_부족" in schema_properties
    tc_schema = pipeline.ProductTestCaseCandidate.model_json_schema()["properties"]
    assert "common_qa_criteria" in tc_schema
    assert "independent_execution" in tc_schema
    assert "double_assert_policy" in tc_schema

def test_control_requirement_cannot_use_local_path() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 제어 명령을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 제어 명령을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="중앙 제어 경로 회귀 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 제어 명령을 적용한다.",
            acceptance_criteria="선택 장비에 일괄 적용한다.",
        ),
    }
    tc = cp2_valid_design().test_cases[0]
    expected_results = [
        item.model_copy(
            update={
                "source_condition_ids": [*item.source_condition_ids, "COND-004"]
            }
        )
        for item in tc.expected_results
    ]
    mismatched = tc.model_copy(
        update={
            "requirement_ids": [*tc.requirement_ids, "REQ-CONTROL-001"],
            "source_condition_ids": [*tc.source_condition_ids, "COND-004"],
            "expected_results": expected_results,
            "control_path": ControlPath.LOCAL,
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [mismatched]})

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-008").status == CheckStatus.FAIL

def test_verify_central_path_can_use_existing_regression_without_new_candidate() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 변경 정책을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 변경 정책을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="중앙 경로에서도 변경 정책 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 변경 정책을 적용한다.",
            acceptance_criteria="선택 장비에 일괄 적용한다.",
        ),
    }
    design = cp2_valid_design().model_copy(
        update={
            "related_existing_tests": [
                *cp2_valid_design().related_existing_tests,
                ExistingTestSelection(
                    tc_id="TC-MODE-001",
                    source_condition_ids=["COND-004"],
                    selection_reason="유지되는 중앙 관제 적용 동작은 기존 TC로 회귀 확인한다.",
                ),
            ]
        }
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-008").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_verify_only_requirement_cannot_be_duplicated_as_new_candidate() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="기존 중앙 제어 회귀 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
            acceptance_criteria="허용 대상에 기존 명령을 반영한다.",
        ),
    }
    base = cp2_valid_design().test_cases[0]
    verify_only = base.model_copy(
        update={
            "tc_id": "TC-CAND-002",
            "title": "기존 중앙 관제 적용 중복 후보",
            "test_type": TcType.NORMAL,
            "requirement_ids": ["REQ-CONTROL-001"],
            "source_condition_ids": ["COND-004"],
            "expected_results": [
                item.model_copy(update={"source_condition_ids": ["COND-004"]})
                for item in base.expected_results
            ],
            "feature_requirement_ids": ["REQ-CONTROL-001"],
        }
    )
    design = cp2_valid_design().model_copy(
        update={"test_cases": [*cp2_valid_design().test_cases, verify_only]}
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-016").status == CheckStatus.FAIL
    assert "VERIFY 유지 동작" in cp2_check(result, "CP2-016").message

def test_structured_test_data_is_required_for_boundary_tc() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"test_data": StructuredTestData()}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-010").status == CheckStatus.FAIL

def test_state_consistency_without_mode_or_temperature_data_is_allowed() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "test_type": TcType.STATE_CONSISTENCY,
            "test_data": StructuredTestData(),
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-010").status == CheckStatus.PASS

def test_boundary_tc_allows_initial_mode_as_execution_context() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "test_data": StructuredTestData(
                initial_mode="AUTO",
                requested_mode=None,
                initial_temperature_c=18,
                requested_temperature_c=17,
            )
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-010").status == CheckStatus.PASS

def test_missing_condition_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"source_condition_ids": ["COND-001", "COND-002"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-004").status == CheckStatus.FAIL

def test_missing_internal_state_assertion_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0]
    expected = [
        item
        for item in tc.expected_results
        if item.observation_layer != ObservationLayer.INTERNAL_STATE
    ]
    design = cp2_valid_design().model_copy(
        update={"test_cases": [tc.model_copy(update={"expected_results": expected})]}
    )

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL

def test_state_consistency_type_without_internal_state_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "requirement_ids": ["REQ-TEMP-001"],
            "source_condition_ids": ["COND-001"],
            "test_type": TcType.STATE_CONSISTENCY,
            "expected_results": [
                ExpectedResult(
                    result_id="ER-001",
                    statement="화면에서 요청이 차단된다.",
                    observation_layer=ObservationLayer.UI,
                    source_condition_ids=["COND-001"],
                )
            ],
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL

def test_missing_three_tier_quality_criteria_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "common_qa_criteria": [],
            "domain_qa_criteria": [],
            "feature_requirement_ids": [],
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-012").status == CheckStatus.FAIL

def test_tc_declared_non_independent_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"independent_execution": False, "independence_reason": None}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-013").status == CheckStatus.FAIL

def test_tc_negative_cross_tc_reference_is_accepted_as_independence_evidence() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "independence_reason": (
                "사전조건을 직접 구성하므로 이전 TC의 적용 또는 복원 결과에 "
                "의존하지 않고 독립적으로 실행한다."
            )
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-013").status == CheckStatus.PASS

def test_tc_positive_cross_tc_dependency_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "preconditions": ["이전 TC가 완료한 장비 상태를 그대로 사용한다."],
            "independence_reason": "선행 테스트 결과를 이어받아 실행한다.",
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-013").status == CheckStatus.FAIL

def test_partial_scope_exclusions_must_be_preserved_by_agent2() -> None:
    analysis = cp2_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": ["정확한 차단 안내 문구"],
            "information_gaps": ["정확한 안내 문구가 정의되지 않음"],
            "excluded_information_gaps": ["정확한 안내 문구가 정의되지 않음"],
            "user_questions": ["차단 안내 문구를 확정해 주세요."],
        }
    )
    design = cp2_valid_design()

    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-014").status == CheckStatus.FAIL

    preserved = design.model_copy(
        update={
            "excluded_scope": analysis.excluded_scope,
            "excluded_information_gaps": analysis.information_gaps,
        }
    )
    preserved_result = evaluate_checkpoint2(
        cp1_request(), analysis, preserved, cp2_requirements()
    )
    assert preserved_result.status == CheckStatus.PASS
    assert cp2_check(preserved_result, "CP2-014").status == CheckStatus.PASS

def test_agent2_preserves_setup_and_restore_notes_as_tc_procedures() -> None:
    setup_note = "첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작한다."
    restore_note = "시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [
                *cp1_request().acceptance_notes,
                setup_note,
                restore_note,
            ]
        }
    )
    analysis = cp2_analysis().model_copy(
        update={"excluded_scope": [setup_note, restore_note]}
    )
    incorrectly_excluded = cp2_valid_design().model_copy(
        update={"excluded_scope": [setup_note, restore_note]}
    )

    rejected = evaluate_checkpoint2(
        request, analysis, incorrectly_excluded, cp2_requirements()
    )

    assert cp2_check(rejected, "CP2-014").status == CheckStatus.FAIL

    base_tc = cp2_valid_design().test_cases[0]
    procedural_tc = base_tc.model_copy(
        update={
            "preconditions": [*base_tc.preconditions, setup_note],
            "restore_required": True,
            "restore_steps": [restore_note],
        }
    )
    preserved = cp2_valid_design().model_copy(
        update={"test_cases": [procedural_tc], "excluded_scope": []}
    )
    accepted = evaluate_checkpoint2(request, analysis, preserved, cp2_requirements())

    assert cp2_check(accepted, "CP2-014").status == CheckStatus.PASS

def test_playwright_code_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"steps": ["page.locator('#temperature').click()"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-009").status == CheckStatus.FAIL
