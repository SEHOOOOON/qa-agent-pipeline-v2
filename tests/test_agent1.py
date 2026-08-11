from types import SimpleNamespace

import pytest

from qa_pipeline_v2.agent1 import Agent1Error, OpenAIAgent1
from qa_pipeline_v2.models import (
    Agent1Analysis,
    AnalysisDecision,
    ChangeRequest,
    Evidence,
    Impact,
    SrsRequirement,
)


def analysis() -> Agent1Analysis:
    return Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_condition="16~30°C",
        after_condition="18~30°C",
        changed_fields=["섭씨 설정 범위"],
        direct_impacts=[Impact(requirement_id="REQ-TEMP-001", reason="직접 변경")],
        related_impacts=[],
        verified_scope=["설정 범위"],
        excluded_scope=[],
        information_gaps=[],
        user_questions=[],
        evidence=[
            Evidence(
                requirement_id="REQ-TEMP-001",
                evidence_text="섭씨 설정 범위는 16~30°C여야 합니다.",
            )
        ],
        decision=AnalysisDecision.PROCEED,
    )


class FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_test",
            output_parsed=analysis(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )


def test_agent1_uses_structured_responses_api() -> None:
    responses = FakeResponses()
    fake_client = SimpleNamespace(responses=responses)
    agent = OpenAIAgent1(model="gpt-5.6-terra", client=fake_client)
    request = ChangeRequest(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_value="16~30°C",
        after_value="18~30°C",
        description="설정 범위를 변경한다.",
    )
    requirements = {
        "REQ-TEMP-001": SrsRequirement(
            requirement_id="REQ-TEMP-001",
            statement="섭씨 설정 범위는 16~30°C여야 합니다.",
            acceptance_criteria="범위 밖 요청이 차단됩니다.",
        )
    }

    result = agent.analyze(request, requirements)

    assert result.response_id == "resp_test"
    assert result.usage["total_tokens"] == 150
    assert responses.kwargs["text_format"] is Agent1Analysis
    assert responses.kwargs["store"] is False
    instructions = responses.kwargs["input"][0]["content"]
    assert "현재 SRS는 변경 전 제품 상태" in instructions
    assert "변경 후 정책의 권한 있는 입력" in instructions
    assert "SRS에 없다는 이유로 다시 확정" in instructions


def test_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent1Error, match="OPENAI_API_KEY"):
        OpenAIAgent1()

