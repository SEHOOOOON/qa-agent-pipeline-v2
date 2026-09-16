from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator
from qa_pipeline_trace import redact_playwright_trace as _redact_playwright_trace
from qa_pipeline_io import *
from qa_pipeline_contracts import *
from qa_pipeline_agent1 import *
from qa_pipeline_agent2 import *

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Agent 3: Evidence-grounded automation planning
# ---------------------------------------------------------------------------
AGENT3_SYSTEM_INSTRUCTIONS = """
Check only conditions stated in the approved TC preconditions; observed facts are available evidence, not additional requirements. Do not add online, visibility, login or selected-state checks merely because the inventory mentions them. A single-device target scope does not itself request a selectedUnitId assertion; an explicitly required selected state still needs its own observed proof.
For BASELINE_CONTEXT, error_free applies to a stated no-error condition, unlocked to a stated unlocked condition, online only to explicit 온라인/online, and target_device_visible to a matching target-device/visibility phrase. Include all facts stated in a compound line, not every available context field. Unknown role/login conditions require their own observed read-only evidence, never the baseline context. Never rewrite the TC source to justify an extra check.
Every READY plan must include precondition_checks covering EVERY exact TC preconditions line, including already-satisfied conditions and setup actions. Use multiple checks for multiple explicit values in a line. They execute after all PRECONDITION actions and BEFORE the first TEST action; setup actions alone are not proof. Each check has source_text, read_kind, selector, expected_value.
Read kinds: UI_TEXT (contains grounded state/value, not a generic label), UI_VALUE (exact string), UI_CHECKED/UI_ENABLED (boolean), INTERNAL_VALUE (exact observed, TC-grounded scalar path), BASELINE_CONTEXT (selector target_device_visible/error_free/unlocked/online, expected_value=true, only for the matching observed baseline fact).
If a stated precondition cannot be observed with these readers, return AUTOMATION_SUPPORT_EXTENSION_REQUIRED with that precise reason. Never delete, invent, or silently weaken preconditions. Product assertions cannot run in PRECONDITION phase.
For state expectations, UI_TEXT_CONTAINS must include the expected state, never only a static control label. CONTROLS_DISABLED requires an explicitly disabled Expected Result. Generic fixed RESTORE checks compare against the prepared TC state immediately before TEST, while RESTORE_OBSERVED_HVAC restores the original pre-setup HVAC state.
Implement every approved TEST and RESTORE operation in order. Trailing read-only verification steps are implemented by their corresponding assertions, not invented clicks.
Keep original restore-operation lines unchanged. A trailing restore confirmation may name an existing Expected Result's exact observation_target and compare it with the pre-test state, or with an initial value already proved for that same target. The compiler performs these existing baseline comparisons; do not invent RESTORE clicks or new product Expected Results for confirmation-only lines. A new observation target or unsupported restore comparison requires support extension, not silent omission.
For each confirmation-only restore line, add one restore_confirmations entry: copy the complete original line as source_text and list every existing ER result_id whose observation_target is confirmed by that line. Do not change the TC wording. These references execute the compiler's existing same-target restoration comparisons, not the product test's expected value. No new selector, expected value, notification, or Action is permitted for these entries. Keep each restore operation as an Action; a confirmation is not a substitute for a restore operation.
For each referenced ER, comparisons must identify its exact source_excerpt (a contiguous clause of that original line containing only that observation_target) and basis. OBSERVED_BASELINE compares that same reader with its runtime pre-test snapshot and requires that clause to say pre-test/original state. PROVED_INITIAL compares with the initial value already proved by a matching precondition reader (or the supported initial-temperature contract); quote that value in the clause. Do not transfer an internal code to a UI label or borrow another clause's baseline wording. Cover the whole confirmation with these clauses, leaving only punctuation/conjunctions. If the TC confuses UI labels with internal codes, report that precise drafting problem; do not invent a label, edit the TC, or add a precondition.
Use only selectors with match_count=1. A text assertion must check a meaningful product value or message, never only generic words such as 표시/state/text.
Preserve negative boolean states: 비활성/disabled/unchecked are false, not true. Explicit true/false values take precedence over field names such as enabled.
You are an Automation Engineer translating an approved product test case into a browser automation plan.

Rules:
1. Never change or invent the TC purpose, preconditions, steps, expected results, values, or Requirement IDs.
2. Use only selectors and window.__vccs interfaces present in the supplied UI Observation.
3. First decide whether the observed UI can implement every approved step and Expected Result with the allowed actions and assertions.
   If not, return planning_status=AUTOMATION_SUPPORT_EXTENSION_REQUIRED, no actions or assertions,
   and concrete extension_reasons based only on the missing interaction or observation technique.
   Do not reject a TC merely because its feature name, control point, mode, value, or selector was not seen in an earlier TC.
   Prefer the generic observed CLICK/FILL/SELECT_OPTION/CHECK/UNCHECK actions and generic UI/internal assertions when the
   supplied observation provides a stable, semantically linked interface. The fixed temperature-controller strategies are
   optimized mappings for that existing UI, not a closed list of product features.
4. For a READY plan, map PRIMARY_TEST_DEVICE and CENTRAL_COMMAND_ALLOWED_ROLE to target_device_id=1.
   If a SELECT_DEVICE action is actually needed, set its value to the same integer 1. A generic single-target page
   whose observed accessible context already identifies PRIMARY_TEST_DEVICE does not need a legacy SELECT_DEVICE action.
5. PRECONDITION actions establish only states explicitly required by the approved TC. A precondition already satisfied
   by ui_observation.verified_execution_context or initial UI/state values needs no action. The isolated runner clears
   localStorage and reloads the product before observation and trial. When the verified context confirms that the target
   device is ready, no extra setup action is needed for matching TC conditions, but their precondition_checks must still
   verify the actual values before TEST. Use the matching BASELINE_CONTEXT readers without inventing extra conditions.
   An observed mode or temperature can similarly ground an explicit initial value check; it does not replace runtime proof.
   Values that differ from the observed clean state still need approved setup actions.
6. TEST actions implement only the approved TC steps. Never assume a blocked request changes the value.
7. Create RESTORE actions only when restore_required=true and use only the approved restore values.
   When test_data.restore_observed_hvac_state=true, create exactly one RESTORE_OBSERVED_HVAC action using
   selector=.btn-apply-cmd, value=null, and the exact approved restore_steps line that says to restore the observed
   pre-trial mode and temperature. The guarded compiler captures those two values at runtime and restores them; never
   invent fixed values. Do not use this action for a generic product feature or when the flag is false.
8. Map every Expected Result exactly once without changing result_id or observation_layer.
   For a grouped TC, preserve the approved condition order. Set each assertion's after_action_id to the last action that
   implements its Expected Result's verify_after_step, so the compiler checks that condition before executing the next one.
   Different Expected Results for the same condition may share one after_action_id. Never postpone an earlier condition's
   assertion until the final condition. New detailed TC results have observation_target: use that human-readable location
   with the expected statement to choose observed evidence, and always set after_action_id to implement verify_after_step,
   including SINGLE_FLOW. Only historical single-flow results without observation_target may omit after_action_id.
8-1. INDEPENDENT_VARIANTS must execute every approved intermediate_reset_step before the next variant. A
   SEQUENTIAL_TRANSITION must keep the approved transition order because that order is part of the test meaning. Do not
   silently split, omit, merge, reorder, or reuse a previous condition's observed result.
9. Generic UI actions are CLICK, FILL, SELECT_OPTION, CHECK, and UNCHECK. Use only an observed selector whose tag,
   role, input_type, enabled state, and action_hint support the selected action.
   New product features must be implemented with these observation-grounded primitives. Do not add or infer a new
   product name, mode, value, selector, or behavior in this shared contract merely to support one feature.
10. Generic UI assertions are UI_TEXT_CONTAINS, UI_VALUE_EQUALS, UI_CHECKED_EQUALS, and UI_ENABLED_EQUALS. An Expected Result that explicitly says disabled or 비활성 grounds UI_ENABLED_EQUALS expected_value=false; enabled or 활성 grounds expected_value=true. This boolean conversion preserves the stated UI condition and does not invent a new product value.
    INTERNAL_VALUE_EQUALS may use only an exact path present in ui_observation.harness_values.
    INTERNAL_DEVICE_FIELDS_EQUALS may compare one or more fields of the approved target device only. Its selector is
    window.__vccs.devices and every expected_fields[].field_name must occur in ui_observation.device_state_fields and be named
    verbatim in the matching INTERNAL_STATE Expected Result. Do not add fields or values not present in that Expected Result.
    When a NOTIFICATION Expected Result specifies that a result is announced but does not fix the whole message,
    UI_TEXT_CONTAINS may verify a short meaningful phrase that occurs verbatim in that Expected Result. Do not invent a full
    message and do not use the entire natural-language Expected Result sentence as expected_text.
11. Generic action values must occur in the approved precondition, step, or restore text. Generic assertion values
    must occur in the matching Expected Result. Do not translate a product meaning into an ungrounded boolean or value.
12. Keep source_text as the exact approved precondition, step, or restore line implemented by the action.
13. The legacy temperature actions and assertions are compatibility adapters for the already observed V1 controller,
    not an extension pattern for new product features. For that existing controller, use UI_TEMPERATURE and
    INTERNAL_SET_TEMP for their corresponding observations.
    When one INTERNAL_STATE Expected Result explicitly contains multiple registered target-device fields (for example mode
    and setTemp), use INTERNAL_DEVICE_FIELDS_EQUALS instead of splitting or weakening that Expected Result.
   TOAST_BLOCKING for a blocking Toast, and CONTROLS_DISABLED or DISABLED_TEMPERATURE_TEXT for disabled states.
14. Return only the structured plan, which is the executable code intent consumed by the guarded compiler. Do not write free-form Python.
15. Do not propose external URLs, shell commands, file changes, arbitrary waits, skip, or ignored exceptions.
16. Only for an observed existing temperature-controller flow, use these compatibility action targets exactly: SELECT_DEVICE=#device-card-1 .card-body-split;
    SET_MODE=the selector matching the requested mode; SET_TEMPERATURE=#det-temp-display. The observed central-panel pending-command
    action uses APPLY_COMMANDS=.btn-apply-cmd for any approved CENTRAL step that applies or restores a command, including a generic
    control selected through an observed CLICK action. Never require these selectors when they are absent from the supplied UI Observation.
    The compiler operates the central control-panel temperature buttons itself. The current V2 execution contract does not
    support LOCAL or wall-remote paths; those cases are excluded before the model call and must never be reinterpreted as CENTRAL.
17. For legacy compatibility assertion strategies use these targets exactly: UI_TEMPERATURE=#det-temp-display;
    INTERNAL_SET_TEMP=window.__vccs.devices; INTERNAL_DEVICE_FIELDS_EQUALS=window.__vccs.devices; TOAST_VISIBLE=#global-toast;
    TOAST_BLOCKING=#global-toast;
    CONTROLS_DISABLED=#det-temp-down-btn; DISABLED_TEMPERATURE_TEXT=#det-temp-display. CONTROLS_DISABLED is for one Expected Result that treats both legacy temperature controls as one observation. When CP2 has separate atomic Expected Results for the observed temperature-down and temperature-up buttons, use UI_ENABLED_EQUALS with expected_value=false and the corresponding observed selector for each result.
    Do not append indexes, properties, or expressions to a window.__vccs interface.
""".strip()


class Agent3Error(RuntimeError):
    """Raised when Agent 3 cannot create or validate an automation candidate."""


class AutomationInterfaceUnavailable(Agent3Error):
    """Observed target lacks required interfaces; exclude this TC, not the Run."""


@dataclass(frozen=True)
class Agent3Response:
    plan: Agent3AutomationPlan
    response_id: str | None
    model: str
    usage: dict[str, int | None]


def build_agent3_model_input(
    test_case: ProductTestCaseCandidate,
    observation: UiObservation,
    requirements: dict[str, SrsRequirement],
) -> dict[str, Any]:
    related = {
        key: value.model_dump(mode="json")
        for key, value in requirements.items()
        if key in test_case.requirement_ids
    }
    observation_payload = observation.model_dump(mode="json")
    tc_grounding_text = " ".join(
        [
            test_case.title,
            *test_case.preconditions,
            *test_case.steps,
            *test_case.restore_steps,
            *(result.statement for result in test_case.expected_results),
            json.dumps(test_case.test_data.model_dump(mode="json"), ensure_ascii=False),
        ]
    )
    normalized_grounding_text = _normalize(tc_grounding_text)
    dedicated_set_temp_is_grounded = (
        test_case.test_data.requested_temperature_c is not None
        and any(
            result.observation_layer == ObservationLayer.INTERNAL_STATE
            and "설정온도" in _normalize(result.statement)
            for result in test_case.expected_results
        )
    )

    def internal_name_is_grounded(value: str) -> bool:
        identifiers = re.findall(r"[A-Za-z_$][A-Za-z0-9_$]*", value)
        return any(
            len(identifier) >= 3
            and identifier.casefold() not in {"window", "vccs", "devices"}
            and (
                _normalize(identifier) in normalized_grounding_text
                or (
                    identifier.casefold() == "settemp"
                    and dedicated_set_temp_is_grounded
                )
            )
            for identifier in identifiers
        )

    observation_payload["harness_values"] = {
        path: value
        for path, value in observation.harness_values.items()
        if internal_name_is_grounded(path)
    }
    observation_payload["device_state_fields"] = [
        field_name
        for field_name in observation.device_state_fields
        if internal_name_is_grounded(field_name)
    ]
    return {
        "destination": "OpenAI Responses API",
        "store": False,
        "system_instructions": AGENT3_SYSTEM_INSTRUCTIONS,
        "test_case": test_case.model_dump(mode="json"),
        "related_srs_requirements": related,
        "ui_observation": observation_payload,
        "excluded": [
            "API keys and authentication values",
            "local absolute paths and HTML source",
            "screenshots and Playwright traces",
        ],
    }


