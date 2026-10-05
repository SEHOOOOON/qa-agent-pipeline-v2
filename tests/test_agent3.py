"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


@pytest.mark.parametrize("tag,role,input_type,expected", [
    ("button", None, None, "CLICK"),
    ("div", "button", None, "CLICK"),
    ("input", None, "submit", "CLICK"),
    ("input", None, "number", "FILL"),
    ("textarea", None, None, "FILL"),
    ("select", None, None, "SELECT_OPTION"),
    ("input", None, "checkbox", "CHECK_OR_UNCHECK"),
    ("div", "switch", None, "CHECK_OR_UNCHECK"),
    ("span", None, None, "READ_STATE"),
    ("input", None, "hidden", "READ_STATE"),
    ("input", None, "file", "READ_STATE"),
    ("input", None, "radio", "READ_STATE"),
])
def test_observed_action_capability(tag, role, input_type, expected):
    from qa_pipeline_agent3 import _observed_action_hint
    assert _observed_action_hint(tag, role, input_type) == expected


@pytest.mark.parametrize("tag,input_type,expected", [
    ("div", None, "CLICK"), ("span", None, "CLICK"),
    ("input", "number", "FILL"), ("input", "checkbox", "CHECK_OR_UNCHECK"),
    ("input", "hidden", "READ_STATE"), ("input", "file", "READ_STATE"),
    ("input", "radio", "READ_STATE"), ("select", None, "SELECT_OPTION"),
])
def test_observed_direct_handler_preserves_specialized_controls(tag, input_type, expected):
    from qa_pipeline_agent3 import _observed_action_hint
    assert _observed_action_hint(tag, None, input_type, has_click_handler=True) == expected


@pytest.mark.parametrize("generic", [False, True])
@pytest.mark.parametrize("handler", ["inline", "property", "none", "delegated"])
def test_observed_card_and_generic_direct_handler(tmp_path, generic, handler):
    target = tmp_path / "handlers.html"
    inline = ' onclick="window.HANDLER_BODY_MUST_STAY_LOCAL=1"' if handler == "inline" else ""
    script = {
        "property": "el.onclick = () => { window.HANDLER_BODY_MUST_STAY_LOCAL=1; };",
        "delegated": "document.addEventListener('click', () => {});",
    }.get(handler, "")
    target.write_text(f'''<!doctype html><title>Handler observation</title>
        <div id="device-card-1"><div class="card-body-split"{inline}>장비 선택</div></div>
        <span id="other"{inline}>동작 영역</span>
        <div id="read-only" tabindex="0" style="cursor:pointer">클릭이라는 설명만 있음</div>
        <script>for (const el of document.querySelectorAll('.card-body-split,#other')) {{ {script} }}</script>
        ''', encoding="utf-8")
    obs = inspect_target_ui(target, required_selectors={"#device-card-1 .card-body-split"},
                            required_harness_keys=set(), discover_generic=generic)
    items = {item.selector: item for item in obs.elements}
    expected = "CLICK" if handler in {"inline", "property"} else "READ_STATE"
    assert items["#device-card-1 .card-body-split"].action_hint == expected
    if generic:
        assert items["#other"].action_hint == expected
        assert items["#read-only"].action_hint == "READ_STATE"
    assert "HANDLER_BODY_MUST_STAY_LOCAL" not in obs.model_dump_json()


@pytest.mark.parametrize("generic", [False, True])
def test_observed_action_capability_known_and_generic(tmp_path, generic):
    target = tmp_path / "capabilities.html"
    target.write_text("""<!doctype html><title>Controls</title>
        <button id="det-temp-up-btn">온도 올림 / Request higher</button>
        <input id="det-temp-display" type="number" value="24">
        <span id="det-temp-limit-text">16~30</span>
        <button id="other">다른 버튼</button>""", encoding="utf-8")
    obs = inspect_target_ui(target, required_selectors={
        "#det-temp-up-btn", "#det-temp-display", "#det-temp-limit-text"
    }, required_harness_keys=set(), discover_generic=generic)
    items = {item.selector: item for item in obs.elements}
    assert items["#det-temp-up-btn"].action_hint == "CLICK"
    assert items["#det-temp-display"].action_hint == "FILL"
    assert items["#det-temp-limit-text"].action_hint == "READ_STATE"
    if generic:
        assert items["#other"].action_hint == "CLICK"


@pytest.fixture
def panel_readback_browser():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        yield browser
        browser.close()


@pytest.mark.parametrize("mutation", ["valid", "read_only", "input", "hidden", "disabled", "duplicate", "missing"])
def test_observed_click_capability_preserves_cp3_guards(mutation):
    from qa_pipeline_agent3 import _observed_action_hint
    case, plan, obs = generic_control_guard_fixture()
    action = plan.actions[0]
    action.action_type = AutomationActionType.CLICK
    element = obs.elements[-1]
    element.tag = "button"
    element.action_hint = _observed_action_hint("button", None, None)
    if mutation == "read_only":
        element.action_hint = _observed_action_hint("span", None, None)
    elif mutation == "input":
        element.action_hint = _observed_action_hint("input", None, "number")
    elif mutation == "hidden":
        element.visible = False
    elif mutation == "disabled":
        element.enabled = False
    elif mutation == "duplicate":
        element.match_count = 2
    elif mutation == "missing":
        obs.elements.pop()
    # Only test this operation's CP3-002; other fixture checks are unrelated.
    plan.actions = [action]
    result = pipeline.evaluate_checkpoint3_plan(case, plan, obs, legacy_wording_checks=False)
    check = next(item for item in result.checks if item.rule_id == "CP3-002")
    assert check.status == (CheckStatus.PASS if mutation == "valid" else CheckStatus.FAIL)


@pytest.fixture
def panel_readback_page(panel_readback_browser):
    context = panel_readback_browser.new_context()
    context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('file:', 'data:')) else route.abort())
    page = context.new_page()
    page.goto((REPO_ROOT / 'product_baseline/virtual-controller.html').as_uri())
    page.wait_for_function('!!window.__vccs')
    # Fixture preparation only; all tested selections/apply use actual product controls.
    page.evaluate('''() => {
      for (const d of devices) Object.assign(d, {status:'STOP',mode:'COOL',setTemp:24,
          fanSpeed:'LOW',locked:false,errorCode:null,purify:false});
      isGatewayOnline=true; currentUserRole='ADMIN'; renderGrid(); selectUnit(1);
    }''')
    yield page
    context.close()


@pytest.mark.parametrize('reason', ['normal', 'error', 'viewer', 'offline', 'locked'])
@pytest.mark.parametrize('field,value', [('status','OPERATION'),('mode','HEAT'),
    ('fanSpeed','HIGH'),('setTemp',22)])
def test_panel_apply_readback_preserves_pending_until_apply(reason, field, value, panel_readback_page):
    page = panel_readback_page
    if reason in {'error','locked'}:
        page.evaluate('''reason => { const d=devices.find(d=>d.id===1);
          if(reason==='locked') d.locked=true;
          else {d.status='ERROR'; d.errorCode='CH05';} renderGrid(); selectUnit(1); }''', reason)
    namespace = {'re': __import__('re'), '_CONTROLLER_BUTTONS': pipeline._CONTROLLER_BUTTONS}
    exec(pipeline._CONTROLLER_RESTORE_HELPERS, namespace)
    original = page.evaluate('() => structuredClone(devices)')
    if field == 'setTemp':
        page.locator('#det-temp-down-btn').click(click_count=2)
    else:
        page.locator(pipeline._CONTROLLER_BUTTONS[field][value]).click()
    assert namespace['_controller_ui_fields'](page,1,'panel')[field] == value
    assert page.evaluate('() => devices') == original
    if reason == 'viewer': page.evaluate("currentUserRole='VIEWER'")
    if reason == 'offline': page.evaluate('isGatewayOnline=false')
    page.locator('.btn-apply-cmd').click()
    expected = value if reason == 'normal' else original[0][field]
    if field == 'status' and expected == 'ERROR':
        # ERROR is shown in panel information, not as an OPERATION/STOP selection.
        assert 'ERROR' in page.locator('#det-unit-info').inner_text()
        assert page.locator('#det-power-on-btn.active, #det-power-off-btn.active').count() == 0
        assert page.evaluate('pendingState.status') == 'ERROR'
        assert page.locator('#device-card-1.state-error').count() == 1
    else:
        assert namespace['_controller_ui_fields'](page,1,'panel')[field] == expected
        assert namespace['_controller_ui_fields'](page,1,'card')[field] == expected
    assert page.evaluate('(field) => devices.find(d=>d.id===1)[field]',field) == expected
    if reason != 'normal':
        assert page.evaluate('() => devices') == original
        assert '차단' in page.locator('#global-toast').inner_text() or reason in {'viewer','offline'}
    else:
        assert page.evaluate('() => devices.slice(1)') == original[1:]
    if reason == 'offline':
        assert page.locator('#det-control-section').evaluate("e=>e.style.pointerEvents") == 'none'


@pytest.mark.parametrize('reason', ['normal','error','viewer','offline'])
def test_panel_apply_readback_lock_field(reason, panel_readback_page):
    page = panel_readback_page
    if reason == 'error': page.evaluate("devices[0].status='ERROR'; devices[0].errorCode='CH05'; renderGrid(); selectUnit(1)")
    page.locator('#det-lock-on-btn').click()
    assert page.locator('#det-lock-on-btn').evaluate("e=>e.classList.contains('active')")
    assert page.evaluate('devices[0].locked') is False
    if reason == 'viewer': page.evaluate("currentUserRole='VIEWER'")
    if reason == 'offline': page.evaluate('isGatewayOnline=false')
    page.locator('.btn-apply-cmd').click()
    expected = reason == 'normal'
    assert page.evaluate('devices[0].locked') is expected
    assert page.locator('#det-lock-on-btn').evaluate("e=>e.classList.contains('active')") is expected
    assert page.evaluate('window.__vccs.pendingState.locked') is expected


def test_panel_apply_readback_unlock_does_not_apply_other_pending_values(panel_readback_page):
    page = panel_readback_page
    page.evaluate('devices[0].locked=true; renderGrid(); selectUnit(1)')
    page.locator('#det-temp-down-btn').click(click_count=2)
    page.locator('#det-lock-off-btn').click()
    page.locator('.btn-apply-cmd').click()
    assert page.evaluate('devices[0].locked') is False
    assert page.evaluate('devices[0].setTemp') == 24
    assert '24.0' in page.locator('#det-temp-display').inner_text()
    # A later, separate application remains allowed after unlocking.
    page.locator('#det-temp-down-btn').click(click_count=2)
    page.locator('.btn-apply-cmd').click()
    assert page.evaluate('devices[0].setTemp') == 22


@pytest.mark.parametrize('blocked,active', [(False,1),(False,2),(True,1),(True,2)])
def test_panel_apply_readback_multi_does_not_overwrite_other_devices(blocked, active, panel_readback_page):
    page = panel_readback_page
    page.evaluate('''({blocked,active}) => { devices[0].locked=blocked; devices[1].setTemp=26;
      document.getElementById('chk-multi-select').checked=true;
      selectedUnitIds=[]; selectedUnitId=null; selectUnit(active===1?2:1); selectUnit(active); }''',dict(blocked=blocked,active=active))
    non_targets=page.evaluate('() => structuredClone(devices.slice(2))')
    if blocked:
        # Explicitly keep lock ON: last-selected unlocked device must not turn this
        # into the separate, permitted unlock-only branch.
        page.locator('#det-lock-on-btn').click()
    page.locator('#det-fan-high').click()
    page.locator('.btn-apply-cmd').click()
    assert page.evaluate('devices[0].fanSpeed') == ('LOW' if blocked else 'HIGH')
    assert page.evaluate('devices[1].fanSpeed') == 'HIGH'
    if blocked:
        assert page.evaluate('devices[0].locked') is True
    assert page.evaluate('window.__vccs.pendingState.fanSpeed') == ('LOW' if blocked and active==1 else 'HIGH')
    assert page.evaluate('selectedUnitId') == active
    assert set(page.evaluate('selectedUnitIds')) == {1,2}
    assert page.evaluate('devices.slice(2)') == non_targets
    assert '표시 기준:' in page.locator('#det-unit-info').inner_text()


def test_panel_apply_readback_no_selection_is_safe(panel_readback_page):
    page=panel_readback_page
    page.evaluate("document.getElementById('chk-multi-select').checked=true; selectUnit(1)")
    before=page.evaluate('() => structuredClone(devices)')
    page.evaluate('applyPanelCommands()')
    assert page.evaluate('pendingState') == {}
    assert page.evaluate('devices') == before
    assert page.locator('#det-control-section').evaluate('e=>e.style.pointerEvents') == 'none'


@pytest.fixture(scope="module")
def mapped_controller_observation():
    return inspect_target_ui(REPO_ROOT / "product_baseline/virtual-controller.html",
                             required_selectors=set(pipeline._UI_SELECTOR_INVENTORY),
                             discover_generic=False)


def test_controller_device_select_hint_reaches_semantic_review(mapped_controller_observation):
    import qa_pipeline_grounding as g
    from qa_pipeline_agent3 import ControllerMapAgent3
    case, _ = mapped_tc_fixture("status", "OPERATION", "STOP")
    obs = mapped_controller_observation
    plan = ControllerMapAgent3().plan(case, obs, {}).plan
    selector = next(a.selector for a in plan.actions if a.action_type.value == "SELECT_DEVICE")
    index = next(i for i, e in enumerate(obs.elements) if e.selector == selector)
    assert obs.elements[index].tag == "div" and obs.elements[index].action_hint == "CLICK"
    review = g.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=obs,
        include_execution_contract=True, include_review_responsibilities=True, include_task_boundaries="1.3")
    docs = {d["source_id"]: d["text"] for d in review["source_documents"]}
    assert docs[f"UI_INVENTORY/elements/{index}/selector"] == selector
    assert docs[f"UI_INVENTORY/elements/{index}/action_hint"] == "CLICK"


@pytest.mark.parametrize("effect", ["correct", "wrong_device", "no_effect"])
def test_compiled_device_selection_checks_effect_not_just_handler(effect, panel_readback_browser):
    from playwright.sync_api import TimeoutError as BrowserTimeout
    case, plan = mapped_tc_fixture("status", "OPERATION", "STOP")
    code = compile_automation_candidate("SELECT-GUARD", case, plan, explicit_expectations_only=True)
    lines = code.splitlines()
    click = next(i for i, line in enumerate(lines) if "page.locator('#device-card-1 .card-body-split').click()" in line)
    block = "\n".join(line.strip() for line in lines[click:click + 2])
    assert "window.__vccs.selectedUnitId === 1" in block
    context = panel_readback_browser.new_context()
    try:
        page = context.new_page()
        page.set_default_timeout(300)
        selected = {"correct": "1", "wrong_device": "2", "no_effect": "null"}[effect]
        page.set_content(f'''<div id="device-card-1"><div class="card-body-split"
            onclick="window.__vccs.selectedUnitId={selected}">선택</div></div>
            <script>window.__vccs={{selectedUnitId:null}}</script>''')
        if effect == "correct":
            exec(block, {"page": page})
        else:
            with pytest.raises(BrowserTimeout):
                exec(block, {"page": page})
    finally:
        context.close()


def test_controller_map_collects_all_declared_internal_values(mapped_controller_observation):
    from qa_pipeline_agent3 import controller_connection_catalog
    observation = mapped_controller_observation
    internal = {path for kind, path in controller_connection_catalog()["preconditions"].values()
                if kind == "INTERNAL_VALUE"}
    assert set(observation.harness_values) == internal | {"window.__vccs.devices[0].id"}
    assert observation.harness_values["window.__vccs.devices[0].id"] == 1
    assert type(observation.harness_values["window.__vccs.devices[0].locked"]) is bool
    assert observation.generic_discovery is False


@pytest.mark.parametrize("variant", ["missing", "object", "wrong_device", "reordered", "future_field"])
def test_controller_map_collection_preserves_actual_identity_and_missing_values(variant, tmp_path, monkeypatch):
    import qa_pipeline_agent3 as agent3
    device = {"id": 1, "mode": "COOL", "setTemp": 24, "status": "STOP", "locked": False,
              "fanSpeed": "LOW", "errorCode": None, "privateNote": "do-not-collect"}
    if variant == "missing":
        del device["fanSpeed"]
    elif variant == "object":
        device["fanSpeed"] = {"invalid": True}
    elif variant == "wrong_device":
        device["id"] = 2
    elif variant == "future_field":
        device["probe"] = 0
        catalog = agent3.controller_connection_catalog()
        catalog["preconditions"]["internal.probe"] = ("INTERNAL_VALUE", "window.__vccs.devices[0].probe")
        monkeypatch.setattr(agent3, "controller_connection_catalog", lambda: catalog)
    devices = [device]
    if variant == "reordered":
        devices.insert(0, {**device, "id": 2, "fanSpeed": "HIGH"})
    target = tmp_path / "observed.html"
    target.write_text("<html><head><title>Observation fixture</title></head><body><button class='btn-apply-cmd'>Apply</button><script>window.__vccs=" + json.dumps({"devices": devices}) +
                      ";</script></body></html>", encoding="utf-8")
    observation = inspect_target_ui(target, required_selectors={".btn-apply-cmd"}, required_harness_keys={"devices"})
    values = observation.harness_values
    assert not any("privateNote" in key for key in values)
    if variant == "wrong_device":
        assert values == {}
    elif variant == "reordered":
        assert values["window.__vccs.devices[1].id"] == 1
        assert values["window.__vccs.devices[1].fanSpeed"] == "LOW"
        assert not any("[0]" in key for key in values)
    elif variant == "future_field":
        assert values["window.__vccs.devices[0].probe"] == 0
    else:
        assert "window.__vccs.devices[0].fanSpeed" not in values
        assert values["window.__vccs.devices[0].locked"] is False


@pytest.mark.parametrize("field,initial,target", [("status", "STOP", "OPERATION"),
    ("mode", "COOL", "HEAT"), ("fanSpeed", "HIGH", "LOW"), ("setTemp", 27, 21), ("locked", False, True)])
def test_controller_map_five_controls_execute_without_binding_model(field, initial, target,
        mapped_controller_observation, tmp_path, monkeypatch, capsys):
    from qa_pipeline_agent3 import ControllerMapAgent3, evaluate_agent3_eligibility
    case, reference = mapped_tc_fixture(field, initial, target)
    eligibility = evaluate_agent3_eligibility(case)
    observation = mapped_controller_observation.model_copy(deep=True)
    observation.elements = [e for e in observation.elements if e.selector in eligibility.required_selectors]
    before = case.model_dump_json()
    response = ControllerMapAgent3().plan(case, observation, {})
    plan = response.plan
    assert response.usage["total_tokens"] == 0 and response.response_id is None
    assert [(a.action_type, a.selector, a.value) for a in plan.actions] == [(a.action_type, a.selector, a.value) for a in reference.actions]
    cp = evaluate_checkpoint3_plan(case, plan, observation)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)
    monkeypatch.setenv("QA_TARGET_URL", (REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(compile_automation_candidate("MAP-LOCAL", case, plan, explicit_expectations_only=True), "mapped", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output and "PRODUCT_MISMATCH" not in output
    assert case.model_dump_json() == before


@pytest.mark.parametrize("value,allowed", [(None, True), (1, True), (2, False),
    (True, False), (False, False), ("1", False), (1.0, False)])
def test_controller_map_device_value_contract(value, allowed, mapped_controller_observation):
    from qa_pipeline_agent3 import ControllerMapAgent3, _controller_device_selection_valid
    case, _ = mapped_tc_fixture("fanSpeed", "AUTO", "HIGH")
    next(o for o in case.execution_spec.operations if o.action_type.value == "SELECT_DEVICE").value = value
    assert _controller_device_selection_valid(value, 1, implicit=True) is allowed
    response = ControllerMapAgent3().plan(case, mapped_controller_observation, {})
    if allowed:
        assert response.plan.planning_status.value == "READY"
        cp = evaluate_checkpoint3_plan(case, response.plan, mapped_controller_observation)
        assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)
        assert not _controller_device_selection_valid(None, 1, implicit=False)
    else:
        assert response.plan.planning_status.value == "AUTOMATION_SUPPORT_EXTENSION_REQUIRED"


@pytest.mark.parametrize("missing", ["#det-temp-display", "#det-temp-limit-text", "#det-lock-off-btn"])
def test_controller_map_restore_inspection_matches_validation(missing, mapped_controller_observation):
    from qa_pipeline_agent3 import ControllerMapAgent3, evaluate_agent3_eligibility, _CONTROLLER_RESTORE_SELECTORS
    case, _ = mapped_tc_fixture("fanSpeed", "AUTO", "HIGH")
    eligibility = evaluate_agent3_eligibility(case)
    assert _CONTROLLER_RESTORE_SELECTORS.issubset(eligibility.required_selectors)
    plan = ControllerMapAgent3().plan(case, mapped_controller_observation, {}).plan
    observation = mapped_controller_observation.model_copy(deep=True)
    observation.elements = [e for e in observation.elements if e.selector != missing]
    cp = evaluate_checkpoint3_plan(case, plan, observation)
    assert cp.status == CheckStatus.FAIL


@pytest.mark.parametrize("mutation", ["unknown", "missing_ui", "duplicate_ui", "wrong_device", "wrong_field", "wrong_mode"])
def test_controller_map_never_guesses_missing_or_incompatible_binding(mutation, controller_observation):
    from qa_pipeline_agent3 import ControllerMapAgent3
    case, _ = mapped_tc_fixture("mode", "COOL", "HEAT")
    observation = controller_observation.model_copy(deep=True)
    if mutation == "unknown":
        case.execution_spec.operations[0].target = "unsupported.automatic_switch"
    elif mutation == "missing_ui":
        observation.elements = [e for e in observation.elements if e.selector != "#det-mode-heat"]
    elif mutation == "duplicate_ui":
        next(e for e in observation.elements if e.selector == "#det-mode-heat").match_count = 2
    elif mutation == "wrong_device":
        observation.harness_values["window.__vccs.devices[0].id"] = 2
    elif mutation == "wrong_field":
        case.execution_spec.verifications[0].target = "card.fanSpeed"
    else:
        next(op for op in case.execution_spec.operations if op.target == "mode.heat").value = "COOL"
    response = ControllerMapAgent3().plan(case, observation, {})
    assert response.plan.planning_status == pipeline.Agent3PlanningStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
    assert not response.plan.actions and not response.plan.assertions


@pytest.mark.parametrize("mutation", ["panel", "device", "field", "operation"])
def test_controller_map_rejects_wrong_locations_even_if_values_match(mutation, controller_observation):
    from qa_pipeline_agent3 import ControllerMapAgent3
    case, _ = mapped_tc_fixture()
    plan = ControllerMapAgent3().plan(case, controller_observation, {}).plan
    if mutation == "panel":
        plan.assertions[0].selector = ".detail-panel"
    elif mutation == "device":
        plan.target_device_id = 2
    elif mutation == "field":
        plan.precondition_checks[0].selector = "window.__vccs.devices[0].status"
    else:
        plan.actions[0].selector = "#device-card-2 .card-body-split"
    assert evaluate_checkpoint3_plan(case, plan, controller_observation).status == CheckStatus.FAIL
    with pytest.raises(pipeline.Agent3Error, match="인계"):
        compile_automation_candidate("MAP-MUTANT", case, plan)


def test_controller_map_saved_bindings_recomputed(controller_observation, tmp_path):
    from qa_pipeline_agent3 import ControllerMapAgent3
    case, _ = mapped_tc_fixture()
    response = ControllerMapAgent3().plan(case, controller_observation, {})
    plan, record = pipeline_execution._prepare_agent3_plan(tmp_path, 1, response.plan, controller_observation,
                                                          case, response.ui_bindings)
    manifest = {"prompt_version": "agent3-3.43", "binding_contract": "controller-map-1.0", "plan_value_formats": [record]}
    pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, plan, case)
    manifest.pop("binding_contract")
    with pytest.raises(ValueError, match="연결 방식"):
        pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, plan, case)


def test_controller_map_real_entry_uses_no_binding_model(controller_observation, tmp_path, monkeypatch):
    case, _ = mapped_tc_fixture()
    run_id = "RUN-20260928-120000-ABCDEF"
    run = tmp_path / run_id
    pipeline._write_json(run / "agent2_manifest.json", {"run_id": run_id})
    monkeypatch.setattr(pipeline_execution, "_load_verified_agent2_run", lambda *_: (
        None, {}, None, SimpleNamespace(test_cases=[case]), None, {"agent2_design_sha256": "a" * 64}))
    monkeypatch.setattr(pipeline_execution, "inspect_target_ui", lambda *a, **kw: controller_observation)
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent3", lambda **kw: pytest.fail("Binding model must not be constructed"))
    monkeypatch.setattr(pipeline_execution, "run_candidate_trial", lambda *a, **kw: _trial(TrialOutcome.PASS))
    assert pipeline.run_agent3(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path), tc_id=case.tc_id,
        target_html=str(REPO_ROOT / "product_baseline/virtual-controller.html"), model="fixture", timeout=60)) == 0
    manifest = pipeline._read_json_payload(run / "agent3_manifest.json")
    assert manifest["binding_contract"] == "controller-map-1.0"
    assert manifest["model"] == "local-controller-map-1.0"
    assert len(manifest["attempts"]) == 1 and manifest["attempts"][0]["usage"]["total_tokens"] == 0

@pytest.mark.parametrize("expected", [None, 30, 31])
def test_controller_map_read_only_and_boundary_keep_tc_verdict(expected, controller_observation,
        tmp_path, monkeypatch, capsys):
    from qa_pipeline_agent3 import ControllerMapAgent3
    if expected is None:
        initial = controller_observation.harness_values["window.__vccs.devices[0].setTemp"]
        case, _ = mapped_tc_fixture("setTemp", initial, initial, read_only=True)
    else:
        case, _ = mapped_tc_fixture("setTemp", 24, 31, blocked=True, blocked_by_lock=False)
        for er, check in zip(case.expected_results, case.execution_spec.verifications):
            er.statement = f"{er.observation_target} 값은 {expected}이다."
            check.expected_fields[0].expected_value = expected
    plan = ControllerMapAgent3().plan(case, controller_observation, {}).plan
    assert evaluate_checkpoint3_plan(case, plan, controller_observation).status == CheckStatus.PASS
    monkeypatch.setenv("QA_TARGET_URL", (REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    code = compile_automation_candidate("MAP-BOUNDARY", case, plan, explicit_expectations_only=True)
    exec(code, namespace)
    if expected == 31:
        # Deliberately incorrect oracle: the adapter must not silently change it to 30.
        with pytest.raises(AssertionError, match="PRODUCT_MISMATCH"):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert ("RESTORE_STATUS: NOT_REQUIRED" if expected is None else "RESTORE_STATUS: RESTORED") in output
    if expected is None:
        assert "_restore_controller(page, 1," not in code
    else:
        assert plan.assertions[0].expected_fields[0].expected_value == expected


@pytest.mark.parametrize("field,initial,requested", [
    ("status", "STOP", "OPERATION"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "HIGH", "LOW"), ("setTemp", 27, 21), ("locked", False, True)])
def test_frozen_tc_bindings_preserve_definition_and_local_execution(
        field, initial, requested, controller_observation, tmp_path, monkeypatch, capsys):
    from qa_pipeline_agent3 import assemble_tc_bindings, tc_plan_handoff_errors
    case, reference = controller_lifecycle_fixture(field, initial, requested,
        prepare={"mode": "HEAT"} if field == "setTemp" else None)
    case, bindings = frozen_tc_and_bindings(case, reference)
    before = case.model_dump_json()
    plan = assemble_tc_bindings(case, bindings)
    assert not tc_plan_handoff_errors(case, plan)
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)
    target = REPO_ROOT / "product_baseline/virtual-controller.html"
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    code = compile_automation_candidate("LOCAL-TC-HANDOFF", case, plan, explicit_expectations_only=True)
    namespace = {}
    exec(compile(code, "tc_handoff", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output and "RESTORE_CONFIRMATIONS_VERIFIED:" in output
    assert "PRODUCT_MISMATCH" not in output and "RESTORE_MISMATCH" not in output
    assert case.model_dump_json() == before


@pytest.mark.parametrize("mutation", ["value", "input", "order", "missing", "timing", "precondition", "restore"])
def test_frozen_tc_rejects_changed_definitions_before_compile(mutation, controller_observation):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("setTemp", 27, 21)
    case, bindings = frozen_tc_and_bindings(case, reference)
    plan = assemble_tc_bindings(case, bindings)
    if mutation == "value":
        plan.assertions[0].expected_fields[0].expected_value = 27
    elif mutation == "input":
        next(a for a in plan.actions if a.phase == AutomationPhase.TEST).value = 25
    elif mutation == "order":
        plan.actions[0], plan.actions[1] = plan.actions[1], plan.actions[0]
    elif mutation == "missing":
        plan.assertions.pop()
    elif mutation == "timing":
        plan.assertions[0].after_action_id = plan.actions[-1].action_id
    elif mutation == "precondition":
        plan.precondition_checks.clear()
    else:
        plan.restore_confirmations.clear()
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation)
    assert cp.status == CheckStatus.FAIL and cp.checks[0].rule_id == "CP3-014"
    with pytest.raises(pipeline.Agent3Error, match="인계"):
        compile_automation_candidate("LOCAL-MUTANT", case, plan)


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "unknown", "precondition"])
def test_frozen_tc_binding_reference_errors_never_assemble(mutation):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    case, bindings = frozen_tc_and_bindings(case, reference)
    if mutation == "missing":
        bindings.verifications.pop()
    elif mutation == "duplicate":
        bindings.operations.append(bindings.operations[0])
    elif mutation == "unknown":
        bindings.verifications[0].result_id = "ER-999"
    else:
        bindings.preconditions[0].verification_index = 99
    with pytest.raises(pipeline.Agent3Error, match="누락·중복"):
        assemble_tc_bindings(case, bindings)


