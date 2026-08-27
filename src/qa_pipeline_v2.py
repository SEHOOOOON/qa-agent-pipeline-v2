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

__version__ = "0.3.0"

# ---------------------------------------------------------------------------
# 데이터 계약
# ---------------------------------------------------------------------------
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
RequirementId = Annotated[str, StringConstraints(pattern=r"^REQ-[A-Z]+-\d{3}$")]


class StrictModel(BaseModel):
    # 저장 산출물은 한글 표시명을 쓰되, 이전 Run의 영문 키도 계속 읽습니다.
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ChangeType(str, Enum):
    MODIFIED = "MODIFIED"


class AnalysisDecision(str, Enum):
    PROCEED = "PROCEED"
    PARTIAL_PROCEED = "PARTIAL_PROCEED"
    WAITING_FOR_USER = "WAITING_FOR_USER"
    BLOCKED = "BLOCKED"


class CheckStatus(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    ERROR = "ERROR"


class HandoffStatus(str, Enum):
    CONTINUE = "CONTINUE"
    PAUSE = "PAUSE"
    BLOCKED = "BLOCKED"


class ConditionSource(str, Enum):
    CHANGE_REQUEST = "CHANGE_REQUEST"
    SRS = "SRS"


class RequirementRelation(str, Enum):
    MODIFIED = "MODIFIED"
    UPDATE_REQUIRED = "UPDATE_REQUIRED"
    VERIFY = "VERIFY"
    NO_IMPACT = "NO_IMPACT"


class ChangeRequest(StrictModel):
    request_id: NonEmptyStr
    change_type: ChangeType = ChangeType.MODIFIED
    target_requirement_id: RequirementId
    before_value: NonEmptyStr
    after_value: NonEmptyStr
    description: NonEmptyStr
    reason: NonEmptyStr | None = None
    acceptance_notes: list[NonEmptyStr] = Field(default_factory=list)
    out_of_scope: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def before_and_after_must_differ(self) -> "ChangeRequest":
        if self.before_value.casefold() == self.after_value.casefold():
            raise ValueError("before_value와 after_value는 달라야 합니다.")
        return self


class SrsRequirement(StrictModel):
    requirement_id: RequirementId
    statement: NonEmptyStr
    acceptance_criteria: NonEmptyStr
    related_requirement_ids: list[RequirementId] = Field(default_factory=list)


class ConfirmedCondition(StrictModel):
    condition_id: Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    statement: NonEmptyStr
    source_type: ConditionSource
    source_text: NonEmptyStr
    requirement_ids: list[RequirementId] = Field(min_length=1)


class RequirementEffect(StrictModel):
    requirement_id: RequirementId
    relation: RequirementRelation
    reason: NonEmptyStr


class Agent1Analysis(StrictModel):
    request_id: NonEmptyStr
    change_type: ChangeType
    target_requirement_id: RequirementId
    change_summary: NonEmptyStr
    before_condition: NonEmptyStr
    after_condition: NonEmptyStr
    confirmed_conditions: list[ConfirmedCondition] = Field(min_length=1)
    requirement_effects: list[RequirementEffect] = Field(min_length=1)
    excluded_scope: list[NonEmptyStr] = Field(default_factory=list)
    information_gaps: list[NonEmptyStr] = Field(default_factory=list)
    excluded_information_gaps: list[NonEmptyStr] = Field(
        default_factory=list, alias="제외된_정보_부족"
    )
    user_questions: list[NonEmptyStr] = Field(default_factory=list)
    decision: AnalysisDecision


class CheckResult(StrictModel):
    rule_id: NonEmptyStr
    status: CheckStatus
    message: NonEmptyStr


class Checkpoint1Result(StrictModel):
    checkpoint: str = "CP1"
    status: CheckStatus
    handoff_status: HandoffStatus
    checks: list[CheckResult] = Field(min_length=1)
    final_review_notes: list[NonEmptyStr] = Field(
        default_factory=list, alias="최종_확인_사항"
    )



class TcPurpose(str, Enum):
    CHANGE_VALIDATION = "CHANGE_VALIDATION"
    RELATED_REGRESSION = "RELATED_REGRESSION"


class TcType(str, Enum):
    NORMAL = "NORMAL"
    BOUNDARY = "BOUNDARY"
    EXCEPTION = "EXCEPTION"
    STATE_CONSISTENCY = "STATE_CONSISTENCY"


class CommonQaCriterion(str, Enum):
    NORMAL_FLOW = "NORMAL_FLOW"
    EXCEPTION_HANDLING = "EXCEPTION_HANDLING"
    BOUNDARY_VALUE = "BOUNDARY_VALUE"
    RECOVERY_AND_RESET = "RECOVERY_AND_RESET"
    ACCESS_CONTROL = "ACCESS_CONTROL"
    USER_FEEDBACK = "USER_FEEDBACK"


class DomainQaCriterion(str, Enum):
    TARGET_DEVICE_ACCURACY = "TARGET_DEVICE_ACCURACY"
    MULTI_DEVICE_CONTROL = "MULTI_DEVICE_CONTROL"
    NON_TARGET_STATE_PRESERVATION = "NON_TARGET_STATE_PRESERVATION"
    UI_INTERNAL_STATE_CONSISTENCY = "UI_INTERNAL_STATE_CONSISTENCY"
    PARTIAL_FAILURE_ISOLATION = "PARTIAL_FAILURE_ISOLATION"


class DoubleAssertPolicy(str, Enum):
    REQUIRED = "REQUIRED"
    UI_ONLY = "UI_ONLY"
    INTERNAL_ONLY = "INTERNAL_ONLY"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ObservationLayer(str, Enum):
    UI = "UI"
    INTERNAL_STATE = "INTERNAL_STATE"
    NOTIFICATION = "NOTIFICATION"


class ControlPath(str, Enum):
    CENTRAL = "CENTRAL"
    LOCAL = "LOCAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class ConditionExecution(str, Enum):
    """How related conditions inside one product TC are executed."""

    SINGLE_FLOW = "SINGLE_FLOW"
    INDEPENDENT_VARIANTS = "INDEPENDENT_VARIANTS"
    SEQUENTIAL_TRANSITION = "SEQUENTIAL_TRANSITION"


class TestData(StrictModel):
    initial_mode: NonEmptyStr | None = None
    requested_mode: NonEmptyStr | None = None
    requested_modes: list[NonEmptyStr] = Field(default_factory=list)
    initial_temperature_c: float | None = None
    requested_temperature_c: float | None = None
    requested_temperatures_c: list[float] = Field(default_factory=list)
    restore_observed_hvac_state: bool = False


class ExpectedResult(StrictModel):
    result_id: Annotated[str, StringConstraints(pattern=r"^ER-\d{3}$")]
    statement: NonEmptyStr
    observation_layer: ObservationLayer
    source_condition_ids: list[
        Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    ] = Field(min_length=1)
    verify_after_step: NonEmptyStr | None = None


class ProductTestCaseCandidate(StrictModel):
    tc_id: Annotated[str, StringConstraints(pattern=r"^TC-CAND-\d{3}$")]
    title: NonEmptyStr
    purpose: TcPurpose
    test_type: TcType
    requirement_ids: list[RequirementId] = Field(min_length=1)
    source_condition_ids: list[
        Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    ] = Field(min_length=1)
    control_path: ControlPath
    target_role: NonEmptyStr
    test_data: TestData
    condition_execution: ConditionExecution = ConditionExecution.SINGLE_FLOW
    grouping_reason: NonEmptyStr | None = None
    intermediate_reset_steps: list[NonEmptyStr] = Field(default_factory=list)
    preconditions: list[NonEmptyStr] = Field(min_length=1)
    steps: list[NonEmptyStr] = Field(min_length=1)
    expected_results: list[ExpectedResult] = Field(min_length=1)
    common_qa_criteria: list[CommonQaCriterion] = Field(default_factory=list)
    domain_qa_criteria: list[DomainQaCriterion] = Field(default_factory=list)
    feature_requirement_ids: list[RequirementId] = Field(default_factory=list)
    independent_execution: bool = False
    independence_reason: NonEmptyStr | None = None
    double_assert_policy: DoubleAssertPolicy = DoubleAssertPolicy.NOT_APPLICABLE
    double_assert_reason: NonEmptyStr | None = None
    restore_required: bool
    restore_steps: list[NonEmptyStr] = Field(default_factory=list)
    automation_candidate: bool
    automation_reason: NonEmptyStr

    @model_validator(mode="after")
    def restore_contract_must_be_consistent(self) -> "ProductTestCaseCandidate":
        if self.restore_required and not self.restore_steps:
            raise ValueError("restore_required가 true이면 restore_steps가 필요합니다.")
        if not self.restore_required and self.restore_steps:
            raise ValueError("restore_required가 false이면 restore_steps는 비워야 합니다.")
        return self


class ExistingTestSelection(StrictModel):
    """Existing human-authored TC selected for impacted regression, not regeneration."""

    tc_id: Annotated[str, StringConstraints(pattern=r"^TC-[A-Z]+-\d{3}$")]
    source_condition_ids: list[
        Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    ] = Field(min_length=1)
    selection_reason: NonEmptyStr


def _tc_requested_modes(test_case: ProductTestCaseCandidate) -> list[str]:
    values = [
        value
        for value in (
            test_case.test_data.requested_mode,
            *test_case.test_data.requested_modes,
        )
        if value is not None
    ]
    return list(dict.fromkeys(values))


def _tc_temperature_values(test_case: ProductTestCaseCandidate) -> list[float]:
    values = [
        float(value)
        for value in (
            test_case.test_data.initial_temperature_c,
            test_case.test_data.requested_temperature_c,
            *test_case.test_data.requested_temperatures_c,
        )
        if value is not None
    ]
    return list(dict.fromkeys(values))


def _is_grouped_test_case(test_case: ProductTestCaseCandidate) -> bool:
    return test_case.condition_execution != ConditionExecution.SINGLE_FLOW


class Agent2TestDesign(StrictModel):
    request_id: NonEmptyStr
    test_cases: list[ProductTestCaseCandidate] = Field(min_length=1)
    existing_tc_comparison_completed: bool = False
    related_existing_tests: list[ExistingTestSelection] = Field(
        default_factory=list, alias="관련_기존_TC"
    )
    coverage_summary: NonEmptyStr
    coverage_notes: list[NonEmptyStr] = Field(default_factory=list)
    excluded_scope: list[NonEmptyStr] = Field(default_factory=list, alias="제외_범위")
    excluded_information_gaps: list[NonEmptyStr] = Field(
        default_factory=list, alias="제외된_정보_부족"
    )
    final_review_notes: list[NonEmptyStr] = Field(
        default_factory=list, alias="최종_확인_사항"
    )
    human_review_notes: list[NonEmptyStr] = Field(
        default_factory=list, alias="중단_확인_사항"
    )


class Checkpoint2Result(StrictModel):
    checkpoint: str = "CP2"
    status: CheckStatus
    checks: list[CheckResult] = Field(min_length=1)

class AutomationPhase(str, Enum):
    PRECONDITION = "PRECONDITION"
    TEST = "TEST"
    RESTORE = "RESTORE"


class AutomationActionType(str, Enum):
    SELECT_DEVICE = "SELECT_DEVICE"
    SET_MODE = "SET_MODE"
    SET_TEMPERATURE = "SET_TEMPERATURE"
    APPLY_COMMANDS = "APPLY_COMMANDS"
    CLICK = "CLICK"
    FILL = "FILL"
    SELECT_OPTION = "SELECT_OPTION"
    CHECK = "CHECK"
    UNCHECK = "UNCHECK"
    RESTORE_OBSERVED_HVAC = "RESTORE_OBSERVED_HVAC"


class AssertionStrategy(str, Enum):
    UI_TEMPERATURE = "UI_TEMPERATURE"
    INTERNAL_SET_TEMP = "INTERNAL_SET_TEMP"
    INTERNAL_DEVICE_FIELDS_EQUALS = "INTERNAL_DEVICE_FIELDS_EQUALS"
    TOAST_VISIBLE = "TOAST_VISIBLE"
    TOAST_BLOCKING = "TOAST_BLOCKING"
    CONTROLS_DISABLED = "CONTROLS_DISABLED"
    DISABLED_TEMPERATURE_TEXT = "DISABLED_TEMPERATURE_TEXT"
    UI_TEXT_CONTAINS = "UI_TEXT_CONTAINS"
    UI_VALUE_EQUALS = "UI_VALUE_EQUALS"
    UI_CHECKED_EQUALS = "UI_CHECKED_EQUALS"
    UI_ENABLED_EQUALS = "UI_ENABLED_EQUALS"
    INTERNAL_VALUE_EQUALS = "INTERNAL_VALUE_EQUALS"


class AutomationCandidateStatus(str, Enum):
    READY_FOR_EXECUTION = "READY_FOR_EXECUTION"
    PRODUCT_MISMATCH_DETECTED = "PRODUCT_MISMATCH_DETECTED"
    REVISION_REQUIRED = "REVISION_REQUIRED"
    TRIAL_FAILED = "TRIAL_FAILED"
    NOT_AUTOMATABLE = "NOT_AUTOMATABLE"
    AUTOMATION_SUPPORT_EXTENSION_REQUIRED = "AUTOMATION_SUPPORT_EXTENSION_REQUIRED"
    BLOCKED = "BLOCKED"


class Agent3EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    DISCOVERY_REQUIRED = "DISCOVERY_REQUIRED"
    NOT_AUTOMATABLE = "NOT_AUTOMATABLE"


class Agent3EligibilityResult(StrictModel):
    tc_id: Annotated[str, StringConstraints(pattern=r"^TC-CAND-\d{3}$")]
    status: Agent3EligibilityStatus
    candidate_status: AutomationCandidateStatus | None = None
    required_capabilities: list[NonEmptyStr]
    missing_capabilities: list[NonEmptyStr]
    required_selectors: list[NonEmptyStr]
    required_harness_keys: list[NonEmptyStr]
    model_call_allowed: bool
    generic_discovery_required: bool = False
    extension_reasons: list[NonEmptyStr] = Field(default_factory=list)


class TrialOutcome(str, Enum):
    PASS = "PASS"
    PRODUCT_MISMATCH_CANDIDATE = "PRODUCT_MISMATCH_CANDIDATE"
    AUTOMATION_ERROR = "AUTOMATION_ERROR"
    ENVIRONMENT_ERROR = "ENVIRONMENT_ERROR"
    TIMEOUT = "TIMEOUT"


class ObservedUiElement(StrictModel):
    selector: NonEmptyStr
    tag: NonEmptyStr
    text: str = ""
    visible: bool
    enabled: bool
    action_hint: NonEmptyStr
    role: str | None = None
    input_type: str | None = None
    accessible_name: str | None = None
    value: str | None = None
    checked: bool | None = None


class UiObservation(StrictModel):
    target_file: NonEmptyStr
    target_sha256: NonEmptyStr
    page_title: NonEmptyStr
    elements: list[ObservedUiElement] = Field(min_length=1)
    harness_keys: list[NonEmptyStr] = Field(default_factory=list)
    harness_values: dict[NonEmptyStr, str | float | int | bool | None] = Field(
        default_factory=dict
    )
    device_state_fields: list[NonEmptyStr] = Field(default_factory=list)
    verified_execution_context: "VerifiedExecutionContext" = Field(
        default_factory=lambda: VerifiedExecutionContext()
    )
    generic_discovery: bool = False
    observed_at: NonEmptyStr
    observer: str = "python-playwright"


class VerifiedExecutionContext(StrictModel):
    clean_page_loaded: bool = False
    target_device_id: int = 1
    target_device_visible: bool = False
    device_state_available: bool = False
    error_free: bool | None = None
    unlocked: bool | None = None
    evidence: list[NonEmptyStr] = Field(default_factory=list)


class AutomationAction(StrictModel):
    action_id: Annotated[str, StringConstraints(pattern=r"^ACT-\d{3}$")]
    phase: AutomationPhase
    action_type: AutomationActionType
    selector: NonEmptyStr
    value: str | float | int | bool | None = None
    source_text: NonEmptyStr


class DeviceFieldExpectation(StrictModel):
    field_name: NonEmptyStr
    expected_value: str | float | int | bool


class AutomationAssertion(StrictModel):
    result_id: Annotated[str, StringConstraints(pattern=r"^ER-\d{3}$")]
    observation_layer: ObservationLayer
    strategy: AssertionStrategy
    selector: NonEmptyStr
    expected_number: float | None = None
    expected_text: str | None = None
    expected_value: str | float | int | bool | None = None
    expected_fields: list[DeviceFieldExpectation] = Field(
        default_factory=list
    )
    after_action_id: Annotated[str, StringConstraints(pattern=r"^ACT-\d{3}$")] | None = None


class Agent3PlanningStatus(str, Enum):
    READY = "READY"
    AUTOMATION_SUPPORT_EXTENSION_REQUIRED = "AUTOMATION_SUPPORT_EXTENSION_REQUIRED"


class Agent3AutomationPlan(StrictModel):
    tc_id: Annotated[str, StringConstraints(pattern=r"^TC-CAND-\d{3}$")]
    target_device_id: int = Field(ge=1, le=16)
    summary: NonEmptyStr
    planning_status: Agent3PlanningStatus = Agent3PlanningStatus.READY
    actions: list[AutomationAction] = Field(default_factory=list)
    assertions: list[AutomationAssertion] = Field(default_factory=list)
    extension_reasons: list[NonEmptyStr] = Field(default_factory=list)
    technical_notes: list[NonEmptyStr] = Field(default_factory=list)

    @model_validator(mode="after")
    def ready_plan_or_grounded_extension(self) -> "Agent3AutomationPlan":
        if self.planning_status == Agent3PlanningStatus.READY:
            if not self.actions or not self.assertions:
                raise ValueError("READY 자동화 계획에는 동작과 검증 조건이 필요합니다.")
            if self.extension_reasons:
                raise ValueError("READY 자동화 계획에는 지원 범위 확장 사유를 넣지 않습니다.")
        else:
            if self.actions or self.assertions:
                raise ValueError("지원 범위 확장 요청에는 실행 동작이나 검증 조건을 넣지 않습니다.")
            if not self.extension_reasons:
                raise ValueError("지원 범위 확장 요청에는 구체적인 사유가 필요합니다.")
        return self


class Checkpoint3Result(StrictModel):
    checkpoint: str = "CP3"
    status: CheckStatus
    candidate_status: AutomationCandidateStatus
    checks: list[CheckResult] = Field(min_length=1)


class Agent3TrialResult(StrictModel):
    outcome: TrialOutcome
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    stdout_file: NonEmptyStr
    stderr_file: NonEmptyStr
    screenshot_file: str | None = None
    trace_file: str | None = None
    evidence_sha256: dict[NonEmptyStr, NonEmptyStr] = Field(default_factory=dict)
    evidence_complete: bool


class ExecutionSource(str, Enum):
    NEW_AUTOMATION_CANDIDATE = "NEW_AUTOMATION_CANDIDATE"
    ENVIRONMENT_PRECHECK = "ENVIRONMENT_PRECHECK"
    EXISTING_REGRESSION = "EXISTING_REGRESSION"


class NeutralExecutionStatus(str, Enum):
    PASSED = "PASSED"
    ASSERTION_FAILED = "ASSERTION_FAILED"
    EXECUTION_ERROR = "EXECUTION_ERROR"
    TIMEOUT = "TIMEOUT"
    SKIPPED = "SKIPPED"


class ValidationStageStatus(str, Enum):
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"


class Agent4FindingCategory(str, Enum):
    PRODUCT_MISMATCH_CANDIDATE = "PRODUCT_MISMATCH_CANDIDATE"
    AUTOMATION_EXECUTION_ISSUE = "AUTOMATION_EXECUTION_ISSUE"
    ENVIRONMENT_ISSUE = "ENVIRONMENT_ISSUE"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    NOT_EXECUTED = "NOT_EXECUTED"


class FinalRecommendation(str, Enum):
    PASS = "PASS"
    HOLD = "HOLD"
    HUMAN_REVIEW = "HUMAN_REVIEW"


class NeutralExecutionResult(StrictModel):
    test_id: NonEmptyStr
    source: ExecutionSource
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    status: NeutralExecutionStatus
    source_outcome: NonEmptyStr
    exit_code: int | None
    duration_ms: int = Field(ge=0)
    test_file: NonEmptyStr
    test_sha256: NonEmptyStr
    target_sha256: NonEmptyStr
    reused: bool = False
    stdout_file: str | None = None
    stderr_file: str | None = None
    evidence_files: list[NonEmptyStr] = Field(default_factory=list)
    evidence_sha256: dict[str, NonEmptyStr] = Field(default_factory=dict)
    evidence_complete: bool
    exception_type: str | None = None
    raw_message: str | None = None


class ValidationExecutionBundle(StrictModel):
    contract_version: str = "1.3"
    run_id: NonEmptyStr
    stage: str = "VALIDATION_EXECUTION"
    status: ValidationStageStatus
    candidate_result: NeutralExecutionResult | None = None
    candidate_results: list[NeutralExecutionResult] = Field(default_factory=list)
    environment_precheck: NeutralExecutionResult
    selected_regression_ids: list[NonEmptyStr]
    regression_results: list[NeutralExecutionResult]
    blocked_reason: str | None = None
    excluded_scope: list[NonEmptyStr] = Field(default_factory=list, alias="제외_범위")
    excluded_information_gaps: list[NonEmptyStr] = Field(
        default_factory=list, alias="제외된_정보_부족"
    )
    final_review_notes: list[NonEmptyStr] = Field(
        default_factory=list, alias="최종_확인_사항"
    )
    automation_exclusions: list["AutomationExclusion"] = Field(
        default_factory=list, alias="자동화_제외_TC"
    )
    created_at: NonEmptyStr

    @model_validator(mode="after")
    def normalize_candidate_results(self) -> "ValidationExecutionBundle":
        if self.candidate_result is not None and not self.candidate_results:
            self.candidate_results = [self.candidate_result]
        elif self.candidate_result is None and self.candidate_results:
            self.candidate_result = self.candidate_results[0]
        elif (
            self.candidate_result is not None
            and self.candidate_results
            and self.candidate_results[0] != self.candidate_result
        ):
            if len(self.candidate_results) == 1:
                self.candidate_results = [self.candidate_result]
            else:
                raise ValueError("candidate_result와 candidate_results[0]이 다릅니다.")
        if not self.candidate_results:
            raise ValueError("최소 한 건의 실행 가능한 신규 후보 결과가 필요합니다.")
        return self


class AutomationExclusion(StrictModel):
    tc_id: Annotated[str, StringConstraints(pattern=r"^TC-CAND-\d{3}$")]
    candidate_status: AutomationCandidateStatus
    reason: NonEmptyStr
    artifact_dir: str | None = None


class Agent4Finding(StrictModel):
    finding_id: Annotated[str, StringConstraints(pattern=r"^FIND-\d{3}$")]
    category: Agent4FindingCategory
    test_id: NonEmptyStr | None = None
    source: ExecutionSource | None = None
    requirement_ids: list[RequirementId] = Field(default_factory=list)
    status: NeutralExecutionStatus | None = None
    evidence_files: list[NonEmptyStr] = Field(default_factory=list)
    rationale: NonEmptyStr


class Agent4Analysis(StrictModel):
    contract_version: str = "1.3"
    run_id: NonEmptyStr
    stage: str = "AGENT_4_ANALYSIS"
    validation_execution_sha256: NonEmptyStr
    total_results: int = Field(ge=0)
    status_counts: dict[NeutralExecutionStatus, int]
    product_result_count: int = Field(ge=0)
    environment_result_count: int = Field(default=0, ge=0)
    pipeline_fixture_result_count: int = Field(ge=0)
    findings: list[Agent4Finding] = Field(default_factory=list, alias="검토_항목")
    excluded_scope: list[NonEmptyStr] = Field(default_factory=list, alias="제외_범위")
    excluded_information_gaps: list[NonEmptyStr] = Field(
        default_factory=list, alias="제외된_정보_부족"
    )
    final_review_notes: list[NonEmptyStr] = Field(
        default_factory=list, alias="최종_확인_사항"
    )
    automation_exclusions: list[AutomationExclusion] = Field(
        default_factory=list, alias="자동화_제외_TC"
    )
    recommendation: FinalRecommendation
    created_at: NonEmptyStr


class Checkpoint4Result(StrictModel):
    checkpoint: str = "CP4"
    status: CheckStatus
    handoff_status: HandoffStatus
    checks: list[CheckResult] = Field(min_length=1)


class FinalReport(StrictModel):
    contract_version: str = "1.3"
    run_id: NonEmptyStr
    stage: str = "FINAL_REPORT"
    analysis_sha256: NonEmptyStr
    checkpoint4_sha256: NonEmptyStr
    total_results: int = Field(ge=0)
    status_counts: dict[NeutralExecutionStatus, int]
    product_result_count: int = Field(default=0, ge=0)
    environment_result_count: int = Field(default=0, ge=0)
    pipeline_fixture_result_count: int = Field(default=0, ge=0)
    findings: list[Agent4Finding] = Field(default_factory=list, alias="검토_항목")
    excluded_scope: list[NonEmptyStr] = Field(default_factory=list, alias="제외_범위")
    excluded_information_gaps: list[NonEmptyStr] = Field(
        default_factory=list, alias="제외된_정보_부족"
    )
    final_review_notes: list[NonEmptyStr] = Field(
        default_factory=list, alias="최종_확인_사항"
    )
    automation_exclusions: list[AutomationExclusion] = Field(
        default_factory=list, alias="자동화_제외_TC"
    )
    recommendation: FinalRecommendation
    checkpoint_status: CheckStatus
    created_at: NonEmptyStr


class ExternalDeliveryStatus(str, Enum):
    PREVIEW = "PREVIEW"
    SENT = "SENT"
    SKIPPED = "SKIPPED"
    FAILED = "FAILED"
    BLOCKED = "BLOCKED"


class ExternalDestinationResult(StrictModel):
    destination: NonEmptyStr
    status: ExternalDeliveryStatus
    item_count: int = Field(default=0, ge=0)
    detail: NonEmptyStr
    payload_file: str | None = None
    payload_sha256: str | None = None


class ExternalReportingResult(StrictModel):
    contract_version: str = "1.0"
    run_id: NonEmptyStr
    stage: str = "AGENT_4_EXTERNAL_REPORTING"
    mode: str
    final_report_sha256: NonEmptyStr
    checkpoint4_sha256: NonEmptyStr
    attempt_id: str | None = None
    previous_reporting_sha256: str | None = None
    allowed: bool
    slack: ExternalDestinationResult
    notion: ExternalDestinationResult
    created_at: NonEmptyStr


@dataclass(frozen=True)
class ExistingRegressionSpec:
    tc_id: str
    test_function: str
    requirement_ids: tuple[str, ...]
    covered_behaviors: tuple[str, ...]


EXISTING_REGRESSION_CATALOG = (
    ExistingRegressionSpec(
        tc_id="TC-MODE-001",
        test_function="test_tc_mode_001_heat_mode_and_temp_apply",
        requirement_ids=("REQ-CONTROL-001", "REQ-MODE-001", "REQ-STATE-001"),
        covered_behaviors=(
            "단일 장비에 HEAT 모드를 중앙 관제 패널로 적용",
            "장비 카드의 난방 표시와 내부 mode=HEAT·setTemp=24.0 동기화",
        ),
    ),
    ExistingRegressionSpec(
        tc_id="TC-MODE-002",
        test_function="test_tc_mode_002_fan_mode_temp_disabled",
        requirement_ids=("REQ-MODE-002",),
        covered_behaviors=(
            "FAN 모드 선택 시 온도 올림·내림 버튼 비활성화",
            "설정 온도 표시 ---와 온도 영역 disabled 상태",
        ),
    ),
    ExistingRegressionSpec(
        tc_id="TC-MODE-003",
        test_function="test_tc_mode_003_dry_mode_then_cool_reactivation",
        requirement_ids=("REQ-MODE-001", "REQ-MODE-002"),
        covered_behaviors=(
            "DRY 모드의 온도 조작 비활성화와 --- 표시",
            "COOL 복귀 시 온도 조작 재활성화와 온도 표시 복원",
        ),
    ),
    ExistingRegressionSpec(
        tc_id="TC-LOCK-001",
        test_function="test_tc_lock_001_all_devices_full_inspection",
        requirement_ids=("REQ-LOCK-001",),
        covered_behaviors=(
            "전체 장비 locked=true 주입 후 잠금 표시 확인",
            "잠긴 장비의 중앙 관제 명령 차단과 기존 내부 상태 불변",
        ),
    ),
    ExistingRegressionSpec(
        tc_id="TC-ERR-001",
        test_function="test_tc_err_001_ch05_fault_injection_control_block",
        requirement_ids=("REQ-ERROR-001",),
        covered_behaviors=(
            "CH05 오류 주입 후 오류 카드·로그 표시",
            "오류 장비 제어 차단 Toast·로그와 내부 status=ERROR 유지",
        ),
    ),
    ExistingRegressionSpec(
        tc_id="TC-TEMP-001",
        test_function="test_tc_temp_001_upper_limit_boundary",
        requirement_ids=("REQ-TEMP-001",),
        covered_behaviors=(
            "설정 온도 30°C 상한 도달 허용",
            "30°C 초과 요청 차단과 범위 안내 Toast·화면 값 유지",
        ),
    ),
)

EXISTING_REGRESSION_BY_ID = {
    item.tc_id: item for item in EXISTING_REGRESSION_CATALOG
}


def render_existing_regression_context() -> str:
    """Render the allowlisted existing TC inventory without local file paths."""

    return "\n".join(
        "- "
        + item.tc_id
        + " | Requirement: "
        + ", ".join(item.requirement_ids)
        + " | 기존 자동화 함수: "
        + item.test_function
        + " | 검증 동작: "
        + " / ".join(item.covered_behaviors)
        for item in EXISTING_REGRESSION_CATALOG
    )

ENVIRONMENT_PRECHECK = ExistingRegressionSpec(
    tc_id="TC-ENV-000",
    test_function="test_tc_env_000_pre_environment_check",
    requirement_ids=("REQ-ENV-001",),
    covered_behaviors=("가상 중앙제어 화면의 기본 실행 환경 준비 상태",),
)


# ---------------------------------------------------------------------------
# Product SRS 로더
# ---------------------------------------------------------------------------
_REQUIREMENT_ROW = re.compile(
    r"^\|\s*(REQ-[A-Z]+-\d{3})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$"
)
_REQUIREMENT_ID = re.compile(r"REQ-[A-Z]+-\d{3}")


def load_srs_requirements(path: Path) -> dict[str, SrsRequirement]:
    """Load requirement rows from the product SRS Markdown tables."""
    if not path.is_file():
        raise FileNotFoundError(f"SRS 파일을 찾을 수 없습니다: {path}")

    requirements: dict[str, SrsRequirement] = {}
    section_relations: list[str] = []
    reading_relations = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("## "):
            section_relations = []
            reading_relations = False
            continue
        if line.startswith("### Relation with other Requirement"):
            section_relations = []
            reading_relations = True
            continue
        if reading_relations and line.startswith("- "):
            section_relations.extend(_REQUIREMENT_ID.findall(line))
            continue
        match = _REQUIREMENT_ROW.match(line)
        if not match:
            continue
        requirement_id, statement, acceptance_criteria = match.groups()
        if requirement_id in requirements:
            raise ValueError(f"중복 Requirement ID: {requirement_id}")
        requirements[requirement_id] = SrsRequirement(
            requirement_id=requirement_id,
            statement=statement,
            acceptance_criteria=acceptance_criteria,
            related_requirement_ids=sorted(
                item for item in set(section_relations) if item != requirement_id
            ),
        )

    if not requirements:
        raise ValueError(f"SRS에서 Requirement를 찾지 못했습니다: {path}")
    unknown_related = sorted(
        {
            related_id
            for requirement in requirements.values()
            for related_id in requirement.related_requirement_ids
            if related_id not in requirements
        }
    )
    if unknown_related:
        raise ValueError(
            "SRS 연관관계에 정의되지 않은 Requirement ID가 있습니다: "
            + ", ".join(unknown_related)
        )
    return requirements


def render_srs_context(requirements: dict[str, SrsRequirement]) -> str:
    """Render only the machine-verifiable requirement rows for the model."""
    rows = ["ID | 요구사항 | 인수 기준"]
    for requirement_id in sorted(requirements):
        item = requirements[requirement_id]
        rows.append(
            f"{item.requirement_id} | {item.statement} | {item.acceptance_criteria} | "
            "관련 요구사항: "
            + (", ".join(item.related_requirement_ids) or "없음")
        )
    return "\n".join(rows)

# ---------------------------------------------------------------------------
# Agent 1: 변경 요구사항 분석
# ---------------------------------------------------------------------------
AGENT1_SYSTEM_INSTRUCTIONS = """
당신은 운영 중인 가상 중앙제어 시스템의 변경 요구사항을 분석하는 Agent 1입니다.

입력의 권한 관계:
- 현재 SRS는 변경 전 제품 상태를 설명하는 기준 문서입니다.
- 변경 요청의 after_value, description, acceptance_notes는 사용자가 제안한 변경 후 정책의 권한 있는 입력입니다.
- 변경 후 정책이 현재 SRS에 없다는 사실만으로 정보 부족이나 사용자 재확인으로 판정하지 않습니다.

반드시 지킬 규칙:
1. 제공된 변경 요청과 SRS Requirement 행만 사실 근거로 사용합니다.
2. 변경 요청에 명시된 신규 기능, 수치, UI 표현은 변경 후 정책으로 사용할 수 있지만, 변경 요청과 SRS 어디에도 없는 내용은 만들지 않습니다.
3. 현재 MVP는 MODIFIED 변경만 처리합니다.
4. before_condition과 after_condition은 요청 값을 바꾸거나 보완하지 않습니다.
5. change_summary는 Agent 2가 변경 목적을 바로 이해할 수 있게 한두 문장으로 작성합니다.
6. confirmed_conditions에는 Agent 2가 TC의 판정 기준으로 사용할 수 있는 확정 조건만 한 항목씩 분리합니다. 테스트 절차나 새로운 기대값은 만들지 않습니다.
7. acceptance_notes 중 제품의 긍정적인 판정 기준은 각각 별도 confirmed_condition으로 만들고 source_text에 해당 인수 조건 원문 전체를 한 글자도 합치거나 바꾸지 않고 기록합니다. `범위에 포함하지 않는다`, `제외한다`, `검증 대상이 아니다`처럼 범위를 제한하는 항목은 confirmed_condition으로 만들지 말고 excluded_scope에 원문 그대로 기록합니다. 시험 준비·선택·종료 후 복원 절차도 제품 기대 결과인 confirmed_condition으로 바꾸지 않습니다. 그 밖에 after_value와 description에만 있는 변경 후 범위·경계·모드별 정책도 별도 조건으로 포함합니다. 특히 하한~상한 범위는 두 경계를 모두 전달하고, 추가 조건의 source_type은 CHANGE_REQUEST, source_text는 해당 요청의 연속된 원문으로 기록합니다.
8. 기존 SRS 조건을 사용할 때는 source_type을 SRS로 지정하고 source_text는 연결 Requirement의 요구사항 또는 인수 기준에서 연속된 원문 일부를 그대로 사용합니다.
9. 각 confirmed_condition의 requirement_ids와 requirement_effects에는 제공된 SRS에 존재하는 ID만 사용합니다.
10. target_requirement_id는 requirement_effects에서 MODIFIED로 분류합니다.
11. 대상 Requirement의 related_requirement_ids와 변경 요청이 직접 언급하는 기존 Requirement를 모두 검토합니다. 변경 후 정책 때문에 기존 문장이나 인수 기준의 수정이 필요한 연관 Requirement는 UPDATE_REQUIRED, 변경으로 실제 영향을 받을 수 있어 기존 동작 회귀가 필요한 기준은 VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT로 분류하고 이유를 작성합니다. 모든 변경에 일반적으로 적용된다는 이유만으로 알림·상태·제어 Requirement를 일괄 VERIFY로 확장하지 않습니다. 연관 항목을 조용히 생략하지 않습니다.
12. MODIFIED, UPDATE_REQUIRED 또는 VERIFY로 분류한 모든 Requirement는 confirmed_conditions의 requirement_ids에 최소 한 번 연결하고, 변경 요청 또는 해당 SRS의 검증 가능한 원문 조건을 함께 전달합니다.
13. VERIFY로 분류할 Requirement에서 전달할 검증 조건 원문을 찾지 못하면 이유만 추측해 VERIFY로 두지 말고 NO_IMPACT로 분류합니다. UPDATE_REQUIRED는 변경 요청과 기존 SRS가 실제로 충돌하는 경우에만 사용합니다.
14. NO_IMPACT Requirement는 confirmed_conditions의 requirement_ids에 연결하지 않습니다.
15. excluded_scope에는 요청에 명시된 제외 범위, 이번 변경과 무관한 범위, 또는 기대 결과가 불명확해 이번 실행에서 분리할 수 있는 범위를 기록합니다. 확정 조건과 제외 범위를 섞지 않습니다.
16. 변경 요청 내부의 충돌, 필수 기대 동작 누락 또는 대상 Requirement 불일치가 있을 때만 information_gaps와 user_questions에 기록합니다. 명확한 확정 조건도 함께 있고 불명확한 범위를 별도로 격리할 수 있으면 PARTIAL_PROCEED를 선택하고, 이번 실행에서 제외하는 information_gaps 원문을 `제외된_정보_부족`에 같은 목록으로 기록합니다.
17. 변경 요청에 이미 명시된 값을 SRS에 없다는 이유로 다시 확정해 달라고 질문하지 않습니다.
18. Toast 같은 안내 수단의 정확한 문구는 변경 요청이 문구 일치를 요구할 때만 필수 정보로 봅니다.
19. 질문이 없고 변경 전 근거, 변경 후 정책과 전달할 확정 조건이 명확하면 PROCEED를 선택합니다. PARTIAL_PROCEED는 확정 조건을 Agent 2로 계속 전달하고 excluded_scope와 information_gaps만 최종 보고 대상으로 남깁니다. 핵심 기대 결과를 확정할 수 없어 분리 진행도 불가능할 때만 WAITING_FOR_USER를 선택합니다.
20. 테스트케이스, 테스트 절차나 Playwright 코드는 작성하지 않습니다.
21. Agent 1은 요구사항 영향도와 확정 조건을 Agent 2에 빠짐없이 전달하는 단계입니다. 현재 UI·하네스·자동화 구현 지원 여부를 이유로 영향 있는 Requirement를 NO_IMPACT로 낮추거나 확정된 제품 조건을 excluded_scope로 보내지 않습니다. TC 구성·기존 TC 선택·자동화 가능 여부는 Agent 2 이후 단계의 책임입니다.
""".strip()


class Agent1Error(RuntimeError):
    """Raised when Agent 1 cannot produce a validated structured response."""


@dataclass(frozen=True)
class Agent1Response:
    analysis: Agent1Analysis
    response_id: str | None
    model: str
    usage: dict[str, int | None]


def _response_usage_summary(response: Any) -> dict[str, int | None]:
    """Preserve billed totals and optional cache/reasoning details from Responses."""

    usage = getattr(response, "usage", None)
    summary: dict[str, int | None] = {
        "input_tokens": getattr(usage, "input_tokens", None),
        "output_tokens": getattr(usage, "output_tokens", None),
        "total_tokens": getattr(usage, "total_tokens", None),
    }
    input_details = getattr(usage, "input_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None)
    optional_values = {
        "cached_input_tokens": getattr(input_details, "cached_tokens", None),
        "cache_write_input_tokens": getattr(
            input_details, "cache_write_tokens", None
        ),
        "reasoning_output_tokens": getattr(
            output_details, "reasoning_tokens", None
        ),
    }
    summary.update(
        {key: value for key, value in optional_values.items() if value is not None}
    )
    return summary


class OpenAIAgent1:
    def __init__(
        self,
        *,
        model: str | None = None,
        client: Any | None = None,
    ) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent1Error(
                    "OPENAI_API_KEY 환경변수가 없습니다. 키를 코드에 넣지 말고 "
                    "PowerShell 환경변수로 설정하세요."
                )
            client = OpenAI()
        self.client = client

    def analyze(
        self,
        request: ChangeRequest,
        requirements: dict[str, SrsRequirement],
        *,
        previous_analysis: Agent1Analysis | None = None,
        checkpoint_feedback: list[str] | None = None,
    ) -> Agent1Response:
        user_input = (
            "[변경 요청]\n"
            f"{request.model_dump_json(indent=2)}\n\n"
            "[현재 SRS Requirement]\n"
            f"{render_srs_context(requirements)}"
        )
        if previous_analysis is not None:
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[이전 분석 결과]\n"
                f"{previous_analysis.model_dump_json(indent=2)}\n\n"
                "[Checkpoint 1 재작업 요청]\n"
                f"{feedback}\n"
                "이전 결과의 근거 있는 내용은 유지하고 위 실패만 수정하세요. "
                "새로운 요구사항이나 테스트 절차를 만들지 마세요."
            )

        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
                prompt_cache_key="qa-v2-agent1-2-6",
                input=[
                    {"role": "system", "content": AGENT1_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent1Analysis,
            )
        except Exception as exc:  # SDK exceptions vary by transport and status.
            raise Agent1Error(f"Agent 1 모델 호출에 실패했습니다: {exc}") from exc

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent1Error("모델이 구조화된 Agent 1 결과를 반환하지 않았습니다.")

        return Agent1Response(
            analysis=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
        )

# ---------------------------------------------------------------------------
# Checkpoint 1: 요구사항 분석 검증
# ---------------------------------------------------------------------------
def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _contains(container: str, expected: str) -> bool:
    return _normalize(expected) in _normalize(container)


def _terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[가-힣A-Za-z0-9°%._~+·-]{2,}", value)
    }


def _has_textual_link(left: str, right: str) -> bool:
    """Match a shared term while tolerating Korean particles and inflections."""
    left_terms = _terms(left)
    right_terms = _terms(right)
    if left_terms & right_terms:
        return True
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    return any(
        len(term) >= 2 and term in right_normalized for term in left_terms
    ) or any(
        len(term) >= 2 and term in left_normalized for term in right_terms
    )


def _temperature_ranges(value: str) -> set[tuple[float, float]]:
    return {
        (float(match.group(1)), float(match.group(2)))
        for match in re.finditer(
            r"(?<!\d)(-?\d+(?:\.\d+)?)\s*~\s*(-?\d+(?:\.\d+)?)\s*°?\s*C",
            value,
            flags=re.IGNORECASE,
        )
    }

def _request_authority_text(request: ChangeRequest) -> str:
    return " ".join(
        filter(
            None,
            [
                request.after_value,
                request.description,
                request.reason,
                *request.acceptance_notes,
            ],
        )
    )


_SCOPE_EXCLUSION_TEXT = re.compile(
    r"(?:범위(?:에|에는|에서)?\s*(?:포함하지|포함되지|벗어)|범위\s*밖|"
    r"검증\s*대상(?:이|은|에는)?\s*아니|요구하지\s*않|"
    r"(?:이번\s*)?(?:변경|시험|검증)?\s*범위에서\s*제외|out[\s-]*of[\s-]*scope)",
    re.IGNORECASE,
)


def _is_scope_exclusion_text(value: str) -> bool:
    return bool(_SCOPE_EXCLUSION_TEXT.search(value))


def _is_redundant_reconfirmation(question: str, request: ChangeRequest) -> bool:
    reconfirmation = re.search(
        r"확정할\s*수\s*있|확정해\s*(?:도|주)|맞습니까|재확인|다시\s*확인|추가하는\s*것으로",
        question,
        flags=re.IGNORECASE,
    )
    if reconfirmation is None:
        return False

    question_terms = _terms(question)
    overlap = question_terms & _terms(_request_authority_text(request))
    return len(overlap) >= 3 and len(overlap) / max(len(question_terms), 1) >= 0.25


def evaluate_checkpoint1(
    request: ChangeRequest,
    analysis: Agent1Analysis,
    requirements: dict[str, SrsRequirement],
) -> Checkpoint1Result:
    checks: list[CheckResult] = []

    def add(rule_id: str, status: CheckStatus, message: str) -> None:
        checks.append(CheckResult(rule_id=rule_id, status=status, message=message))

    if analysis.request_id == request.request_id:
        add("CP1-001", CheckStatus.PASS, "변경 요청 ID가 일치합니다.")
    else:
        add("CP1-001", CheckStatus.FAIL, "변경 요청 ID가 입력과 다릅니다.")

    target = requirements.get(request.target_requirement_id)
    if target and analysis.target_requirement_id == request.target_requirement_id:
        add("CP1-002", CheckStatus.PASS, "대상 Requirement ID가 SRS와 일치합니다.")
    else:
        add("CP1-002", CheckStatus.FAIL, "대상 Requirement ID가 없거나 입력과 다릅니다.")

    if analysis.change_type == request.change_type:
        add("CP1-003", CheckStatus.PASS, "지원 변경 유형 MODIFIED가 유지됐습니다.")
    else:
        add("CP1-003", CheckStatus.FAIL, "모델이 변경 유형을 바꿨습니다.")

    before_matches_output = _contains(analysis.before_condition, request.before_value)
    before_has_source = bool(
        target
        and _contains(
            f"{target.statement} {target.acceptance_criteria}", request.before_value
        )
    )
    if not before_matches_output:
        add("CP1-004", CheckStatus.FAIL, "분석 결과의 변경 전 값이 요청과 다릅니다.")
    elif not before_has_source:
        add(
            "CP1-004",
            CheckStatus.REVIEW,
            "변경 전 값이 대상 SRS 행에서 직접 확인되지 않습니다.",
        )
    else:
        add("CP1-004", CheckStatus.PASS, "변경 전 값이 요청과 SRS 근거에 연결됩니다.")

    if _contains(analysis.after_condition, request.after_value):
        add("CP1-005", CheckStatus.PASS, "변경 후 값이 입력 요청과 일치합니다.")
    else:
        add("CP1-005", CheckStatus.FAIL, "분석 결과의 변경 후 값이 요청과 다릅니다.")

    effect_ids = [item.requirement_id for item in analysis.requirement_effects]
    condition_requirement_ids = {
        requirement_id
        for condition in analysis.confirmed_conditions
        for requirement_id in condition.requirement_ids
    }
    unknown_ids = sorted((set(effect_ids) | condition_requirement_ids) - requirements.keys())
    duplicate_effect_ids = sorted(
        requirement_id
        for requirement_id in set(effect_ids)
        if effect_ids.count(requirement_id) > 1
    )
    target_effects = [
        item
        for item in analysis.requirement_effects
        if item.requirement_id == request.target_requirement_id
    ]
    active_effect_ids = {
        item.requirement_id
        for item in analysis.requirement_effects
        if item.relation != RequirementRelation.NO_IMPACT
    }
    uncovered_effects = sorted(active_effect_ids - condition_requirement_ids)
    unlisted_condition_requirements = sorted(
        condition_requirement_ids - set(effect_ids)
    )
    no_impact_with_conditions = sorted(
        item.requirement_id
        for item in analysis.requirement_effects
        if item.relation == RequirementRelation.NO_IMPACT
        and item.requirement_id in condition_requirement_ids
    )
    required_related_ids = set(target.related_requirement_ids) if target else set()
    missing_related_reviews = sorted(required_related_ids - set(effect_ids))
    if unknown_ids:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            f"SRS에 없는 Requirement ID: {', '.join(unknown_ids)}",
        )
    elif duplicate_effect_ids:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            f"중복된 Requirement 영향 항목: {', '.join(duplicate_effect_ids)}",
        )
    elif len(target_effects) != 1 or target_effects[0].relation != RequirementRelation.MODIFIED:
        add("CP1-006", CheckStatus.FAIL, "대상 Requirement가 MODIFIED로 한 번만 분류되지 않았습니다.")
    elif any(
        item.relation == RequirementRelation.MODIFIED
        and item.requirement_id != request.target_requirement_id
        for item in analysis.requirement_effects
    ):
        add("CP1-006", CheckStatus.FAIL, "대상이 아닌 Requirement를 MODIFIED로 분류했습니다.")
    elif missing_related_reviews:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            "검토되지 않은 SRS 연관 Requirement가 있습니다: "
            + ", ".join(missing_related_reviews),
        )
    elif uncovered_effects:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            "확정 조건과 연결되지 않은 Requirement 영향이 있습니다: "
            + ", ".join(uncovered_effects),
        )
    elif unlisted_condition_requirements:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            "확정 조건에는 있지만 영향 목록에 없는 Requirement가 있습니다: "
            + ", ".join(unlisted_condition_requirements),
        )
    elif no_impact_with_conditions:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            "NO_IMPACT로 분류했지만 확정 조건에 연결된 Requirement가 있습니다: "
            + ", ".join(no_impact_with_conditions),
        )
    else:
        add("CP1-006", CheckStatus.PASS, "변경·확인 Requirement와 확정 조건이 연결됩니다.")

    invalid_conditions: list[str] = []
    condition_ids = [condition.condition_id for condition in analysis.confirmed_conditions]
    duplicate_condition_ids = {
        condition_id
        for condition_id in condition_ids
        if condition_ids.count(condition_id) > 1
    }
    request_authority = _request_authority_text(request)
    for condition in analysis.confirmed_conditions:
        if condition.source_type == ConditionSource.CHANGE_REQUEST:
            grounded = _contains(request_authority, condition.source_text)
        else:
            grounded = any(
                requirement_id in requirements
                and _contains(
                    f"{requirements[requirement_id].statement} "
                    f"{requirements[requirement_id].acceptance_criteria}",
                    condition.source_text,
                )
                for requirement_id in condition.requirement_ids
            )
        if not grounded:
            invalid_conditions.append(condition.condition_id)

    if duplicate_condition_ids:
        add(
            "CP1-007",
            CheckStatus.FAIL,
            "중복된 확정 조건 ID: " + ", ".join(sorted(duplicate_condition_ids)),
        )
    elif invalid_conditions:
        add(
            "CP1-007",
            CheckStatus.FAIL,
            "요청 또는 SRS 원문에서 확인되지 않는 확정 조건 출처: "
            + ", ".join(sorted(invalid_conditions)),
        )
    else:
        add("CP1-007", CheckStatus.PASS, "모든 확정 조건의 출처가 요청 또는 SRS에 존재합니다.")

    change_request_sources = [
        condition.source_text
        for condition in analysis.confirmed_conditions
        if condition.source_type == ConditionSource.CHANGE_REQUEST
    ]
    positive_acceptance_notes = [
        note for note in request.acceptance_notes if not _is_scope_exclusion_text(note)
    ]
    scope_limit_acceptance_notes = [
        note for note in request.acceptance_notes if _is_scope_exclusion_text(note)
    ]
    missing_acceptance_notes = [
        note
        for note in positive_acceptance_notes
        if not any(_normalize(note) == _normalize(source) for source in change_request_sources)
    ]
    required_ranges = _temperature_ranges(f"{request.after_value} {request.description}")
    delivered_ranges = _temperature_ranges(
        " ".join(
            f"{condition.statement} {condition.source_text}"
            for condition in analysis.confirmed_conditions
            if condition.source_type == ConditionSource.CHANGE_REQUEST
        )
    )
    missing_ranges = sorted(required_ranges - delivered_ranges)
    if missing_acceptance_notes or missing_ranges:
        details = []
        if missing_acceptance_notes:
            details.append("인수 조건 원문=" + " | ".join(missing_acceptance_notes))
        if missing_ranges:
            details.append(
                "변경 후 온도 범위 "
                + ", ".join(f"{low:g}~{high:g}°C" for low, high in missing_ranges)
            )
        add(
            "CP1-008",
            CheckStatus.FAIL,
            "Agent 2 전달 조건에서 누락된 항목: " + "; ".join(details),
        )
    else:
        add("CP1-008", CheckStatus.PASS, "변경 요청의 인수 조건과 변경 후 범위가 모두 전달됩니다.")

    confirmed_statements = {_normalize(item.statement) for item in analysis.confirmed_conditions}
    excluded = {_normalize(item) for item in analysis.excluded_scope}
    scope_limit_condition_ids = sorted(
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if condition.source_type == ConditionSource.CHANGE_REQUEST
        and _is_scope_exclusion_text(
            f"{condition.statement} {condition.source_text}"
        )
    )
    missing_scope_limit_notes = [
        item
        for item in scope_limit_acceptance_notes
        if _normalize(item) not in excluded
    ]
    missing_out_of_scope = [
        item
        for item in request.out_of_scope
        if _normalize(item) not in excluded
    ]
    if scope_limit_condition_ids:
        add(
            "CP1-009",
            CheckStatus.FAIL,
            "제외 조건을 Agent 2 확정 조건으로 전달했습니다: "
            + ", ".join(scope_limit_condition_ids),
        )
    elif confirmed_statements & excluded:
        add("CP1-009", CheckStatus.FAIL, "확정 조건과 제외 범위가 겹칩니다.")
    elif missing_scope_limit_notes:
        add(
            "CP1-009",
            CheckStatus.FAIL,
            "범위 제한 인수 조건이 제외 범위에서 누락됐습니다.",
        )
    elif missing_out_of_scope:
        add("CP1-009", CheckStatus.FAIL, "요청에 명시된 제외 범위가 분석 결과에서 누락됐습니다.")
    else:
        add("CP1-009", CheckStatus.PASS, "확정 조건과 제외 범위가 분리됐습니다.")

    has_open_questions = bool(analysis.information_gaps or analysis.user_questions)
    redundant_questions = [
        question
        for question in analysis.user_questions
        if _is_redundant_reconfirmation(question, request)
    ]
    partial_gap_mapping_matches = {
        _normalize(item) for item in analysis.excluded_information_gaps
    } == {_normalize(item) for item in analysis.information_gaps}
    if analysis.decision == AnalysisDecision.PARTIAL_PROCEED and (
        not analysis.excluded_scope
        or not analysis.information_gaps
        or not partial_gap_mapping_matches
    ):
        add(
            "CP1-010",
            CheckStatus.FAIL,
            "PARTIAL_PROCEED는 계속 실행할 확정 조건과 별도로 제외 범위·정보 부족·제외된 정보 부족의 동일 목록을 기록해야 합니다.",
        )
    elif analysis.decision == AnalysisDecision.PROCEED and has_open_questions:
        add(
            "CP1-010",
            CheckStatus.REVIEW,
            "정보 부족 또는 질문이 있는데 PROCEED로 판정했습니다.",
        )
    elif analysis.decision == AnalysisDecision.WAITING_FOR_USER and not analysis.user_questions:
        add(
            "CP1-010",
            CheckStatus.REVIEW,
            "WAITING_FOR_USER이지만 사용자 질문이 없습니다.",
        )
    elif redundant_questions:
        add(
            "CP1-010",
            CheckStatus.REVIEW,
            "변경 요청에 이미 명시된 정책을 다시 확인하는 질문이 있습니다.",
        )
    else:
        add("CP1-010", CheckStatus.PASS, "정보 부족·질문·진행 판정이 일관됩니다.")

    statuses = {check.status for check in checks}
    if CheckStatus.ERROR in statuses:
        status = CheckStatus.ERROR
    elif CheckStatus.FAIL in statuses:
        status = CheckStatus.FAIL
    elif CheckStatus.REVIEW in statuses:
        status = CheckStatus.REVIEW
    else:
        status = CheckStatus.PASS
    blocking_decision = analysis.decision == AnalysisDecision.WAITING_FOR_USER
    if status in {CheckStatus.FAIL, CheckStatus.ERROR}:
        handoff_status = HandoffStatus.BLOCKED
    elif blocking_decision:
        handoff_status = HandoffStatus.PAUSE
    elif analysis.decision in {
        AnalysisDecision.PROCEED,
        AnalysisDecision.PARTIAL_PROCEED,
    }:
        handoff_status = HandoffStatus.CONTINUE
    else:
        handoff_status = HandoffStatus.BLOCKED
    final_review_notes = (
        [check.message for check in checks if check.status == CheckStatus.REVIEW]
        if handoff_status == HandoffStatus.CONTINUE
        else []
    )
    return Checkpoint1Result(
        status=status,
        handoff_status=handoff_status,
        checks=checks,
        final_review_notes=final_review_notes,
    )

