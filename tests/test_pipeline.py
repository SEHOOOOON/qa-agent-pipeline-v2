# Product SRS parser
from pathlib import Path

from qa_pipeline_v2 import load_srs_requirements, render_srs_context


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loads_product_requirements_from_markdown() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert len(requirements) >= 20
    assert requirements["REQ-TEMP-001"].statement == "섭씨 설정 범위는 16~30°C여야 합니다."
    assert "범위 밖 요청" in requirements["REQ-TEMP-001"].acceptance_criteria
    assert set(requirements["REQ-TEMP-001"].related_requirement_ids) == {
        "REQ-CONTROL-001",
        "REQ-LOCAL-002",
        "REQ-NOTIFY-001",
        "REQ-STATE-001",
    }
    assert "Toast" in requirements["REQ-NOTIFY-001"].acceptance_criteria
    assert "currentTemp" in requirements["REQ-MONITOR-001"].acceptance_criteria


def test_rendered_context_contains_ids_and_acceptance_criteria() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    context = render_srs_context(requirements)

    assert "REQ-LOCK-001" in context
    assert "차단 안내가 표시됩니다" in context
    assert "관련 요구사항: REQ-CONTROL-001" in context

def test_product_srs_excludes_test_harness_requirements() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert "REQ-REGISTER-001" not in requirements
    assert "REQ-RESET-001" not in requirements

# Agent 1
from types import SimpleNamespace

import pytest

from qa_pipeline_v2 import Agent1Error, OpenAIAgent1
from qa_pipeline_v2 import (
    Agent1Analysis,
    AnalysisDecision,
    ChangeRequest,
    ConditionSource,
    ConfirmedCondition,
    RequirementEffect,
    RequirementRelation,
    SrsRequirement,
)


def agent1_analysis() -> Agent1Analysis:
    return Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        change_summary="AUTO 모드 설정 범위를 변경한다.",
        before_condition="16~30°C",
        after_condition="18~30°C",
        confirmed_conditions=[
            ConfirmedCondition(
                condition_id="COND-001",
                statement="AUTO 모드의 설정 범위는 18~30°C다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="AUTO 모드의 설정 범위는 18~30°C입니다.",
                requirement_ids=["REQ-TEMP-001"],
            )
        ],
        requirement_effects=[
            RequirementEffect(
                requirement_id="REQ-TEMP-001",
                relation=RequirementRelation.MODIFIED,
                reason="AUTO 모드 설정 범위가 변경된다.",
            )
        ],
        excluded_scope=[],
        information_gaps=[],
        user_questions=[],
        decision=AnalysisDecision.PROCEED,
    )


class Agent1FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_test",
            output_parsed=agent1_analysis(),
            usage=SimpleNamespace(input_tokens=100, output_tokens=50, total_tokens=150),
        )


def test_agent1_uses_structured_responses_api() -> None:
    responses = Agent1FakeResponses()
    fake_client = SimpleNamespace(responses=responses)
    agent = OpenAIAgent1(model="gpt-5.6-terra", client=fake_client)
    request = ChangeRequest(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_value="16~30°C",
        after_value="18~30°C",
        description="AUTO 모드의 설정 범위는 18~30°C입니다.",
        acceptance_notes=["AUTO 모드의 설정 범위는 18~30°C입니다."],
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
    assert "acceptance_notes의 모든 항목" in instructions
    assert "Agent 2가 TC의 판정 기준" in instructions
    assert "VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT" in instructions
    assert "연관 항목을 조용히 생략하지 않습니다" in instructions
    assert "MODIFIED 또는 VERIFY로 분류한 모든 Requirement" in instructions
    assert "검증 조건 원문을 찾지 못하면" in instructions
    assert "테스트 절차나 Playwright 코드는 작성하지 않습니다" in instructions


def test_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent1Error, match="OPENAI_API_KEY"):
        OpenAIAgent1()

# Checkpoint 1
from pathlib import Path

from qa_pipeline_v2 import evaluate_checkpoint1
from qa_pipeline_v2 import (
    Agent1Analysis,
    AnalysisDecision,
    ChangeRequest,
    CheckStatus,
    ConditionSource,
    ConfirmedCondition,
    RequirementEffect,
    RequirementRelation,
)
from qa_pipeline_v2 import load_srs_requirements


