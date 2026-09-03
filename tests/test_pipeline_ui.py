"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_v2_product_baseline_contains_only_runtime_assets() -> None:
    baseline_root = REPO_ROOT / "product_baseline"
    imported_files: list[str] = []
    for path in baseline_root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(baseline_root)
        if any(
            part in {".pytest_cache", "__pycache__", "reports"}
            for part in relative_path.parts
        ) or relative_path.name == "debug.log":
            continue
        imported_files.append(relative_path.as_posix())

    assert sorted(imported_files) == [
        "pytest.ini",
        "tests/conftest.py",
        "tests/test_controller.py",
        "virtual-controller.html",
    ]
    assert (baseline_root / "virtual-controller.html").is_file()

def test_success_fan_speed_request_is_grounded_in_v2_baseline() -> None:
    request = pipeline.ChangeRequest.model_validate_json(
        (REPO_ROOT / "examples" / "change_request.success-fan-speed.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = pipeline.load_srs_requirements(
        REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"
    )
    product_html = (
        REPO_ROOT / "product_baseline" / "virtual-controller.html"
    ).read_text(encoding="utf-8")

    assert request.target_requirement_id == "REQ-FAN-001"
    assert request.target_requirement_id in requirements
    assert "HIGH" in request.after_value
    assert "fanSpeed" in request.after_value
    assert any("LOW" in note and "복원" in note for note in request.acceptance_notes)
    assert 'id="det-fan-high"' in product_html
    assert "setPanelFan('HIGH')" in product_html
    assert "device.fanSpeed = pendingState.fanSpeed" in product_html

def test_pipeline_ui_summarizes_real_run_artifacts(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_id = "RUN-20260829-120000-ABCDEF"
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "request.json",
        {
            "request_id": "CR-UI-001",
            "target_requirement_id": "REQ-FAN-001",
            "description": "실제 Run 표시 확인",
        },
    )
    _write_json(
        run_dir / "agent1_change_analysis.json",
        {
            "change_summary": "HIGH 표시 매핑을 변경한다.",
            "confirmed_conditions": [{"condition_id": "COND-001"}],
            "requirement_effects": [{"requirement_id": "REQ-FAN-001"}],
        },
    )
    _write_json(
        run_dir / "checkpoint1.json",
        {"status": "REVIEW", "final_review_notes": ["사람 확인 1건"]},
    )
    _write_json(
        run_dir / "agent2_test_design.json",
        {
            "test_cases": [
                {
                    "tc_id": "TC-CAND-001",
                    "title": "강풍 표시 검증",
                    "automation_candidate": True,
                }
            ],
            "제외_범위": ["실제 장비 통신"],
        },
    )
    _write_json(run_dir / "checkpoint2.json", {"status": "PASS"})
    _write_json(
        run_dir / "agent3_selection.json",
        {"status": "SELECTED", "selected_tc_ids": ["TC-CAND-001"]},
    )
    _write_json(
        run_dir / "agent3_run_summary.json",
        {
            "status": "PASS",
            "executed_tc_ids": ["TC-CAND-001"],
            "자동화_제외_TC": [],
        },
    )
    _write_json(
        run_dir / "validation_execution.json",
        {
            "status": "COMPLETED",
            "candidate_results": [{"test_id": "TC-CAND-001", "status": "PASSED"}],
            "regression_results": [],
            "environment_precheck": {"test_id": "TC-ENV-000", "status": "PASSED"},
        },
    )
    _write_json(
        run_dir / "agent4_analysis.json",
        {
            "recommendation": "PASS",
            "total_results": 2,
            "product_result_count": 1,
            "environment_result_count": 1,
        },
    )
    _write_json(run_dir / "checkpoint4.json", {"status": "PASS"})
    _write_json(
        run_dir / "final_report.json",
        {
            "recommendation": "PASS",
            "total_results": 2,
            "product_result_count": 1,
            "environment_result_count": 1,
            "검토_항목": [],
            "최종_확인_사항": ["CP1 사람 확인 1건"],
        },
    )
    _write_json(
        run_dir / "external_reporting.json",
        {
            "mode": "DRY_RUN",
            "slack": {"status": "PREVIEW"},
            "notion": {"status": "PREVIEW"},
        },
    )

    summary = pipeline_ui.summarize_run(runs_root, run_id)

    assert summary["request_id"] == "CR-UI-001"
    assert summary["overall_status"] == "PASS"
    assert summary["stages"]["agent1"]["status"] == "REVIEW"
    assert "설계 TC 1건" in summary["stages"]["agent2"]["summary"]
    assert "후보 시험 완료 1건" in summary["stages"]["agent3"]["summary"]
    assert summary["stages"]["agent4"]["summary"] == "최종 판정 PASS · 외부 보고 DRY_RUN"
    assert "Slack: PREVIEW / Notion: PREVIEW" in summary["stages"]["agent4"]["details"]

def test_pipeline_ui_human_approval_registers_immutable_tc_and_automation(
    tmp_path: Path,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, candidate_code = (
        build_approvable_ui_run(tmp_path)
    )
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=tmp_path / "examples",
        target_html=target_html,
        allow_live_run=False,
        allow_asset_approval=True,
        approved_assets_root=approved_root,
    )

    record = bridge.decide_asset(
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="오세훈",
        note="실행 증거와 복원 결과 확인",
    )
    repeated = bridge.decide_asset(
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="다른 입력",
        note="중복 호출",
    )

    assert record["decision"] == "APPROVED"
    assert record["official_tc_id"] == "TC-V2-001"
    assert repeated == record
    registry = json.loads((approved_root / "registry.json").read_text(encoding="utf-8"))
    assert len(registry["assets"]) == 1
    asset = registry["assets"][0]
    assert asset["source_key"] == f"{run_id}:{tc_id}"
    assert (approved_root / asset["automation_file"]).read_text(encoding="utf-8") == candidate_code
    assert _sha256_file(approved_root / asset["automation_file"]) == asset["automation_sha256"]
    approved_tc = json.loads(
        (approved_root / asset["test_case_file"]).read_text(encoding="utf-8")
    )
    assert approved_tc["test_case"]["title"] == "검증된 풍량 변경"
    summary = pipeline_ui.summarize_run(
        runs_root,
        run_id,
        target_html=target_html,
    )
    assert summary["candidate_assets"][0]["decision"]["official_tc_id"] == "TC-V2-001"

def test_approved_tc_registry_is_loaded_and_official_automation_is_reusable(
    tmp_path: Path,
) -> None:
    approved_root = REPO_ROOT / "approved_assets"
    approved, snapshot = pipeline.load_approved_regression_catalog(approved_root)

    spec = next(item for item in approved if item.tc_id == "TC-V2-001")
    assert spec.source == "APPROVED"
    assert "REQ-FAN-001" in spec.requirement_ids
    assert "TC-V2-001" in pipeline.render_existing_regression_context(approved)
    assert snapshot["approved_assets"][0]["automation_sha256"] == spec.automation_sha256

    result = pipeline.run_existing_regression(
        spec,
        approved_root / str(spec.automation_file),
        REPO_ROOT / "product_baseline" / "virtual-controller.html",
        tmp_path / "approved-evidence",
        timeout_seconds=60,
    )

    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.test_file == spec.automation_file
    assert result.test_sha256 == spec.automation_sha256
    assert result.evidence_complete is True
    assert any(path.endswith("trial-final.png") for path in result.evidence_files)
    assert any(path.endswith("trial-trace.zip") for path in result.evidence_files)

def test_pipeline_ui_requires_and_applies_srs_revision_with_asset_approval(
    tmp_path: Path,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    srs_file = tmp_path / "SRS.md"
    srs_file.write_text(
        "# SRS\n\n| ID | 요구사항 | 인수 기준 |\n"
        "|---|---|---|\n"
        "| REQ-FAN-001 | 풍량 설정 | 기존 풍량 기준 |\n"
        "| REQ-LOCK-001 | 잠금 설정 | 기존 잠금 기준 |\n",
        encoding="utf-8",
    )
    final_report_file = runs_root / run_id / "final_report.json"
    _write_json(
        final_report_file,
        {
            "recommendation": "PASS",
            "SRS_개정_제안": [
                {
                    "proposal_id": "SRS-REV-001",
                    "requirement_id": "REQ-FAN-001",
                    "source_condition_ids": ["COND-001"],
                    "current_acceptance_criteria": "기존 풍량 기준",
                    "proposed_acceptance_criteria": "변경 풍량 기준",
                    "reason": "승인된 풍량 변경을 기준 문서에 반영한다.",
                },
                {
                    "proposal_id": "SRS-REV-002",
                    "requirement_id": "REQ-LOCK-001",
                    "source_condition_ids": ["COND-999"],
                    "current_acceptance_criteria": "기존 잠금 기준",
                    "proposed_acceptance_criteria": "다른 후보의 잠금 기준",
                    "reason": "다른 후보에서 검토할 제안이다.",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="SRS 개정 포함 승인"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            srs_path=srs_file,
            decision="APPROVE",
            reviewer="검토자",
            note="",
        )

    record = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        srs_path=srs_file,
        decision="APPROVE",
        reviewer="검토자",
        note="SRS 개정 문구와 실행 증거 확인",
        approve_srs_revisions=True,
    )

    assert record["decision"] == "APPROVED"
    assert record["srs_revision_applied"] is True
    assert "변경 풍량 기준" in srs_file.read_text(encoding="utf-8")
    assert "기존 잠금 기준" in srs_file.read_text(encoding="utf-8")
    assert "다른 후보의 잠금 기준" not in srs_file.read_text(encoding="utf-8")
    registry = json.loads((approved_root / "registry.json").read_text(encoding="utf-8"))
    asset = registry["assets"][0]
    assert asset["srs_revision_before_sha256"] != asset["srs_revision_after_sha256"]
    assert (approved_root / asset["srs_revision_file"]).is_file()
    assert (runs_root / run_id / "srs_revision_decision.json").is_file()

def test_pipeline_ui_rolls_back_all_asset_files_when_approval_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    srs_file = tmp_path / "SRS.md"
    srs_file.write_text(
        "# SRS\n\n| ID | 요구사항 | 인수 기준 |\n"
        "|---|---|---|\n"
        "| REQ-FAN-001 | 풍량 설정 | 기존 풍량 기준 |\n",
        encoding="utf-8",
    )
    _write_json(
        runs_root / run_id / "final_report.json",
        {
            "recommendation": "PASS",
            "SRS_개정_제안": [
                {
                    "proposal_id": "SRS-REV-001",
                    "requirement_id": "REQ-FAN-001",
                    "source_condition_ids": ["COND-001"],
                    "current_acceptance_criteria": "기존 풍량 기준",
                    "proposed_acceptance_criteria": "변경 풍량 기준",
                    "reason": "승인된 풍량 변경을 기준 문서에 반영한다.",
                }
            ],
        },
    )
    srs_before = srs_file.read_bytes()

    def fail_after_partial_copy(_source, destination, *args, **kwargs):
        del args, kwargs
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(b"partial")
        raise OSError("simulated copy failure")

    monkeypatch.setattr(pipeline_ui.shutil, "copy2", fail_after_partial_copy)

    with pytest.raises(OSError, match="simulated copy failure"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            srs_path=srs_file,
            decision="APPROVE",
            reviewer="검토자",
            note="실패 시 원상 복구 확인",
            approve_srs_revisions=True,
        )

    assert srs_file.read_bytes() == srs_before
    assert not (approved_root / "registry.json").exists()
    assert not (approved_root / "test_cases" / "TC-V2-001.json").exists()
    assert not (approved_root / "automation" / "test_tc_v2_001.py").exists()
    assert not (approved_root / "automation" / "test_tc_v2_001.py.tmp").exists()
    assert not (approved_root / "srs_revisions" / "TC-V2-001.json").exists()
    assert not (runs_root / run_id / "srs_revision_decision.json").exists()
    assert not (runs_root / run_id / "asset_decisions.json").exists()

def test_pipeline_ui_hold_is_recorded_and_can_later_be_approved(tmp_path: Path) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )

    held = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        decision="HOLD",
        reviewer="검토자",
        note="요구사항 담당자 확인 필요",
    )
    approved = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="검토자",
        note="확인 완료",
    )

    assert held["decision"] == "HELD"
    assert not (approved_root / "registry.json").read_text(encoding="utf-8").count("HELD")
    assert approved["decision"] == "APPROVED"
    decisions = json.loads(
        (runs_root / run_id / "asset_decisions.json").read_text(encoding="utf-8")
    )
    assert decisions["decisions"] == [approved]

def test_pipeline_ui_blocks_asset_approval_for_failed_or_stale_evidence(
    tmp_path: Path,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    _write_json(runs_root / run_id / "final_report.json", {"recommendation": "HOLD"})

    with pytest.raises(ValueError, match="최종 권고"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            decision="APPROVE",
            reviewer="검토자",
            note="",
        )

    _write_json(runs_root / run_id / "final_report.json", {"recommendation": "PASS"})
    target_html.write_text("<!doctype html><title>changed</title>", encoding="utf-8")
    with pytest.raises(ValueError, match="재검증"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            decision="APPROVE",
            reviewer="검토자",
            note="",
        )
    assert not (approved_root / "registry.json").exists()

def test_pipeline_ui_revalidates_stale_candidate_without_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    target_html.write_text("<!doctype html><title>UI updated</title>", encoding="utf-8")

    def fake_trial(code_file, current_target, evidence_dir, *, timeout_seconds):
        evidence_dir.mkdir(parents=True)
        hashes = {}
        for name, content in (
            ("trial-stdout.txt", b"1 passed"),
            ("trial-stderr.txt", b""),
            ("trial-final.png", b"PNG2"),
            ("trial-trace.zip", b"ZIP2"),
        ):
            path = evidence_dir / name
            path.write_bytes(content)
            hashes[name] = _sha256_file(path)
        return pipeline.Agent3TrialResult(
            outcome=pipeline.TrialOutcome.PASS,
            exit_code=0,
            duration_ms=10,
            stdout_file="trial-stdout.txt",
            stderr_file="trial-stderr.txt",
            screenshot_file="trial-final.png",
            trace_file="trial-trace.zip",
            evidence_sha256=hashes,
            evidence_complete=True,
        )

    monkeypatch.setattr(pipeline, "run_candidate_trial", fake_trial)

    record = pipeline_ui.revalidate_candidate_asset(
        runs_root,
        target_html,
        run_id,
        tc_id,
    )
    summary = pipeline_ui.summarize_run(
        runs_root,
        run_id,
        target_html=target_html,
    )
    approved = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="검토자",
        note="현재 화면 재검증 확인",
    )
    latest = runs_root / run_id / "asset_revalidation" / tc_id / "latest.json"

    assert record["outcome"] == "PASS"
    assert record["target_sha256"] == _sha256_file(target_html)
    assert summary["candidate_assets"][0]["approval_eligible"] is True
    assert summary["candidate_assets"][0]["revalidation_required"] is False
    assert approved["approval_revalidation_sha256"] == _sha256_file(latest)

def test_pipeline_ui_rejects_unscoped_run_and_request_paths(tmp_path: Path) -> None:
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=tmp_path / "runs",
        requests_root=tmp_path / "examples",
        target_html=tmp_path / "virtual-controller.html",
        allow_live_run=False,
    )

    with pytest.raises(ValueError, match="Run ID"):
        pipeline_ui.summarize_run(tmp_path / "runs", "../outside")
    with pytest.raises(ValueError, match="파일명"):
        bridge.request_path("../change_request.json")
    with pytest.raises(PermissionError, match="비활성화"):
        bridge.start_live_run("change_request.json")

