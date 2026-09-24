"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


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
    result = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(),
        legacy_wording_checks=False, require_structured_restoration=True,
        require_state_restoration_policy=True, use_structured_scope_restoration=True)
    assert (result.status == CheckStatus.PASS) == (mutation == "none"), result.model_dump()
    assert design.model_dump_json() == before
    historical = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False)
    assert cp2_check(historical, "CP2-015").status == CheckStatus.FAIL


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
    result = pipeline.evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(),
        legacy_wording_checks=False, use_structured_scope_restoration=True)
    assert (cp2_check(result, "CP2-006").status == CheckStatus.PASS) == (scope == "trace_only")
    historical = pipeline.evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(), legacy_wording_checks=False)
    assert cp2_check(historical, "CP2-006").status == CheckStatus.FAIL


@pytest.mark.parametrize("parts", [
    ["[복원] 원래 값으로 되돌립니다.", "원래 상태인지 확인합니다."],
    ["Return to the recorded value.", "Check the original state."],
])
@pytest.mark.parametrize("mutation", ["whole", "split", "missing", "reordered", "changed",
                                     "interleaved", "across_fields", "across_cases", "disabled_restore"])
def test_split_procedure_preservation_requires_contiguous_complete_source(parts, mutation):
    request, analysis, design = cp1_request(), cp2_analysis(), detailed_boundary_design()
    note = " ".join(parts)
    request.acceptance_notes.append(note)
    analysis.procedure_notes = [note]
    tc = design.test_cases[0]
    tc.restore_required = True
    tc.restore_steps = [note] if mutation == "whole" else list(parts)
    if mutation == "missing": tc.restore_steps.pop()
    elif mutation == "reordered": tc.restore_steps.reverse()
    elif mutation == "changed": tc.restore_steps[-1] += " 다른 값으로 판정합니다."
    elif mutation == "interleaved": tc.restore_steps.insert(1, "다른 조작을 합니다.")
    elif mutation == "across_fields": tc.preconditions.append(tc.restore_steps.pop(0))
    elif mutation == "across_cases":
        other = tc.model_copy(deep=True)
        other.tc_id = "TC-CAND-002"
        tc.restore_steps = parts[:1]
        other.restore_steps = parts[1:]
        design.test_cases.append(other)
    elif mutation == "disabled_restore": tc.restore_required = False
    original = design.model_dump_json()
    result = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(),
        legacy_wording_checks=False, allow_split_procedure_notes=True)
    assert (cp2_check(result, "CP2-014").status == CheckStatus.PASS) == (mutation in {"whole", "split"})
    assert design.model_dump_json() == original
    historical = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(),
        legacy_wording_checks=False)
    assert (cp2_check(historical, "CP2-014").status == CheckStatus.PASS) == (mutation == "whole")
    if mutation not in {"whole", "split"}:
        assert "절차 원문 누락·순서 불일치" in cp2_check(result, "CP2-014").message


@pytest.mark.parametrize("wording", ["실행이 끝나면 처음 기록한 모습으로 되돌립니다.",
                                    "After the exercise, return to the captured state."])
def test_new_wording_policy_preserves_procedure_handoff_without_keywords(wording):
    request, analysis, design = cp1_request(), cp2_analysis(), detailed_boundary_design()
    request.acceptance_notes.append(wording)
    analysis.procedure_notes = [wording]
    first = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False)
    assert cp2_check(first, "CP2-014").status == CheckStatus.FAIL
    tc = design.test_cases[0]
    tc.restore_required = True
    tc.restore_steps.append(wording)
    preserved = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False)
    assert cp2_check(preserved, "CP2-014").status == CheckStatus.PASS
    design.excluded_scope.append(wording)
    excluded = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False)
    assert cp2_check(excluded, "CP2-014").status == CheckStatus.FAIL


@pytest.mark.parametrize("target", ["현재값 표시 영역", "설정치 표시부", "Current setting readout"])
def test_new_wording_policy_accepts_target_labels_but_requires_bindings(target):
    from qa_pipeline_agent2 import _tc_observation_binding_errors
    tc = detailed_boundary_design().test_cases[0]
    tc.expected_results[0].observation_target = target
    assert _tc_observation_binding_errors(tc)
    assert not _tc_observation_binding_errors(tc, legacy_wording_checks=False)
    tc.expected_results[0].verify_after_step = "없는 단계"
    assert _tc_observation_binding_errors(tc, legacy_wording_checks=False)
    tc.expected_results[0].observation_target = None
    assert len(_tc_observation_binding_errors(tc, legacy_wording_checks=False)) >= 2


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
    cp = pipeline.evaluate_checkpoint2(request, analysis, design, cp2_requirements(), legacy_wording_checks=False)
    assert (cp.status == CheckStatus.PASS) == (mutation == "none"), cp.model_dump()


