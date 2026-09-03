"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_verified_agent1_run_can_handoff_to_agent2(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)

    request, _, analysis, checkpoint, _ = _load_verified_agent1_run(run_dir, run_id)

    assert request.request_id == analysis.request_id
    assert checkpoint.handoff_status == HandoffStatus.CONTINUE

def test_modified_agent1_artifact_is_blocked_before_agent2(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)
    analysis_file = run_dir / "agent1_change_analysis.json"
    analysis_file.write_text(
        analysis_file.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Agent 1 분석 파일이"):
        _load_verified_agent1_run(run_dir, run_id)

def test_paused_manifest_is_blocked_before_agent2(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)
    manifest_file = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["handoff_status"] = HandoffStatus.PAUSE.value
    _write_json(manifest_file, manifest)

    with pytest.raises(ValueError, match="인계 상태"):
        _load_verified_agent1_run(run_dir, run_id)

def test_agent1_to_agent2_cli_handoff_with_frozen_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    request_file = tmp_path / "request.json"
    _write_json(request_file, cp1_request().model_dump(mode="json"))

    class FakeAgent1:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent1"

        def analyze(self, request, requirements, **kwargs):
            return pipeline.Agent1Response(
                analysis=cp1_valid_analysis(),
                response_id="not-persisted",
                model=self.model,
                usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    class FakeAgent2:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent2"

        def design(self, request, analysis, requirements, **kwargs):
            tc = ProductTestCaseCandidate(
                tc_id="TC-CAND-001",
                title="AUTO 모드 변경 범위 확인",
                purpose=TcPurpose.CHANGE_VALIDATION,
                test_type=TcType.BOUNDARY,
                requirement_ids=["REQ-TEMP-001"],
                source_condition_ids=["COND-001", "COND-002", "COND-003", "COND-005"],
                    control_path=ControlPath.CENTRAL,
                target_role="PRIMARY_TEST_DEVICE",
                test_data=StructuredTestData(
                    initial_mode="AUTO",
                    requested_mode="AUTO",
                    initial_temperature_c=18,
                    requested_temperature_c=17,
                ),
                preconditions=["대상 장비가 AUTO 모드다."],
                steps=["변경된 하한 경계값을 요청한다."],
                expected_results=[
                    ExpectedResult(


                        result_id="ER-001",
                        statement="요청 결과가 변경 조건과 일치한다.",
                        observation_layer=ObservationLayer.UI,
                        source_condition_ids=["COND-001", "COND-002", "COND-003", "COND-005"],
                        )
                    ],
                    common_qa_criteria=[CommonQaCriterion.BOUNDARY_VALUE],
                    domain_qa_criteria=[DomainQaCriterion.TARGET_DEVICE_ACCURACY],
                    feature_requirement_ids=["REQ-TEMP-001"],
                    independent_execution=True,
                    independence_reason="사전조건에서 대상 장비의 모드와 초기 온도를 직접 구성한다.",
                    double_assert_policy=DoubleAssertPolicy.UI_ONLY,
                    double_assert_reason="이 단위 Fixture는 화면 경계 결과만 확인한다.",
                    restore_required=False,
                    restore_steps=[],
                    automation_candidate=True,
                    automation_reason="화면에서 요청 결과를 확인할 수 있다.",
            )
            return pipeline.Agent2Response(
                    design=Agent2TestDesign(
                        request_id=request.request_id,
                        existing_tc_comparison_completed=True,
                        related_existing_tests=[
                            ExistingTestSelection(
                                tc_id="TC-TEMP-001",
                                source_condition_ids=["COND-001"],
                                selection_reason="변경 대상 온도 정책의 기존 경계 TC를 회귀 확인한다.",
                            )
                        ],
                        test_cases=[tc],
                        srs_revision_proposals=[
                            pipeline.SrsRevisionProposal(
                                proposal_id="SRS-REV-001",
                                requirement_id="REQ-TEMP-001",
                                source_condition_ids=[
                                    "COND-001",
                                    "COND-002",
                                    "COND-003",
                                    "COND-005",
                                ],
                                current_acceptance_criteria=(
                                    "범위 안 요청은 반영되고 범위 밖 요청은 차단되며 "
                                    "화면·내부 설정 온도가 기존 값을 유지합니다."
                                ),
                                proposed_acceptance_criteria=(
                                    "AUTO 모드에서는 18~30°C 요청을 허용하고 범위 밖 요청은 "
                                    "차단하며 화면·내부 설정 온도가 기존 값을 유지합니다."
                                ),
                                reason="AUTO 모드 하한 변경을 SRS 인수 기준에 반영합니다.",
                            )
                        ],
                    coverage_summary="확정 조건을 변경 검증 TC에 연결했다.",
                    excluded_scope=analysis.excluded_scope,
                    excluded_information_gaps=analysis.information_gaps,
                ),
                response_id="not-persisted",
                model=self.model,
                usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            )

    monkeypatch.setattr(pipeline_execution, "OpenAIAgent1", FakeAgent1)
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent2", FakeAgent2)
    runs_root = tmp_path / "runs"
    agent1_args = SimpleNamespace(
        request=str(request_file),
        srs=str(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"),
        runs_root=str(runs_root),
        model=None,
    )

    assert pipeline.run_agent1(agent1_args) == 0
    run_dir = next(path for path in runs_root.iterdir() if path.is_dir())
    agent2_args = SimpleNamespace(
        run_id=run_dir.name,
        runs_root=str(runs_root),
        model=None,
    )

    assert pipeline.run_agent2(agent2_args) == 0
    assert (run_dir / "srs_snapshot.md").is_file()
    assert (run_dir / "agent2_test_design.json").is_file()
    assert (run_dir / "agent2_in_progress.json").exists() is False
    manifest = json.loads((run_dir / "agent2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == CheckStatus.PASS.value
    assert manifest["request_sha256"] == _sha256_file(run_dir / "request.json")
    assert manifest["srs_sha256"] == _sha256_file(run_dir / "srs_snapshot.md")
    catalog_snapshot = json.loads(
        (run_dir / "approved_regression_catalog.json").read_text(encoding="utf-8")
    )
    assert [item["tc_id"] for item in catalog_snapshot["approved_assets"]] == [
        "TC-V2-001"
    ]
    assert manifest["approved_regression_catalog_sha256"] == _sha256_file(
        run_dir / "approved_regression_catalog.json"
    )
    assert manifest["srs_revision_contract"] == "1.0"

def test_agent2_rejects_an_active_run_reservation(tmp_path: Path) -> None:
    run_id = "RUN-20260817-040000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "agent2_in_progress.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="진행 표시가 이미 존재"):
        pipeline.run_agent2(
            SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"), model=None)
        )
