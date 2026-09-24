"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


@pytest.mark.parametrize("variant,allowed", [
    ("normal", True), ("reversed", True), ("three_parts", True),
    ("same_field", True), ("two_requirements", True), ("three_requirements", True),
    ("number_changed", False), ("unknown_part", False), ("empty_part", False),
    ("leading_pipe", False), ("trailing_pipe", False), ("missing_id", False),
    ("extra_id", False), ("unknown_id", False), ("split_token", False),
])
def test_srs_pipe_quotes_validate_each_part_and_each_linked_id(variant, allowed):
    from qa_pipeline_agent1 import _srs_quote_is_grounded
    request, analysis, requirements = cp1_combined_srs_case()
    condition = analysis.confirmed_conditions[2]
    target = requirements[request.target_requirement_id]
    parts = [target.statement, target.acceptance_criteria]
    if variant == "reversed":
        parts.reverse()
    elif variant == "three_parts":
        parts = [target.statement, "범위 안 요청은 반영되고", "범위 밖 요청은 차단되며 화면·내부 설정 온도가 기존 값을 유지합니다."]
    elif variant == "same_field":
        parts = ["범위 안 요청은 반영되고", "범위 밖 요청은 차단되며 화면·내부 설정 온도가 기존 값을 유지합니다."]
        condition.statement = target.acceptance_criteria
    elif variant in {"two_requirements", "three_requirements"}:
        for key in (["REQ-NOTIFY-001"] if variant == "two_requirements" else ["REQ-NOTIFY-001", "REQ-STATE-001"]):
            parts.append(requirements[key].statement)
            condition.requirement_ids.append(key)
        parts.reverse()
    elif variant == "number_changed":
        parts[0] = parts[0].replace("16~30", "16~31")
    elif variant == "unknown_part":
        parts.append("입력에 없는 새로운 동작")
    elif variant == "empty_part":
        parts.insert(1, " ")
    elif variant == "leading_pipe":
        parts.insert(0, "")
    elif variant == "trailing_pipe":
        parts.append("")
    elif variant == "missing_id":
        parts.append(requirements["REQ-NOTIFY-001"].statement)
    elif variant == "extra_id":
        condition.requirement_ids.append("REQ-NOTIFY-001")
    elif variant == "unknown_id":
        condition.requirement_ids.append("REQ-UNKNOWN-001")
    elif variant == "split_token":
        # Cannot join numeric fragments into a value that the SRS never states.
        parts = ["1", "6~30°C"]
    condition.source_text = " | ".join(parts)
    original = analysis.model_dump(mode="json")
    assert _srs_quote_is_grounded(condition.source_text, condition.requirement_ids, requirements) == allowed
    result = evaluate_checkpoint1(request, analysis, requirements,
        legacy_wording_checks=False, allow_background_range_paraphrase=True, allow_srs_quote_parts=True)
    assert (cp1_check(result, "CP1-007").status == CheckStatus.PASS) == allowed
    assert analysis.model_dump(mode="json") == original


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("mutation", ["none", "invented_part", "wrong_id", "partial_range", "after_policy"])
def test_combined_background_range_retains_target_and_complete_source_guards(reverse, mutation):
    request, analysis, requirements = cp1_combined_srs_case()
    request.description = "기존 16~30°C 범위를 유지합니다."
    request.after_value = analysis.after_condition = "범위 밖 입력은 기존 설정값을 유지합니다."
    analysis.confirmed_conditions = analysis.confirmed_conditions[:3]
    condition = analysis.confirmed_conditions[2]
    condition.change_role = ConditionChangeRole.UNCHANGED
    parts = condition.source_text.split(" | ")
    if mutation == "invented_part":
        parts.append("없는 내용")
    elif mutation == "wrong_id":
        condition.requirement_ids = ["REQ-STATE-001"]
    elif mutation == "partial_range":
        parts = ["16~30°C", "범위 밖 요청은 차단되며"]
    elif mutation == "after_policy":
        request.after_value = analysis.after_condition = "변경 후 설정 범위는 16~30°C입니다."
    condition.source_text = " | ".join(reversed(parts) if reverse else parts)
    old = evaluate_checkpoint1(request, analysis, requirements,
        legacy_wording_checks=False, allow_background_range_paraphrase=True)
    new = evaluate_checkpoint1(request, analysis, requirements,
        legacy_wording_checks=False, allow_background_range_paraphrase=True, allow_srs_quote_parts=True)
    assert cp1_check(old, "CP1-008").status == CheckStatus.FAIL
    assert (cp1_check(new, "CP1-008").status == CheckStatus.PASS) == (mutation == "none")


@pytest.mark.parametrize("requirement_id", ["REQ-NOTIFY-001", "REQ-STATE-001"])
@pytest.mark.parametrize("mutation", ["normal", "reversed", "foreign_part", "empty_part"])
def test_scope_evidence_combined_quotes_stay_bound_to_effect_requirement(requirement_id, mutation):
    from qa_pipeline_contracts import RequirementScopeEvidence, ScopeBasis
    request, analysis, requirements = cp1_request(), cp1_valid_analysis(), cp1_requirements()
    condition = analysis.confirmed_conditions[1]
    condition.requirement_ids.append(requirement_id)
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == requirement_id)
    effect.relation = RequirementRelation.VERIFY
    related = requirements[requirement_id]
    parts = [related.statement, related.acceptance_criteria]
    if mutation == "reversed":
        parts.reverse()
    elif mutation == "foreign_part":
        parts.append(requirements["REQ-TEMP-001"].statement)
    elif mutation == "empty_part":
        parts.append("")
    effect.scope_evidence = RequirementScopeEvidence(basis=ScopeBasis.REQUEST_TRACE_ONLY,
        request_condition_ids=[condition.condition_id], srs_source_text=" | ".join(parts))
    result = evaluate_checkpoint1(request, analysis, requirements,
        legacy_wording_checks=False, allow_srs_quote_parts=True)
    assert (cp1_check(result, "CP1-011").status == CheckStatus.PASS) == (mutation in {"normal", "reversed"})


