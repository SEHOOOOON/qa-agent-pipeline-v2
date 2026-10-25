from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Any

from openai import OpenAI
from qa_pipeline_io import *
from qa_pipeline_contracts import *

# ---------------------------------------------------------------------------
# Agent 1: 변경 요구사항 분석
# ---------------------------------------------------------------------------
AGENT1_SYSTEM_INSTRUCTIONS = """
CHANGE_REQUEST source_text may join verbatim excerpts with |, just like SRS citations. Each excerpt must exist in after_value, description, reason or acceptance_notes; for a target VERIFY test, before_value may also ground its stated starting value, not a new product result. Preserve every acceptance note in full within the cited excerpts; larger verbatim quotes are allowed. Cite all sources needed for numbers in the condition, including a stated preparation value. Do not truncate quotes to pass a check or treat excerpt order as meaning. Original request coverage and semantic review remain mandatory.
먼저 이번 요청의 대상·시작 상태·시험할 동작·기대결과·제외 범위를 구분하세요. SRS의 선택지 목록 전체나 before/after 문장에 그대로 남은 정책 전체가 이번 시험 범위는 아닙니다.
confirmed_conditions의 statement는 이번에 확인할 사실 단위로 나눕니다. source_text는 근거 원문 그대로 인용하되 긴 인용 전체를 statement의 검증 범위로 복사하지 않습니다. 요청이 제한한 전환의 새 결과는 변경, 명시적으로 회귀 확인을 요청한 결과는 유지, 나머지 기존 정책은 필요한 경우 보조_근거로 구분합니다. 보조_근거는 제품 기준의 참고이지 전체 선택지 시험 완료 주장이 아닙니다.
제외와 충돌하는 새 검사·간접 영향은 자동 추가하지 않습니다. 사용자가 여러 값·양쪽 경계·순차 결과를 실제로 요구했다면 각각 보존하며 단일 전환으로 축소하지 않습니다. 명시한 범위를 해석할 수 없으면 질문으로 남깁니다.
각 acceptance_notes 원문은 제품 조건, 시험 절차, 명시 제외, 정보 부족 중 하나의 역할로 분류합니다. 전달 목록의 '/'는 선택지이며 모든 위치에 복사하라는 뜻이 아닙니다. procedure_notes는 acceptance_notes 전체의 복사본이 아닙니다. 확정 조건으로 전달한 원문을 절차에도 중복 기록하지 않습니다. 단, 분리 가능한 정보 부족은 기존 계약에 따라 information_gaps·제외된_정보_부족·excluded_scope 세 목록에 함께 보존합니다.
분류 형식 예시(제품 기준이 아님): '적용 후 값은 X이다.'는 제품 조건에만, '[준비] 시험 전 상태를 기록한다.'는 절차에만 보존합니다. 표시 없는 문장도 역할 하나를 판단하되 제품 기대값을 절차로 옮겨 검사를 생략하지 않습니다. 예시의 X나 문장을 실제 산출물에 추가하지 않습니다.
Input routing is not a keyword meaning verdict: an out-of-range product input is a test condition, not an out-of-scope test. Preserve explicit out_of_scope items separately. Explicit [시험 절차 메모], [준비], [복원] markers identify procedure notes; pass them unchanged to Agent 2, not as product expectations. Ambiguous or conflicting authority must be explained as a gap, not silently dropped.
Preserve comparison relations as well as values: >= differs from >; an attempted input differs from the expected retained value. Do not infer correctness from shared numbers. Automatic checks cover explicit contradictions and grounding, not all paraphrase semantics.
Preserve the quoted source's numbers and allow/block or enabled/disabled meaning in statement.
Each SRS condition must cite only its listed Requirements. A pipe (|) separates quoted excerpts, not fixed field positions. Each excerpt must occur verbatim in a statement or acceptance criterion of a listed Requirement, and every listed Requirement must support at least one excerpt. Order and excerpt count do not determine their roles. Do not add row IDs, relation metadata, empty excerpts, or unquoted connective claims to source_text. Separate conditions when their product meaning or scope differs; combined citations alone do not prove a combined interpretation.
Use UNCHANGED only for maintained behavior; do not label a new acceptance criterion UNCHANGED. The enum records this role; no particular maintenance keyword is required. For background ranges, quote the complete criterion of the same target SRS in source_text; statement may explain it without copying that sentence verbatim. Never change its range values or meaning.
당신은 운영 중인 가상 중앙제어 시스템의 변경 요구사항을 분석하는 Agent 1입니다.

입력의 권한 관계:
- 현재 SRS는 제품 기능과 허용 조건의 기준 문서입니다.
- after_value, description, acceptance_notes는 요청한 시험 또는 명시적인 새 정책의 근거입니다. 단순 상태 전환의 시작값·목표값을 제품 허용 범위 개정으로 오해하지 않습니다.
- 명시적인 신규 정책이 현재 SRS에 없다는 사실만으로 정보 부족으로 판정하지 않습니다. 기존 기준 시험은 해당 SRS 기능·허용 범위와 대조하며, 정책 변경인지 시험인지 불명확하면 확인이 필요합니다.

반드시 지킬 규칙:
1. 제공된 변경 요청과 SRS Requirement 행만 사실 근거로 사용합니다.
2. 변경 요청에 명시된 신규 기능, 수치, UI 표현은 변경 후 정책으로 사용할 수 있지만, 변경 요청과 SRS 어디에도 없는 내용은 만들지 않습니다.
3. 현재 MVP는 MODIFIED 변경만 처리합니다.
4. before_condition과 after_condition은 요청 값을 바꾸거나 보완하지 않습니다.
5. change_summary는 Agent 2가 변경 목적을 바로 이해할 수 있게 한두 문장으로 작성합니다.
6. confirmed_conditions에는 Agent 2가 TC의 판정 기준으로 사용할 수 있는 확정 조건만 한 항목씩 분리합니다. 테스트 절차나 새로운 기대값은 만들지 않습니다. 각 조건의 `변경_구분`은 변경 후 새로 검증할 내용이면 `변경`, 변경 전·후에 같은 동작을 회귀 확인하는 내용이면 `유지`, SRS 공통 규칙이나 실행 문맥을 뒷받침하는 내용이면 `보조_근거`로 명시합니다. 단어가 같다는 이유만으로 값의 대응 관계나 실행 순서가 바뀐 조건을 `유지`로 두지 않습니다.
7. acceptance_notes는 제공된 인수 조건 전달 목록에 따라 원문 전체를 해당 위치에 보존합니다. 제품 판정 기준은 confirmed_condition, 명시적 시험 제외는 excluded_scope, 준비·복원 메모는 원문 요청을 통해 Agent 2의 절차로 전달합니다. 제품 허용 범위를 벗어나는 입력을 시험 제외로 분류하지 않습니다. after_value의 변경 후 범위·경계·모드별 정책은 CHANGE_REQUEST 조건에 양쪽 경계와 원문을 보존합니다. description에만 있는 기존 유지 범위는 같은 대상 SRS의 요구사항 또는 인수 기준 전체를 그대로 인용한 SRS·유지 조건으로도 전달할 수 있습니다. 다른 요구사항의 같은 숫자로 대체하지 않습니다.
8. 기존 SRS 조건은 source_type을 SRS로 지정합니다. source_text에는 연결 Requirement의 요구사항 또는 인수 기준에서 연속된 원문을 인용합니다. 여러 원문은 |로 구분할 수 있고 위치로 항목 종류를 정하지 않습니다. 각 조각의 출처와 모든 연결 Requirement의 근거가 있어야 합니다. scope_evidence.srs_source_text도 같은 방식이지만 해당 effect의 Requirement만 출처로 사용합니다. 구분자는 의미를 바꾸거나 임의 내용을 추가할 권한이 아닙니다.
9. 각 confirmed_condition의 requirement_ids와 requirement_effects에는 제공된 SRS에 존재하는 ID만 사용합니다.
10. target_requirement_id도 요청의 의미에 따라 분류합니다. 제품 정책·허용 범위·기능을 실제로 바꾸는 요청은 MODIFIED, 기존 SRS 기준 안에서 상태·값을 조작해 확인하는 시험은 VERIFY입니다. change_type=MODIFIED는 입력 형식이지 모든 요청이 SRS 개정이라는 뜻이 아닙니다. VERIFY의 reason에는 관련 SRS 기능·허용 범위와 시험의 관계를 설명합니다. SRS에 개별 시험 숫자가 문자 그대로 없다는 이유로 수정안을 요구하지 않습니다. 기존 기준을 유지하는 시험에서 준비값이나 성공 기대값이 허용 범위를 벗어나면 충돌로 남깁니다. 범위 밖 입력의 차단을 확인하는 음성 시험과 명시적인 정책 변경은 구분하며, 어느 쪽인지 모호하면 질문합니다.
11. 대상 Requirement의 related_requirement_ids와 변경 요청이 직접 언급하는 기존 Requirement를 모두 검토합니다. 변경 후 정책 때문에 기존 문장이나 인수 기준의 수정이 필요한 연관 Requirement는 UPDATE_REQUIRED, 변경으로 실제 영향을 받을 수 있어 기존 동작 회귀가 필요한 기준은 VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT로 분류하고 이유를 작성합니다. 모든 변경에 일반적으로 적용된다는 이유만으로 알림·상태·제어 Requirement를 일괄 VERIFY로 확장하지 않습니다. 연관 항목을 조용히 생략하지 않습니다.
12. MODIFIED, UPDATE_REQUIRED 또는 VERIFY로 분류한 모든 Requirement는 confirmed_conditions의 requirement_ids에 최소 한 번 연결하고, 변경 요청 또는 해당 SRS의 검증 가능한 원문 조건을 함께 전달합니다.
13. VERIFY로 분류할 Requirement에서 전달할 검증 조건 원문을 찾지 못하면 이유만 추측해 VERIFY로 두지 말고 NO_IMPACT로 분류합니다. UPDATE_REQUIRED는 변경 요청과 기존 SRS가 실제로 충돌하는 경우에만 사용합니다.
14. NO_IMPACT Requirement는 confirmed_conditions의 requirement_ids에 연결하지 않습니다.
15. excluded_scope에는 요청에 명시된 제외 범위, 이번 변경과 무관한 범위, 또는 기대 결과가 불명확해 이번 실행에서 분리할 수 있는 범위를 기록합니다. 확정 조건과 제외 범위를 섞지 않습니다.
16. 변경 요청 내부의 충돌, 필수 기대 동작 누락 또는 대상 Requirement 불일치가 있을 때만 information_gaps와 user_questions에 기록합니다. 명확한 확정 조건도 함께 있고 불명확한 범위를 별도로 격리할 수 있으면 PARTIAL_PROCEED를 선택하고, 이번 실행에서 제외하는 information_gaps 원문을 `제외된_정보_부족`에 같은 목록으로 기록합니다.
16-1. 인수 조건 원문에 목표값 미정·미확정 등 정보 부족이 명시되어 있으면 해당 원문 전체를 information_gaps에 보존하고 user_questions에 필요한 질문을 남기며 confirmed_conditions에는 넣지 않습니다. 확정 범위와 분리하여 PARTIAL_PROCEED할 때만 같은 원문을 제외된_정보_부족과 excluded_scope에도 보존합니다. 핵심 조건이 미정이라 WAITING_FOR_USER이면 그 조건은 확인할 대상이지 제외 범위가 아닙니다. 요청에 명시된 실제 제외 범위는 별도로 유지합니다. 명확한 인수 기준을 임의로 정보 부족으로 바꾸어 제외하지 않습니다.
17. 변경 요청에 이미 명시된 값을 SRS에 없다는 이유로 다시 확정해 달라고 질문하지 않습니다.
18. Toast 같은 안내 수단의 정확한 문구는 변경 요청이 문구 일치를 요구할 때만 필수 정보로 봅니다.
19. 질문이 없고 변경 전 근거, 변경 후 정책과 전달할 확정 조건이 명확하면 PROCEED를 선택합니다. PARTIAL_PROCEED는 확정 조건을 Agent 2로 계속 전달하고 excluded_scope와 information_gaps만 최종 보고 대상으로 남깁니다. 핵심 기대 결과를 확정할 수 없어 분리 진행도 불가능할 때만 WAITING_FOR_USER를 선택합니다.
20. 테스트케이스, 테스트 절차나 Playwright 코드는 작성하지 않습니다.
21. Agent 1은 요구사항 영향도와 확정 조건을 Agent 2에 빠짐없이 전달하는 단계입니다. 현재 UI·하네스·자동화 구현 지원 여부를 이유로 영향 있는 Requirement를 NO_IMPACT로 낮추거나 확정된 제품 조건을 excluded_scope로 보내지 않습니다. TC 구성·기존 TC 선택·자동화 가능 여부는 Agent 2 이후 단계의 책임입니다.
22. 연결 관계는 confirmed_conditions.requirement_ids 한 곳에만 작성합니다. 대상 외 VERIFY·UPDATE_REQUIRED는 해당 CHANGE_REQUEST 조건의 requirement_ids에 연결하고 scope_evidence에는 basis와 해당 연관 SRS 원문 srs_source_text만 작성합니다. request_condition_ids는 프로그램이 이 연결 목록에서 계산하므로 작성하지 않습니다. SRS 조건만 연결하면 요청 영향의 근거가 되지 않습니다. reason에는 어떤 요청 변경이 어떤 기존 동작에 영향을 주는지 적습니다. SRS에 존재하거나 같은 화면에서 실행된다는 이유만으로 검사 범위를 늘리지 않습니다. 근거가 없는 항목은 NO_IMPACT로 검토 기록만 남깁니다.
23. DIRECT_REQUEST·REQUEST_TRACE_ONLY·CHANGE_DEPENDENCY는 범위 근거를 설명하는 분류입니다. 분류명만으로 진행·보류를 정하지 않습니다. 요청 문장에 Requirement ID나 SRS 전체 문장을 넣을 필요는 없습니다. 실제 요청 조건과 연관 Requirement의 연결을 보존하고, 그 검사가 요청된 범위인지 기존 의미 검토에서 원문과 대조합니다. 원문에 없는 ID·문장을 만들거나 명시된 조건을 NO_IMPACT로 지우지 않습니다.
24. 요청된 결과에 관련 SRS를 참고로 연결하는 것과 새 검사·정책 변경을 추가하는 것을 구분합니다. 참고 연결은 관련 SRS 전체를 시험한다는 뜻이 아닙니다. source_text에는 실제 요청 원문을, scope_evidence에는 해당 SRS 원문을 보존합니다. 연결 조건 ID는 조건 목록에서 계산됩니다. 분류와 무관하게 요청 밖 알림·기능·기대값을 추가하지 않습니다. 실제 범위가 불명확하면 질문하고, 단지 ID·전체 SRS 문장이 요청에 없다는 이유로 질문하거나 보류하지 않습니다.
""".strip()


