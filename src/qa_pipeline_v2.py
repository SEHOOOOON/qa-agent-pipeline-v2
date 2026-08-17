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
    model_config = ConfigDict(extra="forbid")


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



class TcPurpose(str, Enum):
    CHANGE_VALIDATION = "CHANGE_VALIDATION"
    RELATED_REGRESSION = "RELATED_REGRESSION"


class TcType(str, Enum):
    NORMAL = "NORMAL"
    BOUNDARY = "BOUNDARY"
    EXCEPTION = "EXCEPTION"
    STATE_CONSISTENCY = "STATE_CONSISTENCY"


class ObservationLayer(str, Enum):
    UI = "UI"
    INTERNAL_STATE = "INTERNAL_STATE"
    NOTIFICATION = "NOTIFICATION"


class ControlPath(str, Enum):
    CENTRAL = "CENTRAL"
    LOCAL = "LOCAL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class TestData(StrictModel):
    initial_mode: NonEmptyStr | None = None
    requested_mode: NonEmptyStr | None = None
    initial_temperature_c: float | None = None
    requested_temperature_c: float | None = None


class ExpectedResult(StrictModel):
    result_id: Annotated[str, StringConstraints(pattern=r"^ER-\d{3}$")]
    statement: NonEmptyStr
    observation_layer: ObservationLayer
    source_condition_ids: list[
        Annotated[str, StringConstraints(pattern=r"^COND-\d{3}$")]
    ] = Field(min_length=1)


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
    preconditions: list[NonEmptyStr] = Field(min_length=1)
    steps: list[NonEmptyStr] = Field(min_length=1)
    expected_results: list[ExpectedResult] = Field(min_length=1)
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


class Agent2TestDesign(StrictModel):
    request_id: NonEmptyStr
    test_cases: list[ProductTestCaseCandidate] = Field(min_length=1)
    coverage_summary: NonEmptyStr
    coverage_notes: list[NonEmptyStr] = Field(default_factory=list)
    human_review_notes: list[NonEmptyStr] = Field(default_factory=list)


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


class AssertionStrategy(str, Enum):
    UI_TEMPERATURE = "UI_TEMPERATURE"
    INTERNAL_SET_TEMP = "INTERNAL_SET_TEMP"
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
    generic_discovery: bool = False
    observed_at: NonEmptyStr
    observer: str = "python-playwright"


class AutomationAction(StrictModel):
    action_id: Annotated[str, StringConstraints(pattern=r"^ACT-\d{3}$")]
    phase: AutomationPhase
    action_type: AutomationActionType
    selector: NonEmptyStr
    value: str | float | int | bool | None = None
    source_text: NonEmptyStr


class AutomationAssertion(StrictModel):
    result_id: Annotated[str, StringConstraints(pattern=r"^ER-\d{3}$")]
    observation_layer: ObservationLayer
    strategy: AssertionStrategy
    selector: NonEmptyStr
    expected_number: float | None = None
    expected_text: str | None = None
    expected_value: str | float | int | bool | None = None


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
    contract_version: str = "1.0"
    run_id: NonEmptyStr
    stage: str = "VALIDATION_EXECUTION"
    status: ValidationStageStatus
    candidate_result: NeutralExecutionResult
    environment_precheck: NeutralExecutionResult
    selected_regression_ids: list[NonEmptyStr]
    regression_results: list[NeutralExecutionResult]
    blocked_reason: str | None = None
    created_at: NonEmptyStr


@dataclass(frozen=True)
class ExistingRegressionSpec:
    tc_id: str
    test_function: str
    requirement_ids: tuple[str, ...]


EXISTING_REGRESSION_CATALOG = (
    ExistingRegressionSpec(
        tc_id="TC-MODE-001",
        test_function="test_tc_mode_001_heat_mode_and_temp_apply",
        requirement_ids=("REQ-CONTROL-001", "REQ-MODE-001", "REQ-STATE-001"),
    ),
    ExistingRegressionSpec(
        tc_id="TC-MODE-002",
        test_function="test_tc_mode_002_fan_mode_temp_disabled",
        requirement_ids=("REQ-MODE-002",),
    ),
    ExistingRegressionSpec(
        tc_id="TC-MODE-003",
        test_function="test_tc_mode_003_dry_mode_then_cool_reactivation",
        requirement_ids=("REQ-MODE-001", "REQ-MODE-002"),
    ),
    ExistingRegressionSpec(
        tc_id="TC-LOCK-001",
        test_function="test_tc_lock_001_all_devices_full_inspection",
        requirement_ids=("REQ-LOCK-001",),
    ),
    ExistingRegressionSpec(
        tc_id="TC-ERR-001",
        test_function="test_tc_err_001_ch05_fault_injection_control_block",
        requirement_ids=("REQ-ERROR-001",),
    ),
    ExistingRegressionSpec(
        tc_id="TC-TEMP-001",
        test_function="test_tc_temp_001_upper_limit_boundary",
        requirement_ids=("REQ-TEMP-001",),
    ),
)

