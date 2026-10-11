"""Prepared local counterexamples; not evidence of new AI generation/review success."""
from pipeline_test_support import *
import qa_pipeline_agent3 as a3
import qa_pipeline_grounding as grounding
import re
from test_agent3 import mapped_controller_observation


def mode_buttons_case(initial, requested):
    case, _ = mapped_tc_fixture("mode", initial, requested, prepare={"setTemp": 26})
    for index, direction in enumerate(("increase", "decrease"), 3):
        rid = f"ER-{index:03}"
        enabled = requested not in {"DRY", "FAN"}
        case.expected_results.append(case.expected_results[0].model_copy(deep=True, update={
            "result_id": rid, "statement": f"온도 {direction} 버튼의 활성 상태는 {str(enabled).lower()}이다.",
            "observation_target": f"온도 {direction} 버튼"}))
        case.execution_spec.verifications.append(pipeline.TcVerification(result_id=rid,
            target=f"temperature.{direction}", observation_layer="UI", strategy="UI_ENABLED_EQUALS",
            expected_value=enabled, after_action_id=case.execution_spec.verifications[0].after_action_id))
        source = f"온도 {direction} 버튼의 활성 상태를 준비 전 관찰값과 비교한다."
        case.restoration.confirmations.append(pipeline.RestoreConfirmation(source_text=source,
            result_ids=[rid], comparisons=[pipeline.RestoreComparison(result_id=rid,
                source_excerpt=source, basis="OBSERVED_BASELINE")]))
    case.restore_steps = case.restoration.operation_steps + [c.source_text for c in case.restoration.confirmations]
    return case