AGENT1_SYSTEM_INSTRUCTIONS += """
변경 후 기준은 원문 전체의 의미로 구분하세요. 이전/부정/제외된 범위와 실제 적용할 새 범위를 같은 필수 조건으로 만들지 않습니다. before/after와 인수 조건의 적용 대상·상하한·경계 포함 여부·허용/차단·기존값 유지를 보존하세요. after_value·description의 요구도 빠짐없이 조건 또는 해당 절차로 연결하고, 원문 인용은 자의적으로 바꾸지 않습니다. 불명확하면 정보 부족으로 남깁니다.
"""

# 2026-10-20: the Agent 1 impact analysis once wrote "panel re-display is not checked
# separately" for a fan request, contradicting confirmed rule F-1 that Agent 2 follows.
AGENT1_SYSTEM_INSTRUCTIONS += "\n" + QA_AGENT1_RULES_NOTE + "\n" + QA_CONFIRMED_RULES
AGENT1_SYSTEM_INSTRUCTIONS += "\n" + QA_LANGUAGE_RULE


class Agent1Error(RuntimeError):
    """Raised when Agent 1 cannot produce a validated structured response."""


@dataclass(frozen=True)
class Agent1Response:
    analysis: Agent1Analysis
    response_id: str | None
    model: str
    usage: dict[str, int | None]
    link_draft: Agent1AnalysisDraft | None = None


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
        self.model = model or os.getenv("OPENAI_MODEL", "gpt-6.1-sol")
        if client is None:
            if not os.getenv("OPENAI_API_KEY"):
                raise Agent1Error(
                    "OPENAI_API_KEY 환경변수가 없습니다. 키를 코드에 넣지 말고 "
                    "PowerShell 환경변수로 설정하세요."
                )
            client = OpenAI(max_retries=0)
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
        user_input += (
            "\n\n[검사기와 공유하는 인수 조건 전달 목록]\n"
            f"{json.dumps(_acceptance_delivery_contract(request), ensure_ascii=False)}\n"
            "각 source_text를 지정된 destination으로 빠짐없이 전달하세요. "
            "destination의 '/'는 서로 배타적인 역할 선택지입니다. 하나를 선택하고 "
            "confirmed_conditions.source_text와 procedure_notes에 같은 원문을 중복 복사하지 마세요. "
            "이는 출력 자동 보정이나 의미 합격 판정이 아닙니다. 범위·대상 제한도 확정 조건에서 누락하지 마세요. "
            "절차 메모는 원문 요청에 보존되므로 제품 기대값이나 제외 범위로 바꾸지 마세요. "
            "미정 항목은 분리 가능할 때만 PARTIAL_PROCEED와 세 정보 부족 목록에 원문을 보존하고, "
            "핵심 범위가 불명확하면 WAITING_FOR_USER로 남기세요."
            "description에만 있는 기존 유지 범위는 같은 target Requirement의 SRS 요구사항 또는 인수 기준 전체 원문을 "
            "statement와 source_text에 그대로 보존하고 SRS·유지로 연결해도 됩니다. "
            "after_value에 명시된 범위는 이 예외로 대체하지 말고 CHANGE_REQUEST 조건으로 전달하세요. "
            "다른 Requirement·다른 대상의 같은 숫자는 근거가 아닙니다."
            "새 검사 정책에서는 단어로 제외·절차 역할을 결정하지 않습니다. "
            "준비·복원에 해당하는 acceptance_notes는 procedure_notes에 원문 전체를 보존하세요. "
            "제품 조건을 절차로 바꿔 검사를 생략하지 마세요. 분류의 의미 정확성을 자동 검사 통과로 보장하지 않습니다. "
            "출처 인용은 그대로 유지하되 분석 설명의 동의어·문체를 검사기에 맞추어 바꾸지 마세요."
        )
        if previous_analysis is not None:
            feedback = "\n".join(f"- {item}" for item in (checkpoint_feedback or []))
            user_input += (
                "\n\n[이전 분석 결과]\n"
                f"{agent1_link_draft(previous_analysis).model_dump_json(indent=2)}\n\n"
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
                prompt_cache_key="qa-v2-agent1-2-25-rules-1",
                input=[
                    {"role": "system", "content": AGENT1_SYSTEM_INSTRUCTIONS},
                    {"role": "user", "content": user_input},
                ],
                text_format=Agent1AnalysisDraft,
            )
        except Exception as exc:  # SDK exceptions vary by transport and status.
            raise Agent1Error(f"Agent 1 모델 호출에 실패했습니다 ({type(exc).__name__}). 외부 오류 본문은 저장하지 않습니다.") from None

        parsed = getattr(response, "output_parsed", None)
        if parsed is None:
            raise Agent1Error("모델이 구조화된 Agent 1 결과를 반환하지 않았습니다.")

        draft = Agent1AnalysisDraft.model_validate(parsed.model_dump(mode="json"))
        return Agent1Response(
            analysis=bind_agent1_requirement_links(draft),
            response_id=getattr(response, "id", None),
            model=self.model,
            usage=_response_usage_summary(response),
            link_draft=draft,
        )

