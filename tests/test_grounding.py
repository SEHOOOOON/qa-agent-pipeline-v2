"""Transport/contract/branch tests. Scripted judgments do not measure model accuracy."""
from pipeline_test_support import *
import qa_pipeline_grounding as grounding


@pytest.mark.parametrize("mutation", ["normal", "missing_er", "missing_test", "wrong_reuse"])
@pytest.mark.parametrize("verdict", ["SUPPORTED", "UNSUPPORTED", "UNCERTAIN"])
def test_condition_coverage_is_enumerated_from_input_and_reviewed(tmp_path, monkeypatch, mutation, verdict):
    request, analysis, design = cp1_request(), cp2_analysis(), detailed_boundary_design()
    catalog = pipeline.EXISTING_REGRESSION_CATALOG
    if mutation == "missing_er":
        design.test_cases[0].expected_results.pop()
    elif mutation == "missing_test":
        design.test_cases = []
    elif mutation == "wrong_reuse":
        request, analysis, design, catalog = compound_reuse_fixture(values=("FAN", "DRY"), layout="actual_gap")
    old_payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
                                                   analysis=analysis, catalog=catalog)
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis, catalog=catalog, include_condition_coverage=True)
    coverage = [i for i in payload["items"] if i["kind"] == "CONDITION_COVERAGE"]
    assert [i["content"]["condition"]["condition_id"] for i in coverage] == [c.condition_id for c in analysis.confirmed_conditions]
    if mutation == "missing_er":
        condition = coverage[-1]["content"]
        assert condition["condition"]["condition_id"] in condition["candidate_tests"][0]["source_condition_ids"]
        assert not any(condition["condition"]["condition_id"] in er["source_condition_ids"]
                       for er in condition["candidate_tests"][0]["expected_results"])
    elif mutation == "missing_test":
        assert all(not i["content"]["candidate_tests"] for i in coverage)
    elif mutation == "wrong_reuse":
        assert "DRY" in coverage[0]["content"]["condition"]["statement"]
        assert all("DRY" not in " ".join(s["covered_behaviors"]) for s in coverage[0]["content"]["existing_behaviors"])
    record = fake_grounding_record(payload)
    target = coverage[-1]["item_id"]
    next(i for i in record["review"]["items"] if i["item_id"] == target).update(verdict=verdict)
    # Scripted verdicts prove routing, not a model's ability to detect these cases.
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer", lambda **kw: SimpleNamespace(review=lambda _: record))
    checkpoint = pipeline.Checkpoint2Result(status="PASS", checks=[pipeline.CheckResult(rule_id="fixture", status="PASS", message="base")])
    result = pipeline_execution._run_grounding_review(tmp_path, "AGENT2", 1, payload, checkpoint, "fake", [])
    assert result.status == {"SUPPORTED": CheckStatus.PASS, "UNSUPPORTED": CheckStatus.FAIL, "UNCERTAIN": CheckStatus.REVIEW}[verdict]
    assert (result.status == CheckStatus.PASS) == (verdict == "SUPPORTED")
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(payload, fake_grounding_record(old_payload))
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != target]
    assert "누락" in grounding.check_review_record(payload, record).message


@pytest.mark.parametrize("missing_field", [False, True])
def test_partial_assertion_is_visible_to_the_existing_semantic_review(missing_field):
    case, plan, observation = structured_restoration_fixture()
    case.expected_results[1].statement = "Internal enabled must equal true and level must equal 5."
    observation.device_state_fields = ["enabled", "level"]
    fields = [{"field_name": "enabled", "expected_value": True}]
    if not missing_field:
        fields.append({"field_name": "level", "expected_value": 5})
    plan.assertions[1] = pipeline.AutomationAssertion.model_validate(dict(result_id="ER-091",
        observation_layer="INTERNAL_STATE", strategy="INTERNAL_DEVICE_FIELDS_EQUALS",
        selector="window.__vccs.devices", expected_fields=fields, after_action_id="ACT-090"))
    structural = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False)
    assert structural.status == CheckStatus.PASS
    payload = grounding.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=observation)
    item = next(i for i in payload["items"] if i["item_id"] == "ER/1")
    assert "level" in item["content"]["expected_result"]["statement"]
    assert len(item["content"]["assertions"][0]["expected_fields"]) == (1 if missing_field else 2)
    record = fake_grounding_record(payload)
    decision = next(i for i in record["review"]["items"] if i["item_id"] == "ER/1")
    # Both compound variants require separation, preserving the second fact.
    decision.update(single_fact=False, verdict="UNSUPPORTED", reason="Preserve both facts; split and cover both.")
    combined = grounding.attach_grounding_check(structural, grounding.check_review_record(payload, record))
    assert combined.status == CheckStatus.FAIL



