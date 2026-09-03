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


class ConditionChangeRole(str, Enum):
    CHANGED = "변경"
    UNCHANGED = "유지"
    SUPPORTING = "보조_근거"


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
    change_role: ConditionChangeRole | None = Field(
        default=None, alias="변경_구분"
    )

    @model_validator(mode="after")
    def infer_legacy_change_role(self) -> "ConfirmedCondition":
        """Read historical Runs conservatively while new Runs provide an explicit role."""

        if self.change_role is not None:
            return self
        if self.source_type == ConditionSource.SRS:
            self.change_role = ConditionChangeRole.SUPPORTING
        else:
            # Missing metadata must not hide a real change.  Treat it as changed
            # so CP2 asks for coverage instead of silently routing it to regression.
            self.change_role = ConditionChangeRole.CHANGED
        return self


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

    tc_id: Annotated[str, StringConstraints(pattern=r"^TC-[A-Z0-9]+-\d{3}$")]
    source_condition_ids: list[
        Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    ] = Field(min_length=1)
    selection_reason: NonEmptyStr


class SrsRevisionProposal(StrictModel):
    """Agent 2 proposal that a person must approve before the baseline SRS changes."""

    proposal_id: Annotated[str, StringConstraints(pattern=r"^SRS-REV-\d{3}$")]
    requirement_id: RequirementId
    source_condition_ids: list[
        Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    ] = Field(min_length=1)
    current_acceptance_criteria: NonEmptyStr
    proposed_acceptance_criteria: NonEmptyStr
    reason: NonEmptyStr


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
    test_cases: list[ProductTestCaseCandidate] = Field(default_factory=list)
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
    srs_revision_proposals: list[SrsRevisionProposal] = Field(
        default_factory=list, alias="SRS_개정_제안"
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
    srs_revision_proposals: list[SrsRevisionProposal] = Field(
        default_factory=list, alias="SRS_개정_제안"
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
    srs_revision_proposals: list[SrsRevisionProposal] = Field(
        default_factory=list, alias="SRS_개정_제안"
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
    srs_revision_proposals: list[SrsRevisionProposal] = Field(
        default_factory=list, alias="SRS_개정_제안"
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
    source: str = "BASELINE"
    test_case_file: str | None = None
    test_case_sha256: str | None = None
    automation_file: str | None = None
    automation_sha256: str | None = None


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


def _existing_regression_by_id(
    catalog: tuple[ExistingRegressionSpec, ...],
) -> dict[str, ExistingRegressionSpec]:
    by_id = {item.tc_id: item for item in catalog}
    if len(by_id) != len(catalog):
        raise ValueError("기존 TC 카탈로그에 중복 ID가 있습니다.")
    return by_id


def _catalog_snapshot_entry(spec: ExistingRegressionSpec) -> dict[str, Any]:
    return {
        "tc_id": spec.tc_id,
        "test_function": spec.test_function,
        "requirement_ids": list(spec.requirement_ids),
        "covered_behaviors": list(spec.covered_behaviors),
        "source": spec.source,
        "test_case_file": spec.test_case_file,
        "test_case_sha256": spec.test_case_sha256,
        "automation_file": spec.automation_file,
        "automation_sha256": spec.automation_sha256,
    }


def _catalog_from_snapshot(payload: dict[str, Any]) -> tuple[ExistingRegressionSpec, ...]:
    entries = payload.get("approved_assets") or []
    if not isinstance(entries, list):
        raise ValueError("승인 TC 카탈로그 Snapshot 형식이 올바르지 않습니다.")
    approved: list[ExistingRegressionSpec] = []
    for item in entries:
        if not isinstance(item, dict) or item.get("source") != "APPROVED":
            raise ValueError("승인 TC 카탈로그 Snapshot 항목이 올바르지 않습니다.")
        approved.append(
            ExistingRegressionSpec(
                tc_id=str(item.get("tc_id") or ""),
                test_function=str(item.get("test_function") or ""),
                requirement_ids=tuple(item.get("requirement_ids") or []),
                covered_behaviors=tuple(item.get("covered_behaviors") or []),
                source="APPROVED",
                test_case_file=str(item.get("test_case_file") or ""),
                test_case_sha256=str(item.get("test_case_sha256") or ""),
                automation_file=str(item.get("automation_file") or ""),
                automation_sha256=str(item.get("automation_sha256") or ""),
            )
        )
    catalog = (*EXISTING_REGRESSION_CATALOG, *approved)
    _existing_regression_by_id(catalog)
    return catalog


def load_approved_regression_catalog(
    approved_assets_root: Path,
) -> tuple[tuple[ExistingRegressionSpec, ...], dict[str, Any]]:
    """Load and verify immutable human-approved TC and automation assets."""

    approved_assets_root = approved_assets_root.resolve()
    registry_file = approved_assets_root / "registry.json"
    if not registry_file.is_file():
        return (), {"contract_version": "1.0", "approved_assets": []}
    registry = json.loads(registry_file.read_text(encoding="utf-8"))
    assets = registry.get("assets")
    if not isinstance(assets, list):
        raise ValueError("공식 자산 Registry의 assets 목록이 올바르지 않습니다.")
    approved: list[ExistingRegressionSpec] = []
    snapshot_entries: list[dict[str, Any]] = []
    for asset in assets:
        if not isinstance(asset, dict):
            raise ValueError("공식 자산 Registry 항목이 JSON 객체가 아닙니다.")
        tc_id = str(asset.get("official_tc_id") or "")
        if not re.fullmatch(r"TC-V2-\d{3}", tc_id):
            raise ValueError(f"공식 TC ID 형식이 올바르지 않습니다: {tc_id}")
        resolved_files: dict[str, Path] = {}
        for key in ("test_case_file", "automation_file"):
            relative = str(asset.get(key) or "")
            candidate = (approved_assets_root / relative).resolve()
            try:
                candidate.relative_to(approved_assets_root)
            except ValueError as exc:
                raise ValueError(f"{tc_id}의 {key} 경로가 공식 자산 폴더 밖입니다.") from exc
            if not candidate.is_file():
                raise ValueError(f"{tc_id}의 {key} 파일을 찾을 수 없습니다.")
            expected_hash = str(asset.get(key.replace("_file", "_sha256")) or "")
            if _sha256_file(candidate) != expected_hash:
                raise ValueError(f"{tc_id}의 {key} SHA-256이 Registry와 다릅니다.")
            resolved_files[key] = candidate
        revision_relative = asset.get("srs_revision_file")
        if revision_relative:
            revision_file = (approved_assets_root / str(revision_relative)).resolve()
            try:
                revision_file.relative_to(approved_assets_root)
            except ValueError as exc:
                raise ValueError(f"{tc_id}의 SRS 개정 기록 경로가 자산 폴더 밖입니다.") from exc
            if (
                not revision_file.is_file()
                or _sha256_file(revision_file)
                != str(asset.get("srs_revision_sha256") or "")
            ):
                raise ValueError(f"{tc_id}의 SRS 개정 기록 SHA-256이 Registry와 다릅니다.")
        tc_payload = json.loads(resolved_files["test_case_file"].read_text(encoding="utf-8"))
        if tc_payload.get("official_tc_id") != tc_id:
            raise ValueError(f"{tc_id}의 TC 파일 ID가 Registry와 다릅니다.")
        test_case = tc_payload.get("test_case")
        if not isinstance(test_case, dict):
            raise ValueError(f"{tc_id}의 구조화 TC를 찾을 수 없습니다.")
        try:
            validated_test_case = ProductTestCaseCandidate.model_validate(test_case)
        except ValidationError as exc:
            raise ValueError(f"{tc_id}의 구조화 TC 계약이 올바르지 않습니다.") from exc
        requirement_ids = tuple(validated_test_case.requirement_ids)
        if list(requirement_ids) != list(asset.get("requirement_ids") or []):
            raise ValueError(f"{tc_id}의 Requirement 목록이 Registry와 다릅니다.")
        covered_behaviors = tuple(
            item.statement for item in validated_test_case.expected_results
        )
        if not covered_behaviors:
            raise ValueError(f"{tc_id}의 검증 동작을 찾을 수 없습니다.")
        syntax = ast.parse(
            resolved_files["automation_file"].read_text(encoding="utf-8")
        )
        test_functions = [
            node.name
            for node in syntax.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name.startswith("test_")
        ]
        if len(test_functions) != 1:
            raise ValueError(f"{tc_id} 자동화에는 test_ 함수가 정확히 한 개여야 합니다.")
        spec = ExistingRegressionSpec(
            tc_id=tc_id,
            test_function=test_functions[0],
            requirement_ids=requirement_ids,
            covered_behaviors=covered_behaviors,
            source="APPROVED",
            test_case_file=str(asset["test_case_file"]),
            test_case_sha256=str(asset["test_case_sha256"]),
            automation_file=str(asset["automation_file"]),
            automation_sha256=str(asset["automation_sha256"]),
        )
        approved.append(spec)
        snapshot_entries.append(_catalog_snapshot_entry(spec))
    _existing_regression_by_id((*EXISTING_REGRESSION_CATALOG, *approved))
    return tuple(approved), {
        "contract_version": "1.0",
        "registry_sha256": _sha256_file(registry_file),
        "approved_assets": snapshot_entries,
    }


def render_existing_regression_context(
    catalog: tuple[ExistingRegressionSpec, ...] = EXISTING_REGRESSION_CATALOG,
) -> str:
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
        for item in catalog
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


def apply_srs_revision_proposals(
    srs_path: Path,
    proposals: list[SrsRevisionProposal],
    *,
    write: bool,
) -> dict[str, Any]:
    """Validate and optionally atomically apply human-approved acceptance criteria."""

    srs_path = srs_path.resolve()
    if not srs_path.is_file():
        raise ValueError("기준 SRS 파일을 찾을 수 없습니다.")
    before_sha256 = _sha256_file(srs_path)
    lines = srs_path.read_text(encoding="utf-8").splitlines()
    by_requirement = {item.requirement_id: item for item in proposals}
    if len(by_requirement) != len(proposals):
        raise ValueError("SRS 개정 제안에 중복 Requirement가 있습니다.")
    found: set[str] = set()
    changed: list[str] = []
    already_applied: list[str] = []
    for index, line in enumerate(lines):
        match = _REQUIREMENT_ROW.match(line)
        if match is None:
            continue
        requirement_id, statement, acceptance_criteria = (
            match.group(1), match.group(2).strip(), match.group(3).strip()
        )
        proposal = by_requirement.get(requirement_id)
        if proposal is None:
            continue
        found.add(requirement_id)
        if "|" in proposal.proposed_acceptance_criteria or "\n" in proposal.proposed_acceptance_criteria:
            raise ValueError(f"{requirement_id} 제안 문구에 Markdown 표 구분자를 사용할 수 없습니다.")
        if acceptance_criteria == proposal.proposed_acceptance_criteria:
            already_applied.append(requirement_id)
            continue
        if acceptance_criteria != proposal.current_acceptance_criteria:
            raise ValueError(
                f"{requirement_id} 현재 인수 기준이 Agent 2 제안의 기준 원문과 다릅니다."
            )
        lines[index] = (
            f"| {requirement_id} | {statement} | "
            f"{proposal.proposed_acceptance_criteria} |"
        )
        changed.append(requirement_id)
    missing = sorted(by_requirement.keys() - found)
    if missing:
        raise ValueError("기준 SRS에서 개정 대상 Requirement를 찾을 수 없습니다: " + ", ".join(missing))
    after_text = "\n".join(lines) + "\n"
    if write and changed:
        _write_text_atomic(srs_path, after_text)
    after_sha256 = _sha256_file(srs_path) if write else hashlib.sha256(
        after_text.encode("utf-8")
    ).hexdigest()
    return {
        "before_sha256": before_sha256,
        "after_sha256": after_sha256,
        "changed_requirement_ids": changed,
        "already_applied_requirement_ids": already_applied,
    }


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

__all__ = ["__version__", *[name for name in globals() if not name.startswith("__")]]
