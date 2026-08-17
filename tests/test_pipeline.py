# Product SRS parser
import json
import zipfile
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


def test_agent1_missing_api_key_fails_before_network(monkeypatch) -> None:
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
    assert "target_role=PRIMARY_TEST_DEVICE" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "전체 test_cases를 완전한 결과로 반환" in Path("src/qa_pipeline_v2.py").read_text(encoding="utf-8")

    agent.design(
        cp1_request(),
        analysis,
        {},
        previous_design=agent2_design(),
        checkpoint_feedback=[
            "CP2-001 PASS: 요청 ID 일치",
            "CP2-002 FAIL: 중복 ID",
        ],
    )
    rework_input = responses.kwargs["input"][1]["content"]
    assert "Checkpoint 2 전체 판정" in rework_input
    assert "CP2-001 PASS" in rework_input
    assert "PASS인 규칙과 그 근거를 보존" in rework_input


def test_agent2_missing_api_key_fails_before_network(monkeypatch) -> None:
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


def test_boundary_tc_with_initial_mode_requires_requested_mode_for_agent3() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "test_data": StructuredTestData(
                initial_mode="AUTO",
                requested_mode=None,
                initial_temperature_c=18,
                requested_temperature_c=17,
            )
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

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
    assert (run_dir / "agent2_in_progress.json").exists() is False
    manifest = json.loads((run_dir / "agent2_manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == CheckStatus.PASS.value
    assert manifest["request_sha256"] == _sha256_file(run_dir / "request.json")
    assert manifest["srs_sha256"] == _sha256_file(run_dir / "srs_snapshot.md")


def test_agent2_rejects_an_active_run_reservation(tmp_path: Path) -> None:
    run_id = "RUN-20260817-040000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    (run_dir / "agent2_in_progress.json").write_text("{}\n", encoding="utf-8")

    with pytest.raises(ValueError, match="진행 표시가 이미 존재"):
        pipeline.run_agent2(
            SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"), model=None)
        )


# Agent 3
from qa_pipeline_v2 import (
    Agent3AutomationPlan,
    Agent3EligibilityStatus,
    AssertionStrategy,
    AutomationAction,
    AutomationActionType,
    AutomationAssertion,
    AutomationCandidateStatus,
    AutomationPhase,
    CheckStatus,
    ObservedUiElement,
    OpenAIAgent3,
    ProductTestCaseCandidate,
    TrialOutcome,
    UiObservation,
    compile_automation_candidate,
    build_agent3_model_input,
    evaluate_agent3_eligibility,
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


def generic_new_control_test_case() -> ProductTestCaseCandidate:
    """Feature-neutral fixture for a newly added control point."""
    return ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-090",
            "title": "Enable a newly added control and verify state",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "STATE_CONSISTENCY",
            "requirement_ids": ["REQ-NEW-001", "REQ-STATE-002"],
            "source_condition_ids": ["COND-090"],
            "control_path": "CENTRAL",
            "target_role": "NEW_CONTROL_POINT",
            "test_data": {},
            "preconditions": ["새 제어 스위치는 꺼짐 상태다."],
            "steps": ["새 제어 스위치를 켠다."],
            "expected_results": [
                {
                    "result_id": "ER-090",
                    "statement": "새 제어 스위치는 켜짐 상태다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-090"],
                },
                {
                    "result_id": "ER-091",
                    "statement": "내부 enabled 값은 true다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-090"],
                },
            ],
            "restore_required": True,
            "restore_steps": ["새 제어 스위치를 끈다."],
            "automation_candidate": True,
            "automation_reason": "The new control is expected to expose UI and state evidence.",
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
        device_state_fields=["id", "mode", "setTemp"],
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
            AutomationAssertion(result_id="ER-007", observation_layer="NOTIFICATION", strategy="TOAST_BLOCKING", selector="#global-toast"),
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
    instructions = responses.kwargs["input"][0]["content"]
    assert "SET_TEMPERATURE=#det-temp-display" in instructions
    assert "Generic UI actions are CLICK, FILL, SELECT_OPTION, CHECK, and UNCHECK" in instructions
    assert "AUTOMATION_SUPPORT_EXTENSION_REQUIRED" in instructions
    assert "INTERNAL_SET_TEMP=window.__vccs.devices" in instructions
    assert "INTERNAL_DEVICE_FIELDS_EQUALS=window.__vccs.devices" in instructions
    assert "Do not append indexes, properties, or expressions" in instructions
    assert "If a SELECT_DEVICE action is actually needed" in instructions
    assert "does not need a legacy SELECT_DEVICE action" in instructions
    assert "UI_TEXT_CONTAINS may verify a short meaningful phrase" in instructions
    assert "do not use the entire natural-language Expected Result sentence" in instructions
    assert "TOAST_BLOCKING" in instructions
    assert "propertyNames" not in json.dumps(Agent3AutomationPlan.model_json_schema())


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


def test_agent3_eligibility_scopes_ui_inventory_to_selected_tc(tmp_path: Path) -> None:
    eligibility = evaluate_agent3_eligibility(agent3_test_case())
    assert eligibility.status == Agent3EligibilityStatus.ELIGIBLE
    assert eligibility.model_call_allowed is True
    assert "#det-mode-auto" in eligibility.required_selectors
    assert "#det-mode-dry" not in eligibility.required_selectors
    assert set(eligibility.required_harness_keys) == {"devices", "selectedUnitId"}
    assert "ASSERT_TOAST_BLOCKING" in eligibility.required_capabilities

    target = tmp_path / "target.html"
    target.write_text(
        """<!doctype html><title>Scoped Inventory</title>
<div id='device-card-1'><button class='card-body-split'>device</button></div>
<button id='det-mode-auto'>AUTO</button>
<span id='det-temp-display'>18 C</span>
<button id='det-temp-down-btn'>-</button><button id='det-temp-up-btn'>+</button>
<button class='btn-apply-cmd'>apply</button><div id='global-toast'>warning</div>
<script>window.__vccs={devices:[],selectedUnitId:null};</script>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors=set(eligibility.required_selectors),
        required_harness_keys=set(eligibility.required_harness_keys),
    )

    assert {item.selector for item in observation.elements} == set(
        eligibility.required_selectors
    )
    assert set(observation.harness_keys) == {"devices", "selectedUnitId"}
    assert observation.device_state_fields == []


def test_agent3_scoped_inventory_still_blocks_a_required_selector(tmp_path: Path) -> None:
    eligibility = evaluate_agent3_eligibility(agent3_test_case())
    target = tmp_path / "target.html"
    target.write_text(
        """<!doctype html><div id='device-card-1'><button class='card-body-split'>device</button></div>
<span id='det-temp-display'>18 C</span>
<button id='det-temp-down-btn'>-</button><button id='det-temp-up-btn'>+</button>
<button class='btn-apply-cmd'>apply</button><div id='global-toast'>warning</div>
<script>window.__vccs={devices:[],selectedUnitId:null};</script>""",
        encoding="utf-8",
    )

    with pytest.raises(pipeline.Agent3Error, match="#det-mode-auto"):
        inspect_target_ui(
            target,
            required_selectors=set(eligibility.required_selectors),
            required_harness_keys=set(eligibility.required_harness_keys),
        )


def test_agent3_inspection_waits_for_delayed_required_selector(tmp_path: Path) -> None:
    target = tmp_path / "delayed-controller.html"
    target.write_text(
        """<!doctype html><title>Delayed Controller</title><body><script>
setTimeout(() => document.body.insertAdjacentHTML('beforeend',
  '<button id="det-mode-auto">AUTO</button>'), 100);
</script></body>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors={"#det-mode-auto"},
        required_harness_keys=set(),
    )

    assert [item.selector for item in observation.elements] == ["#det-mode-auto"]


def test_agent3_unknown_internal_state_uses_generic_discovery() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["requirement_ids"].append("REQ-LOCK-001")
    payload["expected_results"][1]["statement"] = "Internal locked state remains true."

    eligibility = evaluate_agent3_eligibility(
        ProductTestCaseCandidate.model_validate(payload)
    )

    assert eligibility.status == Agent3EligibilityStatus.DISCOVERY_REQUIRED
    assert eligibility.candidate_status is None
    assert eligibility.model_call_allowed is True
    assert eligibility.generic_discovery_required is True
    assert "DISCOVER_INTERNAL_STATE" in eligibility.required_capabilities
    assert eligibility.missing_capabilities == []


def test_agent3_registered_device_fields_are_grounded_and_compiled() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["expected_results"][1]["statement"] = (
        "Internal mode is AUTO and setTemp remains at 18 degrees."
    )
    test_case = ProductTestCaseCandidate.model_validate(payload)
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"][1] = {
        "result_id": "ER-006",
        "observation_layer": "INTERNAL_STATE",
        "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
        "selector": "window.__vccs.devices",
        "expected_fields": [
            {"field_name": "mode", "expected_value": "AUTO"},
            {"field_name": "setTemp", "expected_value": 18},
        ],
    }
    plan = Agent3AutomationPlan.model_validate(plan_payload)

    eligibility = evaluate_agent3_eligibility(test_case)
    checkpoint = evaluate_checkpoint3_plan(test_case, plan, agent3_observation())
    code = compile_automation_candidate("RUN-20260817-FIELDS-ABCDEF", test_case, plan)

    assert "ASSERT_INTERNAL_DEVICE_FIELDS" in eligibility.required_capabilities
    assert checkpoint.status == CheckStatus.PASS
    assert "internal device fields={actual}" in code
    assert "Object.fromEntries(fields.map(field" in code