ENVIRONMENT_PRECHECK = ExistingRegressionSpec(
    tc_id="TC-ENV-000",
    test_function="test_tc_env_000_pre_environment_check",
    requirement_ids=("REQ-ENV-001",),
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
7. acceptance_notes의 모든 항목은 각각 별도 confirmed_condition으로 만들고 source_text에 해당 인수 조건 원문 전체를 한 글자도 합치거나 바꾸지 않고 기록합니다. 그 밖에 after_value와 description에만 있는 변경 후 범위·경계·모드별 정책도 별도 조건으로 포함합니다. 특히 하한~상한 범위는 두 경계를 모두 전달하고, 추가 조건의 source_type은 CHANGE_REQUEST, source_text는 해당 요청의 연속된 원문으로 기록합니다.
8. 기존 SRS 조건을 사용할 때는 source_type을 SRS로 지정하고 source_text는 연결 Requirement의 요구사항 또는 인수 기준에서 연속된 원문 일부를 그대로 사용합니다.
9. 각 confirmed_condition의 requirement_ids와 requirement_effects에는 제공된 SRS에 존재하는 ID만 사용합니다.
10. target_requirement_id는 requirement_effects에서 MODIFIED로 분류합니다.
11. 대상 Requirement의 related_requirement_ids와 변경 요청이 직접 언급하는 기존 Requirement를 모두 검토합니다. 변경 후 정책 때문에 기존 문장이나 인수 기준의 수정이 필요한 연관 Requirement는 UPDATE_REQUIRED, 문서는 유지하되 회귀 확인이 필요한 기준은 VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT로 분류하고 이유를 작성합니다. 연관 항목을 조용히 생략하지 않습니다.
12. MODIFIED, UPDATE_REQUIRED 또는 VERIFY로 분류한 모든 Requirement는 confirmed_conditions의 requirement_ids에 최소 한 번 연결하고, 변경 요청 또는 해당 SRS의 검증 가능한 원문 조건을 함께 전달합니다.
13. VERIFY로 분류할 Requirement에서 전달할 검증 조건 원문을 찾지 못하면 이유만 추측해 VERIFY로 두지 말고 NO_IMPACT로 분류합니다. UPDATE_REQUIRED는 변경 요청과 기존 SRS가 실제로 충돌하는 경우에만 사용합니다.
14. NO_IMPACT Requirement는 confirmed_conditions의 requirement_ids에 연결하지 않습니다.
15. excluded_scope에는 요청에 명시된 제외 범위와, 요청·SRS 근거로 이번 변경과 무관하다고 명확히 구분할 수 있는 범위만 기록합니다.
16. 변경 요청 내부의 충돌, 필수 기대 동작 누락 또는 대상 Requirement 불일치가 있을 때만 information_gaps와 user_questions에 기록합니다.
17. 변경 요청에 이미 명시된 값을 SRS에 없다는 이유로 다시 확정해 달라고 질문하지 않습니다.
18. Toast 같은 안내 수단의 정확한 문구는 변경 요청이 문구 일치를 요구할 때만 필수 정보로 봅니다.
19. 질문이 없고 변경 전 근거, 변경 후 정책과 전달할 확정 조건이 명확하면 PROCEED를 선택합니다.
20. 테스트케이스, 테스트 절차나 Playwright 코드는 작성하지 않습니다.
""".strip()


class Agent1Error(RuntimeError):
    """Raised when Agent 1 cannot produce a validated structured response."""


@dataclass(frozen=True)
class Agent1Response:
    analysis: Agent1Analysis
    response_id: str | None
    model: str
    usage: dict[str, int | None]


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

        usage = getattr(response, "usage", None)
        usage_summary = {
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "total_tokens": getattr(usage, "total_tokens", None),
        }
        return Agent1Response(
            analysis=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=usage_summary,
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
    missing_acceptance_notes = [
        note
        for note in request.acceptance_notes
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
    missing_out_of_scope = [
        item
        for item in request.out_of_scope
        if _normalize(item) not in excluded
    ]
    if confirmed_statements & excluded:
        add("CP1-009", CheckStatus.FAIL, "확정 조건과 제외 범위가 겹칩니다.")
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
    if analysis.decision == AnalysisDecision.PROCEED and has_open_questions:
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
    if status in {CheckStatus.FAIL, CheckStatus.ERROR}:
        handoff_status = HandoffStatus.BLOCKED
    elif status == CheckStatus.REVIEW:
        handoff_status = HandoffStatus.PAUSE
    elif analysis.decision == AnalysisDecision.PROCEED:
        handoff_status = HandoffStatus.CONTINUE
    elif analysis.decision in {
        AnalysisDecision.PARTIAL_PROCEED,
        AnalysisDecision.WAITING_FOR_USER,
    }:
        # 현재 MVP는 승인 범위만 분리 실행하거나 사용자 답변 후 재개하는 기능이 없다.
        handoff_status = HandoffStatus.PAUSE
    else:
        handoff_status = HandoffStatus.BLOCKED
    return Checkpoint1Result(
        status=status,
        handoff_status=handoff_status,
        checks=checks,
    )

# ---------------------------------------------------------------------------
# Agent 2: 제품 기능 테스트케이스 설계
# ---------------------------------------------------------------------------
AGENT2_SYSTEM_INSTRUCTIONS = """
당신은 CP1을 통과한 변경 분석을 제품 기능 테스트케이스 후보로 바꾸는 Agent 2입니다.

역할 경계:
- 무엇을 어떤 조건에서 검증할지 설계합니다.
- Playwright 코드, Selector, Python 코드나 자동화 구현은 작성하지 않습니다.
- V2에 구조화된 기존 TC 자산이 없으므로 NEW·UPDATED·DEPRECATED를 판정하지 않습니다.
- 출력은 사람의 마지막 승인 전 변경 검증용 제품 TC 후보입니다.

반드시 지킬 규칙:
1. 검증된 변경 요청 원문, Agent 1의 confirmed_conditions와 고정된 SRS만 사실 근거로 사용합니다.
2. requirement_effects가 NO_IMPACT인 Requirement는 테스트 범위에 포함하지 않습니다.
3. MODIFIED는 변경 동작 검증, UPDATE_REQUIRED는 변경으로 문구 수정이 필요한 연관 기준 검증, VERIFY는 기존 동작 회귀 검증으로 해석합니다.
4. 모든 confirmed_condition을 최소 한 개 TC의 source_condition_ids로 반영합니다.
5. 모든 기대 결과는 source_condition_ids로 근거를 연결합니다. 근거에 없는 수치·시간·문구·UI 동작을 추가하지 않습니다.
6. CHANGE_VALIDATION은 실제로 변경된 동작에만 사용하고 유지되는 기존 동작은 RELATED_REGRESSION으로 분류합니다.
6-1. 범위 변경은 변경된 경계뿐 아니라 변경 후 범위의 하한과 상한을 각각 검증합니다.
6-2. Agent 1이 CENTRAL과 LOCAL Requirement를 모두 활성 범위로 전달했다면 두 제어 경로에 각각 target_requirement_id를 포함한 CHANGE_VALIDATION TC를 만듭니다.
7. 한 TC에는 하나의 제어 경로와 하나의 주된 모드·경계·상태 목적만 둡니다. 서로 다른 모드의 경계 검증을 한 TC에 합치지 않습니다.
8. REQ-CONTROL-001을 검증하면 CENTRAL 경로에서 관제 패널을 통한 일괄 적용을 다룹니다. REQ-LOCAL-002를 검증하면 LOCAL 경로에서 개별 장치 제어를 다룹니다. LOCAL TC에 REQ-CONTROL-001을 근거처럼 붙이지 않습니다.
9. target_role은 고정 장치 ID를 추측하지 말고 PRIMARY_TEST_DEVICE처럼 역할로 지정합니다.
10. test_data에는 준비·요청에 필요한 모드와 온도를 구조화합니다. TC 절차 안에만 값을 숨기지 않습니다.
11. 상태 변경 또는 차단을 검증하는 TC는 사용자 화면(UI)과 내부 상태(INTERNAL_STATE)를 함께 확인합니다.
12. 안내 표시 조건을 검증하는 TC는 NOTIFICATION 기대 결과를 포함합니다. 정확한 Toast 문구가 입력에 없으면 문구를 만들어 일치 검증하지 않습니다.
13. 사전조건, 실행 행동과 판정 가능한 기대 결과를 구체적으로 작성합니다. 실행 후 상태가 실제로 바뀌면 restore_required=true와 원상 복구 절차를 작성하고, 차단되어 상태가 변하지 않으면 false와 빈 목록을 사용합니다.
14. TC가 참조하는 Requirement와 Condition은 입력에 존재하는 ID만 사용합니다.
15. confirmed_condition을 여러 TC가 공유할 수 있지만 동일 목적의 TC를 표현만 바꿔 중복 생성하지 않습니다.
16. automation_candidate는 현재 가상 중앙제어 화면과 내부 상태 조회로 자동화 가능한지 판단한 후보 표시일 뿐이며 코드를 만들지 않습니다.
16-1. CENTRAL 변경 검증에는 현재 단일 장비 MVP가 실행할 수 있도록 target_role=PRIMARY_TEST_DEVICE인 automation_candidate TC를 최소 한 건 포함합니다. 복수 장비 TC는 추가할 수 있지만 유일한 CENTRAL 후보로 만들지 않습니다.
17. SRS 문구의 후속 개정 필요, 정확한 안내 문구 미지정처럼 기대 동작을 바꾸지 않고 현재 TC를 설계할 수 있는 참고 사항은 coverage_notes에 남깁니다.
18. 서로 충돌하는 권한 입력, 기대 결과 미정처럼 TC 의미를 확정할 수 없어 후속 자동 진행을 중단해야 하는 항목만 human_review_notes에 남깁니다.
19. UPDATE_REQUIRED 자체는 변경관리의 정상 결과이므로 그것만으로 human_review_notes를 만들지 않습니다.
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
            f"{analysis.model_dump_json(indent=2)}\n\n"
            "[고정된 SRS Requirement]\n"
            f"{render_srs_context(requirements)}"
        )
        if previous_design is not None:
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[이전 TC 후보]\n"
                f"{previous_design.model_dump_json(indent=2)}\n\n"
                "[Checkpoint 2 전체 판정과 재작업 요청]\n"
                f"{feedback}\n"
                "근거와 검증 목적은 바꾸지 말고 실패한 품질 기준만 수정하세요. "
                "PASS인 규칙과 그 근거를 보존하고 새 FAIL을 만들지 마세요. "
                "수정 대상 TC만 반환하지 말고 이전의 전체 test_cases를 완전한 결과로 반환하세요. "
                "Checkpoint가 삭제를 요구하지 않은 기존 TC는 제거하지 마세요. "
                "Playwright 코드는 작성하지 마세요."
            )
        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
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
        usage = getattr(response, "usage", None)
        return Agent2Response(
            design=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        )