class OpenAIAgent3:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent3Error(
                    "OPENAI_API_KEY is missing. Never place secrets in code or Run artifacts."
                )
            client = OpenAI()
        self.client = client

    def plan(
        self,
        test_case: ProductTestCaseCandidate,
        observation: UiObservation,
        requirements: dict[str, SrsRequirement],
        *,
        previous_plan: Agent3AutomationPlan | None = None,
        checkpoint_feedback: list[str] | None = None,
    ) -> Agent3Response:
        payload = build_agent3_model_input(test_case, observation, requirements)
        user_input = (
            "[CP2-approved product test case]\n"
            f"{json.dumps(payload['test_case'], ensure_ascii=False, indent=2)}\n\n"
            "[Related SRS Requirements]\n"
            f"{json.dumps(payload['related_srs_requirements'], ensure_ascii=False, indent=2)}\n\n"
            "[Observed real UI inventory]\n"
            f"{json.dumps(payload['ui_observation'], ensure_ascii=False, indent=2)}"
        )
        if previous_plan is not None:
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[Previous automation plan]\n"
                f"{previous_plan.model_dump_json(indent=2)}\n\n"
                "[Checkpoint 3 revision request]\n"
                f"{feedback}\n"
                "Keep all TC semantics and values unchanged; fix only the reported technical plan issues. "
                "For precondition feedback, repair the identified check and preserve valid checks. "
                "Remove an extra check only when its condition is absent from the TC; never delete a stated condition. "
                "A rejected extra check is not evidence that a different UI interface is missing."
            )
        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
                prompt_cache_key="qa-v2-agent3-3-26",
                input=[
                    {"role": "system", "content": AGENT3_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent3AutomationPlan,
            )
        except Exception as exc:
            raise Agent3Error(f"Agent 3 model call failed: {exc}") from exc
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent3Error("The model did not return a structured Agent 3 automation plan.")
        return Agent3Response(
            plan=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
        )

_UI_SELECTOR_INVENTORY = {
    "#device-card-1 .card-body-split": "Select PRIMARY_TEST_DEVICE",
    "#det-mode-cool": "Request COOL mode",
    "#det-mode-heat": "Request HEAT mode",
    "#det-mode-fan": "Request FAN mode",
    "#det-mode-dry": "Request DRY mode",
    "#det-mode-auto": "Request AUTO mode",
    "#det-temp-display": "Read pending temperature",
    "#det-temp-down-btn": "온도 내림 / Request one degree lower",
    "#det-temp-up-btn": "온도 올림 / Request one degree higher",
    "#det-temp-adjust-card": "Read temperature control state",
    ".btn-apply-cmd": "Apply pending commands",
    "#global-toast": "Read blocking toast",
}
_DEFAULT_UI_SELECTORS = {
    "#device-card-1 .card-body-split",
    "#det-mode-cool",
    "#det-mode-heat",
    "#det-mode-fan",
    "#det-mode-dry",
    "#det-mode-auto",
    "#det-temp-display",
    "#det-temp-down-btn",
    "#det-temp-up-btn",
    "#det-temp-adjust-card",
    ".btn-apply-cmd",
    "#global-toast",
}
_REQUIRED_HARNESS_KEYS = {
    "devices",
    "pendingState",
    "selectedUnitId",
    "selectUnit",
    "applyPanelCommands",
}


def inspect_target_ui(
    target_html: Path,
    *,
    required_selectors: set[str] | None = None,
    required_harness_keys: set[str] | None = None,
    discover_generic: bool = False,
) -> UiObservation:
    """Inspect known TC interfaces or discover generic, stable UI interfaces."""
    target = target_html.resolve()
    if not target.is_file() or target.suffix.casefold() != ".html":
        raise Agent3Error("--target-html must point to an existing local HTML file.")
    selectors_to_observe = (
        set(_DEFAULT_UI_SELECTORS)
        if required_selectors is None
        else set(required_selectors)
    )
    harness_to_observe = (
        set(_REQUIRED_HARNESS_KEYS)
        if required_harness_keys is None
        else set(required_harness_keys)
    )
    unknown_selectors = selectors_to_observe - set(_UI_SELECTOR_INVENTORY)
    unknown_harness = harness_to_observe - _REQUIRED_HARNESS_KEYS
    if unknown_selectors or unknown_harness:
        details = []
        if unknown_selectors:
            details.append("selector=" + ", ".join(sorted(unknown_selectors)))
        if unknown_harness:
            details.append("window.__vccs=" + ", ".join(sorted(unknown_harness)))
        raise Agent3Error("Unknown Agent 3 inspection capability: " + " / ".join(details))
    try:
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError, sync_playwright
    except ImportError as exc:
        raise Agent3Error(
            "Agent 3 UI inspection requires Playwright. Run pip install -e .[agent3]."
        ) from exc

    elements: list[ObservedUiElement] = []
    verified_context = VerifiedExecutionContext()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(target.as_uri(), wait_until="domcontentloaded")
        page.evaluate("() => localStorage.clear()")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("body", timeout=5000)
        if selectors_to_observe:
            try:
                page.wait_for_function(
                    "selectors => selectors.every(selector => document.querySelector(selector))",
                    arg=sorted(selectors_to_observe),
                    timeout=5000,
                )
            except PlaywrightTimeoutError:
                # Preserve the existing precise missing-interface error below.
                pass
        if harness_to_observe:
            try:
                page.wait_for_function(
                    "keys => window.__vccs && keys.every(key => key in window.__vccs)",
                    arg=sorted(harness_to_observe),
                    timeout=5000,
                )
            except PlaywrightTimeoutError:
                # Preserve the existing precise missing-interface error below.
                pass

        # Capture the verified execution context only after the interfaces needed
        # by this TC had their readiness window. Recording it immediately after
        # <body> made a valid device intermittently appear absent on delayed pages.
        primary_card = page.locator("#device-card-1 .card-body-split").first
        primary_visible = primary_card.count() > 0 and primary_card.is_visible()
        primary_state = page.evaluate(
            """() => {
                const devices = window.__vccs && Array.isArray(window.__vccs.devices)
                    ? window.__vccs.devices : [];
                const device = devices.find(item => item && item.id === 1);
                if (!device || typeof device !== 'object') return null;
                return {
                    id: device.id,
                    index: devices.indexOf(device),
                    mode: typeof device.mode === 'string' ? device.mode : null,
                    setTemp: typeof device.setTemp === 'number' ? device.setTemp : null,
                    status: typeof device.status === 'string' ? device.status : null,
                    locked: typeof device.locked === 'boolean' ? device.locked : null,
                    errorCode: device.errorCode ?? null,
                    hasErrorCode: Object.prototype.hasOwnProperty.call(device, 'errorCode'),
                };
            }"""
        )
        state_available = isinstance(primary_state, dict)
        error_free = (
            primary_state.get("status") in {"STOP", "OPERATION", "OFFLINE"}
            and primary_state.get("errorCode") is None
            if state_available and primary_state.get("hasErrorCode") and primary_state.get("status") is not None
            else None
        )
        unlocked = (
            primary_state.get("locked") is False if state_available else None
        )
        evidence = ["localStorage 초기화 후 제품 화면을 새로 로드했습니다."]
        if primary_visible:
            evidence.append("PRIMARY_TEST_DEVICE 장비 카드가 표시됩니다.")
        if state_available:
            evidence.append("PRIMARY_TEST_DEVICE 내부 장비 상태를 읽었습니다.")
        if error_free:
            evidence.append("PRIMARY_TEST_DEVICE는 오류 상태가 아닙니다.")
        if unlocked:
            evidence.append("PRIMARY_TEST_DEVICE는 잠금 해제 상태입니다.")
        verified_context = VerifiedExecutionContext(
            clean_page_loaded=True,
            target_device_id=1,
            target_device_visible=primary_visible,
            device_state_available=state_available,
            error_free=error_free,
            online=primary_state.get("status") in {"OPERATION", "STOP", "ERROR"} if state_available else None,
            unlocked=unlocked,
            evidence=evidence,
        )
        for selector, hint in _UI_SELECTOR_INVENTORY.items():
            if selector not in selectors_to_observe:
                continue
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            elements.append(
                ObservedUiElement(
                    selector=selector,
                    match_count=page.locator(selector).count(),
                    tag=locator.evaluate("el => el.tagName.toLowerCase()"),
                    text=(locator.inner_text() or "").strip(),
                    visible=locator.is_visible(),
                    enabled=locator.is_enabled(),
                    action_hint=hint,
                )
            )
        if discover_generic:
            generic_items = page.evaluate(
                r"""() => {
                    const escapeAttr = value => String(value)
                        .replace(/\\/g, '\\\\')
                        .replace(/"/g, '\\"');
                    const stableSelector = element => {
                        if (element.id) return `#${CSS.escape(element.id)}`;
                        const testId = element.getAttribute('data-testid');
                        if (testId) return `[data-testid="${escapeAttr(testId)}"]`;
                        const aria = element.getAttribute('aria-label');
                        if (aria) return `${element.tagName.toLowerCase()}[aria-label="${escapeAttr(aria)}"]`;
                        const name = element.getAttribute('name');
                        if (name) return `${element.tagName.toLowerCase()}[name="${escapeAttr(name)}"]`;
                        return null;
                    };
                    const candidates = document.querySelectorAll(
                        'button,input,select,textarea,[role="button"],[role="switch"],'
                        + '[role="checkbox"],[aria-live],[data-testid],[id]'
                    );
                    const result = [];
                    const seen = new Set();
                    for (const element of candidates) {
                        const selector = stableSelector(element);
                        if (!selector || seen.has(selector)) continue;
                        const style = getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        const visible = style.display !== 'none' && style.visibility !== 'hidden'
                            && rect.width > 0 && rect.height > 0;
                        if (!visible) continue;
                        seen.add(selector);
                        const tag = element.tagName.toLowerCase();
                        const role = element.getAttribute('role');
                        const inputType = tag === 'input' ? (element.getAttribute('type') || 'text') : null;
                        let hint = 'READ_STATE';
                        if (tag === 'select') hint = 'SELECT_OPTION';
                        else if (tag === 'textarea' || (tag === 'input' && !['checkbox','radio','button','submit'].includes(inputType))) hint = 'FILL';
                        else if (inputType === 'checkbox' || role === 'switch' || role === 'checkbox') hint = 'CHECK_OR_UNCHECK';
                        else if (tag === 'button' || role === 'button') hint = 'CLICK';
                        result.push({
                            selector,
                            match_count: document.querySelectorAll(selector).length,
                            tag,
                            text: (element.innerText || element.textContent || '').trim().slice(0, 300),
                            visible,
                            enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
                            action_hint: hint,
                            role,
                            input_type: inputType,
                            accessible_name: (element.getAttribute('aria-label')
                                || (element.labels ? Array.from(element.labels).map(label => label.innerText).join(' ') : '')
                                || element.innerText || element.getAttribute('name') || '').trim().slice(0, 200) || null,
                            value: 'value' in element ? String(element.value) : null,
                            checked: 'checked' in element ? Boolean(element.checked) : null,
                        });
                        if (result.length >= 120) break;
                    }
                    return result;
                }"""
            )
            known = {item.selector for item in elements}
            for item in generic_items:
                if item["selector"] not in known:
                    elements.append(ObservedUiElement.model_validate(item))
                    known.add(item["selector"])
        available_harness_keys = set(
            page.evaluate("() => window.__vccs ? Object.keys(window.__vccs) : []")
        )
        harness_keys = sorted(harness_to_observe & available_harness_keys)
        harness_values: dict[str, str | float | int | bool | None] = {}
        if state_available:
            prefix = f"window.__vccs.devices[{primary_state['index']}]"
            harness_values.update({f"{prefix}.{name}": primary_state[name] for name in ("id", "mode", "setTemp")})
        device_state_fields: list[str] = []
        if "devices" in available_harness_keys:
            device_state_fields = page.evaluate(
                """() => {
                    const devices = window.__vccs && Array.isArray(window.__vccs.devices)
                        ? window.__vccs.devices : [];
                    const fields = new Set();
                    for (const device of devices.filter(device => device && device.id === 1)) {
                        if (!device || typeof device !== 'object') continue;
                        for (const [key, value] of Object.entries(device)) {
                            if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)
                                && (value === null || ['string', 'number', 'boolean'].includes(typeof value))) {
                                fields.add(key);
                            }
                        }
                    }
                    return Array.from(fields).sort();
                }"""
            )
        if discover_generic:
            harness_values = page.evaluate(
                """() => {
                    const output = {};
                    const seen = new WeakSet();
                    const walk = (value, path, depth) => {
                        if (value === null || ['string','number','boolean'].includes(typeof value)) {
                            output[path] = value;
                            return;
                        }
                        if (typeof value !== 'object' || depth >= 4 || seen.has(value)) return;
                        seen.add(value);
                        if (Array.isArray(value)) {
                            value.slice(0, 20).forEach((item, index) => walk(item, `${path}[${index}]`, depth + 1));
                        } else {
                            Object.keys(value).slice(0, 80).forEach(key => {
                                if (/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(key)) {
                                    walk(value[key], `${path}.${key}`, depth + 1);
                                }
                            });
                        }
                    };
                    if (window.__vccs) walk(window.__vccs, 'window.__vccs', 0);
                    return output;
                }"""
            )
        title = page.title()
        context.close()
        browser.close()

    observed_selectors = {item.selector for item in elements}
    missing_selectors = selectors_to_observe - observed_selectors
    missing_harness = harness_to_observe - available_harness_keys
    if missing_selectors or missing_harness:
        details = []
        if missing_selectors:
            details.append("selector=" + ", ".join(sorted(missing_selectors)))
        if missing_harness:
            details.append("window.__vccs=" + ", ".join(sorted(missing_harness)))
        raise AutomationInterfaceUnavailable("Required automation interfaces are missing from the observed UI: " + " / ".join(details))
    return UiObservation(
        target_file=target.name,
        target_sha256=_sha256_file(target),
        page_title=title,
        elements=elements,
        harness_keys=harness_keys,
        harness_values=harness_values,
        device_state_fields=device_state_fields,
        verified_execution_context=verified_context,
        generic_discovery=discover_generic,
        observed_at=datetime.now(timezone.utc).isoformat(),
    )


_MODE_SELECTOR = {
    "AUTO": "#det-mode-auto",
    "COOL": "#det-mode-cool",
    "HEAT": "#det-mode-heat",
    "FAN": "#det-mode-fan",
    "DRY": "#det-mode-dry",
}


_SUPPORTED_AGENT3_TARGET_ROLES = {
    "PRIMARY_TEST_DEVICE",
    "CENTRAL_COMMAND_ALLOWED_ROLE",
}
_TEMPERATURE_TERMS = ("temperature", "degree", "settemp", "온도", "°")
_MODE_TERMS = ("mode", "모드")
_DISABLED_TERMS = ("disabled", "비활성", "조작할 수 없", "사용할 수 없")
_CONTROL_TERMS = ("control", "button", "버튼", "조작")
_TEMPERATURE_DOWN_TERMS = ("온도 내림", "내림 버튼", "decrease", "lower", "temp down")
_TEMPERATURE_UP_TERMS = ("온도 올림", "올림 버튼", "increase", "higher", "temp up")
_DISPLAY_TERMS = ("display", "text", "표시")
_TOAST_TERMS = ("toast", "토스트")
_VISIBLE_TERMS = ("visible", "shown", "appears", "displayed", "표시")
_BLOCKING_EXPECTATION_TERMS = ("block", "blocked", "blocking", "차단")
_BLOCKING_TOAST_ACTUAL_TERMS = (
    "block",
    "blocked",
    "blocking",
    "reject",
    "denied",
    "invalid",
    "out of range",
    "failed",
    "차단",
    "범위",
    "초과",
    "거부",
    "실패",
    "허용되지",
    "할 수 없",
)


def evaluate_agent3_eligibility(
    test_case: ProductTestCaseCandidate,
) -> Agent3EligibilityResult:
    """Choose targeted inspection or generic discovery before a model call."""
    required_capabilities: set[str] = set()
    missing_capabilities: set[str] = set()
    required_selectors: set[str] = set()
    required_harness_keys: set[str] = set()
    generic_discovery_required = False

    if not test_case.automation_candidate:
        missing_capabilities.add("CP2_AUTOMATION_CANDIDATE")
    if test_case.control_path != ControlPath.CENTRAL:
        missing_capabilities.add("CENTRAL_CONTROL_PANEL_ONLY")
        return Agent3EligibilityResult(
            tc_id=test_case.tc_id,
            status=Agent3EligibilityStatus.NOT_AUTOMATABLE,
            candidate_status=AutomationCandidateStatus.NOT_AUTOMATABLE,
            required_capabilities=[],
            missing_capabilities=sorted(missing_capabilities),
            required_selectors=[],
            required_harness_keys=[],
            model_call_allowed=False,
            generic_discovery_required=False,
        )

    modes = {
        value
        for value in (
            test_case.test_data.initial_mode,
            *_tc_requested_modes(test_case),
        )
        if value
    }
    temperature_values = set(_tc_temperature_values(test_case))
    non_hvac_modes = modes - set(_MODE_SELECTOR)
    legacy_controller_flow = bool(modes or temperature_values) and not non_hvac_modes
    primary_device_target = test_case.target_role in _SUPPORTED_AGENT3_TARGET_ROLES
    approved_procedure = " ".join(
        [*test_case.preconditions, *test_case.steps, *test_case.restore_steps]
    )
    central_apply_required = primary_device_target and _contains_any(
        approved_procedure, ("적용", "apply", "복원", "restore")
    )
    if primary_device_target:
        required_capabilities.add("SELECT_PRIMARY_DEVICE")
        required_selectors.add("#device-card-1 .card-body-split")
        required_harness_keys.add("selectedUnitId")
    if legacy_controller_flow:
        required_capabilities.add("APPLY_CENTRAL_COMMAND")
        required_selectors.add(".btn-apply-cmd")
    else:
        generic_discovery_required = True
        required_capabilities.add("DISCOVER_GENERIC_UI")
    if central_apply_required:
        required_capabilities.add("APPLY_CENTRAL_COMMAND")
        required_selectors.add(".btn-apply-cmd")

    if test_case.target_role not in _SUPPORTED_AGENT3_TARGET_ROLES:
        generic_discovery_required = True
        required_capabilities.add("DISCOVER_TARGET_CONTROL")

    if legacy_controller_flow and modes:
        required_capabilities.add("SET_MODE")
    for mode in modes if legacy_controller_flow else set():
        selector = _MODE_SELECTOR.get(mode)
        if selector is not None:
            required_selectors.add(selector)

    if temperature_values:
        required_capabilities.add("SET_TEMPERATURE")
        required_selectors.update(
            {"#det-temp-display", "#det-temp-down-btn", "#det-temp-up-btn"}
        )
    if test_case.test_data.restore_observed_hvac_state:
        required_capabilities.add("RESTORE_OBSERVED_HVAC_STATE")
        required_harness_keys.add("devices")
        required_selectors.update(_MODE_SELECTOR.values())
        required_selectors.update(
            {
                "#det-temp-display",
                "#det-temp-down-btn",
                "#det-temp-up-btn",
                ".btn-apply-cmd",
            }
        )

    disabled_mode = legacy_controller_flow and bool(modes) and modes <= {"FAN", "DRY"}
    for result in test_case.expected_results:
        statement = result.statement
        if result.observation_layer == ObservationLayer.UI:
            if temperature_values and _contains_any(statement, _TEMPERATURE_TERMS):
                required_capabilities.add("ASSERT_UI_TEMPERATURE")
                required_selectors.add("#det-temp-display")
            elif (
                _contains_any(statement, _DISABLED_TERMS)
                and _contains_any(statement, _CONTROL_TERMS)
                and (
                    _contains_any(statement, _TEMPERATURE_DOWN_TERMS)
                    or _contains_any(statement, _TEMPERATURE_UP_TERMS)
                )
            ):
                generic_discovery_required = True
                required_capabilities.add("ASSERT_GENERIC_UI_STATE")
                if _contains_any(statement, _TEMPERATURE_DOWN_TERMS):
                    required_selectors.add("#det-temp-down-btn")
                if _contains_any(statement, _TEMPERATURE_UP_TERMS):
                    required_selectors.add("#det-temp-up-btn")
            elif disabled_mode and _contains_any(statement, _DISABLED_TERMS):
                if _contains_any(statement, _CONTROL_TERMS):
                    required_capabilities.add("ASSERT_TEMPERATURE_CONTROLS_DISABLED")
                    required_selectors.update({"#det-temp-down-btn", "#det-temp-up-btn"})
                elif _contains_any(statement, _DISPLAY_TERMS):
                    required_capabilities.add("ASSERT_DISABLED_TEMPERATURE_TEXT")
                    required_selectors.add("#det-temp-display")
                else:
                    generic_discovery_required = True
                    required_capabilities.add("ASSERT_GENERIC_UI_STATE")
            else:
                generic_discovery_required = True
                required_capabilities.add("ASSERT_GENERIC_UI_STATE")
        elif result.observation_layer == ObservationLayer.INTERNAL_STATE:
            has_temperature = temperature_values and _contains_any(
                statement, _TEMPERATURE_TERMS
            )
            has_mode = bool(modes) and _contains_any(statement, _MODE_TERMS)
            if legacy_controller_flow and (has_temperature or has_mode):
                if has_temperature:
                    required_capabilities.add("ASSERT_INTERNAL_SET_TEMP")
                if has_mode:
                    required_capabilities.add("ASSERT_INTERNAL_DEVICE_FIELDS")
                required_harness_keys.add("devices")
            elif temperature_values and _contains_any(statement, _TEMPERATURE_TERMS):
                required_capabilities.add("ASSERT_INTERNAL_SET_TEMP")
                required_harness_keys.add("devices")
            else:
                generic_discovery_required = True
                required_capabilities.add("DISCOVER_INTERNAL_STATE")
                if primary_device_target:
                    required_harness_keys.add("devices")
        elif result.observation_layer == ObservationLayer.NOTIFICATION:
            if _contains_any(statement, _TOAST_TERMS) and _contains_any(
                statement, _VISIBLE_TERMS
            ) and _contains_any(statement, _BLOCKING_EXPECTATION_TERMS):
                required_capabilities.add("ASSERT_TOAST_BLOCKING")
                required_selectors.add("#global-toast")
            else:
                generic_discovery_required = True
                required_capabilities.add("ASSERT_GENERIC_NOTIFICATION")

    supported = not missing_capabilities
    return Agent3EligibilityResult(
        tc_id=test_case.tc_id,
        status=(
            Agent3EligibilityStatus.NOT_AUTOMATABLE
            if not supported
            else Agent3EligibilityStatus.DISCOVERY_REQUIRED
            if generic_discovery_required
            else Agent3EligibilityStatus.ELIGIBLE
        ),
        candidate_status=(
            None if supported else AutomationCandidateStatus.NOT_AUTOMATABLE
        ),
        required_capabilities=sorted(required_capabilities),
        missing_capabilities=sorted(missing_capabilities),
        required_selectors=sorted(required_selectors),
        required_harness_keys=sorted(required_harness_keys),
        model_call_allowed=supported,
        generic_discovery_required=(generic_discovery_required if supported else False),
    )


_ASSERTION_SELECTOR = {
    AssertionStrategy.UI_TEMPERATURE: "#det-temp-display",
    AssertionStrategy.INTERNAL_SET_TEMP: "window.__vccs.devices",
    AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS: "window.__vccs.devices",
    AssertionStrategy.TOAST_VISIBLE: "#global-toast",
    AssertionStrategy.TOAST_BLOCKING: "#global-toast",
    AssertionStrategy.CONTROLS_DISABLED: "#det-temp-down-btn",
    AssertionStrategy.DISABLED_TEMPERATURE_TEXT: "#det-temp-display",
}

_GENERIC_ACTION_TYPES = {
    AutomationActionType.CLICK,
    AutomationActionType.FILL,
    AutomationActionType.SELECT_OPTION,
    AutomationActionType.CHECK,
    AutomationActionType.UNCHECK,
}
_GENERIC_ASSERTION_STRATEGIES = {
    AssertionStrategy.UI_TEXT_CONTAINS,
    AssertionStrategy.UI_VALUE_EQUALS,
    AssertionStrategy.UI_CHECKED_EQUALS,
    AssertionStrategy.UI_ENABLED_EQUALS,
    AssertionStrategy.INTERNAL_VALUE_EQUALS,
}
_HARNESS_VALUE_PATH = re.compile(
    r"^window\.__vccs(?:\.[A-Za-z_$][A-Za-z0-9_$]*|\[\d+\])+$"
)


def _expected_selector_for_assertion(assertion: AutomationAssertion) -> str | None:
    return _ASSERTION_SELECTOR.get(assertion.strategy)


def _scalar_value_is_grounded(
    value: str | float | int | bool | None, source_text: str
) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        for index in (0, 1, 3, 4):
            states = _state_polarities(source_text, *_STATE_WORD_PAIRS[index])
            if states:
                return states == {value}
        return False
    if isinstance(value, (int, float)):
        return float(value) in {
            float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", source_text)
        }
    escaped = re.escape(str(value).casefold())
    return bool(re.search(r"(?<![a-z0-9_])" + escaped + r"(?![a-z0-9_])", source_text.casefold()))


_BASELINE_PRECONDITION_READS = {
    "target_device_visible": (r"대상.*장비|장비.*표시|\bdevice\b", None),
    "error_free": (r"오류.*없|오류.*없는|정상|error.free|no.error", "['STOP', 'OPERATION', 'OFFLINE'].includes(d.status) && d.errorCode === null"),
    "unlocked": (r"잠금.*해제|잠금.*없|unlocked|no.lock", "d.locked === false"),
    "online": (r"온라인|\bonline\b", "['OPERATION', 'STOP', 'ERROR'].includes(d.status)"),
}


def _precondition_proof_errors(test_case, plan, observation) -> list[str]:
    """Check explicit proof mappings, not general natural-language equivalence."""
    errors = []
    approved = set(test_case.preconditions)
    observed = {item.selector: item for item in observation.elements}
    available_paths = build_agent3_model_input(test_case, observation, {})["ui_observation"]["harness_values"]
    grouped = {line: [] for line in test_case.preconditions}
    phases = {action.action_id: action.phase for action in plan.actions}
    if AutomationPhase.TEST not in phases.values():
        errors.append("precondition verification requires a distinct TEST phase")
    if any(assertion.after_action_id and phases.get(assertion.after_action_id) == AutomationPhase.PRECONDITION for assertion in plan.assertions):
        errors.append("product assertions cannot precede precondition verification")
    for check_index, check in enumerate(plan.precondition_checks, 1):
        if check.source_text not in approved:
            errors.append("proof source_text is not an exact approved precondition")
            continue
        grouped[check.source_text].append(check)
        if check.read_kind == PreconditionReadKind.BASELINE_CONTEXT:
            binding = _BASELINE_PRECONDITION_READS.get(check.selector)
            reason = None
            if binding is None or check.expected_value is not True:
                reason = "허용된 기본 문맥 항목과 expected_value=true를 사용해야 합니다."
            elif re.search(r"로그인|관리자|인증|login|admin|authenticat", check.source_text, re.I):
                reason = "로그인·권한 조건은 장비 기본 문맥으로 증명할 수 없습니다."
            elif not re.search(binding[0], check.source_text, re.I):
                matched = [key for key, (pattern, _) in _BASELINE_PRECONDITION_READS.items()
                           if re.search(pattern, check.source_text, re.I)]
                reason = (
                    f"이 확인 항목은 원문의 조건과 연결되지 않습니다. 원문에 연결되는 기본 문맥: {', '.join(matched) or '없음'}. "
                    "TC에 없는 추가 확인만 제거하고 명시된 조건·유효한 확인은 보존하세요. "
                    "명시된 조건을 다른 읽기 방식으로도 확인할 수 없을 때만 지원 부족으로 판단하세요."
                )
            elif (not isinstance(getattr(observation.verified_execution_context, check.selector, None), bool)
                  or (check.selector != "target_device_visible" and not observation.verified_execution_context.device_state_available)):
                reason = "이 기본 문맥의 실제 관찰 근거가 없습니다. 조건을 충족했다고 추정하지 마세요."
            if reason:
                errors.append(f"사전조건 확인 #{check_index} [BASELINE_CONTEXT/{check.selector}] 원문={check.source_text!r}: {reason}")
            continue
        if not _scalar_value_is_grounded(check.expected_value, check.source_text):
            errors.append("precondition expected value is not grounded in its source")
        if check.read_kind == PreconditionReadKind.INTERNAL_VALUE:
            if not _HARNESS_VALUE_PATH.fullmatch(check.selector) or check.selector not in available_paths:
                errors.append("precondition internal path was not observed or grounded in the TC")
            device_prefix = re.match(r"window\.__vccs\.devices\[\d+\]", check.selector)
            if device_prefix and observation.harness_values.get(device_prefix.group() + ".id") != plan.target_device_id:
                errors.append("precondition device index does not identify the observed target")
        else:
            element = observed.get(check.selector)
            if element is None or element.match_count != 1:
                errors.append("precondition selector must have exactly one observed match")
                continue
            meaning = " ".join([element.text, element.accessible_name or "", element.selector, element.action_hint])
            if not _has_textual_link(meaning, check.source_text):
                errors.append("precondition UI target has no textual link to its source")
            if check.read_kind in {PreconditionReadKind.UI_CHECKED, PreconditionReadKind.UI_ENABLED} and not isinstance(check.expected_value, bool):
                errors.append("precondition boolean observation requires a boolean value")
            if check.read_kind == PreconditionReadKind.UI_ENABLED and _state_polarities(check.source_text, *_STATE_WORD_PAIRS[1]) != {check.expected_value}:
                errors.append("enabled-state proof requires the same explicit enabled/disabled precondition")
            if check.read_kind == PreconditionReadKind.UI_CHECKED and element.tag != "input":
                errors.append("checked-state proof requires an observed input element")
            if check.read_kind in {PreconditionReadKind.UI_TEXT, PreconditionReadKind.UI_VALUE} and not isinstance(check.expected_value, str):
                errors.append("precondition text/value observation requires a string")
            if check.read_kind == PreconditionReadKind.UI_TEXT:
                for positive, negative in _STATE_WORD_PAIRS:
                    state = _state_polarities(check.source_text, positive, negative)
                    if len(state) == 1 and _state_polarities(str(check.expected_value), positive, negative) != state:
                        errors.append("precondition text omits the required state")
    for source, checks in grouped.items():
        if not checks:
            errors.append("missing runtime proof for precondition: " + source)
            continue
        required = _explicit_behavior_values(source) - {"PRIMARY_TEST_DEVICE", "CENTRAL_COMMAND_ALLOWED_ROLE"}
        proved = set().union(*(_explicit_behavior_values(json.dumps(check.expected_value, ensure_ascii=False)) for check in checks))
        if required - proved:
            errors.append("precondition proof omits explicit values: " + ",".join(sorted(required - proved)))
        if any(check.read_kind == PreconditionReadKind.BASELINE_CONTEXT for check in checks):
            covered_context = {check.selector for check in checks if check.read_kind == PreconditionReadKind.BASELINE_CONTEXT}
            required_context = {key for key, (pattern, _) in _BASELINE_PRECONDITION_READS.items() if re.search(pattern, source, re.I)}
            if required_context - covered_context:
                errors.append("baseline proof omits a stated context fact: " + ",".join(sorted(required_context - covered_context)))
    return errors


def _precondition_read_expression(check: PreconditionCheck, target_device_id: int) -> str:
    if check.read_kind == PreconditionReadKind.BASELINE_CONTEXT:
        if check.selector == "target_device_visible":
            return f"page.locator('#device-card-{target_device_id} .card-body-split').is_visible()"
        expression = _BASELINE_PRECONDITION_READS[check.selector][1]
        script = f"id => {{ const d = window.__vccs?.devices?.find(item => item.id === id); return !!d && ({expression}); }}"
        return f"page.evaluate({_py_literal(script)}, {target_device_id})"
    if check.read_kind == PreconditionReadKind.INTERNAL_VALUE:
        device_prefix = re.match(r"window\.__vccs\.devices\[\d+\]", check.selector)
        if device_prefix:
            return f"page.evaluate({_py_literal('() => ' + device_prefix.group() + '?.id === ' + str(target_device_id) + ' ? ' + check.selector + ' : null')})"
        return f"page.evaluate({_py_literal('() => ' + check.selector)})"
    method = {PreconditionReadKind.UI_TEXT: "inner_text", PreconditionReadKind.UI_VALUE: "input_value",
              PreconditionReadKind.UI_CHECKED: "is_checked", PreconditionReadKind.UI_ENABLED: "is_enabled"}[check.read_kind]
    return f"page.locator({_py_literal(check.selector)}).{method}()"


def _restore_comparison_coverage(test_case, plan) -> tuple[set[str], list[str]]:
    """Validate each target's comparison independently; no new values or readers."""
    lines = {line for line in test_case.restore_steps
             if re.search(r"확인|비교|검사|검증|\b(?:verify|compare|check|confirm)\b", line, re.I)
             and not re.search(r"선택하|적용하|입력하|변경하|설정하|복원하|누른|누르|켠다|끈다"
                               r"|\b(?:click|apply|fill|select|set|restore|reset|uncheck)\b", line, re.I)}
    links = {item.source_text: item for item in plan.restore_confirmations}
    errors = []
    if len(links) != len(plan.restore_confirmations) or set(links) != lines:
        errors.append("복원 확인 원문 연결 누락·중복·변조: TC의 확인 문장마다 하나의 연결이 필요합니다.")
    results = {result.result_id: result for result in test_case.expected_results}
    for line in lines:
        link = links.get(line)
        if link is None:
            continue
        target_ids = {r.result_id for r in results.values()
                      if r.observation_target and _contains(line, r.observation_target)}
        ids = [item.result_id for item in link.comparisons]
        if (not target_ids or set(link.result_ids) != target_ids or len(set(link.result_ids)) != len(link.result_ids)
                or set(ids) != target_ids or len(ids) != len(set(ids))):
            errors.append("복원 비교 연결 누락·중복: 언급한 모든 ER에 대상별 비교 방법이 필요합니다.")
            continue
        remainder = line
        for comparison in link.comparisons:
            result = results[comparison.result_id]
            excerpt = comparison.source_excerpt
            mentioned = {r.observation_target for r in results.values()
                         if r.observation_target and _contains(excerpt, r.observation_target)}
            if excerpt not in line or mentioned != {result.observation_target}:
                errors.append(f"{result.result_id}: 비교 근거는 해당 대상 하나를 포함하는 TC 원문의 연속 구절이어야 합니다.")
                continue
            remainder = remainder.replace(excerpt, " ", 1)
            # Keep operation positions and all runtime readers/values. This view only
            # scopes language validation to one target so evidence cannot leak across clauses.
            scoped_case = test_case.model_copy(deep=True)
            scoped_case.expected_results = [result]
            scoped_case.restore_steps = [excerpt if item == line else item
                                         for item in test_case.restore_steps if item == line or item not in lines]
            scoped_plan = plan.model_copy(deep=True)
            scoped_plan.restore_confirmations = [RestoreConfirmation(source_text=excerpt, result_ids=[result.result_id])]
            # A fake action using the whole confirmation must not disappear in the scoped view.
            if any(_normalize(action.source_text) == _normalize(line) for action in plan.actions):
                errors.append(f"{result.result_id}: 복원 확인을 조작으로 구현할 수 없습니다.")
            _, scoped_errors = _restore_confirmation_coverage(scoped_case, scoped_plan, require_plan_links=True,
                _comparison_basis=comparison.basis)
            errors.extend(f"{result.result_id}: {error}" for error in scoped_errors)
        remainder = re.sub(r"\b(?:and|then)\b|그리고|또한|및", " ", remainder, flags=re.I)
        if re.search(r"\w", remainder):
            errors.append("복원 확인 원문 중 연결되지 않은 내용이 있습니다: " + remainder.strip())
    return {_normalize(line) for line in lines}, errors


def _restore_confirmation_coverage(test_case, plan, *, require_plan_links=False,
                                   require_comparison_basis=False, _comparison_basis=None) -> tuple[set[str], list[str]]:
    """Recognize only confirmations already emitted by the guarded compiler.

    This is deliberately a small vocabulary, not a natural-language restore
    interpreter. Extra targets/values and mutation verbs remain fail-closed.
    Historical combined operation/verification lines keep their action mapping.
    """
    if require_comparison_basis or any(item.comparisons for item in plan.restore_confirmations):
        return _restore_comparison_coverage(test_case, plan)
    read_only = {
        index: line for index, line in enumerate(test_case.restore_steps)
        if re.search((r"확인|비교|검사|검증|\b(?:verify|compare|check|confirm)\b" if _comparison_basis is not None else
                      r"확인|비교|검사|\b(?:verify|compare)\b|\bcheck\b.+\b(?:baseline|initial|returned|matches|equals)\b"), line, re.I)
        and not re.search(
            r"선택하|적용하|입력하|변경하|설정하|복원하|누른|누르|켠다|끈다"
            r"|\b(?:click|apply|fill|select|set|restore|reset|uncheck)\b", line, re.I
        )
    }
    covered: set[str] = set()
    errors: list[str] = []
    links = {item.source_text: item for item in plan.restore_confirmations}
    if require_plan_links:
        if len(links) != len(plan.restore_confirmations):
            errors.append("복원 확인 계획에 같은 원문이 중복 연결됐습니다.")
        if set(links) != set(read_only.values()):
            errors.append("복원 확인 문장과 restore_confirmations의 원문 목록이 다릅니다. "
                          "확인 문장은 빠짐없이 연결하고 복원 조작을 확인으로 바꾸지 마세요.")
    if not read_only:
        return covered, errors
    restore_actions = [action for action in plan.actions if action.phase == AutomationPhase.RESTORE]
    last_operation = max((i for i in range(len(test_case.restore_steps)) if i not in read_only), default=-1)
    assertions = {item.result_id: item for item in plan.assertions}
    for index, line in read_only.items():
        label = f"RESTORE confirmation {index + 1}"
        if not restore_actions or last_operation < 0 or index < last_operation:
            errors.append(f"{label}: confirmation must follow the approved restore operations")
            continue
        if any(_normalize(action.source_text) == _normalize(line) for action in plan.actions):
            errors.append(f"{label}: read-only confirmation must not be implemented as an action")
            continue
        # Requiring the exact human-readable target prevents a generic 'check
        # restoration' sentence from claiming an arbitrary additional check.
        targets = [result for result in test_case.expected_results
                   if result.observation_target and _contains(line, result.observation_target)]
        if not targets:
            errors.append(f"{label}: no existing Expected Result observation_target is identified")
            continue
        if require_plan_links:
            link = links.get(line)
            if (link is None or len(set(link.result_ids)) != len(link.result_ids)
                    or set(link.result_ids) != {result.result_id for result in targets}):
                errors.append(f"{label}: 원문에 명시한 모든 확인 대상의 ER ID를 정확히 연결하세요.")
                continue
        remainder = line
        for result in sorted(targets, key=lambda item: len(item.observation_target), reverse=True):
            remainder = re.sub(re.escape(result.observation_target), " ", remainder, flags=re.I)
        comparison_text = remainder
        baseline_comparison = bool(re.search(
            r"시험\s*전|실행\s*전|실행\s*직전|초기\s*상태|원래\s*상태|원상태"
            r"|pre[- ]?test|baseline|initial\s+state", comparison_text, re.I
        ))
        if _comparison_basis == RestoreComparisonBasis.OBSERVED_BASELINE and not baseline_comparison:
            errors.append(f"{label}: 시험 전 관찰값 비교가 원문에 없습니다. 내부 코드를 화면 표시로 가정하지 마세요.")
        if _comparison_basis == RestoreComparisonBasis.PROVED_INITIAL:
            baseline_comparison = False
        supported = True
        for result in targets:
            assertion = assertions.get(result.result_id)
            temperature_restore = (
                assertion is not None
                and assertion.strategy in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}
                and test_case.test_data.initial_temperature_c is not None
                and any(action.action_type == AutomationActionType.SET_TEMPERATURE for action in plan.actions)
            )
            baseline_restore = (
                assertion is not None
                and assertion.observation_layer != ObservationLayer.NOTIFICATION
                and assertion.strategy in (_GENERIC_ASSERTION_STRATEGIES | {AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS})
            )
            observed_hvac_restore = (
                assertion is not None and assertion.strategy == AssertionStrategy.INTERNAL_SET_TEMP
                and test_case.test_data.restore_observed_hvac_state
                and any(action.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC for action in restore_actions)
            )
            if not (temperature_restore or baseline_restore or observed_hvac_restore):
                errors.append(f"{label}: {result.result_id} has no compiler restore comparison")
                supported = False
                continue
            initial_values = []
            if temperature_restore:
                initial_values.append(test_case.test_data.initial_temperature_c)
            reader_for_strategy = {
                AssertionStrategy.UI_TEXT_CONTAINS: PreconditionReadKind.UI_TEXT,
                AssertionStrategy.UI_VALUE_EQUALS: PreconditionReadKind.UI_VALUE,
                AssertionStrategy.UI_CHECKED_EQUALS: PreconditionReadKind.UI_CHECKED,
                AssertionStrategy.UI_ENABLED_EQUALS: PreconditionReadKind.UI_ENABLED,
                AssertionStrategy.INTERNAL_VALUE_EQUALS: PreconditionReadKind.INTERNAL_VALUE,
            }
            for check in plan.precondition_checks:
                if check.source_text not in test_case.preconditions:
                    continue
                same_reader = (check.read_kind == reader_for_strategy.get(assertion.strategy)
                               and check.selector == assertion.selector)
                device_field = (
                    assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS
                    and len(assertion.expected_fields) == 1
                    and check.read_kind == PreconditionReadKind.INTERNAL_VALUE
                    and re.fullmatch(r"window\.__vccs\.devices\[\d+\]\." + re.escape(assertion.expected_fields[0].field_name), check.selector)
                )
                if same_reader or device_field:
                    initial_values.append(check.expected_value)
            named_initial_value = False
            for value in initial_values:
                variants = [str(value)]
                if type(value) in (int, float):
                    variants.append(f"{value:g}")
                for token in variants:
                    pattern = (r"(?<![a-zA-Z0-9_.-])" + re.escape(token) + r"(?![a-zA-Z0-9_.])"
                               if type(value) in (int, float) else
                               r"(?<![a-zA-Z0-9_])" + re.escape(token) + r"(?![a-zA-Z0-9_])")
                    if re.search(pattern, comparison_text, re.I):
                        remainder = re.sub(pattern, " ", remainder, flags=re.I)
                        named_initial_value = True
            if not baseline_comparison and not named_initial_value:
                errors.append(f"{label}: {result.result_id} has no matching proved initial value or baseline comparison")
                supported = False
        # Remove only the supported comparison vocabulary. Any new control,
        # label, numeric value or negation left over must not be silently ignored.
        if require_plan_links:
            remainder = re.sub(r"(?:확인한|관찰한|기록한)(?=\s)", " ", remainder)
        if _comparison_basis is not None:
            remainder = re.sub(r"확인(?:하고|하며|하여|해서)|검사(?:하고|하며)|검증(?:한다|합니다|하고|하며)"
                               r"|비교(?:하고|하며)|\bconfirm\b", "확인한다", remainder, flags=re.I)
        remainder = re.sub(
            r"복원\s*(?:후|뒤)|시험\s*전|실행\s*(?:직전|전)|초기\s*(?:상태|값)|원래\s*상태|원상태"
            r"|동일한지|일치하는지|같은지|돌아왔는지|복구되었는지|복원되었는지|인지"
            r"|비교(?:하여|해서|해)?|확인(?:합니다|한다)?|검사(?:합니다|한다)?"
            r"|pre[- ]?test|baseline|initial\s+state|after\s+restoring|verify|check|compare|matches|equals|same|with|and"
            r"|\b(?:state|value)\b|상태|값|으로|을|를|와|과|및|은|는|이|가|로|에|°c|℃",
            " ", remainder, flags=re.I,
        )
        if require_plan_links:
            # Descriptive wording may name the field already used by this TC.
            # It cannot supply codes, numbers, new targets, or new expected values.
            remainder = re.sub(r"표시|(?<![가-힣])서(?![가-힣])", " ", remainder)
            operation_context = " ".join(test_case.steps)
            result_context = " ".join(result.statement for result in targets)
            initial_context = " ".join(test_case.preconditions)
            for word in set(re.findall(r"[가-힣]{2,}", remainder)):
                if word in operation_context and word in result_context and word in initial_context:
                    remainder = re.sub(r"(?<![가-힣])" + re.escape(word) + r"(?![가-힣])", " ", remainder)
        if re.search(r"[\w가-힣]", remainder):
            errors.append(f"{label}: unsupported target, value or comparison wording" +
                          (f" — 연결되지 않은 표현: {remainder.strip()}; 확인 대상·초기값 근거를 확인하세요."
                           if require_plan_links else ""))
            supported = False
        if supported:
            covered.add(_normalize(line))
    return covered, errors