def test_pipeline_ui_failure_message_is_safe_and_actionable(tmp_path: Path) -> None:
    run_dir = tmp_path / "RUN-20260829-130000-ABCDEF"
    run_dir.mkdir()
    _write_json(
        run_dir / "run_error.json",
        {
            "error_type": "Agent1Error",
            "message": f"모델 연결 실패: {pipeline_ui.REPO_ROOT / 'private-input.json'}",
        },
    )

    message = pipeline_ui._safe_run_error(run_dir)

    assert message == "모델 연결 실패: <REPO_ROOT>\\private-input.json"
    assert str(pipeline_ui.REPO_ROOT) not in message

    (run_dir / "run_error.json").unlink()
    nested = run_dir / "agent3_candidates" / "TC-CAND-001"
    nested.mkdir(parents=True)
    _write_json(
        nested / "agent3_error.json",
        {"tc_id": "TC-CAND-001", "message": "브라우저 종료 오류"},
    )
    assert pipeline_ui._safe_run_error(run_dir) == "TC-CAND-001: 브라우저 종료 오류"

    (nested / "agent3_error.json").unlink()
    _write_json(
        run_dir / "agent3_run_summary.json",
        {"entries": [{"tc_id": "TC-CAND-001", "trial_outcome": "TIMEOUT"}]},
    )
    assert pipeline_ui._safe_run_error(run_dir) == "TC-CAND-001: 후보 시험 TIMEOUT"

