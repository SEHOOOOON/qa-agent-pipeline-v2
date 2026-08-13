# Product SRS parser
import json
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
    assert "MODIFIED, UPDATE_REQUIRED 또는 VERIFY로 분류한 모든 Requirement" in instructions
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
    HandoffStatus,
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
            ConfirmedCondition(
                condition_id="COND-005",
                statement="AUTO 모드의 변경 후 설정 범위는 18~30°C다.",
                source_type=ConditionSource.CHANGE_REQUEST,
                source_text="AUTO 모드는 18~30°C",
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


def test_missing_change_request_range_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "confirmed_conditions": [
                item
                for item in cp1_valid_analysis().confirmed_conditions
                if item.condition_id != "COND-005"
            ]
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-008").status == CheckStatus.FAIL
    assert "18~30°C" in cp1_check(result, "CP1-008").message

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
    assert cp1_request().acceptance_notes[-1] in cp1_check(result, "CP1-008").message


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
    assert result.handoff_status == HandoffStatus.PAUSE
    assert cp1_check(result, "CP1-010").status == CheckStatus.PASS


def test_partial_proceed_pauses_agent2_handoff() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"decision": AnalysisDecision.PARTIAL_PROCEED}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.PAUSE


def test_blocked_decision_blocks_agent2_handoff() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"decision": AnalysisDecision.BLOCKED}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.BLOCKED


def test_related_requirement_can_be_marked_update_required() -> None:
    requirements = cp1_requirements()
    local = requirements["REQ-LOCAL-002"]
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement=local.statement,
            source_type=ConditionSource.SRS,
            source_text=local.statement,
            requirement_ids=["REQ-LOCAL-002"],
        ),
    ]
    effects = [
        item.model_copy(update={"relation": RequirementRelation.UPDATE_REQUIRED})
        if item.requirement_id == "REQ-LOCAL-002"
        else item
        for item in cp1_valid_analysis().requirement_effects
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, requirements)

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE

def test_proceed_with_open_question_requires_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["경계값 적용 시점이 불명확함"],
            "user_questions": ["기존 저장값에도 즉시 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.PAUSE
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
    ControlPath,
    ExpectedResult,
    ObservationLayer,
    ProductTestCaseCandidate,
    RequirementEffect,
    RequirementRelation,
    TcPurpose,
    TcType,
    TestData as StructuredTestData,
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
                control_path=ControlPath.LOCAL,
                target_role="PRIMARY_TEST_DEVICE",
                test_data=StructuredTestData(
                    initial_mode="AUTO",
                    requested_mode="AUTO",
                    initial_temperature_c=18,
                    requested_temperature_c=17,
                ),
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
                restore_required=False,
                restore_steps=[],
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

    response = agent.design(cp1_request(), analysis, {})

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
    ControlPath,
    ExpectedResult,
    ObservationLayer,
    ProductTestCaseCandidate,
    RequirementEffect,
    RequirementRelation,
    SrsRequirement,
    TcPurpose,
    TcType,
    TestData as StructuredTestData,
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
                control_path=ControlPath.LOCAL,
                target_role="PRIMARY_TEST_DEVICE",
                test_data=StructuredTestData(
                    initial_mode="AUTO",
                    requested_mode="AUTO",
                    initial_temperature_c=18,
                    requested_temperature_c=17,
                ),
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
                restore_required=False,
                restore_steps=[],
                automation_candidate=True,
                automation_reason="UI와 내부 상태를 조회할 수 있다.",
            )
        ],
        coverage_summary="확정 조건 3개를 반영했다.",
    )


def cp2_check(result, rule_id: str):
    return next(item for item in result.checks if item.rule_id == rule_id)


def test_valid_design_passes_checkpoint2() -> None:
    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), cp2_valid_design(), cp2_requirements())

    assert result.status == CheckStatus.PASS
    assert len(result.checks) == 11
    assert all(item.status == CheckStatus.PASS for item in result.checks)


def test_human_review_note_pauses_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"human_review_notes": ["기획 확인이 필요한 의미 범위"]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.REVIEW
    assert cp2_check(result, "CP2-011").status == CheckStatus.REVIEW


def test_coverage_note_does_not_pause_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"coverage_notes": ["정확한 Toast 문구는 정의되지 않아 표시 여부만 검증한다."]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-011").status == CheckStatus.PASS
    assert "차단 없는 참고 사항 1건" in cp2_check(result, "CP2-011").message

