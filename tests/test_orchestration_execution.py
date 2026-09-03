"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_pipeline_parser_exposes_one_command_agent1_to_agent3() -> None:
    args = pipeline.build_parser().parse_args(
        [
            "pipeline",
            "--request",
            "request.json",
            "--target-html",
            "virtual-controller.html",
        ]
    )

    assert args.handler is pipeline.run_pipeline
    assert args.tc_id == "AUTO"
    assert args.timeout == 90
    assert pipeline._orchestrator_status(0) == "PASS"
    assert pipeline._orchestrator_status(1) == "ERROR"
    assert pipeline._orchestrator_status(2) == "STOPPED"

    eligible = agent3_test_case()
    unsupported = eligible.model_copy(
        update={
            "tc_id": "TC-CAND-004",
            "target_role": "MULTIPLE_ALLOWED_TEST_DEVICES",
        }
    )
    selected, summaries = pipeline._select_agent3_tc(
        Agent2TestDesign(
            request_id="CR-TEST-001",
            test_cases=[unsupported, eligible],
            coverage_summary="Selection fixture",
        )
    )
    assert selected == eligible.tc_id
    assert len(summaries) == 2
    assert summaries[0]["status"] == "DISCOVERY_REQUIRED"
    discovered, unsupported_summaries = pipeline._select_agent3_tc(
        Agent2TestDesign(
            request_id="CR-TEST-001",
            test_cases=[unsupported],
            coverage_summary="No eligible candidate fixture",
        )
    )
    assert discovered == unsupported.tc_id
    assert unsupported_summaries[0]["generic_discovery_required"] is True
    assert unsupported_summaries[0]["missing_capabilities"] == []

def test_agent3_selection_excludes_related_regression_candidates() -> None:
    changed = agent3_test_case()
    related = changed.model_copy(
        update={
            "tc_id": "TC-CAND-009",
            "purpose": TcPurpose.RELATED_REGRESSION,
        }
    )

    selected, summaries = pipeline._select_agent3_tcs(
        Agent2TestDesign(
            request_id="CR-TEST-001",
            test_cases=[related, changed],
            coverage_summary="변경분과 기존 회귀 분리",
        )
    )

    assert selected == [changed.tc_id]
    related_summary = next(item for item in summaries if item["tc_id"] == related.tc_id)
    assert related_summary["status"] == "NOT_AUTOMATABLE"
    assert "다시 구현하지 않고" in related_summary["missing_capabilities"][0]

