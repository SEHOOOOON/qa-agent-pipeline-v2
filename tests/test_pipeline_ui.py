"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


@pytest.mark.parametrize("decision,mode", [("APPROVE", "ADD"), ("APPROVE", "REPLACE"),
                                         ("DECLINE", "ADD"), ("HOLD", "ADD")])
def test_saved_single_run_asset_choices_preserve_sources(saved_single_approval_run, decision, mode):
    runs, assets, target, run_id, tc_id, srs = saved_single_approval_run
    run = runs / run_id
    before = {str(p.relative_to(assets)): p.read_bytes() for p in assets.rglob('*') if p.is_file()}
    source_before = {str(p.relative_to(run)): p.read_bytes() for p in run.rglob('*') if p.is_file()}
    srs_before = srs.read_bytes()
    case = pipeline_ui._candidate_test_case(run, tc_id)
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    assert not pipeline_ui._candidate_approval_check(run, tc_id, target_html=target)[3]
    result = pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        srs_path=srs, decision=decision, reviewer="로컬 검사", note="사본 선택 경로 시험",
        registration_mode=mode, replace_tc_ids=["TC-MODE-003"] if mode == "REPLACE" else [],
        comparison_sha256=comparison["fingerprint"])
    assert result["decision"] == {"APPROVE": "APPROVED", "DECLINE": "DECLINED", "HOLD": "HELD"}[decision]
    assert all((run / name).read_bytes() == content for name, content in source_before.items())
    assert srs.read_bytes() == srs_before
    if decision == "APPROVE":
        assert all((assets / name).read_bytes() == content for name, content in before.items() if name != 'registry.json')
        _, snapshot = pipeline.load_approved_regression_catalog(assets)
        ids = {item.tc_id for item in pipeline._catalog_from_snapshot(snapshot)}
        assert result['official_tc_id'] in ids
        assert ("TC-MODE-003" not in ids) == (mode == "REPLACE")
        assert {"TC-MODE-001", "TC-MODE-002"}.issubset(ids)
    else:
        assert before == {str(p.relative_to(assets)): p.read_bytes() for p in assets.rglob('*') if p.is_file()}
    view = pipeline_ui.summarize_run(runs, run_id, target_html=target, approved_assets_root=assets)
    assert view['candidate_assets'][0]['decision']['decision'] == result['decision']


@pytest.mark.parametrize("damage", ["outside", "other_tc", "missing_manifest", "wrong_hash",
    "duplicate", "missing_source", "mixed_summary", "missing_trace", "changed_code", "wrong_tc_identity"])
def test_saved_single_run_approval_rejects_damaged_evidence(saved_single_approval_run, damage):
    runs, assets, target, run_id, tc_id, srs = saved_single_approval_run
    run = runs / run_id
    path = run / 'validation_manifest.json'
    metadata = json.loads(path.read_text(encoding='utf-8'))
    source = metadata['source_agent3_artifacts'][0]
    if damage == 'outside': source['agent3_manifest_file'] = '../agent3_manifest.json'
    elif damage == 'other_tc': source['tc_id'] = 'TC-CAND-999'
    elif damage == 'missing_manifest': source['agent3_manifest_file'] = 'missing.json'
    elif damage == 'wrong_hash': source['agent3_manifest_sha256'] = '0' * 64
    elif damage == 'duplicate': metadata['source_agent3_artifacts'].append(dict(source))
    elif damage == 'missing_source': metadata['source_agent3_artifacts'] = []
    elif damage == 'mixed_summary': _write_json(run / 'agent3_run_summary.json', {'entries': []})
    elif damage == 'missing_trace': (run / 'evidence' / tc_id / 'trial-trace.zip').unlink()
    elif damage == 'changed_code':
        code = next((run / 'candidates').glob('*.py'))
        code.write_text(code.read_text(encoding='utf-8') + '\n# changed\n', encoding='utf-8')
    else:
        mf = run / 'agent3_manifest.json'
        altered = json.loads(mf.read_text(encoding='utf-8'))
        altered['tc_id'] = 'TC-CAND-999'
        _write_json(mf, altered)
        source['agent3_manifest_sha256'] = _sha256_file(mf)
    _write_json(path, metadata)
    before = {str(p.relative_to(assets)): p.read_bytes() for p in assets.rglob('*') if p.is_file()}
    assert pipeline_ui._candidate_approval_check(run, tc_id, target_html=target)[3]
    with pytest.raises(ValueError):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            srs_path=srs, decision='APPROVE', reviewer='검사', note='차단 확인')
    assert before == {str(p.relative_to(assets)): p.read_bytes() for p in assets.rglob('*') if p.is_file()}
    assert not (run / 'asset_decisions.json').exists()


@pytest.mark.parametrize('layout', ['single', 'multi'])
@pytest.mark.parametrize('damage', ['none', 'wrong_tc', 'wrong_run', 'wrong_path', 'duplicate', 'bad_hash', 'missing'])
def test_asset_source_resolver_layouts_and_guards(tmp_path, layout, damage):
    run = tmp_path / 'RUN-20261007-120000-ABCDEF'
    tc_id = 'TC-CAND-001'
    directory = run if layout == 'single' else run / 'agent3_candidates' / tc_id
    mf = directory / 'agent3_manifest.json'
    _write_json(mf, dict(run_id=run.name, tc_id=tc_id, stage='AGENT_3_CP3_TRIAL', status='PASS'))
    _write_json(directory / 'checkpoint3.json', {'status': 'PASS'})
    if damage in {'wrong_tc', 'wrong_run'}:
        value = json.loads(mf.read_text(encoding='utf-8'))
        value['tc_id' if damage == 'wrong_tc' else 'run_id'] = 'OTHER'
        _write_json(mf, value)
    item = dict(tc_id=tc_id, agent3_manifest_file=mf.relative_to(run).as_posix(), agent3_manifest_sha256=_sha256_file(mf))
    summary_hash = None
    if layout == 'multi':
        _write_json(run / 'agent3_run_summary.json', {'entries': [dict(tc_id=tc_id, status='PASS', checkpoint_status='PASS',
            artifact_dir=directory.relative_to(run).as_posix(), manifest_sha256=_sha256_file(mf))]})
        summary_hash = _sha256_file(run / 'agent3_run_summary.json')
    if damage == 'wrong_path': item['agent3_manifest_file'] = '../agent3_manifest.json'
    if damage == 'bad_hash': item['agent3_manifest_sha256'] = '0' * 64
    items = [item, dict(item)] if damage == 'duplicate' else [] if damage == 'missing' else [item]
    _write_json(run / 'validation_manifest.json', dict(source_agent3_artifacts=items, source_agent3_run_summary_sha256=summary_hash))
    if damage == 'none':
        actual, manifest, entry = pipeline_ui._candidate_artifacts(run, tc_id)
        assert actual == directory.resolve() and manifest['tc_id'] == tc_id and entry['checkpoint_status'] == 'PASS'
    else:
        with pytest.raises(ValueError): pipeline_ui._candidate_artifacts(run, tc_id)


def test_saved_single_run_local_revalidation_uses_same_source(saved_single_approval_run):
    runs, assets, target, run_id, tc_id, _ = saved_single_approval_run
    record = pipeline_ui.revalidate_candidate_asset(runs, target, run_id, tc_id)
    assert record['outcome'] == 'PASS' and record['evidence_complete']
    assert not pipeline_ui._candidate_approval_check(runs / run_id, tc_id, target_html=target)[3]


