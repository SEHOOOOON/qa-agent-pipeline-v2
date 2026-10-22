"""Transport/contract/branch tests. Scripted judgments do not measure model accuracy."""
from pipeline_test_support import *

def focused_agent2_payload(design=None):
    """The current Agent 2 review input (focused design review)."""
    return grounding.build_grounding_input("AGENT2", cp1_request(), cp2_requirements(),
        design or cp2_valid_design(), analysis=cp2_analysis())


@pytest.mark.parametrize("category", ["CONDITION_COVERAGE", "TC_DESIGN", "PROCEDURE_COVERAGE", "coverage_summary"])
@pytest.mark.parametrize("verdict,status", [("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_focused_review_keeps_essential_verdicts_blocking(category, verdict, status):
    # Scripted verdict handling, not the AI's ability to detect these defects.
    payload = focused_agent2_payload()
    record = fake_grounding_record(payload)
    target = next(i["item_id"] for i in payload["items"] if i["kind"] == category or i["item_id"] == category)
    item = next(i for i in record["review"]["items"] if i["item_id"] == target)
    item.update(verdict=verdict, reason="준비한 대역 판정: 대상·값·조작 후 관찰 연결 확인")
    assert grounding.check_review_record(payload, record).status.value == status


@pytest.mark.parametrize("defect", ["missing_item", "duplicate_item", "invalid_source", "changed_input"])
def test_focused_review_does_not_bypass_review_integrity(defect):
    payload = focused_agent2_payload()
    record = fake_grounding_record(payload)
    items = record["review"]["items"]
    if defect == "missing_item":
        items.pop()
    elif defect == "duplicate_item":
        items.append(dict(items[0]))
    elif defect == "invalid_source":
        items[0]["citations"][0]["source_id"] = "UNKNOWN"
    else:
        record["input_sha256"] = "0" * 64
    with pytest.raises(ValueError):
        grounding.check_review_record(payload, record)


def test_focused_review_uses_short_stage_specific_instructions_and_pins_them():
    payload = focused_agent2_payload()
    sent = []
    def parse(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(output_parsed=None)
    with pytest.raises(ValueError, match="구조화 응답"):
        grounding.OpenAIGroundingReviewer(model="fake", client=SimpleNamespace(
            responses=SimpleNamespace(parse=parse))).review(payload)
    instructions = sent[0]["input"][0]["content"]
    focused = grounding.FOCUSED_AGENT2_REVIEW_INSTRUCTIONS
    assert instructions.startswith(focused + "\n" + grounding.COMPACT_REVIEW_GUIDANCE)
    assert len(focused) < len(grounding.REVIEW_INSTRUCTIONS)
    assert "조작보다 앞선 확인" in focused and "후속 관찰" in focused
    assert "AGENT3:" not in focused and "AGENT1:" not in focused
    assert sent[0]["prompt_cache_key"] == "qa-v2-grounding-1-23"
    assert sent[0]["store"] is False
    assert next(d["text"] for d in payload["source_documents"]
                if d["source_id"] == "FOCUSED_DESIGN_REVIEW") == focused


@pytest.mark.parametrize("field,initial,target", [
    ("status", "OPERATION", "STOP"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "HIGH", "LOW"), ("setTemp", 29, 22), ("locked", False, True)])
@pytest.mark.parametrize("variant", ["normal", "wrong_value", "wrong_target", "early_observation", "missing_check"])
def test_focused_review_preserves_control_variants_without_silently_repairing(field, initial, target, variant):
    from qa_pipeline_agent2 import _normalize_agent2_live_design
    case = repeated_restoration_fixture(field, initial, target)
    design, _ = _normalize_agent2_live_design(cp2_valid_design().model_copy(update={"test_cases": [case]}))
    case = design.test_cases[0]
    check = case.execution_spec.verifications[0]
    if variant == "wrong_value":
        check.expected_fields[0].expected_value = "UNAPPROVED"
    elif variant == "wrong_target":
        check.target = "internal.unrelated"
    elif variant == "early_observation":
        check.after_action_id = case.execution_spec.operations[0].action_id
    elif variant == "missing_check":
        case.execution_spec.verifications.pop()
    before = design.model_dump(mode="json")
    payload = focused_agent2_payload(design)
    # The whole TC is reviewed once (by reference to the identical context copy).
    assert next(i["content"] for i in payload["items"] if i["kind"] == "TC_DESIGN") == {"tc_ref": "TC/0"}
    assert payload["context"]["TC/0"] == before["test_cases"][0]
    assert design.model_dump(mode="json") == before
    # Input preservation does NOT assert that an actual AI detects the fault.


def test_focused_review_keeps_conditions_when_no_new_test_covers_them():
    design = cp2_valid_design().model_copy(update={"test_cases": [], "related_existing_tests": []})
    payload = focused_agent2_payload(design)
    conditions = [i for i in payload["items"] if i["kind"] == "CONDITION_COVERAGE"]
    assert len(conditions) == len(cp2_analysis().confirmed_conditions)
    assert all(i["content"]["candidate_tests"] == [] for i in conditions)
    assert all(i["content"]["existing_selections"] == [] for i in conditions)


@pytest.mark.parametrize("rewrite", [False, True])
def test_human_examples_same_reference_reaches_writer_rewriter_and_reviewer(rewrite):
    from qa_pipeline_agent2 import OpenAIAgent2, Agent2Error
    from qa_pipeline_contracts import QA_HUMAN_JUDGMENT_EXAMPLES
    sent = []
    def parse(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(output_parsed=None)
    client = SimpleNamespace(responses=SimpleNamespace(parse=parse))
    with pytest.raises(Agent2Error):
        OpenAIAgent2(model="fake", client=client).design(cp1_request(), cp2_analysis(), cp2_requirements(),
            previous_design=cp2_valid_design() if rewrite else None,
            checkpoint_feedback=["필수 관찰 누락"] if rewrite else None)
    payload = focused_agent2_payload()
    with pytest.raises(ValueError, match="구조화 응답"):
        grounding.OpenAIGroundingReviewer(model="fake", client=client).review(payload)
    assert len(sent) == 2
    for call in sent:
        assert QA_HUMAN_JUDGMENT_EXAMPLES in call["input"][0]["content"]
    assert payload["context"]["human_judgment_examples"] == QA_HUMAN_JUDGMENT_EXAMPLES
    assert sent[0]["prompt_cache_key"] == "qa-v2-agent2-2-62-rules-6"
    assert sent[1]["prompt_cache_key"] == "qa-v2-grounding-1-23"


@pytest.mark.parametrize("verdict,status", [("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_human_examples_never_override_a_blocking_review(verdict, status):
    payload = focused_agent2_payload()
    record = fake_grounding_record(payload)
    record["review"]["items"][0].update(verdict=verdict, reason="대역: 현재 요청의 검사 누락")
    assert grounding.check_review_record(payload, record).status.value == status


def test_human_examples_changed_reference_is_rejected_before_api():
    payload = focused_agent2_payload()
    payload["context"]["human_judgment_examples"] = "무조건 통과"
    client = SimpleNamespace(responses=None)
    with pytest.raises(ValueError, match="사람 판단"):
        grounding.OpenAIGroundingReviewer(model="fake", client=client).review(payload)


@pytest.mark.parametrize("outcome", [
    "clean", "repair", "unresolved", "uncertain", "no_rewrite",
    "review_error", "invalid_review", "rewrite_error", "second_review_error",
    "second_review_uncertain",
])
def test_agent2_semantic_rework_feedback_and_stop_boundaries(tmp_path, monkeypatch, outcome):
    """Scripted branch/transport evidence, not actual model recovery accuracy."""
    from qa_pipeline_agent2 import OpenAIAgent2
    run_id = "RUN-20261010-210000-ABCDEF"
    run = tmp_path / run_id
    _write_json(run / "run_manifest.json", {})
    request, analysis, requirements = cp1_combined_srs_case()
    source = {"contract_version": "2.11", "wording_policy": "STRUCTURAL_ONLY_V1",
              **{k: "a" * 64 for k in (
                  "request_sha256", "srs_sha256", "agent1_analysis_sha256", "checkpoint1_sha256")}}
    monkeypatch.setattr(pipeline_execution, "_load_verified_agent1_run",
                        lambda *_: (request, requirements, analysis, None, source))
    # Structure is tested elsewhere. Here a semantically incomplete draft has valid links.
    monkeypatch.setattr(pipeline_execution, "evaluate_checkpoint2", lambda *a, **kw:
        pipeline.Checkpoint2Result(status="PASS", checks=[
            pipeline.CheckResult(rule_id="base", status="PASS", message="scripted structural pass")]))
    reason = "시험 조작 이후 적용과 화면·내부값 확인이 빠졌습니다. 이전 적용의 확인으로 대체하지 마세요."
    generated, reviews, sent, events = [], [], [], []
    original = cp2_valid_design()
    class Capture:
        def parse(self, **kw):
            sent.append(kw)
            raise RuntimeError("offline capture only")
    def design(req, a1, srs, **kwargs):
        events.append("generate")
        generated.append(kwargs)
        if len(generated) == 2:
            assert kwargs["previous_design"] == original
            assert any(reason in line for line in kwargs["checkpoint_feedback"])
            assert any("base PASS" in line for line in kwargs["checkpoint_feedback"])
            # Exercise the real prompt assembly up to an offline transport boundary.
            with pytest.raises(Exception, match="모델 호출"):
                OpenAIAgent2(model="offline", client=SimpleNamespace(responses=Capture())).design(
                    req, a1, srs, **kwargs)
            message = sent[-1]["input"][1]["content"]
            assert reason in message and "이전 TC 후보" in message
            assert req.after_value in message
            assert "전체 test_cases와 관련_기존_TC" in message
            if outcome == "rewrite_error":
                raise RuntimeError("scripted generation transport error")
        result = original.model_copy(deep=True)
        if len(generated) == 2:
            result.coverage_summary = "scripted revised draft, not actual model correction"
        return pipeline.Agent2Response(design=result, model="offline", response_id="scripted",
            usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15})
    def review(payload):
        events.append("review")
        reviews.append(payload)
        if outcome == "review_error" or (outcome == "second_review_error" and len(reviews) == 2):
            raise RuntimeError("scripted reviewer transport error")
        record = fake_grounding_record(payload)
        record["usage"] = {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
        if outcome == "invalid_review":
            record["review"]["items"].pop()
            return record
        target = next((x for x in payload["items"] if x["kind"] == "CONDITION_COVERAGE"), payload["items"][0])
        item = next(x for x in record["review"]["items"] if x["item_id"] == target["item_id"])
        if outcome == "uncertain" or (outcome == "second_review_uncertain" and len(reviews) == 2):
            item.update(verdict="UNCERTAIN", reason="필요한 정책의 뜻을 확정할 수 없음")
        elif outcome != "clean" and (len(reviews) == 1 or outcome == "unresolved"):
            item.update(verdict="UNSUPPORTED", reason=reason)
        return record
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent2",
                        lambda **kw: SimpleNamespace(design=design))
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer",
                        lambda **kw: SimpleNamespace(review=review))
    error = outcome in {"review_error", "invalid_review", "rewrite_error", "second_review_error"}
    success = outcome in {"clean", "repair"}
    assert pipeline.run_agent2(SimpleNamespace(
        run_id=run_id, runs_root=str(tmp_path), model="offline",
        approved_assets_root=str(tmp_path / "empty-approved"),
        no_rewrite=outcome == "no_rewrite")) == (1 if error else 0 if success else 2)
    expected_generations = 2 if outcome in {
        "repair", "unresolved", "rewrite_error", "second_review_error", "second_review_uncertain"} else 1
    assert len(generated) == expected_generations
    assert len(reviews) == expected_generations - (outcome == "rewrite_error")
    assert events == (["generate", "review"] * expected_generations)[:len(events)]
    first = pipeline._read_json_payload(run / "agent2_test_design_attempt_1.json")
    assert pipeline.Agent2TestDesign.model_validate(first) == original
    if expected_generations == 2:
        rejected = pipeline._read_json_payload(run / "checkpoint2_attempt_1.json")
        assert rejected["status"] == "FAIL"
        assert any(reason in x["message"] for x in rejected["checks"])
        initial_review = pipeline._read_json_payload(run / "agent2_grounding_review_attempt_1.json")
        assert any(x["verdict"] == "UNSUPPORTED" for x in initial_review["review"]["items"])
    if error:
        assert (run / "agent2_error.json").exists()
        assert not (run / "agent2_manifest.json").exists()
        assert (run / "agent2_in_progress.json").exists()
        return
    manifest = pipeline._read_json_payload(run / "agent2_manifest.json")
    assert len(manifest["attempts"]) == expected_generations
    assert manifest["usage"]["total_tokens"] == 21 * expected_generations
    assert manifest["rewrite_policy"] == ("NONE" if outcome == "no_rewrite" else "ONCE_ON_FAIL")
    assert not (run / "agent2_in_progress.json").exists()
    assert not (run / "agent2_error.json").exists()
    final = pipeline._read_json_payload(run / "checkpoint2.json")
    assert final["status"] == ("PASS" if success else "REVIEW" if "uncertain" in outcome else "FAIL")
    if expected_generations == 2:
        assert manifest["attempts"][0]["status"] == "FAIL"
        assert reviews[0] != reviews[1], "Rewritten draft must receive a fresh review input"


@pytest.mark.parametrize("control", ["power", "mode", "temperature", "fan", "lock"])
@pytest.mark.parametrize("verdict,expected", [("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_shared_guidance_does_not_override_semantic_verdict(control, verdict, expected):
    # Scripted verdict preservation across labels, not model accuracy.
    request = cp1_request().model_copy(update={"reason": "검증 관제점: " + control})
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(),
        cp2_valid_design(), analysis=cp2_analysis())
    record = fake_grounding_record(payload, verdict=verdict)
    assert grounding.check_review_record(payload, record).status.value == expected


@pytest.mark.parametrize("verdict,expected", [("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_essential_policy_keeps_required_semantic_verdict(verdict, expected):
    payload = grounding.build_grounding_input("AGENT2", cp1_request(), cp2_requirements(),
        cp2_valid_design(), analysis=cp2_analysis())
    record = fake_grounding_record(payload, verdict=verdict)
    # A combined observation alone is not an omitted test. An unsupported
    # meaning or unknown requirement still stops. These are scripted verdicts.
    for item in record["review"]["items"]:
        item["single_fact"] = False
    result = grounding.check_review_record(payload, record)
    assert result.status.value == expected
    changed = {**payload, "essential_validation_contract": None}
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(changed, record)


@pytest.mark.parametrize("strategy,expected", [
    ("UI_TEMPERATURE", 21), ("INTERNAL_SET_TEMP", 21),
    ("INTERNAL_DEVICE_FIELDS_EQUALS", {"mode": "HEAT"}),
    ("CONTROLLER_UI_FIELDS_EQUALS", {"mode": "HEAT"}),
    ("TOAST_VISIBLE", True), ("CONTROLS_DISABLED", [False, False]),
    ("DISABLED_TEMPERATURE_TEXT", "---"), ("UI_TEXT_CONTAINS", "ready"),
    ("UI_VALUE_EQUALS", "False"), ("UI_CHECKED_EQUALS", False),
    ("UI_ENABLED_EQUALS", False), ("INTERNAL_VALUE_EQUALS", False),
])
def test_reader_facts_preserve_effective_expectation_and_anchor(strategy, expected):
    from qa_pipeline_agent3 import _assertion_reader_facts
    assertion = pipeline.AutomationAssertion(result_id="ER-001", observation_layer="UI",
        strategy=strategy, selector="#observed", expected_number=21, expected_text="ready",
        expected_value=False, expected_fields=[{"field_name": "mode", "expected_value": "HEAT"}],
        after_action_id="ACT-005")
    before = assertion.model_dump()
    facts = _assertion_reader_facts(assertion, 1)
    assert facts["effective_expected"] == expected
    assert facts["after_action_id"] == "ACT-005"
    assert facts["plan_anchor"] == "#observed"
    assert assertion.model_dump() == before


def test_every_supported_strategy_has_reader_semantics_including_fixed_toast_rules():
    from qa_pipeline_agent3 import _ASSERTION_READER_SEMANTICS, _assertion_reader_facts, _BLOCKING_TOAST_ACTUAL_TERMS
    assert set(_ASSERTION_READER_SEMANTICS) == set(pipeline.AssertionStrategy)
    assertion = pipeline.AutomationAssertion(result_id="ER-001", observation_layer="UI",
        strategy="TOAST_BLOCKING", selector="#global-toast", after_action_id="ACT-002")
    facts = _assertion_reader_facts(assertion, 1)
    assert facts["comparison"] == "visible_and_any_term"
    assert facts["effective_expected"] == {"visible": True, "any_text_term": list(_BLOCKING_TOAST_ACTUAL_TERMS)}


@pytest.mark.parametrize("fault,value", [("expected_fields", [{"field_name": "mode", "expected_value": "DRY"}]),
    ("selector", "#device-card-2"), ("after_action_id", "ACT-099")])
def test_reader_facts_do_not_hide_wrong_plan_value_target_or_timing(fault, value):
    from qa_pipeline_agent3 import execution_interface_facts
    case, plan = mapped_tc_fixture("mode", "COOL", "HEAT")
    observation = generic_control_guard_fixture()[2]
    changed = plan.model_copy(deep=True)
    data = changed.assertions[0].model_dump()
    data[fault] = value
    changed.assertions[0] = pipeline.AutomationAssertion.model_validate(data)
    assert execution_interface_facts(changed, observation) != execution_interface_facts(plan, observation)
    assert pipeline.tc_plan_handoff_errors(case, changed)


@pytest.mark.parametrize("fault", ["missing_restore", "wrong_value", "unsupported", "read_only", "wrong_source", "no_spec"])
def test_agent2_recovery_facts_are_not_fabricated(fault):
    from qa_pipeline_agent3 import controller_recovery_tc_facts
    case, _ = mapped_tc_fixture("fanSpeed", "MED", "LOW")
    restore = case.execution_spec.operations[-1]
    if fault == "missing_restore": case.execution_spec.operations.pop()
    elif fault == "wrong_value": restore.value = 16
    elif fault == "unsupported": restore.target = "unsupported.automatic_switch"
    elif fault == "read_only": case.state_effect = pipeline.TcStateEffect.READ_ONLY
    elif fault == "wrong_source": restore.source_text = "원문에 없는 복원"
    else: case.execution_spec = None
    assert controller_recovery_tc_facts(case) is None


@pytest.mark.parametrize("fault", ["missing_select", "late_select", "wrong_target", "unsupported_select", "missing_restore"])
def test_agent2_baseline_order_never_promises_invalid_selection_or_recovery(fault):
    from qa_pipeline_agent3 import controller_recovery_tc_facts
    case, _ = mapped_tc_fixture("setTemp", 28, 23)
    operations = case.execution_spec.operations
    if fault == "missing_select":
        operations.pop(0)
    elif fault == "late_select":
        operations[0], operations[1] = operations[1], operations[0]
    elif fault == "wrong_target":
        operations[0].value = 4
    elif fault == "unsupported_select":
        operations[0].target = "unsupported.other_device"
    else:
        operations.pop()
    before = case.model_dump(mode="json")
    facts = controller_recovery_tc_facts(case, include_baseline_order=True)
    assert facts is None or facts.get("baseline_capture_order") is None
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    payload = focused_agent2_payload(design)
    recovery = payload["context"].get("compiler_recovery_facts", {}).get("TC/0", {}).get("controller_recovery")
    assert recovery is None or recovery.get("baseline_capture_order") is None
    assert case.model_dump(mode="json") == before


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("selection", ["exact", "multiple", "parent", "joined", "unknown"])
def test_live_source_schema_only_accepts_exact_original_ids(stage, selection):
    payload = review_payload(stage)
    payload["source_documents"] = [
        {"source_id": "APPROVED_TC/execution_spec/operations/2/value", "text": "27"},
        {"source_id": "SRS/REQ-TEMP-001/description", "text": " 16~30°C \n"}]
    original = json.dumps(payload, ensure_ascii=False)
    ids = [d["source_id"] for d in payload["source_documents"]]
    selected = {"exact": ids[:1], "multiple": ids, "parent": [ids[0].rsplit("/", 1)[0]],
                "joined": [" | ".join(ids)], "unknown": ["SRS/OTHER"]}[selection]
    data = dict(items=[dict(item_id="ER/0", verdict="SUPPORTED", single_fact=True,
                           source_ids=selected, reason="local schema test")])
    model = grounding.source_selection_schema(payload)
    if selection in {"exact", "multiple"}:
        parsed = model.model_validate(data)
        review = grounding.bind_review_sources(payload, parsed)
        assert [c.source_id for c in review.items[0].citations] == selected
        assert [c.quote for c in review.items[0].citations] == [
            d["text"] for d in payload["source_documents"] if d["source_id"] in selected]
    else:
        with pytest.raises(ValueError):
            model.model_validate(data)
    assert json.dumps(payload, ensure_ascii=False) == original


@pytest.mark.parametrize("count", [1, 250, 251, 456, 997])
def test_live_source_schema_strict_sdk_enum_limits_and_complete_ids(count):
    from openai.lib._pydantic import to_strict_json_schema
    ids = ["APPROVED_TC/execution_spec/precondition_verifications/" + str(i) + "/expected_value"
           for i in range(count)]
    model = grounding.source_selection_schema(dict(source_documents=[
        dict(source_id=s, text="原文 그대로") for s in ids]))
    schema = to_strict_json_schema(model)
    field = schema["$defs"]["BoundReviewSourceSelection"]["properties"]["source_ids"]["items"]
    branches = field.get("anyOf", [field])
    values = [v for branch in branches for v in branch.get("enum", [branch.get("const")])]
    assert values == ids
    assert all(len(branch.get("enum", [branch.get("const")])) <= 250 for branch in branches)
    assert schema["$defs"]["BoundReviewSourceSelection"]["additionalProperties"] is False
    for source_id in (ids[0], ids[-1]):
        model.model_validate(dict(items=[dict(item_id="ER/0", verdict="SUPPORTED",
            single_fact=True, source_ids=[source_id], reason="test")]))


@pytest.mark.parametrize("invalid", ["empty", "duplicate", "blank", "characters"])
def test_live_source_schema_invalid_or_oversized_catalog_stops_before_call(invalid):
    documents = [dict(source_id="A", text="original")]
    if invalid == "empty":
        documents = []
    elif invalid == "duplicate":
        documents *= 2
    elif invalid == "blank":
        documents[0]["source_id"] = " "
    else:
        documents[0]["source_id"] = "x" * 120001
    calls = []
    reviewer = grounding.OpenAIGroundingReviewer(model="test", client=SimpleNamespace(
        responses=SimpleNamespace(parse=lambda **kw: calls.append(kw))))
    with pytest.raises(ValueError):
        reviewer.review(dict(source_documents=documents))
    assert calls == []


def test_live_source_schema_is_request_local_and_uncertain_can_have_no_sources():
    a = grounding.source_selection_schema(dict(source_documents=[dict(source_id="A", text="a")]))
    b = grounding.source_selection_schema(dict(source_documents=[dict(source_id="B", text="b")]))
    data = dict(items=[dict(item_id="ER/0", verdict="UNCERTAIN", single_fact=True,
                           source_ids=[], reason="uncertain")])
    assert b.model_validate(data).items[0].source_ids == []
    data["items"][0]["source_ids"] = ["A"]
    a.model_validate(data)
    with pytest.raises(ValueError):
        b.model_validate(data)


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
def test_live_source_schema_reaches_sdk_wire_and_parses_without_network(stage):
    import httpx
    payload = review_payload(stage)
    payload["task_boundary_contract"] = "1.3"
    selection = source_selected_review_record(payload)["source_selection"]
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=dict(id="resp_local", object="response", created_at=0,
            status="completed", model="test-model", output=[dict(id="msg_local", type="message",
            role="assistant", status="completed", content=[dict(type="output_text",
                text=json.dumps(selection, ensure_ascii=False), annotations=[])])],
            usage=dict(input_tokens=1, output_tokens=1, total_tokens=2)))
    with grounding.OpenAI(api_key="local-test-not-a-secret", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        record = grounding.OpenAIGroundingReviewer(model="test-model", client=client).review(payload)
    assert len(sent) == 1
    fmt = sent[0]["text"]["format"]
    assert fmt["strict"] is True and fmt["type"] == "json_schema"
    field = fmt["schema"]["$defs"]["BoundReviewSourceSelection"]["properties"]["source_ids"]["items"]
    assert field.get("enum", [field.get("const")]) == [d["source_id"] for d in payload["source_documents"]]
    assert record["source_selection"] == selection
    assert grounding.check_review_record(payload, record).status == CheckStatus.PASS


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("mutation", ["none", "unknown", "empty", "duplicate", "quote",
                                    "verdict", "source_text", "marker", "selection", "missing_item"])
def test_source_id_review_preserves_original_and_rejects_tampering(stage, mutation):
    payload = review_payload(stage)
    payload["task_boundary_contract"] = "1.3"
    record = source_selected_review_record(payload)
    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    item = record["source_selection"]["items"][0]
    if mutation == "unknown":
        item["source_ids"] = ["SRS/NOT-PROVIDED"]
    elif mutation == "empty":
        item["source_ids"] = []
    elif mutation == "duplicate":
        item["source_ids"] *= 2
    elif mutation == "quote":
        record["review"]["items"][0]["citations"][0]["quote"] += "."
    elif mutation == "verdict":
        record["review"]["items"][0]["verdict"] = "UNSUPPORTED"
    elif mutation == "source_text":
        payload["source_documents"][0]["text"] += " modified"
    elif mutation == "marker":
        record.pop("citation_binding_contract")
    elif mutation == "selection":
        record.pop("source_selection")
    elif mutation == "missing_item":
        record["source_selection"]["items"].pop()
        record["review"]["items"].pop()
    if mutation == "none":
        assert grounding.check_review_record(payload, record).status == CheckStatus.PASS
        assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == before
        for result in record["review"]["items"]:
            assert result["citations"][0]["quote"] == payload["source_documents"][0]["text"]
    else:
        with pytest.raises(ValueError):
            grounding.check_review_record(payload, record)


@pytest.mark.parametrize("text", [
    "적용 후 내부 fanSpeed는 선택한 코드와 같고, HIGH는 강풍으로 표시됩니다.",
    "운전 상태는 정지이며, mode는 HEAT입니다.",
    "18~30°C만 허용합니다. 31°C는 적용하지 않습니다.",
    "잠금 해제 후 다시 설정합니다.\nlocked=true",
    "  기존 문구와 공백도 그대로 유지합니다.  ",
])
def test_source_id_binding_never_rewrites_words_punctuation_or_values(text):
    payload = review_payload()
    payload["source_documents"][0]["text"] = text
    record = source_selected_review_record(payload)
    assert record["review"]["items"][0]["citations"][0]["quote"] == text
    assert grounding.check_review_record(payload, record).status == CheckStatus.PASS


@pytest.mark.parametrize("verdict,status", [
    ("SUPPORTED", CheckStatus.PASS), ("UNSUPPORTED", CheckStatus.FAIL), ("UNCERTAIN", CheckStatus.REVIEW)])
def test_source_id_binding_does_not_change_semantic_verdict(verdict, status):
    payload = review_payload()
    payload["task_boundary_contract"] = "1.3"
    record = source_selected_review_record(payload, verdict=verdict)
    assert grounding.check_review_record(payload, record).status == status


def test_source_id_live_schema_forbids_model_written_quotes():
    from openai.lib._pydantic import to_strict_json_schema
    schema = to_strict_json_schema(grounding.GroundingSourceSelection)
    item = schema["$defs"]["ReviewSourceSelection"]
    assert "source_ids" in item["required"]
    assert "quote" not in json.dumps(schema) and "citations" not in item["properties"]
    assert item["additionalProperties"] is False
    with pytest.raises(ValueError):
        grounding.GroundingSourceSelection.model_validate(fake_grounding_record(review_payload())["review"])


def test_source_id_invalid_selection_retains_response_and_usage():
    payload = review_payload()
    record = source_selected_review_record(payload)
    record["source_selection"]["items"][0]["source_ids"] = ["MISSING-SOURCE"]
    parsed = grounding.GroundingSourceSelection.model_validate(record["source_selection"])
    sdk = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: SimpleNamespace(
        output_parsed=parsed, id="received-invalid-source",
        usage=SimpleNamespace(input_tokens=7, output_tokens=3, total_tokens=10))))
    result = grounding.OpenAIGroundingReviewer(model="test-model", client=sdk).review(payload)
    assert result["source_selection"] == record["source_selection"]
    assert result["response_id"] == "received-invalid-source" and result["usage"]["total_tokens"] == 10
    assert result["review"] is None
    with pytest.raises(ValueError, match="ID 없음"):
        grounding.check_review_record(payload, result)


def indexed_test_payload(stage="AGENT3", count=1005):
    payload = review_payload(stage)
    payload["task_boundary_contract"] = "1.3"
    payload["source_documents"] = [dict(source_id=f"SRS/TEST/{n}", text=f" 原文 {n}·16~30°C\n")
                                   for n in range(count)]
    return payload


def indexed_test_record(payload, verdict="SUPPORTED", indices=None):
    selection = grounding.GroundingIndexSelection(items=[grounding.ReviewIndexSelection(
        item_id=item["item_id"], verdict=verdict, single_fact=True,
        source_indices=[0, len(payload["source_documents"]) - 1] if indices is None else indices,
        reason="scripted transport test, not semantic judgment") for item in payload["items"]])
    sdk = SimpleNamespace(responses=SimpleNamespace(parse=lambda **kwargs: SimpleNamespace(
        output_parsed=selection, id="local-indexed", usage=SimpleNamespace(
            input_tokens=7, output_tokens=3, total_tokens=10))))
    return grounding.OpenAIGroundingReviewer(model="test", client=sdk).review(payload)


@pytest.mark.parametrize("count", [997, 998, 1005, 1200])
def test_indexed_transport_preserves_every_document_and_request_local_mapping(count):
    from openai.lib._pydantic import to_strict_json_schema
    payload = indexed_test_payload(count=count)
    before = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    wire, model = grounding.indexed_review_transport(payload)
    for n, (source, sent) in enumerate(zip(payload["source_documents"], wire["source_documents"])):
        assert sent == dict(source, source_index=n)
    assert len(wire["source_documents"]) == count
    restored = json.loads(json.dumps(wire))
    restored.pop("source_selection_transport")
    for doc in restored["source_documents"]:
        doc.pop("source_index")
    assert restored == payload
    schema = to_strict_json_schema(model)
    field = schema["$defs"]["BoundReviewIndexSelection"]["properties"]["source_indices"]["items"]
    assert field["type"] == "integer" and field["minimum"] == 0 and field["maximum"] == count - 1
    assert "SRS/TEST/" not in json.dumps(schema)
    data = dict(items=[dict(item_id="ER/0", verdict="SUPPORTED", single_fact=True,
                           source_indices=list(range(count)), reason="all original citations")])
    bound = grounding.bind_review_sources(payload, grounding.bind_review_indices(payload, model.model_validate(data)))
    assert [c.model_dump() for c in bound.items[0].citations] == [
        dict(source_id=d["source_id"], quote=d["text"]) for d in payload["source_documents"]]
    assert json.dumps(payload, ensure_ascii=False, sort_keys=True) == before


@pytest.mark.parametrize("bad", [-1, 1005, True, 1.0, "1", None])
def test_indexed_transport_rejects_invalid_number_without_coercion(bad):
    payload = indexed_test_payload()
    _, model = grounding.indexed_review_transport(payload)
    item = dict(item_id="ER/0", verdict="SUPPORTED", single_fact=True,
                source_indices=[bad], reason="invalid index")
    with pytest.raises(ValueError):
        model.model_validate(dict(items=[item]))
    # The binding guard also rejects invalid objects bypassing model validation.
    raw = SimpleNamespace(items=[SimpleNamespace(source_indices=[bad])])
    with pytest.raises(ValueError):
        grounding.bind_review_indices(payload, raw)


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("count", [997, 998, 1005])
def test_indexed_transport_actual_sdk_wire_and_legacy_threshold(stage, count):
    import httpx
    payload = indexed_test_payload(stage, count)
    indexed = count > 997
    field = "source_indices" if indexed else "source_ids"
    selected = [0, count - 1] if indexed else [d["source_id"] for d in payload["source_documents"][::count-1]]
    data = dict(items=[dict(item_id=i["item_id"], verdict="SUPPORTED", single_fact=True,
                           **{field: selected}, reason="local SDK test") for i in payload["items"]])
    sent = []
    def transport(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=dict(id="resp_local", object="response", created_at=0,
            status="completed", model="test", output=[dict(id="msg_local", type="message",
            role="assistant", status="completed", content=[dict(type="output_text",
            text=json.dumps(data), annotations=[])])],
            usage=dict(input_tokens=7, output_tokens=3, total_tokens=10)))
    with grounding.OpenAI(api_key="local-test-not-a-secret", max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(transport))) as client:
        result = grounding.OpenAIGroundingReviewer(model="test", client=client).review(payload)
    assert len(sent) == 1 and sent[0]["store"] is False
    assert sent[0]["text"]["format"]["strict"] is True
    wire = json.loads(sent[0]["input"][1]["content"])
    assert wire == (grounding.indexed_review_transport(payload)[0] if indexed
                    else grounding.static_first_wire(payload))
    if indexed:  # position-based numbers keep the original document order
        assert [d["source_id"] for d in wire["source_documents"]] == [
            d["source_id"] for d in payload["source_documents"]]
    assert ("source_indices" in sent[0]["input"][0]["content"]) == indexed
    assert result["citation_binding_contract"] == ("source-index-1.0" if indexed else "source-id-1.0")
    assert result.get("wire_layout") == (None if indexed else "static-first-1.0")
    assert grounding.check_review_record(payload, result).status == CheckStatus.PASS
    assert result["usage"]["total_tokens"] == 10


@pytest.mark.parametrize("verdict,status", [("SUPPORTED", CheckStatus.PASS),
    ("UNSUPPORTED", CheckStatus.FAIL), ("UNCERTAIN", CheckStatus.REVIEW)])
def test_indexed_transport_keeps_verdict_and_empty_evidence_rules(verdict, status):
    payload = indexed_test_payload()
    assert grounding.check_review_record(payload, indexed_test_record(payload, verdict)).status == status
    record = indexed_test_record(payload, verdict, indices=[])
    if verdict == "UNCERTAIN":
        assert grounding.check_review_record(payload, record).status == CheckStatus.REVIEW
    else:
        with pytest.raises(ValueError):
            grounding.check_review_record(payload, record)


@pytest.mark.parametrize("mutation", ["index", "duplicate_index", "out_of_range", "source_id", "quote",
    "verdict", "wire_hash", "input_text", "input_order", "missing_document", "missing_marker",
    "unknown_marker", "missing_selection", "missing_item", "duplicate_item"])
def test_indexed_saved_review_detects_tampering_and_missing_review(mutation):
    payload = indexed_test_payload()
    record = indexed_test_record(payload)
    item = record["index_selection"]["items"][0]
    if mutation == "index": item["source_indices"][0] = 1
    elif mutation == "duplicate_index": item["source_indices"] = [0, 0]
    elif mutation == "out_of_range": item["source_indices"] = [1005]
    elif mutation == "source_id": record["source_selection"]["items"][0]["source_ids"][0] = "UNKNOWN"
    elif mutation == "quote": record["review"]["items"][0]["citations"][0]["quote"] += "."
    elif mutation == "verdict": record["review"]["items"][0]["verdict"] = "UNSUPPORTED"
    elif mutation == "wire_hash": record["wire_input_sha256"] = "0" * 64
    elif mutation == "input_text": payload["source_documents"][0]["text"] += "wrong"
    elif mutation == "input_order": payload["source_documents"].reverse()
    elif mutation == "missing_document": payload["source_documents"].pop()
    elif mutation == "missing_marker": record.pop("citation_binding_contract")
    elif mutation == "unknown_marker": record["citation_binding_contract"] = "unknown"
    elif mutation == "missing_selection": record.pop("index_selection")
    elif mutation == "missing_item":
        for field in ("index_selection", "source_selection", "review"): record[field]["items"].pop()
    elif mutation == "duplicate_item":
        for field in ("index_selection", "source_selection", "review"):
            record[field]["items"].append(record[field]["items"][0])
    with pytest.raises(ValueError):
        grounding.check_review_record(payload, record)


def test_indexed_invalid_selection_retains_raw_response_and_usage():
    payload = indexed_test_payload()
    record = indexed_test_record(payload, indices=[0, 0])
    assert record["index_selection"]["items"][0]["source_indices"] == [0, 0]
    assert record["response_id"] == "local-indexed" and record["usage"]["total_tokens"] == 10
    assert record["review"] is None
    with pytest.raises(ValueError): grounding.check_review_record(payload, record)


@pytest.mark.parametrize("focused", [False, True])
def test_indexed_instructions_only_change_citation_addressing(focused):
    original = grounding.FOCUSED_AGENT2_REVIEW_INSTRUCTIONS if focused else grounding.REVIEW_INSTRUCTIONS
    updated = grounding._indexed_review_instructions(original)
    assert "source_indices" in updated
    assert "정확한 source_id를 선택" not in updated and "source_id를 source_ids에" not in updated
    assert "SUPPORTED / UNSUPPORTED / UNCERTAIN" in updated
    # Non-addressing paragraphs must remain intact.
    for paragraph in original.split("\n"):
        if not any(token in paragraph for token in ("source_id", "source_ids")):
            assert paragraph in updated


def test_source_id_duplicate_documents_never_pick_one_silently():
    payload = review_payload()
    record = source_selected_review_record(payload)
    payload["source_documents"].append(dict(payload["source_documents"][0]))
    with pytest.raises(ValueError, match="source_id 중복"):
        grounding.bind_review_sources(payload, grounding.GroundingSourceSelection.model_validate(record["source_selection"]))


@pytest.mark.parametrize("verdict,status", [("UNSUPPORTED", CheckStatus.FAIL),
    ("UNCERTAIN", CheckStatus.REVIEW), ("SUPPORTED", CheckStatus.PASS)])
def test_srs_revision_review_contains_whole_old_and_proposed_policy(verdict, status):
    requirements, design = cp2_requirements(), cp2_valid_design()
    original = requirements["REQ-TEMP-001"].acceptance_criteria
    design.srs_revision_proposals = [pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001", requirement_id="REQ-TEMP-001", source_condition_ids=["COND-001"],
        current_acceptance_criteria=original, proposed_acceptance_criteria="새 설정 기능을 제공한다.",
        reason="기존 제한을 누락한 부적절한 제안 사본")]
    payload = grounding.build_grounding_input("AGENT2", cp1_request(), requirements, design,
        analysis=cp2_analysis())
    assert next(d["text"] for d in payload["source_documents"]
        if d["source_id"] == "SRS/REQ-TEMP-001/acceptance") == original
    proposal = next(i for i in payload["items"] if i["item_id"] == "srs_revision_proposals/0")
    assert proposal["content"]["current_acceptance_criteria"] == original
    assert proposal["content"]["proposed_acceptance_criteria"] == "새 설정 기능을 제공한다."
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == proposal["item_id"])["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status == status
    # A scripted SUPPORTED is not proof that dropped-policy proposals are detected.

@pytest.mark.parametrize("version", ["1.2", "1.3"])
def test_precondition_checks_remain_covered_when_duplicate_items_removed(version):
    case, plan = agent3_test_case(), agent3_plan()
    payload = grounding.build_grounding_input("AGENT3", None, cp2_requirements(), plan,
        test_case=case, observation=agent3_observation())
    preconditions = [i for i in payload["items"] if i["kind"] == "PRECONDITION_COVERAGE"]
    assert len(preconditions) == len(case.preconditions)
    assert [i["content"]["source"] for i in preconditions] == case.preconditions
    assert sum(len(i["content"]["checks"]) for i in preconditions) == len(plan.precondition_checks)
    standalone = [i for i in payload["items"] if i["item_id"].startswith("precondition_checks/")]
    assert len(standalone) == (0 if version == "1.3" else len(plan.precondition_checks))
    assert payload["context"]["compiler_plan_facts"]["trial_success_proved"] is False

@pytest.mark.parametrize("fault", ["none", "ambiguous", "fragment", "invented", "product_source", "unknown_source"])
def test_host_citation_resolution_is_exact_unique_and_audited(fault):
    payload = review_payload("AGENT2")
    payload["task_boundary_contract"] = "1.3"
    quote = "Concrete selectors still require Agent 3 UI inventory and target identity checks."
    payload["source_documents"] = [
        {"source_id": "EXECUTION_CONTRACT", "text": "Other execution facts."},
        {"source_id": "TASK_BOUNDARIES", "text": quote},
    ]
    if fault == "ambiguous":
        payload["source_documents"].append({"source_id": "REVIEW_RESPONSIBILITIES", "text": quote})
    if fault == "product_source":
        payload["source_documents"][1]["source_id"] = "SRS/REQ-TEMP-001/acceptance"
    record = fake_grounding_record(payload)
    citation = record["review"]["items"][0]["citations"][0]
    citation.update(source_id="EXECUTION_CONTRACT", quote=quote)
    if fault == "fragment": citation["quote"] = "Concrete selectors"
    if fault == "invented": citation["quote"] = "Invented complete sentence."
    if fault == "unknown_source": citation["source_id"] = "UNKNOWN"
    original = json.dumps(record, sort_keys=True)
    if fault == "none":
        result = grounding.check_review_record(payload, record)
        assert result.status == CheckStatus.PASS
        assert "EXECUTION_CONTRACT → TASK_BOUNDARIES" in result.message
        assert json.dumps(record, sort_keys=True) == original
        record["review"]["items"][0]["verdict"] = "UNSUPPORTED"
        assert grounding.check_review_record(payload, record).status == CheckStatus.FAIL
    else:
        with pytest.raises(ValueError, match="검토 응답 오류"):
            grounding.check_review_record(payload, record)


def test_unified_procedure_review_keeps_sources_and_unsupported_feature_tc():
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    analysis.procedure_notes = ["[준비] 시험 전 상태 기록", "[복원] 시험 전 상태로 복원"]
    design.test_cases[0].automation_candidate = False
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis)
    ids = [i["item_id"] for i in payload["items"]]
    assert "PROCEDURE/ALL" in ids
    assert not any("/preconditions/" in i or "/restore_steps/" in i for i in ids)
    procedure = next(i for i in payload["items"] if i["item_id"] == "PROCEDURE/ALL")
    assert procedure["content"]["source_procedures"] == analysis.procedure_notes
    assert procedure["content"]["candidate_procedures"][0]["preconditions"] == design.test_cases[0].preconditions
    assert "TC/0/design" in ids  # ERs are reviewed inside the whole TC
    assert payload["context"]["TC/0"]["automation_candidate"] is False
    record = fake_grounding_record(payload)
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != "PROCEDURE/ALL"]
    with pytest.raises(ValueError, match="누락"):
        grounding.check_review_record(payload, record)


@pytest.mark.parametrize("request_text,relation,verdict,expected", [
    ("기존 범위에서 난방 27→21°C 적용", "VERIFY", "SUPPORTED", "PASS"),
    ("기존 범위 유지, 35°C 준비 후 31°C 적용 성공", "VERIFY", "UNSUPPORTED", "FAIL"),
    ("30°C에서 31°C 요청 차단·기존 값 유지", "VERIFY", "SUPPORTED", "PASS"),
    ("AUTO 허용 범위를 18~30°C로 변경", "MODIFIED", "SUPPORTED", "PASS"),
    ("AUTO 허용 범위를 18~30°C로 변경", "VERIFY", "UNSUPPORTED", "FAIL"),
    ("새 자동 전환 설정·해제 기능을 확인", "MODIFIED", "SUPPORTED", "PASS"),
])
def test_request_intent_review_routes_scripted_judgments(request_text, relation, verdict, expected):
    # This deliberately tests routing, NOT whether a live model understands it.
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.description = request_text
    analysis.requirement_effects[0].relation = RequirementRelation(relation)
    payload = grounding.build_grounding_input("AGENT1", request, cp1_requirements(), analysis)
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "requirement_effects/0")["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status.value == expected


@pytest.mark.parametrize("mutation", ["missing_boundary", "wrong_value", "reversed_policy"])
@pytest.mark.parametrize("verdict,expected", [("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_request_coverage_survives_bad_or_missing_analysis(mutation, verdict, expected):
    request, analysis = cp1_request(), cp1_valid_analysis()
    if mutation == "missing_boundary":
        analysis.confirmed_conditions = analysis.confirmed_conditions[:2]
    elif mutation == "wrong_value":
        analysis.confirmed_conditions[-1].statement = "새 범위는 19~30°C이다."
    else:
        analysis.confirmed_conditions[1].statement = "18°C 미만 요청을 허용한다."
    payload = grounding.build_grounding_input("AGENT1", request, cp1_requirements(), analysis)
    coverage = [i for i in payload["items"] if i["kind"] == "REQUEST_COVERAGE"]
    assert [i["content"]["source_text"] for i in coverage] == [request.before_value, request.after_value, request.description]
    assert coverage[0]["content"]["analysis"] == analysis.model_dump(mode="json")
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "REQUEST_COVERAGE/after_value").update(verdict=verdict)
    assert grounding.check_review_record(payload, record).status.value == expected
    record["review"]["items"] = [i for i in record["review"]["items"] if not i["item_id"].startswith("REQUEST_COVERAGE")]
    with pytest.raises(ValueError, match="누락"):
        grounding.check_review_record(payload, record)
    # Explicit scripted judgment: routing/coverage, not live detection accuracy.


@pytest.mark.parametrize('verdict,expected', [('SUPPORTED', 'PASS'), ('UNSUPPORTED', 'FAIL'), ('UNCERTAIN', 'REVIEW')])
@pytest.mark.parametrize('text', ['AUTO 적용 직후 화면에 허용된 값이 표시된다.', '화면 값은 99로 변경된다.'])
def test_prose_value_guard_is_replaced_by_required_review_not_automatic_success(text, verdict, expected):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    design.test_cases[0].expected_results[0].statement = text
    new = evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert cp2_check(new, 'CP2-017').status == CheckStatus.PASS
    payload = grounding.build_grounding_input('AGENT2', request, cp2_requirements(), design, analysis=analysis)
    record = fake_grounding_record(payload, verdict=verdict)
    # Scripted verdict tests routing, NOT the model's ability to identify 99 as wrong.
    combined = grounding.attach_grounding_check(new, grounding.check_review_record(payload, record))
    assert combined.status.value == expected


import qa_pipeline_grounding as grounding


@pytest.mark.parametrize("control,start,target", [
    ("전원", "OPERATION", "STOP"), ("운전 모드", "AUTO", "DRY"),
    ("풍량", "HIGH", "AUTO"), ("온도", "24", "28"), ("잠금", "해제", "설정"),
])
@pytest.mark.parametrize("mutation", ["normal", "missing_setup", "extra_test", "missing_restore"])
def test_every_control_procedure_is_reviewed_from_source(control, start, target, mutation):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    note = f"{control}을 {start}로 준비한 뒤 {target}을 적용하고 준비 전 상태로 복원합니다."
    request.acceptance_notes.append(note)
    request.out_of_scope.append(f"{control}의 나머지 값 시험")
    analysis.procedure_notes = [note]
    tc = design.test_cases[0]
    tc.preconditions = [f"{control}의 준비 상태는 {start}이며 시험 전에 준비하고 확인한다."]
    tc.steps = ["대상 장비를 선택한다.", f"{control}을 {target}으로 선택한다.", "선택한 값을 적용한다."]
    tc.restore_steps = [f"{control}을 준비 전 관찰 상태로 복원하고 확인한다."]
    if mutation == "missing_setup": tc.preconditions = []
    if mutation == "extra_test": tc.steps.append(f"{control}의 나머지 모든 값도 적용하여 시험한다.")
    if mutation == "missing_restore": tc.restore_steps = []
    original = design.model_dump_json()
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG)
    item = next(i for i in payload["items"] if i["item_id"] == "PROCEDURE/ALL")
    assert item["content"]["source_procedures"] == [note]
    candidate = item["content"]["candidate_procedures"][0]
    assert candidate["preconditions"] == tc.preconditions
    assert candidate["steps"] == tc.steps
    assert candidate["restore_steps"] == tc.restore_steps
    assert any(d["text"] == request.out_of_scope[-1] for d in payload["source_documents"])
    # This proves evidence/routing, NOT that a live reviewer is always correct.
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "PROCEDURE/ALL")["verdict"] = (
        "SUPPORTED" if mutation == "normal" else "UNSUPPORTED")
    assert grounding.check_review_record(payload, record).status == (
        CheckStatus.PASS if mutation == "normal" else CheckStatus.FAIL)
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != "PROCEDURE/ALL"]
    with pytest.raises(ValueError, match="누락"):
        grounding.check_review_record(payload, record)
    assert design.model_dump_json() == original


@pytest.mark.parametrize("control", ["전원", "운전 모드", "풍량", "온도", "잠금"])
@pytest.mark.parametrize("scope", ["bounded", "explicit_multiple", "conflict"])
def test_control_scope_retains_reference_and_actual_test_claims(control, scope):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    request.description = f"{control}의 시작 상태에서 목표 상태로 한 번 전환한다."
    request.out_of_scope = [f"{control}의 다른 상태 시험"] if scope != "explicit_multiple" else []
    request.acceptance_notes = [f"{control}의 목표 상태를 확인한다."]
    if scope in {"explicit_multiple", "conflict"}:
        request.acceptance_notes.append(f"{control}의 다른 상태도 확인한다.")
    analysis.confirmed_conditions[-1].change_role = pipeline.ConditionChangeRole.SUPPORTING
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG)
    coverage = [i for i in payload["items"] if i["kind"] == "CONDITION_COVERAGE"]
    assert [i["content"]["condition"] for i in coverage] == [c.model_dump(mode="json") for c in analysis.confirmed_conditions]
    sources = [d["text"] for d in payload["source_documents"]]
    assert all(line in sources for line in request.acceptance_notes + request.out_of_scope)
    record = fake_grounding_record(payload)
    if scope == "conflict":
        next(i for i in record["review"]["items"] if i["item_id"].startswith("CONDITION/"))["verdict"] = "UNCERTAIN"
    assert grounding.check_review_record(payload, record).status == (CheckStatus.REVIEW if scope == "conflict" else CheckStatus.PASS)


def test_procedure_coverage_cannot_disappear_with_candidate_deletion():
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    analysis.procedure_notes = ["상태를 준비한다.", "종료 뒤 원상태로 복원한다."]
    design.test_cases = []
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis)
    items = [i for i in payload["items"] if i["kind"] == "PROCEDURE_COVERAGE"]
    assert len(items) == 1 and items[0]["content"]["source_procedures"] == analysis.procedure_notes
    assert items[0]["content"]["candidate_procedures"] == []


def test_scope_and_preparation_guidance_is_consistent_across_agents():
    import qa_pipeline_agent1 as a1
    import qa_pipeline_agent2 as a2
    assert "보조_근거는 제품 기준의 참고" in a1.AGENT1_SYSTEM_INSTRUCTIONS
    assert "준비→목표 전환 하나는 SINGLE_FLOW" in a2.AGENT2_SYSTEM_INSTRUCTIONS
    assert "다른 관제점 값을 넣거나 실행 정의와 모순되게 쓰지 않습니다" in a2.AGENT2_SYSTEM_INSTRUCTIONS
    assert "원문 한 문장을 통째로 steps에 복사" in a2.AGENT2_SYSTEM_INSTRUCTIONS
    assert "전체 시험을 요구하지 않습니다" in grounding.REVIEW_INSTRUCTIONS
    assert "PROCEDURE_COVERAGE" in grounding.REVIEW_INSTRUCTIONS
    schema = pipeline.TestData.model_json_schema()
    assert "풍량·전원·잠금" in schema["properties"]["initial_mode"]["description"]
    assert set(pipeline.TestData.model_fields) == {"initial_mode", "requested_mode", "requested_modes",
        "initial_temperature_c", "requested_temperature_c", "requested_temperatures_c", "restore_observed_hvac_state"}


@pytest.mark.parametrize("verdict,expected", [("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_agent1_progress_decision_is_reviewed_without_claiming_human_approval(verdict, expected):
    payload = review_payload("AGENT1")
    decision = next(item for item in payload["items"] if item["item_id"] == "decision")
    assert decision["content"] == "PROCEED"
    record = fake_grounding_record(payload)
    next(item for item in record["review"]["items"] if item["item_id"] == "decision")["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status.value == expected
    assert "사람의 공식 SRS·TC 승인이 아닙니다" in grounding.REVIEW_INSTRUCTIONS
    assert "실제 누락·충돌·근거 없는 확정은 계속 지적" in grounding.REVIEW_INSTRUCTIONS
    record["review"]["items"] = [item for item in record["review"]["items"] if item["item_id"] != "decision"]
    with pytest.raises(ValueError, match="누락"):
        grounding.check_review_record(payload, record)


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
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis, catalog=catalog)
    coverage = [i for i in payload["items"] if i["kind"] == "CONDITION_COVERAGE"]
    assert [i["content"]["condition"]["condition_id"] for i in coverage] == [c.condition_id for c in analysis.confirmed_conditions]
    def candidates(content):  # identical TC copies are referenced, never summarized
        return content.get("candidate_tests") or [payload["context"][r] for r in content.get("candidate_test_refs", [])]
    if mutation == "missing_er":
        condition = coverage[-1]["content"]
        assert condition["condition"]["condition_id"] in candidates(condition)[0]["source_condition_ids"]
        assert not any(condition["condition"]["condition_id"] in er["source_condition_ids"]
                       for er in candidates(condition)[0]["expected_results"])
    elif mutation == "missing_test":
        assert all(not candidates(i["content"]) for i in coverage)
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
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != target]
    with pytest.raises(ValueError, match="누락"):
        grounding.check_review_record(payload, record)


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
    structural = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
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
        expected = {"hash": "입력 해시", "stage": "검토의 단계", "contract": "계약 형식"}[mutation]
        with pytest.raises(ValueError, match=expected):
            grounding.check_review_record(payload, record)
    elif mutation in {"missing", "duplicate", "unknown_id", "citation", "empty_citations"}:
        # A broken review is a review error, never feedback on the artifact.
        with pytest.raises(ValueError, match="검토 응답 오류"):
            grounding.check_review_record(payload, record)
    else:
        result = grounding.check_review_record(payload, record)
        assert result.status == (CheckStatus.PASS if mutation in {"none", "order"} else
                                 CheckStatus.REVIEW if mutation == "uncertain" else CheckStatus.FAIL)


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("field, message", [
    ("contract", "계약 형식"), ("stage", "검토의 단계"), ("input_sha256", "입력 해시"),
])
def test_saved_review_missing_identity_reports_cause_before_reading_verdict(stage, field, message):
    payload = review_payload(stage)
    record = source_selected_review_record(payload)
    record.pop(field)
    # Invalid identity must stop before using (or even reading) the saved verdict.
    record.pop("review")
    before = json.dumps(record, sort_keys=True)
    with pytest.raises(ValueError, match=message) as error:
        grounding.check_review_record(payload, record)
    assert "이전 판정을 재사용할 수 없습니다" in str(error.value)
    assert json.dumps(record, sort_keys=True) == before


@pytest.mark.parametrize("stage", ["AGENT3"])  # Agent 2 reviews whole TCs (essential contract)
def test_compound_expected_result_review_cannot_be_treated_as_complete(stage):
    payload = review_payload(stage)
    record = fake_grounding_record(payload)
    index = next(i for i, entry in enumerate(payload["items"]) if entry["kind"] == "EXPECTED_RESULT")
    record["review"]["items"][index]["single_fact"] = False
    record["review"]["items"].reverse()  # Kinds still match by ID, not array index.
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
    index = next(i for i, item in enumerate(payload["items"]) if item["item_id"] == "TC/0/design")
    assert text in payload["context"]["TC/0"]["steps"]
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
    payload = review_payload("AGENT3")
    calls = []
    def parse(**kwargs):
        calls.append(kwargs)
        if result_kind == "error":
            raise RuntimeError("transport unavailable")
        return SimpleNamespace(output_parsed=None if result_kind == "refusal" else
            grounding.GroundingSourceSelection.model_validate({
                "items": [{**{k: v for k, v in item.items() if k != "citations"},
                           "source_ids": [c["source_id"] for c in item["citations"]]}
                          for item in fake_grounding_record(payload)["review"]["items"]]}),
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
    assert issubclass(calls[0]["text_format"], grounding.GroundingSourceSelection)
    with pytest.raises(ValueError):
        calls[0]["text_format"].model_validate(dict(items=[dict(item_id="ER/0",
            verdict="SUPPORTED", single_fact=True, source_ids=["NOT-PROVIDED"], reason="test")]))
    assert calls[0]["prompt_cache_key"] == "qa-v2-grounding-1-17"
    instructions = calls[0]["input"][0]["content"]
    assert instructions == grounding.REVIEW_INSTRUCTIONS
    assert "task_boundary_contract=1.1/1.2/1.3에서는 UNSUPPORTED도" in instructions
    assert "같은 관찰 위치에서 그 실제 기록값과 비교" in instructions
    assert "source_documents 원문을 인용" in instructions
    assert "임의 기본값으로 복원" in instructions
    assert "준비·복원은 요청된 상태·순서·대상 보존을 검토" in instructions
    assert "유지 조건도 반드시 검토" in instructions
    assert "요청 원문과 명시적 제외" in instructions
    assert "제외와 요구가 충돌하거나 시험 범위가 불명확하면 UNCERTAIN" in instructions
    assert "각 TC가 모든 검사를 중복 수행할 필요는 없습니다" in instructions
    assert "일부 범위 시험을 전체 SRS 검증 완료로 주장" in instructions


@pytest.mark.parametrize("verdict", ["SUPPORTED", "UNSUPPORTED", "UNCERTAIN"])
@pytest.mark.parametrize("scope", ["bounded", "explicit_multiple", "conflict"])
def test_scope_guidance_never_silently_drops_preserved_conditions(scope, verdict):
    request, analysis, requirements = cp1_combined_srs_case()
    design = cp2_valid_design()
    # Distinct scopes must remain visible; this test scripts judgment, not accuracy.
    if scope == "bounded":
        request.out_of_scope.append("별도 하한 경계 시험")
    elif scope == "explicit_multiple":
        request.acceptance_notes.append("요청한 두 경계에서 화면과 내부 값 모두 확인합니다.")
    else:
        request.acceptance_notes.append("동일 대상의 추가 알림을 확인합니다.")
        request.out_of_scope.append("동일 대상의 추가 알림을 확인합니다.")
    payload = grounding.build_grounding_input("AGENT2", request, requirements, design,
        analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG)
    coverage = [i for i in payload["items"] if i["kind"] == "CONDITION_COVERAGE"]
    assert [i["content"]["condition"] for i in coverage] == [c.model_dump(mode="json") for c in analysis.confirmed_conditions]
    source_values = [d["text"] for d in payload["source_documents"]]
    assert all(value in source_values for value in request.out_of_scope + request.acceptance_notes)
    record = fake_grounding_record(payload)
    target = coverage[0]["item_id"]
    next(item for item in record["review"]["items"] if item["item_id"] == target)["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status == {
        "SUPPORTED": CheckStatus.PASS, "UNSUPPORTED": CheckStatus.FAIL, "UNCERTAIN": CheckStatus.REVIEW}[verdict]


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


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("mutation", ["missing_file", "changed_hash", "unsupported"])
def test_review_artifact_required_on_new_handoff(tmp_path, stage, mutation):
    payload = review_payload(stage)
    record = fake_grounding_record(payload, verdict="UNSUPPORTED" if mutation == "unsupported" else "SUPPORTED")
    path = tmp_path / f"{stage.lower()}_grounding_review.json"
    if mutation != "missing_file":
        _write_json(path, record)
    manifest = {"grounding_review_sha256": _sha256_file(path) if path.exists() else "0" * 64}
    if mutation == "changed_hash":
        manifest["grounding_review_sha256"] = "0" * 64
    checkpoint = pipeline.Checkpoint2Result(status="PASS", checks=[pipeline.CheckResult(rule_id="base", status="PASS", message="ok")])
    if mutation == "unsupported":
        assert pipeline_execution._load_grounding_review(tmp_path, manifest, stage, payload, checkpoint).status == CheckStatus.FAIL
    else:
        with pytest.raises(ValueError):
            pipeline_execution._load_grounding_review(tmp_path, manifest, stage, payload, checkpoint)


@pytest.mark.parametrize("change", ["missing", "older", "unknown"])
def test_saved_run_with_a_non_current_contract_marker_is_rejected_as_old_format(change):
    contract = pipeline_execution._current_agent2_contract()
    manifest = dict(contract)
    key = "range_checklist_contract"
    if change == "missing":
        manifest.pop(key)
    else:
        manifest[key] = "1.0" if change == "older" else "9.9"
    pipeline_execution._require_current_contract(contract, contract, "Agent 2")
    with pytest.raises(ValueError, match="옛 형식 Agent 2 실행이라 지원하지 않습니다.*range_checklist_contract"):
        pipeline_execution._require_current_contract(manifest, contract, "Agent 2")


@pytest.mark.parametrize("stage", ["AGENT2", "AGENT3"])
@pytest.mark.parametrize("outcome", ["unsupported", "uncertain", "error", "invalid_review"])
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
        if outcome == "invalid_review":
            record = fake_grounding_record(payload)
            record["review"]["items"].pop()
            return record
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
    assert code == (1 if outcome in {"error", "invalid_review"} else 2)
    if outcome in {"error", "invalid_review"}:
        receipt = pipeline._read_json_payload(run / f"{stage.lower()}_generation_usage_attempt_1.json")
        assert receipt["usage"] is None  # Unknown is not zero.
    assert calls == (["generate", "review"] * (2 if outcome == "unsupported" else 1))
    if outcome not in {"error", "invalid_review"}:
        assert pipeline._read_json_payload(path)["status"] == ("FAIL" if outcome == "unsupported" else "REVIEW")
        if stage == "AGENT3":
            assert "근거·검사 연결 검토" in pipeline_orchestrator._agent3_run_entry(run, case.tc_id, run, code)["reason"]
    assert not (run / "agent3_trial.json").exists()
    if outcome == "invalid_review":
        assert not path.exists()
        assert (run / f"{stage.lower()}_grounding_review_attempt_1.json").is_file()


@pytest.mark.parametrize('stage', ['AGENT1', 'AGENT2', 'AGENT3'])
@pytest.mark.parametrize('fault', ['missing_item', 'duplicate_item', 'wrong_quote', 'unsupported_without_citation', 'supported_without_citation'])
def test_malformed_review_is_not_artifact_feedback(stage, fault):
    payload = review_payload(stage)
    record = fake_grounding_record(payload)
    items = record['review']['items']
    if fault == 'missing_item': items.pop()
    elif fault == 'duplicate_item': items.append(dict(items[0]))
    elif fault == 'wrong_quote': items[0]['citations'][0]['quote'] = 'not-in-original-source-98765'
    else:
        items[0].update(verdict='UNSUPPORTED' if fault.startswith('unsupported') else 'SUPPORTED', citations=[])
    with pytest.raises(ValueError, match='검토 응답 오류'):
        grounding.check_review_record(payload, record)


@pytest.mark.parametrize('fault', ['missing_item', 'wrong_quote', 'unsupported_without_citation'])
def test_agent1_invalid_review_preserves_analysis_without_rewriting(tmp_path, monkeypatch, fault):
    request, analysis, _ = cp1_combined_srs_case()
    calls = []
    def generate(*args, **kwargs):
        calls.append('generation')
        return pipeline.Agent1Response(analysis=analysis.model_copy(deep=True), response_id='fake', model='fake', usage={})
    def review(payload):
        calls.append('review')
        record = fake_grounding_record(payload)
        if fault == 'missing_item': record['review']['items'].pop()
        elif fault == 'wrong_quote': record['review']['items'][0]['citations'][0]['quote'] = 'not-in-original-source-98765'
        else: record['review']['items'][0].update(verdict='UNSUPPORTED', citations=[])
        return record
    monkeypatch.setattr(pipeline_execution, 'OpenAIAgent1', lambda **kw: SimpleNamespace(analyze=generate))
    monkeypatch.setattr(pipeline_execution, 'OpenAIGroundingReviewer', lambda **kw: SimpleNamespace(review=review))
    path = tmp_path / 'request.json'
    _write_json(path, request.model_dump(mode='json'))
    code = pipeline.run_agent1(SimpleNamespace(request=str(path), srs=str(REPO_ROOT / 'docs/01_PRODUCT_SRS.md'),
        runs_root=str(tmp_path / 'runs'), model='fake'))
    run = next((tmp_path / 'runs').iterdir())
    assert code == 1 and calls == ['generation', 'review']
    assert pipeline._read_json_payload(run / 'agent1_change_analysis_attempt_1.json') == analysis.model_dump(mode='json')
    assert (run / 'agent1_grounding_review_attempt_1.json').is_file()
    assert (run / 'agent1_review_usage_attempt_1.json').is_file()
    assert not (run / 'run_manifest.json').exists()
    assert not (run / 'agent1_change_analysis_attempt_2.json').exists()


def test_structural_failure_does_not_make_an_extra_review_call(tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline_execution, "OpenAIGroundingReviewer", lambda **kw: pytest.fail("unnecessary call"))
    checkpoint = pipeline.Checkpoint2Result(status="FAIL", checks=[pipeline.CheckResult(rule_id="base", status="FAIL", message="bad ID")])
    records = []
    result = pipeline_execution._run_grounding_review(tmp_path, "AGENT2", 1, review_payload("AGENT2"), checkpoint, "fake", records)
    assert result.status == CheckStatus.FAIL and records == []


def test_uncertain_atomicity_pauses_instead_of_being_rewritten():
    payload = review_payload("AGENT3")
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
@pytest.mark.parametrize("new_policy", [False, True])
def test_extension_review_checks_reasons_not_prohibited_assertions(verdict, expected, new_policy):
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


def test_static_first_wire_only_reorders_transport_and_keeps_digest():
    # 2026-10-17: fixed guidance/product/request documents go first so repeated
    # review calls share a cacheable prefix; the stored payload is unchanged.
    docs = [dict(source_id=s, text=s) for s in (
        "REQUEST/after_value", "APPROVED_TC/tc_id", "TASK_BOUNDARIES", "SRS/REQ-1/statement",
        "COMPILER_PLAN_FACTS/0", "UI_INVENTORY/0", "EXECUTION_CONTRACT", "APPROVED_TC/title")]
    payload = {"contract": "grounding-1.0", "stage": "AGENT3", "artifact_sha256": "a" * 64,
               "source_documents": docs, "context": {"plan": 1}, "items": [{"item_id": "x"}],
               "task_boundary_contract": "1.3"}
    before = grounding._review_digest(payload)
    wire = grounding.static_first_wire(payload)
    assert [d["source_id"] for d in wire["source_documents"]] == [
        "TASK_BOUNDARIES", "EXECUTION_CONTRACT", "SRS/REQ-1/statement", "UI_INVENTORY/0",
        "REQUEST/after_value", "APPROVED_TC/tc_id", "COMPILER_PLAN_FACTS/0", "APPROVED_TC/title"]
    assert list(wire)[:3] == ["contract", "stage", "task_boundary_contract"]
    assert list(wire)[-1] == "artifact_sha256"
    assert grounding._review_digest(payload) == before  # input not mutated
    assert [d["source_id"] for d in payload["source_documents"]][0] == "REQUEST/after_value"
    # Different artifacts of the same stage now share the fixed-document prefix.
    other = dict(payload, artifact_sha256="b" * 64,
                 source_documents=[*docs[:1], dict(source_id="APPROVED_TC/tc_id", text="TC-2"), *docs[2:]])
    a, b = json.dumps(wire, ensure_ascii=False), json.dumps(grounding.static_first_wire(other), ensure_ascii=False)
    assert a[:a.index("APPROVED_TC")] == b[:b.index("APPROVED_TC")]


@pytest.mark.parametrize("reason,status", [
    ("[경고] 장비 선택 조작의 요청 근거 문장이 없습니다.", CheckStatus.PASS),
    ("[치명] 준비로 바꾼 mode의 원래값 기록·복원이 없습니다.", CheckStatus.FAIL),
    ("표시 없는 반려입니다.", CheckStatus.FAIL),  # untagged stays critical
])
def test_review_severity_stops_only_critical_findings(reason, status):
    """2026-10-17 사용자 결정(저장 사례 8건): 치명만 멈추고 경고는 기록 후 진행."""
    request, analysis, requirements = cp1_scope_case(direct=True)
    payload = grounding.build_grounding_input("AGENT1", request, requirements, analysis)
    assert payload["review_severity_contract"] == "1.0"
    record = fake_grounding_record(payload)
    record["review"]["items"][0].update(verdict="UNSUPPORTED", reason=reason)
    result = grounding.check_review_record(payload, record)
    assert result.status == status
    if status == CheckStatus.PASS:
        assert "경고(진행" in result.message and reason in result.message