@pytest.mark.parametrize("marked", ["[시험 절차 메모] 시험이 끝나면 원래 상태로 복원하고 확인합니다.",
                                  "[복원] 모든 검사가 끝났을 때 원래 값으로 복원합니다."])
def test_marked_restoration_is_preserved_as_procedure_not_exclusion(marked):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    request.acceptance_notes.append(marked)
    assert cp2_check(evaluate_checkpoint2(request, analysis, design, cp2_requirements()), "CP2-014").status == CheckStatus.FAIL
    design.test_cases[0].restore_steps.append(marked)
    design.test_cases[0].restore_required = True
    assert cp2_check(evaluate_checkpoint2(request, analysis, design, cp2_requirements()), "CP2-014").status == CheckStatus.PASS
    design.excluded_scope.append(marked)
    assert cp2_check(evaluate_checkpoint2(request, analysis, design, cp2_requirements()), "CP2-014").status == CheckStatus.FAIL


@pytest.mark.parametrize("altered", [False, True])
def test_cp2_boundary_relation_compares_linked_condition_not_shared_numbers(altered):
    request, analysis, design = cp1_request(), cp2_analysis(), cp2_valid_design()
    case = design.test_cases[0]
    result = case.expected_results[0]
    condition = next(c for c in analysis.confirmed_conditions if c.condition_id == result.source_condition_ids[0])
    condition.source_text = condition.statement = "온도 30°C 이상 요청은 차단합니다."
    result.statement = "온도 30°C 초과 요청은 차단합니다." if altered else condition.source_text
    result.source_condition_ids = [condition.condition_id]
    request.acceptance_notes.append(condition.source_text)
    checkpoint = evaluate_checkpoint2(request, analysis, design, cp2_requirements())
    failures = cp2_check(checkpoint, "CP2-017")
    assert ("연결된 조건과 기대 동작이 반대" in failures.message) == altered


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
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(),
                                  require_structured_restoration=True)
    assert (cp2_check(result, "CP2-023").status == CheckStatus.PASS) is (mutation == "valid")


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
@pytest.mark.parametrize("mutation", [None, "different_target", "duplicate_modifier", "wrong_step"])
def test_common_observation_binding_has_no_feature_specific_exception(target, mutation):
    from qa_pipeline_agent2 import _tc_observation_binding_errors
    tc = detailed_boundary_design().test_cases[0]
    tc.expected_results = [tc.expected_results[0]]
    er = tc.expected_results[0]
    er.observation_target = target
    er.statement = f"{target}가 요구된 값으로 표시된다."
    er.verify_after_step = tc.steps[-1]
    if mutation == "different_target":
        er.observation_target = "다른 장비의 상태"
    elif mutation == "duplicate_modifier":
        er.observation_target = f"대상 장비의 {target}"
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
            for error in _tc_observation_binding_errors(design.test_cases[0], legacy_wording_checks=False):
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
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(),
                                          require_state_restoration_policy=True)
    assert cp2_check(result, "CP2-022").status == (CheckStatus.PASS if accepted else CheckStatus.FAIL)


def test_blocked_change_requires_state_observation_not_just_notification():
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.state_effect = pipeline.TcStateEffect.BLOCKED_CHANGE
    tc.restore_required, tc.restore_steps = True, ["초기 상태로 복원한다."]
    tc.expected_results = [r for r in tc.expected_results if r.observation_layer == ObservationLayer.NOTIFICATION]
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(),
                                          require_state_restoration_policy=True)
    assert cp2_check(result, "CP2-022").status == CheckStatus.FAIL


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


@pytest.mark.parametrize("mutation", [None, "extra_alert", "changed_value", "combined_sources", "unknown_source"])
def test_trace_only_expected_results_cannot_expand_original_request(mutation):
    from qa_pipeline_contracts import RequirementScopeEvidence, ScopeBasis
    analysis, design = cp2_analysis(), cp2_valid_design()
    condition = analysis.confirmed_conditions[2]
    condition.statement = condition.source_text
    effect = analysis.requirement_effects[2]
    effect.scope_evidence = RequirementScopeEvidence(basis=ScopeBasis.REQUEST_TRACE_ONLY,
        request_condition_ids=[condition.condition_id], srs_source_text="Toast 표시")
    expected = design.test_cases[0].expected_results[2]
    expected.statement = condition.source_text
    if mutation == "extra_alert":
        expected.statement += " 경고 아이콘도 표시한다."
    elif mutation == "changed_value":
        expected.statement = "성공 안내 Toast를 표시한다."
    elif mutation == "combined_sources":
        expected.source_condition_ids.append("COND-001")
    elif mutation == "unknown_source":
        expected.source_condition_ids.append("COND-999")
    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())
    assert cp2_check(result, "CP2-017").status == (CheckStatus.PASS if mutation is None else CheckStatus.FAIL)


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
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(), require_procedure_detail=False)
    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-020").status == CheckStatus.PASS
    assert design.test_cases[0].expected_results[0].verify_after_step == design.test_cases[0].expected_results[1].verify_after_step
    assert Agent2TestDesign.model_validate_json(design.model_dump_json()) == design


