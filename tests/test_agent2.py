"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *

@pytest.mark.parametrize("field,initial,target", [
    ("status", "OPERATION", "STOP"), ("setTemp", 29, 22), ("locked", False, True)])
@pytest.mark.parametrize("layout", ["split", "reversed_comparisons", "different_prose", "shared_prose"])
def test_live_restoration_layout_preserves_every_reader(field, initial, target, layout):
    from qa_pipeline_agent2 import _normalize_agent2_live_design
    case = repeated_restoration_fixture(field, initial, target)
    if layout == "different_prose":
        for index, c in enumerate(case.restoration.confirmations):
            c.source_text += f" (확인 {index + 1})"
            c.comparisons[0].source_excerpt = c.source_text
    elif layout == "shared_prose":
        for c in case.restoration.confirmations:
            c.source_text = "각 연결 대상이 준비 전 관찰 상태와 같은지 확인한다."
            c.comparisons[0].source_excerpt = c.source_text
    elif layout == "reversed_comparisons":
        first, second, third, fourth = case.restoration.confirmations
        for a, b in ((first, third), (second, fourth)):
            a.result_ids += b.result_ids
            a.comparisons = b.comparisons + a.comparisons
        case.restoration.confirmations = [first, second]
    case.restore_steps = case.restoration.operation_steps + [c.source_text for c in case.restoration.confirmations]
    before = case.model_dump(mode="json")
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    normalized, changes = _normalize_agent2_live_design(design)
    after = normalized.test_cases[0]
    assert case.model_dump(mode="json") == before
    assert pipeline._structured_restoration_errors(after) == []
    assert pipeline.tc_execution_spec_errors(after) == []
    assert case.model_dump(exclude={"restoration", "restore_steps"}) == after.model_dump(exclude={"restoration", "restore_steps"})
    def links(tc):
        return sorted((c.source_text, x.result_id, x.source_excerpt, x.basis.value)
                      for c in tc.restoration.confirmations for x in c.comparisons)
    assert links(case) == links(after)
    assert case.restoration.operation_steps == after.restoration.operation_steps
    assert bool(changes) == (layout != "different_prose")
    again, repeated_changes = _normalize_agent2_live_design(normalized)
    assert again.model_dump() == normalized.model_dump() and not repeated_changes


@pytest.mark.parametrize("fault", [
    "missing_er", "duplicate_er", "unknown_er", "wrong_basis", "excerpt",
    "missing_comparison", "duplicate_comparison", "missing_mirror", "duplicate_operation",
    "operation_is_confirmation", "unknown_target", "duplicate_expected_id"])
def test_live_restoration_layout_does_not_repair_broken_contract(fault):
    from qa_pipeline_agent2 import _normalize_agent2_live_design
    case = repeated_restoration_fixture()
    c = case.restoration.confirmations[0]
    if fault == "missing_er":
        case.restoration.confirmations.pop()
    elif fault == "duplicate_er":
        case.restoration.confirmations.append(c.model_copy(deep=True))
    elif fault == "unknown_er":
        c.result_ids = ["ER-999"]; c.comparisons[0].result_id = "ER-999"
    elif fault == "wrong_basis":
        c.comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    elif fault == "excerpt":
        c.comparisons[0].source_excerpt += " 변경"
    elif fault == "missing_comparison":
        c.comparisons = []
    elif fault == "duplicate_comparison":
        c.comparisons.append(c.comparisons[0].model_copy(deep=True))
    elif fault == "duplicate_operation":
        case.restoration.operation_steps *= 2
    elif fault == "operation_is_confirmation":
        case.restoration.operation_steps[0] = c.source_text
    elif fault == "unknown_target":
        case.expected_results[0].observation_target = None
    elif fault == "duplicate_expected_id":
        case.expected_results[-1].result_id = case.expected_results[0].result_id
    case.restore_steps = case.restoration.operation_steps + [x.source_text for x in case.restoration.confirmations]
    if fault == "missing_mirror":
        case.restore_steps.pop()
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    after, changes = _normalize_agent2_live_design(design)
    assert not changes
    assert after.model_dump() == design.model_dump()
    assert pipeline._structured_restoration_errors(after.test_cases[0])


@pytest.mark.parametrize("field,initial,target", [
    ("status", "OPERATION", "STOP"), ("setTemp", 27, 21), ("locked", False, True)])
@pytest.mark.parametrize("variant,valid", [
    ("paired", True), ("extra_panel", True), ("separate_read_lines", True),
    ("different_action", False), ("different_condition", True),
    ("missing_ui", False), ("missing_internal", False)])
def test_double_assert_execution_anchors(field, initial, target, variant, valid):
    case, _ = mapped_tc_fixture(field, initial, target)
    case.double_assert_policy = DoubleAssertPolicy.REQUIRED
    spec = case.execution_spec
    test_ops = [op for op in spec.operations if op.phase == pipeline.AutomationPhase.TEST]
    if variant == "extra_panel":
        case.expected_results.append(case.expected_results[0].model_copy(deep=True, update={
            "result_id": "ER-099", "verify_after_step": case.steps[0],
            "statement": f"패널의 {field} 선택 값은 {target}이다.",
            "observation_target": f"패널의 {field}"}))
        spec.verifications.append(spec.verifications[0].model_copy(deep=True, update={
            "result_id": "ER-099", "after_action_id": test_ops[0].action_id,
            "target": f"panel.{field}"}))
    elif variant == "separate_read_lines":
        case.steps.extend(["적용된 카드 상태를 확인한다.", "적용된 내부 상태를 확인한다."])
        case.expected_results[0].verify_after_step = case.steps[-2]
        case.expected_results[1].verify_after_step = case.steps[-1]
    elif variant == "different_action":
        case.expected_results[0].verify_after_step = case.steps[0]
        spec.verifications[0].after_action_id = test_ops[0].action_id
    elif variant == "different_condition":
        case.expected_results[0].source_condition_ids = ["COND-098"]
    elif variant.startswith("missing_"):
        index = 0 if variant == "missing_ui" else 1
        case.expected_results.pop(index)
        spec.verifications.pop(index)
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert (cp2_check(result, "CP2-006").status == CheckStatus.PASS) == valid
    if variant in {"paired", "extra_panel", "separate_read_lines"}:
        assert not pipeline.tc_execution_spec_errors(case)


@pytest.mark.parametrize("field,initial,target", [
    ("status", "OPERATION", "STOP"), ("setTemp", 28, 22), ("locked", False, True)])
def test_live_reference_whitespace_normalization_preserves_source_and_values(field, initial, target):
    from qa_pipeline_agent2 import _normalize_agent2_live_design
    case, _ = mapped_tc_fixture(field, initial, target)
    case.expected_results[0].verify_after_step = "  " + "  ".join(case.steps[-1].split()) + "\n"
    case.execution_spec.operations[-1].source_text += "  "
    case.execution_spec.precondition_verifications[0].source_text += "\t"
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    before = design.model_dump()
    normalized, changes = _normalize_agent2_live_design(design)
    assert design.model_dump() == before
    assert len(changes) == 3
    assert not pipeline.tc_execution_spec_errors(normalized.test_cases[0])
    assert normalized.test_cases[0].steps == case.steps
    assert normalized.test_cases[0].expected_results[0].statement == case.expected_results[0].statement
    assert normalized.test_cases[0].execution_spec.verifications == case.execution_spec.verifications
    again, second_changes = _normalize_agent2_live_design(normalized)
    assert again == normalized and not second_changes


@pytest.mark.parametrize("fault", ["wording", "value", "ambiguous"])
def test_live_reference_normalization_does_not_guess(fault):
    from qa_pipeline_agent2 import _normalize_agent2_live_design
    case, _ = mapped_tc_fixture("setTemp", 28, 22)
    if fault == "ambiguous":
        case.steps.append("  ".join(case.steps[0].split()))
        case.expected_results[0].verify_after_step = "\t" + case.steps[0]
    elif fault == "value":
        case.expected_results[0].verify_after_step = case.steps[0].replace("22", "23")
    else:
        case.expected_results[0].verify_after_step = case.steps[-1] + " 완료"
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    normalized, changes = _normalize_agent2_live_design(design)
    assert not changes and normalized == design
    assert pipeline.tc_execution_spec_errors(normalized.test_cases[0])


def essential_cp2(design):
    return evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())


@pytest.mark.parametrize("field,initial,target", [
    ("status", "OPERATION", "STOP"), ("setTemp", 27, 21), ("locked", False, True)])
@pytest.mark.parametrize("variant", ["group_label", "duplicate_values", "record_flag", "purpose_label", "dependency_mention"])
def test_essential_checks_use_execution_not_presentation(field, initial, target, variant):
    case, _ = mapped_tc_fixture(field, initial, target)
    if variant == "group_label":
        case.condition_execution = pipeline.ConditionExecution.SEQUENTIAL_TRANSITION
        case.grouping_reason = None
    elif variant == "duplicate_values":
        case.test_data.requested_modes = ["HEAT", "HEAT"]
    elif variant == "record_flag":
        case.test_data.restore_observed_hvac_state = True
        case.test_data.requested_mode = case.test_data.requested_temperature_c = None
    elif variant == "purpose_label":
        case.purpose = TcPurpose.RELATED_REGRESSION
    else:
        # Readable text is preserved verbatim, including a reference to another
        # test; mentioning it alone must not prove a dependency.
        line = "앞선 TC와 비교 가능한 기록을 남기되 이 시험은 현재 장비에서 시작한다."
        case.preconditions.append(line)
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    case.independent_execution = True
    case.source_condition_ids = [c.condition_id for c in cp2_analysis().confirmed_conditions]
    before = design.model_dump()
    cp = essential_cp2(design)
    rule = "CP2-016" if variant == "purpose_label" else "CP2-013" if variant == "dependency_mention" else "CP2-015"
    assert cp2_check(cp, rule).status == CheckStatus.PASS, cp.model_dump_json(indent=2)
    assert design.model_dump() == before
    # Never turn malformed executable data into PASS.
    case.execution_spec.verifications.pop()
    assert cp2_check(essential_cp2(design), "CP2-024").status == CheckStatus.FAIL


def test_essential_duplicate_title_does_not_hide_duplicate_ids():
    design = cp2_valid_design()
    other = design.test_cases[0].model_copy(deep=True)
    other.tc_id = "TC-CAND-099"
    for i, er in enumerate(other.expected_results):
        er.result_id = f"ER-{i + 900:03d}"
    design.test_cases.append(other)
    assert cp2_check(essential_cp2(design), "CP2-002").status == CheckStatus.PASS
    other.tc_id = design.test_cases[0].tc_id
    assert cp2_check(essential_cp2(design), "CP2-002").status == CheckStatus.FAIL


def test_essential_state_label_does_not_override_explicit_layer_policy():
    design = cp2_valid_design()
    case = design.test_cases[0]
    case.test_type = TcType.STATE_CONSISTENCY
    case.expected_results = [er for er in case.expected_results if er.observation_layer == ObservationLayer.UI]
    case.double_assert_policy = DoubleAssertPolicy.UI_ONLY
    case.double_assert_reason = None
    assert cp2_check(essential_cp2(design), "CP2-006").status == CheckStatus.PASS
    case.double_assert_policy = DoubleAssertPolicy.REQUIRED
    assert cp2_check(essential_cp2(design), "CP2-006").status == CheckStatus.FAIL


@pytest.mark.parametrize("value,valid", [(None, True), ("---", True), ("24°C", False), ("", False)])
def test_fixed_text_accepts_identical_expectation_without_mutating_tc(value, valid):
    case, plan = controller_lifecycle_fixture("mode", "COOL", "DRY")
    case, _ = frozen_tc_and_bindings(case, plan)
    check = case.execution_spec.verifications[0]
    check.strategy = pipeline.AssertionStrategy.DISABLED_TEMPERATURE_TEXT
    check.expected_fields = []
    check.expected_value = check.expected_number = None
    check.expected_text = value
    before = case.model_dump()
    errors = pipeline.tc_execution_spec_errors(case)
    assert (not any("자료형" in error for error in errors)) == valid
    assert case.model_dump() == before