def test_agent3_rejects_unobserved_or_ungrounded_device_fields() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["expected_results"][1]["statement"] = "Internal setTemp remains at 18 degrees."
    test_case = ProductTestCaseCandidate.model_validate(payload)
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"][1] = {
        "result_id": "ER-006",
        "observation_layer": "INTERNAL_STATE",
        "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
        "selector": "window.__vccs.devices",
        "expected_fields": [
            {"field_name": "mode", "expected_value": "AUTO"},
            {"field_name": "unregistered", "expected_value": True},
        ],
    }
    checkpoint = evaluate_checkpoint3_plan(
        test_case, Agent3AutomationPlan.model_validate(plan_payload), agent3_observation()
    )

    cp3 = next(item for item in checkpoint.checks if item.rule_id == "CP3-004")
    assert checkpoint.status == CheckStatus.FAIL
    assert "field is not named in the Expected Result: mode" in cp3.message
    assert "field was not observed: unregistered" in cp3.message


def test_agent3_non_hvac_mode_values_use_generic_discovery() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["test_data"] = {
        "initial_mode": "STOP",
        "requested_mode": "OPERATION",
        "initial_temperature_c": None,
        "requested_temperature_c": None,
    }
    payload["expected_results"] = [
        {
            "result_id": "ER-005",
            "statement": "화면 상태가 OPERATION으로 변경된다.",
            "observation_layer": "UI",
            "source_condition_ids": ["COND-001"],
        },
        {
            "result_id": "ER-006",
            "statement": "내부 status가 OPERATION으로 변경된다.",
            "observation_layer": "INTERNAL_STATE",
            "source_condition_ids": ["COND-001"],
        },
    ]

    eligibility = evaluate_agent3_eligibility(
        ProductTestCaseCandidate.model_validate(payload)
    )

    assert eligibility.status == Agent3EligibilityStatus.DISCOVERY_REQUIRED
    assert eligibility.generic_discovery_required is True
    assert eligibility.required_selectors == []
    assert eligibility.required_harness_keys == []
    assert "DISCOVER_GENERIC_UI" in eligibility.required_capabilities
    assert "SET_MODE" not in eligibility.required_capabilities


def test_agent3_textual_link_tolerates_korean_particles() -> None:
    assert pipeline._has_textual_link("적용", "적용을 실행한다.")
    assert pipeline._has_textual_link(
        "window vccs primaryTestDevice status",
        "PRIMARY_TEST_DEVICE의 내부 status가 OPERATION으로 변경된다.",
    )
    assert not pipeline._has_textual_link("삭제 버튼", "적용을 실행한다.")


def test_agent3_notification_rejects_the_whole_expected_result_as_ui_text() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][2] = {
        "result_id": "ER-007",
        "observation_layer": "NOTIFICATION",
        "strategy": "UI_TEXT_CONTAINS",
        "selector": "#global-toast",
        "expected_text": "A blocking Toast is visible.",
    }

    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "not the whole Expected Result sentence" in item.message
        for item in checkpoint.checks
    )


