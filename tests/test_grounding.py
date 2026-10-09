"""Transport/contract/branch tests. Scripted judgments do not measure model accuracy."""
from pipeline_test_support import *

@pytest.mark.parametrize("enabled", [False, True])
def test_essential_review_policy_reaches_model_instructions(enabled):
    payload = grounding.build_grounding_input("AGENT2", cp1_request(), cp2_requirements(),
        cp2_valid_design(), analysis=cp2_analysis(), include_tc_execution_alignment=True,
        essential_checks=enabled)
    calls = []
    def parse(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(output_parsed=None)
    reviewer = grounding.OpenAIGroundingReviewer(model="test",
        client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    with pytest.raises(ValueError, match="구조화 응답"):
        reviewer.review(payload)
    instructions = calls[0]["input"][0]["content"]
    assert ("호스트의 ESSENTIAL_VALIDATION 계약" in instructions) == enabled
    assert json.loads(calls[0]["input"][1]["content"]) == payload
    if not enabled:
        assert instructions == grounding.REVIEW_INSTRUCTIONS

@pytest.mark.parametrize("verdict,expected", [("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_essential_policy_keeps_required_semantic_verdict(verdict, expected):
    payload = grounding.build_grounding_input("AGENT2", cp1_request(), cp2_requirements(),
        cp2_valid_design(), analysis=cp2_analysis(), include_condition_coverage=True,
        include_tc_execution_alignment=True, essential_checks=True)
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


@pytest.mark.parametrize("prompt,marker,valid", [
    ("agent3-3.43", None, True), ("agent3-3.43", "1.0", False),
    ("agent3-3.44", "1.0", True), ("agent3-3.45", "1.0", True),
    ("agent3-3.44", None, False), ("agent3-3.45", "unknown", False)])
def test_execution_interface_policy_is_version_bound(prompt, marker, valid):
    from qa_pipeline_execution import _agent3_review_options
    manifest = dict(contract_version="4.10", prompt_version=prompt, grounding_contract="1.0",
        task_boundary_contract="1.3", output_tolerance_contract="1.0", wording_policy="STRUCTURAL_ONLY_V1",
        terminal_observation_contract="1.0", product_verdict_contract="1.0")
    if marker is not None:
        manifest["execution_interface_contract"] = marker
    if valid:
        assert _agent3_review_options(manifest)["execution_interface"] == (marker == "1.0")
    else:
        with pytest.raises(ValueError, match="실행 인터페이스"):
            _agent3_review_options(manifest)


@pytest.mark.parametrize("field,initial,target", [("setTemp", 27, 21), ("fanSpeed", "AUTO", "HIGH"),
    ("status", "OPERATION", "STOP"), ("mode", "COOL", "HEAT"), ("locked", False, True)])
def test_execution_interface_preserves_tc_review_and_old_payload(field, initial, target):
    from qa_pipeline_agent3 import execution_interface_facts
    case, plan = mapped_tc_fixture(field, initial, target)
    observation = generic_control_guard_fixture()[2]
    args = ("AGENT3", None, {}, plan)
    options = dict(test_case=case, observation=observation, include_execution_contract=True,
        include_review_responsibilities=True, include_task_boundaries="1.3", explicit_expectations_only=True)
    old = grounding.build_grounding_input(*args, **options)
    new = grounding.build_grounding_input(*args, **options, execution_interface=True)
    assert "execution_interface" not in old["context"]
    assert old == grounding.build_grounding_input(*args, **options, execution_interface=False)
    assert old["items"] == new["items"] and old["artifact_sha256"] == new["artifact_sha256"]
    facts = new["context"]["execution_interface"]
    assert facts == execution_interface_facts(plan, observation)
    assert facts["trial_success_proved"] is False
    if field == "setTemp":
        adapter = facts["adapters"][0]
        assert adapter["read_selector"] == "#det-temp-display"
        assert adapter["click_selectors"] == ["#det-temp-up-btn", "#det-temp-down-btn"]
        # This fixture does not invent observations for missing dependencies.
        observed = {e.selector: e for e in observation.elements}
        for dependency in adapter["dependencies"]:
            assert dependency["match_count"] == (observed[dependency["selector"]].match_count
                if dependency["selector"] in observed else 0)
        code = compile_automation_candidate("INTERFACE", case, plan, explicit_expectations_only=True)
        assert "return _displayed_temperature(page, '#det-temp-display')" in code
        assert "selector = '#det-temp-up-btn' if before < target else '#det-temp-down-btn'" in code
        assert "_adjust_temperature(page, target, allow_blocked=False)" in code
        assert "_adjust_temperature(page, target, allow_blocked=True)" in code
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(new, fake_grounding_record(old))
    record = fake_grounding_record(new)
    assert grounding.check_review_record(new, record).status == CheckStatus.PASS
    record["review"]["items"][0]["verdict"] = "UNSUPPORTED"
    assert grounding.check_review_record(new, record).status == CheckStatus.FAIL

@pytest.mark.parametrize("field,initial,target", [
    ("setTemp", 27, 21), ("fanSpeed", "AUTO", "HIGH"), ("mode", "COOL", "HEAT"),
    ("status", "OPERATION", "STOP"), ("locked", False, True)])
def test_agent2_receives_same_compiler_recovery_facts_without_claiming_success(field, initial, target):
    from qa_pipeline_agent3 import (controller_recovery_tc_facts, controller_recovery_plan_facts,
                                   resolve_controller_bindings, assemble_tc_bindings)
    case, _ = mapped_tc_fixture(field, initial, target)
    before = case.model_dump()
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    args = ("AGENT2", cp1_request(), cp2_requirements(), design)
    old = grounding.build_grounding_input(*args, analysis=cp2_analysis())
    new = grounding.build_grounding_input(*args, analysis=cp2_analysis(), include_tc_execution_alignment=True)
    assert "compiler_recovery_facts" not in old["context"]
    facts = new["context"]["compiler_recovery_facts"]["TC/0"]["controller_recovery"]
    plan = assemble_tc_bindings(case, resolve_controller_bindings(case))
    assert facts == controller_recovery_tc_facts(case) == controller_recovery_plan_facts(case, plan)
    assert set(facts["internal_fields"]) == {"status", "mode", "setTemp", "fanSpeed", "locked"}
    assert facts["includes_preparation_changes"] and not facts["trial_success_proved"]
    assert facts["capture_timing"] == "BEFORE_SETUP"
    assert facts["comparison_timing"] == "AFTER_RESTORE"
    assert old["artifact_sha256"] == new["artifact_sha256"]
    assert case.model_dump() == before
    assert {i["item_id"] for i in old["items"]} == {i["item_id"] for i in new["items"]}
    assert any(d["source_id"].startswith("COMPILER_RECOVERY/") for d in new["source_documents"])
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(new, fake_grounding_record(old))


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


def test_alignment_does_not_bypass_meaning_review_or_reuse_old_judgment():
    request, analysis, design, catalog = compound_reuse_fixture()
    analysis.confirmed_conditions[0].change_role = ConditionChangeRole.UNCHANGED
    args = ("AGENT2", request, cp2_requirements(), design)
    options = dict(analysis=analysis, catalog=catalog, include_condition_coverage=True)
    old = grounding.build_grounding_input(*args, **options)
    new = grounding.build_grounding_input(*args, **options, include_tc_execution_alignment=True)
    assert any(i["kind"] == "CONDITION_COVERAGE" for i in new["items"])
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(new, fake_grounding_record(old))
    record = fake_grounding_record(new)
    record["review"]["items"][0]["verdict"] = "UNSUPPORTED"
    assert grounding.check_review_record(new, record).status == CheckStatus.FAIL
    record["review"]["items"].pop()
    assert grounding.check_review_record(new, record).status == CheckStatus.FAIL




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


@pytest.mark.parametrize("invalid", ["empty", "duplicate", "blank", "count", "characters"])
def test_live_source_schema_invalid_or_oversized_catalog_stops_before_call(invalid):
    documents = [dict(source_id="A", text="original")]
    if invalid == "empty":
        documents = []
    elif invalid == "duplicate":
        documents *= 2
    elif invalid == "blank":
        documents[0]["source_id"] = " "
    elif invalid == "count":
        documents = [dict(source_id=str(i), text="original") for i in range(998)]
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


def test_source_id_duplicate_documents_never_pick_one_silently():
    payload = review_payload()
    record = source_selected_review_record(payload)
    payload["source_documents"].append(dict(payload["source_documents"][0]))
    with pytest.raises(ValueError, match="source_id 중복"):
        grounding.bind_review_sources(payload, grounding.GroundingSourceSelection.model_validate(record["source_selection"]))


@pytest.mark.parametrize("prompt,marker,valid,enabled", [
    ("agent3-3.41", None, True, False), ("agent3-3.42", "1.0", True, True),
    ("agent3-3.42", None, False, False), ("agent3-3.41", "1.0", False, False),
    ("agent3-3.42", "unknown", False, False)])
def test_product_verdict_policy_cannot_be_downgraded(prompt, marker, valid, enabled):
    from qa_pipeline_execution import _agent3_review_options
    manifest = dict(contract_version="4.10", prompt_version=prompt,
        grounding_contract="1.0", task_boundary_contract="1.3",
        output_tolerance_contract="1.0", wording_policy="STRUCTURAL_ONLY_V1",
        review_responsibility_contract="1.0", terminal_observation_contract="1.0")
    if marker is not None:
        manifest["product_verdict_contract"] = marker
    if valid:
        assert _agent3_review_options(manifest)["explicit_expectations_only"] == enabled
    else:
        with pytest.raises(ValueError):
            _agent3_review_options(manifest)


@pytest.mark.parametrize("field,initial,requested", [
    ("status", "STOP", "OPERATION"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "LOW", "HIGH"), ("setTemp", 24, 30), ("locked", False, True)])
def test_product_verdict_review_is_bound_without_losing_expected_results(field, initial, requested):
    case, plan = controller_lifecycle_fixture(field, initial, requested)
    args = dict(test_case=case, observation=agent3_observation(),
        include_task_boundaries="1.3", include_execution_contract=True)
    old = grounding.build_grounding_input("AGENT3", None, {}, plan, **args)
    new = grounding.build_grounding_input("AGENT3", None, {}, plan,
        explicit_expectations_only=True, **args)
    assert old["items"] == new["items"]
    assert new["product_verdict_contract"] == "1.0"
    assert any(d["source_id"] == "PRODUCT_VERDICT_CONTRACT" for d in new["source_documents"])
    with pytest.raises(ValueError):
        grounding.check_review_record(new, fake_grounding_record(old))
    record = fake_grounding_record(new)
    assert grounding.check_review_record(new, record).status == CheckStatus.PASS
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != "ER/0"]
    with pytest.raises(ValueError, match="검토 응답 오류"):
        grounding.check_review_record(new, record)


@pytest.mark.parametrize("basis", ["DIRECT_REQUEST", "CHANGE_DEPENDENCY", "REQUEST_TRACE_ONLY"])
@pytest.mark.parametrize("verdict,status", [("UNSUPPORTED", CheckStatus.FAIL),
    ("UNCERTAIN", CheckStatus.REVIEW), ("SUPPORTED", CheckStatus.PASS)])
def test_agent2_scope_policy_keeps_missing_condition_review(basis, verdict, status):
    analysis, design = cp2_analysis(), cp2_valid_design()
    condition = analysis.confirmed_conditions[-1]
    effect = analysis.requirement_effects[-1]
    effect.scope_evidence = pipeline.RequirementScopeEvidence(basis=basis,
        request_condition_ids=[condition.condition_id], srs_source_text=condition.source_text)
    # Delete an output: the missing input condition must still be reviewed.
    for tc in design.test_cases:
        tc.expected_results = [r for r in tc.expected_results if condition.condition_id not in r.source_condition_ids]
    args = dict(analysis=analysis, include_condition_coverage=True, include_task_boundaries="1.3")
    legacy = grounding.build_grounding_input("AGENT2", cp1_request(), cp2_requirements(), design, **args)
    payload = grounding.build_grounding_input("AGENT2", cp1_request(), cp2_requirements(), design,
        review_scope_semantics=True, **args)
    assert payload["items"] == legacy["items"]
    assert payload["scope_guard_contract"] == "1.2"
    item_id = "CONDITION/" + condition.condition_id
    assert any(i["item_id"] == item_id for i in payload["items"])
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == item_id)["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status == status
    # SUPPORTED is intentionally tested too: scripted tests do not prove judge accuracy.
    with pytest.raises(ValueError):
        grounding.check_review_record(payload, fake_grounding_record(legacy))


@pytest.mark.parametrize("stage", ["AGENT2", "AGENT3"])
@pytest.mark.parametrize("mutation", ["none", "missing", "unknown", "historical", "historical_with_new_marker"])
def test_new_scope_and_terminal_policies_cannot_silently_downgrade(stage, mutation):
    from qa_pipeline_execution import _agent2_checkpoint_options, _agent3_review_options, _current_agent2_contract
    if stage == "AGENT2":
        manifest, marker = _current_agent2_contract(), "scope_guard_contract"
        historical_prompt, reader, option = "agent2-2.49", _agent2_checkpoint_options, "review_scope_semantics"
    else:
        manifest = dict(contract_version="4.10", prompt_version="agent3-3.41",
            grounding_contract="1.0", task_boundary_contract="1.3",
            output_tolerance_contract="1.0", wording_policy="STRUCTURAL_ONLY_V1",
            review_responsibility_contract="1.0", terminal_observation_contract="1.0")
        marker = "terminal_observation_contract"
        historical_prompt, reader, option = "agent3-3.40", _agent3_review_options, "allow_state_change_terminal_observation"
    if mutation in {"missing", "historical"}: manifest.pop(marker)
    if mutation == "unknown": manifest[marker] = "unknown"
    if mutation.startswith("historical"): manifest["prompt_version"] = historical_prompt
    if mutation.startswith("historical") and stage == "AGENT2":
        manifest.pop("tc_execution_alignment_contract")
        manifest.pop("essential_validation_contract")
    if mutation in {"none", "historical"}:
        assert reader(manifest)[option] == (mutation == "none")
    else:
        with pytest.raises(ValueError): reader(manifest)


def test_terminal_observation_policy_is_reviewed_and_hash_bound():
    case, plan = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    args = dict(test_case=case, observation=agent3_observation(),
        include_task_boundaries="1.3", include_execution_contract=True)
    old = grounding.build_grounding_input("AGENT3", None, {}, plan, **args)
    new = grounding.build_grounding_input("AGENT3", None, {}, plan,
        allow_state_change_terminal_observation=True, **args)
    assert old["items"] == new["items"]  # no extra reviewer call
    assert new["terminal_observation_contract"] == "1.0"
    with pytest.raises(ValueError):
        grounding.check_review_record(new, fake_grounding_record(old))
    assert grounding.check_review_record(new, fake_grounding_record(new)).status == CheckStatus.PASS


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
        analysis=cp2_analysis(), include_condition_coverage=True, include_task_boundaries="1.3",
        review_scope_semantics=True)
    assert next(d["text"] for d in payload["source_documents"]
        if d["source_id"] == "SRS/REQ-TEMP-001/acceptance") == original
    proposal = next(i for i in payload["items"] if i["item_id"] == "srs_revision_proposals/0")
    assert proposal["content"]["current_acceptance_criteria"] == original
    assert proposal["content"]["proposed_acceptance_criteria"] == "새 설정 기능을 제공한다."
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == proposal["item_id"])["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status == status
    # A scripted SUPPORTED is not proof that dropped-policy proposals are detected.

@pytest.mark.parametrize("verdict,status", [("SUPPORTED", CheckStatus.PASS),
    ("UNSUPPORTED", CheckStatus.FAIL), ("UNCERTAIN", CheckStatus.REVIEW)])
def test_scope_semantics_uses_existing_review_and_binds_policy_hash(verdict, status):
    request, analysis, requirements = cp1_scope_case(direct=True)
    # Real source, but invented extra behavior: the structure cannot prove meaning.
    analysis.confirmed_conditions[-1].statement += " 새 경고음도 발생한다."
    structural = evaluate_checkpoint1(request, analysis, requirements,
        legacy_wording_checks=False, review_scope_semantics=True)
    assert cp1_check(structural, "CP1-011").status == CheckStatus.PASS
    # A scripted SUPPORTED intentionally demonstrates the remaining judge-error risk.
    legacy = grounding.build_grounding_input("AGENT1", request, requirements, analysis,
        include_task_boundaries="1.3")
    payload = grounding.build_grounding_input("AGENT1", request, requirements, analysis,
        include_task_boundaries="1.3", review_scope_semantics=True)
    assert payload["scope_guard_contract"] == "1.2"
    assert "scope_guard_contract" not in legacy
    assert payload["items"] == legacy["items"]  # no extra reviewer stage/items
    assert any(i["item_id"].startswith("requirement_effects/") for i in payload["items"])
    record = fake_grounding_record(payload, verdict=verdict)
    assert grounding.check_review_record(payload, record).status == status
    with pytest.raises(ValueError):
        grounding.check_review_record(payload, fake_grounding_record(legacy))

@pytest.mark.parametrize("version", ["1.2", "1.3"])
def test_precondition_checks_remain_covered_when_duplicate_items_removed(version):
    case, plan = agent3_test_case(), agent3_plan()
    payload = grounding.build_grounding_input("AGENT3", None, cp2_requirements(), plan,
        test_case=case, observation=agent3_observation(), include_task_boundaries=version,
        include_execution_contract=True, include_review_responsibilities=True)
    preconditions = [i for i in payload["items"] if i["kind"] == "PRECONDITION_COVERAGE"]
    assert len(preconditions) == len(case.preconditions)
    assert [i["content"]["source"] for i in preconditions] == case.preconditions
    assert sum(len(i["content"]["checks"]) for i in preconditions) == len(plan.precondition_checks)
    standalone = [i for i in payload["items"] if i["item_id"].startswith("precondition_checks/")]
    assert len(standalone) == (0 if version == "1.3" else len(plan.precondition_checks))
    assert payload["context"]["compiler_plan_facts"]["trial_success_proved"] is False

@pytest.mark.parametrize("fault", ["none", "ambiguous", "fragment", "invented", "product_source", "unknown_source", "legacy"])
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
    if fault == "legacy": payload["task_boundary_contract"] = "1.2"
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
        analysis=analysis, include_task_boundaries="1.3", include_procedure_coverage=True,
        include_execution_contract=True, include_condition_coverage=True)
    ids = [i["item_id"] for i in payload["items"]]
    assert "PROCEDURE/ALL" in ids
    assert not any("/preconditions/" in i or "/restore_steps/" in i for i in ids)
    procedure = next(i for i in payload["items"] if i["item_id"] == "PROCEDURE/ALL")
    assert procedure["content"]["source_procedures"] == analysis.procedure_notes
    assert procedure["content"]["candidate_procedures"][0]["preconditions"] == design.test_cases[0].preconditions
    assert any("/ER/" in i for i in ids)
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
    payload = grounding.build_grounding_input("AGENT1", request, cp1_requirements(), analysis,
        include_task_boundaries="1.3")
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "requirement_effects/0")["verdict"] = verdict
    assert grounding.check_review_record(payload, record).status.value == expected


@pytest.mark.parametrize("stage,version,prompt,policy", [
    ("AGENT1", "2.11", "agent1-2.19", "1.0"),
    ("AGENT2", "3.13", "agent2-2.47", "1.0"),
    ("AGENT3", "4.10", "agent3-3.37", "1.0"),
    ("AGENT1", "2.11", "agent1-2.20", "1.1"),
    ("AGENT2", "3.13", "agent2-2.48", "1.1"),
    ("AGENT3", "4.10", "agent3-3.38", "1.1"),
    ("AGENT1", "2.11", "agent1-2.21", "1.2"),
    ("AGENT3", "4.10", "agent3-3.39", "1.2"),
    ("AGENT1", "2.11", "agent1-2.22", "1.3"),
    ("AGENT2", "3.13", "agent2-2.49", "1.3"),
    ("AGENT3", "4.10", "agent3-3.40", "1.3"),
    ("AGENT2", "3.13", "agent2-2.50", "1.3"),
    ("AGENT3", "4.10", "agent3-3.41", "1.3"),
])
@pytest.mark.parametrize("mutation", ["none", "missing", "unknown", "no_review", "old_prompt", "version", "mixed_policy"])
def test_task_boundary_policy_is_bound_to_new_manifest(stage, version, prompt, policy, mutation):
    from qa_pipeline_execution import _task_boundary_policy
    manifest = dict(contract_version=version, prompt_version=prompt,
        task_boundary_contract=policy, grounding_contract="1.0",
        output_tolerance_contract="1.0", wording_policy="STRUCTURAL_ONLY_V1")
    if mutation == "missing": manifest.pop("task_boundary_contract")
    elif mutation == "unknown": manifest["task_boundary_contract"] = "unknown"
    elif mutation == "no_review": manifest.pop("grounding_contract")
    elif mutation == "old_prompt": manifest["prompt_version"] = "old"
    elif mutation == "version": manifest["contract_version"] = "old"
    elif mutation == "mixed_policy": manifest["task_boundary_contract"] = "1.1" if policy == "1.0" else "1.0"
    if mutation == "none":
        assert _task_boundary_policy(manifest)
        assert not _task_boundary_policy({"prompt_version": "old"})
    else:
        with pytest.raises(ValueError, match="작업 경계"):
            _task_boundary_policy(manifest)


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
    payload = grounding.build_grounding_input("AGENT1", request, cp1_requirements(), analysis,
        include_task_boundaries=True)
    coverage = [i for i in payload["items"] if i["kind"] == "REQUEST_COVERAGE"]
    assert [i["content"]["source_text"] for i in coverage] == [request.after_value, request.description]
    assert coverage[0]["content"]["analysis"] == analysis.model_dump(mode="json")
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "REQUEST_COVERAGE/after_value").update(verdict=verdict)
    assert grounding.check_review_record(payload, record).status.value == expected
    record["review"]["items"] = [i for i in record["review"]["items"] if not i["item_id"].startswith("REQUEST_COVERAGE")]
    assert grounding.check_review_record(payload, record).status == CheckStatus.FAIL
    # Explicit scripted judgment: routing/coverage, not live detection accuracy.


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("previous,current", [(False, True), ("1.0", "1.1")])
def test_task_boundary_review_cannot_reuse_old_judgment(stage, previous, current):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    artifact = {"AGENT1": analysis, "AGENT2": design, "AGENT3": agent3_plan()}[stage]
    opts = dict(analysis=analysis, test_case=agent3_test_case(), observation=agent3_observation(),
        include_execution_contract=True, include_review_responsibilities=True)
    old = grounding.build_grounding_input(stage, request, cp2_requirements(), artifact, **opts, include_task_boundaries=previous)
    new = grounding.build_grounding_input(stage, request, cp2_requirements(), artifact, **opts, include_task_boundaries=current)
    assert old.get("task_boundary_contract") == ("1.0" if previous else None)
    assert next(d["text"] for d in new["source_documents"] if d["source_id"] == "TASK_BOUNDARIES") == pipeline.QA_TASK_BOUNDARIES
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(new, fake_grounding_record(old))
    assert grounding.check_review_record(old, fake_grounding_record(old)).status == CheckStatus.PASS