@pytest.mark.parametrize("strategy", list(pipeline.AssertionStrategy))
def test_text_contract_rejects_unused_text_for_other_readers(strategy):
    from qa_pipeline_contracts import assertion_text_matches_contract, FIXED_ASSERTION_TEXT
    assert assertion_text_matches_contract(strategy, "---") == (
        strategy == pipeline.AssertionStrategy.UI_TEXT_CONTAINS or strategy in FIXED_ASSERTION_TEXT)


@pytest.mark.parametrize("role", list(ConditionChangeRole))
@pytest.mark.parametrize("values", [("MED", "HIGH"), ("18°C", "30°C")])
def test_reuse_target_alignment_preserves_condition_roles(role, values):
    request, analysis, design, catalog = compound_reuse_fixture(values)
    analysis.confirmed_conditions[0].change_role = role
    analysis.requirement_effects[0].relation = RequirementRelation.VERIFY
    before = analysis.model_dump()
    new = evaluate_checkpoint2(request, analysis, design, cp2_requirements(), existing_catalog=catalog)
    assert (cp2_check(new, "CP2-008").status == CheckStatus.PASS) == (role != ConditionChangeRole.SUPPORTING)
    assert analysis.model_dump() == before


@pytest.mark.parametrize("fault", ["wrong_requirement", "missing_link", "unknown_tc"])
def test_reuse_alignment_does_not_accept_unrelated_selection(fault):
    request, analysis, design, catalog = compound_reuse_fixture(layout="one_complete")
    analysis.confirmed_conditions[0].change_role = ConditionChangeRole.UNCHANGED
    if fault == "wrong_requirement":
        analysis.confirmed_conditions[0].requirement_ids = ["REQ-STATE-001"]
    elif fault == "missing_link":
        design.related_existing_tests[0].source_condition_ids = []
    else:
        design.related_existing_tests[0].tc_id = "TC-UNKNOWN-999"
    result = evaluate_checkpoint2(request, analysis, design, cp2_requirements(),
        existing_catalog=catalog)
    assert cp2_check(result, "CP2-008").status == CheckStatus.FAIL


@pytest.mark.parametrize("field,initial,target", [
    ("setTemp", 16, 15), ("setTemp", 30, 31), ("status", "OPERATION", "STOP")])
def test_boundary_execution_definition_does_not_require_redundant_metadata(field, initial, target):
    case, _ = mapped_tc_fixture(field, initial, target, blocked=True)
    case.test_type = TcType.BOUNDARY
    case.test_data.requested_mode = case.test_data.requested_temperature_c = None
    case.test_data.requested_modes = []
    case.test_data.requested_temperatures_c = []
    if field == "setTemp":
        op = next(o for o in case.execution_spec.operations
                  if o.phase == AutomationPhase.TEST and o.action_type == AutomationActionType.SET_TEMPERATURE)
        op.action_type, op.value = AutomationActionType.CLICK, None
        op.target = "temperature.decrease" if target < initial else "temperature.increase"
        case.steps[0] = op.source_text = "온도 감소 버튼을 누른다." if target < initial else "온도 증가 버튼을 누른다."
    before = case.model_dump()
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    new = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(new, "CP2-010").status == CheckStatus.PASS
    assert cp2_check(new, "CP2-024").status == CheckStatus.PASS
    assert case.model_dump() == before
    case.execution_spec.verifications.pop()
    broken = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(broken, "CP2-024").status == CheckStatus.FAIL
    assert cp2_check(broken, "CP2-010").status == CheckStatus.FAIL


@pytest.mark.parametrize("rewrite", [False, True])
def test_agent2_exact_connection_catalog_initial_and_rewrite(rewrite):
    from qa_pipeline_agent3 import controller_connection_catalog
    responses = Agent2FakeResponses()
    extra = {"previous_design": agent2_design(), "checkpoint_feedback": ["항목 확인"]} if rewrite else {}
    OpenAIAgent2(client=SimpleNamespace(responses=responses)).design(
        cp1_request(), cp2_analysis(), cp2_requirements(), **extra)
    text = responses.kwargs["input"][1]["content"]
    raw = text.split("[실행 연결표의 정확한 항목 목록]\n", 1)[1]
    options = json.JSONDecoder().raw_decode(raw)[0]
    catalog = controller_connection_catalog()
    explanation = options.pop("temperature_interface")
    assert "입력칸이 아니라 증가·감소 버튼과 표시창" in explanation
    assert "기대값·확인 시점은 요청/SRS" in explanation
    assert options == {
        "actions": {k: v[0] for k, v in catalog["actions"].items()},
        "readers": {k: list(v) for k, v in catalog["readers"].items()},
        "preconditions": {k: v[0] for k, v in catalog["preconditions"].items()},
    }
    assert {k for k in options["preconditions"] if k.startswith("context.")} == {
        "context.target_device_visible", "context.error_free", "context.unlocked", "context.online"}
    assert options["readers"]["temperature.increase"] == ["UI_ENABLED_EQUALS"]
    assert options["readers"]["temperature.decrease"] == ["UI_ENABLED_EQUALS"]
    assert "UI_ENABLED_EQUALS" not in options["readers"]["temperature.display"]
    assert "context.target_device_visible/error_free/unlocked/online" not in AGENT2_SYSTEM_INSTRUCTIONS
    assert "unsupported.<요청 항목명>" in AGENT2_SYSTEM_INSTRUCTIONS
    encoded = json.dumps(options)
    assert not any(token in encoded for token in ("#device", ".detail-panel", "window.__", str(REPO_ROOT)))


def test_agent2_connection_options_follow_runtime_catalog(monkeypatch):
    import qa_pipeline_agent3 as agent3
    catalog = agent3.controller_connection_catalog()
    catalog["preconditions"]["context.future_probe"] = ("BASELINE_CONTEXT", "private-reader")
    monkeypatch.setattr(agent3, "controller_connection_catalog", lambda: catalog)
    responses = Agent2FakeResponses()
    OpenAIAgent2(client=SimpleNamespace(responses=responses)).design(
        cp1_request(), cp2_analysis(), cp2_requirements())
    text = responses.kwargs["input"][1]["content"]
    assert '"context.future_probe": "BASELINE_CONTEXT"' in text
    assert "private-reader" not in text


def test_frozen_tc_live_schema_requires_execution_spec_without_selectors():
    from openai.lib._pydantic import to_strict_json_schema
    schema = to_strict_json_schema(pipeline.LiveAgent2TestDesign)
    candidate = schema["$defs"]["LiveProductTestCaseCandidate"]
    assert "execution_spec" in candidate["required"]
    assert {"$ref": "#/$defs/LiveTcExecutionSpec"} in candidate["properties"]["execution_spec"]["anyOf"]
    assert "binding_contract" in schema["$defs"]["LiveTcExecutionSpec"]["required"]
    assert "target" in schema["$defs"]["LiveTcVerification"]["required"]
    for name in ("TcOperation", "LiveTcVerification", "TcPreconditionVerification"):
        assert "selector" not in schema["$defs"][name]["properties"]
        assert schema["$defs"][name]["additionalProperties"] is False
    old = agent3_test_case()
    before = old.model_dump(mode="json")
    assert "execution_spec" not in before
    assert pipeline.ProductTestCaseCandidate.model_validate(before).model_dump(mode="json") == before
    with pytest.raises(ValueError):
        pipeline.LiveProductTestCaseCandidate.model_validate(before)
    with pytest.raises(ValueError):
        pipeline.LiveProductTestCaseCandidate.model_validate({**before, "execution_spec": None})
    manual = pipeline.LiveProductTestCaseCandidate.model_validate({
        **before, "execution_spec": None, "automation_candidate": False})
    assert manual.execution_spec is None


@pytest.mark.parametrize("mutation", ["none", "missing_er", "duplicate_id", "wrong_source", "wrong_time", "wrong_layer", "wrong_shape"])
def test_frozen_tc_definition_reference_validation(mutation):
    case, plan = controller_lifecycle_fixture("fanSpeed", "HIGH", "LOW")
    case, _ = frozen_tc_and_bindings(case, plan)
    spec = case.execution_spec
    if mutation == "missing_er":
        spec.verifications.pop()
    elif mutation == "duplicate_id":
        spec.operations[1].action_id = spec.operations[0].action_id
    elif mutation == "wrong_source":
        spec.operations[0].source_text = "TC에 없는 별도 조작"
    elif mutation == "wrong_time":
        spec.verifications[0].after_action_id = spec.operations[-1].action_id
    elif mutation == "wrong_layer":
        spec.verifications[0].observation_layer = ObservationLayer.INTERNAL_STATE
    elif mutation == "wrong_shape":
        spec.verifications[0].expected_number = 27
    assert bool(pipeline.tc_execution_spec_errors(case)) == (mutation != "none")


def test_frozen_tc_technical_id_repair_updates_verification_refs():
    case, plan = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    case, _ = frozen_tc_and_bindings(case, plan)
    second = case.model_copy(deep=True)
    second.title = "두 번째 독립 TC"
    design = Agent2TestDesign(request_id="CR-FROZEN", test_cases=[case, second], coverage_summary="두 TC")
    normalized, changes = pipeline._normalize_agent2_technical_ids(design)
    assert changes
    for tc in normalized.test_cases:
        assert {v.result_id for v in tc.execution_spec.verifications} == {er.result_id for er in tc.expected_results}
        assert not pipeline.tc_execution_spec_errors(tc)
    assert design.test_cases[0].expected_results[0].result_id == case.expected_results[0].result_id


@pytest.mark.parametrize("basis", ["DIRECT_REQUEST", "REQUEST_TRACE_ONLY"])
@pytest.mark.parametrize("requirement,layer,rule", [
    ("REQ-STATE-001", ObservationLayer.INTERNAL_STATE, "CP2-006"),
    ("REQ-NOTIFY-001", ObservationLayer.NOTIFICATION, "CP2-007")])
def test_scope_labels_do_not_invent_observation_layers(basis, requirement, layer, rule):
    analysis, design = cp2_analysis(), detailed_boundary_design()
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == requirement)
    condition = next(c for c in analysis.confirmed_conditions if requirement in c.requirement_ids)
    # A UI-only request references a related requirement, not its entire scope.
    condition.statement = condition.source_text = "장비 카드에 현재 설정 온도를 표시한다."
    effect.scope_evidence = pipeline.RequirementScopeEvidence(basis=basis,
        request_condition_ids=[condition.condition_id], srs_source_text=condition.source_text)
    tc = design.test_cases[0]
    tc.expected_results = [r for r in tc.expected_results if r.observation_layer != layer]
    for result in tc.expected_results:
        if condition.condition_id in result.source_condition_ids:
            result.statement = condition.statement
    if layer == ObservationLayer.INTERNAL_STATE:
        tc.double_assert_policy = DoubleAssertPolicy.UI_ONLY
        tc.double_assert_reason = "화면 표시 확인만 요청되었습니다."
    new = pipeline.evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())
    assert cp2_check(new, rule).status == CheckStatus.PASS
    # This isolates the structural rule; mandatory meaning review decides actual scope.


@pytest.mark.parametrize("basis", ["DIRECT_REQUEST", "REQUEST_TRACE_ONLY"])
@pytest.mark.parametrize("required_by", ["policy", "type"])
def test_scope_relaxation_keeps_explicit_double_assert_contract(basis, required_by):
    """An explicit REQUIRED policy needs both layers; a STATE_CONSISTENCY label alone does not."""
    analysis, design = cp2_analysis(), detailed_boundary_design()
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == "REQ-STATE-001")
    effect.scope_evidence = pipeline.RequirementScopeEvidence(basis=basis,
        request_condition_ids=["COND-002"], srs_source_text="UI와 내부 상태 일치")
    tc = design.test_cases[0]
    tc.expected_results = [r for r in tc.expected_results if r.observation_layer != ObservationLayer.INTERNAL_STATE]
    tc.double_assert_policy = DoubleAssertPolicy.REQUIRED if required_by == "policy" else DoubleAssertPolicy.UI_ONLY
    if required_by == "type":
        tc.test_type = TcType.STATE_CONSISTENCY
    result = pipeline.evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())
    expected = CheckStatus.FAIL if required_by == "policy" else CheckStatus.PASS
    assert cp2_check(result, "CP2-006").status == expected