REPO_ROOT = Path(__file__).resolve().parents[1]


def cp1_request() -> ChangeRequest:
    return ChangeRequest(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_value="16~30°C",
        after_value="AUTO 모드는 18~30°C",
        description="AUTO 모드의 설정 범위를 18~30°C로 변경한다.",
        acceptance_notes=[
            "AUTO 모드에서 18°C는 허용합니다.",
            "AUTO 모드에서 18°C 미만 요청은 차단합니다.",
        ],
    )


def cp1_valid_analysis() -> Agent1Analysis:
    return Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        change_summary="AUTO 모드 설정 온도 하한을 18°C로 변경한다.",
        before_condition="현재 섭씨 설정 범위는 16~30°C다.",
        after_condition="변경 후 AUTO 모드는 18~30°C다.",
        confirmed_conditions=[
            ConfirmedCondition(
                condition_id="COND-001",
                statement="AUTO 모드에서 18°C는 허용한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="AUTO 모드에서 18°C는 허용합니다.",
                requirement_ids=["REQ-TEMP-001"],
            ),
            ConfirmedCondition(
                condition_id="COND-002",
                statement="AUTO 모드에서 18°C 미만 요청은 차단한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="AUTO 모드에서 18°C 미만 요청은 차단합니다.",
                requirement_ids=["REQ-TEMP-001"],
            ),
            ConfirmedCondition(
                condition_id="COND-003",
                statement="기존 섭씨 설정 범위는 16~30°C다.",
                source_type=ConditionSource.SRS,
                source_text="섭씨 설정 범위는 16~30°C여야 합니다.",
                requirement_ids=["REQ-TEMP-001"],
            ),
        ],
        requirement_effects=[
            RequirementEffect(
                requirement_id="REQ-TEMP-001",
                relation=RequirementRelation.MODIFIED,
                reason="AUTO 모드 설정 범위가 변경된다.",
            ),
            RequirementEffect(
                requirement_id="REQ-CONTROL-001",
                relation=RequirementRelation.NO_IMPACT,
                reason="적용 명령 정책은 이번 단위 입력에서 변경하지 않는다.",
            ),
            RequirementEffect(
                requirement_id="REQ-LOCAL-002",
                relation=RequirementRelation.NO_IMPACT,
                reason="현장 온도 정책은 이번 단위 입력에서 변경하지 않는다.",
            ),
            RequirementEffect(
                requirement_id="REQ-NOTIFY-001",
                relation=RequirementRelation.NO_IMPACT,
                reason="알림 정책은 이번 단위 입력에서 변경하지 않는다.",
            ),
            RequirementEffect(
                requirement_id="REQ-STATE-001",
                relation=RequirementRelation.NO_IMPACT,
                reason="공통 상태 정합성 정책은 이번 단위 입력에서 변경하지 않는다.",
            )
        ],
        excluded_scope=["화씨 표시 정책"],
        information_gaps=[],
        user_questions=[],
        decision=AnalysisDecision.PROCEED,
    )


def cp1_requirements():
    return load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")


def cp1_check(result, rule_id: str):
    return next(item for item in result.checks if item.rule_id == rule_id)