# ---------------------------------------------------------------------------
# Checkpoint 1: 요구사항 분석 검증
# ---------------------------------------------------------------------------
def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _contains(container: str, expected: str) -> bool:
    return _normalize(expected) in _normalize(container)


def _contains_fact(container: str, expected: str) -> bool:
    """Match a quote without cutting an identifier or a signed numeric token."""
    expected = expected.strip()
    if not expected:
        return False
    pattern = r"\s*".join(re.escape(part) for part in expected.split())
    if re.match(r"[A-Za-z0-9_]", expected[0]):
        pattern = r"(?<![A-Za-z0-9_])" + pattern
    if re.match(r"[A-Za-z0-9_]", expected[-1]):
        pattern += r"(?![A-Za-z0-9_])"
    numbers = list(re.finditer(r"[+\-−]?(?:\d+(?:\.\d+)?|\.\d+)(?:[eE][+\-]?\d+)?", container))
    for match in re.finditer(pattern, container, re.I):
        partial_number = False
        for number in numbers:
            start, end = number.span()
            # In 16-30 the hyphen separates endpoints, unlike a unary -30.
            if container[start] == "-" and start and container[start - 1].isdigit():
                start += 1
            if start < match.start() < end or start < match.end() < end:
                partial_number = True
                break
        if not partial_number:
            return True
    return False