@pytest.mark.parametrize("mutation", ["unknown", "no_review", "downgraded"])
def test_output_tolerance_policy_cannot_bypass_review(mutation):
    from qa_pipeline_execution import _current_agent2_contract, _output_tolerance_policy
    manifest = _current_agent2_contract()
    assert _output_tolerance_policy(manifest)
    if mutation == "unknown": manifest["output_tolerance_contract"] = "unknown"
    if mutation == "no_review": manifest["grounding_contract"] = None
    if mutation == "downgraded": manifest.pop("output_tolerance_contract")
    with pytest.raises(ValueError, match="출력 허용 계약"):
        _output_tolerance_policy(manifest)


@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
def test_output_tolerance_review_hash_cannot_be_reused_as_legacy(stage):
    old = review_payload(stage)
    new = {**old, "output_tolerance_contract": "1.0"}
    for payload, record in [(new, fake_grounding_record(old)), (old, fake_grounding_record(new))]:
        with pytest.raises(ValueError, match="해시"):
            grounding.check_review_record(payload, record)
    unknown = {**old, "output_tolerance_contract": "unknown"}
    with pytest.raises(ValueError, match="출력 허용 계약"):
        grounding.check_review_record(unknown, fake_grounding_record(unknown))


@pytest.mark.parametrize('verdict,expected', [('SUPPORTED', 'PASS'), ('UNSUPPORTED', 'FAIL'), ('UNCERTAIN', 'REVIEW')])
@pytest.mark.parametrize('text', ['AUTO 적용 직후 화면에 허용된 값이 표시된다.', '화면 값은 99로 변경된다.'])
def test_prose_value_guard_is_replaced_by_required_review_not_automatic_success(text, verdict, expected):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    design.test_cases[0].expected_results[0].statement = text
    old = evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False)
    new = evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False,
                               review_expected_result_values=True)
    if '99' in text:
        assert cp2_check(old, 'CP2-017').status == CheckStatus.FAIL
    assert cp2_check(new, 'CP2-017').status == CheckStatus.PASS
    payload = grounding.build_grounding_input('AGENT2', request, cp2_requirements(), design, analysis=analysis,
        include_condition_coverage=True, include_execution_contract=True, include_review_responsibilities=True)
    record = fake_grounding_record(payload, verdict=verdict)
    # Scripted verdict tests routing, NOT the model's ability to identify 99 as wrong.
    combined = grounding.attach_grounding_check(new, grounding.check_review_record(payload, record))
    assert combined.status.value == expected