def test_srs_pipe_policy_does_not_split_change_request_source():
    request, analysis, requirements = cp1_request(), cp1_valid_analysis(), cp1_requirements()
    analysis.confirmed_conditions[0].source_text += " | " + request.acceptance_notes[1]
    result = evaluate_checkpoint1(request, analysis, requirements,
        legacy_wording_checks=False, allow_srs_quote_parts=True)
    assert cp1_check(result, "CP1-007").status == CheckStatus.FAIL


@pytest.mark.parametrize("mutation", ["none", "missing", "wrong_requirement", "changed_role", "altered_source", "changed_number", "after_policy"])
def test_background_range_uses_frozen_source_not_verbatim_explanation(mutation):
    request, analysis, requirements = cp1_request(), cp1_valid_analysis(), cp1_requirements()
    request.description = "기존 16~30°C 범위를 유지합니다."
    request.after_value = analysis.after_condition = "범위 밖 입력은 기존 설정값을 유지합니다."
    analysis.confirmed_conditions = analysis.confirmed_conditions[:3]
    maintenance = analysis.confirmed_conditions[-1]
    maintenance.source_text = requirements[request.target_requirement_id].statement
    maintenance.statement = "섭씨 설정 범위 16~30°C는 기존 기준으로 유지합니다."
    maintenance.change_role = ConditionChangeRole.UNCHANGED
    if mutation == "missing":
        analysis.confirmed_conditions.pop()
    elif mutation == "wrong_requirement":
        maintenance.requirement_ids = ["REQ-STATE-001"]
    elif mutation == "changed_role":
        maintenance.change_role = ConditionChangeRole.CHANGED
    elif mutation == "altered_source":
        maintenance.source_text += " 임의 근거"
    elif mutation == "changed_number":
        maintenance.statement = "설정 범위는 15~30°C를 유지합니다."
    elif mutation == "after_policy":
        request.after_value = analysis.after_condition = "변경 후 설정 범위는 16~30°C입니다."
    original = analysis.model_dump(mode="json")
    old = evaluate_checkpoint1(request, analysis, requirements, legacy_wording_checks=False)
    assert cp1_check(old, "CP1-008").status == CheckStatus.FAIL
    new = evaluate_checkpoint1(request, analysis, requirements, legacy_wording_checks=False,
                              allow_background_range_paraphrase=True)
    assert (new.status == CheckStatus.PASS) == (mutation == "none"), new.model_dump()
    assert analysis.model_dump(mode="json") == original


@pytest.mark.parametrize("rewrite", [False, True])
def test_agent1_prompt_requires_exclusive_roles_without_dropping_gap_contract(rewrite):
    responses = Agent1FakeResponses()
    agent = OpenAIAgent1(client=SimpleNamespace(responses=responses))
    request = cp1_request()
    before = request.model_dump_json()
    extra = {"previous_analysis": cp1_valid_analysis(), "checkpoint_feedback": ["중복 분류"]} if rewrite else {}
    agent.analyze(request, cp1_requirements(), **extra)
    system, user = [item["content"] for item in responses.kwargs["input"]]
    assert "procedure_notes는 acceptance_notes 전체의 복사본이 아닙니다" in system
    assert "하나를 선택" in user and "중복 복사하지" in user
    assert "세 목록에 함께 보존" in system
    assert request.model_dump_json() == before


@pytest.mark.parametrize("note", [
    "[준비] 복원 버튼이 있는 화면을 엽니다.",
    "[복원] Return to the captured state after the scenario.",
    "[시험 절차 메모] 마무리할 때 처음 기록한 상태와 대조합니다.",
])
def test_structural_cp1_preserves_marked_procedure_roles_with_free_body_wording(note):
    from qa_pipeline_agent1 import _acceptance_delivery_contract

    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    analysis.procedure_notes = [note]
    request_before, analysis_before = request.model_dump_json(), analysis.model_dump_json()

    delivery = _acceptance_delivery_contract(request, legacy_wording_checks=False)
    assert delivery[-1]["source_text"] == note
    assert delivery[-1]["destination"] == "procedure_notes"
    result = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)

    assert result.status == CheckStatus.PASS, result.model_dump()
    assert cp1_check(result, "CP1-012").status == CheckStatus.PASS
    assert request.model_dump_json() == request_before
    assert analysis.model_dump_json() == analysis_before


@pytest.mark.parametrize("destination", ["missing", "condition", "scope", "gap"])
def test_structural_cp1_rejects_marked_procedure_omission_or_role_change(destination):
    note = "[복원] 원래 상태로 되돌립니다."
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    if destination == "condition":
        analysis.confirmed_conditions.append(ConfirmedCondition(
            condition_id="COND-090", statement=note, source_text=note,
            source_type=ConditionSource.CHANGE_REQUEST,
            requirement_ids=[request.target_requirement_id],
        ))
    elif destination == "scope":
        analysis.excluded_scope.append(note)
    elif destination == "gap":
        analysis.decision = AnalysisDecision.PARTIAL_PROCEED
        analysis.excluded_scope.append(note)
        analysis.information_gaps = [note]
        analysis.excluded_information_gaps = [note]
        analysis.user_questions = ["복원 절차를 추가로 확인해 주세요."]

    result = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)

    assert cp1_check(result, "CP1-012").status == CheckStatus.FAIL, result.model_dump()
    assert result.handoff_status == HandoffStatus.BLOCKED


@pytest.mark.parametrize("gap_field", ["information_gaps", "excluded_information_gaps"])
def test_structural_cp1_rejects_procedure_and_gap_role_overlap(gap_field):
    # Unmarked input isolates the list conflict from the mandatory marker rule.
    note = "마무리할 때 처음 기록한 상태와 대조합니다."
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    analysis.procedure_notes = [note]
    setattr(analysis, gap_field, [note])

    result = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)

    assert cp1_check(result, "CP1-012").status == CheckStatus.FAIL, result.model_dump()
    assert result.handoff_status == HandoffStatus.BLOCKED


