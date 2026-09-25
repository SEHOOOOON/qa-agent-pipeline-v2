"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_editable_execution_instructions_match_workspace_runtime():
    readme = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    guide = (REPO_ROOT / "docs/PROJECT_GUIDE.md").read_text(encoding="utf-8")
    assert 'pip install -e ".[agent3,test]"' in readme
    assert 'pip install -e ".[agent3,video]"' in guide
    assert pipeline_ui.REPO_ROOT == REPO_ROOT
    assert pipeline_ui.DEFAULT_TARGET_HTML.is_file() and pipeline_ui.DEFAULT_SRS.is_file()


def test_public_and_approved_evidence_preserves_bytes_with_windows_checkout(tmp_path):
    """Exercise add/checkout in a disposable index; never normalize original files."""
    root = tmp_path / "git-work"
    root.mkdir()
    def git(*args):
        return subprocess.check_output(["git", "-C", str(root), *args], stderr=subprocess.STDOUT)
    git("init", "-q")
    git("config", "core.autocrlf", "true")
    git("config", "core.safecrlf", "false")
    (root / ".gitattributes").write_bytes((REPO_ROOT / ".gitattributes").read_bytes())
    paths = subprocess.check_output(["git", "ls-files", "-z", "--", "examples/results", "approved_assets"], cwd=REPO_ROOT).decode().split("\0")
    originals = {}
    for name in filter(None, paths):
        originals[name] = (REPO_ROOT / name).read_bytes()
        destination = root / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(originals[name])
    git("add", ".")
    output = tmp_path / "checkout-copy"
    output.mkdir()
    git("checkout-index", "--all", "--prefix=" + output.as_posix() + "/")
    assert originals
    for name, raw in originals.items():
        assert git("show", ":" + name) == raw, name
        assert (output / name).read_bytes() == raw, name



@pytest.mark.parametrize("statuses", [[], *[[a, b] for a in CheckStatus for b in CheckStatus]])
def test_shared_status_aggregation_preserves_priority_and_exports(statuses):
    import qa_pipeline_agent1 as a1
    import qa_pipeline_agent2 as a2
    import qa_pipeline_contracts as contracts
    expected = next((s for s in (CheckStatus.ERROR, CheckStatus.FAIL, CheckStatus.REVIEW)
                     if s in statuses), CheckStatus.PASS)
    assert contracts._aggregate_check_status(iter(statuses)) == expected
    assert a1._aggregate_check_status is a2._aggregate_check_status is pipeline._aggregate_check_status


@pytest.mark.parametrize("mutation,message", [
    ("registry_type", "assets 목록"), ("entry_type", "JSON 객체"),
    ("tc_id", "TC ID 형식"), ("missing_file", "찾을 수 없습니다"),
    ("hash", "SHA-256"), ("revision", "SRS 개정 기록 SHA-256"),
    ("payload_id", "TC 파일 ID"), ("payload_type", "구조화 TC"),
    ("requirements", "Requirement 목록"), ("functions", "정확히 한 개"),
])
def test_approved_catalog_failure_branches_preserve_original_assets(tmp_path, mutation, message):
    import shutil
    original = REPO_ROOT / "approved_assets"
    before = {p.relative_to(original): _sha256_file(p) for p in original.rglob('*') if p.is_file()}
    root = tmp_path / "assets"
    shutil.copytree(original, root)
    registry_file = root / "registry.json"
    registry = pipeline._read_json_payload(registry_file)
    asset = registry['assets'][0]
    if mutation == "registry_type": registry['assets'] = {}
    elif mutation == "entry_type": registry['assets'] = [None]
    elif mutation == "tc_id": asset['official_tc_id'] = 'INVALID'
    elif mutation == "missing_file": asset['automation_file'] = 'missing.py'
    elif mutation == "hash": asset['automation_sha256'] = '0' * 64
    elif mutation == "revision": asset['srs_revision_sha256'] = '0' * 64
    elif mutation == "requirements": asset['requirement_ids'] = []
    elif mutation == "functions":
        source = root / asset['automation_file']
        source.write_text('def helper():\n    pass\n', encoding='utf-8')
        asset['automation_sha256'] = _sha256_file(source)
    else:
        source = root / asset['test_case_file']
        payload = pipeline._read_json_payload(source)
        if mutation == "payload_id": payload['official_tc_id'] = 'TC-V2-999'
        else: payload['test_case'] = None
        _write_json(source, payload)
        asset['test_case_sha256'] = _sha256_file(source)
    _write_json(registry_file, registry)
    with pytest.raises(ValueError, match=message):
        pipeline.load_approved_regression_catalog(root)
    assert before == {p.relative_to(original): _sha256_file(p) for p in original.rglob('*') if p.is_file()}