@pytest.mark.parametrize("earlier_decision", [None, "HOLD", "DECLINE"])
def test_saved_single_registered_asset_reexecutes_without_source_stub(
        saved_single_approval_run, earlier_decision, tmp_path):
    runs, assets, target, run_id, tc_id, srs = saved_single_approval_run
    run = runs / run_id
    before = {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    srs_before = srs.read_bytes()
    if earlier_decision:
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            srs_path=srs, decision=earlier_decision, reviewer="로컬 검증", note="등록 전 선택")
        assert before == {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    comparison = pipeline_ui.candidate_asset_comparison(pipeline_ui._candidate_test_case(run, tc_id), assets)
    kwargs = dict(srs_path=srs, decision="APPROVE", reviewer="로컬 검증",
                  note="사본 신규 등록과 재사용 확인", comparison_sha256=comparison["fingerprint"])
    record = pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id, **kwargs)
    after = {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    assert record["decision"] == "APPROVED"
    assert pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id, **kwargs) == record
    assert after == {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    catalog, snapshot = pipeline.load_approved_regression_catalog(assets)
    spec = next(item for item in catalog if item.tc_id == record["official_tc_id"])
    assert spec.tc_id in {item.tc_id for item in pipeline._catalog_from_snapshot(snapshot)}
    result = pipeline.run_existing_regression(spec, assets / spec.automation_file, target,
        tmp_path / "registered-evidence", timeout_seconds=90)
    _write_json(tmp_path / "registered-result.json", result.model_dump(mode="json"))
    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.evidence_complete and result.test_sha256 == spec.automation_sha256
    stdout = next((tmp_path / "registered-evidence").rglob("*stdout*")).read_text(encoding="utf-8")
    assert "RESTORE_STATUS: RESTORED" in stdout
    assert after == {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    assert srs.read_bytes() == srs_before


@pytest.mark.parametrize("case", [
    "normal", "fan_question", "lock_question", "missing_question", "tampered_analysis",
    "tampered_checkpoint", "wrong_run", "internal_error", "later_stage", "quality_fail",
    "proceed", "transport_error", "malformed",
])
def test_ui_distinguishes_verified_waiting_from_failure(tmp_path, monkeypatch, case):
    run_id = "RUN-20261005-120000-ABCDEF"
    run = tmp_path / "runs" / run_id
    run.mkdir(parents=True)
    question = {"fan_question": "새 풍량은 무엇인가요?", "lock_question": "잠글 대상은 무엇인가요?"}.get(
        case, '새 하한은 몇 도인가요?\n"18°C"처럼 값을 알려주세요.')
    analysis = {"decision": "WAITING_FOR_USER", "user_questions": [question]}
    checkpoint = {"status": "PASS", "handoff_status": "PAUSE"}
    if case == "missing_question":
        analysis["user_questions"] = []
    if case == "proceed":
        analysis["decision"] = "PROCEED"
    if case == "quality_fail":
        checkpoint["status"] = "FAIL"
    _write_json(run / "agent1_change_analysis.json", analysis)
    _write_json(run / "checkpoint1.json", checkpoint)
    manifest = {"run_id": run_id, "stage": "AGENT_1_CP1", **checkpoint,
        "agent1_analysis_sha256": _sha256_file(run / "agent1_change_analysis.json"),
        "checkpoint1_sha256": _sha256_file(run / "checkpoint1.json")}
    _write_json(run / "run_manifest.json", manifest)
    orchestrator = {"run_id": run_id, "status": "STOPPED", "stopped_at": "agent1",
        "stage_exit_codes": {"agent1": 2}, "agent1_manifest_sha256": _sha256_file(run / "run_manifest.json")}
    if case == "wrong_run":
        orchestrator["run_id"] = "RUN-20261005-120000-FFFFFF"
    if case == "internal_error":
        orchestrator["status"] = "ERROR"
    if case == "later_stage":
        orchestrator["stage_exit_codes"]["agent2"] = 1
    _write_json(run / "orchestrator_manifest.json", orchestrator)
    if case == "tampered_analysis":
        _write_json(run / "agent1_change_analysis.json", {**analysis, "user_questions": ["changed"]})
    if case == "tampered_checkpoint":
        _write_json(run / "checkpoint1.json", {**checkpoint, "extra": "changed"})
    if case == "malformed":
        (run / "agent1_change_analysis.json").write_text("{", encoding="utf-8")
    before = {f.name: _sha256_file(f) for f in run.iterdir()}
    monkeypatch.setattr(pipeline_ui, "_new_run_id", lambda: run_id)
    bridge = pipeline_ui.PipelineUiBridge(runs_root=run.parent, requests_root=tmp_path,
        target_html=REPO_ROOT / "product_baseline/virtual-controller.html", allow_live_run=True)
    calls = []
    def fake_command(*args):
        calls.append(args[0])
        return SimpleNamespace(returncode=1 if case == "transport_error" else 2)
    monkeypatch.setattr(bridge, "_command", fake_command)
    assert bridge.live_run_lock.acquire()
    bridge._run_pipeline(tmp_path / "request.json")
    state = bridge.state.snapshot()
    expected_wait = case in {"normal", "fan_question", "lock_question"}
    assert state["phase"] == ("WAITING_FOR_USER" if expected_wait else "FAILED")
    assert state["running"] is False and calls == ["pipeline"]
    if expected_wait:
        assert question in state["message"]
        summary = pipeline_ui.summarize_run(run.parent, run_id)
        assert summary["overall_status"] == "확인 대기"
        assert any(question in detail for detail in summary["stages"]["agent1"]["details"])
    assert before == {f.name: _sha256_file(f) for f in run.iterdir()}
    assert bridge.live_run_lock.acquire()
    bridge.live_run_lock.release()


def test_ui_waiting_message_is_not_failure_or_completion_in_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("https://**/*", lambda route: route.abort())
        page.goto((REPO_ROOT / "product_baseline/virtual-controller.html").as_uri(),
                  wait_until="domcontentloaded")
        page.wait_for_function("typeof updateQaLiveExecutionControls === 'function'")
        result = page.evaluate("""() => {
            const seen = [];
            setTowerStatus = (text, color) => seen.push({text, color});
            qaLiveState.connected = true;
            qaLiveState.demoMode = false;
            qaLiveState.startApprovalArmed = false;
            updateQaLiveExecutionControls({running:false, allow_live_run:true,
                phase:'WAITING_FOR_USER', message:'확인 질문: 새 하한은 몇 도인가요?'});
            return {seen, message:document.getElementById('qa-live-message').textContent,
                disabled:document.getElementById('qa-live-start-btn').disabled};
        }""")
        assert result["seen"][-1]["text"] == "사용자 확인 대기"
        assert result["seen"][-1]["color"] == "#fbbf24"
        assert "새 하한은 몇 도인가요?" in result["message"]
        assert result["disabled"] is False
        browser.close()


@pytest.mark.parametrize("requirement", ["REQ-CONTROL-001", "REQ-MODE-001", "REQ-TEMP-001", "REQ-FAN-001", "REQ-LOCK-001"])
def test_tc_comparison_replacement_all_controls(tmp_path, monkeypatch, requirement):
    roots = build_approvable_ui_run(tmp_path, monkeypatch)
    runs, assets, target, run_id, tc_id, _ = roots
    run = runs / run_id
    case = cp2_valid_design().test_cases[0].model_dump(mode="json")
    case.update(tc_id=tc_id, requirement_ids=[requirement])
    _write_json(run / "agent2_test_design.json", {"test_cases": [case]})
    first = pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        decision="APPROVE", reviewer="검토자", note="첫 기준")
    original = (assets / "test_cases/TC-V2-001.json").read_bytes()
    import shutil
    next_id = "RUN-20261004-120000-ABCDEF"
    shutil.copytree(run, runs / next_id)
    (runs / next_id / "asset_decisions.json").unlink()
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    related = [item for item in comparison["existing"] if item["shared_requirement_ids"]]
    assert any(item["tc_id"] == first["official_tc_id"] for item in related)
    record = pipeline_ui.decide_candidate_asset(runs, assets, target, next_id, tc_id,
        decision="APPROVE", reviewer="검토자", note="변경 기준으로 대체",
        registration_mode="REPLACE", replace_tc_ids=["TC-V2-001"],
        comparison_sha256=comparison["fingerprint"])
    assert record["official_tc_id"] == "TC-V2-002"
    assert record["replaced_tc_ids"] == ["TC-V2-001"]
    assert (assets / "test_cases/TC-V2-001.json").read_bytes() == original
    catalog, snapshot = pipeline.load_approved_regression_catalog(assets)
    assert [item.tc_id for item in catalog] == ["TC-V2-002"]
    assert "TC-V2-001" not in {item.tc_id for item in pipeline._catalog_from_snapshot(snapshot)}
    # Historical snapshots are not rewritten, and the old source files remain readable.
    repeated = pipeline_ui.decide_candidate_asset(runs, assets, target, next_id, tc_id,
        decision="APPROVE", reviewer="검토자", note="반복",
        registration_mode="REPLACE", replace_tc_ids=["TC-V2-001"],
        comparison_sha256=comparison["fingerprint"])
    assert repeated == record
    shown = pipeline_ui.candidate_asset_comparison(case, assets)
    assert not next(item for item in shown["existing"] if item["tc_id"] == "TC-V2-001")["active"]


@pytest.mark.parametrize("decision", ["APPROVE", "HOLD", "DECLINE"])
@pytest.mark.parametrize("stored_decision", [None, "HELD"])
def test_registered_source_without_local_decision_cannot_record_new_intent(tmp_path, monkeypatch, decision, stored_decision):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        decision="APPROVE", reviewer="첫 검토자", note="기존 승인")
    # Only this isolated test copy loses its local decision; registry remains authoritative.
    decision_file = runs / run_id / "asset_decisions.json"
    decision_file.unlink()
    if stored_decision:
        _write_json(decision_file, {"decisions": [{"tc_id": tc_id, "decision": stored_decision}]})
    decision_before = decision_file.read_bytes() if decision_file.exists() else None
    before = {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    case = pipeline_ui._candidate_test_case(runs / run_id, tc_id)
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    kwargs = dict(decision=decision, reviewer="새 검토자", note="다른 판단")
    if decision == "APPROVE":
        kwargs.update(registration_mode="REPLACE", replace_tc_ids=["TC-TEMP-001"],
            comparison_sha256=comparison["fingerprint"])
    with pytest.raises(ValueError, match="이미 공식 등록"):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id, **kwargs)
    assert (decision_file.read_bytes() if decision_file.exists() else None) == decision_before
    assert before == {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}


@pytest.mark.parametrize("fail_write", [False, True])
def test_multiple_replacements_preserve_existing_assets_and_rollback(tmp_path, monkeypatch, fail_write):
    import shutil
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    case = cp2_valid_design().test_cases[0].model_dump(mode="json")
    case["tc_id"] = tc_id
    _write_json(runs / run_id / "agent2_test_design.json", {"test_cases": [case]})
    pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        decision="APPROVE", reviewer="검토자", note="첫 자산")
    next_id = "RUN-20261004-140000-ABCDEF"
    shutil.copytree(runs / run_id, runs / next_id)
    (runs / next_id / "asset_decisions.json").unlink()
    case = pipeline_ui._candidate_test_case(runs / next_id, tc_id)
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    before = {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    kwargs = dict(decision="APPROVE", reviewer="검토자", note="복수 선택 처리 검증",
        registration_mode="REPLACE", replace_tc_ids=["TC-V2-001", "TC-TEMP-001"],
        comparison_sha256=comparison["fingerprint"])
    if fail_write:
        write = pipeline_ui._write_json_atomic
        def fail(path, payload):
            if path.name == "asset_decisions.json":
                raise OSError("after registry update")
            return write(path, payload)
        monkeypatch.setattr(pipeline_ui, "_write_json_atomic", fail)
        with pytest.raises(OSError):
            pipeline_ui.decide_candidate_asset(runs, assets, target, next_id, tc_id, **kwargs)
        assert not (runs / next_id / "asset_decisions.json").exists()
        assert before == {p.relative_to(assets): p.read_bytes() for p in assets.rglob("*") if p.is_file()}
    else:
        record = pipeline_ui.decide_candidate_asset(runs, assets, target, next_id, tc_id, **kwargs)
        assert record["replaced_tc_ids"] == kwargs["replace_tc_ids"]
        catalog, snapshot = pipeline.load_approved_regression_catalog(assets)
        assert [tc.tc_id for tc in catalog] == ["TC-V2-002"]
        active = {tc.tc_id for tc in pipeline._catalog_from_snapshot(snapshot)}
        assert not active.intersection(kwargs["replace_tc_ids"])
        assert "TC-MODE-001" in active
        assert all((assets / p).read_bytes() == value for p, value in before.items() if p.name != "registry.json")


def test_tc_comparison_baseline_replacement_and_snapshot_history(tmp_path, monkeypatch):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    case = cp2_valid_design().test_cases[0].model_dump(mode="json")
    case.update(tc_id=tc_id, requirement_ids=["REQ-TEMP-001"])
    _write_json(runs / run_id / "agent2_test_design.json", {"test_cases": [case]})
    before = pipeline._catalog_from_snapshot({})
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        decision="APPROVE", reviewer="검토자", note="상한 시험 대체",
        registration_mode="REPLACE", replace_tc_ids=["TC-TEMP-001"],
        comparison_sha256=comparison["fingerprint"])
    _, snapshot = pipeline.load_approved_regression_catalog(assets)
    current = pipeline._catalog_from_snapshot(snapshot)
    assert "TC-TEMP-001" not in {item.tc_id for item in current}
    assert "TC-MODE-001" in {item.tc_id for item in current}
    assert "TC-TEMP-001" in {item.tc_id for item in before}
    # A saved old design must not execute a TC retired after its selection.
    old_run_id = "RUN-20261004-130000-ABCDEF"
    old_run = runs / old_run_id
    design = cp2_valid_design().model_copy(update={
        "existing_tc_comparison_completed": True,
        "related_existing_tests": [pipeline.ExistingTestSelection(
            tc_id="TC-TEMP-001", source_condition_ids=["COND-001"], selection_reason="과거 선택")],
    })
    _write_json(old_run / "agent2_test_design.json", design.model_dump(mode="json"))
    # Isolate the post-handoff retirement guard; the real handoff loader has
    # separate valid-source and tampering controls in test_orchestration_execution.
    monkeypatch.setattr(pipeline_execution, "_load_verified_agent2_run",
        lambda *_: (None, None, None, design, None, {}))
    monkeypatch.setattr(pipeline_execution, "_candidate_execution_records", lambda *_: ([], [], {}))
    def unexpected(*a, **k):
        raise AssertionError("대체된 TC 실행 전 중단해야 합니다")
    monkeypatch.setattr(pipeline_execution, "run_existing_regression", unexpected)
    baseline = tmp_path / "test_baseline.py"
    baseline.write_text("def test_example(): pass", encoding="utf-8")
    with pytest.raises(ValueError, match="사람 승인으로 대체"):
        pipeline_execution.run_validation_execution(SimpleNamespace(
            runs_root=str(runs), run_id=old_run_id, target_html=str(target),
            baseline_tests=str(baseline), approved_assets_root=str(assets), timeout=5))