def test_structural_cp1_explicit_scope_exclusion_precedes_procedure_marker():
    from qa_pipeline_agent1 import _acceptance_delivery_contract

    note = "[복원] 외부 장비를 원래 상태로 되돌립니다."
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    request.out_of_scope.append(note)
    analysis.excluded_scope.append(note)

    delivery = _acceptance_delivery_contract(request, legacy_wording_checks=False)
    assert delivery[-1]["destination"] == "excluded_scope"
    result = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert result.status == CheckStatus.PASS, result.model_dump()
    assert cp1_check(result, "CP1-012").status == CheckStatus.PASS

    analysis.procedure_notes = [note]
    duplicate = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert cp1_check(duplicate, "CP1-012").status == CheckStatus.FAIL
    assert duplicate.handoff_status == HandoffStatus.BLOCKED


def test_legacy_cp1_keeps_marker_routing_without_new_procedure_notes_field():
    note = "[복원] 원래 상태로 되돌립니다."
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    assert analysis.procedure_notes == []

    legacy = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=True)
    assert legacy.status == CheckStatus.PASS, legacy.model_dump()
    assert not any(check.rule_id == "CP1-012" for check in legacy.checks)

    current = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert cp1_check(current, "CP1-012").status == CheckStatus.FAIL
    assert current.handoff_status == HandoffStatus.BLOCKED


@pytest.mark.parametrize("wording", ["시험이 끝나면 원래 상태로 되돌립니다.",
                                    "마무리할 때 처음 기록한 상태와 대조합니다.",
                                    "Restore the captured state after the scenario."])
def test_new_wording_policy_routes_declared_procedures_without_verb_guessing(wording):
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(wording)
    before = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert any(c.rule_id == "CP1-008" and c.status == CheckStatus.FAIL for c in before.checks)
    analysis.procedure_notes = [wording]
    after = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert after.status == CheckStatus.PASS, after.model_dump()
    analysis.procedure_notes = ["입력에 없는 절차"]
    invalid = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert any(c.rule_id == "CP1-012" and c.status == CheckStatus.FAIL for c in invalid.checks)


@pytest.mark.parametrize("mutation", ["none", "id", "source", "number", "after", "missing_note"])
def test_new_wording_policy_preserves_cp1_integrity(mutation):
    request, analysis = cp1_request(), cp1_valid_analysis()
    if mutation == "id":
        analysis.request_id = "OTHER"
    elif mutation == "source":
        analysis.confirmed_conditions[0].source_text = "없는 출처"
    elif mutation == "number":
        analysis.confirmed_conditions[0].statement += " 999도"
    elif mutation == "after":
        analysis.after_condition = "다른 변경값"
    elif mutation == "missing_note":
        request.acceptance_notes.append("새로운 필수 인수 조건")
    result = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert (result.status == CheckStatus.PASS) == (mutation == "none"), result.model_dump()


def test_new_wording_policy_does_not_claim_boundary_sentence_semantics():
    request, analysis = cp1_request(), cp1_valid_analysis()
    source = "온도 30°C 이상 요청은 차단합니다."
    request.acceptance_notes.append(source)
    analysis.confirmed_conditions.append(ConfirmedCondition(condition_id="COND-099",
        statement="온도 30°C 초과 요청은 차단합니다.", source_type="CHANGE_REQUEST",
        source_text=source, requirement_ids=[request.target_requirement_id], change_role=ConditionChangeRole.CHANGED))
    old = evaluate_checkpoint1(request, analysis, cp1_requirements())
    new = evaluate_checkpoint1(request, analysis, cp1_requirements(), legacy_wording_checks=False)
    assert any(c.rule_id == "CP1-007" and c.status == CheckStatus.FAIL for c in old.checks)
    assert not any(c.rule_id == "CP1-007" and c.status == CheckStatus.FAIL for c in new.checks)
    # Deliberate limitation: equal numbers do not prove equal boundary semantics.


@pytest.mark.parametrize("subject", ["온도", "속도", "용량", "압력"])
@pytest.mark.parametrize("wording", ["허용 범위 밖 입력은 차단합니다.", "허용 범위를 벗어나는 입력은 차단합니다.", "상한 초과 입력은 차단합니다."])
def test_product_boundaries_are_not_test_exclusions(subject, wording):
    from qa_pipeline_agent1 import _acceptance_delivery_contract, _is_scope_exclusion_text
    note = subject + " " + wording
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    assert not _is_scope_exclusion_text(note)
    assert _acceptance_delivery_contract(request)[-1]["destination"] == "confirmed_conditions.source_text"
    # Still mandatory: removing the real boundary condition is not a workaround.
    assert cp1_check(evaluate_checkpoint1(request, analysis, cp1_requirements()), "CP1-008").status == CheckStatus.FAIL
    analysis.confirmed_conditions.append(ConfirmedCondition(condition_id="COND-090", statement=note,
        source_text=note, source_type="CHANGE_REQUEST", requirement_ids=[request.target_requirement_id]))
    assert evaluate_checkpoint1(request, analysis, cp1_requirements()).status == CheckStatus.PASS


@pytest.mark.parametrize("note", ["알림 검사는 제외한다.", "통신 검증은 이번 시험 범위 밖입니다.",
    "다중 장비 제어는 범위에 포함하지 않습니다.", "풍량 검증은 변경 범위에서 제외합니다.", "외부 통신"])
def test_explicit_exclusions_remain_binding_without_product_keyword_guessing(note):
    from qa_pipeline_agent1 import _acceptance_delivery_contract
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    request.out_of_scope.append(note)
    analysis.excluded_scope.append(note)
    assert _acceptance_delivery_contract(request)[-1]["destination"] == "excluded_scope"
    assert evaluate_checkpoint1(request, analysis, cp1_requirements()).status == CheckStatus.PASS
    analysis.confirmed_conditions.append(ConfirmedCondition(condition_id="COND-090", statement=note,
        source_text=note, source_type="CHANGE_REQUEST", requirement_ids=[request.target_requirement_id]))
    assert cp1_check(evaluate_checkpoint1(request, analysis, cp1_requirements()), "CP1-009").status == CheckStatus.FAIL