def review_payload(stage="AGENT1"):
    request, analysis, requirements = cp1_combined_srs_case()
    if stage == "AGENT1":
        return grounding.build_grounding_input(stage, request, requirements, analysis)
    if stage == "AGENT2":
        return grounding.build_grounding_input(stage, request, requirements, cp2_valid_design(),
                                               analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG)
    case, plan, observation = structured_restoration_fixture()
    return grounding.build_grounding_input(stage, None, {}, plan, test_case=case, observation=observation)


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("mutation", ["none", "missing", "duplicate", "order", "unknown_id", "citation",
                                     "empty_citations", "unsupported", "uncertain", "hash", "stage", "contract"])
def test_grounding_coverage_evidence_and_decisions(stage, mutation):
    payload = review_payload(stage)
    record = fake_grounding_record(payload)
    items = record["review"]["items"]
    if mutation == "missing":
        items.pop()
    elif mutation == "duplicate":
        items.append(items[0])
    elif mutation == "order":
        items.reverse()
    elif mutation == "unknown_id":
        items[0]["item_id"] = "invented"
    elif mutation == "citation":
        items[0]["citations"][0]["quote"] = "THIS IS NOT IN ANY SOURCE"
    elif mutation == "empty_citations":
        items[0]["citations"] = []
    elif mutation in {"unsupported", "uncertain"}:
        items[0]["verdict"] = mutation.upper()
    elif mutation == "hash":
        payload["items"][0]["content"] = "changed after review"
    elif mutation == "stage":
        record["stage"] = "OTHER"
    elif mutation == "contract":
        record["contract"] = "unknown"
    if mutation in {"hash", "stage", "contract"}:
        with pytest.raises(ValueError, match="해시"):
            grounding.check_review_record(payload, record)
    else:
        result = grounding.check_review_record(payload, record)
        assert result.status == (CheckStatus.PASS if mutation == "none" else
                                 CheckStatus.REVIEW if mutation == "uncertain" else CheckStatus.FAIL)


@pytest.mark.parametrize("stage", ["AGENT2", "AGENT3"])
def test_compound_expected_result_review_cannot_be_treated_as_complete(stage):
    payload = review_payload(stage)
    record = fake_grounding_record(payload)
    index = next(i for i, entry in enumerate(payload["items"]) if entry["kind"] == "EXPECTED_RESULT")
    record["review"]["items"][index]["single_fact"] = False
    result = grounding.check_review_record(payload, record)
    assert result.status == CheckStatus.FAIL and "모든 검사를 보존" in result.message


@pytest.mark.parametrize("text", ["검색창에 장비 이름을 입력하고 검색 버튼을 누른다.",
                                  "설정 변경을 알리는 이메일이 발송된다.",
                                  "선택한 장비가 목록에서 사라진다."])
def test_unsupported_feature_is_reviewed_without_keyword_blacklist(text):
    request, analysis, requirements = cp1_combined_srs_case()
    design = cp2_valid_design()
    design.test_cases[0].steps.append(text)
    payload = grounding.build_grounding_input("AGENT2", request, requirements, design, analysis=analysis)
    record = fake_grounding_record(payload)
    index = next(i for i, item in enumerate(payload["items"]) if item["content"] == text)
    # Simulates a reviewer finding, NOT an actual API-generated finding.
    record["review"]["items"][index].update(verdict="UNSUPPORTED", reason="원문에 없는 기능")
    assert grounding.check_review_record(payload, record).status == CheckStatus.FAIL


def test_agent2_review_has_original_request_not_only_corrupted_analysis():
    request, analysis, requirements = cp1_combined_srs_case()
    analysis.confirmed_conditions[0].statement += " INVENTED_FEATURE"
    payload = grounding.build_grounding_input("AGENT2", request, requirements, cp2_valid_design(), analysis=analysis)
    assert "INVENTED_FEATURE" in json.dumps(payload["context"])
    assert "INVENTED_FEATURE" not in json.dumps(payload["source_documents"])
    assert any(d["source_id"] == "REQUEST/after_value" for d in payload["source_documents"])