@pytest.mark.parametrize("mutation", [
    "combined", "english_combined", "missing_timing", "unknown_timing", "ambiguous_timing",
    "missing_target", "different_target", "generic_target", "vague_step",
])
def test_new_tc_detail_rejects_compressed_or_unlinked_drafts(mutation):
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    if mutation == "combined":
        tc.steps[1] = "제어 패널에 온도를 입력하고 적용한다."
    elif mutation == "english_combined":
        tc.steps[1] = "Enter the temperature and apply the pending command."
    elif mutation == "missing_timing":
        tc.expected_results[0].verify_after_step = None
    elif mutation == "unknown_timing":
        tc.expected_results[0].verify_after_step = "존재하지 않는 조작"
    elif mutation == "ambiguous_timing":
        tc.steps.append(tc.steps[-1])
    elif mutation == "missing_target":
        tc.expected_results[0].observation_target = None
    elif mutation == "different_target":
        tc.expected_results[0].observation_target = "다른 장비의 이력"
    elif mutation == "generic_target":
        tc.expected_results[0].observation_target = "화면"
    else:
        tc.steps[0] = "테스트를 실행한다."
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(), require_procedure_detail=False)
    assert cp2_check(result, "CP2-020").status == CheckStatus.FAIL


def test_tc_detail_preserves_legacy_read_only_and_existing_only_designs():
    old = cp2_valid_design()
    assert cp2_check(pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), old, cp2_requirements(), require_procedure_detail=False), "CP2-020").status == CheckStatus.FAIL
    assert pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), old, cp2_requirements(), require_tc_detail=False).status == CheckStatus.PASS
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.steps = ["대상 장비의 화면과 내부 값을 조회한다."]
    for result in tc.expected_results:
        result.verify_after_step = tc.steps[0]
    tc.restore_required = True
    tc.restore_steps = ["원래 값을 선택하고 적용한다."]
    assert cp2_check(pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(), require_procedure_detail=False), "CP2-020").status == CheckStatus.PASS
    design.test_cases = []
    assert cp2_check(pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements(), require_procedure_detail=False), "CP2-020").status == CheckStatus.PASS


@pytest.mark.parametrize("feature", ["temperature", "fan"])
def test_procedure_detail_accepts_explicit_selection_and_restore_without_new_product_results(feature):
    request, analysis, requirements = cp1_request(), cp2_analysis(), cp2_requirements()
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.restore_required = True
    tc.restore_steps = [
        "대상 장비의 설정 온도를 초기값인 18°C로 복원하고 적용한다.",
        "대상 장비의 화면 온도와 내부 온도가 모두 초기값 18°C인지 확인한다.",
    ]
    if feature == "fan":
        request = ChangeRequest(
            request_id="CR-PROCEDURE-FAN-001", change_type="MODIFIED",
            target_requirement_id="REQ-FAN-001",
            before_value="MED의 표시 문구는 미정이다.",
            after_value="MED 적용 후 대상 장비 카드에 중풍이 표시되고 내부 fanSpeed는 MED이다.",
            description="MED 풍량의 표시 문구를 중풍으로 명시한다.",
            acceptance_notes=["초기 LOW 풍량을 확인하고 시험 후 LOW 풍량으로 복원한다."],
        )
        conditions = [
            ConfirmedCondition(
                condition_id=f"COND-{index:03}", statement=statement,
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text=request.after_value, requirement_ids=["REQ-FAN-001"],
            )
            for index, statement in enumerate([
                "대상 장비 카드에 중풍이 표시된다.",
                "대상 장비의 내부 fanSpeed는 MED이다.",
            ], 1)
        ]
        analysis = analysis.model_copy(update={
            "request_id": request.request_id, "target_requirement_id": "REQ-FAN-001",
            "change_summary": request.description, "before_condition": request.before_value,
            "after_condition": request.after_value, "confirmed_conditions": conditions,
            "requirement_effects": [RequirementEffect(
                requirement_id="REQ-FAN-001", relation=RequirementRelation.MODIFIED,
                reason="MED 표시 문구 변경",
            )],
        })
        requirements = {"REQ-FAN-001": SrsRequirement(
            requirement_id="REQ-FAN-001", statement="풍량 선택과 적용",
            acceptance_criteria="적용 후 내부 fanSpeed는 선택한 풍량 코드와 같다.",
        )}
        design.request_id = request.request_id
        design.related_existing_tests = []
        tc.title = "MED 적용 후 중풍 표시와 내부 코드 확인"
        tc.test_type = TcType.NORMAL
        tc.requirement_ids = tc.feature_requirement_ids = ["REQ-FAN-001"]
        tc.source_condition_ids = ["COND-001", "COND-002"]
        tc.test_data = StructuredTestData()
        tc.preconditions = ["오류와 잠금이 없는 단일 대상 장비의 초기 풍량이 LOW이다."]
        tc.steps = [
            "중앙 관제 패널에서 대상 장비를 선택한다.",
            "대상 장비의 풍량 값으로 MED를 선택한다.",
            "선택한 MED 풍량을 중앙 관제 패널에서 적용한다.",
        ]
        tc.expected_results = [
            ExpectedResult(
                result_id="ER-001", statement=conditions[0].statement,
                observation_layer=ObservationLayer.UI, source_condition_ids=["COND-001"],
                verify_after_step=tc.steps[-1], observation_target="대상 장비 카드",
            ),
            ExpectedResult(
                result_id="ER-002", statement=conditions[1].statement,
                observation_layer=ObservationLayer.INTERNAL_STATE, source_condition_ids=["COND-002"],
                verify_after_step=tc.steps[-1], observation_target="대상 장비의 내부 fanSpeed",
            ),
        ]
        tc.restore_steps = [
            "시험 뒤 대상 장비를 초기 LOW 풍량으로 복원하고 적용한다.",
            "대상 장비의 내부 fanSpeed가 초기값 LOW로 돌아왔는지 확인한다.",
        ]
    product_results = [item.model_dump() for item in tc.expected_results]

    result = pipeline.evaluate_checkpoint2(request, analysis, design, requirements)

    assert cp2_check(result, "CP2-020").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-021").status == CheckStatus.PASS
    assert [item.model_dump() for item in tc.expected_results] == product_results
    assert Agent2TestDesign.model_validate_json(design.model_dump_json()) == design