def test_frozen_tc_binding_order_is_not_test_order():
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("setTemp", 27, 21, prepare={"mode": "HEAT"})
    case, bindings = frozen_tc_and_bindings(case, reference)
    expected = assemble_tc_bindings(case, bindings)
    bindings.operations.reverse()
    bindings.verifications.reverse()
    bindings.preconditions.reverse()
    assert assemble_tc_bindings(case, bindings) == expected


@pytest.mark.parametrize("field,initial,target,variant", [
    ("mode", "COOL", "HEAT", "heat."), ("mode", "COOL", "HEAT", "난방"),
    ("fanSpeed", "HIGH", "LOW", "low."), ("status", "STOP", "OPERATION", "operation."),
    ("locked", True, False, "해제")])
def test_frozen_tc_keeps_bounded_value_format_conversion(field, initial, target, variant, tmp_path, controller_observation):
    from qa_pipeline_agent3 import assemble_tc_bindings, tc_plan_handoff_errors
    case, reference = controller_lifecycle_fixture(field, initial, target)
    case, bindings = frozen_tc_and_bindings(case, reference)
    for check in case.execution_spec.verifications:
        check.expected_fields[0].expected_value = variant
    if field == "mode":
        next(op for op in case.execution_spec.operations if op.phase == AutomationPhase.TEST).value = variant
    raw = assemble_tc_bindings(case, bindings)
    before = case.model_dump_json()
    plan, record = pipeline_execution._prepare_agent3_plan(tmp_path, 1, raw, controller_observation, case, bindings)
    assert plan.assertions[0].expected_fields[0].expected_value == target
    assert not tc_plan_handoff_errors(case, plan)
    assert pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation).status == CheckStatus.PASS
    pipeline_execution._verify_agent3_plan_value_formats(tmp_path,
        {"prompt_version": "agent3-3.43", "plan_value_formats": [record]}, controller_observation, plan, case)
    assert case.model_dump_json() == before
    plan.assertions[0].expected_fields[0].expected_value = initial
    assert tc_plan_handoff_errors(case, plan)  # format equivalence is not value replacement


def test_frozen_tc_model_returns_locations_only_and_missing_ui_stays_review(controller_observation):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("fanSpeed", "HIGH", "LOW")
    case, bindings = frozen_tc_and_bindings(case, reference)
    class Responses:
        def parse(self, **kwargs):
            self.kwargs = kwargs
            return SimpleNamespace(output_parsed=bindings, id="local-binding", usage=None)
    responses = Responses()
    result = OpenAIAgent3(client=SimpleNamespace(responses=responses)).plan(case, controller_observation, {})
    assert responses.kwargs["text_format"] is pipeline.Agent3UiBindings
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent3-3-43"
    assert result.plan.actions == reference.actions
    assert result.plan.assertions == reference.assertions
    schema = json.dumps(pipeline.Agent3UiBindings.model_json_schema())
    for forbidden in ("expected_value", "expected_number", "after_action_id", "action_type"):
        assert forbidden not in schema
    bindings.operations[0].selector = "#missing-control"
    invalid = assemble_tc_bindings(case, bindings)
    assert pipeline.evaluate_checkpoint3_plan(case, invalid, controller_observation).status == CheckStatus.FAIL
    extension = pipeline.Agent3UiBindings(planning_status="AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
        operations=[], verifications=[], preconditions=[], extension_reasons=["필요한 독립 제어가 관찰되지 않음"], technical_notes=[])
    plan = assemble_tc_bindings(case, extension)
    assert pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation).status == CheckStatus.REVIEW
    assert not plan.actions and not plan.assertions


@pytest.mark.parametrize("expected,mismatch", [(30, False), (24, True), (31, True)])
def test_frozen_tc_boundary_input_is_not_expected_output(expected, mismatch, controller_observation,
        tmp_path, monkeypatch, capsys):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("setTemp", 24, 31, blocked=True, blocked_by_lock=False)
    for er, a in zip(case.expected_results, reference.assertions):
        er.statement = f"{er.observation_target} 값은 {expected}이다."
        a.expected_fields[0].expected_value = expected
    case, bindings = frozen_tc_and_bindings(case, reference)
    plan = assemble_tc_bindings(case, bindings)
    assert pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation).status == CheckStatus.PASS
    monkeypatch.setenv("QA_TARGET_URL", (REPO_ROOT / "product_baseline/virtual-controller.html").as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile_automation_candidate("LOCAL-FROZEN-BOUNDARY", case, plan, explicit_expectations_only=True), namespace)
    if mismatch:
        with pytest.raises(AssertionError, match="PRODUCT_MISMATCH"):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    assert "RESTORE_STATUS: RESTORED" in capsys.readouterr().out
    assert plan.assertions[0].expected_fields[0].expected_value == expected


@pytest.mark.parametrize("mutation", ["none", "plan", "bindings", "missing"])
def test_frozen_tc_saved_binding_record_reassembles_original(tmp_path, mutation, controller_observation):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    case, bindings = frozen_tc_and_bindings(case, reference)
    plan = assemble_tc_bindings(case, bindings)
    actual, record = pipeline_execution._prepare_agent3_plan(tmp_path, 1, plan, controller_observation, case, bindings)
    assert actual == plan
    manifest = {"prompt_version": "agent3-3.43", "plan_value_formats": [record]}
    if mutation in {"plan", "bindings"}:
        path = tmp_path / "agent3_plan_value_format_attempt_1.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        if mutation == "plan":
            payload["raw_plan"]["assertions"][0]["expected_fields"][0]["expected_value"] = "FAN"
        else:
            payload["ui_bindings"]["verifications"][0]["selector"] = ".detail-panel"
        pipeline._write_json(path, payload)
        record["sha256"] = pipeline._sha256_file(path)  # test beyond mere hash mismatch
    elif mutation == "missing":
        manifest.pop("plan_value_formats")
    if mutation == "none":
        pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, plan, case)
    else:
        with pytest.raises(ValueError):
            pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, plan, case)


def test_frozen_tc_agent3_orchestration_saves_binding_and_shared_review(tmp_path, monkeypatch, controller_observation):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("fanSpeed", "HIGH", "LOW")
    case, bindings = frozen_tc_and_bindings(case, reference)
    plan = assemble_tc_bindings(case, bindings)
    run_id = "RUN-20260927-210000-ABCDEF"
    run = tmp_path / run_id
    pipeline._write_json(run / "agent2_manifest.json", {"run_id": run_id})
    observation = controller_observation
    monkeypatch.setattr(pipeline_execution, "_load_verified_agent2_run", lambda *_: (
        None, {}, None, SimpleNamespace(test_cases=[case]), None, {"agent2_design_sha256": "a" * 64}))
    monkeypatch.setattr(pipeline_execution, "inspect_target_ui", lambda *a, **kw: observation)
    calls = []
    def model_plan(*args, **kwargs):
        calls.append("binding")
        return pipeline.Agent3Response(plan=plan, response_id="local", model="fixture", usage={}, ui_bindings=bindings)
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent3", lambda **kw: SimpleNamespace(plan=model_plan))
    monkeypatch.setattr(pipeline_execution, "run_candidate_trial", lambda *a, **kw: calls.append("trial") or _trial(TrialOutcome.PASS))
    assert pipeline.run_agent3(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path), tc_id=case.tc_id,
        target_html=str(REPO_ROOT / "product_baseline/virtual-controller.html"), model="fixture", timeout=60)) == 0
    assert calls == ["binding", "trial"]
    manifest = pipeline._read_json_payload(run / "agent3_manifest.json")
    assert manifest["prompt_version"] == "agent3-3.43"
    pipeline_execution._agent3_review_options(manifest)
    pipeline_execution._verify_agent3_plan_value_formats(run, manifest, observation, plan, case)
    payload = pipeline._read_json_payload(run / "agent3_grounding_input_attempt_1.json")
    assert any(d["source_id"] == "TC_EXECUTION_HANDOFF/definition_preserved" and d["text"] == "true"
               for d in payload["source_documents"])


@pytest.mark.parametrize("wording", ["난방 상태를 준비하고 시작합니다.", "운전 모드는 HEAT입니다.", "난방으로 전환된 상태에서 시험합니다."])
def test_frozen_tc_paraphrases_do_not_reinterpret_values(wording, controller_observation):
    from qa_pipeline_agent3 import assemble_tc_bindings
    case, reference = controller_lifecycle_fixture("mode", "HEAT", "COOL")
    old = case.preconditions[0]
    case.preconditions[0] = wording
    for a in reference.actions:
        if a.source_text == old:
            a.source_text = wording
    for c in reference.precondition_checks:
        if c.source_text == old:
            c.source_text = wording
    # Different wording, same reviewed executable meaning.
    for er in case.expected_results:
        er.statement = er.statement.replace("COOL", "냉방")
    case, bindings = frozen_tc_and_bindings(case, reference)
    plan = assemble_tc_bindings(case, bindings)
    payload = pipeline.build_agent3_model_input(case, controller_observation, {})
    assert payload["related_srs_requirements"] == {}
    assert payload["precondition_context_bindings"]
    assert all("allowed_baseline_context_selectors" not in c for c in payload["precondition_context_bindings"])
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)


@pytest.mark.parametrize("field,initial,permitted,rejected", [
    ("status", "OPERATION", "STOP", "OPERATION"),
    ("mode", "COOL", "HEAT", "FAN"),
    ("fanSpeed", "LOW", "MED", "HIGH"),
    ("setTemp", 18, 24, 27),
    ("locked", False, True, "HIGH")])
@pytest.mark.parametrize("explicit", [False, True])
def test_product_verdict_does_not_invent_whole_test_retention(
        tmp_path, monkeypatch, capsys, controller_observation, field, initial, permitted, rejected, explicit):
    case, plan = permitted_then_blocked_fixture(field, initial, permitted, rejected)
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, shared_evidence=True, require_restore_plan_links=True,
        require_plan_fidelity=True, require_assertion_target_identity=True)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump_json(indent=2)
    original = case.model_dump_json(), plan.model_dump_json()
    code = compile_automation_candidate("LOCAL-VERDICT-SCOPE", case, plan,
        explicit_expectations_only=explicit)
    assert all(c.status == CheckStatus.PASS for c in pipeline.evaluate_compiled_candidate(case, code))
    target = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "verdict_scope", "exec"), namespace)
    if explicit:
        namespace["test_tc_cand_090"]()
    else:
        with pytest.raises(AssertionError, match="blocked operation changed observed state"):
            namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output
    assert "RESTORE_MISMATCH" not in output
    if explicit:
        assert "PRODUCT_MISMATCH" not in output
        assert "RESTORE_CONFIRMATIONS_VERIFIED" in output
    assert original == (case.model_dump_json(), plan.model_dump_json())


@pytest.mark.parametrize("initial,requested,expected,mismatch", [
    (24, 31, 30, False), (29, 32, 30, False), (30, 31, 30, False),
    (16, 15, 16, True), (24, 31, 24, True), (24, 31, 31, True)])
def test_explicit_boundary_results_are_not_replaced_by_observation(
        tmp_path, monkeypatch, capsys, controller_observation, initial, requested, expected, mismatch):
    case, plan = controller_lifecycle_fixture("setTemp", initial, requested,
        blocked=True, blocked_by_lock=False)
    for result, assertion in zip(case.expected_results, plan.assertions):
        result.statement = f"{result.observation_target} 값은 {expected}이다."
        assertion.expected_fields[0].expected_value = expected
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, shared_evidence=True, require_plan_fidelity=True)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump_json(indent=2)
    code = compile_automation_candidate("LOCAL-BOUNDARY-SCOPE", case, plan,
        explicit_expectations_only=True)
    target = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "boundary_scope", "exec"), namespace)
    if mismatch:
        with pytest.raises(AssertionError, match="PRODUCT_MISMATCH"):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output and "RESTORE_MISMATCH" not in output
    # The deliberately wrong 24 expectation must not be rewritten to the observed 30.
    assert plan.assertions[0].expected_fields[0].expected_value == expected


@pytest.mark.parametrize("requested", [21, 27, 31, 32])
@pytest.mark.parametrize("expected", [16, 24, 30, 31])
def test_product_action_is_independent_of_expected_output(requested, expected):
    case, plan = controller_lifecycle_fixture("setTemp", 24, requested,
        blocked=True, blocked_by_lock=False)
    for assertion in plan.assertions:
        assertion.expected_fields[0].expected_value = expected
    code = compile_automation_candidate("LOCAL-ACTION-SCOPE", case, plan,
        explicit_expectations_only=True)
    assert f"_request_temperature(page, {float(requested)})" in code
    assert "_set_temperature(page, 24.0)" in code  # setup remains strict
    assert "unexpected_state_change" not in code
    assert plan.assertions[0].expected_fields[0].expected_value == expected


@pytest.mark.parametrize("field,initial,requested", [
    ("status", "STOP", "OPERATION"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "LOW", "AUTO"), ("setTemp", 27, 21), ("locked", False, True)])
@pytest.mark.parametrize("mutation", ["none", "early", "restore_anchor", "missing_assertion",
    "wrong_device", "missing_apply", "mixed_operation", "intermediate", "source_paraphrase"])
def test_terminal_observation_preserves_execution_guards(field, initial, requested, mutation, controller_observation):
    case, plan = controller_lifecycle_fixture(field, initial, requested)
    observation_step = "장비 카드와 내부값을 확인한다."
    case.steps.append(observation_step)
    for result in case.expected_results:
        result.verify_after_step = observation_step
    test_actions = [a for a in plan.actions if a.phase == AutomationPhase.TEST]
    if mutation == "early":
        for assertion in plan.assertions: assertion.after_action_id = test_actions[0].action_id
    elif mutation == "restore_anchor":
        for assertion in plan.assertions: assertion.after_action_id = plan.actions[-1].action_id
    elif mutation == "missing_assertion": plan.assertions.pop()
    elif mutation == "wrong_device": plan.target_device_id = 2
    elif mutation == "missing_apply": plan.actions.remove(test_actions[-1])
    elif mutation == "mixed_operation":
        case.steps[-1] = "장비 카드와 내부값을 확인하고 적용 버튼을 누른다."
        for result in case.expected_results: result.verify_after_step = case.steps[-1]
    elif mutation == "intermediate":
        case.steps.remove(observation_step)
        case.steps.insert(1, observation_step)
    elif mutation == "source_paraphrase":
        test_actions[-1].source_text = test_actions[-1].source_text.replace("한다", "합니다")
    options = dict(legacy_wording_checks=False, allow_terminal_observation_anchor=True,
        require_assertion_target_identity=True, require_precondition_proof=True,
        require_restore_plan_links=True, require_restore_comparison_basis=True,
        review_precondition_coverage=True, review_value_roles=True, shared_evidence=True)
    before = case.model_dump_json(), plan.model_dump_json()
    result = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        allow_state_change_terminal_observation=True, **options)
    assert (result.status == CheckStatus.PASS) == (mutation == "none"), result.model_dump_json()
    if mutation == "none":
        legacy = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, **options)
        assert next(c for c in legacy.checks if c.rule_id == "CP3-003A").status == CheckStatus.FAIL
        from qa_pipeline_agent2 import _tc_observation_binding_errors
        assert not _tc_observation_binding_errors(case, legacy_wording_checks=False)
    assert before == (case.model_dump_json(), plan.model_dump_json())


@pytest.mark.parametrize("kind", ["state_change", "blocked_change", "read_only", "grouped"])
def test_terminal_observation_local_trial_and_restoration(kind, controller_observation, tmp_path, monkeypatch, capsys):
    if kind == "grouped":
        case, plan = controller_grouped_boundary_fixture()
    else:
        case, plan = controller_lifecycle_fixture("fanSpeed", "LOW", "AUTO",
            blocked=kind == "blocked_change", read_only=kind == "read_only")
    final_action = [a for a in plan.actions if a.phase == AutomationPhase.TEST][-1].action_id
    observation_step = "장비 카드와 내부값을 확인한다."
    case.steps.append(observation_step)
    final_ids = {a.result_id for a in plan.assertions if a.after_action_id == final_action}
    for result in case.expected_results:
        if result.result_id in final_ids: result.verify_after_step = observation_step
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, allow_terminal_observation_anchor=True,
        allow_state_change_terminal_observation=True, require_assertion_target_identity=True,
        require_restore_plan_links=True, review_precondition_coverage=True, review_value_roles=True, shared_evidence=True)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json()
    code = compile_automation_candidate("LOCAL-TERMINAL-OBSERVATION", case, plan)
    product = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    before = product.read_bytes()
    monkeypatch.setenv("QA_TARGET_URL", product.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "terminal_observation", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    if kind != "read_only":
        assert "RESTORE_STATUS: RESTORED" in output
        assert "RESTORE_CONFIRMATIONS_VERIFIED:" in output
    assert "PRODUCT_MISMATCH" not in output and "RESTORE_MISMATCH" not in output
    assert product.read_bytes() == before


@pytest.fixture(scope='module')
def controller_observation():
    from playwright.sync_api import Browser
    original = Browser.new_context
    def local_context(browser, *args, **kwargs):
        context = original(browser, *args, **kwargs)
        context.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('file:', 'data:', 'http://127.0.0.1', 'http://localhost')) else route.abort())
        return context
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(Browser, 'new_context', local_context)
        yield pipeline.inspect_target_ui(target, required_selectors=set(pipeline._UI_SELECTOR_INVENTORY), discover_generic=True)


@pytest.mark.parametrize("numbered", [False, True])
def test_repeated_apply_steps_require_unique_reference_not_fuzzy_matching(numbered, controller_observation):
    from qa_pipeline_agent2 import _tc_observation_binding_errors
    case, plan = controller_grouped_boundary_fixture()
    apply_steps = [case.steps[1], case.steps[3]]
    for index, source in enumerate(apply_steps):
        replacement = f"{index + 1}. 적용 버튼을 누른다." if numbered else "적용 버튼을 누른다."
        case.steps[case.steps.index(source)] = replacement
        for result in case.expected_results:
            if result.verify_after_step == source: result.verify_after_step = replacement
        for action in plan.actions:
            if action.source_text == source: action.source_text = replacement
    errors = _tc_observation_binding_errors(case, legacy_wording_checks=False)
    assert bool(errors) == (not numbered)
    if numbered:
        result = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
            legacy_wording_checks=False, allow_terminal_observation_anchor=True,
            allow_state_change_terminal_observation=True, require_assertion_target_identity=True,
            require_restore_plan_links=True, review_precondition_coverage=True, review_value_roles=True, shared_evidence=True)
        assert result.status == CheckStatus.PASS, result.model_dump_json()


@pytest.mark.parametrize("field,initial,requested", [
    ("status", "STOP", "OPERATION"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "LOW", "HIGH"), ("setTemp", 24, 25), ("locked", False, True)])
@pytest.mark.parametrize("variant", ["baseline", "mixed", "wrong_device", "unknown_reader"])
def test_mixed_precondition_readers_share_coverage(field, initial, requested, variant, controller_observation):
    case, plan = mixed_precondition_fixture(field, initial, requested, variant)
    before = case.model_dump_json(), plan.model_dump_json()
    errors = pipeline._precondition_proof_errors(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True,
        review_value_roles=True, shared_evidence=True)
    assert bool(errors) == (variant in {"wrong_device", "unknown_reader"}), errors
    legacy = pipeline._precondition_proof_errors(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=False,
        review_value_roles=True, shared_evidence=True)
    assert bool(legacy) == (variant != "baseline")
    assert before == (case.model_dump_json(), plan.model_dump_json())


@pytest.mark.parametrize("split", [False, True])
@pytest.mark.parametrize("requested,expected", [(31, 30), (15, 16), (25, 25)])
def test_temperature_helper_follows_action_anchor_not_prose(split, requested, expected):
    case, plan = split_boundary_fixture(split=split, request_value=requested, expected_value=expected)
    before = case.model_dump_json(), plan.model_dump_json()
    code = compile_automation_candidate("LOCAL-ANCHOR", case, plan)
    helper = "_request_temperature" if requested != expected else "_set_temperature"
    assert f"{helper}(page, {float(requested)})" in code
    # The intermediate reset is preparation, not this boundary's request.
    assert "_set_temperature(page, 30.0)" in code
    assert before == (case.model_dump_json(), plan.model_dump_json())


@pytest.mark.parametrize("field,initial,requested", [
    ("status", "STOP", "OPERATION"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "LOW", "HIGH"), ("setTemp", 24, 25), ("locked", False, True)])
def test_mixed_reader_local_trial_and_restoration(field, initial, requested, controller_observation,
                                                 tmp_path, monkeypatch, capsys):
    case, plan = mixed_precondition_fixture(field, initial, requested)
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True,
        shared_evidence=True, require_assertion_target_identity=True, require_restore_plan_links=True)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json()
    code = compile_automation_candidate("LOCAL-MIXED-READERS", case, plan)
    product = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    before = product.read_bytes()
    monkeypatch.setenv("QA_TARGET_URL", product.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "mixed_readers", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output
    assert "RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091" in output
    assert "PRODUCT_MISMATCH" not in output and "RESTORE_MISMATCH" not in output
    assert product.read_bytes() == before


@pytest.mark.parametrize("split,second_expected", [(False, 21), (True, 21), (True, 22)])
def test_grouped_boundary_local_trial_preserves_assertions_and_restore(split, second_expected,
        controller_observation, tmp_path, monkeypatch, capsys):
    case, plan = controller_grouped_boundary_fixture(split=split, second_expected=second_expected)
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True,
        shared_evidence=True, require_assertion_target_identity=True, require_restore_plan_links=True)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json()
    code = compile_automation_candidate("LOCAL-GROUPED-BOUNDARY", case, plan)
    assert "_request_temperature(page, 31.0)" in code
    second_helper = "_set_temperature" if second_expected == 21 else "_request_temperature"
    assert f"{second_helper}(page, 21.0)" in code
    assert all(c.status == CheckStatus.PASS for c in pipeline.evaluate_compiled_candidate(case, code))
    product = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    before = product.read_bytes()
    monkeypatch.setenv("QA_TARGET_URL", product.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "grouped_boundary", "exec"), namespace)
    if second_expected != 21:
        with pytest.raises(AssertionError, match="PRODUCT_MISMATCH"):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output and "RESTORE_MISMATCH" not in output
    if second_expected == 21:
        assert "RESTORE_CONFIRMATIONS_VERIFIED:" in output
        assert all(result.result_id in output for result in case.expected_results)
    assert product.read_bytes() == before


@pytest.mark.parametrize("variant,verdict,expected", [
    ("mixed", "SUPPORTED", "PASS"), ("missing", "UNSUPPORTED", "FAIL"),
    ("missing", "UNCERTAIN", "REVIEW")])
def test_mixed_reader_coverage_still_requires_review(controller_observation, variant, verdict, expected):
    import qa_pipeline_grounding as g
    case, plan = mixed_precondition_fixture("mode", "COOL", "HEAT", variant)
    payload = g.build_grounding_input("AGENT3", None, {}, plan, test_case=case,
        observation=controller_observation, include_execution_contract=True,
        include_review_responsibilities=True, include_task_boundaries="1.2")
    item = next(i for i in payload["items"] if i["kind"] == "PRECONDITION_COVERAGE"
        and i["content"]["source"] == case.preconditions[-1])
    assert len(item["content"]["checks"]) == (1 if variant == "missing" else 2)
    record = fake_grounding_record(payload)
    next(i for i in record["review"]["items"] if i["item_id"] == item["item_id"])["verdict"] = verdict
    assert g.check_review_record(payload, record).status.value == expected
    record["review"]["items"] = [i for i in record["review"]["items"] if i["item_id"] != item["item_id"]]
    with pytest.raises(ValueError, match="검토 응답 오류"):
        g.check_review_record(payload, record)


def test_temperature_helper_does_not_borrow_later_condition():
    case, plan = split_boundary_fixture()
    # Remove the upper-bound observation. The lower bound must not authorize it.
    plan.assertions = plan.assertions[:-1]
    code = compile_automation_candidate("LOCAL-NO-BORROW", case, plan)
    assert "_set_temperature(page, 31.0)" in code
    # A late assertion must not leak past the first apply into another segment.
    plan.assertions[0].after_action_id = "ACT-010"
    code = compile_automation_candidate("LOCAL-NO-BORROW", case, plan)
    assert "_set_temperature(page, 30.0)" in code


@pytest.mark.parametrize("mutation", ["normal", "wrong_input", "wrong_output", "missing_assertion", "early_anchor"])
def test_boundary_outputs_are_not_inputs_but_remain_bound_to_er(controller_observation, mutation):
    case, plan = controller_grouped_boundary_fixture()
    if mutation == "wrong_input":
        next(a for a in plan.actions if a.action_id == "ACT-100").value = 99
    elif mutation == "wrong_output":
        plan.assertions[-1].expected_fields[0].expected_value = 99
    elif mutation == "missing_assertion":
        plan.assertions.pop()
    elif mutation == "early_anchor":
        plan.assertions[-1].after_action_id = "ACT-100"
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True,
        shared_evidence=True, require_assertion_target_identity=True, require_restore_plan_links=True)
    expected_rule = {"wrong_input": "CP3-005", "wrong_output": "CP3-004",
        "missing_assertion": "CP3-003", "early_anchor": "CP3-003A"}.get(mutation)
    if expected_rule:
        assert any(c.rule_id == expected_rule and c.status == CheckStatus.FAIL for c in cp.checks)
    else:
        assert cp.status == CheckStatus.PASS, cp.model_dump_json()
    legacy = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True,
        shared_evidence=False)
    assert any(c.rule_id == "CP3-005" and c.status == CheckStatus.FAIL for c in legacy.checks)


_CONTROL_SCENARIOS = [
    ('status', 'STOP', 'OPERATION', False), ('status', 'OPERATION', 'STOP', False),
    *[('mode', initial, target, False) for initial in ('COOL', 'HEAT', 'FAN', 'DRY', 'AUTO')
      for target in ('COOL', 'HEAT', 'FAN', 'DRY', 'AUTO') if initial != target],
    *[('fanSpeed', initial, target, False) for initial in ('LOW', 'MED', 'HIGH', 'AUTO')
      for target in ('LOW', 'MED', 'HIGH', 'AUTO') if initial != target],
    ('setTemp', 18, 24, False), ('setTemp', 30, 18, False), ('setTemp', 18, 30, False),
    ('setTemp', 30, 23, False),
    ('locked', True, False, False), ('locked', False, True, False),
    ('status', 'OPERATION', 'STOP', True), ('mode', 'COOL', 'HEAT', True),
    ('fanSpeed', 'LOW', 'HIGH', True), ('setTemp', 24, 25, True),
]


_PLAN_FORMAT_VALUES = [
    ("status", "OPERATION", "운전"), ("status", "STOP", "정지"),
    ("mode", "COOL", "냉방"), ("mode", "HEAT", "난방"), ("mode", "FAN", "송풍"),
    ("mode", "DRY", "제습"), ("mode", "AUTO", "자동"),
    ("fanSpeed", "LOW", "약풍"), ("fanSpeed", "MED", "중풍"),
    ("fanSpeed", "HIGH", "강풍"), ("fanSpeed", "AUTO", "자동"),
    ("locked", True, "잠금"), ("locked", False, "해제"),
]


