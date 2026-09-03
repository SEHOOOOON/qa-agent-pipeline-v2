"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_loads_product_requirements_from_markdown() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert len(requirements) >= 20
    assert requirements["REQ-TEMP-001"].statement == "섭씨 설정 범위는 16~30°C여야 합니다."
    assert "범위 밖 요청" in requirements["REQ-TEMP-001"].acceptance_criteria
    assert set(requirements["REQ-TEMP-001"].related_requirement_ids) == {
        "REQ-CONTROL-001",
        "REQ-NOTIFY-001",
        "REQ-STATE-001",
    }
    assert not any(item.startswith("REQ-LOCAL-") for item in requirements)
    assert "Toast" in requirements["REQ-NOTIFY-001"].acceptance_criteria
    assert "currentTemp" in requirements["REQ-MONITOR-001"].acceptance_criteria

def test_rendered_context_contains_ids_and_acceptance_criteria() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    context = render_srs_context(requirements)

    assert "REQ-LOCK-001" in context
    assert "차단 안내가 표시됩니다" in context
    assert "관련 요구사항: REQ-CONTROL-001" in context

def test_product_srs_excludes_test_harness_requirements() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert "REQ-REGISTER-001" not in requirements
    assert "REQ-RESET-001" not in requirements

def test_agent1_uses_structured_responses_api() -> None:
    responses = Agent1FakeResponses()
    fake_client = SimpleNamespace(responses=responses)
    agent = OpenAIAgent1(model="gpt-5.6-terra", client=fake_client)
    request = ChangeRequest(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_value="16~30°C",
        after_value="18~30°C",
        description="AUTO 모드의 설정 범위는 18~30°C입니다.",
        acceptance_notes=["AUTO 모드의 설정 범위는 18~30°C입니다."],
    )
    requirements = {
        "REQ-TEMP-001": SrsRequirement(
            requirement_id="REQ-TEMP-001",
            statement="섭씨 설정 범위는 16~30°C여야 합니다.",
            acceptance_criteria="범위 밖 요청이 차단됩니다.",
        )
    }

    result = agent.analyze(request, requirements)

    assert result.response_id == "resp_test"
    assert result.usage["total_tokens"] == 150
    assert responses.kwargs["text_format"] is Agent1Analysis
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent1-2-8"
    assert responses.kwargs["store"] is False
    instructions = responses.kwargs["input"][0]["content"]
    assert "현재 SRS는 변경 전 제품 상태" in instructions
    assert "변경 후 정책의 권한 있는 입력" in instructions
    assert "acceptance_notes 중 제품의 긍정적인 판정 기준" in instructions
    assert "Agent 2가 TC의 판정 기준" in instructions
    assert "VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT" in instructions
    assert "연관 항목을 조용히 생략하지 않습니다" in instructions
    assert "자동화 구현 지원 여부를 이유로" in instructions
    assert "TC 구성·기존 TC 선택·자동화 가능 여부" in instructions
    assert "MODIFIED, UPDATE_REQUIRED 또는 VERIFY로 분류한 모든 Requirement" in instructions
    assert "검증 조건 원문을 찾지 못하면" in instructions
    assert "테스트 절차나 Playwright 코드는 작성하지 않습니다" in instructions

def test_agent1_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent1Error, match="OPENAI_API_KEY"):
        OpenAIAgent1()