# ---------------------------------------------------------------------------
# Checkpoint 2: 테스트케이스 품질 검증
# ---------------------------------------------------------------------------
_FORBIDDEN_CODE = re.compile(
    r"(page\.|expect\(|pytest|playwright|def\s+test_|locator\(|assert\s+True)",
    flags=re.IGNORECASE,
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
    active_requirements = {
        item.requirement_id
        for item in analysis.requirement_effects
        if item.relation != RequirementRelation.NO_IMPACT
    }
    referenced_requirements = {item for tc in design.test_cases for item in tc.requirement_ids}
    referenced_conditions = {item for tc in design.test_cases for item in tc.source_condition_ids}
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
        add("CP2-004", CheckStatus.FAIL, "TC에 반영되지 않은 확정 조건: " + ", ".join(missing_conditions))
    else:
        add("CP2-004", CheckStatus.PASS, "Agent 1의 모든 확정 조건을 TC가 반영합니다.")

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
        expected_condition_ids = {
            condition_id
            for expected in tc.expected_results
            for condition_id in expected.source_condition_ids
        }
        if not tc_condition_ids.issubset(expected_condition_ids):
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
    if state_errors:
        add(
            "CP2-006",
            CheckStatus.FAIL,
            "상태 관련 TC에 UI·내부 상태 이중 검증이 누락됐습니다: " + ", ".join(state_errors),
        )
    else:
        add("CP2-006", CheckStatus.PASS, "상태 관련 TC가 UI·내부 상태를 함께 검증합니다.")
    if notify_errors:
        add("CP2-007", CheckStatus.FAIL, "알림 기대 결과가 누락된 TC: " + ", ".join(notify_errors))
    else:
        add("CP2-007", CheckStatus.PASS, "알림 조건이 NOTIFICATION 결과로 연결됩니다.")

    path_errors: list[str] = []
    for tc in design.test_cases:
        if "REQ-CONTROL-001" in tc.requirement_ids and tc.control_path != ControlPath.CENTRAL:
            path_errors.append(f"{tc.tc_id}:REQ-CONTROL-001은 CENTRAL 필요")
        if "REQ-LOCAL-002" in tc.requirement_ids and tc.control_path != ControlPath.LOCAL:
            path_errors.append(f"{tc.tc_id}:REQ-LOCAL-002는 LOCAL 필요")
    if "REQ-CONTROL-001" in active_requirements and not any(
        tc.control_path == ControlPath.CENTRAL and "REQ-CONTROL-001" in tc.requirement_ids
        for tc in design.test_cases
    ):
        path_errors.append("REQ-CONTROL-001 중앙 제어 TC 누락")
    if "REQ-LOCAL-002" in active_requirements and not any(
        tc.control_path == ControlPath.LOCAL and "REQ-LOCAL-002" in tc.requirement_ids
        for tc in design.test_cases
    ):
        path_errors.append("REQ-LOCAL-002 로컬 제어 TC 누락")

    required_change_paths: list[tuple[str, ControlPath]] = []
    if "REQ-CONTROL-001" in active_requirements:
        required_change_paths.append(("REQ-CONTROL-001", ControlPath.CENTRAL))
    if "REQ-LOCAL-002" in active_requirements:
        required_change_paths.append(("REQ-LOCAL-002", ControlPath.LOCAL))
    for requirement_id, control_path in required_change_paths:
        if not any(
            tc.purpose == TcPurpose.CHANGE_VALIDATION
            and tc.control_path == control_path
            and request.target_requirement_id in tc.requirement_ids
            and requirement_id in tc.requirement_ids
            for tc in design.test_cases
        ):
            path_errors.append(f"{control_path.value} 경로의 직접 변경 검증 TC 누락")
    uncovered_requirements = sorted(active_requirements - referenced_requirements)
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
        add("CP2-008", CheckStatus.PASS, "변경·회귀 Requirement와 중앙·로컬 경로가 구분됩니다.")

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
        if tc.test_type in {TcType.BOUNDARY, TcType.EXCEPTION, TcType.STATE_CONSISTENCY}
        and tc.test_data.requested_mode is None
        and tc.test_data.requested_temperature_c is None
    ]
    if test_data_errors:
        add(
            "CP2-010",
            CheckStatus.FAIL,
            "경계·예외·상태 TC의 구조화된 요청 시험 데이터가 없습니다: "
            + ", ".join(test_data_errors),
        )
    else:
        add("CP2-010", CheckStatus.PASS, "실행에 필요한 대상 역할과 시험 데이터가 구조화됐습니다.")

    if design.human_review_notes:
        add(
            "CP2-011",
            CheckStatus.REVIEW,
            "사람이 최종 승인 전에 확인할 의미 판단 항목이 있습니다: "
            + " / ".join(design.human_review_notes),
        )
    else:
        if design.coverage_notes:
            add(
                "CP2-011",
                CheckStatus.PASS,
                f"차단 없는 참고 사항 {len(design.coverage_notes)}건을 기록했습니다.",
            )
        else:
            add("CP2-011", CheckStatus.PASS, "추가 의미 판단이 필요한 항목이 없습니다.")

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
4. For a READY plan, map PRIMARY_TEST_DEVICE and CENTRAL_COMMAND_ALLOWED_ROLE to target_device_id=1.
   If a SELECT_DEVICE action is actually needed, set its value to the same integer 1. A generic single-target page
   whose observed accessible context already identifies PRIMARY_TEST_DEVICE does not need a legacy SELECT_DEVICE action.
