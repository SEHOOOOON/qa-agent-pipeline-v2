"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_request_trace_run_handoff_requires_new_scope_contract(tmp_path, monkeypatch):
    from qa_pipeline_contracts import RequirementScopeEvidence, ScopeBasis
    analysis = cp1_valid_analysis()
    condition = analysis.confirmed_conditions[1]
    condition.statement = condition.source_text
    condition.requirement_ids.append("REQ-NOTIFY-001")
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == "REQ-NOTIFY-001")
    effect.relation = RequirementRelation.VERIFY
    effect.scope_evidence = RequirementScopeEvidence(basis=ScopeBasis.REQUEST_TRACE_ONLY,
        request_condition_ids=[condition.condition_id],
        srs_source_text=cp1_requirements()["REQ-NOTIFY-001"].statement)
    class FakeAgent:
        def __init__(self, **kwargs):
            pass
        def analyze(self, *args, **kwargs):
            return pipeline.Agent1Response(analysis=analysis, response_id=None,
                model="fake-trace", usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent1", FakeAgent)
    request_file = tmp_path / "request.json"
    _write_json(request_file, cp1_request().model_dump(mode="json"))
    assert pipeline.run_agent1(SimpleNamespace(request=str(request_file),
        srs=str(REPO_ROOT / "docs/01_PRODUCT_SRS.md"), runs_root=str(tmp_path / "runs"), model=None)) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    assert _load_verified_agent1_run(run_dir, run_dir.name)[3].handoff_status == HandoffStatus.CONTINUE
    manifest_file = run_dir / "run_manifest.json"
    original = pipeline._read_json_payload(manifest_file)
    for contract, scope in [("2.6", None), ("2.6", "1.0"), ("2.5", "1.0"), ("2.5", "1.1")]:
        altered = {**original, "contract_version": contract, "scope_guard_contract": scope}
        _write_json(manifest_file, altered)
        with pytest.raises(ValueError, match="검사 범위 계약"):
            _load_verified_agent1_run(run_dir, run_dir.name)


@pytest.mark.parametrize("outcome", ["repair", "unresolved", "scope_review"])
def test_scope_gate_rewrite_and_pause_before_agent2(tmp_path, monkeypatch, outcome):
    request, expanded, requirements = cp1_scope_case()
    # Use the repository SRS unchanged, not a model-created product criterion.
    related = cp1_requirements()["REQ-NOTIFY-001"]
    condition = expanded.confirmed_conditions[-1]
    condition.statement = condition.source_text = related.statement
    effect = next(item for item in expanded.requirement_effects
                  if item.requirement_id == "REQ-NOTIFY-001")
    effect.scope_evidence.srs_source_text = related.statement
    if outcome != "scope_review":
        effect.scope_evidence = None
    calls = []

    class FakeAgent1:
        def __init__(self, **kwargs):
            pass

        def analyze(self, request, requirements, **kwargs):
            calls.append(kwargs)
            result = (cp1_valid_analysis() if outcome == "repair" and len(calls) == 2
                      else expanded)
            return pipeline.Agent1Response(
                analysis=result, response_id=None, model="fake-scope",
                usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            )

    monkeypatch.setattr(pipeline_execution, "OpenAIAgent1", FakeAgent1)
    request_file = tmp_path / "request.json"
    _write_json(request_file, request.model_dump(mode="json"))
    args = SimpleNamespace(request=str(request_file),
        srs=str(REPO_ROOT / "docs/01_PRODUCT_SRS.md"),
        runs_root=str(tmp_path / "runs"), model=None)
    assert pipeline.run_agent1(args) == (0 if outcome == "repair" else 2)
    run_dir = next((tmp_path / "runs").iterdir())
    manifest = pipeline._read_json_payload(run_dir / "run_manifest.json")
    assert manifest["scope_guard_contract"] == "1.1"
    assert manifest["prompt_version"] == "agent1-2.11"
    if outcome == "scope_review":
        assert len(calls) == 1
        assert manifest["handoff_status"] == "PAUSE"
    else:
        assert len(calls) == 2
        assert any("검사 범위" in msg
                   for msg in calls[1]["checkpoint_feedback"])
    if outcome == "repair":
        _load_verified_agent1_run(run_dir, run_dir.name)
    else:
        def forbidden_agent2(**kwargs):
            pytest.fail("A paused/failed scope must not construct an Agent 2 client")
        monkeypatch.setattr(pipeline_execution, "OpenAIAgent2", forbidden_agent2)
        with pytest.raises(ValueError):
            pipeline.run_agent2(SimpleNamespace(
                run_id=run_dir.name, runs_root=args.runs_root, model=None,
            ))
        assert not (run_dir / "agent2_test_design.json").exists()


def test_scope_contract_loader_preserves_legacy_and_rejects_missing_new_contract(tmp_path):
    run_dir, run_id = build_verified_agent1_run(tmp_path)
    manifest_file = run_dir / "run_manifest.json"
    manifest = pipeline._read_json_payload(manifest_file)
    manifest.pop("scope_guard_contract")
    historical = evaluate_checkpoint1(cp1_request(), cp1_valid_analysis(), cp1_requirements(),
                                     require_scope_guard=False)
    _write_json(run_dir / "checkpoint1.json", historical.model_dump(mode="json"))
    manifest["checkpoint1_sha256"] = _sha256_file(run_dir / "checkpoint1.json")
    _write_json(manifest_file, manifest)
    assert len(_load_verified_agent1_run(run_dir, run_id)[3].checks) == 10
    manifest["contract_version"] = "2.5"
    _write_json(manifest_file, manifest)
    with pytest.raises(ValueError, match="검사 범위 계약"):
        _load_verified_agent1_run(run_dir, run_id)


def test_atomic_write_short_temp_preserves_original_on_failure(tmp_path, monkeypatch):
    import qa_pipeline_io as io
    parent = tmp_path / ("p" * max(1, 210 - len(str(tmp_path)) - 1))
    target = parent / "agent3_automation_plan_attempt_1.json"
    original_write = Path.write_text
    written = []
    def limited_write(path, *args, **kwargs):
        assert len(str(path)) < 260, "temporary path exceeded Windows limit"
        written.append(path)
        return original_write(path, *args, **kwargs)
    monkeypatch.setattr(Path, "write_text", limited_write)
    io._write_json(target, {"original": True})
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
    def fail_replace(*args):
        raise OSError("injected publication failure")
    monkeypatch.setattr(io.os, "replace", fail_replace)
    with pytest.raises(OSError, match="publication failure"):
        io._write_json(target, {"original": False})
    assert json.loads(target.read_text(encoding="utf-8")) == {"original": True}
    assert len(written) == 2 and written[0] != written[1]
    assert all(path.parent == parent and not path.exists() for path in written)


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

@pytest.mark.parametrize("detail_outcome", ["clean", "repair", "unresolved"])
def test_agent1_to_agent2_cli_handoff_with_frozen_inputs(
    tmp_path: Path, monkeypatch, detail_outcome
) -> None:
    current_catalog, _ = pipeline.load_approved_regression_catalog(REPO_ROOT / "approved_assets")
    expected_catalog_ids = [item.tc_id for item in current_catalog]
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

    design_calls = []

    class FakeAgent2:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent2"

        def design(self, request, analysis, requirements, **kwargs):
            design_calls.append(kwargs)
            steps = ["변경된 하한 경계값을 요청한다."]
            if detail_outcome == "clean" or (detail_outcome == "repair" and len(design_calls) == 2):
                steps.insert(0, "중앙 관제 화면에서 대상 장비 카드를 선택한다.")
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
                steps=steps,
                expected_results=[
                    ExpectedResult(


                        result_id="ER-001",
                        statement="화면 온도가 변경 조건과 일치한다.",
                        observation_target="화면 온도",
                        verify_after_step="변경된 하한 경계값을 요청한다.",
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

    assert pipeline.run_agent2(agent2_args) == (2 if detail_outcome == "unresolved" else 0)
    detail_manifest = pipeline._read_json_payload(run_dir / "agent2_manifest.json")
    assert detail_manifest["tc_detail_contract"] == "1.2"
    assert detail_manifest["prompt_version"] == "agent2-2.27"
    assert len(design_calls) == (1 if detail_outcome == "clean" else 2)
    if detail_outcome != "clean":
        assert any("CP2-021" in text for text in design_calls[1]["checkpoint_feedback"])
    if detail_outcome == "unresolved":
        assert detail_manifest["status"] == "FAIL"
        with pytest.raises(ValueError, match="Checkpoint 2 must PASS"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
        return
    pipeline._load_verified_agent2_run(run_dir, run_dir.name)
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
    assert [item["tc_id"] for item in catalog_snapshot["approved_assets"]] == expected_catalog_ids
    assert manifest["approved_regression_catalog_sha256"] == _sha256_file(
        run_dir / "approved_regression_catalog.json"
    )
    assert manifest["srs_revision_contract"] == "1.0"

    # New runs may not drop/downgrade the additional procedure check. Old 1.0
    # records retain their original checks and are not rewritten by the loader.
    for unsupported in (None, "1.0", "1.1", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "tc_detail_contract": unsupported})
        with pytest.raises(ValueError, match="TC 상세화 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    checkpoint = pipeline._read_json_payload(run_dir / "checkpoint2.json")
    checkpoint["checks"] = [item for item in checkpoint["checks"] if item["rule_id"] != "CP2-021"]
    _write_json(run_dir / "checkpoint2.json", checkpoint)
    legacy = {**manifest, "contract_version": "3.1", "tc_detail_contract": "1.0",
              "prompt_version": "agent2-2.24", "checkpoint2_sha256": _sha256_file(run_dir / "checkpoint2.json")}
    _write_json(run_dir / "agent2_manifest.json", legacy)
    pipeline._load_verified_agent2_run(run_dir, run_dir.name)

def test_agent2_rejects_an_active_run_reservation(tmp_path: Path) -> None:
    run_id = "RUN-20260817-040000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "agent2_in_progress.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="진행 표시가 이미 존재"):
        pipeline.run_agent2(
            SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"), model=None)
        )