@pytest.mark.parametrize("relation,proposal_required", [("VERIFY", False), ("MODIFIED", True)])
def test_baseline_test_does_not_require_srs_revision(relation, proposal_required):
    from qa_pipeline_agent2 import _srs_revision_policy
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    for effect in analysis.requirement_effects:
        if effect.requirement_id == request.target_requirement_id:
            effect.relation = RequirementRelation(relation)
    policy = _srs_revision_policy(request, analysis, cp2_requirements())
    assert (request.target_requirement_id in policy["required_requirement_ids"]) is proposal_required
    design.srs_revision_proposals = []
    cp = evaluate_checkpoint2(request, analysis, design, cp2_requirements(), existing_catalog=())
    assert cp2_check(cp, "CP2-018").status == (CheckStatus.FAIL if proposal_required else CheckStatus.PASS)


@pytest.mark.parametrize('values,excluded', [(('MED', 'HIGH'), 'LOW'), (('21', '27'), '16')])
@pytest.mark.parametrize('suffix', [' {value}는 제외한다.', ' 이전 값 {value}의 검사는 요구하지 않는다.'])
def test_reuse_value_roles_do_not_turn_exclusions_into_tests(values, excluded, suffix):
    request, analysis, design, catalog = compound_reuse_fixture(values)
    statement = analysis.confirmed_conditions[0].statement + suffix.format(value=excluded)
    request.after_value = statement
    analysis.confirmed_conditions[0].statement = statement
    analysis.confirmed_conditions[0].source_text = statement
    requirements = cp2_requirements()
    design.srs_revision_proposals = [pipeline.SrsRevisionProposal(proposal_id='SRS-REV-001',
        requirement_id='REQ-TEMP-001', source_condition_ids=['COND-010'],
        current_acceptance_criteria=requirements['REQ-TEMP-001'].acceptance_criteria,
        proposed_acceptance_criteria=statement, reason='요청한 변경 기준')]
    new = evaluate_checkpoint2(request, analysis, design, requirements, existing_catalog=catalog)
    assert new.status == CheckStatus.PASS, new.model_dump_json(indent=2)
    hints = pipeline._existing_reuse_link_context(analysis, catalog, design, include_value_tokens=False)
    assert all('detected_values' not in h and 'values_not_covered_by_links' not in h for h in hints)
    assert hints[0]['condition'] == statement


@pytest.mark.parametrize('layout', ['missing_link', 'actual_gap'])
@pytest.mark.parametrize('verdict,expected', [('UNSUPPORTED', 'FAIL'), ('UNCERTAIN', 'REVIEW')])
def test_reuse_missing_required_coverage_still_blocks_in_semantic_review(layout, verdict, expected):
    import qa_pipeline_grounding as g
    request, analysis, design, catalog = compound_reuse_fixture(layout=layout)
    payload = g.build_grounding_input('AGENT2', request, cp2_requirements(), design, analysis=analysis,
        catalog=catalog)
    target = next(i for i in payload['items'] if i['item_id'] == 'CONDITION/COND-010')
    assert target['content']['condition']['statement'] == analysis.confirmed_conditions[0].statement
    record = fake_grounding_record(payload)
    item = next(i for i in record['review']['items'] if i['item_id'] == target['item_id'])
    item.update(verdict=verdict, reason='Scripted: required second operation is not covered by the linked tests.')
    assert g.check_review_record(payload, record).status.value == expected
    # Judgment is scripted, not proof that the model detects the omission.


@pytest.mark.parametrize("mutation,blocked", [
    ("empty_classification", False), ("missing_reason", False), ("both", False),
    ("wrong_feature_id", True), ("non_independent", True), ("dependent_setup", False),
    ("missing_requirement", True), ("missing_condition", True), ("missing_results", True),
])
def test_optional_explanations_do_not_replace_required_test_contract(mutation, blocked):
    design = cp2_valid_design()
    tc = design.test_cases[0]
    if mutation in {"empty_classification", "both"}:
        tc.common_qa_criteria = []
        tc.domain_qa_criteria = []
        tc.feature_requirement_ids = []
    if mutation in {"missing_reason", "both"}:
        tc.independence_reason = None
    if mutation == "wrong_feature_id": tc.feature_requirement_ids = ["REQ-UNKNOWN-999"]
    if mutation == "non_independent": tc.independent_execution = False
    if mutation == "dependent_setup": tc.preconditions = ["이전 TC가 완료한 장비 상태를 그대로 사용한다."]
    if mutation == "missing_requirement": tc.requirement_ids = []
    if mutation == "missing_condition": tc.source_condition_ids = []
    if mutation == "missing_results": tc.expected_results = []
    before = design.model_dump_json()
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert (result.status == CheckStatus.FAIL) == blocked
    assert design.model_dump_json() == before


@pytest.mark.parametrize("verdict,expected", [("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")])
def test_rephrased_procedure_needs_complete_semantic_review(verdict, expected):
    import qa_pipeline_grounding as grounding
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    note = "시험 시작 상태를 준비한 뒤 목표값을 적용하고 시험 뒤 원래 상태로 복원한다."
    request.acceptance_notes.append(note)
    analysis.procedure_notes = [note]
    design.test_cases[0].preconditions.append("시험할 초기 상태를 준비하고 확인한다.")
    new = evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert cp2_check(new, "CP2-014").status == CheckStatus.PASS
    payload = grounding.build_grounding_input("AGENT2", request, cp2_requirements(), design,
        analysis=analysis)
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == "PROCEDURE/ALL")["verdict"] = verdict
    combined = grounding.attach_grounding_check(new, grounding.check_review_record(payload, record))
    assert combined.status.value == expected


@pytest.mark.parametrize("wording", ["처음 기록한 설정으로 되돌립니다.", "Return to the saved settings."])
@pytest.mark.parametrize("mutation", ["none", "missing_contract", "missing_comparison", "changed_basis", "wrong_order"])
def test_structured_hvac_restore_does_not_require_magic_words(wording, mutation):
    request, analysis, design = cp1_request(), cp2_analysis(), detailed_boundary_design()
    tc = design.test_cases[0]
    tc.state_effect = pipeline.TcStateEffect.BLOCKED_CHANGE
    tc.restore_required = True
    tc.test_data.restore_observed_hvac_state = True
    confirmations = [pipeline.RestoreConfirmation(source_text=f"{r.observation_target}: 처음 기록한 값과 비교합니다.",
        result_ids=[r.result_id], comparisons=[pipeline.RestoreComparison(result_id=r.result_id,
            source_excerpt=f"{r.observation_target}: 처음 기록한 값과 비교합니다.", basis="OBSERVED_BASELINE")])
        for r in tc.expected_results if r.observation_layer != ObservationLayer.NOTIFICATION]
    tc.restoration = pipeline.StructuredRestoration(operation_steps=[wording],
        confirmations=confirmations, verify_when="AFTER_RESTORE")
    tc.restore_steps = [wording, *(c.source_text for c in confirmations)]
    if mutation == "missing_contract": tc.restoration = None
    elif mutation == "missing_comparison": tc.restoration.confirmations.pop()
    elif mutation == "changed_basis": tc.restoration.confirmations[0].comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    elif mutation == "wrong_order": tc.restore_steps.reverse()
    before = design.model_dump_json()
    result = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert (result.status == CheckStatus.PASS) == (mutation == "none"), result.model_dump()
    assert design.model_dump_json() == before


@pytest.mark.parametrize("scope", ["trace_only", "direct", "state_type", "explicit_double"])
def test_reference_only_srs_does_not_force_extra_state_assertion(scope):
    analysis, design = cp2_analysis(), detailed_boundary_design()
    tc = design.test_cases[0]
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == "REQ-STATE-001")
    effect.scope_evidence = pipeline.RequirementScopeEvidence(basis="REQUEST_TRACE_ONLY",
        request_condition_ids=["COND-002"], srs_source_text="UI와 내부 상태 일치")
    tc.expected_results = [r for r in tc.expected_results if r.observation_layer != ObservationLayer.INTERNAL_STATE]
    tc.double_assert_policy = DoubleAssertPolicy.UI_ONLY
    tc.double_assert_reason = "요청된 UI 결과만 확인하며 관련 SRS는 참고 근거입니다."
    if scope == "direct": effect.scope_evidence.basis = pipeline.ScopeBasis.DIRECT_REQUEST
    elif scope == "state_type": tc.test_type = TcType.STATE_CONSISTENCY
    elif scope == "explicit_double": tc.double_assert_policy = DoubleAssertPolicy.REQUIRED
    result = pipeline.evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())
    assert (cp2_check(result, "CP2-006").status == CheckStatus.PASS) == (scope != "explicit_double")


@pytest.mark.parametrize("wording", ["실행이 끝나면 처음 기록한 모습으로 되돌립니다.",
                                    "After the exercise, return to the captured state."])
def test_new_wording_policy_preserves_procedure_handoff_without_keywords(wording):
    request, analysis, design = cp1_request(), cp2_analysis(), detailed_boundary_design()
    request.acceptance_notes.append(wording)
    analysis.procedure_notes = [wording]
    first = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert cp2_check(first, "CP2-014").status == CheckStatus.PASS  # placement: mandatory review
    tc = design.test_cases[0]
    tc.restore_required = True
    tc.restore_steps.append(wording)
    preserved = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert cp2_check(preserved, "CP2-014").status == CheckStatus.PASS
    design.excluded_scope.append(wording)
    excluded = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert cp2_check(excluded, "CP2-014").status == CheckStatus.FAIL


@pytest.mark.parametrize("target", ["현재값 표시 영역", "설정치 표시부", "Current setting readout"])
def test_new_wording_policy_accepts_target_labels_but_requires_bindings(target):
    from qa_pipeline_agent2 import _tc_observation_binding_errors
    tc = detailed_boundary_design().test_cases[0]
    tc.expected_results[0].observation_target = target
    assert not _tc_observation_binding_errors(tc)
    tc.expected_results[0].verify_after_step = "없는 단계"
    assert _tc_observation_binding_errors(tc)
    tc.expected_results[0].observation_target = None
    assert len(_tc_observation_binding_errors(tc)) >= 2


@pytest.mark.parametrize("mutation", ["none", "id", "condition", "expected_value", "missing_target", "missing_timing"])
def test_new_wording_policy_preserves_cp2_integrity(mutation):
    request, analysis, design = cp1_request(), cp2_analysis(), detailed_boundary_design()
    er = design.test_cases[0].expected_results[0]
    if mutation == "id":
        design.request_id = "OTHER"
    elif mutation == "condition":
        er.source_condition_ids = ["COND-999"]
    elif mutation == "expected_value":
        er.statement += " 999°C"
    elif mutation == "missing_target":
        er.observation_target = None
    elif mutation == "missing_timing":
        er.verify_after_step = None
    cp = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    assert (cp.status == CheckStatus.PASS) == (mutation in {"none", "expected_value"}), cp.model_dump()


@pytest.mark.parametrize("mutation", ["valid", "missing", "omit_target", "wrong_target", "duplicate",
                                    "wrong_basis", "wrong_timing", "omit_operation", "order", "excerpt"])