def test_reviewer_prompt_allows_paraphrases_and_requested_but_unimplemented_features():
    instructions = grounding.REVIEW_INSTRUCTIONS
    for phrase in ("문체·동의어", "아직 없으면", "원문 근거를 대체하지", "일부만 맞는데",
                   "모두 검토할 데이터", "out_of_scope", "마침표·접속사 개수로 판정하지"):
        assert phrase in instructions
    request, analysis, requirements = cp1_combined_srs_case()
    request.after_value += " 검색 기능이 제공되어야 한다."
    payload = grounding.build_grounding_input("AGENT2", request, requirements, cp2_valid_design(), analysis=analysis)
    assert "검색 기능" in next(d["text"] for d in payload["source_documents"] if d["source_id"] == "REQUEST/after_value")
    assert grounding.check_review_record(payload, fake_grounding_record(payload)).status == CheckStatus.PASS


def test_review_input_excludes_catalog_paths_and_ui_filename():
    from dataclasses import replace
    request, analysis, requirements = cp1_combined_srs_case()
    entry = replace(pipeline.EXISTING_REGRESSION_CATALOG[0], automation_file="C:/private/secret.py",
                    test_case_file="C:/private/test.json")
    payload = grounding.build_grounding_input("AGENT2", request, requirements, cp2_valid_design(),
                                             analysis=analysis, catalog=(entry,))
    assert "C:/private" not in json.dumps(payload)
    case, plan, observation = structured_restoration_fixture()
    observation.target_file = "C:/private/product.html"
    payload = grounding.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=observation)
    assert "C:/private" not in json.dumps(payload)