@pytest.mark.parametrize("field,initial,target,label", [
    ("status", "STOP", "OPERATION", "운전"), ("mode", "COOL", "HEAT", "난방"),
    ("fanSpeed", "LOW", "HIGH", "강풍"), ("locked", False, True, "설정"), ("setTemp", 27, 21, "21"),
])
def test_shared_evidence_writer_checker_reviewer_use_same_inventory(controller_observation, field, initial, target, label):
    import qa_pipeline_grounding as g
    case, plan = controller_lifecycle_fixture(field, initial, target)
    for result in case.expected_results:
        result.statement = "해당 관제점의 적용 결과는 " + label + " 상태이다."
    # Remove English field names from human prose without editing technical paths.
    for name in ("title",): setattr(case, name, "한글로 작성한 제어 시험")
    case.preconditions = ["시작 상태를 준비한다."]
    for action in plan.actions:
        if action.phase == pipeline.AutomationPhase.PRECONDITION: action.source_text = case.preconditions[0]
    for check in plan.precondition_checks: check.source_text = case.preconditions[0]
    case.steps = ["목표 상태를 선택한다.", "선택한 값을 적용한다."]
    for action in plan.actions:
        if action.phase == pipeline.AutomationPhase.TEST and action.action_type != pipeline.AutomationActionType.APPLY_COMMANDS:
            action.source_text = case.steps[0]
    # State meaning is deliberately a model-review responsibility, not a word parser.
    payload = pipeline.build_agent3_model_input(case, controller_observation, {}, shared_evidence=True)
    review = g.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=controller_observation,
        include_execution_contract=True, include_review_responsibilities=True, include_task_boundaries="1.2")
    assert field in payload["ui_observation"]["device_state_fields"]
    assert f"window.__vccs.devices[0].{field}" in payload["ui_observation"]["harness_values"]
    assert review["context"]["controller_evidence"] == payload["controller_evidence"]
    documents = {d["source_id"]: d["text"] for d in review["source_documents"]}
    for path, value in payload["ui_observation"]["harness_values"].items():
        assert documents["UI_INVENTORY/harness_values/" + path] == (value if isinstance(value, str) else json.dumps(value))
    assert len([i for i in review["items"] if i["kind"] == "EXPECTED_RESULT"]) == len(case.expected_results)
    # Missing checks and unsupported readers remain structural failures.
    plan.assertions.pop()
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True, shared_evidence=True)
    assert cp.status == CheckStatus.FAIL


@pytest.mark.parametrize("field,initial,target,label,wrong", [
    ("status", "STOP", "OPERATION", "운전", "STOP"), ("mode", "COOL", "HEAT", "난방", "COOL"),
    ("fanSpeed", "LOW", "HIGH", "강풍", "LOW"), ("locked", False, True, "잠금", False),
])
def test_shared_evidence_keeps_value_mismatch_in_mandatory_review(controller_observation, field, initial, target, label, wrong):
    import qa_pipeline_grounding as g
    case, plan = controller_lifecycle_fixture(field, initial, target)
    case.expected_results[1].statement = "적용 후 내부 상태는 " + label + "이다."
    opts = dict(legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True)
    assert pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, **opts, shared_evidence=True).status == CheckStatus.PASS
    # A valid enum is not proof of correct meaning. Scripted rejection tests routing only.
    plan.assertions[1].expected_fields[0].expected_value = wrong
    payload = g.build_grounding_input("AGENT3", None, {}, plan, test_case=case, observation=controller_observation,
        include_review_responsibilities=True, include_task_boundaries="1.2")
    record = fake_grounding_record(payload)
    item_id = next(i["item_id"] for i in payload["items"]
                   if i["kind"] == "EXPECTED_RESULT"
                   and i["content"]["expected_result"]["result_id"] == case.expected_results[1].result_id)
    next(i for i in record["review"]["items"] if i["item_id"] == item_id).update(
        verdict="UNSUPPORTED", reason="Scripted counterexample: expected and planned states differ.")
    assert g.check_review_record(payload, record).status == CheckStatus.FAIL


def test_shared_evidence_missing_control_does_not_gain_auto_capability(controller_observation):
    case, plan = controller_lifecycle_fixture("mode", "COOL", "AUTO")
    case.title = "기존 AUTO 운전 모드와 별개인 자동 전환 설정 시험"
    evidence = pipeline.build_agent3_model_input(case, controller_observation, {}, shared_evidence=True)
    assert set(evidence["controller_evidence"]) == {"status", "mode", "fanSpeed", "locked"}
    assert "automaticSwitch" not in evidence["ui_observation"]["device_state_fields"]
    # Inventing a selector for a requested but absent control is still rejected.
    action = next(a for a in plan.actions if a.phase == pipeline.AutomationPhase.TEST and a.selector)
    action.selector = "#nonexistent-automatic-switch"
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True, shared_evidence=True)
    assert cp.status == CheckStatus.FAIL
    unsupported = Agent3AutomationPlan.model_validate(dict(tc_id=case.tc_id, target_device_id=1,
        summary="요청한 독립 관제점이 관찰되지 않았습니다.",
        planning_status="AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
        extension_reasons=["기존 AUTO 운전 모드는 별개이며 자동 전환 설정/해제 조작과 관찰 경로가 없습니다."]))
    cp = pipeline.evaluate_checkpoint3_plan(case, unsupported, controller_observation, shared_evidence=True)
    assert cp.status == CheckStatus.REVIEW
    assert cp.candidate_status == pipeline.AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED


@pytest.mark.parametrize("field,value,label", _PLAN_FORMAT_VALUES)
@pytest.mark.parametrize("spelling", ["canonical", "lower", "mixed", "period", "label"])
def test_plan_value_format_accepts_only_finite_domain_tokens(field, value, label, spelling):
    token = {"canonical": value, "lower": str(value).lower(), "mixed": str(value).capitalize(),
             "period": "  " + str(value).lower() + ".  ", "label": " " + label + ". "}[spelling]
    actual = pipeline._normalize_controller_plan_value(field, token)
    assert type(actual) is type(value) and actual == value


@pytest.mark.parametrize("field", ["status", "mode", "fanSpeed", "locked", "setTemp", "unknown"])
@pytest.mark.parametrize("value", ["HEAT 또는 COOL", "HEAT 아님", "not HEAT", "HEAT..", ".HEAT",
                                  "HEAT/COOL", "HEAT;", "HE AT", "heat .", "", "21.", 1, None])
def test_plan_value_format_never_guesses_or_parses_sentences(field, value):
    assert pipeline._normalize_controller_plan_value(field, value) == value


@pytest.mark.parametrize("field,initial,target", [
    ("status", "STOP", "OPERATION"), ("mode", "COOL", "HEAT"),
    ("fanSpeed", "LOW", "HIGH"), ("locked", False, True), ("setTemp", 27, 21),
])
def test_plan_value_format_shared_across_plan_roles(tmp_path, monkeypatch, capsys, controller_observation, field, initial, target):
    case, canonical = controller_lifecycle_fixture(field, initial, target, prove_ui=True)
    raw = canonical.model_copy(deep=True)
    if field != "setTemp":
        for action in raw.actions:
            if action.action_type == pipeline.AutomationActionType.SET_MODE:
                action.value = " " + str(action.value).lower() + ". "
        for assertion in raw.assertions:
            for entry in assertion.expected_fields:
                entry.expected_value = " " + str(entry.expected_value).lower() + ". "
        for check in raw.precondition_checks:
            if check.selector != "card.selected":
                check.expected_value = " " + str(check.expected_value).lower() + ". "
    before = raw.model_dump_json(), case.model_dump_json(), controller_observation.model_dump_json()
    normalized, changes = pipeline._normalize_agent3_plan_values(raw, controller_observation)
    assert normalized == canonical
    assert bool(changes) == (field != "setTemp")
    assert before == (raw.model_dump_json(), case.model_dump_json(), controller_observation.model_dump_json())
    assert pipeline._normalize_agent3_plan_values(normalized, controller_observation) == (normalized, [])
    cp = pipeline.evaluate_checkpoint3_plan(case, normalized, controller_observation,
        legacy_wording_checks=False, require_restore_plan_links=True, require_restore_comparison_basis=True,
        review_precondition_coverage=True, review_value_roles=True, require_assertion_target_identity=True)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)

    # Execute the normalized plan against the unchanged local product, not a
    # mocked trial. The temperature case also proves numeric values stay intact.
    code = compile_automation_candidate("LOCAL-PLAN-VALUE-FORMAT", case, normalized)
    assert all(check.status == CheckStatus.PASS for check in pipeline.evaluate_compiled_candidate(case, code))
    product = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    before_product = product.read_bytes()
    monkeypatch.setenv("QA_TARGET_URL", product.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "normalized_controller_candidate", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output
    assert "RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091" in output
    assert "PRODUCT_MISMATCH" not in output and "RESTORE_MISMATCH" not in output
    assert product.read_bytes() == before_product


def test_local_heat_temperature_trial_restores_preparation_state(tmp_path, monkeypatch, capsys, controller_observation):
    # Hand-authored input, not an AI generation/evaluation success claim.
    case, plan = controller_lifecycle_fixture("setTemp", 27, 21, prepare={"mode": "HEAT"}, prove_ui=True)
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, require_restore_plan_links=True, require_restore_comparison_basis=True,
        review_precondition_coverage=True, review_value_roles=True, require_assertion_target_identity=True,
        shared_evidence=True)
    assert cp.status == CheckStatus.PASS, cp.model_dump_json(indent=2)
    code = compile_automation_candidate("LOCAL-HEAT-27-21", case, plan)
    assert all(check.status == CheckStatus.PASS for check in pipeline.evaluate_compiled_candidate(case, code))
    product = Path(__file__).resolve().parents[1] / "product_baseline/virtual-controller.html"
    before = product.read_bytes()
    monkeypatch.setenv("QA_TARGET_URL", product.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "local_heat_candidate", "exec"), namespace)
    namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: RESTORED" in output
    assert "RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091" in output
    assert "PRODUCT_MISMATCH" not in output and "RESTORE_MISMATCH" not in output
    assert product.read_bytes() == before


def test_plan_value_format_does_not_fix_wrong_expectation_or_selector(controller_observation):
    case, raw = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    raw.assertions[1].expected_fields[0].expected_value = "cool."
    normalized, changes = pipeline._normalize_agent3_plan_values(raw, controller_observation)
    assert changes and normalized.assertions[1].expected_fields[0].expected_value == "COOL"
    cp = pipeline.evaluate_checkpoint3_plan(case, normalized, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True)
    assert any(c.rule_id == "CP3-004" and c.status == CheckStatus.FAIL for c in cp.checks)
    case, raw = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    action = next(a for a in raw.actions if a.action_type == pipeline.AutomationActionType.SET_MODE)
    action.value, action.selector = "cool.", "#det-mode-heat"
    normalized, _ = pipeline._normalize_agent3_plan_values(raw, controller_observation)
    assert normalized.actions[1].selector == raw.actions[1].selector
    cp = pipeline.evaluate_checkpoint3_plan(case, normalized, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, review_value_roles=True)
    assert any(c.rule_id == "CP3-002" and c.status == CheckStatus.FAIL for c in cp.checks)


def test_plan_value_format_preserves_text_numbers_and_other_product_paths(controller_observation):
    _, raw = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    raw.assertions[0].strategy = pipeline.AssertionStrategy.UI_TEXT_CONTAINS
    raw.assertions[0].expected_fields = []
    raw.assertions[0].expected_text = " heat. "
    raw.assertions[1].strategy = pipeline.AssertionStrategy.INTERNAL_VALUE_EQUALS
    raw.assertions[1].expected_fields = []
    raw.assertions[1].selector = "window.__vccs.feature.mode"
    raw.assertions[1].expected_value = " heat. "
    raw.actions[1].action_type = pipeline.AutomationActionType.FILL
    raw.actions[1].value = " heat. "
    before = raw.model_dump_json()
    normalized, changes = pipeline._normalize_agent3_plan_values(raw, controller_observation)
    assert normalized.model_dump_json() == before and changes == []


@pytest.mark.parametrize("attempts", [1, 2])
def test_plan_value_format_records_raw_and_checks_handoff(tmp_path, controller_observation, attempts):
    _, canonical = controller_lifecycle_fixture("fanSpeed", "LOW", "HIGH")
    raw = canonical.model_copy(deep=True)
    raw.assertions[1].expected_fields[0].expected_value = "강풍."
    records = []
    for attempt in range(1, attempts + 1):
        normalized, record = pipeline_execution._prepare_agent3_plan(tmp_path, attempt, raw, controller_observation)
        records.append(record)
    manifest = {"plan_value_formats": records}
    pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, canonical)
    assert normalized == canonical and raw.assertions[1].expected_fields[0].expected_value == "강풍."
    pipeline_execution._verify_agent3_plan_value_formats(tmp_path, {}, controller_observation, raw)
    with pytest.raises(ValueError, match="최종 계획"):
        pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, raw)
    path = tmp_path / "agent3_plan_value_format_attempt_1.json"
    payload = pipeline._read_json_payload(path)
    assert payload["raw_plan"] == raw.model_dump(mode="json")
    payload["changes"] = []
    pipeline._write_json(path, payload)
    with pytest.raises(ValueError):
        pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, canonical)
    records[0]["sha256"] = pipeline._sha256_file(path)
    with pytest.raises(ValueError, match="재계산"):
        pipeline_execution._verify_agent3_plan_value_formats(tmp_path, manifest, controller_observation, canonical)


@pytest.mark.parametrize("needs_repair", [False, True])
def test_plan_value_format_pipeline_uses_same_plan_for_review_and_compile(tmp_path, monkeypatch, controller_observation, needs_repair):
    case, canonical = controller_lifecycle_fixture("mode", "COOL", "HEAT")
    observation = controller_observation.model_copy(deep=True)
    raw = canonical.model_copy(deep=True)
    for action in raw.actions:
        if action.action_type == pipeline.AutomationActionType.SET_MODE:
            action.value = str(action.value).lower() + "."
    raw.assertions[1].expected_fields[0].expected_value = "난방."
    preserved = case.model_dump_json(), raw.model_dump_json()
    run_id = "RUN-20260927-120000-ABCDEF"
    run = tmp_path / run_id
    pipeline._write_json(run / "agent2_manifest.json", {"run_id": run_id})
    target = tmp_path / "target.html"
    pipeline._write_text_atomic(target, "<!doctype html><title>fixture</title>")
    observation.target_sha256 = pipeline._sha256_file(target)
    monkeypatch.setattr(pipeline_execution, "_load_verified_agent2_run", lambda *_: (
        None, {}, None, SimpleNamespace(test_cases=[case]), None, {"agent2_design_sha256": "a" * 64}))
    monkeypatch.setattr(pipeline_execution, "inspect_target_ui", lambda *a, **kw: observation)
    calls = []
    def generate(*args, **kwargs):
        calls.append("model")
        plan = raw.model_copy(deep=True)
        if needs_repair and len(calls) == 1:
            plan.assertions.pop(0)
        return pipeline.Agent3Response(plan=plan, response_id=None, model="fixture", usage={})
    def review(directory, stage, attempt, payload, checkpoint, model, records):
        assert all(a["value"] in {"COOL", "HEAT"} for a in payload["context"]["plan"]["actions"]
                   if a["action_type"] == "SET_MODE")
        pipeline._write_json(directory / "agent3_grounding_review.json", {"fixture": True})
        return checkpoint
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent3", lambda **kw: SimpleNamespace(plan=generate))
    monkeypatch.setattr(pipeline_execution, "_run_grounding_review", review)
    original_compile = pipeline_execution.compile_automation_candidate
    def compile_plan(run_id, tc, plan, **kwargs):
        assert plan == canonical
        assert kwargs == {"explicit_expectations_only": True}
        return original_compile(run_id, tc, plan, **kwargs)
    monkeypatch.setattr(pipeline_execution, "compile_automation_candidate", compile_plan)
    monkeypatch.setattr(pipeline_execution, "run_candidate_trial", lambda *a, **kw: _trial(TrialOutcome.PASS))
    assert pipeline.run_agent3(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path), tc_id=case.tc_id,
        target_html=str(target), model="fixture", timeout=60)) == 0
    assert calls == ["model"] * (2 if needs_repair else 1)
    assert preserved == (case.model_dump_json(), raw.model_dump_json())
    manifest = pipeline._read_json_payload(run / "agent3_manifest.json")
    assert len(manifest["plan_value_formats"]) == len(calls)
    pipeline_execution._verify_agent3_plan_value_formats(run, manifest, observation, canonical)


@pytest.mark.parametrize('field,initial,requested,other', [
    ('setTemp', 27, 21, 24), ('setTemp', 23, 28, 18),
    ('mode', 'COOL', 'HEAT', 'AUTO'), ('mode', 'DRY', 'COOL', 'FAN'),
    ('fanSpeed', 'MED', 'HIGH', 'LOW'), ('status', 'STOP', 'OPERATION', 'OFFLINE'),
])
def test_precondition_value_roles_preserve_only_required_starting_state(controller_observation, field, initial, requested, other):
    case, plan = controller_lifecycle_fixture(field, initial, requested)
    index = next(i for i, line in enumerate(case.preconditions) if field in line)
    original = case.preconditions[index]
    source = f'대상 장비의 {field}는 이전 값 {other}가 아니라 시작값 {initial}이다.'
    case.preconditions[index] = source
    for entry in [*plan.actions, *plan.precondition_checks]:
        if entry.source_text == original: entry.source_text = source
    opts = dict(legacy_wording_checks=False, require_precondition_proof=True, review_precondition_coverage=True,
        require_restore_plan_links=True, require_restore_comparison_basis=True, require_assertion_target_identity=True)
    old = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, **opts)
    assert any(c.rule_id == 'CP3-006D' and c.status == CheckStatus.FAIL for c in old.checks)
    current = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, review_value_roles=True, **opts)
    assert current.status == CheckStatus.PASS, current.model_dump_json(indent=2)
    # Structural support/identity and cited-value protection are not removed.
    check = next(c for c in plan.precondition_checks if c.source_text == source)
    check.expected_value = 'UNSUPPORTED_VALUE'
    bad = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, review_value_roles=True, **opts)
    assert bad.status == CheckStatus.FAIL


@pytest.mark.parametrize('fault', ['missing_start', 'wrong_start', 'wrong_target'])
@pytest.mark.parametrize('verdict,expected', [('UNSUPPORTED', 'FAIL'), ('UNCERTAIN', 'REVIEW')])
def test_precondition_semantic_coverage_is_required_after_value_role_relaxation(controller_observation, fault, verdict, expected):
    import qa_pipeline_grounding as g
    case, plan = controller_lifecycle_fixture('setTemp', 27, 21)
    if fault == 'missing_start': plan.precondition_checks.pop()
    elif fault == 'wrong_start': plan.precondition_checks[-1].expected_value = 21
    else: plan.precondition_checks[-1].selector = 'window.__vccs.devices[0].mode'
    payload = g.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=controller_observation,
        include_execution_contract=True, include_review_responsibilities=True, include_task_boundaries='1.1')
    target = next(i for i in payload['items'] if i['item_id'] == 'PRECONDITION/1')
    assert target['content']['source'] == case.preconditions[1]
    record = fake_grounding_record(payload)
    next(i for i in record['review']['items'] if i['item_id'] == target['item_id']).update(verdict=verdict,
        reason='Scripted: starting value check is missing or mismatched.')
    assert g.check_review_record(payload, record).status.value == expected


@pytest.mark.parametrize("field,initial,target", [
    ("status", "OPERATION", "STOP"), ("mode", "COOL", "AUTO"),
    ("fanSpeed", "LOW", "HIGH"), ("setTemp", 27, 21), ("locked", False, True),
])
def test_preparation_recovery_has_compiler_facts_without_extra_product_ers(controller_observation, field, initial, target):
    import qa_pipeline_grounding as grounding
    case, plan = controller_lifecycle_fixture(field, initial, target, prepare={"mode": "HEAT"})
    result_ids = [r.result_id for r in case.expected_results]
    payload = grounding.build_grounding_input("AGENT3", None, {}, plan, test_case=case,
        observation=controller_observation, include_execution_contract=True,
        include_review_responsibilities=True, include_task_boundaries=True)
    recovery = payload["context"]["compiler_plan_facts"]["controller_recovery"]
    assert set(recovery["internal_fields"]) == {"status", "mode", "fanSpeed", "setTemp", "locked"}
    assert recovery["target_device_id"] == plan.target_device_id
    assert recovery["capture_timing"] == "BEFORE_SETUP"
    assert recovery["comparison_timing"] == "AFTER_RESTORE"
    assert not recovery["depends_on_product_result_ids"] and not recovery["trial_success_proved"]
    code = compile_automation_candidate("RECOVERY-FACTS", case, plan)
    assert "controller_original = _controller_baseline" in code
    assert "if restored_controller != controller_original:" in code
    assert [r.result_id for r in case.expected_results] == result_ids
    assert all(field in r.observation_target for r in case.expected_results)
    # Facts never fabricate a restore operation when the plan omits it.
    plan.actions = [a for a in plan.actions if a.phase != AutomationPhase.RESTORE]
    assert pipeline.controller_recovery_plan_facts(case, plan) is None
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, review_precondition_coverage=True, require_restore_plan_links=True)
    assert cp.status == CheckStatus.FAIL


@pytest.mark.parametrize("mutation", ["read_only", "legacy_restore", "wrong_phase", "duplicate"])
def test_controller_recovery_facts_do_not_claim_unsupported_coverage(mutation):
    case, plan = controller_lifecycle_fixture("fanSpeed", "MED", "LOW")
    restore = next(a for a in plan.actions if a.phase == AutomationPhase.RESTORE)
    if mutation == "read_only": case.state_effect = pipeline.TcStateEffect.READ_ONLY
    elif mutation == "legacy_restore": restore.action_type = pipeline.AutomationActionType.RESTORE_OBSERVED_HVAC
    elif mutation == "wrong_phase": restore.phase = AutomationPhase.TEST
    else: plan.actions.append(restore.model_copy())
    assert pipeline.controller_recovery_plan_facts(case, plan) is None


@pytest.mark.parametrize("mode,initial,target", [("HEAT", 27, 21), ("AUTO", 23, 28), ("COOL", 25, 19)])
@pytest.mark.parametrize("fault", [None, "mode_restore"])
def test_temperature_context_recovers_mode_without_mode_product_er(
        tmp_path, monkeypatch, capsys, controller_observation, mode, initial, target, fault):
    case, plan = controller_lifecycle_fixture("setTemp", initial, target, prepare={"mode": mode}, prove_ui=True)
    assert all("setTemp" in r.observation_target for r in case.expected_results)
    assert case.test_data.initial_mode == mode
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation,
        legacy_wording_checks=False, require_precondition_proof=True,
        review_precondition_coverage=True, require_restore_plan_links=True,
        require_restore_comparison_basis=True, require_assertion_target_identity=True)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump_json(indent=2)
    code = compile_automation_candidate("CONTEXT-RECOVERY", case, plan)
    target_html = REPO_ROOT / "product_baseline/virtual-controller.html"
    monkeypatch.setenv("QA_TARGET_URL", target_html.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "context_recovery", "exec"), namespace)
    if fault:
        original_restore = namespace["_restore_controller"]
        def broken_mode_restore(page, device_id, original):
            original_restore(page, device_id, original)
            different = "HEAT" if original["state"]["mode"] != "HEAT" else "COOL"
            page.locator(pipeline._MODE_SELECTOR[different]).click()
            page.locator(".btn-apply-cmd").click()
        namespace["_restore_controller"] = broken_mode_restore
        with pytest.raises(AssertionError, match="RESTORE_MISMATCH"):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "PRECONDITIONS_VERIFIED:" in output
    assert ("RESTORE_STATUS: FAILED" if fault else "RESTORE_STATUS: RESTORED") in output
    if fault:
        assert "ENVIRONMENT_RETIRED" in output

@pytest.mark.parametrize('field,initial,target', [
    ('status', 'OPERATION', 'STOP'), ('mode', 'AUTO', 'DRY'), ('fanSpeed', 'HIGH', 'AUTO'),
    ('setTemp', 24, 25), ('locked', False, True),
])
def test_automatic_capture_and_required_state_have_separate_review_coverage(controller_observation, field, initial, target):
    import qa_pipeline_grounding as grounding
    case, plan = controller_lifecycle_fixture(field, initial, target)
    record_instruction = '준비 전 대상 장비의 화면 및 내부 원래 값을 기록한다.'
    case.preconditions.append(record_instruction)
    opts = dict(legacy_wording_checks=False, require_restore_plan_links=True, require_restore_comparison_basis=True,
                require_assertion_target_identity=True)
    old = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, **opts)
    assert old.status == CheckStatus.FAIL
    new = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, review_precondition_coverage=True, **opts)
    assert new.status == CheckStatus.PASS, new.model_dump_json(indent=2)
    payload = grounding.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=controller_observation,
        include_execution_contract=True, include_review_responsibilities=True)
    coverage = [item for item in payload['items'] if item['kind'] == 'PRECONDITION_COVERAGE']
    assert [item['content']['source'] for item in coverage] == case.preconditions
    assert coverage[-1]['content']['checks'] == []
    facts = payload['context']['compiler_plan_facts']
    assert {item['result_id'] for item in facts['automatic_baseline_captures']} == {'ER-090', 'ER-091'}
    assert all(set(item['reader']) == {'strategy', 'selector', 'field_names'} for item in facts['automatic_baseline_captures'])
    assert all(item['observed_device_id'] == item['required_device_id'] == 1 for item in facts['indexed_internal_readers'])
    assert not facts['trial_success_proved']
    valid = fake_grounding_record(payload)
    assert grounding.attach_grounding_check(new, grounding.check_review_record(payload, valid)).status == CheckStatus.PASS
    missing_review = fake_grounding_record(payload)
    missing_review['review']['items'] = [i for i in missing_review['review']['items'] if i['item_id'] != coverage[-1]['item_id']]
    assert grounding.check_review_record(payload, missing_review).status == CheckStatus.FAIL
    # Omission remains in the TC-driven review targets, even if no checks remain.
    plan.precondition_checks = []
    missing = grounding.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=controller_observation,
        include_execution_contract=True, include_review_responsibilities=True)
    assert len([i for i in missing['items'] if i['kind'] == 'PRECONDITION_COVERAGE']) == len(case.preconditions)
    record = fake_grounding_record(missing)
    next(i for i in record['review']['items'] if i['item_id'] == 'PRECONDITION/0').update(
        verdict='UNSUPPORTED', reason='시작 상태 확인이 누락됨')
    assert grounding.check_review_record(missing, record).status == CheckStatus.FAIL


@pytest.mark.parametrize('mutation', ['device', 'reader', 'expected_value', 'missing_assertion', 'missing_restore'])
def test_review_ownership_keeps_structural_plan_protections(controller_observation, mutation):
    case, plan = controller_lifecycle_fixture('fanSpeed', 'HIGH', 'AUTO')
    if mutation == 'device': plan.target_device_id = 2
    elif mutation == 'reader': plan.precondition_checks[0].selector = 'window.__vccs.unknown'
    elif mutation == 'expected_value': plan.assertions[0].expected_fields[0].expected_value = 'HIGH'
    elif mutation == 'missing_assertion': plan.assertions.pop()
    elif mutation == 'missing_restore': plan.actions = [a for a in plan.actions if a.phase != AutomationPhase.RESTORE]
    result = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, legacy_wording_checks=False,
        review_precondition_coverage=True, require_restore_plan_links=True, require_assertion_target_identity=True)
    if mutation == 'expected_value':
        # Finite UI enum meaning is deliberately model reviewed; internal value mismatch remains separate.
        import qa_pipeline_grounding as grounding
        payload = grounding.build_grounding_input('AGENT3', None, {}, plan, test_case=case, observation=controller_observation,
            include_execution_contract=True, include_review_responsibilities=True)
        record = fake_grounding_record(payload, verdict='UNSUPPORTED')
        assert grounding.attach_grounding_check(result, grounding.check_review_record(payload, record)).status == CheckStatus.FAIL
    else:
        assert result.status == CheckStatus.FAIL, result.model_dump_json(indent=2)


@pytest.mark.parametrize('field,initial,requested', [
    ('status', 'OPERATION', 'STOP'), ('mode', 'AUTO', 'DRY'),
    ('fanSpeed', 'HIGH', 'AUTO'), ('setTemp', 24, 25), ('locked', False, True),
])
@pytest.mark.parametrize('ui_target', ['#device-card-1', '.detail-panel'])
def test_detailed_controller_preconditions_and_target_readers(tmp_path, monkeypatch, capsys, controller_observation,
                                                             field, initial, requested, ui_target):
    case, plan = controller_lifecycle_fixture(field, initial, requested, prove_ui=True)
    plan.assertions[0].selector = ui_target
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, legacy_wording_checks=False,
        require_precondition_proof=True, require_restore_plan_links=True, require_plan_fidelity=True,
        require_assertion_target_identity=True)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump_json(indent=2)
    code = compile_automation_candidate('DETAILED-CONTROLLER', case, plan)
    assert all(c.status == CheckStatus.PASS for c in pipeline.evaluate_compiled_candidate(case, code))
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'controller_candidate', 'exec'), namespace)
    namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    assert 'PRECONDITIONS_VERIFIED:' in output
    assert 'RESTORE_STATUS: RESTORED' in output
    assert 'RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091' in output


@pytest.mark.parametrize('selector', ['card.fake', 'panel.selected', 'window.__vccs.devices', 'card.status;evil()', 'card.status.extra'])
def test_controller_precondition_reader_rejects_unknown_targets(controller_observation, selector):
    case, plan = controller_lifecycle_fixture('status', 'OPERATION', 'STOP', prove_ui=True)
    plan.precondition_checks[-1].selector = selector
    errors = pipeline._precondition_proof_errors(case, plan, controller_observation, legacy_wording_checks=False)
    assert 'unsupported or unobserved controller precondition reader' in errors