@pytest.mark.parametrize("note", ["[시험 절차 메모] 시험이 끝나면 원래 상태로 복원하고 확인합니다.",
    "[복원] 모든 검사가 끝났을 때 처음의 값으로 복원합니다.",
    "[복원] 모든 검사가 끝났을 때 처음의 값으로 되돌립니다.",
    "[준비] 시작할 장비를 지정합니다.", "[시험 절차 메모] 진행에 앞서 대상 장비를 지정합니다."])
def test_explicit_procedure_markers_do_not_depend_on_time_wording(note):
    from qa_pipeline_agent1 import _acceptance_delivery_contract
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    assert _acceptance_delivery_contract(request)[-1]["destination"].startswith("request.acceptance_notes")
    assert evaluate_checkpoint1(request, analysis, cp1_requirements()).status == CheckStatus.PASS
    analysis.confirmed_conditions.append(ConfirmedCondition(condition_id="COND-090", statement=note,
        source_text=note, source_type="CHANGE_REQUEST", requirement_ids=[request.target_requirement_id]))
    assert cp1_check(evaluate_checkpoint1(request, analysis, cp1_requirements()), "CP1-007").status == CheckStatus.FAIL


def test_explicit_procedure_role_does_not_guess_from_body_words():
    from qa_pipeline_agent1 import _is_test_setup_note, _is_test_restore_note
    assert _is_test_restore_note("[복원] 최초 설정으로 되돌립니다.")
    assert not _is_test_setup_note("[복원] 최초 설정으로 되돌립니다.")
    assert _is_test_setup_note("[준비] 복원 버튼이 있는 화면을 엽니다.")
    assert not _is_test_restore_note("[준비] 복원 버튼이 있는 화면을 엽니다.")


@pytest.mark.parametrize("subject,unit,value", [("온도", "°C", 30), ("속도", "rpm", 1200), ("중량", "kg", 5)])
@pytest.mark.parametrize("before,after", [("이상", "초과"), ("초과", "이상"), ("이하", "미만"), ("미만", "이하")])
def test_same_frame_boundary_relation_changes_are_rejected(subject, unit, value, before, after):
    request, analysis = cp1_request(), cp1_valid_analysis()
    source = f"{subject} {value}{unit} {before} 요청은 차단합니다."
    statement = source.replace(before, after)
    request.acceptance_notes.append(source)
    condition = ConfirmedCondition(condition_id="COND-090", statement=statement,
        source_text=source, source_type="CHANGE_REQUEST", requirement_ids=[request.target_requirement_id])
    analysis.confirmed_conditions.append(condition)
    assert cp1_check(evaluate_checkpoint1(request, analysis, cp1_requirements()), "CP1-007").status == CheckStatus.FAIL
    assert evaluate_checkpoint1(request, analysis, cp1_requirements(), require_input_contract=False).status == CheckStatus.PASS
    condition.statement = source.replace(f"{value}{unit}", f"{value}.0 {unit}")
    assert evaluate_checkpoint1(request, analysis, cp1_requirements()).status == CheckStatus.PASS


@pytest.mark.parametrize("source,statement", [
    ("온도 30°C 이상에서 차단합니다.", "속도 30rpm 초과에서 차단합니다."),
    ("온도 30°C 이상이면 차단합니다.", "온도가 30°C를 넘으면 차단합니다."),
])
def test_relation_checker_does_not_claim_general_paraphrase_or_target_matching(source, statement):
    from qa_pipeline_agent1 import _explicit_relation_conflict
    # False is only 'no supported same-frame comparison', never proof of equivalence.
    assert not _explicit_relation_conflict(source, statement)


@pytest.mark.parametrize("source,changed", [
    ("31°C 입력 후 30°C를 유지합니다.", "30°C 입력 후 31°C를 유지합니다."),
    ("속도 1200rpm 입력 후 1000rpm을 유지합니다.", "속도 1000rpm 입력 후 1200rpm을 유지합니다."),
    ("용량 8kg 입력 후 5kg을 유지합니다.", "용량 5kg 입력 후 8kg을 유지합니다."),
])
def test_ordered_input_output_values_are_not_a_bag_of_numbers(source, changed):
    from qa_pipeline_agent1 import _meaning_conflicts
    assert _meaning_conflicts(source, changed)
    assert not _meaning_conflicts(source, source)
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(source)
    analysis.confirmed_conditions.append(ConfirmedCondition(condition_id="COND-090", statement=changed,
        source_text=source, source_type="CHANGE_REQUEST", requirement_ids=[request.target_requirement_id]))
    assert cp1_check(evaluate_checkpoint1(request, analysis, cp1_requirements()), "CP1-007").status == CheckStatus.FAIL


@pytest.mark.parametrize("mutation", ["none", "missing", "wrong_requirement", "changed_role", "altered_quote", "after_policy"])
def test_srs_maintenance_range_requires_same_target_verbatim_background_authority(mutation):
    request, analysis, requirements = cp1_request(), cp1_valid_analysis(), cp1_requirements()
    request.description = "기존 16~30°C 허용 범위는 유지하고 상한 차단 결과를 명확히 합니다."
    request.after_value = "범위 밖 입력은 기존 설정값을 유지합니다."
    analysis.after_condition = request.after_value
    analysis.confirmed_conditions = analysis.confirmed_conditions[:3]
    maintenance = analysis.confirmed_conditions[-1]
    maintenance.statement = maintenance.source_text = requirements[request.target_requirement_id].statement
    maintenance.change_role = ConditionChangeRole.UNCHANGED
    if mutation == "missing":
        analysis.confirmed_conditions.pop()
    elif mutation == "wrong_requirement":
        maintenance.requirement_ids = ["REQ-STATE-001"]
    elif mutation == "changed_role":
        maintenance.change_role = ConditionChangeRole.CHANGED
    elif mutation == "altered_quote":
        maintenance.statement += " 알림도 표시합니다."
    elif mutation == "after_policy":
        request.after_value = analysis.after_condition = "AUTO 모드는 16~30°C입니다."
    result = evaluate_checkpoint1(request, analysis, requirements)
    assert (cp1_check(result, "CP1-008").status == CheckStatus.PASS) == (mutation == "none")
    if mutation == "none":
        assert result.status == CheckStatus.PASS
        assert cp1_check(evaluate_checkpoint1(request, analysis, requirements, require_input_contract=False), "CP1-008").status == CheckStatus.FAIL