def _srs_quote_parts(source_text: str) -> list[str]:
    """Preserve every excerpt; empty segments must not disappear silently."""
    parts = [part.strip() for part in source_text.split("|")]
    return parts if all(parts) else []


def _srs_quote_is_grounded(
    source_text: str, requirement_ids: list[str], requirements: dict[str, SrsRequirement]
) -> bool:
    """Match excerpts to linked fields, independent of order or field position.

    Both sides need coverage: no unsupported excerpt and no unrelated linked ID.
    This establishes provenance, not the semantics of combining the excerpts.
    """
    parts = _srs_quote_parts(source_text)
    if not parts or not requirement_ids or any(key not in requirements for key in requirement_ids):
        return False
    matches = [
        [any(_contains_fact(field, part) for field in (
            requirements[key].statement, requirements[key].acceptance_criteria
        )) for key in requirement_ids]
        for part in parts
    ]
    return all(any(row) for row in matches) and all(
        any(row[index] for row in matches) for index in range(len(requirement_ids))
    )


def _numeric_facts(text: str) -> set[str]:
    text = re.sub(r"\b(?:REQ|TC|COND|ER)-[A-Z0-9-]+", "", text)
    return {f"{float(value):g}" for value in re.findall(r"(?<![\w.])-?\d+(?:\.\d+)?", text)}