@pytest.mark.parametrize("result_kind", ["valid", "refusal", "error"])
def test_real_reviewer_adapter_with_fake_sdk(result_kind):
    payload = review_payload()
    calls = []
    def parse(**kwargs):
        calls.append(kwargs)
        if result_kind == "error":
            raise RuntimeError("transport unavailable")
        return SimpleNamespace(output_parsed=None if result_kind == "refusal" else
            grounding.GroundingReview.model_validate(fake_grounding_record(payload)["review"]),
            id="response-review", usage=SimpleNamespace(input_tokens=7, output_tokens=3, total_tokens=10))
    reviewer = grounding.OpenAIGroundingReviewer(model="test-model",
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    if result_kind == "valid":
        record = reviewer.review(payload)
        assert record["usage"]["total_tokens"] == 10
        assert grounding.check_review_record(payload, record).status == CheckStatus.PASS
    else:
        with pytest.raises((RuntimeError, ValueError)):
            reviewer.review(payload)
    assert len(calls) == 1 and calls[0]["store"] is False
    assert calls[0]["text_format"] is grounding.GroundingReview


@pytest.mark.parametrize("outcome", ["supported", "repair", "unresolved", "uncertain", "error"])
def test_agent1_grounding_controls_rewrite_handoff_and_cost(tmp_path, monkeypatch, outcome):
    request, analysis, _ = cp1_combined_srs_case()
    generation_calls, reviews = [], []
    def analyze(*args, **kwargs):
        generation_calls.append(kwargs)
        return pipeline.Agent1Response(analysis=analysis.model_copy(deep=True), response_id=None,
            model="fake", usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    def review(payload):
        reviews.append(payload)
        if outcome == "error":
            raise RuntimeError("review failed")
        verdict = "UNSUPPORTED" if outcome == "unresolved" or (outcome == "repair" and len(reviews) == 1) else (
            "UNCERTAIN" if outcome == "uncertain" else "SUPPORTED")
        result = fake_grounding_record(payload, verdict=verdict)
        result["usage"] = {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
        return result
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent1", lambda **kw: SimpleNamespace(analyze=analyze))
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer", lambda **kw: SimpleNamespace(review=review))
    request_file = tmp_path / "request.json"
    _write_json(request_file, request.model_dump(mode="json"))
    args = SimpleNamespace(request=str(request_file), srs=str(REPO_ROOT / "docs/01_PRODUCT_SRS.md"),
                           runs_root=str(tmp_path / "runs"), model="fake")
    assert pipeline.run_agent1(args) == (1 if outcome == "error" else 0 if outcome in {"supported", "repair"} else 2)
    run = next((tmp_path / "runs").iterdir())
    expected_calls = 2 if outcome in {"repair", "unresolved"} else 1
    assert len(generation_calls) == len(reviews) == expected_calls
    if outcome == "error":
        receipt = pipeline._read_json_payload(run / "agent1_generation_usage_attempt_1.json")
        assert receipt["usage"]["total_tokens"] == 15
        assert (run / "agent1_grounding_error_attempt_1.json").is_file()
        assert (run / "agent1_change_analysis_attempt_1.json").is_file()
        assert not (run / "run_manifest.json").exists()
        return
    manifest = pipeline._read_json_payload(run / "run_manifest.json")
    assert manifest["usage"]["total_tokens"] == 21 * expected_calls
    assert len(manifest["grounding_reviews"]) == expected_calls
    if outcome in {"supported", "repair"}:
        pipeline._load_verified_agent1_run(run, run.name)
        path = run / "agent1_grounding_review.json"
        original = pipeline._read_json_payload(path)
        _write_json(path, {**original, "input_sha256": "wrong"})
        manifest["grounding_review_sha256"] = _sha256_file(path)
        _write_json(run / "run_manifest.json", manifest)
        with pytest.raises(ValueError, match="해시"):
            pipeline._load_verified_agent1_run(run, run.name)
    else:
        with pytest.raises(ValueError):
            pipeline._load_verified_agent1_run(run, run.name)


@pytest.mark.parametrize("stage,version", [("AGENT1", "2.11"), ("AGENT2", "3.11"), ("AGENT2", "3.12"), ("AGENT3", "4.9"), ("AGENT3", "4.10")])
@pytest.mark.parametrize("mutation", ["missing_marker", "missing_file", "changed_hash", "downgrade", "unsupported"])
def test_review_artifact_required_on_new_handoff(tmp_path, stage, version, mutation):
    payload = review_payload(stage)
    record = fake_grounding_record(payload, verdict="UNSUPPORTED" if mutation == "unsupported" else "SUPPORTED")
    path = tmp_path / f"{stage.lower()}_grounding_review.json"
    if mutation != "missing_file":
        _write_json(path, record)
    manifest = {"contract_version": version, "grounding_contract": "1.0",
                "grounding_review_sha256": _sha256_file(path) if path.exists() else "0" * 64}
    if mutation == "missing_marker":
        manifest.pop("grounding_contract")
    elif mutation == "changed_hash":
        manifest["grounding_review_sha256"] = "0" * 64
    elif mutation == "downgrade":
        manifest.update(contract_version="old", grounding_contract=None, grounding_review_sha256=None)
    checkpoint = pipeline.Checkpoint2Result(status="PASS", checks=[pipeline.CheckResult(rule_id="base", status="PASS", message="ok")])
    if mutation == "unsupported":
        assert pipeline_execution._load_grounding_review(tmp_path, manifest, stage, version, payload, checkpoint).status == CheckStatus.FAIL
    else:
        with pytest.raises(ValueError):
            pipeline_execution._load_grounding_review(tmp_path, manifest, stage, version, payload, checkpoint)


@pytest.mark.parametrize("stage", ["AGENT2", "AGENT3"])
@pytest.mark.parametrize("outcome", ["unsupported", "uncertain", "error"])
def test_review_blocks_agent2_handoff_and_agent3_trial(tmp_path, monkeypatch, stage, outcome):
    """Run real CLI branch orchestration with scripted generator/reviewer outputs."""
    run_id = "RUN-20260924-120000-ABCDEF"
    run = tmp_path / run_id
    _write_json(run / "run_manifest.json", {})
    calls = []
    def review(payload):
        calls.append("review")
        if outcome == "error":
            raise RuntimeError("unavailable reviewer")
        return fake_grounding_record(payload, verdict=outcome.upper())
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer", lambda **kw: SimpleNamespace(review=review))
    if stage == "AGENT2":
        request, analysis, requirements = cp1_combined_srs_case()
        source = {"contract_version": "2.11", "wording_policy": "STRUCTURAL_ONLY_V1",
                  **{key: "a" * 64 for key in ("request_sha256", "srs_sha256", "agent1_analysis_sha256", "checkpoint1_sha256")}}
        monkeypatch.setattr(pipeline_execution, "_load_verified_agent1_run",
                            lambda *_: (request, requirements, analysis, None, source))
        def design(*args, **kwargs):
            calls.append("generate")
            return pipeline.Agent2Response(design=cp2_valid_design(), model="fake", response_id=None, usage={})
        monkeypatch.setattr(pipeline_execution, "OpenAIAgent2", lambda **kw: SimpleNamespace(design=design))
        # This branch test supplies structural PASS. Structural guards have their own tests.
        monkeypatch.setattr(pipeline_execution, "evaluate_checkpoint2", lambda *a, **kw:
            pipeline.Checkpoint2Result(status="PASS", checks=[pipeline.CheckResult(rule_id="base", status="PASS", message="fixture")]))
        code = pipeline.run_agent2(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path), model="fake",
            approved_assets_root=str(tmp_path / "empty-approved")))
        path = run / "checkpoint2.json"
    else:
        case, plan, observation = structured_restoration_fixture()
        _write_json(run / "agent2_manifest.json", {})
        target = tmp_path / "target.html"
        _write_text_atomic(target, "<!doctype html><title>fixture</title>")
        observation.target_sha256 = _sha256_file(target)
        monkeypatch.setattr(pipeline_execution, "_load_verified_agent2_run", lambda *_:
            (None, {}, None, SimpleNamespace(test_cases=[case]), None, {"agent2_design_sha256": "a" * 64}))
        monkeypatch.setattr(pipeline_execution, "inspect_target_ui", lambda *a, **kw: observation)
        def generate(*args, **kwargs):
            calls.append("generate")
            return pipeline.Agent3Response(plan=plan, model="fake", response_id=None, usage={})
        monkeypatch.setattr(pipeline_execution, "OpenAIAgent3", lambda **kw: SimpleNamespace(plan=generate))
        monkeypatch.setattr(pipeline_execution, "run_candidate_trial", lambda *a, **kw: pytest.fail("Unreviewed plan executed"))
        code = pipeline.run_agent3(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path), tc_id=case.tc_id,
            target_html=str(target), model="fake", timeout=30))
        path = run / "checkpoint3.json"
    assert code == (1 if outcome == "error" else 2)
    if outcome == "error":
        receipt = pipeline._read_json_payload(run / f"{stage.lower()}_generation_usage_attempt_1.json")
        assert receipt["usage"] is None  # Unknown is not zero.
    assert calls == (["generate", "review"] * (2 if outcome == "unsupported" else 1))
    if outcome != "error":
        assert pipeline._read_json_payload(path)["status"] == ("FAIL" if outcome == "unsupported" else "REVIEW")
        if stage == "AGENT3":
            assert "근거·검사 연결 검토" in pipeline_orchestrator._agent3_run_entry(run, case.tc_id, run, code)["reason"]
    assert not (run / "agent3_trial.json").exists()