@pytest.mark.parametrize("note,destination", [
    ("온라인 단일 장비를 대상으로 합니다.", "confirmed_conditions.source_text"),
    ("중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다.", "confirmed_conditions.source_text"),
    ("설정 온도는 18~30°C 범위여야 합니다.", "confirmed_conditions.source_text"),
    ("운전 모드를 COOL로 표시합니다.", "confirmed_conditions.source_text"),
    ("풍량 변경 시 내부 fanSpeed를 MED로 표시합니다.", "confirmed_conditions.source_text"),
    ("조회 후 설정 상태를 유지합니다.", "confirmed_conditions.source_text"),
    ("알림의 목표 색상은 미정입니다.", "information_gaps"),
    ("다중 장비 제어는 범위에 포함하지 않습니다.", "excluded_scope"),
    ("시험 전에 대상 장비를 선택한다.", "request.acceptance_notes"),
    ("시험 후 원래 상태로 복원한다.", "request.acceptance_notes"),
])
def test_acceptance_routing_is_shared_by_initial_repair_and_checkpoint(note, destination):
    from qa_pipeline_agent1 import _acceptance_delivery_contract
    request, analysis = cp1_request(), cp1_valid_analysis()
    request.acceptance_notes.append(note)
    original = request.model_dump_json()
    row = _acceptance_delivery_contract(request)[-1]
    assert row["source_text"] == note and row["destination"].startswith(destination)
    responses = Agent1FakeResponses()
    agent = OpenAIAgent1(client=SimpleNamespace(responses=responses))
    for extra in ({}, {"previous_analysis": analysis, "checkpoint_feedback": ["조건 누락"]}):
        agent.analyze(request, cp1_requirements(), **extra)
        assert json.dumps(_acceptance_delivery_contract(request, legacy_wording_checks=False), ensure_ascii=False) in responses.kwargs["input"][1]["content"]
    cp = evaluate_checkpoint1(request, analysis, cp1_requirements())
    needs_source = destination in {"confirmed_conditions.source_text", "information_gaps"}
    assert (cp1_check(cp, "CP1-008").status == CheckStatus.FAIL) == needs_source
    assert request.model_dump_json() == original


@pytest.mark.parametrize("requirement_id", ["REQ-NOTIFY-001", "REQ-STATE-001"])
def test_request_trace_only_keeps_requested_words_without_full_srs_scope(requirement_id):
    from qa_pipeline_contracts import ScopeBasis
    request, analysis, requirements = cp1_scope_case(direct=True, requirement_id=requirement_id)
    condition = analysis.confirmed_conditions[-1]
    request.acceptance_notes[-1] = "화면에 변경한 설정값을 표시합니다."
    condition.statement = condition.source_text = request.acceptance_notes[-1]
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == requirement_id)
    effect.scope_evidence.basis = ScopeBasis.REQUEST_TRACE_ONLY
    result = evaluate_checkpoint1(request, analysis, requirements)
    assert cp1_check(result, "CP1-011").status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert evaluate_checkpoint1(request, analysis, requirements,
                               allow_request_trace=False).handoff_status == HandoffStatus.BLOCKED


@pytest.mark.parametrize("mutation", ["new_words", "srs_condition", "extra_condition",
                                     "update", "missing_link", "invented_srs", "exclusion"])
def test_request_trace_only_cannot_authorize_new_conditions(mutation):
    from qa_pipeline_contracts import ScopeBasis
    request, analysis, requirements = cp1_scope_case(direct=True)
    condition = analysis.confirmed_conditions[-1]
    effect = next(e for e in analysis.requirement_effects if e.requirement_id == "REQ-NOTIFY-001")
    effect.scope_evidence.basis = ScopeBasis.REQUEST_TRACE_ONLY
    if mutation == "new_words":
        condition.statement += " 경고 색상도 표시합니다."
    elif mutation == "srs_condition":
        condition.source_type = ConditionSource.SRS
    elif mutation == "extra_condition":
        extra = condition.model_copy(deep=True)
        extra.condition_id = "COND-007"
        analysis.confirmed_conditions.append(extra)
    elif mutation == "update":
        effect.relation = RequirementRelation.UPDATE_REQUIRED
    elif mutation == "missing_link":
        condition.requirement_ids = [request.target_requirement_id]
    elif mutation == "invented_srs":
        effect.scope_evidence.srs_source_text = "없는 문장"
    else:
        request.acceptance_notes[-1] = "알림 검사는 제외한다."
        condition.source_text = condition.statement = request.acceptance_notes[-1]
    result = evaluate_checkpoint1(request, analysis, requirements)
    assert cp1_check(result, "CP1-011").status == CheckStatus.FAIL
    assert result.handoff_status == HandoffStatus.BLOCKED