def test_detailed_controller_eligibility_includes_panel_observation():
    case, _ = controller_lifecycle_fixture('mode', 'AUTO', 'DRY', prove_ui=True)
    case.target_role = 'PRIMARY_TEST_DEVICE'
    eligibility = pipeline.evaluate_agent3_eligibility(case)
    assert '.detail-panel' in eligibility.required_selectors


@pytest.mark.parametrize('field,value,label,expected', [
    ('mode', 'DRY', '제습 상태', True), ('status', 'STOP', '정지 상태', True),
    ('fanSpeed', 'AUTO', '자동 풍량', True), ('locked', True, '잠금 설정 상태', True),
    ('mode', 'UNKNOWN', '제습 상태', False), ('setTemp', 99, '설정 온도 25°C', False),
])
def test_decoded_ui_values_use_adapter_types_and_semantic_review(field, value, label, expected):
    assert pipeline._controller_ui_value_is_grounded(field, value, label, legacy_wording_checks=False) is expected
    if field == 'mode' and value == 'DRY':
        assert not pipeline._controller_ui_value_is_grounded(field, value, label, legacy_wording_checks=True)


@pytest.mark.parametrize('field,value', [('status', 'OPERATION'), ('mode', 'HEAT'), ('fanSpeed', 'HIGH'), ('setTemp', 25), ('locked', True)])
def test_panel_reader_does_not_substitute_card_or_internal(field, value):
    from playwright.sync_api import sync_playwright
    import re
    namespace = {'re': re, '_CONTROLLER_BUTTONS': pipeline._CONTROLLER_BUTTONS}
    exec(pipeline._CONTROLLER_RESTORE_HELPERS, namespace)
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.route('**/*', lambda route: route.continue_() if route.request.url.startswith(('file:', 'data:')) else route.abort())
            page.goto(target.as_uri())
            page.locator('#device-card-1 .card-body-split').click()
            original = namespace['_controller_ui_fields'](page, 1)
            internal = page.evaluate('() => window.__vccs.devices[0]')
            if field == 'setTemp':
                page.locator('#det-temp-up-btn').click()
            else:
                page.locator(pipeline._CONTROLLER_BUTTONS[field][value]).click()
            assert namespace['_controller_ui_fields'](page, 1, 'panel')[field] == value
            assert namespace['_controller_ui_fields'](page, 1, 'card') == original
            assert page.evaluate('() => window.__vccs.devices[0]') == internal
        finally:
            browser.close()


@pytest.mark.parametrize('field,initial,requested,blocked', _CONTROL_SCENARIOS)
def test_controller_common_lifecycle_on_unmodified_product(tmp_path, monkeypatch, capsys, controller_observation,
                                                         field, initial, requested, blocked):
    case, plan = controller_lifecycle_fixture(field, initial, requested, blocked=blocked)
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, legacy_wording_checks=False,
        require_restore_plan_links=True, require_plan_fidelity=True, require_assertion_target_identity=True)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump_json(indent=2)
    code = compile_automation_candidate('LOCAL-CONTROLLER-LIFECYCLE', case, plan)
    assert all(c.status == CheckStatus.PASS for c in pipeline.evaluate_compiled_candidate(case, code))
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    before = target.read_bytes()
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'controller_candidate', 'exec'), namespace)
    namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    (tmp_path / 'execution.txt').write_text(output, encoding='utf-8')
    (tmp_path / 'candidate_tc.json').write_text(case.model_dump_json(indent=2), encoding='utf-8')
    (tmp_path / 'plan.json').write_text(plan.model_dump_json(indent=2), encoding='utf-8')
    (tmp_path / 'candidate.py').write_text(code, encoding='utf-8')
    assert 'CONTROLLER_ORIGINAL:' in output and 'CONTROLLER_PREPARED:' in output
    assert 'RESTORE_STATUS: RESTORED' in output
    assert 'RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091' in output
    assert 'RESTORE_MISMATCH' not in output and 'PRODUCT_MISMATCH' not in output
    observations = [json.loads(line.split(': ', 1)[1]) for line in output.splitlines()
                    if line.startswith('QA_ASSERTION_OBSERVED: ')]
    assert [row['assertion'] for row in observations] == [a.model_dump(mode='json') for a in plan.assertions]
    assert all(row['matched'] is True and 'actual' in row for row in observations)
    assert all(row['tc_id'] == case.tc_id and row['target_device_id'] == plan.target_device_id for row in observations)
    assert output.count('QA_ASSERTIONS_COMPLETE: ') == 1
    assert target.read_bytes() == before


@pytest.mark.parametrize('field,initial,requested', [
    ('status', 'STOP', 'OPERATION'), ('mode', 'COOL', 'HEAT'), ('fanSpeed', 'MED', 'LOW'),
    ('setTemp', 18, 24), ('locked', False, True),
])
@pytest.mark.parametrize('fault', ['UI', 'INTERNAL'])
@pytest.mark.parametrize('explicit', [False, True])
def test_controller_restoration_detects_each_layer_failure(tmp_path, monkeypatch, capsys, controller_observation,
                                                         field, initial, requested, fault, explicit):
    case, plan = controller_lifecycle_fixture(field, initial, requested)
    code = compile_automation_candidate('LOCAL-RESTORATION-FAULT', case, plan, explicit_expectations_only=explicit)
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'controller_fault', 'exec'), namespace)
    restore = namespace['_restore_controller']
    def broken_restore(page, device_id, original):
        restore(page, device_id, original)
        # Fault injection is test-only, AFTER a real UI restoration; never part
        # of the emitted candidate or the baseline HTML.
        if fault == 'INTERNAL':
            changed = {'status': 'OPERATION', 'mode': 'HEAT', 'fanSpeed': 'HIGH', 'setTemp': 19, 'locked': True}[field]
            assert original['state'][field] != changed
            page.evaluate('({id, field, value}) => { window.__vccs.devices.find(d => d.id === id)[field] = value; }',
                          {'id': device_id, 'field': field, 'value': changed})
        else:
            scripts = {
                'status': "card.classList.remove('state-stop');card.classList.add('state-run');",
                'mode': "card.classList.remove('mode-cool');card.classList.add('mode-heat');",
                'fanSpeed': "card.querySelector('.fan-speed-indicator').textContent='강풍';",
                'setTemp': "card.querySelector('.card-set-temp').textContent='19.0°C';",
                'locked': "card.classList.add('locked');",
            }
            page.evaluate("() => { const card = document.querySelector('#device-card-1'); " + scripts[field] + ' }')
    namespace['_restore_controller'] = broken_restore
    with pytest.raises(AssertionError, match='RESTORE_MISMATCH'):
        namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    (tmp_path / 'execution.txt').write_text(output, encoding='utf-8')
    assert 'ENVIRONMENT_RETIRED' in output and 'RESTORE_STATUS: FAILED' in output
    assert 'RESTORE_CONFIRMATIONS_VERIFIED' not in output
    assert 'PRODUCT_MISMATCH:' not in output


@pytest.mark.parametrize('field', ['status', 'mode', 'fanSpeed', 'setTemp', 'locked'])
def test_controller_read_only_never_writes(tmp_path, monkeypatch, capsys, controller_observation, field):
    initial = controller_observation.harness_values[f'window.__vccs.devices[0].{field}']
    case, plan = controller_lifecycle_fixture(field, initial, initial, read_only=True)
    check = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, legacy_wording_checks=False)
    assert check.status == CheckStatus.PASS, check.model_dump_json(indent=2)
    code = compile_automation_candidate('LOCAL-READ-ONLY', case, plan)
    # A helper definition may be emitted, but no write helper is called.
    assert '_restore_controller(page, 1,' not in code
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'controller_read_only', 'exec'), namespace)
    namespace['test_tc_cand_090']()
    assert 'RESTORE_STATUS: NOT_REQUIRED' in capsys.readouterr().out


@pytest.mark.parametrize('original_mode,original_locked', [('FAN', False), ('DRY', False), ('COOL', True), ('FAN', True)])
def test_controller_restores_dependency_state_set_through_ui(tmp_path, monkeypatch, capsys, controller_observation,
                                                           original_mode, original_locked):
    case, plan = controller_lifecycle_fixture('setTemp', 18, 25, prepare={'locked': False})
    code = compile_automation_candidate('LOCAL-DEPENDENCIES', case, plan)
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'dependency_candidate', 'exec'), namespace)
    capture = namespace['_controller_baseline']
    def environment_baseline(page, device_id):
        # Simulate a different initial environment entirely through real UI,
        # before the candidate records it. No HTML seed or internal setter.
        page.locator(pipeline._MODE_SELECTOR[original_mode]).click()
        page.locator(pipeline._CONTROLLER_BUTTONS['locked'][original_locked]).click()
        page.locator('.btn-apply-cmd').click()
        return capture(page, device_id)
    namespace['_controller_baseline'] = environment_baseline
    namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    (tmp_path / 'execution.txt').write_text(output, encoding='utf-8')
    assert 'RESTORE_STATUS: RESTORED' in output and 'RESTORE_MISMATCH' not in output


@pytest.mark.parametrize('fault', ['precondition', 'partial_preparation'])
def test_controller_recovers_before_test_starts(tmp_path, monkeypatch, capsys, controller_observation, fault):
    from playwright.sync_api import Locator
    case, plan = controller_lifecycle_fixture('fanSpeed', 'MED', 'HIGH')
    code = compile_automation_candidate('LOCAL-PREPARATION-FAULT', case, plan)
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'preparation_fault', 'exec'), namespace)
    if fault == 'precondition':
        wait = namespace['_wait_for_observations']
        namespace['_wait_for_observations'] = lambda page, observe: ['injected failed preparation proof'] if observe.__name__ == 'observe_preconditions' else wait(page, observe)
        error = AssertionError
    else:
        click = Locator.click
        injected = []
        def broken_click(locator, *args, **kwargs):
            result = click(locator, *args, **kwargs)
            if not injected and locator.get_attribute('id') == 'det-fan-med':
                injected.append(True)
                raise RuntimeError('injected interruption after pending preparation write')
            return result
        monkeypatch.setattr(Locator, 'click', broken_click)
        error = RuntimeError
    with pytest.raises(error):
        namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    assert 'RESTORE_STATUS: RESTORED' in output
    assert 'RESTORE_MISMATCH' not in output and 'RESTORE_CONFIRMATIONS_VERIFIED' not in output


@pytest.mark.parametrize('initial,requested,product_mismatch', [(30, 31, False), (16, 15, True)])
def test_controller_temperature_boundary_preserves_product_failure(tmp_path, monkeypatch, capsys, controller_observation,
                                                                 initial, requested, product_mismatch):
    case, plan = controller_lifecycle_fixture('setTemp', initial, requested, blocked=True, blocked_by_lock=False)
    check = pipeline.evaluate_checkpoint3_plan(case, plan, controller_observation, legacy_wording_checks=False,
                                             require_plan_fidelity=True)
    assert check.status == CheckStatus.PASS, check.model_dump_json(indent=2)
    code = compile_automation_candidate('LOCAL-TEMPERATURE-BOUNDARY', case, plan)
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'temperature_boundary', 'exec'), namespace)
    if product_mismatch:
        with pytest.raises(AssertionError, match='PRODUCT_MISMATCH'):
            namespace['test_tc_cand_090']()
    else:
        namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    (tmp_path / 'execution.txt').write_text(output, encoding='utf-8')
    assert 'RESTORE_STATUS: RESTORED' in output and 'RESTORE_MISMATCH' not in output


@pytest.mark.parametrize('unexpected_write', [False, True])
@pytest.mark.parametrize('explicit', [False, True])
def test_controller_blocked_without_preparation_cleans_pending_only(tmp_path, monkeypatch, capsys, controller_observation,
                                                                   unexpected_write, explicit):
    from playwright.sync_api import Locator
    case, plan = controller_lifecycle_fixture('fanSpeed', 'LOW', 'HIGH', blocked=True)
    plan.actions = [a for a in plan.actions if a.phase != AutomationPhase.PRECONDITION or a.action_type == AutomationActionType.SELECT_DEVICE]
    code = compile_automation_candidate('LOCAL-BLOCKED-ORIGINAL', case, plan, explicit_expectations_only=explicit)
    target = Path(__file__).resolve().parents[1] / 'product_baseline/virtual-controller.html'
    monkeypatch.setenv('QA_TARGET_URL', target.as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(code, 'blocked_original', 'exec'), namespace)
    capture, restore = namespace['_controller_baseline'], namespace['_restore_controller']
    def locked_environment(page, device_id):
        page.locator('#det-lock-on-btn').click()
        page.locator('.btn-apply-cmd').click()
        if unexpected_write:
            click = Locator.click
            injected = []
            def apply_with_fault(locator, *args, **kwargs):
                result = click(locator, *args, **kwargs)
                if not injected and 'btn-apply-cmd' in (locator.get_attribute('class') or ''):
                    injected.append(True)
                    page.evaluate("() => { window.__vccs.devices[0].fanSpeed = 'HIGH'; window.__vccs.renderGrid(); }")
                return result
            monkeypatch.setattr(Locator, 'click', apply_with_fault)
        return capture(page, device_id)
    restored = []
    def counted_restore(*args):
        restored.append(True)
        return restore(*args)
    namespace['_controller_baseline'], namespace['_restore_controller'] = locked_environment, counted_restore
    if unexpected_write:
        with pytest.raises(AssertionError, match='PRODUCT_MISMATCH'):
            namespace['test_tc_cand_090']()
    else:
        namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    assert bool(restored) == unexpected_write
    assert ('RESTORE_STATUS: RESTORED' if unexpected_write else 'RESTORE_STATUS: UNCHANGED') in output
    assert 'RESTORE_MISMATCH' not in output


@pytest.mark.parametrize('mutation', ['unknown_button', 'mixed_restore', 'missing_structure', 'legacy', 'missing_selection', 'wrong_phase', 'wrong_basis', 'missing_interface', 'extra_ui_field', 'duplicate_restore_control', 'duplicate_ui_target'])
def test_controller_common_contract_rejects_unsafe_plans(controller_observation, mutation):
    case, plan = controller_lifecycle_fixture('fanSpeed', 'MED', 'LOW')
    observation = controller_observation.model_copy(deep=True)
    if mutation == 'unknown_button':
        plan.actions[1].selector = '#det-purify-on-btn'
    elif mutation == 'mixed_restore':
        plan.actions.append(plan.actions[-1].model_copy(update={'action_id': 'ACT-099'}))
    elif mutation == 'missing_structure':
        case.restoration = None
    elif mutation == 'legacy':
        case.state_effect = None
    elif mutation == 'missing_selection':
        plan.actions.pop(0)
    elif mutation == 'wrong_phase':
        plan.actions[-1].phase = AutomationPhase.TEST
    elif mutation == 'wrong_basis':
        plan.restore_confirmations[0].comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    elif mutation == 'missing_interface':
        observation.elements = [e for e in observation.elements if e.selector != '#det-lock-off-btn']
    elif mutation in {'duplicate_restore_control', 'duplicate_ui_target'}:
        selector = '#det-lock-off-btn' if mutation == 'duplicate_restore_control' else '#device-card-1'
        next(e for e in observation.elements if e.selector == selector).match_count = 2
    else:
        plan.assertions[0].expected_fields[0].field_name = 'purify'
    result = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False)
    assert result.status == CheckStatus.FAIL


@pytest.mark.parametrize("output,exit_code,expected", [
    ("    assert not mismatches, 'PRODUCT_MISMATCH: ' + details\nE   AssertionError: RESTORE_MISMATCH: internal value differs", 1, TrialOutcome.AUTOMATION_ERROR),
    ('>   assert not mismatches, "PRODUCT_MISMATCH: " + details\nE   RuntimeError: failed', 1, TrialOutcome.AUTOMATION_ERROR),
    ("    # PRODUCT_MISMATCH: sample\nE   AssertionError: RESTORE_MISMATCH: UI differs", 1, TrialOutcome.AUTOMATION_ERROR),
    ("RuntimeError: failed while formatting PRODUCT_MISMATCH: details", 1, TrialOutcome.AUTOMATION_ERROR),
    ("E   AssertionError: PRODUCT_MISMATCH: ER-001 differs", 1, TrialOutcome.PRODUCT_MISMATCH_CANDIDATE),
    ("AssertionError: PRODUCT_MISMATCH: ER-002 differs", 1, TrialOutcome.PRODUCT_MISMATCH_CANDIDATE),
    ("PRODUCT_MISMATCH: blocked operation changed observed state", 1, TrialOutcome.PRODUCT_MISMATCH_CANDIDATE),
    ("E   AssertionError: PRODUCT_MISMATCH: ER-001 differs\nRESTORE_MISMATCH: internal value differs", 1, TrialOutcome.PRODUCT_MISMATCH_CANDIDATE),
    ("E   AssertionError: PRECONDITION_NOT_MET: LOW required\n    assert not mismatches, 'PRODUCT_MISMATCH: ' + details", 1, TrialOutcome.AUTOMATION_ERROR),
    ("PRODUCT_MISMATCH: unused diagnostic", 0, TrialOutcome.PASS),
])
def test_candidate_trial_classifies_runtime_markers_not_source(tmp_path, monkeypatch, output, exit_code, expected):
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def test_candidate():\n    pass\n", encoding="utf-8")
    target = tmp_path / "product.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setattr(pipeline_execution, "_run_trial_subprocess",
        lambda *args, **kwargs: SimpleNamespace(returncode=exit_code, stdout=output, stderr=""))
    result = run_candidate_trial(candidate, target, tmp_path / "evidence", timeout_seconds=10)
    assert result.outcome == expected
    # Classification does not discard restoration or product observations.
    assert (tmp_path / "evidence" / result.stdout_file).read_text(encoding="utf-8") == output


@pytest.mark.parametrize("identity", [1, 2, None])
@pytest.mark.parametrize("index", [0, 4])
def test_assertion_device_path_must_identify_plan_target(identity, index):
    case, plan, observation = structured_restoration_fixture()
    path = f"window.__vccs.devices[{index}]"
    plan.assertions[1].selector = path + ".enabled"
    observation.harness_values[path + ".enabled"] = False
    if identity is not None:
        observation.harness_values[path + ".id"] = identity
    old = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False)
    assert old.status == CheckStatus.PASS  # Stored historical contract is unchanged.
    current = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False,
                                                  require_assertion_target_identity=True)
    assert (current.status == CheckStatus.PASS) == (identity == plan.target_device_id)
    if identity != plan.target_device_id:
        assert "device index" in next(c.message for c in current.checks if c.rule_id == "CP3-004")


@pytest.mark.parametrize('selectors,harness,message', [
    ({'#unknown'}, set(), 'selector='), (set(), {'unknown'}, 'window.__vccs='),
    ({'#unknown'}, {'unknown'}, 'selector=.*window.__vccs='),
])
def test_inventory_unknown_interfaces_are_rejected_before_browser(selectors, harness, message):
    with pytest.raises(pipeline.Agent3Error, match=message):
        inspect_target_ui(REPO_ROOT / 'product_baseline/virtual-controller.html',
                          required_selectors=selectors, required_harness_keys=harness)


def test_inventory_missing_html_is_rejected_before_browser(tmp_path):
    with pytest.raises(pipeline.Agent3Error, match='existing local HTML'):
        inspect_target_ui(tmp_path / 'missing.html')


@pytest.mark.parametrize('mutation', ['none', 'precondition', 'sequence'])
def test_checkpoint3_proof_and_sequence_have_distinct_identifiers(mutation):
    case, plan, observation = precondition_guard_fixture()
    if mutation == 'precondition': plan.precondition_checks = []
    elif mutation == 'sequence':
        next(a for a in plan.actions if a.phase == pipeline.AutomationPhase.TEST).source_text = 'not in TC'
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    by_id = {c.rule_id: c for c in checkpoint.checks}
    assert len(by_id) == len(checkpoint.checks)
    assert by_id['CP3-006D'].status == (CheckStatus.FAIL if mutation == 'precondition' else CheckStatus.PASS)
    assert by_id['CP3-006A'].status == (CheckStatus.FAIL if mutation == 'sequence' else CheckStatus.PASS)

@pytest.mark.parametrize("mutation", ["none", "early_anchor", "restore_anchor", "omitted_operation", "earlier_observation", "changed_value", "missing_assertion", "write_tc"])
def test_terminal_observation_uses_last_test_action_without_invented_click(mutation):
    case, plan, observation = structured_restoration_fixture()
    case.state_effect = pipeline.TcStateEffect.READ_ONLY
    case.restore_required, case.restore_steps = False, []
    case.restoration.operation_steps, case.restoration.confirmations = [], []
    plan.actions, plan.restore_confirmations = plan.actions[:1], []
    case.steps = ["대상 장비를 선택한다."]
    action = plan.actions[0]
    action.action_type, action.selector, action.value = AutomationActionType.SELECT_DEVICE, "#device-card-1 .card-body-split", 1
    action.source_text = case.steps[0]
    case.expected_results[0].statement = "새 제어 스위치의 checked 값은 false이다."
    case.expected_results[1].statement = "내부 enabled 값은 false이다."
    for assertion in plan.assertions:
        assertion.expected_value = False
    read_step = "새 제어 스위치와 내부 enabled 값을 확인한다."
    case.steps.append(read_step)
    for result in case.expected_results:
        result.verify_after_step = read_step
    if mutation == "early_anchor":
        plan.actions.insert(0, plan.actions[0].model_copy(update={"action_id": "ACT-089"}))
        plan.assertions[0].after_action_id = "ACT-089"
    elif mutation == "restore_anchor":
        plan.actions.append(plan.actions[0].model_copy(update={"action_id": "ACT-099", "phase": AutomationPhase.RESTORE}))
        plan.assertions[0].after_action_id = plan.actions[-1].action_id
    elif mutation == "omitted_operation":
        case.steps.insert(-1, "새 제어 스위치를 해제한다.")
    elif mutation == "earlier_observation":
        case.steps.insert(0, case.steps.pop())
    elif mutation == "changed_value":
        plan.assertions[0].expected_value = True
    elif mutation == "missing_assertion":
        plan.assertions.pop()
    elif mutation == "write_tc":
        case.state_effect = pipeline.TcStateEffect.STATE_CHANGE
    legacy = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False)
    assert legacy.status == CheckStatus.FAIL
    current = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False,
                                       allow_terminal_observation_anchor=True)
    assert (current.status == CheckStatus.PASS) == (mutation == "none"), current.model_dump()
    if mutation == "none":
        code = compile_automation_candidate("RUN-20260924-120000-ABCDEF", case, plan)
        assert not any(c.status == CheckStatus.FAIL for c in evaluate_compiled_candidate(case, code))


@pytest.mark.parametrize("mutation", ["none", "selector", "source", "assertion", "expected_value", "restore", "restore_link"])
def test_new_wording_policy_preserves_execution_contract(mutation):
    case, plan, observation = structured_restoration_fixture()
    # UI metadata can be localized independently of the TC explanation.
    for element in observation.elements:
        element.text = "Localized caption"
        element.accessible_name = "Localized caption"
    if mutation == "selector":
        plan.actions[0].selector = "#unobserved"
    elif mutation == "source":
        plan.actions[0].source_text = "출처가 없는 조작"
    elif mutation == "assertion":
        plan.assertions.pop()
    elif mutation == "expected_value":
        plan.assertions[0].expected_value = "INVENTED"
    elif mutation == "restore":
        plan.actions.pop()
    elif mutation == "restore_link":
        plan.restore_confirmations.pop()
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, observation, legacy_wording_checks=False)
    assert (cp.status == CheckStatus.PASS) == (mutation == "none"), cp.model_dump()


@pytest.mark.parametrize("wording", [
    "실행 전 관찰값과 같은지 확인한다.", "처음 저장해 둔 상태로 돌아왔는지 살펴본다.",
    "시작 직전의 측정 결과와 대조합니다.", "Compare with the original captured value.",
    "복구 완료 뒤 원상태 일치 여부 점검", "기록해 둔 초기 관측치와 비교",
])
def test_structured_restoration_does_not_parse_description_vocabulary(wording):
    case, plan, observation = structured_restoration_fixture(wording)
    assert pipeline._structured_restoration_errors(case) == []
    assert pipeline._tc_restore_basis_errors(case) == []
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump()
    code = compile_automation_candidate("RUN-20260922-120000-ABCDEF", case, plan)
    assert "RESTORE_CONFIRMATIONS_VERIFIED" in code
    assert not any(c.status == CheckStatus.FAIL for c in evaluate_compiled_candidate(case, code))


@pytest.mark.parametrize("mutation", ["missing_link", "basis", "wrong_id", "excerpt", "no_restore",
                                    "no_reader", "new_action", "changed_source"])
def test_structured_restore_plan_rejects_execution_contract_changes(mutation):
    case, plan, observation = structured_restoration_fixture()
    if mutation == "missing_link":
        plan.restore_confirmations.pop()
    elif mutation == "basis":
        plan.restore_confirmations[0].comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    elif mutation == "wrong_id":
        plan.restore_confirmations[0].result_ids = ["ER-999"]
    elif mutation == "excerpt":
        plan.restore_confirmations[0].comparisons[0].source_excerpt = "관찰값"
    elif mutation == "no_restore":
        plan.actions.pop()
    elif mutation == "no_reader":
        plan.assertions.pop()
    elif mutation == "new_action":
        plan.actions[-1].source_text = case.restore_steps[-1]
    else:
        plan.restore_confirmations[0].source_text += " 바꿈"
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    assert checkpoint.status == CheckStatus.FAIL
    with pytest.raises(pipeline.Agent3Error):
        compile_automation_candidate("RUN-20260922-120000-ABCDEF", case, plan)


@pytest.mark.parametrize("broken", [False, True])
def test_structured_restoration_executes_real_baseline_comparison(tmp_path, monkeypatch, capsys, broken):
    case, plan, _ = structured_restoration_fixture()
    code = compile_automation_candidate("RUN-20260922-120000-ABCDEF", case, plan)
    target = tmp_path / "switch.html"
    handler = "true" if broken else "this.checked"
    _write_text_atomic(target, '<input id="new-feature-toggle" type="checkbox" onchange="window.__vccs.feature.enabled='
        + handler + '"><script>window.__vccs={feature:{enabled:false}};</script>')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "structured_restoration", "exec"), namespace)
    if broken:
        with pytest.raises(AssertionError):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: " + ("FAILED" if broken else "RESTORED") in output
    assert ("RESTORE_CONFIRMATIONS_VERIFIED" in output) is not broken
    if broken:
        assert "ENVIRONMENT_RETIRED" in output


@pytest.mark.parametrize("basis", ["시험 전", "시험 시작 전", "실행 시작 직전", "시험 직전", "실행 전"])
@pytest.mark.parametrize("target", ["풍량 표시", "설정 온도 표시", "운전 모드 표시", "잠금 상태 표시", "조회 결과 표시"])
def test_cp2_cp3_share_baseline_vocabulary_across_observation_targets(basis, target):
    from qa_pipeline_agent2 import _tc_restore_basis_errors, _tc_procedure_detail_errors
    case, plan, observation = mixed_restore_comparison_fixture()
    # Change only presentation wording; typed reader, expected value and actual
    # compiler binding remain identical. No product scenario result is invented.
    case = type(case).model_validate_json(case.model_dump_json().replace("풍량 표시", target).replace("실행 전", basis))
    plan = type(plan).model_validate_json(plan.model_dump_json().replace("풍량 표시", target).replace("실행 전", basis))
    assert not _tc_restore_basis_errors(case)
    assert not _tc_procedure_detail_errors(case)
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_comparison_basis=True)
    assert cp.status == CheckStatus.PASS, [c.message for c in cp.checks if c.status == CheckStatus.FAIL]


@pytest.mark.parametrize("basis", ["시험 시작 후", "실행 종료 후", "다음 시험 전", "시험 시작 전과 다른 상태"])
def test_shared_baseline_does_not_approve_wrong_comparison(basis):
    case, plan, observation = mixed_restore_comparison_fixture()
    case = type(case).model_validate_json(case.model_dump_json().replace("실행 전 상태", basis))
    plan = type(plan).model_validate_json(plan.model_dump_json().replace("실행 전 상태", basis))
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_comparison_basis=True)
    assert cp.status == CheckStatus.FAIL


@pytest.mark.parametrize("scenario", ["change", "blocked", "blocked_bug", "prepare_failure",
    "partial_prepare_failure", "restore_failure", "original_fan", "original_dry"])