@pytest.mark.parametrize("mutation", [
    "missing_selection", "value_selection_only", "negated_selection_step",
    "negated_click_step", "negated_selected_precondition", "selected_state_denied",
    "selection_after_value_operation",
])
def test_procedure_detail_rejects_missing_false_or_late_target_preparation(mutation):
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    if mutation == "missing_selection":
        tc.steps.pop(0)
    elif mutation == "value_selection_only":
        tc.steps[0] = "대상 장비의 온도 값으로 17°C를 선택한다."
    elif mutation == "negated_selection_step":
        tc.steps[0] = "대상 장비 카드를 선택하지 않는다."
    elif mutation == "negated_click_step":
        tc.steps[0] = "대상 장비 카드를 클릭하지 않는다."
    elif mutation == "negated_selected_precondition":
        tc.steps.pop(0)
        tc.preconditions.append("대상 장비가 아직 선택되지 않은 상태이다.")
    elif mutation == "selected_state_denied":
        tc.steps.pop(0)
        tc.preconditions.append("대상 장비가 이미 선택된 상태가 아니다.")
    else:
        tc.steps[0], tc.steps[1] = tc.steps[1], tc.steps[0]

    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-021").status == CheckStatus.FAIL


def test_procedure_detail_accepts_already_selected_target_without_extra_click():
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.preconditions.append("중앙 관제 화면에서 대상 장비가 이미 선택된 상태이다.")
    tc.steps.pop(0)

    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-021").status == CheckStatus.PASS
    assert len(tc.steps) == 2


@pytest.mark.parametrize("restore_steps", [
    ["대상 장비의 설정 온도를 초기값 18°C로 복원하고 적용한다."],
    ["원래 값을 선택하고 적용한다.", "결과를 확인한다."],
    ["대상 장비의 설정 온도를 초기값 18°C로 복원하고 적용한다.", "복원 결과를 확인한다."],
    ["대상 장비의 설정 온도를 초기값 18°C로 복원하고 적용한다.", "대상 장비의 내부 온도를 확인한다."],
    ["대상 장비의 설정 온도를 초기값 18°C로 복원하고 적용한다.", "대상 장비의 내부 온도가 18°C인지 확인하지 않는다."],
])
def test_procedure_detail_rejects_vague_missing_or_negated_restore_verification(restore_steps):
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.restore_required = True
    tc.restore_steps = restore_steps

    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-021").status == CheckStatus.FAIL


def test_procedure_detail_accepts_observed_baseline_without_invented_initial_value():
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.restore_required = True
    tc.restore_steps = [
        "시험 직전에 관찰한 대상 장비의 모드와 설정 온도로 복원하고 적용한다.",
        "대상 장비의 내부 모드와 설정 온도가 시험 직전에 관찰한 원상태와 일치하는지 확인한다.",
    ]

    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-021").status == CheckStatus.PASS