def test_cp2_structured_restoration_checks_ids_coverage_and_policy(mutation):
    case, _, _ = structured_restoration_fixture()
    if mutation == "missing":
        case.restoration = None
    elif mutation == "omit_target":
        case.restoration.confirmations.pop()
    elif mutation == "wrong_target":
        case.restoration.confirmations[0].result_ids = ["ER-999"]
        case.restoration.confirmations[0].comparisons[0].result_id = "ER-999"
    elif mutation == "duplicate":
        case.restoration.confirmations.append(case.restoration.confirmations[0])
    elif mutation == "wrong_basis":
        case.restoration.confirmations[0].comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    elif mutation == "wrong_timing":
        case.restoration.verify_when = "BEFORE_RESTORE"
    elif mutation == "omit_operation":
        case.restoration.operation_steps = []
    elif mutation == "order":
        case.restore_steps.reverse()
    elif mutation == "excerpt":
        case.restoration.confirmations[0].comparisons[0].source_excerpt = "일부"
    design = cp2_valid_design().model_copy(update={"test_cases": [case]})
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert (cp2_check(result, "CP2-023").status == CheckStatus.PASS) is (mutation == "valid")


@pytest.mark.parametrize("field,initial,target", [
    ("status", "STOP", "OPERATION"), ("locked", False, True), ("setTemp", 27, 21),
])
@pytest.mark.parametrize("variant", ["duplicate", "grouped", "missing_result", "wrong_basis"])
def test_restoration_duplicate_feedback_preserves_each_result(field, initial, target, variant):
    case, plan = controller_lifecycle_fixture(field, initial, target)
    # Two test observations may use the same reader and baseline after restoration.
    # Retain both ER identities; only their restoration confirmation can be grouped.
    for index, original in enumerate(list(case.expected_results)):
        result_id = f"ER-{92 + index:03}"
        case.expected_results.append(original.model_copy(update={"result_id": result_id}))
        plan.assertions.append(plan.assertions[index].model_copy(update={"result_id": result_id}, deep=True))
        confirmation = case.restoration.confirmations[index]
        comparison = confirmation.comparisons[0].model_copy(update={"result_id": result_id})
        if variant == "duplicate":
            case.restoration.confirmations.append(confirmation.model_copy(update={
                "result_ids": [result_id], "comparisons": [comparison]}, deep=True))
        else:
            confirmation.result_ids.append(result_id)
            confirmation.comparisons.append(comparison)
    if variant == "missing_result":
        case.restoration.confirmations[0].result_ids.pop()
        case.restoration.confirmations[0].comparisons.pop()
    elif variant == "wrong_basis":
        case.restoration.confirmations[0].comparisons[-1].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    case.restore_steps = case.restoration.operation_steps + [c.source_text for c in case.restoration.confirmations]
    plan.restore_confirmations = case.restoration.confirmations
    before = case.model_dump_json(), plan.model_dump_json()
    errors = pipeline._structured_restoration_errors(case)
    _, plan_errors = pipeline._structured_restore_plan_coverage(case, plan)
    assert (not errors) is (variant == "grouped")
    assert (not plan_errors) is (variant == "grouped")
    assert all(error in plan_errors for error in errors)
    if variant == "duplicate":
        assert any("result_ids와 comparisons를 모두" in error and "삭제하지 마세요" in error for error in errors)
    assert before == (case.model_dump_json(), plan.model_dump_json())


def test_structured_restoration_read_only_and_strict_api_schema():
    from openai.lib._pydantic import to_strict_json_schema
    case, _, _ = structured_restoration_fixture()
    case.state_effect = pipeline.TcStateEffect.READ_ONLY
    case.restore_required, case.restore_steps = False, []
    case.restoration.operation_steps = []
    case.restoration.confirmations = []
    assert pipeline._structured_restoration_errors(case) == []
    schema = to_strict_json_schema(Agent2TestDesign)
    assert "restoration" in schema["$defs"]["ProductTestCaseCandidate"]["required"]
    assert set(schema["$defs"]["StructuredRestoration"]["required"]) == {"operation_steps", "confirmations", "verify_when"}
    case.restoration.operation_steps = ["변경"]
    assert pipeline._structured_restoration_errors(case)


def test_structured_restoration_id_normalization_keeps_local_references():
    case, _, _ = structured_restoration_fixture()
    original = cp2_valid_design().model_copy(update={"test_cases": [case, case.model_copy(deep=True)]})
    normalized, changes = pipeline._normalize_agent2_technical_ids(original)
    assert changes
    for tc in normalized.test_cases:
        assert pipeline._structured_restoration_errors(tc) == []
    assert original.test_cases[0].expected_results[0].result_id == "ER-090"
    ambiguous = case.model_copy(deep=True)
    ambiguous.expected_results[1].result_id = ambiguous.expected_results[0].result_id
    unchanged, changes = pipeline._normalize_agent2_technical_ids(original.model_copy(update={"test_cases": [ambiguous]}))
    assert not changes
    assert unchanged.test_cases[0].expected_results[0].result_id == unchanged.test_cases[0].expected_results[1].result_id
    dangling = original.model_copy(deep=True)
    dangling.test_cases[0].restoration.confirmations[0].result_ids = ["ER-001"]
    dangling.test_cases[0].restoration.confirmations[0].comparisons[0].result_id = "ER-001"
    unchanged, changes = pipeline._normalize_agent2_technical_ids(dangling)
    assert not changes  # ER-001 must not become valid through global renumbering.
    assert pipeline._structured_restoration_errors(unchanged.test_cases[0])


@pytest.mark.parametrize("target", ["대상 장비 카드의 온도", "대상 장비의 운전 모드", "대상 장비의 잠금 상태", "대상 장비의 풍량", "조회 화면의 장비 수"])
@pytest.mark.parametrize("mutation", [None, "missing_target", "wrong_step"])
def test_common_observation_binding_has_no_feature_specific_exception(target, mutation):
    from qa_pipeline_agent2 import _tc_observation_binding_errors
    tc = detailed_boundary_design().test_cases[0]
    tc.expected_results = [tc.expected_results[0]]
    er = tc.expected_results[0]
    er.observation_target = target
    er.statement = f"{target}가 요구된 값으로 표시된다."
    er.verify_after_step = tc.steps[-1]
    if mutation == "missing_target":
        er.observation_target = " "
    elif mutation == "wrong_step":
        er.verify_after_step = "존재하지 않는 적용 단계"
    assert bool(_tc_observation_binding_errors(tc)) == (mutation is not None)


def test_agent2_repair_receives_same_binding_diagnostics_without_mutation():
    from qa_pipeline_agent2 import _tc_observation_binding_errors
    design = detailed_boundary_design()
    design.test_cases[0].expected_results[0].observation_target = None
    original = design.model_dump_json()
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(client=SimpleNamespace(responses=responses))
    for extra in ({}, {"previous_design": design, "checkpoint_feedback": ["확인 대상 오류"]}):
        agent.design(cp1_request(), cp2_analysis(), cp2_requirements(), **extra)
        text = responses.kwargs["input"][1]["content"]
        assert json.dumps(pipeline.TC_OBSERVATION_BINDING_RULES, ensure_ascii=False) in text
        if extra:
            for error in _tc_observation_binding_errors(design.test_cases[0]):
                assert error in text
    assert design.model_dump_json() == original


@pytest.mark.parametrize("effect,restore,accepted", [
    (None, False, False), ("READ_ONLY", False, True), ("READ_ONLY", True, False),
    ("STATE_CHANGE", True, True), ("STATE_CHANGE", False, False),
    ("BLOCKED_CHANGE", True, True), ("BLOCKED_CHANGE", False, False),
])
def test_tc_state_restoration_policy_required_for_new_contract(effect, restore, accepted):
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.state_effect = pipeline.TcStateEffect(effect) if effect else None
    tc.restore_required = restore
    tc.restore_steps = ["대상 장비를 시험 전 상태로 복원한다."] if restore else []
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(result, "CP2-022").status == (CheckStatus.PASS if accepted else CheckStatus.FAIL)


def test_blocked_change_requires_state_observation_not_just_notification():
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.state_effect = pipeline.TcStateEffect.BLOCKED_CHANGE
    tc.restore_required, tc.restore_steps = True, ["초기 상태로 복원한다."]
    tc.expected_results = [r for r in tc.expected_results if r.observation_layer == ObservationLayer.NOTIFICATION]
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(result, "CP2-022").status == CheckStatus.FAIL
    assert "요구된 차단 결과의 대상 상태" in cp2_check(result, "CP2-022").message


@pytest.mark.parametrize("variant", ["mixed", "ui_code", "ui_literal_proved", "missing_ui_basis", "connector"])
def test_restore_drafting_separates_ui_labels_and_internal_codes(variant):
    from qa_pipeline_agent2 import _tc_restore_basis_errors
    case, _, _ = mixed_restore_comparison_fixture()
    if variant in {"ui_code", "ui_literal_proved"}:
        case.restore_steps[-1] = case.restore_steps[-1].replace("실행 전 상태와 같은지", "LOW인지")
    if variant == "ui_literal_proved":
        case.preconditions.append("풍량 표시의 초기값은 LOW이다.")
    if variant == "missing_ui_basis":
        case.restore_steps[-1] = case.restore_steps[-1].replace("실행 전 상태와 같은지", "정상인지")
    if variant == "connector":
        case.restore_steps[-1] = case.restore_steps[-1].replace("확인하고,", "확인하며,")
    assert bool(_tc_restore_basis_errors(case)) == (variant in {"ui_code", "missing_ui_basis"})


    # Multiple valid IDs alone never prove that their combined meaning is correct.


def test_trace_reference_does_not_force_unrequested_notification_layer():
    from qa_pipeline_contracts import RequirementScopeEvidence, ScopeBasis
    analysis, design = cp2_analysis(), cp2_valid_design()
    condition = analysis.confirmed_conditions[2]
    condition.statement = condition.source_text = "화면에 현재 설정 온도를 표시한다."
    analysis.requirement_effects[2].scope_evidence = RequirementScopeEvidence(
        basis=ScopeBasis.REQUEST_TRACE_ONLY, request_condition_ids=[condition.condition_id],
        srs_source_text="Toast 표시")
    expected = design.test_cases[0].expected_results[2]
    expected.statement = condition.source_text
    expected.observation_layer = ObservationLayer.UI
    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())
    assert not any(check.status == CheckStatus.FAIL and "알림" in check.message for check in result.checks)
    assert cp2_check(result, "CP2-017").status == CheckStatus.PASS


def test_new_tc_detail_keeps_steps_observation_locations_and_shared_timing():
    design = detailed_boundary_design()
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-020").status == CheckStatus.PASS
    assert design.test_cases[0].expected_results[0].verify_after_step == design.test_cases[0].expected_results[1].verify_after_step
    assert Agent2TestDesign.model_validate_json(design.model_dump_json()) == design


@pytest.mark.parametrize("mutation", [
    "missing_timing", "unknown_timing", "ambiguous_timing", "missing_target",
])
def test_new_tc_detail_rejects_unlinked_drafts(mutation):
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    if mutation == "missing_timing":
        tc.expected_results[0].verify_after_step = None
    elif mutation == "unknown_timing":
        tc.expected_results[0].verify_after_step = "존재하지 않는 조작"
    elif mutation == "ambiguous_timing":
        tc.steps.append(tc.steps[-1])
    else:
        tc.expected_results[0].observation_target = None
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(result, "CP2-020").status == CheckStatus.FAIL


def test_approved_reuse_context_preserves_spec_without_registration_metadata():
    approved, _ = pipeline.load_approved_regression_catalog(REPO_ROOT / "approved_assets")
    spec = approved[0]
    original = json.loads((REPO_ROOT / "approved_assets" / spec.test_case_file).read_text(encoding="utf-8"))["test_case"]
    context = json.loads(spec.reuse_context_json)
    for field in ("control_path", "target_role", "test_data", "preconditions", "steps",
                  "condition_execution", "intermediate_reset_steps", "restore_required",
                  "restore_steps", "independent_execution", "independence_reason"):
        assert context[field] == original[field]
    assert context["expected_results"] == [
        {**{key: result.get(key) for key in ("statement", "observation_layer", "verify_after_step")},
         **({"observation_target": result["observation_target"]}
            if result.get("observation_target") is not None else {})}
        for result in original["expected_results"]
    ]
    rendered = pipeline.render_existing_regression_context(approved)
    assert "사전조건/절차/기대결과/판정 시점/복원" in rendered
    for text in original["preconditions"] + original["steps"] + original["restore_steps"]:
        assert text in rendered
    for private_field in ("reviewer", "approval_note", "source_run_id", "source_condition_ids",
                          "test_case_file", "automation_file", "target_sha256"):
        assert private_field not in context and f'"{private_field}"' not in rendered
    assert str(REPO_ROOT) not in rendered and spec.automation_file not in rendered