def test_hvac_preparation_restores_original_not_prepared_state(tmp_path, monkeypatch, capsys, scenario):
    case, plan, observation = hvac_preparation_restoration_fixture()
    if scenario == "change":
        case.state_effect = pipeline.TcStateEffect.STATE_CHANGE
        for result, assertion in zip(case.expected_results, plan.assertions):
            result.statement = result.statement.replace("18", "17")
            assertion.expected_number = 17
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation,
        require_restore_plan_links=True, require_restore_comparison_basis=True)
    assert checkpoint.status == CheckStatus.PASS, checkpoint.model_dump_json()
    code = compile_automation_candidate("RUN-20260920-120000-ABCDEF", case, plan)
    assert all(c.status == CheckStatus.PASS for c in evaluate_compiled_candidate(case, code))
    initial_mode = {"original_fan": "FAN", "original_dry": "DRY"}.get(scenario, "COOL")
    # Controlled test product, not the approved controller: inject a different
    # product/prepare/restore failure while keeping the compiler and plan real.
    html = '''<!doctype html><div id="device-card-1"><button class="card-body-split"
      onclick="window.__vccs.selectedUnitId=1">장비</button></div>
    <button id="det-mode-cool" onclick="setMode('COOL')">냉방</button>
    <button id="det-mode-auto" onclick="setMode('AUTO')">자동</button>
    <button id="det-mode-fan" onclick="setMode('FAN')">송풍</button>
    <button id="det-mode-dry" onclick="setMode('DRY')">제습</button>
    <span id="det-temp-display">24</span>
    <button id="det-temp-down-btn" onclick="step(-1)">감소</button>
    <button id="det-temp-up-btn" onclick="step(1)">증가</button>
    <button class="btn-apply-cmd" onclick="apply()">적용</button>
    <script>
    const scenario=SCENARIO, initialMode=INITIAL_MODE;
    window.__vccs={selectedUnitId:1, devices:[{id:1,mode:initialMode,setTemp:24}]};
    let mode=initialMode, temp=24, writes=0;
    function show(){document.querySelector('#det-temp-display').textContent=temp;}
    function setMode(value){mode=value;}
    function step(delta){
      if(scenario==='partial_prepare_failure' && writes===0 && mode==='AUTO' && temp<=20 && delta<0)return;
      if(!['change','blocked_bug'].includes(scenario) && mode==='AUTO' && temp<=18 && delta<0)return;
      temp+=delta;show();
    }
    function apply(){
      writes++;
      if(scenario==='prepare_failure' && writes===1)return;
      if(scenario==='restore_failure' && writes>=3)return;
      window.__vccs.devices[0].mode=mode;
      if(!['FAN','DRY'].includes(mode))window.__vccs.devices[0].setTemp=temp;
    }
    </script>'''.replace("SCENARIO", repr(scenario)).replace("INITIAL_MODE", repr(initial_mode))
    target = tmp_path / "preparation.html"
    _write_text_atomic(target, html)
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "hvac_preparation", "exec"), namespace)
    if scenario in {"blocked_bug", "prepare_failure", "partial_prepare_failure", "restore_failure"}:
        with pytest.raises((AssertionError, RuntimeError)):
            namespace["test_tc_cand_003"]()
    else:
        namespace["test_tc_cand_003"]()
    output = capsys.readouterr().out
    assert "RESTORE_STATUS: " + ("FAILED" if scenario == "restore_failure" else "RESTORED") in output
    assert ("PRODUCT_MISMATCH: blocked operation" in output) == (scenario == "blocked_bug")
    if scenario == "restore_failure":
        assert "ENVIRONMENT_RETIRED:" in output
    assert (tmp_path / "evidence" / "trial-trace.zip").is_file()


@pytest.mark.parametrize("original_mode", ["COOL", "FAN", "DRY"])
def test_hvac_preparation_on_controller_copy(tmp_path, monkeypatch, capsys, original_mode):
    case, plan, observation = hvac_preparation_restoration_fixture()
    case.state_effect = pipeline.TcStateEffect.STATE_CHANGE
    for result, assertion in zip(case.expected_results, plan.assertions):
        result.statement = result.statement.replace("18", "17")
        assertion.expected_number = 17
    target_source = REPO_ROOT / "product_baseline" / "virtual-controller.html"
    original_hash = _sha256_file(target_source)
    target = tmp_path / "controller.html"
    _write_text_atomic(target, target_source.read_text(encoding="utf-8").replace(
        "setTemp: 24, mode: 'COOL'", f"setTemp: 24, mode: '{original_mode}'", 1))
    code = compile_automation_candidate("RUN-20260920-120000-ABCDEF", case, plan)
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "controller_preparation", "exec"), namespace)
    namespace["test_tc_cand_003"]()
    assert "RESTORE_STATUS: RESTORED" in capsys.readouterr().out
    assert _sha256_file(target_source) == original_hash


@pytest.mark.parametrize("mutation", ["missing_inverse", "uncovered_write", "prepared_comparison", "selection_after_write"])
def test_hvac_preparation_rejects_unproved_recovery(mutation):
    case, plan, observation = hvac_preparation_restoration_fixture()
    if mutation == "missing_inverse":
        case.test_data.restore_observed_hvac_state = False
    elif mutation == "uncovered_write":
        plan.actions[1].action_type = AutomationActionType.CLICK
    elif mutation == "selection_after_write":
        plan.actions[0], plan.actions[1] = plan.actions[1], plan.actions[0]
    else:
        plan.restore_confirmations[0].comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    assert any(c.rule_id == "CP3-006C" and c.status == CheckStatus.FAIL for c in checkpoint.checks)
    with pytest.raises(pipeline.Agent3Error, match="상태 복원 정책"):
        compile_automation_candidate("RUN-20260920-120000-ABCDEF", case, plan)


@pytest.mark.parametrize("scenario", ["change", "read", "read_precondition_failure", "blocked", "blocked_bug", "restore_failure", "test_and_restore_failure", "precondition_failure"])
def test_state_restoration_policy_in_real_browser(tmp_path, monkeypatch, capsys, scenario):
    case, plan, observation = precondition_guard_fixture()
    case.state_effect = pipeline.TcStateEffect.STATE_CHANGE
    handler = "window.__vccs.feature.enabled=this.checked"
    if scenario in {"read", "read_precondition_failure"}:
        case.state_effect = pipeline.TcStateEffect.READ_ONLY
        case.restore_required, case.restore_steps, plan.actions = False, [], []
        for assertion in plan.assertions:
            assertion.expected_value = False
        if scenario == "read_precondition_failure":
            plan.precondition_checks[0].expected_value = True
    elif scenario in {"blocked", "blocked_bug"}:
        case.state_effect = pipeline.TcStateEffect.BLOCKED_CHANGE
        for assertion in plan.assertions:
            assertion.expected_value = False
        # click permits a blocked checkbox to stay unchecked (Playwright.check
        # itself raises when a product correctly refuses to change it).
        plan.actions[0].action_type = AutomationActionType.CLICK
        if scenario == "blocked":
            handler = "this.checked=false; window.__vccs.feature.enabled=false"
    elif scenario in {"restore_failure", "test_and_restore_failure"}:
        handler = "window.__vccs.feature.enabled=true"
        if scenario == "test_and_restore_failure":
            plan.assertions[0].expected_value = False
    elif scenario == "precondition_failure":
        plan.precondition_checks[0].expected_value = True
    code = compile_automation_candidate("RUN-20260920-120000-ABCDEF", case, plan)
    assert not any(check.status == CheckStatus.FAIL for check in evaluate_compiled_candidate(case, code))
    target = tmp_path / "switch.html"
    _write_text_atomic(target, '<!doctype html><input id="new-feature-toggle" type="checkbox" onchange="' + handler + '">'
                       '<script>window.__vccs={feature:{enabled:false}};</script>')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "state_policy", "exec"), namespace)
    if scenario in {"blocked_bug", "restore_failure", "test_and_restore_failure", "precondition_failure", "read_precondition_failure"}:
        with pytest.raises(AssertionError):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    status = {"change": "RESTORED", "read": "NOT_REQUIRED", "read_precondition_failure": "NOT_REQUIRED", "blocked": "UNCHANGED",
              "blocked_bug": "RESTORED", "restore_failure": "FAILED",
              "test_and_restore_failure": "FAILED", "precondition_failure": "NOT_STARTED"}[scenario]
    assert "RESTORE_STATUS: " + status in output
    if scenario == "blocked_bug":
        assert "PRODUCT_MISMATCH: blocked operation" in output
    if "restore_failure" in scenario:
        assert "RESTORE_MISMATCH:" in output
        assert "ENVIRONMENT_RETIRED:" in output
    assert (tmp_path / "evidence" / "trial-trace.zip").is_file()


@pytest.mark.parametrize("mutation", ["read_mutates", "missing_restore", "preparation_mutates", "no_state_reader", "blocked_only_enabled"])
def test_state_restoration_policy_rejects_unsafe_plans(mutation):
    case, plan, observation = precondition_guard_fixture()
    case.state_effect = pipeline.TcStateEffect.STATE_CHANGE
    if mutation == "read_mutates":
        case.state_effect = pipeline.TcStateEffect.READ_ONLY
        case.restore_required, case.restore_steps = False, []
        plan.actions = plan.actions[:1]
    elif mutation == "missing_restore":
        plan.actions = plan.actions[:1]
    elif mutation == "preparation_mutates":
        plan.actions[0].phase = AutomationPhase.PRECONDITION
    elif mutation == "blocked_only_enabled":
        case.state_effect = pipeline.TcStateEffect.BLOCKED_CHANGE
        plan.assertions = [plan.assertions[0].model_copy(update={"strategy": pipeline.AssertionStrategy.UI_ENABLED_EQUALS})]
    else:
        plan.assertions = []
    result = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    assert any(c.rule_id == "CP3-006C" and c.status == CheckStatus.FAIL for c in result.checks)
    with pytest.raises(pipeline.Agent3Error, match="상태 복원 정책"):
        compile_automation_candidate("RUN-20260920-120000-ABCDEF", case, plan)


@pytest.mark.parametrize("statement,value,valid", [
    ("카드에 중풍이 표시된다.", "중풍", True),
    ("카드에 중풍이 표시된다.", "풍", False),
    ("카드에 중풍이 표시된다.", "중", False),
    ("상태는 OFF이다.", "OFF", True),
    ("상태는 OFF이다.", "OF", False),
    ("등급은 A로 표시된다.", "A", True),
    ("등급은 가로 표시된다.", "가", True),
    ("메시지는 '처리 완료'로 표시된다.", "처리 완료", True),
])
def test_agent3_complete_text_value_boundaries(statement, value, valid):
    assert pipeline._complete_text_value(statement, value) is valid


@pytest.mark.parametrize("mutation", ["none", "reverse", "omit_reset"])
def test_agent3_temperature_plan_preserves_approved_step_order(mutation):
    case, plan = grouped_agent3_case_and_plan()
    observation = agent3_observation()
    if mutation == "reverse":
        setup = [item for item in plan.actions if item.phase == AutomationPhase.PRECONDITION]
        by_id = {item.action_id: item for item in plan.actions}
        plan.actions = setup + [by_id[f"ACT-{n:03d}"] for n in (9, 10, 7, 8, 5, 6)]
    elif mutation == "omit_reset":
        plan.actions = [item for item in plan.actions if item.action_id not in {"ACT-007", "ACT-008"}]
    result = pipeline.evaluate_checkpoint3_plan(case, plan, observation,
        require_precondition_proof=False)
    assert (result.status == CheckStatus.PASS) is (mutation == "none")


@pytest.mark.parametrize("source,allowed", [
    ("중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다.", ["error_free", "unlocked"]),
    ("대상 장비가 온라인이고 오류가 없으며 잠금 해제 상태이다.", ["target_device_visible", "error_free", "unlocked", "online"]),
    ("첫 실행 기본 상태인 LOW 풍량을 확인한다.", []),
    ("설정 온도 18°C를 확인한다.", []),
    ("새 제어 스위치의 enabled 값은 false이다.", []),
    ("관리자 로그인 후 대상 장비가 온라인이다.", []),
    ("device is online with no error and unlocked", ["target_device_visible", "error_free", "unlocked", "online"]),
])
def test_agent3_context_bindings_are_source_specific_and_do_not_mutate_tc(source, allowed):
    case = agent3_test_case().model_copy(update={"preconditions": [source]})
    observation = agent3_observation()
    observation.verified_execution_context = observation.verified_execution_context.model_copy(update={
        "device_state_available": True, "target_device_visible": True,
        "error_free": True, "unlocked": True, "online": True,
    })
    before = case.model_dump_json(), observation.model_dump_json()
    payload = build_agent3_model_input(case, observation, {})
    assert payload["precondition_context_bindings"] == [{
        "source_text": source, "allowed_baseline_context_selectors": allowed}]
    assert (case.model_dump_json(), observation.model_dump_json()) == before


@pytest.mark.parametrize("state_available", [True, False])
def test_agent3_context_bindings_preserve_false_observations_without_inventing_evidence(state_available):
    case = agent3_test_case().model_copy(update={"preconditions": ["오류와 잠금이 없는 단일 장비를 대상으로 한다."]})
    observation = agent3_observation()
    observation.verified_execution_context = observation.verified_execution_context.model_copy(update={
        "device_state_available": state_available, "error_free": False, "unlocked": None})
    payload = build_agent3_model_input(case, observation, {})
    assert payload["precondition_context_bindings"][0]["allowed_baseline_context_selectors"] == (
        ["error_free"] if state_available else [])
    assert payload["ui_observation"]["verified_execution_context"]["error_free"] is False


def test_agent3_sends_context_bindings_and_action_only_repair_guidance_without_weakening_cp():
    source = "중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다."
    case = agent3_test_case().model_copy(update={"preconditions": [source]})
    observation = agent3_observation()
    observation.verified_execution_context = observation.verified_execution_context.model_copy(update={
        "device_state_available": True, "target_device_visible": True, "error_free": True, "unlocked": True})
    expected = json.dumps(build_agent3_model_input(case, observation, {})["precondition_context_bindings"], ensure_ascii=False, indent=2)
    responses = Agent3FakeResponses()
    agent = OpenAIAgent3(model="test-model", client=SimpleNamespace(responses=responses))
    agent.plan(case, observation, {})
    assert expected in responses.kwargs["input"][1]["content"]
    plan = agent3_plan()
    plan.precondition_checks = [pipeline.PreconditionCheck(source_text=source, read_kind="BASELINE_CONTEXT", selector=name, expected_value=True)
        for name in ["error_free", "unlocked", "target_device_visible"]]
    errors_before = pipeline._precondition_proof_errors(case, plan, observation)
    assert any("target_device_visible" in error for error in errors_before)
    before = plan.model_dump_json()
    agent.plan(case, observation, {}, previous_plan=plan, checkpoint_feedback=["ACT-001: observed element does not support CLICK"])
    repair = responses.kwargs["input"][1]["content"]
    assert expected in repair
    assert "When feedback concerns only Action mapping" in repair
    assert "precondition_checks, assertions and restore_confirmations unchanged" in repair
    assert plan.model_dump_json() == before
    assert pipeline._precondition_proof_errors(case, plan, observation) == errors_before


@pytest.mark.parametrize("connector", ["확인하고,", "확인하며,", "확인한다."])
@pytest.mark.parametrize("failure", [None, "ui", "internal"])
def test_explicit_restore_basis_checks_display_and_internal_separately(tmp_path, monkeypatch, capsys, connector, failure):
    case, plan, observation = mixed_restore_comparison_fixture(connector)
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_comparison_basis=True)
    assert cp.status == CheckStatus.PASS, [c.message for c in cp.checks if c.status == CheckStatus.FAIL]
    code = compile_automation_candidate("RUN-20260916-130000-ABCDEF", case, plan)
    target = tmp_path / "mixed.html"
    ui_guard = "if(this.value!=='LOW')" if failure == "ui" else ""
    internal_guard = "if(this.value!=='LOW')" if failure == "internal" else ""
    _write_text_atomic(target, f'''<!doctype html><span id="feature-label">약풍</span>
      <input id="new-feature-toggle" value="LOW" oninput="{ui_guard}document.querySelector('#feature-label').textContent=this.value==='MED'?'중풍':'약풍';{internal_guard}window.__vccs.feature.fanSpeed=this.value">
      <script>window.__vccs={{feature:{{fanSpeed:'LOW'}}}};</script>''')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "mixed_restore", "exec"), namespace)
    if failure:
        with pytest.raises(AssertionError, match="RESTORE_MISMATCH"):
            namespace["test_tc_cand_090"]()
        assert "RESTORE_CONFIRMATIONS_VERIFIED" not in capsys.readouterr().out
    else:
        namespace["test_tc_cand_090"]()
        assert "RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091" in capsys.readouterr().out


@pytest.mark.parametrize("mutation", ["missing", "duplicate", "wrong_er", "wrong_basis", "ui_code", "uncovered",
    "changed_excerpt", "other_target", "negation", "wrong_value", "fake_action", "missing_action", "cross_clause"])
def test_explicit_restore_basis_rejects_ungrounded_or_missing_comparisons(mutation):
    case, plan, observation = mixed_restore_comparison_fixture()
    link = plan.restore_confirmations[0]
    if mutation == "missing":
        link.comparisons.clear()
    elif mutation == "duplicate":
        link.comparisons.append(link.comparisons[0].model_copy())
    elif mutation == "wrong_er":
        link.comparisons[0].result_id = "ER-999"
    elif mutation == "wrong_basis":
        link.comparisons[0].basis = pipeline.RestoreComparisonBasis.PROVED_INITIAL
    elif mutation == "changed_excerpt":
        link.comparisons[0].source_excerpt += " 변조"
    elif mutation == "fake_action":
        plan.actions.append(plan.actions[-1].model_copy(update={"action_id":"ACT-092", "source_text":link.source_text}))
    elif mutation == "missing_action":
        plan.actions.pop()
    else:
        old = link.comparisons[0].source_excerpt
        new = {"ui_code": "복원 후 풍량 표시가 LOW인지 확인하고,",
               "uncovered": old + " 새 알림도 확인한다.",
               "other_target": old.replace("풍량 표시", "다른 장비 표시"),
               "negation": old.replace("같은지", "다른지"),
               "wrong_value": old.replace("실행 전 상태", "HIGH"),
               "cross_clause": "복원 후 풍량 표시가 LOW인지 확인하고,"}[mutation]
        case.restore_steps[-1] = link.source_text = link.source_text.replace(old, new)
        if mutation != "uncovered":
            link.comparisons[0].source_excerpt = new
        if mutation == "cross_clause":
            old_internal = link.comparisons[1].source_excerpt
            new_internal = old_internal.replace("초기값 LOW", "실행 전 상태")
            case.restore_steps[-1] = link.source_text = link.source_text.replace(old_internal, new_internal)
            link.comparisons[1].source_excerpt = new_internal
            link.comparisons[1].basis = pipeline.RestoreComparisonBasis.OBSERVED_BASELINE
    cp = pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_comparison_basis=True)
    assert cp.status == CheckStatus.FAIL
    assert any(c.rule_id == "CP3-006B" and c.status == CheckStatus.FAIL for c in cp.checks)
    if mutation != "missing_action":
        assert not any("approved step is missing" in c.message for c in cp.checks)


@pytest.mark.parametrize("mutation", [None, "missing", "wrong_id", "duplicate_id", "duplicate_line", "changed_source", "extra_line", "missing_target", "new_target", "wrong_value", "negated", "fake_action"])
def test_restore_plan_links_preserve_sources_targets_and_fail_closed(mutation):
    case, plan, observation = _restoration_detail_fixture()
    line = "복원 후 새 제어 스위치와 내부 enabled 값을 실행 전 확인한 상태와 비교해 일치하는지 확인한다."
    case.restore_steps.append(line)
    link = pipeline.RestoreConfirmation(source_text=line, result_ids=[r.result_id for r in case.expected_results])
    plan.restore_confirmations = [link]
    if mutation == "missing":
        plan.restore_confirmations = []
    elif mutation == "wrong_id":
        link.result_ids[0] = "ER-999"
    elif mutation == "duplicate_id":
        link.result_ids.append(link.result_ids[0])
    elif mutation == "duplicate_line":
        plan.restore_confirmations.append(link.model_copy(deep=True))
    elif mutation == "changed_source":
        link.source_text += " 새 문장"
    elif mutation == "extra_line":
        plan.restore_confirmations.append(link.model_copy(update={"source_text": "추가 검사"}))
    elif mutation == "missing_target":
        link.result_ids.pop()
    elif mutation == "new_target":
        case.restore_steps[-1] = link.source_text = line.replace("상태와", "상태 및 새 알림과")
    elif mutation == "wrong_value":
        case.restore_steps[-1] = link.source_text = line.replace("상태와", "상태 및 HIGH와")
    elif mutation == "negated":
        case.restore_steps[-1] = link.source_text = line.replace("일치하는지", "불일치하는지")
    elif mutation == "fake_action":
        plan.actions.append(plan.actions[-1].model_copy(update={"action_id": "ACT-092", "source_text": line}))
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_plan_links=True)
    assert checkpoint.status == (CheckStatus.PASS if mutation is None else CheckStatus.FAIL)
    if mutation is None:
        code = compile_automation_candidate("RUN-20260916-130000-ABCDEF", case, plan)
        assert "RESTORE_CONFIRMATIONS_VERIFIED" in code
        assert "restore_actual != restore_baseline_" in code
        assert pipeline.Agent3AutomationPlan.model_validate_json(plan.model_dump_json()) == plan
    elif plan.restore_confirmations:
        with pytest.raises(pipeline.Agent3Error, match="복원 확인 계획"):
            compile_automation_candidate("RUN-20260916-130000-ABCDEF", case, plan)


@pytest.mark.parametrize("wording", [
    "복원 후 새 제어 스위치와 내부 enabled 값을 실행 전 확인한 상태와 비교해 일치하는지 확인한다.",
    "복원 후 새 제어 스위치와 내부 enabled 값을 시험 전 관찰한 상태와 비교해 일치하는지 확인한다.",
    "복원 후 새 제어 스위치와 내부 enabled 값을 실행 전 기록한 상태와 비교해 일치하는지 확인한다.",
])
def test_restore_links_accept_observed_initial_state_wording(wording):
    case, plan, observation = _restoration_detail_fixture()
    case.restore_steps.append(wording)
    plan.restore_confirmations = [pipeline.RestoreConfirmation(source_text=wording,
        result_ids=[r.result_id for r in case.expected_results])]
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_plan_links=True).status == CheckStatus.PASS


def _restoration_detail_fixture():
    case, plan, observation = precondition_guard_fixture()
    for result, target in zip(case.expected_results, ["새 제어 스위치", "내부 enabled 값"]):
        result.observation_target = target
        result.verify_after_step = case.steps[0]
    for assertion in plan.assertions:
        assertion.after_action_id = "ACT-090"
    return case, plan, observation


@pytest.mark.parametrize("feature,initial,changed", [
    ("풍량", "LOW", "MED"), ("온도", "18", "24"), ("모드", "AUTO", "HEAT"),
])
@pytest.mark.parametrize("restore_broken", [False, True])
@pytest.mark.parametrize("detailed", [False, True])
@pytest.mark.parametrize("explicit_basis", [False, True])
def test_restore_linked_browser_comparisons_across_control_values(tmp_path, monkeypatch, capsys, feature, initial, changed, restore_broken, detailed, explicit_basis):
    case, plan, observation = _restoration_detail_fixture()
    ui_target, internal_target = f"{feature} 입력란", f"내부 {feature} value 값"
    case.preconditions = [f"{ui_target}의 초기값은 {initial}이고 {internal_target}은 {initial}이다."]
    case.steps = [f"{ui_target}에 {changed}를 입력한다."]
    operation = f"{ui_target}에 {initial}를 입력해 복원한다."
    confirmation = f"복원 후 {ui_target}과 {internal_target}을 실행 전 확인한 상태와 비교해 일치하는지 확인한다."
    if detailed:
        confirmation = f"복원 후 {ui_target}에서 {feature} 표시가 실행 전 확인한 {initial} {feature} 상태와 같은지, {internal_target}이 {initial}인지 확인한다."
    case.restore_steps = [operation, confirmation]
    case.expected_results[0].statement = f"{ui_target}의 값은 {changed}이다."
    case.expected_results[1].statement = f"{internal_target}은 {changed}이다."
    for result, target in zip(case.expected_results, [ui_target, internal_target]):
        result.observation_target, result.verify_after_step = target, case.steps[0]
    plan.actions = [AutomationAction(action_id=f"ACT-{90+i:03}", phase=phase, action_type="FILL",
        selector="#new-feature-toggle", value=value, source_text=source)
        for i, (phase, value, source) in enumerate([("TEST", changed, case.steps[0]), ("RESTORE", initial, operation)])]
    plan.assertions[0].strategy = pipeline.AssertionStrategy.UI_VALUE_EQUALS
    plan.assertions[0].expected_value = changed
    plan.assertions[1].expected_value = changed
    plan.assertions[1].selector = "window.__vccs.feature.value"
    plan.precondition_checks = [pipeline.PreconditionCheck(source_text=case.preconditions[0],
        read_kind="UI_VALUE", selector="#new-feature-toggle", expected_value=initial),
        pipeline.PreconditionCheck(source_text=case.preconditions[0], read_kind="INTERNAL_VALUE",
            selector="window.__vccs.feature.value", expected_value=initial)]
    plan.restore_confirmations = [pipeline.RestoreConfirmation(source_text=confirmation,
        result_ids=[r.result_id for r in case.expected_results])]
    if explicit_basis:
        # Exercise the new lifecycle with fan/temperature/mode values, while
        # the other half retains historical artifact compiler coverage.
        case.state_effect = pipeline.TcStateEffect.STATE_CHANGE
        ui_clause = f"복원 후 {ui_target}이 실행 전 상태와 같은지 확인하고,"
        internal_clause = f"{internal_target}이 초기값 {initial}와 같은지 확인한다."
        if detailed:
            ui_clause = f"복원 후 {ui_target}에서 {feature} 표시가 실행 전 확인한 상태와 같은지 확인하며,"
        case.restore_steps[-1] = plan.restore_confirmations[0].source_text = ui_clause + " " + internal_clause
        plan.restore_confirmations[0].comparisons = [
            pipeline.RestoreComparison(result_id=case.expected_results[0].result_id, source_excerpt=ui_clause, basis="OBSERVED_BASELINE"),
            pipeline.RestoreComparison(result_id=case.expected_results[1].result_id, source_excerpt=internal_clause, basis="PROVED_INITIAL")]
    observation.harness_values = {"window.__vccs.feature.value": initial}
    observation.elements[-1].text = ui_target
    observation.elements[-1].action_hint = "FILL"
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_plan_links=True)
    assert checkpoint.status == CheckStatus.PASS, [item.message for item in checkpoint.checks if item.status == CheckStatus.FAIL]
    code = compile_automation_candidate("RUN-20260916-130000-ABCDEF", case, plan)
    target = tmp_path / "control.html"
    # A deliberately faulty product updates the TEST value but ignores the restore value.
    handler = (f"if(this.value!=={json.dumps(initial)})" if restore_broken else "")
    _write_text_atomic(target, f'''<!doctype html><input id="new-feature-toggle" value="{initial}"
      oninput='{handler}window.__vccs.feature.value=this.value'><script>
      window.__vccs={{feature:{{value:{json.dumps(initial)}}}}};</script>''')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "linked_restore", "exec"), namespace)
    if restore_broken:
        with pytest.raises(AssertionError, match="RESTORE_MISMATCH"):
            namespace["test_tc_cand_090"]()
        assert "RESTORE_CONFIRMATIONS_VERIFIED" not in capsys.readouterr().out
    else:
        namespace["test_tc_cand_090"]()
        assert "RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091" in capsys.readouterr().out


@pytest.mark.parametrize("initial,changed", [(a, b) for a in ("LOW", "MED", "HIGH")
                                           for b in ("LOW", "MED", "HIGH") if a != b])
@pytest.mark.parametrize("fault", [None, "UI", "INTERNAL_STATE"])
def test_product_fan_transitions_share_dual_restoration(tmp_path, monkeypatch, capsys, initial, changed, fault):
    case, plan, observation = fan_transition_restoration_fixture(initial, changed)
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation,
        require_restore_plan_links=True, legacy_wording_checks=False)
    assert checkpoint.status == CheckStatus.PASS, [c.message for c in checkpoint.checks if c.status == CheckStatus.FAIL]
    code = compile_automation_candidate("RUN-20260925-130000-ABCDEF", case, plan)
    # Only the temporary product's initial data changes; the actual test and
    # restoration still use the real UI and the unmodified shared compiler.
    html = (REPO_ROOT / "product_baseline" / "virtual-controller.html").read_text(encoding="utf-8")
    seed = "{ id: 1, name: 'IDU-00', status: 'STOP', currentTemp: 25.0, setTemp: 24, mode: 'COOL', fanSpeed: 'LOW'"
    assert html.count(seed) == 1
    html = html.replace(seed, seed.replace("fanSpeed: 'LOW'", f"fanSpeed: '{initial}'"), 1)
    if fault:
        # Introduce a restoration-only defect, independently in each layer.
        # The first apply must still pass both product assertions.
        html += f'''<script>
        const originalApply = applyPanelCommands;
        let testApplyCount = 0;
        applyPanelCommands = function() {{
            const label = document.querySelector('#device-card-1 .fan-speed-indicator > span');
            const previousLabel = label.textContent;
            const previousValue = window.__vccs.devices[0].fanSpeed;
            originalApply();
            if (++testApplyCount === 2) {{
                if ({json.dumps(fault)} === 'UI') {{
                    document.querySelector('#device-card-1 .fan-speed-indicator > span').textContent = previousLabel;
                }} else {{ window.__vccs.devices[0].fanSpeed = previousValue; }}
            }}
        }};
        </script>'''
    target = tmp_path / "virtual-controller.html"
    target.write_text(html, encoding="utf-8")
    (tmp_path / "candidate_tc.json").write_text(case.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "automation_plan.json").write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    (tmp_path / "candidate.py").write_text(code, encoding="utf-8")
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "fan_transition_candidate", "exec"), namespace)
    if fault:
        with pytest.raises(AssertionError, match="RESTORE_MISMATCH"):
            namespace["test_tc_cand_090"]()
    else:
        namespace["test_tc_cand_090"]()
    output = capsys.readouterr().out
    (tmp_path / "execution.txt").write_text(output, encoding="utf-8")
    assert "PRECONDITIONS_VERIFIED: 5" in output
    if fault:
        assert "RESTORE_STATUS: FAILED" in output
        assert "ENVIRONMENT_RETIRED" in output
        assert "RESTORE_CONFIRMATIONS_VERIFIED" not in output
        assert "PRODUCT_MISMATCH:" not in output
    else:
        assert "RESTORE_STATUS: RESTORED" in output
        assert "RESTORE_CONFIRMATIONS_VERIFIED: ER-090,ER-091" in output