def test_procedure_detail_preserves_read_only_existing_only_and_legacy_contracts():
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.steps = ["대상 장비의 화면 온도와 내부 온도를 조회한다."]
    tc.restore_required = False
    tc.restore_steps = []
    for expected in tc.expected_results:
        expected.verify_after_step = tc.steps[0]
    read_only = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(read_only, "CP2-021").status == CheckStatus.PASS
    tc.steps = ["Check the current device temperature."]
    for expected in tc.expected_results:
        expected.verify_after_step = tc.steps[0]
    read_only = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(read_only, "CP2-021").status == CheckStatus.PASS

    design.test_cases = []
    existing_only = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(existing_only, "CP2-021").status == CheckStatus.PASS

    legacy = detailed_boundary_design()
    legacy.test_cases[0].steps.pop(0)
    legacy.test_cases[0].restore_required = True
    legacy.test_cases[0].restore_steps = ["원래 값을 선택하고 적용한다."]
    for kwargs in ({"require_procedure_detail": False}, {"require_tc_detail": False}):
        result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), legacy, cp2_requirements(), **kwargs)
        assert not any(check.rule_id == "CP2-021" for check in result.checks)


@pytest.mark.parametrize("basis, accepted", [
    ("초기값", False),
    ("시험 전에 관찰한 값", True),
    ("시험 직전에 기록한 원상태", True),
])
def test_procedure_detail_requires_a_named_or_observed_restoration_baseline(basis, accepted):
    design = detailed_boundary_design()
    tc = design.test_cases[0]
    tc.test_data = StructuredTestData()
    tc.preconditions = ["오류 없는 대상 장비를 준비한다."]
    tc.restore_required = True
    tc.restore_steps = [f"대상 장비를 {basis}으로 복원하고 적용한다.",
                        f"대상 장비의 내부 온도를 {basis}과 비교해 확인한다."]
    result = pipeline.evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(result, "CP2-021").status == (CheckStatus.PASS if accepted else CheckStatus.FAIL)


def test_procedure_detail_does_not_invent_device_selection_for_standalone_control():
    case = generic_new_control_test_case()
    case.restore_steps.append("복원 후 새 제어 스위치 상태를 시험 전에 기록한 값과 비교해 확인한다.")
    case.expected_results[0].observation_target = "새 제어 스위치"
    assert not pipeline._tc_procedure_detail_errors(case)


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
        {key: result.get(key) for key in ("statement", "observation_layer", "verify_after_step")}
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
        assert "같은 TC의 같은 절차 배열" in instructions
        assert "조작 수단이 없는 입력에서 버튼·횟수를 추정하지 않습니다" in instructions
        assert "UI 기대결과에 내부 enum을 곧바로 화면 표시 문자열처럼 쓰지 않습니다" in instructions
        assert "설정 온도 30°C 입력 → 적용" not in instructions
        assert "작성 수준 예시 (아래는 기존 필드의 일부만 발췌한 형식 참고이며 이번 입력의 제품 기준이 아닙니다)" in instructions
        assert "1. 중앙 관제 화면에서 시험할 대상 장비 카드를 선택한다." in instructions
        assert "2. 선택한 장비의 제어 패널에서 풍량을 MED로 선택한다." in instructions
        assert "3. 제어 패널의 적용 버튼을 눌러 선택한 풍량을 대상 장비에 적용한다." in instructions
        assert "복원 후 대상 장비의 내부 fanSpeed가 초기값 LOW로 돌아왔는지 확인한다." in instructions
        assert "대상 선택 성공·알림·선택 색상·LOW의 한글 표시를 새 expected_results로 만들지 않습니다." in instructions
        assert "예시 B: 입력이 '초기 설정 온도 24°C, 30°C 적용 후 카드·내부 설정 온도 30°C'를 요구하면" in instructions
        assert "예시 C: 입력이 현재 상태를 조회하는 읽기 전용 시험이면" in instructions
        assert "값·화면명·필드명·조건 ID·초기 상태는 반드시 현재 입력에서 가져오며" in instructions
        assert responses.kwargs["store"] is False


@pytest.mark.parametrize("expected", ["HIGH", "99", "17"])
def test_new_tc_expected_value_requires_its_own_condition(expected):
    design = cp2_valid_design()
    design.test_cases[0].expected_results[0].statement = f"화면 값은 {expected}로 변경된다."
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL


def test_new_tc_med_to_high_is_rejected_without_rejecting_med():
    analysis, design = cp2_analysis(), cp2_valid_design()
    condition = analysis.confirmed_conditions[0]
    condition.statement = condition.source_text = "중풍(MED) 값이 화면에 표시된다."
    expected = design.test_cases[0].expected_results[0]
    expected.source_condition_ids = [condition.condition_id]
    expected.statement = "중풍(MED) 값이 화면에 표시된다."
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements()), "CP2-017").status == CheckStatus.PASS
    expected.statement = "강풍(HIGH) 값이 화면에 표시된다."
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements()), "CP2-017").status == CheckStatus.FAIL
    # Historical reports retain their explicitly versioned original CP2 result.
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(), require_candidate_expectation_guard=False), "CP2-017").status == CheckStatus.PASS