@pytest.mark.parametrize("payload", [{'approved_assets': 'bad'}, {'approved_assets': [None]},
                                      {'approved_assets': [{'source': 'UNKNOWN'}]}])
def test_catalog_snapshot_rejects_non_catalog_data(payload):
    with pytest.raises(ValueError, match='Snapshot'):
        pipeline._catalog_from_snapshot(payload)


def test_catalog_duplicate_ids_and_invalid_hash_are_rejected(tmp_path):
    spec = pipeline.EXISTING_REGRESSION_CATALOG[0]
    with pytest.raises(ValueError, match='중복 ID'):
        pipeline._existing_regression_by_id((spec, spec))
    with pytest.raises(ValueError, match='SHA-256 값'):
        pipeline._verify_sha256(tmp_path / 'not-read', None, 'test')


@pytest.mark.parametrize("mutation,message", [
    ('run_id', 'Run ID'), ('stage', '단계'), ('status', 'PASS'),
    ('design_hash', '설계 해시'), ('tc_id', '선택 TC'), ('target_name', '파일명'),
    ('product_modified', '제품 불변'), ('candidate_name', '파일명'),
])
def test_candidate_handoff_rejects_invalid_manifest_branches(tmp_path, monkeypatch, mutation, message):
    run, target, run_id = _build_candidate_execution_handoff(tmp_path, monkeypatch)
    file = run / 'agent3_manifest.json'
    manifest = pipeline._read_json_payload(file)
    key, value = {
        'run_id': ('run_id', 'RUN-20200101-000000-ABCDEF'), 'stage': ('stage', 'AGENT_1_CP1'),
        'status': ('status', 'FAIL'), 'design_hash': ('source_agent2_design_sha256', '0'*64),
        'tc_id': ('tc_id', 'TC-CAND-999'), 'target_name': ('target_file', 'other.html'),
        'product_modified': ('project1_modified', True), 'candidate_name': ('candidate_file', None),
    }[mutation]
    manifest[key] = value
    _write_json(file, manifest)
    with pytest.raises(ValueError, match=message):
        pipeline._candidate_execution_record(run, run_id, target)


@pytest.mark.parametrize("rewrite", [False, True])
def test_srs_quote_policy_initial_rewrite_and_verified_loader(tmp_path, monkeypatch, rewrite):
    request, analysis, _ = cp1_combined_srs_case()
    calls = []
    class FakeAgent:
        def __init__(self, **kwargs):
            pass
        def analyze(self, *args, **kwargs):
            calls.append(kwargs)
            result = analysis.model_copy(deep=True)
            if rewrite and len(calls) == 1:
                result.confirmed_conditions[2].source_text += " | 없는 근거"
            return pipeline.Agent1Response(analysis=result, response_id=None,
                model="fake-srs-quotes", usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0})
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent1", FakeAgent)
    request_file = tmp_path / "request.json"
    _write_json(request_file, request.model_dump(mode="json"))
    assert pipeline.run_agent1(SimpleNamespace(request=str(request_file),
        srs=str(REPO_ROOT / "docs/01_PRODUCT_SRS.md"), runs_root=str(tmp_path / "runs"), model=None)) == 0
    run_dir = next((tmp_path / "runs").iterdir())
    verified = _load_verified_agent1_run(run_dir, run_dir.name)
    assert verified[2].model_dump() == analysis.model_dump()
    assert len(calls) == (2 if rewrite else 1)
    if rewrite:
        assert any("출처" in message for message in calls[1]["checkpoint_feedback"])
    manifest_file = run_dir / "run_manifest.json"
    original = pipeline._read_json_payload(manifest_file)
    assert original["contract_version"] == "2.11"
    assert original["srs_quote_contract"] == "1.0"
    for invalid in (None, "unknown", "0.9"):
        _write_json(manifest_file, {**original, "srs_quote_contract": invalid})
        with pytest.raises(ValueError, match="SRS 인용 계약"):
            _load_verified_agent1_run(run_dir, run_dir.name)
    _write_json(manifest_file, {**original, "contract_version": "2.9"})
    with pytest.raises(ValueError, match="SRS 인용 계약"):
        _load_verified_agent1_run(run_dir, run_dir.name)
    _write_json(manifest_file, {**original, "contract_version": "2.9", "srs_quote_contract": None})
    with pytest.raises(ValueError, match="근거 검토 계약"):
        _load_verified_agent1_run(run_dir, run_dir.name)
    _write_json(manifest_file, original)
    assert _load_verified_agent1_run(run_dir, run_dir.name)[3].status == CheckStatus.PASS


