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
AGENT3_SYSTEM_INSTRUCTIONS = QA_EXPECTATION_SCOPE_GUIDANCE + """
For a TC with restoration, use its STRUCTURED contract instead of interpreting confirmation prose: copy restoration.confirmations verbatim into restore_confirmations, including full source_excerpt, result_ids and OBSERVED_BASELINE basis. Implement restoration.operation_steps as RESTORE Actions in order. verify_when=AFTER_RESTORE is implemented by the compiler after restoration, comparing the same ER reader to its original value captured before preparation. Do NOT split descriptions into clauses or infer values, timing or extra targets from them. The legacy prose/excerpt guidance below applies ONLY to TCs without restoration. All action allowlists, source grounding, assertion coverage, original expectations and precondition checks still apply.
For TCs with state_effect: READ_ONLY permits observation and SELECT_DEVICE navigation only, no mutation or restore actions. STATE_CHANGE and BLOCKED_CHANGE require approved restore operations and same-target comparisons. Preserve the original state BEFORE preparation separately from the prepared state BEFORE TEST. Product verdicts use the approved TC assertions at their linked action anchors, not an implicit equality with the whole prepared state. Snapshot differences decide cleanup only; final restoration is compared with the original state. For the observed existing central controller's power/status, mode, fanSpeed, setTemp and locked controls, use a single RESTORE_OBSERVED_CONTROLLER action (RESTORE phase, selector=.btn-apply-cmd, value=null) when the structured restoration operation calls for restoring the original observed controls. Select the target device before any write. Use SELECT_DEVICE, SET_MODE, SET_TEMPERATURE, APPLY_COMMANDS and observed CLICKs on those five controls only. The compiler snapshots and verifies the five internal fields, panel selection/display and card state, including preparation changes; it restores through UI, unlocking separately before other commands and restoring the original lock last. Initial values describe required prepared state, not fixed restore defaults. Do not add unrelated product Expected Results merely to support cleanup. Historical RESTORE_OBSERVED_HVAC with restore_observed_hvac_state=true remains a narrower compatibility path. Use OBSERVED_BASELINE restoration comparisons. The compiler restores even after partial preparation or failed precondition checks. BLOCKED_CHANGE skips restore writes only when no preparation write happened and applied state stayed unchanged. Unsupported recovery/read targets require AUTOMATION_SUPPORT_EXTENSION_REQUIRED, never invented inverse actions or defaults. A restore failure retires that browser context; later independent tests run only in fresh contexts.
Check only conditions stated in the approved TC preconditions; observed facts are available evidence, not additional requirements. Do not add online, visibility, login or selected-state checks merely because the inventory mentions them. A single-device target scope does not itself request a selectedUnitId assertion; an explicitly required selected state still needs its own observed proof.
For BASELINE_CONTEXT, error_free applies to a stated no-error condition, unlocked to a stated unlocked condition, online only to explicit 온라인/online, and target_device_visible to a matching target-device/visibility phrase. Include all facts stated in a compound line, not every available context field. Unknown role/login conditions require their own observed read-only evidence, never the baseline context. Never rewrite the TC source to justify an extra check.
The per-source precondition_context_bindings list exposes the current checker's allowed BASELINE_CONTEXT selectors for each exact TC line. Use only selectors listed for that source; do not borrow selectors from another source or from the overall inventory. These hints cover baseline context only, not all precondition values: explicit initial values still need their matching observed readers. An empty list does not mean the condition is optional or unsupported; inspect the other allowed readers before deciding support is missing.
Every required starting state needs matching precondition_checks, including already-satisfied states. Use multiple checks for multiple explicit values in a line. They execute after all PRECONDITION actions and BEFORE the first TEST action; setup actions alone are not proof. Each check has source_text, read_kind, selector, expected_value. Instructions solely to capture original values can use the compiler's existing same-target baseline capture; do not invent a fixed value or a visibility check for them. All TC preconditions are separately reviewed for coverage, including lines without an explicit check.
Read kinds: UI_TEXT (contains grounded state/value, not a generic label), UI_VALUE (exact string), UI_CHECKED/UI_ENABLED (boolean), INTERNAL_VALUE (exact observed, TC-grounded scalar path), BASELINE_CONTEXT (selector target_device_visible/error_free/unlocked/online, expected_value=true, only for the matching observed baseline fact).
If a stated precondition cannot be observed with these readers, return AUTOMATION_SUPPORT_EXTENSION_REQUIRED with that precise reason. Never delete, invent, or silently weaken preconditions. Product assertions cannot run in PRECONDITION phase.
For state expectations, UI_TEXT_CONTAINS must include the expected state, never only a static control label. CONTROLS_DISABLED requires an explicitly disabled Expected Result. Historical plans without state_effect retain their original prepared-state comparison. New state_effect plans preserve the original pre-setup state for final restoration. CONTROLLER_UI_FIELDS_EQUALS on observed #device-card-1 reads status from card state-run/state-stop classes, mode from mode-* classes, fanSpeed from its displayed fan label, locked from the card lock indication and setTemp from the displayed Celsius value (disabled temperature is not a number). Use expected_fields for the existing five fields, only as grounded in that UI Expected Result. It reads DOM, not the internal harness; INTERNAL_DEVICE_FIELDS_EQUALS separately reads internal values. Do not substitute the fixed text of a power/lock button for its selected state.
Implement every approved TEST and RESTORE operation in order. Trailing read-only verification steps are implemented by their corresponding assertions, not invented clicks.
For UI_TEXT_CONTAINS, copy a complete product value or meaningful message phrase from the Expected Result, never a substring inside a label. This also applies to temperature/mode plans: preserve every step and intermediate reset in the original order.
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
   For new structured state_effect TCs using the five-control inverse, use RESTORE_OBSERVED_CONTROLLER even if the
   grouped HVAC compatibility flag is present. Otherwise, when test_data.restore_observed_hvac_state=true, create exactly one RESTORE_OBSERVED_HVAC action using
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
    Treat it as a source reference, not a description to paraphrase. Copy punctuation and wording.
    A trailing observation-only step, including in STATE_CHANGE/BLOCKED_CHANGE tests, is implemented by
    its assertion after the last TEST action; do not invent a click for reading. Earlier observations
    and mixed operation/observation steps still need their actual operation and ordering.
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
    ui_bindings: Agent3UiBindings | None = None


AGENT3_BINDING_INSTRUCTIONS = """
You bind an approved TC execution_spec to the observed UI, not design another test.
Return only Agent3UiBindings: operation IDs, result IDs, zero-based precondition verification
indices and their observed selectors. Do not write/change values, action kinds, readers,
order, expected results, or timing. The host copies those from the CP2-approved TC.
Use every reference exactly once. Binding-list order is irrelevant; the host preserves
the TC operation order by ID. Copying a similarly named feature
is not a valid binding. Card, panel and internal state are different observation locations.
For a READY result leave extension_reasons empty. If a required interface cannot be
observed, return AUTOMATION_SUPPORT_EXTENSION_REQUIRED, empty binding lists, and precise
missing-interface reasons. Do not change the TC or substitute an existing AUTO mode for
a separately requested function. A TC can be valid while automation is unavailable.
Use only unique observed interfaces appropriate for the fixed operation or reader.
SELECT_DEVICE=#device-card-1 .card-body-split; SET_TEMPERATURE=#det-temp-display;
APPLY_COMMANDS and RESTORE_OBSERVED_CONTROLLER=.btn-apply-cmd for the existing controller.
SET_MODE uses the observed button for that fixed mode. CLICK binds the control named by
source_text, not any other control with the same word. Do not invent a missing selector.
UI_TEMPERATURE=#det-temp-display; INTERNAL_SET_TEMP and INTERNAL_DEVICE_FIELDS_EQUALS
use window.__vccs.devices. CONTROLLER_UI_FIELDS_EQUALS uses #device-card-1 or .detail-panel,
as specified by the ER observation_target. Generic UI readers use the corresponding
observed element. INTERNAL_VALUE_EQUALS uses an exact observed scalar harness path.
CONTROLS_DISABLED=#det-temp-down-btn; DISABLED_TEMPERATURE_TEXT=#det-temp-display;
TOAST_VISIBLE/TOAST_BLOCKING=#global-toast. Availability never proves test success.
""" + QA_EXECUTION_CONTRACT


def assemble_tc_bindings(tc: ProductTestCaseCandidate, bindings: Agent3UiBindings) -> Agent3AutomationPlan:
    """Only UI locations come from Agent 3. Copy all test meaning from Agent 2."""
    spec = tc.execution_spec
    if spec is None:
        raise Agent3Error("화면 연결에 필요한 Agent 2 실행 정의가 없습니다.")
    errors = tc_execution_spec_errors(tc)
    if errors:
        raise Agent3Error("Agent 2 실행 정의: " + " / ".join(errors))
    common = dict(tc_id=tc.tc_id, target_device_id=1, summary=tc.title,
                  planning_status=bindings.planning_status,
                  extension_reasons=bindings.extension_reasons, technical_notes=bindings.technical_notes)
    if bindings.planning_status == Agent3PlanningStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED:
        if bindings.operations or bindings.verifications or bindings.preconditions:
            raise Agent3Error("지원 부족 응답에는 일부 실행 연결을 넣을 수 없습니다.")
        return Agent3AutomationPlan(**common)
    for actual, required in (
        ([b.action_id for b in bindings.operations], [op.action_id for op in spec.operations]),
        ([b.result_id for b in bindings.verifications], [v.result_id for v in spec.verifications]),
        ([b.verification_index for b in bindings.preconditions], list(range(len(spec.precondition_verifications))))):
        if len(actual) != len(set(actual)) or set(actual) != set(required):
            raise Agent3Error("Agent 2 실행 정의의 연결이 누락·중복되거나 알 수 없는 ID입니다.")
    operations = {b.action_id: b.selector for b in bindings.operations}
    verifications = {b.result_id: b.selector for b in bindings.verifications}
    preconditions = {b.verification_index: b.selector for b in bindings.preconditions}
    return Agent3AutomationPlan(**common,
        actions=[AutomationAction(**op.model_dump(exclude={"target"}), selector=operations[op.action_id])
                 for op in spec.operations],
        assertions=[AutomationAssertion(**v.model_dump(exclude={"target"}), selector=verifications[v.result_id])
                    for v in spec.verifications],
        precondition_checks=[PreconditionCheck(**v.model_dump(exclude={"observation_target"}), selector=preconditions[i])
                             for i, v in enumerate(spec.precondition_verifications)],
        restore_confirmations=[c.model_copy(deep=True) for c in tc.restoration.confirmations] if tc.restoration else [])


def tc_plan_handoff_errors(tc: ProductTestCaseCandidate, plan: Agent3AutomationPlan) -> list[str]:
    """Recheck compiled/saved plans; do not trust model or historical PASS flags."""
    if tc.execution_spec is None:
        return []
    errors = tc_execution_spec_errors(tc)
    if errors or plan.planning_status != Agent3PlanningStatus.READY:
        return errors
    if tc.execution_spec.binding_contract == "controller-map-1.0":
        mapped = resolve_controller_bindings(tc)
        if mapped.planning_status != Agent3PlanningStatus.READY:
            return ["연결표에 없는 항목을 실행 계획으로 변환할 수 없습니다."]
        if (plan.target_device_id != 1
                or [(a.action_id, a.selector) for a in plan.actions] != [(b.action_id, b.selector) for b in mapped.operations]
                or [(a.result_id, a.selector) for a in plan.assertions] != [(b.result_id, b.selector) for b in mapped.verifications]
                or [c.selector for c in plan.precondition_checks] != [b.selector for b in mapped.preconditions]):
            return ["TC 연결표의 장비·조작·관찰 위치가 변경되었습니다."]
    try:
        reference = assemble_tc_bindings(tc, Agent3UiBindings(planning_status="READY",
            operations=[OperationBinding(action_id=a.action_id, selector=a.selector) for a in plan.actions],
            verifications=[VerificationBinding(result_id=a.result_id, selector=a.selector) for a in plan.assertions],
            preconditions=[PreconditionBinding(verification_index=i, selector=c.selector)
                           for i, c in enumerate(plan.precondition_checks)],
            extension_reasons=[], technical_notes=[]))
    except Agent3Error as exc:
        return [str(exc)]
    # Only the existing finite-domain spelling conversion is equivalent. No
    # observation is claimed here; CP3 independently checks real interfaces/IDs.
    reference, _ = _normalize_agent3_plan_values(reference, None)
    comparable, _ = _normalize_agent3_plan_values(plan, None)
    for name, actual, expected in (
        ("조작", comparable.actions, reference.actions),
        ("기대값·시점", comparable.assertions, reference.assertions),
        ("사전조건", comparable.precondition_checks, reference.precondition_checks)):
        actual_values = [v.model_dump(mode="json", exclude={"selector"}) for v in actual]
        expected_values = [v.model_dump(mode="json", exclude={"selector"}) for v in expected]
        # JSON comparison deliberately distinguishes false from 0.
        if json.dumps(actual_values, sort_keys=True) != json.dumps(expected_values, sort_keys=True):
            errors.append(f"Agent 2 → Agent 3 {name} 정의 변경·누락")
    confirmations = tc.restoration.confirmations if tc.restoration else []
    if plan.restore_confirmations != confirmations:
        errors.append("Agent 2 복원 확인 연결 변경")
    return errors


def build_agent3_model_input(
    test_case: ProductTestCaseCandidate,
    observation: UiObservation,
    requirements: dict[str, SrsRequirement],
    *, shared_evidence: bool = False,
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
        if shared_evidence:
            field = value.rsplit(".", 1)[-1]
            if field in {*_CONTROLLER_BUTTONS, "setTemp", "id"}:
                return True
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
    payload = {
        "destination": "OpenAI Responses API",
        "store": False,
        "system_instructions": AGENT3_BINDING_INSTRUCTIONS if test_case.execution_spec is not None else AGENT3_SYSTEM_INSTRUCTIONS,
        "test_case": test_case.model_dump(mode="json"),
        "observation_binding_rules": TC_OBSERVATION_BINDING_RULES,
        "execution_contract": QA_EXECUTION_CONTRACT,
        "related_srs_requirements": {} if test_case.execution_spec is not None else related,
        "ui_observation": observation_payload,
        "precondition_context_bindings": [
            {
                "source_text": source,
                "allowed_baseline_context_selectors": [
                    name
                    for name, (pattern, _) in _BASELINE_PRECONDITION_READS.items()
                    if not re.search(r"로그인|관리자|인증|login|admin|authenticat", source, re.I)
                    and re.search(pattern, source, re.I)
                    and isinstance(getattr(observation.verified_execution_context, name, None), bool)
                    and (name == "target_device_visible" or observation.verified_execution_context.device_state_available)
                ],
            }
            for source in (test_case.preconditions if test_case.execution_spec is None else [])
        ],
        "excluded": [
            "API keys and authentication values",
            "local absolute paths and HTML source",
            "screenshots and Playwright traces",
        ],
    }
    if test_case.execution_spec is not None:
        payload["precondition_context_bindings"] = [
            {"verification_index": i, "source_text": v.source_text,
             "observation_target": v.observation_target, "read_kind": v.read_kind.value}
            for i, v in enumerate(test_case.execution_spec.precondition_verifications)]
    if shared_evidence:
        payload["controller_evidence"] = controller_evidence(observation)
    return payload


AGENT3_SYSTEM_INSTRUCTIONS += """
Use the shared observed controller adapter for both UI and internal-value bindings. Its available fields are capabilities, not permission to add tests. Keep the approved TC's target, value, timing and scope unchanged; display labels and internal enums can represent the same state. Never substitute a similarly named existing control for a distinct requested feature. If the required control or reader is absent, request support extension without invented selectors or success claims.
Implement the whole fact of each ExpectedResult, not just a matching result_id or numeric token.
Do not silently omit an independent claim attached to an ExpectedResult. If the approved TC combines
facts that cannot be faithfully asserted, return support-extension/review reasons; never shorten the TC.
The semantic grounding review checks actual actions/assertions against the approved TC separately.
"""


AGENT3_SYSTEM_INSTRUCTIONS += "\n" + QA_EXECUTION_CONTRACT
AGENT3_SYSTEM_INSTRUCTIONS += "\n" + QA_REVIEW_RESPONSIBILITIES
AGENT3_SYSTEM_INSTRUCTIONS += "\n" + QA_TASK_BOUNDARIES


class OpenAIAgent3:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent3Error(
                    "OPENAI_API_KEY is missing. Never place secrets in code or Run artifacts."
                )
            client = OpenAI(max_retries=0)
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
        payload = build_agent3_model_input(test_case, observation, requirements, shared_evidence=True)
        binding_only = test_case.execution_spec is not None
        errors = tc_execution_spec_errors(test_case)
        if errors:
            raise Agent3Error("Agent 2 실행 정의: " + " / ".join(errors))
        user_input = (
            "[CP2-approved product test case]\n"
            f"{json.dumps(payload['test_case'], ensure_ascii=False, indent=2)}\n\n"
            "[Related SRS Requirements]\n"
            f"{json.dumps(payload['related_srs_requirements'], ensure_ascii=False, indent=2)}\n\n"
            "[Observed real UI inventory]\n"
            f"{json.dumps(payload['ui_observation'], ensure_ascii=False, indent=2)}\n\n"
            "[Precondition reader references]\n"
            f"{json.dumps(payload['precondition_context_bindings'], ensure_ascii=False, indent=2)}"
        )
        user_input += "\n[Observed controller adapter; availability is not TC authority]\n" + json.dumps(
            payload["controller_evidence"], ensure_ascii=False)
        if previous_plan is not None and binding_only:
            user_input += "\n[Previous UI bindings; fix locations only]\n" + json.dumps({
                "operations": [{"action_id": a.action_id, "selector": a.selector} for a in previous_plan.actions],
                "verifications": [{"result_id": a.result_id, "selector": a.selector} for a in previous_plan.assertions],
                "preconditions": [{"verification_index": i, "selector": c.selector}
                                  for i, c in enumerate(previous_plan.precondition_checks)],
                "feedback": checkpoint_feedback or [],
            }, ensure_ascii=False)
        elif previous_plan is not None:
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
                " When feedback concerns only Action mapping, copy the previous precondition_checks, "
                "assertions and restore_confirmations unchanged; do not add a new check while fixing an Action. "
                "Use an observed compatibility Action when the inventory does not support the generic Action. "
                "Re-check every BASELINE_CONTEXT selector against the per-source bindings before returning."
            )
        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
                prompt_cache_key="qa-v2-agent3-3-43" if binding_only else "qa-v2-agent3-3-42",
                input=[
                    {"role": "system", "content": payload["system_instructions"]},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent3UiBindings if binding_only else Agent3AutomationPlan,
            )
        except Exception as exc:
            raise Agent3Error(f"Agent 3 model call failed ({type(exc).__name__}). External error body omitted.") from None
        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent3Error("The model did not return a structured Agent 3 automation plan.")
        return Agent3Response(
            plan=assemble_tc_bindings(test_case, parsed) if binding_only else parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
            ui_bindings=parsed if binding_only else None,
        )

_UI_SELECTOR_INVENTORY = {
    ".detail-panel": "READ_STATE: control panel selected values, distinct from device card",
    "#device-card-1": "READ_STATE",
    "#det-power-on-btn": "CLICK",
    "#det-power-off-btn": "CLICK",
    "#det-fan-low": "CLICK",
    "#det-fan-med": "CLICK",
    "#det-fan-high": "CLICK",
    "#det-fan-auto": "CLICK",
    "#det-lock-on-btn": "CLICK",
    "#det-lock-off-btn": "CLICK",
    "#det-temp-limit-text": "Read temperature unit",
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


def _observed_action_hint(
    tag: str, role: str | None, input_type: str | None, *, has_click_handler: bool = False
) -> str:
    """Describe the observed control capability, never its prose label."""
    if tag == "select":
        return "SELECT_OPTION"
    if tag == "textarea" or (tag == "input" and input_type not in {
        "checkbox", "radio", "button", "submit", "reset", "hidden", "file", "image"
    }):
        return "FILL"
    if input_type == "checkbox" or role in {"switch", "checkbox"}:
        return "CHECK_OR_UNCHECK"
    if tag == "button" or role == "button" or (
        tag == "input" and input_type in {"button", "submit", "reset"}
    ):
        return "CLICK"
    # An observed handler is a capability hint, not proof of its effect. Keep
    # specialized/unsupported input types intact; execution verifies the result.
    if has_click_handler and tag not in {"input", "select", "textarea"}:
        return "CLICK"
    return "READ_STATE"


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
        internal_fields = sorted({"id"} | {
            key.removeprefix("internal.")
            for key, (kind, _) in controller_connection_catalog()["preconditions"].items()
            if key.startswith("internal.") and kind == "INTERNAL_VALUE"
        })
        primary_state = page.evaluate(
            """fields => {
                const devices = window.__vccs && Array.isArray(window.__vccs.devices)
                    ? window.__vccs.devices : [];
                const device = devices.find(item => item && item.id === 1);
                if (!device || typeof device !== 'object') return null;
                const observed = {};
                for (const field of fields) {
                    if (!Object.prototype.hasOwnProperty.call(device, field)) continue;
                    const value = device[field];
                    if (value === null || ['string', 'boolean'].includes(typeof value)
                        || (typeof value === 'number' && Number.isFinite(value))) {
                        observed[field] = value;
                    }
                }
                return {
                    observed,
                    id: device.id,
                    index: devices.indexOf(device),
                    mode: typeof device.mode === 'string' ? device.mode : null,
                    setTemp: typeof device.setTemp === 'number' ? device.setTemp : null,
                    status: typeof device.status === 'string' ? device.status : null,
                    locked: typeof device.locked === 'boolean' ? device.locked : null,
                    errorCode: device.errorCode ?? null,
                    hasErrorCode: Object.prototype.hasOwnProperty.call(device, 'errorCode'),
                };
            }""", arg=internal_fields
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
        for selector in _UI_SELECTOR_INVENTORY:
            if selector not in selectors_to_observe:
                continue
            locator = page.locator(selector).first
            if locator.count() == 0:
                continue
            metadata = locator.evaluate("""el => ({
                tag: el.tagName.toLowerCase(),
                role: el.getAttribute('role'),
                input_type: el.tagName.toLowerCase() === 'input' ? el.type : null,
                has_click_handler: typeof el.onclick === 'function'
            })""")
            elements.append(
                ObservedUiElement(
                    selector=selector,
                    match_count=page.locator(selector).count(),
                    tag=metadata["tag"],
                    text=(locator.inner_text() or "").strip(),
                    visible=locator.is_visible(),
                    enabled=locator.is_enabled(),
                    action_hint=_observed_action_hint(**metadata),
                    role=metadata["role"],
                    input_type=metadata["input_type"],
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
                        result.push({
                            selector,
                            match_count: document.querySelectorAll(selector).length,
                            tag,
                            text: (element.innerText || element.textContent || '').trim().slice(0, 300),
                            visible,
                            enabled: !element.disabled && element.getAttribute('aria-disabled') !== 'true',
                            role,
                            input_type: inputType,
                            has_click_handler: typeof element.onclick === 'function',
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
                    item["action_hint"] = _observed_action_hint(
                        item["tag"], item["role"], item["input_type"],
                        has_click_handler=item.pop("has_click_handler", False),
                    )
                    elements.append(ObservedUiElement.model_validate(item))
                    known.add(item["selector"])
        available_harness_keys = set(
            page.evaluate("() => window.__vccs ? Object.keys(window.__vccs) : []")
        )
        harness_keys = sorted(harness_to_observe & available_harness_keys)
        harness_values: dict[str, str | float | int | bool | None] = {}
        if state_available:
            prefix = f"window.__vccs.devices[{primary_state['index']}]"
            harness_values.update({f"{prefix}.{name}": value
                                   for name, value in primary_state["observed"].items()})
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

# Product adapter, not scenario templates: one bounded inverse for the five
# central controls. Keep historical HVAC artifacts on their original path.
_CONTROLLER_BUTTONS = {
    "status": {"OPERATION": "#det-power-on-btn", "STOP": "#det-power-off-btn"},
    "mode": _MODE_SELECTOR,
    "fanSpeed": {value: f"#det-fan-{value.lower()}" for value in ("LOW", "MED", "HIGH", "AUTO")},
    "locked": {True: "#det-lock-on-btn", False: "#det-lock-off-btn"},
}
_TEMPERATURE_CONTROLS = {
    "display": "#det-temp-display", "increase": "#det-temp-up-btn", "decrease": "#det-temp-down-btn",
}
_CONTROLLER_WRITE_SELECTORS = {s for values in _CONTROLLER_BUTTONS.values() for s in values.values()} | {
    ".btn-apply-cmd", "#det-temp-up-btn", "#det-temp-down-btn",
}
_CONTROLLER_RESTORE_SELECTORS = _CONTROLLER_WRITE_SELECTORS | {
    "#det-temp-display", "#det-temp-limit-text", "#device-card-1",
}


def _controller_device_selection_valid(value, target_id, *, implicit=False):
    """An omitted mapped value uses the fixed device; explicit IDs stay strict."""
    return (implicit and value is None) or (type(value) is int and value == target_id)

# Display labels of the existing central-controller adapter, not request examples.
# Numeric values, arbitrary UI text, selectors and product observations are never normalized.
_CONTROLLER_VALUE_LABELS = {
    "status": {"운전": "OPERATION", "정지": "STOP"},
    "mode": {"냉방": "COOL", "난방": "HEAT", "송풍": "FAN", "제습": "DRY", "자동": "AUTO"},
    "fanSpeed": {"약풍": "LOW", "중풍": "MED", "강풍": "HIGH", "자동": "AUTO"},
    "locked": {"잠금": True, "설정": True, "해제": False},
}


def controller_connection_catalog():
    """Product locations/capabilities only. Never stores scenario expected values."""
    actions = {
        "device.select": ("SELECT_DEVICE", "#device-card-1 .card-body-split"),
        "temperature.set": ("SET_TEMPERATURE", _TEMPERATURE_CONTROLS["display"]),
        "temperature.increase": ("CLICK", _TEMPERATURE_CONTROLS["increase"]),
        "temperature.decrease": ("CLICK", _TEMPERATURE_CONTROLS["decrease"]),
        "command.apply": ("APPLY_COMMANDS", ".btn-apply-cmd"),
        "controller.restore": ("RESTORE_OBSERVED_CONTROLLER", ".btn-apply-cmd"),
    }
    for field, choices in _CONTROLLER_BUTTONS.items():
        for value, selector in choices.items():
            name = ("on" if value else "off") if field == "locked" else str(value).lower()
            actions[f"{field}.{name}"] = ("SET_MODE" if field == "mode" else "CLICK", selector)
    fields = (*_CONTROLLER_BUTTONS, "setTemp")
    readers = {}
    for field in fields:
        for location, selector in (("card", "#device-card-1"), ("panel", ".detail-panel"),
                                   ("internal", "window.__vccs.devices")):
            strategy = "INTERNAL_DEVICE_FIELDS_EQUALS" if location == "internal" else "CONTROLLER_UI_FIELDS_EQUALS"
            readers[f"{location}.{field}"] = {strategy: selector}
    readers["panel.setTemp"]["UI_TEMPERATURE"] = "#det-temp-display"
    readers["internal.setTemp"]["INTERNAL_SET_TEMP"] = "window.__vccs.devices"
    readers["temperature.controls"] = {"CONTROLS_DISABLED": "#det-temp-down-btn"}
    readers["temperature.display"] = {"DISABLED_TEMPERATURE_TEXT": "#det-temp-display"}
    readers["notification.toast"] = {kind: "#global-toast" for kind in ("TOAST_VISIBLE", "TOAST_BLOCKING", "UI_TEXT_CONTAINS")}
    preconditions = {f"{location}.{field}": ("CONTROLLER_UI_FIELD", f"{location}.{field}")
                     for location in ("card", "panel") for field in fields}
    preconditions["card.selected"] = ("CONTROLLER_UI_FIELD", "card.selected")
    preconditions.update({f"internal.{field}": ("INTERNAL_VALUE", f"window.__vccs.devices[0].{field}") for field in fields})
    preconditions.update({f"context.{key}": ("BASELINE_CONTEXT", key) for key in _BASELINE_PRECONDITION_READS})
    return {"actions": actions, "readers": readers, "preconditions": preconditions}


def resolve_controller_bindings(tc, observation=None):
    """Resolve exact logical keys, not prose. No fallback to AI or similar keys."""
    spec = tc.execution_spec
    if spec is None or spec.binding_contract != "controller-map-1.0":
        raise Agent3Error("현재 연결표용 TC 실행 정의가 필요합니다.")
    errors = tc_execution_spec_errors(tc)
    if errors:
        raise Agent3Error("Agent 2 실행 정의: " + " / ".join(errors))
    catalog = controller_connection_catalog()
    reasons, operations, verifications, preconditions = [], [], [], []
    observed = {e.selector: e for e in observation.elements} if observation else {}

    def available(selector):
        if observation is None:
            return True
        if selector.startswith("window."):
            return (observation.verified_execution_context.target_device_id == 1
                    and observation.verified_execution_context.device_state_available
                    and (selector == "window.__vccs.devices" or (
                        selector in observation.harness_values
                        and observation.harness_values.get("window.__vccs.devices[0].id") == 1)))
        target = _controller_precondition_target(selector)
        if target:
            selector = target[0]
        elif selector in _BASELINE_PRECONDITION_READS:
            return isinstance(getattr(observation.verified_execution_context, selector, None), bool)
        return selector in observed and observed[selector].match_count == 1

    for op in spec.operations:
        entry = catalog["actions"].get(op.target)
        valid = entry is not None and op.action_type.value == entry[0]
        if valid and op.action_type == AutomationActionType.SET_MODE:
            valid = _MODE_SELECTOR.get(_normalize_controller_plan_value("mode", op.value)) == entry[1]
        if valid and op.action_type == AutomationActionType.SELECT_DEVICE:
            valid = _controller_device_selection_valid(op.value, 1, implicit=True)
        elif valid and op.action_type not in {AutomationActionType.SET_MODE, AutomationActionType.SET_TEMPERATURE}:
            valid = op.value is None
        if not valid or not available(entry[1]):
            reasons.append(f"{op.action_id}: 조작 연결 미지원 또는 실제 위치 없음 ({op.target})")
        else:
            operations.append(OperationBinding(action_id=op.action_id, selector=entry[1]))
    for check in spec.verifications:
        selector = catalog["readers"].get(check.target, {}).get(check.strategy.value)
        field = check.target.split(".", 1)[-1] if check.target else None
        fields_match = not check.expected_fields or [f.field_name for f in check.expected_fields] == [field]
        internal_available = (observation is None or check.observation_layer != ObservationLayer.INTERNAL_STATE
                              or field in observation.device_state_fields)
        if not selector or not fields_match or not internal_available or not available(selector):
            reasons.append(f"{check.result_id}: 관찰 연결 미지원 또는 실제 위치 없음 ({check.target})")
        else:
            verifications.append(VerificationBinding(result_id=check.result_id, selector=selector))
    for i, check in enumerate(spec.precondition_verifications):
        entry = catalog["preconditions"].get(check.observation_target)
        if not entry or check.read_kind.value != entry[0] or not available(entry[1]):
            reasons.append(f"사전조건 {i}: 연결 미지원 또는 실제 위치 없음 ({check.observation_target})")
        else:
            preconditions.append(PreconditionBinding(verification_index=i, selector=entry[1]))
    if reasons:
        return Agent3UiBindings(planning_status="AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
            operations=[], verifications=[], preconditions=[], extension_reasons=reasons, technical_notes=[])
    return Agent3UiBindings(planning_status="READY", operations=operations, verifications=verifications,
                            preconditions=preconditions, extension_reasons=[], technical_notes=[])


class ControllerMapAgent3:
    """Deterministic binding; semantic review remains a separate existing stage."""
    def plan(self, test_case, observation, requirements, **kwargs):
        bindings = resolve_controller_bindings(test_case, observation)
        return Agent3Response(plan=assemble_tc_bindings(test_case, bindings), response_id=None,
            model="local-controller-map-1.0", usage={"input_tokens": 0, "output_tokens": 0, "total_tokens": 0},
            ui_bindings=bindings)


def controller_evidence(observation):
    """Bounded product-adapter vocabulary shared by writer and reviewer."""
    observed = {item.selector for item in observation.elements if item.match_count == 1}
    return {field: {"buttons": [{"value": value, "selector": selector}
                    for value, selector in buttons.items() if selector in observed],
                    "display_labels": _CONTROLLER_VALUE_LABELS[field]}
            for field, buttons in _CONTROLLER_BUTTONS.items()
            if field in observation.device_state_fields}


def _normalize_controller_plan_value(field: str, value: Any) -> Any:
    """Canonicalize a whole finite-domain token, never extract a token from prose."""
    if not isinstance(value, str) or field not in _CONTROLLER_BUTTONS:
        return value
    token = value.strip()
    if token.endswith("."):
        token = token[:-1]  # Exactly one terminal period; no punctuation stripping.
    choices = {str(choice).casefold(): choice for choice in _CONTROLLER_BUTTONS[field]}
    choices.update(_CONTROLLER_VALUE_LABELS[field])
    return choices.get(token.casefold(), value)


def _normalize_agent3_plan_values(
    plan: Agent3AutomationPlan, observation: UiObservation | None,
) -> tuple[Agent3AutomationPlan, list[dict[str, Any]]]:
    """Normalize new model plans only, before all checks/review/compilation.

    Execution requires an observed existing controller reader/action. None is
    used only for finite-domain equivalence comparison, not interface approval.
    No TC, source sentence, selector, field name, timing or observation is rewritten.
    Checkpoint and semantic review still establish whether the chosen value is right.
    """
    result = plan.model_copy(deep=True)
    changes: list[dict[str, Any]] = []
    observed = {item.selector for item in observation.elements if item.match_count == 1} if observation is not None else set()

    def supported(field):
        return (field in _CONTROLLER_BUTTONS and (observation is None or (
                field in observation.device_state_fields
                and any(selector in observed for selector in _CONTROLLER_BUTTONS[field].values()))))

    def update(owner, attribute, field, path):
        if not supported(field):
            return
        before = getattr(owner, attribute)
        after = _normalize_controller_plan_value(field, before)
        if type(before) is not type(after) or before != after:
            setattr(owner, attribute, after)
            changes.append({"path": path, "field": field, "before": before, "after": after})

    def internal_field(selector):
        match = re.fullmatch(r"window\.__vccs\.devices\[(\d+)\]\.(\w+)", selector)
        if not match or (observation is not None and selector not in observation.harness_values):
            return None
        if observation is None:
            return match[2]
        prefix = f"window.__vccs.devices[{match[1]}]"
        return match[2] if observation.harness_values.get(prefix + ".id") == plan.target_device_id else None

    for index, action in enumerate(result.actions):
        if action.action_type == AutomationActionType.SET_MODE and (observation is None or action.selector in observed):
            update(action, "value", "mode", f"actions/{index}/value")
    for index, assertion in enumerate(result.assertions):
        if ((assertion.strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS
             and assertion.selector == "window.__vccs.devices")
                or (assertion.strategy == AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS
                    and assertion.selector in {"#device-card-1", ".detail-panel"}
                    and (observation is None or assertion.selector in observed))):
            for field_index, entry in enumerate(assertion.expected_fields):
                update(entry, "expected_value", entry.field_name,
                       f"assertions/{index}/expected_fields/{field_index}/expected_value")
        elif assertion.strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS:
            update(assertion, "expected_value", internal_field(assertion.selector),
                   f"assertions/{index}/expected_value")
    for index, check in enumerate(result.precondition_checks):
        field = None
        if check.read_kind == PreconditionReadKind.INTERNAL_VALUE:
            field = internal_field(check.selector)
        elif check.read_kind == PreconditionReadKind.CONTROLLER_UI_FIELD:
            target = _controller_precondition_target(check.selector)
            if target and (observation is None or target[0] in observed):
                field = target[2]
        update(check, "expected_value", field, f"precondition_checks/{index}/expected_value")
    return result, changes


def controller_recovery_plan_facts(test_case, plan):
    """Describe emitted cleanup independently of product ERs, never trial success."""
    actions = [a for a in plan.actions
               if a.phase == AutomationPhase.RESTORE
               and a.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER]
    if (test_case.state_effect not in {TcStateEffect.STATE_CHANGE, TcStateEffect.BLOCKED_CHANGE}
            or plan.planning_status != Agent3PlanningStatus.READY or len(actions) != 1):
        return None
    return {
        "action_id": actions[0].action_id, "target_device_id": plan.target_device_id,
        "capture_timing": "BEFORE_SETUP", "comparison_timing": "AFTER_RESTORE",
        "comparison": "FULL_CONTROLLER_SNAPSHOT_EQUALS_ORIGINAL",
        "internal_fields": sorted([*_CONTROLLER_BUTTONS, "setTemp"]),
        "ui_observations": ["panel active selections", "panel temperature and enabled state",
                            "card classes", "card mode/fan/temperature text", "card lock visibility"],
        "includes_preparation_changes": True, "depends_on_product_result_ids": False,
        "trial_success_proved": False,
    }


def controller_recovery_tc_facts(test_case):
    """Use the same binding/restoration validators as execution; no UI/run claim."""
    try:
        bindings = resolve_controller_bindings(test_case)
        plan = assemble_tc_bindings(test_case, bindings)
        if _state_restoration_plan_errors(test_case, plan):
            return None
        return controller_recovery_plan_facts(test_case, plan)
    except (Agent3Error, ValueError):
        return None


# Emitted into standalone candidates; no runtime dependency on this repository.
_CONTROLLER_RESTORE_HELPERS = '''
def _controller_ui_fields(page, device_id, location='card'):
    ui = _controller_snapshot(page, device_id)['ui']
    if location == 'panel':
        values = {}
        for field, choices in _CONTROLLER_BUTTONS.items():
            active = [value for value, selector in choices.items() if ui[field][selector]]
            values[field] = active[0] if len(active) == 1 else None
        temperature = re.search(r'-?\\d+(?:\\.\\d+)?', ui['temperature'])
        values['setTemp'] = float(temperature.group()) if temperature else None
        return values
    classes = ui['card_classes']
    power = [value for css, value in (('state-run', 'OPERATION'), ('state-stop', 'STOP')) if css in classes]
    mode_labels = {'COOL': '냉방', 'HEAT': '난방', 'FAN': '송풍', 'DRY': '제습', 'AUTO': '자동'}
    mode = [value for value, label in mode_labels.items() if 'mode-' + value.lower() in classes and ui['card_values'][0].strip().endswith(label)]
    fan_text = ' '.join(ui['card_values'][1].split())
    fan = {'약풍': 'LOW', '중풍': 'MED', '강풍': 'HIGH', 'A 자동': 'AUTO', '자동': 'AUTO'}.get(fan_text)
    temperature = re.search(r'-?\\d+(?:\\.\\d+)?', ui['card_values'][2])
    return {'status': power[0] if len(power) == 1 else None,
            'mode': mode[0] if len(mode) == 1 else None, 'fanSpeed': fan,
            'locked': 'locked' in classes and ui['card_locked'],
            'setTemp': float(temperature.group()) if temperature else None}

def _controller_snapshot(page, device_id):
    # One read-only observation turn. UI is read from DOM, never synthesized
    # from device fields. No product event or internal mutation is invoked.
    return page.evaluate("""({id, buttons}) => {
        const d = window.__vccs.devices.find(d => d.id === id);
        const state = d ? {status:d.status, mode:d.mode, fanSpeed:d.fanSpeed, setTemp:d.setTemp, locked:d.locked} : null;
        const card = document.querySelector('#device-card-' + id);
        const ui = Object.fromEntries(Object.entries(buttons).map(([field, choices]) =>
            [field, Object.fromEntries(Object.values(choices).map(selector => [selector, document.querySelector(selector).classList.contains('active')]))]));
        ui.temperature = document.querySelector('#det-temp-display').innerText;
        ui.temperature_enabled = ['#det-temp-up-btn','#det-temp-down-btn'].map(s => !document.querySelector(s).disabled);
        ui.card_classes = Array.from(card.classList).filter(c => c !== 'selected').sort();
        ui.card_values = ['.card-mode-text','.fan-speed-indicator','.card-set-temp'].map(s => card.querySelector(s).innerText);
        const lock = card.querySelector('.card-lock-indicator');
        ui.card_locked = getComputedStyle(lock).visibility !== 'hidden' && !!(lock.offsetWidth || lock.offsetHeight || lock.getClientRects().length);
        return {state, ui};
    }""", {'id': device_id, 'buttons': {field: list(choices.values()) for field, choices in _CONTROLLER_BUTTONS.items()}})

def _controller_baseline(page, device_id):
    selectors = [s for choices in _CONTROLLER_BUTTONS.values() for s in choices.values()]
    selectors += ['.btn-apply-cmd', '#det-temp-display', '#det-temp-limit-text', '#det-temp-up-btn', '#det-temp-down-btn', f'#device-card-{device_id}']
    if not page.evaluate('selectors => selectors.every(s => document.querySelectorAll(s).length === 1)', selectors):
        raise RuntimeError('controller interface is missing or ambiguous; no write started')
    snapshot = _controller_snapshot(page, device_id)
    state = snapshot['state']
    if not state or any(state.get(k) not in choices for k, choices in _CONTROLLER_BUTTONS.items()):
        raise RuntimeError('controller baseline is unavailable or unsupported')
    if type(state['locked']) is not bool or type(state['setTemp']) not in (int, float):
        raise RuntimeError('controller baseline has unsupported value types')
    if '°C' not in page.locator('#det-temp-limit-text').inner_text():
        raise RuntimeError('controller restoration currently requires Celsius')
    if page.evaluate("id => !!window.__vccs.devices.find(d => d.id === id).purify", device_id):
        raise RuntimeError('purification recovery is outside the five-control adapter')
    print('CONTROLLER_ORIGINAL: ' + repr(snapshot))
    return snapshot

def _restore_controller(page, device_id, original):
    target = original['state']
    # Re-select through the UI to discard an unapplied pending command.
    page.locator(f'#device-card-{device_id} .card-body-split').click()
    current = _controller_snapshot(page, device_id)['state']
    if current == target:
        return
    if current['locked']:
        page.locator(_CONTROLLER_BUTTONS['locked'][False]).click()
        page.locator('.btn-apply-cmd').click()
        if _controller_snapshot(page, device_id)['state']['locked']:
            raise RuntimeError('controller unlock failed; restoration stopped')
    # FAN/DRY hide temperature. Only use a writable mode when temperature
    # really changed; no fixed initial values or direct internal writes.
    current = _controller_snapshot(page, device_id)['state']
    if current['setTemp'] != target['setTemp']:
        writable = target['mode'] if target['mode'] not in ('FAN', 'DRY') else 'COOL'
        page.locator(_CONTROLLER_BUTTONS['mode'][writable]).click()
        _set_temperature(page, float(target['setTemp']))
        page.locator('.btn-apply-cmd').click()
        if _controller_snapshot(page, device_id)['state']['setTemp'] != target['setTemp']:
            raise RuntimeError('controller temperature restoration failed')
    for field in ('status', 'mode', 'fanSpeed', 'locked'):
        page.locator(_CONTROLLER_BUTTONS[field][target[field]]).click()
    page.locator('.btn-apply-cmd').click()

'''
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
    if test_case.execution_spec is not None and test_case.execution_spec.binding_contract == "controller-map-1.0":
        bindings = resolve_controller_bindings(test_case)
        reasons = list(bindings.extension_reasons)
        if not test_case.automation_candidate or test_case.control_path != ControlPath.CENTRAL:
            reasons.append("중앙제어 자동화 후보가 아닙니다.")
        selectors = {b.selector for b in bindings.operations + bindings.verifications
                     if b.selector.startswith(("#", "."))}
        selectors.update({"#device-card-1", ".detail-panel"})
        # Runtime setup/cleanup uses the same five-control adapter, not inferred TC prose.
        if any(op.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER for op in test_case.execution_spec.operations):
            selectors.update(_CONTROLLER_RESTORE_SELECTORS)
        if any(op.action_type == AutomationActionType.SET_TEMPERATURE for op in test_case.execution_spec.operations):
            selectors.update({"#det-temp-up-btn", "#det-temp-down-btn"})
        return Agent3EligibilityResult(tc_id=test_case.tc_id,
            status=Agent3EligibilityStatus.NOT_AUTOMATABLE if reasons else Agent3EligibilityStatus.ELIGIBLE,
            candidate_status=AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED if reasons else None,
            required_capabilities=["CONTROLLER_MAP_1"], missing_capabilities=reasons,
            required_selectors=sorted(selectors), required_harness_keys=sorted(_REQUIRED_HARNESS_KEYS),
            model_call_allowed=not reasons, extension_reasons=reasons)
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
    if test_case.state_effect is not None and test_case.restoration is not None and primary_device_target:
        # Observe the entire bounded inverse, even for a temperature-only TC.
        required_selectors.update(_CONTROLLER_RESTORE_SELECTORS)
        required_selectors.update({'#det-temp-display', '#det-temp-limit-text', '#device-card-1', '.detail-panel'})
        required_harness_keys.add('devices')

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


def _controller_precondition_target(selector):
    location, separator, field = selector.partition('.')
    allowed = {'status', 'mode', 'fanSpeed', 'setTemp', 'locked'}
    if separator and location in {'card', 'panel'} and (field in allowed or (location == 'card' and field == 'selected')):
        return ('#device-card-1' if location == 'card' else '.detail-panel'), location, field
    return None


def _controller_ui_value_is_grounded(field, value, source, *, legacy_wording_checks):
    if _scalar_value_is_grounded(value, source):
        return True
    # A DOM-decoded enum (e.g. DRY) need not be the TC's display label.
    # Under semantic review, validate the finite adapter value here; the shared
    # execution contract lets the reviewer check its meaning against the TC.
    return (not legacy_wording_checks and field in _CONTROLLER_BUTTONS
            and any(type(value) is type(choice) and value == choice for choice in _CONTROLLER_BUTTONS[field]))


def _precondition_proof_errors(test_case, plan, observation, *, legacy_wording_checks: bool = True,
                               review_precondition_coverage: bool = False,
                               review_value_roles: bool = False, shared_evidence: bool = False) -> list[str]:
    """Check explicit proof mappings, not general natural-language equivalence."""
    errors = []
    frozen = test_case.execution_spec is not None
    approved = set(test_case.preconditions)
    observed = {item.selector: item for item in observation.elements}
    available_paths = build_agent3_model_input(test_case, observation, {}, shared_evidence=shared_evidence)["ui_observation"]["harness_values"]
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
        if check.read_kind == PreconditionReadKind.CONTROLLER_UI_FIELD:
            target = _controller_precondition_target(check.selector)
            if target is None or target[0] not in observed or observed[target[0]].match_count != 1 or plan.target_device_id != 1:
                errors.append('unsupported or unobserved controller precondition reader')
            if target and target[2] in {'locked', 'selected'} and not isinstance(check.expected_value, bool):
                errors.append('controller boolean precondition requires a boolean')
            if not frozen and target and target[2] != 'selected' and not _controller_ui_value_is_grounded(target[2], check.expected_value, check.source_text, legacy_wording_checks=legacy_wording_checks):
                errors.append('controller precondition value is not grounded in its source')
            continue
        if check.read_kind == PreconditionReadKind.BASELINE_CONTEXT:
            binding = _BASELINE_PRECONDITION_READS.get(check.selector)
            reason = None
            if binding is None or check.expected_value is not True:
                reason = "허용된 기본 문맥 항목과 expected_value=true를 사용해야 합니다."
            elif not frozen and re.search(r"로그인|관리자|인증|login|admin|authenticat", check.source_text, re.I):
                reason = "로그인·권한 조건은 장비 기본 문맥으로 증명할 수 없습니다."
            elif not frozen and not re.search(binding[0], check.source_text, re.I):
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
        value_grounded = (_controller_ui_value_is_grounded(check.selector.rsplit(".", 1)[-1],
                            check.expected_value, check.source_text, legacy_wording_checks=False)
                          if shared_evidence and check.read_kind == PreconditionReadKind.INTERNAL_VALUE
                          else _scalar_value_is_grounded(check.expected_value, check.source_text))
        if not frozen and not value_grounded:
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
            if legacy_wording_checks and not _has_textual_link(meaning, check.source_text):
                errors.append("precondition UI target has no textual link to its source")
            if check.read_kind in {PreconditionReadKind.UI_CHECKED, PreconditionReadKind.UI_ENABLED} and not isinstance(check.expected_value, bool):
                errors.append("precondition boolean observation requires a boolean value")
            if not frozen and check.read_kind == PreconditionReadKind.UI_ENABLED and _state_polarities(check.source_text, *_STATE_WORD_PAIRS[1]) != {check.expected_value}:
                errors.append("enabled-state proof requires the same explicit enabled/disabled precondition")
            if check.read_kind == PreconditionReadKind.UI_CHECKED and element.tag != "input":
                errors.append("checked-state proof requires an observed input element")
            if check.read_kind in {PreconditionReadKind.UI_TEXT, PreconditionReadKind.UI_VALUE} and not isinstance(check.expected_value, str):
                errors.append("precondition text/value observation requires a string")
            if not frozen and check.read_kind == PreconditionReadKind.UI_TEXT:
                for positive, negative in _STATE_WORD_PAIRS:
                    state = _state_polarities(check.source_text, positive, negative)
                    if len(state) == 1 and _state_polarities(str(check.expected_value), positive, negative) != state:
                        errors.append("precondition text omits the required state")
    for source, checks in grouped.items():
        if not checks:
            if not review_precondition_coverage:
                errors.append("missing runtime proof for precondition: " + source)
            continue
        required = _explicit_behavior_values(source) - {"PRIMARY_TEST_DEVICE", "CENTRAL_COMMAND_ALLOWED_ROLE"}
        proved = set().union(*(_explicit_behavior_values(json.dumps(check.expected_value, ensure_ascii=False)) for check in checks))
        if not review_value_roles and required - proved:
            errors.append("precondition proof omits explicit values: " + ",".join(sorted(required - proved)))
        # The mandatory coverage review sees every reader for this source.
        # Counting only context readers here rejects valid mixed-reader proofs.
        # Keep the historical completeness rule when that review is not enabled.
        if not review_precondition_coverage and any(check.read_kind == PreconditionReadKind.BASELINE_CONTEXT for check in checks):
            covered_context = {check.selector for check in checks if check.read_kind == PreconditionReadKind.BASELINE_CONTEXT}
            required_context = {key for key, (pattern, _) in _BASELINE_PRECONDITION_READS.items() if re.search(pattern, source, re.I)}
            if required_context - covered_context:
                errors.append("baseline proof omits a stated context fact: " + ",".join(sorted(required_context - covered_context)))
    return errors


def _precondition_read_expression(check: PreconditionCheck, target_device_id: int) -> str:
    if check.read_kind == PreconditionReadKind.CONTROLLER_UI_FIELD:
        target = _controller_precondition_target(check.selector)
        if target is None:
            raise Agent3Error('Unsupported controller precondition reader')
        _, location, field = target
        if field == 'selected':
            return f"page.locator('#device-card-{target_device_id}').evaluate(\"e => e.classList.contains('selected')\")"
        return f"_controller_ui_fields(page, {target_device_id}, {location!r})[{field!r}]"
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
    if test_case.restoration is not None:
        return _structured_restore_plan_coverage(test_case, plan)
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
        baseline_comparison = _has_restore_baseline(comparison_text)
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
        remainder = re.sub(RESTORE_BASELINE_PATTERN, " ", remainder, flags=re.I)
        remainder = re.sub(
            r"복원\s*(?:후|뒤)|초기\s*값"
            r"|동일한지|일치하는지|같은지|돌아왔는지|복구되었는지|복원되었는지|인지"
            r"|비교(?:하여|해서|해)?|확인(?:합니다|한다)?|검사(?:합니다|한다)?"
            r"|after\s+restoring|verify|check|compare|matches|equals|same|with|and"
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


def _structured_restore_plan_coverage(test_case, plan) -> tuple[set[str], list[str]]:
    """Validate the frozen CP2 intent against executable readers, not its prose."""
    errors = _structured_restoration_errors(test_case)
    contract = test_case.restoration
    if contract is None:
        return set(), errors
    approved = [item.model_dump(mode="json") for item in contract.confirmations]
    actual = [item.model_dump(mode="json") for item in plan.restore_confirmations]
    if approved != actual:
        errors.append("Agent 2의 복원 확인 연결·비교 기준을 누락·변경할 수 없습니다")
    sources = {item.source_text for item in contract.confirmations}
    if any(action.source_text in sources for action in plan.actions):
        errors.append("복원 확인 설명을 조작으로 구현할 수 없습니다")
    actions = [a for a in plan.actions if a.phase == AutomationPhase.RESTORE]
    implemented = list(dict.fromkeys(a.source_text for a in actions))
    if implemented != contract.operation_steps:
        errors.append("구조화 복원 조작의 누락·추가 또는 순서 변경")
    results = {r.result_id: r for r in test_case.expected_results}
    assertions = {a.result_id: a for a in plan.assertions}
    for confirmation in contract.confirmations:
        for result_id in confirmation.result_ids:
            result, assertion = results.get(result_id), assertions.get(result_id)
            if (result is None or assertion is None
                    or assertion.observation_layer != result.observation_layer
                    or not _restoration_read_expression(assertion, plan.target_device_id)):
                errors.append(f"{result_id}: 동일 대상의 실제 복원 비교 reader 누락")
    errors.extend(_state_restoration_plan_errors(test_case, plan))
    return {_normalize(line) for line in sources}, errors


def _complete_text_value(statement: str, value: str) -> bool:
    """Accept a whole literal (with Korean particles), not part of a label."""
    literal = r"\s*".join(re.escape(part) for part in value.strip().split())
    if not literal:
        return False
    particle = r"(?:으로|에서|처럼|으로는|로는|입니다|이다|이|가|은|는|을|를|로|도|만|와|과|에)?"
    return re.search(r"(?<![\w])" + literal + particle + r"(?![\w])",
                     statement, re.IGNORECASE) is not None


def _trailing_observation_steps(
    test_case: ProductTestCaseCandidate, plan: Agent3AutomationPlan,
) -> set[str]:
    """Share the existing terminal-read rule between coverage and timing checks."""
    implemented = {_normalize(a.source_text) for a in plan.actions if a.phase == AutomationPhase.TEST}
    last_operation = max((i for i, line in enumerate(test_case.steps)
                          if _normalize(line) in implemented), default=-1)
    mapped = {a.result_id for a in plan.assertions}
    return {
        _normalize(result.verify_after_step) for result in test_case.expected_results
        if result.verify_after_step and result.result_id in mapped
        and any(i > last_operation and _normalize(line) == _normalize(result.verify_after_step)
                and re.search(r"확인|조회|관찰|검사|\b(?:verify|read|observe|check)\b", line, re.I)
                and not re.search(r"선택하|적용하|입력하|변경하|설정하|누른|\b(?:click|apply|fill|select|set)\b", line, re.I)
                for i, line in enumerate(test_case.steps))
    }


_DISABLED_TEMPERATURE_TEXT = FIXED_ASSERTION_TEXT[AssertionStrategy.DISABLED_TEMPERATURE_TEXT]

# Describes supported operations, not whether the product or the TC is correct.
_ASSERTION_READER_SEMANTICS = {
    AssertionStrategy.UI_TEMPERATURE: ("displayed_temperature", "equals", "온도 표시를 숫자로 읽어 expected_number와 비교합니다."),
    AssertionStrategy.INTERNAL_SET_TEMP: ("device.setTemp", "equals", "대상 장비 ID의 내부 setTemp를 expected_number와 비교합니다."),
    AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS: ("device.fields", "equals", "대상 장비 ID의 지정 내부 필드를 expected_fields와 비교합니다."),
    AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS: ("controller_ui_fields", "equals", "패널은 버튼 선택 상태와 온도 표시를, 카드는 상태 클래스·모드/풍량/온도·잠금 표시를 읽습니다. 내부값이 아닌 DOM 필드를 expected_fields와 비교합니다."),
    AssertionStrategy.TOAST_VISIBLE: ("toast.show_class", "equals", "알림 요소의 class에 show가 있는지 확인합니다. 문구 내용은 검사하지 않습니다."),
    AssertionStrategy.TOAST_BLOCKING: ("toast.show_class_and_text", "visible_and_any_term", "알림 show 클래스와 소문자·양끝 공백 제거 문구를 읽고 차단 표현 중 하나가 포함되는지 확인합니다. 정확한 문구 일치 검사가 아닙니다."),
    AssertionStrategy.CONTROLS_DISABLED: ("temperature_buttons.is_enabled", "all_false", "두 온도 버튼의 is_enabled 값을 읽어 모두 비활성인지 확인합니다. 클릭하지 않습니다."),
    AssertionStrategy.DISABLED_TEMPERATURE_TEXT: ("inner_text", "contains", "온도 표시창의 inner_text를 읽어 고정된 비활성 표시 문자열이 포함되는지 확인합니다. 별도 expected_text가 없어도 이 전략에 고정된 비교값이 있습니다."),
    AssertionStrategy.UI_TEXT_CONTAINS: ("inner_text", "contains", "지정 요소의 화면 문구에 expected_text가 포함되는지 확인합니다."),
    AssertionStrategy.UI_VALUE_EQUALS: ("input_value", "equals", "지정 입력 요소의 문자열 값을 문자열로 변환한 expected_value와 비교합니다."),
    AssertionStrategy.UI_CHECKED_EQUALS: ("is_checked", "equals", "지정 요소의 체크 상태를 expected_value와 비교합니다."),
    AssertionStrategy.UI_ENABLED_EQUALS: ("is_enabled", "equals", "지정 요소의 활성 상태를 expected_value와 비교합니다."),
    AssertionStrategy.INTERNAL_VALUE_EQUALS: ("internal_expression", "equals", "허용된 내부 읽기 표현식의 값을 expected_value와 비교합니다."),
}


def _assertion_reader_facts(assertion: AutomationAssertion, device_id: int) -> dict:
    kind, comparison, behavior = _ASSERTION_READER_SEMANTICS[assertion.strategy]
    strategy = assertion.strategy
    selectors = [assertion.selector]
    if strategy in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.DISABLED_TEMPERATURE_TEXT}:
        selectors = [_TEMPERATURE_CONTROLS["display"]]
    elif strategy == AssertionStrategy.CONTROLS_DISABLED:
        selectors = [_TEMPERATURE_CONTROLS["decrease"], _TEMPERATURE_CONTROLS["increase"]]
    elif strategy in {AssertionStrategy.TOAST_VISIBLE, AssertionStrategy.TOAST_BLOCKING}:
        selectors = ["#global-toast"]
    expected = assertion.expected_value
    if strategy in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}:
        expected = assertion.expected_number
    elif strategy in {AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS, AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS}:
        expected = {f.field_name: f.expected_value for f in assertion.expected_fields}
    elif strategy == AssertionStrategy.UI_TEXT_CONTAINS:
        expected = assertion.expected_text
    elif strategy == AssertionStrategy.UI_VALUE_EQUALS:
        expected = str(assertion.expected_value)
    elif strategy == AssertionStrategy.DISABLED_TEMPERATURE_TEXT:
        expected = _DISABLED_TEMPERATURE_TEXT
    elif strategy == AssertionStrategy.CONTROLS_DISABLED:
        expected = [False, False]
    elif strategy == AssertionStrategy.TOAST_VISIBLE:
        expected = True
    elif strategy == AssertionStrategy.TOAST_BLOCKING:
        expected = {"visible": True, "any_text_term": list(_BLOCKING_TOAST_ACTUAL_TERMS)}
    return {"result_id": assertion.result_id, "strategy": strategy.value,
        "plan_anchor": assertion.selector, "read_selectors": selectors,
        "target_device_id": device_id, "observation_layer": assertion.observation_layer.value,
        "after_action_id": assertion.after_action_id, "read_kind": kind,
        "comparison": comparison, "effective_expected": expected, "behavior": behavior}


def execution_interface_facts(plan: Agent3AutomationPlan, observation: UiObservation) -> dict:
    """Describe emitted adapters, not successful execution or product expectations."""
    elements = {e.selector: e for e in observation.elements}
    adapters = []
    for action in plan.actions:
        if action.action_type == AutomationActionType.SET_TEMPERATURE:
            adapters.append({"action_id": action.action_id, "plan_anchor": action.selector,
                "read_selector": _TEMPERATURE_CONTROLS["display"],
                "click_selectors": [_TEMPERATURE_CONTROLS["increase"], _TEMPERATURE_CONTROLS["decrease"]],
                "behavior": "온도 표시를 읽고 목표 방향의 버튼을 반복 클릭합니다. 표시창을 클릭하거나 입력하지 않습니다. "
                    "TEST의 범위 제한 관찰은 목표 도달 또는 표시값 정지 후 TC의 기대결과로 판정합니다. "
                    "준비·복원은 목표값 도달을 요구합니다.",
                "dependencies": [{"selector": selector,
                    "match_count": elements[selector].match_count if selector in elements else 0,
                    "action_hint": elements[selector].action_hint if selector in elements else None}
                    for selector in _TEMPERATURE_CONTROLS.values()]})
    readers = [_assertion_reader_facts(a, plan.target_device_id) for a in plan.assertions]
    return {"contract": "1.0", "trial_success_proved": False,
        "actionability": "UI 목록의 visible/enabled는 수집 당시 상태입니다. 대상 선택·준비 후에는 달라질 수 있습니다. "
            "존재·유일성·조작 종류는 사전에 검사하고, 실제 조작 가능 여부는 각 동작 시 Playwright가 확인합니다. "
            "실행 불가 시 오류로 남기며 강제 클릭하거나 성공으로 건너뛰지 않습니다. "
            "TC에서 요구한 활성·비활성 기대결과 검사는 별도로 유지합니다.",
        "adapters": adapters, "readers": readers}


def evaluate_checkpoint3_plan(
    test_case: ProductTestCaseCandidate,
    plan: Agent3AutomationPlan,
    observation: UiObservation,
    *, require_precondition_proof: bool = True,
    require_restore_confirmation_detail: bool = True,
    require_restore_plan_links: bool = False,
    require_restore_comparison_basis: bool = False,
    require_plan_fidelity: bool = True,
    legacy_wording_checks: bool = True,
    allow_terminal_observation_anchor: bool = False,
    allow_state_change_terminal_observation: bool = False,
    require_assertion_target_identity: bool = False,
    review_precondition_coverage: bool = False,
    review_value_roles: bool = False,
    shared_evidence: bool = False,
    execution_interface: bool = False,
) -> Checkpoint3Result:
    frozen = test_case.execution_spec is not None
    handoff_errors = tc_plan_handoff_errors(test_case, plan)
    if handoff_errors:
        return Checkpoint3Result(status=CheckStatus.FAIL,
            candidate_status=AutomationCandidateStatus.REVISION_REQUIRED,
            checks=[CheckResult(rule_id="CP3-014", status=CheckStatus.FAIL, message=" / ".join(handoff_errors))])
    if frozen:
        # The accepted TC's typed definitions replace prose value inference.
        # Interface/identity/runtime checks and semantic UI-binding review remain.
        legacy_wording_checks = False
        review_value_roles = True
        review_precondition_coverage = True
        shared_evidence = True
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
        proof_errors = _precondition_proof_errors(test_case, plan, observation, legacy_wording_checks=legacy_wording_checks,
                                                  review_precondition_coverage=review_precondition_coverage,
                                                  review_value_roles=review_value_roles, shared_evidence=shared_evidence)
        # CP3-006A remains the historical action-sequence identifier. Saved
        # checkpoints are not rewritten; fresh proof checks have their own ID.
        add("CP3-006D", CheckStatus.FAIL if proof_errors else CheckStatus.PASS,
            " / ".join(proof_errors) if proof_errors else
            "Provided runtime checks are structurally valid; complete precondition coverage requires semantic review." if review_precondition_coverage else
            "Every precondition has a grounded read-only runtime check before TEST.")

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
            or not _controller_device_selection_valid(item.value, plan.target_device_id,
                implicit=(test_case.execution_spec is not None
                          and test_case.execution_spec.binding_contract == "controller-map-1.0"))
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
        elif item.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER:
            required = _CONTROLLER_RESTORE_SELECTORS
            missing = required - observed_selectors
            if (item.phase != AutomationPhase.RESTORE or test_case.state_effect is None
                    or test_case.restoration is None or item.selector != '.btn-apply-cmd' or item.value is not None
                    or missing or any(observed_by_selector[s].match_count != 1 for s in required if s in observed_by_selector)
                    or not {'status', 'mode', 'fanSpeed', 'setTemp', 'locked'}.issubset(observation.device_state_fields)):
                action_errors.append(f'{item.action_id}: 공통 관제점 복원 계약 또는 관찰 인터페이스 누락')
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
            if not execution_interface and (not observed.visible or not observed.enabled):
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
            if legacy_wording_checks and not _has_textual_link(observed_meaning, item.source_text):
                action_errors.append(
                    f"{item.action_id}: observed element has no textual link to the approved TC step"
                )
            if item.action_type in {
                AutomationActionType.FILL,
                AutomationActionType.SELECT_OPTION,
            } and not frozen and not _scalar_value_is_grounded(item.value, item.source_text):
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
    terminal_observations = _trailing_observation_steps(test_case, plan)
    test_actions = [item for item in plan.actions if item.phase == AutomationPhase.TEST]
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
        elif not frozen and _normalize(anchor.source_text) != _normalize(result.verify_after_step):
            terminal_read = (
                allow_terminal_observation_anchor
                and (allow_state_change_terminal_observation or (
                    test_case.state_effect == TcStateEffect.READ_ONLY
                    and all(a.action_type == AutomationActionType.SELECT_DEVICE for a in plan.actions)))
                and _normalize(result.verify_after_step) in terminal_observations
                and test_actions and anchor.action_id == test_actions[-1].action_id
            )
            if not terminal_read:
                anchoring_errors.append(
                    f"{assertion.result_id}: anchor action does not implement verify_after_step"
                )
        elif not frozen:
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
                AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS,
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
        if frozen:
            allowed_strategies[ObservationLayer.NOTIFICATION] = {
                AssertionStrategy.TOAST_BLOCKING, AssertionStrategy.TOAST_VISIBLE, AssertionStrategy.UI_TEXT_CONTAINS}
        if assertion.strategy not in allowed_strategies[result.observation_layer]:
            fidelity_errors.append(f"{assertion.result_id}: assertion strategy changed the observation meaning")
        if not frozen and assertion.strategy == AssertionStrategy.CONTROLS_DISABLED:
            if _state_polarities(result.statement, *_STATE_WORD_PAIRS[1]) != {False}:
                fidelity_errors.append(f"{assertion.result_id}: disabled strategy requires an explicit disabled expectation")
        if assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
            for positive, negative in ([] if frozen else _STATE_WORD_PAIRS):
                required_state = _state_polarities(result.statement, positive, negative)
                if len(required_state) == 1 and _state_polarities(assertion.expected_text or "", positive, negative) != required_state:
                    fidelity_errors.append(f"{assertion.result_id}: text assertion omits the expected product state")
            if not assertion.expected_text or (not frozen and not _contains(
                result.statement, assertion.expected_text
            )):
                fidelity_errors.append(
                    f"{assertion.result_id}: expected text is not grounded in the Expected Result"
                )
            elif not frozen and not re.sub(r"표시|화면|상태|텍스트|확인|display|visible|text|state|\W", "", assertion.expected_text, flags=re.I):
                fidelity_errors.append(f"{assertion.result_id}: expected text contains no product value or message")
            elif not frozen and require_plan_fidelity and not _complete_text_value(result.statement, assertion.expected_text):
                fidelity_errors.append(f"{assertion.result_id}: expected text is only part of a product value or message")
            elif (
                not frozen and result.observation_layer == ObservationLayer.NOTIFICATION
                and len(_terms(assertion.expected_text)) >= len(_terms(result.statement))
            ):
                fidelity_errors.append(
                    f"{assertion.result_id}: notification expected_text must be a meaningful phrase, not the whole Expected Result sentence"
                )
        elif not assertion_text_matches_contract(assertion.strategy, assertion.expected_text):
            fidelity_errors.append(
                f"{assertion.result_id}: expected_text is unsupported by the current compiler"
            )
        if assertion.strategy in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}:
            if assertion.expected_number is None:
                fidelity_errors.append(f"{assertion.result_id}: numeric expectation is missing")
            else:
                statement_numbers = {float(item) for item in re.findall(r"\d+(?:\.\d+)?", result.statement)}
                if not frozen and statement_numbers and float(assertion.expected_number) not in statement_numbers:
                    fidelity_errors.append(f"{assertion.result_id}: numeric expectation is not grounded in the Expected Result")
        if assertion.strategy in {
            AssertionStrategy.UI_VALUE_EQUALS,
            AssertionStrategy.UI_CHECKED_EQUALS,
            AssertionStrategy.UI_ENABLED_EQUALS,
            AssertionStrategy.INTERNAL_VALUE_EQUALS,
        }:
            value_grounded = (_controller_ui_value_is_grounded(assertion.selector.rsplit(".", 1)[-1],
                                assertion.expected_value, result.statement, legacy_wording_checks=False)
                              if shared_evidence and assertion.strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS
                              else _scalar_value_is_grounded(assertion.expected_value, result.statement))
            if not frozen and not value_grounded:
                fidelity_errors.append(
                    f"{assertion.result_id}: expected value is not grounded in the Expected Result"
                )
        elif assertion.expected_value is not None:
            fidelity_errors.append(
                f"{assertion.result_id}: expected_value is not used by the selected strategy"
            )
        if assertion.strategy in {AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS, AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS}:
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
                if assertion.strategy == AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS and (
                    assertion.selector not in {'#device-card-1', '.detail-panel'} or field_name not in {'status', 'mode', 'fanSpeed', 'setTemp', 'locked'}
                    or assertion.selector not in observed_by_selector or observed_by_selector[assertion.selector].match_count != 1
                ):
                    fidelity_errors.append(f'{assertion.result_id}: unsupported controller UI field/target')
                if field_name not in observation.device_state_fields:
                    fidelity_errors.append(
                        f"{assertion.result_id}: target-device field was not observed: {field_name}"
                    )
                if legacy_wording_checks and field_name not in result.statement:
                    fidelity_errors.append(
                        f"{assertion.result_id}: target-device field is not named in the Expected Result: {field_name}"
                    )
                value_grounded = (_controller_ui_value_is_grounded(field_name, expected_value, result.statement, legacy_wording_checks=legacy_wording_checks)
                                  if assertion.strategy == AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS or shared_evidence
                                  else _scalar_value_is_grounded(expected_value, result.statement))
                if not frozen and not value_grounded:
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
            device_prefix = re.match(r"window\.__vccs\.devices\[\d+\]", assertion.selector)
            if (require_assertion_target_identity and device_prefix
                    and observation.harness_values.get(device_prefix.group() + ".id") != plan.target_device_id):
                fidelity_errors.append(f"{assertion.result_id}: internal device index does not identify the observed target")
            path_meaning = re.sub(r"[^가-힣A-Za-z0-9]+", " ", assertion.selector)
            if legacy_wording_checks and not _has_textual_link(path_meaning, result.statement):
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
                if legacy_wording_checks and not approved_target_card and not _has_textual_link(
                    observed_meaning, result.statement
                ):
                    fidelity_errors.append(
                        f"{assertion.result_id}: observed element has no textual link to the Expected Result"
                    )
    if fidelity_errors:
        add("CP3-004", CheckStatus.FAIL, " / ".join(fidelity_errors))
    else:
        add("CP3-004", CheckStatus.PASS,
            "Observation layers and targets preserve the approved expectations." if legacy_wording_checks
            else "Observation layers, available readers and grounded values checked; target semantics are not proved by wording.")

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
        if frozen:
            continue
        if item.action_type == AutomationActionType.SET_TEMPERATURE:
            if not isinstance(item.value, (int, float)) or float(item.value) not in {
                float(value) for value in allowed_numbers
            }:
                value_errors.append(f"{item.action_id}: temperature not present in TC: {item.value}")
        if item.action_type == AutomationActionType.SET_MODE:
            if item.value not in allowed_modes:
                value_errors.append(f"{item.action_id}: mode not present in TC: {item.value}")
    for assertion in plan.assertions:
        # Outputs need not equal inputs (e.g. a boundary clamp). CP3-004 checks
        # each output against its ER; the mandatory shared-evidence review
        # verifies its meaning. Retain the old input-membership rule for legacy.
        if shared_evidence:
            continue
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
        and test_case.state_effect != TcStateEffect.READ_ONLY
        and bool(tc_modes or allowed_numbers)
        and not (tc_modes - set(_MODE_SELECTOR))
    )
    if require_plan_fidelity or not legacy_controller_flow:
        for phase, lines in ([] if frozen else ((AutomationPhase.TEST, test_case.steps), (AutomationPhase.RESTORE, test_case.restore_steps))):
            implemented = [_normalize(item.source_text) for item in plan.actions if item.phase == phase]
            # A trailing read-only step is implemented by its mapped assertion,
            # not by an invented click. Earlier observations still need ordering.
            observation_steps = terminal_observations if phase == AutomationPhase.TEST else set()
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
    if legacy_controller_flow and not frozen:
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
    elif any(a.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER for a in restore_actions):
        restore_errors.extend(_state_restoration_plan_errors(test_case, plan))
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

    if test_case.state_effect is not None:
        policy_errors = _state_restoration_plan_errors(test_case, plan)
        add("CP3-006C", CheckStatus.FAIL if policy_errors else CheckStatus.PASS,
            " / ".join(policy_errors) if policy_errors else "유형별 상태 복원·관찰 계획 확인")
    statuses = {item.status for item in checks}
    status = CheckStatus.FAIL if CheckStatus.FAIL in statuses else CheckStatus.PASS
    candidate_status = (
        AutomationCandidateStatus.REVISION_REQUIRED
        if status == CheckStatus.FAIL
        else AutomationCandidateStatus.READY_FOR_EXECUTION
    )
    return Checkpoint3Result(status=status, candidate_status=candidate_status, checks=checks)


def _restoration_read_expression(assertion: AutomationAssertion, device_id: int) -> str | None:
    """Read only the approved assertion target; never discover/write arbitrary state."""
    strategy, selector = assertion.strategy, repr(assertion.selector)
    methods = {
        AssertionStrategy.UI_TEXT_CONTAINS: "inner_text",
        AssertionStrategy.UI_VALUE_EQUALS: "input_value",
        AssertionStrategy.UI_CHECKED_EQUALS: "is_checked",
        AssertionStrategy.UI_ENABLED_EQUALS: "is_enabled",
        AssertionStrategy.CONTROLS_DISABLED: "is_enabled",
        AssertionStrategy.DISABLED_TEMPERATURE_TEXT: "inner_text",
    }
    if strategy in methods:
        return f"page.locator({selector}).{methods[strategy]}()"
    if strategy == AssertionStrategy.UI_TEMPERATURE:
        return "_displayed_temperature(page, '#det-temp-display')"
    if strategy == AssertionStrategy.INTERNAL_SET_TEMP:
        return f"page.evaluate('id => window.__vccs.devices.find(d => d.id === id).setTemp', {device_id})"
    if strategy == AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS:
        fields = sorted(f.field_name for f in assertion.expected_fields)
        location = 'panel' if assertion.selector == '.detail-panel' else 'card'
        return f'{{k: v for k, v in _controller_ui_fields(page, {device_id}, {location!r}).items() if k in {fields!r}}}'
    if strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS:
        return f"page.evaluate({repr('() => ' + assertion.selector)})"
    if strategy == AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS:
        args = {'id': device_id, 'fields': sorted(item.field_name for item in assertion.expected_fields)}
        return ("page.evaluate('({id, fields}) => { const d = window.__vccs.devices.find(d => d.id === id); "
                "return Object.fromEntries(fields.map(f => [f, d ? d[f] : null])); }', " + repr(args) + ")")
    return None


def _state_restoration_plan_errors(test_case: ProductTestCaseCandidate, plan: Agent3AutomationPlan) -> list[str]:
    if test_case.state_effect is None:
        if any(a.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER for a in plan.actions):
            return ['공통 관제점 복원에는 state_effect 계약이 필요합니다']
        return []  # Historical artifacts keep their original contract.
    errors = []
    read_only = test_case.state_effect == TcStateEffect.READ_ONLY
    if test_case.restore_required == read_only:
        errors.append("조회는 복원 불필요, 변경·차단은 복원 필요")
    preparation = [a for a in plan.actions if a.phase == AutomationPhase.PRECONDITION
                   and a.action_type != AutomationActionType.SELECT_DEVICE]
    controller_restore = any(a.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER for a in plan.actions)
    if controller_restore:
        restores = [a for a in plan.actions if a.phase == AutomationPhase.RESTORE]
        if (test_case.restoration is None or not test_case.restore_required
                or len(restores) != 1 or restores[0].action_type != AutomationActionType.RESTORE_OBSERVED_CONTROLLER
                or restores[0].selector != '.btn-apply-cmd' or restores[0].value is not None):
            errors.append('공통 관제점 복원은 구조화 복원 조작 하나에 연결해야 합니다')
        allowed = {AutomationActionType.SELECT_DEVICE, AutomationActionType.SET_MODE,
                   AutomationActionType.SET_TEMPERATURE, AutomationActionType.APPLY_COMMANDS}
        for a in (a for a in plan.actions if a.phase != AutomationPhase.RESTORE):
            if a.action_type not in allowed and not (a.action_type == AutomationActionType.CLICK and a.selector in _CONTROLLER_WRITE_SELECTORS):
                errors.append('공통 복원 지원 밖 조작: ' + a.selector)
        if not plan.actions or plan.actions[0].action_type != AutomationActionType.SELECT_DEVICE:
            errors.append('공통 관제점 시험은 변경 전에 대상 장비를 선택해야 합니다')
        if any(c.basis != RestoreComparisonBasis.OBSERVED_BASELINE for r in plan.restore_confirmations for c in r.comparisons):
            errors.append('공통 관제점 복원은 준비 전 관찰값과 비교해야 합니다')
    if preparation:
        # Reuse the bounded HVAC inverse, not arbitrary DOM/state rollback.
        reversible = {AutomationActionType.SELECT_DEVICE, AutomationActionType.SET_MODE,
                      AutomationActionType.SET_TEMPERATURE, AutomationActionType.APPLY_COMMANDS}
        restores = [a for a in plan.actions if a.phase == AutomationPhase.RESTORE]
        if not controller_restore and (not test_case.test_data.restore_observed_hvac_state
                or len(restores) != 1
                or restores[0].action_type != AutomationActionType.RESTORE_OBSERVED_HVAC
                or any(a.action_type not in reversible for a in plan.actions if a.phase != AutomationPhase.RESTORE)):
            errors.append("준비 상태 변경은 원래 모드·온도의 관찰 복원이 연결된 HVAC 동작만 지원합니다")
        first_write = next(i for i, a in enumerate(plan.actions) if a in preparation)
        if not any(a.action_type == AutomationActionType.SELECT_DEVICE for a in plan.actions[:first_write]):
            errors.append("준비 값을 변경하기 전에 대상 장비를 선택해야 합니다")
        if any(comparison.basis == RestoreComparisonBasis.PROVED_INITIAL
               for item in plan.restore_confirmations for comparison in item.comparisons):
            errors.append("준비 후 초기값과 준비 전 원래 상태는 다릅니다. 복원 확인은 OBSERVED_BASELINE을 사용하세요")
    if read_only:
        if any(a.action_type != AutomationActionType.SELECT_DEVICE or a.phase == AutomationPhase.RESTORE for a in plan.actions):
            errors.append("조회 TC에 상태 변경 가능 동작 또는 복원 동작이 있습니다")
    elif not any(a.phase == AutomationPhase.RESTORE for a in plan.actions):
        errors.append("변경·차단 TC의 비상 복원 동작 누락")
    elif not any(a.observation_layer != ObservationLayer.NOTIFICATION and
                 _restoration_read_expression(a, plan.target_device_id) for a in plan.assertions):
        errors.append("복원 비교가 가능한 변경 대상 관찰값이 없습니다")
    if test_case.state_effect == TcStateEffect.BLOCKED_CHANGE and not any(
        a.observation_layer != ObservationLayer.NOTIFICATION and _restoration_read_expression(a, plan.target_device_id)
        and a.strategy not in {AssertionStrategy.CONTROLS_DISABLED, AssertionStrategy.UI_ENABLED_EQUALS,
                               AssertionStrategy.DISABLED_TEMPERATURE_TEXT}
        for a in plan.assertions
    ):
        errors.append("버튼 비활성·안내 표시만으로 요구된 차단 결과의 대상 상태를 증명할 수 없습니다")
    return errors


def _py_literal(value: Any) -> str:
    return repr(value)

def _safe_comment(value: str) -> str:
    return " ".join(value.replace("\r", " ").replace("\n", " ").split())



_TYPED_VALUE_COMPARISON_HELPER = '''
def _qa_values_equal(actual, expected):
    # JSON numbers may be int/float; booleans are not numbers in this contract.
    if type(actual) in (int, float) and type(expected) in (int, float):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(_qa_values_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(_qa_values_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected

'''


def compile_automation_candidate(
    run_id: str,
    test_case: ProductTestCaseCandidate,
    plan: Agent3AutomationPlan,
    *,
    explicit_expectations_only: bool = False,
    typed_values: bool = False,
) -> str:
    """Compile a constrained plan; historical callers retain their verdict policy."""
    def different(actual: str, expected: str) -> str:
        return f"not _qa_values_equal({actual}, {expected})" if typed_values else f"{actual} != {expected}"
    handoff_errors = tc_plan_handoff_errors(test_case, plan)
    if handoff_errors:
        raise Agent3Error("TC 실행 정의 인계 오류: " + " / ".join(handoff_errors))
    policy_errors = _state_restoration_plan_errors(test_case, plan)
    if policy_errors:
        raise Agent3Error("상태 복원 정책: " + " / ".join(policy_errors))
    state_policy = test_case.state_effect is not None
    if plan.restore_confirmations or test_case.restoration is not None:
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
    def assertion_temperature(assertion):
        if assertion.strategy in {AssertionStrategy.UI_TEMPERATURE, AssertionStrategy.INTERNAL_SET_TEMP}:
            return assertion.expected_number
        if assertion.strategy in {AssertionStrategy.INTERNAL_DEVICE_FIELDS_EQUALS, AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS}:
            return next((f.expected_value for f in assertion.expected_fields if f.field_name == 'setTemp'), None)
        return None
    asserted_temperatures = {
        float(value)
        for assertion in plan.assertions
        if (value := assertion_temperature(assertion)) is not None
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
        # Follow this input to its first apply, never into the next temperature
        # request. Detailed TC steps may separate input and apply prose.
        anchors = {action.action_id}
        action_index = next(i for i, item in enumerate(plan.actions) if item.action_id == action.action_id)
        for following in plan.actions[action_index + 1:]:
            if following.phase != AutomationPhase.TEST or following.action_type == AutomationActionType.SET_TEMPERATURE:
                break
            if (following.action_type == AutomationActionType.APPLY_COMMANDS
                    or (following.action_type == AutomationActionType.CLICK and following.selector == ".btn-apply-cmd")):
                anchors.add(following.action_id)
                break
        linked_expected_numbers = {
            float(value)
            for assertion in plan.assertions
            if (value := assertion_temperature(assertion)) is not None
            and assertion.result_id in expected_results_by_id
            and assertion.after_action_id in anchors
        }
        if linked_expected_numbers:
            return float(action.value) not in linked_expected_numbers
        # Unanchored historical single-flow plans used end-of-test assertions.
        # Never borrow another segment's value in an explicitly anchored plan.
        return blocked_request if all(a.after_action_id is None for a in plan.assertions) else False
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
    uses_controller_restore = any(a.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER for a in plan.actions)
    uses_controller_helpers = (uses_controller_restore or any(a.strategy == AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS for a in plan.assertions)
        or any(c.read_kind == PreconditionReadKind.CONTROLLER_UI_FIELD for c in plan.precondition_checks))
    needs_legacy_temperature_helpers = (
        uses_legacy_temperature_action
        or uses_dynamic_hvac_restore
        or uses_controller_helpers
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
    if state_policy and restore_actions:
        restore_assertions = [a for a in plan.assertions if a.observation_layer != ObservationLayer.NOTIFICATION
                              and _restoration_read_expression(a, plan.target_device_id)]
    lines = [
        "from __future__ import annotations",
        "",
        "import os",
        "import json",
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
    if typed_values:
        lines.extend(_TYPED_VALUE_COMPARISON_HELPER.splitlines())
    if needs_legacy_temperature_helpers:
        lines.extend(
            [
                "def _displayed_temperature(page, selector):",
                "    text = page.locator(selector).inner_text()",
                "    match = re.search(r'-?\\d+(?:\\.\\d+)?', text)",
                "    return float(match.group(0)) if match else None",
                "",
                "def _temperature(page):",
                f"    return _displayed_temperature(page, {_TEMPERATURE_CONTROLS['display']!r})",
                "",
                "def _adjust_temperature(page, target, *, allow_blocked):",
                "    seen = set()",
                "    for _ in range(40):",
                "        before = _temperature(page)",
                "        if before == target:",
                "            return",
                "        if before is None:",
                "            raise RuntimeError(f'temperature adjustment stopped: unreadable display, target={target}')",
                "        if before in seen:",
                "            raise RuntimeError(f'temperature adjustment stopped: repeated display, target={target}, actual={before}')",
                "        seen.add(before)",
                f"        selector = {_TEMPERATURE_CONTROLS['increase']!r} if before < target else {_TEMPERATURE_CONTROLS['decrease']!r}",
                "        page.locator(selector).click()",
                "        after = _temperature(page)",
                "        if after == target:",
                "            return",
                "        if after == before:",
                "            if allow_blocked:",
                "                return",
                "            raise RuntimeError(f'temperature adjustment stopped: no progress, target={target}, actual={after}')",
                "    raise RuntimeError(f'temperature adjustment stopped: attempt limit, target={target}, actual={_temperature(page)}')",
                "",
                "def _set_temperature(page, target):",
                "    _adjust_temperature(page, target, allow_blocked=False)",
                "",
                "def _request_temperature(page, target):",
                "    _adjust_temperature(page, target, allow_blocked=True)",
                "",
            ]
        )
    if uses_controller_helpers:
        lines.append(f'_CONTROLLER_BUTTONS = {_py_literal(_CONTROLLER_BUTTONS)}')
        restore_helpers = _CONTROLLER_RESTORE_HELPERS
        if typed_values:
            restore_helpers = restore_helpers.replace("if current == target:", "if _qa_values_equal(current, target):")
        lines.extend(restore_helpers.splitlines())
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
    if state_policy:
        # This declaration must precede page loading so cleanup is safe even if
        # navigation/precondition checks fail before any product action.
        marker = lines.index("        try:")
        lines[marker:marker] = ["        state_change_started = False", "        preparation_started = False",
                               "        test_state_started = False"] + (
                                   [] if explicit_expectations_only else ["        unexpected_state_change = False"])
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
        if state_policy:
            lines.append(f"{indent}{variable} = {_restoration_read_expression(assertion, plan.target_device_id)}")
        elif assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
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
    if uses_controller_restore:
        baseline_block.insert(0, f'{indent}controller_original = _controller_baseline(page, {plan.target_device_id})')
    if state_policy:
        # UI observations belong to the selected target, not the panel shown
        # before SELECT_DEVICE. Capture once, before the first write.
        del lines[baseline_start:]
    if state_policy and restore_actions:
        lines.extend([f"{indent}def observe_restoration():", f"{indent}    changes = []"])
        for variable, assertion in restore_baselines:
            lines.extend([
                f"{indent}    actual = {_restoration_read_expression(assertion, plan.target_device_id)}",
                f"{indent}    if {different('actual', 'prepared_' + variable)}:",
                f"{indent}        changes.append({_py_literal(assertion.result_id)} + ' state differs from pre-test observation')",
            ])
        if uses_dynamic_hvac_restore:
            lines.extend([
                f"{indent}    actual_hvac = page.evaluate(\"id => {{ const d = window.__vccs.devices.find(d => d.id === id); return d ? {{mode: d.mode, setTemp: d.setTemp}} : null; }}\", {plan.target_device_id})",
                f"{indent}    if {different('actual_hvac', 'prepared_hvac_baseline')}:",
                f"{indent}        changes.append('HVAC state differs from prepared observation')",
            ])
        if uses_controller_restore:
            lines.extend([
                f'{indent}    actual_controller = _controller_snapshot(page, {plan.target_device_id})',
                f"""{indent}    if {different("actual_controller['state']", "controller_prepared['state']")} or any({different("actual_controller['ui'][k]", "controller_prepared['ui'][k]")} for k in ('card_classes', 'card_values', 'card_locked')):""",
                f"{indent}        changes.append('controller applied state differs from prepared observation')",
            ])
        lines.append(f"{indent}    return changes")
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
            if (explicit_expectations_only and action.phase == AutomationPhase.TEST) or is_blocked_temperature_action(action):
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
        lines.append(f"{indent}mismatch_count_before = len(mismatches)")
        if assertion.strategy == AssertionStrategy.CONTROLLER_UI_FIELDS_EQUALS:
            expected = {f.field_name: f.expected_value for f in assertion.expected_fields}
            lines.extend([
                f'{indent}actual = {_restoration_read_expression(assertion, plan.target_device_id)}',
                f'{indent}if {different("actual", repr(expected))}:',
                f"{indent}    mismatches.append({assertion.result_id!r} + ': controller UI=' + repr(actual))",
            ])
        elif assertion.strategy == AssertionStrategy.UI_TEMPERATURE:
            lines.extend(
                [
                    f"{indent}actual = _displayed_temperature(page, '#det-temp-display')",
                    f"{indent}if {different('actual', repr(float(assertion.expected_number)))}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': UI temperature={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_SET_TEMP:
            lines.extend(
                [
                    f"{indent}actual = page.evaluate(\"id => window.__vccs.devices.find(d => d.id === id).setTemp\", {plan.target_device_id})",
                    f"{indent}if {different('actual', repr(float(assertion.expected_number)))}:",
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
                    f"{indent}if {different('actual', _py_literal(expected_fields))}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': internal device fields={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.TOAST_BLOCKING:
            lines.extend(
                [
                    f"{indent}toast = page.locator('#global-toast')",
                    f"{indent}toast_text = toast.inner_text().strip().lower()",
                    f"{indent}actual = {{'visible': 'show' in (toast.get_attribute('class') or '').split(), 'text': toast_text}}",
                    f"{indent}if not actual['visible']:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': toast not visible')",
                    f"{indent}elif not any(term in toast_text for term in {_py_literal(_BLOCKING_TOAST_ACTUAL_TERMS)}):",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': toast does not indicate blocking: {{toast_text}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.TOAST_VISIBLE:
            lines.extend(
                [
                    f"{indent}toast = page.locator('#global-toast')",
                    f"{indent}actual = 'show' in (toast.get_attribute('class') or '').split()",
                    f"{indent}if not actual:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': toast not visible')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.CONTROLS_DISABLED:
            lines.extend(
                [
                    f"{indent}actual = [page.locator({_TEMPERATURE_CONTROLS['decrease']!r}).is_enabled(), page.locator({_TEMPERATURE_CONTROLS['increase']!r}).is_enabled()]",
                    f"{indent}if any(actual):",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + ': temperature controls enabled')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.DISABLED_TEMPERATURE_TEXT:
            lines.extend(
                [
                    f"{indent}actual = page.locator('#det-temp-display').inner_text()",
                    f"{indent}if {_DISABLED_TEMPERATURE_TEXT!r} not in actual:",
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
                    f"{indent}if {different('actual', 'str(' + _py_literal(assertion.expected_value) + ')')}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': UI value={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.UI_CHECKED_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.locator({_py_literal(assertion.selector)}).is_checked()",
                    f"{indent}if {different('actual', _py_literal(assertion.expected_value))}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': checked={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.UI_ENABLED_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.locator({_py_literal(assertion.selector)}).is_enabled()",
                    f"{indent}if {different('actual', _py_literal(assertion.expected_value))}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': enabled={{actual}}')",
                ]
            )
        elif assertion.strategy == AssertionStrategy.INTERNAL_VALUE_EQUALS:
            lines.extend(
                [
                    f"{indent}actual = page.evaluate({_py_literal('() => ' + assertion.selector)})",
                    f"{indent}if {different('actual', _py_literal(assertion.expected_value))}:",
                    f"{indent}    mismatches.append({_py_literal(assertion.result_id)} + f': internal value={{actual}}')",
                ]
            )
        observation = dict(version="assertion-observations-1.0", run_id=run_id, tc_id=test_case.tc_id,
                           target_device_id=plan.target_device_id, assertion=assertion.model_dump(mode="json"))
        lines.extend([
            f"{indent}observation = {observation!r}",
            f"{indent}observation.update(actual=actual, matched=len(mismatches) == mismatch_count_before)",
            f"{indent}observations[{assertion.result_id!r}] = observation",
        ])
        assertion_blocks.append((assertion.after_action_id, lines[block_start:]))
        del lines[block_start:]

    def append_observation_group(blocks: list[list[str]], prefix: str, errors: str) -> None:
        if not blocks:
            return
        lines.append(f"{prefix}observations = {{}}")
        lines.append(f"{prefix}def observe():")
        lines.append(f"{prefix}    observations.clear()")
        lines.append(f"{prefix}    {errors} = []")
        for block in blocks:
            lines.extend("    " + line for line in block)
        lines.append(f"{prefix}    return {errors}")
        lines.extend([
            f"{prefix}try:",
            f"{prefix}    {errors}.extend(_wait_for_observations(page, observe))",
            f"{prefix}finally:",
            f"{prefix}    for observation in observations.values():",
            f"{prefix}        print('QA_ASSERTION_OBSERVED: ' + json.dumps(observation, ensure_ascii=True, allow_nan=False))",
        ])

    prepared_baseline_captured = False
    original_baseline_captured = False
    def append_precondition_checks():
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

    phases_by_id = {action.action_id: action.phase for action in plan.actions}
    has_preparation = any(action.phase == AutomationPhase.PRECONDITION for action in plan.actions)
    preconditions_checked = False
    for action_id, block in action_blocks:
        action = next(a for a in plan.actions if a.action_id == action_id)
        if state_policy and not original_baseline_captured and action.action_type != AutomationActionType.SELECT_DEVICE:
            lines.extend(baseline_block)
            lines.extend(f"{indent}prepared_{variable} = {variable}" for variable, _ in restore_baselines)
            if uses_dynamic_hvac_restore:
                lines.append(f"{indent}prepared_hvac_baseline = observed_hvac_baseline")
            if uses_controller_restore:
                lines.append(f'{indent}controller_prepared = controller_original')
            original_baseline_captured = True
        if has_preparation and not prepared_baseline_captured and phases_by_id[action_id] == AutomationPhase.TEST:
            # Capture the prepared state even when its verification fails.
            if state_policy:
                lines.extend(f"{indent}prepared_{variable} = {_restoration_read_expression(assertion, plan.target_device_id)}"
                             for variable, assertion in restore_baselines)
                if uses_dynamic_hvac_restore:
                    lines.append(f"{indent}prepared_hvac_baseline = page.evaluate(\"id => {{ const d = window.__vccs.devices.find(d => d.id === id); return d ? {{mode: d.mode, setTemp: d.setTemp}} : null; }}\", {plan.target_device_id})")
                if uses_controller_restore:
                    lines.append(f'{indent}controller_prepared = _controller_snapshot(page, {plan.target_device_id})')
                    lines.append(f"{indent}print('CONTROLLER_PREPARED: ' + repr(controller_prepared))")
            else:
                lines.extend(baseline_block)
            prepared_baseline_captured = True
        if not preconditions_checked and phases_by_id[action_id] == AutomationPhase.TEST and plan.precondition_checks:
            append_precondition_checks()
            preconditions_checked = True
        if state_policy and action.action_type != AutomationActionType.SELECT_DEVICE:
            lines.append(f"{indent}state_change_started = True")
            flag = "preparation_started" if action.phase == AutomationPhase.PRECONDITION else "test_state_started"
            lines.append(f"{indent}{flag} = True")
        lines.extend(block)
        append_observation_group(
            [block for after, block in assertion_blocks if after == action_id], indent, "mismatches"
        )
    if state_policy and not preconditions_checked and plan.precondition_checks:
        append_precondition_checks()
    append_observation_group(
        [block for after, block in assertion_blocks if after is None], indent, "mismatches"
    )

    lines.extend(
        [
            f"{indent}page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)",
            f"{indent}print('QA_ASSERTIONS_COMPLETE: ' + json.dumps({dict(version='assertion-observations-1.0', run_id=run_id, tc_id=test_case.tc_id)!r}))",
            f"{indent}assert not mismatches, 'PRODUCT_MISMATCH: ' + ' | '.join(mismatches)",
            f"{indent}test_completed = True",
            "        except Exception:",
            "            try:",
            "                if not (EVIDENCE_DIR / 'trial-final.png').exists():",
            "                    page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)",
            "            except Exception:",
            "                print('EVIDENCE_CAPTURE_FAILED: failure screenshot unavailable')",
            "            raise",
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
    restore_action_start = len(lines)
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
        elif action.action_type == AutomationActionType.RESTORE_OBSERVED_CONTROLLER:
            lines.append(f'                _restore_controller(page, {plan.target_device_id}, controller_original)')
        elif action.action_type == AutomationActionType.RESTORE_OBSERVED_HVAC:
            lines.extend(
                [
                    f"                observed_mode_selector = {_py_literal(_MODE_SELECTOR)}[observed_hvac_baseline['mode']]",
                    "                page.locator(observed_mode_selector).click()",
                    "                _set_temperature(page, float(observed_hvac_baseline['setTemp']))",
                    f"                page.locator({_py_literal(action.selector)}).click()",
                ]
            )
            if state_policy:
                # FAN/DRY hide the temperature control. Restore temperature in
                # a writable mode, then the original mode, before applying.
                lines[-4:] = [
                    f"                observed_mode_selector = {_py_literal(_MODE_SELECTOR)}[observed_hvac_baseline['mode']]",
                    f"                writable_mode_selector = {_py_literal(_MODE_SELECTOR['COOL'])} if observed_hvac_baseline['mode'] in ('FAN', 'DRY') else observed_mode_selector",
                    "                page.locator(writable_mode_selector).click()",
                    "                _set_temperature(page, float(observed_hvac_baseline['setTemp']))",
                    "                if observed_hvac_baseline['mode'] in ('FAN', 'DRY'):",
                    f"                    page.locator({_py_literal(action.selector)}).click()",
                    "                page.locator(observed_mode_selector).click()",
                    f"                page.locator({_py_literal(action.selector)}).click()",
                ]
        else:
            lines.append(
                f"                _set_temperature(page, {float(action.value)})"
            )
    restore_observation_start = len(lines)
    if uses_controller_restore:
        lines.extend([
            f'                restored_controller = _controller_snapshot(page, {plan.target_device_id})',
            f'                if {different("restored_controller", "controller_original")}:',
            "                    restore_mismatches.append('controller original=' + repr(controller_original) + ', actual=' + repr(restored_controller))",
        ])
    for action in restore_actions:
        if action.action_type in {
            AutomationActionType.FILL,
            AutomationActionType.SELECT_OPTION,
        }:
            lines.extend(
                [
                    f"                restore_control_value = page.locator({_py_literal(action.selector)}).input_value()",
                    f"                if {different('restore_control_value', 'str(' + _py_literal(action.value) + ')')}:",
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
                    f"                if {different('restore_control_checked', _py_literal(expected_checked))}:",
                    f"                    restore_mismatches.append({_py_literal(action.selector)} + f' checked={{restore_control_checked}}')",
                ]
            )
    for variable, assertion in restore_baselines:
        if state_policy:
            actual = _restoration_read_expression(assertion, plan.target_device_id)
        elif assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
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
                f"                if {different('restore_actual', variable)}:",
                f"                    restore_mismatches.append({_py_literal(assertion.selector)} + f' baseline={{{variable}}}, actual={{restore_actual}}')",
            ]
        )
    if (
        restore_actions
        and uses_legacy_temperature_action
        and test_case.test_data.initial_temperature_c is not None
        and not (state_policy and (uses_dynamic_hvac_restore or uses_controller_restore))
    ):
        initial_temperature = float(test_case.test_data.initial_temperature_c)
        lines.extend(
            [
                "                restore_ui_temperature = _temperature(page)",
                f"                if {different('restore_ui_temperature', repr(initial_temperature))}:",
                "                    restore_mismatches.append(f'UI temperature={restore_ui_temperature}')",
                f"                restore_internal_temperature = page.evaluate(\"id => window.__vccs.devices.find(d => d.id === id).setTemp\", {plan.target_device_id})",
                f"                if {different('restore_internal_temperature', repr(initial_temperature))}:",
                "                    restore_mismatches.append(f'internal setTemp={restore_internal_temperature}')",
            ]
        )
    if restore_actions and uses_dynamic_hvac_restore:
        lines.extend(
            [
                f"                restored_hvac_state = page.evaluate(\"id => {{ const device = window.__vccs.devices.find(d => d.id === id); return device ? {{mode: device.mode, setTemp: device.setTemp}} : null; }}\", {plan.target_device_id})",
                f"                if {different('restored_hvac_state', 'observed_hvac_baseline')}:",
                "                    restore_mismatches.append(f'internal HVAC baseline={observed_hvac_baseline}, actual={restored_hvac_state}')",
            ]
        )
    if restore_actions:
        restore_block = lines[restore_observation_start:]
        del lines[restore_observation_start:]
        append_observation_group([restore_block], "                ", "restore_mismatches")
        if state_policy:
            # Snapshot differences determine cleanup, not product expectations.
            # Historical candidates retain their implicit blocked-state verdict.
            body = lines[restore_action_start:]
            action_count = restore_observation_start - restore_action_start
            action_body, verification_body = body[:action_count], body[action_count:]
            del lines[restore_action_start:]
            lines.extend([
                "                if state_change_started:",
                "                    changes = observe_restoration() if test_state_started else []",
            ])
            if test_case.state_effect == TcStateEffect.BLOCKED_CHANGE:
                if not explicit_expectations_only:
                    lines.extend([
                        "                    if test_state_started and changes:",
                        "                        unexpected_state_change = True",
                        "                        print('PRODUCT_MISMATCH: blocked operation changed observed state: ' + ' | '.join(changes))",
                    ])
                lines.append("                    if preparation_started or changes:")
            action_indent = "        " if test_case.state_effect == TcStateEffect.BLOCKED_CHANGE else "    "
            lines.extend(action_indent + line for line in action_body)
            if uses_controller_restore and test_case.state_effect == TcStateEffect.BLOCKED_CHANGE:
                lines.extend([
                    '                    else:',
                    f"                        page.locator('#device-card-{plan.target_device_id} .card-body-split').click()",
                ])
            lines.extend("    " + line for line in verification_body)
            lines.extend([
                "                    print('RESTORE_STATUS: ' + ('FAILED' if restore_mismatches else ('RESTORED' if preparation_started or changes else 'UNCHANGED')))"
                if test_case.state_effect == TcStateEffect.BLOCKED_CHANGE else
                "                    print('RESTORE_STATUS: ' + ('FAILED' if restore_mismatches else 'RESTORED'))",
                "                else:",
                "                    print('RESTORE_STATUS: NOT_STARTED')",
            ])
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
        if state_policy:
            failure_marker = lines.index("                print(restore_message)") + 1
            lines[failure_marker:failure_marker] = [
                "                print('RESTORE_STATUS: FAILED')",
                "                print('ENVIRONMENT_RETIRED: restoration failed; browser context closed')",
            ]
            if not explicit_expectations_only:
                lines.extend([
                    "            if unexpected_state_change and test_completed:",
                    "                raise AssertionError('PRODUCT_MISMATCH: blocked operation changed observed state')",
                ])
    else:
        lines.extend(
            [
                "            context.tracing.stop(path=str(EVIDENCE_DIR / 'trial-trace.zip'))",
                "            context.close()",
                "            browser.close()",
                "",
            ]
        )
        if state_policy:
            lines.append("            print('RESTORE_STATUS: NOT_REQUIRED')")
    if restore_actions and plan.restore_confirmations:
        lines.extend([
            "            if not restore_mismatches and test_completed:",
            "                print('RESTORE_CONFIRMATIONS_VERIFIED: ' + "
            + _py_literal(",".join(sorted({result_id for item in plan.restore_confirmations for result_id in item.result_ids}))) + ")",
            "",
        ])
    if state_policy:
        close_index = next(i for i, line in enumerate(lines) if "context.tracing.stop(" in line)
        close_lines = lines[close_index:close_index + 3]
        prefix = close_lines[0][:len(close_lines[0]) - len(close_lines[0].lstrip())]
        lines[close_index:close_index + 3] = [
            prefix + "try:", "    " + close_lines[0], prefix + "finally:",
            prefix + "    try:", "        " + close_lines[1],
            prefix + "    finally:", "        " + close_lines[2],
        ]
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
            if any(module not in {"__future__", "os", "json", "re", "pathlib", "playwright", "time"} for module in modules):
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