def test_tc_comparison_changed_registry_or_source_requires_refresh(tmp_path, monkeypatch):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    case = pipeline_ui._candidate_test_case(runs / run_id, tc_id)
    view = pipeline_ui.candidate_asset_comparison(case, assets)
    _write_json(assets / "registry.json", {"assets": [], "review_note": "another change"})
    before = (assets / "registry.json").read_bytes()
    with pytest.raises(ValueError, match="다시 비교"):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            decision="APPROVE", reviewer="검토자", note="새 TC",
            comparison_sha256=view["fingerprint"])
    assert (assets / "registry.json").read_bytes() == before
    assert not (runs / run_id / "asset_decisions.json").exists()
    pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        decision="APPROVE", reviewer="검토자", note="등록")
    (assets / "test_cases/TC-V2-001.json").write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="원본이 변경"):
        pipeline_ui.candidate_asset_comparison(case, assets)


@pytest.mark.parametrize("damage", ["missing", "unknown", "duplicate", "stale", "no_note", "add_with_targets"])
def test_tc_comparison_rejects_invalid_replacement_without_writes(tmp_path, monkeypatch, damage):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    case = pipeline_ui._candidate_test_case(runs / run_id, tc_id)
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    kwargs = dict(decision="APPROVE", reviewer="검토자", note="대체",
        registration_mode="REPLACE", replace_tc_ids=["TC-TEMP-001"],
        comparison_sha256=comparison["fingerprint"])
    if damage == "missing": kwargs["replace_tc_ids"] = []
    if damage == "unknown": kwargs["replace_tc_ids"] = ["TC-NOT-001"]
    if damage == "duplicate": kwargs["replace_tc_ids"] *= 2
    if damage == "stale": kwargs["comparison_sha256"] = "old"
    if damage == "no_note": kwargs["note"] = ""
    if damage == "add_with_targets": kwargs["registration_mode"] = "ADD"
    with pytest.raises(ValueError):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id, **kwargs)
    assert not (assets / "registry.json").exists()
    assert not (runs / run_id / "asset_decisions.json").exists()


@pytest.mark.parametrize("decision", ["HOLD", "DECLINE"])
def test_tc_comparison_no_registration_preserves_assets(tmp_path, monkeypatch, decision):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    result = pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
        decision=decision, reviewer="검토자", note="기존 시험으로 충분")
    assert result["decision"] == {"HOLD": "HELD", "DECLINE": "DECLINED"}[decision]
    assert not (assets / "registry.json").exists()


def test_tc_comparison_replacement_rolls_back_registry(tmp_path, monkeypatch):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    case = pipeline_ui._candidate_test_case(runs / run_id, tc_id)
    comparison = pipeline_ui.candidate_asset_comparison(case, assets)
    write = pipeline_ui._write_json_atomic
    def fail_after_registry(path, payload):
        if path.name == "asset_decisions.json":
            raise OSError("decision write failed")
        return write(path, payload)
    monkeypatch.setattr(pipeline_ui, "_write_json_atomic", fail_after_registry)
    with pytest.raises(OSError):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            decision="APPROVE", reviewer="검토자", note="대체",
            registration_mode="REPLACE", replace_tc_ids=["TC-TEMP-001"],
            comparison_sha256=comparison["fingerprint"])
    assert not (assets / "registry.json").exists()
    assert not list(assets.rglob("*.json"))


def test_tc_comparison_browser_http_replace_and_decline(tmp_path, monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from playwright.sync_api import sync_playwright, expect
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    target.write_bytes((REPO_ROOT / "product_baseline/virtual-controller.html").read_bytes())
    result_file = runs / run_id / "validation_execution.json"
    validation = json.loads(result_file.read_text(encoding="utf-8"))
    validation["candidate_results"][0]["target_sha256"] = _sha256_file(target)
    _write_json(result_file, validation)
    bridge = pipeline_ui.PipelineUiBridge(runs_root=runs, requests_root=tmp_path,
        target_html=target, allow_live_run=False, allow_asset_approval=True,
        approved_assets_root=assets, srs_path=tmp_path / "srs.md")
    server = ThreadingHTTPServer(("127.0.0.1", 0), pipeline_ui.make_handler(bridge))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.goto(origin, wait_until="domcontentloaded")
            page.wait_for_function("qaLiveState.run !== null")
            page.evaluate("openQaLiveModal('agent4')")
            expect(page.locator("#qa-live-tc-comparison")).to_be_visible()
            page.locator("#qa-live-reviewer").fill("시험 검토자")
            page.locator("#qa-live-approval-note").fill("기존 TC와 비교한 사람 판단")
            page.locator("#qa-live-decline-btn").click()
            expect(page.locator("#qa-live-approval-status")).to_contain_text("등록하지 않음")
            assert not (assets / "registry.json").exists()
            page.locator("#qa-live-registration-mode").select_option("REPLACE")
            page.locator("#qa-live-approve-btn").click()
            expect(page.locator("#qa-live-approval-status")).to_contain_text("직접 선택")
            page.get_by_text("다른 TC·대체 이력도 보기", exact=True).click()
            # All controls are available; relatedness is not an automatic deletion decision.
            page.locator("summary").filter(has_text="TC-TEMP-001 ·").click()
            page.locator('.qa-tc-replacement[value="TC-TEMP-001"]').check()
            page.locator("#qa-live-approve-btn").click()
            expect(page.locator("#qa-live-approval-status")).to_contain_text("대체 대상: TC-TEMP-001")
            assert not (assets / "registry.json").exists()
            evidence = REPO_ROOT / "runs/asset-comparison-20261004"
            evidence.mkdir(parents=True, exist_ok=True)
            page.locator("#qa-live-tc-comparison").screenshot(path=str(evidence / "comparison.png"))
            page.locator("#qa-live-approve-btn").click()
            expect(page.locator("#qa-live-approval-status")).to_contain_text("등록 완료")
            registry = json.loads((assets / "registry.json").read_text(encoding="utf-8"))
            assert registry["supersessions"][0]["tc_id"] == "TC-TEMP-001"
            assert registry["supersessions"][0]["replaced_by"] == "TC-V2-001"
            expect(page.locator("#qa-live-decline-btn")).to_be_disabled()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


@pytest.mark.parametrize('mutation,expected', [('none', None), ('precondition', '사전조건'), ('sequence', '조작·복원 순서')])
def test_approval_recheck_distinguishes_sequence_from_precondition(tmp_path, monkeypatch, mutation, expected):
    # Isolate diagnostic routing; source/hash checks are tested independently.
    import qa_pipeline_agent2 as a2
    case, plan, observation = precondition_guard_fixture()
    request, analysis, requirements = cp1_combined_srs_case()
    design = cp2_valid_design().model_copy(update={'test_cases': [case]})
    if mutation == 'precondition': plan.precondition_checks = []
    elif mutation == 'sequence':
        next(a for a in plan.actions if a.phase == pipeline.AutomationPhase.TEST).source_text = 'not in TC'
    run = tmp_path / 'RUN-20260924-000000-ABCDEF'
    folder = run / 'agent3_candidates' / case.tc_id
    _write_json(folder / 'agent3_manifest.json', {})
    _write_json(folder / 'agent3_automation_plan.json', plan.model_dump(mode='json'))
    _write_json(folder / 'agent3_ui_observation.json', observation.model_dump(mode='json'))
    monkeypatch.setattr(pipeline_reporting, '_verify_final_report_sources', lambda *_: None)
    monkeypatch.setattr(pipeline_execution, '_load_verified_agent2_run', lambda *_: (request, requirements, analysis, design, None, pipeline_execution._current_agent2_contract()))
    monkeypatch.setattr(pipeline_execution, '_verify_sha256', lambda *_: None)
    def no_duplicate_cp2(*args, **kwargs):
        raise AssertionError('The verified Agent 2 loader owns the complete CP2 recheck')
    monkeypatch.setattr(a2, 'evaluate_checkpoint2', no_duplicate_cp2)
    if expected:
        with pytest.raises(ValueError, match=expected):
            pipeline_ui._verify_candidate_sources(run, case.tc_id)
    else:
        pipeline_ui._verify_candidate_sources(run, case.tc_id)


def test_approval_propagates_common_agent2_verification_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_reporting, '_verify_final_report_sources', lambda *_: None)
    def reject(*args):
        raise ValueError('source verification rejected')
    monkeypatch.setattr(pipeline_execution, '_load_verified_agent2_run', reject)
    with pytest.raises(ValueError, match='source verification rejected'):
        pipeline_ui._verify_candidate_sources(tmp_path / 'RUN', 'TC-CAND-001')