@pytest.mark.parametrize("requirement_id", ["REQ-NOTIFY-001", "REQ-STATE-001"])
def test_scope_direct_request_passes_but_unrequested_dependency_pauses(requirement_id):
    for direct in (True, False):
        request, analysis, requirements = cp1_scope_case(
            direct=direct, requirement_id=requirement_id,
        )
        result = evaluate_checkpoint1(request, analysis, requirements)
        assert cp1_check(result, "CP1-011").status == (
            CheckStatus.PASS if direct else CheckStatus.REVIEW
        )
        assert result.handoff_status == (
            HandoffStatus.CONTINUE if direct else HandoffStatus.PAUSE
        )
        # An unresolved scope decision cannot escape via PARTIAL_PROCEED.
        if not direct:
            analysis.decision = AnalysisDecision.PARTIAL_PROCEED
            analysis.excluded_scope = analysis.information_gaps = ["적용 범위 미정"]
            analysis.excluded_information_gaps = ["적용 범위 미정"]
            result = evaluate_checkpoint1(request, analysis, requirements)
            assert result.handoff_status == HandoffStatus.PAUSE


@pytest.mark.parametrize("mutation", [
    "missing", "srs_condition", "unknown_condition", "duplicate_condition",
    "invented_srs", "wrong_requirement", "excluded_request", "before_only",
    "procedure_only",
])
def test_scope_rejects_unfounded_evidence(mutation):
    request, analysis, requirements = cp1_scope_case(direct=True)
    effect = next(item for item in analysis.requirement_effects
                  if item.requirement_id == "REQ-NOTIFY-001")
    if mutation == "missing":
        effect.scope_evidence = None
    elif mutation == "srs_condition":
        analysis.confirmed_conditions[-1].source_type = ConditionSource.SRS
    elif mutation == "unknown_condition":
        effect.scope_evidence.request_condition_ids = ["COND-999"]
    elif mutation == "duplicate_condition":
        effect.scope_evidence.request_condition_ids *= 2
    elif mutation == "invented_srs":
        effect.scope_evidence.srs_source_text = "새로 만들어 낸 알림 규칙"
    elif mutation == "wrong_requirement":
        effect.scope_evidence.request_condition_ids = ["COND-001"]
    else:
        condition = analysis.confirmed_conditions[-1]
        request.acceptance_notes.pop()
        if mutation == "before_only":
            request.before_value = condition.source_text
        else:
            note = ("알림 검사는 범위에 포함하지 않는다." if mutation == "excluded_request"
                    else "시험 종료 후 대상 장비를 복원한다.")
            request.acceptance_notes.append(note)
            condition.source_text = condition.statement = note
    result = evaluate_checkpoint1(request, analysis, requirements)
    assert cp1_check(result, "CP1-011").status == CheckStatus.FAIL
    assert result.handoff_status == HandoffStatus.BLOCKED


def test_scope_does_not_accept_relabelled_dependency_or_shared_word_as_direct():
    from qa_pipeline_contracts import ScopeBasis

    request, analysis, requirements = cp1_scope_case()
    effect = next(item for item in analysis.requirement_effects
                  if item.requirement_id == "REQ-NOTIFY-001")
    effect.scope_evidence.basis = ScopeBasis.DIRECT_REQUEST
    # Merely linking a real request condition to another Requirement is not proof.
    analysis.confirmed_conditions[1].requirement_ids.append("REQ-NOTIFY-001")
    effect.scope_evidence.srs_source_text = "표시"
    result = evaluate_checkpoint1(request, analysis, requirements)
    assert cp1_check(result, "CP1-011").status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.PAUSE


def test_scope_explicit_requirement_reference_and_update_are_supported():
    request, analysis, requirements = cp1_scope_case(direct=True)
    effect = next(item for item in analysis.requirement_effects
                  if item.requirement_id == "REQ-NOTIFY-001")
    note = "REQ-NOTIFY-001의 처리 결과 안내 문구를 변경합니다."
    request.acceptance_notes[-1] = note
    analysis.confirmed_conditions[-1].source_text = note
    analysis.confirmed_conditions[-1].statement = note
    effect.relation = RequirementRelation.UPDATE_REQUIRED
    result = evaluate_checkpoint1(request, analysis, requirements)
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert cp1_check(result, "CP1-011").status == CheckStatus.PASS


def test_scope_guard_is_versioned_not_retroactive():
    request, analysis, requirements = cp1_scope_case()
    for item in analysis.requirement_effects:
        item.scope_evidence = None
    assert evaluate_checkpoint1(request, analysis, requirements).handoff_status == HandoffStatus.BLOCKED
    historical = evaluate_checkpoint1(request, analysis, requirements, require_scope_guard=False)
    assert historical.handoff_status == HandoffStatus.CONTINUE
    assert len(historical.checks) == 10


@pytest.mark.parametrize("mutation", ["reverse", "number", "role", "requirement"])
def test_cp1_rejects_explicit_meaning_and_source_errors(mutation):
    analysis = cp1_valid_analysis()
    if mutation == "reverse":
        analysis.confirmed_conditions[1].statement = "AUTO 모드에서 18°C 미만 요청은 허용한다."
    elif mutation == "number":
        analysis.confirmed_conditions[0].statement = "AUTO 모드에서 99°C는 허용한다."
    elif mutation == "role":
        analysis.confirmed_conditions[0].change_role = ConditionChangeRole.UNCHANGED
    else:
        analysis.confirmed_conditions[2].requirement_ids.append("REQ-CONTROL-001")
        analysis.requirement_effects[1].relation = RequirementRelation.VERIFY
    assert evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements()).status == CheckStatus.FAIL
    assert evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements(), require_meaning_guard=False, require_scope_guard=False).status == CheckStatus.PASS


def test_source_quote_respects_code_and_number_boundaries():
    assert not pipeline._contains_fact("NONE", "ON")
    assert not pipeline._contains_fact("130°C", "30°C")
    assert pipeline._contains_fact("모드는 ON이다.", "ON")
    assert pipeline._contains_fact("설정 온도는 30°C다.", "30°C")