# ---------------------------------------------------------------------------
# Agent 2: 제품 기능 테스트케이스 설계
# ---------------------------------------------------------------------------
AGENT2_SYSTEM_INSTRUCTIONS = """
당신은 CP1을 통과한 변경 분석을 제품 기능 테스트케이스 후보로 바꾸는 Agent 2입니다.

역할 경계:
- 무엇을 어떤 조건에서 검증할지 설계합니다.
- Playwright 코드, Selector, Python 코드나 자동화 구현은 작성하지 않습니다.
- 입력으로 제공된 기존 TC 카탈로그와 변경 조건을 먼저 대조합니다.
- test_cases에는 이번 변경으로 새로 필요하거나 기대 결과·절차가 달라져 수정이 필요한 변경 검증 후보만 작성합니다.
- 유지되는 기존 동작은 새 TC로 다시 작성하지 않고 관련_기존_TC에 기존 TC ID와 연결 조건을 기록합니다.
- 출력은 사람의 마지막 승인 전 변경 검증용 제품 TC 후보와 영향받는 기존 회귀 선택입니다.

반드시 지킬 규칙:
1. 검증된 변경 요청 원문, Agent 1의 confirmed_conditions와 고정된 SRS만 사실 근거로 사용합니다.
2. requirement_effects가 NO_IMPACT인 Requirement는 테스트 범위에 포함하지 않습니다.
3. MODIFIED는 변경 동작 검증 후보, UPDATE_REQUIRED는 변경으로 기대 결과·절차 수정이 필요한 후보, VERIFY는 기존 동작 회귀 선택으로 해석합니다.
3-1. 기존 TC 카탈로그의 `검증 동작`이 VERIFY·유지 조건을 그대로 검증하면 관련_기존_TC로 선택하고 동일 내용을 TC-CAND로 다시 만들지 않습니다. Requirement ID만 같고 검증 동작이 다르면 재사용으로 판단하지 않습니다. 기존 TC가 변경된 기대 결과를 검증할 수 없을 때만 부족한 변경분 후보를 만듭니다.
4. 모든 confirmed_condition을 test_cases 또는 관련_기존_TC의 source_condition_ids 중 최소 한 곳에 반영합니다. 실제로 바뀐 제품 판정 조건은 반드시 test_cases에 반영합니다. 준비·선택·복원 절차를 제품 기대 결과로 바꾸지 않습니다.
5. 모든 기대 결과는 source_condition_ids로 제품 판정 근거를 연결합니다. 근거에 없는 수치·시간·문구·UI 동작을 추가하지 않습니다. 장비 선택 성공, 사전조건 준비 완료, 시험 종료 후 복원처럼 실행을 위한 절차는 steps·preconditions·restore_steps에만 두고, 변경 요청이 그 동작 자체의 제품 결과를 요구하지 않는 한 expected_results로 만들지 않습니다.
5-1. 제출 전 각 TC를 자체 점검합니다. (a) TC의 requirement_ids는 그 TC의 source_condition_ids가 함께 근거를 가져야 하고, (b) 각 기대 결과의 source_condition_ids는 그 TC의 source_condition_ids 범위 안에 있어야 하며, (c) 각 기대 결과의 UI 표시·상태는 연결 Condition의 source_text 원문에 실제로 있어야 합니다. TC 수준 Condition에는 제품 판정 기준뿐 아니라 준비·복원 지시가 포함될 수 있으므로 모든 TC Condition을 억지로 expected_results에 다시 넣지 않습니다. 특히 UI·내부 상태 이중 검증 TC는 사용자가 요청한 UI 변경 결과와 그 동작을 뒷받침하는 내부 상태를 사용하고, 별도의 UI 상태 표시를 새로 만들지 않습니다.
5-2. 모드가 사전조건의 실행 문맥이면 initial_mode에만 기록합니다. steps에서 모드를 실제로 설정·변경·전환·요청할 때만 단일 조건은 requested_mode, 묶음 조건은 requested_modes에 해당 모드를 기록해 Agent 3가 필요한 모드 행동을 계획하게 합니다. 사전조건과 같은 모드를 requested_mode에 복제해 불필요한 제품 동작을 만들지 않습니다.
5-2-1. 기존 중앙 관제 온도·모드 흐름의 묶음 TC가 실행 전 모드·설정 온도를 요구사항으로 고정하지 않았지만 시험 중 두 값 중 하나를 변경하고 원상 복구해야 하면 restore_observed_hvac_state=true를 사용합니다. 이때 임의 initial_mode·initial_temperature_c를 만들지 말고 restore_steps에 `실행 직전 관찰한 모드와 설정 온도로 복원하고 적용한다`는 뜻을 명시합니다. 이 표시는 처음 보는 일반 기능의 내부 값을 임의로 복원하는 허가가 아닙니다.
5-3. 각 expected_result는 한 observation_layer에서 독립적으로 한 번 판정할 수 있는 관찰값 하나만 기술합니다. 화면 모드·화면 온도·대기값 반영·버튼 활성 상태처럼 서로 다른 관찰값을 한 Expected Result에 묶지 말고 고유한 ER ID로 분리합니다. 내부 장비 객체의 서로 연관된 여러 필드는 하나의 INTERNAL_STATE 결과로 함께 기록할 수 있습니다. Expected Result를 분리한다는 것은 TC 자체를 분리한다는 뜻이 아닙니다.
5-4. 하나의 TC 안에 여러 조건 구간이 있으면 각 expected_result의 verify_after_step에 그 결과를 확인해야 하는 steps의 문장을 정확히 복사합니다. 마지막에 한꺼번에 확인하면 앞 조건의 결과가 사라질 수 있으므로, 조건별 실행 직후 판정 위치를 명시합니다.
6. test_cases의 purpose는 CHANGE_VALIDATION만 사용합니다. 유지되는 기존 동작은 RELATED_REGRESSION 후보를 새로 만들지 말고 관련_기존_TC로 분리합니다.
6-1. 범위 변경은 변경된 경계뿐 아니라 변경 후 범위의 하한과 상한을 각각 검증합니다. 같은 관제점의 같은 범위 규칙이면 하한·상한을 하나의 TC 안에서 조건 구간으로 묶을 수 있습니다.
6-2. 현재 V2의 제품 조작 기준은 중앙 관제 패널 하나입니다. 모든 실행 TC는 control_path=CENTRAL을 사용하며 LOCAL·현장 리모컨 TC를 만들지 않습니다.
7. TC 분리 단위는 입력값 하나가 아니라 하나의 업무 규칙입니다. 같은 관제점·제어 경로·업무 규칙이고 입력값이나 모드만 달라지는 경우에는 하나의 TC로 묶어 중복을 줄입니다. 예시의 특정 모드명·온도값을 고정 규칙으로 사용하지 말고 현재 입력의 Requirement와 confirmed_condition으로 동일 업무 규칙인지 판단합니다.
7-1. 관련 조건을 묶을 때 condition_execution을 사용합니다. 조건마다 독립 초기화가 필요하면 INDEPENDENT_VARIANTS, 앞 상태에서 다음 상태로의 전환 자체를 검증하면 SEQUENTIAL_TRANSITION, 조건 구간이 하나뿐이면 SINGLE_FLOW입니다.
7-2. INDEPENDENT_VARIANTS는 각 조건이 앞 조건의 결과에 의존하지 않도록 steps 안에 초기화·재준비 절차를 넣고, 그 문장을 intermediate_reset_steps에도 정확히 복사합니다. SEQUENTIAL_TRANSITION은 전환 순서가 Requirement의 검증 목적일 때만 사용하며 임의로 독립 조건을 연결하지 않습니다.
7-3. 묶음 TC는 grouping_reason에 같은 TC로 처리하는 근거가 되는 공통 관제점·업무 규칙을 구체적으로 기록합니다. 서로 다른 Requirement 목적, 서로 다른 제어 경로, 실패 원인이 무관한 기능은 별도 TC로 분리합니다.
7-4. 묶음 TC의 각 조건은 steps와 expected_results에서 구분되어야 합니다. 한 조건의 입력·행동·결과를 작성한 뒤 필요한 초기화 또는 전환을 거쳐 다음 조건을 작성합니다. 모든 결과를 TC 마지막 상태에서 한꺼번에 확인하도록 작성하지 않습니다.
7-5. requested_modes와 requested_temperatures_c에는 묶음 TC가 실제로 요청하는 모든 모드·온도 값을 중복 없이 기록합니다. 단일 조건은 기존 requested_mode와 requested_temperature_c를 사용할 수 있습니다. test_data와 절차에 없는 값을 자동화 단계가 추정하게 하지 않습니다.
8. REQ-CONTROL-001을 검증하면 CENTRAL 경로에서 관제 패널을 통한 적용을 다룹니다. 과거 산출물의 LOCAL 값이나 REQ-LOCAL-*를 현재 SRS 근거로 추정하거나 새 TC로 확장하지 않습니다.
9. target_role은 고정 장치 ID를 추측하지 말고 PRIMARY_TEST_DEVICE처럼 역할로 지정합니다.
10. test_data에는 준비·요청에 필요한 모드와 온도를 구조화합니다. TC 절차 안에만 값을 숨기지 않으며, 여러 조건을 묶었으면 모든 조건 값을 복수형 필드에 기록합니다.
11. 상태 변경 또는 차단을 검증하는 TC는 사용자 화면(UI)과 내부 상태(INTERNAL_STATE)를 함께 확인합니다. 이중 검증은 동일 변경을 서로 다른 계층에서 확인하는 원칙이지, 요청에 없는 화면 배지·선택 표시·잠금 상태 표시를 추가하라는 뜻이 아닙니다. 변경된 버튼 disabled 상태가 UI 결과라면 내부 locked 같은 근거 상태와 짝지을 수 있으며 별도 잠금 표시 UI를 요구하지 않습니다. 변경 요청·SRS에 `locked`, `mode`, `setTemp`처럼 내부 필드 식별자가 명시돼 있으면 INTERNAL_STATE 기대 결과에도 그 식별자를 번역하거나 생략하지 않고 정확히 보존합니다.
11-1. 각 TC는 V1의 3단계 QA 기준을 명시적으로 기록합니다. common_qa_criteria에는 정상·예외·경계·복구·권한·사용자 피드백 중 적용 기준을, domain_qa_criteria에는 장비 식별·다중 제어·비대상 보존·UI/내부 상태 정합성·부분 장애 격리 중 적용 기준을, feature_requirement_ids에는 기능별 기준이 되는 해당 TC의 Requirement ID를 기록합니다.
11-2. 각 TC는 이전 TC 결과에 의존하지 않고 단독 실행 가능해야 합니다. independent_execution=true와 구체적인 independence_reason을 기록하고, 필요한 초기 상태는 preconditions·test_data로, 상태가 바뀌면 restore_steps로 복원합니다.
11-3. UI와 내부 상태를 함께 확인해야 하면 double_assert_policy=REQUIRED를 사용합니다. UI 전용·내부 상태 전용·해당 없음은 각각 UI_ONLY·INTERNAL_ONLY·NOT_APPLICABLE로 구분하고 double_assert_reason에 예외 사유를 기록합니다.
12. 안내 표시 조건을 검증하는 TC는 NOTIFICATION 기대 결과를 포함합니다. 정확한 Toast 문구가 입력에 없으면 문구를 만들어 일치 검증하지 않습니다.
13. 사전조건, 실행 행동과 판정 가능한 변경 기대 결과를 구체적으로 작성합니다. 실행 후 상태가 실제로 바뀌면 restore_required=true와 원상 복구 절차를 작성하되 복원 완료를 제품 expected_result로 중복 생성하지 않습니다. 차단되어 상태가 변하지 않으면 false와 빈 목록을 사용합니다.
14. TC가 참조하는 Requirement와 Condition은 입력에 존재하는 ID만 사용합니다.
15. confirmed_condition을 여러 TC가 공유할 수 있지만 동일 목적의 TC를 표현만 바꿔 중복 생성하지 않습니다.
16. automation_candidate는 현재 가상 중앙제어 화면과 내부 상태 조회로 자동화 가능한지 판단한 후보 표시일 뿐이며 코드를 만들지 않습니다.
16-1. CENTRAL 변경 검증에는 현재 단일 장비 MVP가 실행할 수 있도록 target_role=PRIMARY_TEST_DEVICE인 automation_candidate TC를 최소 한 건 포함합니다. 복수 장비 TC는 추가할 수 있지만 유일한 CENTRAL 후보로 만들지 않습니다.
17. SRS 문구의 후속 개정 필요, 정확한 안내 문구 미지정처럼 기대 동작을 바꾸지 않고 현재 TC를 설계할 수 있는 참고 사항은 coverage_notes에 남깁니다.
17-1. Agent 1의 excluded_scope와 `제외된_정보_부족`은 TC로 만들지 말고 Agent 2의 `제외_범위`와 `제외된_정보_부족`에 원문 그대로 인계합니다. 제외 범위의 상태 유지 여부를 확인하는 기대 결과도 새로 만들지 않습니다. 확정된 긍정적 변경 결과만 test_cases에 포함합니다.
18. 현재 TC의 기대 결과와 실행 범위가 이미 근거로 확정됐지만 사람이 최종 보고에서 확인하면 좋은 사항은 `최종_확인_사항`에 남깁니다. 이 항목은 후속 자동 실행을 중단하지 않습니다.
19. 서로 충돌하는 권한 입력, 기대 결과 미정처럼 TC 의미를 확정할 수 없어 후속 자동 진행을 중단해야 하는 항목만 `중단_확인_사항`에 남깁니다.
20. UPDATE_REQUIRED 자체는 변경관리의 정상 결과이므로 그것만으로 `중단_확인_사항` 또는 `최종_확인_사항`을 만들지 않습니다.
21. existing_tc_comparison_completed=true로 기록합니다. 관련_기존_TC에는 제공된 기존 TC ID만 사용하고 각 선택이 어떤 유지·영향 조건을 회귀 확인하는지 source_condition_ids와 selection_reason으로 설명합니다. 변경 대상 Requirement를 포함하는 기존 TC도 `검증 동작`을 대조하되 변경 후에도 그대로 유효한 경우에만 선택합니다. 재사용할 수 없으면 억지로 선택하지 말고 TC ID와 미선택 이유를 coverage_notes에 기록합니다.
""".strip()