def test_valid_analysis_passes_checkpoint1() -> None:
    result = evaluate_checkpoint1(cp1_request(), cp1_valid_analysis(), cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 10
    assert all(item.status == CheckStatus.PASS for item in result.checks)

def test_missing_change_request_range_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "confirmed_conditions": [
                item
                for item in cp1_valid_analysis().confirmed_conditions
                if item.condition_id != "COND-005"
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-008").status == CheckStatus.FAIL
    assert "18~30°C" in cp1_check(result, "CP1-008").message

def test_unknown_requirement_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "requirement_effects": [
                *cp1_valid_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-FAKE-999",
                    relation=RequirementRelation.VERIFY,
                    reason="존재하지 않는 기능",
                ),
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL

def test_missing_related_requirement_review_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "requirement_effects": [
                item
                for item in cp1_valid_analysis().requirement_effects
                if item.requirement_id != "REQ-STATE-001"
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL

def test_condition_requirement_missing_from_effects_is_rejected() -> None:
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement="화면과 내부 상태가 일치한다.",
            source_type=ConditionSource.SRS,
            source_text="status·mode·currentTemp·setTemp·fanSpeed·locked 등 검증 대상 공통 값이 같습니다.",
            requirement_ids=["REQ-STATE-001"],
        ),
    ]
    effects = [
        item
        for item in cp1_valid_analysis().requirement_effects
        if item.requirement_id != "REQ-STATE-001"
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL

def test_unverified_before_value_requires_review() -> None:
    changed_request = cp1_request().model_copy(update={"before_value": "17~30°C"})
    analysis = cp1_valid_analysis().model_copy(
        update={"before_condition": "현재 섭씨 설정 범위는 17~30°C다."}
    )

    result = evaluate_checkpoint1(changed_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert result.final_review_notes == [
        "변경 전 값이 대상 SRS 행에서 직접 확인되지 않습니다."
    ]
    assert cp1_check(result, "CP1-004").status == CheckStatus.REVIEW

def test_ungrounded_confirmed_condition_is_rejected() -> None:
    conditions = list(cp1_valid_analysis().confirmed_conditions)
    conditions[0] = conditions[0].model_copy(
        update={"source_text": "요청과 SRS에 없는 자동 복원 정책"}
    )
    analysis = cp1_valid_analysis().model_copy(update={"confirmed_conditions": conditions})

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-007").status == CheckStatus.FAIL

def test_missing_acceptance_note_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": cp1_valid_analysis().confirmed_conditions[:1]}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-008").status == CheckStatus.FAIL
    assert cp1_request().acceptance_notes[-1] in cp1_check(result, "CP1-008").message

def test_checkpoint1_does_not_require_setup_or_restore_as_product_conditions() -> None:
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
    analysis = cp1_valid_analysis().model_copy(
        update={
            "excluded_scope": [
                *cp1_valid_analysis().excluded_scope,
                setup_note,
                restore_note,
            ]
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS

def test_missing_requested_out_of_scope_is_rejected() -> None:
    scoped_request = cp1_request().model_copy(update={"out_of_scope": ["화씨 표시 정책"]})
    analysis = cp1_valid_analysis().model_copy(update={"excluded_scope": []})

    result = evaluate_checkpoint1(scoped_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL

def test_scope_limited_acceptance_note_is_only_excluded() -> None:
    scope_note = "온도 표시값 변경은 이번 변경 범위에 포함하지 않는다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [*cp1_request().acceptance_notes, scope_note],
            "out_of_scope": [scope_note],
        }
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "excluded_scope": [*cp1_valid_analysis().excluded_scope, scope_note]
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS
    assert cp1_check(result, "CP1-009").status == CheckStatus.PASS

def test_scope_limited_acceptance_note_cannot_be_confirmed_condition() -> None:
    scope_note = "온도 표시값 변경은 이번 변경 범위에 포함하지 않는다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [*cp1_request().acceptance_notes, scope_note],
            "out_of_scope": [scope_note],
        }
    )
    scope_condition = ConfirmedCondition(
        condition_id="COND-004",
        statement=scope_note,
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=scope_note,
        requirement_ids=["REQ-TEMP-001"],
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *cp1_valid_analysis().confirmed_conditions,
                scope_condition,
            ],
            "excluded_scope": [*cp1_valid_analysis().excluded_scope, scope_note],
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL
    assert "제외 조건" in cp1_check(result, "CP1-009").message

def test_redundant_reconfirmation_requires_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["변경 정책을 다시 확인해야 함"],
            "user_questions": [
                "AUTO 모드의 설정 범위를 18~30°C로 변경하는 것으로 확정할 수 있습니까?"
            ],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert cp1_check(result, "CP1-010").status == CheckStatus.REVIEW

def test_legitimate_missing_detail_question_passes_checkpoint() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["기존 저장 데이터의 적용 시점이 요청에 없음"],
            "user_questions": ["기존에 저장된 장비에도 즉시 소급 적용합니까?"],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.PAUSE
    assert cp1_check(result, "CP1-010").status == CheckStatus.PASS

def test_partial_proceed_continues_confirmed_scope_and_preserves_exclusions() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": ["기존 저장값의 소급 적용"],
            "information_gaps": ["기존 저장값의 적용 시점이 정의되지 않음"],
            "excluded_information_gaps": ["기존 저장값의 적용 시점이 정의되지 않음"],
            "user_questions": ["기존 저장값에도 즉시 소급 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE

def test_partial_proceed_without_excluded_scope_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": [],
            "information_gaps": ["적용 시점이 정의되지 않음"],
            "excluded_information_gaps": ["적용 시점이 정의되지 않음"],
            "user_questions": ["언제 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert result.handoff_status == HandoffStatus.BLOCKED
    assert cp1_check(result, "CP1-010").status == CheckStatus.FAIL

    mismatched = analysis.model_copy(
        update={
            "excluded_scope": ["적용 시점"],
            "excluded_information_gaps": [],
        }
    )
    mismatched_result = evaluate_checkpoint1(
        cp1_request(), mismatched, cp1_requirements()
    )
    assert cp1_check(mismatched_result, "CP1-010").status == CheckStatus.FAIL

def test_blocked_decision_blocks_agent2_handoff() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"decision": AnalysisDecision.BLOCKED}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.BLOCKED

def test_related_requirement_can_be_marked_update_required() -> None:
    requirements = cp1_requirements()
    related = requirements["REQ-NOTIFY-001"]
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement=related.statement,
            source_type=ConditionSource.SRS,
            source_text=related.statement,
            requirement_ids=["REQ-NOTIFY-001"],
        ),
    ]
    effects = [
        item.model_copy(update={"relation": RequirementRelation.UPDATE_REQUIRED})
        if item.requirement_id == "REQ-NOTIFY-001"
        else item
        for item in cp1_valid_analysis().requirement_effects
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, requirements)

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE

def test_proceed_with_open_question_is_recorded_for_final_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["경계값 적용 시점이 불명확함"],
            "user_questions": ["기존 저장값에도 즉시 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert result.final_review_notes == [
        "정보 부족 또는 질문이 있는데 PROCEED로 판정했습니다."
    ]
    assert cp1_check(result, "CP1-010").status == CheckStatus.REVIEW
