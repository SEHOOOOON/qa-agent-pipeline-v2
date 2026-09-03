"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_agent3_uses_structured_plan_api() -> None:
    responses = Agent3FakeResponses()
    result = OpenAIAgent3(model="test-model", client=SimpleNamespace(responses=responses)).plan(
        agent3_test_case(), agent3_observation(), {"REQ-TEMP-001": SrsRequirement(requirement_id="REQ-TEMP-001", statement="range", acceptance_criteria="block")}
    )
    assert result.plan.tc_id == "TC-CAND-003"
    assert responses.kwargs["text_format"] is Agent3AutomationPlan
    assert responses.kwargs["store"] is False
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent3-3-18"
    instructions = responses.kwargs["input"][0]["content"]
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
    import shutil

    source = REPO_ROOT / "examples" / "results" / "agent1-agent2-auto-temperature"
    run_id = "RUN-20260813-125229-31EB5F"
    run_dir = tmp_path / run_id
    shutil.copytree(source, run_dir)
    design_file = run_dir / "agent2_test_design.json"
    design_file.write_text(design_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Agent 2 design"):
        pipeline._load_verified_agent2_run(run_dir, run_id)