def test_restore_confirmation_uses_existing_baselines_without_extra_actions(tmp_path, monkeypatch):
    case, plan, observation = _restoration_detail_fixture()
    previous = compile_automation_candidate("RUN-20260916-120000-ABCDEF", case, plan)
    case.restore_steps.append("복원 후 새 제어 스위치와 내부 enabled 값을 시험 전 상태와 비교해 일치하는지 확인한다.")
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.PASS
    code = compile_automation_candidate("RUN-20260916-120000-ABCDEF", case, plan)
    assert code == previous
    assert len(plan.actions) == 2 and len(plan.assertions) == 2
    target = tmp_path / "restore-detail.html"
    _write_text_atomic(target, '''<!doctype html><input id="new-feature-toggle" type="checkbox"
        onchange="window.__vccs.feature.enabled=this.checked"><script>
        window.__vccs={feature:{enabled:false}};</script>''')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "restore_detail_check", "exec"), namespace)
    namespace["test_tc_cand_090"]()


@pytest.mark.parametrize("restore_broken", [False, True])
def test_restore_linked_switch_checks_real_boolean_restoration(tmp_path, monkeypatch, capsys, restore_broken):
    case, plan, observation = _restoration_detail_fixture()
    line = "복원 후 새 제어 스위치와 내부 enabled 값을 시험 전 관찰한 상태와 비교해 일치하는지 확인한다."
    case.restore_steps.append(line)
    plan.restore_confirmations = [pipeline.RestoreConfirmation(source_text=line,
        result_ids=[r.result_id for r in case.expected_results])]
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_plan_links=True).status == CheckStatus.PASS
    code = compile_automation_candidate("RUN-20260916-130000-ABCDEF", case, plan)
    target = tmp_path / "switch.html"
    handler = "if(this.checked)" if restore_broken else ""
    _write_text_atomic(target, f'''<!doctype html><input id="new-feature-toggle" type="checkbox"
        onchange="{handler}window.__vccs.feature.enabled=this.checked"><script>
        window.__vccs={{feature:{{enabled:false}}}};</script>''')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "boolean_restore", "exec"), namespace)
    if restore_broken:
        with pytest.raises(AssertionError, match="RESTORE_MISMATCH"):
            namespace["test_tc_cand_090"]()
        assert "RESTORE_CONFIRMATIONS_VERIFIED" not in capsys.readouterr().out
    else:
        namespace["test_tc_cand_090"]()
        assert "RESTORE_CONFIRMATIONS_VERIFIED" in capsys.readouterr().out


def test_restore_comparison_supports_shared_target_without_borrowing_other_target_basis():
    from qa_pipeline_agent3 import _restore_comparison_coverage
    case, plan, _ = mixed_restore_comparison_fixture()
    case.expected_results.append(case.expected_results[0].model_copy(update={"result_id":"ER-092"}))
    plan.assertions.append(plan.assertions[0].model_copy(update={"result_id":"ER-092"}))
    link = plan.restore_confirmations[0]
    link.result_ids.append("ER-092")
    link.comparisons.append(link.comparisons[0].model_copy(update={"result_id":"ER-092"}))
    assert not _restore_comparison_coverage(case, plan)[1]
    link.comparisons.pop()
    assert _restore_comparison_coverage(case, plan)[1]


@pytest.mark.parametrize("mutation", ["notification", "unsupported_strategy", "wrong_initial", "wrong_device"])
def test_restore_links_do_not_claim_unsupported_or_unproved_comparisons(mutation):
    case, plan, observation = _restoration_detail_fixture()
    line = "복원 후 내부 enabled 값이 false로 돌아왔는지 확인한다."
    case.preconditions.append("내부 enabled 값은 false다.")
    proof = pipeline.PreconditionCheck(source_text=case.preconditions[-1], read_kind="INTERNAL_VALUE",
        selector="window.__vccs.feature.enabled", expected_value=False)
    plan.precondition_checks.append(proof)
    case.restore_steps.append(line)
    plan.restore_confirmations = [pipeline.RestoreConfirmation(source_text=line, result_ids=["ER-091"])]
    if mutation == "notification":
        plan.assertions[1].observation_layer = ObservationLayer.NOTIFICATION
    elif mutation == "unsupported_strategy":
        plan.assertions[1].strategy = pipeline.AssertionStrategy.TOAST_VISIBLE
    elif mutation == "wrong_initial":
        case.restore_steps[-1] = plan.restore_confirmations[0].source_text = line.replace("false", "true")
    else:
        proof.selector = "window.__vccs.devices[1].enabled"
        observation.harness_values[proof.selector] = False
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation, require_restore_plan_links=True).status == CheckStatus.FAIL


@pytest.mark.parametrize("mutation", ["new_target", "new_value", "unproved_value", "missing_action", "early_check", "fake_action", "negated_comparison"])
def test_restore_confirmation_rejects_unimplemented_or_ungrounded_checks(mutation):
    case, plan, observation = _restoration_detail_fixture()
    line = "복원 후 내부 enabled 값을 시험 전 상태와 비교해 일치하는지 확인한다."
    if mutation == "new_target":
        line = "복원 후 내부 enabled 값과 새 알림을 시험 전 상태와 비교해 일치하는지 확인한다."
    elif mutation == "new_value":
        line = "복원 후 내부 enabled 값이 true로 돌아왔는지 확인한다."
    elif mutation == "unproved_value":
        line = "복원 후 내부 enabled 값이 false로 돌아왔는지 확인한다."
    elif mutation == "negated_comparison":
        line = "복원 후 내부 enabled 값을 시험 전 상태와 비교해 불일치하는지 확인한다."
    if mutation == "early_check":
        case.restore_steps.insert(0, line)
    else:
        case.restore_steps.append(line)
    if mutation == "missing_action":
        plan.actions = plan.actions[:1]
    elif mutation == "fake_action":
        plan.actions.append(plan.actions[-1].model_copy(update={"action_id": "ACT-092", "source_text": line}))
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-006A" and item.status == CheckStatus.FAIL for item in checkpoint.checks)


def test_restore_confirmation_explicit_value_needs_same_target_precondition_proof():
    case, plan, observation = _restoration_detail_fixture()
    initial = "내부 enabled 값은 false다."
    case.preconditions.append(initial)
    plan.precondition_checks.append(pipeline.PreconditionCheck(source_text=initial,
        read_kind="INTERNAL_VALUE", selector="window.__vccs.feature.enabled", expected_value=False))
    case.restore_steps.append("복원 후 내부 enabled 값이 false로 돌아왔는지 확인한다.")
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.PASS
    plan.precondition_checks[-1].selector = "window.__vccs.other.enabled"
    observation.harness_values["window.__vccs.other.enabled"] = False
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL


def test_restore_confirmation_matches_string_initial_value_not_feature_names():
    case, plan, _ = _restoration_detail_fixture()
    case.expected_results[1].observation_target = "대상 장비의 내부 fanSpeed"
    case.preconditions = ["대상 장비의 내부 fanSpeed는 LOW이다."]
    plan.assertions[1] = AutomationAssertion(result_id="ER-091", observation_layer="INTERNAL_STATE",
        strategy="INTERNAL_DEVICE_FIELDS_EQUALS", selector="window.__vccs.devices",
        expected_fields=[pipeline.DeviceFieldExpectation(field_name="fanSpeed", expected_value="HIGH")])
    plan.precondition_checks = [pipeline.PreconditionCheck(source_text=case.preconditions[0],
        read_kind="INTERNAL_VALUE", selector="window.__vccs.devices[0].fanSpeed", expected_value="LOW")]
    line = "복원 후 대상 장비의 내부 fanSpeed가 초기값 LOW로 돌아왔는지 확인한다."
    case.restore_steps.append(line)
    covered, errors = pipeline._restore_confirmation_coverage(case, plan)
    assert not errors and pipeline._normalize(line) in covered
    case.restore_steps[-1] = line.replace("LOW", "HIGH")
    assert pipeline._restore_confirmation_coverage(case, plan)[1]
    case.expected_results[1].observation_target = "LOW 상태 표시"
    case.restore_steps[-1] = "복원 후 LOW 상태 표시를 확인한다."
    assert pipeline._restore_confirmation_coverage(case, plan)[1]


def test_restore_confirmation_does_not_accept_proof_for_another_device():
    case, plan, observation = _restoration_detail_fixture()
    initial = "내부 enabled 값은 false다."
    case.preconditions.append(initial)
    plan.precondition_checks.append(pipeline.PreconditionCheck(source_text=initial,
        read_kind="INTERNAL_VALUE", selector="window.__vccs.devices[0].enabled", expected_value=False))
    observation.harness_values.update({"window.__vccs.devices[0].id": 1, "window.__vccs.devices[0].enabled": False})
    observation.device_state_fields.append("enabled")
    plan.assertions[1] = AutomationAssertion(result_id="ER-091", observation_layer="INTERNAL_STATE",
        strategy="INTERNAL_DEVICE_FIELDS_EQUALS", selector="window.__vccs.devices", after_action_id="ACT-090",
        expected_fields=[pipeline.DeviceFieldExpectation(field_name="enabled", expected_value=True)])
    case.restore_steps.append("복원 후 내부 enabled 값이 초기값 false로 돌아왔는지 확인한다.")
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.PASS
    observation.harness_values["window.__vccs.devices[0].id"] = 2
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL


def test_restore_check_action_is_not_mistaken_for_read_only_confirmation():
    case, plan, observation = generic_control_guard_fixture()
    case.restore_steps = ["Check the new feature toggle."]
    plan.actions[-1].source_text = case.restore_steps[0]
    plan.actions[-1].action_type = AutomationActionType.CHECK
    assert pipeline._restore_confirmation_coverage(case, plan) == (set(), [])


def test_restore_confirmation_legacy_temperature_uses_existing_fixed_checks():
    case = agent3_test_case()
    plan = agent3_plan()
    operation = "Restore AUTO 18 and verify UI and internal state."
    case.restore_required = True
    case.restore_steps = [operation]
    for result, target in zip(case.expected_results[:2], ["UI", "Internal setTemp"]):
        result.observation_target = target
        result.verify_after_step = case.steps[0]
    for assertion in plan.assertions[:2]:
        assertion.after_action_id = "ACT-006"
    plan.actions.extend([
        AutomationAction(action_id="ACT-007", phase="RESTORE", action_type="SET_TEMPERATURE",
                         selector="#det-temp-display", value=18.0, source_text=operation),
        AutomationAction(action_id="ACT-008", phase="RESTORE", action_type="APPLY_COMMANDS",
                         selector=".btn-apply-cmd", source_text=operation),
    ])
    previous = compile_automation_candidate("RUN-20260916-120000-ABCDEF", case, plan)
    case.restore_steps.extend(["복원 후 UI가 18로 돌아왔는지 확인한다.", "복원 후 Internal setTemp가 18로 돌아왔는지 확인한다."])
    assert evaluate_checkpoint3_plan(case, plan, agent3_observation()).status == CheckStatus.PASS
    assert compile_automation_candidate("RUN-20260916-120000-ABCDEF", case, plan) == previous
    case.restore_steps[-1] = "복원 후 Internal setTemp가 17로 돌아왔는지 확인한다."
    assert evaluate_checkpoint3_plan(case, plan, agent3_observation()).status == CheckStatus.FAIL


def test_historical_restore_confirmation_uses_previous_checkpoint_rules():
    case, plan = agent3_test_case(), agent3_plan()
    operation = "Restore AUTO 18 and verify UI and internal state."
    case.restore_required = True
    case.restore_steps = [operation, "복원 후 UI가 초기값 18로 돌아왔는지 확인한다."]
    plan.actions.extend([
        AutomationAction(action_id="ACT-007", phase="RESTORE", action_type="SET_TEMPERATURE",
                         selector="#det-temp-display", value=18.0, source_text=operation),
        AutomationAction(action_id="ACT-008", phase="RESTORE", action_type="APPLY_COMMANDS",
                         selector=".btn-apply-cmd", source_text=operation),
    ])
    previous = pipeline.evaluate_checkpoint3_plan(case, plan, agent3_observation(),
        require_precondition_proof=False, require_restore_confirmation_detail=False,
        require_plan_fidelity=False)
    current = pipeline.evaluate_checkpoint3_plan(case, plan, agent3_observation(), require_precondition_proof=False)
    assert previous.status == CheckStatus.PASS
    assert current.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-006A" and "observation_target" in item.message for item in current.checks)


def test_detailed_single_flow_requires_and_executes_explicit_assertion_anchor(tmp_path, monkeypatch):
    case, plan, observation = precondition_guard_fixture()
    for result, target in zip(case.expected_results, ["새 제어 스위치", "내부 enabled 값"]):
        result.observation_target = target
        result.verify_after_step = case.steps[0]
    checkpoint = pipeline.evaluate_checkpoint3_plan(case, plan, observation)
    assert next(item for item in checkpoint.checks if item.rule_id == "CP3-003A").status == CheckStatus.FAIL
    for assertion in plan.assertions:
        assertion.after_action_id = "ACT-090"
    assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.PASS
    code = compile_automation_candidate("RUN-20260915-120000-ABCDEF", case, plan)
    assert code.index("# EXPECTED_RESULT: ER-090") < code.index("# ACT-091 RESTORE")
    target = tmp_path / "detailed-switch.html"
    _write_text_atomic(target, '''<!doctype html><input id="new-feature-toggle" type="checkbox"
        onchange="window.__vccs.feature.enabled=this.checked"><script>
        window.__vccs={feature:{enabled:false}};</script>''')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "detailed_tc_check", "exec"), namespace)
    namespace["test_tc_cand_090"]()


@pytest.mark.parametrize("mutation", ["missing", "wrong_source", "unknown_selector", "wrong_value", "weak_text", "unproved_login", "enabled_instead_of_checked", "early_assertion"])
def test_precondition_proof_rejects_unverified_plans(mutation):
    case, plan, observation = precondition_guard_fixture()
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.PASS
    check = plan.precondition_checks[0]
    if mutation == "missing":
        plan.precondition_checks = []
        assert pipeline.evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL
    elif mutation == "wrong_source":
        check.source_text = "다른 사전조건"
    elif mutation == "unknown_selector":
        check.selector = "#not-observed"
    elif mutation == "wrong_value":
        check.expected_value = True
    elif mutation == "weak_text":
        check.read_kind = pipeline.PreconditionReadKind.UI_TEXT
        check.expected_value = "새 제어"
    elif mutation == "enabled_instead_of_checked":
        check.read_kind = pipeline.PreconditionReadKind.UI_ENABLED
    elif mutation == "early_assertion":
        preparation = plan.actions[-1].model_copy(update={"action_id": "ACT-089", "phase": AutomationPhase.PRECONDITION, "source_text": case.preconditions[0]})
        plan.actions.insert(0, preparation)
        plan.assertions[0].after_action_id = preparation.action_id
    else:
        case.preconditions.append("관리자 권한으로 로그인되어 있어야 한다.")
    checkpoint = evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True)
    assert next(item for item in checkpoint.checks if item.rule_id == "CP3-006D").status == CheckStatus.FAIL


def test_baseline_context_cannot_prove_administrator_login():
    case, plan, observation = precondition_guard_fixture()
    case.preconditions.append("관리자 권한으로 로그인된 대상 장비다.")
    observation.verified_execution_context.target_device_visible = True
    plan.precondition_checks.append(pipeline.PreconditionCheck(source_text=case.preconditions[-1],
        read_kind="BASELINE_CONTEXT", selector="target_device_visible", expected_value=True))
    checkpoint = evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True)
    assert checkpoint.status == CheckStatus.FAIL


def test_compound_baseline_precondition_needs_each_observed_fact():
    case, plan, observation = precondition_guard_fixture()
    source = "온라인 대상 장비는 오류와 잠금이 없는 상태다."
    case.preconditions.append(source)
    context = observation.verified_execution_context
    context.target_device_visible = context.device_state_available = True
    context.error_free = context.unlocked = context.online = True
    plan.precondition_checks.append(pipeline.PreconditionCheck(source_text=source,
        read_kind="BASELINE_CONTEXT", selector="target_device_visible", expected_value=True))
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.FAIL
    plan.precondition_checks.extend(pipeline.PreconditionCheck(source_text=source,
        read_kind="BASELINE_CONTEXT", selector=key, expected_value=True) for key in ("error_free", "unlocked", "online"))
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.PASS


def test_narrow_inventory_exposes_target_initial_values_without_full_discovery():
    observation = inspect_target_ui(REPO_ROOT / "product_baseline/virtual-controller.html",
        required_selectors={"#device-card-1 .card-body-split"}, required_harness_keys={"devices"}, discover_generic=False)
    assert observation.harness_values["window.__vccs.devices[0].id"] == 1
    assert isinstance(observation.harness_values["window.__vccs.devices[0].mode"], str)
    assert type(observation.harness_values["window.__vccs.devices[0].setTemp"]) in (int, float)
    assert observation.verified_execution_context.online is True
    assert not observation.generic_discovery


def test_precondition_internal_device_reference_must_match_target_identity():
    case, plan, observation = precondition_guard_fixture()
    case.preconditions = ["mode 값은 AUTO다."]
    observation.harness_values.update({"window.__vccs.devices[0].id": 2, "window.__vccs.devices[0].mode": "AUTO"})
    plan.precondition_checks = [pipeline.PreconditionCheck(source_text=case.preconditions[0],
        read_kind="INTERNAL_VALUE", selector="window.__vccs.devices[0].mode", expected_value="AUTO")]
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.FAIL
    observation.harness_values["window.__vccs.devices[0].id"] = 1
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.PASS


@pytest.mark.parametrize("initial_checked", [False, True])
def test_runtime_precondition_is_verified_before_product_test(tmp_path, initial_checked):
    case, plan, observation = precondition_guard_fixture()
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.PASS
    target = tmp_path / "switch.html"
    _write_text_atomic(target, f'''<!doctype html><title>Proof fixture</title>
        <input id="new-feature-toggle" type="checkbox" {'checked' if initial_checked else ''}
        onchange="window.__vccs.feature.enabled=this.checked"><script>
        window.__vccs={{feature:{{enabled:{str(initial_checked).lower()}}}}};</script>''')
    candidate = tmp_path / "test_proof.py"
    _write_text_atomic(candidate, compile_automation_candidate("RUN-20260912-180000-ABCDEF", case, plan))
    trial = run_candidate_trial(candidate, target, tmp_path / "evidence", timeout_seconds=60)
    assert trial.outcome == (TrialOutcome.AUTOMATION_ERROR if initial_checked else TrialOutcome.PASS)
    assert trial.evidence_complete
    stdout = (tmp_path / "evidence" / trial.stdout_file).read_text(encoding="utf-8")
    if initial_checked:
        assert "PRECONDITION_NOT_MET:" in stdout
        observations = pipeline_reporting._execution_failure_observations(
            tmp_path, pipeline.NeutralExecutionResult.model_validate({
                **_neutral_execution_result("TC-CAND-090", pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE,
                    pipeline.NeutralExecutionStatus.EXECUTION_ERROR).model_dump(mode="json"),
                "stdout_file": "evidence/" + trial.stdout_file, "stderr_file": "evidence/" + trial.stderr_file,
                "evidence_files": ["evidence/" + name for name in trial.evidence_sha256],
                "evidence_sha256": {"evidence/" + name: value for name, value in trial.evidence_sha256.items()},
            }))
        assert "PRECONDITION_NOT_MET" in observations
        assert "PRODUCT_MISMATCH" not in observations
    else:
        assert "PRECONDITION_OBSERVED: 1 False" in stdout
        assert "PRECONDITIONS_VERIFIED: 1" in stdout


def test_precondition_multiple_explicit_values_need_multiple_checks():
    case, plan, observation = precondition_guard_fixture()
    case.preconditions = ["내부 role 값은 ADMIN이고 site 값은 SOUTH다."]
    observation.harness_values.update({"window.__vccs.role": "ADMIN", "window.__vccs.site": "SOUTH"})
    plan.precondition_checks = [pipeline.PreconditionCheck(source_text=case.preconditions[0],
        read_kind="INTERNAL_VALUE", selector="window.__vccs.role", expected_value="ADMIN")]
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.FAIL
    plan.precondition_checks.append(pipeline.PreconditionCheck(source_text=case.preconditions[0],
        read_kind="INTERNAL_VALUE", selector="window.__vccs.site", expected_value="SOUTH"))
    assert evaluate_checkpoint3_plan(case, plan, observation, require_precondition_proof=True).status == CheckStatus.PASS


def test_cp3_rejects_static_label_in_place_of_switch_state():
    case, plan, observation = generic_control_guard_fixture()
    plan.assertions[0].strategy = AssertionStrategy.UI_TEXT_CONTAINS
    plan.assertions[0].expected_value = None
    plan.assertions[0].expected_text = "새 제어"
    assert evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL


def test_cp3_rejects_disabled_strategy_for_enabled_expectation():
    case, plan, observation = agent3_test_case(), agent3_plan(), agent3_observation()
    case.expected_results[0].statement = "온도 버튼은 활성 상태다."
    plan.assertions[0] = AutomationAssertion(result_id=case.expected_results[0].result_id,
        observation_layer="UI", strategy="CONTROLS_DISABLED", selector="#det-temp-down-btn")
    assert evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL


def test_generic_restore_snapshot_follows_preparation(tmp_path, monkeypatch):
    case, plan, _ = generic_control_guard_fixture()
    case.preconditions = ["새 제어 스위치를 끈다."]
    preparation = plan.actions[-1].model_copy(update={
        "action_id": "ACT-089", "phase": AutomationPhase.PRECONDITION,
        "source_text": case.preconditions[0],
    })
    plan.actions.insert(0, preparation)
    code = compile_automation_candidate("RUN-20260912-120000-ABCDEF", case, plan)
    assert code.index("# ACT-089 PRECONDITION") < code.rindex("restore_baseline_0 =") < code.index("# ACT-090 TEST")
    target = tmp_path / "switch.html"
    _write_text_atomic(target, '''<!doctype html><input id="new-feature-toggle" type="checkbox" checked
        onchange="window.__vccs.feature.enabled=this.checked"><script>
        window.__vccs={feature:{enabled:true}};</script>''')
    monkeypatch.setenv("QA_TARGET_URL", target.as_uri())
    monkeypatch.setenv("QA_EVIDENCE_DIR", str(tmp_path / "evidence"))
    namespace = {}
    exec(compile(code, "generated_restore_check", "exec"), namespace)
    namespace["test_tc_cand_090"]()


@pytest.mark.parametrize("mutation", ["reverse", "missing_step", "missing_restore", "weak_text", "duplicate"])
def test_cp3_rejects_false_pass_plans(mutation):
    case, plan, observation = generic_control_guard_fixture()
    assert evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.PASS
    if mutation == "reverse":
        case.expected_results[0].statement = "새 제어 스위치는 비활성 상태다."
        plan.assertions[0].strategy = AssertionStrategy.UI_ENABLED_EQUALS
    elif mutation == "missing_step":
        case.steps.append("저장 버튼을 누른다.")
    elif mutation == "missing_restore":
        case.restore_steps.append("복원 명령을 적용한다.")
    elif mutation == "weak_text":
        case.expected_results[0].statement = "새 제어 스위치에 사용 금지가 표시된다."
        plan.assertions[0].strategy = AssertionStrategy.UI_TEXT_CONTAINS
        plan.assertions[0].expected_value = None
        plan.assertions[0].expected_text = "표시"
    else:
        observation.elements[-1].match_count = 2
    assert evaluate_checkpoint3_plan(case, plan, observation).status == CheckStatus.FAIL


@pytest.mark.parametrize("value,text,expected", [
    (True, "비활성", False), (False, "비활성", True), (True, "unchecked", False),
    (False, "enabled 값은 false다.", True), ("ON", "NONE", False), (30, "130°C", False),
    (True, "켜짐", True), (False, "꺼짐", True),
    (True, "not enabled", False), (False, "not enabled", True),
])
def test_scalar_guard_distinguishes_values(value, text, expected):
    assert pipeline._scalar_value_is_grounded(value, text) is expected


def test_inventory_counts_duplicate_selectors_and_target_only_fields(tmp_path):
    target = tmp_path / "inventory.html"
    _write_text_atomic(target, '''<!doctype html><html><head><title>Inventory</title></head><body>
      <input aria-label="switch" type="checkbox"><input aria-label="switch" type="checkbox">
      <script>window.__vccs={devices:[{id:2,unrelated:true},{id:1,enabled:false}]};</script>
      </body></html>''')
    observation = inspect_target_ui(target, required_selectors=set(), required_harness_keys=set(), discover_generic=True)
    assert "unrelated" not in observation.device_state_fields
    assert "enabled" in observation.device_state_fields
    assert next(item for item in observation.elements if 'aria-label="switch"' in item.selector).match_count == 2


def test_compiled_observation_wait_handles_delayed_browser_state_without_reclicking():
    import ast
    from playwright.sync_api import sync_playwright
    code = compile_automation_candidate("RUN-20260909-120000-ABCDEF", agent3_test_case(), agent3_plan())
    tree = ast.parse(code)
    helper = ast.Module(body=[node for node in tree.body if
        isinstance(node, ast.ImportFrom) and node.module == "time"
        or isinstance(node, ast.FunctionDef) and node.name == "_wait_for_observations"], type_ignores=[])
    namespace = {}
    exec(compile(helper, "generated_wait", "exec"), namespace)
    with sync_playwright() as browser_api:
        browser = browser_api.chromium.launch(headless=True)
        page = browser.new_page()
        page.set_content('<button id="apply" onclick="window.clicks++; setTimeout(() => {document.querySelector(\'#value\').textContent=\'ready\'; window.state=\'ready\'}, 350)">apply</button><div id="value">pending</div><script>window.clicks=0;window.state="pending";</script>')
        page.locator("#apply").click()
        def observe():
            return [] if page.locator("#value").inner_text() == "ready" and page.evaluate("window.state") == "ready" else ["not ready"]
        assert namespace["_wait_for_observations"](page, observe) == []
        assert page.evaluate("window.clicks") == 1
        assert namespace["_wait_for_observations"](page, lambda: ["PRODUCT_MISMATCH: wrong value"]) == ["PRODUCT_MISMATCH: wrong value"]
        browser.close()


def test_agent3_uses_structured_plan_api() -> None:
    responses = Agent3FakeResponses()
    result = OpenAIAgent3(model="test-model", client=SimpleNamespace(responses=responses)).plan(
        agent3_test_case(), agent3_observation(), {"REQ-TEMP-001": SrsRequirement(requirement_id="REQ-TEMP-001", statement="range", acceptance_criteria="block")}
    )
    assert result.plan.tc_id == "TC-CAND-003"
    assert responses.kwargs["text_format"] is Agent3AutomationPlan
    assert responses.kwargs["store"] is False
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent3-3-42"
    instructions = responses.kwargs["input"][0]["content"]
    assert "Check only conditions stated in the approved TC preconditions" in instructions
    assert "not every available context field" in instructions
    assert "does not replace runtime proof" in instructions
    assert "SET_TEMPERATURE=#det-temp-display" in instructions
    assert "Generic UI actions are CLICK, FILL, SELECT_OPTION, CHECK, and UNCHECK" in instructions
    assert "AUTOMATION_SUPPORT_EXTENSION_REQUIRED" in instructions
    assert "INTERNAL_SET_TEMP=window.__vccs.devices" in instructions
    assert "INTERNAL_DEVICE_FIELDS_EQUALS=window.__vccs.devices" in instructions
    assert "Do not append indexes, properties, or expressions" in instructions
    assert "If a SELECT_DEVICE action is actually needed" in instructions
    assert "does not need a legacy SELECT_DEVICE action" in instructions
    assert "UI_TEXT_CONTAINS may verify a short meaningful phrase" in instructions
    assert "do not use the entire natural-language Expected Result sentence" in instructions
    assert "TOAST_BLOCKING" in instructions
    assert "disabled or 비활성 grounds UI_ENABLED_EQUALS" in instructions
    assert "RESTORE_OBSERVED_HVAC" in instructions
    OpenAIAgent3(model="test-model", client=SimpleNamespace(responses=responses)).plan(
        agent3_test_case(), agent3_observation(), {}, previous_plan=agent3_plan(),
        checkpoint_feedback=["사전조건 확인 #2 [BASELINE_CONTEXT/online]: 원문 근거 없음"],
    )
    repair_input = responses.kwargs["input"][1]["content"]
    assert "사전조건 확인 #2 [BASELINE_CONTEXT/online]" in repair_input
    assert "repair the identified check and preserve valid checks" in repair_input
    assert "never delete a stated condition" in repair_input