def _request_quote_parts(source_text: str, authority: list[str]) -> list[str]:
    """Resolve provenance once; never infer meaning from excerpt position."""
    authority = [part for part in authority if part]
    # A literal pipe inside a genuine quote is not an invented separator.
    if any(_contains_fact(part, source_text) for part in authority):
        return [source_text.strip()]
    excerpts = _srs_quote_parts(source_text)
    return excerpts if excerpts and all(
        any(_contains_fact(part, excerpt) for part in authority) for excerpt in excerpts
    ) else []


def _state_polarities(text: str, positive: str, negative: str) -> set[bool]:
    """Recognize explicit state words, removing negative forms before positives."""
    lowered = text.casefold()
    for affirmative, negated in (("enabled", "disabled"), ("checked", "unchecked"), ("allowed", "blocked"), ("on", "off")):
        lowered = re.sub(r"\bnot\s+" + affirmative + r"\b", negated, lowered)
    result = {False} if re.search(negative, lowered) else set()
    remainder = re.sub(negative, " ", lowered)
    if re.search(positive, remainder):
        result.add(True)
    return result


_STATE_WORD_PAIRS = (
    (r"(?<![a-z_])true(?![a-z_])", r"(?<![a-z_])false(?![a-z_])"),
    (r"활성|(?<![a-z_])enabled?(?![a-z_])", r"비활성|(?<![a-z_])disabled?(?![a-z_])"),
    (r"허용|(?<![a-z_])allow(?:ed)?(?![a-z_])", r"차단|금지|(?<![a-z_])(?:block(?:ed)?|denied|forbidden)(?![a-z_])"),
    (r"선택됨|체크됨|(?<![a-z_])checked(?![a-z_])", r"선택\s*해제|체크\s*해제|(?<![a-z_])unchecked(?![a-z_])"),
    (r"켜짐|켠다|(?<![a-z_])on(?![a-z_])", r"꺼짐|끈다|(?<![a-z_])off(?![a-z_])"),
)


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