class Agent2Error(RuntimeError):
    """Raised when Agent 2 cannot produce a validated structured response."""


@dataclass(frozen=True)
class Agent2Response:
    design: Agent2TestDesign
    response_id: str | None
    model: str
    usage: dict[str, int | None]


class OpenAIAgent2:
    def __init__(self, *, model: str | None = None, client: Any | None = None) -> None:
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent2Error(
                    "OPENAI_API_KEY 환경변수가 없습니다. 키를 코드에 넣지 말고 "
                    "PowerShell 환경변수로 설정하세요."
                )
            client = OpenAI()
        self.client = client

    def design(
        self,
        request: ChangeRequest,
        analysis: Agent1Analysis,
        requirements: dict[str, SrsRequirement],
        *,
        previous_design: Agent2TestDesign | None = None,
        checkpoint_feedback: list[str] | None = None,
    ) -> Agent2Response:
        user_input = (
            "[검증된 변경 요청 원문]\n"
            f"{request.model_dump_json(indent=2)}\n\n"
            "[CP1 통과 Agent 1 분석]\n"
            f"{analysis.model_dump_json(indent=2, by_alias=True)}\n\n"
            "[고정된 SRS Requirement]\n"
            f"{render_srs_context(requirements)}\n\n"
            "[기존 사람 작성·자동화 TC 카탈로그]\n"
            f"{render_existing_regression_context()}"
        )
        if previous_design is not None:
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[이전 TC 후보]\n"
                f"{previous_design.model_dump_json(indent=2, by_alias=True)}\n\n"
                "[Checkpoint 2 전체 판정과 재작업 요청]\n"
                f"{feedback}\n"
                "근거와 검증 목적은 바꾸지 말고 실패한 품질 기준만 수정하세요. "
                "PASS인 규칙과 그 근거를 보존하고 새 FAIL을 만들지 마세요. "
                "수정 대상 TC만 반환하지 말고 이전의 전체 test_cases와 관련_기존_TC를 완전한 결과로 반환하세요. "
                "Checkpoint가 삭제를 요구하지 않은 변경분 후보와 기존 TC 선택은 제거하지 마세요. "
                "Playwright 코드는 작성하지 마세요."
            )
        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
            prompt_cache_key="qa-v2-agent2-2-14",
                input=[
                    {"role": "system", "content": AGENT2_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent2TestDesign,
            )
        except Exception as exc:
            raise Agent2Error(f"Agent 2 모델 호출에 실패했습니다: {exc}") from exc

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent2Error("모델이 구조화된 Agent 2 결과를 반환하지 않았습니다.")
        return Agent2Response(
            design=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
        )


def _normalize_agent2_technical_ids(
    design: Agent2TestDesign,
) -> tuple[Agent2TestDesign, list[dict[str, str]]]:
    """Fix only duplicate technical IDs; never alter TC meaning or expected values."""

    tc_ids = [test_case.tc_id for test_case in design.test_cases]
    result_ids = [
        result.result_id
        for test_case in design.test_cases
        for result in test_case.expected_results
    ]
    normalize_tc_ids = len(tc_ids) != len(set(tc_ids))
    normalize_result_ids = len(result_ids) != len(set(result_ids))
    if not normalize_tc_ids and not normalize_result_ids:
        return design, []

    changes: list[dict[str, str]] = []
    result_number = 1
    normalized_cases: list[ProductTestCaseCandidate] = []
    for case_number, test_case in enumerate(design.test_cases, start=1):
        case_update: dict[str, Any] = {}
        if normalize_tc_ids:
            normalized_tc_id = f"TC-CAND-{case_number:03d}"
            if test_case.tc_id != normalized_tc_id:
                changes.append(
                    {
                        "field": "tc_id",
                        "before": test_case.tc_id,
                        "after": normalized_tc_id,
                    }
                )
            case_update["tc_id"] = normalized_tc_id
        if normalize_result_ids:
            normalized_results: list[ExpectedResult] = []
            for result in test_case.expected_results:
                normalized_result_id = f"ER-{result_number:03d}"
                result_number += 1
                if result.result_id != normalized_result_id:
                    changes.append(
                        {
                            "field": "result_id",
                            "before": result.result_id,
                            "after": normalized_result_id,
                        }
                    )
                normalized_results.append(
                    result.model_copy(update={"result_id": normalized_result_id})
                )
            case_update["expected_results"] = normalized_results
        normalized_cases.append(test_case.model_copy(update=case_update))
    return design.model_copy(update={"test_cases": normalized_cases}), changes


def _normalize_agent2_verify_regressions(
    analysis: Agent1Analysis,
    design: Agent2TestDesign,
) -> tuple[Agent2TestDesign, list[dict[str, Any]]]:
    """Deterministically add catalog regressions for Agent 1 VERIFY relations.

    Agent 2 still decides whether a regression tied to the directly modified
    Requirement remains reusable.  This normalizer only prevents an already
    confirmed VERIFY relation from disappearing because of model wording
    variation.
    """

    verify_requirement_ids = {
        effect.requirement_id
        for effect in analysis.requirement_effects
        if effect.relation == RequirementRelation.VERIFY
    }
    selected_ids = {item.tc_id for item in design.related_existing_tests}
    additions: list[ExistingTestSelection] = []
    changes: list[dict[str, Any]] = []
    for spec in EXISTING_REGRESSION_CATALOG:
        matched_requirements = sorted(
            verify_requirement_ids.intersection(spec.requirement_ids)
        )
        if not matched_requirements or spec.tc_id in selected_ids:
            continue
        source_condition_ids = [
            condition.condition_id
            for condition in analysis.confirmed_conditions
            if set(condition.requirement_ids).intersection(matched_requirements)
        ]
        if not source_condition_ids:
            continue
        additions.append(
            ExistingTestSelection(
                tc_id=spec.tc_id,
                source_condition_ids=list(dict.fromkeys(source_condition_ids)),
                selection_reason=(
                    "Agent 1이 VERIFY로 확정한 유지 Requirement "
                    + ", ".join(matched_requirements)
                    + "에 연결된 기존 검증 동작을 결정론적으로 회귀 확인합니다."
                ),
            )
        )
        selected_ids.add(spec.tc_id)
        changes.append(
            {
                "tc_id": spec.tc_id,
                "matched_requirement_ids": matched_requirements,
                "source_condition_ids": list(dict.fromkeys(source_condition_ids)),
                "reason": "AGENT1_VERIFY_RELATION",
            }
        )
    if not additions:
        return design, []
    catalog_order = {
        spec.tc_id: index for index, spec in enumerate(EXISTING_REGRESSION_CATALOG)
    }
    selections = sorted(
        [*design.related_existing_tests, *additions],
        key=lambda item: catalog_order[item.tc_id],
    )
    return design.model_copy(update={"related_existing_tests": selections}), changes

# ---------------------------------------------------------------------------
# Checkpoint 2: 테스트케이스 품질 검증
# ---------------------------------------------------------------------------
_FORBIDDEN_CODE = re.compile(
    r"(page\.|expect\(|pytest|playwright|def\s+test_|locator\(|assert\s+True)",
    flags=re.IGNORECASE,
)

_UNCHANGED_CONDITION = re.compile(
    r"(?:기존(?:과\s*같이)?|유지|변경\s*없|그대로)", re.IGNORECASE
)
_PROCEDURAL_SELECTION_RESULT = re.compile(
    r"선택(?:된다|되었|되어|상태)", re.IGNORECASE
)
_UI_DISPLAY_RESULT = re.compile(
    r"(?:(?:화면|\bUI\b)[^.!?]{0,80}(?:표시|보이|나타)|"
    r"(?:표시)[^.!?]{0,40}(?:된다|상태))",
    re.IGNORECASE,
)
_UI_DISPLAY_AUTHORITY = re.compile(
    r"(?:화면|\bUI\b|표시|보이|나타)", re.IGNORECASE
)


def _is_unchanged_condition(condition: ConfirmedCondition) -> bool:
    return bool(
        _UNCHANGED_CONDITION.search(
            f"{condition.statement} {condition.source_text}"
        )
    )


def evaluate_checkpoint2(
    request: ChangeRequest,
    analysis: Agent1Analysis,
    design: Agent2TestDesign,
    requirements: dict[str, SrsRequirement],
) -> Checkpoint2Result:
    checks: list[CheckResult] = []

    def add(rule_id: str, status: CheckStatus, message: str) -> None:
        checks.append(CheckResult(rule_id=rule_id, status=status, message=message))

    if design.request_id == analysis.request_id == request.request_id:
        add("CP2-001", CheckStatus.PASS, "변경 요청·Agent 1·Agent 2의 요청 ID가 일치합니다.")
    else:
        add("CP2-001", CheckStatus.FAIL, "Agent 2의 변경 요청 ID가 앞 단계 입력과 다릅니다.")

    tc_ids = [tc.tc_id for tc in design.test_cases]
    result_ids = [result.result_id for tc in design.test_cases for result in tc.expected_results]
    duplicate_tc_ids = sorted({item for item in tc_ids if tc_ids.count(item) > 1})
    duplicate_result_ids = sorted({item for item in result_ids if result_ids.count(item) > 1})
    normalized_titles = [re.sub(r"\s+", "", tc.title).casefold() for tc in design.test_cases]
    duplicate_titles = sorted(
        {
            design.test_cases[index].title
            for index, item in enumerate(normalized_titles)
            if normalized_titles.count(item) > 1
        }
    )
    if duplicate_tc_ids or duplicate_result_ids or duplicate_titles:
        add("CP2-002", CheckStatus.FAIL, "TC·기대 결과 ID 또는 제목이 중복됩니다.")
    else:
        add("CP2-002", CheckStatus.PASS, "TC·기대 결과 ID와 제목이 고유합니다.")

    known_conditions = {item.condition_id: item for item in analysis.confirmed_conditions}
    requirement_relations = {
        item.requirement_id: item.relation for item in analysis.requirement_effects
    }
    active_requirements = {
        item.requirement_id
        for item in analysis.requirement_effects
        if item.relation != RequirementRelation.NO_IMPACT
    }
    referenced_requirements = {
        item for tc in design.test_cases for item in tc.requirement_ids
    }
    candidate_conditions = {
        item for tc in design.test_cases for item in tc.source_condition_ids
    }
    existing_conditions = {
        item
        for selection in design.related_existing_tests
        for item in selection.source_condition_ids
    }
    referenced_conditions = candidate_conditions | existing_conditions
    selected_existing_specs = [
        EXISTING_REGRESSION_BY_ID[item.tc_id]
        for item in design.related_existing_tests
        if item.tc_id in EXISTING_REGRESSION_BY_ID
    ]
    covered_requirements = referenced_requirements | {
        requirement_id
        for spec in selected_existing_specs
        for requirement_id in spec.requirement_ids
    }
    unknown_requirements = sorted(
        (referenced_requirements - requirements.keys())
        | (referenced_requirements - active_requirements)
    )
    unknown_conditions = sorted(referenced_conditions - known_conditions.keys())
    if unknown_requirements or unknown_conditions:
        add("CP2-003", CheckStatus.FAIL, "입력 범위 밖 Requirement 또는 Condition을 참조했습니다.")
    else:
        add("CP2-003", CheckStatus.PASS, "모든 추적 ID가 승인된 입력 범위에 존재합니다.")

    missing_conditions = sorted(known_conditions.keys() - referenced_conditions)
    if missing_conditions:
        add("CP2-004", CheckStatus.FAIL, "변경 후보 또는 관련 기존 TC에 반영되지 않은 확정 조건: " + ", ".join(missing_conditions))
    else:
        add("CP2-004", CheckStatus.PASS, "Agent 1의 모든 확정 조건을 변경 후보 또는 관련 기존 TC가 반영합니다.")

    trace_errors: list[str] = []
    for tc in design.test_cases:
        tc_condition_ids = set(tc.source_condition_ids)
        condition_requirement_ids = {
            req_id
            for condition_id in tc_condition_ids
            if condition_id in known_conditions
            for req_id in known_conditions[condition_id].requirement_ids
        }
        if not set(tc.requirement_ids).issubset(condition_requirement_ids):
            trace_errors.append(tc.tc_id)
            continue
        if any(
            not set(expected.source_condition_ids).issubset(tc_condition_ids)
            for expected in tc.expected_results
        ):
            trace_errors.append(tc.tc_id)
    if trace_errors:
        add(
            "CP2-005",
            CheckStatus.FAIL,
            "TC 내부 Requirement·Condition·기대 결과 추적이 끊겼습니다: "
            + ", ".join(sorted(set(trace_errors))),
        )
    else:
        add("CP2-005", CheckStatus.PASS, "TC 내부 추적성이 유지됩니다.")

    state_errors: list[str] = []
    notify_errors: list[str] = []
    compound_ui_errors: list[str] = []
    ui_observation_groups = {
        "mode": re.compile(
            r"(?:(?:화면|UI|관제\s*패널)[^.!?]{0,60}(?:표시[^.!?]{0,30})?(?:모드|\bmode\b)\s*(?:는|가|값|상태|[:=])|(?:모드|\bmode\b)\s*(?:표시|값|상태))",
            re.IGNORECASE,
        ),
        "temperature": re.compile(r"(?:설정\s*온도|\bsetTemp\b)", re.IGNORECASE),
        "pending": re.compile(r"(?:대기값|대기\s*상태|\bpending\b)", re.IGNORECASE),
        "control_state": re.compile(r"(?:버튼|컨트롤|활성|비활성|\bdisabled\b|\benabled\b)", re.IGNORECASE),
    }
    for tc in design.test_cases:
        source_requirements = {
            req_id
            for condition_id in tc.source_condition_ids
            if condition_id in known_conditions
            for req_id in known_conditions[condition_id].requirement_ids
        }
        layers = {result.observation_layer for result in tc.expected_results}
        requires_double_assert = (
            "REQ-STATE-001" in source_requirements
            or tc.test_type == TcType.STATE_CONSISTENCY
        )
        if requires_double_assert and not {
            ObservationLayer.UI,
            ObservationLayer.INTERNAL_STATE,
        }.issubset(layers):
            state_errors.append(tc.tc_id)
        if "REQ-NOTIFY-001" in source_requirements and ObservationLayer.NOTIFICATION not in layers:
            notify_errors.append(tc.tc_id)
        for result in tc.expected_results:
            if result.observation_layer != ObservationLayer.UI:
                continue
            matched_groups = [
                name
                for name, pattern in ui_observation_groups.items()
                if pattern.search(result.statement)
            ]
            if len(matched_groups) > 1:
                compound_ui_errors.append(
                    f"{tc.tc_id}/{result.result_id}:" + ",".join(matched_groups)
                )
    policy_errors: list[str] = []
    for tc in design.test_cases:
        layers = {result.observation_layer for result in tc.expected_results}
        requires_double_assert = (
            "REQ-STATE-001" in tc.requirement_ids
            or tc.test_type == TcType.STATE_CONSISTENCY
        )
        if requires_double_assert and tc.double_assert_policy != DoubleAssertPolicy.REQUIRED:
            policy_errors.append(f"{tc.tc_id}:필수 이중 검증 정책 누락")
        elif tc.double_assert_policy == DoubleAssertPolicy.REQUIRED and not {
            ObservationLayer.UI,
            ObservationLayer.INTERNAL_STATE,
        }.issubset(layers):
            policy_errors.append(f"{tc.tc_id}:UI·내부 상태 결과 누락")
        elif tc.double_assert_policy == DoubleAssertPolicy.UI_ONLY and (
            ObservationLayer.UI not in layers or ObservationLayer.INTERNAL_STATE in layers
        ):
            policy_errors.append(f"{tc.tc_id}:UI_ONLY 계층 불일치")
        elif tc.double_assert_policy == DoubleAssertPolicy.INTERNAL_ONLY and (
            ObservationLayer.INTERNAL_STATE not in layers or ObservationLayer.UI in layers
        ):
            policy_errors.append(f"{tc.tc_id}:INTERNAL_ONLY 계층 불일치")
        if (
            tc.double_assert_policy != DoubleAssertPolicy.REQUIRED
            and not tc.double_assert_reason
        ):
            policy_errors.append(f"{tc.tc_id}:이중 검증 예외 사유 누락")
    if state_errors or policy_errors or compound_ui_errors:
        details = [*state_errors, *policy_errors]
        details.extend(
            f"{item}:UI 기대 결과를 관찰값별로 분리 필요"
            for item in compound_ui_errors
        )
        add(
            "CP2-006",
            CheckStatus.FAIL,
            "조건부 이중 검증 또는 원자적 기대 결과 계약이 맞지 않습니다: " + ", ".join(details),
        )
    else:
        add(
            "CP2-006",
            CheckStatus.PASS,
            "상태 관련 TC의 이중 검증·예외 정책과 원자적 UI 기대 결과가 일치합니다.",
        )
    if notify_errors:
        add("CP2-007", CheckStatus.FAIL, "알림 기대 결과가 누락된 TC: " + ", ".join(notify_errors))
    else:
        add("CP2-007", CheckStatus.PASS, "알림 조건이 NOTIFICATION 결과로 연결됩니다.")

    path_errors: list[str] = []
    for tc in design.test_cases:
        if tc.control_path != ControlPath.CENTRAL:
            path_errors.append(f"{tc.tc_id}:현재 V2는 중앙 관제 패널(CENTRAL) 경로만 허용")
        if any(req_id.startswith("REQ-LOCAL-") for req_id in tc.requirement_ids):
            path_errors.append(f"{tc.tc_id}:현재 SRS 범위 밖 REQ-LOCAL 참조")
    candidate_required_requirements = {
        requirement_id
        for requirement_id, relation in requirement_relations.items()
        if relation in {
            RequirementRelation.MODIFIED,
            RequirementRelation.UPDATE_REQUIRED,
        }
    }
    if "REQ-CONTROL-001" in candidate_required_requirements and not any(
        tc.control_path == ControlPath.CENTRAL and "REQ-CONTROL-001" in tc.requirement_ids
        for tc in design.test_cases
    ):
        path_errors.append("REQ-CONTROL-001 중앙 제어 TC 누락")
    required_change_paths: list[tuple[str, ControlPath]] = []
    if "REQ-CONTROL-001" in candidate_required_requirements:
        required_change_paths.append(("REQ-CONTROL-001", ControlPath.CENTRAL))
    for requirement_id, control_path in required_change_paths:
        if not any(
            tc.purpose == TcPurpose.CHANGE_VALIDATION
            and tc.control_path == control_path
            and request.target_requirement_id in tc.requirement_ids
            and requirement_id in tc.requirement_ids
            for tc in design.test_cases
        ):
            path_errors.append(f"{control_path.value} 경로의 직접 변경 검증 TC 누락")
    uncovered_requirements = sorted(active_requirements - covered_requirements)
    target_change_tests = [
        tc
        for tc in design.test_cases
        if request.target_requirement_id in tc.requirement_ids
        and tc.purpose == TcPurpose.CHANGE_VALIDATION
    ]
    if uncovered_requirements or not target_change_tests or path_errors:
        details = []
        if uncovered_requirements:
            details.append("미포함 Requirement=" + ",".join(uncovered_requirements))
        if not target_change_tests:
            details.append("대상 변경 검증 TC 없음")
        details.extend(path_errors)
        add("CP2-008", CheckStatus.FAIL, "변경 범위 또는 제어 경로가 불완전합니다: " + "; ".join(details))
    else:
        add("CP2-008", CheckStatus.PASS, "변경 후보와 영향받는 기존 회귀 Requirement가 중앙 관제 패널 경로로 연결됩니다.")

    text_fields = [
        value
        for tc in design.test_cases
        for value in [
            tc.title,
            *tc.preconditions,
            *tc.steps,
            *(result.statement for result in tc.expected_results),
            *tc.restore_steps,
            tc.automation_reason,
        ]
    ]
    if any(_FORBIDDEN_CODE.search(value) for value in text_fields):
        add("CP2-009", CheckStatus.FAIL, "제품 TC에 자동화 코드 또는 금지 표현이 섞였습니다.")
    else:
        add("CP2-009", CheckStatus.PASS, "제품 TC와 자동화 구현의 역할이 분리됐습니다.")

    test_data_errors = [
        tc.tc_id
        for tc in design.test_cases
        if tc.test_type == TcType.BOUNDARY
        and tc.test_data.requested_mode is None
        and not tc.test_data.requested_modes
        and tc.test_data.requested_temperature_c is None
        and not tc.test_data.requested_temperatures_c
    ]
    if test_data_errors:
        add(
            "CP2-010",
            CheckStatus.FAIL,
            "경계 TC의 구조화된 요청 모드 또는 온도 시험 데이터가 없습니다: "
            + ", ".join(test_data_errors),
        )
    else:
        add("CP2-010", CheckStatus.PASS, "실행에 필요한 대상 역할과 시험 데이터가 구조화됐습니다.")

    if design.human_review_notes:
        add(
            "CP2-011",
            CheckStatus.REVIEW,
            "기대 결과를 확정할 수 없어 실행을 멈춘 확인 사항이 있습니다: "
            + " / ".join(design.human_review_notes),
        )
    else:
        note_count = len(design.coverage_notes) + len(design.final_review_notes)
        if note_count:
            add(
                "CP2-011",
                CheckStatus.PASS,
                "후속 자동 실행을 막지 않는 참고·최종 검토 사항 "
                f"{note_count}건을 기록했습니다.",
            )
        else:
            add("CP2-011", CheckStatus.PASS, "추가 의미 판단이 필요한 항목이 없습니다.")

    tier_errors: list[str] = []
    expected_common_by_type = {
        TcType.NORMAL: CommonQaCriterion.NORMAL_FLOW,
        TcType.BOUNDARY: CommonQaCriterion.BOUNDARY_VALUE,
        TcType.EXCEPTION: CommonQaCriterion.EXCEPTION_HANDLING,
    }
    for tc in design.test_cases:
        expected_common = expected_common_by_type.get(tc.test_type)
        if not tc.common_qa_criteria or (
            expected_common is not None and expected_common not in tc.common_qa_criteria
        ):
            tier_errors.append(f"{tc.tc_id}:1단계 공통 QA 기준")
        if not tc.domain_qa_criteria:
            tier_errors.append(f"{tc.tc_id}:2단계 도메인 QA 기준")
        if (
            not tc.feature_requirement_ids
            or not set(tc.feature_requirement_ids).issubset(set(tc.requirement_ids))
        ):
            tier_errors.append(f"{tc.tc_id}:3단계 기능 기준 Requirement")
        if (
            tc.test_type == TcType.STATE_CONSISTENCY
            and DomainQaCriterion.UI_INTERNAL_STATE_CONSISTENCY
            not in tc.domain_qa_criteria
        ):
            tier_errors.append(f"{tc.tc_id}:상태 정합성 도메인 기준")
    if tier_errors:
        add(
            "CP2-012",
            CheckStatus.FAIL,
            "3단계 QA 기준 적용 근거가 누락되거나 TC 추적 범위와 다릅니다: "
            + ", ".join(tier_errors),
        )
    else:
        add("CP2-012", CheckStatus.PASS, "모든 TC에 공통·도메인·기능별 QA 기준이 추적됩니다.")

    dependency_pattern = re.compile(
        r"(?:이전|앞선|선행)\s*(?:TC|테스트)|TC-CAND-\d{3}",
        re.IGNORECASE,
    )
    non_dependency_pattern = re.compile(
        r"(?:의존|필요|전제|이어받)[^.!?\n]{0,16}(?:않|없)|없이|무관|독립",
        re.IGNORECASE,
    )
    independence_errors: list[str] = []
    for tc in design.test_cases:
        dependency_texts = [
            *tc.preconditions,
            *tc.steps,
            *tc.restore_steps,
            tc.independence_reason or "",
        ]
        has_cross_tc_dependency = any(
            dependency_pattern.search(text)
            and not non_dependency_pattern.search(text)
            for text in dependency_texts
        )
        if (
            not tc.independent_execution
            or not tc.independence_reason
            or has_cross_tc_dependency
        ):
            independence_errors.append(tc.tc_id)
    if independence_errors:
        add(
            "CP2-013",
            CheckStatus.FAIL,
            "단독 실행 근거가 없거나 다른 TC에 의존합니다: "
            + ", ".join(independence_errors),
        )
    else:
        add("CP2-013", CheckStatus.PASS, "모든 TC가 초기 조건과 복원 기준을 가진 독립 실행 단위입니다.")

    excluded_scope_matches = {
        _normalize(item) for item in design.excluded_scope
    } == {_normalize(item) for item in analysis.excluded_scope}
    excluded_gaps_match = {
        _normalize(item) for item in design.excluded_information_gaps
    } == {_normalize(item) for item in analysis.excluded_information_gaps}
    if not excluded_scope_matches or not excluded_gaps_match:
        add(
            "CP2-014",
            CheckStatus.FAIL,
            "Agent 1의 제외 범위 또는 정보 부족이 Agent 2 제외 목록에 그대로 인계되지 않았습니다.",
        )
    else:
        add(
            "CP2-014",
            CheckStatus.PASS,
            f"실행 제외 범위 {len(design.excluded_scope)}건과 정보 부족 {len(design.excluded_information_gaps)}건을 보존했습니다.",
        )

    grouping_errors: list[str] = []
    for tc in design.test_cases:
        data = tc.test_data
        plural_values_used = bool(
            data.requested_modes or data.requested_temperatures_c
        )
        if len(data.requested_modes) != len(set(data.requested_modes)):
            grouping_errors.append(f"{tc.tc_id}:requested_modes 중복")
        normalized_temperatures = [float(value) for value in data.requested_temperatures_c]
        if len(normalized_temperatures) != len(set(normalized_temperatures)):
            grouping_errors.append(f"{tc.tc_id}:requested_temperatures_c 중복")

        grouped = _is_grouped_test_case(tc)
        hvac_values_changed = bool(
            data.requested_mode
            or data.requested_modes
            or data.requested_temperature_c is not None
            or data.requested_temperatures_c
        )
        dynamic_restore_text = " ".join(tc.restore_steps)
        if data.restore_observed_hvac_state:
            if not grouped:
                grouping_errors.append(
                    f"{tc.tc_id}:실행 전 HVAC 상태 저장·복원은 묶음 TC에서만 허용"
                )
            if not tc.restore_required or not hvac_values_changed:
                grouping_errors.append(
                    f"{tc.tc_id}:상태 변경과 최종 복원이 없는 동적 HVAC 복원 표시"
                )
            if data.initial_mode is not None or data.initial_temperature_c is not None:
                grouping_errors.append(
                    f"{tc.tc_id}:동적 HVAC 복원과 고정 초기값을 함께 사용"
                )
            if not (
                _contains_any(dynamic_restore_text, ("실행 직전", "관찰", "observed"))
                and _contains_any(dynamic_restore_text, ("모드", "mode"))
                and _contains_any(dynamic_restore_text, ("온도", "temperature"))
                and _contains_any(dynamic_restore_text, ("복원", "restore"))
                and _contains_any(dynamic_restore_text, ("적용", "apply"))
            ):
                grouping_errors.append(
                    f"{tc.tc_id}:동적 HVAC 복원 절차에 저장 대상·복원·적용 의미 누락"
                )
        elif (
            grouped
            and tc.restore_required
            and hvac_values_changed
            and data.initial_mode is None
            and data.initial_temperature_c is None
        ):
            grouping_errors.append(
                f"{tc.tc_id}:고정 초기값이 없는 묶음 HVAC TC의 실행 전 상태 저장·복원 표시 누락"
            )
        if plural_values_used and not grouped:
            grouping_errors.append(f"{tc.tc_id}:복수 조건인데 condition_execution=SINGLE_FLOW")
        if not grouped:
            if tc.grouping_reason or tc.intermediate_reset_steps:
                grouping_errors.append(f"{tc.tc_id}:단일 흐름에 묶음 근거 또는 중간 초기화가 있음")
            continue

        if not tc.grouping_reason:
            grouping_errors.append(f"{tc.tc_id}:동일 업무 규칙 묶음 근거 누락")
        invalid_reset_steps = [
            step for step in tc.intermediate_reset_steps if step not in tc.steps
        ]
        if invalid_reset_steps:
            grouping_errors.append(f"{tc.tc_id}:steps에 없는 중간 초기화 절차")
        if (
            tc.condition_execution == ConditionExecution.INDEPENDENT_VARIANTS
            and not tc.intermediate_reset_steps
        ):
            grouping_errors.append(f"{tc.tc_id}:독립 조건 사이 초기화 절차 누락")

        verification_steps = [
            result.verify_after_step for result in tc.expected_results
        ]
        if any(step is None or step not in tc.steps for step in verification_steps):
            grouping_errors.append(f"{tc.tc_id}:기대 결과의 조건별 판정 단계 누락 또는 불일치")
        elif len(set(verification_steps)) < 2:
            grouping_errors.append(f"{tc.tc_id}:모든 조건 결과를 마지막 한 단계에서만 판정")

        procedure_text = " ".join([*tc.preconditions, *tc.steps])
        for mode in data.requested_modes:
            if not _contains(procedure_text, mode):
                grouping_errors.append(f"{tc.tc_id}:절차에 없는 요청 모드 {mode}")
        procedure_numbers = {
            float(value) for value in re.findall(r"-?\d+(?:\.\d+)?", procedure_text)
        }
        for temperature in data.requested_temperatures_c:
            if float(temperature) not in procedure_numbers:
                grouping_errors.append(
                    f"{tc.tc_id}:절차에 없는 요청 온도 {temperature:g}"
                )

    if grouping_errors:
        add(
            "CP2-015",
            CheckStatus.FAIL,
            "동일 업무 규칙 묶음 TC의 조건별 실행·판정 계약이 맞지 않습니다: "
            + ", ".join(grouping_errors),
        )
    else:
        add(
            "CP2-015",
            CheckStatus.PASS,
            "같은 업무 규칙의 조건 묶음과 조건별 판정·초기화 계약이 일치합니다.",
        )

    existing_selection_errors: list[str] = []
    selected_existing_ids = [item.tc_id for item in design.related_existing_tests]
    duplicate_existing_ids = sorted(
        {
            item
            for item in selected_existing_ids
            if selected_existing_ids.count(item) > 1
        }
    )
    if duplicate_existing_ids:
        existing_selection_errors.append(
            "중복 기존 TC=" + ",".join(duplicate_existing_ids)
        )
    unknown_existing_ids = sorted(
        set(selected_existing_ids) - EXISTING_REGRESSION_BY_ID.keys()
    )
    if unknown_existing_ids:
        existing_selection_errors.append(
            "카탈로그 밖 기존 TC=" + ",".join(unknown_existing_ids)
        )
    for selection in design.related_existing_tests:
        spec = EXISTING_REGRESSION_BY_ID.get(selection.tc_id)
        if spec is None:
            continue
        for condition_id in selection.source_condition_ids:
            condition = known_conditions.get(condition_id)
            if condition is None:
                existing_selection_errors.append(
                    f"{selection.tc_id}:입력 밖 조건 {condition_id}"
                )
            elif not set(condition.requirement_ids).intersection(spec.requirement_ids):
                existing_selection_errors.append(
                    f"{selection.tc_id}:{condition_id} Requirement 근거 불일치"
                )
    regenerated_regressions = [
        tc.tc_id
        for tc in design.test_cases
        if tc.purpose != TcPurpose.CHANGE_VALIDATION
    ]
    if regenerated_regressions:
        existing_selection_errors.append(
            "기존 회귀를 신규 후보로 재작성=" + ",".join(regenerated_regressions)
        )
    verify_only_candidates = [
        tc.tc_id
        for tc in design.test_cases
        if tc.requirement_ids
        and all(
            requirement_relations.get(requirement_id)
            == RequirementRelation.VERIFY
            for requirement_id in tc.requirement_ids
        )
    ]
    if verify_only_candidates:
        existing_selection_errors.append(
            "VERIFY 유지 동작을 신규 후보로 중복 생성="
            + ",".join(verify_only_candidates)
        )
    direct_change_condition_ids = {
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if condition.source_type == ConditionSource.CHANGE_REQUEST
        and not _is_unchanged_condition(condition)
    }
    misrouted_change_conditions = sorted(
        direct_change_condition_ids - candidate_conditions
    )
    if misrouted_change_conditions:
        existing_selection_errors.append(
            "변경 조건의 신규·수정 후보 누락="
            + ",".join(misrouted_change_conditions)
        )
    if not design.existing_tc_comparison_completed:
        existing_selection_errors.append("기존 TC 대조 완료 표시 누락")
    if existing_selection_errors:
        add(
            "CP2-016",
            CheckStatus.FAIL,
            "변경분 후보와 관련 기존 TC 분리가 맞지 않습니다: "
            + "; ".join(existing_selection_errors),
        )
    else:
        add(
            "CP2-016",
            CheckStatus.PASS,
            "변경된 조건만 신규·수정 후보로 만들고 유지 조건은 기존 TC 선택으로 분리했습니다.",
        )

    minimality_errors: list[str] = []
    scope_limit_condition_ids = {
        condition.condition_id
        for condition in analysis.confirmed_conditions
        if condition.source_type == ConditionSource.CHANGE_REQUEST
        and _is_scope_exclusion_text(
            f"{condition.statement} {condition.source_text}"
        )
    }
    for tc in design.test_cases:
        for result in tc.expected_results:
            result_condition_ids = set(result.source_condition_ids)
            excluded_sources = sorted(
                result_condition_ids & scope_limit_condition_ids
            )
            if excluded_sources:
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:제외 조건을 기대 결과로 사용="
                    + ",".join(excluded_sources)
                )
            if (
                request.target_requirement_id != "REQ-SELECT-001"
                and result.observation_layer == ObservationLayer.UI
                and _PROCEDURAL_SELECTION_RESULT.search(result.statement)
            ):
                minimality_errors.append(
                    f"{tc.tc_id}/{result.result_id}:준비용 장비 선택을 제품 기대 결과로 확장"
                )
            if (
                result.observation_layer == ObservationLayer.UI
                and _UI_DISPLAY_RESULT.search(result.statement)
            ):
                source_authority = " ".join(
                    known_conditions[condition_id].source_text
                    for condition_id in result.source_condition_ids
                    if condition_id in known_conditions
                )
                if not _UI_DISPLAY_AUTHORITY.search(source_authority):
                    minimality_errors.append(
                        f"{tc.tc_id}/{result.result_id}:Condition 원문에 없는 UI 표시 기대"
                    )
    if minimality_errors:
        add(
            "CP2-017",
            CheckStatus.FAIL,
            "변경 요구 범위를 넘어선 기대 결과가 있습니다: "
            + "; ".join(minimality_errors),
        )
    else:
        add(
            "CP2-017",
            CheckStatus.PASS,
            "제품 기대 결과가 긍정적 변경 조건과 원문 UI 근거 범위 안에 있습니다.",
        )

    statuses = {item.status for item in checks}
    if CheckStatus.ERROR in statuses:
        status = CheckStatus.ERROR
    elif CheckStatus.FAIL in statuses:
        status = CheckStatus.FAIL
    elif CheckStatus.REVIEW in statuses:
        status = CheckStatus.REVIEW
    else:
        status = CheckStatus.PASS
    return Checkpoint2Result(status=status, checks=checks)

# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Agent 3: Evidence-grounded automation planning
# ---------------------------------------------------------------------------
AGENT3_SYSTEM_INSTRUCTIONS = """
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
   device exists, is visible, error-free, and unlocked, treat those baseline preconditions as satisfied and never demand
   another selector or action for them. A mode or temperature value read from the target device in ui_observation.harness_values
   also satisfies the same initial_mode or initial_temperature_c precondition. Values that differ from the observed clean state
   still need approved setup actions.
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
   assertion until the final condition. For a single-flow TC, after_action_id may be omitted and assertions run at the end.
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
                "Keep all TC semantics and values unchanged; fix only the reported technical plan issues."
            )
        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
                prompt_cache_key="qa-v2-agent3-3-17",
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
                const device = devices.find(item => item && item.id === 1) || devices[0];
                if (!device || typeof device !== 'object') return null;
                return {
                    status: typeof device.status === 'string' ? device.status : null,
                    locked: typeof device.locked === 'boolean' ? device.locked : null,
                    errorCode: device.errorCode ?? null,
                };
            }"""
        )
        state_available = isinstance(primary_state, dict)
        error_free = (
            primary_state.get("status") != "ERROR"
            and primary_state.get("errorCode") is None
            if state_available
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
        device_state_fields: list[str] = []
        if "devices" in available_harness_keys:
            device_state_fields = page.evaluate(
                """() => {
                    const devices = window.__vccs && Array.isArray(window.__vccs.devices)
                        ? window.__vccs.devices : [];
                    const fields = new Set();
                    for (const device of devices) {
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
        raise Agent3Error("Required automation interfaces are missing from the observed UI: " + " / ".join(details))
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


def _contains_any(value: str, terms: tuple[str, ...]) -> bool:
    normalized = value.casefold()
    return any(term.casefold() in normalized for term in terms)


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
        positive = ("true", "on", "checked", "enabled", "활성", "켜", "선택")
        negative = ("false", "off", "unchecked", "disabled", "비활성", "꺼", "해제")
        return _contains_any(source_text, positive if value else negative)
    if isinstance(value, (int, float)):
        return float(value) in {
            float(item) for item in re.findall(r"-?\d+(?:\.\d+)?", source_text)
        }
    return _contains(source_text, str(value))


def evaluate_checkpoint3_plan(
    test_case: ProductTestCaseCandidate,
    plan: Agent3AutomationPlan,
    observation: UiObservation,
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
        if _is_grouped_test_case(test_case) and assertion.after_action_id is None:
            anchoring_errors.append(
                f"{assertion.result_id}: grouped-condition assertion has no after_action_id"
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
        if assertion.strategy == AssertionStrategy.UI_TEXT_CONTAINS:
            if not assertion.expected_text or not _contains(
                result.statement, assertion.expected_text
            ):
                fidelity_errors.append(
                    f"{assertion.result_id}: expected text is not grounded in the Expected Result"
                )
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
                if not _has_textual_link(observed_meaning, result.statement):
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
            if assertion.strategy in _GENERIC_ASSERTION_STRATEGIES
            and assertion.observation_layer != ObservationLayer.NOTIFICATION
        ]
        if generic_plan and restore_actions
        else []
    )
    lines = [
        "from __future__ import annotations",
        "",
        "import os",
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
            lines.append(f"{indent}page.wait_for_timeout(100)")
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

    for action_id, block in action_blocks:
        lines.extend(block)
        for after_action_id, assertion_block in assertion_blocks:
            if after_action_id == action_id:
                lines.extend(assertion_block)
    for after_action_id, assertion_block in assertion_blocks:
        if after_action_id is None:
            lines.extend(assertion_block)

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
            if action.action_type == AutomationActionType.APPLY_COMMANDS:
                lines.append("                page.wait_for_timeout(100)")
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
                    "                page.wait_for_timeout(100)",
                ]
            )
        else:
            lines.append(
                f"                _set_temperature(page, {float(action.value)})"
            )
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
            if any(module not in {"__future__", "os", "re", "pathlib", "playwright"} for module in modules):
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

# CLI
# ---------------------------------------------------------------------------
DEFAULT_SRS = Path("docs") / "01_PRODUCT_SRS.md"
DEFAULT_RUNS_ROOT = Path("runs")
_RUN_ID_PATTERN = re.compile(r"^RUN-\d{8}-\d{6}-[A-F0-9]{6}$")


def _read_request(path: Path) -> ChangeRequest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ChangeRequest.model_validate(payload)
    except FileNotFoundError as exc:
        raise ValueError(f"변경 요청 파일을 찾을 수 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"변경 요청 JSON 형식이 잘못됐습니다: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"변경 요청 Schema 검증에 실패했습니다:\n{exc}") from exc


def _read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"필수 실행 산출물을 찾을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"실행 산출물 JSON 형식이 잘못됐습니다: {path.name}\n{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"실행 산출물은 JSON 객체여야 합니다: {path.name}")
    return payload


def _read_json_model(path: Path, model_type):
    try:
        return model_type.model_validate(_read_json_payload(path))
    except ValidationError as exc:
        raise ValueError(f"실행 산출물 Schema 검증에 실패했습니다: {path.name}\n{exc}") from exc


def _resolve_run_dir(runs_root: Path, run_id: str) -> Path:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Run ID 형식이 올바르지 않습니다.")
    root = runs_root.resolve()
    run_dir = (root / run_id).resolve()
    try:
        run_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("Run ID가 runs 폴더 밖을 가리킬 수 없습니다.") from exc
    if not run_dir.is_dir():
        raise ValueError(f"Run 폴더를 찾을 수 없습니다: {run_dir}")
    return run_dir


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"RUN-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _write_json(path: Path, payload: Any) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sha256(path: Path, expected: Any, label: str) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"run_manifest의 {label} SHA-256 값이 올바르지 않습니다.")
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} 파일이 Agent 1 실행 후 변경되어 Agent 2를 차단했습니다.")


def run_agent1(args: argparse.Namespace) -> int:
    request_path = Path(args.request).resolve()
    srs_path = Path(args.srs).resolve()
    request = _read_request(request_path)
    requirements = load_srs_requirements(srs_path)
    srs_text = srs_path.read_text(encoding="utf-8")
    agent = OpenAIAgent1(model=args.model)
    run_id = getattr(args, "run_id", None) or _new_run_id()
    run_dir = Path(args.runs_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    request_file = run_dir / "request.json"
    srs_snapshot_file = run_dir / "srs_snapshot.md"
    analysis_file = run_dir / "agent1_change_analysis.json"
    checkpoint_file = run_dir / "checkpoint1.json"
    _write_json(request_file, request.model_dump(mode="json"))
    _write_text_atomic(srs_snapshot_file, srs_text)
    try:
        response = agent.analyze(request, requirements)
        checkpoint = evaluate_checkpoint1(request, response.analysis, requirements)
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint.status.value,
                "handoff_status": checkpoint.handoff_status.value,
                "model": response.model,
                "usage": response.usage,
            }
        ]
        if checkpoint.status == CheckStatus.FAIL:
            _write_json(
                run_dir / "agent1_change_analysis_attempt_1.json",
                response.analysis.model_dump(mode="json"),
            )
            _write_json(
                run_dir / "checkpoint1_attempt_1.json",
                checkpoint.model_dump(mode="json", by_alias=True),
            )
            response = agent.analyze(
                request,
                requirements,
                previous_analysis=response.analysis,
                checkpoint_feedback=[
                    item.message
                    for item in checkpoint.checks
                    if item.status == CheckStatus.FAIL
                ],
            )
            checkpoint = evaluate_checkpoint1(request, response.analysis, requirements)
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint.status.value,
                    "handoff_status": checkpoint.handoff_status.value,
                    "model": response.model,
                    "usage": response.usage,
                }
            )

        _write_json(analysis_file, response.analysis.model_dump(mode="json"))
        _write_json(checkpoint_file, checkpoint.model_dump(mode="json"))
        _write_json(
            run_dir / "run_manifest.json",
            {
                "contract_version": "2.4",
                "prompt_version": "agent1-2.3",
                "run_id": run_id,
                "stage": "AGENT_1_CP1",
                "status": checkpoint.status.value,
                "handoff_status": checkpoint.handoff_status.value,
                "model": response.model,
                "usage": _aggregate_model_usage(attempts),
                "final_attempt_usage": response.usage,
                "attempts": attempts,
                "request_file": request_file.name,
                "request_sha256": _sha256_file(request_file),
                "srs_snapshot_file": srs_snapshot_file.name,
                "srs_sha256": _sha256_file(srs_snapshot_file),
                "agent1_analysis_sha256": _sha256_file(analysis_file),
                "checkpoint1_sha256": _sha256_file(checkpoint_file),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        _write_json(
            run_dir / "run_error.json",
            {
                "run_id": run_id,
                "stage": "AGENT_1_CP1",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"실행 실패: {exc}\n기록 위치: {run_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {run_id}")
    print(f"Agent 1 model: {response.model}")
    print(f"Checkpoint 1: {checkpoint.status.value}")
    print(f"Agent 2 handoff: {checkpoint.handoff_status.value}")
    print(f"결과 위치: {run_dir}")
    return 0 if checkpoint.handoff_status == HandoffStatus.CONTINUE else 2


def _load_verified_agent1_run(run_dir: Path, run_id: str) -> tuple[
    ChangeRequest,
    dict[str, SrsRequirement],
    Agent1Analysis,
    Checkpoint1Result,
    dict[str, Any],
]:
    manifest_file = run_dir / "run_manifest.json"
    manifest = _read_json_payload(manifest_file)
    if manifest.get("run_id") != run_id or manifest.get("stage") != "AGENT_1_CP1":
        raise ValueError("run_manifest가 요청한 Agent 1 Run과 일치하지 않습니다.")
    if manifest.get("status") not in {
        CheckStatus.PASS.value,
        CheckStatus.REVIEW.value,
    }:
        raise ValueError(f"Checkpoint 1이 {manifest.get('status')}이므로 Agent 2를 실행할 수 없습니다.")
    if manifest.get("handoff_status") != HandoffStatus.CONTINUE.value:
        raise ValueError(
            f"Agent 2 인계 상태가 {manifest.get('handoff_status')}이므로 실행을 계속할 수 없습니다."
        )

    request_file = run_dir / "request.json"
    srs_snapshot_file = run_dir / "srs_snapshot.md"
    analysis_file = run_dir / "agent1_change_analysis.json"
    checkpoint_file = run_dir / "checkpoint1.json"
    _verify_sha256(request_file, manifest.get("request_sha256"), "변경 요청")
    _verify_sha256(srs_snapshot_file, manifest.get("srs_sha256"), "SRS 스냅샷")
    _verify_sha256(analysis_file, manifest.get("agent1_analysis_sha256"), "Agent 1 분석")
    _verify_sha256(checkpoint_file, manifest.get("checkpoint1_sha256"), "Checkpoint 1")

    request = _read_request(request_file)
    requirements = load_srs_requirements(srs_snapshot_file)
    analysis = _read_json_model(analysis_file, Agent1Analysis)
    checkpoint = _read_json_model(checkpoint_file, Checkpoint1Result)
    recomputed = evaluate_checkpoint1(request, analysis, requirements)
    if recomputed.model_dump(mode="json") != checkpoint.model_dump(mode="json"):
        raise ValueError("현재 CP1 규칙으로 재검증한 결과가 저장된 Checkpoint 1과 다릅니다.")
    if checkpoint.status not in {CheckStatus.PASS, CheckStatus.REVIEW} or checkpoint.handoff_status != HandoffStatus.CONTINUE:
        raise ValueError("Checkpoint 1이 Agent 2 실행을 허용하지 않습니다.")
    return request, requirements, analysis, checkpoint, manifest


def run_agent2(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    reservation_file = run_dir / "agent2_in_progress.json"
    immutable_outputs = [
        run_dir / "agent2_test_design.json",
        run_dir / "checkpoint2.json",
        run_dir / "agent2_manifest.json",
        run_dir / "agent2_technical_id_normalization.json",
        run_dir / "agent2_regression_selection_normalization.json",
        reservation_file,
    ]
    if any(path.exists() for path in immutable_outputs):
        raise ValueError("이 Run에는 Agent 2 산출물 또는 진행 표시가 이미 존재합니다. 새 Agent 1 Run을 사용하세요.")
    request, requirements, analysis, _, source_manifest = _load_verified_agent1_run(
        run_dir, args.run_id
    )
    try:
        with reservation_file.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": args.run_id,
                    "stage": "AGENT_2_CP2",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError("이 Run의 Agent 2가 이미 진행 중입니다. 새 Agent 1 Run을 사용하세요.") from exc

    agent = OpenAIAgent2(model=args.model)
    try:
        response = agent.design(request, analysis, requirements)
        raw_design = response.design
        normalized_design, first_normalizations = _normalize_agent2_technical_ids(
            raw_design
        )
        normalized_design, first_regression_normalizations = (
            _normalize_agent2_verify_regressions(analysis, normalized_design)
        )
        normalization_attempts: list[dict[str, Any]] = []
        regression_normalization_attempts: list[dict[str, Any]] = []
        if first_normalizations:
            raw_file = run_dir / "agent2_test_design_model_raw_attempt_1.json"
            _write_json(
                raw_file,
                raw_design.model_dump(mode="json", by_alias=True),
            )
            normalization_attempts.append(
                {
                    "attempt": 1,
                    "raw_design_file": raw_file.name,
                    "raw_design_sha256": _sha256_file(raw_file),
                    "changes": first_normalizations,
                }
            )
            response = Agent2Response(
                design=normalized_design,
                response_id=response.response_id,
                model=response.model,
                usage=response.usage,
            )
        elif first_regression_normalizations:
            response = Agent2Response(
                design=normalized_design,
                response_id=response.response_id,
                model=response.model,
                usage=response.usage,
            )
        if first_regression_normalizations:
            regression_normalization_attempts.append(
                {
                    "attempt": 1,
                    "changes": first_regression_normalizations,
                }
            )
        checkpoint2 = evaluate_checkpoint2(
            request, analysis, response.design, requirements
        )
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint2.status.value,
                "model": response.model,
                "usage": response.usage,
            }
        ]
        if checkpoint2.status == CheckStatus.FAIL:
            _write_json(
                run_dir / "agent2_test_design_attempt_1.json",
                response.design.model_dump(mode="json", by_alias=True),
            )
            _write_json(
                run_dir / "checkpoint2_attempt_1.json",
                checkpoint2.model_dump(mode="json"),
            )
            response = agent.design(
                request,
                analysis,
                requirements,
                previous_design=response.design,
                checkpoint_feedback=[
                    f"{item.rule_id} {item.status.value}: {item.message}"
                    for item in checkpoint2.checks
                ],
            )
            raw_design = response.design
            normalized_design, retry_normalizations = (
                _normalize_agent2_technical_ids(raw_design)
            )
            normalized_design, retry_regression_normalizations = (
                _normalize_agent2_verify_regressions(analysis, normalized_design)
            )
            if retry_normalizations:
                raw_file = run_dir / "agent2_test_design_model_raw_attempt_2.json"
                _write_json(
                    raw_file,
                    raw_design.model_dump(mode="json", by_alias=True),
                )
                normalization_attempts.append(
                    {
                        "attempt": 2,
                        "raw_design_file": raw_file.name,
                        "raw_design_sha256": _sha256_file(raw_file),
                        "changes": retry_normalizations,
                    }
                )
                response = Agent2Response(
                    design=normalized_design,
                    response_id=response.response_id,
                    model=response.model,
                    usage=response.usage,
                )
            elif retry_regression_normalizations:
                response = Agent2Response(
                    design=normalized_design,
                    response_id=response.response_id,
                    model=response.model,
                    usage=response.usage,
                )
            if retry_regression_normalizations:
                regression_normalization_attempts.append(
                    {
                        "attempt": 2,
                        "changes": retry_regression_normalizations,
                    }
                )
            checkpoint2 = evaluate_checkpoint2(
                request, analysis, response.design, requirements
            )
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint2.status.value,
                    "model": response.model,
                    "usage": response.usage,
                }
            )

        normalization_file = run_dir / "agent2_technical_id_normalization.json"
        if normalization_attempts:
            _write_json(
                normalization_file,
                {
                    "contract_version": "1.0",
                    "run_id": args.run_id,
                    "stage": "AGENT_2_TECHNICAL_ID_NORMALIZATION",
                    "scope": "TC and Expected Result identifiers only",
                    "semantic_fields_changed": False,
                    "attempts": normalization_attempts,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        regression_normalization_file = (
            run_dir / "agent2_regression_selection_normalization.json"
        )
        if regression_normalization_attempts:
            _write_json(
                regression_normalization_file,
                {
                    "contract_version": "1.0",
                    "run_id": args.run_id,
                    "stage": "AGENT_2_REGRESSION_SELECTION_NORMALIZATION",
                    "scope": "Agent 1 VERIFY relations only",
                    "changed_product_expectations": False,
                    "attempts": regression_normalization_attempts,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        design_file = run_dir / "agent2_test_design.json"
        checkpoint2_file = run_dir / "checkpoint2.json"
        _write_json(design_file, response.design.model_dump(mode="json", by_alias=True))
        _write_json(checkpoint2_file, checkpoint2.model_dump(mode="json"))
        _write_json(
            run_dir / "agent2_manifest.json",
            {
                "contract_version": "2.9",
                "prompt_version": "agent2-2.10",
                "run_id": args.run_id,
                "source_stage": "AGENT_1_CP1",
                "stage": "AGENT_2_CP2",
                "status": checkpoint2.status.value,
                "model": response.model,
                "usage": _aggregate_model_usage(attempts),
                "final_attempt_usage": response.usage,
                "attempts": attempts,
                "technical_id_normalization_sha256": (
                    _sha256_file(normalization_file)
                    if normalization_file.is_file()
                    else None
                ),
                "regression_selection_normalization_sha256": (
                    _sha256_file(regression_normalization_file)
                    if regression_normalization_file.is_file()
                    else None
                ),
                "source_run_manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
                "request_sha256": source_manifest["request_sha256"],
                "srs_sha256": source_manifest["srs_sha256"],
                "agent1_analysis_sha256": source_manifest["agent1_analysis_sha256"],
                "checkpoint1_sha256": source_manifest["checkpoint1_sha256"],
                "agent2_design_sha256": _sha256_file(design_file),
                "checkpoint2_sha256": _sha256_file(checkpoint2_file),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        reservation_file.unlink()
    except Exception as exc:
        _write_json(
            run_dir / "agent2_error.json",
            {
                "run_id": args.run_id,
                "stage": "AGENT_2_CP2",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"실행 실패: {exc}\n기록 위치: {run_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {args.run_id}")
    print(f"Agent 2 model: {response.model}")
    print(f"Checkpoint 2: {checkpoint2.status.value}")
    print(f"TC candidates: {len(response.design.test_cases)}")
    print(f"결과 위치: {run_dir}")
    return 0 if checkpoint2.status == CheckStatus.PASS else 2



def _load_verified_agent2_run(
    run_dir: Path, run_id: str
) -> tuple[
    ChangeRequest,
    dict[str, SrsRequirement],
    Agent1Analysis,
    Agent2TestDesign,
    Checkpoint2Result,
    dict[str, Any],
]:
    request, requirements, analysis, _, source_manifest = _load_verified_agent1_run(run_dir, run_id)
    manifest_file = run_dir / "agent2_manifest.json"
    manifest = _read_json_payload(manifest_file)
    if manifest.get("run_id") != run_id or manifest.get("stage") != "AGENT_2_CP2":
        raise ValueError("agent2_manifest does not match the requested Run.")
    if manifest.get("status") != CheckStatus.PASS.value:
        raise ValueError("Checkpoint 2 must PASS before Agent 3 can run.")
    _verify_sha256(
        run_dir / "run_manifest.json",
        manifest.get("source_run_manifest_sha256"),
        "Agent 1 Run manifest",
    )
    for key in ("request_sha256", "srs_sha256", "agent1_analysis_sha256", "checkpoint1_sha256"):
        if manifest.get(key) != source_manifest.get(key):
            raise ValueError(f"Agent 2 source chain mismatch: {key}")
    design_file = run_dir / "agent2_test_design.json"
    checkpoint_file = run_dir / "checkpoint2.json"
    _verify_sha256(design_file, manifest.get("agent2_design_sha256"), "Agent 2 design")
    _verify_sha256(checkpoint_file, manifest.get("checkpoint2_sha256"), "Checkpoint 2")
    design = _read_json_model(design_file, Agent2TestDesign)
    checkpoint = _read_json_model(checkpoint_file, Checkpoint2Result)
    recomputed = evaluate_checkpoint2(request, analysis, design, requirements)
    if recomputed.model_dump(mode="json") != checkpoint.model_dump(mode="json"):
        raise ValueError("Stored Checkpoint 2 differs from the current CP2 rules.")
    if checkpoint.status != CheckStatus.PASS:
        raise ValueError("Checkpoint 2 does not allow Agent 3 execution.")
    return request, requirements, analysis, design, checkpoint, manifest


_AGENT3_TRIAL_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOME",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
)


def _redact_playwright_trace(
    trace_file: Path,
    redactions: dict[Path, str],
) -> None:
    """Rewrite a Playwright trace without known local filesystem paths."""
    replacements: set[tuple[bytes, bytes]] = set()
    for path, placeholder in redactions.items():
        resolved = path.resolve()
        values = {
            str(resolved),
            resolved.as_posix(),
            resolved.as_uri(),
        }
        for value in tuple(values):
            values.add(json.dumps(value, ensure_ascii=False)[1:-1])
            values.add(json.dumps(value, ensure_ascii=True)[1:-1])
        for value in values:
            replacements.add((value.encode("utf-8"), placeholder.encode("utf-8")))

    ordered_replacements = sorted(replacements, key=lambda item: len(item[0]), reverse=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{trace_file.stem}-",
        suffix=".zip",
        dir=trace_file.parent,
        delete=False,
    ) as temp_handle:
        temp_trace = Path(temp_handle.name)
    try:
        with zipfile.ZipFile(trace_file, "r") as source, zipfile.ZipFile(
            temp_trace, "w"
        ) as destination:
            for info in source.infolist():
                payload = source.read(info.filename)
                for raw_value, placeholder in ordered_replacements:
                    payload = payload.replace(raw_value, placeholder)
                destination.writestr(info, payload)
        os.replace(temp_trace, trace_file)
    finally:
        if temp_trace.exists():
            temp_trace.unlink()


def run_candidate_trial(
    code_file: Path,
    target_html: Path,
    evidence_dir: Path,
    *,
    timeout_seconds: int,
) -> Agent3TrialResult:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stdout_file = evidence_dir / "trial-stdout.txt"
    stderr_file = evidence_dir / "trial-stderr.txt"
    started = time.monotonic()
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    outcome = TrialOutcome.AUTOMATION_ERROR

    def redact_output(value: str, *paths: Path) -> str:
        redacted = value
        for path in paths:
            resolved = str(path.resolve())
            redacted = redacted.replace(resolved, "<LOCAL_PATH>")
            redacted = redacted.replace(path.resolve().as_uri(), "<LOCAL_FILE_URL>")
        return redacted

    with tempfile.TemporaryDirectory(prefix="qa-agent3-") as temp_name:
        temp_root = Path(temp_name)
        isolated_candidate = temp_root / code_file.name
        shutil.copy2(code_file, isolated_candidate)
        env = {name: os.environ[name] for name in _AGENT3_TRIAL_ENV_ALLOWLIST if name in os.environ}
        # PYTHONUTF8=1 also changes how Windows decodes legacy site-package
        # .pth files and can prevent Python from starting. Keep locale-mode
        # startup while making the captured stdout/stderr encoding explicit.
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        env["QA_TARGET_URL"] = target_html.resolve().as_uri()
        env["QA_EVIDENCE_DIR"] = str(evidence_dir.resolve())
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", isolated_candidate.name, "-q"],
                cwd=temp_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            exit_code = completed.returncode
            stdout = redact_output(completed.stdout[-20000:], temp_root, target_html, evidence_dir)
            stderr = redact_output(completed.stderr[-20000:], temp_root, target_html, evidence_dir)
            combined = stdout + "\n" + stderr
            if exit_code == 0:
                outcome = TrialOutcome.PASS
            elif "PRODUCT_MISMATCH:" in combined:
                outcome = TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
            elif any(
                marker in combined
                for marker in (
                    "Executable doesn't exist",
                    "BrowserType.launch",
                    "ERR_FILE_NOT_FOUND",
                    "Target page, context or browser has been closed",
                )
            ):
                outcome = TrialOutcome.ENVIRONMENT_ERROR
            else:
                outcome = TrialOutcome.AUTOMATION_ERROR
        except subprocess.TimeoutExpired as exc:
            stdout = redact_output((exc.stdout or "")[-20000:], temp_root, target_html, evidence_dir) if isinstance(exc.stdout, str) else ""
            stderr = redact_output((exc.stderr or "")[-20000:], temp_root, target_html, evidence_dir) if isinstance(exc.stderr, str) else ""
            outcome = TrialOutcome.TIMEOUT
    _write_text_atomic(stdout_file, stdout)
    _write_text_atomic(stderr_file, stderr)
    screenshot = evidence_dir / "trial-final.png"
    trace = evidence_dir / "trial-trace.zip"
    if trace.is_file():
        _redact_playwright_trace(
            trace,
            {
                temp_root: "<TRIAL_WORKSPACE>",
                Path.home(): "<USER_HOME>",
                target_html: "<QA_TARGET_FILE>",
                evidence_dir: "<EVIDENCE_DIR>",
                code_file: "<CANDIDATE_FILE>",
            },
        )
    evidence_files = [stdout_file, stderr_file]
    if screenshot.is_file():
        evidence_files.append(screenshot)
    if trace.is_file():
        evidence_files.append(trace)
    return Agent3TrialResult(
        outcome=outcome,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        stdout_file=stdout_file.name,
        stderr_file=stderr_file.name,
        screenshot_file=screenshot.name if screenshot.is_file() else None,
        trace_file=trace.name if trace.is_file() else None,
        evidence_sha256={path.name: _sha256_file(path) for path in evidence_files},
        evidence_complete=screenshot.is_file() and trace.is_file(),
    )


def _agent3_cli_exit_code(
    checkpoint: Checkpoint3Result,
    trial: Agent3TrialResult | None,
) -> int:
    """Return success only when the evaluation flow completed meaningfully.

    A product mismatch is a valid QA finding, so the pipeline itself completed
    successfully. Automation, environment, and timeout failures mean that the
    product result is not trustworthy and must not be reported as CLI success.
    """
    if checkpoint.status != CheckStatus.PASS or trial is None:
        return 2
    required_evidence = {
        trial.stdout_file,
        trial.stderr_file,
        trial.screenshot_file,
        trial.trace_file,
    }
    evidence_is_complete = (
        trial.evidence_complete
        and None not in required_evidence
        and required_evidence == set(trial.evidence_sha256)
    )
    if trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    } and evidence_is_complete:
        return 0
    return 2


def _aggregate_model_usage(
    attempts: list[dict[str, Any]],
) -> dict[str, int | None]:
    """Sum model-token usage across every structured model attempt."""
    aggregate: dict[str, int | None] = {}
    required_keys = ("input_tokens", "output_tokens", "total_tokens")
    detail_keys = sorted(
        {
            key
            for attempt in attempts
            if isinstance((usage := attempt.get("usage")), dict)
            for key, value in usage.items()
            if key not in required_keys and isinstance(value, int)
        }
    )
    for key in (*required_keys, *detail_keys):
        values = [
            usage[key]
            for attempt in attempts
            if isinstance((usage := attempt.get("usage")), dict)
            and isinstance(usage.get(key), int)
        ]
        aggregate[key] = sum(values) if values else None
    return aggregate


def _aggregate_agent3_usage(
    attempts: list[dict[str, Any]],
) -> dict[str, int | None]:
    """Backward-compatible Agent 3 name for the shared usage aggregator."""
    return _aggregate_model_usage(attempts)


def run_agent3(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    artifact_dir_arg = getattr(args, "artifact_dir", None)
    artifact_dir = Path(artifact_dir_arg).resolve() if artifact_dir_arg else run_dir
    if artifact_dir != run_dir:
        try:
            artifact_dir.relative_to(run_dir)
        except ValueError as exc:
            raise ValueError("Agent 3 후보 산출물 경로는 현재 Run 안에 있어야 합니다.") from exc
        artifact_dir.mkdir(parents=True, exist_ok=False)
    final_outputs = [
        artifact_dir / "agent3_automation_plan.json",
        artifact_dir / "checkpoint3.json",
        artifact_dir / "agent3_trial.json",
        artifact_dir / "agent3_manifest.json",
        artifact_dir / "agent3_error.json",
    ]
    candidate_dir = artifact_dir / "candidates"
    evidence_dir = artifact_dir / "evidence" / args.tc_id
    if any(path.exists() for path in final_outputs) or candidate_dir.exists():
        raise ValueError("This Run already contains final Agent 3 artifacts.")

    _, requirements, _, design, _, source_manifest = _load_verified_agent2_run(
        run_dir, args.run_id
    )
    matches = [item for item in design.test_cases if item.tc_id == args.tc_id]
    if len(matches) != 1:
        raise ValueError(f"Exactly one CP2-approved TC is required: {args.tc_id}")
    test_case = matches[0]
    eligibility = evaluate_agent3_eligibility(test_case)
    eligibility_file = artifact_dir / "agent3_eligibility.json"
    _write_json(
        eligibility_file,
        {
            "contract_version": "3.2",
            "run_id": args.run_id,
            "stage": "AGENT_3_ELIGIBILITY",
            "source_agent2_manifest_sha256": _sha256_file(
                run_dir / "agent2_manifest.json"
            ),
            "source_agent2_design_sha256": source_manifest[
                "agent2_design_sha256"
            ],
            **eligibility.model_dump(mode="json"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if not eligibility.model_call_allowed:
        print(f"Run ID: {args.run_id}")
        print("자동화 후보 상태: 현재 TC가 자동화 후보로 승인되지 않음")
        print("Agent 3 model call: NOT EXECUTED")
        print("자동화 불가 사유: " + ", ".join(eligibility.missing_capabilities))
        print(f"Artifacts: {artifact_dir}")
        return 2

    target_html = Path(args.target_html).resolve()
    try:
        observation = inspect_target_ui(
            target_html,
            required_selectors=set(eligibility.required_selectors),
            required_harness_keys=set(eligibility.required_harness_keys),
            discover_generic=eligibility.generic_discovery_required,
        )
        observation_file = artifact_dir / "agent3_ui_observation.json"
        _write_json(observation_file, observation.model_dump(mode="json"))
        preview_payload = build_agent3_model_input(test_case, observation, requirements)
        preview_payload["model"] = args.model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        preview_file = artifact_dir / "agent3_model_input_preview.json"
        _write_json(preview_file, preview_payload)
        if getattr(args, "preview_only", False):
            print(f"Run ID: {args.run_id}")
            print("Agent 3 model call: NOT EXECUTED")
            print(f"Preview: {preview_file}")
            return 0

        agent = OpenAIAgent3(model=args.model)
        response = agent.plan(test_case, observation, requirements)
        checkpoint = evaluate_checkpoint3_plan(test_case, response.plan, observation)
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint.status.value,
                "model": response.model,
                "usage": response.usage,
                "usage_source": "AGENT_3_MODEL_CALL",
            }
        ]
        if checkpoint.status == CheckStatus.FAIL:
            _write_json(artifact_dir / "agent3_automation_plan_attempt_1.json", response.plan.model_dump(mode="json"))
            _write_json(artifact_dir / "checkpoint3_attempt_1.json", checkpoint.model_dump(mode="json"))
            response = agent.plan(
                test_case,
                observation,
                requirements,
                previous_plan=response.plan,
                checkpoint_feedback=[item.message for item in checkpoint.checks if item.status == CheckStatus.FAIL],
            )
            checkpoint = evaluate_checkpoint3_plan(test_case, response.plan, observation)
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint.status.value,
                    "model": response.model,
                    "usage": response.usage,
                    "usage_source": "AGENT_3_INDIVIDUAL_REPAIR_CALL",
                }
            )

        plan_file = artifact_dir / "agent3_automation_plan.json"
        checkpoint_file = artifact_dir / "checkpoint3.json"
        _write_json(plan_file, response.plan.model_dump(mode="json"))
        trial: Agent3TrialResult | None = None
        candidate_file: Path | None = None
        if checkpoint.status == CheckStatus.PASS:
            candidate_dir.mkdir(parents=True, exist_ok=False)
            candidate_file = candidate_dir / f"test_{args.tc_id.lower().replace('-', '_')}.py"
            code = compile_automation_candidate(args.run_id, test_case, response.plan)
            static_checks = evaluate_compiled_candidate(test_case, code)
            checkpoint.checks.extend(static_checks)
            if any(item.status == CheckStatus.FAIL for item in static_checks):
                checkpoint.status = CheckStatus.FAIL
                checkpoint.candidate_status = AutomationCandidateStatus.REVISION_REQUIRED
            else:
                _write_text_atomic(candidate_file, code)
                trial = run_candidate_trial(
                    candidate_file,
                    target_html,
                    evidence_dir,
                    timeout_seconds=args.timeout,
                )
                if _sha256_file(target_html) != observation.target_sha256:
                    raise Agent3Error(
                        "The read-only Project1 target changed during the isolated trial."
                    )
                if trial.outcome == TrialOutcome.PASS:
                    checkpoint.candidate_status = AutomationCandidateStatus.READY_FOR_EXECUTION
                elif trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE:
                    checkpoint.candidate_status = AutomationCandidateStatus.PRODUCT_MISMATCH_DETECTED
                else:
                    checkpoint.candidate_status = AutomationCandidateStatus.TRIAL_FAILED
        _write_json(checkpoint_file, checkpoint.model_dump(mode="json"))
        if trial is not None:
            _write_json(artifact_dir / "agent3_trial.json", trial.model_dump(mode="json"))

        manifest_payload = {
            "contract_version": "4.0",
            "prompt_version": "agent3-3.12",
            "run_id": args.run_id,
            "source_stage": "AGENT_2_CP2",
            "stage": "AGENT_3_CP3_TRIAL",
            "tc_id": args.tc_id,
            "status": checkpoint.status.value,
            "candidate_status": checkpoint.candidate_status.value,
            "model": response.model,
            "usage": _aggregate_agent3_usage(attempts),
            "final_attempt_usage": response.usage,
            "attempts": attempts,
            "source_agent2_manifest_sha256": _sha256_file(run_dir / "agent2_manifest.json"),
            "source_agent2_design_sha256": source_manifest["agent2_design_sha256"],
            "eligibility_sha256": _sha256_file(eligibility_file),
            "ui_observation_sha256": _sha256_file(observation_file),
            "target_file": target_html.name,
            "target_sha256": observation.target_sha256,
            "automation_plan_sha256": _sha256_file(plan_file),
            "checkpoint3_sha256": _sha256_file(checkpoint_file),
            "candidate_file": candidate_file.name if candidate_file and candidate_file.is_file() else None,
            "candidate_sha256": _sha256_file(candidate_file) if candidate_file and candidate_file.is_file() else None,
            "trial_file": "agent3_trial.json" if trial is not None else None,
            "trial_sha256": _sha256_file(artifact_dir / "agent3_trial.json") if trial is not None else None,
            "trial_evidence_sha256": (
                trial.evidence_sha256 if trial is not None else {}
            ),
            "project1_modified": _sha256_file(target_html) != observation.target_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(artifact_dir / "agent3_manifest.json", manifest_payload)
    except Exception as exc:
        _write_json(
            artifact_dir / "agent3_error.json",
            {
                "run_id": args.run_id,
                "stage": "AGENT_3_CP3_TRIAL",
                "tc_id": args.tc_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Agent 3 failed: {exc}\nArtifacts: {artifact_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {args.run_id}")
    print(f"Agent 3 모델: {response.model}")
    print(f"검증 단계 3: {checkpoint.status.value}")
    print(f"자동화 후보 상태: {checkpoint.candidate_status.value}")
    if trial is not None:
        print(f"신규 자동화 후보 시험 결과: {trial.outcome.value}")
    print(f"Artifacts: {artifact_dir}")
    return _agent3_cli_exit_code(checkpoint, trial)


def select_existing_regressions(
    requirement_ids: list[str] | set[str] | tuple[str, ...],
) -> list[ExistingRegressionSpec]:
    """Select only reusable Project1 regressions related to the approved TC."""
    approved = set(requirement_ids)
    return [
        spec
        for spec in EXISTING_REGRESSION_CATALOG
        if approved.intersection(spec.requirement_ids)
    ]


def _safe_artifact_child(parent: Path, name: str, label: str) -> Path:
    if Path(name).name != name:
        raise ValueError(f"{label} 파일명은 하위 경로를 포함할 수 없습니다.")
    path = (parent / name).resolve()
    try:
        path.relative_to(parent.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} 파일이 허용된 폴더 밖을 가리킵니다.") from exc
    if not path.is_file():
        raise ValueError(f"{label} 파일을 찾을 수 없습니다: {name}")
    return path


def _last_output_line(stdout: str, stderr: str) -> str | None:
    lines = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    return lines[-1][-1000:] if lines else None


def _exception_type_from_output(stdout: str, stderr: str) -> str | None:
    combined = stdout + "\n" + stderr
    match = re.search(
        r"\b(AssertionError|SimulatorTimeoutError|TimeoutError|PlaywrightError|Error)\b",
        combined,
    )
    return match.group(1) if match else None


def _neutral_status_from_trial(outcome: TrialOutcome) -> NeutralExecutionStatus:
    return {
        TrialOutcome.PASS: NeutralExecutionStatus.PASSED,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE: (
            NeutralExecutionStatus.ASSERTION_FAILED
        ),
        TrialOutcome.AUTOMATION_ERROR: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.ENVIRONMENT_ERROR: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.TIMEOUT: NeutralExecutionStatus.TIMEOUT,
    }[outcome]


def _candidate_execution_record(
    run_dir: Path,
    run_id: str,
    target_html: Path,
    artifact_dir: Path | None = None,
) -> tuple[NeutralExecutionResult, ProductTestCaseCandidate, dict[str, Any]]:
    artifact_dir = artifact_dir or run_dir
    try:
        artifact_dir.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("Agent 3 후보 산출물은 현재 Run 안에 있어야 합니다.") from exc
    _, _, _, design, _, agent2_manifest = _load_verified_agent2_run(run_dir, run_id)
    agent2_manifest_file = run_dir / "agent2_manifest.json"
    agent3_manifest_file = artifact_dir / "agent3_manifest.json"
    agent3_manifest = _read_json_payload(agent3_manifest_file)
    if agent3_manifest.get("run_id") != run_id:
        raise ValueError("Agent 3 Manifest의 Run ID가 현재 Run과 다릅니다.")
    if agent3_manifest.get("stage") != "AGENT_3_CP3_TRIAL":
        raise ValueError("Agent 3 Manifest 단계가 신규 자동화 후보 시험이 아닙니다.")
    if agent3_manifest.get("status") != CheckStatus.PASS.value:
        raise ValueError("Agent 3가 PASS 상태가 아니어서 실행 결과를 인계할 수 없습니다.")
    _verify_sha256(
        agent2_manifest_file,
        agent3_manifest.get("source_agent2_manifest_sha256"),
        "Agent 2 Manifest",
    )
    if agent3_manifest.get("source_agent2_design_sha256") != agent2_manifest.get(
        "agent2_design_sha256"
    ):
        raise ValueError("Agent 3가 참조한 Agent 2 설계 해시가 현재 Manifest와 다릅니다.")

    tc_id = agent3_manifest.get("tc_id")
    test_case = next((item for item in design.test_cases if item.tc_id == tc_id), None)
    if test_case is None:
        raise ValueError("Agent 3 선택 TC가 현재 Agent 2 설계에 없습니다.")

    artifact_hashes = (
        ("agent3_eligibility.json", "eligibility_sha256", "Agent 3 Eligibility"),
        ("agent3_ui_observation.json", "ui_observation_sha256", "UI Observation"),
        ("agent3_automation_plan.json", "automation_plan_sha256", "Agent 3 계획"),
        ("checkpoint3.json", "checkpoint3_sha256", "Checkpoint 3"),
        ("agent3_trial.json", "trial_sha256", "Agent 3 시험 결과"),
    )
    for filename, key, label in artifact_hashes:
        _verify_sha256(artifact_dir / filename, agent3_manifest.get(key), label)

    observation = _read_json_model(
        artifact_dir / "agent3_ui_observation.json", UiObservation
    )
    plan = _read_json_model(
        artifact_dir / "agent3_automation_plan.json", Agent3AutomationPlan
    )
    current_checkpoint3 = evaluate_checkpoint3_plan(test_case, plan, observation)
    current_code = compile_automation_candidate(run_id, test_case, plan)
    current_static_checks = evaluate_compiled_candidate(test_case, current_code)
    current_checkpoint3.checks.extend(current_static_checks)
    if any(check.status == CheckStatus.FAIL for check in current_static_checks):
        current_checkpoint3.status = CheckStatus.FAIL
        current_checkpoint3.candidate_status = (
            AutomationCandidateStatus.REVISION_REQUIRED
        )
    if current_checkpoint3.status != CheckStatus.PASS:
        failed_rules = ", ".join(
            check.rule_id
            for check in current_checkpoint3.checks
            if check.status == CheckStatus.FAIL
        )
        raise ValueError(
            "저장된 Agent 3 계획이 현재 CP3 규칙을 통과하지 못했습니다: "
            + failed_rules
        )

    checkpoint3 = _read_json_model(artifact_dir / "checkpoint3.json", Checkpoint3Result)
    if checkpoint3.status != CheckStatus.PASS:
        raise ValueError("Checkpoint 3가 PASS가 아니어서 실행 결과를 인계할 수 없습니다.")
    trial = _read_json_model(artifact_dir / "agent3_trial.json", Agent3TrialResult)
    trusted_product_observation = trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    }
    if trusted_product_observation and (
        not trial.evidence_complete
        or trial.screenshot_file is None
        or trial.trace_file is None
    ):
        raise ValueError("신규 자동화 후보 시험 증거가 완전하지 않습니다.")

    target_html = target_html.resolve()
    if not target_html.is_file():
        raise ValueError("검증 대상 HTML을 찾을 수 없습니다.")
    target_sha256 = _sha256_file(target_html)
    if target_html.name != agent3_manifest.get("target_file"):
        raise ValueError("검증 대상 파일명이 Agent 3 Manifest와 다릅니다.")
    if target_sha256 != agent3_manifest.get("target_sha256"):
        raise ValueError("검증 대상 HTML이 신규 자동화 후보 시험 후 변경됐습니다.")
    if agent3_manifest.get("project1_modified") is not False:
        raise ValueError("Agent 3 실행에서 Project1 불변을 확인하지 못했습니다.")

    candidate_name = agent3_manifest.get("candidate_file")
    if not isinstance(candidate_name, str):
        raise ValueError("Agent 3 Candidate 파일명이 없습니다.")
    candidate_file = _safe_artifact_child(
        artifact_dir / "candidates", candidate_name, "Agent 3 Candidate"
    )
    _verify_sha256(
        candidate_file,
        agent3_manifest.get("candidate_sha256"),
        "Agent 3 Candidate",
    )

    evidence_dir = artifact_dir / "evidence" / test_case.tc_id
    evidence_names = [trial.stdout_file, trial.stderr_file]
    if trial.screenshot_file:
        evidence_names.append(trial.screenshot_file)
    if trial.trace_file:
        evidence_names.append(trial.trace_file)
    if set(trial.evidence_sha256) != set(evidence_names):
        raise ValueError("Agent 3 Trial의 증거 목록과 SHA-256 목록이 다릅니다.")
    evidence_files = [
        _safe_artifact_child(evidence_dir, name, "신규 후보 시험 증거")
        for name in evidence_names
    ]
    evidence_paths = [path.relative_to(run_dir).as_posix() for path in evidence_files]
    evidence_hashes = {
        relative: _sha256_file(path)
        for relative, path in zip(evidence_paths, evidence_files, strict=True)
    }
    manifest_evidence_hashes = agent3_manifest.get("trial_evidence_sha256")
    if not isinstance(manifest_evidence_hashes, dict):
        raise ValueError("Agent 3 Manifest에 시험 증거 SHA-256이 없습니다.")
    if manifest_evidence_hashes != trial.evidence_sha256:
        raise ValueError("Agent 3 Manifest와 Trial의 증거 SHA-256이 다릅니다.")
    for evidence_file in evidence_files:
        expected_hash = trial.evidence_sha256.get(evidence_file.name)
        if expected_hash is None or _sha256_file(evidence_file) != expected_hash:
            raise ValueError(
                f"Agent 3 시험 증거 SHA-256이 일치하지 않습니다: {evidence_file.name}"
            )
    stdout = (evidence_dir / trial.stdout_file).read_text(encoding="utf-8")
    stderr = (evidence_dir / trial.stderr_file).read_text(encoding="utf-8")
    status = _neutral_status_from_trial(trial.outcome)
    return (
        NeutralExecutionResult(
            test_id=test_case.tc_id,
            source=ExecutionSource.NEW_AUTOMATION_CANDIDATE,
            requirement_ids=test_case.requirement_ids,
            status=status,
            source_outcome=trial.outcome.value,
            exit_code=trial.exit_code,
            duration_ms=trial.duration_ms,
            test_file=candidate_file.relative_to(run_dir).as_posix(),
            test_sha256=_sha256_file(candidate_file),
            target_sha256=target_sha256,
            reused=True,
            stdout_file=(evidence_dir / trial.stdout_file).relative_to(run_dir).as_posix(),
            stderr_file=(evidence_dir / trial.stderr_file).relative_to(run_dir).as_posix(),
            evidence_files=evidence_paths,
            evidence_sha256=evidence_hashes,
            evidence_complete=trial.evidence_complete,
            exception_type=(
                "AssertionError"
                if trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
                else _exception_type_from_output(stdout, stderr)
            ),
            raw_message=_last_output_line(stdout, stderr),
        ),
        test_case,
        agent3_manifest,
    )


def _candidate_file_for_result(
    run_dir: Path, result: NeutralExecutionResult
) -> Path:
    relative = Path(result.test_file)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Candidate 파일 경로가 현재 Run 밖을 가리킵니다.")
    candidate_file = (
        run_dir / "candidates" / relative
        if relative.name == result.test_file
        else run_dir / relative
    ).resolve()
    try:
        candidate_file.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("Candidate 파일 경로가 현재 Run 밖을 가리킵니다.") from exc
    return candidate_file


def _candidate_execution_records(
    run_dir: Path,
    run_id: str,
    target_html: Path,
) -> tuple[
    list[tuple[NeutralExecutionResult, ProductTestCaseCandidate, dict[str, Any], Path]],
    list[AutomationExclusion],
    dict[str, Any] | None,
]:
    summary_file = run_dir / "agent3_run_summary.json"
    if not summary_file.is_file():
        result, test_case, manifest = _candidate_execution_record(
            run_dir, run_id, target_html
        )
        return [(result, test_case, manifest, run_dir)], [], None

    summary = _read_json_payload(summary_file)
    if (
        summary.get("run_id") != run_id
        or summary.get("stage") != "AGENT_3_RUN_SUMMARY"
    ):
        raise ValueError("Agent 3 실행 요약의 Run ID 또는 단계가 다릅니다.")
    if summary.get("target_file") != target_html.name:
        raise ValueError("Agent 3 실행 요약의 대상 파일명이 현재 검증 대상과 다릅니다.")
    if summary.get("target_sha256") != _sha256_file(target_html):
        raise ValueError("Agent 3 실행 이후 검증 대상 HTML이 변경됐습니다.")
    raw_entries = summary.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Agent 3 실행 결과 목록이 없습니다.")
    records = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or entry.get("exit_code") != 0:
            continue
        relative_dir = entry.get("artifact_dir")
        if not isinstance(relative_dir, str):
            raise ValueError("Agent 3 산출물 경로가 없습니다.")
        relative_path = Path(relative_dir)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Agent 3 산출물 경로가 현재 Run 밖을 가리킵니다.")
        artifact_dir = (run_dir / relative_path).resolve()
        try:
            artifact_dir.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("Agent 3 산출물 경로가 현재 Run 밖을 가리킵니다.") from exc
        if not artifact_dir.is_dir():
            raise ValueError("Agent 3 산출물 폴더를 찾을 수 없습니다.")
        manifest_file = artifact_dir / "agent3_manifest.json"
        _verify_sha256(
            manifest_file, entry.get("manifest_sha256"), "Agent 3 후보 Manifest"
        )
        result, test_case, manifest = _candidate_execution_record(
            run_dir, run_id, target_html, artifact_dir
        )
        records.append((result, test_case, manifest, artifact_dir))
    if not records:
        raise ValueError("검증 실행으로 인계할 Agent 3 완료 후보가 없습니다.")
    exclusions = [
        AutomationExclusion.model_validate(item)
        for item in summary.get("자동화_제외_TC", [])
    ]
    return records, exclusions, summary


def _current_candidate_execution_record(
    run_dir: Path,
    run_id: str,
    target_html: Path,
    test_case: ProductTestCaseCandidate,
    stored_result: NeutralExecutionResult,
    *,
    timeout_seconds: int,
    artifact_dir: Path | None = None,
) -> NeutralExecutionResult:
    """Reuse an identical candidate or recompile and retrial without a model call."""
    artifact_dir = artifact_dir or run_dir
    plan = _read_json_model(
        artifact_dir / "agent3_automation_plan.json", Agent3AutomationPlan
    )
    current_code = compile_automation_candidate(run_id, test_case, plan)
    stored_candidate_file = _candidate_file_for_result(run_dir, stored_result)
    if (
        stored_candidate_file.is_file()
        and _sha256_file(stored_candidate_file) == stored_result.test_sha256
        and stored_candidate_file.read_text(encoding="utf-8") == current_code
    ):
        return stored_result

    candidate_dir = run_dir / "validation_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate_file = candidate_dir / f"test_{test_case.tc_id.lower().replace('-', '_')}.py"
    _write_text_atomic(candidate_file, current_code)
    evidence_dir = run_dir / "validation_evidence" / test_case.tc_id
    trial = run_candidate_trial(
        candidate_file,
        target_html,
        evidence_dir,
        timeout_seconds=timeout_seconds,
    )
    trial_dir = run_dir / "validation_candidate_trials"
    trial_dir.mkdir(parents=True, exist_ok=True)
    trial_file = trial_dir / f"{test_case.tc_id}.json"
    _write_json(trial_file, trial.model_dump(mode="json"))
    if trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    } and not trial.evidence_complete:
        raise ValueError("현재 컴파일러의 신규 자동화 후보 시험 증거가 완전하지 않습니다.")

    evidence_names = [trial.stdout_file, trial.stderr_file]
    if trial.screenshot_file:
        evidence_names.append(trial.screenshot_file)
    if trial.trace_file:
        evidence_names.append(trial.trace_file)
    evidence_files = [
        _safe_artifact_child(evidence_dir, name, "현재 Candidate 시험 증거")
        for name in evidence_names
    ]
    evidence_paths = [path.relative_to(run_dir).as_posix() for path in evidence_files]
    stdout = (evidence_dir / trial.stdout_file).read_text(encoding="utf-8")
    stderr = (evidence_dir / trial.stderr_file).read_text(encoding="utf-8")
    return NeutralExecutionResult(
        test_id=test_case.tc_id,
        source=ExecutionSource.NEW_AUTOMATION_CANDIDATE,
        requirement_ids=test_case.requirement_ids,
        status=_neutral_status_from_trial(trial.outcome),
        source_outcome=trial.outcome.value,
        exit_code=trial.exit_code,
        duration_ms=trial.duration_ms,
        test_file=candidate_file.relative_to(run_dir).as_posix(),
        test_sha256=_sha256_file(candidate_file),
        target_sha256=_sha256_file(target_html),
        reused=False,
        stdout_file=(evidence_dir / trial.stdout_file).relative_to(run_dir).as_posix(),
        stderr_file=(evidence_dir / trial.stderr_file).relative_to(run_dir).as_posix(),
        evidence_files=evidence_paths,
        evidence_sha256={
            relative: _sha256_file(path)
            for relative, path in zip(evidence_paths, evidence_files, strict=True)
        },
        evidence_complete=trial.evidence_complete,
        exception_type=(
            "AssertionError"
            if trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
            else _exception_type_from_output(stdout, stderr)
        ),
        raw_message=_last_output_line(stdout, stderr),
    )


_BASELINE_VIEWPORT_CONFTEST = """import pytest

@pytest.fixture(scope=\"session\")
def browser_context_args(browser_context_args):
    return {**browser_context_args, \"viewport\": {\"width\": 1600, \"height\": 900}}
"""


def run_existing_regression(
    spec: ExistingRegressionSpec,
    baseline_test_file: Path,
    target_html: Path,
    evidence_root: Path,
    *,
    timeout_seconds: int,
    source: ExecutionSource = ExecutionSource.EXISTING_REGRESSION,
) -> NeutralExecutionResult:
    """Run one allowlisted Project1 test from a copied, neutral workspace."""
    baseline_test_file = baseline_test_file.resolve()
    target_html = target_html.resolve()
    evidence_dir = evidence_root / spec.tc_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    stdout_file = evidence_dir / "stdout.txt"
    stderr_file = evidence_dir / "stderr.txt"
    started = time.monotonic()
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    status = NeutralExecutionStatus.EXECUTION_ERROR
    source_outcome = "PYTEST_ERROR"

    def redact(value: str, *paths: Path) -> str:
        redacted = value
        for path in paths:
            resolved = path.resolve()
            redacted = redacted.replace(str(resolved), "<LOCAL_PATH>")
            redacted = redacted.replace(resolved.as_uri(), "<LOCAL_FILE_URL>")
        return redacted

    with tempfile.TemporaryDirectory(prefix="qa-regression-") as temp_name:
        temp_root = Path(temp_name)
        tests_dir = temp_root / "tests"
        tests_dir.mkdir()
        isolated_test = tests_dir / "test_controller.py"
        isolated_target = temp_root / "virtual-controller.html"
        shutil.copy2(baseline_test_file, isolated_test)
        shutil.copy2(target_html, isolated_target)
        _write_text_atomic(tests_dir / "conftest.py", _BASELINE_VIEWPORT_CONFTEST)
        env = {
            name: os.environ[name]
            for name in _AGENT3_TRIAL_ENV_ALLOWLIST
            if name in os.environ
        }
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    f"tests/test_controller.py::{spec.test_function}",
                    "-q",
                    "--browser",
                    "chromium",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=temp_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            exit_code = completed.returncode
            stdout = redact(
                completed.stdout[-20000:],
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            stderr = redact(
                completed.stderr[-20000:],
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            combined = stdout + "\n" + stderr
            if exit_code == 0 and re.search(r"\bskipped\b", combined, re.IGNORECASE):
                status = NeutralExecutionStatus.SKIPPED
                source_outcome = "PYTEST_SKIPPED"
            elif exit_code == 0:
                status = NeutralExecutionStatus.PASSED
                source_outcome = "PYTEST_PASSED"
            elif "AssertionError" in combined:
                status = NeutralExecutionStatus.ASSERTION_FAILED
                source_outcome = "PYTEST_FAILED"
            else:
                status = NeutralExecutionStatus.EXECUTION_ERROR
                source_outcome = "PYTEST_ERROR"
        except subprocess.TimeoutExpired as exc:
            stdout = redact(
                (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            stderr = redact(
                (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else "",
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            status = NeutralExecutionStatus.TIMEOUT
            source_outcome = "PYTEST_TIMEOUT"

    _write_text_atomic(stdout_file, stdout)
    _write_text_atomic(stderr_file, stderr)
    evidence_paths = [
        stdout_file.relative_to(evidence_root.parent).as_posix(),
        stderr_file.relative_to(evidence_root.parent).as_posix(),
    ]
    return NeutralExecutionResult(
        test_id=spec.tc_id,
        source=source,
        requirement_ids=list(spec.requirement_ids),
        status=status,
        source_outcome=source_outcome,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        test_file=baseline_test_file.name,
        test_sha256=_sha256_file(baseline_test_file),
        target_sha256=_sha256_file(target_html),
        reused=False,
        stdout_file=evidence_paths[0],
        stderr_file=evidence_paths[1],
        evidence_files=evidence_paths,
        evidence_sha256={
            evidence_paths[0]: _sha256_file(stdout_file),
            evidence_paths[1]: _sha256_file(stderr_file),
        },
        evidence_complete=stdout_file.is_file() and stderr_file.is_file(),
        exception_type=_exception_type_from_output(stdout, stderr),
        raw_message=_last_output_line(stdout, stderr),
    )


def _final_review_notes_for_validation(run_dir: Path) -> list[str]:
    """검증된 이전 단계의 최종 확인 사항만 수집합니다."""
    notes: list[str] = []
    checkpoint1_file = run_dir / "checkpoint1.json"
    if checkpoint1_file.is_file():
        checkpoint1 = _read_json_model(checkpoint1_file, Checkpoint1Result)
        notes.extend(f"CP1: {note}" for note in checkpoint1.final_review_notes)
    design_file = run_dir / "agent2_test_design.json"
    if design_file.is_file():
        design = _read_json_model(design_file, Agent2TestDesign)
        notes.extend(f"CP2: {note}" for note in design.final_review_notes)
    return list(dict.fromkeys(notes))


def _excluded_scope_for_validation(run_dir: Path) -> tuple[list[str], list[str]]:
    """검증된 Agent 2 인계에 보존된 실행 제외 범위를 읽습니다."""
    design = _read_json_model(run_dir / "agent2_test_design.json", Agent2TestDesign)
    return list(design.excluded_scope), list(design.excluded_information_gaps)


def run_validation_execution(args: argparse.Namespace) -> int:
    """Reuse the trusted new-candidate trial and run related baseline regressions."""
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    target_html = Path(args.target_html).resolve()
    baseline_test_file = (
        Path(args.baseline_tests).resolve()
        if args.baseline_tests
        else target_html.parent / "tests" / "test_controller.py"
    )
    if not target_html.is_file():
        raise ValueError("검증 대상 HTML을 찾을 수 없습니다.")
    if not baseline_test_file.is_file():
        raise ValueError("Project1 기존 테스트 파일을 찾을 수 없습니다.")
    final_outputs = (
        run_dir / "validation_execution.json",
        run_dir / "validation_manifest.json",
        run_dir / "validation_error.json",
        run_dir / "validation_evidence",
        run_dir / "validation_candidates",
        run_dir / "validation_candidate_trial.json",
        run_dir / "validation_candidate_trials",
    )
    if any(path.exists() for path in final_outputs):
        raise ValueError("이 Run에는 이미 검증 실행 산출물이 있습니다. 기존 증거를 덮어쓸 수 없습니다.")

    target_before = _sha256_file(target_html)
    baseline_before = _sha256_file(baseline_test_file)
    try:
        stored_records, automation_exclusions, run_summary = (
            _candidate_execution_records(run_dir, args.run_id, target_html)
        )
        candidate_results: list[NeutralExecutionResult] = []
        test_cases: list[ProductTestCaseCandidate] = []
        source_artifacts: list[dict[str, Any]] = []
        for stored_result, test_case, _, artifact_dir in stored_records:
            candidate_result = _current_candidate_execution_record(
                run_dir,
                args.run_id,
                target_html,
                test_case,
                stored_result,
                timeout_seconds=args.timeout,
                artifact_dir=artifact_dir,
            )
            candidate_results.append(candidate_result)
            test_cases.append(test_case)
            agent3_manifest_file = artifact_dir / "agent3_manifest.json"
            agent3_trial_file = artifact_dir / "agent3_trial.json"
            validation_trial_file = (
                run_dir / "validation_candidate_trials" / f"{test_case.tc_id}.json"
            )
            source_artifacts.append(
                {
                    "tc_id": test_case.tc_id,
                    "agent3_manifest_file": agent3_manifest_file.relative_to(run_dir).as_posix(),
                    "agent3_manifest_sha256": _sha256_file(agent3_manifest_file),
                    "agent3_trial_file": agent3_trial_file.relative_to(run_dir).as_posix(),
                    "agent3_trial_sha256": _sha256_file(agent3_trial_file),
                    "candidate_reused": candidate_result.reused,
                    "validation_candidate_sha256": candidate_result.test_sha256,
                    "validation_candidate_trial_file": (
                        validation_trial_file.relative_to(run_dir).as_posix()
                        if validation_trial_file.is_file()
                        else None
                    ),
                    "validation_candidate_trial_sha256": (
                        _sha256_file(validation_trial_file)
                        if validation_trial_file.is_file()
                        else None
                    ),
                }
            )
        design = _read_json_model(
            run_dir / "agent2_test_design.json", Agent2TestDesign
        )
        if design.existing_tc_comparison_completed:
            selected = [
                EXISTING_REGRESSION_BY_ID[item.tc_id]
                for item in design.related_existing_tests
            ]
        else:
            # Historical Run compatibility: older Agent 2 contracts did not
            # carry explicit existing-TC selections.
            requirement_ids = {
                requirement_id
                for test_case in test_cases
                for requirement_id in test_case.requirement_ids
            }
            selected = select_existing_regressions(requirement_ids)
        evidence_root = run_dir / "validation_evidence"
        precheck = run_existing_regression(
            ENVIRONMENT_PRECHECK,
            baseline_test_file,
            target_html,
            evidence_root,
            timeout_seconds=args.timeout,
            source=ExecutionSource.ENVIRONMENT_PRECHECK,
        )
        regression_results: list[NeutralExecutionResult] = []
        blocked_reason: str | None = None
        if precheck.status == NeutralExecutionStatus.PASSED:
            for spec in selected:
                regression_results.append(
                    run_existing_regression(
                        spec,
                        baseline_test_file,
                        target_html,
                        evidence_root,
                        timeout_seconds=args.timeout,
                    )
                )
            stage_status = ValidationStageStatus.COMPLETED
        else:
            stage_status = ValidationStageStatus.BLOCKED
            blocked_reason = "ENVIRONMENT_PRECHECK_NOT_PASSED"

        if _sha256_file(target_html) != target_before:
            raise RuntimeError("검증 실행 중 Project1 대상 HTML이 변경됐습니다.")
        if _sha256_file(baseline_test_file) != baseline_before:
            raise RuntimeError("검증 실행 중 Project1 기존 테스트 파일이 변경됐습니다.")

        excluded_scope, excluded_information_gaps = _excluded_scope_for_validation(run_dir)
        bundle = ValidationExecutionBundle(
            run_id=args.run_id,
            status=stage_status,
            candidate_result=candidate_results[0],
            candidate_results=candidate_results,
            environment_precheck=precheck,
            selected_regression_ids=[item.tc_id for item in selected],
            regression_results=regression_results,
            blocked_reason=blocked_reason,
            excluded_scope=excluded_scope,
            excluded_information_gaps=excluded_information_gaps,
            final_review_notes=_final_review_notes_for_validation(run_dir),
            automation_exclusions=automation_exclusions,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        execution_file = run_dir / "validation_execution.json"
        _write_json(execution_file, bundle.model_dump(mode="json", by_alias=True))
        agent3_manifest_file = run_dir / "agent3_manifest.json"
        agent3_trial_file = run_dir / "agent3_trial.json"
        _write_json(
            run_dir / "validation_manifest.json",
            {
                "contract_version": "1.3",
                "run_id": args.run_id,
                "stage": "VALIDATION_EXECUTION",
                "status": stage_status.value,
                "source_agent3_manifest_sha256": (
                    _sha256_file(agent3_manifest_file)
                    if agent3_manifest_file.is_file()
                    else None
                ),
                "source_agent3_trial_sha256": (
                    _sha256_file(agent3_trial_file)
                    if agent3_trial_file.is_file()
                    else None
                ),
                "source_agent3_run_summary_sha256": (
                    _sha256_file(run_dir / "agent3_run_summary.json")
                    if run_summary is not None
                    else None
                ),
                "source_agent3_artifacts": source_artifacts,
                "candidate_reused": candidate_results[0].reused,
                "validation_candidate_sha256": candidate_results[0].test_sha256,
                "validation_candidate_trial_sha256": None,
                "baseline_test_file": baseline_test_file.name,
                "baseline_test_sha256": baseline_before,
                "target_file": target_html.name,
                "target_sha256": target_before,
                "validation_execution_sha256": _sha256_file(execution_file),
                "project1_modified": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        _write_json(
            run_dir / "validation_error.json",
            {
                "run_id": args.run_id,
                "stage": "VALIDATION_EXECUTION",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        raise

    print(f"Run ID: {args.run_id}")
    print(f"Validation execution: {stage_status.value}")
    print("Candidate results: " + ", ".join(item.test_id for item in candidate_results))
    print(f"Candidate trials reused: {sum(item.reused for item in candidate_results)}/{len(candidate_results)}")
    print(f"Automation exclusions: {len(automation_exclusions)}")
    print(f"Related regressions selected: {len(selected)}")
    print(f"Related regressions executed: {len(regression_results)}")
    print(f"Artifacts: {run_dir}")
    return 0 if stage_status == ValidationStageStatus.COMPLETED else 2


def _validation_results(bundle: ValidationExecutionBundle) -> list[NeutralExecutionResult]:
    return [*bundle.candidate_results, bundle.environment_precheck, *bundle.regression_results]


def _agent4_finding_for_result(
    result: NeutralExecutionResult, finding_number: int
) -> Agent4Finding | None:
    if result.status == NeutralExecutionStatus.PASSED:
        return None
    if result.source == ExecutionSource.ENVIRONMENT_PRECHECK:
        category = Agent4FindingCategory.ENVIRONMENT_ISSUE
        rationale = "환경 사전 점검이 통과하지 않아 제품 회귀 결과를 신뢰할 수 없습니다."
    elif result.source_outcome == TrialOutcome.ENVIRONMENT_ERROR.value:
        category = Agent4FindingCategory.ENVIRONMENT_ISSUE
        rationale = "신규 후보 실행 환경 오류로 제품 결과를 판정할 수 없습니다."
    elif result.status == NeutralExecutionStatus.ASSERTION_FAILED:
        category = Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE
        rationale = "기대 결과와 관찰 결과가 달라 제품 불일치 후보로 분류합니다. 제품 결함 확정은 아닙니다."
    elif result.status in {
        NeutralExecutionStatus.EXECUTION_ERROR,
        NeutralExecutionStatus.TIMEOUT,
    }:
        category = Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE
        rationale = "실행 기술 오류 또는 시간 초과로 제품 결과를 판정할 수 없습니다."
    else:
        category = Agent4FindingCategory.NOT_EXECUTED
        rationale = "이 TC는 실행되지 않았으므로 제품 결과 근거가 부족합니다."
    return Agent4Finding(
        finding_id=f"FIND-{finding_number:03d}",
        category=category,
        test_id=result.test_id,
        source=result.source,
        requirement_ids=result.requirement_ids,
        status=result.status,
        evidence_files=result.evidence_files,
        rationale=rationale,
    )


def _agent4_recommendation(
    findings: list[Agent4Finding], checkpoint_status: CheckStatus
) -> FinalRecommendation:
    if checkpoint_status != CheckStatus.PASS:
        return FinalRecommendation.HOLD
    blocking_categories = {
        Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE,
        Agent4FindingCategory.ENVIRONMENT_ISSUE,
        Agent4FindingCategory.INSUFFICIENT_EVIDENCE,
        Agent4FindingCategory.NOT_EXECUTED,
    }
    if any(finding.category in blocking_categories for finding in findings):
        return FinalRecommendation.HOLD
    if any(
        finding.category == Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE
        for finding in findings
    ):
        return FinalRecommendation.HUMAN_REVIEW
    return FinalRecommendation.PASS


def _agent4_evidence_issues(
    run_dir: Path, results: list[NeutralExecutionResult]
) -> list[str]:
    issues: list[str] = []
    for result in results:
        trusted_product_observation = result.status in {
            NeutralExecutionStatus.PASSED,
            NeutralExecutionStatus.ASSERTION_FAILED,
        }
        if trusted_product_observation and (
            not result.evidence_complete or not result.evidence_files
        ):
            issues.append(
                f"{result.test_id}: 제품 판정에 필요한 완전한 실행 증거가 없습니다"
            )
        elif not result.evidence_files:
            issues.append(f"{result.test_id}: 실행 상태를 설명할 증거가 없습니다")
        if (
            trusted_product_observation
            and result.source == ExecutionSource.NEW_AUTOMATION_CANDIDATE
        ):
            named_output = {result.stdout_file, result.stderr_file}
            candidate_evidence_complete = (
                None not in named_output
                and named_output <= set(result.evidence_files)
                and any(Path(name).suffix.casefold() == ".png" for name in result.evidence_files)
                and any(Path(name).suffix.casefold() == ".zip" for name in result.evidence_files)
            )
            if not candidate_evidence_complete:
                issues.append(
                    f"{result.test_id}: 신규 후보 제품 판정에 stdout·stderr·Screenshot·Trace가 모두 필요합니다"
                )
        if set(result.evidence_sha256) != set(result.evidence_files):
            issues.append(
                f"{result.test_id}: 증거 목록과 SHA-256 목록이 일치하지 않습니다"
            )
        for named_file in (result.stdout_file, result.stderr_file):
            if named_file is not None and named_file not in result.evidence_files:
                issues.append(
                    f"{result.test_id}: stdout 또는 stderr가 증거 목록에 없습니다"
                )
        for relative_name in result.evidence_files:
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                issues.append(f"{result.test_id}: 증거 경로가 Run 폴더 밖을 가리킵니다")
                continue
            evidence_file = (run_dir / relative_path).resolve()
            try:
                evidence_file.relative_to(run_dir.resolve())
            except ValueError:
                issues.append(f"{result.test_id}: 증거 경로가 Run 폴더 밖을 가리킵니다")
                continue
            expected_hash = result.evidence_sha256.get(relative_name)
            if not evidence_file.is_file():
                issues.append(f"{result.test_id}: 증거 파일이 없습니다: {relative_name}")
            elif expected_hash is None or _sha256_file(evidence_file) != expected_hash:
                issues.append(f"{result.test_id}: 증거 SHA-256이 일치하지 않습니다: {relative_name}")
    return issues


def _agent4_status_contract_issues(
    results: list[NeutralExecutionResult],
) -> list[str]:
    expected_status = {
        TrialOutcome.PASS.value: NeutralExecutionStatus.PASSED,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE.value: (
            NeutralExecutionStatus.ASSERTION_FAILED
        ),
        TrialOutcome.AUTOMATION_ERROR.value: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.ENVIRONMENT_ERROR.value: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.TIMEOUT.value: NeutralExecutionStatus.TIMEOUT,
        "PYTEST_PASSED": NeutralExecutionStatus.PASSED,
        "PYTEST_FAILED": NeutralExecutionStatus.ASSERTION_FAILED,
        "PYTEST_ERROR": NeutralExecutionStatus.EXECUTION_ERROR,
        "PYTEST_TIMEOUT": NeutralExecutionStatus.TIMEOUT,
        "PYTEST_SKIPPED": NeutralExecutionStatus.SKIPPED,
    }
    issues: list[str] = []
    for result in results:
        expected = expected_status.get(result.source_outcome)
        if expected is None or result.status != expected:
            issues.append(
                f"{result.test_id}: source_outcome과 중립 상태가 일치하지 않습니다"
            )
        if result.status in {
            NeutralExecutionStatus.PASSED,
            NeutralExecutionStatus.SKIPPED,
        } and result.exit_code != 0:
            issues.append(f"{result.test_id}: 통과 또는 건너뜀 종료 코드가 0이 아닙니다")
        if result.status in {
            NeutralExecutionStatus.ASSERTION_FAILED,
            NeutralExecutionStatus.EXECUTION_ERROR,
        } and result.exit_code in {None, 0}:
            issues.append(f"{result.test_id}: 실패 상태의 종료 코드가 유효하지 않습니다")
        if result.status == NeutralExecutionStatus.TIMEOUT and result.exit_code is not None:
            issues.append(f"{result.test_id}: 시간 초과 결과에 종료 코드가 기록됐습니다")
    return issues


def _agent4_candidate_artifact_matches(
    run_dir: Path, result: NeutralExecutionResult
) -> bool:
    try:
        candidate_file = _candidate_file_for_result(run_dir, result)
    except ValueError:
        return False
    return (
        candidate_file.is_file()
        and _sha256_file(candidate_file) == result.test_sha256
    )


def _safe_run_file(run_dir: Path, relative_name: Any) -> Path | None:
    if not isinstance(relative_name, str):
        return None
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = (run_dir / relative).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _agent4_new_source_chain_matches(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    manifest: dict[str, Any],
) -> bool | None:
    raw_artifacts = manifest.get("source_agent3_artifacts")
    if not isinstance(raw_artifacts, list):
        return None
    artifacts = {
        item.get("tc_id"): item for item in raw_artifacts if isinstance(item, dict)
    }
    if set(artifacts) != {item.test_id for item in bundle.candidate_results}:
        return False
    summary_hash = manifest.get("source_agent3_run_summary_sha256")
    summary_file = run_dir / "agent3_run_summary.json"
    if summary_hash is not None and (
        not isinstance(summary_hash, str)
        or not summary_file.is_file()
        or _sha256_file(summary_file) != summary_hash
    ):
        return False
    for result in bundle.candidate_results:
        item = artifacts[result.test_id]
        agent3_manifest = _safe_run_file(
            run_dir, item.get("agent3_manifest_file")
        )
        agent3_trial = _safe_run_file(run_dir, item.get("agent3_trial_file"))
        if (
            agent3_manifest is None
            or agent3_trial is None
            or _sha256_file(agent3_manifest) != item.get("agent3_manifest_sha256")
            or _sha256_file(agent3_trial) != item.get("agent3_trial_sha256")
            or item.get("candidate_reused") != result.reused
            or item.get("validation_candidate_sha256") != result.test_sha256
            or not _agent4_candidate_artifact_matches(run_dir, result)
        ):
            return False
        validation_trial = _safe_run_file(
            run_dir, item.get("validation_candidate_trial_file")
        )
        validation_trial_hash = item.get("validation_candidate_trial_sha256")
        if result.reused:
            if item.get("validation_candidate_trial_file") is not None or validation_trial_hash is not None:
                return False
        elif (
            validation_trial is None
            or not isinstance(validation_trial_hash, str)
            or _sha256_file(validation_trial) != validation_trial_hash
        ):
            return False
    return True


_HUMAN_REVIEW_DOCUMENT = "사람_최종_검토.md"
_HUMAN_REVIEW_MANIFEST = "사람_최종_검토_manifest.json"


def _markdown_text(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _human_review_observation(
    run_dir: Path, result: NeutralExecutionResult | None
) -> str:
    if result is None:
        return "실행 결과 상세가 연결되지 않았습니다."
    for relative_name in (result.stdout_file, result.stderr_file):
        if not relative_name:
            continue
        candidate = (run_dir / relative_name).resolve()
        try:
            candidate.relative_to(run_dir.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")[-12000:]
        mismatch = re.search(
            r"AssertionError:\s*PRODUCT_MISMATCH:\s*(.+)$",
            text,
            flags=re.MULTILINE,
        )
        if mismatch:
            return _markdown_text(mismatch.group(1)[:2000])
        restore = re.search(
            r"(?:AssertionError:\s*)?RESTORE_MISMATCH:\s*(.+)$",
            text,
            flags=re.MULTILINE,
        )
        if restore:
            return _markdown_text(restore.group(1)[:2000])
    return _markdown_text(result.raw_message or result.source_outcome)


def _human_review_markdown(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    report: FinalReport,
    design: Agent2TestDesign | None,
) -> str:
    results_by_id = {
        result.test_id: result for result in _validation_results(bundle)
    }
    candidates_by_id = (
        {test_case.tc_id: test_case for test_case in design.test_cases}
        if design is not None
        else {}
    )
    existing_by_id = {item.tc_id: item for item in EXISTING_REGRESSION_CATALOG}
    category_labels = {
        Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE: "제품 동작 불일치 후보",
        Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE: "자동화 실행 문제",
        Agent4FindingCategory.ENVIRONMENT_ISSUE: "실행 환경 문제",
        Agent4FindingCategory.INSUFFICIENT_EVIDENCE: "판정 근거 부족",
        Agent4FindingCategory.NOT_EXECUTED: "미실행",
    }
    lines = [
        "# 사람 최종 검토서",
        "",
        "> 이 문서는 자동 판정을 사람이 최종 확정하기 위한 양식입니다. `제품 동작 불일치 후보`는 제품 결함 확정이 아닙니다.",
        "> 아래 작성란을 사람이 채우면 Manifest의 문서 SHA-256과 달라지는 것이 정상입니다. Manifest 해시는 자동 생성 원본을 식별하며, 사람이 작성한 문서는 `--refresh`가 덮어쓰지 않습니다.",
        "",
        "## 1. 전체 결론 작성란",
        "",
        "- [ ] 변경 승인",
        "- [ ] 제품 수정 후 재검증",
        "- [ ] 요구사항 보완 후 새 Run 실행",
        "- [ ] 자동화 또는 환경 보완 후 재실행",
        "- [ ] 이번 변경 보류",
        "",
        "- 검토자: ____________________",
        "- 검토일: ____________________",
        "- 최종 결론과 근거: ____________________",
        "- 후속 조치 담당자·기한: ____________________",
        "",
        "## 2. 자동 실행 요약",
        "",
        "| 항목 | 결과 |",
        "|---|---|",
        f"| Run ID | `{_markdown_text(report.run_id)}` |",
        f"| Checkpoint 4 | `{report.checkpoint_status.value}` |",
        f"| 자동 권고 | `{report.recommendation.value}` |",
        f"| 전체 실행 결과 | {report.total_results}건 |",
        f"| 제품 결과 | {report.product_result_count}건 |",
        f"| 환경 점검 | {report.environment_result_count}건 |",
        f"| 사람이 판단할 항목 | {len(report.findings)}건 |",
        "",
        "## 3. 항목별 사람 판정",
        "",
    ]
    if not report.findings:
        lines.extend(["사람이 별도로 판정할 자동 검토 항목이 없습니다.", ""])
    for index, finding in enumerate(report.findings, start=1):
        result = results_by_id.get(finding.test_id or "")
        test_case = candidates_by_id.get(finding.test_id or "")
        existing = existing_by_id.get(finding.test_id or "")
        requirements = finding.requirement_ids or (
            result.requirement_ids if result is not None else []
        )
        lines.extend(
            [
                f"### 3.{index} {category_labels[finding.category]} — `{_markdown_text(finding.finding_id)}`",
                "",
                "| 구분 | 내용 |",
                "|---|---|",
                f"| 관련 TC | `{_markdown_text(finding.test_id or '연결 없음')}` |",
                f"| TC 제목 | {_markdown_text(test_case.title if test_case is not None else '기존 회귀 또는 제목 정보 없음')} |",
                f"| 관련 Requirement | {', '.join(f'`{item}`' for item in requirements) or '없음'} |",
                f"| 실행 상태 | `{result.status.value if result is not None else finding.status.value if finding.status else '없음'}` |",
                f"| 자동 분류 근거 | {_markdown_text(finding.rationale)} |",
                "",
                "#### 기대 결과",
                "",
            ]
        )
        if test_case is not None:
            for expected in test_case.expected_results:
                timing = (
                    f" — 확인 시점: {_markdown_text(expected.verify_after_step)}"
                    if expected.verify_after_step
                    else ""
                )
                lines.append(
                    f"- `{expected.result_id}` {_markdown_text(expected.statement)}{timing}"
                )
        elif existing is not None:
            lines.extend(
                f"- {_markdown_text(behavior)}" for behavior in existing.covered_behaviors
            )
        else:
            lines.append("- 구조화된 기대 결과가 연결되지 않았습니다.")
        observation_detail = _human_review_observation(run_dir, result)
        lines.extend(
            [
                "",
                "#### 실제 관찰",
                "",
                f"- {observation_detail}",
            ]
        )
        if "enabled=True" in observation_detail:
            lines.append(
                "- `enabled=True`는 비활성화 기대와 달리 버튼이 실제로 활성 상태였음을 뜻합니다."
            )
        if (
            test_case is not None
            and result is not None
            and result.status == NeutralExecutionStatus.ASSERTION_FAILED
        ):
            mismatch_result_ids = set(re.findall(r"ER-\d{3}", observation_detail))
            lines.extend(
                f"- `{expected.result_id}`: 불일치가 기록되지 않아 해당 자동 검증은 통과했습니다."
                for expected in test_case.expected_results
                if expected.result_id not in mismatch_result_ids
            )
        lines.extend(["", "#### 실행 증거", ""])
        evidence_files = finding.evidence_files or (
            result.evidence_files if result is not None else []
        )
        if evidence_files:
            lines.extend(
                f"- [{_markdown_text(Path(item).name)}]({_markdown_text(item)})"
                for item in evidence_files
            )
        else:
            lines.append("- 연결된 증거 파일이 없습니다.")
        lines.extend(
            [
                "",
                "#### 사람 판정",
                "",
                "- [ ] 요구사항이 맞으며 제품 구현 수정이 필요함",
                "- [ ] 제품 동작이 맞으며 요구사항 수정 또는 명확화가 필요함",
                "- [ ] 자동화 계획·코드·Selector를 재검토해야 함",
                "- [ ] 실행 환경을 보완해 다시 실행해야 함",
                "- [ ] 현재 근거로 종결 가능함",
                "",
                "- 선택 근거: ____________________",
                "- 후속 조치: ____________________",
                "- 재검증 필요 여부·조건: ____________________",
                "",
            ]
        )
    lines.extend(["## 4. 추가 확인 사항", ""])
    if report.final_review_notes:
        lines.extend(f"- {_markdown_text(item)}" for item in report.final_review_notes)
    else:
        lines.append("- 없음")
    lines.extend(["", "## 5. 실행에서 제외된 항목", ""])
    if report.excluded_information_gaps:
        lines.append("### 정보 부족으로 제외")
        lines.append("")
        lines.extend(
            f"- {_markdown_text(item)}" for item in report.excluded_information_gaps
        )
        lines.append("")
    if report.automation_exclusions:
        lines.append("### 자동화 지원 범위로 실행하지 못한 TC")
        lines.append("")
        lines.extend(
            f"- `{item.tc_id}` {_markdown_text(item.reason)}"
            for item in report.automation_exclusions
        )
        lines.append("")
    if not report.excluded_information_gaps and not report.automation_exclusions:
        lines.extend(["정보 부족 또는 자동화 한계로 제외된 TC가 없습니다.", ""])
    lines.extend(
        [
            "## 6. 범위 경계",
            "",
            *(f"- {_markdown_text(item)}" for item in report.excluded_scope),
            "",
            "## 7. 원본 무결성 참조",
            "",
            f"- `final_report.json` SHA-256: `{_sha256_file(run_dir / 'final_report.json')}`",
            f"- `validation_execution.json` SHA-256: `{_sha256_file(run_dir / 'validation_execution.json')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_human_review_document(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    report: FinalReport,
    design: Agent2TestDesign | None,
    *,
    refresh: bool = False,
) -> tuple[Path, Path]:
    document_file = run_dir / _HUMAN_REVIEW_DOCUMENT
    manifest_file = run_dir / _HUMAN_REVIEW_MANIFEST
    document = _human_review_markdown(run_dir, bundle, report, design)
    document_changed = (
        document_file.exists()
        and document_file.read_text(encoding="utf-8") != document
    )
    if document_changed and not refresh:
        raise ValueError(
            "기존 사람 최종 검토 문서와 현재 생성 결과가 다릅니다. "
            "검증된 자동 생성 문서를 갱신하려면 --refresh를 사용하세요."
        )
    if document_changed and refresh:
        if not manifest_file.is_file():
            raise ValueError("기존 사람 최종 검토 문서의 Manifest가 없어 안전하게 갱신할 수 없습니다.")
        previous_manifest = _read_json_payload(manifest_file)
        if (
            previous_manifest.get("document_sha256") != _sha256_file(document_file)
            or previous_manifest.get("final_report_sha256")
            != _sha256_file(run_dir / "final_report.json")
        ):
            raise ValueError("기존 사람 최종 검토 문서 또는 원본 보고 해시가 달라 갱신을 차단했습니다.")
    if not document_file.exists() or document_changed:
        document_file.write_text(document, encoding="utf-8", newline="\n")
    manifest_payload = {
        "contract_version": "1.0",
        "run_id": report.run_id,
        "stage": "HUMAN_FINAL_REVIEW_DOCUMENT",
        "document_file": document_file.name,
        "document_sha256": _sha256_file(document_file),
        "final_report_sha256": _sha256_file(run_dir / "final_report.json"),
        "validation_execution_sha256": _sha256_file(
            run_dir / "validation_execution.json"
        ),
        "created_at": report.created_at,
    }
    if manifest_file.exists():
        existing_manifest = _read_json_payload(manifest_file)
        if existing_manifest != manifest_payload:
            if not refresh:
                raise ValueError("기존 사람 최종 검토 Manifest와 현재 검증 결과가 다릅니다.")
            _write_json(manifest_file, manifest_payload)
    else:
        _write_json(manifest_file, manifest_payload)
    return document_file, manifest_file


def run_human_review_document(args: argparse.Namespace) -> int:
    """Create an idempotent, human-readable decision form from verified results."""
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    report = _read_json_model(run_dir / "final_report.json", FinalReport)
    checkpoint = _read_json_model(run_dir / "checkpoint4.json", Checkpoint4Result)
    analysis_file = run_dir / "agent4_analysis.json"
    if (
        report.run_id != args.run_id
        or report.analysis_sha256 != _sha256_file(analysis_file)
        or report.checkpoint4_sha256 != _sha256_file(run_dir / "checkpoint4.json")
        or checkpoint.status != report.checkpoint_status
    ):
        raise ValueError("Checkpoint 4 또는 최종 보고 무결성이 일치하지 않습니다.")
    bundle = _read_json_model(
        run_dir / "validation_execution.json", ValidationExecutionBundle
    )
    design_file = run_dir / "agent2_test_design.json"
    design = (
        _read_json_model(design_file, Agent2TestDesign)
        if design_file.is_file()
        else None
    )
    document_file, manifest_file = _write_human_review_document(
        run_dir,
        bundle,
        report,
        design,
        refresh=getattr(args, "refresh", False),
    )
    print(f"사람 최종 검토 문서: {document_file.relative_to(run_dir).as_posix()}")
    print(f"문서 무결성 증거: {manifest_file.relative_to(run_dir).as_posix()}")
    return 0


def _slack_report_payload(report: FinalReport) -> dict[str, Any]:
    status_lines = [
        f"{status.value}: {report.status_counts.get(status, 0)}"
        for status in NeutralExecutionStatus
    ]
    finding_lines = [
        f"• {item.finding_id} | {item.category.value} | {item.test_id or '-'}"
        for item in report.findings
    ] or ["• 검토 항목 없음"]
    exclusion_lines = [
        f"• {item.tc_id} | {item.candidate_status.value}"
        for item in report.automation_exclusions
    ] or ["• 자동화 제외 없음"]
    return {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"QA 변경 검증 결과 · {report.recommendation.value}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Run ID*\n{report.run_id}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Checkpoint 4*\n{report.checkpoint_status.value}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*제품 결과*\n{report.product_result_count}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*환경 점검*\n{report.environment_result_count}",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*상태 집계*\n" + "\n".join(status_lines),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*검토 항목*\n" + "\n".join(finding_lines),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*자동화 제외 TC*\n" + "\n".join(exclusion_lines),
                },
            },
        ]
    }


def _notion_report_records(
    bundle: ValidationExecutionBundle, report: FinalReport
) -> list[dict[str, Any]]:
    findings_by_test = {
        item.test_id: item for item in report.findings if item.test_id is not None
    }
    records: list[dict[str, Any]] = []
    for result in _validation_results(bundle):
        finding = findings_by_test.get(result.test_id)
        records.append(
            {
                "run_id": report.run_id,
                "tc_id": result.test_id,
                "source": result.source.value,
                "requirement_ids": result.requirement_ids,
                "result": result.status.value,
                "finding_category": (
                    finding.category.value if finding is not None else "NONE"
                ),
                "recommendation": report.recommendation.value,
                "evidence_complete": result.evidence_complete,
            }
        )
    return records


def _http_json_request(
    method: str,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, Any]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = raw
        return int(response.status), body


def _send_slack_report(payload: dict[str, Any]) -> ExternalDestinationResult:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.SKIPPED,
            detail="SLACK_WEBHOOK_URL 환경변수가 없어 전송하지 않았습니다.",
        )
    try:
        status, _ = _http_json_request("POST", webhook_url, payload, timeout=15)
        if not 200 <= status < 300:
            raise RuntimeError(f"HTTP {status}")
        return ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.SENT,
            item_count=1,
            detail="검증된 최종 보고를 Slack으로 전송했습니다.",
        )
    except Exception as exc:
        return ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.FAILED,
            detail=f"Slack 전송 실패: {type(exc).__name__}",
        )


def _notion_status_name(status: str) -> str:
    return {
        NeutralExecutionStatus.PASSED.value: "Pass",
        NeutralExecutionStatus.ASSERTION_FAILED.value: "Fail",
        NeutralExecutionStatus.EXECUTION_ERROR.value: "Blocker",
        NeutralExecutionStatus.TIMEOUT.value: "Blocker",
        NeutralExecutionStatus.SKIPPED.value: "Review Needed",
    }.get(status, "Review Needed")


def _upsert_notion_reports(
    records: list[dict[str, Any]],
) -> ExternalDestinationResult:
    notion_token = os.getenv("NOTION_API_KEY", "").strip()
    data_source_id = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
    if not notion_token or not data_source_id:
        return ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.SKIPPED,
            detail="NOTION_API_KEY 또는 NOTION_DATA_SOURCE_ID 환경변수가 없어 전송하지 않았습니다.",
        )
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2026-03-11",
    }
    completed = 0
    try:
        for record in records:
            tc_id = str(record["tc_id"])
            query_status, query_body = _http_json_request(
                "POST",
                f"https://api.notion.com/v1/data_sources/{data_source_id}/query",
                {
                    "filter": {
                        "property": "TC-ID",
                        "title": {"equals": tc_id},
                    },
                    "page_size": 1,
                },
                headers=headers,
            )
            if not 200 <= query_status < 300 or not isinstance(query_body, dict):
                raise RuntimeError(f"Notion query HTTP {query_status}")
            finding = str(record["finding_category"])
            category = (
                "사전 점검"
                if record["source"] == ExecutionSource.ENVIRONMENT_PRECHECK.value
                else "예외/결함"
                if record["result"]
                in {
                    NeutralExecutionStatus.ASSERTION_FAILED.value,
                    NeutralExecutionStatus.EXECUTION_ERROR.value,
                    NeutralExecutionStatus.TIMEOUT.value,
                }
                else "엣지케이스"
            )
            properties = {
                "TC-ID": {"title": [{"text": {"content": tc_id}}]},
                "테스트 제목": {
                    "rich_text": [{"text": {"content": f"{tc_id} 변경 검증"}}]
                },
                "실행 결과": {
                    "select": {"name": _notion_status_name(str(record["result"]))}
                },
                "결과 ": {
                    "rich_text": [
                        {
                            "text": {
                                "content": (
                                    f"Run {record['run_id']} | {record['result']} | "
                                    f"{finding} | {record['recommendation']}"
                                )[:2000]
                            }
                        }
                    ]
                },
                "구분": {"select": {"name": category}},
                "우선 순위": {
                    "select": {
                        "name": (
                            "P1"
                            if record["result"]
                            in {
                                NeutralExecutionStatus.ASSERTION_FAILED.value,
                                NeutralExecutionStatus.EXECUTION_ERROR.value,
                            }
                            else "P2"
                        )
                    }
                },
            }
            results = query_body.get("results", [])
            if results:
                url = f"https://api.notion.com/v1/pages/{results[0]['id']}"
                method = "PATCH"
                payload = {"properties": properties}
            else:
                url = "https://api.notion.com/v1/pages"
                method = "POST"
                payload = {
                    "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                    "properties": properties,
                }
            mutation_status, _ = _http_json_request(
                method, url, payload, headers=headers
            )
            if not 200 <= mutation_status < 300:
                raise RuntimeError(f"Notion mutation HTTP {mutation_status}")
            completed += 1
        return ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.SENT,
            item_count=completed,
            detail=f"TC ID 기준으로 Notion {completed}건을 Upsert했습니다.",
        )
    except Exception as exc:
        return ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.FAILED,
            item_count=completed,
            detail=f"Notion Upsert 실패: {type(exc).__name__}",
        )


def run_external_reporting(args: argparse.Namespace) -> int:
    """Preview or send a previously validated Agent 4 report."""

    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    base_output_file = run_dir / "external_reporting.json"
    base_payload_files = (
        run_dir / "slack_payload.json",
        run_dir / "notion_payload.json",
    )
    if not base_output_file.exists() and any(
        path.exists() for path in base_payload_files
    ):
        raise ValueError("완료 결과가 없는 기존 외부 보고 Payload가 있어 덮어쓸 수 없습니다.")
    previous_reporting_sha256: str | None = None
    attempt_id: str | None = None
    if base_output_file.exists():
        previous = _read_json_model(base_output_file, ExternalReportingResult)
        if previous.run_id != args.run_id:
            raise ValueError("기존 외부 보고 Run ID가 요청과 다릅니다.")
        previous_reporting_sha256 = _sha256_file(base_output_file)
        attempt_id = (
            "ATTEMPT-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            + "-"
            + uuid.uuid4().hex[:6].upper()
        )
        output_dir = run_dir / "external_reporting_attempts" / attempt_id
    else:
        output_dir = run_dir
    output_file = output_dir / "external_reporting.json"
    slack_payload_file = output_dir / "slack_payload.json"
    notion_payload_file = output_dir / "notion_payload.json"
    if output_dir != run_dir and output_dir.exists():
        raise ValueError("동일한 외부 보고 시도 폴더가 이미 존재합니다.")
    final_report_file = run_dir / "final_report.json"
    checkpoint_file = run_dir / "checkpoint4.json"
    analysis_file = run_dir / "agent4_analysis.json"
    execution_file = run_dir / "validation_execution.json"
    report = _read_json_model(final_report_file, FinalReport)
    checkpoint = _read_json_model(checkpoint_file, Checkpoint4Result)
    bundle = _read_json_model(execution_file, ValidationExecutionBundle)
    allowed = (
        report.run_id == args.run_id == bundle.run_id
        and report.checkpoint_status == CheckStatus.PASS
        and checkpoint.status == CheckStatus.PASS
        and checkpoint.handoff_status == HandoffStatus.CONTINUE
        and report.analysis_sha256 == _sha256_file(analysis_file)
        and report.checkpoint4_sha256 == _sha256_file(checkpoint_file)
    )
    mode = "SEND" if getattr(args, "send", False) else "DRY_RUN"
    if not allowed:
        slack = ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.BLOCKED,
            detail="Checkpoint 4 또는 최종 보고 무결성이 통과하지 않아 전송을 차단했습니다.",
        )
        notion = ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.BLOCKED,
            detail="Checkpoint 4 또는 최종 보고 무결성이 통과하지 않아 전송을 차단했습니다.",
        )
    else:
        slack_payload = _slack_report_payload(report)
        notion_records = _notion_report_records(bundle, report)
        _write_json(slack_payload_file, slack_payload)
        _write_json(notion_payload_file, {"records": notion_records})
        if mode == "SEND":
            slack = _send_slack_report(slack_payload)
            notion = _upsert_notion_reports(notion_records)
        else:
            slack = ExternalDestinationResult(
                destination="SLACK",
                status=ExternalDeliveryStatus.PREVIEW,
                item_count=1,
                detail="Slack Payload를 생성했으며 외부 전송은 하지 않았습니다.",
            )
            notion = ExternalDestinationResult(
                destination="NOTION",
                status=ExternalDeliveryStatus.PREVIEW,
                item_count=len(notion_records),
                detail="Notion Upsert Payload를 생성했으며 외부 변경은 하지 않았습니다.",
            )
        slack = slack.model_copy(
            update={
                "payload_file": slack_payload_file.relative_to(run_dir).as_posix(),
                "payload_sha256": _sha256_file(slack_payload_file),
            }
        )
        notion = notion.model_copy(
            update={
                "payload_file": notion_payload_file.relative_to(run_dir).as_posix(),
                "payload_sha256": _sha256_file(notion_payload_file),
            }
        )
    result = ExternalReportingResult(
        run_id=args.run_id,
        mode=mode,
        final_report_sha256=_sha256_file(final_report_file),
        checkpoint4_sha256=_sha256_file(checkpoint_file),
        attempt_id=attempt_id,
        previous_reporting_sha256=previous_reporting_sha256,
        allowed=allowed,
        slack=slack,
        notion=notion,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_json(output_file, result.model_dump(mode="json"))
    print(f"Slack 보고: {slack.status.value}")
    print(f"Notion 보고: {notion.status.value}")
    print(f"외부 보고 증거: {output_file.relative_to(run_dir).as_posix()}")
    if not allowed:
        return 2
    if ExternalDeliveryStatus.FAILED in {slack.status, notion.status}:
        return 3
    return 0


def run_agent4(args: argparse.Namespace) -> int:
    """Analyze one verified validation bundle without rerunning tests or calling a model."""
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    outputs = (
        run_dir / "agent4_analysis.json",
        run_dir / "checkpoint4.json",
        run_dir / "final_report.json",
        run_dir / _HUMAN_REVIEW_DOCUMENT,
        run_dir / _HUMAN_REVIEW_MANIFEST,
        run_dir / "agent4_error.json",
    )
    if any(path.exists() for path in outputs):
        raise ValueError("이 Run에는 이미 Agent 4 보고 산출물이 있습니다. 기존 증거를 덮어쓸 수 없습니다.")
    try:
        execution_file = run_dir / "validation_execution.json"
        bundle = _read_json_model(execution_file, ValidationExecutionBundle)
        manifest = _read_json_payload(run_dir / "validation_manifest.json")
        checks: list[CheckResult] = []
        manifest_hash = manifest.get("validation_execution_sha256")
        execution_hash_matches = (
            isinstance(manifest_hash, str)
            and manifest_hash == _sha256_file(execution_file)
        )
        source_agent3_manifest = run_dir / "agent3_manifest.json"
        source_agent3_trial = run_dir / "agent3_trial.json"
        common_source_chain_matches = (
            manifest.get("stage") == "VALIDATION_EXECUTION"
            and manifest.get("status") == bundle.status.value
            and manifest.get("project1_modified") is False
            and all(
                result.target_sha256 == manifest.get("target_sha256")
                for result in bundle.candidate_results
            )
            and all(
                result.target_sha256 == manifest.get("target_sha256")
                for result in _validation_results(bundle)
            )
            and bundle.environment_precheck.test_sha256
            == manifest.get("baseline_test_sha256")
            and all(
                result.test_sha256 == manifest.get("baseline_test_sha256")
                for result in bundle.regression_results
            )
        )
        new_source_chain_matches = _agent4_new_source_chain_matches(
            run_dir, bundle, manifest
        )
        if new_source_chain_matches is None:
            source_chain_matches = (
                common_source_chain_matches
                and source_agent3_manifest.is_file()
                and source_agent3_trial.is_file()
                and manifest.get("source_agent3_manifest_sha256")
                == _sha256_file(source_agent3_manifest)
                and manifest.get("source_agent3_trial_sha256")
                == _sha256_file(source_agent3_trial)
                and manifest.get("candidate_reused") == bundle.candidate_result.reused
                and manifest.get("validation_candidate_sha256")
                == bundle.candidate_result.test_sha256
                and _agent4_candidate_artifact_matches(
                    run_dir, bundle.candidate_result
                )
            )
            validation_trial_hash = manifest.get("validation_candidate_trial_sha256")
            validation_trial_file = run_dir / "validation_candidate_trial.json"
            validation_trial_matches = (
                bundle.candidate_result.reused
                and validation_trial_hash is None
                and not validation_trial_file.exists()
                or not bundle.candidate_result.reused
                and isinstance(validation_trial_hash, str)
                and validation_trial_file.is_file()
                and validation_trial_hash == _sha256_file(validation_trial_file)
            )
        else:
            source_chain_matches = (
                common_source_chain_matches and new_source_chain_matches
            )
            validation_trial_matches = True
        hash_matches = (
            execution_hash_matches
            and source_chain_matches
            and validation_trial_matches
        )
        checks.append(
            CheckResult(
                rule_id="CP4-001",
                status=CheckStatus.PASS if bundle.run_id == args.run_id and manifest.get("run_id") == args.run_id else CheckStatus.FAIL,
                message="단일 Run ID가 실행 결과와 Manifest에 일치합니다."
                if bundle.run_id == args.run_id and manifest.get("run_id") == args.run_id
                else "실행 결과 또는 Manifest의 Run ID가 요청 Run ID와 다릅니다.",
            )
        )
        checks.append(
            CheckResult(
                rule_id="CP4-002",
                status=CheckStatus.PASS if hash_matches else CheckStatus.FAIL,
                message="검증 실행·Agent 3·후보·대상·기존 테스트 SHA-256 체인이 Manifest와 일치합니다."
                if hash_matches
                else "검증 실행 또는 이전 단계 SHA-256 체인이 Manifest와 일치하지 않습니다.",
            )
        )
        results = _validation_results(bundle)
        test_ids = [result.test_id for result in results]
        duplicate_ids = sorted({test_id for test_id in test_ids if test_ids.count(test_id) > 1})
        checks.append(
            CheckResult(
                rule_id="CP4-003",
                status=CheckStatus.PASS if not duplicate_ids else CheckStatus.FAIL,
                message="실행 결과에 중복 TC가 없습니다."
                if not duplicate_ids
                else f"실행 결과에 중복 TC가 있습니다: {', '.join(duplicate_ids)}",
            )
        )
        source_contract_ok = (
            all(
                result.source == ExecutionSource.NEW_AUTOMATION_CANDIDATE
                for result in bundle.candidate_results
            )
            and bundle.environment_precheck.source == ExecutionSource.ENVIRONMENT_PRECHECK
            and all(
                result.source == ExecutionSource.EXISTING_REGRESSION
                for result in bundle.regression_results
            )
        )
        status_contract_issues = _agent4_status_contract_issues(results)
        source_contract_issues = [] if source_contract_ok else [
            "후보·환경 사전 점검·기존 회귀의 출처가 계약과 다릅니다"
        ]
        source_contract_issues.extend(status_contract_issues)
        source_contract_ok = source_contract_ok and not status_contract_issues
        checks.append(
            CheckResult(
                rule_id="CP4-004",
                status=CheckStatus.PASS if source_contract_ok else CheckStatus.FAIL,
                message="후보·환경 사전 점검·기존 회귀의 출처·상태·종료 코드가 계약과 일치합니다."
                if source_contract_ok
                else (
                    "실행 결과 출처 또는 상태 계약이 일치하지 않습니다: "
                    + "; ".join(source_contract_issues)
                ),
            )
        )
        regression_ids = [result.test_id for result in bundle.regression_results]
        regression_execution_ok = (
            (
                bundle.status == ValidationStageStatus.COMPLETED
                and bundle.environment_precheck.status
                == NeutralExecutionStatus.PASSED
                and bundle.blocked_reason is None
                and regression_ids == bundle.selected_regression_ids
            )
            or (
                bundle.status == ValidationStageStatus.BLOCKED
                and bundle.environment_precheck.status
                != NeutralExecutionStatus.PASSED
                and not regression_ids
                and bundle.blocked_reason == "ENVIRONMENT_PRECHECK_NOT_PASSED"
            )
        )
        checks.append(
            CheckResult(
                rule_id="CP4-005",
                status=CheckStatus.PASS if regression_execution_ok else CheckStatus.FAIL,
                message="선택된 기존 회귀의 실행 수와 차단 상태가 실행 결과와 일치합니다."
                if regression_execution_ok
                else "선택된 기존 회귀의 실행 결과 또는 차단 상태가 일치하지 않습니다.",
            )
        )
        evidence_issues = _agent4_evidence_issues(run_dir, results)
        checks.append(
            CheckResult(
                rule_id="CP4-006",
                status=CheckStatus.PASS if not evidence_issues else CheckStatus.FAIL,
                message="실행 증거 파일의 경로·존재·SHA-256이 계약과 일치합니다."
                if not evidence_issues
                else f"실행 증거 검증 실패: {'; '.join(evidence_issues)}",
            )
        )
        environment_results = [
            result
            for result in results
            if result.source == ExecutionSource.ENVIRONMENT_PRECHECK
        ]
        fixture_results = [
            result
            for result in results
            if result.source != ExecutionSource.ENVIRONMENT_PRECHECK
            and result.test_id.startswith("TC-PIPE-")
        ]
        product_results = [
            result
            for result in results
            if result.source != ExecutionSource.ENVIRONMENT_PRECHECK
            and not result.test_id.startswith("TC-PIPE-")
        ]
        checks.append(
            CheckResult(
                rule_id="CP4-007",
                status=CheckStatus.PASS,
                message=(
                    "제품 TC와 파이프라인 고정 사례를 분리했습니다. "
                    f"제품 TC {len(product_results)}건, 환경 점검 {len(environment_results)}건, "
                    f"고정 사례 {len(fixture_results)}건입니다."
                ),
            )
        )
        checkpoint_status = (
            CheckStatus.PASS
            if all(check.status == CheckStatus.PASS for check in checks)
            else CheckStatus.FAIL
        )
        checkpoint = Checkpoint4Result(
            status=checkpoint_status,
            handoff_status=(HandoffStatus.CONTINUE if checkpoint_status == CheckStatus.PASS else HandoffStatus.BLOCKED),
            checks=checks,
        )
        findings: list[Agent4Finding] = []
        for result in results:
            finding = _agent4_finding_for_result(result, len(findings) + 1)
            if finding is not None:
                findings.append(finding)
        if bundle.status == ValidationStageStatus.BLOCKED:
            findings.append(
                Agent4Finding(
                    finding_id=f"FIND-{len(findings) + 1:03d}",
                    category=Agent4FindingCategory.INSUFFICIENT_EVIDENCE,
                    rationale="환경 사전 점검 차단으로 선택된 관련 회귀가 실행되지 않았습니다.",
                )
            )
        status_counts = {status: sum(result.status == status for result in results) for status in NeutralExecutionStatus}
        analysis = Agent4Analysis(
            run_id=args.run_id,
            validation_execution_sha256=_sha256_file(execution_file),
            total_results=len(results),
            status_counts=status_counts,
            product_result_count=len(product_results),
            environment_result_count=len(environment_results),
            pipeline_fixture_result_count=len(fixture_results),
            findings=findings,
            excluded_scope=bundle.excluded_scope,
            excluded_information_gaps=bundle.excluded_information_gaps,
            final_review_notes=bundle.final_review_notes,
            automation_exclusions=bundle.automation_exclusions,
            recommendation=_agent4_recommendation(findings, checkpoint_status),
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        analysis_file = run_dir / "agent4_analysis.json"
        checkpoint_file = run_dir / "checkpoint4.json"
        _write_json(analysis_file, analysis.model_dump(mode="json", by_alias=True))
        _write_json(checkpoint_file, checkpoint.model_dump(mode="json", by_alias=True))
        report = FinalReport(
            run_id=args.run_id,
            analysis_sha256=_sha256_file(analysis_file),
            checkpoint4_sha256=_sha256_file(checkpoint_file),
            total_results=analysis.total_results,
            status_counts=analysis.status_counts,
            product_result_count=analysis.product_result_count,
            environment_result_count=analysis.environment_result_count,
            pipeline_fixture_result_count=analysis.pipeline_fixture_result_count,
            findings=analysis.findings,
            excluded_scope=analysis.excluded_scope,
            excluded_information_gaps=analysis.excluded_information_gaps,
            final_review_notes=analysis.final_review_notes,
            automation_exclusions=analysis.automation_exclusions,
            recommendation=analysis.recommendation,
            checkpoint_status=checkpoint.status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _write_json(run_dir / "final_report.json", report.model_dump(mode="json", by_alias=True))
        design_file = run_dir / "agent2_test_design.json"
        design = (
            _read_json_model(design_file, Agent2TestDesign)
            if design_file.is_file()
            else None
        )
        _write_human_review_document(run_dir, bundle, report, design)
    except Exception as exc:
        _write_json(
            run_dir / "agent4_error.json",
            {"run_id": args.run_id, "stage": "AGENT_4_ANALYSIS", "error_type": type(exc).__name__, "message": str(exc), "created_at": datetime.now(timezone.utc).isoformat()},
        )
        raise
    print(f"Run ID: {args.run_id}")
    print(f"Checkpoint 4: {checkpoint.status.value}")
    print(f"최종 권고: {report.recommendation.value}")
    print(f"검토 항목: {len(report.findings)}")
    print(f"사람 최종 검토 문서: {_HUMAN_REVIEW_DOCUMENT}")
    print(f"산출물 위치: {run_dir}")
    delivery_exit = run_external_reporting(
        argparse.Namespace(
            run_id=args.run_id,
            runs_root=args.runs_root,
            send=getattr(args, "send", False),
        )
    )
    return delivery_exit if checkpoint.status == CheckStatus.PASS else 2


def _write_orchestrator_manifest(
    run_dir: Path,
    run_id: str,
    *,
    status: str,
    selected_tc_id: str | None,
    target_html: Path,
    stage_exit_codes: dict[str, int],
    stopped_at: str | None,
    error: Exception | None = None,
) -> None:
    """Write the one-command A1→A3 summary without replacing stage evidence."""
    stage_manifests = {
        "agent1_manifest_sha256": run_dir / "run_manifest.json",
        "agent2_manifest_sha256": run_dir / "agent2_manifest.json",
        "agent3_manifest_sha256": run_dir / "agent3_manifest.json",
    }
    payload: dict[str, Any] = {
        "contract_version": "1.0",
        "run_id": run_id,
        "stage": "ORCHESTRATOR_AGENT_1_TO_3",
        "status": status,
        "selected_tc_id": selected_tc_id,
        "target_file": target_html.name,
        "stage_exit_codes": stage_exit_codes,
        "completed_stages": [
            stage
            for stage in ("agent1", "agent2", "agent3")
            if stage_exit_codes.get(stage) == 0
        ],
        "stopped_at": stopped_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for key, path in stage_manifests.items():
        payload[key] = _sha256_file(path) if path.is_file() else None
    agent3_manifest_file = run_dir / "agent3_manifest.json"
    if agent3_manifest_file.is_file():
        agent3_manifest = _read_json_payload(agent3_manifest_file)
        payload["candidate_status"] = agent3_manifest.get("candidate_status")
    trial_file = run_dir / "agent3_trial.json"
    if trial_file.is_file():
        payload["trial_outcome"] = _read_json_payload(trial_file).get("outcome")
    selection_file = run_dir / "agent3_selection.json"
    if selection_file.is_file():
        payload["agent3_selection_sha256"] = _sha256_file(selection_file)
        selection = _read_json_payload(selection_file)
        payload["selected_tc_ids"] = selection.get("selected_tc_ids", [])
    summary_file = run_dir / "agent3_run_summary.json"
    if summary_file.is_file():
        summary = _read_json_payload(summary_file)
        payload["agent3_run_summary_sha256"] = _sha256_file(summary_file)
        payload["executed_tc_ids"] = summary.get("executed_tc_ids", [])
        payload["자동화_제외_TC"] = summary.get("자동화_제외_TC", [])
    if error is not None:
        payload["error_type"] = type(error).__name__
    _write_json(run_dir / "orchestrator_manifest.json", payload)


def _orchestrator_status(exit_code: int) -> str:
    if exit_code == 0:
        return "PASS"
    if exit_code == 1:
        return "ERROR"
    return "STOPPED"


def _select_agent3_tc(
    design: Agent2TestDesign,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Backward-compatible helper returning the first ordered Agent 3 TC."""
    selected, summaries = _select_agent3_tcs(design)
    return (selected[0] if selected else None), summaries


def _select_agent3_tcs(
    design: Agent2TestDesign,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Order every current-Run TC that may proceed to Agent 3."""
    candidates: list[tuple[ProductTestCaseCandidate, Agent3EligibilityResult]] = []
    summaries: list[dict[str, Any]] = []
    for test_case in design.test_cases:
        if test_case.purpose != TcPurpose.CHANGE_VALIDATION:
            summaries.append(
                {
                    "tc_id": test_case.tc_id,
                    "purpose": test_case.purpose.value,
                    "test_type": test_case.test_type.value,
                    "control_path": test_case.control_path.value,
                    "target_role": test_case.target_role,
                    "automation_candidate": test_case.automation_candidate,
                    "status": Agent3EligibilityStatus.NOT_AUTOMATABLE.value,
                    "candidate_status": AutomationCandidateStatus.NOT_AUTOMATABLE.value,
                    "missing_capabilities": [
                        "관련 기존 TC는 Agent 3에서 다시 구현하지 않고 execute 단계에서 회귀 실행합니다."
                    ],
                    "generic_discovery_required": False,
                }
            )
            continue
        eligibility = evaluate_agent3_eligibility(test_case)
        summaries.append(
            {
                "tc_id": test_case.tc_id,
                "purpose": test_case.purpose.value,
                "test_type": test_case.test_type.value,
                "control_path": test_case.control_path.value,
                "target_role": test_case.target_role,
                "automation_candidate": test_case.automation_candidate,
                "status": eligibility.status.value,
                "candidate_status": (
                    eligibility.candidate_status.value
                    if eligibility.candidate_status is not None
                    else None
                ),
                "missing_capabilities": eligibility.missing_capabilities,
                "generic_discovery_required": (
                    eligibility.generic_discovery_required
                ),
            }
        )
        if eligibility.model_call_allowed:
            candidates.append((test_case, eligibility))
    if not candidates:
        return [], summaries

    def priority(
        item: tuple[ProductTestCaseCandidate, Agent3EligibilityResult],
    ) -> tuple[Any, ...]:
        test_case, eligibility = item
        layers = {result.observation_layer for result in test_case.expected_results}
        return (
            eligibility.status != Agent3EligibilityStatus.ELIGIBLE,
            test_case.purpose != TcPurpose.CHANGE_VALIDATION,
            ObservationLayer.NOTIFICATION not in layers,
            test_case.restore_required,
            test_case.test_type != TcType.BOUNDARY,
            test_case.tc_id,
        )

    selected = [item[0].tc_id for item in sorted(candidates, key=priority)]
    return selected, summaries


def _select_agent3_tc_from_run(
    run_dir: Path,
    run_id: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    _, _, _, design, _, _ = _load_verified_agent2_run(run_dir, run_id)
    return _select_agent3_tc(design)


def _select_agent3_tcs_from_run(
    run_dir: Path,
    run_id: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    _, _, _, design, _, _ = _load_verified_agent2_run(run_dir, run_id)
    return _select_agent3_tcs(design)


def _agent3_run_entry(
    run_dir: Path,
    tc_id: str,
    artifact_dir: Path,
    exit_code: int,
    error: Exception | None = None,
) -> dict[str, Any]:
    relative_dir = artifact_dir.relative_to(run_dir).as_posix()
    entry: dict[str, Any] = {
        "tc_id": tc_id,
        "artifact_dir": relative_dir,
        "exit_code": exit_code,
        "status": "ERROR" if error is not None else _orchestrator_status(exit_code),
        "candidate_status": None,
        "trial_outcome": None,
        "reason": None,
        "manifest_sha256": None,
        "trial_sha256": None,
    }
    manifest_file = artifact_dir / "agent3_manifest.json"
    if manifest_file.is_file():
        manifest = _read_json_payload(manifest_file)
        entry["checkpoint_status"] = manifest.get("status")
        entry["candidate_status"] = manifest.get("candidate_status")
        entry["manifest_sha256"] = _sha256_file(manifest_file)
        trial_file = artifact_dir / "agent3_trial.json"
        if trial_file.is_file():
            entry["trial_outcome"] = _read_json_payload(trial_file).get("outcome")
            entry["trial_sha256"] = _sha256_file(trial_file)
        plan_file = artifact_dir / "agent3_automation_plan.json"
        if plan_file.is_file():
            plan = _read_json_payload(plan_file)
            reasons = plan.get("extension_reasons")
            if isinstance(reasons, list) and reasons:
                entry["reason"] = " / ".join(str(item) for item in reasons)
    eligibility_file = artifact_dir / "agent3_eligibility.json"
    if entry["reason"] is None and eligibility_file.is_file():
        eligibility = _read_json_payload(eligibility_file)
        missing = eligibility.get("missing_capabilities")
        if isinstance(missing, list) and missing:
            entry["reason"] = " / ".join(str(item) for item in missing)
    if error is not None:
        entry["reason"] = str(error)
        entry["candidate_status"] = AutomationCandidateStatus.BLOCKED.value
    if entry["reason"] is None and exit_code != 0:
        entry["reason"] = "Agent 3 후보 시험이 신뢰 가능한 완료 상태에 도달하지 못했습니다."
    return entry


def _automation_exclusion_from_run_entry(entry: dict[str, Any]) -> dict[str, Any]:
    raw_status = entry.get("candidate_status") or AutomationCandidateStatus.BLOCKED.value
    try:
        status = AutomationCandidateStatus(raw_status)
    except ValueError:
        status = AutomationCandidateStatus.BLOCKED
    return AutomationExclusion(
        tc_id=entry["tc_id"],
        candidate_status=status,
        reason=entry.get("reason") or "자동화 실행에서 제외됐습니다.",
        artifact_dir=entry.get("artifact_dir"),
    ).model_dump(mode="json")


def run_pipeline(args: argparse.Namespace) -> int:
    """Run Agent 1→2 and continue every eligible Agent 3 candidate."""
    run_id = _new_run_id()
    runs_root = Path(args.runs_root).resolve()
    run_dir = runs_root / run_id
    target_html = Path(args.target_html).resolve()
    if not target_html.is_file():
        raise ValueError(f"Agent 3 target HTML does not exist: {target_html.name}")
    explicit_tc_id = None if args.tc_id in {None, "AUTO"} else args.tc_id
    selected_tc_id = explicit_tc_id
    stage_exit_codes: dict[str, int] = {}
    current_stage = "agent1"
    try:
        agent1_exit = run_agent1(
            argparse.Namespace(
                request=args.request,
                srs=args.srs,
                runs_root=str(runs_root),
                model=args.model,
                run_id=run_id,
            )
        )
        stage_exit_codes["agent1"] = agent1_exit
        if agent1_exit != 0:
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status=_orchestrator_status(agent1_exit),
                selected_tc_id=selected_tc_id,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at="agent1",
            )
            return agent1_exit

        current_stage = "agent2"
        agent2_exit = run_agent2(
            argparse.Namespace(
                run_id=run_id,
                runs_root=str(runs_root),
                model=args.model,
            )
        )
        stage_exit_codes["agent2"] = agent2_exit
        if agent2_exit != 0:
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status=_orchestrator_status(agent2_exit),
                selected_tc_id=selected_tc_id,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at="agent2",
            )
            return agent2_exit

        current_stage = "agent3"
        auto_selected_ids, selection_candidates = _select_agent3_tcs_from_run(
            run_dir, run_id
        )
        selected_tc_ids = (
            [explicit_tc_id] if explicit_tc_id is not None else auto_selected_ids
        )
        selected_tc_id = selected_tc_ids[0] if selected_tc_ids else None
        prefiltered_exclusions: list[dict[str, Any]] = []
        if explicit_tc_id is None:
            selected_set = set(selected_tc_ids)
            for item in selection_candidates:
                if item.get("automation_candidate") and item.get("tc_id") not in selected_set:
                    prefiltered_exclusions.append(
                        AutomationExclusion(
                            tc_id=item["tc_id"],
                            candidate_status=AutomationCandidateStatus.NOT_AUTOMATABLE,
                            reason=(
                                " / ".join(item.get("missing_capabilities") or [])
                                or "현재 자동화 실행 범위에 포함되지 않습니다."
                            ),
                        ).model_dump(mode="json")
                    )
        selection_file = run_dir / "agent3_selection.json"
        _write_json(
            selection_file,
            {
                "contract_version": "1.1",
                "run_id": run_id,
                "stage": "AGENT_3_SELECTION",
                "status": "SELECTED" if selected_tc_ids else "NOT_AUTOMATABLE",
                "selected_tc_id": selected_tc_id,
                "selected_tc_ids": selected_tc_ids,
                "candidates": selection_candidates,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if not selected_tc_ids:
            stage_exit_codes["agent3"] = 2
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status="STOPPED",
                selected_tc_id=None,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at="agent3",
            )
            print(f"Run ID: {run_id}")
            print("Agent 3 selection: NO ELIGIBLE TC")
            print("Agent 3 model call: NOT EXECUTED")
            print(f"Orchestrator manifest: {run_dir / 'orchestrator_manifest.json'}")
            return 2

        print("Agent 3 selected TCs: " + ", ".join(selected_tc_ids))
        candidates_root = run_dir / "agent3_candidates"
        run_entries: list[dict[str, Any]] = []
        for tc_id in selected_tc_ids:
            artifact_dir = candidates_root / tc_id
            candidate_error: Exception | None = None
            try:
                candidate_exit = run_agent3(
                    argparse.Namespace(
                        run_id=run_id,
                        tc_id=tc_id,
                        target_html=str(target_html),
                        runs_root=str(runs_root),
                        model=args.model,
                        timeout=args.timeout,
                        preview_only=False,
                        artifact_dir=str(artifact_dir),
                    )
                )
            except Exception as exc:
                candidate_error = exc
                candidate_exit = 1
            run_entries.append(
                _agent3_run_entry(
                    run_dir, tc_id, artifact_dir, candidate_exit, candidate_error
                )
            )

        successful_entries = [item for item in run_entries if item["exit_code"] == 0]
        automation_exclusions = [
            *prefiltered_exclusions,
            *[
                _automation_exclusion_from_run_entry(item)
                for item in run_entries
                if item["exit_code"] != 0
            ],
        ]
        run_status = (
            "PASS"
            if successful_entries and not automation_exclusions
            else "PARTIAL"
            if successful_entries
            else "STOPPED"
        )
        summary_file = run_dir / "agent3_run_summary.json"
        _write_json(
            summary_file,
            {
                "contract_version": "1.0",
                "run_id": run_id,
                "stage": "AGENT_3_RUN_SUMMARY",
                "status": run_status,
                "selected_tc_ids": selected_tc_ids,
                "executed_tc_ids": [item["tc_id"] for item in successful_entries],
                "entries": run_entries,
                "자동화_제외_TC": automation_exclusions,
                "target_file": target_html.name,
                "target_sha256": _sha256_file(target_html),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        agent3_exit = 0 if successful_entries else 2
        stage_exit_codes["agent3"] = agent3_exit
        status = run_status
        _write_orchestrator_manifest(
            run_dir,
            run_id,
            status=status,
            selected_tc_id=selected_tc_id,
            target_html=target_html,
            stage_exit_codes=stage_exit_codes,
            stopped_at=None if agent3_exit == 0 else "agent3",
        )
        print(f"Orchestrator status: {status}")
        print(f"Agent 3 completed candidates: {len(successful_entries)}")
        print(f"Agent 3 excluded candidates: {len(automation_exclusions)}")
        print(f"Orchestrator manifest: {run_dir / 'orchestrator_manifest.json'}")
        return agent3_exit
    except Exception as exc:
        if run_dir.is_dir():
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status="ERROR",
                selected_tc_id=selected_tc_id,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at=current_stage,
                error=exc,
            )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa-pipeline-v2",
        description="변경 요구사항 기반 QA Pipeline V2",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    agent1 = subparsers.add_parser("agent1", help="Agent 1과 Checkpoint 1 실행")
    agent1.add_argument("--request", required=True, help="변경 요청 JSON 경로")
    agent1.add_argument("--srs", default=str(DEFAULT_SRS), help="제품 SRS Markdown 경로")
    agent1.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent1.add_argument(
        "--model",
        default=None,
        help="OpenAI 모델 ID. 미지정 시 OPENAI_MODEL 또는 gpt-5.6-terra",
    )
    agent1.set_defaults(handler=run_agent1)

    agent2 = subparsers.add_parser("agent2", help="Agent 2와 Checkpoint 2 실행")
    agent2.add_argument("--run-id", required=True, help="CP1을 통과한 Run ID")
    agent2.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent2.add_argument(
        "--model",
        default=None,
        help="OpenAI 모델 ID. 미지정 시 OPENAI_MODEL 또는 gpt-5.6-terra",
    )
    agent2.set_defaults(handler=run_agent2)

    agent3 = subparsers.add_parser("agent3", help="Run Agent 3, CP3, and the isolated trial")
    agent3.add_argument("--run-id", required=True, help="Run ID whose CP2 status is PASS")
    agent3.add_argument("--tc-id", required=True, help="One CP2-approved automation candidate TC ID")
    agent3.add_argument("--target-html", required=True, help="Read-only local virtual controller HTML path")
    agent3.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT), help="Run artifact root")
    agent3.add_argument("--model", default=None, help="OpenAI model ID")
    agent3.add_argument("--timeout", type=int, default=30, help="Isolated trial timeout in seconds")
    agent3.add_argument("--preview-only", action="store_true", help="Inspect UI and write the exact model-input preview without calling the API")
    agent3.set_defaults(handler=run_agent3)

    pipeline = subparsers.add_parser(
        "pipeline",
        help="Agent 1→2→3, CP1→3, and the candidate trial in one command",
    )
    pipeline.add_argument("--request", required=True, help="Change-request JSON path")
    pipeline.add_argument(
        "--tc-id",
        default="AUTO",
        help="Current-Run TC ID, or AUTO to select one eligible CP2 candidate",
    )
    pipeline.add_argument(
        "--target-html",
        required=True,
        help="Read-only local virtual controller HTML path",
    )
    pipeline.add_argument("--srs", default=str(DEFAULT_SRS), help="Product SRS Markdown path")
    pipeline.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT), help="Run artifact root")
    pipeline.add_argument("--model", default=None, help="OpenAI model ID shared by Agent 1→3")
    pipeline.add_argument("--timeout", type=int, default=30, help="Isolated trial timeout in seconds")
    pipeline.set_defaults(handler=run_pipeline)

    execute = subparsers.add_parser(
        "execute",
        help="신규 자동화 후보 시험 결과를 재사용하고 관련 기존 회귀 TC 실행",
    )
    execute.add_argument("--run-id", required=True, help="Agent 3 시험이 완료된 Run ID")
    execute.add_argument(
        "--target-html",
        required=True,
        help="읽기 전용 Project1 virtual-controller.html 경로",
    )
    execute.add_argument(
        "--baseline-tests",
        default=None,
        help="Project1 tests/test_controller.py 경로. 생략 시 대상 HTML 옆 tests 폴더 사용",
    )
    execute.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    execute.add_argument(
        "--timeout", type=int, default=60, help="기존 TC 한 건당 제한 시간(초)"
    )
    execute.set_defaults(handler=run_validation_execution)
    agent4 = subparsers.add_parser(
        "agent4",
        help="검증 실행 결과를 재실행 없이 규칙 기반으로 분류하고 최종 보고 생성",
    )
    agent4.add_argument("--run-id", required=True, help="검증 실행이 완료된 Run ID")
    agent4.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent4.add_argument(
        "--send",
        action="store_true",
        help="CP4 통과 후 Slack·Notion에 실제 전송. 기본값은 Dry-run",
    )
    agent4.set_defaults(handler=run_agent4)
    reporting = subparsers.add_parser(
        "report",
        help="이미 완료된 Agent 4 최종 보고의 Slack·Notion Payload 생성 또는 전송",
    )
    reporting.add_argument("--run-id", required=True, help="Agent 4가 완료된 Run ID")
    reporting.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    reporting.add_argument(
        "--send",
        action="store_true",
        help="Slack·Notion에 실제 전송. 기본값은 Dry-run",
    )
    reporting.set_defaults(handler=run_external_reporting)
    human_review = subparsers.add_parser(
        "human-review",
        help="완료된 Agent 4 결과에서 사람이 작성할 최종 검토 Markdown 생성",
    )
    human_review.add_argument("--run-id", required=True, help="Agent 4가 완료된 Run ID")
    human_review.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    human_review.add_argument(
        "--refresh",
        action="store_true",
        help="기존 자동 생성 문서와 Manifest 해시를 확인한 뒤 현재 양식으로 갱신",
    )
    human_review.set_defaults(handler=run_human_review_document)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError, Agent1Error, Agent2Error, Agent3Error) as exc:
        parser.error(str(exc))
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