def test_agent3_accepts_atomic_temperature_up_disabled_assertion() -> None:
    test_case = agent3_test_case()
    disabled_up = test_case.expected_results[0].model_copy(
        update={
            "statement": "온도 올림 버튼이 disabled 상태이다.",
        }
    )
    test_case = test_case.model_copy(
        update={
            "expected_results": [
                disabled_up,
                *test_case.expected_results[1:],
            ]
        }
    )
    plan = agent3_plan()
    enabled_assertion = plan.assertions[0].model_copy(
        update={
            "strategy": AssertionStrategy.UI_ENABLED_EQUALS,
            "selector": "#det-temp-up-btn",
            "expected_number": None,
            "expected_value": False,
        }
    )
    plan = plan.model_copy(
        update={"assertions": [enabled_assertion, *plan.assertions[1:]]}
    )
    observation = agent3_observation()
    observation = observation.model_copy(
        update={
            "elements": [
                item.model_copy(
                    update={"action_hint": "온도 올림 / Request one degree higher"}
                )
                if item.selector == "#det-temp-up-btn"
                else item
                for item in observation.elements
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)

    assert checkpoint.status == CheckStatus.PASS
    code = compile_automation_candidate(
        "RUN-20260826-133000-ABCDEF", test_case, plan
    )
    assert "#det-temp-up-btn" in code
    assert ".is_enabled()" in code

def test_agent3_eligibility_keeps_atomic_temperature_button_selectors() -> None:
    test_case = ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-004",
            "title": "잠금 후 온도 버튼 비활성화",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "STATE_CONSISTENCY",
            "requirement_ids": ["REQ-LOCK-001", "REQ-STATE-001"],
            "source_condition_ids": ["COND-001"],
            "control_path": "CENTRAL",
            "target_role": "PRIMARY_TEST_DEVICE",
            "test_data": {},
            "preconditions": ["대상 장비는 잠금 해제 상태이다."],
            "steps": ["대상 장비에 잠금 설정을 적용한다."],
            "expected_results": [
                {
                    "result_id": "ER-001",
                    "statement": "온도 내림 버튼이 disabled 상태이다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-001"],
                },
                {
                    "result_id": "ER-002",
                    "statement": "온도 올림 버튼이 disabled 상태이다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-001"],
                },
                {
                    "result_id": "ER-003",
                    "statement": "내부 locked 값이 활성화되어 있다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-001"],
                },
            ],
            "restore_required": True,
            "restore_steps": ["대상 장비의 잠금을 해제한다."],
            "automation_candidate": True,
            "automation_reason": "관찰된 UI와 내부 상태로 확인할 수 있다.",
        }
    )

    eligibility = evaluate_agent3_eligibility(test_case)

    assert "#det-temp-down-btn" in eligibility.required_selectors
    assert "#det-temp-up-btn" in eligibility.required_selectors
    assert "#device-card-1 .card-body-split" in eligibility.required_selectors
    assert ".btn-apply-cmd" in eligibility.required_selectors
    assert "selectedUnitId" in eligibility.required_harness_keys
    assert "devices" in eligibility.required_harness_keys
    assert "SELECT_PRIMARY_DEVICE" in eligibility.required_capabilities
    assert "APPLY_CENTRAL_COMMAND" in eligibility.required_capabilities
    assert "ASSERT_GENERIC_UI_STATE" in eligibility.required_capabilities

def test_agent3_allows_observed_initial_mode_without_reapplying() -> None:
    test_case = agent3_test_case()
    plan = agent3_plan().model_copy(
        update={
            "actions": [
                item
                for item in agent3_plan().actions
                if item.action_id not in {"ACT-002", "ACT-003", "ACT-004"}
            ]
        }
    )
    observation = agent3_observation().model_copy(
        update={
            "harness_values": {
                "window.__vccs.devices[0].mode": "AUTO",
                "window.__vccs.devices[0].setTemp": 18,
            }
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)

    assert checkpoint.status == CheckStatus.PASS
    sequence = next(
        item for item in checkpoint.checks if item.rule_id == "CP3-006A"
    )
    assert sequence.status == CheckStatus.PASS

def test_agent3_model_input_preview_is_minimal_and_has_no_local_path() -> None:
    requirements = {
        "REQ-TEMP-001": SrsRequirement(requirement_id="REQ-TEMP-001", statement="range", acceptance_criteria="block"),
        "REQ-UNRELATED-001": SrsRequirement(requirement_id="REQ-UNRELATED-001", statement="unrelated", acceptance_criteria="none"),
    }
    observation = agent3_observation().model_copy(
        update={
            "harness_values": {
                "window.__vccs.devices[0].setTemp": 18,
                "window.__vccs.unrelated.secretFlag": True,
            }
        }
    )
    payload = build_agent3_model_input(agent3_test_case(), observation, requirements)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["destination"] == "OpenAI Responses API"
    assert payload["store"] is False
    assert set(payload["related_srs_requirements"]) == {"REQ-TEMP-001"}
    assert payload["ui_observation"]["target_file"] == "virtual-controller.html"
    assert set(payload["ui_observation"]["harness_values"]) == {
        "window.__vccs.devices[0].setTemp"
    }
    assert set(payload["ui_observation"]["device_state_fields"]) == {
        "mode",
        "setTemp",
    }
    korean_expected_results = [
        result.model_copy(
            update={
                "statement": "적용 후 내부 설정 온도는 18°C이며 기존 값과 일치합니다."
            }
        )
        if result.observation_layer == ObservationLayer.INTERNAL_STATE
        else result
        for result in agent3_test_case().expected_results
    ]
    korean_tc = agent3_test_case().model_copy(
        update={"expected_results": korean_expected_results}
    )
    korean_payload = build_agent3_model_input(korean_tc, observation, requirements)
    assert "setTemp" in korean_payload["ui_observation"]["device_state_fields"]
    assert "window.__vccs.devices[0].setTemp" in (
        korean_payload["ui_observation"]["harness_values"]
    )
    assert "C:\\" not in serialized
    assert "<!doctype html" not in serialized

def test_agent3_eligibility_scopes_ui_inventory_to_selected_tc(tmp_path: Path) -> None:
    eligibility = evaluate_agent3_eligibility(agent3_test_case())
    assert eligibility.status == Agent3EligibilityStatus.ELIGIBLE
    assert eligibility.model_call_allowed is True
    assert "#det-mode-auto" in eligibility.required_selectors
    assert "#det-mode-dry" not in eligibility.required_selectors
    assert set(eligibility.required_harness_keys) == {"devices", "selectedUnitId"}
    assert "ASSERT_TOAST_BLOCKING" in eligibility.required_capabilities

    target = tmp_path / "target.html"
    target.write_text(
        """<!doctype html><title>Scoped Inventory</title>
<div id='device-card-1'><button class='card-body-split'>device</button></div>
<button id='det-mode-auto'>AUTO</button>
<span id='det-temp-display'>18 C</span>
<button id='det-temp-down-btn'>-</button><button id='det-temp-up-btn'>+</button>
<button class='btn-apply-cmd'>apply</button><div id='global-toast'>warning</div>
<script>window.__vccs={devices:[],selectedUnitId:null};</script>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors=set(eligibility.required_selectors),
        required_harness_keys=set(eligibility.required_harness_keys),
    )

    assert {item.selector for item in observation.elements} == set(
        eligibility.required_selectors
    )
    assert set(observation.harness_keys) == {"devices", "selectedUnitId"}
    assert observation.device_state_fields == []

def test_agent3_scoped_inventory_still_blocks_a_required_selector(tmp_path: Path) -> None:
    eligibility = evaluate_agent3_eligibility(agent3_test_case())
    target = tmp_path / "target.html"
    target.write_text(
        """<!doctype html><div id='device-card-1'><button class='card-body-split'>device</button></div>
<span id='det-temp-display'>18 C</span>
<button id='det-temp-down-btn'>-</button><button id='det-temp-up-btn'>+</button>
<button class='btn-apply-cmd'>apply</button><div id='global-toast'>warning</div>
<script>window.__vccs={devices:[],selectedUnitId:null};</script>""",
        encoding="utf-8",
    )

    with pytest.raises(pipeline.Agent3Error, match="#det-mode-auto"):
        inspect_target_ui(
            target,
            required_selectors=set(eligibility.required_selectors),
            required_harness_keys=set(eligibility.required_harness_keys),
        )

def test_agent3_observation_records_verified_clean_execution_context(
    tmp_path: Path,
) -> None:
    target = tmp_path / "verified-context.html"
    target.write_text(
        """<!doctype html><html><head><title>Verified Context</title></head><body>
        <div id="device-card-1"><div class="card-body-split">IDU-00</div></div>
        <script>window.__vccs = {devices: [{id: 1, status: 'STOP', locked: false, errorCode: null}]};</script>
        </body></html>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors={"#device-card-1 .card-body-split"},
        required_harness_keys={"devices"},
    )

    context = observation.verified_execution_context
    assert context.clean_page_loaded is True
    assert context.target_device_visible is True
    assert context.device_state_available is True
    assert context.error_free is True
    assert context.unlocked is True
    preview = build_agent3_model_input(
        agent3_test_case(),
        observation,
        {
            "REQ-TEMP-001": SrsRequirement(
                requirement_id="REQ-TEMP-001",
                statement="range",
                acceptance_criteria="block",
            )
        },
    )
    assert preview["ui_observation"]["verified_execution_context"]["error_free"] is True

def test_agent3_inspection_waits_for_delayed_required_selector(tmp_path: Path) -> None:
    target = tmp_path / "delayed-controller.html"
    target.write_text(
        """<!doctype html><title>Delayed Controller</title><body><script>
setTimeout(() => document.body.insertAdjacentHTML('beforeend',
  '<button id="det-mode-auto">AUTO</button>'), 100);
</script></body>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors={"#det-mode-auto"},
        required_harness_keys=set(),
    )

    assert [item.selector for item in observation.elements] == ["#det-mode-auto"]

def test_agent3_verified_context_is_captured_after_delayed_interfaces(
    tmp_path: Path,
) -> None:
    target = tmp_path / "delayed-context.html"
    target.write_text(
        """<!doctype html><title>Delayed Context</title><body><script>
setTimeout(() => {
  document.body.insertAdjacentHTML('beforeend',
    '<div id="device-card-1"><div class="card-body-split">IDU-00</div></div>');
  window.__vccs = {devices: [{id: 1, status: 'STOP', locked: false, errorCode: null}]};
}, 100);
</script></body>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors={"#device-card-1 .card-body-split"},
        required_harness_keys={"devices"},
    )

    context = observation.verified_execution_context
    assert context.target_device_visible is True
    assert context.device_state_available is True
    assert context.error_free is True
    assert context.unlocked is True

def test_agent3_local_control_path_is_excluded_before_ui_or_model() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["control_path"] = "LOCAL"
    test_case = ProductTestCaseCandidate.model_validate(payload)
    eligibility = evaluate_agent3_eligibility(test_case)

    assert eligibility.status == Agent3EligibilityStatus.NOT_AUTOMATABLE
    assert eligibility.model_call_allowed is False
    assert eligibility.generic_discovery_required is False
    assert eligibility.required_selectors == []
    assert eligibility.required_harness_keys == []
    assert "CENTRAL_CONTROL_PANEL_ONLY" in eligibility.missing_capabilities
    assert evaluate_checkpoint3_plan(
        test_case, agent3_plan(), agent3_observation()
    ).status == CheckStatus.FAIL
    with pytest.raises(pipeline.Agent3Error, match="CENTRAL control-panel"):
        compile_automation_candidate(
            "RUN-20260824-LOCALBLOCK-ABCDEF", test_case, agent3_plan()
        )

def test_agent3_unknown_internal_state_uses_generic_discovery() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["requirement_ids"].append("REQ-LOCK-001")
    payload["expected_results"][1]["statement"] = "Internal locked state remains true."

    eligibility = evaluate_agent3_eligibility(
        ProductTestCaseCandidate.model_validate(payload)
    )

    assert eligibility.status == Agent3EligibilityStatus.DISCOVERY_REQUIRED
    assert eligibility.candidate_status is None
    assert eligibility.model_call_allowed is True
    assert eligibility.generic_discovery_required is True
    assert "DISCOVER_INTERNAL_STATE" in eligibility.required_capabilities
    assert eligibility.missing_capabilities == []

def test_agent3_registered_device_fields_are_grounded_and_compiled() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["expected_results"][1]["statement"] = (
        "Internal mode is AUTO and setTemp remains at 18 degrees."
    )
    test_case = ProductTestCaseCandidate.model_validate(payload)
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"][1] = {
        "result_id": "ER-006",
        "observation_layer": "INTERNAL_STATE",
        "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
        "selector": "window.__vccs.devices",
        "expected_fields": [
            {"field_name": "mode", "expected_value": "AUTO"},
            {"field_name": "setTemp", "expected_value": 18},
        ],
    }
    plan = Agent3AutomationPlan.model_validate(plan_payload)

    eligibility = evaluate_agent3_eligibility(test_case)
    checkpoint = evaluate_checkpoint3_plan(test_case, plan, agent3_observation())
    code = compile_automation_candidate("RUN-20260817-FIELDS-ABCDEF", test_case, plan)

    assert "ASSERT_INTERNAL_DEVICE_FIELDS" in eligibility.required_capabilities
    assert checkpoint.status == CheckStatus.PASS
    assert "internal device fields={actual}" in code
    assert "Object.fromEntries(fields.map(field" in code

def test_agent3_rejects_unobserved_or_ungrounded_device_fields() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["expected_results"][1]["statement"] = "Internal setTemp remains at 18 degrees."
    test_case = ProductTestCaseCandidate.model_validate(payload)
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"][1] = {
        "result_id": "ER-006",
        "observation_layer": "INTERNAL_STATE",
        "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
        "selector": "window.__vccs.devices",
        "expected_fields": [
            {"field_name": "mode", "expected_value": "AUTO"},
            {"field_name": "unregistered", "expected_value": True},
        ],
    }
    checkpoint = evaluate_checkpoint3_plan(
        test_case, Agent3AutomationPlan.model_validate(plan_payload), agent3_observation()
    )

    cp3 = next(item for item in checkpoint.checks if item.rule_id == "CP3-004")
    assert checkpoint.status == CheckStatus.FAIL
    assert "field is not named in the Expected Result: mode" in cp3.message
    assert "field was not observed: unregistered" in cp3.message

def test_agent3_non_hvac_mode_values_use_generic_discovery() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["test_data"] = {
        "initial_mode": "STOP",
        "requested_mode": "OPERATION",
        "initial_temperature_c": None,
        "requested_temperature_c": None,
    }
    payload["expected_results"] = [
        {
            "result_id": "ER-005",
            "statement": "화면 상태가 OPERATION으로 변경된다.",
            "observation_layer": "UI",
            "source_condition_ids": ["COND-001"],
        },
        {
            "result_id": "ER-006",
            "statement": "내부 status가 OPERATION으로 변경된다.",
            "observation_layer": "INTERNAL_STATE",
            "source_condition_ids": ["COND-001"],
        },
    ]

    eligibility = evaluate_agent3_eligibility(
        ProductTestCaseCandidate.model_validate(payload)
    )

    assert eligibility.status == Agent3EligibilityStatus.DISCOVERY_REQUIRED
    assert eligibility.generic_discovery_required is True
    assert eligibility.required_selectors == [
        "#device-card-1 .card-body-split",
        ".btn-apply-cmd",
    ]
    assert eligibility.required_harness_keys == ["devices", "selectedUnitId"]
    assert "SELECT_PRIMARY_DEVICE" in eligibility.required_capabilities
    assert "DISCOVER_GENERIC_UI" in eligibility.required_capabilities
    assert "SET_MODE" not in eligibility.required_capabilities

def test_agent3_textual_link_tolerates_korean_particles() -> None:
    assert pipeline._has_textual_link("적용", "적용을 실행한다.")
    assert pipeline._has_textual_link(
        "window vccs primaryTestDevice status",
        "PRIMARY_TEST_DEVICE의 내부 status가 OPERATION으로 변경된다.",
    )
    assert not pipeline._has_textual_link("삭제 버튼", "적용을 실행한다.")

def test_agent3_allows_dynamic_text_on_the_approved_target_device_card() -> None:
    test_case = ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-101",
            "title": "대상 장비 카드 풍량 표시와 내부 코드 검증",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "NORMAL",
            "requirement_ids": ["REQ-FAN-001"],
            "source_condition_ids": ["COND-101"],
            "control_path": "CENTRAL",
            "target_role": "PRIMARY_TEST_DEVICE",
            "test_data": {},
            "preconditions": ["오류와 잠금이 없는 단일 대상 장비를 준비한다."],
            "steps": [
                "대상 장비를 단일 선택한다.",
                "대상 장비의 풍량으로 HIGH를 선택하고 적용한다.",
                "대상 장비 카드의 풍량 표시를 확인한다.",
                "대상 장비의 내부 fanSpeed를 확인한다.",
            ],
            "expected_results": [
                {
                    "result_id": "ER-101",
                    "statement": "대상 장비 카드에 강풍이 표시된다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-101"],
                    "verify_after_step": "대상 장비 카드의 풍량 표시를 확인한다.",
                },
                {
                    "result_id": "ER-102",
                    "statement": "대상 장비의 내부 fanSpeed는 HIGH이다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-101"],
                    "verify_after_step": "대상 장비의 내부 fanSpeed를 확인한다.",
                },
            ],
            "restore_required": False,
            "restore_steps": [],
            "automation_candidate": True,
            "automation_reason": "대상 카드와 내부 상태를 관찰할 수 있다.",
        }
    )
    observation = UiObservation(
        target_file="virtual-controller.html",
        target_sha256="a" * 64,
        page_title="Virtual Controller",
        elements=[
            ObservedUiElement(
                selector="#device-card-1 .card-body-split",
                tag="div",
                text="약풍",
                visible=True,
                enabled=True,
                action_hint="Select PRIMARY_TEST_DEVICE",
            ),
            ObservedUiElement(
                selector="#det-fan-high",
                tag="button",
                text="강풍",
                visible=True,
                enabled=True,
                action_hint="CLICK",
            ),
            ObservedUiElement(
                selector=".btn-apply-cmd",
                tag="button",
                text="적용",
                visible=True,
                enabled=True,
                action_hint="Apply pending commands",
            ),
            ObservedUiElement(
                selector="#device-card-1",
                tag="div",
                text="약풍",
                visible=True,
                enabled=True,
                action_hint="READ_STATE",
            ),
        ],
        harness_keys=["devices", "selectedUnitId"],
        harness_values={"window.__vccs.devices[0].fanSpeed": "LOW"},
        device_state_fields=["fanSpeed"],
        observed_at="2026-08-29T00:00:00+00:00",
    )
    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": "TC-CAND-101",
            "target_device_id": 1,
            "summary": "HIGH 풍량 적용 뒤 카드 표시와 내부 코드를 확인한다.",
            "actions": [
                {
                    "action_id": "ACT-101",
                    "phase": "TEST",
                    "action_type": "SELECT_DEVICE",
                    "selector": "#device-card-1 .card-body-split",
                    "value": 1,
                    "source_text": "대상 장비를 단일 선택한다.",
                },
                {
                    "action_id": "ACT-102",
                    "phase": "TEST",
                    "action_type": "CLICK",
                    "selector": "#det-fan-high",
                    "source_text": "대상 장비의 풍량으로 HIGH를 선택하고 적용한다.",
                },
                {
                    "action_id": "ACT-103",
                    "phase": "TEST",
                    "action_type": "APPLY_COMMANDS",
                    "selector": ".btn-apply-cmd",
                    "source_text": "대상 장비의 풍량으로 HIGH를 선택하고 적용한다.",
                },
            ],
            "assertions": [
                {
                    "result_id": "ER-101",
                    "observation_layer": "UI",
                    "strategy": "UI_TEXT_CONTAINS",
                    "selector": "#device-card-1",
                    "expected_text": "강풍",
                },
                {
                    "result_id": "ER-102",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
                    "selector": "window.__vccs.devices",
                    "expected_fields": [
                        {"field_name": "fanSpeed", "expected_value": "HIGH"}
                    ],
                },
            ],
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)

    assert checkpoint.status == CheckStatus.PASS
    assert next(
        item for item in checkpoint.checks if item.rule_id == "CP3-004"
    ).status == CheckStatus.PASS

    strict = pipeline.evaluate_checkpoint3_plan(test_case, plan, observation,
        require_precondition_proof=False)
    assert strict.status == CheckStatus.PASS
    shortened = plan.model_copy(deep=True)
    shortened.assertions[0].expected_text = "풍"
    rejected = pipeline.evaluate_checkpoint3_plan(test_case, shortened, observation,
        require_precondition_proof=False)
    assert rejected.status == CheckStatus.FAIL
    assert any("only part" in item.message for item in rejected.checks)

    restore_step = "시험 뒤 대상 장비의 풍량을 LOW로 복원한다."
    restorable_case = test_case.model_copy(
        update={"restore_required": True, "restore_steps": [restore_step]}
    )
    restorable_plan = plan.model_copy(
        update={
            "actions": [
                *plan.actions,
                AutomationAction(
                    action_id="ACT-104",
                    phase=AutomationPhase.RESTORE,
                    action_type=AutomationActionType.CLICK,
                    selector="#det-fan-low",
                    source_text=restore_step,
                ),
            ]
        }
    )
    compiled = compile_automation_candidate(
        "RUN-20260829-120000-ABCDEF", restorable_case, restorable_plan
    )
    assert "restore_baseline_0" in compiled
    assert "'fields': ['fanSpeed']" in compiled
    assert "if restore_actual != restore_baseline_0" in compiled

def test_agent3_notification_rejects_the_whole_expected_result_as_ui_text() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][2] = {
        "result_id": "ER-007",
        "observation_layer": "NOTIFICATION",
        "strategy": "UI_TEXT_CONTAINS",
        "selector": "#global-toast",
        "expected_text": "A blocking Toast is visible.",
    }

    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "not the whole Expected Result sentence" in item.message
        for item in checkpoint.checks
    )

def test_agent3_generic_discovery_compiles_and_runs_a_new_control(
    tmp_path: Path,
) -> None:
    test_case = generic_new_control_test_case()
    eligibility = evaluate_agent3_eligibility(test_case)
    assert eligibility.status == Agent3EligibilityStatus.DISCOVERY_REQUIRED
    assert eligibility.generic_discovery_required is True

    target = tmp_path / "new-control.html"
    target.write_text(
        """<!doctype html><html><head><title>New Control</title></head><body>
<label for="new-feature-toggle">새 제어</label>
<input id="new-feature-toggle" type="checkbox">
<span id="new-feature-status">꺼짐</span>
<script>
window.__vccs = {feature: {enabled: false}};
const toggle = document.getElementById('new-feature-toggle');
toggle.addEventListener('change', () => {
  window.__vccs.feature.enabled = toggle.checked;
  document.getElementById('new-feature-status').textContent = toggle.checked ? '켜짐' : '꺼짐';
});
</script></body></html>""",
        encoding="utf-8",
    )
    observation = inspect_target_ui(
        target,
        required_selectors=set(),
        required_harness_keys=set(),
        discover_generic=True,
    )
    elements = {item.selector: item for item in observation.elements}
    assert elements["#new-feature-toggle"].action_hint == "CHECK_OR_UNCHECK"
    assert observation.harness_values["window.__vccs.feature.enabled"] is False

    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": test_case.tc_id,
            "target_device_id": 1,
            "summary": "Use the newly observed generic switch and verify both layers.",
            "actions": [
                {
                    "action_id": "ACT-090",
                    "phase": "TEST",
                    "action_type": "CHECK",
                    "selector": "#new-feature-toggle",
                    "source_text": "새 제어 스위치를 켠다.",
                },
                {
                    "action_id": "ACT-091",
                    "phase": "RESTORE",
                    "action_type": "UNCHECK",
                    "selector": "#new-feature-toggle",
                    "source_text": "새 제어 스위치를 끈다.",
                },
            ],
            "assertions": [
                {
                    "result_id": "ER-090",
                    "observation_layer": "UI",
                    "strategy": "UI_CHECKED_EQUALS",
                    "selector": "#new-feature-toggle",
                    "expected_value": True,
                },
                {
                    "result_id": "ER-091",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_VALUE_EQUALS",
                    "selector": "window.__vccs.feature.enabled",
                    "expected_value": True,
                },
            ],
        }
    )
    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)
    assert checkpoint.status == CheckStatus.PASS

    code = compile_automation_candidate("RUN-20260816-NEW001-ABCDEF", test_case, plan)
    assert "restore_baseline_0" in code
    assert "restore_control_checked" in code
    assert "#new-feature-toggle" in code
    assert "window.__vccs.feature.enabled" in code
    assert "#det-temp-display" not in code
    assert "#det-temp-up-btn" not in code
    assert "#det-temp-down-btn" not in code
    assert "window.__vccs.devices" not in code
    assert all(
        item.status == CheckStatus.PASS
        for item in evaluate_compiled_candidate(test_case, code)
    )
    candidate = tmp_path / "test_new_control.py"
    candidate.write_text(code, encoding="utf-8")
    trial = run_candidate_trial(
        candidate,
        target,
        tmp_path / "new-control-evidence",
        timeout_seconds=90,
    )
    assert trial.outcome == TrialOutcome.PASS

def test_grouped_hvac_trial_restores_runtime_baseline(tmp_path: Path) -> None:
    test_case = ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-099",
            "title": "묶음 모드·온도 조건 실행과 원래 상태 복원",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "STATE_CONSISTENCY",
            "requirement_ids": ["REQ-MODE-001", "REQ-TEMP-001"],
            "source_condition_ids": ["COND-099"],
            "control_path": "CENTRAL",
            "target_role": "PRIMARY_TEST_DEVICE",
            "test_data": {
                "requested_modes": ["AUTO", "COOL"],
                "requested_temperatures_c": [18, 30],
                "restore_observed_hvac_state": True,
            },
            "condition_execution": "SEQUENTIAL_TRANSITION",
            "grouping_reason": "같은 장비의 모드·온도 전환 규칙을 순서대로 확인한다.",
            "preconditions": ["온라인 정상 장비를 단일 대상으로 선택한다."],
            "steps": [
                "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
            ],
            "expected_results": [
                {
                    "result_id": "ER-099",
                    "statement": "내부 mode 값은 AUTO이고 setTemp 값은 18이다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-099"],
                    "verify_after_step": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "result_id": "ER-100",
                    "statement": "내부 mode 값은 COOL이고 setTemp 값은 30이다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-099"],
                    "verify_after_step": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
            ],
            "restore_required": True,
            "restore_steps": [
                "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다."
            ],
            "automation_candidate": True,
            "automation_reason": "관찰된 중앙 관제 모드·온도 UI와 내부 상태를 사용한다.",
        }
    )
    eligibility = evaluate_agent3_eligibility(test_case)
    target = REPO_ROOT / "product_baseline" / "virtual-controller.html"
    target_hash = _sha256_file(target)
    observation = inspect_target_ui(
        target,
        required_selectors=set(eligibility.required_selectors),
        required_harness_keys=set(eligibility.required_harness_keys),
        discover_generic=eligibility.generic_discovery_required,
    )
    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": test_case.tc_id,
            "target_device_id": 1,
            "summary": "두 조건을 판정한 뒤 실행 직전 HVAC 상태를 복원한다.",
            "actions": [
                {
                    "action_id": "ACT-090",
                    "phase": "PRECONDITION",
                    "action_type": "SELECT_DEVICE",
                    "selector": "#device-card-1 .card-body-split",
                    "value": 1,
                    "source_text": "온라인 정상 장비를 단일 대상으로 선택한다.",
                },
                {
                    "action_id": "ACT-091",
                    "phase": "TEST",
                    "action_type": "SET_MODE",
                    "selector": "#det-mode-auto",
                    "value": "AUTO",
                    "source_text": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-092",
                    "phase": "TEST",
                    "action_type": "SET_TEMPERATURE",
                    "selector": "#det-temp-display",
                    "value": 18,
                    "source_text": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-093",
                    "phase": "TEST",
                    "action_type": "APPLY_COMMANDS",
                    "selector": ".btn-apply-cmd",
                    "source_text": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-094",
                    "phase": "TEST",
                    "action_type": "SET_MODE",
                    "selector": "#det-mode-cool",
                    "value": "COOL",
                    "source_text": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-095",
                    "phase": "TEST",
                    "action_type": "SET_TEMPERATURE",
                    "selector": "#det-temp-display",
                    "value": 30,
                    "source_text": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-096",
                    "phase": "TEST",
                    "action_type": "APPLY_COMMANDS",
                    "selector": ".btn-apply-cmd",
                    "source_text": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-097",
                    "phase": "RESTORE",
                    "action_type": "RESTORE_OBSERVED_HVAC",
                    "selector": ".btn-apply-cmd",
                    "source_text": "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다.",
                },
            ],
            "assertions": [
                {
                    "result_id": "ER-099",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
                    "selector": "window.__vccs.devices",
                    "expected_fields": [
                        {"field_name": "mode", "expected_value": "AUTO"},
                        {"field_name": "setTemp", "expected_value": 18},
                    ],
                    "after_action_id": "ACT-093",
                },
                {
                    "result_id": "ER-100",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
                    "selector": "window.__vccs.devices",
                    "expected_fields": [
                        {"field_name": "mode", "expected_value": "COOL"},
                        {"field_name": "setTemp", "expected_value": 30},
                    ],
                    "after_action_id": "ACT-096",
                },
            ],
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)
    assert checkpoint.status == CheckStatus.PASS
    code = compile_automation_candidate(
        "RUN-20260827-130000-ABCDEF", test_case, plan
    )
    assert "observed_hvac_baseline" in code
    assert "restored_hvac_state != observed_hvac_baseline" in code
    assert all(
        item.status == CheckStatus.PASS
        for item in evaluate_compiled_candidate(test_case, code)
    )
    candidate = tmp_path / "test_dynamic_hvac_restore.py"
    candidate.write_text(code, encoding="utf-8")
    trial = run_candidate_trial(
        candidate,
        target,
        tmp_path / "dynamic-hvac-evidence",
        timeout_seconds=90,
    )

    assert trial.outcome == TrialOutcome.PASS
    assert _sha256_file(target) == target_hash