def test_control_requirement_cannot_use_local_path() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 제어 명령을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 제어 명령을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="중앙 제어 경로 회귀 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 제어 명령을 적용한다.",
            acceptance_criteria="선택 장비에 일괄 적용한다.",
        ),
    }
    tc = cp2_valid_design().test_cases[0]
    expected_results = [
        item.model_copy(
            update={
                "source_condition_ids": [*item.source_condition_ids, "COND-004"]
            }
        )
        for item in tc.expected_results
    ]
    mismatched = tc.model_copy(
        update={
            "requirement_ids": [*tc.requirement_ids, "REQ-CONTROL-001"],
            "source_condition_ids": [*tc.source_condition_ids, "COND-004"],
            "expected_results": expected_results,
            "control_path": ControlPath.LOCAL,
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [mismatched]})

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-008").status == CheckStatus.FAIL


def test_active_central_path_requires_direct_change_validation() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 변경 정책을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 변경 정책을 적용한다.",
        requirement_ids=["REQ-CONTROL-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [*cp2_analysis().confirmed_conditions, condition],
            "requirement_effects": [
                *cp2_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-CONTROL-001",
                    relation=RequirementRelation.VERIFY,
                    reason="중앙 경로에서도 변경 정책 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 변경 정책을 적용한다.",
            acceptance_criteria="선택 장비에 일괄 적용한다.",
        ),
    }
    central_regression = ProductTestCaseCandidate(
        tc_id="TC-CAND-002",
        title="중앙 관제 패널 기존 적용 회귀",
        purpose=TcPurpose.RELATED_REGRESSION,
        test_type=TcType.NORMAL,
        requirement_ids=["REQ-CONTROL-001"],
        source_condition_ids=["COND-004"],
        control_path=ControlPath.CENTRAL,
        target_role="SELECTED_ALLOWED_TEST_DEVICE_SET",
        test_data=StructuredTestData(
            initial_mode="COOL",
            requested_mode="AUTO",
            initial_temperature_c=19,
            requested_temperature_c=18,
        ),
        preconditions=["선택 장비가 제어 허용 상태다."],
        steps=["관제 패널에서 변경 값을 일괄 적용한다."],
        expected_results=[
            ExpectedResult(
                result_id="ER-004",
                statement="선택 장비에 요청 값이 적용된다.",
                observation_layer=ObservationLayer.UI,
                source_condition_ids=["COND-004"],
            )
        ],
        restore_required=True,
        restore_steps=["선택 장비의 기존 값을 복구한다."],
        automation_candidate=True,
        automation_reason="관제 패널과 대상 상태를 조회할 수 있다.",
    )
    design = cp2_valid_design().model_copy(
        update={"test_cases": [*cp2_valid_design().test_cases, central_regression]}
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-008").status == CheckStatus.FAIL
    assert "CENTRAL 경로의 직접 변경 검증 TC 누락" in cp2_check(result, "CP2-008").message

def test_structured_test_data_is_required_for_boundary_tc() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"test_data": StructuredTestData()}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-010").status == CheckStatus.FAIL

def test_missing_condition_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"source_condition_ids": ["COND-001", "COND-002"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

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

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

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

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL


def test_playwright_code_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"steps": ["page.locator('#temperature').click()"]}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-009").status == CheckStatus.FAIL

# Run integrity
from qa_pipeline_v2 import (
    _load_verified_agent1_run,
    _sha256_file,
    _write_json,
    _write_text_atomic,
)