def evaluate_checkpoint3_plan(
    test_case: ProductTestCaseCandidate,
    plan: Agent3AutomationPlan,
    observation: UiObservation,
    *, require_precondition_proof: bool = True,
    require_restore_confirmation_detail: bool = True,
    require_restore_plan_links: bool = False,
    require_restore_comparison_basis: bool = False,
) -> Checkpoint3Result:
    if test_case.control_path != ControlPath.CENTRAL:
        return Checkpoint3Result(
            status=CheckStatus.FAIL,
            candidate_status=AutomationCandidateStatus.REVISION_REQUIRED,
            checks=[
                CheckResult(
                    rule_id="CP3-001",
                    status=CheckStatus.FAIL,
                    message="The current V2 contract accepts CENTRAL control-panel TCs only.",
                )
            ],
        )
    if (
        plan.planning_status
        == Agent3PlanningStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
    ):
        identity_matches = plan.tc_id == test_case.tc_id and plan.target_device_id == 1
        return Checkpoint3Result(
            status=CheckStatus.REVIEW if identity_matches else CheckStatus.FAIL,
            candidate_status=(
                AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
                if identity_matches
                else AutomationCandidateStatus.REVISION_REQUIRED
            ),
            checks=[
                CheckResult(
                    rule_id="CP3-000",
                    status=CheckStatus.REVIEW,
                    message=(
                        "현재 범용 조작과 관찰만으로 TC를 구현할 수 없어 "
                        "자동화 지원 범위 확장이 필요합니다: "
                        + " / ".join(plan.extension_reasons)
                    ),
                ),
                CheckResult(
                    rule_id="CP3-001",
                    status=CheckStatus.PASS if identity_matches else CheckStatus.FAIL,
                    message=(
                        "The support-extension request preserves the approved TC ID and MVP target device."
                        if identity_matches
                        else "The support-extension request changed the approved TC ID or MVP target device."
                    ),
                ),
            ],
        )
    checks: list[CheckResult] = []

    def add(rule_id: str, status: CheckStatus, message: str) -> None:
        checks.append(CheckResult(rule_id=rule_id, status=status, message=message))

    if require_precondition_proof or plan.precondition_checks:
        proof_errors = _precondition_proof_errors(test_case, plan, observation)
        add("CP3-006A", CheckStatus.FAIL if proof_errors else CheckStatus.PASS,
            " / ".join(proof_errors) if proof_errors else "Every precondition has a grounded read-only runtime check before TEST.")

    observed_selectors = {item.selector for item in observation.elements}
    observed_by_selector = {item.selector: item for item in observation.elements}
    if plan.tc_id == test_case.tc_id and plan.target_device_id == 1:
        add(
            "CP3-001",
            CheckStatus.PASS,
            "The plan preserves the approved TC ID and MVP target device.",
        )
    else:
        add(
            "CP3-001",
            CheckStatus.FAIL,
            "The plan TC ID or MVP target device differs from the approved contract.",
        )

    action_ids = [item.action_id for item in plan.actions]
    unobserved = sorted(
        {
            item.selector
            for item in plan.actions
            if item.selector not in observed_selectors
        }
    )
    action_errors: list[str] = []
    for item in plan.actions:
        if item.selector in observed_by_selector and observed_by_selector[item.selector].match_count != 1:
            action_errors.append(f"{item.action_id}: selector must match exactly one element")
        approved_source = {
            AutomationPhase.PRECONDITION: test_case.preconditions,
            AutomationPhase.TEST: test_case.steps,
            AutomationPhase.RESTORE: test_case.restore_steps,
        }[item.phase]
        if not any(
            _normalize(item.source_text) == _normalize(text)
            for text in approved_source
        ):
            action_errors.append(
                f"{item.action_id}: source_text is not an exact approved TC line"
            )
        if item.action_type == AutomationActionType.SELECT_DEVICE and (
            item.selector != "#device-card-1 .card-body-split"
            or item.value != plan.target_device_id
        ):
            action_errors.append(f"{item.action_id}: invalid device selector or target value")
        elif item.action_type == AutomationActionType.SET_MODE:
            expected_selector = _MODE_SELECTOR.get(str(item.value))
            if expected_selector is None or item.selector != expected_selector:
                action_errors.append(f"{item.action_id}: mode and selector do not match")
        elif item.action_type == AutomationActionType.SET_TEMPERATURE:
            if item.selector != "#det-temp-display":
                action_errors.append(f"{item.action_id}: invalid temperature target")
        elif item.action_type == AutomationActionType.APPLY_COMMANDS and item.selector != ".btn-apply-cmd":
            action_errors.append(f"{item.action_id}: invalid apply selector")
        elif item.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC:
            if (
                item.phase != AutomationPhase.RESTORE
                or not test_case.test_data.restore_observed_hvac_state
                or item.selector != ".btn-apply-cmd"
                or item.value is not None
            ):
                action_errors.append(
                    f"{item.action_id}: invalid observed HVAC restore contract"
                )
        elif item.action_type in _GENERIC_ACTION_TYPES:
            observed = observed_by_selector.get(item.selector)
            if observed is None:
                continue
            if not observed.visible or not observed.enabled:
                action_errors.append(
                    f"{item.action_id}: generic action target is not visible and enabled"
                )
            elif item.action_type == AutomationActionType.CLICK and observed.action_hint != "CLICK":
                action_errors.append(f"{item.action_id}: observed element does not support CLICK")
            elif item.action_type == AutomationActionType.FILL and observed.action_hint != "FILL":
                action_errors.append(f"{item.action_id}: observed element does not support FILL")
            elif item.action_type == AutomationActionType.SELECT_OPTION and observed.action_hint != "SELECT_OPTION":
                action_errors.append(
                    f"{item.action_id}: observed element does not support SELECT_OPTION"
                )
            elif item.action_type in {
                AutomationActionType.CHECK,
                AutomationActionType.UNCHECK,
            } and observed.action_hint != "CHECK_OR_UNCHECK":
                action_errors.append(
                    f"{item.action_id}: observed element does not support checkbox or switch control"
                )
            observed_meaning = " ".join(
                part
                for part in (
                    observed.selector.replace("-", " ").replace("_", " "),
                    observed.text,
                    observed.accessible_name or "",
                    observed.action_hint,
                )
                if part
            )
            if not _has_textual_link(observed_meaning, item.source_text):
                action_errors.append(
                    f"{item.action_id}: observed element has no textual link to the approved TC step"
                )
            if item.action_type in {
                AutomationActionType.FILL,
                AutomationActionType.SELECT_OPTION,
            } and not _scalar_value_is_grounded(item.value, item.source_text):
                action_errors.append(
                    f"{item.action_id}: generic action value is not grounded in source_text"
                )
    if len(action_ids) == len(set(action_ids)) and not unobserved and not action_errors:
        add("CP3-002", CheckStatus.PASS, "Action IDs are unique and every selector was observed.")
    else:
        details = []
        if len(action_ids) != len(set(action_ids)):
            details.append("duplicate action IDs")
        if unobserved:
            details.append("unobserved selectors: " + ", ".join(unobserved))
        if action_errors:
            details.extend(action_errors)
        add("CP3-002", CheckStatus.FAIL, " / ".join(details))

    expected_ids = {item.result_id for item in test_case.expected_results}
    mapped_ids = [item.result_id for item in plan.assertions]
    if set(mapped_ids) == expected_ids and len(mapped_ids) == len(set(mapped_ids)):
        add("CP3-003", CheckStatus.PASS, "Every Expected Result maps to exactly one assertion.")
    else:
        add(
            "CP3-003",
            CheckStatus.FAIL,
            "Expected Result to assertion mapping is incomplete or duplicated. "
            f"expected={sorted(expected_ids)}, mapped={sorted(mapped_ids)}",
        )

    results_by_id = {item.result_id: item for item in test_case.expected_results}
    actions_by_id = {item.action_id: item for item in plan.actions}
    anchoring_errors: list[str] = []
    for assertion in plan.assertions:
        result = results_by_id.get(assertion.result_id)
        if (_is_grouped_test_case(test_case) or (result is not None and result.observation_target)) and assertion.after_action_id is None:
            anchoring_errors.append(
                f"{assertion.result_id}: grouped/detailed-condition assertion has no after_action_id"
            )
            continue
        if assertion.after_action_id is None:
            continue
        anchor = actions_by_id.get(assertion.after_action_id)
        if anchor is None:
            anchoring_errors.append(
                f"{assertion.result_id}: after_action_id does not exist"
            )
            continue
        if anchor.phase == AutomationPhase.RESTORE:
            anchoring_errors.append(
                f"{assertion.result_id}: product expectation cannot be anchored after final restore"
            )
        if result is None:
            continue
        if not result.verify_after_step:
            anchoring_errors.append(
                f"{assertion.result_id}: Expected Result has no verify_after_step"
            )
        elif _normalize(anchor.source_text) != _normalize(result.verify_after_step):
            anchoring_errors.append(
                f"{assertion.result_id}: anchor action does not implement verify_after_step"
            )
        else:
            matching_actions = [
                item
                for item in plan.actions
                if item.phase != AutomationPhase.RESTORE
                and _normalize(item.source_text)
                == _normalize(result.verify_after_step)
            ]
            if matching_actions and anchor.action_id != matching_actions[-1].action_id:
                anchoring_errors.append(
                    f"{assertion.result_id}: assertion is not anchored after the last action for verify_after_step"
                )
    add(
        "CP3-003A",
        CheckStatus.FAIL if anchoring_errors else CheckStatus.PASS,
        " / ".join(anchoring_errors)
        if anchoring_errors
        else "Condition-specific assertions are anchored to the approved execution order.",
    )

    fidelity_errors: list[str] = []
    for assertion in plan.assertions:
        result = results_by_id.get(assertion.result_id)
        if result is None:
            continue
        if assertion.observation_layer != result.observation_layer:
            fidelity_errors.append(f"{assertion.result_id}: observation layer changed")
        fixed_selector = _expected_selector_for_assertion(assertion)
        if fixed_selector is not None and assertion.selector != fixed_selector:
            fidelity_errors.append(f"{assertion.result_id}: invalid observation target")
        allowed_strategies = {
            ObservationLayer.UI: {
                AssertionStrategy.UI_TEMPERATURE,
                AssertionStrategy.CONTROLS_DISABLED,
                AssertionStrategy.DISABLED_TEMPERATURE_TEXT,
                AssertionStrategy.UI_TEXT_CONTAINS,
                AssertionStrategy.UI_VALUE_EQUALS,
                AssertionStrategy.UI_CHECKED_EQUALS,
                AssertionStrategy.UI_ENABLED_EQUALS,
            },
            ObservationLayer.INTERNAL_STATE: {
                AssertionStrategy.INTERNAL_SET_TEMP,
                AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS,
                AssertionStrategy.INTERNAL_VALUE_EQUALS,
            },
            ObservationLayer.NOTIFICATION: (
                {
                    AssertionStrategy.TOAST_BLOCKING,
                    AssertionStrategy.UI_TEXT_CONTAINS,
                }
                if _contains_any(result.statement, _BLOCKING_EXPECTATION_TERMS)
                else {
                    AssertionStrategy.TOAST_VISIBLE,
                    AssertionStrategy.UI_TEXT_CONTAINS,
                }
            ),
        }
        if assertion.strategy not in allowed_strategies[result.observation_layer]:
            fidelity_errors.append(f"{assertion.result_id}: assertion strategy changed the observation meaning")
        if assertion.strategy == AssertionStrategy.CONTROLS_DISABLED:
            if _state_polarities(result.statement, *_STATE_WORD_PAIRS[1]) != {False}:
                fidelity_errors.append(f"{assertion.result_id}: disabled strategy requires an explicit disabled expectation")
        if assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
            for positive, negative in _STATE_WORD_PAIRS:
                required_state = _state_polarities(result.statement, positive, negative)
                if len(required_state) == 1 and _state_polarities(assertion.expected_text or "", positive, negative) != required_state:
                    fidelity_errors.append(f"{assertion.result_id}: text assertion omits the expected product state")
            if not assertion.expected_text or not _contains(
                result.statement, assertion.expected_text
            ):
                fidelity_errors.append(
                    f"{assertion.result_id}: expected text is not grounded in the Expected Result"
                )
            elif not re.sub(r"표시|화면|상태|텍스트|확인|display|visible|text|state|\W", "", assertion.expected_text, flags=re.I):
                fidelity_errors.append(f"{assertion.result_id}: expected text contains no product value or message")
            elif (
                result.observation_layer == ObservationLayer.NOTIFICATION
                and len(_terms(assertion.expected_text)) >= len(_terms(result.statement))
            ):
                fidelity_errors.append(
                    f"{assertion.result_id}: notification expected_text must be a meaningful phrase, not the whole Expected Result sentence"
                )
        elif assertion.expected_text is not None:
            fidelity_errors.append(
                f"{assertion.result_id}: expected_text is unsupported by the current compiler"
            )
        if assertion.strategy in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}:
            if assertion.expected_number is None:
                fidelity_errors.append(f"{assertion.result_id}: numeric expectation is missing")
            else:
                statement_numbers = {float(item) for item in re.findall(r"\d+(?:\.\d+)?", result.statement)}
                if statement_numbers and float(assertion.expected_number) not in statement_numbers:
                    fidelity_errors.append(f"{assertion.result_id}: numeric expectation is not grounded in the Expected Result")
        if assertion.strategy in {
            AssertionStrategy.UI_VALUE_EQUALS,
            AssertionStrategy.UI_CHECKED_EQUALS,
            AssertionStrategy.UI_ENABLED_EQUALS,
            AssertionStrategy.INTERNAL_VALUE_EQUALS,
        }:
            if not _scalar_value_is_grounded(assertion.expected_value, result.statement):
                fidelity_errors.append(
                    f"{assertion.result_id}: expected value is not grounded in the Expected Result"
                )
        elif assertion.expected_value is not None:
            fidelity_errors.append(
                f"{assertion.result_id}: expected_value is not used by the selected strategy"
            )
        if assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS:
            if not assertion.expected_fields:
                fidelity_errors.append(
                    f"{assertion.result_id}: target-device expected_fields are missing"
                )
            field_names = [item.field_name for item in assertion.expected_fields]
            if len(field_names) != len(set(field_names)):
                fidelity_errors.append(
                    f"{assertion.result_id}: target-device field names are duplicated"
                )
            for expected_field in assertion.expected_fields:
                field_name = expected_field.field_name
                expected_value = expected_field.expected_value
                if field_name not in observation.device_state_fields:
                    fidelity_errors.append(
                        f"{assertion.result_id}: target-device field was not observed: {field_name}"
                    )
                if field_name not in result.statement:
                    fidelity_errors.append(
                        f"{assertion.result_id}: target-device field is not named in the Expected Result: {field_name}"
                    )
                if not _scalar_value_is_grounded(expected_value, result.statement):
                    fidelity_errors.append(
                        f"{assertion.result_id}: target-device field value is not grounded in the Expected Result: {field_name}"
                    )
        elif assertion.expected_fields:
            fidelity_errors.append(
                f"{assertion.result_id}: expected_fields are only valid for INTERNAL_DEVICE_FIELDS_EQUALS"
            )
        if assertion.strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS:
            if (
                not _HARNESS_VALUE_PATH.fullmatch(assertion.selector)
                or assertion.selector not in observation.harness_values
            ):
                fidelity_errors.append(
                    f"{assertion.result_id}: internal state path was not observed"
                )
            path_meaning = re.sub(r"[^가-힣A-Za-z0-9]+", " ", assertion.selector)
            if not _has_textual_link(path_meaning, result.statement):
                fidelity_errors.append(
                    f"{assertion.result_id}: internal state path has no textual link to the Expected Result"
                )
        elif assertion.selector != "window.__vccs.devices" and assertion.selector not in observed_selectors:
            fidelity_errors.append(f"{assertion.result_id}: selector was not observed")
        elif assertion.strategy in _GENERIC_ASSERTION_STRATEGIES:
            observed = observed_by_selector.get(assertion.selector)
            if observed is not None:
                if observed.match_count != 1:
                    fidelity_errors.append(f"{assertion.result_id}: selector must match exactly one element")
                observed_meaning = " ".join(
                    part
                    for part in (
                        observed.selector.replace("-", " ").replace("_", " "),
                        observed.text,
                        observed.accessible_name or "",
                        observed.action_hint,
                    )
                    if part
                )
                target_card_selector = f"#device-card-{plan.target_device_id}"
                approved_target_card = (
                    assertion.selector == target_card_selector
                    and bool(
                        re.search(
                            r"(?:장비\s*카드|device\s*card)",
                            result.statement,
                            flags=re.IGNORECASE,
                        )
                    )
                )
                if not approved_target_card and not _has_textual_link(
                    observed_meaning, result.statement
                ):
                    fidelity_errors.append(
                        f"{assertion.result_id}: observed element has no textual link to the Expected Result"
                    )
    if fidelity_errors:
        add("CP3-004", CheckStatus.FAIL, " / ".join(fidelity_errors))
    else:
        add("CP3-004", CheckStatus.PASS, "Observation layers and targets preserve the approved expectations.")

    data = test_case.test_data
    plan_values = [item.value for item in plan.actions]
    value_errors: list[str] = []
    allowed_numbers = set(_tc_temperature_values(test_case))
    allowed_modes = {
        value
        for value in (data.initial_mode, *_tc_requested_modes(test_case))
        if value
    }
    for item in plan.actions:
        if item.action_type == AutomationActionType.SET_TEMPERATURE:
            if not isinstance(item.value, (int, float)) or float(item.value) not in {
                float(value) for value in allowed_numbers
            }:
                value_errors.append(f"{item.action_id}: temperature not present in TC: {item.value}")
        if item.action_type == AutomationActionType.SET_MODE:
            if item.value not in allowed_modes:
                value_errors.append(f"{item.action_id}: mode not present in TC: {item.value}")
    for assertion in plan.assertions:
        if assertion.expected_number is not None and float(assertion.expected_number) not in {
            float(value) for value in allowed_numbers
        }:
            value_errors.append(f"{assertion.result_id}: expected temperature not present in TC")
        if assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS:
            for expected_field in assertion.expected_fields:
                field_name = expected_field.field_name
                expected_value = expected_field.expected_value
                if field_name == "mode" and expected_value not in allowed_modes:
                    value_errors.append(
                        f"{assertion.result_id}: expected mode not present in TC"
                    )
                if field_name == "setTemp" and (
                    not isinstance(expected_value, (int, float))
                    or float(expected_value) not in {
                        float(value) for value in allowed_numbers
                    }
                ):
                    value_errors.append(
                        f"{assertion.result_id}: expected setTemp not present in TC"
                    )
    if value_errors:
        add("CP3-005", CheckStatus.FAIL, " / ".join(value_errors))
    else:
        add("CP3-005", CheckStatus.PASS, "Mode and temperature values are unchanged from the TC.")

    sequence_errors: list[str] = []
    restore_confirmations, confirmation_errors = (
        _restore_confirmation_coverage(test_case, plan,
            require_plan_links=require_restore_plan_links or bool(plan.restore_confirmations),
            require_comparison_basis=require_restore_comparison_basis)
        if require_restore_confirmation_detail else (set(), [])
    )
    explicit_comparisons = require_restore_comparison_basis or any(item.comparisons for item in plan.restore_confirmations)
    if explicit_comparisons:
        add("CP3-006B", CheckStatus.FAIL if confirmation_errors else CheckStatus.PASS,
            " / ".join(confirmation_errors) if confirmation_errors else "복원 대상별 원문·비교 기준·실제 비교 연결을 확인했습니다.")
    else:
        sequence_errors.extend(confirmation_errors)
    phase_rank = {AutomationPhase.PRECONDITION: 0, AutomationPhase.TEST: 1, AutomationPhase.RESTORE: 2}
    ranks = [phase_rank[item.phase] for item in plan.actions]
    if ranks != sorted(ranks):
        sequence_errors.append("action phases are not ordered PRECONDITION -> TEST -> RESTORE")

    def has_action(phase: AutomationPhase, action_type: AutomationActionType, value: Any = None) -> bool:
        return any(
            item.phase == phase
            and item.action_type == action_type
            and (value is None or item.value == value)
            for item in plan.actions
        )

    tc_modes = allowed_modes
    legacy_controller_flow = (
        test_case.control_path == ControlPath.CENTRAL
        and bool(tc_modes or allowed_numbers)
        and not (tc_modes - set(_MODE_SELECTOR))
    )
    if not legacy_controller_flow:
        for phase, lines in ((AutomationPhase.TEST, test_case.steps), (AutomationPhase.RESTORE, test_case.restore_steps)):
            implemented = [_normalize(item.source_text) for item in plan.actions if item.phase == phase]
            last_operation = max((i for i, line in enumerate(lines) if _normalize(line) in implemented), default=-1)
            # A trailing read-only step is implemented by its mapped assertion,
            # not by an invented click. Earlier observations still need ordering.
            observation_steps = {
                _normalize(result.verify_after_step) for result in test_case.expected_results
                if result.verify_after_step and result.result_id in mapped_ids
                and phase == AutomationPhase.TEST
                and any(i > last_operation and _normalize(line) == _normalize(result.verify_after_step)
                    and re.search(r"확인|조회|관찰|검사|\b(?:verify|read|observe|check)\b", line, re.I)
                    and not re.search(r"선택하|적용하|입력하|변경하|설정하|누른|\b(?:click|apply|fill|select|set)\b", line, re.I)
                    for i, line in enumerate(lines))
            }
            required = [_normalize(line) for line in lines
                        if _normalize(line) not in observation_steps
                        and not (phase == AutomationPhase.RESTORE and _normalize(line) in restore_confirmations)]
            if any(line not in implemented for line in required):
                sequence_errors.append(f"{phase.value}: approved step is missing from the plan")
            elif [required.index(line) for line in implemented if line in required] != sorted(
                required.index(line) for line in implemented if line in required
            ):
                sequence_errors.append(f"{phase.value}: approved step order changed")
        if not any(item.phase == AutomationPhase.TEST for item in plan.actions):
            sequence_errors.append("generic plan has no TEST action")
        if test_case.restore_required and not any(
            item.phase == AutomationPhase.RESTORE for item in plan.actions
        ):
            sequence_errors.append("generic plan is missing approved restore actions")
    else:
        target_index = max(plan.target_device_id - 1, 0)
        observed_initial_mode = observation.harness_values.get(
            f"window.__vccs.devices[{target_index}].mode"
        )
        observed_initial_temperature = observation.harness_values.get(
            f"window.__vccs.devices[{target_index}].setTemp"
        )
        initial_mode_needs_setup = (
            data.initial_mode is not None
            and observed_initial_mode != data.initial_mode
        )
        initial_temperature_needs_setup = (
            data.initial_temperature_c is not None
            and (
                not isinstance(observed_initial_temperature, (int, float))
                or float(observed_initial_temperature)
                != float(data.initial_temperature_c)
            )
        )
        needs_initial_apply = (
            initial_mode_needs_setup or initial_temperature_needs_setup
        )
        selection_indices = [
            index
            for index, item in enumerate(plan.actions)
            if item.action_type == AutomationActionType.SELECT_DEVICE
        ]
        test_operation_indices = [
            index
            for index, item in enumerate(plan.actions)
            if item.phase == AutomationPhase.TEST
            and item.action_type
            in {
                AutomationActionType.SET_MODE,
                AutomationActionType.SET_TEMPERATURE,
                AutomationActionType.APPLY_COMMANDS,
            }
        ]
        if not selection_indices:
            sequence_errors.append("target device selection is missing")
        elif test_operation_indices and min(selection_indices) > min(
            test_operation_indices
        ):
            sequence_errors.append(
                "target device selection occurs after a requested test operation"
            )
        if initial_mode_needs_setup and not has_action(AutomationPhase.PRECONDITION, AutomationActionType.SET_MODE, data.initial_mode):
            sequence_errors.append("initial mode setup is missing")
        if initial_temperature_needs_setup and not has_action(AutomationPhase.PRECONDITION, AutomationActionType.SET_TEMPERATURE, data.initial_temperature_c):
            sequence_errors.append("initial temperature setup is missing")
        if needs_initial_apply and not has_action(AutomationPhase.PRECONDITION, AutomationActionType.APPLY_COMMANDS):
            sequence_errors.append("initial state apply is missing")
        for requested_mode in _tc_requested_modes(test_case):
            mode_is_requested_by_step = any(
                _contains(step, requested_mode)
                and re.search(
                    r"(?:설정|변경|전환|선택|요청|set|change|switch)",
                    step,
                    flags=re.IGNORECASE,
                )
                for step in test_case.steps
            )
            if not mode_is_requested_by_step:
                continue
            if not has_action(
                AutomationPhase.TEST,
                AutomationActionType.SET_MODE,
                requested_mode,
            ):
                sequence_errors.append(
                    f"requested mode action is missing: {requested_mode}"
                )
        requested_temperatures = [
            value
            for value in (
                data.requested_temperature_c,
                *data.requested_temperatures_c,
            )
            if value is not None
        ]
        for requested_temperature in dict.fromkeys(requested_temperatures):
            if not has_action(
                AutomationPhase.TEST,
                AutomationActionType.SET_TEMPERATURE,
                requested_temperature,
            ):
                sequence_errors.append(
                    f"requested temperature action is missing: {requested_temperature:g}"
                )
        for reset_step in test_case.intermediate_reset_steps:
            if not any(
                item.phase == AutomationPhase.TEST
                and _normalize(item.source_text) == _normalize(reset_step)
                for item in plan.actions
            ):
                sequence_errors.append(
                    "approved intermediate reset step is missing"
                )
        if test_case.control_path == ControlPath.CENTRAL and not has_action(AutomationPhase.TEST, AutomationActionType.APPLY_COMMANDS):
            sequence_errors.append("central command apply is missing")
    add("CP3-006A", CheckStatus.FAIL if sequence_errors else CheckStatus.PASS, " / ".join(sequence_errors) if sequence_errors else "Action sequence implements the approved setup and test steps.")

    restore_actions = [item for item in plan.actions if item.phase == AutomationPhase.RESTORE]
    restore_errors: list[str] = []
    if bool(restore_actions) != test_case.restore_required:
        restore_errors.append("restore action presence does not match restore_required")
    elif data.restore_observed_hvac_state:
        dynamic_restore_actions = [
            item
            for item in restore_actions
            if item.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC
        ]
        if len(dynamic_restore_actions) != 1:
            restore_errors.append(
                "exactly one observed HVAC restore action is required"
            )
        if any(
            item.action_type
            in {
                AutomationActionType.SET_MODE,
                AutomationActionType.SET_TEMPERATURE,
                AutomationActionType.APPLY_COMMANDS,
            }
            for item in restore_actions
        ):
            restore_errors.append(
                "fixed HVAC restore actions cannot be mixed with observed-state restore"
            )
    elif test_case.restore_required and legacy_controller_flow:
        if (
            data.initial_mode is not None
            and data.requested_mode is not None
            and data.initial_mode != data.requested_mode
            and not has_action(
                AutomationPhase.RESTORE,
                AutomationActionType.SET_MODE,
                data.initial_mode,
            )
        ):
            restore_errors.append("initial mode restore is missing")
        if (
            data.initial_temperature_c is not None
            and data.requested_temperature_c is not None
            and data.initial_temperature_c != data.requested_temperature_c
            and not has_action(
                AutomationPhase.RESTORE,
                AutomationActionType.SET_TEMPERATURE,
                data.initial_temperature_c,
            )
        ):
            restore_errors.append("initial temperature restore is missing")
        if (
            test_case.control_path == ControlPath.CENTRAL
            and not has_action(
                AutomationPhase.RESTORE,
                AutomationActionType.APPLY_COMMANDS,
            )
        ):
            restore_errors.append("central restore apply is missing")
    add(
        "CP3-006",
        CheckStatus.FAIL if restore_errors else CheckStatus.PASS,
        " / ".join(restore_errors)
        if restore_errors
        else "Restore actions preserve the TC initial state contract.",
    )

    statuses = {item.status for item in checks}
    status = CheckStatus.FAIL if CheckStatus.FAIL in statuses else CheckStatus.PASS
    candidate_status = (
        AutomationCandidateStatus.REVISION_REQUIRED
        if status == CheckStatus.FAIL
        else AutomationCandidateStatus.READY_FOR_EXECUTION
    )
    return Checkpoint3Result(status=status, candidate_status=candidate_status, checks=checks)