def test_agent3_generic_discovery_compiles_and_runs_a_new_control(
    tmp_path: Path,
) -> None:
    test_case = generic_new_control_test_case()
    eligibility = evaluate_agent3_eligibility(test_case)
    assert eligibility.status == Agent3EligibilityStatus.DISCOVERY_REQUIRED
    assert eligibility.generic_discovery_required is True

    target = tmp_path / "new-control.html"
    target.write_text(
        """<!doctype html><html><head><title>New Control</title></head><body>
<label for="new-feature-toggle">새 제어</label>
<input id="new-feature-toggle" type="checkbox">
<span id="new-feature-status">꺼짐</span>
<script>
window.__vccs = {feature: {enabled: false}};
const toggle = document.getElementById('new-feature-toggle');
toggle.addEventListener('change', () => {
  window.__vccs.feature.enabled = toggle.checked;
  document.getElementById('new-feature-status').textContent = toggle.checked ? '켜짐' : '꺼짐';
});
</script></body></html>""",
        encoding="utf-8",
    )
    observation = inspect_target_ui(
        target,
        required_selectors=set(),
        required_harness_keys=set(),
        discover_generic=True,
    )
    elements = {item.selector: item for item in observation.elements}
    assert elements["#new-feature-toggle"].action_hint == "CHECK_OR_UNCHECK"
    assert observation.harness_values["window.__vccs.feature.enabled"] is False

    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": test_case.tc_id,
            "target_device_id": 1,
            "summary": "Use the newly observed generic switch and verify both layers.",
            "actions": [
                {
                    "action_id": "ACT-090",
                    "phase": "TEST",
                    "action_type": "CHECK",
                    "selector": "#new-feature-toggle",
                    "source_text": "새 제어 스위치를 켠다.",
                },
                {
                    "action_id": "ACT-091",
                    "phase": "RESTORE",
                    "action_type": "UNCHECK",
                    "selector": "#new-feature-toggle",
                    "source_text": "새 제어 스위치를 끈다.",
                },
            ],
            "assertions": [
                {
                    "result_id": "ER-090",
                    "observation_layer": "UI",
                    "strategy": "UI_CHECKED_EQUALS",
                    "selector": "#new-feature-toggle",
                    "expected_value": True,
                },
                {
                    "result_id": "ER-091",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_VALUE_EQUALS",
                    "selector": "window.__vccs.feature.enabled",
                    "expected_value": True,
                },
            ],
        }
    )
    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)
    assert checkpoint.status == CheckStatus.PASS

    code = compile_automation_candidate("RUN-20260816-NEW001-ABCDEF", test_case, plan)
    assert "restore_baseline_0" in code
    assert "restore_control_checked" in code
    assert all(
        item.status == CheckStatus.PASS
        for item in evaluate_compiled_candidate(test_case, code)
    )
    candidate = tmp_path / "test_new_control.py"
    candidate.write_text(code, encoding="utf-8")
    trial = run_candidate_trial(
        candidate,
        target,
        tmp_path / "new-control-evidence",
        timeout_seconds=30,
    )
    assert trial.outcome == TrialOutcome.PASS


def test_agent3_records_support_extension_without_generating_code() -> None:
    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": "TC-CAND-090",
            "target_device_id": 1,
            "summary": "The observed control requires an unsupported interaction.",
            "planning_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
            "extension_reasons": [
                "The approved step requires a drag interaction that is not in the generic action set."
            ],
        }
    )
    checkpoint = evaluate_checkpoint3_plan(
        generic_new_control_test_case(), plan, agent3_observation()
    )
    assert checkpoint.status == CheckStatus.REVIEW
    assert (
        checkpoint.candidate_status
        == AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED
    )
    assert checkpoint.checks[0].rule_id == "CP3-000"


def test_agent3_non_candidate_records_not_automatable_before_ui_or_model(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260815-120000-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "agent2_manifest.json").write_text("{}", encoding="utf-8")
    payload = agent3_test_case().model_dump(mode="json")
    payload["automation_candidate"] = False
    payload["automation_reason"] = "CP2 did not approve automation."
    non_candidate = ProductTestCaseCandidate.model_validate(payload)
    design = SimpleNamespace(test_cases=[non_candidate])
    monkeypatch.setattr(
        pipeline,
        "_load_verified_agent2_run",
        lambda *_: (
            None,
            {},
            None,
            design,
            None,
            {"agent2_design_sha256": "b" * 64},
        ),
    )

    def unexpected_call(*_args, **_kwargs):
        raise AssertionError("UI inspection and model construction must not run")

    monkeypatch.setattr(pipeline, "inspect_target_ui", unexpected_call)
    monkeypatch.setattr(pipeline, "OpenAIAgent3", unexpected_call)
    args = SimpleNamespace(
        runs_root=str(tmp_path),
        run_id=run_id,
        tc_id=non_candidate.tc_id,
        target_html=str(tmp_path / "unused.html"),
        model=None,
        timeout=30,
        preview_only=False,
    )

    assert pipeline.run_agent3(args) == 2
    result = json.loads((run_dir / "agent3_eligibility.json").read_text(encoding="utf-8"))
    assert result["status"] == "NOT_AUTOMATABLE"
    assert result["candidate_status"] == "NOT_AUTOMATABLE"
    assert result["model_call_allowed"] is False
    assert result["source_agent2_design_sha256"] == "b" * 64
    assert "CP2_AUTOMATION_CANDIDATE" in result["missing_capabilities"]
    assert not (run_dir / "agent3_model_input_preview.json").exists()
    assert not (run_dir / "agent3_error.json").exists()


def test_agent3_preview_does_not_require_api_key_or_create_model_client(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260815-120001-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "agent2_manifest.json").write_text("{}", encoding="utf-8")
    design = SimpleNamespace(test_cases=[agent3_test_case()])
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(
        pipeline,
        "_load_verified_agent2_run",
        lambda *_: (
            None,
            {},
            None,
            design,
            None,
            {"agent2_design_sha256": "c" * 64},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "inspect_target_ui",
        lambda *_args, **_kwargs: agent3_observation(),
    )

    def unexpected_model_client(*_args, **_kwargs):
        raise AssertionError("Preview must not create the Agent 3 model client")

    monkeypatch.setattr(pipeline, "OpenAIAgent3", unexpected_model_client)
    args = SimpleNamespace(
        runs_root=str(tmp_path),
        run_id=run_id,
        tc_id=agent3_test_case().tc_id,
        target_html=str(tmp_path / "unused.html"),
        model=None,
        timeout=30,
        preview_only=True,
    )

    assert pipeline.run_agent3(args) == 0
    preview = json.loads(
        (run_dir / "agent3_model_input_preview.json").read_text(encoding="utf-8")
    )
    assert preview["destination"] == "OpenAI Responses API"
    assert not (run_dir / "agent3_error.json").exists()


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


def test_restore_contract_requires_initial_temperature_and_apply() -> None:
    tc = agent3_test_case().model_copy(
        update={
            "restore_required": True,
            "restore_steps": ["Restore AUTO 18 and verify UI and internal state."],
        }
    )
    plan = agent3_plan().model_copy(
        update={
            "actions": [
                *agent3_plan().actions,
                AutomationAction(
                    action_id="ACT-007",
                    phase="RESTORE",
                    action_type="SET_TEMPERATURE",
                    selector="#det-temp-display",
                    value=17.0,
                    source_text="Keep requested temperature",
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase="RESTORE",
                    action_type="APPLY_COMMANDS",
                    selector=".btn-apply-cmd",
                    source_text="Apply restore",
                ),
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(tc, plan, agent3_observation())

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-006"
        and item.status == CheckStatus.FAIL
        and "initial temperature restore is missing" in item.message
        for item in checkpoint.checks
    )


def test_compiler_verifies_restored_ui_and_internal_temperature() -> None:
    tc = agent3_test_case().model_copy(
        update={
            "restore_required": True,
            "restore_steps": ["Restore AUTO 18 and verify UI and internal state."],
        }
    )
    plan = agent3_plan().model_copy(
        update={
            "actions": [
                *agent3_plan().actions,
                AutomationAction(
                    action_id="ACT-007",
                    phase="RESTORE",
                    action_type="SET_TEMPERATURE",
                    selector="#det-temp-display",
                    value=18.0,
                    source_text="Restore initial temperature",
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase="RESTORE",
                    action_type="APPLY_COMMANDS",
                    selector=".btn-apply-cmd",
                    source_text="Apply restore",
                ),
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(tc, plan, agent3_observation())
    code = compile_automation_candidate("RUN-20260813-120000-ABCDEF", tc, plan)
    compiled_checks = evaluate_compiled_candidate(tc, code)

    assert checkpoint.status == CheckStatus.PASS
    assert all(item.status == CheckStatus.PASS for item in compiled_checks)
    assert "restore_ui_temperature = _temperature(page)" in code
    assert "restore_internal_temperature = page.evaluate" in code
    assert "RESTORE_MISMATCH:" in code



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


def test_missing_select_device_value_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["actions"][0]["value"] = None
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-002"
        and item.status == CheckStatus.FAIL
        and "invalid device selector or target value" in item.message
        for item in checkpoint.checks
    )


def test_observed_but_wrong_assertion_selector_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][0]["selector"] = "#det-temp-adjust-card"
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "invalid observation target" in item.message
        for item in checkpoint.checks
    )


def test_ungrounded_numeric_expectation_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][0]["expected_number"] = 19.0
    checkpoint = evaluate_checkpoint3_plan(agent3_test_case(), Agent3AutomationPlan.model_validate(payload), agent3_observation())
    assert checkpoint.status == CheckStatus.FAIL
    assert any(item.rule_id == "CP3-004" and item.status == CheckStatus.FAIL for item in checkpoint.checks)
    assert any(item.rule_id == "CP3-005" and item.status == CheckStatus.FAIL for item in checkpoint.checks)


def test_unsupported_expected_text_is_rejected_by_cp3() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][2]["expected_text"] = "warning message"
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "expected_text is unsupported" in item.message
        for item in checkpoint.checks
    )