def test_pipeline_runs_stages_in_order_and_hashes_manifests(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")
    calls: list[str] = []

    def fake_agent1(stage_args) -> int:
        calls.append("agent1")
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent2(stage_args) -> int:
        calls.append("agent2")
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        _write_json(run_dir / "agent2_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent3(stage_args) -> int:
        calls.append("agent3")
        assert stage_args.tc_id == "TC-CAND-003"
        artifact_dir = Path(stage_args.artifact_dir)
        artifact_dir.mkdir(parents=True)
        _write_json(
            artifact_dir / "agent3_manifest.json",
            {
                "run_id": stage_args.run_id,
                "candidate_status": "PRODUCT_MISMATCH_DETECTED",
            },
        )
        _write_json(
            artifact_dir / "agent3_trial.json",
            {"outcome": "PRODUCT_MISMATCH_CANDIDATE"},
        )
        return 0

    monkeypatch.setattr(pipeline_orchestrator, "run_agent1", fake_agent1)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent2", fake_agent2)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent3", fake_agent3)
    monkeypatch.setattr(
        pipeline_orchestrator,
        "_select_agent3_tcs_from_run",
        lambda _run_dir, _run_id: (
            ["TC-CAND-003"],
            [
                {
                    "tc_id": "TC-CAND-003",
                    "automation_candidate": True,
                    "status": "ELIGIBLE",
                    "missing_capabilities": [],
                }
            ],
        ),
    )

    assert pipeline.run_pipeline(args) == 0
    assert calls == ["agent1", "agent2", "agent3"]
    run_dir = next((tmp_path / "runs").iterdir())
    manifest = json.loads(
        (run_dir / "orchestrator_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "PASS"
    assert manifest["completed_stages"] == ["agent1", "agent2", "agent3"]
    assert manifest["stopped_at"] is None
    assert manifest["selected_tc_id"] == "TC-CAND-003"
    assert manifest["selected_tc_ids"] == ["TC-CAND-003"]
    assert manifest["executed_tc_ids"] == ["TC-CAND-003"]
    assert manifest["agent3_selection_sha256"] == _sha256_file(
        run_dir / "agent3_selection.json"
    )
    assert manifest["agent1_manifest_sha256"] == _sha256_file(
        run_dir / "run_manifest.json"
    )
    assert manifest["agent2_manifest_sha256"] == _sha256_file(
        run_dir / "agent2_manifest.json"
    )
    assert manifest["agent3_run_summary_sha256"] == _sha256_file(
        run_dir / "agent3_run_summary.json"
    )

def test_pipeline_continues_after_one_agent3_candidate_is_excluded(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")
    calls: list[str] = []

    def fake_agent1(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent2(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        _write_json(run_dir / "agent2_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent3(stage_args) -> int:
        calls.append(stage_args.tc_id)
        artifact_dir = Path(stage_args.artifact_dir)
        artifact_dir.mkdir(parents=True)
        if stage_args.tc_id == "TC-CAND-003":
            _write_json(
                artifact_dir / "agent3_automation_plan.json",
                {
                    "planning_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
                    "extension_reasons": ["화면 상태 관찰 방법이 없습니다."],
                },
            )
            _write_json(
                artifact_dir / "agent3_manifest.json",
                {
                    "run_id": stage_args.run_id,
                    "status": "REVIEW",
                    "candidate_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
                },
            )
            return 2
        _write_json(
            artifact_dir / "agent3_manifest.json",
            {
                "run_id": stage_args.run_id,
                "status": "PASS",
                "candidate_status": "READY_FOR_EXECUTION",
            },
        )
        _write_json(artifact_dir / "agent3_trial.json", {"outcome": "PASS"})
        return 0

    monkeypatch.setattr(pipeline_orchestrator, "run_agent1", fake_agent1)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent2", fake_agent2)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent3", fake_agent3)
    monkeypatch.setattr(
        pipeline_orchestrator,
        "_select_agent3_tcs_from_run",
        lambda _run_dir, _run_id: (
            ["TC-CAND-003", "TC-CAND-004"],
            [
                {
                    "tc_id": tc_id,
                    "automation_candidate": True,
                    "status": "ELIGIBLE",
                    "missing_capabilities": [],
                }
                for tc_id in ("TC-CAND-003", "TC-CAND-004")
            ],
        ),
    )

    assert pipeline.run_pipeline(args) == 0
    assert calls == ["TC-CAND-003", "TC-CAND-004"]
    run_dir = next((tmp_path / "runs").iterdir())
    summary = json.loads(
        (run_dir / "agent3_run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "PARTIAL"
    assert summary["executed_tc_ids"] == ["TC-CAND-004"]
    assert [item["tc_id"] for item in summary["자동화_제외_TC"]] == [
        "TC-CAND-003"
    ]

def test_pipeline_reports_all_agent3_candidates_excluded_without_stopping(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")

    def fake_agent1(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent2(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        _write_json(run_dir / "agent2_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def excluded_agent3(stage_args) -> int:
        artifact_dir = Path(stage_args.artifact_dir)
        artifact_dir.mkdir(parents=True)
        _write_json(
            artifact_dir / "agent3_manifest.json",
            {
                "run_id": stage_args.run_id,
                "status": "REVIEW",
                "candidate_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
            },
        )
        return 2

    monkeypatch.setattr(pipeline_orchestrator, "run_agent1", fake_agent1)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent2", fake_agent2)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent3", excluded_agent3)
    monkeypatch.setattr(
        pipeline_orchestrator,
        "_select_agent3_tcs_from_run",
        lambda _run_dir, _run_id: (
            ["TC-CAND-003"],
            [
                {
                    "tc_id": "TC-CAND-003",
                    "automation_candidate": True,
                    "status": "ELIGIBLE",
                    "missing_capabilities": [],
                }
            ],
        ),
    )

    assert pipeline.run_pipeline(args) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    summary = json.loads(
        (run_dir / "agent3_run_summary.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (run_dir / "orchestrator_manifest.json").read_text(encoding="utf-8")
    )

    assert summary["status"] == "PARTIAL"
    assert summary["executed_tc_ids"] == []
    assert [item["tc_id"] for item in summary["자동화_제외_TC"]] == [
        "TC-CAND-003"
    ]
    assert manifest["status"] == "PARTIAL"
    assert manifest["stopped_at"] is None

def test_pipeline_stops_after_checkpoint_block_without_later_calls(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")

    def blocked_agent1(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"status": "REVIEW"})
        return 2

    def unexpected_call(_stage_args) -> int:
        raise AssertionError("A blocked checkpoint must stop later agents")

    monkeypatch.setattr(pipeline_orchestrator, "run_agent1", blocked_agent1)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent2", unexpected_call)
    monkeypatch.setattr(pipeline_orchestrator, "run_agent3", unexpected_call)

    assert pipeline.run_pipeline(args) == 2
    run_dir = next((tmp_path / "runs").iterdir())
    manifest = json.loads(
        (run_dir / "orchestrator_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "STOPPED"
    assert manifest["stage_exit_codes"] == {"agent1": 2}
    assert manifest["completed_stages"] == []
    assert manifest["stopped_at"] == "agent1"

def test_pipeline_rejects_missing_target_before_any_model_stage(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)

    def unexpected_call(_stage_args) -> int:
        raise AssertionError("Missing local inputs must fail before a model stage")

    monkeypatch.setattr(pipeline_orchestrator, "run_agent1", unexpected_call)

    with pytest.raises(ValueError, match="target HTML does not exist"):
        pipeline.run_pipeline(args)

def test_related_regression_selection_is_grounded_and_excludes_demo_cases() -> None:
    selected = pipeline.select_existing_regressions(
        ["REQ-TEMP-001", "REQ-CONTROL-001", "REQ-STATE-001"]
    )

    assert [item.tc_id for item in selected] == ["TC-MODE-001", "TC-TEMP-001"]
    assert "TC-INT-002" not in {item.tc_id for item in pipeline.EXISTING_REGRESSION_CATALOG}
    assert all(not item.tc_id.startswith("TC-PIPE-") for item in selected)
    assert all(item.tc_id != "TC-TEMP-002" for item in selected)

def test_checkpoint2_does_not_invent_regression_from_requirement_id_alone() -> None:
    analysis = agent1_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *agent1_analysis().confirmed_conditions,
                ConfirmedCondition(
                    condition_id="COND-004",
                    statement="화면과 내부 장비 상태의 공통 값이 같다.",
                    source_type=ConditionSource.SRS,
                    source_text="화면과 내부 장비 상태의 공통 값이 같습니다.",
                    requirement_ids=["REQ-STATE-001"],
                ),
            ],
            "requirement_effects": [
                *agent1_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-STATE-001",
                    relation=RequirementRelation.VERIFY,
                    reason="변경 뒤에도 기존 화면·내부 상태 정합성을 확인한다.",
                ),
            ],
        }
    )
    design = agent2_design().model_copy(update={"related_existing_tests": []})

    request = cp1_request()
    checkpoint = evaluate_checkpoint2(
        request,
        analysis,
        design,
        load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"),
    )

    assert design.related_existing_tests == []
    assert cp2_check(checkpoint, "CP2-004").status == CheckStatus.FAIL
    assert "COND-004" in cp2_check(checkpoint, "CP2-004").message

def test_existing_regression_runs_from_a_copied_neutral_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    target = tmp_path / "project1" / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline_hash = _sha256_file(baseline)
    target_hash = _sha256_file(target)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        workspace = Path(kwargs["cwd"])
        captured["command"] = command
        captured["env"] = kwargs["env"]
        assert (workspace / "tests" / "test_controller.py").is_file()
        assert (workspace / "tests" / "conftest.py").is_file()
        assert (workspace / "virtual-controller.html").is_file()
        evidence_dir = Path(kwargs["env"]["QA_EVIDENCE_DIR"])
        trace_file = evidence_dir / "trial-trace.zip"
        with zipfile.ZipFile(trace_file, "w") as archive:
            archive.writestr(
                "trace.trace",
                json.dumps(
                    {
                        "workspace": str(workspace.resolve()),
                        "target": (workspace / "virtual-controller.html").resolve().as_uri(),
                        "source": str(baseline.resolve()),
                        "home": str(Path.home().resolve()),
                    },
                    ensure_ascii=True,
                ),
            )
        return SimpleNamespace(returncode=0, stdout=". [100%]\n1 passed\n", stderr="")

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-regression")
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    spec = next(
        item for item in pipeline.EXISTING_REGRESSION_CATALOG if item.tc_id == "TC-TEMP-001"
    )

    result = pipeline.run_existing_regression(
        spec,
        baseline,
        target,
        tmp_path / "run" / "validation_evidence",
        timeout_seconds=10,
    )

    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.source == pipeline.ExecutionSource.EXISTING_REGRESSION
    assert result.test_id == "TC-TEMP-001"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["command"][-2:] == ["-p", "no:cacheprovider"]
    assert _sha256_file(baseline) == baseline_hash
    assert _sha256_file(target) == target_hash
    assert result.evidence_complete is True
    trace_path = next(
        tmp_path / "run" / relative
        for relative in result.evidence_files
        if relative.endswith("trial-trace.zip")
    )
    with zipfile.ZipFile(trace_path) as archive:
        trace_payload = archive.read("trace.trace").decode("utf-8")
    assert str(baseline.resolve()) not in trace_payload
    assert str(target.resolve()) not in trace_payload
    assert str(Path.home().resolve()) not in trace_payload
    assert "qa-regression-" not in trace_payload
    assert "<REGRESSION_WORKSPACE>" in trace_payload

def test_candidate_trial_is_reused_only_after_hash_and_evidence_checks(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, target, run_id = _build_candidate_execution_handoff(tmp_path, monkeypatch)

    result, test_case, _ = pipeline._candidate_execution_record(
        run_dir, run_id, target
    )

    assert result.test_id == test_case.tc_id == "TC-CAND-003"
    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.reused is True
    assert len(result.evidence_files) == 4
    assert result.evidence_complete is True

    target.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="HTML이 신규 자동화 후보 시험 후 변경"):
        pipeline._candidate_execution_record(run_dir, run_id, target)

def test_candidate_handoff_recomputes_current_cp3_rules(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, target, run_id = _build_candidate_execution_handoff(
        tmp_path, monkeypatch
    )
    plan_file = run_dir / "agent3_automation_plan.json"
    plan = Agent3AutomationPlan.model_validate_json(
        plan_file.read_text(encoding="utf-8")
    )
    weakened = plan.model_copy(update={"actions": [plan.actions[-1]]})
    _write_json(plan_file, weakened.model_dump(mode="json"))
    manifest_file = run_dir / "agent3_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["automation_plan_sha256"] = _sha256_file(plan_file)
    _write_json(manifest_file, manifest)

    with pytest.raises(ValueError, match="현재 CP3 규칙"):
        pipeline._candidate_execution_record(run_dir, run_id, target)

def test_candidate_handoff_rejects_evidence_changed_after_agent3(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, target, run_id = _build_candidate_execution_handoff(
        tmp_path, monkeypatch
    )
    evidence_file = run_dir / "evidence" / "TC-CAND-003" / "trial-stdout.txt"
    evidence_file.write_text("changed after Agent 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="시험 증거 SHA-256"):
        pipeline._candidate_execution_record(run_dir, run_id, target)

def test_current_compiler_reuses_identical_code_and_retrials_stale_code(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-015000-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    target = tmp_path / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    test_case = agent3_test_case()
    plan = agent3_plan()
    _write_json(
        run_dir / "agent3_automation_plan.json", plan.model_dump(mode="json")
    )
    current_code = compile_automation_candidate(run_id, test_case, plan)
    stored_candidate = run_dir / "candidates" / "test_tc_cand_003.py"
    stored_candidate.parent.mkdir()
    stored_candidate.write_text(current_code, encoding="utf-8")
    current_hash = _sha256_file(stored_candidate)
    stored = _neutral_execution_result(
        test_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    ).model_copy(
        update={
            "test_file": stored_candidate.name,
            "test_sha256": current_hash,
        }
    )

    monkeypatch.setattr(
        pipeline_execution,
        "run_candidate_trial",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("identical code must reuse the stored trial")
        ),
    )
    assert pipeline._current_candidate_execution_record(
        run_dir,
        run_id,
        target,
        test_case,
        stored,
        timeout_seconds=10,
    ) is stored

    def fake_trial(candidate_file, _target, evidence_dir, *, timeout_seconds):
        assert timeout_seconds == 10
        assert candidate_file.read_text(encoding="utf-8") == current_code
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "trial-stdout.txt").write_text("1 passed\n", encoding="utf-8")
        (evidence_dir / "trial-stderr.txt").write_text("", encoding="utf-8")
        (evidence_dir / "trial-final.png").write_bytes(b"png")
        (evidence_dir / "trial-trace.zip").write_bytes(b"zip")
        return _trial(TrialOutcome.PASS).model_copy(
            update={
                "exit_code": 0,
                "evidence_complete": True,
                "screenshot_file": "trial-final.png",
                "trace_file": "trial-trace.zip",
            }
        )

    monkeypatch.setattr(pipeline_execution, "run_candidate_trial", fake_trial)
    refreshed = pipeline._current_candidate_execution_record(
        run_dir,
        run_id,
        target,
        test_case,
        stored.model_copy(update={"test_sha256": "f" * 64}),
        timeout_seconds=10,
    )

    assert refreshed.reused is False
    assert refreshed.test_sha256 == _sha256_file(
        run_dir / "validation_candidates" / "test_tc_cand_003.py"
    )
    assert refreshed.status == pipeline.NeutralExecutionStatus.PASSED
    assert (
        run_dir / "validation_candidate_trials" / "TC-CAND-003.json"
    ).is_file()

def test_current_candidate_trial_returns_technical_failure_for_agent4(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-015500-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    target = tmp_path / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    test_case = agent3_test_case()
    plan = agent3_plan()
    _write_json(
        run_dir / "agent3_automation_plan.json", plan.model_dump(mode="json")
    )
    stored = _neutral_execution_result(
        test_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    ).model_copy(update={"test_sha256": "f" * 64})

    def failed_trial(_candidate_file, _target, evidence_dir, *, timeout_seconds):
        assert timeout_seconds == 10
        evidence_dir.mkdir(parents=True)
        stdout = evidence_dir / "trial-stdout.txt"
        stderr = evidence_dir / "trial-stderr.txt"
        stdout.write_text("locator failed\n", encoding="utf-8")
        stderr.write_text("PlaywrightError\n", encoding="utf-8")
        return pipeline.Agent3TrialResult(
            outcome=TrialOutcome.AUTOMATION_ERROR,
            exit_code=1,
            duration_ms=1,
            stdout_file=stdout.name,
            stderr_file=stderr.name,
            evidence_sha256={
                stdout.name: _sha256_file(stdout),
                stderr.name: _sha256_file(stderr),
            },
            evidence_complete=False,
        )

    monkeypatch.setattr(pipeline_execution, "run_candidate_trial", failed_trial)
    result = pipeline._current_candidate_execution_record(
        run_dir,
        run_id,
        target,
        test_case,
        stored,
        timeout_seconds=10,
    )

    assert result.status == pipeline.NeutralExecutionStatus.EXECUTION_ERROR
    assert result.source_outcome == TrialOutcome.AUTOMATION_ERROR.value
    assert result.evidence_complete is False
    assert len(result.evidence_files) == 2

def test_validation_execution_reuses_candidate_and_runs_related_regressions(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-020000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    _write_json(run_dir / "agent3_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_trial.json", {"outcome": "PASS"})
    _write_json(
        run_dir / "checkpoint1.json",
        pipeline.Checkpoint1Result(
            status=pipeline.CheckStatus.REVIEW,
            handoff_status=pipeline.HandoffStatus.CONTINUE,
            checks=[
                pipeline.CheckResult(
                    rule_id="CP1-004",
                    status=pipeline.CheckStatus.REVIEW,
                    message="변경 전 값의 SRS 근거를 최종 확인합니다.",
                )
            ],
            final_review_notes=["변경 전 값의 SRS 근거를 최종 확인합니다."],
        ).model_dump(mode="json"),
    )
    _write_json(
        run_dir / "agent2_test_design.json",
        cp2_valid_design()
        .model_copy(
            update={
                "final_review_notes": ["운영 반영 시점을 최종 확인합니다."],
                "excluded_scope": ["정확한 안내 문구"],
                "excluded_information_gaps": ["정확한 문구가 정의되지 않음"],
            }
        )
        .model_dump(mode="json"),
    )
    candidate = _neutral_execution_result(
        "TC-CAND-003", pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    )
    test_case = agent3_test_case()
    calls: list[str] = []

    monkeypatch.setattr(
        pipeline_execution,
        "_candidate_execution_record",
        lambda _run_dir, _run_id, _target: (candidate, test_case, {}),
    )
    monkeypatch.setattr(
        pipeline_execution,
        "_current_candidate_execution_record",
        lambda _run_dir, _run_id, _target, _test_case, stored, **_kwargs: stored,
    )

    def fake_regression(spec, *_args, source=pipeline.ExecutionSource.EXISTING_REGRESSION, **_kwargs):
        calls.append(spec.tc_id)
        return _neutral_execution_result(spec.tc_id, source)

    monkeypatch.setattr(pipeline_execution, "run_existing_regression", fake_regression)

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 0
    assert calls == ["TC-ENV-000", "TC-TEMP-001"]
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (run_dir / "validation_manifest.json").read_text(encoding="utf-8")
    )
    assert bundle.status == pipeline.ValidationStageStatus.COMPLETED
    assert bundle.candidate_result.reused is True
    assert bundle.selected_regression_ids == ["TC-TEMP-001"]
    assert [item.test_id for item in bundle.regression_results] == ["TC-TEMP-001"]
    assert bundle.final_review_notes == [
        "CP1: 변경 전 값의 SRS 근거를 최종 확인합니다.",
        "CP2: 운영 반영 시점을 최종 확인합니다.",
    ]
    assert bundle.excluded_scope == ["정확한 안내 문구"]
    assert bundle.excluded_information_gaps == ["정확한 문구가 정의되지 않음"]
    assert manifest["validation_execution_sha256"] == _sha256_file(
        run_dir / "validation_execution.json"
    )
    assert manifest["project1_modified"] is False

def test_validation_execution_carries_multiple_candidates_and_exclusions(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-025000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    _write_json(
        run_dir / "agent2_test_design.json",
        cp2_valid_design().model_dump(mode="json", by_alias=True),
    )
    _write_json(run_dir / "agent3_run_summary.json", {"run_id": run_id})
    first_case = agent3_test_case()
    second_case = first_case.model_copy(update={"tc_id": "TC-CAND-004"})
    first_result = _neutral_execution_result(
        first_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    )
    second_result = _neutral_execution_result(
        second_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    )
    records = []
    for result, test_case in (
        (first_result, first_case),
        (second_result, second_case),
    ):
        artifact_dir = run_dir / "agent3_candidates" / test_case.tc_id
        artifact_dir.mkdir(parents=True)
        _write_json(artifact_dir / "agent3_manifest.json", {"run_id": run_id})
        _write_json(artifact_dir / "agent3_trial.json", {"outcome": "PASS"})
        records.append((result, test_case, {}, artifact_dir))
    exclusion = pipeline.AutomationExclusion(
        tc_id="TC-CAND-005",
        candidate_status=pipeline.AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED,
        reason="현재 관찰 방법으로 구현할 수 없습니다.",
    )
    monkeypatch.setattr(
        pipeline_execution,
        "_candidate_execution_records",
        lambda *_args: (records, [exclusion], {"status": "PARTIAL"}),
    )
    monkeypatch.setattr(
        pipeline_execution,
        "_current_candidate_execution_record",
        lambda _run_dir, _run_id, _target, _case, stored, **_kwargs: stored,
    )
    monkeypatch.setattr(
        pipeline_execution,
        "run_existing_regression",
        lambda spec, *_args, source=pipeline.ExecutionSource.EXISTING_REGRESSION, **_kwargs: _neutral_execution_result(
            spec.tc_id, source
        ),
    )

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 0
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )
    assert [item.test_id for item in bundle.candidate_results] == [
        "TC-CAND-003",
        "TC-CAND-004",
    ]
    assert bundle.candidate_result == bundle.candidate_results[0]
    assert [item.tc_id for item in bundle.automation_exclusions] == [
        "TC-CAND-005"
    ]

def test_validation_execution_runs_existing_tc_when_no_new_candidate_is_needed(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-026000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    design = Agent2TestDesign(
        request_id="CR-EXISTING-ONLY-001",
        existing_tc_comparison_completed=True,
        related_existing_tests=[
            ExistingTestSelection(
                tc_id="TC-TEMP-001",
                source_condition_ids=["COND-001"],
                selection_reason="변경 후 조건을 기존 공식 TC가 이미 검증한다.",
            )
        ],
        test_cases=[],
        coverage_summary="신규 후보 없이 기존 공식 TC만 다시 실행한다.",
    )
    _write_json(
        run_dir / "agent2_test_design.json",
        design.model_dump(mode="json", by_alias=True),
    )
    _write_json(
        run_dir / "agent3_run_summary.json",
        {
            "contract_version": "1.1",
            "run_id": run_id,
            "stage": "AGENT_3_RUN_SUMMARY",
            "status": "NOT_REQUIRED",
            "selected_tc_ids": [],
            "executed_tc_ids": [],
            "entries": [],
            "자동화_제외_TC": [],
            "target_file": target.name,
            "target_sha256": _sha256_file(target),
        },
    )
    calls: list[str] = []

    def fake_regression(
        spec,
        *_args,
        source=pipeline.ExecutionSource.EXISTING_REGRESSION,
        **_kwargs,
    ):
        calls.append(spec.tc_id)
        return _neutral_execution_result(spec.tc_id, source)

    monkeypatch.setattr(pipeline_execution, "run_existing_regression", fake_regression)

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 0
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )

    assert calls == ["TC-ENV-000", "TC-TEMP-001"]
    assert bundle.candidate_result is None
    assert bundle.candidate_results == []
    assert bundle.selected_regression_ids == ["TC-TEMP-001"]
    assert [item.test_id for item in bundle.regression_results] == ["TC-TEMP-001"]

def test_validation_execution_stops_regressions_when_precheck_is_not_passed(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-030000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    _write_json(run_dir / "agent3_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_trial.json", {"outcome": "PASS"})
    _write_json(
        run_dir / "agent2_test_design.json",
        cp2_valid_design().model_dump(mode="json", by_alias=True),
    )
    monkeypatch.setattr(
        pipeline_execution,
        "_candidate_execution_record",
        lambda _run_dir, _run_id, _target: (
            _neutral_execution_result(
                "TC-CAND-003", pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
            ),
            agent3_test_case(),
            {},
        ),
    )
    monkeypatch.setattr(
        pipeline_execution,
        "_current_candidate_execution_record",
        lambda _run_dir, _run_id, _target, _test_case, stored, **_kwargs: stored,
    )
    calls: list[str] = []

    def failed_precheck(spec, *_args, source=pipeline.ExecutionSource.EXISTING_REGRESSION, **_kwargs):
        calls.append(spec.tc_id)
        return _neutral_execution_result(
            spec.tc_id,
            source,
            pipeline.NeutralExecutionStatus.EXECUTION_ERROR,
        )

    monkeypatch.setattr(pipeline_execution, "run_existing_regression", failed_precheck)

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 2
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )
    assert calls == ["TC-ENV-000"]
    assert bundle.status == pipeline.ValidationStageStatus.BLOCKED
    assert bundle.selected_regression_ids == ["TC-TEMP-001"]
    assert bundle.regression_results == []
    assert bundle.blocked_reason == "ENVIRONMENT_PRECHECK_NOT_PASSED"

def test_execute_parser_exposes_validation_execution_command() -> None:
    args = pipeline.build_parser().parse_args(
        [
            "execute",
            "--run-id",
            "RUN-20260816-010000-ABCDEF",
            "--target-html",
            "virtual-controller.html",
        ]
    )

    assert args.handler is pipeline.run_validation_execution
    assert args.baseline_tests is None
    assert args.timeout == 60