@pytest.mark.parametrize("stage", ["CP1", "CP2"])
@pytest.mark.parametrize("legacy", [True, False])
@pytest.mark.parametrize("mutation", [
    "unchanged", "pass_message", "fail_message", "review_message", "overall_status",
    "rule_status", "rule_id", "missing", "duplicate", "order", "checkpoint_name",
])
def test_checkpoint_revalidation_limits_legacy_pass_message_compatibility(stage, legacy, mutation):
    stored = checkpoint_revalidation_fixture(stage)
    recomputed = stored.model_copy(deep=True)
    if mutation == "pass_message":
        recomputed.checks[0].message = "새 성공 안내"
    elif mutation in {"fail_message", "review_message"}:
        status = CheckStatus.FAIL if mutation == "fail_message" else CheckStatus.REVIEW
        stored.checks[0].status = recomputed.checks[0].status = status
        recomputed.checks[0].message = "바뀐 실패 또는 검토 근거"
    elif mutation == "overall_status":
        recomputed.status = CheckStatus.FAIL
    elif mutation == "rule_status":
        recomputed.checks[0].status = CheckStatus.FAIL
    elif mutation == "rule_id":
        recomputed.checks[0].rule_id = f"{stage}-999"
    elif mutation == "missing":
        recomputed.checks.pop()
    elif mutation == "duplicate":
        recomputed.checks.append(recomputed.checks[0].model_copy(deep=True))
    elif mutation == "order":
        recomputed.checks.reverse()
    elif mutation == "checkpoint_name":
        recomputed.checkpoint = "OTHER"
    original = stored.model_dump(mode="json"), recomputed.model_dump(mode="json")
    expected = mutation == "unchanged" or (legacy and mutation == "pass_message")
    assert pipeline_execution._checkpoint_revalidation_matches(
        stored, recomputed, legacy=legacy) == expected
    assert original == (stored.model_dump(mode="json"), recomputed.model_dump(mode="json"))


@pytest.mark.parametrize("mutation", ["review_notes", "handoff", "different_model"])
def test_checkpoint_revalidation_preserves_review_notes_and_handoff(mutation):
    stored = checkpoint_revalidation_fixture("CP1")
    recomputed = stored.model_copy(deep=True)
    if mutation == "review_notes":
        recomputed.final_review_notes.append("사람이 확인해야 할 추가 근거")
    elif mutation == "handoff":
        recomputed.handoff_status = HandoffStatus.PAUSE
    else:
        recomputed = checkpoint_revalidation_fixture("CP2")
    assert not pipeline_execution._checkpoint_revalidation_matches(stored, recomputed, legacy=True)


@pytest.mark.parametrize("stage", ["CP1", "CP2"])
@pytest.mark.parametrize("mutation", ["pass_message", "unhashed_message", "rule_status", "missing_rule", "recomputed_failure"])
def test_historical_checkpoint_loader_preserves_hash_and_decision_guards(tmp_path, monkeypatch, stage, mutation):
    builder = build_verified_agent1_run if stage == "CP1" else build_historical_agent2_run
    run_dir, run_id = builder(tmp_path)
    loader = (pipeline_execution._load_verified_agent1_run if stage == "CP1"
              else pipeline_execution._load_verified_agent2_run)
    checkpoint_file = run_dir / f"checkpoint{stage[-1]}.json"
    manifest_file = run_dir / ("run_manifest.json" if stage == "CP1" else "agent2_manifest.json")
    checkpoint = pipeline._read_json_payload(checkpoint_file)
    manifest = pipeline._read_json_payload(manifest_file)
    if mutation in {"pass_message", "unhashed_message"}:
        next(item for item in checkpoint["checks"] if item["status"] == "PASS")["message"] = "과거 버전의 성공 안내"
    elif mutation == "rule_status":
        checkpoint["checks"][0]["status"] = "FAIL"
    elif mutation == "missing_rule":
        checkpoint["checks"].pop()
    elif mutation == "recomputed_failure":
        name = f"evaluate_checkpoint{stage[-1]}"
        original = getattr(pipeline_execution, name)
        def failed(*args, **kwargs):
            result = original(*args, **kwargs)
            result.checks[0].status = CheckStatus.FAIL
            return result
        monkeypatch.setattr(pipeline_execution, name, failed)
    _write_json(checkpoint_file, checkpoint)
    if mutation != "unhashed_message":
        manifest[f"checkpoint{stage[-1]}_sha256"] = _sha256_file(checkpoint_file)
        _write_json(manifest_file, manifest)
    before = {path.name: _sha256_file(path) for path in run_dir.iterdir() if path.is_file()}
    def forbid_model(*args, **kwargs):
        raise AssertionError("Read-only checkpoint verification must not construct an API client")
    monkeypatch.setattr(pipeline_execution, "OpenAI", forbid_model)
    if mutation == "pass_message":
        loader(run_dir, run_id)
    else:
        with pytest.raises(ValueError):
            loader(run_dir, run_id)
    assert before == {path.name: _sha256_file(path) for path in run_dir.iterdir() if path.is_file()}