def test_pipeline_ui_live_run_is_disabled_by_default() -> None:
    args = pipeline_ui.build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.allow_live_run is False
    assert args.allow_asset_approval is False

def test_pipeline_ui_prevents_parallel_live_runs_across_bridges(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    requests_root = tmp_path / "examples"
    requests_root.mkdir()
    _write_json(requests_root / "change_request.json", {"request_id": "CR-LOCK-001"})
    target_html = tmp_path / "virtual-controller.html"
    target_html.write_text("<!doctype html>", encoding="utf-8")
    first = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=requests_root,
        target_html=target_html,
        allow_live_run=True,
    )
    second = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=requests_root,
        target_html=target_html,
        allow_live_run=True,
    )

    assert first.live_run_lock.acquire() is True
    try:
        with pytest.raises(RuntimeError, match="다른 로컬 브리지"):
            second.start_live_run("change_request.json")
    finally:
        first.live_run_lock.release()
    assert second.live_run_lock.acquire() is True
    second.live_run_lock.release()

def test_pipeline_ui_live_run_uses_agent1_to_4_order_without_external_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = tmp_path / "runs"
    requests_root = tmp_path / "examples"
    requests_root.mkdir()
    request_file = requests_root / "change_request.success.json"
    _write_json(request_file, {"request_id": "CR-UI-LIVE-001"})
    target_html = tmp_path / "virtual-controller.html"
    target_html.write_text("<!doctype html>", encoding="utf-8")
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=requests_root,
        target_html=target_html,
        allow_live_run=True,
    )
    run_id = "RUN-20260829-130000-ABCDEF"
    commands: list[tuple[str, ...]] = []

    def fake_command(*arguments: str) -> SimpleNamespace:
        commands.append(arguments)
        if arguments[0] == "pipeline":
            (runs_root / run_id).mkdir(parents=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge, "_command", fake_command)

    bridge._run_pipeline(request_file)

    assert [command[0] for command in commands] == ["pipeline", "execute", "agent4"]
    assert commands[0][-2:] == ("--timeout", "90")
    assert "--send" not in commands[-1]
    assert bridge.state.snapshot()["phase"] == "COMPLETED"
    assert bridge.state.snapshot()["run_id"] == run_id