def test_reuse_context_snapshot_roundtrip_and_legacy_compatibility():
    from qa_pipeline_contracts import _catalog_from_snapshot
    approved, snapshot = pipeline.load_approved_regression_catalog(REPO_ROOT / "approved_assets")
    restored = next(s for s in _catalog_from_snapshot(snapshot) if s.tc_id == approved[0].tc_id)
    assert restored == approved[0]
    legacy = json.loads(json.dumps(snapshot))
    for item in legacy["approved_assets"]:
        item.pop("reuse_context_json")
    historical = next(s for s in _catalog_from_snapshot(legacy) if s.tc_id == approved[0].tc_id)
    assert historical.reuse_context_json is None
    assert historical.covered_behaviors == restored.covered_behaviors
    assert "승인 TC 명세" not in pipeline.render_existing_regression_context((historical,))


def test_agent2_sends_approved_procedures_on_initial_and_rewrite_calls():
    approved, _ = pipeline.load_approved_regression_catalog(REPO_ROOT / "approved_assets")
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(model="gpt-5.6-terra", client=SimpleNamespace(responses=responses))
    for extra in ({}, {"previous_design": agent2_design(), "checkpoint_feedback": ["검사 항목 확인"]}):
        agent.design(cp1_request(), cp2_analysis(), cp2_requirements(), existing_catalog=approved, **extra)
        text = responses.kwargs["input"][1]["content"]
        instructions = responses.kwargs["input"][0]["content"]
        assert approved[0].reuse_context_json in text
        assert "승인 TC 명세가 제공되면" in instructions
        assert instructions == AGENT2_SYSTEM_INSTRUCTIONS
        assert "내부 분류명·정책 키" in instructions
        assert "코드 처리 과정을 풀어 쓰지 않고" in instructions
        assert "추가 확인 사항이 없으면 빈 목록" in instructions
        assert "근거 개수와 검증 사실 개수는 다릅니다" in instructions
        assert "유지 조건이라는 이유로 이번 요청에 필요한 검사를 생략" in instructions
        assert "후보와 기존 TC를 합친 실제 검사 범위" in instructions
        assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent2-2-62-rules-6"
        assert "기존 TC는 전체 단위로 실행" in instructions
        assert "명시적 제외와 충돌하는 검사가 포함돼 있으면 선택하지 않고" in instructions
        assert "기존 assertion을 삭제하지 않습니다" in instructions
        assert "요청된 변경분 후보가 실제로 확인하는 유지 기준도 함께 연결" in instructions
        assert "유지` 조건은 관련_기존_TC로만" not in instructions
        assert "입력 절차 원문은 Agent 1의 해시 검증된 기록에 보존" in instructions
        assert "원문에 명시된 준비값은 사전조건 준비·확인에만 사용하며 복원 목표와 혼동하지 않습니다" in instructions
        assert "내부 초기값은 해당 내부 관찰 대상과 원문에 명시한 초기값으로 확인" not in instructions
        assert "조작 수단이 없는 입력에서 버튼·횟수를 추정하지 않습니다" in instructions
        assert "UI 기대결과에 내부 enum을 곧바로 화면 표시 문자열처럼 쓰지 않습니다" in instructions
        assert "설정 온도 30°C 입력 → 적용" not in instructions
        assert "작성 수준 예시 (아래는 기존 필드의 일부만 발췌한 형식 참고이며 이번 입력의 제품 기준이 아닙니다)" in instructions
        assert "1. 중앙 관제 화면에서 시험할 대상 장비 카드를 선택한다." in instructions
        assert "2. 선택한 장비의 제어 패널에서 풍량을 MED로 선택한다." in instructions
        assert "3. 제어 패널의 적용 버튼을 눌러 선택한 풍량을 대상 장비에 적용한다." in instructions
        # The example restores to the observed baseline, never to a fixed initial value.
        assert "대상 장비의 내부 fanSpeed를 준비 전 관찰값과 비교한다." in instructions
        assert "초기값 LOW로 돌아왔는지" not in instructions
        assert "대상 선택 성공·알림·선택 색상·LOW의 한글 표시를 새 expected_results로 만들지 않습니다." in instructions
        assert "예시 B: 입력이 '초기 설정 온도 24°C, 30°C 적용 후 카드·내부 설정 온도 30°C'를 요구하면" in instructions
        assert "예시 C: 입력이 현재 상태를 조회하는 읽기 전용 시험이면" in instructions
        assert "값·화면명·필드명·조건 ID·초기 상태는 반드시 현재 입력에서 가져오며" in instructions
        assert responses.kwargs["store"] is False


def test_cp2_rejects_srs_revision_value_without_source():
    analysis = cp2_analysis()
    design = cp2_valid_design()
    design.srs_revision_proposals = [pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001", requirement_id="REQ-TEMP-001", source_condition_ids=["COND-001"],
        current_acceptance_criteria="범위 밖 차단", proposed_acceptance_criteria="AUTO 모드 99°C 허용", reason="변경 반영")]
    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())
    assert cp2_check(result, "CP2-018").status == CheckStatus.FAIL


def test_existing_test_selection_accepts_versioned_official_tc_id():
    selection = ExistingTestSelection(
        tc_id="TC-V2-001",
        source_condition_ids=["COND-001"],
        selection_reason="승인된 V2 공식 TC를 영향 회귀 대상으로 재사용한다.",
    )

    assert selection.tc_id == "TC-V2-001"

@pytest.mark.parametrize("rewrite", [False, True])
def test_agent2_writer_and_rewriter_receive_same_baseline_order_guidance(rewrite):
    from qa_pipeline_contracts import QA_CONTROLLER_BASELINE_GUIDANCE
    responses = Agent2FakeResponses()
    source = agent2_design()
    before = source.model_dump(mode="json")
    options = {"previous_design": source, "checkpoint_feedback": ["기록 시점과 조작 순서를 대조하세요."]} if rewrite else {}
    OpenAIAgent2(model="offline", client=SimpleNamespace(responses=responses)).design(
        cp1_request(), cp2_analysis(), cp2_requirements(), **options)
    prompt = responses.kwargs["input"][1]["content"]
    assert "[대상 선택·원래값 기록 순서]" in prompt
    assert prompt.count(QA_CONTROLLER_BASELINE_GUIDANCE) == 1
    assert responses.kwargs["input"][0]["content"] == AGENT2_SYSTEM_INSTRUCTIONS
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent2-2-62-rules-6"
    assert source.model_dump(mode="json") == before
    if rewrite:
        assert "기록 시점과 조작 순서를 대조하세요." in prompt


def test_agent2_uses_structured_responses_api() -> None:
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
    )
    analysis = Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        change_summary="AUTO 모드 하한 변경",
        before_condition="16~30°C",
        after_condition="18~30°C",
        confirmed_conditions=[
            ConfirmedCondition(
                condition_id="COND-001",
                statement="18°C 미만 요청은 차단한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="18°C 미만 요청은 차단한다.",
                requirement_ids=["REQ-TEMP-001"],
            )
        ],
        requirement_effects=[
            RequirementEffect(
                requirement_id="REQ-TEMP-001",
                relation=RequirementRelation.MODIFIED,
                reason="하한 변경",
            )
        ],
        decision=AnalysisDecision.PROCEED,
    )

    response = agent.design(cp1_request(), analysis, {})

    assert response.response_id == "resp_agent2"
    assert response.usage["total_tokens"] == 300
    assert responses.kwargs["text_format"] is pipeline.Agent2TransportDesign
    assert responses.kwargs["store"] is False
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent2-2-62-rules-6"
    agent2_input = responses.kwargs["input"][1]["content"]
    assert "[기존 사람 작성·자동화 TC 카탈로그]" in agent2_input
    assert '[코드로 확인한 SRS 개정 범위]' in agent2_input
    assert '"required_requirement_ids": ["REQ-TEMP-001"]' in agent2_input
    assert "TC-TEMP-001" in agent2_input
    assert "TC-MODE-002" in agent2_input
    assert "검증 동작" in agent2_input
    assert "30°C 초과 요청 차단" in agent2_input
    assert "제품 기능 테스트케이스 후보" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Playwright 코드" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 confirmed_condition" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Requirement ID만 같거나 일부 검사가 맞는다는 이유로 재사용하지 않습니다" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "내부 필드 식별자" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "target_role=PRIMARY_TEST_DEVICE" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "선택적인 설명용 QA 분류" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "independence_reason은 선택 설명으로 null을 허용" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "independent_execution=true" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 실행 TC는 control_path=CENTRAL" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "TC 분리 단위는 입력값 하나가 아니라 하나의 업무 규칙" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "INDEPENDENT_VARIANTS" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "verify_after_step" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "대상 선택 → 값 선택/입력 → 적용" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "observation_target" in responses.kwargs["input"][0]["content"]
    assert "제외된_정보_부족" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "전체 test_cases와 관련_기존_TC를 완전한 결과로 반환" in Path(
        "src/qa_pipeline_agent2.py"
    ).read_text(encoding="utf-8")

    agent.design(
        cp1_request(),
        analysis,
        {},
        previous_design=agent2_design(),
        checkpoint_feedback=[
            "CP2-001 PASS: 요청 ID 일치",
            "CP2-002 FAIL: 중복 ID",
        ],
    )
    rework_input = responses.kwargs["input"][1]["content"]
    assert "observation_target" in responses.kwargs["input"][0]["content"]
    assert "Checkpoint 2 전체 판정" in rework_input
    assert "CP2-001 PASS" in rework_input
    assert "PASS인 규칙과 그 근거를 보존" in rework_input
    assert "최종_확인_사항" in rework_input
    assert "중단_확인_사항" in rework_input

def test_agent2_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent2Error, match="OPENAI_API_KEY"):
        OpenAIAgent2()

def test_valid_design_passes_checkpoint2() -> None:
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), cp2_valid_design(), cp2_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 22  # CP2-LANG appears only on a violation
    assert all(item.status == CheckStatus.PASS for item in result.checks)

@pytest.mark.parametrize("values", [("MED", "HIGH"), ("18°C", "30°C")])
@pytest.mark.parametrize("layout", ["split", "one_complete", "missing_link", "actual_gap"])
def test_compound_existing_reuse_requires_actual_condition_links(values, layout):
    request, analysis, design, catalog = compound_reuse_fixture(values, layout)
    before = design.model_dump()
    result = evaluate_checkpoint2(request, analysis, design, cp2_requirements(),
        existing_catalog=catalog)
    assert cp2_check(result, "CP2-019").status == CheckStatus.PASS  # values: mandatory review
    context = pipeline._existing_reuse_link_context(analysis, catalog, design)
    pair = next(row for row in context if row["condition_id"] == "COND-010")
    assert bool(pair["values_not_covered_by_links"]) == (layout in {"missing_link", "actual_gap"})
    if layout == "missing_link":
        assert pair["linked_existing_tc_ids"] == ["TC-SPLIT-001"]
        assert "TC-SPLIT-002" in [s.tc_id for s in design.related_existing_tests]
    assert design.model_dump() == before