def test_agent3_records_support_extension_without_generating_code() -> None:
    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": "TC-CAND-090",
            "target_device_id": 1,
            "summary": "The observed control requires an unsupported interaction.",
            "planning_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
            "extension_reasons": [
                "The approved step requires a drag interaction that is not in the generic action set."
            ],
        }
    )
    checkpoint = evaluate_checkpoint3_plan(
        generic_new_control_test_case(), plan, agent3_observation()
    )
    assert checkpoint.status == CheckStatus.REVIEW
    assert (
        checkpoint.candidate_status
        == AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
    )
    assert checkpoint.checks[0].rule_id == "CP3-000"

def test_agent3_non_candidate_records_not_automatable_before_ui_or_model(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260815-120000-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "agent2_manifest.json").write_text("{}", encoding="utf-8")
    payload = agent3_test_case().model_dump(mode="json")
    payload["automation_candidate"] = False
    payload["automation_reason"] = "CP2 did not approve automation."
    non_candidate = ProductTestCaseCandidate.model_validate(payload)
    design = SimpleNamespace(test_cases=[non_candidate])
    monkeypatch.setattr(
        pipeline_execution,
        "_load_verified_agent2_run",
        lambda *_: (
            None,
            {},
            None,
            design,
            None,
            {"agent2_design_sha256": "b" * 64},
        ),
    )

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("UI inspection and model construction must not run")

    monkeypatch.setattr(pipeline_execution, "inspect_target_ui", unexpected_call)
    monkeypatch.setattr(pipeline_execution, "OpenAIAgent3", unexpected_call)
    args = SimpleNamespace(
        runs_root=str(tmp_path),
        run_id=run_id,
        tc_id=non_candidate.tc_id,
        target_html=str(tmp_path / "unused.html"),
        model=None,
        timeout=30,
        preview_only=False,
    )

    assert pipeline.run_agent3(args) == 2
    result = json.loads((run_dir / "agent3_eligibility.json").read_text(encoding="utf-8"))
    assert result["status"] == "NOT_AUTOMATABLE"
    assert result["candidate_status"] == "NOT_AUTOMATABLE"
    assert result["model_call_allowed"] is False
    assert result["source_agent2_design_sha256"] == "b" * 64
    assert "CP2_AUTOMATION_CANDIDATE" in result["missing_capabilities"]
    assert not (run_dir / "agent3_model_input_preview.json").exists()
    assert not (run_dir / "agent3_error.json").exists()

def test_agent3_preview_does_not_require_api_key_or_create_model_client(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260815-120001-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "agent2_manifest.json").write_text("{}", encoding="utf-8")
    design = SimpleNamespace(test_cases=[agent3_test_case()])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        pipeline_execution,
        "_load_verified_agent2_run",
        lambda *_: (
            None,
            {},
            None,
            design,
            None,
            {"agent2_design_sha256": "c" * 64},
        ),
    )
    monkeypatch.setattr(
        pipeline_execution,
        "inspect_target_ui",
        lambda *_args, **_kwargs: agent3_observation(),
    )

    def unexpected_model_client(*_args, **_kwargs):
        raise AssertionError("Preview must not create the Agent 3 model client")

    monkeypatch.setattr(pipeline_execution, "OpenAIAgent3", unexpected_model_client)
    args = SimpleNamespace(
        runs_root=str(tmp_path),
        run_id=run_id,
        tc_id=agent3_test_case().tc_id,
        target_html=str(tmp_path / "unused.html"),
        model=None,
        timeout=30,
        preview_only=True,
    )

    assert pipeline.run_agent3(args) == 0
    preview = json.loads(
        (run_dir / "agent3_model_input_preview.json").read_text(encoding="utf-8")
    )
    assert preview["destination"] == "OpenAI Responses API"
    assert not (run_dir / "agent3_error.json").exists()

def test_valid_agent3_plan_passes_cp3_and_compiles() -> None:
    tc = agent3_test_case()
    plan = agent3_plan()
    checkpoint = evaluate_checkpoint3_plan(tc, plan, agent3_observation())
    assert checkpoint.status == CheckStatus.PASS
    code = compile_automation_candidate("RUN-20260813-120000-ABCDEF", tc, plan)
    checks = evaluate_compiled_candidate(tc, code)
    assert all(item.status == CheckStatus.PASS for item in checks)
    assert "# EXPECTED_RESULT: ER-007" in code
    assert "PRODUCT_MISMATCH:" in code

    test_phase_selection = plan.actions[0].model_copy(
        update={
            "phase": AutomationPhase.TEST,
            "source_text": tc.steps[0],
        }
    )
    test_phase_plan = plan.model_copy(
        update={
            "actions": [
                *plan.actions[1:4],
                test_phase_selection,
                *plan.actions[4:],
            ]
        }
    )
    test_phase_checkpoint = evaluate_checkpoint3_plan(
        tc, test_phase_plan, agent3_observation()
    )
    assert test_phase_checkpoint.status == CheckStatus.PASS

    late_selection_plan = test_phase_plan.model_copy(
        update={
            "actions": [
                *test_phase_plan.actions[:3],
                test_phase_plan.actions[4],
                test_phase_plan.actions[3],
                *test_phase_plan.actions[5:],
            ]
        }
    )
    late_selection_checkpoint = evaluate_checkpoint3_plan(
        tc, late_selection_plan, agent3_observation()
    )
    assert late_selection_checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-006A"
        and "selection occurs after" in item.message
        for item in late_selection_checkpoint.checks
    )

def test_agent3_grouped_tc_interleaves_assertions_before_next_condition() -> None:
    test_case, plan = grouped_agent3_case_and_plan()

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, agent3_observation())
    code = compile_automation_candidate(
        "RUN-20260825-GROUPED-ABCDEF", test_case, plan
    )

    assert checkpoint.status == CheckStatus.PASS
    assert next(
        item for item in checkpoint.checks if item.rule_id == "CP3-003A"
    ).status == CheckStatus.PASS
    assert code.index("# ACT-006") < code.index("# EXPECTED_RESULT: ER-005")
    assert code.index("# EXPECTED_RESULT: ER-007") < code.index("# ACT-007")
    assert code.index("# ACT-010") < code.index("# EXPECTED_RESULT: ER-008")
    assert "_request_temperature(page, 17.0)" in code
    assert "_set_temperature(page, 30.0)" in code
    assert "_request_temperature(page, 31.0)" in code

def test_agent3_grouped_tc_rejects_unanchored_condition_results() -> None:
    test_case, plan = grouped_agent3_case_and_plan()
    unanchored = plan.model_copy(
        update={
            "assertions": [
                assertion.model_copy(update={"after_action_id": None})
                for assertion in plan.assertions
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(
        test_case, unanchored, agent3_observation()
    )

    assert checkpoint.status == CheckStatus.FAIL
    check = next(
        item for item in checkpoint.checks if item.rule_id == "CP3-003A"
    )
    assert check.status == CheckStatus.FAIL
    assert "no after_action_id" in check.message

    early_assertions = list(plan.assertions)
    early_assertions[0] = early_assertions[0].model_copy(
        update={"after_action_id": "ACT-005"}
    )
    early_checkpoint = evaluate_checkpoint3_plan(
        test_case,
        plan.model_copy(update={"assertions": early_assertions}),
        agent3_observation(),
    )
    early_check = next(
        item for item in early_checkpoint.checks if item.rule_id == "CP3-003A"
    )
    assert early_check.status == CheckStatus.FAIL
    assert "not anchored after the last action" in early_check.message

def test_legacy_central_plan_cannot_bypass_required_actions_with_generic_assertion() -> None:
    base = agent3_plan()
    plan = base.model_copy(
        update={
            "actions": [base.actions[-1]],
            "assertions": [
                base.assertions[0],
                base.assertions[1],
                AutomationAssertion(
                    result_id="ER-007",
                    observation_layer="NOTIFICATION",
                    strategy="UI_TEXT_CONTAINS",
                    selector="#global-toast",
                    expected_text="Toast",
                ),
            ],
        }
    )

    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(), plan, agent3_observation()
    )

    assert checkpoint.status == CheckStatus.FAIL
    sequence_check = next(
        item for item in checkpoint.checks if item.rule_id == "CP3-006A"
    )
    assert sequence_check.status == CheckStatus.FAIL
    assert "target device selection is missing" in sequence_check.message
    assert "requested temperature action is missing" in sequence_check.message

def test_specialized_action_source_text_must_be_an_approved_tc_line() -> None:
    base = agent3_plan()
    actions = list(base.actions)
    actions[0] = actions[0].model_copy(
        update={"source_text": "Model-invented setup step"}
    )

    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        base.model_copy(update={"actions": actions}),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-002"
        and "source_text is not an exact approved TC line" in item.message
        for item in checkpoint.checks
    )

def test_blocked_temperature_request_compiles_until_target_or_stall() -> None:
    code = compile_automation_candidate(
        "RUN-20260813-120000-ABCDEF", agent3_test_case(), agent3_plan()
    )
    assert "def _request_temperature(page, target):" in code
    assert "if after == before:" in code
    assert "_request_temperature(page, 17.0)" in code

def test_central_blocked_temperature_without_notification_uses_stall_request() -> None:
    test_case_payload = agent3_test_case().model_dump(mode="json")
    test_case_payload["expected_results"] = test_case_payload["expected_results"][:2]
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"] = plan_payload["assertions"][:2]

    test_case = ProductTestCaseCandidate.model_validate(test_case_payload)
    plan = Agent3AutomationPlan.model_validate(plan_payload)
    checkpoint = evaluate_checkpoint3_plan(test_case, plan, agent3_observation())
    code = compile_automation_candidate(
        "RUN-20260823-CENTRAL-ABCDEF", test_case, plan
    )

    assert checkpoint.status == CheckStatus.PASS
    assert "_request_temperature(page, 17.0)" in code
    assert "simulateLocalTemp" not in code
    assert "#qa-drawer-panel" not in code
    compile(code, "<central-candidate>", "exec")

def test_restore_contract_requires_initial_temperature_and_apply() -> None:
    tc = agent3_test_case().model_copy(
        update={
            "restore_required": True,
            "restore_steps": ["Restore AUTO 18 and verify UI and internal state."],
        }
    )
    plan = agent3_plan().model_copy(
        update={
            "actions": [
                *agent3_plan().actions,
                AutomationAction(
                    action_id="ACT-007",
                    phase="RESTORE",
                    action_type="SET_TEMPERATURE",
                    selector="#det-temp-display",
                    value=17.0,
                    source_text="Restore AUTO 18 and verify UI and internal state.",
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase="RESTORE",
                    action_type="APPLY_COMMANDS",
                    selector=".btn-apply-cmd",
                    source_text="Restore AUTO 18 and verify UI and internal state.",
                ),
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(tc, plan, agent3_observation())

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-006"
        and item.status == CheckStatus.FAIL
        and "initial temperature restore is missing" in item.message
        for item in checkpoint.checks
    )

def test_compiler_verifies_restored_ui_and_internal_temperature() -> None:
    tc = agent3_test_case().model_copy(
        update={
            "restore_required": True,
            "restore_steps": ["Restore AUTO 18 and verify UI and internal state."],
        }
    )
    plan = agent3_plan().model_copy(
        update={
            "actions": [
                *agent3_plan().actions,
                AutomationAction(
                    action_id="ACT-007",
                    phase="RESTORE",
                    action_type="SET_TEMPERATURE",
                    selector="#det-temp-display",
                    value=18.0,
                    source_text="Restore AUTO 18 and verify UI and internal state.",
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase="RESTORE",
                    action_type="APPLY_COMMANDS",
                    selector=".btn-apply-cmd",
                    source_text="Restore AUTO 18 and verify UI and internal state.",
                ),
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(tc, plan, agent3_observation())
    code = compile_automation_candidate("RUN-20260813-120000-ABCDEF", tc, plan)
    compiled_checks = evaluate_compiled_candidate(tc, code)

    assert checkpoint.status == CheckStatus.PASS
    assert all(item.status == CheckStatus.PASS for item in compiled_checks)
    assert "restore_ui_temperature = _temperature(page)" in code
    assert "restore_internal_temperature = page.evaluate" in code
    assert "RESTORE_MISMATCH:" in code

def test_unobserved_selector_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["actions"][0]["selector"] = "#invented-selector"
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-002" and item.status == CheckStatus.FAIL for item in checkpoint.checks)

def test_observed_but_wrong_action_selector_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["actions"][1]["selector"] = "#det-mode-cool"
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-002" and item.status == CheckStatus.FAIL for item in checkpoint.checks)

def test_missing_select_device_value_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["actions"][0]["value"] = None
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-002"
        and item.status == CheckStatus.FAIL
        and "invalid device selector or target value" in item.message
        for item in checkpoint.checks
    )

def test_observed_but_wrong_assertion_selector_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][0]["selector"] = "#det-temp-adjust-card"
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "invalid observation target" in item.message
        for item in checkpoint.checks
    )

def test_ungrounded_numeric_expectation_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][0]["expected_number"] = 19.0
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-004" and item.status == CheckStatus.FAIL for item in checkpoint.checks)
    assert any(item.rule_id == "CP3-005" and item.status == CheckStatus.FAIL for item in checkpoint.checks)

def test_unsupported_expected_text_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][2]["expected_text"] = "warning message"
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "expected_text is unsupported" in item.message
        for item in checkpoint.checks
    )

def test_generic_visible_toast_is_rejected_for_blocking_expected_result() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][2]["strategy"] = "TOAST_VISIBLE"
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "assertion strategy changed" in item.message
        for item in checkpoint.checks
    )

def test_missing_expected_result_mapping_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"] = payload["assertions"][:-1]
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-003" and item.status == CheckStatus.FAIL for item in checkpoint.checks)

def test_agent3_trial_distinguishes_product_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "virtual-controller.html"
    target.write_text(
        """<!doctype html><title>Virtual Controller</title>
<div id='device-card-1'><button class='card-body-split' onclick='selectUnit(1)'>device</button></div>
<button id='det-mode-cool'></button><button id='det-mode-heat'></button><button id='det-mode-fan'></button><button id='det-mode-dry'></button>
<button id='det-mode-auto' onclick=\"pendingState.mode='AUTO'\"></button>
<div id='det-temp-adjust-card'><span id='det-temp-display'>24.0 C</span></div>
<button id='det-temp-down-btn' onclick='adjust(-1)'>-</button><button id='det-temp-up-btn' onclick='adjust(1)'>+</button>
<button class='btn-apply-cmd' onclick='applyPanelCommands()'>apply</button><div id='global-toast' class='toast-box'>warning</div>
<script>
let devices=[{id:1,setTemp:24,mode:'COOL'}]; let pendingState={setTemp:24,mode:'COOL'}; let selectedUnitId=null;
function draw(){document.getElementById('det-temp-display').innerText=pendingState.setTemp.toFixed(1)+' C'}
function selectUnit(id){selectedUnitId=id; pendingState={...devices[0]}; draw()}
function adjust(v){pendingState.setTemp+=v; draw()}
function applyPanelCommands(){devices[0].setTemp=pendingState.setTemp; devices[0].mode=pendingState.mode; let toast=document.getElementById('global-toast'); toast.innerText='Successfully applied'; toast.className='toast-box show'}
window.__vccs={get devices(){return devices},get pendingState(){return pendingState},get selectedUnitId(){return selectedUnitId},selectUnit,applyPanelCommands,renderGrid(){},saveStateToLocalStorage(){}};
</script>""",
        encoding="utf-8",
    )
    observation = inspect_target_ui(target)
    assert observation.page_title == "Virtual Controller"
    assert {"mode", "setTemp"} <= set(observation.device_state_fields)
    test_case_payload = agent3_test_case().model_dump(mode="json")
    test_case_payload["expected_results"][1]["statement"] = (
        "Internal mode is AUTO and setTemp remains at 18 degrees."
    )
    test_case = ProductTestCaseCandidate.model_validate(test_case_payload)
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"][1] = {
        "result_id": "ER-006",
        "observation_layer": "INTERNAL_STATE",
        "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
        "selector": "window.__vccs.devices",
        "expected_fields": [
            {"field_name": "mode", "expected_value": "AUTO"},
            {"field_name": "setTemp", "expected_value": 18},
        ],
    }
    plan = Agent3AutomationPlan.model_validate(plan_payload)
    assert evaluate_checkpoint3_plan(test_case, plan, observation).status == CheckStatus.PASS
    candidate = tmp_path / "candidate.py"
    candidate.write_text(
        compile_automation_candidate("RUN-20260813-120000-ABCDEF", test_case, plan),
        encoding="utf-8",
    )
    trial = run_candidate_trial(candidate, target, tmp_path / "evidence", timeout_seconds=20)
    assert trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
    assert trial.evidence_complete is True
    assert set(trial.evidence_sha256) == {
        "trial-stdout.txt",
        "trial-stderr.txt",
        "trial-final.png",
        "trial-trace.zip",
    }
    stdout = (tmp_path / "evidence" / "trial-stdout.txt").read_text(encoding="utf-8")
    assert "ER-007: toast does not indicate blocking: successfully applied" in stdout
    assert "ER-006: internal device fields={'mode': 'AUTO', 'setTemp': 17}" in stdout
    with zipfile.ZipFile(tmp_path / "evidence" / "trial-trace.zip") as archive:
        trace_payload = b"".join(archive.read(name) for name in archive.namelist())
    assert str(tmp_path.resolve()).encode("utf-8") not in trace_payload
    assert tmp_path.resolve().as_uri().encode("utf-8") not in trace_payload

def test_agent3_trace_redaction_handles_path_uri_and_json_escapes(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "사용자 폴더"
    local_root.mkdir()
    trace_file = tmp_path / "trial-trace.zip"
    raw_path = str(local_root.resolve())
    raw_uri = local_root.resolve().as_uri()
    escaped_path = json.dumps(raw_path, ensure_ascii=True)[1:-1]
    with zipfile.ZipFile(trace_file, "w") as archive:
        archive.writestr(
            "trace.trace",
            f"path={raw_path}\nuri={raw_uri}\nescaped={escaped_path}".encode("utf-8"),
        )
        archive.writestr("resources/evidence.bin", b"unchanged-binary-evidence")

    pipeline._redact_playwright_trace(
        trace_file,
        {local_root: "<LOCAL_ROOT>"},
    )

    with zipfile.ZipFile(trace_file) as archive:
        redacted = archive.read("trace.trace").decode("utf-8")
        binary = archive.read("resources/evidence.bin")
    assert raw_path not in redacted
    assert raw_uri not in redacted
    assert escaped_path not in redacted
    assert redacted.count("<LOCAL_ROOT>") == 3
    assert binary == b"unchanged-binary-evidence"

def test_agent3_trial_strips_secrets_and_redacts_local_paths(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def test_candidate():\n    assert False\n", encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    captured_env = {}

    def fake_run(_command, *, cwd, env, timeout_seconds):
        assert timeout_seconds == 5
        captured_env.update(env)
        local_path = str(target.resolve())
        temp_path = str(Path(cwd).resolve())
        return SimpleNamespace(
            returncode=1,
            stdout=f"한글 실행 증거\n{local_path}\n{temp_path}",
            stderr="",
        )

    for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "must-not-reach-trial")
    monkeypatch.setattr(pipeline_execution, "_run_trial_subprocess", fake_run)

    evidence_dir = tmp_path / "evidence"
    result = run_candidate_trial(candidate, target, evidence_dir, timeout_seconds=5)

    assert result.outcome == TrialOutcome.AUTOMATION_ERROR
    assert all(name not in captured_env for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"))
    allowed = set(pipeline._AGENT3_TRIAL_ENV_ALLOWLIST) | {"QA_TARGET_URL", "QA_EVIDENCE_DIR"}
    assert set(captured_env) <= allowed
    assert captured_env["PYTHONUTF8"] == "0"
    assert captured_env["PYTHONIOENCODING"] == "utf-8"
    stdout = (evidence_dir / "trial-stdout.txt").read_text(encoding="utf-8")
    assert "한글 실행 증거" in stdout
    assert str(target.resolve()) not in stdout
    assert "<LOCAL_PATH>" in stdout

def test_agent3_timeout_discards_incomplete_unredacted_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def test_candidate():\n    pass\n", encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    evidence = tmp_path / "evidence"

    def fake_timeout(command, *, cwd, env, timeout_seconds):
        trace = Path(env["QA_EVIDENCE_DIR"]) / "trial-trace.zip"
        trace.write_bytes(b"incomplete trace with unredacted local data")
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    monkeypatch.setattr(pipeline_execution, "_run_trial_subprocess", fake_timeout)
    result = run_candidate_trial(
        candidate,
        target,
        evidence,
        timeout_seconds=5,
    )

    assert result.outcome == TrialOutcome.TIMEOUT
    assert result.trace_file is None
    assert result.evidence_complete is False
    assert not (evidence / "trial-trace.zip").exists()

def test_trial_timeout_terminates_playwright_child_processes(tmp_path: Path) -> None:
    psutil = pytest.importorskip("psutil")
    child_pid_file = tmp_path / "child.pid"
    parent_script = (
        "import subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        pipeline._run_trial_subprocess(
            [sys.executable, "-c", parent_script, str(child_pid_file)],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=2,
        )

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    for _ in range(20):
        if not psutil.pid_exists(child_pid):
            break
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)

@pytest.mark.parametrize(
    ("outcome", "expected_exit_code"),
    [
        (TrialOutcome.PASS, 0),
        (TrialOutcome.PRODUCT_MISMATCH_CANDIDATE, 0),
        (TrialOutcome.AUTOMATION_ERROR, 2),
        (TrialOutcome.ENVIRONMENT_ERROR, 2),
        (TrialOutcome.TIMEOUT, 2),
    ],
)
def test_agent3_cli_exit_code_reflects_trial_trustworthiness(
    outcome: TrialOutcome,
    expected_exit_code: int,
) -> None:
    assert (
        pipeline._agent3_cli_exit_code(
            _checkpoint3(CheckStatus.PASS),
            _trial(outcome),
        )
        == expected_exit_code
    )

def test_agent3_cli_exit_code_blocks_missing_trial_or_failed_checkpoint() -> None:
    assert pipeline._agent3_cli_exit_code(_checkpoint3(CheckStatus.PASS), None) == 2
    assert (
        pipeline._agent3_cli_exit_code(
            _checkpoint3(CheckStatus.FAIL),
            _trial(TrialOutcome.PASS),
        )
        == 2
    )
    incomplete = _trial(TrialOutcome.PASS).model_copy(
        update={"evidence_complete": False, "evidence_sha256": {}}
    )
    assert pipeline._agent3_cli_exit_code(
        _checkpoint3(CheckStatus.PASS), incomplete
    ) == 2
    extra_hash = _trial(TrialOutcome.PASS).model_copy(
        update={
            "evidence_sha256": {
                **_trial(TrialOutcome.PASS).evidence_sha256,
                "not-recorded.txt": "e" * 64,
            }
        }
    )
    assert pipeline._agent3_cli_exit_code(
        _checkpoint3(CheckStatus.PASS), extra_hash
    ) == 2

def test_agent3_usage_aggregates_all_planning_attempts() -> None:
    attempts = [
        {
            "attempt": 1,
            "usage": {
                "input_tokens": 2337,
                "output_tokens": 1023,
                "total_tokens": 3360,
            },
        },
        {
            "attempt": 2,
            "usage": {
                "input_tokens": 3157,
                "output_tokens": 1139,
                "total_tokens": 4296,
            },
        },
    ]

    assert pipeline._aggregate_agent3_usage(attempts) == {
        "input_tokens": 5494,
        "output_tokens": 2162,
        "total_tokens": 7656,
    }
    assert pipeline._aggregate_model_usage(attempts) == {
        "input_tokens": 5494,
        "output_tokens": 2162,
        "total_tokens": 7656,
    }

def test_model_usage_records_cache_and_reasoning_details() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=30,
            total_tokens=130,
            input_tokens_details=SimpleNamespace(
                cached_tokens=80,
                cache_write_tokens=20,
            ),
            output_tokens_details=SimpleNamespace(reasoning_tokens=12),
        )
    )

    usage = pipeline._response_usage_summary(response)

    assert usage == {
        "input_tokens": 100,
        "output_tokens": 30,
        "total_tokens": 130,
        "cached_input_tokens": 80,
        "cache_write_input_tokens": 20,
        "reasoning_output_tokens": 12,
    }
    assert pipeline._aggregate_model_usage(
        [{"usage": usage}, {"usage": usage}]
    )["cached_input_tokens"] == 160

def test_agent2_duplicate_technical_ids_are_normalized_without_semantic_changes() -> None:
    first = agent2_design().test_cases[0]
    second = first.model_copy(update={"title": "독립적인 두 번째 경계값 검증"})
    original = Agent2TestDesign(
        request_id="CR-TEST-001",
        test_cases=[first, second],
        coverage_summary="중복 기술 ID 정리 검증",
    )

    normalized, changes = pipeline._normalize_agent2_technical_ids(original)

    assert [item.tc_id for item in original.test_cases] == [
        "TC-CAND-001",
        "TC-CAND-001",
    ]
    assert [item.tc_id for item in normalized.test_cases] == [
        "TC-CAND-001",
        "TC-CAND-002",
    ]
    assert [
        result.result_id
        for item in normalized.test_cases
        for result in item.expected_results
    ] == [f"ER-{index:03d}" for index in range(1, 7)]
    assert changes

    def without_technical_ids(test_case):
        payload = test_case.model_dump(mode="json")
        payload.pop("tc_id")
        for result in payload["expected_results"]:
            result.pop("result_id")
        return payload

    assert [without_technical_ids(item) for item in normalized.test_cases] == [
        without_technical_ids(item) for item in original.test_cases
    ]

def test_agent3_error_artifact_requires_a_fresh_attempt_workspace(
    tmp_path: Path,
) -> None:
    run_id = "RUN-20260815-120002-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "agent3_error.json").write_text("{}", encoding="utf-8")
    args = SimpleNamespace(
        runs_root=str(tmp_path),
        run_id=run_id,
        tc_id=agent3_test_case().tc_id,
        target_html=str(tmp_path / "unused.html"),
        model=None,
        timeout=30,
        preview_only=False,
    )

    with pytest.raises(ValueError, match="final Agent 3 artifacts"):
        pipeline.run_agent3(args)

def test_modified_agent2_artifact_is_blocked_before_agent3(tmp_path: Path) -> None:
    # Test design tampering independently of historical checkout line endings.
    run_dir, run_id = build_historical_agent2_run(tmp_path)
    pipeline._load_verified_agent2_run(run_dir, run_id)
    design_file = run_dir / "agent2_test_design.json"
    design_file.write_text(design_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Agent 2 design"):
        pipeline._load_verified_agent2_run(run_dir, run_id)