def _py_literal(value: Any) -> str:
    return repr(value)

def _safe_comment(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())



def compile_automation_candidate(
    run_id: str,
    test_case: ProductTestCaseCandidate,
    plan: Agent3AutomationPlan,
) -> str:
    """Compile a constrained plan into deterministic pytest + Playwright code."""
    if plan.restore_confirmations:
        _, link_errors = _restore_confirmation_coverage(test_case, plan, require_plan_links=True)
        if link_errors:
            raise Agent3Error("복원 확인 계획 연결 오류: " + " / ".join(link_errors))
    if test_case.control_path != ControlPath.CENTRAL:
        raise Agent3Error(
            "The guarded compiler accepts CENTRAL control-panel TCs only."
        )
    action_ids = {action.action_id for action in plan.actions}
    unknown_assertion_anchors = {
        assertion.after_action_id
        for assertion in plan.assertions
        if assertion.after_action_id is not None
        and assertion.after_action_id not in action_ids
    }
    if unknown_assertion_anchors:
        raise Agent3Error(
            "The guarded compiler received unknown assertion anchors: "
            + ", ".join(sorted(unknown_assertion_anchors))
        )
    requested_temperature = test_case.test_data.requested_temperature_c
    asserted_temperatures = {
        float(assertion.expected_number)
        for assertion in plan.assertions
        if assertion.strategy
        in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}
        and assertion.expected_number is not None
    }
    blocked_request = (
        requested_temperature is not None
        and bool(asserted_temperatures)
        and float(requested_temperature) not in asserted_temperatures
    )
    expected_results_by_id = {
        result.result_id: result for result in test_case.expected_results
    }

    def is_blocked_temperature_action(action: AutomationAction) -> bool:
        if action.phase != AutomationPhase.TEST:
            return False
        linked_expected_numbers = {
            float(assertion.expected_number)
            for assertion in plan.assertions
            if assertion.strategy
            in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}
            and assertion.expected_number is not None
            and (
                result := expected_results_by_id.get(assertion.result_id)
            ) is not None
            and result.verify_after_step is not None
            and _normalize(result.verify_after_step) == _normalize(action.source_text)
        }
        if linked_expected_numbers:
            return float(action.value) not in linked_expected_numbers
        return blocked_request
    generic_plan = any(
        item.action_type in _GENERIC_ACTION_TYPES for item in plan.actions
    ) or any(
        item.strategy in _GENERIC_ASSERTION_STRATEGIES for item in plan.assertions
    )
    uses_legacy_temperature_action = any(
        item.action_type == AutomationActionType.SET_TEMPERATURE
        for item in plan.actions
    )
    uses_dynamic_hvac_restore = any(
        item.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC
        for item in plan.actions
    )
    needs_legacy_temperature_helpers = (
        uses_legacy_temperature_action
        or uses_dynamic_hvac_restore
        or any(
            item.strategy == AssertionStrategy.UI_TEMPERATURE
            for item in plan.assertions
        )
    )
    ready_selector = "body" if generic_plan else "#device-card-1"
    restore_actions = [
        action for action in plan.actions if action.phase == AutomationPhase.RESTORE
    ]
    restore_assertions = (
        [
            assertion
            for assertion in plan.assertions
            if (
                assertion.strategy in _GENERIC_ASSERTION_STRATEGIES
                or assertion.strategy
                == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS
            )
            and assertion.observation_layer != ObservationLayer.NOTIFICATION
        ]
        if restore_actions
        else []
    )
    lines = [
        "from __future__ import annotations",
        "",
        "import os",
        "from time import monotonic",
    ]
    if needs_legacy_temperature_helpers:
        lines.append("import re")
    lines.extend(
        [
            "from pathlib import Path",
            "",
            "from playwright.sync_api import sync_playwright",
            "",
            f"# RUN_ID: {run_id}",
            f"# SOURCE_TC: {test_case.tc_id}",
            "TARGET_URL = os.environ['QA_TARGET_URL']",
            "EVIDENCE_DIR = Path(os.environ['QA_EVIDENCE_DIR'])",
            "",
            "def _wait_for_observations(page, observe):",
            "    deadline = monotonic() + 2.0",
            "    while True:",
            "        errors = observe()",
            "        if not errors or monotonic() >= deadline:",
            "            return errors",
            "        page.wait_for_timeout(50)",
            "",
        ]
    )
    if needs_legacy_temperature_helpers:
        lines.extend(
            [
                "def _displayed_temperature(page, selector):",
                "    text = page.locator(selector).inner_text()",
                "    match = re.search(r'-?\\d+(?:\\.\\d+)?', text)",
                "    return float(match.group(0)) if match else None",
                "",
                "def _temperature(page):",
                "    return _displayed_temperature(page, '#det-temp-display')",
                "",
                "def _set_temperature(page, target):",
                "    for _ in range(40):",
                "        current = _temperature(page)",
                "        if current == target:",
                "            return",
                "        selector = '#det-temp-up-btn' if current < target else '#det-temp-down-btn'",
                "        page.locator(selector).click()",
                "    raise RuntimeError(f'temperature setup failed: target={target}, actual={_temperature(page)}')",
                "",
                "def _request_temperature(page, target):",
                "    for _ in range(40):",
                "        before = _temperature(page)",
                "        if before == target:",
                "            return",
                "        selector = '#det-temp-up-btn' if before < target else '#det-temp-down-btn'",
                "        page.locator(selector).click()",
                "        after = _temperature(page)",
                "        if after == before:",
                "            return",
                "    raise RuntimeError(f'temperature request did not settle: target={target}, actual={_temperature(page)}')",
                "",
            ]
        )
    lines.extend(
        [
        f"def test_{test_case.tc_id.lower().replace('-', '_')}():",
        "    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)",
        "    mismatches = []",
        "    test_completed = False",
        "    with sync_playwright() as playwright:",
        "        browser = playwright.chromium.launch(headless=True)",
        "        context = browser.new_context()",
        "        context.tracing.start(screenshots=True, snapshots=True, sources=True)",
        "        page = context.new_page()",
        "        try:",
        "            page.goto(TARGET_URL, wait_until='domcontentloaded')",
        "            page.evaluate('() => localStorage.clear()')",
        "            page.reload(wait_until='domcontentloaded')",
        f"            page.wait_for_selector({_py_literal(ready_selector)}, timeout=5000)",
        ]
    )
    indent = "            "
    if uses_dynamic_hvac_restore:
        lines.extend(
            [
                f"{indent}observed_hvac_baseline = page.evaluate(\"id => {{ const device = window.__vccs.devices.find(d => d.id === id); return device ? {{mode: device.mode, setTemp: device.setTemp}} : null; }}\", {plan.target_device_id})",
                f"{indent}if not observed_hvac_baseline or observed_hvac_baseline.get('mode') not in {_py_literal(sorted(_MODE_SELECTOR))}:",
                f"{indent}    raise RuntimeError('runtime HVAC baseline is unavailable or unsupported')",
                f"{indent}if not isinstance(observed_hvac_baseline.get('setTemp'), (int, float)):",
                f"{indent}    raise RuntimeError('runtime setTemp baseline is unavailable')",
            ]
        )
    restore_baselines: list[tuple[str, AutomationAssertion]] = []
    baseline_start = len(lines)
    for index, assertion in enumerate(restore_assertions):
        variable = f"restore_baseline_{index}"
        restore_baselines.append((variable, assertion))
        if assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
            lines.append(
                f"{indent}{variable} = page.locator({_py_literal(assertion.selector)}).inner_text()"
            )
        elif assertion.strategy == AssertionStrategy.UI_VALUE_EQUALS:
            lines.append(
                f"{indent}{variable} = page.locator({_py_literal(assertion.selector)}).input_value()"
            )
        elif assertion.strategy == AssertionStrategy.UI_CHECKED_EQUALS:
            lines.append(
                f"{indent}{variable} = page.locator({_py_literal(assertion.selector)}).is_checked()"
            )
        elif assertion.strategy == AssertionStrategy.UI_ENABLED_EQUALS:
            lines.append(
                f"{indent}{variable} = page.locator({_py_literal(assertion.selector)}).is_enabled()"
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS:
            lines.append(
                f"{indent}{variable} = page.evaluate({_py_literal('() => ' + assertion.selector)})"
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS:
            field_names = sorted(
                item.field_name for item in assertion.expected_fields
            )
            lines.append(
                f"{indent}{variable} = page.evaluate(\"({{id, fields}}) => {{ const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }}\", "
                + _py_literal(
                    {"id": plan.target_device_id, "fields": field_names}
                )
                + ")"
            )
    baseline_block = lines[baseline_start:]
    action_blocks: list[tuple[str, list[str]]] = []
    for action in [item for item in plan.actions if item.phase != AutomationPhase.RESTORE]:
        block_start = len(lines)
        lines.append(f"{indent}# {action.action_id} {action.phase.value}: {_safe_comment(action.source_text)}")
        if action.action_type == AutomationActionType.SELECT_DEVICE:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).click()")
            lines.append(f"{indent}page.wait_for_function(\"() => window.__vccs.selectedUnitId === {plan.target_device_id}\")")
        elif action.action_type == AutomationActionType.SET_MODE:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).click()")
        elif action.action_type == AutomationActionType.SET_TEMPERATURE:
            if is_blocked_temperature_action(action):
                lines.append(f"{indent}_request_temperature(page, {float(action.value)})")
            else:
                lines.append(f"{indent}_set_temperature(page, {float(action.value)})")
        elif action.action_type == AutomationActionType.APPLY_COMMANDS:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).click()")
        elif action.action_type == AutomationActionType.CLICK:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).click()")
        elif action.action_type == AutomationActionType.FILL:
            lines.append(
                f"{indent}page.locator({_py_literal(action.selector)}).fill(str({_py_literal(action.value)}))"
            )
        elif action.action_type == AutomationActionType.SELECT_OPTION:
            lines.append(
                f"{indent}page.locator({_py_literal(action.selector)}).select_option(str({_py_literal(action.value)}))"
            )
        elif action.action_type == AutomationActionType.CHECK:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).check()")
        elif action.action_type == AutomationActionType.UNCHECK:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).uncheck()")
        elif action.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC:
            lines.append(
                f"{indent}raise RuntimeError('observed HVAC restore action must use RESTORE phase')"
            )
        action_blocks.append((action.action_id, lines[block_start:]))
        del lines[block_start:]

    assertion_blocks: list[tuple[str | None, list[str]]] = []
    for assertion in plan.assertions:
        block_start = len(lines)
        marker = f"{indent}# EXPECTED_RESULT: {assertion.result_id}"
        lines.append(marker)
        if assertion.strategy == AssertionStrategy.UI_TEMPERATURE:
            lines.extend(
                [
                    f"{indent}actual = _displayed_temperature(page, '#det-temp-display')",
                    f"{indent}if actual != {float(assertion.expected_number)}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': UI temperature={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_SET_TEMP:
            lines.extend(
                [
                    f"{indent}actual = page.evaluate(\"id => window.__vccs.devices.find(d => d.id === id).setTemp\", {plan.target_device_id})",
                    f"{indent}if actual != {float(assertion.expected_number)}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': internal setTemp={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS:
            expected_fields = {
                item.field_name: item.expected_value
                for item in assertion.expected_fields
            }
            lines.extend(
                [
                    f"{indent}actual = page.evaluate(\"({{id, fields}}) => {{ const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }}\", "
                    + _py_literal(
                        {
                            "id": plan.target_device_id,
                            "fields": sorted(expected_fields),
                        }
                    )
                    + ")",
                    f"{indent}if actual != {_py_literal(expected_fields)}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': internal device fields={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.TOAST_BLOCKING:
            lines.extend(
                [
                    f"{indent}toast = page.locator('#global-toast')",
                    f"{indent}toast_text = toast.inner_text().strip().lower()",
                    f"{indent}if 'show' not in (toast.get_attribute('class') or '').split():",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': toast not visible')",
                    f"{indent}elif not any(term in toast_text for term in {_py_literal(_BLOCKING_TOAST_ACTUAL_TERMS)}):",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': toast does not indicate blocking: {{toast_text}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.TOAST_VISIBLE:
            lines.extend(
                [
                    f"{indent}toast = page.locator('#global-toast')",
                    f"{indent}if 'show' not in (toast.get_attribute('class') or '').split():",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': toast not visible')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.CONTROLS_DISABLED:
            lines.extend(
                [
                    f"{indent}if page.locator('#det-temp-down-btn').is_enabled() or page.locator('#det-temp-up-btn').is_enabled():",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': temperature controls enabled')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.DISABLED_TEMPERATURE_TEXT:
            lines.extend(
                [
                    f"{indent}if '---' not in page.locator('#det-temp-display').inner_text():",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': disabled text missing')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
            lines.extend(
                [
                    f"{indent}actual = page.locator({_py_literal(assertion.selector)}).inner_text()",
                    f"{indent}if {_py_literal(assertion.expected_text)} not in actual:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': expected text missing: {{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.UI_VALUE_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.locator({_py_literal(assertion.selector)}).input_value()",
                    f"{indent}if actual != str({_py_literal(assertion.expected_value)}):",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': UI value={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.UI_CHECKED_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.locator({_py_literal(assertion.selector)}).is_checked()",
                    f"{indent}if actual != {_py_literal(assertion.expected_value)}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': checked={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.UI_ENABLED_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.locator({_py_literal(assertion.selector)}).is_enabled()",
                    f"{indent}if actual != {_py_literal(assertion.expected_value)}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': enabled={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.evaluate({_py_literal('() => ' + assertion.selector)})",
                    f"{indent}if actual != {_py_literal(assertion.expected_value)}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': internal value={{actual}}')",
                ]
            )
        assertion_blocks.append((assertion.after_action_id, lines[block_start:]))
        del lines[block_start:]

    def append_observation_group(blocks: list[list[str]], prefix: str, errors: str) -> None:
        if not blocks:
            return
        lines.append(f"{prefix}def observe():")
        lines.append(f"{prefix}    {errors} = []")
        for block in blocks:
            lines.extend("    " + line for line in block)
        lines.append(f"{prefix}    return {errors}")
        lines.append(f"{prefix}{errors}.extend(_wait_for_observations(page, observe))")

    prepared_baseline_captured = False
    phases_by_id = {action.action_id: action.phase for action in plan.actions}
    has_preparation = any(action.phase == AutomationPhase.PRECONDITION for action in plan.actions)
    preconditions_checked = False
    for action_id, block in action_blocks:
        if has_preparation and not prepared_baseline_captured and phases_by_id[action_id] == AutomationPhase.TEST:
            # Capture the prepared state even when its verification fails.
            lines.extend(baseline_block)
            prepared_baseline_captured = True
        if not preconditions_checked and phases_by_id[action_id] == AutomationPhase.TEST and plan.precondition_checks:
            lines.extend([f"{indent}precondition_values = {{}}",
                          f"{indent}def observe_preconditions():",
                          f"{indent}    precondition_errors = []"])
            for index, check in enumerate(plan.precondition_checks, start=1):
                expression = _precondition_read_expression(check, plan.target_device_id)
                comparison = (f"{_py_literal(check.expected_value)} in str(precondition_actual)"
                              if check.read_kind == PreconditionReadKind.UI_TEXT else
                              f"type(precondition_actual) is type({_py_literal(check.expected_value)}) and precondition_actual == {_py_literal(check.expected_value)}")
                if type(check.expected_value) in {float, int}:
                    comparison = f"type(precondition_actual) in (int, float) and precondition_actual == {_py_literal(check.expected_value)}"
                lines.extend([
                    f"{indent}    # PRECONDITION: {index} {_safe_comment(check.source_text)}",
                    f"{indent}    precondition_actual = {expression}",
                    f"{indent}    precondition_values[{index}] = precondition_actual",
                    f"{indent}    if not ({comparison}):",
                    f"{indent}        precondition_errors.append('check {index} expected=' + repr({_py_literal(check.expected_value)}) + ' actual=' + repr(precondition_actual))",
                ])
            lines.extend([
                f"{indent}    return precondition_errors",
                f"{indent}precondition_errors = _wait_for_observations(page, observe_preconditions)",
                f"{indent}for check_index, observed_value in precondition_values.items():",
                f"{indent}    print('PRECONDITION_OBSERVED: ' + str(check_index) + ' ' + repr(observed_value))",
                f"{indent}if precondition_errors:",
                f"{indent}    page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)",
                f"{indent}    raise AssertionError('PRECONDITION_NOT_MET: ' + ' | '.join(precondition_errors))",
                f"{indent}print('PRECONDITIONS_VERIFIED: {len(plan.precondition_checks)}')",
            ])
            preconditions_checked = True
        lines.extend(block)
        append_observation_group(
            [block for after, block in assertion_blocks if after == action_id], indent, "mismatches"
        )
    append_observation_group(
        [block for after, block in assertion_blocks if after is None], indent, "mismatches"
    )

    lines.extend(
        [
            f"{indent}page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)",
            f"{indent}assert not mismatches, 'PRODUCT_MISMATCH: ' + ' | '.join(mismatches)",
            f"{indent}test_completed = True",
            "        finally:",
        ]
    )
    if restore_actions:
        lines.extend(
            [
                "            restore_mismatches = []",
                "            try:",
            ]
        )
    for action in restore_actions:
        lines.append(
            f"                # {action.action_id} RESTORE: {_safe_comment(action.source_text)}"
        )
        if action.action_type in {
            AutomationActionType.SELECT_DEVICE,
            AutomationActionType.SET_MODE,
            AutomationActionType.APPLY_COMMANDS,
            AutomationActionType.CLICK,
        }:
            lines.append(
                f"                page.locator({_py_literal(action.selector)}).click()"
            )
        elif action.action_type == AutomationActionType.FILL:
            lines.append(
                f"                page.locator({_py_literal(action.selector)}).fill(str({_py_literal(action.value)}))"
            )
        elif action.action_type == AutomationActionType.SELECT_OPTION:
            lines.append(
                f"                page.locator({_py_literal(action.selector)}).select_option(str({_py_literal(action.value)}))"
            )
        elif action.action_type == AutomationActionType.CHECK:
            lines.append(
                f"                page.locator({_py_literal(action.selector)}).check()"
            )
        elif action.action_type == AutomationActionType.UNCHECK:
            lines.append(
                f"                page.locator({_py_literal(action.selector)}).uncheck()"
            )
        elif action.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC:
            lines.extend(
                [
                    f"                observed_mode_selector = {_py_literal(_MODE_SELECTOR)}[observed_hvac_baseline['mode']]",
                    "                page.locator(observed_mode_selector).click()",
                    "                _set_temperature(page, float(observed_hvac_baseline['setTemp']))",
                    f"                page.locator({_py_literal(action.selector)}).click()",
                ]
            )
        else:
            lines.append(
                f"                _set_temperature(page, {float(action.value)})"
            )
    restore_observation_start = len(lines)
    for action in restore_actions:
        if action.action_type in {
            AutomationActionType.FILL,
            AutomationActionType.SELECT_OPTION,
        }:
            lines.extend(
                [
                    f"                restore_control_value = page.locator({_py_literal(action.selector)}).input_value()",
                    f"                if restore_control_value != str({_py_literal(action.value)}):",
                    f"                    restore_mismatches.append({_py_literal(action.selector)} + f' value={{restore_control_value}}')",
                ]
            )
        elif action.action_type in {
            AutomationActionType.CHECK,
            AutomationActionType.UNCHECK,
        }:
            expected_checked = action.action_type == AutomationActionType.CHECK
            lines.extend(
                [
                    f"                restore_control_checked = page.locator({_py_literal(action.selector)}).is_checked()",
                    f"                if restore_control_checked != {_py_literal(expected_checked)}:",
                    f"                    restore_mismatches.append({_py_literal(action.selector)} + f' checked={{restore_control_checked}}')",
                ]
            )
    for variable, assertion in restore_baselines:
        if assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
            actual = f"page.locator({_py_literal(assertion.selector)}).inner_text()"
        elif assertion.strategy == AssertionStrategy.UI_VALUE_EQUALS:
            actual = f"page.locator({_py_literal(assertion.selector)}).input_value()"
        elif assertion.strategy == AssertionStrategy.UI_CHECKED_EQUALS:
            actual = f"page.locator({_py_literal(assertion.selector)}).is_checked()"
        elif assertion.strategy == AssertionStrategy.UI_ENABLED_EQUALS:
            actual = f"page.locator({_py_literal(assertion.selector)}).is_enabled()"
        elif assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS:
            field_names = sorted(
                item.field_name for item in assertion.expected_fields
            )
            actual = (
                "page.evaluate(\"({id, fields}) => { const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }\", "
                + _py_literal(
                    {"id": plan.target_device_id, "fields": field_names}
                )
                + ")"
            )
        else:
            actual = f"page.evaluate({_py_literal('() => ' + assertion.selector)})"
        lines.extend(
            [
                f"                restore_actual = {actual}",
                f"                if restore_actual != {variable}:",
                f"                    restore_mismatches.append({_py_literal(assertion.selector)} + f' baseline={{{variable}}}, actual={{restore_actual}}')",
            ]
        )
    if (
        restore_actions
        and uses_legacy_temperature_action
        and test_case.test_data.initial_temperature_c is not None
    ):
        initial_temperature = float(test_case.test_data.initial_temperature_c)
        lines.extend(
            [
                "                restore_ui_temperature = _temperature(page)",
                f"                if restore_ui_temperature != {initial_temperature}:",
                "                    restore_mismatches.append(f'UI temperature={restore_ui_temperature}')",
                f"                restore_internal_temperature = page.evaluate(\"id => window.__vccs.devices.find(d => d.id === id).setTemp\", {plan.target_device_id})",
                f"                if restore_internal_temperature != {initial_temperature}:",
                "                    restore_mismatches.append(f'internal setTemp={restore_internal_temperature}')",
            ]
        )
    if restore_actions and uses_dynamic_hvac_restore:
        lines.extend(
            [
                f"                restored_hvac_state = page.evaluate(\"id => {{ const device = window.__vccs.devices.find(d => d.id === id); return device ? {{mode: device.mode, setTemp: device.setTemp}} : null; }}\", {plan.target_device_id})",
                "                if restored_hvac_state != observed_hvac_baseline:",
                "                    restore_mismatches.append(f'internal HVAC baseline={observed_hvac_baseline}, actual={restored_hvac_state}')",
            ]
        )
    if restore_actions:
        restore_block = lines[restore_observation_start:]
        del lines[restore_observation_start:]
        append_observation_group([restore_block], "                ", "restore_mismatches")
        lines.extend(
            [
                "            except Exception as restore_error:",
                "                restore_mismatches.append(f'exception={type(restore_error).__name__}: {restore_error}')",
                "            finally:",
                "                context.tracing.stop(path=str(EVIDENCE_DIR / 'trial-trace.zip'))",
                "                context.close()",
                "                browser.close()",
                "            if restore_mismatches:",
                "                restore_message = 'RESTORE_MISMATCH: ' + ' | '.join(restore_mismatches)",
                "                print(restore_message)",
                "                if test_completed:",
                "                    raise AssertionError(restore_message)",
                "",
            ]
        )
    else:
        lines.extend(
            [
                "            context.tracing.stop(path=str(EVIDENCE_DIR / 'trial-trace.zip'))",
                "            context.close()",
                "            browser.close()",
                "",
            ]
        )
    if restore_actions and plan.restore_confirmations:
        lines.extend([
            "            if not restore_mismatches and test_completed:",
            "                print('RESTORE_CONFIRMATIONS_VERIFIED: ' + "
            + _py_literal(",".join(sorted({result_id for item in plan.restore_confirmations for result_id in item.result_ids}))) + ")",
            "",
        ])
    return "\n".join(lines)


_FORBIDDEN_AGENT3_AST_CALLS = {"eval", "exec", "compile", "open", "system", "remove", "unlink", "rmtree"}


def evaluate_compiled_candidate(
    test_case: ProductTestCaseCandidate, code: str
) -> list[CheckResult]:
    checks: list[CheckResult] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        return [CheckResult(rule_id="CP3-007", status=CheckStatus.FAIL, message=f"Python syntax error: {exc}")]
    checks.append(CheckResult(rule_id="CP3-007", status=CheckStatus.PASS, message="Python syntax and the test function are valid."))

    unsafe: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            modules = [item.name.split('.')[0] for item in node.names] if isinstance(node, ast.Import) else [(node.module or '').split('.')[0]]
            if any(module not in {"__future__", "os", "re", "pathlib", "playwright", "time"} for module in modules):
                unsafe.append("disallowed import: " + ", ".join(modules))
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else node.func.attr if isinstance(node.func, ast.Attribute) else ""
            if name in _FORBIDDEN_AGENT3_AST_CALLS:
                unsafe.append("forbidden call: " + name)
    if "assert True" in code or "pytest.skip" in code or "@pytest.mark.skip" in code:
        unsafe.append("disabled assertion or unconditional skip")
    if unsafe:
        checks.append(CheckResult(rule_id="CP3-008", status=CheckStatus.FAIL, message=" / ".join(sorted(set(unsafe)))))
    else:
        checks.append(CheckResult(rule_id="CP3-008", status=CheckStatus.PASS, message="No shell, file mutation, external call, or assertion bypass was found."))

    missing_markers = [
        item.result_id
        for item in test_case.expected_results
        if f"# EXPECTED_RESULT: {item.result_id}" not in code
    ]
    if missing_markers:
        checks.append(CheckResult(rule_id="CP3-009", status=CheckStatus.FAIL, message="Missing code mappings: " + ", ".join(missing_markers)))
    else:
        checks.append(CheckResult(rule_id="CP3-009", status=CheckStatus.PASS, message="Every Expected Result is traceable to a code assertion."))
    return checks

__all__ = [name for name in globals() if not name.startswith("__")]