def test_old_approval_keeps_extra_expectation_guard(tmp_path, monkeypatch):
    import qa_pipeline_agent2 as a2
    request, analysis, requirements = cp1_combined_srs_case()
    monkeypatch.setattr(pipeline_reporting, '_verify_final_report_sources', lambda *_: None)
    monkeypatch.setattr(pipeline_execution, '_load_verified_agent2_run',
        lambda *_: (request, requirements, analysis, cp2_valid_design(), None, {}))
    monkeypatch.setattr(a2, 'evaluate_checkpoint2', lambda *a, **k: pipeline.Checkpoint2Result(
        status=CheckStatus.FAIL, checks=[pipeline.CheckResult(rule_id='CP2-017', status=CheckStatus.FAIL, message='legacy guard')]))
    with pytest.raises(ValueError, match='기대 결과가 현재 요구사항'):
        pipeline_ui._verify_candidate_sources(tmp_path / 'RUN', 'TC-CAND-001')


@pytest.mark.parametrize('new_policy', [False, True, 'output_tolerance', 'task_boundaries', 'value_roles', 'shared_evidence', 'scenario_review', 'terminal_observation', 'product_verdict', 'execution_interface'])
@pytest.mark.parametrize('review_state', ['valid', 'missing', 'tampered'])
def test_approval_reconstructs_same_agent3_review_policy(tmp_path, monkeypatch, new_policy, review_state):
    import qa_pipeline_grounding as grounding
    case, plan, observation = precondition_guard_fixture()
    request, analysis, requirements = cp1_combined_srs_case()
    design = cp2_valid_design().model_copy(update={'test_cases': [case]})
    run = tmp_path / 'RUN-20260924-000000-ABCDEF'
    folder = run / 'agent3_candidates' / case.tc_id
    manifest = {'contract_version': '4.10', 'grounding_contract': '1.0',
        'wording_policy': 'STRUCTURAL_ONLY_V1',
        'prompt_version': 'agent3-3.36' if new_policy else 'agent3-3.35'}
    if new_policy:
        manifest['review_responsibility_contract'] = '1.0'
    if new_policy in {'output_tolerance', 'task_boundaries', 'value_roles', 'shared_evidence', 'scenario_review', 'terminal_observation', 'product_verdict', 'execution_interface'}:
        manifest['output_tolerance_contract'] = '1.0'
    if new_policy == 'task_boundaries':
        manifest['prompt_version'] = 'agent3-3.37'
        manifest['task_boundary_contract'] = '1.0'
    elif new_policy == 'value_roles':
        manifest['prompt_version'] = 'agent3-3.38'
        manifest['task_boundary_contract'] = '1.1'
    elif new_policy == 'shared_evidence':
        manifest['prompt_version'] = 'agent3-3.39'
        manifest['task_boundary_contract'] = '1.2'
    elif new_policy == 'scenario_review':
        manifest['prompt_version'] = 'agent3-3.40'
        manifest['task_boundary_contract'] = '1.3'
    elif new_policy in {'terminal_observation', 'product_verdict', 'execution_interface'}:
        manifest['prompt_version'] = 'agent3-3.42' if new_policy == 'product_verdict' else 'agent3-3.41'
        manifest['task_boundary_contract'] = '1.3'
        manifest['terminal_observation_contract'] = '1.0'
        if new_policy in {'product_verdict', 'execution_interface'}:
            manifest['product_verdict_contract'] = '1.0'
        if new_policy == 'execution_interface':
            manifest['prompt_version'] = 'agent3-3.45'
            manifest['execution_interface_contract'] = '1.0'
    payload = grounding.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=observation,
        include_execution_contract=True, include_review_responsibilities=bool(new_policy),
        allow_output_tolerance=bool(manifest.get('output_tolerance_contract')),
        include_task_boundaries=manifest.get('task_boundary_contract', False),
        allow_state_change_terminal_observation=new_policy in {'terminal_observation', 'product_verdict', 'execution_interface'},
        explicit_expectations_only=new_policy in {'product_verdict', 'execution_interface'},
        execution_interface=new_policy == 'execution_interface')
    _write_json(folder / 'agent3_manifest.json', manifest)
    _write_json(folder / 'agent3_automation_plan.json', plan.model_dump(mode='json'))
    _write_json(folder / 'agent3_ui_observation.json', observation.model_dump(mode='json'))
    if review_state != 'missing':
        record = fake_grounding_record(payload)
        if new_policy == 'output_tolerance':
            record['review']['items'].reverse()
        if review_state == 'tampered':
            record['input_sha256'] = '0' * 64
        _write_json(folder / 'agent3_grounding_review.json', record)
    monkeypatch.setattr(pipeline_reporting, '_verify_final_report_sources', lambda *_: None)
    monkeypatch.setattr(pipeline_execution, '_load_verified_agent2_run', lambda *_: (request, requirements, analysis, design, None, pipeline_execution._current_agent2_contract()))
    monkeypatch.setattr(pipeline_execution, '_verify_sha256', lambda *_: None)
    # The payload/hash test alone would miss stale CP3 flags if that particular
    # fixture happened to pass both rulesets. Check the selected policy too.
    import qa_pipeline_agent3 as a3
    evaluate = a3.evaluate_checkpoint3_plan
    selected = []
    def capture_policy(*args, **kwargs):
        selected.append((kwargs['review_value_roles'], kwargs['shared_evidence'], kwargs['allow_state_change_terminal_observation'], kwargs['execution_interface']))
        return evaluate(*args, **kwargs)
    monkeypatch.setattr(a3, 'evaluate_checkpoint3_plan', capture_policy)
    if review_state != 'valid':
        with pytest.raises(ValueError, match='필수 모델 근거 검토' if review_state == 'missing' else '해시'):
            pipeline_ui._verify_candidate_sources(run, case.tc_id)
    else:
        pipeline_ui._verify_candidate_sources(run, case.tc_id)
    assert selected == [(new_policy in {'value_roles', 'shared_evidence', 'scenario_review', 'terminal_observation', 'product_verdict', 'execution_interface'},
                         new_policy in {'shared_evidence', 'scenario_review', 'terminal_observation', 'product_verdict', 'execution_interface'},
                         new_policy in {'terminal_observation', 'product_verdict', 'execution_interface'}, new_policy == 'execution_interface')]


@pytest.mark.parametrize('value,required,limit', [(None, False, 10), (' ', True, 10), ('long', False, 2)])
def test_ui_text_guards_reject_invalid_input(value, required, limit):
    with pytest.raises(ValueError):
        pipeline_ui._safe_text(value, field_name='field', required=required, limit=limit)

@pytest.mark.parametrize("ending", [b"\n", b"\r\n"])
def test_git_preserves_approved_asset_bytes(ending):
    import subprocess
    payload = ending.join([b"# approved evidence", b"assert True", b""])
    raw = subprocess.run(["git", "hash-object", "--no-filters", "--stdin"],
        input=payload, cwd=REPO_ROOT, check=True, capture_output=True).stdout
    filtered = subprocess.run(["git", "hash-object", "--path=approved_assets/automation/test_integrity.py", "--stdin"],
        input=payload, cwd=REPO_ROOT, check=True, capture_output=True).stdout
    assert filtered == raw