def test_agent2_sends_compound_link_guidance_on_initial_and_repair():
    request, analysis, design, catalog = compound_reuse_fixture(layout="missing_link")
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(model="gpt-5.6-terra", client=SimpleNamespace(responses=responses))
    before = design.model_dump()
    for kwargs in ({}, {"previous_design": design, "checkpoint_feedback": ["CP2-019 FAIL"]}):
        agent.design(request, analysis, cp2_requirements(), existing_catalog=catalog, **kwargs)
        prompt = responses.kwargs["input"][1]["content"]
        assert "[조건별 기존 TC 연결 점검]" in prompt
        assert '"detected_values"' not in prompt
        assert '"condition":' in prompt
        assert "TC-X와 TC-Y 모두 C에 연결" in prompt
        assert "권장 TC 목록이나 합격 판정이 아닙니다" in prompt
        if kwargs:
            assert '"linked_existing_tc_ids": ["TC-SPLIT-001"]' in prompt
            assert '"values_not_covered_by_links"' not in prompt
            assert "CP2-019 FAIL" in prompt
    assert design.model_dump() == before


def test_reuse_link_diagnostics_do_not_infer_coverage_from_unknown_tests_or_candidates():
    request, analysis, design, catalog = compound_reuse_fixture()
    unrelated = ExistingTestSelection(tc_id="TC-UNKNOWN-999", source_condition_ids=["COND-010"],
        selection_reason="허용 목록 밖 테스트")
    candidate = cp2_valid_design().test_cases[0].model_copy(update={"source_condition_ids": ["COND-010"]})
    design = design.model_copy(update={"related_existing_tests": [unrelated], "test_cases": [candidate]})
    row = pipeline._existing_reuse_link_context(analysis, catalog, design)[0]
    assert row["values_not_covered_by_links"] == ["HIGH", "MED"]
    assert row["candidate_tc_ids"] == [candidate.tc_id]
    assert row["linked_existing_tc_ids"] == ["TC-UNKNOWN-999"]
    assert "linked_existing_tc_ids" not in pipeline._existing_reuse_link_context(analysis, catalog)[0]


def test_checkpoint2_allows_existing_tc_only_when_behavior_covers_change() -> None:
    analysis = cp2_analysis()
    existing_spec = pipeline.ExistingRegressionSpec(
        tc_id="TC-V2-999",
        test_function="test_tc_v2_999",
        requirement_ids=("REQ-TEMP-001", "REQ-STATE-001", "REQ-NOTIFY-001"),
        covered_behaviors=("AUTO 18°C 미만 차단, 상태 유지, 차단 안내를 함께 검증",),
        source="APPROVED",
    )
    design = Agent2TestDesign(
        request_id=analysis.request_id,
        existing_tc_comparison_completed=True,
        related_existing_tests=[
            ExistingTestSelection(
                tc_id=existing_spec.tc_id,
                source_condition_ids=["COND-001", "COND-002", "COND-003"],
                selection_reason="변경 후 차단 동작과 유지 상태·안내를 이미 동일하게 검증한다.",
            )
        ],
        test_cases=[],
        srs_revision_proposals=cp2_valid_design().srs_revision_proposals,
        coverage_summary="변경 후 동작을 기존 공식 TC 한 건으로 전부 재검증한다.",
    )

    result = evaluate_checkpoint2(
        cp1_request(),
        analysis,
        design,
        cp2_requirements(),
        existing_catalog=(*pipeline.EXISTING_REGRESSION_CATALOG, existing_spec),
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-008").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

    guarded = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements(),
        existing_catalog=(*pipeline.EXISTING_REGRESSION_CATALOG, existing_spec),
    )
    assert guarded.status == CheckStatus.PASS
    assert cp2_check(guarded, "CP2-019").status == CheckStatus.PASS

    request_with_procedures = cp1_request().model_copy(update={"acceptance_notes": [
        "첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작한다.",
        "시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다.",
    ]})
    kwargs = dict(existing_catalog=(*pipeline.EXISTING_REGRESSION_CATALOG, existing_spec))
    analysis = analysis.model_copy(update={"procedure_notes": request_with_procedures.acceptance_notes})
    reviewed = evaluate_checkpoint2(
        request_with_procedures, analysis, design, cp2_requirements(), **kwargs,
    )
    assert reviewed.status == CheckStatus.PASS
    assert "최종 사람 검토" in cp2_check(reviewed, "CP2-014").message
    excluded = design.model_copy(update={"excluded_scope": request_with_procedures.acceptance_notes})
    assert cp2_check(evaluate_checkpoint2(
        request_with_procedures, analysis, excluded, cp2_requirements(), **kwargs,
    ), "CP2-014").status == CheckStatus.FAIL


def test_existing_only_reuse_with_different_values_is_left_to_the_review() -> None:
    analysis = cp2_analysis()
    spec = pipeline.ExistingRegressionSpec(
        tc_id="TC-V2-999", test_function="test_tc_v2_999",
        requirement_ids=("REQ-TEMP-001", "REQ-STATE-001", "REQ-NOTIFY-001"),
        covered_behaviors=("AUTO 16°C 미만 차단, 상태 유지, 차단 안내 검증",),
        source="APPROVED",
    )
    design = Agent2TestDesign(
        request_id=analysis.request_id, existing_tc_comparison_completed=True,
        related_existing_tests=[ExistingTestSelection(
            tc_id=spec.tc_id,
            source_condition_ids=["COND-001", "COND-002", "COND-003"],
            selection_reason="같은 Requirement를 검증한다.",
        )], test_cases=[], coverage_summary="기존 TC 재사용",
    )
    kwargs = dict(existing_catalog=(*pipeline.EXISTING_REGRESSION_CATALOG, spec))
    # 16°C vs 18°C is a value-role question for the mandatory grounding review.
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(), **kwargs),
                     "CP2-019").status == CheckStatus.PASS
    assert pipeline._explicit_behavior_values("REQ-FAN-001 MED 18.0°C") == {"MED", "18"}
    assert pipeline._explicit_behavior_values("HIGH 18°C") == {"HIGH", "18"}
    candidate = evaluate_checkpoint2(
        cp1_request(), analysis, cp2_valid_design(), cp2_requirements(),
    )
    assert candidate.status == CheckStatus.PASS

def test_checkpoint2_requires_grounded_srs_revision_proposal_for_modified_requirement() -> None:
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="범위 밖 차단",
        proposed_acceptance_criteria="AUTO 모드는 18~30°C를 허용하고 범위 밖 요청을 차단",
        reason="AUTO 모드 하한 변경을 기준 문서에 반영한다.",
    )
    design = cp2_valid_design().model_copy(
        update={"srs_revision_proposals": [proposal]}
    )

    passed = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design,
        cp2_requirements(),
    )
    missing = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        cp2_valid_design().model_copy(update={"srs_revision_proposals": []}),
        cp2_requirements(),
    )

    assert cp2_check(passed, "CP2-018").status == CheckStatus.PASS
    assert cp2_check(missing, "CP2-018").status == CheckStatus.FAIL
    assert "개정 제안 누락=REQ-TEMP-001" in cp2_check(missing, "CP2-018").message

@pytest.mark.parametrize("current, reflected", [
    ("AUTO 모드는 18~30°C", True),
    ("  AUTO 모드는 18~30°C\n", True),
    ("AUTO 모드는 16~30°C", False),
    ("AUTO 모드는 18~30°C이며 추가 조건이 있다", False),
    ("auto 모드는 18~30°C", False),
    ("AUTO  모드는 18~30°C", False),
])
def test_srs_revision_exemption_requires_full_exact_current_criteria(current, reflected):
    requirements = cp2_requirements()
    requirements["REQ-TEMP-001"] = requirements["REQ-TEMP-001"].model_copy(
        update={"acceptance_criteria": current}
    )
    design = cp2_valid_design().model_copy(update={"srs_revision_proposals": []})
    original = design.model_dump()
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, requirements,
    )
    assert cp2_check(result, "CP2-018").status == (CheckStatus.PASS if reflected else CheckStatus.FAIL)
    assert design.model_dump() == original


@pytest.mark.parametrize("variant", ["identical", "rephrased", "related_missing", "target_missing"])
def test_srs_revision_policy_keeps_invalid_proposals_and_related_changes_blocked(variant):
    request, analysis, requirements = cp1_request(), cp2_analysis(), cp2_requirements()
    requirements[request.target_requirement_id] = requirements[request.target_requirement_id].model_copy(
        update={"acceptance_criteria": request.after_value}
    )
    design = cp2_valid_design().model_copy(update={"srs_revision_proposals": []})
    if variant in {"identical", "rephrased"}:
        design = design.model_copy(update={"srs_revision_proposals": [pipeline.SrsRevisionProposal(
            proposal_id="SRS-REV-001", requirement_id=request.target_requirement_id,
            source_condition_ids=["COND-001"], current_acceptance_criteria=request.after_value,
            proposed_acceptance_criteria=(request.after_value if variant == "identical" else request.after_value + "입니다."),
            reason="개정안을 만들기 위한 불필요한 제안",
        )]})
    elif variant == "related_missing":
        analysis = analysis.model_copy(update={"requirement_effects": [
            effect.model_copy(update={"relation": RequirementRelation.UPDATE_REQUIRED})
            if effect.requirement_id == "REQ-STATE-001" else effect
            for effect in analysis.requirement_effects
        ]})
    else:
        del requirements[request.target_requirement_id]
    result = evaluate_checkpoint2(
        request, analysis, design, requirements,
    )
    check = cp2_check(result, "CP2-018")
    assert check.status == CheckStatus.FAIL
    if variant in {"identical", "rephrased"}:
        assert "해당 개정안을 제외하고 TC 선택·검증 범위는 유지" in check.message
    elif variant == "related_missing":
        assert "개정 제안 누락=REQ-STATE-001" in check.message
    else:
        assert "개정 제안 누락=REQ-TEMP-001" in check.message


def test_agent2_sends_reflected_srs_policy_on_initial_and_repair_without_mutation():
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(model="gpt-5.6-terra", client=SimpleNamespace(responses=responses))
    request, requirements = cp1_request(), cp2_requirements()
    requirements[request.target_requirement_id] = requirements[request.target_requirement_id].model_copy(
        update={"acceptance_criteria": request.after_value}
    )
    before = {key: value.model_dump() for key, value in requirements.items()}
    for kwargs in ({}, {"previous_design": cp2_valid_design(), "checkpoint_feedback": ["CP2-018 FAIL"]}):
        agent.design(request, cp2_analysis(), requirements, **kwargs)
        prompt = responses.kwargs["input"][1]["content"]
        assert '"already_reflected_requirement_ids": ["REQ-TEMP-001"]' in prompt
        assert '"required_requirement_ids": []' in prompt
        assert request.after_value in prompt
    assert {key: value.model_dump() for key, value in requirements.items()} == before


def test_srs_revision_preview_apply_and_conflict_detection(tmp_path: Path) -> None:
    srs_file = tmp_path / "SRS.md"
    srs_file.write_text(
        "# SRS\n\n| ID | 요구사항 | 인수 기준 |\n"
        "|---|---|---|\n"
        "| REQ-TEMP-001 | 온도 범위 | 기존 기준 |\n",
        encoding="utf-8",
    )
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="기존 기준",
        proposed_acceptance_criteria="변경 기준",
        reason="승인된 변경을 반영한다.",
    )

    preview = pipeline.apply_srs_revision_proposals(
        srs_file, [proposal], write=False
    )
    assert preview["changed_requirement_ids"] == ["REQ-TEMP-001"]
    assert "기존 기준" in srs_file.read_text(encoding="utf-8")

    applied = pipeline.apply_srs_revision_proposals(srs_file, [proposal], write=True)
    repeated = pipeline.apply_srs_revision_proposals(srs_file, [proposal], write=True)
    assert applied["changed_requirement_ids"] == ["REQ-TEMP-001"]
    assert repeated["already_applied_requirement_ids"] == ["REQ-TEMP-001"]
    assert "변경 기준" in srs_file.read_text(encoding="utf-8")

    conflicting = proposal.model_copy(
        update={
            "current_acceptance_criteria": "다른 기준",
            "proposed_acceptance_criteria": "또 다른 기준",
        }
    )
    with pytest.raises(ValueError, match="기준 원문과 다릅니다"):
        pipeline.apply_srs_revision_proposals(srs_file, [conflicting], write=True)