def build_verified_agent1_run(tmp_path: Path) -> tuple[Path, str]:
    run_id = "RUN-20260813-120000-ABC123"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    request = cp1_request()
    analysis = cp1_valid_analysis()
    requirements = cp1_requirements()
    checkpoint = evaluate_checkpoint1(request, analysis, requirements)
    request_file = run_dir / "request.json"
    srs_file = run_dir / "srs_snapshot.md"
    analysis_file = run_dir / "agent1_change_analysis.json"
    checkpoint_file = run_dir / "checkpoint1.json"
    _write_json(request_file, request.model_dump(mode="json"))
    _write_text_atomic(
        srs_file,
        (REPO_ROOT / "docs" / "01_PRODUCT_SRS.md").read_text(encoding="utf-8"),
    )
    _write_json(analysis_file, analysis.model_dump(mode="json"))
    _write_json(checkpoint_file, checkpoint.model_dump(mode="json"))
    _write_json(
        run_dir / "run_manifest.json",
        {
            "run_id": run_id,
            "stage": "AGENT_1_CP1",
            "status": checkpoint.status.value,
            "handoff_status": checkpoint.handoff_status.value,
            "request_sha256": _sha256_file(request_file),
            "srs_sha256": _sha256_file(srs_file),
            "agent1_analysis_sha256": _sha256_file(analysis_file),
            "checkpoint1_sha256": _sha256_file(checkpoint_file),
        },
    )
    return run_dir, run_id


def test_verified_agent1_run_can_handoff_to_agent2(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)

    request, _, analysis, checkpoint, _ = _load_verified_agent1_run(run_dir, run_id)

    assert request.request_id == analysis.request_id
    assert checkpoint.handoff_status == HandoffStatus.CONTINUE