@pytest.mark.parametrize("operation", ["revalidate", "decision"])
@pytest.mark.parametrize("failed", [False, True])
def test_browser_ignores_previous_run_post_response(operation, failed):
    from playwright.sync_api import sync_playwright
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("https://**/*", lambda route: route.abort())
        page.goto((REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
        page.wait_for_function("qaLiveState.demoMode && qaLiveState.run !== null")
        result = page.evaluate("""async ({operation,failed}) => {
          const first=structuredClone(qaLiveState.run);first.run_id='A';
          const second=structuredClone(first);second.run_id='B';
          qaLiveState.demoMode=false;qaLiveState.run=first;
          qaLiveState.overview={allow_asset_approval:true};renderQaLiveRun();
          document.getElementById('qa-live-reviewer').value='tester';
          document.getElementById('qa-live-approval-note').value='hold for review';
          let resolve,reject;qaLiveFetch=()=>new Promise((ok,bad)=>{resolve=ok;reject=bad;});
          const pending=operation==='revalidate'?revalidateQaAsset():submitQaAssetDecision('HOLD');
          ++qaLiveState.loadSequence;qaLiveState.run=second;renderQaLiveRun();
          const status=document.getElementById('qa-live-approval-status').textContent;
          if(failed)reject(Error('old error'));else resolve({run:first});
          await pending;
          return {id:qaLiveState.run.run_id,unchanged:status===document.getElementById('qa-live-approval-status').textContent};
        }""", {"operation": operation, "failed": failed})
        assert result == {"id": "B", "unchanged": True}
        browser.close()


def test_shared_lock_rejects_overlapping_thread_and_is_reusable(tmp_path):
    import threading
    lock = pipeline_ui.LiveRunFileLock(tmp_path / "approval.lock")
    assert lock.acquire()
    acquired = []
    thread = threading.Thread(target=lambda: acquired.append(lock.acquire()))
    thread.start()
    thread.join(timeout=3)
    assert not thread.is_alive() and acquired == [False]
    lock.release()
    assert lock.acquire()
    lock.release()


def test_approval_rejects_unverified_pass_labels(tmp_path):
    # Deliberately do not use the UI transaction fixture's source-verification stub.
    run = tmp_path / "RUN-20260912-120000-ABCDEF"
    _write_json(run / "final_report.json", {"recommendation": "PASS"})
    with pytest.raises(ValueError):
        pipeline_ui._verify_candidate_sources(run, "TC-CAND-001")


@pytest.mark.parametrize("origin,host,content_type,status", [
    ("http://127.0.0.1:8765", "127.0.0.1:8765", "application/json", 202),
    ("https://untrusted.example", "127.0.0.1:8765", "application/json", 403),
    ("null", "127.0.0.1:8765", "application/json", 403),
    (None, "127.0.0.1:8765", "application/json", 403),
    ("http://attacker.example:8765", "attacker.example:8765", "application/json", 403),
    ("http://127.0.0.1:8765", "127.0.0.1:8765", "text/plain", 415),
])
def test_local_mutations_require_same_origin_json(origin, host, content_type, status):
    import io
    from email.message import Message
    calls, responses = [], []
    bridge = SimpleNamespace(start_live_run=lambda name: calls.append(name), overview=lambda: {})
    handler_type = pipeline_ui.make_handler(bridge)
    handler = handler_type.__new__(handler_type)
    handler.server = SimpleNamespace(server_address=("127.0.0.1", 8765))
    handler.path = "/api/qa/runs"
    handler.headers = Message()
    handler.headers["Host"] = host
    if origin is not None:
        handler.headers["Origin"] = origin
    handler.headers["Content-Type"] = content_type
    body = b'{"request_file":"fixture.json"}'
    handler.headers["Content-Length"] = str(len(body))
    handler.rfile = io.BytesIO(body)
    handler._send_json = lambda payload, code=200: responses.append(int(code))
    handler.do_POST()
    assert responses == [status]
    assert bool(calls) is (status == 202)


def test_ui_waits_for_final_report_before_overall_pass(tmp_path):
    run_id = "RUN-20260912-091420-ABCDEF"
    run = tmp_path / run_id
    for status in ("PASS", "COMPLETED", "SELECTED"):
        _write_json(run / "orchestrator_manifest.json", {"status": status})
        assert pipeline_ui.summarize_run(tmp_path, run_id)["overall_status"] == "후속 검증 대기"
    _write_json(run / "orchestrator_manifest.json", {"status": "STOPPED"})
    assert pipeline_ui.summarize_run(tmp_path, run_id)["overall_status"] == "STOPPED"
    _write_json(run / "final_report.json", {"recommendation": "HUMAN_REVIEW"})
    assert pipeline_ui.summarize_run(tmp_path, run_id)["overall_status"] == "HUMAN_REVIEW"


def test_asset_approval_rejects_different_executed_code(tmp_path, monkeypatch):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    execution_file = runs / run_id / "validation_execution.json"
    data = json.loads(execution_file.read_text(encoding="utf-8"))
    data["candidate_results"][0]["test_sha256"] = "a" * 64
    _write_json(execution_file, data)
    with pytest.raises(ValueError, match="해시"):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            decision="APPROVE", reviewer="테스트", note="검증")
    with pytest.raises(ValueError, match="코드가 다릅니다"):
        pipeline_ui.revalidate_candidate_asset(runs, target, run_id, tc_id)
    assert not (assets / "registry.json").exists()


def test_report_uses_verified_tc_snapshot_and_legacy_custom_root(tmp_path):
    _, snapshot = pipeline.load_approved_regression_catalog(REPO_ROOT / "approved_assets")
    entry = snapshot["approved_assets"][0]
    tc_id = entry["tc_id"]
    raw = entry["test_case_json"]
    expected = json.loads(raw)["test_case"]
    _write_json(tmp_path / "approved_regression_catalog.json", snapshot)
    _write_json(tmp_path / "agent2_test_design.json", {"related_existing_tests": [{"tc_id": tc_id}]})
    missing_root = tmp_path / "missing-assets"
    rows = pipeline_reporting.build_run_test_rows(tmp_path, approved_assets_root=missing_root)
    assert rows[0]["steps"] == expected["steps"]
    assert rows[0]["title"] == expected["title"]
    # Old Runs have no embedded source: use the explicitly configured folder.
    del entry["test_case_json"]
    legacy_file = missing_root / entry["test_case_file"]
    legacy_file.parent.mkdir(parents=True)
    legacy_file.write_bytes(raw.encode("utf-8"))
    _write_json(tmp_path / "approved_regression_catalog.json", snapshot)
    assert pipeline_reporting.build_run_test_rows(tmp_path, approved_assets_root=missing_root)[0]["steps"] == expected["steps"]
    entry["test_case_json"] = raw + " "  # Do not hide a damaged snapshot using current files.
    _write_json(tmp_path / "approved_regression_catalog.json", snapshot)
    assert pipeline_reporting.build_run_test_rows(tmp_path, approved_assets_root=missing_root)[0]["steps"] == []


def test_browser_resets_cross_run_consent_and_separates_timeouts():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        page.route("https://**/*", lambda route: route.abort())
        page.goto((REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
        result = page.evaluate("""async () => {
          qaLiveState.demoMode=false;
          const limits=[];const nativeTimeout=AbortSignal.timeout;
          AbortSignal.timeout=ms=>{limits.push(ms);return nativeTimeout(ms);};
          window.fetch=async()=>({ok:true,json:async()=>({})});
          await qaLiveFetch('/read');await qaLiveFetch('/revalidate',{method:'POST'});
          const asset={tc_id:'TC-CAND-001',title:'mock',approval_eligible:true,srs_revision_proposals:[{requirement_id:'REQ',current_acceptance_criteria:'old',proposed_acceptance_criteria:'new'}]};
          const first={run_id:'A',stages:{agent4:{name:'보고',status:'PASS',summary:'상세',details:Array(15).fill('검토 사항')}},candidate_assets:[asset]};
          const second={...first,run_id:'B'};
          qaLiveState.overview={allow_asset_approval:true};qaLiveState.run=first;qaLiveState.selectedStage='agent4';renderQaLiveRun();
          document.getElementById('qa-live-modal').classList.add('show');
          document.getElementById('qa-live-reviewer').value='검토자';
          document.getElementById('qa-live-srs-approve').checked=true;
          const sent=[];qaLiveFetch=async(path,options)=>{if(options?.method==='POST')sent.push(path);return second;};
          await submitQaAssetDecision('APPROVE');
          const armedBefore=qaLiveState.assetApprovalArmed;
          await loadQaLiveRun('B');
          const cleared=!qaLiveState.assetApprovalArmed && !document.getElementById('qa-live-srs-approve').checked;
          await submitQaAssetDecision('APPROVE');
          const list=document.getElementById('qa-live-detail-list').getBoundingClientRect();
          const table=document.querySelector('.qa-live-results').getBoundingClientRect();
          return {limits,armedBefore,cleared,sent,overlap:list.bottom>table.top};
        }""")
        assert result == dict(limits=[10000,180000], armedBefore=True, cleared=True, sent=[], overlap=False)
        browser.close()


def test_pipeline_ui_browser_recovers_polling_and_preserves_selected_run():
    from playwright.sync_api import sync_playwright
    html = (REPO_ROOT / "product_baseline/virtual-controller.html").read_text(encoding="utf-8")
    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page()
        page.route("**/*", lambda route: route.fulfill(status=200, content_type="text/html", body=html)
                   if route.request.url == "http://127.0.0.1:9998/" else route.abort())
        page.goto("http://127.0.0.1:9998/", wait_until="domcontentloaded")
        page.wait_for_function("document.getElementById('qa-live-connection').textContent.includes('상태 확인 불가')")
        assert page.evaluate("qaLiveState.connected")  # HTTP 장애는 고정 데모로 대체하지 않음
        result = page.evaluate("""async () => {
          clearTimeout(qaLiveState.pollTimer); qaLiveState.pollTimer=null;
          let calls=0, fail=false;
          const state={running:true, allow_live_run:true, phase:'AGENT_1_TO_3', message:'running', run_id:'NEW', latest_run_id:'NEW'};
          qaLiveFetch=async path=>{calls++; if(fail)throw Error('temporary');
            if(path.endsWith('/state'))return state;
            if(path.endsWith('/requests'))return {requests:[]};
            return {runs:['NEW','OLD']};};
          const originalLoad=loadQaLiveRun;
          loadQaLiveRun=async ()=>{};
          await initQaLiveBridge();
          const initPoll=!!qaLiveState.pollTimer;
          closeQaLiveModal();
          const closedPoll=!!qaLiveState.pollTimer;
          document.getElementById('qa-live-run-select').value='OLD';
          await refreshQaLiveData();
          const selected=document.getElementById('qa-live-run-select').value;
          fail=true;
          clearTimeout(qaLiveState.pollTimer);qaLiveState.pollTimer=null;
          await refreshQaLiveData();
          const retry=!!qaLiveState.pollTimer;
          const disabled=document.getElementById('qa-live-start-btn').disabled;
          fail=false;state.running=false;state.phase='COMPLETED';
          await new Promise(resolve=>setTimeout(resolve,1700));
          const recovered=qaLiveState.overview.phase==='COMPLETED' && !document.getElementById('qa-live-start-btn').disabled;
          loadQaLiveRun=originalLoad;
          let resolveOld;
          qaLiveFetch=path=>path.endsWith('/OLD') ? new Promise(resolve=>resolveOld=resolve) : Promise.resolve({run_id:'NEW'});
          renderQaLiveRun=()=>{};
          const old=loadQaLiveRun('OLD');await loadQaLiveRun('NEW');
          resolveOld({run_id:'OLD'});await old;
          return {initPoll,closedPoll,selected,retry,disabled,recovered,lastRun:qaLiveState.run.run_id};
        }""")
        assert result == dict(initPoll=True, closedPoll=True, selected="OLD", retry=True,
                              disabled=True, recovered=True, lastRun="NEW")
        browser.close()


def test_public_demo_shows_one_v2_normal_change_without_api_or_file_registration():
    from playwright.sync_api import sync_playwright

    with sync_playwright() as api:
        browser = api.chromium.launch(headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 1100})
        page_errors: list[str] = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("https://**/*", lambda route: route.abort())
        page.goto((REPO_ROOT / "product_baseline/virtual-controller.html").as_uri(), wait_until="domcontentloaded")
        page.wait_for_function("qaLiveState.demoMode && qaLiveState.run !== null")
        result = page.evaluate("""async () => {
          let fetchCalls=0;
          window.fetch=async()=>{fetchCalls++;throw Error('공개 데모는 API를 호출하면 안 됩니다.');};
          const stageStatuses=Object.fromEntries(
            Object.entries(qaLiveState.run.stages).map(([key,value])=>[key,value.status])
          );
          const rows=qaLiveState.run.test_rows.map(row=>({id:row.tc_id,category:row.category,status:row.status}));
          const visited=[];
          for(const [id,stage] of [['agent-1-btn','agent1'],['agent-2-btn','agent2'],['agent-3-btn','agent3'],['agent-4-btn','agent4'],['agent-lead-btn','overview']]){
            document.getElementById(id).click();visited.push(qaLiveState.selectedStage);closeQaLiveModal();
          }
          openQaLiveModal('agent2');
          const agent2Title=document.getElementById('qa-live-detail-title').textContent;
          openQaLiveModal('agent4');
          document.getElementById('qa-live-reviewer').value='포트폴리오 방문자';
          document.getElementById('qa-live-approval-note').value='정상 변경 결과 확인';
          document.getElementById('qa-live-srs-approve').checked=true;
          await submitQaAssetDecision('APPROVE');
          const firstClickArmed=qaLiveState.assetApprovalArmed;
          await submitQaAssetDecision('APPROVE');
          return {
            title:document.getElementById('qa-live-title').textContent,
            description:qaLiveState.run.description,
            requirementIds:[
              qaLiveState.run.target_requirement_id,
              ...qaLiveState.run.test_rows.flatMap(row=>row.requirement_ids),
              qaLiveState.run.candidate_assets[0].srs_revision_proposals[0].requirement_id
            ],
            stageStatuses,rows,visited,agent2Title,firstClickArmed,fetchCalls,
            decision:qaLiveState.run.candidate_assets[0].decision.decision,
            agent4DecisionDetail:qaLiveState.run.stages.agent4.details.at(-1),
            approvalStatus:document.getElementById('qa-live-approval-status').textContent,
            message:document.getElementById('qa-live-message').textContent,
            startDisabled:document.getElementById('qa-live-start-btn').disabled,
            startLabel:document.getElementById('qa-live-start-btn').textContent
          };
        }""")
        assert result["title"] == "✅ QA Pipeline V2 정상 변경 데모"
        assert "중풍" in result["description"] and "MED" in result["description"]
        assert set(result["requirementIds"]) == {"REQ-FAN-001"}
        assert result["stageStatuses"] == {
            "agent1": "PASS", "agent2": "PASS", "agent3": "COMPLETED", "agent4": "PASS"
        }
        assert result["rows"] == [
            {"id": "TC-ENV-000", "category": "사전 점검", "status": "PASSED"},
            {"id": "TC-CAND-001", "category": "정상 변경", "status": "PASSED"},
        ]
        assert result["visited"] == ["agent1", "agent2", "agent3", "agent4", "overview"]
        assert result["agent2Title"].startswith("Agent 2 · TC 설계")
        assert result["firstClickArmed"] is True
        assert result["fetchCalls"] == 0
        assert result["decision"] == "APPROVED"
        assert result["agent4DecisionDetail"] == "후보 TC·SRS 승인 미리보기 완료 · 실제 자산 미반영"
        assert "실제 SRS·TC 파일은 변경되지 않았습니다" in result["approvalStatus"]
        assert "실제 SRS·TC·자동화 파일은 변경하지 않았습니다" in result["message"]
        assert result["startDisabled"] is True
        assert result["startLabel"] == "실제 실행은 로컬에서 사용"
        assert page_errors == []
        browser.close()


def test_existing_srs_approval_requires_consent_and_creates_no_tc(tmp_path, monkeypatch):
    run_dir, target, srs = build_existing_srs_review_run(tmp_path, monkeypatch)
    assets = tmp_path / "approved"
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=run_dir.parent, requests_root=tmp_path, target_html=target,
        allow_live_run=False, allow_asset_approval=False, approved_assets_root=assets, srs_path=srs,
    )
    kwargs = dict(decision="APPROVE", reviewer="검토자", note="기존 TC 절차와 SRS 확인")
    with pytest.raises(PermissionError):
        bridge.decide_asset(run_dir.name, "SRS_ONLY", **kwargs, approve_srs_revisions=True)
    bridge.state.allow_asset_approval = True
    with pytest.raises(ValueError, match="반영 승인"):
        bridge.decide_asset(run_dir.name, "SRS_ONLY", **kwargs)
    held = bridge.decide_asset(run_dir.name, "SRS_ONLY", **{**kwargs, "decision": "HOLD"})
    assert held["decision"] == "HELD" and "기존 기준" in srs.read_text(encoding="utf-8")
    record = bridge.decide_asset(run_dir.name, "SRS_ONLY", **kwargs, approve_srs_revisions=True)
    assert record["decision"] == "APPROVED" and "변경 기준" in srs.read_text(encoding="utf-8")
    assert not (assets / "registry.json").exists() and not (assets / "test_cases").exists()
    assert bridge.decide_asset(run_dir.name, "SRS_ONLY", **kwargs, approve_srs_revisions=True) == record
    assert pipeline_ui.summarize_run(run_dir.parent, run_dir.name, target_html=target)["srs_revision_asset"]["decision"] == record


@pytest.mark.parametrize("damage", ["target", "evidence", "proposal", "srs"])
def test_existing_srs_approval_rejects_changed_inputs(tmp_path, monkeypatch, damage):
    run_dir, target, srs = build_existing_srs_review_run(tmp_path, monkeypatch)
    if damage == "target":
        target.write_text("changed", encoding="utf-8")
    elif damage == "srs":
        srs.write_text("| REQ-TEMP-001 | 온도 요구사항 | 다른 기준 |\n", encoding="utf-8")
    elif damage == "proposal":
        report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
        report["SRS_개정_제안"][0]["proposed_acceptance_criteria"] = "임의 기준"
        _write_json(run_dir / "final_report.json", report)
    else:
        result = json.loads((run_dir / "validation_execution.json").read_text(encoding="utf-8"))
        (run_dir / result["regression_results"][0]["stdout_file"]).write_text("changed", encoding="utf-8")
    before = srs.read_bytes()
    with pytest.raises(ValueError):
        pipeline_ui.decide_existing_srs(run_dir.parent, tmp_path / "approved", target, run_dir.name,
            srs_path=srs, decision="APPROVE", reviewer="검토자", note="확인", approve_srs_revisions=True)
    assert srs.read_bytes() == before
    assert not (run_dir / "srs_only_decision.json").exists()


@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt, SystemExit])
def test_existing_srs_approval_rolls_back_on_record_failure(tmp_path, monkeypatch, failure):
    run_dir, target, srs = build_existing_srs_review_run(tmp_path, monkeypatch)
    before = srs.read_bytes()
    original = pipeline_ui._write_json_atomic
    def fail_record(path, payload):
        if path.name == "srs_only_decision.json":
            raise failure("record write failed")
        original(path, payload)
    monkeypatch.setattr(pipeline_ui, "_write_json_atomic", fail_record)
    assets = tmp_path / "approved"
    with pytest.raises(failure):
        pipeline_ui.decide_existing_srs(run_dir.parent, assets, target, run_dir.name,
            srs_path=srs, decision="APPROVE", reviewer="검토자", note="확인", approve_srs_revisions=True)
    assert srs.read_bytes() == before
    assert not (assets / "srs_revisions" / f"{run_dir.name}.json").exists()