def test_v2_product_ui_routes_agent_buttons_to_real_run_bridge() -> None:
    product_html = (
        REPO_ROOT / "product_baseline" / "virtual-controller.html"
    ).read_text(encoding="utf-8")

    assert 'id="qa-live-modal"' in product_html
    assert "qaLiveFetch('/api/qa/state')" in product_html
    assert "if (openQaLiveModal('agent1')) return;" in product_html
    assert "if (openQaLiveModal('agent2')) return;" in product_html
    assert "if (openQaLiveModal('agent3')) return;" in product_html
    assert "if (openQaLiveModal('agent4')) return;" in product_html
    assert "if (openQaLiveModal('overview')) return;" in product_html
    assert "function showQaLiveOverview()" in product_html
    assert "Agent 1→4 실제 Run 상태입니다." in product_html
    assert "setTowerStatus('실제 실행 실패', '#f87171')" in product_html
    assert "setTowerStatus('실제 실행 완료', '#34d399')" in product_html
    assert "확인: API Live 실행" in product_html
    assert "qaLiveState.startApprovalArmed && !overview.running" in product_html
    assert "window.confirm(" not in product_html
    assert "외부 보고는 미리보기만 생성" in product_html
    assert "저장 결과 보기" in product_html
    assert "AI API 사용 없음" in product_html
    assert "새 요구사항 실제 실행" in product_html
    assert "AI API 비용 발생" in product_html
    assert "후보 TC 공식 자산 판단" in product_html
    assert "공식 TC·자동화 등록 승인" in product_html
    assert "/asset-decision" in product_html
    assert "현재 화면에서 후보 재검증" in product_html
    assert "/asset-revalidation" in product_html
    assert "확인: 공식 자산 등록" in product_html