def test_checkpoint2_routes_unchanged_condition_to_existing_tc() -> None:
    maintained = ConfirmedCondition(
        condition_id="COND-004",
        statement="기존 30°C 상한 차단 정책을 유지한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text="기존 30°C 상한 차단 정책을 유지한다.",
        requirement_ids=["REQ-TEMP-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *cp2_analysis().confirmed_conditions,
                maintained,
            ]
        }
    )
    design = cp2_valid_design().model_copy(
        update={
            "related_existing_tests": [
                ExistingTestSelection(
                    tc_id="TC-TEMP-001",
                    source_condition_ids=["COND-001", "COND-004"],
                    selection_reason="유지되는 상한 정책은 기존 TC로 회귀 확인한다.",
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_checkpoint2_allows_incompatible_target_regression_to_be_omitted() -> None:
    design = cp2_valid_design().model_copy(update={"related_existing_tests": []})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_checkpoint2_keeps_grounded_product_capability_result() -> None:
    analysis = cp2_analysis()
    grounded_condition = analysis.confirmed_conditions[0].model_copy(
        update={
            "statement": "AUTO 모드를 선택하고 적용할 수 있다.",
            "source_text": "AUTO 모드를 선택하고 적용할 수 있다.",
        }
    )
    analysis = analysis.model_copy(
        update={
            "confirmed_conditions": [
                grounded_condition,
                *analysis.confirmed_conditions[1:],
            ]
        }
    )
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    grounded_result = ExpectedResult(
        result_id="ER-004",
        statement="AUTO 모드를 선택하고 적용할 수 있다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            grounded_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-017").status == CheckStatus.PASS

def test_checkpoint2_accepts_related_boundaries_as_one_grouped_tc() -> None:
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), grouped_boundary_design(), cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-015").status == CheckStatus.PASS

def test_checkpoint2_pairs_double_assertions_at_the_same_step() -> None:
    design = grouped_boundary_design()
    tc = design.test_cases[0]
    broken = tc.model_copy(update={"expected_results": [
        result.model_copy(update={"verify_after_step": tc.steps[-1]})
        if result.observation_layer == ObservationLayer.INTERNAL_STATE else result
        for result in tc.expected_results
    ]})
    design = design.model_copy(update={"test_cases": [broken]})
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL
    assert "판정 단계 불일치" in cp2_check(result, "CP2-006").message

def test_checkpoint2_accepts_single_operation_with_separate_observations() -> None:
    design = cp2_valid_design()
    tc = design.test_cases[0]
    tc = tc.model_copy(update={"expected_results": [
        result.model_copy(update={"verify_after_step": tc.steps[-1]})
        for result in tc.expected_results
    ]})
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design.model_copy(update={"test_cases": [tc]}),
        cp2_requirements(),
    )
    assert cp2_check(result, "CP2-006").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-015").status == CheckStatus.PASS

def test_checkpoint2_rejects_grouped_tc_without_reset_or_result_timing() -> None:
    design = grouped_boundary_design()
    test_case = design.test_cases[0]
    broken_results = [
        result.model_copy(update={"verify_after_step": None})
        for result in test_case.expected_results
    ]
    broken = test_case.model_copy(
        update={
            "intermediate_reset_steps": [],
            "expected_results": broken_results,
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(),
        design.model_copy(update={"test_cases": [broken]}),
        cp2_requirements(),
    )

    assert result.status == CheckStatus.FAIL
    check = cp2_check(result, "CP2-015")
    assert check.status == CheckStatus.FAIL
    assert "초기화 절차 누락" in check.message
    assert "판정 단계 누락" in check.message

def test_checkpoint2_requires_explicit_runtime_restore_for_unknown_grouped_hvac_baseline() -> None:
    design = grouped_boundary_design()
    test_case = design.test_cases[0]
    restore_step = "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다."
    unknown_baseline = test_case.model_copy(
        update={
            "test_data": test_case.test_data.model_copy(
                update={
                    "initial_mode": None,
                    "initial_temperature_c": None,
                    "restore_observed_hvac_state": False,
                }
            ),
            "restore_required": True,
            "restore_steps": [restore_step],
        }
    )

    rejected = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [unknown_baseline]}),
        cp2_requirements(),
    )
    accepted_case = unknown_baseline.model_copy(
        update={
            "test_data": unknown_baseline.test_data.model_copy(
                update={"restore_observed_hvac_state": True}
            )
        }
    )
    accepted = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [accepted_case]}),
        cp2_requirements(),
    )

    assert cp2_check(rejected, "CP2-015").status == CheckStatus.FAIL
    assert "실행 전 상태 저장·복원 표시 누락" in cp2_check(
        rejected, "CP2-015"
    ).message
    assert cp2_check(accepted, "CP2-015").status == CheckStatus.PASS


@pytest.mark.parametrize("new_policy", [False, True])
def test_checkpoint2_distinguishes_hvac_preparation_from_original_restore(new_policy):
    design = cp2_valid_design()
    case = design.test_cases[0]
    case.test_data.initial_mode = "AUTO"
    case.test_data.initial_temperature_c = 18
    case.test_data.requested_temperature_c = 17
    case.test_data.restore_observed_hvac_state = True
    case.restore_required = True
    case.restore_steps = ["실행 직전 관찰한 모드와 설정 온도로 복원하고 적용한다."]
    case.state_effect = pipeline.TcStateEffect.BLOCKED_CHANGE if new_policy else None
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    check = cp2_check(result, "CP2-015")
    assert check.status == (CheckStatus.PASS if new_policy else CheckStatus.FAIL), check.message

def test_human_review_note_pauses_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"human_review_notes": ["기획 확인이 필요한 의미 범위"]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.REVIEW
    assert cp2_check(result, "CP2-011").status == CheckStatus.REVIEW

def test_coverage_note_does_not_pause_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"coverage_notes": ["정확한 Toast 문구는 정의되지 않아 표시 여부만 검증한다."]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-011").status == CheckStatus.PASS

def test_final_review_note_does_not_pause_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"final_review_notes": ["운영 적용 시점은 최종 보고에서 확인한다."]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-011").status == CheckStatus.PASS
    assert "후속 자동 실행을 막지 않는 참고·최종 검토 사항 1건" in cp2_check(result, "CP2-011").message
    schema_properties = pipeline.Agent2TestDesign.model_json_schema()["properties"]
    assert "최종_확인_사항" in schema_properties
    assert "중단_확인_사항" in schema_properties
    assert "제외_범위" in schema_properties
    assert "제외된_정보_부족" in schema_properties
    tc_schema = pipeline.ProductTestCaseCandidate.model_json_schema()["properties"]
    assert "common_qa_criteria" in tc_schema
    assert "independent_execution" in tc_schema
    assert "double_assert_policy" in tc_schema

def test_control_requirement_cannot_use_local_path() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 제어 명령을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 제어 명령을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="중앙 제어 경로 회귀 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 제어 명령을 적용한다.",
            acceptance_criteria="선택 장비에 일괄 적용한다.",
        ),
    }
    tc = cp2_valid_design().test_cases[0]
    expected_results = [
        item.model_copy(
            update={
                "source_condition_ids": [*item.source_condition_ids, "COND-004"]
            }
        )
        for item in tc.expected_results
    ]
    mismatched = tc.model_copy(
        update={
            "requirement_ids": [*tc.requirement_ids, "REQ-CONTROL-001"],
            "source_condition_ids": [*tc.source_condition_ids, "COND-004"],
            "expected_results": expected_results,
            "control_path": ControlPath.LOCAL,
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [mismatched]})

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-008").status == CheckStatus.FAIL

def test_verify_central_path_can_use_existing_regression_without_new_candidate() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 변경 정책을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 변경 정책을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="중앙 경로에서도 변경 정책 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 변경 정책을 적용한다.",
            acceptance_criteria="선택 장비에 일괄 적용한다.",
        ),
    }
    design = cp2_valid_design().model_copy(
        update={
            "related_existing_tests": [
                *cp2_valid_design().related_existing_tests,
                ExistingTestSelection(
                    tc_id="TC-MODE-001",
                    source_condition_ids=["COND-004"],
                    selection_reason="유지되는 중앙 관제 적용 동작은 기존 TC로 회귀 확인한다.",
                ),
            ]
        }
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-008").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_structured_test_data_is_required_for_boundary_tc() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"test_data": StructuredTestData()}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-010").status == CheckStatus.FAIL

def test_state_consistency_without_mode_or_temperature_data_is_allowed() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "test_type": TcType.STATE_CONSISTENCY,
            "test_data": StructuredTestData(),
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-010").status == CheckStatus.PASS

def test_boundary_tc_allows_initial_mode_as_execution_context() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "test_data": StructuredTestData(
                initial_mode="AUTO",
                requested_mode=None,
                initial_temperature_c=18,
                requested_temperature_c=17,
            )
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-010").status == CheckStatus.PASS

def test_missing_condition_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"source_condition_ids": ["COND-001", "COND-002"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-004").status == CheckStatus.FAIL

def test_missing_internal_state_assertion_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0]
    expected = [
        item
        for item in tc.expected_results
        if item.observation_layer != ObservationLayer.INTERNAL_STATE
    ]
    design = cp2_valid_design().model_copy(
        update={"test_cases": [tc.model_copy(update={"expected_results": expected})]}
    )

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL

def test_state_consistency_type_without_internal_state_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "requirement_ids": ["REQ-TEMP-001"],
            "source_condition_ids": ["COND-001"],
            "test_type": TcType.STATE_CONSISTENCY,
            "expected_results": [
                ExpectedResult(
                    result_id="ER-001",
                    statement="화면에서 요청이 차단된다.",
                    observation_layer=ObservationLayer.UI,
                    source_condition_ids=["COND-001"],
                )
            ],
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL

def test_tc_declared_non_independent_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"independent_execution": False, "independence_reason": None}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-013").status == CheckStatus.FAIL

def test_tc_negative_cross_tc_reference_is_accepted_as_independence_evidence() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "independence_reason": (
                "사전조건을 직접 구성하므로 이전 TC의 적용 또는 복원 결과에 "
                "의존하지 않고 독립적으로 실행한다."
            )
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-013").status == CheckStatus.PASS

def test_partial_scope_exclusions_must_be_preserved_by_agent2() -> None:
    analysis = cp2_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": ["정확한 차단 안내 문구"],
            "information_gaps": ["정확한 안내 문구가 정의되지 않음"],
            "excluded_information_gaps": ["정확한 안내 문구가 정의되지 않음"],
            "user_questions": ["차단 안내 문구를 확정해 주세요."],
        }
    )
    design = cp2_valid_design()

    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-014").status == CheckStatus.FAIL

    preserved = design.model_copy(
        update={
            "excluded_scope": analysis.excluded_scope,
            "excluded_information_gaps": analysis.information_gaps,
        }
    )
    preserved_result = evaluate_checkpoint2(
        cp1_request(), analysis, preserved, cp2_requirements()
    )
    assert preserved_result.status == CheckStatus.PASS
    assert cp2_check(preserved_result, "CP2-014").status == CheckStatus.PASS

def test_agent2_preserves_setup_and_restore_notes_as_tc_procedures() -> None:
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
    analysis = cp2_analysis().model_copy(
        update={"procedure_notes": [setup_note, restore_note]}
    )
    incorrectly_excluded = cp2_valid_design().model_copy(
        update={"excluded_scope": [setup_note, restore_note]}
    )

    rejected = evaluate_checkpoint2(
        request, analysis, incorrectly_excluded, cp2_requirements()
    )

    assert cp2_check(rejected, "CP2-014").status == CheckStatus.FAIL

    base_tc = cp2_valid_design().test_cases[0]
    procedural_tc = base_tc.model_copy(
        update={
            "preconditions": [*base_tc.preconditions, setup_note],
            "restore_required": True,
            "restore_steps": [restore_note],
        }
    )
    preserved = cp2_valid_design().model_copy(
        update={"test_cases": [procedural_tc], "excluded_scope": []}
    )
    accepted = evaluate_checkpoint2(request, analysis, preserved, cp2_requirements())

    assert cp2_check(accepted, "CP2-014").status == CheckStatus.PASS