@pytest.mark.parametrize('mutation', ['missing_marker', 'unknown_marker', 'missing_review', 'old_version', 'old_prompt'])
@pytest.mark.parametrize('stage', ['AGENT2', 'AGENT3'])
def test_review_responsibility_policy_cannot_be_silently_downgraded(stage, mutation):
    from qa_pipeline_execution import _review_responsibility_policy
    manifest = {'contract_version': '3.13' if stage == 'AGENT2' else '4.10',
        'prompt_version': 'agent2-2.45' if stage == 'AGENT2' else 'agent3-3.36',
        'wording_policy': 'STRUCTURAL_ONLY_V1', 'grounding_contract': '1.0', 'review_responsibility_contract': '1.0'}
    assert _review_responsibility_policy(manifest, stage)
    key, value = {'missing_marker': ('review_responsibility_contract', None),
        'unknown_marker': ('review_responsibility_contract', 'unknown'), 'missing_review': ('grounding_contract', None),
        'old_version': ('contract_version', 'old'), 'old_prompt': ('prompt_version', 'old')}[mutation]
    manifest[key] = value
    with pytest.raises(ValueError, match='검토 책임 계약'):
        _review_responsibility_policy(manifest, stage)


def test_old_review_payload_does_not_acquire_new_fields():
    case, plan, observation = precondition_guard_fixture()
    old = grounding.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=observation,
                                           include_execution_contract=True)
    new = grounding.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=observation,
                                           include_execution_contract=True, include_review_responsibilities=True)
    assert 'compiler_plan_facts' not in old['context']
    assert not any(i['kind'] == 'PRECONDITION_COVERAGE' for i in old['items'])
    assert any(i['kind'] == 'PRECONDITION_COVERAGE' for i in new['items'])
    with pytest.raises(ValueError, match='해시'):
        grounding.check_review_record(new, fake_grounding_record(old))