def test_loads_product_requirements_from_markdown() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert len(requirements) >= 20
    assert requirements["REQ-TEMP-001"].statement == "섭씨 설정 범위는 16~30°C여야 합니다."
    assert "범위 밖 요청" in requirements["REQ-TEMP-001"].acceptance_criteria
    assert set(requirements["REQ-TEMP-001"].related_requirement_ids) == {
        "REQ-CONTROL-001",
        "REQ-NOTIFY-001",
        "REQ-STATE-001",
    }
    assert not any(item.startswith("REQ-LOCAL-") for item in requirements)
    assert "Toast" in requirements["REQ-NOTIFY-001"].acceptance_criteria
    assert "currentTemp" in requirements["REQ-MONITOR-001"].acceptance_criteria

def test_rendered_context_contains_ids_and_acceptance_criteria() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    context = render_srs_context(requirements)

    assert "REQ-LOCK-001" in context
    assert "차단 안내가 표시됩니다" in context
    assert "관련 요구사항: REQ-CONTROL-001" in context

def test_product_srs_excludes_test_harness_requirements() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert "REQ-REGISTER-001" not in requirements
    assert "REQ-RESET-001" not in requirements

def test_agent1_uses_structured_responses_api() -> None:
    responses = Agent1FakeResponses()
    fake_client = SimpleNamespace(responses=responses)
    agent = OpenAIAgent1(model="gpt-5.6-terra", client=fake_client)
    request = ChangeRequest(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_value="16~30°C",
        after_value="18~30°C",
        description="AUTO 모드의 설정 범위는 18~30°C입니다.",
        acceptance_notes=["AUTO 모드의 설정 범위는 18~30°C입니다."],
    )
    requirements = {
        "REQ-TEMP-001": SrsRequirement(
            requirement_id="REQ-TEMP-001",
            statement="섭씨 설정 범위는 16~30°C여야 합니다.",
            acceptance_criteria="범위 밖 요청이 차단됩니다.",
        )
    }

    result = agent.analyze(request, requirements)

    assert result.response_id == "resp_test"
    assert result.usage["total_tokens"] == 150
    assert responses.kwargs["text_format"] is Agent1Analysis
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent1-2-17"
    assert responses.kwargs["store"] is False
    instructions = responses.kwargs["input"][0]["content"]
    assert "현재 SRS는 변경 전 제품 상태" in instructions
    assert "변경 후 정책의 권한 있는 입력" in instructions
    assert "acceptance_notes는 제공된 인수 조건 전달 목록" in instructions
    assert "Agent 2가 TC의 판정 기준" in instructions
    assert "VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT" in instructions
    assert "연관 항목을 조용히 생략하지 않습니다" in instructions
    assert "자동화 구현 지원 여부를 이유로" in instructions
    assert "TC 구성·기존 TC 선택·자동화 가능 여부" in instructions
    assert "MODIFIED, UPDATE_REQUIRED 또는 VERIFY로 분류한 모든 Requirement" in instructions
    assert "검증 조건 원문을 찾지 못하면" in instructions
    assert "테스트 절차나 Playwright 코드는 작성하지 않습니다" in instructions

def test_agent1_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent1Error, match="OPENAI_API_KEY"):
        OpenAIAgent1()