def test_structural_failure_does_not_make_an_extra_review_call(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer", lambda **kw: pytest.fail("unnecessary call"))
    checkpoint = pipeline.Checkpoint2Result(status="FAIL", checks=[pipeline.CheckResult(rule_id="base", status="FAIL", message="bad ID")])
    records = []
    result = pipeline_execution._run_grounding_review(tmp_path, "AGENT2", 1, review_payload("AGENT2"), checkpoint, "fake", records)
    assert result.status == CheckStatus.FAIL and records == []


def test_uncertain_atomicity_pauses_instead_of_being_rewritten():
    payload = review_payload("AGENT2")
    record = fake_grounding_record(payload)
    index = next(i for i, entry in enumerate(payload["items"]) if entry["kind"] == "EXPECTED_RESULT")
    record["review"]["items"][index].update(verdict="UNCERTAIN", single_fact=False)
    assert grounding.check_review_record(payload, record).status == CheckStatus.REVIEW
    record["review"]["items"][0].update(verdict="UNSUPPORTED", reason="별도 수정 가능한 문제")
    assert grounding.check_review_record(payload, record).status == CheckStatus.REVIEW


@pytest.mark.parametrize("module_name,class_name", [
    ("qa_pipeline_agent1", "OpenAIAgent1"), ("qa_pipeline_agent2", "OpenAIAgent2"),
    ("qa_pipeline_agent3", "OpenAIAgent3"), ("qa_pipeline_grounding", "OpenAIGroundingReviewer")])
def test_model_clients_do_not_silently_retry_transport(monkeypatch, module_name, class_name):
    import importlib
    module = importlib.import_module(module_name)
    calls = []
    monkeypatch.setenv("OPENAI_API_KEY", "unit-test-placeholder-not-a-key")
    monkeypatch.setattr(module, "OpenAI", lambda **kwargs: calls.append(kwargs) or object())
    getattr(module, class_name)(model="unit-test")
    assert calls == [{"max_retries": 0}]


def test_citations_preserve_multiline_and_quoted_original_text():
    request, analysis, requirements = cp1_combined_srs_case()
    note = '첫째 줄: "온도"\n둘째 줄: 값을 확인합니다.'
    request.acceptance_notes.append(note)
    payload = grounding.build_grounding_input("AGENT1", request, requirements, analysis)
    source = next(d for d in payload["source_documents"] if d["text"] == note)
    record = fake_grounding_record(payload)
    record["review"]["items"][0]["citations"] = [{"source_id": source["source_id"], "quote": note}]
    assert grounding.check_review_record(payload, record).status == CheckStatus.PASS


@pytest.mark.parametrize("verdict,expected", [("SUPPORTED", "REVIEW"), ("UNCERTAIN", "REVIEW"), ("UNSUPPORTED", "FAIL")])
def test_extension_review_checks_reasons_not_prohibited_assertions(verdict, expected):
    case, plan, observation = structured_restoration_fixture()
    plan = pipeline.Agent3AutomationPlan(tc_id=case.tc_id, target_device_id=1,
        summary="지원 확장 검토", planning_status="AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
        extension_reasons=["TC에 필요한 관찰을 현재 화면 정보로 연결할 수 없습니다."])
    payload = grounding.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=observation)
    assert [item["kind"] for item in payload["items"]] == ["SUPPORT_EXTENSION"]
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    result = grounding.attach_grounding_check(checkpoint,
        grounding.check_review_record(payload, fake_grounding_record(payload, verdict=verdict)))
    assert result.status.value == expected
    if expected == "REVIEW":
        assert result.candidate_status.value == "AUTOMATION_SUPPORT_EXTENSION_REQUIRED"
    else:
        assert result.candidate_status.value == "REVISION_REQUIRED"
    plan.tc_id = "TC-CAND-999"
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL


@pytest.mark.parametrize("stage", [1, 2, 3])
def test_generator_exception_body_is_not_exposed(stage):
    marker = "SYNTHETIC_PRIVATE_ERROR_BODY"
    def fail(**kwargs):
        raise RuntimeError(marker)
    client = SimpleNamespace(responses=SimpleNamespace(parse=fail))
    request, analysis, requirements = cp1_combined_srs_case()
    case, plan, observation = structured_restoration_fixture()
    agent = getattr(pipeline, f"OpenAIAgent{stage}")(model="fake", client=client)
    with pytest.raises(Exception) as caught:
        if stage == 1:
            agent.analyze(request, requirements)
        elif stage == 2:
            agent.design(request, analysis, requirements)
        else:
            agent.plan(case, observation, requirements)
    import traceback
    formatted = "".join(traceback.format_exception(caught.type, caught.value, caught.tb))
    assert marker not in formatted
    assert "RuntimeError" in str(caught.value)


def test_invalid_review_record_still_preserves_received_usage(tmp_path, monkeypatch):
    payload = review_payload()
    record = fake_grounding_record(payload)
    record.update(input_sha256="wrong", usage={"total_tokens": 30})
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer",
                        lambda **kw: SimpleNamespace(review=lambda _: record))
    checkpoint = pipeline.Checkpoint2Result(status="PASS", checks=[
        pipeline.CheckResult(rule_id="base", status="PASS", message="fixture")])
    with pytest.raises(ValueError):
        pipeline_execution._run_grounding_review(tmp_path, "AGENT1", 1, payload, checkpoint, "fake", [])
    receipt = pipeline._read_json_payload(tmp_path / "agent1_review_usage_attempt_1.json")
    assert receipt["usage"]["total_tokens"] == 30
