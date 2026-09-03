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
6. confirmed_conditions에는 Agent 2가 TC의 판정 기준으로 사용할 수 있는 확정 조건만 한 항목씩 분리합니다. 테스트 절차나 새로운 기대값은 만들지 않습니다. 각 조건의 `변경_구분`은 변경 후 새로 검증할 내용이면 `변경`, 변경 전·후에 같은 동작을 회귀 확인하는 내용이면 `유지`, SRS 공통 규칙이나 실행 문맥을 뒷받침하는 내용이면 `보조_근거`로 명시합니다. 단어가 같다는 이유만으로 값의 대응 관계나 실행 순서가 바뀐 조건을 `유지`로 두지 않습니다.
7. acceptance_notes 중 제품의 긍정적인 판정 기준은 각각 별도 confirmed_condition으로 만들고 source_text에 해당 인수 조건 원문 전체를 한 글자도 합치거나 바꾸지 않고 기록합니다. `범위에 포함하지 않는다`, `제외한다`, `검증 대상이 아니다`처럼 범위를 제한하는 항목은 confirmed_condition으로 만들지 말고 excluded_scope에 원문 그대로 기록합니다. 시험 준비·선택·종료 후 복원 절차도 제품 기대 결과인 confirmed_condition으로 바꾸지 않지만 excluded_scope에도 넣지 않습니다. 해당 원문은 변경 요청에 보존되어 Agent 2가 TC 절차로 사용합니다. 그 밖에 after_value와 description에만 있는 변경 후 범위·경계·모드별 정책도 별도 조건으로 포함합니다. 특히 하한~상한 범위는 두 경계를 모두 전달하고, 추가 조건의 source_type은 CHANGE_REQUEST, source_text는 해당 요청의 연속된 원문으로 기록합니다.
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
                prompt_cache_key="qa-v2-agent1-2-8",
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


_TEST_SETUP_NOTE = re.compile(
    r"(?:"
    r"(?:확인|준비|선택).*?시험을?\s*시작|"
    r"시험\s*전.*?(?:확인|준비|선택)"
    r")",
    re.IGNORECASE,
)
_TEST_RESTORE_NOTE = re.compile(
    r"(?:시험|검증)\s*(?:뒤|후|종료\s*후).*?(?:복원|원복)",
    re.IGNORECASE,
)


def _is_test_setup_note(value: str) -> bool:
    return bool(_TEST_SETUP_NOTE.search(value))


def _is_test_restore_note(value: str) -> bool:
    return bool(_TEST_RESTORE_NOTE.search(value))


def _is_test_procedure_note(value: str) -> bool:
    """Return True only for explicit test setup or post-test restoration notes."""

    return _is_test_setup_note(value) or _is_test_restore_note(value)


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
        note
        for note in request.acceptance_notes
        if not _is_scope_exclusion_text(note) and not _is_test_procedure_note(note)
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

__all__ = [name for name in globals() if not name.startswith("__")]