def test_valid_analysis_passes_checkpoint1() -> None:
    result = evaluate_checkpoint1(cp1_request(), cp1_valid_analysis(), cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 11
    assert all(item.status == CheckStatus.PASS for item in result.checks)

def test_missing_change_request_range_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "confirmed_conditions": [
                item
                for item in cp1_valid_analysis().confirmed_conditions
                if item.condition_id != "COND-005"
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-008").status == CheckStatus.FAIL
    assert "18~30°C" in cp1_check(result, "CP1-008").message

def test_unknown_requirement_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "requirement_effects": [
                *cp1_valid_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-FAKE-999",
                    relation=RequirementRelation.VERIFY,
                    reason="존재하지 않는 기능",
                ),
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL

def test_missing_related_requirement_review_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "requirement_effects": [
                item
                for item in cp1_valid_analysis().requirement_effects
                if item.requirement_id != "REQ-STATE-001"
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL

def test_condition_requirement_missing_from_effects_is_rejected() -> None:
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement="화면과 내부 상태가 일치한다.",
            source_type=ConditionSource.SRS,
            source_text="status·mode·currentTemp·setTemp·fanSpeed·locked 등 검증 대상 공통 값이 같습니다.",
            requirement_ids=["REQ-STATE-001"],
        ),
    ]
    effects = [
        item
        for item in cp1_valid_analysis().requirement_effects
        if item.requirement_id != "REQ-STATE-001"
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL

def test_unverified_before_value_requires_review() -> None:
    changed_request = cp1_request().model_copy(update={"before_value": "17~30°C"})
    analysis = cp1_valid_analysis().model_copy(
        update={"before_condition": "현재 섭씨 설정 범위는 17~30°C다."}
    )

    result = evaluate_checkpoint1(changed_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert result.final_review_notes == [
        "변경 전 값이 대상 SRS 행에서 직접 확인되지 않습니다."
    ]
    assert cp1_check(result, "CP1-004").status == CheckStatus.REVIEW

def test_ungrounded_confirmed_condition_is_rejected() -> None:
    conditions = list(cp1_valid_analysis().confirmed_conditions)
    conditions[0] = conditions[0].model_copy(
        update={"source_text": "요청과 SRS에 없는 자동 복원 정책"}
    )
    analysis = cp1_valid_analysis().model_copy(update={"confirmed_conditions": conditions})

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-007").status == CheckStatus.FAIL

def test_missing_acceptance_note_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": cp1_valid_analysis().confirmed_conditions[:1]}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-008").status == CheckStatus.FAIL
    assert cp1_request().acceptance_notes[-1] in cp1_check(result, "CP1-008").message

def test_checkpoint1_does_not_require_setup_or_restore_as_product_conditions() -> None:
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
    analysis = cp1_valid_analysis().model_copy(
        update={
            "excluded_scope": [
                *cp1_valid_analysis().excluded_scope,
                setup_note,
                restore_note,
            ]
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS

def test_missing_requested_out_of_scope_is_rejected() -> None:
    scoped_request = cp1_request().model_copy(update={"out_of_scope": ["화씨 표시 정책"]})
    analysis = cp1_valid_analysis().model_copy(update={"excluded_scope": []})

    result = evaluate_checkpoint1(scoped_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL

def test_scope_limited_acceptance_note_is_only_excluded() -> None:
    scope_note = "온도 표시값 변경은 이번 변경 범위에 포함하지 않는다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [*cp1_request().acceptance_notes, scope_note],
            "out_of_scope": [scope_note],
        }
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "excluded_scope": [*cp1_valid_analysis().excluded_scope, scope_note]
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS
    assert cp1_check(result, "CP1-009").status == CheckStatus.PASS

def test_scope_limited_acceptance_note_cannot_be_confirmed_condition() -> None:
    scope_note = "온도 표시값 변경은 이번 변경 범위에 포함하지 않는다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [*cp1_request().acceptance_notes, scope_note],
            "out_of_scope": [scope_note],
        }
    )
    scope_condition = ConfirmedCondition(
        condition_id="COND-004",
        statement=scope_note,
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=scope_note,
        requirement_ids=["REQ-TEMP-001"],
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *cp1_valid_analysis().confirmed_conditions,
                scope_condition,
            ],
            "excluded_scope": [*cp1_valid_analysis().excluded_scope, scope_note],
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL
    assert "제외 조건" in cp1_check(result, "CP1-009").message

def test_redundant_reconfirmation_requires_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["변경 정책을 다시 확인해야 함"],
            "user_questions": [
                "AUTO 모드의 설정 범위를 18~30°C로 변경하는 것으로 확정할 수 있습니까?"
            ],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert cp1_check(result, "CP1-010").status == CheckStatus.REVIEW

def test_legitimate_missing_detail_question_passes_checkpoint() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["기존 저장 데이터의 적용 시점이 요청에 없음"],
            "user_questions": ["기존에 저장된 장비에도 즉시 소급 적용합니까?"],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.PAUSE
    assert cp1_check(result, "CP1-010").status == CheckStatus.PASS

def test_partial_proceed_continues_confirmed_scope_and_preserves_exclusions() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": ["기존 저장값의 소급 적용"],
            "information_gaps": ["기존 저장값의 적용 시점이 정의되지 않음"],
            "excluded_information_gaps": ["기존 저장값의 적용 시점이 정의되지 않음"],
            "user_questions": ["기존 저장값에도 즉시 소급 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE

def test_partial_proceed_without_excluded_scope_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": [],
            "information_gaps": ["적용 시점이 정의되지 않음"],
            "excluded_information_gaps": ["적용 시점이 정의되지 않음"],
            "user_questions": ["언제 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert result.handoff_status == HandoffStatus.BLOCKED
    assert cp1_check(result, "CP1-010").status == CheckStatus.FAIL

    mismatched = analysis.model_copy(
        update={
            "excluded_scope": ["적용 시점"],
            "excluded_information_gaps": [],
        }
    )
    mismatched_result = evaluate_checkpoint1(
        cp1_request(), mismatched, cp1_requirements()
    )
    assert cp1_check(mismatched_result, "CP1-010").status == CheckStatus.FAIL

def test_partial_unresolved_acceptance_is_handed_off_as_gap_not_condition():
    note = "적용 완료 알림의 색상을 변경해야 하지만 목표 색상은 미정입니다."
    request = cp1_request().model_copy(update={"acceptance_notes": [*cp1_request().acceptance_notes, note]})
    analysis = cp1_valid_analysis().model_copy(update={
        "decision": AnalysisDecision.PARTIAL_PROCEED,
        "excluded_scope": [note], "information_gaps": [note],
        "excluded_information_gaps": [note], "user_questions": ["목표 색상은 무엇입니까?"],
    })
    result = evaluate_checkpoint1(request, analysis, cp1_requirements())
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS
    for field in ("excluded_scope", "information_gaps", "excluded_information_gaps"):
        broken = analysis.model_copy(update={field: []})
        assert cp1_check(evaluate_checkpoint1(request, broken, cp1_requirements()), "CP1-008").status == CheckStatus.FAIL
    clear = "적용 완료 알림은 파란색으로 표시되어야 합니다."
    clear_request = request.model_copy(update={"acceptance_notes": [*cp1_request().acceptance_notes, clear]})
    excluded_clear = analysis.model_copy(update={
        "excluded_scope": [clear], "information_gaps": [clear], "excluded_information_gaps": [clear],
    })
    assert cp1_check(evaluate_checkpoint1(clear_request, excluded_clear, cp1_requirements()), "CP1-008").status == CheckStatus.FAIL

def test_blocked_decision_blocks_agent2_handoff() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"decision": AnalysisDecision.BLOCKED}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.BLOCKED

def test_related_update_without_scope_evidence_is_rejected() -> None:
    requirements = cp1_requirements()
    related = requirements["REQ-NOTIFY-001"]
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement=related.statement,
            source_type=ConditionSource.SRS,
            source_text=related.statement,
            requirement_ids=["REQ-NOTIFY-001"],
        ),
    ]
    effects = [
        item.model_copy(update={"relation": RequirementRelation.UPDATE_REQUIRED})
        if item.requirement_id == "REQ-NOTIFY-001"
        else item
        for item in cp1_valid_analysis().requirement_effects
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, requirements)

    assert cp1_check(result, "CP1-006").status == CheckStatus.PASS
    assert cp1_check(result, "CP1-011").status == CheckStatus.FAIL
    assert result.handoff_status == HandoffStatus.BLOCKED

def test_proceed_with_open_question_is_recorded_for_final_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["경계값 적용 시점이 불명확함"],
            "user_questions": ["기존 저장값에도 즉시 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert result.final_review_notes == [
        "정보 부족 또는 질문이 있는데 PROCEED로 판정했습니다."
    ]
    assert cp1_check(result, "CP1-010").status == CheckStatus.REVIEW