def test_modified_agent1_artifact_is_blocked_before_agent2(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)
    analysis_file = run_dir / "agent1_change_analysis.json"
    analysis_file.write_text(
        analysis_file.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Agent 1 분석 파일이"):
        _load_verified_agent1_run(run_dir, run_id)


def test_paused_manifest_is_blocked_before_agent2(tmp_path: Path) -> None:
    run_dir, run_id = build_verified_agent1_run(tmp_path)
    manifest_file = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["handoff_status"] = HandoffStatus.PAUSE.value
    _write_json(manifest_file, manifest)

    with pytest.raises(ValueError, match="인계 상태"):
        _load_verified_agent1_run(run_dir, run_id)
# CLI integration without external API
import qa_pipeline_v2 as pipeline


def test_agent1_to_agent2_cli_handoff_with_frozen_inputs(
    tmp_path: Path, monkeypatch
) -> None:
    request_file = tmp_path / "request.json"
    _write_json(request_file, cp1_request().model_dump(mode="json"))

    class FakeAgent1:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent1"

        def analyze(self, request, requirements, **kwargs):
            return pipeline.Agent1Response(
                analysis=cp1_valid_analysis(),
                response_id="not-persisted",
                model=self.model,
                usage={"input_tokens": 10, "output_tokens": 5, "total_tokens": 15},
            )

    class FakeAgent2:
        def __init__(self, *, model=None) -> None:
            self.model = model or "fake-agent2"

        def design(self, request, analysis, requirements, **kwargs):
            tc = ProductTestCaseCandidate(
                tc_id="TC-CAND-001",
                title="AUTO 모드 변경 범위 확인",
                purpose=TcPurpose.CHANGE_VALIDATION,
                test_type=TcType.BOUNDARY,
                requirement_ids=["REQ-TEMP-001"],
                source_condition_ids=["COND-001", "COND-002", "COND-003", "COND-005"],
                control_path=ControlPath.NOT_APPLICABLE,
                target_role="PRIMARY_TEST_DEVICE",
                test_data=StructuredTestData(
                    initial_mode="AUTO",
                    requested_mode="AUTO",
                    initial_temperature_c=18,
                    requested_temperature_c=17,
                ),
                preconditions=["대상 장비가 AUTO 모드다."],
                steps=["변경된 하한 경계값을 요청한다."],
                expected_results=[
                    ExpectedResult(


                        result_id="ER-001",
                        statement="요청 결과가 변경 조건과 일치한다.",
                        observation_layer=ObservationLayer.UI,
                        source_condition_ids=["COND-001", "COND-002", "COND-003", "COND-005"],
                    )
                ],
                restore_required=False,
                restore_steps=[],
                automation_candidate=True,
                automation_reason="화면에서 요청 결과를 확인할 수 있다.",
            )
            return pipeline.Agent2Response(
                design=Agent2TestDesign(
                    request_id=request.request_id,
                    test_cases=[tc],
                    coverage_summary="확정 조건을 변경 검증 TC에 연결했다.",
                ),
                response_id="not-persisted",
                model=self.model,
                usage={"input_tokens": 20, "output_tokens": 10, "total_tokens": 30},
            )

    monkeypatch.setattr(pipeline, "OpenAIAgent1", FakeAgent1)
    monkeypatch.setattr(pipeline, "OpenAIAgent2", FakeAgent2)
    runs_root = tmp_path / "runs"
    agent1_args = SimpleNamespace(
        request=str(request_file),
        srs=str(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"),
        runs_root=str(runs_root),
        model=None,
    )

    assert pipeline.run_agent1(agent1_args) == 0
    run_dir = next(path for path in runs_root.iterdir() if path.is_dir())
    agent2_args = SimpleNamespace(
        run_id=run_dir.name,
        runs_root=str(runs_root),
        model=None,
    )

    assert pipeline.run_agent2(agent2_args) == 0
    assert (run_dir / "srs_snapshot.md").is_file()
    assert (run_dir / "agent2_test_design.json").is_file()
    manifest = json.loads((run_dir / "agent2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == CheckStatus.PASS.value
    assert manifest["request_sha256"] == _sha256_file(run_dir / "request.json")
    assert manifest["srs_sha256"] == _sha256_file(run_dir / "srs_snapshot.md")

# Agent 3
from qa_pipeline_v2 import (
    Agent3AutomationPlan,
    AssertionStrategy,
    AutomationAction,
    AutomationActionType,
    AutomationAssertion,
    AutomationPhase,
    CheckStatus,
    ObservedUiElement,
    OpenAIAgent3,
    ProductTestCaseCandidate,
    TrialOutcome,
    UiObservation,
    compile_automation_candidate,
    build_agent3_model_input,
    evaluate_checkpoint3_plan,
    evaluate_compiled_candidate,
    inspect_target_ui,
    run_candidate_trial,
)


def agent3_test_case() -> ProductTestCaseCandidate:
    return ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-003",
            "title": "Block AUTO temperature below lower bound",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "BOUNDARY",
            "requirement_ids": ["REQ-TEMP-001"],
            "source_condition_ids": ["COND-001"],
            "control_path": "CENTRAL",
            "target_role": "CENTRAL_COMMAND_ALLOWED_ROLE",
            "test_data": {
                "initial_mode": "AUTO",
                "requested_mode": None,
                "initial_temperature_c": 18.0,
                "requested_temperature_c": 17.0,
            },
            "preconditions": ["Select an allowed device at AUTO 18 degrees."],
            "steps": ["Request 17 degrees and apply the pending command."],
            "expected_results": [
                {"result_id": "ER-005", "statement": "UI remains at 18 degrees.", "observation_layer": "UI", "source_condition_ids": ["COND-001"]},
                {"result_id": "ER-006", "statement": "Internal setTemp remains at 18 degrees.", "observation_layer": "INTERNAL_STATE", "source_condition_ids": ["COND-001"]},
                {"result_id": "ER-007", "statement": "A blocking Toast is visible.", "observation_layer": "NOTIFICATION", "source_condition_ids": ["COND-001"]},
            ],
            "restore_required": False,
            "restore_steps": [],
            "automation_candidate": True,
            "automation_reason": "The local UI and internal state are observable.",
        }
    )


def agent3_observation() -> UiObservation:
    selectors = [
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
    ]
    return UiObservation(
        target_file="virtual-controller.html",
        target_sha256="a" * 64,
        page_title="Virtual Controller",
        elements=[ObservedUiElement(selector=item, tag="button", text="", visible=True, enabled=True, action_hint="observed") for item in selectors],
        harness_keys=["devices", "pendingState", "selectedUnitId", "selectUnit", "applyPanelCommands"],
        observed_at="2026-08-13T00:00:00+00:00",
    )


def agent3_plan() -> Agent3AutomationPlan:
    return Agent3AutomationPlan(
        tc_id="TC-CAND-003",
        target_device_id=1,
        summary="Prepare AUTO 18, request 17, then verify blocking evidence.",
        actions=[
            AutomationAction(action_id="ACT-001", phase="PRECONDITION", action_type="SELECT_DEVICE", selector="#device-card-1 .card-body-split", value=1, source_text="Select target"),
            AutomationAction(action_id="ACT-002", phase="PRECONDITION", action_type="SET_MODE", selector="#det-mode-auto", value="AUTO", source_text="Prepare AUTO"),
            AutomationAction(action_id="ACT-003", phase="PRECONDITION", action_type="SET_TEMPERATURE", selector="#det-temp-display", value=18.0, source_text="Prepare 18"),
            AutomationAction(action_id="ACT-004", phase="PRECONDITION", action_type="APPLY_COMMANDS", selector=".btn-apply-cmd", source_text="Apply initial state"),
            AutomationAction(action_id="ACT-005", phase="TEST", action_type="SET_TEMPERATURE", selector="#det-temp-display", value=17.0, source_text="Request 17"),
            AutomationAction(action_id="ACT-006", phase="TEST", action_type="APPLY_COMMANDS", selector=".btn-apply-cmd", source_text="Apply request"),
        ],
        assertions=[
            AutomationAssertion(result_id="ER-005", observation_layer="UI", strategy="UI_TEMPERATURE", selector="#det-temp-display", expected_number=18.0),
            AutomationAssertion(result_id="ER-006", observation_layer="INTERNAL_STATE", strategy="INTERNAL_SET_TEMP", selector="window.__vccs.devices", expected_number=18.0),
            AutomationAssertion(result_id="ER-007", observation_layer="NOTIFICATION", strategy="TOAST_VISIBLE", selector="#global-toast"),
        ],
    )


class Agent3FakeResponses:
    def __init__(self) -> None:
        self.kwargs = None

    def parse(self, **kwargs):
        self.kwargs = kwargs
        return SimpleNamespace(id="resp_agent3", output_parsed=agent3_plan(), usage=SimpleNamespace(input_tokens=50, output_tokens=30, total_tokens=80))


def test_agent3_uses_structured_plan_api() -> None:
    responses = Agent3FakeResponses()
    result = OpenAIAgent3(model="test-model", client=SimpleNamespace(responses=responses)).plan(
        agent3_test_case(), agent3_observation(), {"REQ-TEMP-001": SrsRequirement(requirement_id="REQ-TEMP-001", statement="range", acceptance_criteria="block")}
    )
    assert result.plan.tc_id == "TC-CAND-003"
    assert responses.kwargs["text_format"] is Agent3AutomationPlan
    assert responses.kwargs["store"] is False


def test_agent3_model_input_preview_is_minimal_and_has_no_local_path() -> None:
    requirements = {
        "REQ-TEMP-001": SrsRequirement(requirement_id="REQ-TEMP-001", statement="range", acceptance_criteria="block"),
        "REQ-UNRELATED-001": SrsRequirement(requirement_id="REQ-UNRELATED-001", statement="unrelated", acceptance_criteria="none"),
    }
    payload = build_agent3_model_input(agent3_test_case(), agent3_observation(), requirements)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["destination"] == "OpenAI Responses API"
    assert payload["store"] is False
    assert set(payload["related_srs_requirements"]) == {"REQ-TEMP-001"}
    assert payload["ui_observation"]["target_file"] == "virtual-controller.html"
    assert "C:\\" not in serialized
    assert "<!doctype html" not in serialized


def test_valid_agent3_plan_passes_cp3_and_compiles() -> None:
    tc = agent3_test_case()
    plan = agent3_plan()
    checkpoint = evaluate_checkpoint3_plan(tc, plan, agent3_observation())
    assert checkpoint.status == CheckStatus.PASS
    code = compile_automation_candidate("RUN-20260813-120000-ABCDEF", tc, plan)
    checks = evaluate_compiled_candidate(tc, code)
    assert all(item.status == CheckStatus.PASS for item in checks)
    assert "# EXPECTED_RESULT: ER-007" in code
    assert "PRODUCT_MISMATCH:" in code

def test_blocked_temperature_request_compiles_until_target_or_stall() -> None:
    code = compile_automation_candidate(
        "RUN-20260813-120000-ABCDEF", agent3_test_case(), agent3_plan()
    )
    assert "def _request_temperature(page, target):" in code
    assert "if after == before:" in code
    assert "_request_temperature(page, 17.0)" in code



def test_unobserved_selector_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["actions"][0]["selector"] = "#invented-selector"
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-002" and item.status == CheckStatus.FAIL for item in checkpoint.checks)

def test_observed_but_wrong_action_selector_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["actions"][1]["selector"] = "#det-mode-cool"
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-002" and item.status == CheckStatus.FAIL for item in checkpoint.checks)


def test_ungrounded_numeric_expectation_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][0]["expected_number"] = 19.0
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-004" and item.status == CheckStatus.FAIL for item in checkpoint.checks)
    assert any(item.rule_id == "CP3-005" and item.status == CheckStatus.FAIL for item in checkpoint.checks)



def test_missing_expected_result_mapping_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"] = payload["assertions"][:-1]
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-003" and item.status == CheckStatus.FAIL for item in checkpoint.checks)


def test_agent3_trial_distinguishes_product_mismatch(tmp_path: Path) -> None:
    target = tmp_path / "virtual-controller.html"
    target.write_text(
        """<!doctype html><title>Virtual Controller</title>
<div id='device-card-1'><button class='card-body-split' onclick='selectUnit(1)'>device</button></div>
<button id='det-mode-cool'></button><button id='det-mode-heat'></button><button id='det-mode-fan'></button><button id='det-mode-dry'></button>
<button id='det-mode-auto' onclick=\"pendingState.mode='AUTO'\"></button>
<div id='det-temp-adjust-card'><span id='det-temp-display'>24.0 C</span></div>
<button id='det-temp-down-btn' onclick='adjust(-1)'>-</button><button id='det-temp-up-btn' onclick='adjust(1)'>+</button>
<button class='btn-apply-cmd' onclick='applyPanelCommands()'>apply</button><div id='global-toast' class='toast-box'>warning</div>
<script>
let devices=[{id:1,setTemp:24,mode:'COOL'}]; let pendingState={setTemp:24,mode:'COOL'}; let selectedUnitId=null;
function draw(){document.getElementById('det-temp-display').innerText=pendingState.setTemp.toFixed(1)+' C'}
function selectUnit(id){selectedUnitId=id; pendingState={...devices[0]}; draw()}
function adjust(v){pendingState.setTemp+=v; draw()}
function applyPanelCommands(){devices[0].setTemp=pendingState.setTemp; devices[0].mode=pendingState.mode}
window.__vccs={get devices(){return devices},get pendingState(){return pendingState},get selectedUnitId(){return selectedUnitId},selectUnit,applyPanelCommands,renderGrid(){},saveStateToLocalStorage(){}};
</script>""",
        encoding="utf-8",
    )
    observation = inspect_target_ui(target)
    assert observation.page_title == "Virtual Controller"
    candidate = tmp_path / "candidate.py"
    candidate.write_text(compile_automation_candidate("RUN-20260813-120000-ABCDEF", agent3_test_case(), agent3_plan()), encoding="utf-8")
    trial = run_candidate_trial(candidate, target, tmp_path / "evidence", timeout_seconds=20)
    assert trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
    assert trial.evidence_complete is True


def test_agent3_trial_strips_secrets_and_redacts_local_paths(tmp_path: Path, monkeypatch) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def test_candidate():\n    assert False\n", encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    captured_env = {}

    def fake_run(*args, **kwargs):
        captured_env.update(kwargs["env"])
        local_path = str(target.resolve())
        temp_path = str(Path(kwargs["cwd"]).resolve())
        return SimpleNamespace(returncode=1, stdout=f"{local_path}\n{temp_path}", stderr="")

    for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "must-not-reach-trial")
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    evidence_dir = tmp_path / "evidence"
    result = run_candidate_trial(candidate, target, evidence_dir, timeout_seconds=5)

    assert result.outcome == TrialOutcome.AUTOMATION_ERROR
    assert all(name not in captured_env for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"))
    allowed = set(pipeline._AGENT3_TRIAL_ENV_ALLOWLIST) | {"QA_TARGET_URL", "QA_EVIDENCE_DIR"}
    assert set(captured_env) <= allowed
    stdout = (evidence_dir / "trial-stdout.txt").read_text(encoding="utf-8")
    assert str(target.resolve()) not in stdout
    assert "<LOCAL_PATH>" in stdout


def test_modified_agent2_artifact_is_blocked_before_agent3(tmp_path: Path) -> None:
    import shutil

    source = REPO_ROOT / "examples" / "results" / "agent1-agent2-auto-temperature"
    run_id = "RUN-20260813-125229-31EB5F"
    run_dir = tmp_path / run_id
    shutil.copytree(source, run_dir)
    design_file = run_dir / "agent2_test_design.json"
    design_file.write_text(design_file.read_text(encoding="utf-8") + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="Agent 2 design"):
        pipeline._load_verified_agent2_run(run_dir, run_id)