@pytest.mark.parametrize('stage', ['AGENT2', 'AGENT3'])
def test_generation_and_review_share_execution_contract_without_changing_legacy_payload(stage):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    kwargs = dict(analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG) if stage == 'AGENT2' else dict(
        test_case=agent3_test_case(), observation=agent3_observation())
    artifact = design if stage == 'AGENT2' else agent3_plan()
    old = grounding.build_grounding_input(stage, request, cp2_requirements(), artifact, **kwargs)
    new = grounding.build_grounding_input(stage, request, cp2_requirements(), artifact, **kwargs, include_execution_contract=True)
    assert not any(d['source_id'] == 'EXECUTION_CONTRACT' for d in old['source_documents'])
    assert next(d['text'] for d in new['source_documents'] if d['source_id'] == 'EXECUTION_CONTRACT') == pipeline.QA_EXECUTION_CONTRACT
    assert pipeline.QA_EXECUTION_CONTRACT in pipeline.AGENT2_SYSTEM_INSTRUCTIONS
    assert pipeline.QA_EXECUTION_CONTRACT in pipeline.AGENT3_SYSTEM_INSTRUCTIONS
    assert grounding.check_review_record(old, fake_grounding_record(old)).status == CheckStatus.PASS
    with pytest.raises(ValueError, match='해시'):
        grounding.check_review_record(new, fake_grounding_record(old))
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
    kwargs = dict(analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG, include_condition_coverage=True)
    old = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design, **kwargs)
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        **kwargs, include_procedure_coverage=True)
    assert old == grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        **kwargs, include_procedure_coverage=False)
    item = next(i for i in payload["items"] if i["item_id"] == "PROCEDURE/0")
    assert item["content"]["source_text"] == note
    candidate = item["content"]["candidate_procedures"][0]
    assert candidate["preconditions"] == tc.preconditions
    assert candidate["steps"] == tc.steps
    assert candidate["restore_steps"] == tc.restore_steps
    assert any(d["text"] == request.out_of_scope[-1] for d in payload["source_documents"])
    # This proves evidence/routing, NOT that a live reviewer is always correct.
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "PROCEDURE/0")["verdict"] = (
        "SUPPORTED" if mutation == "normal" else "UNSUPPORTED")
    assert grounding.check_review_record(payload, record).status == (
        CheckStatus.PASS if mutation == "normal" else CheckStatus.FAIL)
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != "PROCEDURE/0"]
    assert grounding.check_review_record(payload, record).status == CheckStatus.FAIL
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(payload, fake_grounding_record(old))
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
        analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG,
        include_condition_coverage=True, include_procedure_coverage=True)
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
        analysis=analysis, include_procedure_coverage=True)
    items = [i for i in payload["items"] if i["kind"] == "PROCEDURE_COVERAGE"]
    assert [i["content"]["source_text"] for i in items] == analysis.procedure_notes
    assert all(i["content"]["candidate_procedures"] == [] for i in items)


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
    assert grounding.check_review_record(payload, record).status == CheckStatus.FAIL


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