def test_new_tc_range_allows_in_range_value_but_not_opposite_policy():
    analysis, design = cp2_analysis(), cp2_valid_design()
    condition = analysis.confirmed_conditions[0]
    condition.statement = condition.source_text = "18°C에서 30°C 입력을 허용한다."
    expected = design.test_cases[0].expected_results[0]
    expected.source_condition_ids = [condition.condition_id]
    expected.statement = "24°C 입력을 허용한다."
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements()), "CP2-017").status == CheckStatus.PASS
    expected.statement = "24°C 입력을 차단한다."
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements()), "CP2-017").status == CheckStatus.FAIL


def test_boundary_input_in_expectation_is_not_confused_with_output():
    analysis, design = cp2_analysis(), cp2_valid_design()
    result = design.test_cases[0].expected_results[0]
    result.source_condition_ids = ["COND-001"]
    result.statement = "17°C 요청을 차단한다."
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements()), "CP2-017").status == CheckStatus.PASS
    result.statement = "17°C 요청을 차단하고 화면 온도는 17°C가 된다."
    assert cp2_check(evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements()), "CP2-017").status == CheckStatus.FAIL


def test_cp2_rejects_opposite_existing_behavior_and_srs_value():
    analysis = cp2_analysis()
    spec = pipeline.ExistingRegressionSpec(
        tc_id="TC-V2-999", test_function="test_tc_v2_999",
        requirement_ids=("REQ-TEMP-001", "REQ-STATE-001", "REQ-NOTIFY-001"),
        covered_behaviors=("AUTO 18°C 미만 허용, 상태 유지, 안내 표시",), source="APPROVED",
    )
    design = Agent2TestDesign(request_id=analysis.request_id, existing_tc_comparison_completed=True,
        related_existing_tests=[ExistingTestSelection(tc_id=spec.tc_id,
            source_condition_ids=["COND-001", "COND-002", "COND-003"], selection_reason="기존 검증 재사용")],
        test_cases=[], coverage_summary="기존 검증")
    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(),
        existing_catalog=(spec,), require_existing_behavior_values=True)
    assert cp2_check(result, "CP2-019").status == CheckStatus.FAIL
    design = cp2_valid_design()
    design.srs_revision_proposals = [pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001", requirement_id="REQ-TEMP-001", source_condition_ids=["COND-001"],
        current_acceptance_criteria="범위 밖 차단", proposed_acceptance_criteria="AUTO 모드 99°C 허용", reason="변경 반영")]
    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(), require_srs_revision_proposals=True)
    assert cp2_check(result, "CP2-018").status == CheckStatus.FAIL


def test_existing_test_selection_accepts_versioned_official_tc_id():
    selection = ExistingTestSelection(
        tc_id="TC-V2-001",
        source_condition_ids=["COND-001"],
        selection_reason="승인된 V2 공식 TC를 영향 회귀 대상으로 재사용한다.",
    )

    assert selection.tc_id == "TC-V2-001"

def test_request_diff_recognizes_repeated_existing_clause_as_unchanged():
    request = ChangeRequest(
        request_id="CR-FAN-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-FAN-001",
        before_value="HIGH는 장비 카드에 강풍으로 표시됩니다.",
        after_value="MED는 장비 카드에 중풍으로, HIGH는 강풍으로 표시됩니다.",
        description="MED 표시 규칙을 추가합니다.",
    )
    existing_high = ConfirmedCondition(
        condition_id="COND-001",
        statement="HIGH는 장비 카드에 강풍으로 표시되어야 한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=request.after_value,
        requirement_ids=["REQ-FAN-001"],
        change_role=ConditionChangeRole.UNCHANGED,
    )
    changed_medium = ConfirmedCondition(
        condition_id="COND-002",
        statement="MED는 장비 카드에 중풍으로 표시되어야 한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=request.after_value,
        requirement_ids=["REQ-FAN-001"],
        change_role=ConditionChangeRole.CHANGED,
    )

    assert _is_unchanged_condition_for_request(existing_high, request) is True
    assert _is_unchanged_condition_for_request(changed_medium, request) is False

def test_request_diff_treats_mapping_or_order_change_as_changed_without_explicit_role():
    request = ChangeRequest(
        request_id="CR-MAPPING-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-FAN-001",
        before_value="LOW 다음은 MED, MED 다음은 HIGH다.",
        after_value="LOW 다음은 HIGH, HIGH 다음은 MED다.",
        description="풍량 전환 순서를 변경한다.",
    )
    swapped_mapping = ConfirmedCondition(
        condition_id="COND-003",
        statement="LOW 다음 풍량은 HIGH다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=request.after_value,
        requirement_ids=["REQ-FAN-001"],
    )

    assert swapped_mapping.change_role == ConditionChangeRole.CHANGED
    assert _is_unchanged_condition_for_request(swapped_mapping, request) is False

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
    assert responses.kwargs["text_format"] is Agent2TestDesign
    assert responses.kwargs["store"] is False
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent2-2-38"
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
    assert "Requirement ID만 같고 검증 동작이 다르면" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "내부 필드 식별자" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "target_role=PRIMARY_TEST_DEVICE" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "V1의 3단계 QA 기준" in AGENT2_SYSTEM_INSTRUCTIONS
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
    assert len(result.checks) == 17
    assert all(item.status == CheckStatus.PASS for item in result.checks)