@pytest.mark.parametrize("initial,requested", [("COOL", "DRY"), ("HEAT", "FAN"), ("DRY", "COOL"), ("FAN", "HEAT")])
def test_mapped_mode_buttons_execute_and_restore(initial, requested, mapped_controller_observation,
        tmp_path, monkeypatch, capsys):
    case = mode_buttons_case(initial, requested)
    before = case.model_dump_json()
    plan = a3.ControllerMapAgent3().plan(case, mapped_controller_observation, {}).plan
    cp = a3.evaluate_checkpoint3_plan(case, plan, mapped_controller_observation, execution_interface=True)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)
    enabled_checks = [a for a in plan.assertions if a.strategy.value == "UI_ENABLED_EQUALS"]
    assert {a.selector for a in enabled_checks} == {"#det-temp-up-btn", "#det-temp-down-btn"}
    monkeypatch.setenv("QA_TARGET_URL", (REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(compile_automation_candidate("LOCAL-MODE-BUTTONS", case, plan,
        explicit_expectations_only=True, typed_values=True), "mode_buttons", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output
    assert "PRODUCT_MISMATCH" not in output
    assert "RESTORE_CONFIRMATION" in output
    assert case.model_dump_json() == before


@pytest.mark.parametrize("fault", ["display_as_input", "wrong_device", "missing_button", "duplicate_button", "missing_check", "wrong_value_type"])
def test_mode_reader_connection_still_rejects_invalid_targets(fault, mapped_controller_observation):
    case = mode_buttons_case("COOL", "DRY")
    obs = mapped_controller_observation.model_copy(deep=True)
    check = case.execution_spec.verifications[-1]
    if fault == "display_as_input":
        check.target = "temperature.display"
    elif fault == "wrong_device":
        case.execution_spec.operations[0].value = 2
    elif fault == "missing_button":
        obs.elements = [e for e in obs.elements if e.selector != "#det-temp-down-btn"]
    elif fault == "duplicate_button":
        next(e for e in obs.elements if e.selector == "#det-temp-down-btn").match_count = 2
    elif fault == "missing_check":
        case.execution_spec.verifications.pop()
    else:
        check.expected_value = "false"
    if fault in {"missing_check", "wrong_value_type"}:
        with pytest.raises(a3.Agent3Error, match="실행 정의"):
            a3.resolve_controller_bindings(case, obs)
        return
    binding = a3.resolve_controller_bindings(case, obs)
    assert binding.planning_status.value == "AUTOMATION_SUPPORT_EXTENSION_REQUIRED"
    assert not binding.verifications


@pytest.mark.parametrize("direction", ["increase", "decrease"])
def test_each_button_mismatch_is_detected_and_still_restored(direction, mapped_controller_observation,
        tmp_path, monkeypatch, capsys):
    case = mode_buttons_case("COOL", "DRY")
    check = next(c for c in case.execution_spec.verifications if c.target == f"temperature.{direction}")
    check.expected_value = True  # Deliberately wrong product expectation in a separate fixture.
    er = next(r for r in case.expected_results if r.result_id == check.result_id)
    er.statement = f"온도 {direction} 버튼의 활성 상태는 true이다."
    plan = a3.ControllerMapAgent3().plan(case, mapped_controller_observation, {}).plan
    monkeypatch.setenv("QA_TARGET_URL", (REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(compile_automation_candidate("LOCAL-BUTTON-MISMATCH", case, plan,
        explicit_expectations_only=True, typed_values=True), "button_mismatch", "exec"), namespace)
    with pytest.raises(AssertionError):
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output
    assert check.result_id in output


def test_existing_ui_reader_really_maps_labels_not_internal_values():
    # Exercise the exact helper emitted to candidates. Internal state is deliberately inconsistent.
    namespace = {"re": re, "_CONTROLLER_BUTTONS": a3._CONTROLLER_BUTTONS}
    exec(a3._CONTROLLER_RESTORE_HELPERS, namespace)
    ui = {"card_classes": ["state-stop", "mode-heat"],
          "card_values": ["난방", "중풍", "27°C"], "card_locked": False}
    class Page:
        def evaluate(self, *args):
            return {"state": {"fanSpeed": "HIGH"}, "ui": ui}
    case, plan = controller_lifecycle_fixture("fanSpeed", "LOW", "MED")
    facts = a3._controller_ui_decoding_facts(plan.assertions[0])
    assert facts["source"] == "DOM"
    reader = namespace["_controller_ui_fields"]
    for label, value in facts["fan_labels"].items():
        ui["card_values"][1] = f"  {label}  "
        assert reader(Page(), 1)["fanSpeed"] == value
    for label in ("중풍 오류", "UNKNOWN", "", "HIGH"):
        ui["card_values"][1] = label
        assert reader(Page(), 1)["fanSpeed"] is None
    for label, value in facts["mode_labels"].items():
        ui["card_values"][0] = label
        ui["card_classes"] = ["state-stop", "mode-" + value.lower()]
        assert reader(Page(), 1)["mode"] == value
    for css, value in facts["status_classes"].items():
        ui["card_classes"] = [css, "mode-heat"]
        assert reader(Page(), 1)["status"] == value
    for css_locked in (True, False):
        for visible_locked in (True, False):
            ui["card_classes"] = ["mode-heat", "state-stop"] + (["locked"] if css_locked else [])
            ui["card_locked"] = visible_locked
            assert reader(Page(), 1)["locked"] is (css_locked and visible_locked)
    for text, expected in (("27°C", 27.0), ("---", None), ("", None)):
        ui["card_values"][2] = text
        assert reader(Page(), 1)["setTemp"] == expected
    ui["card_values"][0] = "냉방"  # Label and class must agree.
    assert reader(Page(), 1)["mode"] is None
    ui["card_classes"].append("state-run")
    assert reader(Page(), 1)["status"] is None
    panel_assertion = plan.assertions[0].model_copy(update={"selector": ".detail-panel"})
    panel_facts = a3._controller_ui_decoding_facts(panel_assertion)
    ui["temperature"] = "26°C"
    for field, buttons in a3._CONTROLLER_BUTTONS.items():
        ui[field] = {selector: False for selector in buttons.values()}
    for field, choices in panel_facts["selected_buttons"].items():
        assert reader(Page(), 1, "panel")[field] is None
        for choice in choices:
            ui[field] = {selector: selector == choice["selector"] for selector in ui[field]}
            actual = reader(Page(), 1, "panel")[field]
            assert actual == choice["value"] and type(actual) is type(choice["value"])
        ui[field] = {selector: True for selector in ui[field]}
        assert reader(Page(), 1, "panel")[field] is None
    assert reader(Page(), 1, "panel")["setTemp"] == 26.0
    ui["temperature"] = "---"
    assert reader(Page(), 1, "panel")["setTemp"] is None


@pytest.mark.parametrize("field,initial,target", [("status", "OPERATION", "STOP"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "LOW", "MED"), ("setTemp", 24, 26), ("locked", False, True)])
def test_interface_explanation_preserves_old_inputs_and_review_responsibility(field, initial, target):
    case, plan = controller_lifecycle_fixture(field, initial, target)
    options = dict(test_case=case, observation=generic_control_guard_fixture()[2],
        include_review_responsibilities=True, include_task_boundaries="1.3", explicit_expectations_only=True)
    old = grounding.build_grounding_input("AGENT3", None, {}, plan, execution_interface=True, **options)
    new = grounding.build_grounding_input("AGENT3", None, {}, plan, execution_interface="1.1", **options)
    assert old == grounding.build_grounding_input("AGENT3", None, {}, plan, execution_interface="1.0", **options)
    assert old["items"] == new["items"]
    assert old["artifact_sha256"] == new["artifact_sha256"]
    assert new["context"]["execution_interface"]["trial_success_proved"] is False
    assert all("ui_decoding" not in r for r in old["context"]["execution_interface"]["readers"])
    interface = new["context"]["execution_interface"]
    assert any("ui_decoding_ref" in r for r in interface["readers"])
    assert all(r["ui_decoding_ref"] in interface["ui_decoders"] for r in interface["readers"] if "ui_decoding_ref" in r)
    with pytest.raises(ValueError, match="해시"):
        grounding.check_review_record(new, fake_grounding_record(old))
    for verdict, status in (("SUPPORTED", "PASS"), ("UNSUPPORTED", "FAIL"), ("UNCERTAIN", "REVIEW")):
        record = fake_grounding_record(new)
        record["review"]["items"][0]["verdict"] = verdict
        assert grounding.check_review_record(new, record).status.value == status