5. PRECONDITION actions establish only states explicitly required by the approved TC. A precondition already satisfied
   by the observed page context or initial UI/state values needs no action; never demand an unobserved legacy selector for it.
6. TEST actions implement only the approved TC steps. Never assume a blocked request changes the value.
7. Create RESTORE actions only when restore_required=true and use only the approved restore values.
8. Map every Expected Result exactly once without changing result_id or observation_layer.
9. Generic UI actions are CLICK, FILL, SELECT_OPTION, CHECK, and UNCHECK. Use only an observed selector whose tag,
   role, input_type, enabled state, and action_hint support the selected action.
10. Generic UI assertions are UI_TEXT_CONTAINS, UI_VALUE_EQUALS, UI_CHECKED_EQUALS, and UI_ENABLED_EQUALS.
    INTERNAL_VALUE_EQUALS may use only an exact path present in ui_observation.harness_values.
    When a NOTIFICATION Expected Result specifies that a result is announced but does not fix the whole message,
    UI_TEXT_CONTAINS may verify a short meaningful phrase that occurs verbatim in that Expected Result. Do not invent a full
    message and do not use the entire natural-language Expected Result sentence as expected_text.
11. Generic action values must occur in the approved precondition, step, or restore text. Generic assertion values
    must occur in the matching Expected Result. Do not translate a product meaning into an ungrounded boolean or value.
12. Keep source_text as the exact approved precondition, step, or restore line implemented by the action.
13. For the existing temperature controller, use UI_TEMPERATURE and INTERNAL_SET_TEMP for their corresponding observations,
   TOAST_BLOCKING for a blocking Toast, and CONTROLS_DISABLED or DISABLED_TEMPERATURE_TEXT for disabled states.
14. Return only the structured plan, which is the executable code intent consumed by the guarded compiler. Do not write free-form Python.
15. Do not propose external URLs, shell commands, file changes, arbitrary waits, skip, or ignored exceptions.
16. Only for an observed existing temperature-controller flow, use these action targets exactly: SELECT_DEVICE=#device-card-1 .card-body-split;
    SET_MODE=the selector matching the requested mode; SET_TEMPERATURE=#det-temp-display;
    APPLY_COMMANDS=.btn-apply-cmd. Never require these legacy selectors when they are absent from the supplied UI Observation.
    The compiler operates the temperature buttons itself.