def _acceptance_delivery_contract(request: ChangeRequest) -> list[dict[str, str]]:
    """Route acceptance notes only by explicit input fields/markers, without editing them."""
    excluded = {_normalize(s) for s in request.out_of_scope}
    rows = []
    for index, note in enumerate(request.acceptance_notes, 1):
        destination = ("excluded_scope" if _normalize(note) in excluded
                       else "procedure_notes" if re.match(r"\s*\[(?:준비|복원|시험 절차 메모)\]", note)
                       else "confirmed_conditions.source_text / procedure_notes / explicit information_gaps")
        rows.append({"note_id": f"NOTE-{index:03d}", "source_text": note, "destination": destination})
    return rows


def evaluate_checkpoint1(
    request: ChangeRequest,
    analysis: Agent1Analysis,
    requirements: dict[str, SrsRequirement],
) -> Checkpoint1Result:
    """Current CP1 only (2026-10-20 cleanup: no historical switches).

    Code checks sources, links, routing and decisions. Wording, range meaning and
    scope meaning are owned by the mandatory grounding review.
    """
    checks: list[CheckResult] = []
    baseline_test = any(
        effect.requirement_id == request.target_requirement_id and effect.relation == RequirementRelation.VERIFY
        for effect in analysis.requirement_effects)
    request_parts = [request.after_value, request.description, request.reason, *request.acceptance_notes]
    if baseline_test:
        request_parts.append(request.before_value)

    def request_quotes(source):
        return _request_quote_parts(source, request_parts)

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
    elif not before_has_source and not baseline_test:
        add(
            "CP1-004",
            CheckStatus.REVIEW,
            "변경 전 값이 대상 SRS 행에서 직접 확인되지 않습니다.",
        )
    else:
        add("CP1-004", CheckStatus.PASS, "시험 시작값이 요청과 일치합니다. SRS 허용 여부는 필수 의미 검토 대상입니다."
            if baseline_test else "변경 전 값이 요청과 SRS 근거에 연결됩니다.")

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
    elif len(target_effects) != 1 or target_effects[0].relation not in {
            RequirementRelation.MODIFIED, RequirementRelation.VERIFY}:
        add("CP1-006", CheckStatus.FAIL, "대상 Requirement의 변경/시험 분류가 없거나 중복·허용되지 않은 분류입니다.")
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

    def srs_contains(requirement_id, source_text):
        return requirement_id in requirements and _contains_fact(
            f"{requirements[requirement_id].statement} {requirements[requirement_id].acceptance_criteria}",
            source_text)

    for condition in analysis.confirmed_conditions:
        quoted_srs = "|" in condition.source_text
        if condition.source_type == ConditionSource.CHANGE_REQUEST:
            grounded = bool(request_quotes(condition.source_text))
        elif quoted_srs:
            grounded = _srs_quote_is_grounded(condition.source_text, condition.requirement_ids, requirements)
        else:
            grounded = any(srs_contains(requirement_id, condition.source_text)
                           for requirement_id in condition.requirement_ids)
        if not grounded:
            invalid_conditions.append(condition.condition_id)
        numeric_sources = condition.source_text
        if condition.source_type == ConditionSource.SRS:
            # A baseline range need not enumerate every requested test value.
            # Presence is only provenance; mandatory review checks range/role.
            numeric_sources += " " + request_authority
            if baseline_test:
                numeric_sources += " " + request.before_value
        if _numeric_facts(condition.statement) - _numeric_facts(numeric_sources):
            invalid_conditions.append(condition.condition_id + ": 원문과 분석의 값·의미 불일치")
        if condition.source_type == ConditionSource.SRS and not (
            grounded if quoted_srs else all(
                srs_contains(requirement_id, condition.source_text)
                for requirement_id in condition.requirement_ids
            )
        ):
            invalid_conditions.append(condition.condition_id + ": Requirement별 SRS 출처 누락")

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
    # Preserve explicit role markers using the same routing list sent to
    # Agent 1. No interpretation of the note's verbs or body is needed.
    required_procedures = [row["source_text"] for row in _acceptance_delivery_contract(request)
                           if row["destination"] == "procedure_notes"]
    procedure_keys = [_normalize(note) for note in analysis.procedure_notes]
    other_role_keys = {
        _normalize(item) for item in [
            *(condition.source_text for condition in analysis.confirmed_conditions),
            *request.out_of_scope, *analysis.excluded_scope,
            *analysis.information_gaps, *analysis.excluded_information_gaps,
        ]
    }
    procedure_errors = []
    if len(procedure_keys) != len(set(procedure_keys)):
        procedure_errors.append("procedure_notes에 동일 원문을 중복 기록")
    if any(note not in request.acceptance_notes for note in analysis.procedure_notes):
        procedure_errors.append("입력에 없는 절차 원문")
    missing_procedures = [note for note in required_procedures if note not in analysis.procedure_notes]
    if missing_procedures:
        procedure_errors.append("표시된 절차 원문은 procedure_notes에 보존: " + " | ".join(missing_procedures))
    conflicting_procedures = [note for note in analysis.procedure_notes
                              if _normalize(note) in other_role_keys or any(
                                  _contains_fact(part, note) for source in change_request_sources
                                  for part in request_quotes(source))]
    if conflicting_procedures:
        procedure_errors.append("절차와 확정 조건·제외 범위·정보 부족의 중복 분류: " + " | ".join(conflicting_procedures))
    # Only explicit input fields/markers determine routing. Unmarked notes
    # must still be preserved in a condition or the explicit gap/scope lists;
    # word fragments do not establish their meaning.
    excluded_note_keys = {_normalize(s) for s in [*request.out_of_scope, *analysis.excluded_scope]}
    positive_acceptance_notes = [note for note in request.acceptance_notes
                                 if _normalize(note) not in excluded_note_keys
                                 and note not in analysis.procedure_notes]
    add("CP1-012", CheckStatus.FAIL if procedure_errors else CheckStatus.PASS,
        "절차 원문·역할 연결 오류: " + "; ".join(procedure_errors) if procedure_errors
        else "절차 원문 연결을 확인했습니다. 절차 분류의 의미 정확성·실제 수행은 별도 확인 대상입니다.")
    # Explicitly unresolved request notes may be handed off as gaps, not assertions.
    # All three records must retain the request verbatim; clear criteria still belong
    # in confirmed conditions even if the model labels them as a gap.
    recorded_gaps = (
        {_normalize(item) for item in analysis.information_gaps}
        & {_normalize(item) for item in analysis.excluded_information_gaps}
        & {_normalize(item) for item in analysis.excluded_scope}
    ) if analysis.decision == AnalysisDecision.PARTIAL_PROCEED else set()
    if analysis.decision == AnalysisDecision.WAITING_FOR_USER:
        # Waiting preserves unresolved input without declaring it out of scope.
        # CP1-010 and the mandatory review still check the question/decision;
        # WAITING_FOR_USER never authorizes the Agent 2 handoff.
        recorded_gaps = {_normalize(item) for item in analysis.information_gaps}
    missing_acceptance_notes = [
        note
        for note in positive_acceptance_notes
        if _normalize(note) not in recorded_gaps
        if not any(_contains_fact(part, note) for source in change_request_sources for part in request_quotes(source))
    ]
    # Range coverage and meaning are reviewed from the raw request by the
    # mandatory grounding review; numbers alone do not establish a requirement.
    if missing_acceptance_notes:
        add(
            "CP1-008",
            CheckStatus.FAIL,
            "Agent 2 전달 조건에서 누락된 항목: 인수 조건 원문=" + " | ".join(missing_acceptance_notes),
        )
    else:
        add("CP1-008", CheckStatus.PASS,
            "인수 조건 원문 전달을 확인했습니다. 변경 전·후 범위와 조건 누락의 의미는 필수 원문 검토에서 확인합니다.")

    confirmed_statements = {_normalize(item.statement) for item in analysis.confirmed_conditions}
    confirmed_statements |= {_normalize(item.source_text) for item in analysis.confirmed_conditions}
    excluded = {_normalize(item) for item in analysis.excluded_scope}
    explicit_exclusions = {_normalize(item) for item in request.out_of_scope}
    scope_limit_condition_ids = sorted(
        c.condition_id for c in analysis.confirmed_conditions
        if c.source_type == ConditionSource.CHANGE_REQUEST and (
            _normalize(c.source_text) in explicit_exclusions or any(
                _contains_fact(part, excluded_note) for part in request_quotes(c.source_text)
                for excluded_note in request.out_of_scope))
    )
    missing_scope_limit_notes = [
        note for note in request.acceptance_notes
        if _normalize(note) in excluded_note_keys and _normalize(note) not in excluded
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
    else:
        add("CP1-010", CheckStatus.PASS, "정보 부족·질문·진행 판정이 일관됩니다.")

    # CP1-011: provenance and links of related-requirement scope. Scope meaning
    # belongs to the mandatory grounding review. Since the 2026-10-17 user
    # decision, a weak scope basis is a warning, not a stop.
    scope_errors: list[str] = []
    conditions_by_id = {item.condition_id: item for item in analysis.confirmed_conditions}
    # Do not use before_value, reason, preparation, or exclusions as authority
    # for adding a product assertion. Keep each input field separate.
    positive_request_parts = [
        part for part in [request.after_value, request.description, *request.acceptance_notes]
        if _normalize(part) not in explicit_exclusions
    ]
    # A VERIFY quote may include its stated preparation context, as CP1-007
    # already permits. It must also cite an actual requested condition;
    # before_value alone remains insufficient authority for another check.
    scope_quote_parts = positive_request_parts + ([request.before_value] if baseline_test else [])
    for effect in analysis.requirement_effects:
        if (effect.requirement_id == request.target_requirement_id
                or effect.relation == RequirementRelation.NO_IMPACT):
            continue
        label = effect.requirement_id
        proof = effect.scope_evidence
        related = requirements.get(label)
        if proof is None:
            scope_errors.append(f"{label}: 요청과 연결된 검사 범위 근거 누락")
            continue
        sources = [conditions_by_id.get(key) for key in proof.request_condition_ids]
        if (len(set(proof.request_condition_ids)) != len(proof.request_condition_ids)
                or not all(
                    item is not None
                    and item.source_type == ConditionSource.CHANGE_REQUEST
                    and any(
                        any(_contains_fact(part, excerpt) for part in positive_request_parts)
                        for excerpt in _request_quote_parts(item.source_text, scope_quote_parts)
                    )
                    for item in sources
                )):
            scope_errors.append(f"{label}: 긍정 변경 요청 원문 조건에 연결되지 않은 범위 근거")
            continue
        if related is None or not (
            _srs_quote_is_grounded(proof.srs_source_text, [label], requirements)
            if "|" in proof.srs_source_text else any(
                _contains_fact(part, proof.srs_source_text)
                for part in [related.statement, related.acceptance_criteria]
            )
        ):
            scope_errors.append(f"{label}: 연관 Requirement의 영향 근거 원문 불일치")
            continue
        if not all(label in item.requirement_ids for item in sources):
            scope_errors.append(f"{label}: 요청 조건과 Requirement 연결 불일치")
    if scope_errors:
        add("CP1-011", CheckStatus.PASS,
            "경고(진행, 사람 확인 권장): 범위 근거 보완 필요 — " + "; ".join(scope_errors))
    else:
        add("CP1-011", CheckStatus.PASS,
            "범위 근거의 출처·연결을 확인했습니다. 범위의 의미는 별도 근거 검토에서 확인합니다.")

    # 2026-10-25: user questions and analysis text are read by people. Reported only on a
    # violation, so saved Korean analyses recompute the same checkpoint.
    foreign = foreign_script_texts(
        analysis.model_dump(mode="json"),
        [request.model_dump_json(), *(r.model_dump_json() for r in requirements.values())])
    if foreign:
        add("CP1-LANG", CheckStatus.FAIL, "한국어로 다시 작성해야 하는 분석 문장(한자·일본 문자 포함): " + "; ".join(foreign[:8]))

    status = _aggregate_check_status(check.status for check in checks)
    if status in {CheckStatus.FAIL, CheckStatus.ERROR}:
        handoff_status = HandoffStatus.BLOCKED
    elif analysis.decision == AnalysisDecision.WAITING_FOR_USER:
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