def test_declared_procedures_reach_final_review_for_existing_tests(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    note = "마지막에는 처음 기록해 둔 상태와 대조합니다."
    request.acceptance_notes.append(note)
    analysis.procedure_notes = [note]
    design.test_cases = []
    _write_json(run_dir / "request.json", request.model_dump(mode="json"))
    _write_json(run_dir / "agent1_change_analysis.json", analysis.model_dump(mode="json"))
    _write_json(run_dir / "agent2_test_design.json", design.model_dump(mode="json"))
    _write_json(run_dir / "run_manifest.json", {
        "agent1_analysis_sha256": _sha256_file(run_dir / "agent1_change_analysis.json")})
    _write_json(run_dir / "agent2_manifest.json", {
        "wording_policy": "STRUCTURAL_ONLY_V1", "existing_procedure_review_contract": "1.0",
        "request_sha256": _sha256_file(run_dir / "request.json")})
    notes = pipeline_execution._final_review_notes_for_validation(run_dir)
    assert any(note in item and "실제 수행 증거" in item for item in notes)


@pytest.mark.parametrize("current,previous", [("2.8", "2.7"), ("3.8", "3.7"), ("4.6", "4.4"), ("4.7", "4.5")])
@pytest.mark.parametrize("mutation", ["valid", "missing", "unknown", "downgrade", "legacy"])
def test_wording_policy_is_bound_to_contract_version(current, previous, mutation):
    manifest = {"contract_version": current, "wording_policy": "STRUCTURAL_ONLY_V1"}
    if mutation == "missing":
        manifest.pop("wording_policy")
    elif mutation == "unknown":
        manifest["wording_policy"] = "unknown"
    elif mutation == "downgrade":
        manifest["contract_version"] = previous
    elif mutation == "legacy":
        manifest = {"contract_version": previous}
    if mutation in {"valid", "legacy"}:
        assert pipeline_execution._legacy_wording_policy(manifest, {current}) == (mutation == "legacy")
    else:
        with pytest.raises(ValueError, match="문장 검사 정책"):
            pipeline_execution._legacy_wording_policy(manifest, {current})


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
    assert original["input_routing_contract"] == "1.0"
    for invalid in (None, "0.9", "unknown"):
        _write_json(manifest_file, {**original, "input_routing_contract": invalid})
        with pytest.raises(ValueError, match="입력 분류 계약"):
            _load_verified_agent1_run(run_dir, run_dir.name)
    _write_json(manifest_file, {**original, "contract_version": "2.6"})
    with pytest.raises(ValueError, match="입력 분류 계약"):
        _load_verified_agent1_run(run_dir, run_dir.name)
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
    assert manifest["prompt_version"] == "agent1-2.17"
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


def test_historical_agent1_run_remains_readable(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)

    request, _, analysis, checkpoint, _ = _load_verified_agent1_run(run_dir, run_id)

    assert request.request_id == analysis.request_id
    assert checkpoint.handoff_status == HandoffStatus.CONTINUE


@pytest.mark.parametrize("contract", ["2.6", "2.7"])
@pytest.mark.parametrize("note", [
    "[준비] 시험 전 대상 장비가 AUTO 모드인지 확인합니다.",
    "시험 전 대상 장비가 AUTO 모드인지 확인합니다.",
    "[복원] 시험 후 대상 장비를 시험 전 상태로 복원합니다.",
    "시험 후 대상 장비를 시험 전 상태로 복원합니다.",
])
def test_new_agent2_rejects_historical_analysis_before_any_side_effect(
    tmp_path, monkeypatch, contract, note
):
    run_dir, run_id = build_verified_agent1_run(tmp_path)
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    checkpoint = evaluate_checkpoint1(
        request, analysis, cp1_requirements(),
        require_input_contract=contract == "2.7", legacy_wording_checks=True,
    )
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump()
    assert checkpoint.handoff_status == HandoffStatus.CONTINUE

    # Historical responses genuinely lack the new field. Recompute their CP
    # under the original policy instead of relabeling a current checkpoint.
    historical_analysis = analysis.model_dump(mode="json")
    historical_analysis.pop("procedure_notes")
    _write_json(run_dir / "request.json", request.model_dump(mode="json"))
    _write_json(run_dir / "agent1_change_analysis.json", historical_analysis)
    _write_json(run_dir / "checkpoint1.json", checkpoint.model_dump(mode="json"))
    manifest = pipeline._read_json_payload(run_dir / "run_manifest.json")
    manifest.update({
        "contract_version": contract,
        "prompt_version": "agent1-2.13" if contract == "2.7" else "agent1-2.12",
        "scope_guard_contract": "1.1",
        "meaning_guard_contract": "1.0",
        "request_sha256": _sha256_file(run_dir / "request.json"),
        "agent1_analysis_sha256": _sha256_file(run_dir / "agent1_change_analysis.json"),
        "checkpoint1_sha256": _sha256_file(run_dir / "checkpoint1.json"),
    })
    if contract == "2.7":
        manifest["input_routing_contract"] = "1.0"
    _write_json(run_dir / "run_manifest.json", manifest)
    original_hashes = {path.name: _sha256_file(path) for path in run_dir.iterdir()}

    historical = _load_verified_agent1_run(run_dir, run_id)
    assert historical[2].procedure_notes == []
    assert historical[4]["contract_version"] == contract
    calls = []

    def forbidden_agent2(**kwargs):
        calls.append("model")
        pytest.fail("A historical analysis must be rejected before model construction")

    def forbidden_catalog(*args, **kwargs):
        calls.append("catalog")
        pytest.fail("A historical analysis must be rejected before catalog preparation")

    monkeypatch.setattr(pipeline_execution, "OpenAIAgent2", forbidden_agent2)
    monkeypatch.setattr(pipeline_execution, "load_approved_regression_catalog", forbidden_catalog)
    with pytest.raises(ValueError, match="과거 Agent 1.*새 Agent 1"):
        pipeline.run_agent2(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path), model=None))

    assert calls == []
    assert not (run_dir / "agent2_in_progress.json").exists()
    assert not (run_dir / "approved_regression_catalog.json").exists()
    assert {path.name: _sha256_file(path) for path in run_dir.iterdir()} == original_hashes

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
@pytest.mark.parametrize("procedure_style", ["none", "marked", "unmarked", "split"])
def test_agent1_to_agent2_cli_handoff_with_frozen_inputs(
    tmp_path: Path, monkeypatch, detail_outcome, procedure_style
) -> None:
    current_catalog, _ = pipeline.load_approved_regression_catalog(REPO_ROOT / "approved_assets")
    expected_catalog_ids = [item.tc_id for item in current_catalog]
    request_file = tmp_path / "request.json"
    request = cp1_request()
    procedure_notes = []
    if procedure_style != "none":
        procedure_notes = [
            "시험 전 대상 장비가 AUTO 모드인지 확인합니다.",
            "시험 후 대상 장비를 시험 전 온도로 복원합니다.",
        ]
        if procedure_style == "marked":
            procedure_notes = [f"[준비] {procedure_notes[0]}", f"[복원] {procedure_notes[1]}"]
        if procedure_style == "split":
            procedure_notes[1] += " 복원 조작을 적용합니다."
        request.acceptance_notes.extend(procedure_notes)
    _write_json(request_file, request.model_dump(mode="json"))

    class FakeAgent1:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent1"

        def analyze(self, request, requirements, **kwargs):
            analysis = cp1_valid_analysis()
            analysis.procedure_notes = list(procedure_notes)
            return pipeline.Agent1Response(
                analysis=analysis,
                response_id="not-persisted",
                model=self.model,
                usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    design_calls = []

    class FakeAgent2:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent2"

        def design(self, request, analysis, requirements, **kwargs):
            assert analysis.procedure_notes == procedure_notes
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
                preconditions=["대상 장비가 AUTO 모드다.", *procedure_notes[:1]],
                steps=steps,
                expected_results=[
                    ExpectedResult(


                        result_id="ER-001",
                        statement="화면 온도가 변경 조건과 일치한다.",
                        observation_target=("화면 온도" if detail_outcome == "clean" or
                                            (detail_outcome == "repair" and len(design_calls) == 2) else None),
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
                    state_effect=pipeline.TcStateEffect.BLOCKED_CHANGE,
                    restore_required=True,
                    restore_steps=[procedure_notes[1] if procedure_notes else "대상 장비를 시험 전 온도로 복원한다.",
                                   "화면 온도가 시험 전 기록한 상태와 같은지 확인한다."],
                    automation_candidate=True,
                    automation_reason="화면에서 요청 결과를 확인할 수 있다.",
            )
            if procedure_style == "split":
                tc.restore_steps = ["시험 후 대상 장비를 시험 전 온도로 복원합니다.",
                                    "복원 조작을 적용합니다.", *tc.restore_steps[1:]]
            line = tc.restore_steps[-1]
            tc.restoration = pipeline.StructuredRestoration(operation_steps=tc.restore_steps[:-1],
                confirmations=[pipeline.RestoreConfirmation(source_text=line, result_ids=["ER-001"],
                    comparisons=[pipeline.RestoreComparison(result_id="ER-001", source_excerpt=line,
                                                           basis="OBSERVED_BASELINE")])], verify_when="AFTER_RESTORE")
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
    verified_agent1 = _load_verified_agent1_run(run_dir, run_dir.name)
    assert verified_agent1[2].procedure_notes == procedure_notes
    assert verified_agent1[4]["contract_version"] == "2.11"
    assert verified_agent1[4]["wording_policy"] == "STRUCTURAL_ONLY_V1"
    agent2_args = SimpleNamespace(
        run_id=run_dir.name,
        runs_root=str(runs_root),
        model=None,
    )

    assert pipeline.run_agent2(agent2_args) == (2 if detail_outcome == "unresolved" else 0)
    detail_manifest = pipeline._read_json_payload(run_dir / "agent2_manifest.json")
    assert detail_manifest["tc_detail_contract"] == "1.2"
    assert detail_manifest["prompt_version"] == "agent2-2.40"
    assert len(design_calls) == (1 if detail_outcome == "clean" else 2)
    if detail_outcome != "clean":
        assert any("CP2-020" in text for text in design_calls[1]["checkpoint_feedback"])
    if detail_outcome == "unresolved":
        assert detail_manifest["status"] == "FAIL"
        with pytest.raises(ValueError, match="Checkpoint 2 must PASS"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
        return
    verified = pipeline._load_verified_agent2_run(run_dir, run_dir.name)
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
    assert manifest["srs_revision_contract"] == "1.1"
    assert manifest["contract_version"] == "3.13"
    reviewed_attempt = manifest["grounding_reviews"][-1]["attempt"]
    review_input = pipeline._read_json_payload(
        run_dir / f"agent2_grounding_input_attempt_{reviewed_attempt}.json"
    )
    assert any(item["kind"] == "CONDITION_COVERAGE" for item in review_input["items"])
    # Downgrading a new manifest cannot reuse a review over different inputs.
    _write_json(run_dir / "agent2_manifest.json", {**manifest, "contract_version": "3.11"})
    with pytest.raises(ValueError, match="해시"):
        pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    _write_json(run_dir / "agent2_manifest.json", manifest)
    assert manifest["scope_restoration_policy"] == "STRUCTURED_V1"
    for invalid in (None, "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "scope_restoration_policy": invalid})
        with pytest.raises(ValueError, match="범위·복원 검사 정책"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    _write_json(run_dir / "agent2_manifest.json", {**manifest, "contract_version": "3.9"})
    with pytest.raises(ValueError, match="범위·복원 검사 정책"):
        pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    assert manifest["procedure_preservation_contract"] == "1.0"
    for invalid in (None, "0.9", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "procedure_preservation_contract": invalid})
        with pytest.raises(ValueError, match="절차 보존 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    _write_json(run_dir / "agent2_manifest.json", {**manifest, "contract_version": "3.8"})
    with pytest.raises(ValueError, match="절차 보존 계약"):
        pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    assert manifest["wording_policy"] == "STRUCTURAL_ONLY_V1"
    for invalid in (None, "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "wording_policy": invalid})
        with pytest.raises(ValueError, match="문장 검사 정책"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    assert manifest["input_routing_contract"] == "1.0"
    for invalid in (None, "0.9", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "input_routing_contract": invalid})
        with pytest.raises(ValueError, match="입력 분류 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    assert manifest["structured_restoration_contract"] == "1.0"
    for invalid in (None, "0.9", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "structured_restoration_contract": invalid})
        with pytest.raises(ValueError, match="구조화 복원 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    _write_json(run_dir / "agent2_manifest.json", {**manifest, "contract_version": "3.5", "structured_restoration_contract": None})
    with pytest.raises(ValueError, match="구조화 복원 계약"):
        pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    assert manifest["state_restoration_contract"] == "1.0"
    for invalid in (None, "0.9", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "state_restoration_contract": invalid})
        with pytest.raises(ValueError, match="상태 복원 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    _write_json(run_dir / "agent2_manifest.json", {**manifest, "contract_version": "3.4"})
    with pytest.raises(ValueError, match="상태 복원 계약"):
        pipeline._load_verified_agent2_run(run_dir, run_dir.name)

    for unsupported in (None, "1.0", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "srs_revision_contract": unsupported})
        with pytest.raises(ValueError, match="SRS 개정 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    _write_json(run_dir / "agent2_manifest.json", {**manifest, "contract_version": "3.3"})
    with pytest.raises(ValueError, match="SRS 개정 계약"):
        pipeline._load_verified_agent2_run(run_dir, run_dir.name)

    # New runs may not drop/downgrade the additional procedure check. Old 1.0
    # records retain their original checks and are not rewritten by the loader.
    for unsupported in (None, "1.0", "1.1", "unknown"):
        _write_json(run_dir / "agent2_manifest.json", {**manifest, "tc_detail_contract": unsupported})
        with pytest.raises(ValueError, match="TC 상세화 계약"):
            pipeline._load_verified_agent2_run(run_dir, run_dir.name)
    checkpoint = pipeline._read_json_payload(run_dir / "checkpoint2.json")
    checkpoint["checks"] = [item for item in checkpoint["checks"] if item["rule_id"] not in {"CP2-021", "CP2-022", "CP2-023"}]
    _write_json(run_dir / "checkpoint2.json", checkpoint)
    legacy_design = pipeline._read_json_payload(run_dir / "agent2_test_design.json")
    for tc in legacy_design["test_cases"]:
        tc.pop("state_effect")
        tc.pop("restoration")
        if procedure_style == "split":
            # Historical contract only accepts the whole note as one item.
            tc["restore_steps"] = [" ".join(tc["restore_steps"][:2]), *tc["restore_steps"][2:]]
    _write_json(run_dir / "agent2_test_design.json", legacy_design)
    # Build a historical fixture using historical rules/messages, not by
    # relabeling the new-policy checkpoint as an old checkpoint.
    historical_cp = pipeline.evaluate_checkpoint2(
        verified[0], verified[2], Agent2TestDesign.model_validate(legacy_design), verified[1],
        existing_catalog=pipeline._catalog_from_snapshot(catalog_snapshot),
        require_srs_revision_proposals=True, require_existing_behavior_values=True,
        require_procedure_detail=False, require_input_contract=False,
        legacy_wording_checks=True,
    )
    _write_json(run_dir / "checkpoint2.json", historical_cp.model_dump(mode="json"))
    legacy = {**manifest, "contract_version": "3.1", "tc_detail_contract": "1.0", "srs_revision_contract": "1.0",
              "grounding_contract": None, "grounding_review_sha256": None, "grounding_reviews": [],
              "state_restoration_contract": None, "structured_restoration_contract": None, "input_routing_contract": None,
              "wording_policy": None, "procedure_preservation_contract": None, "scope_restoration_policy": None,
              "agent2_design_sha256": _sha256_file(run_dir / "agent2_test_design.json"),
              "prompt_version": "agent2-2.24", "checkpoint2_sha256": _sha256_file(run_dir / "checkpoint2.json")}
    # This temporary historical fixture predates the independent review artifact.
    (run_dir / "agent2_grounding_review.json").unlink()
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