@pytest.mark.parametrize("values", [("MED", "HIGH"), ("18°C", "30°C"), ("HEAT", "COOL")])
@pytest.mark.parametrize("layout", ["split", "one_complete", "missing_link", "actual_gap"])
def test_compound_existing_reuse_requires_actual_condition_links(values, layout):
    request, analysis, design, catalog = compound_reuse_fixture(values, layout)
    before = design.model_dump()
    result = evaluate_checkpoint2(request, analysis, design, cp2_requirements(),
        existing_catalog=catalog, require_existing_behavior_values=True)
    check = cp2_check(result, "CP2-019")
    assert check.status == (CheckStatus.PASS if layout in {"split", "one_complete"} else CheckStatus.FAIL)
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
        assert '"detected_values": ["HIGH", "MED"]' in prompt
        assert "TC-X와 TC-Y 모두 C에 연결" in prompt
        assert "권장 TC 목록이나 합격 판정이 아닙니다" in prompt
        if kwargs:
            assert '"linked_existing_tc_ids": ["TC-SPLIT-001"]' in prompt
            assert '"values_not_covered_by_links": ["HIGH"]' in prompt
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
        require_existing_behavior_values=True,
    )
    assert guarded.status == CheckStatus.PASS
    assert cp2_check(guarded, "CP2-019").status == CheckStatus.PASS

    request_with_procedures = cp1_request().model_copy(update={"acceptance_notes": [
        "첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작한다.",
        "시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다.",
    ]})
    kwargs = dict(existing_catalog=(*pipeline.EXISTING_REGRESSION_CATALOG, existing_spec))
    legacy = evaluate_checkpoint2(
        request_with_procedures, analysis, design, cp2_requirements(),
        allow_existing_procedure_review=False, **kwargs,
    )
    assert cp2_check(legacy, "CP2-014").status == CheckStatus.FAIL
    reviewed = evaluate_checkpoint2(
        request_with_procedures, analysis, design, cp2_requirements(), **kwargs,
    )
    assert reviewed.status == CheckStatus.PASS
    assert "최종 사람 검토" in cp2_check(reviewed, "CP2-014").message
    notes = pipeline._existing_test_procedure_review_notes(request_with_procedures, design)
    assert len(notes) == 2
    assert all(any(original in note for note in notes) for original in request_with_procedures.acceptance_notes)
    assert all(existing_spec.tc_id in note and "자동 확정하지 않았습니다" in note for note in notes)
    # 기존 TC 선택이 없거나 신규 후보가 있으면 준비·복원 검사를 건너뛰지 않습니다.
    for other in (design.model_copy(update={"related_existing_tests": []}), cp2_valid_design()):
        checked = evaluate_checkpoint2(request_with_procedures, analysis, other, cp2_requirements(), **kwargs)
        assert cp2_check(checked, "CP2-014").status == CheckStatus.FAIL
    excluded = design.model_copy(update={"excluded_scope": request_with_procedures.acceptance_notes})
    assert cp2_check(evaluate_checkpoint2(
        request_with_procedures, analysis, excluded, cp2_requirements(), **kwargs,
    ), "CP2-014").status == CheckStatus.FAIL


def test_checkpoint2_rejects_existing_only_reuse_with_different_explicit_values() -> None:
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
    legacy = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements(), **kwargs)
    guarded = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements(),
        require_existing_behavior_values=True, **kwargs,
    )
    assert legacy.status == CheckStatus.PASS  # 역사적 계약을 소급 변경하지 않음
    assert cp2_check(guarded, "CP2-019").status == CheckStatus.FAIL
    assert pipeline._explicit_behavior_values("REQ-FAN-001 MED 18.0°C") == {"MED", "18"}
    assert pipeline._explicit_behavior_values("HIGH 18°C") == {"HIGH", "18"}
    candidate = evaluate_checkpoint2(
        cp1_request(), analysis, cp2_valid_design(), cp2_requirements(),
        require_existing_behavior_values=True,
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
        require_srs_revision_proposals=True,
    )
    missing = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        cp2_valid_design(),
        cp2_requirements(),
        require_srs_revision_proposals=True,
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
    design = cp2_valid_design()
    original = design.model_dump()
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, requirements,
        require_srs_revision_proposals=True, allow_already_reflected_srs=True,
    )
    assert cp2_check(result, "CP2-018").status == (CheckStatus.PASS if reflected else CheckStatus.FAIL)
    assert design.model_dump() == original
    # Old evidence is rechecked with its old policy, never silently upgraded.
    legacy = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, requirements,
        require_srs_revision_proposals=True,
    )
    assert cp2_check(legacy, "CP2-018").status == CheckStatus.FAIL