@pytest.mark.parametrize("allow_tolerance", [False, True])
@pytest.mark.parametrize("stage", ["AGENT1", "AGENT2", "AGENT3"])
@pytest.mark.parametrize("mutation", ["none", "missing", "duplicate", "order", "unknown_id", "citation",
                                     "empty_citations", "unsupported", "uncertain", "hash", "stage", "contract"])
def test_grounding_coverage_evidence_and_decisions(stage, mutation, allow_tolerance):
    payload = review_payload(stage)
    if allow_tolerance:
        payload["output_tolerance_contract"] = "1.0"
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
    else:
        result = grounding.check_review_record(payload, record)
        assert result.status == (CheckStatus.PASS if mutation == "none" or (mutation == "order" and allow_tolerance) else
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


@pytest.mark.parametrize("stage", ["AGENT2", "AGENT3"])
def test_compound_expected_result_review_cannot_be_treated_as_complete(stage):
    payload = review_payload(stage)
    payload["output_tolerance_contract"] = "1.0"
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
        analysis=analysis, catalog=pipeline.EXISTING_REGRESSION_CATALOG, include_condition_coverage=True)
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


@pytest.mark.parametrize("stage,version", [("AGENT1", "2.11"), ("AGENT2", "3.11"), ("AGENT2", "3.12"), ("AGENT2", "3.13"), ("AGENT3", "4.9"), ("AGENT3", "4.10")])
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
    payload['task_boundary_contract'] = '1.1'
    record = fake_grounding_record(payload)
    items = record['review']['items']
    if fault == 'missing_item': items.pop()
    elif fault == 'duplicate_item': items.append(dict(items[0]))
    elif fault == 'wrong_quote': items[0]['citations'][0]['quote'] = 'not-in-original-source-98765'
    else:
        items[0].update(verdict='UNSUPPORTED' if fault.startswith('unsupported') else 'SUPPORTED', citations=[])
    with pytest.raises(ValueError, match='검토 응답 오류'):
        grounding.check_review_record(payload, record)
    old = dict(payload, task_boundary_contract='1.0')
    legacy = dict(record, input_sha256=grounding._review_digest(old))
    assert grounding.check_review_record(old, legacy).status == CheckStatus.FAIL


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
@pytest.mark.parametrize("new_policy", [False, True])
def test_extension_review_checks_reasons_not_prohibited_assertions(verdict, expected, new_policy):
    case, plan, observation = structured_restoration_fixture()
    plan = pipeline.Agent3AutomationPlan(tc_id=case.tc_id, target_device_id=1,
        summary="지원 확장 검토", planning_status="AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
        extension_reasons=["TC에 필요한 관찰을 현재 화면 정보로 연결할 수 없습니다."])
    payload = grounding.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=observation,
        include_review_responsibilities=new_policy)
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