def test_existing_srs_approval_works_through_browser_and_http(tmp_path, monkeypatch):
    import threading
    from http.server import ThreadingHTTPServer
    from playwright.sync_api import sync_playwright, expect
    html = (REPO_ROOT / "product_baseline" / "virtual-controller.html").read_text(encoding="utf-8")
    run_dir, target, srs = build_existing_srs_review_run(tmp_path, monkeypatch, target_content=html)
    assets = tmp_path / "approved"
    bridge = pipeline_ui.PipelineUiBridge(runs_root=run_dir.parent, requests_root=tmp_path,
        target_html=target, allow_live_run=False, allow_asset_approval=True,
        approved_assets_root=assets, srs_path=srs)
    server = ThreadingHTTPServer(("127.0.0.1", 0), pipeline_ui.make_handler(bridge))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    try:
        with sync_playwright() as api:
            browser = api.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1440, "height": 1100})
            page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(origin + "/") else route.abort())
            page.goto(origin, wait_until="domcontentloaded")
            page.wait_for_function("qaLiveState.run !== null")
            page.evaluate("openQaLiveModal('agent4')")
            expect(page.locator("#qa-live-candidate-select")).to_have_value("SRS_ONLY")
            page.locator("#qa-live-reviewer").fill("테스트 검토자")
            page.locator("#qa-live-approval-note").fill("문구와 기존 TC 절차 확인")
            page.locator("#qa-live-srs-approve").check()
            page.locator("#qa-live-approve-btn").click()
            assert "기존 기준" in srs.read_text(encoding="utf-8")
            page.locator("#qa-live-approve-btn").click()
            expect(page.locator("#qa-live-approval-status")).to_contain_text("등록 완료: SRS 문서 개정")
            expect(page.locator("#qa-live-approve-btn")).to_be_disabled()
            assert "변경 기준" in srs.read_text(encoding="utf-8")
            assert not (assets / "test_cases").exists()
            page.screenshot(path=str(tmp_path / "srs-approval-ui.png"), full_page=True)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_run_test_rows_keep_design_type_failure_reason_and_manual_exclusions_separate(tmp_path: Path) -> None:
    _write_json(tmp_path / "agent2_test_design.json", {
        "test_cases": [
            {"tc_id": "TC-CAND-001", "test_type": "NORMAL", "title": "정상 표시 검증",
             "automation_candidate": True, "preconditions": ["장비 선택"],
             "steps": ["설정 적용"], "expected_results": [{"statement": "새 값 표시"}],
             "restore_steps": ["초기값 복원"]},
            {"tc_id": "TC-CAND-002", "test_type": "BOUNDARY", "title": "수동 확인",
             "automation_candidate": False, "automation_reason": "외부 장비 확인 필요"},
        ], "관련_기존_TC": [{"tc_id": "TC-TEMP-001"}],
    })
    _write_json(tmp_path / "validation_execution.json", {
        "created_at": "2026-09-06T00:00:00Z",
        "candidate_results": [{"test_id": "TC-CAND-001", "status": "ASSERTION_FAILED"}],
        "environment_precheck": {"test_id": "TC-ENV-000", "status": "PASSED"},
        "자동화_제외_TC": [{"tc_id": "TC-CAND-002", "reason": "외부 장비 확인 필요"}],
    })
    _write_json(tmp_path / "final_report.json", {
        "검토_항목": [{"test_id": "TC-CAND-001", "category": "PRODUCT_MISMATCH_CANDIDATE",
                     "rationale": "표시가 기대와 다름"}],
    })
    rows = {row["tc_id"]: row for row in pipeline_reporting.build_run_test_rows(tmp_path)}
    failed, manual, existing = rows["TC-CAND-001"], rows["TC-CAND-002"], rows["TC-TEMP-001"]
    assert failed["category"] == "해피패스"  # 실패했다고 예외 TC로 바꾸지 않음
    assert failed["classification"] == "제품 동작 불일치 후보"
    assert failed["steps"] == ["설정 적용"] and failed["expected_results"] == ["새 값 표시"]
    assert failed["priority"] == "미지정"
    assert manual["status"] == "MANUAL_REVIEW" and manual["executed_at"] is None
    assert manual["reason"] == "외부 장비 확인 필요"
    assert existing["status"] == "NOT_EXECUTED" and existing["steps"] == []
    assert rows["TC-ENV-000"]["category"] == "사전 점검"


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