def test_generic_visible_toast_is_rejected_for_blocking_expected_result() -> None:
    payload = agent3_plan().model_dump(mode="json")
    payload["assertions"][2]["strategy"] = "TOAST_VISIBLE"
    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        Agent3AutomationPlan.model_validate(payload),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-004"
        and item.status == CheckStatus.FAIL
        and "assertion strategy changed" in item.message
        for item in checkpoint.checks
    )



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
function applyPanelCommands(){devices[0].setTemp=pendingState.setTemp; devices[0].mode=pendingState.mode; let toast=document.getElementById('global-toast'); toast.innerText='Successfully applied'; toast.className='toast-box show'}
window.__vccs={get devices(){return devices},get pendingState(){return pendingState},get selectedUnitId(){return selectedUnitId},selectUnit,applyPanelCommands,renderGrid(){},saveStateToLocalStorage(){}};
</script>""",
        encoding="utf-8",
    )
    observation = inspect_target_ui(target)
    assert observation.page_title == "Virtual Controller"
    assert {"mode", "setTemp"} <= set(observation.device_state_fields)
    test_case_payload = agent3_test_case().model_dump(mode="json")
    test_case_payload["expected_results"][1]["statement"] = (
        "Internal mode is AUTO and setTemp remains at 18 degrees."
    )
    test_case = ProductTestCaseCandidate.model_validate(test_case_payload)
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"][1] = {
        "result_id": "ER-006",
        "observation_layer": "INTERNAL_STATE",
        "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
        "selector": "window.__vccs.devices",
        "expected_fields": [
            {"field_name": "mode", "expected_value": "AUTO"},
            {"field_name": "setTemp", "expected_value": 18},
        ],
    }
    plan = Agent3AutomationPlan.model_validate(plan_payload)
    assert evaluate_checkpoint3_plan(test_case, plan, observation).status == CheckStatus.PASS
    candidate = tmp_path / "candidate.py"
    candidate.write_text(
        compile_automation_candidate("RUN-20260813-120000-ABCDEF", test_case, plan),
        encoding="utf-8",
    )
    trial = run_candidate_trial(candidate, target, tmp_path / "evidence", timeout_seconds=20)
    assert trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
    assert trial.evidence_complete is True
    stdout = (tmp_path / "evidence" / "trial-stdout.txt").read_text(encoding="utf-8")
    assert "ER-007: toast does not indicate blocking: successfully applied" in stdout
    assert "ER-006: internal device fields={'mode': 'AUTO', 'setTemp': 17}" in stdout
    with zipfile.ZipFile(tmp_path / "evidence" / "trial-trace.zip") as archive:
        trace_payload = b"".join(archive.read(name) for name in archive.namelist())
    assert str(tmp_path.resolve()).encode("utf-8") not in trace_payload
    assert tmp_path.resolve().as_uri().encode("utf-8") not in trace_payload


def test_agent3_trace_redaction_handles_path_uri_and_json_escapes(
    tmp_path: Path,
) -> None:
    local_root = tmp_path / "사용자 폴더"
    local_root.mkdir()
    trace_file = tmp_path / "trial-trace.zip"
    raw_path = str(local_root.resolve())
    raw_uri = local_root.resolve().as_uri()
    escaped_path = json.dumps(raw_path, ensure_ascii=True)[1:-1]
    with zipfile.ZipFile(trace_file, "w") as archive:
        archive.writestr(
            "trace.trace",
            f"path={raw_path}\nuri={raw_uri}\nescaped={escaped_path}".encode("utf-8"),
        )
        archive.writestr("resources/evidence.bin", b"unchanged-binary-evidence")

    pipeline._redact_playwright_trace(
        trace_file,
        {local_root: "<LOCAL_ROOT>"},
    )

    with zipfile.ZipFile(trace_file) as archive:
        redacted = archive.read("trace.trace").decode("utf-8")
        binary = archive.read("resources/evidence.bin")
    assert raw_path not in redacted
    assert raw_uri not in redacted
    assert escaped_path not in redacted
    assert redacted.count("<LOCAL_ROOT>") == 3
    assert binary == b"unchanged-binary-evidence"


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
        return SimpleNamespace(
            returncode=1,
            stdout=f"한글 실행 증거\n{local_path}\n{temp_path}",
            stderr="",
        )

    for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "must-not-reach-trial")
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)

    evidence_dir = tmp_path / "evidence"
    result = run_candidate_trial(candidate, target, evidence_dir, timeout_seconds=5)

    assert result.outcome == TrialOutcome.AUTOMATION_ERROR
    assert all(name not in captured_env for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"))
    allowed = set(pipeline._AGENT3_TRIAL_ENV_ALLOWLIST) | {"QA_TARGET_URL", "QA_EVIDENCE_DIR"}
    assert set(captured_env) <= allowed
    assert captured_env["PYTHONUTF8"] == "0"
    assert captured_env["PYTHONIOENCODING"] == "utf-8"
    stdout = (evidence_dir / "trial-stdout.txt").read_text(encoding="utf-8")
    assert "한글 실행 증거" in stdout
    assert str(target.resolve()) not in stdout
    assert "<LOCAL_PATH>" in stdout


def _checkpoint3(status: CheckStatus) -> pipeline.Checkpoint3Result:
    candidate_status = (
        pipeline.AutomationCandidateStatus.READY_FOR_EXECUTION
        if status == CheckStatus.PASS
        else pipeline.AutomationCandidateStatus.REVISION_REQUIRED
    )
    return pipeline.Checkpoint3Result(
        status=status,
        candidate_status=candidate_status,
        checks=[
            pipeline.CheckResult(
                rule_id="CP3-TEST",
                status=status,
                message="CLI exit-code test fixture.",
            )
        ],
    )


def _trial(outcome: TrialOutcome) -> pipeline.Agent3TrialResult:
    return pipeline.Agent3TrialResult(
        outcome=outcome,
        exit_code=0 if outcome == TrialOutcome.PASS else 1,
        duration_ms=1,
        stdout_file="trial-stdout.txt",
        stderr_file="trial-stderr.txt",
        evidence_complete=False,
    )


@pytest.mark.parametrize(
    ("outcome", "expected_exit_code"),
    [
        (TrialOutcome.PASS, 0),
        (TrialOutcome.PRODUCT_MISMATCH_CANDIDATE, 0),
        (TrialOutcome.AUTOMATION_ERROR, 2),
        (TrialOutcome.ENVIRONMENT_ERROR, 2),
        (TrialOutcome.TIMEOUT, 2),
    ],
)
def test_agent3_cli_exit_code_reflects_trial_trustworthiness(
    outcome: TrialOutcome,
    expected_exit_code: int,
) -> None:
    assert (
        pipeline._agent3_cli_exit_code(
            _checkpoint3(CheckStatus.PASS),
            _trial(outcome),
        )
        == expected_exit_code
    )


def test_agent3_cli_exit_code_blocks_missing_trial_or_failed_checkpoint() -> None:
    assert pipeline._agent3_cli_exit_code(_checkpoint3(CheckStatus.PASS), None) == 2
    assert (
        pipeline._agent3_cli_exit_code(
            _checkpoint3(CheckStatus.FAIL),
            _trial(TrialOutcome.PASS),
        )
        == 2
    )


def test_agent3_usage_aggregates_all_planning_attempts() -> None:
    attempts = [
        {
            "attempt": 1,
            "usage": {
                "input_tokens": 2337,
                "output_tokens": 1023,
                "total_tokens": 3360,
            },
        },
        {
            "attempt": 2,
            "usage": {
                "input_tokens": 3157,
                "output_tokens": 1139,
                "total_tokens": 4296,
            },
        },
    ]

    assert pipeline._aggregate_agent3_usage(attempts) == {
        "input_tokens": 5494,
        "output_tokens": 2162,
        "total_tokens": 7656,
    }
    assert pipeline._aggregate_model_usage(attempts) == {
        "input_tokens": 5494,
        "output_tokens": 2162,
        "total_tokens": 7656,
    }


def test_agent3_error_artifact_requires_a_fresh_attempt_workspace(
    tmp_path: Path,
) -> None:
    run_id = "RUN-20260815-120002-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    (run_dir / "agent3_error.json").write_text("{}", encoding="utf-8")
    args = SimpleNamespace(
        runs_root=str(tmp_path),
        run_id=run_id,
        tc_id=agent3_test_case().tc_id,
        target_html=str(tmp_path / "unused.html"),
        model=None,
        timeout=30,
        preview_only=False,
    )

    with pytest.raises(ValueError, match="final Agent 3 artifacts"):
        pipeline.run_agent3(args)


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


# Minimal Agent 1→3 orchestrator
def _pipeline_args(tmp_path: Path) -> SimpleNamespace:
    return SimpleNamespace(
        request=str(tmp_path / "request.json"),
        srs=str(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"),
        runs_root=str(tmp_path / "runs"),
        model="fake-model",
        tc_id="AUTO",
        target_html=str(tmp_path / "virtual-controller.html"),
        timeout=30,
    )


def test_pipeline_parser_exposes_one_command_agent1_to_agent3() -> None:
    args = pipeline.build_parser().parse_args(
        [
            "pipeline",
            "--request",
            "request.json",
            "--target-html",
            "virtual-controller.html",
        ]
    )

    assert args.handler is pipeline.run_pipeline
    assert args.tc_id == "AUTO"
    assert args.timeout == 30
    assert pipeline._orchestrator_status(0) == "PASS"
    assert pipeline._orchestrator_status(1) == "ERROR"
    assert pipeline._orchestrator_status(2) == "STOPPED"

    eligible = agent3_test_case()
    unsupported = eligible.model_copy(
        update={
            "tc_id": "TC-CAND-004",
            "target_role": "MULTIPLE_ALLOWED_TEST_DEVICES",
        }
    )
    selected, summaries = pipeline._select_agent3_tc(
        Agent2TestDesign(
            request_id="CR-TEST-001",
            test_cases=[unsupported, eligible],
            coverage_summary="Selection fixture",
        )
    )
    assert selected == eligible.tc_id
    assert len(summaries) == 2
    assert summaries[0]["status"] == "DISCOVERY_REQUIRED"
    discovered, unsupported_summaries = pipeline._select_agent3_tc(
        Agent2TestDesign(
            request_id="CR-TEST-001",
            test_cases=[unsupported],
            coverage_summary="No eligible candidate fixture",
        )
    )
    assert discovered == unsupported.tc_id
    assert unsupported_summaries[0]["generic_discovery_required"] is True
    assert unsupported_summaries[0]["missing_capabilities"] == []


def test_pipeline_runs_stages_in_order_and_hashes_manifests(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")
    calls: list[str] = []

    def fake_agent1(stage_args) -> int:
        calls.append("agent1")
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent2(stage_args) -> int:
        calls.append("agent2")
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        _write_json(run_dir / "agent2_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent3(stage_args) -> int:
        calls.append("agent3")
        assert stage_args.tc_id == "TC-CAND-003"
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        _write_json(
            run_dir / "agent3_manifest.json",
            {
                "run_id": stage_args.run_id,
                "candidate_status": "PRODUCT_MISMATCH_DETECTED",
            },
        )
        _write_json(
            run_dir / "agent3_trial.json",
            {"outcome": "PRODUCT_MISMATCH_CANDIDATE"},
        )
        return 0

    monkeypatch.setattr(pipeline, "run_agent1", fake_agent1)
    monkeypatch.setattr(pipeline, "run_agent2", fake_agent2)
    monkeypatch.setattr(pipeline, "run_agent3", fake_agent3)
    monkeypatch.setattr(
        pipeline,
        "_select_agent3_tc_from_run",
        lambda _run_dir, _run_id: (
            "TC-CAND-003",
            [
                {
                    "tc_id": "TC-CAND-003",
                    "status": "ELIGIBLE",
                    "missing_capabilities": [],
                }
            ],
        ),
    )

    assert pipeline.run_pipeline(args) == 0
    assert calls == ["agent1", "agent2", "agent3"]
    run_dir = next((tmp_path / "runs").iterdir())
    manifest = json.loads(
        (run_dir / "orchestrator_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "PASS"
    assert manifest["completed_stages"] == ["agent1", "agent2", "agent3"]
    assert manifest["stopped_at"] is None
    assert manifest["selected_tc_id"] == "TC-CAND-003"
    assert manifest["trial_outcome"] == "PRODUCT_MISMATCH_CANDIDATE"
    assert manifest["agent3_selection_sha256"] == _sha256_file(
        run_dir / "agent3_selection.json"
    )
    assert manifest["agent1_manifest_sha256"] == _sha256_file(
        run_dir / "run_manifest.json"
    )
    assert manifest["agent2_manifest_sha256"] == _sha256_file(
        run_dir / "agent2_manifest.json"
    )
    assert manifest["agent3_manifest_sha256"] == _sha256_file(
        run_dir / "agent3_manifest.json"
    )


def test_pipeline_stops_after_checkpoint_block_without_later_calls(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")

    def blocked_agent1(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"status": "REVIEW"})
        return 2

    def unexpected_call(_stage_args) -> int:
        raise AssertionError("A blocked checkpoint must stop later agents")

    monkeypatch.setattr(pipeline, "run_agent1", blocked_agent1)
    monkeypatch.setattr(pipeline, "run_agent2", unexpected_call)
    monkeypatch.setattr(pipeline, "run_agent3", unexpected_call)

    assert pipeline.run_pipeline(args) == 2
    run_dir = next((tmp_path / "runs").iterdir())
    manifest = json.loads(
        (run_dir / "orchestrator_manifest.json").read_text(encoding="utf-8")
    )
    assert manifest["status"] == "STOPPED"
    assert manifest["stage_exit_codes"] == {"agent1": 2}
    assert manifest["completed_stages"] == []
    assert manifest["stopped_at"] == "agent1"


def test_pipeline_rejects_missing_target_before_any_model_stage(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)

    def unexpected_call(_stage_args) -> int:
        raise AssertionError("Missing local inputs must fail before a model stage")

    monkeypatch.setattr(pipeline, "run_agent1", unexpected_call)

    with pytest.raises(ValueError, match="target HTML does not exist"):
        pipeline.run_pipeline(args)


# Validation execution: trusted new candidate + related existing regressions
def _neutral_execution_result(
    test_id: str,
    source: pipeline.ExecutionSource,
    status: pipeline.NeutralExecutionStatus = pipeline.NeutralExecutionStatus.PASSED,
) -> pipeline.NeutralExecutionResult:
    return pipeline.NeutralExecutionResult(
        test_id=test_id,
        source=source,
        requirement_ids=["REQ-ENV-001"] if test_id == "TC-ENV-000" else ["REQ-TEMP-001"],
        status=status,
        source_outcome="PYTEST_PASSED" if status == pipeline.NeutralExecutionStatus.PASSED else "PYTEST_ERROR",
        exit_code=0 if status == pipeline.NeutralExecutionStatus.PASSED else 1,
        duration_ms=1,
        test_file="test_controller.py",
        test_sha256="a" * 64,
        target_sha256="b" * 64,
        reused=source == pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE,
        stdout_file="evidence/stdout.txt",
        stderr_file="evidence/stderr.txt",
        evidence_files=["evidence/stdout.txt", "evidence/stderr.txt"],
        evidence_sha256={
            "evidence/stdout.txt": "c" * 64,
            "evidence/stderr.txt": "d" * 64,
        },
        evidence_complete=True,
    )


def test_related_regression_selection_is_grounded_and_excludes_demo_cases() -> None:
    selected = pipeline.select_existing_regressions(
        ["REQ-TEMP-001", "REQ-CONTROL-001", "REQ-STATE-001"]
    )

    assert [item.tc_id for item in selected] == ["TC-MODE-001", "TC-TEMP-001"]
    assert "TC-INT-002" not in {item.tc_id for item in pipeline.EXISTING_REGRESSION_CATALOG}
    assert all(not item.tc_id.startswith("TC-PIPE-") for item in selected)
    assert all(item.tc_id != "TC-TEMP-002" for item in selected)


def test_existing_regression_runs_from_a_copied_neutral_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    target = tmp_path / "project1" / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline_hash = _sha256_file(baseline)
    target_hash = _sha256_file(target)
    captured: dict[str, object] = {}

    def fake_run(command, **kwargs):
        workspace = Path(kwargs["cwd"])
        captured["command"] = command
        captured["env"] = kwargs["env"]
        assert (workspace / "tests" / "test_controller.py").is_file()
        assert (workspace / "tests" / "conftest.py").is_file()
        assert (workspace / "virtual-controller.html").is_file()
        return SimpleNamespace(returncode=0, stdout=". [100%]\n1 passed\n", stderr="")

    monkeypatch.setenv("OPENAI_API_KEY", "must-not-reach-regression")
    monkeypatch.setattr(pipeline.subprocess, "run", fake_run)
    spec = next(
        item for item in pipeline.EXISTING_REGRESSION_CATALOG if item.tc_id == "TC-TEMP-001"
    )

    result = pipeline.run_existing_regression(
        spec,
        baseline,
        target,
        tmp_path / "run" / "validation_evidence",
        timeout_seconds=10,
    )

    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.source == pipeline.ExecutionSource.EXISTING_REGRESSION
    assert result.test_id == "TC-TEMP-001"
    assert "OPENAI_API_KEY" not in captured["env"]
    assert captured["command"][-2:] == ["-p", "no:cacheprovider"]
    assert _sha256_file(baseline) == baseline_hash
    assert _sha256_file(target) == target_hash
    assert result.evidence_complete is True


def _build_candidate_execution_handoff(
    tmp_path: Path, monkeypatch
) -> tuple[Path, Path, str]:
    run_id = "RUN-20260816-010000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    evidence_dir = run_dir / "evidence" / "TC-CAND-003"
    candidate_dir = run_dir / "candidates"
    evidence_dir.mkdir(parents=True)
    candidate_dir.mkdir()
    target = tmp_path / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    tc = agent3_test_case()
    agent2_manifest = {"agent2_design_sha256": "b" * 64}
    _write_json(run_dir / "agent2_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_eligibility.json", {})
    _write_json(run_dir / "agent3_ui_observation.json", {})
    _write_json(run_dir / "agent3_automation_plan.json", {})
    _write_json(
        run_dir / "checkpoint3.json",
        _checkpoint3(CheckStatus.PASS).model_dump(mode="json"),
    )
    trial = _trial(TrialOutcome.PASS).model_copy(
        update={
            "exit_code": 0,
            "evidence_complete": True,
            "screenshot_file": "trial-final.png",
            "trace_file": "trial-trace.zip",
        }
    )
    _write_json(run_dir / "agent3_trial.json", trial.model_dump(mode="json"))
    candidate = candidate_dir / "test_tc_cand_003.py"
    candidate.write_text("def test_tc_cand_003():\n    assert True\n", encoding="utf-8")
    (evidence_dir / "trial-stdout.txt").write_text("1 passed\n", encoding="utf-8")
    (evidence_dir / "trial-stderr.txt").write_text("", encoding="utf-8")
    (evidence_dir / "trial-final.png").write_bytes(b"png")
    (evidence_dir / "trial-trace.zip").write_bytes(b"zip")
    _write_json(
        run_dir / "agent3_manifest.json",
        {
            "run_id": run_id,
            "stage": "AGENT_3_CP3_TRIAL",
            "status": "PASS",
            "tc_id": tc.tc_id,
            "source_agent2_manifest_sha256": _sha256_file(run_dir / "agent2_manifest.json"),
            "source_agent2_design_sha256": "b" * 64,
            "eligibility_sha256": _sha256_file(run_dir / "agent3_eligibility.json"),
            "ui_observation_sha256": _sha256_file(run_dir / "agent3_ui_observation.json"),
            "automation_plan_sha256": _sha256_file(run_dir / "agent3_automation_plan.json"),
            "checkpoint3_sha256": _sha256_file(run_dir / "checkpoint3.json"),
            "candidate_file": candidate.name,
            "candidate_sha256": _sha256_file(candidate),
            "trial_sha256": _sha256_file(run_dir / "agent3_trial.json"),
            "target_file": target.name,
            "target_sha256": _sha256_file(target),
            "project1_modified": False,
        },
    )
    monkeypatch.setattr(
        pipeline,
        "_load_verified_agent2_run",
        lambda _run_dir, _run_id: (
            None,
            None,
            None,
            SimpleNamespace(test_cases=[tc]),
            None,
            agent2_manifest,
        ),
    )
    return run_dir, target, run_id


def test_candidate_trial_is_reused_only_after_hash_and_evidence_checks(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, target, run_id = _build_candidate_execution_handoff(tmp_path, monkeypatch)

    result, test_case, _ = pipeline._candidate_execution_record(
        run_dir, run_id, target
    )

    assert result.test_id == test_case.tc_id == "TC-CAND-003"
    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.reused is True
    assert len(result.evidence_files) == 4
    assert result.evidence_complete is True

    target.write_text("changed", encoding="utf-8")
    with pytest.raises(ValueError, match="HTML이 신규 자동화 후보 시험 후 변경"):
        pipeline._candidate_execution_record(run_dir, run_id, target)


def test_current_compiler_reuses_identical_code_and_retrials_stale_code(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-015000-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    target = tmp_path / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    test_case = agent3_test_case()
    plan = agent3_plan()
    _write_json(
        run_dir / "agent3_automation_plan.json", plan.model_dump(mode="json")
    )
    current_code = compile_automation_candidate(run_id, test_case, plan)
    stored_candidate = run_dir / "candidates" / "test_tc_cand_003.py"
    stored_candidate.parent.mkdir()
    stored_candidate.write_text(current_code, encoding="utf-8")
    current_hash = _sha256_file(stored_candidate)
    stored = _neutral_execution_result(
        test_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    ).model_copy(
        update={
            "test_file": stored_candidate.name,
            "test_sha256": current_hash,
        }
    )

    monkeypatch.setattr(
        pipeline,
        "run_candidate_trial",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("identical code must reuse the stored trial")
        ),
    )
    assert pipeline._current_candidate_execution_record(
        run_dir,
        run_id,
        target,
        test_case,
        stored,
        timeout_seconds=10,
    ) is stored

    def fake_trial(candidate_file, _target, evidence_dir, *, timeout_seconds):
        assert timeout_seconds == 10
        assert candidate_file.read_text(encoding="utf-8") == current_code
        evidence_dir.mkdir(parents=True)
        (evidence_dir / "trial-stdout.txt").write_text("1 passed\n", encoding="utf-8")
        (evidence_dir / "trial-stderr.txt").write_text("", encoding="utf-8")
        (evidence_dir / "trial-final.png").write_bytes(b"png")
        (evidence_dir / "trial-trace.zip").write_bytes(b"zip")
        return _trial(TrialOutcome.PASS).model_copy(
            update={
                "exit_code": 0,
                "evidence_complete": True,
                "screenshot_file": "trial-final.png",
                "trace_file": "trial-trace.zip",
            }
        )

    monkeypatch.setattr(pipeline, "run_candidate_trial", fake_trial)
    refreshed = pipeline._current_candidate_execution_record(
        run_dir,
        run_id,
        target,
        test_case,
        stored.model_copy(update={"test_sha256": "f" * 64}),
        timeout_seconds=10,
    )

    assert refreshed.reused is False
    assert refreshed.test_sha256 == _sha256_file(
        run_dir / "validation_candidates" / "test_tc_cand_003.py"
    )
    assert refreshed.status == pipeline.NeutralExecutionStatus.PASSED
    assert (run_dir / "validation_candidate_trial.json").is_file()


def _validation_execution_args(
    tmp_path: Path, run_id: str, target: Path, baseline: Path
) -> SimpleNamespace:
    return SimpleNamespace(
        run_id=run_id,
        runs_root=str(tmp_path / "runs"),
        target_html=str(target),
        baseline_tests=str(baseline),
        timeout=10,
    )


def test_validation_execution_reuses_candidate_and_runs_related_regressions(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-020000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    _write_json(run_dir / "agent3_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_trial.json", {"outcome": "PASS"})
    candidate = _neutral_execution_result(
        "TC-CAND-003", pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    )
    test_case = agent3_test_case()
    calls: list[str] = []

    monkeypatch.setattr(
        pipeline,
        "_candidate_execution_record",
        lambda _run_dir, _run_id, _target: (candidate, test_case, {}),
    )
    monkeypatch.setattr(
        pipeline,
        "_current_candidate_execution_record",
        lambda _run_dir, _run_id, _target, _test_case, stored, **_kwargs: stored,
    )

    def fake_regression(spec, *_args, source=pipeline.ExecutionSource.EXISTING_REGRESSION, **_kwargs):
        calls.append(spec.tc_id)
        return _neutral_execution_result(spec.tc_id, source)

    monkeypatch.setattr(pipeline, "run_existing_regression", fake_regression)

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 0
    assert calls == ["TC-ENV-000", "TC-TEMP-001"]
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )
    manifest = json.loads(
        (run_dir / "validation_manifest.json").read_text(encoding="utf-8")
    )
    assert bundle.status == pipeline.ValidationStageStatus.COMPLETED
    assert bundle.candidate_result.reused is True
    assert bundle.selected_regression_ids == ["TC-TEMP-001"]
    assert [item.test_id for item in bundle.regression_results] == ["TC-TEMP-001"]
    assert manifest["validation_execution_sha256"] == _sha256_file(
        run_dir / "validation_execution.json"
    )
    assert manifest["project1_modified"] is False


def test_validation_execution_stops_regressions_when_precheck_is_not_passed(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-030000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    _write_json(run_dir / "agent3_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_trial.json", {"outcome": "PASS"})
    monkeypatch.setattr(
        pipeline,
        "_candidate_execution_record",
        lambda _run_dir, _run_id, _target: (
            _neutral_execution_result(
                "TC-CAND-003", pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
            ),
            agent3_test_case(),
            {},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_current_candidate_execution_record",
        lambda _run_dir, _run_id, _target, _test_case, stored, **_kwargs: stored,
    )
    calls: list[str] = []

    def failed_precheck(spec, *_args, source=pipeline.ExecutionSource.EXISTING_REGRESSION, **_kwargs):
        calls.append(spec.tc_id)
        return _neutral_execution_result(
            spec.tc_id,
            source,
            pipeline.NeutralExecutionStatus.EXECUTION_ERROR,
        )

    monkeypatch.setattr(pipeline, "run_existing_regression", failed_precheck)

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 2
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )
    assert calls == ["TC-ENV-000"]
    assert bundle.status == pipeline.ValidationStageStatus.BLOCKED
    assert bundle.selected_regression_ids == ["TC-TEMP-001"]
    assert bundle.regression_results == []
    assert bundle.blocked_reason == "ENVIRONMENT_PRECHECK_NOT_PASSED"


def test_execute_parser_exposes_validation_execution_command() -> None:
    args = pipeline.build_parser().parse_args(
        [
            "execute",
            "--run-id",
            "RUN-20260816-010000-ABCDEF",
            "--target-html",
            "virtual-controller.html",
        ]
    )

    assert args.handler is pipeline.run_validation_execution
    assert args.baseline_tests is None
    assert args.timeout == 60


# Agent 4: verified neutral results -> rules-only findings and final report
def _write_agent4_inputs(
    tmp_path: Path,
    *,
    candidate_status: pipeline.NeutralExecutionStatus = pipeline.NeutralExecutionStatus.PASSED,
    precheck_status: pipeline.NeutralExecutionStatus = pipeline.NeutralExecutionStatus.PASSED,
) -> tuple[Path, str]:
    run_id = "RUN-20260817-030000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    candidate = _neutral_execution_result(
        "TC-CAND-003", pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE, candidate_status
    )
    precheck = _neutral_execution_result(
        "TC-ENV-000", pipeline.ExecutionSource.ENVIRONMENT_PRECHECK, precheck_status
    )
    regressions = (
        [_neutral_execution_result("TC-TEMP-001", pipeline.ExecutionSource.EXISTING_REGRESSION)]
        if precheck_status == pipeline.NeutralExecutionStatus.PASSED
        else []
    )

    def materialize_evidence(
        result: pipeline.NeutralExecutionResult,
    ) -> pipeline.NeutralExecutionResult:
        hashes: dict[str, str] = {}
        for relative_name in result.evidence_files:
            evidence_file = run_dir / relative_name
            evidence_file.parent.mkdir(parents=True, exist_ok=True)
            evidence_file.write_text(
                f"evidence:{relative_name}\n", encoding="utf-8"
            )
            hashes[relative_name] = _sha256_file(evidence_file)
        return result.model_copy(update={"evidence_sha256": hashes})

    candidate = materialize_evidence(candidate)
    precheck = materialize_evidence(precheck)
    regressions = [materialize_evidence(result) for result in regressions]
    bundle = pipeline.ValidationExecutionBundle(
        run_id=run_id,
        status=(
            pipeline.ValidationStageStatus.COMPLETED
            if precheck_status == pipeline.NeutralExecutionStatus.PASSED
            else pipeline.ValidationStageStatus.BLOCKED
        ),
        candidate_result=candidate,
        environment_precheck=precheck,
        selected_regression_ids=["TC-TEMP-001"],
        regression_results=regressions,
        blocked_reason=(
            None
            if precheck_status == pipeline.NeutralExecutionStatus.PASSED
            else "ENVIRONMENT_PRECHECK_NOT_PASSED"
        ),
        created_at="2026-08-17T00:00:00+00:00",
    )
    execution_file = run_dir / "validation_execution.json"
    _write_json(execution_file, bundle.model_dump(mode="json"))
    _write_json(
        run_dir / "validation_manifest.json",
        {
            "run_id": run_id,
            "validation_execution_sha256": _sha256_file(execution_file),
            "project1_modified": False,
        },
    )
    return run_dir, run_id


def test_agent4_writes_consistent_pass_report_without_rerunning_tests(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    analysis = pipeline.Agent4Analysis.model_validate_json(
        (run_dir / "agent4_analysis.json").read_text(encoding="utf-8")
    )
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.PASS
    assert analysis.total_results == 3
    assert analysis.status_counts[pipeline.NeutralExecutionStatus.PASSED] == 3
    assert analysis.findings == []
    assert report.recommendation == pipeline.FinalRecommendation.PASS
    assert report.total_results == analysis.total_results
    assert report.status_counts == analysis.status_counts


def test_agent4_marks_assertion_failure_as_product_mismatch_candidate(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, candidate_status=pipeline.NeutralExecutionStatus.ASSERTION_FAILED
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HUMAN_REVIEW
    assert report.findings[0].category == pipeline.Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE
    assert "확정" in report.findings[0].rationale


def test_agent4_holds_when_environment_precheck_blocks_regressions(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, precheck_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HOLD
    assert {finding.category for finding in report.findings} == {
        pipeline.Agent4FindingCategory.ENVIRONMENT_ISSUE,
        pipeline.Agent4FindingCategory.INSUFFICIENT_EVIDENCE,
    }


def test_agent4_rejects_validation_execution_hash_mismatch(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["validation_execution_sha256"] = "0" * 64
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.FAIL
    assert (run_dir / "agent4_error.json").exists() is False


def test_agent4_rejects_mismatched_execution_source_contract(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    execution_file = run_dir / "validation_execution.json"
    execution = json.loads(execution_file.read_text(encoding="utf-8"))
    execution["environment_precheck"]["source"] = "EXISTING_REGRESSION"
    _write_json(execution_file, execution)
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["validation_execution_sha256"] = _sha256_file(execution_file)
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2

    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[3].rule_id == "CP4-004"
    assert checkpoint.checks[3].status == pipeline.CheckStatus.FAIL


def test_agent4_rejects_missing_or_changed_evidence_file(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    (run_dir / "evidence" / "stdout.txt").unlink()

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2

    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[5].rule_id == "CP4-006"
    assert checkpoint.checks[5].status == pipeline.CheckStatus.FAIL


def test_agent4_parser_exposes_rules_only_report_command() -> None:
    args = pipeline.build_parser().parse_args(
        ["agent4", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )

    assert args.handler is pipeline.run_agent4