17. For legacy assertion strategies, use these targets exactly: UI_TEMPERATURE=#det-temp-display;
    INTERNAL_SET_TEMP=window.__vccs.devices; TOAST_VISIBLE=#global-toast;
    TOAST_BLOCKING=#global-toast;
    CONTROLS_DISABLED=#det-temp-down-btn; DISABLED_TEMPERATURE_TEXT=#det-temp-display.
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
    return {
        "destination": "OpenAI Responses API",
        "store": False,
        "system_instructions": AGENT3_SYSTEM_INSTRUCTIONS,
        "test_case": test_case.model_dump(mode="json"),
        "related_srs_requirements": related,
        "ui_observation": observation.model_dump(mode="json"),
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
        usage = getattr(response, "usage", None)
        return Agent3Response(
            plan=parsed,
            response_id=getattr(response, "id", None),
            model=self.model,
            usage={
                "input_tokens": getattr(usage, "input_tokens", None),
                "output_tokens": getattr(usage, "output_tokens", None),
                "total_tokens": getattr(usage, "total_tokens", None),
            },
        )


_UI_SELECTOR_INVENTORY = {
    "#device-card-1 .card-body-split": "Select PRIMARY_TEST_DEVICE",
    "#det-mode-cool": "Request COOL mode",
    "#det-mode-heat": "Request HEAT mode",
    "#det-mode-fan": "Request FAN mode",
    "#det-mode-dry": "Request DRY mode",
    "#det-mode-auto": "Request AUTO mode",
    "#det-temp-display": "Read pending temperature",
    "#det-temp-down-btn": "Request one degree lower",
    "#det-temp-up-btn": "Request one degree higher",
    "#det-temp-adjust-card": "Read temperature control state",
    ".btn-apply-cmd": "Apply pending commands",
    "#global-toast": "Read blocking toast",
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
        set(_UI_SELECTOR_INVENTORY)
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
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise Agent3Error(
            "Agent 3 UI inspection requires Playwright. Run pip install -e .[agent3]."
        ) from exc

    elements: list[ObservedUiElement] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.goto(target.as_uri(), wait_until="domcontentloaded")
        page.evaluate("() => localStorage.clear()")
        page.reload(wait_until="domcontentloaded")
        page.wait_for_selector("body", timeout=5000)
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
_DISABLED_TERMS = ("disabled", "비활성", "조작할 수 없", "사용할 수 없")
_CONTROL_TERMS = ("control", "button", "버튼", "조작")
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

    modes = {
        value
        for value in (
            test_case.test_data.initial_mode,
            test_case.test_data.requested_mode,
        )
        if value
    }
    temperature_values = {
        float(value)
        for value in (
            test_case.test_data.initial_temperature_c,
            test_case.test_data.requested_temperature_c,
        )
        if value is not None
    }
    non_hvac_modes = modes - set(_MODE_SELECTOR)
    legacy_controller_flow = bool(modes or temperature_values) and not non_hvac_modes
    if legacy_controller_flow:
        required_capabilities.add("SELECT_PRIMARY_DEVICE")
        required_selectors.add("#device-card-1 .card-body-split")
        required_harness_keys.add("selectedUnitId")
        if test_case.control_path == ControlPath.CENTRAL:
            required_capabilities.add("APPLY_CENTRAL_COMMAND")
            required_selectors.add(".btn-apply-cmd")
        else:
            generic_discovery_required = True
            required_capabilities.add("DISCOVER_CONTROL_PATH")
    else:
        generic_discovery_required = True
        required_capabilities.add("DISCOVER_GENERIC_UI")

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

    disabled_mode = legacy_controller_flow and bool(modes) and modes <= {"FAN", "DRY"}
    for result in test_case.expected_results:
        statement = result.statement
        if result.observation_layer == ObservationLayer.UI:
            if temperature_values and _contains_any(statement, _TEMPERATURE_TERMS):
                required_capabilities.add("ASSERT_UI_TEMPERATURE")
                required_selectors.add("#det-temp-display")
            elif disabled_mode and _contains_any(statement, _DISABLED_TERMS):
                if _contains_any(statement, _CONTROL_TERMS):
                    required_capabilities.add("ASSERT_TEMPERATURE_CONTROLS_DISABLED")
                    required_selectors.update(
                        {"#det-temp-down-btn", "#det-temp-up-btn"}
                    )
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
            if temperature_values and _contains_any(statement, _TEMPERATURE_TERMS):
                required_capabilities.add("ASSERT_INTERNAL_SET_TEMP")
                required_harness_keys.add("devices")
            else:
                generic_discovery_required = True
                required_capabilities.add("DISCOVER_INTERNAL_STATE")
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
        generic_discovery_required=generic_discovery_required,
    )


_ASSERTION_SELECTOR = {
    AssertionStrategy.UI_TEMPERATURE: "#det-temp-display",
    AssertionStrategy.INTERNAL_SET_TEMP: "window.__vccs.devices",
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
    if (
        plan.planning_status
        == Agent3PlanningStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
    ):
        return Checkpoint3Result(
            status=CheckStatus.REVIEW,
            candidate_status=(
                AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
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
                )
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
        if item.action_type == AutomationActionType.SELECT_DEVICE and (
            item.selector != "#device-card-1 .card-body-split"
            or item.value != plan.target_device_id
        ):
            action_errors.append(f"{item.action_id}: invalid device selector or target value")
        elif item.action_type == AutomationActionType.SET_MODE:
            expected_selector = _MODE_SELECTOR.get(str(item.value))
            if expected_selector is None or item.selector != expected_selector:
                action_errors.append(f"{item.action_id}: mode and selector do not match")
        elif item.action_type == AutomationActionType.SET_TEMPERATURE and item.selector != "#det-temp-display":
            action_errors.append(f"{item.action_id}: invalid temperature target")
        elif item.action_type == AutomationActionType.APPLY_COMMANDS and item.selector != ".btn-apply-cmd":
            action_errors.append(f"{item.action_id}: invalid apply selector")
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
            approved_source = {
                AutomationPhase.PRECONDITION: test_case.preconditions,
                AutomationPhase.TEST: test_case.steps,
                AutomationPhase.RESTORE: test_case.restore_steps,
            }[item.phase]
            if not any(_normalize(item.source_text) == _normalize(text) for text in approved_source):
                action_errors.append(
                    f"{item.action_id}: source_text is not an exact approved TC line"
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
    allowed_numbers = {
        value
        for value in (
            data.initial_temperature_c,
            data.requested_temperature_c,
        )
        if value is not None
    }
    for item in plan.actions:
        if item.action_type == AutomationActionType.SET_TEMPERATURE:
            if not isinstance(item.value, (int, float)) or float(item.value) not in {
                float(value) for value in allowed_numbers
            }:
                value_errors.append(f"{item.action_id}: temperature not present in TC: {item.value}")
        if item.action_type == AutomationActionType.SET_MODE:
            allowed_modes = {x for x in (data.initial_mode, data.requested_mode) if x}
            if item.value not in allowed_modes:
                value_errors.append(f"{item.action_id}: mode not present in TC: {item.value}")
    for assertion in plan.assertions:
        if assertion.expected_number is not None and float(assertion.expected_number) not in {
            float(value) for value in allowed_numbers
        }:
            value_errors.append(f"{assertion.result_id}: expected temperature not present in TC")
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

    generic_plan = any(
        item.action_type in _GENERIC_ACTION_TYPES for item in plan.actions
    ) or any(
        item.strategy in _GENERIC_ASSERTION_STRATEGIES for item in plan.assertions
    )
    if generic_plan:
        if not any(item.phase == AutomationPhase.TEST for item in plan.actions):
            sequence_errors.append("generic plan has no TEST action")
        if test_case.restore_required and not any(
            item.phase == AutomationPhase.RESTORE for item in plan.actions
        ):
            sequence_errors.append("generic plan is missing approved restore actions")
    else:
        if not has_action(AutomationPhase.PRECONDITION, AutomationActionType.SELECT_DEVICE):
            sequence_errors.append("target device selection is missing")
        if data.initial_mode and not has_action(AutomationPhase.PRECONDITION, AutomationActionType.SET_MODE, data.initial_mode):
            sequence_errors.append("initial mode setup is missing")
        if data.initial_temperature_c is not None and not has_action(AutomationPhase.PRECONDITION, AutomationActionType.SET_TEMPERATURE, data.initial_temperature_c):
            sequence_errors.append("initial temperature setup is missing")
        if not has_action(AutomationPhase.PRECONDITION, AutomationActionType.APPLY_COMMANDS):
            sequence_errors.append("initial state apply is missing")
        if data.requested_mode and not has_action(AutomationPhase.TEST, AutomationActionType.SET_MODE, data.requested_mode):
            sequence_errors.append("requested mode action is missing")
        if data.requested_temperature_c is not None and not has_action(AutomationPhase.TEST, AutomationActionType.SET_TEMPERATURE, data.requested_temperature_c):
            sequence_errors.append("requested temperature action is missing")
        if test_case.control_path == ControlPath.CENTRAL and not has_action(AutomationPhase.TEST, AutomationActionType.APPLY_COMMANDS):
            sequence_errors.append("central command apply is missing")
    add("CP3-006A", CheckStatus.FAIL if sequence_errors else CheckStatus.PASS, " / ".join(sequence_errors) if sequence_errors else "Action sequence implements the approved setup and test steps.")

    restore_actions = [item for item in plan.actions if item.phase == AutomationPhase.RESTORE]
    restore_errors: list[str] = []
    if bool(restore_actions) != test_case.restore_required:
        restore_errors.append("restore action presence does not match restore_required")
    elif test_case.restore_required and not generic_plan:
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
    blocked_request = any(item.observation_layer == ObservationLayer.NOTIFICATION for item in test_case.expected_results)
    generic_plan = any(
        item.action_type in _GENERIC_ACTION_TYPES for item in plan.actions
    ) or any(
        item.strategy in _GENERIC_ASSERTION_STRATEGIES for item in plan.assertions
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
        "import re",
        "from pathlib import Path",
        "",
        "from playwright.sync_api import sync_playwright",
        "",
        f"# RUN_ID: {run_id}",
        f"# SOURCE_TC: {test_case.tc_id}",
        "TARGET_URL = os.environ['QA_TARGET_URL']",
        "EVIDENCE_DIR = Path(os.environ['QA_EVIDENCE_DIR'])",
        "",
        "def _temperature(page):",
        "    text = page.locator('#det-temp-display').inner_text()",
        "    match = re.search(r'-?\\d+(?:\\.\\d+)?', text)",
        "    return float(match.group(0)) if match else None",
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
    indent = "            "
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
    for action in [item for item in plan.actions if item.phase != AutomationPhase.RESTORE]:
        lines.append(f"{indent}# {action.action_id} {action.phase.value}: {_safe_comment(action.source_text)}")
        if action.action_type == AutomationActionType.SELECT_DEVICE:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).click()")
            lines.append(f"{indent}page.wait_for_function(\"() => window.__vccs.selectedUnitId === {plan.target_device_id}\")")
        elif action.action_type == AutomationActionType.SET_MODE:
            lines.append(f"{indent}page.locator({_py_literal(action.selector)}).click()")
        elif action.action_type == AutomationActionType.SET_TEMPERATURE:
            if action.phase == AutomationPhase.TEST and blocked_request:
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

    for assertion in plan.assertions:
        marker = f"{indent}# EXPECTED_RESULT: {assertion.result_id}"
        lines.append(marker)
        if assertion.strategy == AssertionStrategy.UI_TEMPERATURE:
            lines.extend(
                [
                    f"{indent}actual = _temperature(page)",
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
        else:
            lines.append(f"                _set_temperature(page, {float(action.value)})")
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
    if restore_actions and test_case.test_data.initial_temperature_c is not None:
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
                checkpoint.model_dump(mode="json"),
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
                "contract_version": "2.3",
                "prompt_version": "agent1-2.2",
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
    return 0 if (
        checkpoint.status == CheckStatus.PASS
        and checkpoint.handoff_status == HandoffStatus.CONTINUE
    ) else 2


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
    if manifest.get("status") != CheckStatus.PASS.value:
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
    if checkpoint.status != CheckStatus.PASS or checkpoint.handoff_status != HandoffStatus.CONTINUE:
        raise ValueError("Checkpoint 1이 Agent 2 실행을 허용하지 않습니다.")
    return request, requirements, analysis, checkpoint, manifest


def run_agent2(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    immutable_outputs = [
        run_dir / "agent2_test_design.json",
        run_dir / "checkpoint2.json",
        run_dir / "agent2_manifest.json",
    ]
    if any(path.exists() for path in immutable_outputs):
        raise ValueError("이 Run에는 Agent 2 최종 산출물이 이미 존재합니다. 새 Agent 1 Run을 사용하세요.")

    request, requirements, analysis, _, source_manifest = _load_verified_agent1_run(
        run_dir, args.run_id
    )
    agent = OpenAIAgent2(model=args.model)
    try:
        response = agent.design(request, analysis, requirements)
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
                response.design.model_dump(mode="json"),
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

        design_file = run_dir / "agent2_test_design.json"
        checkpoint2_file = run_dir / "checkpoint2.json"
        _write_json(design_file, response.design.model_dump(mode="json"))
        _write_json(checkpoint2_file, checkpoint2.model_dump(mode="json"))
        _write_json(
            run_dir / "agent2_manifest.json",
            {
                "contract_version": "2.3",
                "prompt_version": "agent2-2.3",
                "run_id": args.run_id,
                "source_stage": "AGENT_1_CP1",
                "stage": "AGENT_2_CP2",
                "status": checkpoint2.status.value,
                "model": response.model,
                "usage": _aggregate_model_usage(attempts),
                "final_attempt_usage": response.usage,
                "attempts": attempts,
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
    return Agent3TrialResult(
        outcome=outcome,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        stdout_file=stdout_file.name,
        stderr_file=stderr_file.name,
        screenshot_file=screenshot.name if screenshot.is_file() else None,
        trace_file=trace.name if trace.is_file() else None,
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
    if trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    }:
        return 0
    return 2


def _aggregate_model_usage(
    attempts: list[dict[str, Any]],
) -> dict[str, int | None]:
    """Sum model-token usage across every structured model attempt."""
    aggregate: dict[str, int | None] = {}
    for key in ("input_tokens", "output_tokens", "total_tokens"):
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
    final_outputs = [
        run_dir / "agent3_automation_plan.json",
        run_dir / "checkpoint3.json",
        run_dir / "agent3_trial.json",
        run_dir / "agent3_manifest.json",
        run_dir / "agent3_error.json",
    ]
    candidate_dir = run_dir / "candidates"
    evidence_dir = run_dir / "evidence" / args.tc_id
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
    eligibility_file = run_dir / "agent3_eligibility.json"
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
        print(f"Artifacts: {run_dir}")
        return 2

    target_html = Path(args.target_html).resolve()
    try:
        observation = inspect_target_ui(
            target_html,
            required_selectors=set(eligibility.required_selectors),
            required_harness_keys=set(eligibility.required_harness_keys),
            discover_generic=eligibility.generic_discovery_required,
        )
        observation_file = run_dir / "agent3_ui_observation.json"
        _write_json(observation_file, observation.model_dump(mode="json"))
        preview_payload = build_agent3_model_input(test_case, observation, requirements)
        preview_payload["model"] = args.model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        preview_file = run_dir / "agent3_model_input_preview.json"
        _write_json(preview_file, preview_payload)
        if getattr(args, "preview_only", False):
            print(f"Run ID: {args.run_id}")
            print("Agent 3 model call: NOT EXECUTED")
            print(f"Preview: {preview_file}")
            return 0

        agent = OpenAIAgent3(model=args.model)
        response = agent.plan(test_case, observation, requirements)
        checkpoint = evaluate_checkpoint3_plan(test_case, response.plan, observation)
        attempts = [{"attempt": 1, "status": checkpoint.status.value, "model": response.model, "usage": response.usage}]
        if checkpoint.status == CheckStatus.FAIL:
            _write_json(run_dir / "agent3_automation_plan_attempt_1.json", response.plan.model_dump(mode="json"))
            _write_json(run_dir / "checkpoint3_attempt_1.json", checkpoint.model_dump(mode="json"))
            response = agent.plan(
                test_case,
                observation,
                requirements,
                previous_plan=response.plan,
                checkpoint_feedback=[item.message for item in checkpoint.checks if item.status == CheckStatus.FAIL],
            )
            checkpoint = evaluate_checkpoint3_plan(test_case, response.plan, observation)
            attempts.append({"attempt": 2, "status": checkpoint.status.value, "model": response.model, "usage": response.usage})

        plan_file = run_dir / "agent3_automation_plan.json"
        checkpoint_file = run_dir / "checkpoint3.json"
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
            _write_json(run_dir / "agent3_trial.json", trial.model_dump(mode="json"))

        manifest_payload = {
            "contract_version": "3.4",
            "prompt_version": "agent3-3.7",
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
            "trial_sha256": _sha256_file(run_dir / "agent3_trial.json") if trial is not None else None,
            "project1_modified": _sha256_file(target_html) != observation.target_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(run_dir / "agent3_manifest.json", manifest_payload)
    except Exception as exc:
        _write_json(
            run_dir / "agent3_error.json",
            {
                "run_id": args.run_id,
                "stage": "AGENT_3_CP3_TRIAL",
                "tc_id": args.tc_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Agent 3 failed: {exc}\nArtifacts: {run_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {args.run_id}")
    print(f"Agent 3 모델: {response.model}")
    print(f"검증 단계 3: {checkpoint.status.value}")
    print(f"자동화 후보 상태: {checkpoint.candidate_status.value}")
    if trial is not None:
        print(f"신규 자동화 후보 시험 결과: {trial.outcome.value}")
    print(f"Artifacts: {run_dir}")
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


def _candidate_execution_record(
    run_dir: Path,
    run_id: str,
    target_html: Path,
) -> tuple[NeutralExecutionResult, ProductTestCaseCandidate, dict[str, Any]]:
    _, _, _, design, _, agent2_manifest = _load_verified_agent2_run(run_dir, run_id)
    agent2_manifest_file = run_dir / "agent2_manifest.json"
    agent3_manifest_file = run_dir / "agent3_manifest.json"
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
        _verify_sha256(run_dir / filename, agent3_manifest.get(key), label)

    checkpoint3 = _read_json_model(run_dir / "checkpoint3.json", Checkpoint3Result)
    if checkpoint3.status != CheckStatus.PASS:
        raise ValueError("Checkpoint 3가 PASS가 아니어서 실행 결과를 인계할 수 없습니다.")
    trial = _read_json_model(run_dir / "agent3_trial.json", Agent3TrialResult)
    if trial.outcome not in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    }:
        raise ValueError("신규 자동화 후보 시험이 신뢰 가능한 제품 관찰로 끝나지 않았습니다.")
    if not trial.evidence_complete:
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
        run_dir / "candidates", candidate_name, "Agent 3 Candidate"
    )
    _verify_sha256(
        candidate_file,
        agent3_manifest.get("candidate_sha256"),
        "Agent 3 Candidate",
    )

    evidence_dir = run_dir / "evidence" / test_case.tc_id
    evidence_names = [trial.stdout_file, trial.stderr_file]
    if trial.screenshot_file:
        evidence_names.append(trial.screenshot_file)
    if trial.trace_file:
        evidence_names.append(trial.trace_file)
    evidence_files = [
        _safe_artifact_child(evidence_dir, name, "신규 후보 시험 증거")
        for name in evidence_names
    ]
    evidence_paths = [path.relative_to(run_dir).as_posix() for path in evidence_files]
    evidence_hashes = {
        relative: _sha256_file(path)
        for relative, path in zip(evidence_paths, evidence_files, strict=True)
    }
    stdout = (evidence_dir / trial.stdout_file).read_text(encoding="utf-8")
    stderr = (evidence_dir / trial.stderr_file).read_text(encoding="utf-8")
    status = (
        NeutralExecutionStatus.PASSED
        if trial.outcome == TrialOutcome.PASS
        else NeutralExecutionStatus.ASSERTION_FAILED
    )
    return (
        NeutralExecutionResult(
            test_id=test_case.tc_id,
            source=ExecutionSource.NEW_AUTOMATION_CANDIDATE,
            requirement_ids=test_case.requirement_ids,
            status=status,
            source_outcome=trial.outcome.value,
            exit_code=trial.exit_code,
            duration_ms=trial.duration_ms,
            test_file=candidate_file.name,
            test_sha256=_sha256_file(candidate_file),
            target_sha256=target_sha256,
            reused=True,
            stdout_file=(evidence_dir / trial.stdout_file).relative_to(run_dir).as_posix(),
            stderr_file=(evidence_dir / trial.stderr_file).relative_to(run_dir).as_posix(),
            evidence_files=evidence_paths,
            evidence_sha256=evidence_hashes,
            evidence_complete=True,
            exception_type=(
                "AssertionError"
                if trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
                else None
            ),
            raw_message=_last_output_line(stdout, stderr),
        ),
        test_case,
        agent3_manifest,
    )


def _current_candidate_execution_record(
    run_dir: Path,
    run_id: str,
    target_html: Path,
    test_case: ProductTestCaseCandidate,
    stored_result: NeutralExecutionResult,
    *,
    timeout_seconds: int,
) -> NeutralExecutionResult:
    """Reuse an identical candidate or recompile and retrial without a model call."""
    plan = _read_json_model(
        run_dir / "agent3_automation_plan.json", Agent3AutomationPlan
    )
    current_code = compile_automation_candidate(run_id, test_case, plan)
    stored_candidate_file = run_dir / "candidates" / Path(stored_result.test_file).name
    if (
        stored_candidate_file.is_file()
        and _sha256_file(stored_candidate_file) == stored_result.test_sha256
        and stored_candidate_file.read_text(encoding="utf-8") == current_code
    ):
        return stored_result

    candidate_dir = run_dir / "validation_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=False)
    candidate_file = candidate_dir / f"test_{test_case.tc_id.lower().replace('-', '_')}.py"
    _write_text_atomic(candidate_file, current_code)
    evidence_dir = run_dir / "validation_evidence" / test_case.tc_id
    trial = run_candidate_trial(
        candidate_file,
        target_html,
        evidence_dir,
        timeout_seconds=timeout_seconds,
    )
    trial_file = run_dir / "validation_candidate_trial.json"
    _write_json(trial_file, trial.model_dump(mode="json"))
    if trial.outcome not in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    }:
        raise ValueError("현재 컴파일러의 신규 자동화 후보 시험이 신뢰 가능한 관찰로 끝나지 않았습니다.")
    if not trial.evidence_complete:
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
        status=(
            NeutralExecutionStatus.PASSED
            if trial.outcome == TrialOutcome.PASS
            else NeutralExecutionStatus.ASSERTION_FAILED
        ),
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
        evidence_complete=True,
        exception_type=(
            "AssertionError"
            if trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
            else None
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
    )
    if any(path.exists() for path in final_outputs):
        raise ValueError("이 Run에는 이미 검증 실행 산출물이 있습니다. 기존 증거를 덮어쓸 수 없습니다.")

    target_before = _sha256_file(target_html)
    baseline_before = _sha256_file(baseline_test_file)
    try:
        stored_candidate_result, test_case, _ = _candidate_execution_record(
            run_dir, args.run_id, target_html
        )
        candidate_result = _current_candidate_execution_record(
            run_dir,
            args.run_id,
            target_html,
            test_case,
            stored_candidate_result,
            timeout_seconds=args.timeout,
        )
        selected = select_existing_regressions(test_case.requirement_ids)
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

        bundle = ValidationExecutionBundle(
            run_id=args.run_id,
            status=stage_status,
            candidate_result=candidate_result,
            environment_precheck=precheck,
            selected_regression_ids=[item.tc_id for item in selected],
            regression_results=regression_results,
            blocked_reason=blocked_reason,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        execution_file = run_dir / "validation_execution.json"
        _write_json(execution_file, bundle.model_dump(mode="json"))
        agent3_manifest_file = run_dir / "agent3_manifest.json"
        _write_json(
            run_dir / "validation_manifest.json",
            {
                "contract_version": "1.0",
                "run_id": args.run_id,
                "stage": "VALIDATION_EXECUTION",
                "status": stage_status.value,
                "source_agent3_manifest_sha256": _sha256_file(agent3_manifest_file),
                "source_agent3_trial_sha256": _sha256_file(run_dir / "agent3_trial.json"),
                "candidate_reused": candidate_result.reused,
                "validation_candidate_sha256": candidate_result.test_sha256,
                "validation_candidate_trial_sha256": (
                    _sha256_file(run_dir / "validation_candidate_trial.json")
                    if (run_dir / "validation_candidate_trial.json").is_file()
                    else None
                ),
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
    print(f"Candidate result: {candidate_result.test_id}")
    print(f"Candidate trial reused: {candidate_result.reused}")
    print(f"Related regressions selected: {len(selected)}")
    print(f"Related regressions executed: {len(regression_results)}")
    print(f"Artifacts: {run_dir}")
    return 0 if stage_status == ValidationStageStatus.COMPLETED else 2


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
    """Choose a current-Run TC by automation support, never by a previous ID."""
    candidates: list[tuple[ProductTestCaseCandidate, Agent3EligibilityResult]] = []
    summaries: list[dict[str, Any]] = []
    for test_case in design.test_cases:
        eligibility = evaluate_agent3_eligibility(test_case)
        summaries.append(
            {
                "tc_id": test_case.tc_id,
                "purpose": test_case.purpose.value,
                "test_type": test_case.test_type.value,
                "control_path": test_case.control_path.value,
                "target_role": test_case.target_role,
                "status": eligibility.status.value,
                "missing_capabilities": eligibility.missing_capabilities,
                "generic_discovery_required": (
                    eligibility.generic_discovery_required
                ),
            }
        )
        if eligibility.model_call_allowed:
            candidates.append((test_case, eligibility))
    if not candidates:
        return None, summaries

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

    selected = min(candidates, key=priority)[0]
    return selected.tc_id, summaries


def _select_agent3_tc_from_run(
    run_dir: Path,
    run_id: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    _, _, _, design, _, _ = _load_verified_agent2_run(run_dir, run_id)
    return _select_agent3_tc(design)


def run_pipeline(args: argparse.Namespace) -> int:
    """Run Agent 1→2→3 once and stop when a stage cannot continue."""
    run_id = _new_run_id()
    runs_root = Path(args.runs_root).resolve()
    run_dir = runs_root / run_id
    target_html = Path(args.target_html).resolve()
    if not target_html.is_file():
        raise ValueError(f"Agent 3 target HTML does not exist: {target_html.name}")
    selected_tc_id = None if args.tc_id in {None, "AUTO"} else args.tc_id
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
        if selected_tc_id is None:
            selected_tc_id, selection_candidates = _select_agent3_tc_from_run(
                run_dir, run_id
            )
            selection_file = run_dir / "agent3_selection.json"
            _write_json(
                selection_file,
                {
                    "contract_version": "1.0",
                    "run_id": run_id,
                    "stage": "AGENT_3_SELECTION",
                    "status": "SELECTED" if selected_tc_id else "NOT_AUTOMATABLE",
                    "selected_tc_id": selected_tc_id,
                    "candidates": selection_candidates,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if selected_tc_id is None:
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
            print(f"Agent 3 auto-selected TC: {selected_tc_id}")
        agent3_exit = run_agent3(
            argparse.Namespace(
                run_id=run_id,
                tc_id=selected_tc_id,
                target_html=str(target_html),
                runs_root=str(runs_root),
                model=args.model,
                timeout=args.timeout,
                preview_only=False,
            )
        )
        stage_exit_codes["agent3"] = agent3_exit
        status = _orchestrator_status(agent3_exit)
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