@pytest.mark.parametrize("item,expected", [
    ({"test_id": "TC-CAND-001", "category": "PRODUCT_MISMATCH_CANDIDATE",
      "rationale": "기대 결과와 관찰 결과가 다릅니다. 결함 확정은 아닙니다.",
      "evidence_files": ["evidence/trial-stdout.txt"]},
     "TC-CAND-001 · 기대 결과와 관찰 결과가 다릅니다. 결함 확정은 아닙니다."),
    ("기존 사람 확인 문장", "기존 사람 확인 문장"),
    ({"finding_id": "FIND-002", "category": "UNCLASSIFIED"}, "FIND-002 · UNCLASSIFIED"),
    ({}, "검토 근거가 기록되지 않았습니다."),
])
def test_ui_review_item_preserves_rationale_without_raw_json(item, expected):
    assert pipeline_ui._review_item_text(item) == expected


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
    assert "최종 권고 PASS" in summary["stages"]["agent4"]["summary"]
    assert "외부 보고 DRY_RUN" in summary["stages"]["agent4"]["summary"]
    assert "Slack: PREVIEW / Notion: PREVIEW" in summary["stages"]["agent4"]["details"]

def test_pipeline_ui_human_approval_registers_immutable_tc_and_automation(
    tmp_path: Path, monkeypatch,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, candidate_code = (
        build_approvable_ui_run(tmp_path, monkeypatch)
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
    snapshot_asset = snapshot["approved_assets"][0]
    assert snapshot_asset["automation_sha256"] == spec.automation_sha256
    registry = json.loads((approved_root / "registry.json").read_text(encoding="utf-8"))
    asset = registry["assets"][0]
    provenance_file = approved_root / asset["approval_revalidation_file"]
    provenance = json.loads(provenance_file.read_text(encoding="utf-8"))
    assert provenance_file.is_file()
    assert _sha256_file(provenance_file) == asset["approval_revalidation_sha256"]
    assert provenance["source_revalidation_sha256"] == asset["source_revalidation_sha256"]
    assert all(
        "/" not in name and "\\" not in name
        for name in provenance["evidence_sha256"]
    )

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

def test_pipeline_ui_shows_latest_delivery_and_preserves_prior_send_history(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_id = "RUN-20260904-120000-ABCDEF"
    run_dir = runs_root / run_id
    _write_json(run_dir / "final_report.json", {"recommendation": "PASS"})
    preview = {"mode": "DRY_RUN", "slack": {"status": "PREVIEW"}, "notion": {"status": "PREVIEW"}}
    _write_json(run_dir / "external_reporting.json", preview)
    original = (run_dir / "external_reporting.json").read_bytes()
    attempts = run_dir / "external_reporting_attempts"
    _write_json(attempts / "ATTEMPT-20260904-120001-000000-ABCDEF" / "external_reporting.json", {
        "attempt_id": "ATTEMPT-20260904-120001-000000-ABCDEF",
        "mode": "SEND", "slack": {"status": "SENT"}, "notion": {"status": "FAILED"},
    })
    stage = pipeline_ui.summarize_run(runs_root, run_id)["stages"]["agent4"]
    assert "최종 권고 PASS" in stage["summary"] and "외부 보고 SEND" in stage["summary"]
    assert "Slack: SENT / Notion: FAILED" in stage["details"]

    _write_json(attempts / "ATTEMPT-20260904-120002-000000-ABCDEF" / "external_reporting.json", preview)
    stage = pipeline_ui.summarize_run(runs_root, run_id)["stages"]["agent4"]
    assert "최종 권고 PASS" in stage["summary"] and "외부 보고 DRY_RUN" in stage["summary"]
    assert "Slack: PREVIEW / Notion: PREVIEW" in stage["details"]
    assert any("이전 전송" in item and "Slack SENT / Notion FAILED" in item for item in stage["details"])
    assert (run_dir / "external_reporting.json").read_bytes() == original


def test_pipeline_ui_requires_and_applies_srs_revision_with_asset_approval(
    tmp_path: Path, monkeypatch,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path, monkeypatch
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

    candidates = pipeline_ui.summarize_run(runs_root, run_id, target_html=target_html)["candidate_assets"]
    displayed_proposals = next(item for item in candidates if item["tc_id"] == tc_id)["srs_revision_proposals"]
    assert [item["proposal_id"] for item in displayed_proposals] == ["SRS-REV-001"]

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

@pytest.mark.parametrize("failure", [OSError, KeyboardInterrupt, SystemExit])
def test_pipeline_ui_rolls_back_all_asset_files_when_approval_copy_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path, monkeypatch
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
        raise failure("simulated copy failure")

    monkeypatch.setattr(pipeline_ui.shutil, "copy2", fail_after_partial_copy)

    with pytest.raises(failure, match="simulated copy failure"):
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
    assert not (approved_root / "provenance" / "TC-V2-001-revalidation-summary.json").exists()
    assert not (runs_root / run_id / "srs_revision_decision.json").exists()
    assert not (runs_root / run_id / "asset_decisions.json").exists()

def test_pipeline_ui_hold_is_recorded_and_can_later_be_approved(tmp_path: Path, monkeypatch) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path, monkeypatch
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
    tmp_path: Path, monkeypatch,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path, monkeypatch
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

@pytest.mark.parametrize("target_changed", [False, True])
def test_pipeline_ui_revalidates_stale_candidate_without_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_changed
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path, monkeypatch
    )
    if target_changed:
        target_html.write_text("<!doctype html><title>UI updated</title>", encoding="utf-8")

    def fake_trial(code_file, current_target, evidence_dir, *, timeout_seconds):
        _, _, _, reasons = pipeline_ui._candidate_approval_check(
            runs_root / run_id, tc_id, target_html=target_html)
        assert reasons, "Approval must be blocked while the retry is unfinished"
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
    registry = json.loads((approved_root / "registry.json").read_text(encoding="utf-8"))
    asset = registry["assets"][0]
    provenance_file = approved_root / asset["approval_revalidation_file"]
    provenance = json.loads(provenance_file.read_text(encoding="utf-8"))

    assert record["outcome"] == "PASS"
    assert record["target_sha256"] == _sha256_file(target_html)
    assert summary["candidate_assets"][0]["approval_eligible"] is True
    assert summary["candidate_assets"][0]["revalidation_required"] is False
    assert approved["source_revalidation_sha256"] == _sha256_file(latest)
    assert approved["approval_revalidation_sha256"] == _sha256_file(provenance_file)
    assert provenance["source_revalidation_sha256"] == _sha256_file(latest)
    assert provenance["evidence_sha256"] == {
        Path(path).name: digest
        for path, digest in record["evidence_sha256"].items()
    }

@pytest.mark.parametrize("target_changed", [False, True])
@pytest.mark.parametrize("outcome,complete", [
    ("PRODUCT_MISMATCH_CANDIDATE", True), ("AUTOMATION_ERROR", False),
    ("TIMEOUT", False), ("PASS", False),
])
def test_latest_failed_revalidation_blocks_old_pass(tmp_path, monkeypatch, target_changed, outcome, complete):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    if target_changed:
        target.write_text("<html>changed</html>", encoding="utf-8")
    def trial(code, html, evidence_dir, *, timeout_seconds):
        return pipeline.Agent3TrialResult(outcome=pipeline.TrialOutcome(outcome),
            exit_code=None if outcome == "TIMEOUT" else 0 if outcome == "PASS" else 1,
            duration_ms=1, stdout_file="stdout.txt", stderr_file="stderr.txt", evidence_complete=complete)
    monkeypatch.setattr(pipeline, "run_candidate_trial", trial)
    with pytest.raises(ValueError, match="공식 등록 조건"):
        pipeline_ui.revalidate_candidate_asset(runs, target, run_id, tc_id)
    latest = json.loads((runs / run_id / "asset_revalidation" / tc_id / "latest.json").read_text(encoding="utf-8"))
    assert latest["outcome"] == outcome
    _, _, _, reasons = pipeline_ui._candidate_approval_check(runs / run_id, tc_id, target_html=target)
    assert reasons, "A failed current retry must supersede the original PASS"
    with pytest.raises(ValueError):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            decision="APPROVE", reviewer="검토자", note="실패 재시험 차단 확인")
    assert not (assets / "registry.json").exists()


@pytest.mark.parametrize("changed", ["target", "candidate"])
def test_pipeline_ui_revalidation_rejects_files_changed_during_trial(tmp_path, monkeypatch, changed):
    runs_root, _, target_html, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    latest = runs_root / run_id / "asset_revalidation" / tc_id / "latest.json"
    latest.parent.mkdir(parents=True, exist_ok=True)
    latest.write_text('{"previous":"preserved"}', encoding="utf-8")
    original_target = target_html.read_bytes()
    candidate = runs_root / run_id / "agent3_candidates" / tc_id / "candidates"
    original_code = {path: path.read_bytes() for path in candidate.iterdir() if path.is_file()}

    def changing_trial(code_file, current_target, evidence_dir, *, timeout_seconds):
        changed_file = current_target if changed == "target" else code_file
        changed_file.write_bytes(changed_file.read_bytes() + b"\n# changed during trial\n")
        return pipeline.Agent3TrialResult(outcome=pipeline.TrialOutcome.PASS,
            exit_code=0, duration_ms=1, stdout_file="stdout.txt", stderr_file="stderr.txt",
            evidence_complete=True)

    monkeypatch.setattr(pipeline, "run_candidate_trial", changing_trial)
    with pytest.raises(ValueError, match="재검증 중"):
        pipeline_ui.revalidate_candidate_asset(runs_root, target_html, run_id, tc_id)
    assert json.loads(latest.read_text(encoding="utf-8"))["outcome"] == "INCOMPLETE"
    target_html.write_bytes(original_target)
    for path, content in original_code.items():
        path.write_bytes(content)
    assert pipeline_ui._candidate_approval_check(
        runs_root / run_id, tc_id, target_html=target_html)[3]


@pytest.mark.parametrize("prior_retry", [False, True])
@pytest.mark.parametrize("failure", [OSError, RuntimeError, KeyboardInterrupt])
def test_interrupted_revalidation_cannot_reuse_old_pass(tmp_path, monkeypatch, prior_retry, failure):
    runs, assets, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    run_dir = runs / run_id
    latest = run_dir / "asset_revalidation" / tc_id / "latest.json"
    if prior_retry:
        original = pipeline_ui._candidate_validation(run_dir, tc_id)
        _write_json(latest, {
            "outcome": "PASS", "candidate_sha256": original["test_sha256"],
            "target_sha256": original["target_sha256"], "evidence_complete": True,
            "evidence_files": original["evidence_files"],
            "evidence_sha256": original["evidence_sha256"],
        })
    assert not pipeline_ui._candidate_approval_check(run_dir, tc_id, target_html=target)[3]
    def interrupted(*args, **kwargs):
        raise failure("trial interrupted")
    monkeypatch.setattr(pipeline, "run_candidate_trial", interrupted)
    with pytest.raises(failure):
        pipeline_ui.revalidate_candidate_asset(runs, target, run_id, tc_id)
    assert pipeline_ui._candidate_approval_check(run_dir, tc_id, target_html=target)[3], (
        "An interrupted retry must not silently restore approval eligibility"
    )
    with pytest.raises(ValueError):
        pipeline_ui.decide_candidate_asset(runs, assets, target, run_id, tc_id,
            decision="APPROVE", reviewer="검토자", note="중단 시험 차단")
    assert not (assets / "registry.json").exists()


@pytest.mark.parametrize("fail_write", [1, 2])
def test_revalidation_record_write_failure_is_safe(tmp_path, monkeypatch, fail_write):
    runs, _, target, run_id, tc_id, _ = build_approvable_ui_run(tmp_path, monkeypatch)
    original_write = pipeline_ui._write_json_atomic
    calls = {"write": 0, "trial": 0}
    def writing(path, payload):
        calls["write"] += 1
        if calls["write"] == fail_write:
            raise OSError("simulated record failure")
        original_write(path, payload)
    def trial(*args, **kwargs):
        calls["trial"] += 1
        return pipeline.Agent3TrialResult(outcome=pipeline.TrialOutcome.PASS,
            exit_code=0, duration_ms=1, stdout_file="stdout.txt", stderr_file="stderr.txt",
            evidence_complete=True)
    monkeypatch.setattr(pipeline_ui, "_write_json_atomic", writing)
    monkeypatch.setattr(pipeline, "run_candidate_trial", trial)
    with pytest.raises(OSError):
        pipeline_ui.revalidate_candidate_asset(runs, target, run_id, tc_id)
    assert calls["trial"] == fail_write - 1
    reasons = pipeline_ui._candidate_approval_check(runs / run_id, tc_id, target_html=target)[3]
    assert bool(reasons) == (fail_write == 2)


@pytest.mark.parametrize("existing", [False, True])
def test_ui_atomic_writer_cleans_failed_temporary_file(tmp_path, monkeypatch, existing):
    import qa_pipeline_io
    target = tmp_path / "record.json"
    if existing:
        target.write_bytes(b'{"original":true}')
    def fail_replace(*args, **kwargs):
        raise OSError("simulated replacement failure")
    monkeypatch.setattr(Path, "replace", fail_replace)
    monkeypatch.setattr(qa_pipeline_io.os, "replace", fail_replace)
    with pytest.raises(OSError):
        pipeline_ui._write_json_atomic(target, {"new": "record"})
    assert sorted(p.name for p in tmp_path.iterdir()) == (["record.json"] if existing else [])
    if existing:
        assert target.read_bytes() == b'{"original":true}'


@pytest.mark.parametrize("url,method,allowed", [
    ("http://127.0.0.1:8765/", "GET", True),
    ("http://127.0.0.1:8765/api/runs", "GET", True),
    ("http://127.0.0.1:8765/api/approve", "POST", False),
    ("http://127.0.0.1:8765/api/run", "POST", False),
    ("http://127.0.0.1:8766/", "GET", False),
    ("https://api.openai.com/v1/responses", "POST", False),
    ("https://api.notion.com/v1/pages", "POST", False),
    ("http://127.0.0.1:8765.example.com/", "GET", False),
])
def test_recording_preview_blocks_writes_and_external_requests(monkeypatch, url, method, allowed):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import record_demo
    assert record_demo.permitted_request(url, method, "http://127.0.0.1:8765") is allowed


def test_recording_preview_timeline_does_not_claim_registration(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).resolve().parents[1] / "scripts"))
    import record_demo
    assert sum(scene.seconds for scene in record_demo.SCENES) == 90
    assert "미등록" in record_demo.SCENES[5].title
    assert "승인을 수행하지 않습니다" in record_demo.SCENES[5].caption
    assert "변경하지 않았습니다" in record_demo.SCENES[-1].caption


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

    expected_path = str(pipeline_ui.REPO_ROOT / "private-input.json").replace(
        str(pipeline_ui.REPO_ROOT), "<REPO_ROOT>"
    )
    assert message == f"모델 연결 실패: {expected_path}"
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
        srs_path=tmp_path / "custom-srs.md",
        approved_assets_root=tmp_path / "custom-assets",
    )
    run_id = "RUN-20260829-130000-ABCDEF"
    monkeypatch.setattr(pipeline_ui, "_new_run_id", lambda: run_id)
    commands: list[tuple[str, ...]] = []

    def fake_command(*arguments: str) -> SimpleNamespace:
        commands.append(arguments)
        if arguments[0] == "pipeline":
            (runs_root / run_id).mkdir(parents=True)
            (runs_root / "RUN-20990101-000000-ABCDEF").mkdir()
            assert arguments[arguments.index("--run-id") + 1] == run_id
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge, "_command", fake_command)

    bridge._run_pipeline(request_file)

    assert [command[0] for command in commands] == ["pipeline", "execute", "agent4"]
    assert commands[0][-2:] == ("--timeout", "90")
    assert "--send" not in commands[-1]
    assert commands[0][commands[0].index("--srs") + 1] == str(bridge.srs_path)
    for command in commands[:2]:
        assert command[command.index("--approved-assets-root") + 1] == str(bridge.approved_assets_root)
    assert commands[1][2] == commands[2][2] == run_id
    assert bridge.state.snapshot()["phase"] == "COMPLETED"
    assert bridge.state.snapshot()["run_id"] == run_id