def test_valid_analysis_passes_checkpoint1() -> None:
    result = evaluate_checkpoint1(cp1_request(), cp1_valid_analysis(), cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 10
    assert all(item.status == CheckStatus.PASS for item in result.checks)


def test_unknown_requirement_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "requirement_effects": [
                *cp1_valid_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-FAKE-999",
                    relation=RequirementRelation.VERIFY,
                    reason="존재하지 않는 기능",
                ),
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL


def test_missing_related_requirement_review_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "requirement_effects": [
                item
                for item in cp1_valid_analysis().requirement_effects
                if item.requirement_id != "REQ-STATE-001"
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL


def test_condition_requirement_missing_from_effects_is_rejected() -> None:
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement="화면과 내부 상태가 일치한다.",
            source_type=ConditionSource.SRS,
            source_text="status·mode·currentTemp·setTemp·fanSpeed·locked 등 검증 대상 공통 값이 같습니다.",
            requirement_ids=["REQ-STATE-001"],
        ),
    ]
    effects = [
        item
        for item in cp1_valid_analysis().requirement_effects
        if item.requirement_id != "REQ-STATE-001"
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-006").status == CheckStatus.FAIL


def test_unverified_before_value_requires_review() -> None:
    changed_request = cp1_request().model_copy(update={"before_value": "17~30°C"})
    analysis = cp1_valid_analysis().model_copy(
        update={"before_condition": "현재 섭씨 설정 범위는 17~30°C다."}
    )

    result = evaluate_checkpoint1(changed_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert cp1_check(result, "CP1-004").status == CheckStatus.REVIEW


def test_ungrounded_confirmed_condition_is_rejected() -> None:
    conditions = list(cp1_valid_analysis().confirmed_conditions)
    conditions[0] = conditions[0].model_copy(
        update={"source_text": "요청과 SRS에 없는 자동 복원 정책"}
    )
    analysis = cp1_valid_analysis().model_copy(update={"confirmed_conditions": conditions})

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-007").status == CheckStatus.FAIL


def test_missing_acceptance_note_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": cp1_valid_analysis().confirmed_conditions[:1]}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-008").status == CheckStatus.FAIL


def test_missing_requested_out_of_scope_is_rejected() -> None:
    scoped_request = cp1_request().model_copy(update={"out_of_scope": ["화씨 표시 정책"]})
    analysis = cp1_valid_analysis().model_copy(update={"excluded_scope": []})

    result = evaluate_checkpoint1(scoped_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL


def test_redundant_reconfirmation_requires_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["변경 정책을 다시 확인해야 함"],
            "user_questions": [
                "AUTO 모드의 설정 범위를 18~30°C로 변경하는 것으로 확정할 수 있습니까?"
            ],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert cp1_check(result, "CP1-010").status == CheckStatus.REVIEW


def test_legitimate_missing_detail_question_passes_checkpoint() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["기존 저장 데이터의 적용 시점이 요청에 없음"],
            "user_questions": ["기존에 저장된 장비에도 즉시 소급 적용합니까?"],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert cp1_check(result, "CP1-010").status == CheckStatus.PASS


def test_proceed_with_open_question_requires_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["경계값 적용 시점이 불명확함"],
            "user_questions": ["기존 저장값에도 즉시 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert cp1_check(result, "CP1-010").status == CheckStatus.REVIEW

# Agent 2
from pathlib import Path
from types import SimpleNamespace

import pytest

from qa_pipeline_v2 import Agent2Error, OpenAIAgent2, AGENT2_SYSTEM_INSTRUCTIONS
from qa_pipeline_v2 import (
    Agent1Analysis,
    Agent2TestDesign,
    AnalysisDecision,
    ConfirmedCondition,
    ConditionSource,
    ExpectedResult,
    ObservationLayer,
    ProductTestCaseCandidate,
    RequirementEffect,
    RequirementRelation,
    TcPurpose,
    TcType,
)


def agent2_design() -> Agent2TestDesign:
    return Agent2TestDesign(
        request_id="CR-TEST-001",
        test_cases=[
            ProductTestCaseCandidate(
                tc_id="TC-CAND-001",
                title="AUTO 모드 하한 차단 검증",
                purpose=TcPurpose.CHANGE_VALIDATION,
                test_type=TcType.BOUNDARY,
                requirement_ids=[
                    "REQ-TEMP-001",
                    "REQ-STATE-001",
                    "REQ-NOTIFY-001",
                ],
                source_condition_ids=["COND-001", "COND-002", "COND-003"],
                preconditions=["대상 장비가 AUTO 모드이고 설정 온도가 18°C다."],
                steps=["설정 온도를 18°C 미만으로 변경 요청한다."],
                expected_results=[
                    ExpectedResult(
                        result_id="ER-001",
                        statement="화면의 설정 온도가 기존 값을 유지한다.",
                        observation_layer=ObservationLayer.UI,
                        source_condition_ids=["COND-001", "COND-002"],
                    ),
                    ExpectedResult(
                        result_id="ER-002",
                        statement="내부 설정 온도가 기존 값을 유지한다.",
                        observation_layer=ObservationLayer.INTERNAL_STATE,
                        source_condition_ids=["COND-002"],
                    ),
                    ExpectedResult(
                        result_id="ER-003",
                        statement="차단 안내 Toast가 표시된다.",
                        observation_layer=ObservationLayer.NOTIFICATION,
                        source_condition_ids=["COND-003"],
                    ),
                ],
                restore_steps=["대상 장비의 실행 전 상태를 복원한다."],
                automation_candidate=True,
                automation_reason="화면과 내부 상태를 모두 조회할 수 있다.",
            )
        ],
        coverage_summary="확정 조건 3개를 한 개의 경계값 TC로 연결했다.",
    )


class Agent2FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(
            id="resp_agent2",
            output_parsed=agent2_design(),
            usage=SimpleNamespace(input_tokens=200, output_tokens=100, total_tokens=300),
        )


def test_agent2_uses_structured_responses_api() -> None:
    responses = Agent2FakeResponses()
    agent = OpenAIAgent2(
        model="gpt-5.6-terra",
        client=SimpleNamespace(responses=responses),
    )
    analysis = Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        change_summary="AUTO 모드 하한 변경",
        before_condition="16~30°C",
        after_condition="18~30°C",
        confirmed_conditions=[
            ConfirmedCondition(
                condition_id="COND-001",
                statement="18°C 미만 요청은 차단한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="18°C 미만 요청은 차단한다.",
                requirement_ids=["REQ-TEMP-001"],
            )
        ],
        requirement_effects=[
            RequirementEffect(
                requirement_id="REQ-TEMP-001",
                relation=RequirementRelation.MODIFIED,
                reason="하한 변경",
            )
        ],
        decision=AnalysisDecision.PROCEED,
    )

    response = agent.design(analysis, {})

    assert response.response_id == "resp_agent2"
    assert response.usage["total_tokens"] == 300
    assert responses.kwargs["text_format"] is Agent2TestDesign
    assert responses.kwargs["store"] is False
    assert "제품 기능 테스트케이스 후보" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Playwright 코드" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 confirmed_condition" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "전체 test_cases를 완전한 결과로 반환" in Path("src/qa_pipeline_v2.py").read_text(encoding="utf-8")


def test_missing_api_key_fails_before_network(monkeypatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)

    with pytest.raises(Agent2Error, match="OPENAI_API_KEY"):
        OpenAIAgent2()

# Checkpoint 2
from qa_pipeline_v2 import evaluate_checkpoint2
from qa_pipeline_v2 import (
    Agent1Analysis,
    Agent2TestDesign,
    AnalysisDecision,
    CheckStatus,
    ConfirmedCondition,
    ConditionSource,
    ExpectedResult,
    ObservationLayer,
    ProductTestCaseCandidate,
    RequirementEffect,
    RequirementRelation,
    SrsRequirement,
    TcPurpose,
    TcType,
)


def cp2_analysis() -> Agent1Analysis:
    return Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        change_summary="AUTO 모드 하한 변경",
        before_condition="16~30°C",
        after_condition="18~30°C",
        confirmed_conditions=[
            ConfirmedCondition(
                condition_id="COND-001",
                statement="18°C 미만 요청을 차단한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="18°C 미만 요청을 차단한다.",
                requirement_ids=["REQ-TEMP-001"],
            ),
            ConfirmedCondition(
                condition_id="COND-002",
                statement="화면과 내부 온도가 기존 값을 유지한다.",
                source_type=ConditionSource.SRS,
                source_text="화면과 내부 설정 온도가 기존 값을 유지합니다.",
                requirement_ids=["REQ-STATE-001"],
            ),
            ConfirmedCondition(
                condition_id="COND-003",
                statement="차단 안내를 표시한다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="차단 안내 Toast를 표시한다.",
                requirement_ids=["REQ-NOTIFY-001"],
            ),
        ],
        requirement_effects=[
            RequirementEffect(
                requirement_id="REQ-TEMP-001",
                relation=RequirementRelation.MODIFIED,
                reason="하한 변경",
            ),
            RequirementEffect(
                requirement_id="REQ-STATE-001",
                relation=RequirementRelation.VERIFY,
                reason="상태 유지 확인",
            ),
            RequirementEffect(
                requirement_id="REQ-NOTIFY-001",
                relation=RequirementRelation.VERIFY,
                reason="차단 안내 확인",
            ),
        ],
        decision=AnalysisDecision.PROCEED,
    )


def cp2_requirements():
    return {
        item.requirement_id: item
        for item in [
            SrsRequirement(
                requirement_id="REQ-TEMP-001",
                statement="온도 범위",
                acceptance_criteria="범위 밖 차단",
            ),
            SrsRequirement(
                requirement_id="REQ-STATE-001",
                statement="상태 정합성",
                acceptance_criteria="화면과 내부 상태 일치",
            ),
            SrsRequirement(
                requirement_id="REQ-NOTIFY-001",
                statement="결과 안내",
                acceptance_criteria="Toast 표시",
            ),
        ]
    }


def cp2_valid_design() -> Agent2TestDesign:
    return Agent2TestDesign(
        request_id="CR-TEST-001",
        test_cases=[
            ProductTestCaseCandidate(
                tc_id="TC-CAND-001",
                title="AUTO 모드 하한 차단",
                purpose=TcPurpose.CHANGE_VALIDATION,
                test_type=TcType.BOUNDARY,
                requirement_ids=[
                    "REQ-TEMP-001",
                    "REQ-STATE-001",
                    "REQ-NOTIFY-001",
                ],
                source_condition_ids=["COND-001", "COND-002", "COND-003"],
                preconditions=["AUTO 모드이고 설정 온도가 18°C다."],
                steps=["18°C 미만 온도를 요청한다."],
                expected_results=[
                    ExpectedResult(
                        result_id="ER-001",
                        statement="화면 온도가 기존 값을 유지한다.",
                        observation_layer=ObservationLayer.UI,
                        source_condition_ids=["COND-001", "COND-002"],
                    ),
                    ExpectedResult(
                        result_id="ER-002",
                        statement="내부 온도가 기존 값을 유지한다.",
                        observation_layer=ObservationLayer.INTERNAL_STATE,
                        source_condition_ids=["COND-002"],
                    ),
                    ExpectedResult(
                        result_id="ER-003",
                        statement="차단 안내가 표시된다.",
                        observation_layer=ObservationLayer.NOTIFICATION,
                        source_condition_ids=["COND-003"],
                    ),
                ],
                restore_steps=["실행 전 온도로 복원한다."],
                automation_candidate=True,
                automation_reason="UI와 내부 상태를 조회할 수 있다.",
            )
        ],
        coverage_summary="확정 조건 3개를 반영했다.",
    )


def cp2_check(result, rule_id: str):
    return next(item for item in result.checks if item.rule_id == rule_id)


def test_valid_design_passes_checkpoint2() -> None:
    result = evaluate_checkpoint2(cp2_analysis(), cp2_valid_design(), cp2_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 9
    assert all(item.status == CheckStatus.PASS for item in result.checks)


def test_missing_condition_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"source_condition_ids": ["COND-001", "COND-002"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-004").status == CheckStatus.FAIL


def test_missing_internal_state_assertion_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0]
    expected = [
        item
        for item in tc.expected_results
        if item.observation_layer != ObservationLayer.INTERNAL_STATE
    ]
    design = cp2_valid_design().model_copy(
        update={"test_cases": [tc.model_copy(update={"expected_results": expected})]}
    )

    result = evaluate_checkpoint2(cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL


def test_state_consistency_type_without_internal_state_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "requirement_ids": ["REQ-TEMP-001"],
            "source_condition_ids": ["COND-001"],
            "test_type": TcType.STATE_CONSISTENCY,
            "expected_results": [
                ExpectedResult(
                    result_id="ER-001",
                    statement="화면에서 요청이 차단된다.",
                    observation_layer=ObservationLayer.UI,
                    source_condition_ids=["COND-001"],
                )
            ],
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL


def test_playwright_code_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"steps": ["page.locator('#temperature').click()"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-009").status == CheckStatus.FAIL