def test_playwright_code_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"steps": ["page.locator('#temperature').click()"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-009").status == CheckStatus.FAIL


# --- range_checklist_contract 1.0 (2026-10-17) -------------------------------------------
def _range_conditions(*rows):
    return SimpleNamespace(confirmed_conditions=[
        SimpleNamespace(change_role=role, source_type=source, statement=text) for role, source, text in rows])


RANGE_ANALYSIS = _range_conditions(
    ("변경", "CHANGE_REQUEST", "냉방(COOL)의 설정 온도 허용 범위는 하한 20°C와 상한 30°C를 포함하는 20~30°C로 변경된다."),
    ("유지", "CHANGE_REQUEST", "난방(HEAT)의 설정 온도 허용 범위는 기존 16~30°C를 유지한다."),
    ("변경", "CHANGE_REQUEST", "냉방에서 20°C를 적용한 상태로 감소 조작을 한 뒤 적용하면 내부 setTemp는 20°C이다."),
)


def _probe_tc(tc_id, start, op, attempted_expected):
    ops = [dict(action_id="M", phase="SETUP", target="mode.cool"),
           dict(action_id="S", phase="SETUP", target="temperature.set", value=start),
           dict(action_id="T", phase="TEST", target=op)]
    checks = [dict(after_action_id="T", target=f"{loc}.setTemp", expected_value=attempted_expected)
              for loc in ("panel", "card", "internal")]
    return dict(tc_id=tc_id, execution_spec=dict(operations=ops, verifications=checks))


def _full_range_design(question=True, where="최종_확인_사항"):
    design = {"test_cases": [
        _probe_tc("T1", 21, "temperature.decrease", 20), _probe_tc("T2", 29, "temperature.increase", 30),
        _probe_tc("T3", 20, "temperature.decrease", 20), _probe_tc("T4", 30, "temperature.increase", 30)],
        "최종_확인_사항": [], "중단_확인_사항": []}
    if question:
        design[where] = ["난방 16~30°C 중 냉방 범위 밖 온도에서 냉방으로 바꿀 때 동작이 요청에 없습니다. 어떻게 처리하나요?"]
    return design


def test_range_checklist_reads_only_unambiguous_agent1_range_statements():
    import qa_pipeline_range_checklist as rc
    table = rc.range_table(RANGE_ANALYSIS)
    assert table == {"changed": [dict(mode="COOL", lower=20, upper=30)], "kept": [dict(mode="HEAT", lower=16, upper=30)]}
    ids = [row["id"] for row in rc.checklist(table)]
    assert ids == ["T-1:APPLY:COOL:20", "T-1:APPLY:COOL:30", "T-2:BLOCK:COOL:19", "T-2:BLOCK:COOL:31", "T-5:QUESTION:COOL"]
    # Not a range change, two modes in one sentence, or an SRS-sourced sentence: no checklist, no stop.
    assert rc.range_table(_range_conditions(("변경", "CHANGE_REQUEST", "HIGH 풍량은 강풍으로 표시된다."))) is None
    assert rc.range_table(_range_conditions(("변경", "CHANGE_REQUEST", "냉방과 난방의 허용 범위는 20~30°C로 변경된다."))) is None
    assert rc.range_table(_range_conditions(("변경", "SRS", "냉방 허용 범위는 20~30°C로 변경된다."))) is None
    assert rc.range_checklist_check(_range_conditions(("변경", "CHANGE_REQUEST", "HIGH 풍량은 강풍으로 표시된다.")), {}) is None
    # No kept mode outside the new range: no switch question.
    narrow = _range_conditions(("변경", "CHANGE_REQUEST", "냉방 허용 범위는 18~30°C로 변경된다."),
                               ("유지", "CHANGE_REQUEST", "난방 허용 범위는 20~28°C를 유지한다."))
    assert "T-5:QUESTION:COOL" not in [r["id"] for r in rc.checklist(rc.range_table(narrow))]


@pytest.mark.parametrize("variant,status,missing", [
    ("complete", CheckStatus.PASS, []),
    ("no_question", CheckStatus.FAIL, ["T-5:QUESTION:COOL"]),
    ("blocking_question", CheckStatus.FAIL, ["T-5:QUESTION:COOL"]),  # must not stop the run
    ("no_upper_block", CheckStatus.FAIL, ["T-2:BLOCK:COOL:31"]),
    ("wrong_value", CheckStatus.FAIL, ["T-2:BLOCK:COOL:19"]),
])
def test_range_checklist_marks_missing_items_as_critical(variant, status, missing):
    import qa_pipeline_range_checklist as rc
    design = _full_range_design(question=variant != "no_question",
                                where="중단_확인_사항" if variant == "blocking_question" else "최종_확인_사항")
    if variant == "no_upper_block":
        design["test_cases"].pop()
    if variant == "wrong_value":
        design["test_cases"][2]["execution_spec"]["verifications"][2]["expected_value"] = 19
    check = rc.range_checklist_check(RANGE_ANALYSIS, design)
    assert check.rule_id == "CP2-RANGE-CHECKLIST" and check.status == status
    assert [m for m in missing if m not in check.message] == []
    if status == CheckStatus.FAIL:
        assert check.message.startswith("[치명]")


def test_range_checklist_reaches_the_writer():
    # The writer receives the computed list only when it is given.
    sent = []
    def parse(**kwargs):
        sent.append(kwargs)
        raise RuntimeError("stop after capture")
    agent = OpenAIAgent2(model="test", client=SimpleNamespace(responses=SimpleNamespace(parse=parse)))
    for checklist in (None, "- [T-5:QUESTION:COOL] 질문"):
        with pytest.raises(Exception):
            agent.design(cp1_request(), cp2_analysis(), cp2_requirements(), required_checklist=checklist)
    assert "[코드가 계산한 필수 확인 목록" not in sent[0]["input"][1]["content"]
    assert "[T-5:QUESTION:COOL]" in sent[1]["input"][1]["content"]


# --- range_checklist_contract 1.1 (2026-10-17 사람 대조 H-2) ------------------------------
def _with_exclusions(*items):
    return SimpleNamespace(confirmed_conditions=RANGE_ANALYSIS.confirmed_conditions, excluded_scope=list(items))


def test_request_excluded_switch_policy_needs_no_question():
    """Real temperature request: out_of_scope names the COOL entry policy from outside its range."""
    import qa_pipeline_range_checklist as rc
    analysis = _with_exclusions("새 냉방 범위 밖 온도를 가진 장비의 냉방 모드 진입 시 자동 보정 정책")
    assert rc.excluded_switch_modes(analysis) == {"COOL"}
    ids = [r["id"] for r in rc.checklist(rc.range_table(analysis), rc.excluded_switch_modes(analysis))]
    assert "T-5:QUESTION:COOL" not in ids and len(ids) == 4
    check = rc.range_checklist_check(analysis, _full_range_design(question=False))
    assert check.status == CheckStatus.PASS and "4개" in check.message
    # Asking anyway is still fine.
    assert rc.range_checklist_check(analysis, _full_range_design()).status == CheckStatus.PASS


@pytest.mark.parametrize("item", [
    "다중 장비 제어 및 실제 장비 통신",              # unrelated exclusion
    "냉방 알림 문구 정책",                          # mode named, no switch/entry
    "냉방·난방 전환 시 온도 보정",                  # two modes: ambiguous, keep the question
])
def test_unrelated_or_ambiguous_exclusion_keeps_the_question(item):
    import qa_pipeline_range_checklist as rc
    analysis = _with_exclusions(item)
    check = rc.range_checklist_check(analysis, _full_range_design(question=False))
    assert check.status == CheckStatus.FAIL and "T-5:QUESTION:COOL" in check.message


# --- 기존 TC 고쳐 쓰기 (2026-10-17 사람 대조 H-3) ------------------------------------------
def test_empty_revision_list_keeps_historical_design_serialization():
    design = cp2_valid_design()
    for by_alias in (True, False):
        dumped = design.model_dump(mode="json", by_alias=by_alias)
        assert "기존_TC_수정" not in dumped and "existing_tc_revisions" not in dumped
    assert Agent2TestDesign.model_validate(design.model_dump(mode="json", by_alias=True)) == design
    assert all(check.rule_id != "CP2-TC-REVISION" for check in
               evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements()).checks)


@pytest.mark.parametrize("revision,reuse,ok,message", [
    (dict(tc_id="TC-MODE-003", revised_by="TC-CAND-001"), False, True, "사람 승인 전까지"),
    (dict(tc_id="TC-NONE-999", revised_by="TC-CAND-001"), False, False, "기존 TC 목록에 없음"),
    (dict(tc_id="TC-MODE-003", revised_by="TC-CAND-009"), False, False, "test_cases에 없음"),
    (dict(tc_id="TC-TEMP-001", revised_by="TC-CAND-001"), True, False, "그대로 재사용할 수 없음"),
])
def test_existing_tc_revision_is_checked_against_catalog_and_candidates(revision, reuse, ok, message):
    design = cp2_valid_design()
    payload = design.model_dump(mode="json", by_alias=True)
    payload["기존_TC_수정"] = [dict(revision, reason="같은 제습→냉방 전환에서 적용 버튼과 내부값 확인만 빠짐")]
    if not reuse:
        payload["관련_기존_TC"] = []
    revised = Agent2TestDesign.model_validate(payload)
    assert revised.model_dump(mode="json", by_alias=True)["기존_TC_수정"][0]["tc_id"] == revision["tc_id"]
    check = cp2_check(evaluate_checkpoint2(cp1_request(), cp2_analysis(), revised, cp2_requirements()),
                      "CP2-TC-REVISION")
    assert (check.status == CheckStatus.PASS) is ok and message in check.message


def test_revision_rule_reaches_the_writer_but_not_the_shared_review_rules():
    from qa_pipeline_agent2 import AGENT2_SYSTEM_INSTRUCTIONS
    from qa_pipeline_contracts import QA_CONFIRMED_RULES, QA_TC_REVISION_RULE
    assert QA_TC_REVISION_RULE in AGENT2_SYSTEM_INSTRUCTIONS and "기존_TC_수정" in QA_TC_REVISION_RULE
    assert "H-3" not in QA_CONFIRMED_RULES  # its stored text is bound to earlier review inputs


def test_writer_is_told_not_to_mix_operation_and_check_in_one_step():
    """2026-10-18 사람 대조 H-4: 절차 한 줄에는 조작만, 확인은 expected_results로."""
    from qa_pipeline_agent2 import AGENT2_SYSTEM_INSTRUCTIONS
    assert "조작 문장에 확인 내용을 붙이지 않습니다(H-4" in AGENT2_SYSTEM_INSTRUCTIONS


# --- TC 문장 언어 (2026-10-23 사람 대조: 풍량 TC 제목이 중국어로 생성됨) -----------------------
@pytest.mark.parametrize("field,text,ok", [
    ("title", "LOW准备后应用HIGH并核对面板、卡片与内部风量", False),   # 실제 10-23 풍량 제목
    ("title", "LOW 준비 후 HIGH 적용 時 패널 확인", False),          # 한자 한 글자
    ("steps", "選択した風量を適用する。", False),                    # 일본어
    ("title", "냉방 20°C 적용 후 패널·카드·내부 setTemp=20 확인 (COOL, IDU-00)", True),
])
def test_tc_text_must_be_korean(field, text, ok):
    design = cp2_valid_design()
    tc = design.test_cases[0]
    setattr(tc, field, text if field == "title" else [text, *tc.steps[1:]])
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    lang = [c for c in result.checks if c.rule_id == "CP2-LANG"]
    if ok:   # reported only on a violation, so saved Korean designs recompute unchanged
        assert not lang
    else:
        assert lang[0].status == CheckStatus.FAIL and result.status == CheckStatus.FAIL
        assert tc.tc_id in lang[0].message and "한국어로 다시 작성" in lang[0].message
