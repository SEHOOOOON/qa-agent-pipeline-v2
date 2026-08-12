from __future__ import annotations

import argparse
import json
import os
import re
import sys
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

__version__ = "0.1.0"

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


class ConditionSource(str, Enum):
    CHANGE_REQUEST = "CHANGE_REQUEST"
    SRS = "SRS"


class RequirementRelation(str, Enum):
    MODIFIED = "MODIFIED"
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
    preconditions: list[NonEmptyStr] = Field(min_length=1)
    steps: list[NonEmptyStr] = Field(min_length=1)
    expected_results: list[ExpectedResult] = Field(min_length=1)
    restore_steps: list[NonEmptyStr] = Field(min_length=1)
    automation_candidate: bool
    automation_reason: NonEmptyStr


class Agent2TestDesign(StrictModel):
    request_id: NonEmptyStr
    test_cases: list[ProductTestCaseCandidate] = Field(min_length=1)
    coverage_summary: NonEmptyStr


class Checkpoint2Result(StrictModel):
    checkpoint: str = "CP2"
    status: CheckStatus
    checks: list[CheckResult] = Field(min_length=1)

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
7. acceptance_notes의 모든 항목을 각각 confirmed_conditions에 포함하고 source_type을 CHANGE_REQUEST, source_text를 해당 원문 전체로 기록합니다.
8. 기존 SRS 조건을 사용할 때는 source_type을 SRS로 지정하고 source_text는 연결 Requirement의 요구사항 또는 인수 기준에서 연속된 원문 일부를 그대로 사용합니다.
9. 각 confirmed_condition의 requirement_ids와 requirement_effects에는 제공된 SRS에 존재하는 ID만 사용합니다.
10. target_requirement_id는 requirement_effects에서 MODIFIED로 분류합니다.
11. 대상 Requirement의 related_requirement_ids와 변경 요청이 직접 언급하는 기존 Requirement를 모두 검토합니다. 함께 검증할 기준은 VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT로 분류하고 이유를 작성합니다. 연관 항목을 조용히 생략하지 않습니다.
12. MODIFIED 또는 VERIFY로 분류한 모든 Requirement는 confirmed_conditions의 requirement_ids에 최소 한 번 연결하고, 변경 요청 또는 해당 SRS의 검증 가능한 원문 조건을 함께 전달합니다.
13. VERIFY로 분류할 Requirement에서 전달할 검증 조건 원문을 찾지 못하면 이유만 추측해 VERIFY로 두지 말고 NO_IMPACT로 분류합니다.
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
    if missing_acceptance_notes:
        add(
            "CP1-008",
            CheckStatus.FAIL,
            f"Agent 2 전달 조건에서 누락된 인수 조건이 {len(missing_acceptance_notes)}개 있습니다.",
        )
    else:
        add("CP1-008", CheckStatus.PASS, "변경 요청의 인수 조건이 모두 확정 조건으로 전달됩니다.")

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
    return Checkpoint1Result(status=status, checks=checks)

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
1. Agent 1의 confirmed_conditions와 제공된 SRS만 사실 근거로 사용합니다.
2. requirement_effects가 NO_IMPACT인 Requirement는 테스트 범위에 포함하지 않습니다.
3. 모든 confirmed_condition을 최소 한 개 TC의 source_condition_ids로 반영합니다.
4. 모든 기대 결과는 source_condition_ids로 근거를 연결합니다. 근거에 없는 수치·시간·문구·UI 동작을 추가하지 않습니다.
5. 한 TC에는 하나의 분명한 검증 목적을 두고 정상·경계·예외·상태 정합성 관점을 필요 범위에서 선택합니다.
6. 상태 변경 또는 차단을 검증하는 TC는 사용자 화면(UI)과 내부 상태(INTERNAL_STATE)를 함께 확인합니다.
7. 안내 표시 조건을 검증하는 TC는 NOTIFICATION 기대 결과를 포함합니다. 정확한 Toast 문구가 입력에 없으면 문구를 만들어 일치 검증하지 않습니다.
8. 사전조건, 실행 행동, 판정 가능한 기대 결과와 원상 복구 절차를 구체적으로 작성합니다.
9. TC가 참조하는 Requirement와 Condition은 입력에 존재하는 ID만 사용합니다.
10. confirmed_condition을 여러 TC가 공유할 수 있지만, 동일 목적의 TC를 표현만 바꿔 중복 생성하지 않습니다.
11. automation_candidate는 현재 가상 중앙제어 화면과 내부 상태 조회로 자동화 가능한지 판단한 후보 표시일 뿐이며 코드를 만들지 않습니다.
12. 정보가 부족해 기대 결과를 확정할 수 없는 새 조건을 추측하지 않습니다.
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
        analysis: Agent1Analysis,
        requirements: dict[str, SrsRequirement],
        *,
        previous_design: Agent2TestDesign | None = None,
        checkpoint_feedback: list[str] | None = None,
    ) -> Agent2Response:
        user_input = (
            "[CP1 통과 Agent 1 분석]\n"
            f"{analysis.model_dump_json(indent=2)}\n\n"
            "[현재 SRS Requirement]\n"
            f"{render_srs_context(requirements)}"
        )
        if previous_design is not None:
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[이전 TC 후보]\n"
                f"{previous_design.model_dump_json(indent=2)}\n\n"
                "[Checkpoint 2 재작업 요청]\n"
                f"{feedback}\n"
                "근거와 검증 목적은 바꾸지 말고 실패한 품질 기준만 수정하세요. "
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
    analysis: Agent1Analysis,
    design: Agent2TestDesign,
    requirements: dict[str, SrsRequirement],
) -> Checkpoint2Result:
    checks: list[CheckResult] = []

    def add(rule_id: str, status: CheckStatus, message: str) -> None:
        checks.append(CheckResult(rule_id=rule_id, status=status, message=message))

    if design.request_id == analysis.request_id:
        add("CP2-001", CheckStatus.PASS, "Agent 1과 Agent 2의 변경 요청 ID가 일치합니다.")
    else:
        add("CP2-001", CheckStatus.FAIL, "Agent 2의 변경 요청 ID가 Agent 1과 다릅니다.")

    tc_ids = [tc.tc_id for tc in design.test_cases]
    result_ids = [
        result.result_id
        for tc in design.test_cases
        for result in tc.expected_results
    ]
    duplicate_tc_ids = sorted({item for item in tc_ids if tc_ids.count(item) > 1})
    duplicate_result_ids = sorted(
        {item for item in result_ids if result_ids.count(item) > 1}
    )
    normalized_titles = [re.sub(r"\s+", "", tc.title).casefold() for tc in design.test_cases]
    duplicate_titles = sorted(
        {design.test_cases[index].title for index, item in enumerate(normalized_titles)
         if normalized_titles.count(item) > 1}
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
    referenced_requirements = {
        item for tc in design.test_cases for item in tc.requirement_ids
    }
    referenced_conditions = {
        item for tc in design.test_cases for item in tc.source_condition_ids
    }
    unknown_requirements = sorted(
        referenced_requirements - requirements.keys()
        | (referenced_requirements - active_requirements)
    )
    unknown_conditions = sorted(referenced_conditions - known_conditions.keys())
    if unknown_requirements or unknown_conditions:
        add(
            "CP2-003",
            CheckStatus.FAIL,
            "입력 범위 밖 Requirement 또는 Condition을 참조했습니다.",
        )
    else:
        add("CP2-003", CheckStatus.PASS, "모든 추적 ID가 승인된 입력 범위에 존재합니다.")

    missing_conditions = sorted(known_conditions.keys() - referenced_conditions)
    if missing_conditions:
        add(
            "CP2-004",
            CheckStatus.FAIL,
            "TC에 반영되지 않은 확정 조건: " + ", ".join(missing_conditions),
        )
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
        for expected in tc.expected_results:
            if not set(expected.source_condition_ids).issubset(tc_condition_ids):
                trace_errors.append(tc.tc_id)
                break
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
        if (
            "REQ-NOTIFY-001" in source_requirements
            and ObservationLayer.NOTIFICATION not in layers
        ):
            notify_errors.append(tc.tc_id)
    if state_errors:
        add(
            "CP2-006",
            CheckStatus.FAIL,
            "상태 정합성 Requirement 또는 TC 유형에 UI·내부 상태 이중 검증이 누락됐습니다: "
            + ", ".join(state_errors),
        )
    else:
        add("CP2-006", CheckStatus.PASS, "상태 관련 TC가 UI·내부 상태를 함께 검증합니다.")

    if notify_errors:
        add(
            "CP2-007",
            CheckStatus.FAIL,
            "알림 기대 결과가 누락된 TC: " + ", ".join(notify_errors),
        )
    else:
        add("CP2-007", CheckStatus.PASS, "알림 조건이 NOTIFICATION 결과로 연결됩니다.")

    active_effect_ids = {
        item.requirement_id
        for item in analysis.requirement_effects
        if item.relation != RequirementRelation.NO_IMPACT
    }
    uncovered_requirements = sorted(active_effect_ids - referenced_requirements)
    target_change_tests = [
        tc
        for tc in design.test_cases
        if analysis.target_requirement_id in tc.requirement_ids
        and tc.purpose == TcPurpose.CHANGE_VALIDATION
    ]
    if uncovered_requirements or not target_change_tests:
        add(
            "CP2-008",
            CheckStatus.FAIL,
            "변경 또는 확인 Requirement의 TC 범위가 불완전합니다.",
        )
    else:
        add("CP2-008", CheckStatus.PASS, "변경·확인 Requirement가 TC 범위에 포함됩니다.")

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
# CLI
# ---------------------------------------------------------------------------
DEFAULT_SRS = Path("docs") / "01_PRODUCT_SRS.md"
DEFAULT_RUNS_ROOT = Path("runs")


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


def _read_json_model(path: Path, model_type):
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return model_type.model_validate(payload)
    except FileNotFoundError as exc:
        raise ValueError(f"필수 실행 산출물을 찾을 수 없습니다: {path}") from exc
    except (json.JSONDecodeError, ValidationError) as exc:
        raise ValueError(f"실행 산출물 검증에 실패했습니다: {path}\n{exc}") from exc


def _resolve_run_dir(runs_root: Path, run_id: str) -> Path:
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


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_agent1(args: argparse.Namespace) -> int:
    request = _read_request(Path(args.request).resolve())
    requirements = load_srs_requirements(Path(args.srs).resolve())
    agent = OpenAIAgent1(model=args.model)
    run_id = _new_run_id()
    run_dir = Path(args.runs_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    _write_json(run_dir / "request.json", request.model_dump(mode="json"))
    try:
        response = agent.analyze(request, requirements)
        checkpoint = evaluate_checkpoint1(request, response.analysis, requirements)
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint.status.value,
                "model": response.model,
                "response_id": response.response_id,
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
            checkpoint = evaluate_checkpoint1(
                request, response.analysis, requirements
            )
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint.status.value,
                    "model": response.model,
                    "response_id": response.response_id,
                    "usage": response.usage,
                }
            )

        _write_json(
            run_dir / "agent1_change_analysis.json",
            response.analysis.model_dump(mode="json"),
        )
        _write_json(
            run_dir / "checkpoint1.json", checkpoint.model_dump(mode="json")
        )
        _write_json(
            run_dir / "run_manifest.json",
            {
                "run_id": run_id,
                "stage": "AGENT_1_CP1",
                "status": checkpoint.status.value,
                "model": response.model,
                "response_id": response.response_id,
                "usage": response.usage,
                "attempts": attempts,
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
    print(f"결과 위치: {run_dir}")
    return 0 if checkpoint.status == CheckStatus.PASS else 2


def run_agent2(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    analysis = _read_json_model(
        run_dir / "agent1_change_analysis.json", Agent1Analysis
    )
    checkpoint1 = _read_json_model(
        run_dir / "checkpoint1.json", Checkpoint1Result
    )
    if checkpoint1.status != CheckStatus.PASS:
        raise ValueError(
            f"Checkpoint 1이 {checkpoint1.status.value}이므로 Agent 2를 실행할 수 없습니다."
        )

    requirements = load_srs_requirements(Path(args.srs).resolve())
    agent = OpenAIAgent2(model=args.model)
    try:
        response = agent.design(analysis, requirements)
        checkpoint2 = evaluate_checkpoint2(
            analysis, response.design, requirements
        )
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint2.status.value,
                "model": response.model,
                "response_id": response.response_id,
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
                analysis,
                requirements,
                previous_design=response.design,
                checkpoint_feedback=[
                    item.message
                    for item in checkpoint2.checks
                    if item.status == CheckStatus.FAIL
                ],
            )
            checkpoint2 = evaluate_checkpoint2(
                analysis, response.design, requirements
            )
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint2.status.value,
                    "model": response.model,
                    "response_id": response.response_id,
                    "usage": response.usage,
                }
            )

        _write_json(
            run_dir / "agent2_test_design.json",
            response.design.model_dump(mode="json"),
        )
        _write_json(
            run_dir / "checkpoint2.json",
            checkpoint2.model_dump(mode="json"),
        )
        _write_json(
            run_dir / "agent2_manifest.json",
            {
                "run_id": args.run_id,
                "source_stage": "AGENT_1_CP1",
                "stage": "AGENT_2_CP2",
                "status": checkpoint2.status.value,
                "model": response.model,
                "response_id": response.response_id,
                "usage": response.usage,
                "attempts": attempts,
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
    agent2.add_argument("--srs", default=str(DEFAULT_SRS), help="제품 SRS Markdown 경로")
    agent2.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent2.add_argument(
        "--model",
        default=None,
        help="OpenAI 모델 ID. 미지정 시 OPENAI_MODEL 또는 gpt-5.6-terra",
    )
    agent2.set_defaults(handler=run_agent2)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError, Agent1Error, Agent2Error) as exc:
        parser.error(str(exc))
    return 1

if __name__ == "__main__":
    raise SystemExit(main())