@pytest.mark.parametrize("variant", ["identical", "rephrased", "related_missing", "target_missing"])
def test_srs_revision_policy_keeps_invalid_proposals_and_related_changes_blocked(variant):
    request, analysis, requirements = cp1_request(), cp2_analysis(), cp2_requirements()
    requirements[request.target_requirement_id] = requirements[request.target_requirement_id].model_copy(
        update={"acceptance_criteria": request.after_value}
    )
    design = cp2_valid_design()
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
        require_srs_revision_proposals=True, allow_already_reflected_srs=True,
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

def test_checkpoint2_rejects_existing_regression_regenerated_as_candidate() -> None:
    design = cp2_valid_design()
    regenerated = design.test_cases[0].model_copy(
        update={"purpose": TcPurpose.RELATED_REGRESSION}
    )

    result = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [regenerated]}),
        cp2_requirements(),
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-016").status == CheckStatus.FAIL
    assert "신규 후보로 재작성" in cp2_check(result, "CP2-016").message

def test_checkpoint2_allows_incompatible_target_regression_to_be_omitted() -> None:
    design = cp2_valid_design().model_copy(update={"related_existing_tests": []})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS

def test_checkpoint2_rejects_compound_ui_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    compound_result = test_case.expected_results[0].model_copy(
        update={"statement": "화면 모드는 AUTO이고 설정 온도는 18°C로 유지된다."}
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            compound_result,
                            *test_case.expected_results[1:],
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL
    assert "관찰값별로 분리" in cp2_check(result, "CP2-006").message

    for contextual_statement in (
        "AUTO 모드에서 화면의 온도 조작 버튼은 비활성화된다.",
        "AUTO 모드에서 화면의 설정 온도 표시는 ---이다.",
    ):
        contextual_result = test_case.expected_results[0].model_copy(
            update={"statement": contextual_statement}
        )
        contextual_design = design.model_copy(
            update={
                "test_cases": [
                    test_case.model_copy(
                        update={
                            "expected_results": [
                                contextual_result,
                                *test_case.expected_results[1:],
                            ]
                        }
                    )
                ]
            }
        )
        contextual_checkpoint = evaluate_checkpoint2(
            cp1_request(), cp2_analysis(), contextual_design, cp2_requirements()
        )
        assert cp2_check(contextual_checkpoint, "CP2-006").status == CheckStatus.PASS

def test_checkpoint2_rejects_procedural_selection_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    selection_result = ExpectedResult(
        result_id="ER-004",
        statement="PRIMARY_TEST_DEVICE가 단일 선택된다.",
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
                            selection_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "준비용 장비 선택" in cp2_check(result, "CP2-017").message

def test_checkpoint2_rejects_action_success_as_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    procedural_result = ExpectedResult(
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
                            procedural_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "Condition 원문에 없는 실행 행동 성공" in cp2_check(result, "CP2-017").message

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

def test_checkpoint2_rejects_ui_display_not_present_in_condition_source() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    invented_display = ExpectedResult(
        result_id="ER-004",
        statement="사용자 화면의 잠금 상태가 잠금으로 표시된다.",
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
                            invented_display,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "Condition 원문에 없는 UI 표시" in cp2_check(result, "CP2-017").message

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
    historical = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements(),
        require_double_assert_timing=False,
    )
    assert cp2_check(historical, "CP2-006").status == CheckStatus.PASS

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

def test_verify_only_requirement_cannot_be_duplicated_as_new_candidate() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
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
                    reason="기존 중앙 제어 회귀 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
            acceptance_criteria="허용 대상에 기존 명령을 반영한다.",
        ),
    }
    base = cp2_valid_design().test_cases[0]
    verify_only = base.model_copy(
        update={
            "tc_id": "TC-CAND-002",
            "title": "기존 중앙 관제 적용 중복 후보",
            "test_type": TcType.NORMAL,
            "requirement_ids": ["REQ-CONTROL-001"],
            "source_condition_ids": ["COND-004"],
            "expected_results": [
                item.model_copy(update={"source_condition_ids": ["COND-004"]})
                for item in base.expected_results
            ],
            "feature_requirement_ids": ["REQ-CONTROL-001"],
        }
    )
    design = cp2_valid_design().model_copy(
        update={"test_cases": [*cp2_valid_design().test_cases, verify_only]}
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-016").status == CheckStatus.FAIL
    assert "VERIFY 유지 동작" in cp2_check(result, "CP2-016").message

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

def test_missing_three_tier_quality_criteria_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "common_qa_criteria": [],
            "domain_qa_criteria": [],
            "feature_requirement_ids": [],
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-012").status == CheckStatus.FAIL

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

def test_tc_positive_cross_tc_dependency_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "preconditions": ["이전 TC가 완료한 장비 상태를 그대로 사용한다."],
            "independence_reason": "선행 테스트 결과를 이어받아 실행한다.",
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-013").status == CheckStatus.FAIL

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
        update={"excluded_scope": [setup_note, restore_note]}
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
