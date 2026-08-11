from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from openai import OpenAI

from .models import Agent1Analysis, ChangeRequest, SrsRequirement
from .srs import render_srs_context


SYSTEM_INSTRUCTIONS = """
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
5. direct_impacts에는 target_requirement_id를 반드시 포함합니다.
6. 모든 영향 Requirement ID는 제공된 SRS에 존재해야 합니다.
7. evidence_text는 SRS의 요구사항 또는 인수 기준에서 연속된 원문 일부를 그대로 사용합니다.
8. 변경 요청 내부의 충돌, 필수 기대 동작 누락 또는 대상 Requirement 불일치가 있을 때만 information_gaps와 user_questions에 기록합니다.
9. 변경 요청에 이미 명시된 값을 SRS에 없다는 이유로 다시 확정해 달라고 질문하지 않습니다.
10. Toast 같은 안내 수단의 정확한 문구는 변경 요청이 문구 일치를 요구할 때만 필수 정보로 봅니다.
11. 질문이 없고 변경 전 근거, 변경 후 정책과 영향 범위가 명확하면 PROCEED를 선택합니다.
12. 테스트케이스나 Playwright 코드는 작성하지 않습니다.
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
    ) -> Agent1Response:
        user_input = (
            "[변경 요청]\n"
            f"{request.model_dump_json(indent=2)}\n\n"
            "[현재 SRS Requirement]\n"
            f"{render_srs_context(requirements)}"
        )

        try:
            response = self.client.responses.parse(
                model=self.model,
                reasoning={"effort": "medium"},
                store=False,
                input=[
                    {"role": "system", "content": SYSTEM_INSTRUCTIONS},
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