def test_pipeline_ui_reports_environment_block_without_external_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(pipeline_ui, "_new_run_id", lambda: "RUN-20260817-030000-ABCDEF")
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=tmp_path / "runs", requests_root=tmp_path,
        target_html=tmp_path / "virtual-controller.html", allow_live_run=True,
    )
    commands: list[tuple[str, ...]] = []

    def fake_command(*arguments: str) -> SimpleNamespace:
        commands.append(arguments)
        if arguments[0] == "pipeline":
            _write_agent4_inputs(tmp_path, precheck_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR)
        if arguments[0] == "execute":
            return SimpleNamespace(returncode=2)
        if arguments[0] == "agent4":
            # Agent 4 분석·CP4·보고 생성은 실제 코드로 확인하며 모델·외부 전송은 사용하지 않습니다.
            return SimpleNamespace(returncode=pipeline.run_agent4(
                SimpleNamespace(run_id=arguments[2], runs_root=str(bridge.runs_root))
            ))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge, "_command", fake_command)
    bridge._run_pipeline(tmp_path / "change_request.json")
    state = bridge.state.snapshot()
    assert [command[0] for command in commands] == ["pipeline", "execute", "agent4"]
    assert "--send" not in commands[-1]
    assert state["phase"] == "COMPLETED"
    assert "환경 점검 실패" in state["message"]
    summary = pipeline_ui.summarize_run(bridge.runs_root, state["run_id"])
    assert summary["overall_status"] == "HOLD"
    assert summary["stages"]["agent4"]["status"] == "PASS"
    assert "Slack: PREVIEW / Notion: PREVIEW" in summary["stages"]["agent4"]["details"]


def test_pipeline_ui_stops_on_missing_or_damaged_failure_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    for scenario in ("missing", "damaged"):
        monkeypatch.setattr(pipeline_ui, "_new_run_id", lambda: "RUN-20260817-030000-ABCDEF")
        case_root = tmp_path / scenario
        bridge = pipeline_ui.PipelineUiBridge(
            runs_root=case_root / "runs", requests_root=case_root,
            target_html=case_root / "virtual-controller.html", allow_live_run=True,
        )
        commands: list[str] = []

        def fake_command(*arguments: str) -> SimpleNamespace:
            commands.append(arguments[0])
            if arguments[0] == "pipeline":
                if scenario == "missing":
                    (bridge.runs_root / "RUN-20260817-030000-ABCDEF").mkdir(parents=True)
                else:
                    run_dir, _ = _write_agent4_inputs(
                        case_root, precheck_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR
                    )
                    manifest_file = run_dir / "validation_manifest.json"
                    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
                    manifest["validation_execution_sha256"] = "0" * 64
                    _write_json(manifest_file, manifest)
            return SimpleNamespace(returncode=2 if arguments[0] == "execute" else 0)

        monkeypatch.setattr(bridge, "_command", fake_command)
        bridge._run_pipeline(case_root / "change_request.json")
        assert commands == ["pipeline", "execute"]
        assert bridge.state.snapshot()["phase"] == "FAILED"


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
    assert "qaLiveState.demoMode ? '공개 데모' : '실제 Run'" in product_html
    assert "QA Pipeline V2 정상 변경 데모" in product_html
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
