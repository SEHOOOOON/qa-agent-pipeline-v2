# Product SRS parser
import json
import os
import subprocess
import sys
import time
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
        "REQ-NOTIFY-001",
        "REQ-STATE-001",
    }
    assert not any(item.startswith("REQ-LOCAL-") for item in requirements)
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
import qa_pipeline_ui as pipeline_ui

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
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent1-2-7"
    assert responses.kwargs["store"] is False
    instructions = responses.kwargs["input"][0]["content"]
    assert "현재 SRS는 변경 전 제품 상태" in instructions
    assert "변경 후 정책의 권한 있는 입력" in instructions
    assert "acceptance_notes 중 제품의 긍정적인 판정 기준" in instructions
    assert "Agent 2가 TC의 판정 기준" in instructions
    assert "VERIFY, 이번 변경과 무관한 기준은 NO_IMPACT" in instructions
    assert "연관 항목을 조용히 생략하지 않습니다" in instructions
    assert "자동화 구현 지원 여부를 이유로" in instructions
    assert "TC 구성·기존 TC 선택·자동화 가능 여부" in instructions
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
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert result.final_review_notes == [
        "변경 전 값이 대상 SRS 행에서 직접 확인되지 않습니다."
    ]
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


def test_checkpoint1_does_not_require_setup_or_restore_as_product_conditions() -> None:
    setup_note = "첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작한다."
    restore_note = "시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [
                *cp1_request().acceptance_notes,
                setup_note,
                restore_note,
            ]
        }
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "excluded_scope": [
                *cp1_valid_analysis().excluded_scope,
                setup_note,
                restore_note,
            ]
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS


def test_missing_requested_out_of_scope_is_rejected() -> None:
    scoped_request = cp1_request().model_copy(update={"out_of_scope": ["화씨 표시 정책"]})
    analysis = cp1_valid_analysis().model_copy(update={"excluded_scope": []})

    result = evaluate_checkpoint1(scoped_request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL


def test_scope_limited_acceptance_note_is_only_excluded() -> None:
    scope_note = "온도 표시값 변경은 이번 변경 범위에 포함하지 않는다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [*cp1_request().acceptance_notes, scope_note],
            "out_of_scope": [scope_note],
        }
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "excluded_scope": [*cp1_valid_analysis().excluded_scope, scope_note]
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert cp1_check(result, "CP1-008").status == CheckStatus.PASS
    assert cp1_check(result, "CP1-009").status == CheckStatus.PASS


def test_scope_limited_acceptance_note_cannot_be_confirmed_condition() -> None:
    scope_note = "온도 표시값 변경은 이번 변경 범위에 포함하지 않는다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [*cp1_request().acceptance_notes, scope_note],
            "out_of_scope": [scope_note],
        }
    )
    scope_condition = ConfirmedCondition(
        condition_id="COND-004",
        statement=scope_note,
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text=scope_note,
        requirement_ids=["REQ-TEMP-001"],
    )
    analysis = cp1_valid_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *cp1_valid_analysis().confirmed_conditions,
                scope_condition,
            ],
            "excluded_scope": [*cp1_valid_analysis().excluded_scope, scope_note],
        }
    )

    result = evaluate_checkpoint1(request, analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp1_check(result, "CP1-009").status == CheckStatus.FAIL
    assert "제외 조건" in cp1_check(result, "CP1-009").message


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


def test_partial_proceed_continues_confirmed_scope_and_preserves_exclusions() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": ["기존 저장값의 소급 적용"],
            "information_gaps": ["기존 저장값의 적용 시점이 정의되지 않음"],
            "excluded_information_gaps": ["기존 저장값의 적용 시점이 정의되지 않음"],
            "user_questions": ["기존 저장값에도 즉시 소급 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE


def test_partial_proceed_without_excluded_scope_is_rejected() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": [],
            "information_gaps": ["적용 시점이 정의되지 않음"],
            "excluded_information_gaps": ["적용 시점이 정의되지 않음"],
            "user_questions": ["언제 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.FAIL
    assert result.handoff_status == HandoffStatus.BLOCKED
    assert cp1_check(result, "CP1-010").status == CheckStatus.FAIL

    mismatched = analysis.model_copy(
        update={
            "excluded_scope": ["적용 시점"],
            "excluded_information_gaps": [],
        }
    )
    mismatched_result = evaluate_checkpoint1(
        cp1_request(), mismatched, cp1_requirements()
    )
    assert cp1_check(mismatched_result, "CP1-010").status == CheckStatus.FAIL


def test_blocked_decision_blocks_agent2_handoff() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={"decision": AnalysisDecision.BLOCKED}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.BLOCKED


def test_related_requirement_can_be_marked_update_required() -> None:
    requirements = cp1_requirements()
    related = requirements["REQ-NOTIFY-001"]
    conditions = [
        *cp1_valid_analysis().confirmed_conditions,
        ConfirmedCondition(
            condition_id="COND-004",
            statement=related.statement,
            source_type=ConditionSource.SRS,
            source_text=related.statement,
            requirement_ids=["REQ-NOTIFY-001"],
        ),
    ]
    effects = [
        item.model_copy(update={"relation": RequirementRelation.UPDATE_REQUIRED})
        if item.requirement_id == "REQ-NOTIFY-001"
        else item
        for item in cp1_valid_analysis().requirement_effects
    ]
    analysis = cp1_valid_analysis().model_copy(
        update={"confirmed_conditions": conditions, "requirement_effects": effects}
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, requirements)

    assert result.status == CheckStatus.PASS
    assert result.handoff_status == HandoffStatus.CONTINUE

def test_proceed_with_open_question_is_recorded_for_final_review() -> None:
    analysis = cp1_valid_analysis().model_copy(
        update={
            "information_gaps": ["경계값 적용 시점이 불명확함"],
            "user_questions": ["기존 저장값에도 즉시 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(cp1_request(), analysis, cp1_requirements())

    assert result.status == CheckStatus.REVIEW
    assert result.handoff_status == HandoffStatus.CONTINUE
    assert result.final_review_notes == [
        "정보 부족 또는 질문이 있는데 PROCEED로 판정했습니다."
    ]
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
    CommonQaCriterion,
    ConfirmedCondition,
    ConditionSource,
    ControlPath,
    DomainQaCriterion,
    DoubleAssertPolicy,
    ExistingTestSelection,
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
        existing_tc_comparison_completed=True,
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
                control_path=ControlPath.CENTRAL,
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
                common_qa_criteria=[CommonQaCriterion.BOUNDARY_VALUE],
                domain_qa_criteria=[
                    DomainQaCriterion.TARGET_DEVICE_ACCURACY,
                    DomainQaCriterion.UI_INTERNAL_STATE_CONSISTENCY,
                ],
                feature_requirement_ids=["REQ-TEMP-001"],
                independent_execution=True,
                independence_reason="사전조건에서 대상 장비의 AUTO 모드와 초기 온도를 직접 구성한다.",
                double_assert_policy=DoubleAssertPolicy.REQUIRED,
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
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent2-2-15"
    agent2_input = responses.kwargs["input"][1]["content"]
    assert "[기존 사람 작성·자동화 TC 카탈로그]" in agent2_input
    assert "TC-TEMP-001" in agent2_input
    assert "TC-MODE-002" in agent2_input
    assert "검증 동작" in agent2_input
    assert "30°C 초과 요청 차단" in agent2_input
    assert "제품 기능 테스트케이스 후보" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Playwright 코드" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 confirmed_condition" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "Requirement ID만 같고 검증 동작이 다르면" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "내부 필드 식별자" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "target_role=PRIMARY_TEST_DEVICE" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "V1의 3단계 QA 기준" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "independent_execution=true" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "모든 실행 TC는 control_path=CENTRAL" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "TC 분리 단위는 입력값 하나가 아니라 하나의 업무 규칙" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "INDEPENDENT_VARIANTS" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "verify_after_step" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "제외된_정보_부족" in AGENT2_SYSTEM_INSTRUCTIONS
    assert "전체 test_cases와 관련_기존_TC를 완전한 결과로 반환" in Path(
        "src/qa_pipeline_v2.py"
    ).read_text(encoding="utf-8")

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
    assert "최종_확인_사항" in rework_input
    assert "중단_확인_사항" in rework_input


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
    CommonQaCriterion,
    ConfirmedCondition,
    ConditionSource,
    ControlPath,
    DomainQaCriterion,
    DoubleAssertPolicy,
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
        existing_tc_comparison_completed=True,
        related_existing_tests=[
            ExistingTestSelection(
                tc_id="TC-TEMP-001",
                source_condition_ids=["COND-001"],
                selection_reason="변경된 온도 정책이 기존 상한 경계에 영향을 주는지 회귀 확인한다.",
            )
        ],
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
                control_path=ControlPath.CENTRAL,
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
                common_qa_criteria=[CommonQaCriterion.BOUNDARY_VALUE],
                domain_qa_criteria=[
                    DomainQaCriterion.TARGET_DEVICE_ACCURACY,
                    DomainQaCriterion.UI_INTERNAL_STATE_CONSISTENCY,
                ],
                feature_requirement_ids=["REQ-TEMP-001"],
                independent_execution=True,
                independence_reason="사전조건에서 AUTO 모드와 초기 온도를 직접 구성한다.",
                double_assert_policy=DoubleAssertPolicy.REQUIRED,
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
    assert len(result.checks) == 17
    assert all(item.status == CheckStatus.PASS for item in result.checks)


def test_checkpoint2_requires_grounded_srs_revision_proposal_for_modified_requirement() -> None:
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="범위 밖 차단",
        proposed_acceptance_criteria="AUTO 모드는 18~30°C를 허용하고 범위 밖 요청을 차단",
        reason="AUTO 모드 하한 변경을 기준 문서에 반영한다.",
    )
    design = cp2_valid_design().model_copy(
        update={"srs_revision_proposals": [proposal]}
    )

    passed = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design,
        cp2_requirements(),
        require_srs_revision_proposals=True,
    )
    missing = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        cp2_valid_design(),
        cp2_requirements(),
        require_srs_revision_proposals=True,
    )

    assert cp2_check(passed, "CP2-018").status == CheckStatus.PASS
    assert cp2_check(missing, "CP2-018").status == CheckStatus.FAIL
    assert "개정 제안 누락=REQ-TEMP-001" in cp2_check(missing, "CP2-018").message


def test_srs_revision_preview_apply_and_conflict_detection(tmp_path: Path) -> None:
    srs_file = tmp_path / "SRS.md"
    srs_file.write_text(
        "# SRS\n\n| ID | 요구사항 | 인수 기준 |\n"
        "|---|---|---|\n"
        "| REQ-TEMP-001 | 온도 범위 | 기존 기준 |\n",
        encoding="utf-8",
    )
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="기존 기준",
        proposed_acceptance_criteria="변경 기준",
        reason="승인된 변경을 반영한다.",
    )

    preview = pipeline.apply_srs_revision_proposals(
        srs_file, [proposal], write=False
    )
    assert preview["changed_requirement_ids"] == ["REQ-TEMP-001"]
    assert "기존 기준" in srs_file.read_text(encoding="utf-8")

    applied = pipeline.apply_srs_revision_proposals(srs_file, [proposal], write=True)
    repeated = pipeline.apply_srs_revision_proposals(srs_file, [proposal], write=True)
    assert applied["changed_requirement_ids"] == ["REQ-TEMP-001"]
    assert repeated["already_applied_requirement_ids"] == ["REQ-TEMP-001"]
    assert "변경 기준" in srs_file.read_text(encoding="utf-8")

    conflicting = proposal.model_copy(
        update={
            "current_acceptance_criteria": "다른 기준",
            "proposed_acceptance_criteria": "또 다른 기준",
        }
    )
    with pytest.raises(ValueError, match="기준 원문과 다릅니다"):
        pipeline.apply_srs_revision_proposals(srs_file, [conflicting], write=True)


def test_checkpoint2_routes_unchanged_condition_to_existing_tc() -> None:
    maintained = ConfirmedCondition(
        condition_id="COND-004",
        statement="기존 30°C 상한 차단 정책을 유지한다.",
        source_type=ConditionSource.CHANGE_REQUEST,
        source_text="기존 30°C 상한 차단 정책을 유지한다.",
        requirement_ids=["REQ-TEMP-001"],
    )
    analysis = cp2_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *cp2_analysis().confirmed_conditions,
                maintained,
            ]
        }
    )
    design = cp2_valid_design().model_copy(
        update={
            "related_existing_tests": [
                ExistingTestSelection(
                    tc_id="TC-TEMP-001",
                    source_condition_ids=["COND-001", "COND-004"],
                    selection_reason="유지되는 상한 정책은 기존 TC로 회귀 확인한다.",
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), analysis, design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS


def test_checkpoint2_rejects_existing_regression_regenerated_as_candidate() -> None:
    design = cp2_valid_design()
    regenerated = design.test_cases[0].model_copy(
        update={"purpose": TcPurpose.RELATED_REGRESSION}
    )

    result = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [regenerated]}),
        cp2_requirements(),
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-016").status == CheckStatus.FAIL
    assert "신규 후보로 재작성" in cp2_check(result, "CP2-016").message


def test_checkpoint2_allows_incompatible_target_regression_to_be_omitted() -> None:
    design = cp2_valid_design().model_copy(update={"related_existing_tests": []})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS


def test_checkpoint2_rejects_compound_ui_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    compound_result = test_case.expected_results[0].model_copy(
        update={"statement": "화면 모드는 AUTO이고 설정 온도는 18°C로 유지된다."}
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            compound_result,
                            *test_case.expected_results[1:],
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-006").status == CheckStatus.FAIL
    assert "관찰값별로 분리" in cp2_check(result, "CP2-006").message

    for contextual_statement in (
        "AUTO 모드에서 화면의 온도 조작 버튼은 비활성화된다.",
        "AUTO 모드에서 화면의 설정 온도 표시는 ---이다.",
    ):
        contextual_result = test_case.expected_results[0].model_copy(
            update={"statement": contextual_statement}
        )
        contextual_design = design.model_copy(
            update={
                "test_cases": [
                    test_case.model_copy(
                        update={
                            "expected_results": [
                                contextual_result,
                                *test_case.expected_results[1:],
                            ]
                        }
                    )
                ]
            }
        )
        contextual_checkpoint = evaluate_checkpoint2(
            cp1_request(), cp2_analysis(), contextual_design, cp2_requirements()
        )
        assert cp2_check(contextual_checkpoint, "CP2-006").status == CheckStatus.PASS


def test_checkpoint2_rejects_procedural_selection_expected_result() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    selection_result = ExpectedResult(
        result_id="ER-004",
        statement="PRIMARY_TEST_DEVICE가 단일 선택된다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            selection_result,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "준비용 장비 선택" in cp2_check(result, "CP2-017").message


def test_checkpoint2_rejects_ui_display_not_present_in_condition_source() -> None:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    invented_display = ExpectedResult(
        result_id="ER-004",
        statement="사용자 화면의 잠금 상태가 잠금으로 표시된다.",
        observation_layer=ObservationLayer.UI,
        source_condition_ids=["COND-001"],
    )
    design = design.model_copy(
        update={
            "test_cases": [
                test_case.model_copy(
                    update={
                        "expected_results": [
                            *test_case.expected_results,
                            invented_display,
                        ]
                    }
                )
            ]
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-017").status == CheckStatus.FAIL
    assert "Condition 원문에 없는 UI 표시" in cp2_check(result, "CP2-017").message


def grouped_boundary_design() -> Agent2TestDesign:
    design = cp2_valid_design()
    test_case = design.test_cases[0]
    lower_step = "AUTO 모드에서 17°C를 요청해 하한 차단을 확인한다."
    reset_step = "상한 검증을 위해 AUTO 모드와 설정 온도 30°C를 독립적으로 다시 준비한다."
    upper_step = "AUTO 모드에서 31°C를 요청해 상한 차단을 확인한다."
    expected_results = [
        test_case.expected_results[0].model_copy(
            update={"verify_after_step": lower_step}
        ),
        test_case.expected_results[1].model_copy(
            update={"verify_after_step": lower_step}
        ),
        test_case.expected_results[2].model_copy(
            update={"verify_after_step": upper_step}
        ),
    ]
    grouped = test_case.model_copy(
        update={
            "title": "AUTO 모드 설정 온도 범위",
            "test_data": test_case.test_data.model_copy(
                update={
                    "requested_mode": None,
                    "requested_modes": ["AUTO"],
                    "requested_temperature_c": None,
                    "requested_temperatures_c": [17.0, 30.0, 31.0],
                }
            ),
            "condition_execution": pipeline.ConditionExecution.INDEPENDENT_VARIANTS,
            "grouping_reason": "같은 설정 온도 관제점의 AUTO 허용 범위라는 하나의 업무 규칙이다.",
            "intermediate_reset_steps": [reset_step],
            "steps": [lower_step, reset_step, upper_step],
            "expected_results": expected_results,
            "independence_reason": "하한과 상한 조건 사이에 AUTO 30°C 상태를 다시 준비해 서로 의존하지 않는다.",
        }
    )
    return design.model_copy(update={"test_cases": [grouped]})


def test_checkpoint2_accepts_related_boundaries_as_one_grouped_tc() -> None:
    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), grouped_boundary_design(), cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-015").status == CheckStatus.PASS


def test_checkpoint2_rejects_grouped_tc_without_reset_or_result_timing() -> None:
    design = grouped_boundary_design()
    test_case = design.test_cases[0]
    broken_results = [
        result.model_copy(update={"verify_after_step": None})
        for result in test_case.expected_results
    ]
    broken = test_case.model_copy(
        update={
            "intermediate_reset_steps": [],
            "expected_results": broken_results,
        }
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(),
        design.model_copy(update={"test_cases": [broken]}),
        cp2_requirements(),
    )

    assert result.status == CheckStatus.FAIL
    check = cp2_check(result, "CP2-015")
    assert check.status == CheckStatus.FAIL
    assert "초기화 절차 누락" in check.message
    assert "판정 단계 누락" in check.message


def test_checkpoint2_requires_explicit_runtime_restore_for_unknown_grouped_hvac_baseline() -> None:
    design = grouped_boundary_design()
    test_case = design.test_cases[0]
    restore_step = "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다."
    unknown_baseline = test_case.model_copy(
        update={
            "test_data": test_case.test_data.model_copy(
                update={
                    "initial_mode": None,
                    "initial_temperature_c": None,
                    "restore_observed_hvac_state": False,
                }
            ),
            "restore_required": True,
            "restore_steps": [restore_step],
        }
    )

    rejected = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [unknown_baseline]}),
        cp2_requirements(),
    )
    accepted_case = unknown_baseline.model_copy(
        update={
            "test_data": unknown_baseline.test_data.model_copy(
                update={"restore_observed_hvac_state": True}
            )
        }
    )
    accepted = evaluate_checkpoint2(
        cp1_request(),
        cp2_analysis(),
        design.model_copy(update={"test_cases": [accepted_case]}),
        cp2_requirements(),
    )

    assert cp2_check(rejected, "CP2-015").status == CheckStatus.FAIL
    assert "실행 전 상태 저장·복원 표시 누락" in cp2_check(
        rejected, "CP2-015"
    ).message
    assert cp2_check(accepted, "CP2-015").status == CheckStatus.PASS


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


def test_final_review_note_does_not_pause_checkpoint2() -> None:
    design = cp2_valid_design().model_copy(
        update={"final_review_notes": ["운영 적용 시점은 최종 보고에서 확인한다."]}
    )

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-011").status == CheckStatus.PASS
    assert "후속 자동 실행을 막지 않는 참고·최종 검토 사항 1건" in cp2_check(result, "CP2-011").message
    schema_properties = pipeline.Agent2TestDesign.model_json_schema()["properties"]
    assert "최종_확인_사항" in schema_properties
    assert "중단_확인_사항" in schema_properties
    assert "제외_범위" in schema_properties
    assert "제외된_정보_부족" in schema_properties
    tc_schema = pipeline.ProductTestCaseCandidate.model_json_schema()["properties"]
    assert "common_qa_criteria" in tc_schema
    assert "independent_execution" in tc_schema
    assert "double_assert_policy" in tc_schema

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


def test_verify_central_path_can_use_existing_regression_without_new_candidate() -> None:
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
    design = cp2_valid_design().model_copy(
        update={
            "related_existing_tests": [
                *cp2_valid_design().related_existing_tests,
                ExistingTestSelection(
                    tc_id="TC-MODE-001",
                    source_condition_ids=["COND-004"],
                    selection_reason="유지되는 중앙 관제 적용 동작은 기존 TC로 회귀 확인한다.",
                ),
            ]
        }
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.PASS
    assert cp2_check(result, "CP2-008").status == CheckStatus.PASS
    assert cp2_check(result, "CP2-016").status == CheckStatus.PASS


def test_verify_only_requirement_cannot_be_duplicated_as_new_candidate() -> None:
    condition = ConfirmedCondition(
        condition_id="COND-004",
        statement="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
        source_type=ConditionSource.SRS,
        source_text="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
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
                    reason="기존 중앙 제어 회귀 확인",
                ),
            ],
        }
    )
    requirements = {
        **cp2_requirements(),
        "REQ-CONTROL-001": SrsRequirement(
            requirement_id="REQ-CONTROL-001",
            statement="중앙 관제 패널에서 기존 제어 명령을 적용한다.",
            acceptance_criteria="허용 대상에 기존 명령을 반영한다.",
        ),
    }
    base = cp2_valid_design().test_cases[0]
    verify_only = base.model_copy(
        update={
            "tc_id": "TC-CAND-002",
            "title": "기존 중앙 관제 적용 중복 후보",
            "test_type": TcType.NORMAL,
            "requirement_ids": ["REQ-CONTROL-001"],
            "source_condition_ids": ["COND-004"],
            "expected_results": [
                item.model_copy(update={"source_condition_ids": ["COND-004"]})
                for item in base.expected_results
            ],
            "feature_requirement_ids": ["REQ-CONTROL-001"],
        }
    )
    design = cp2_valid_design().model_copy(
        update={"test_cases": [*cp2_valid_design().test_cases, verify_only]}
    )

    result = evaluate_checkpoint2(cp1_request(), analysis, design, requirements)

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-016").status == CheckStatus.FAIL
    assert "VERIFY 유지 동작" in cp2_check(result, "CP2-016").message

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


def test_state_consistency_without_mode_or_temperature_data_is_allowed() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "test_type": TcType.STATE_CONSISTENCY,
            "test_data": StructuredTestData(),
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(
        cp1_request(), cp2_analysis(), design, cp2_requirements()
    )

    assert cp2_check(result, "CP2-010").status == CheckStatus.PASS


def test_boundary_tc_allows_initial_mode_as_execution_context() -> None:
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

    assert cp2_check(result, "CP2-010").status == CheckStatus.PASS

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


def test_missing_three_tier_quality_criteria_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "common_qa_criteria": [],
            "domain_qa_criteria": [],
            "feature_requirement_ids": [],
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-012").status == CheckStatus.FAIL


def test_tc_declared_non_independent_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={"independent_execution": False, "independence_reason": None}
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-013").status == CheckStatus.FAIL


def test_tc_negative_cross_tc_reference_is_accepted_as_independence_evidence() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "independence_reason": (
                "사전조건을 직접 구성하므로 이전 TC의 적용 또는 복원 결과에 "
                "의존하지 않고 독립적으로 실행한다."
            )
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-013").status == CheckStatus.PASS


def test_tc_positive_cross_tc_dependency_is_rejected() -> None:
    tc = cp2_valid_design().test_cases[0].model_copy(
        update={
            "preconditions": ["이전 TC가 완료한 장비 상태를 그대로 사용한다."],
            "independence_reason": "선행 테스트 결과를 이어받아 실행한다.",
        }
    )
    design = cp2_valid_design().model_copy(update={"test_cases": [tc]})

    result = evaluate_checkpoint2(cp1_request(), cp2_analysis(), design, cp2_requirements())

    assert cp2_check(result, "CP2-013").status == CheckStatus.FAIL


def test_partial_scope_exclusions_must_be_preserved_by_agent2() -> None:
    analysis = cp2_analysis().model_copy(
        update={
            "decision": AnalysisDecision.PARTIAL_PROCEED,
            "excluded_scope": ["정확한 차단 안내 문구"],
            "information_gaps": ["정확한 안내 문구가 정의되지 않음"],
            "excluded_information_gaps": ["정확한 안내 문구가 정의되지 않음"],
            "user_questions": ["차단 안내 문구를 확정해 주세요."],
        }
    )
    design = cp2_valid_design()

    result = evaluate_checkpoint2(cp1_request(), analysis, design, cp2_requirements())

    assert result.status == CheckStatus.FAIL
    assert cp2_check(result, "CP2-014").status == CheckStatus.FAIL

    preserved = design.model_copy(
        update={
            "excluded_scope": analysis.excluded_scope,
            "excluded_information_gaps": analysis.information_gaps,
        }
    )
    preserved_result = evaluate_checkpoint2(
        cp1_request(), analysis, preserved, cp2_requirements()
    )
    assert preserved_result.status == CheckStatus.PASS
    assert cp2_check(preserved_result, "CP2-014").status == CheckStatus.PASS


def test_agent2_preserves_setup_and_restore_notes_as_tc_procedures() -> None:
    setup_note = "첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작한다."
    restore_note = "시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다."
    request = cp1_request().model_copy(
        update={
            "acceptance_notes": [
                *cp1_request().acceptance_notes,
                setup_note,
                restore_note,
            ]
        }
    )
    analysis = cp2_analysis().model_copy(
        update={"excluded_scope": [setup_note, restore_note]}
    )
    incorrectly_excluded = cp2_valid_design().model_copy(
        update={"excluded_scope": [setup_note, restore_note]}
    )

    rejected = evaluate_checkpoint2(
        request, analysis, incorrectly_excluded, cp2_requirements()
    )

    assert cp2_check(rejected, "CP2-014").status == CheckStatus.FAIL

    base_tc = cp2_valid_design().test_cases[0]
    procedural_tc = base_tc.model_copy(
        update={
            "preconditions": [*base_tc.preconditions, setup_note],
            "restore_required": True,
            "restore_steps": [restore_note],
        }
    )
    preserved = cp2_valid_design().model_copy(
        update={"test_cases": [procedural_tc], "excluded_scope": []}
    )
    accepted = evaluate_checkpoint2(request, analysis, preserved, cp2_requirements())

    assert cp2_check(accepted, "CP2-014").status == CheckStatus.PASS


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
                    control_path=ControlPath.CENTRAL,
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
                    common_qa_criteria=[CommonQaCriterion.BOUNDARY_VALUE],
                    domain_qa_criteria=[DomainQaCriterion.TARGET_DEVICE_ACCURACY],
                    feature_requirement_ids=["REQ-TEMP-001"],
                    independent_execution=True,
                    independence_reason="사전조건에서 대상 장비의 모드와 초기 온도를 직접 구성한다.",
                    double_assert_policy=DoubleAssertPolicy.UI_ONLY,
                    double_assert_reason="이 단위 Fixture는 화면 경계 결과만 확인한다.",
                    restore_required=False,
                    restore_steps=[],
                    automation_candidate=True,
                    automation_reason="화면에서 요청 결과를 확인할 수 있다.",
            )
            return pipeline.Agent2Response(
                    design=Agent2TestDesign(
                        request_id=request.request_id,
                        existing_tc_comparison_completed=True,
                        related_existing_tests=[
                            ExistingTestSelection(
                                tc_id="TC-TEMP-001",
                                source_condition_ids=["COND-001"],
                                selection_reason="변경 대상 온도 정책의 기존 경계 TC를 회귀 확인한다.",
                            )
                        ],
                        test_cases=[tc],
                        srs_revision_proposals=[
                            pipeline.SrsRevisionProposal(
                                proposal_id="SRS-REV-001",
                                requirement_id="REQ-TEMP-001",
                                source_condition_ids=[
                                    "COND-001",
                                    "COND-002",
                                    "COND-003",
                                    "COND-005",
                                ],
                                current_acceptance_criteria=(
                                    "범위 안 요청은 반영되고 범위 밖 요청은 차단되며 "
                                    "화면·내부 설정 온도가 기존 값을 유지합니다."
                                ),
                                proposed_acceptance_criteria=(
                                    "AUTO 모드에서는 18~30°C 요청을 허용하고 범위 밖 요청은 "
                                    "차단하며 화면·내부 설정 온도가 기존 값을 유지합니다."
                                ),
                                reason="AUTO 모드 하한 변경을 SRS 인수 기준에 반영합니다.",
                            )
                        ],
                    coverage_summary="확정 조건을 변경 검증 TC에 연결했다.",
                    excluded_scope=analysis.excluded_scope,
                    excluded_information_gaps=analysis.information_gaps,
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
    catalog_snapshot = json.loads(
        (run_dir / "approved_regression_catalog.json").read_text(encoding="utf-8")
    )
    assert [item["tc_id"] for item in catalog_snapshot["approved_assets"]] == [
        "TC-V2-001"
    ]
    assert manifest["approved_regression_catalog_sha256"] == _sha256_file(
        run_dir / "approved_regression_catalog.json"
    )
    assert manifest["srs_revision_contract"] == "1.0"


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
            "automation_reason": "The central control-panel UI and internal state are observable.",
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
            AutomationAction(action_id="ACT-001", phase="PRECONDITION", action_type="SELECT_DEVICE", selector="#device-card-1 .card-body-split", value=1, source_text="Select an allowed device at AUTO 18 degrees."),
            AutomationAction(action_id="ACT-002", phase="PRECONDITION", action_type="SET_MODE", selector="#det-mode-auto", value="AUTO", source_text="Select an allowed device at AUTO 18 degrees."),
            AutomationAction(action_id="ACT-003", phase="PRECONDITION", action_type="SET_TEMPERATURE", selector="#det-temp-display", value=18.0, source_text="Select an allowed device at AUTO 18 degrees."),
            AutomationAction(action_id="ACT-004", phase="PRECONDITION", action_type="APPLY_COMMANDS", selector=".btn-apply-cmd", source_text="Select an allowed device at AUTO 18 degrees."),
            AutomationAction(action_id="ACT-005", phase="TEST", action_type="SET_TEMPERATURE", selector="#det-temp-display", value=17.0, source_text="Request 17 degrees and apply the pending command."),
            AutomationAction(action_id="ACT-006", phase="TEST", action_type="APPLY_COMMANDS", selector=".btn-apply-cmd", source_text="Request 17 degrees and apply the pending command."),
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
    assert responses.kwargs["prompt_cache_key"] == "qa-v2-agent3-3-18"
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
    assert "disabled or 비활성 grounds UI_ENABLED_EQUALS" in instructions
    assert "RESTORE_OBSERVED_HVAC" in instructions


def test_agent3_accepts_atomic_temperature_up_disabled_assertion() -> None:
    test_case = agent3_test_case()
    disabled_up = test_case.expected_results[0].model_copy(
        update={
            "statement": "온도 올림 버튼이 disabled 상태이다.",
        }
    )
    test_case = test_case.model_copy(
        update={
            "expected_results": [
                disabled_up,
                *test_case.expected_results[1:],
            ]
        }
    )
    plan = agent3_plan()
    enabled_assertion = plan.assertions[0].model_copy(
        update={
            "strategy": AssertionStrategy.UI_ENABLED_EQUALS,
            "selector": "#det-temp-up-btn",
            "expected_number": None,
            "expected_value": False,
        }
    )
    plan = plan.model_copy(
        update={"assertions": [enabled_assertion, *plan.assertions[1:]]}
    )
    observation = agent3_observation()
    observation = observation.model_copy(
        update={
            "elements": [
                item.model_copy(
                    update={"action_hint": "온도 올림 / Request one degree higher"}
                )
                if item.selector == "#det-temp-up-btn"
                else item
                for item in observation.elements
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)

    assert checkpoint.status == CheckStatus.PASS
    code = compile_automation_candidate(
        "RUN-20260826-133000-ABCDEF", test_case, plan
    )
    assert "#det-temp-up-btn" in code
    assert ".is_enabled()" in code


def test_agent3_eligibility_keeps_atomic_temperature_button_selectors() -> None:
    test_case = ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-004",
            "title": "잠금 후 온도 버튼 비활성화",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "STATE_CONSISTENCY",
            "requirement_ids": ["REQ-LOCK-001", "REQ-STATE-001"],
            "source_condition_ids": ["COND-001"],
            "control_path": "CENTRAL",
            "target_role": "PRIMARY_TEST_DEVICE",
            "test_data": {},
            "preconditions": ["대상 장비는 잠금 해제 상태이다."],
            "steps": ["대상 장비에 잠금 설정을 적용한다."],
            "expected_results": [
                {
                    "result_id": "ER-001",
                    "statement": "온도 내림 버튼이 disabled 상태이다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-001"],
                },
                {
                    "result_id": "ER-002",
                    "statement": "온도 올림 버튼이 disabled 상태이다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-001"],
                },
                {
                    "result_id": "ER-003",
                    "statement": "내부 locked 값이 활성화되어 있다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-001"],
                },
            ],
            "restore_required": True,
            "restore_steps": ["대상 장비의 잠금을 해제한다."],
            "automation_candidate": True,
            "automation_reason": "관찰된 UI와 내부 상태로 확인할 수 있다.",
        }
    )

    eligibility = evaluate_agent3_eligibility(test_case)

    assert "#det-temp-down-btn" in eligibility.required_selectors
    assert "#det-temp-up-btn" in eligibility.required_selectors
    assert "#device-card-1 .card-body-split" in eligibility.required_selectors
    assert ".btn-apply-cmd" in eligibility.required_selectors
    assert "selectedUnitId" in eligibility.required_harness_keys
    assert "devices" in eligibility.required_harness_keys
    assert "SELECT_PRIMARY_DEVICE" in eligibility.required_capabilities
    assert "APPLY_CENTRAL_COMMAND" in eligibility.required_capabilities
    assert "ASSERT_GENERIC_UI_STATE" in eligibility.required_capabilities


def test_agent3_allows_observed_initial_mode_without_reapplying() -> None:
    test_case = agent3_test_case()
    plan = agent3_plan().model_copy(
        update={
            "actions": [
                item
                for item in agent3_plan().actions
                if item.action_id not in {"ACT-002", "ACT-003", "ACT-004"}
            ]
        }
    )
    observation = agent3_observation().model_copy(
        update={
            "harness_values": {
                "window.__vccs.devices[0].mode": "AUTO",
                "window.__vccs.devices[0].setTemp": 18,
            }
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)

    assert checkpoint.status == CheckStatus.PASS
    sequence = next(
        item for item in checkpoint.checks if item.rule_id == "CP3-006A"
    )
    assert sequence.status == CheckStatus.PASS


def test_agent3_model_input_preview_is_minimal_and_has_no_local_path() -> None:
    requirements = {
        "REQ-TEMP-001": SrsRequirement(requirement_id="REQ-TEMP-001", statement="range", acceptance_criteria="block"),
        "REQ-UNRELATED-001": SrsRequirement(requirement_id="REQ-UNRELATED-001", statement="unrelated", acceptance_criteria="none"),
    }
    observation = agent3_observation().model_copy(
        update={
            "harness_values": {
                "window.__vccs.devices[0].setTemp": 18,
                "window.__vccs.unrelated.secretFlag": True,
            }
        }
    )
    payload = build_agent3_model_input(agent3_test_case(), observation, requirements)
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["destination"] == "OpenAI Responses API"
    assert payload["store"] is False
    assert set(payload["related_srs_requirements"]) == {"REQ-TEMP-001"}
    assert payload["ui_observation"]["target_file"] == "virtual-controller.html"
    assert set(payload["ui_observation"]["harness_values"]) == {
        "window.__vccs.devices[0].setTemp"
    }
    assert set(payload["ui_observation"]["device_state_fields"]) == {
        "mode",
        "setTemp",
    }
    korean_expected_results = [
        result.model_copy(
            update={
                "statement": "적용 후 내부 설정 온도는 18°C이며 기존 값과 일치합니다."
            }
        )
        if result.observation_layer == ObservationLayer.INTERNAL_STATE
        else result
        for result in agent3_test_case().expected_results
    ]
    korean_tc = agent3_test_case().model_copy(
        update={"expected_results": korean_expected_results}
    )
    korean_payload = build_agent3_model_input(korean_tc, observation, requirements)
    assert "setTemp" in korean_payload["ui_observation"]["device_state_fields"]
    assert "window.__vccs.devices[0].setTemp" in (
        korean_payload["ui_observation"]["harness_values"]
    )
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


def test_agent3_observation_records_verified_clean_execution_context(
    tmp_path: Path,
) -> None:
    target = tmp_path / "verified-context.html"
    target.write_text(
        """<!doctype html><html><head><title>Verified Context</title></head><body>
        <div id="device-card-1"><div class="card-body-split">IDU-00</div></div>
        <script>window.__vccs = {devices: [{id: 1, status: 'STOP', locked: false, errorCode: null}]};</script>
        </body></html>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors={"#device-card-1 .card-body-split"},
        required_harness_keys={"devices"},
    )

    context = observation.verified_execution_context
    assert context.clean_page_loaded is True
    assert context.target_device_visible is True
    assert context.device_state_available is True
    assert context.error_free is True
    assert context.unlocked is True
    preview = build_agent3_model_input(
        agent3_test_case(),
        observation,
        {
            "REQ-TEMP-001": SrsRequirement(
                requirement_id="REQ-TEMP-001",
                statement="range",
                acceptance_criteria="block",
            )
        },
    )
    assert preview["ui_observation"]["verified_execution_context"]["error_free"] is True


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


def test_agent3_verified_context_is_captured_after_delayed_interfaces(
    tmp_path: Path,
) -> None:
    target = tmp_path / "delayed-context.html"
    target.write_text(
        """<!doctype html><title>Delayed Context</title><body><script>
setTimeout(() => {
  document.body.insertAdjacentHTML('beforeend',
    '<div id="device-card-1"><div class="card-body-split">IDU-00</div></div>');
  window.__vccs = {devices: [{id: 1, status: 'STOP', locked: false, errorCode: null}]};
}, 100);
</script></body>""",
        encoding="utf-8",
    )

    observation = inspect_target_ui(
        target,
        required_selectors={"#device-card-1 .card-body-split"},
        required_harness_keys={"devices"},
    )

    context = observation.verified_execution_context
    assert context.target_device_visible is True
    assert context.device_state_available is True
    assert context.error_free is True
    assert context.unlocked is True


def test_agent3_local_control_path_is_excluded_before_ui_or_model() -> None:
    payload = agent3_test_case().model_dump(mode="json")
    payload["control_path"] = "LOCAL"
    test_case = ProductTestCaseCandidate.model_validate(payload)
    eligibility = evaluate_agent3_eligibility(test_case)

    assert eligibility.status == Agent3EligibilityStatus.NOT_AUTOMATABLE
    assert eligibility.model_call_allowed is False
    assert eligibility.generic_discovery_required is False
    assert eligibility.required_selectors == []
    assert eligibility.required_harness_keys == []
    assert "CENTRAL_CONTROL_PANEL_ONLY" in eligibility.missing_capabilities
    assert evaluate_checkpoint3_plan(
        test_case, agent3_plan(), agent3_observation()
    ).status == CheckStatus.FAIL
    with pytest.raises(pipeline.Agent3Error, match="CENTRAL control-panel"):
        compile_automation_candidate(
            "RUN-20260824-LOCALBLOCK-ABCDEF", test_case, agent3_plan()
        )


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
    assert eligibility.required_selectors == [
        "#device-card-1 .card-body-split",
        ".btn-apply-cmd",
    ]
    assert eligibility.required_harness_keys == ["devices", "selectedUnitId"]
    assert "SELECT_PRIMARY_DEVICE" in eligibility.required_capabilities
    assert "DISCOVER_GENERIC_UI" in eligibility.required_capabilities
    assert "SET_MODE" not in eligibility.required_capabilities


def test_agent3_textual_link_tolerates_korean_particles() -> None:
    assert pipeline._has_textual_link("적용", "적용을 실행한다.")
    assert pipeline._has_textual_link(
        "window vccs primaryTestDevice status",
        "PRIMARY_TEST_DEVICE의 내부 status가 OPERATION으로 변경된다.",
    )
    assert not pipeline._has_textual_link("삭제 버튼", "적용을 실행한다.")


def test_agent3_allows_dynamic_text_on_the_approved_target_device_card() -> None:
    test_case = ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-101",
            "title": "대상 장비 카드 풍량 표시와 내부 코드 검증",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "NORMAL",
            "requirement_ids": ["REQ-FAN-001"],
            "source_condition_ids": ["COND-101"],
            "control_path": "CENTRAL",
            "target_role": "PRIMARY_TEST_DEVICE",
            "test_data": {},
            "preconditions": ["오류와 잠금이 없는 단일 대상 장비를 준비한다."],
            "steps": [
                "대상 장비를 단일 선택한다.",
                "대상 장비의 풍량으로 HIGH를 선택하고 적용한다.",
                "대상 장비 카드의 풍량 표시를 확인한다.",
                "대상 장비의 내부 fanSpeed를 확인한다.",
            ],
            "expected_results": [
                {
                    "result_id": "ER-101",
                    "statement": "대상 장비 카드에 강풍이 표시된다.",
                    "observation_layer": "UI",
                    "source_condition_ids": ["COND-101"],
                    "verify_after_step": "대상 장비 카드의 풍량 표시를 확인한다.",
                },
                {
                    "result_id": "ER-102",
                    "statement": "대상 장비의 내부 fanSpeed는 HIGH이다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-101"],
                    "verify_after_step": "대상 장비의 내부 fanSpeed를 확인한다.",
                },
            ],
            "restore_required": False,
            "restore_steps": [],
            "automation_candidate": True,
            "automation_reason": "대상 카드와 내부 상태를 관찰할 수 있다.",
        }
    )
    observation = UiObservation(
        target_file="virtual-controller.html",
        target_sha256="a" * 64,
        page_title="Virtual Controller",
        elements=[
            ObservedUiElement(
                selector="#device-card-1 .card-body-split",
                tag="div",
                text="약풍",
                visible=True,
                enabled=True,
                action_hint="Select PRIMARY_TEST_DEVICE",
            ),
            ObservedUiElement(
                selector="#det-fan-high",
                tag="button",
                text="강풍",
                visible=True,
                enabled=True,
                action_hint="CLICK",
            ),
            ObservedUiElement(
                selector=".btn-apply-cmd",
                tag="button",
                text="적용",
                visible=True,
                enabled=True,
                action_hint="Apply pending commands",
            ),
            ObservedUiElement(
                selector="#device-card-1",
                tag="div",
                text="약풍",
                visible=True,
                enabled=True,
                action_hint="READ_STATE",
            ),
        ],
        harness_keys=["devices", "selectedUnitId"],
        harness_values={"window.__vccs.devices[0].fanSpeed": "LOW"},
        device_state_fields=["fanSpeed"],
        observed_at="2026-08-29T00:00:00+00:00",
    )
    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": "TC-CAND-101",
            "target_device_id": 1,
            "summary": "HIGH 풍량 적용 뒤 카드 표시와 내부 코드를 확인한다.",
            "actions": [
                {
                    "action_id": "ACT-101",
                    "phase": "TEST",
                    "action_type": "SELECT_DEVICE",
                    "selector": "#device-card-1 .card-body-split",
                    "value": 1,
                    "source_text": "대상 장비를 단일 선택한다.",
                },
                {
                    "action_id": "ACT-102",
                    "phase": "TEST",
                    "action_type": "CLICK",
                    "selector": "#det-fan-high",
                    "source_text": "대상 장비의 풍량으로 HIGH를 선택하고 적용한다.",
                },
                {
                    "action_id": "ACT-103",
                    "phase": "TEST",
                    "action_type": "APPLY_COMMANDS",
                    "selector": ".btn-apply-cmd",
                    "source_text": "대상 장비의 풍량으로 HIGH를 선택하고 적용한다.",
                },
            ],
            "assertions": [
                {
                    "result_id": "ER-101",
                    "observation_layer": "UI",
                    "strategy": "UI_TEXT_CONTAINS",
                    "selector": "#device-card-1",
                    "expected_text": "강풍",
                },
                {
                    "result_id": "ER-102",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
                    "selector": "window.__vccs.devices",
                    "expected_fields": [
                        {"field_name": "fanSpeed", "expected_value": "HIGH"}
                    ],
                },
            ],
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)

    assert checkpoint.status == CheckStatus.PASS
    assert next(
        item for item in checkpoint.checks if item.rule_id == "CP3-004"
    ).status == CheckStatus.PASS


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
    assert "#new-feature-toggle" in code
    assert "window.__vccs.feature.enabled" in code
    assert "#det-temp-display" not in code
    assert "#det-temp-up-btn" not in code
    assert "#det-temp-down-btn" not in code
    assert "window.__vccs.devices" not in code
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
        timeout_seconds=90,
    )
    assert trial.outcome == TrialOutcome.PASS


def test_grouped_hvac_trial_restores_runtime_baseline(tmp_path: Path) -> None:
    test_case = ProductTestCaseCandidate.model_validate(
        {
            "tc_id": "TC-CAND-099",
            "title": "묶음 모드·온도 조건 실행과 원래 상태 복원",
            "purpose": "CHANGE_VALIDATION",
            "test_type": "STATE_CONSISTENCY",
            "requirement_ids": ["REQ-MODE-001", "REQ-TEMP-001"],
            "source_condition_ids": ["COND-099"],
            "control_path": "CENTRAL",
            "target_role": "PRIMARY_TEST_DEVICE",
            "test_data": {
                "requested_modes": ["AUTO", "COOL"],
                "requested_temperatures_c": [18, 30],
                "restore_observed_hvac_state": True,
            },
            "condition_execution": "SEQUENTIAL_TRANSITION",
            "grouping_reason": "같은 장비의 모드·온도 전환 규칙을 순서대로 확인한다.",
            "preconditions": ["온라인 정상 장비를 단일 대상으로 선택한다."],
            "steps": [
                "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
            ],
            "expected_results": [
                {
                    "result_id": "ER-099",
                    "statement": "내부 mode 값은 AUTO이고 setTemp 값은 18이다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-099"],
                    "verify_after_step": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "result_id": "ER-100",
                    "statement": "내부 mode 값은 COOL이고 setTemp 값은 30이다.",
                    "observation_layer": "INTERNAL_STATE",
                    "source_condition_ids": ["COND-099"],
                    "verify_after_step": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
            ],
            "restore_required": True,
            "restore_steps": [
                "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다."
            ],
            "automation_candidate": True,
            "automation_reason": "관찰된 중앙 관제 모드·온도 UI와 내부 상태를 사용한다.",
        }
    )
    eligibility = evaluate_agent3_eligibility(test_case)
    target = REPO_ROOT / "product_baseline" / "virtual-controller.html"
    target_hash = _sha256_file(target)
    observation = inspect_target_ui(
        target,
        required_selectors=set(eligibility.required_selectors),
        required_harness_keys=set(eligibility.required_harness_keys),
        discover_generic=eligibility.generic_discovery_required,
    )
    plan = Agent3AutomationPlan.model_validate(
        {
            "tc_id": test_case.tc_id,
            "target_device_id": 1,
            "summary": "두 조건을 판정한 뒤 실행 직전 HVAC 상태를 복원한다.",
            "actions": [
                {
                    "action_id": "ACT-090",
                    "phase": "PRECONDITION",
                    "action_type": "SELECT_DEVICE",
                    "selector": "#device-card-1 .card-body-split",
                    "value": 1,
                    "source_text": "온라인 정상 장비를 단일 대상으로 선택한다.",
                },
                {
                    "action_id": "ACT-091",
                    "phase": "TEST",
                    "action_type": "SET_MODE",
                    "selector": "#det-mode-auto",
                    "value": "AUTO",
                    "source_text": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-092",
                    "phase": "TEST",
                    "action_type": "SET_TEMPERATURE",
                    "selector": "#det-temp-display",
                    "value": 18,
                    "source_text": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-093",
                    "phase": "TEST",
                    "action_type": "APPLY_COMMANDS",
                    "selector": ".btn-apply-cmd",
                    "source_text": "AUTO 모드와 18도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-094",
                    "phase": "TEST",
                    "action_type": "SET_MODE",
                    "selector": "#det-mode-cool",
                    "value": "COOL",
                    "source_text": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-095",
                    "phase": "TEST",
                    "action_type": "SET_TEMPERATURE",
                    "selector": "#det-temp-display",
                    "value": 30,
                    "source_text": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-096",
                    "phase": "TEST",
                    "action_type": "APPLY_COMMANDS",
                    "selector": ".btn-apply-cmd",
                    "source_text": "COOL 모드와 30도를 선택하고 중앙 관제 명령을 적용한다.",
                },
                {
                    "action_id": "ACT-097",
                    "phase": "RESTORE",
                    "action_type": "RESTORE_OBSERVED_HVAC",
                    "selector": ".btn-apply-cmd",
                    "source_text": "실행 직전 관찰한 모드와 설정 온도로 복원하고 중앙 관제 명령을 적용한다.",
                },
            ],
            "assertions": [
                {
                    "result_id": "ER-099",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
                    "selector": "window.__vccs.devices",
                    "expected_fields": [
                        {"field_name": "mode", "expected_value": "AUTO"},
                        {"field_name": "setTemp", "expected_value": 18},
                    ],
                    "after_action_id": "ACT-093",
                },
                {
                    "result_id": "ER-100",
                    "observation_layer": "INTERNAL_STATE",
                    "strategy": "INTERNAL_DEVICE_FIELDS_EQUALS",
                    "selector": "window.__vccs.devices",
                    "expected_fields": [
                        {"field_name": "mode", "expected_value": "COOL"},
                        {"field_name": "setTemp", "expected_value": 30},
                    ],
                    "after_action_id": "ACT-096",
                },
            ],
        }
    )

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, observation)
    assert checkpoint.status == CheckStatus.PASS
    code = compile_automation_candidate(
        "RUN-20260827-130000-ABCDEF", test_case, plan
    )
    assert "observed_hvac_baseline" in code
    assert "restored_hvac_state != observed_hvac_baseline" in code
    assert all(
        item.status == CheckStatus.PASS
        for item in evaluate_compiled_candidate(test_case, code)
    )
    candidate = tmp_path / "test_dynamic_hvac_restore.py"
    candidate.write_text(code, encoding="utf-8")
    trial = run_candidate_trial(
        candidate,
        target,
        tmp_path / "dynamic-hvac-evidence",
        timeout_seconds=90,
    )

    assert trial.outcome == TrialOutcome.PASS
    assert _sha256_file(target) == target_hash


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

    test_phase_selection = plan.actions[0].model_copy(
        update={
            "phase": AutomationPhase.TEST,
            "source_text": tc.steps[0],
        }
    )
    test_phase_plan = plan.model_copy(
        update={
            "actions": [
                *plan.actions[1:4],
                test_phase_selection,
                *plan.actions[4:],
            ]
        }
    )
    test_phase_checkpoint = evaluate_checkpoint3_plan(
        tc, test_phase_plan, agent3_observation()
    )
    assert test_phase_checkpoint.status == CheckStatus.PASS

    late_selection_plan = test_phase_plan.model_copy(
        update={
            "actions": [
                *test_phase_plan.actions[:3],
                test_phase_plan.actions[4],
                test_phase_plan.actions[3],
                *test_phase_plan.actions[5:],
            ]
        }
    )
    late_selection_checkpoint = evaluate_checkpoint3_plan(
        tc, late_selection_plan, agent3_observation()
    )
    assert late_selection_checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-006A"
        and "selection occurs after" in item.message
        for item in late_selection_checkpoint.checks
    )


def grouped_agent3_case_and_plan() -> tuple[ProductTestCaseCandidate, Agent3AutomationPlan]:
    base_case = agent3_test_case()
    lower_step = base_case.steps[0]
    reset_step = "Reset AUTO temperature to 30 degrees for an independent upper-bound check."
    upper_step = "Request 31 degrees and apply the pending command."
    expected_results = [
        result.model_copy(update={"verify_after_step": lower_step})
        for result in base_case.expected_results
    ]
    expected_results.append(
        ExpectedResult(
            result_id="ER-008",
            statement="UI remains at 30 degrees.",
            observation_layer=ObservationLayer.UI,
            source_condition_ids=["COND-001"],
            verify_after_step=upper_step,
        )
    )
    test_case = base_case.model_copy(
        update={
            "test_data": base_case.test_data.model_copy(
                update={
                    "requested_temperature_c": None,
                    "requested_temperatures_c": [17.0, 30.0, 31.0],
                }
            ),
            "condition_execution": pipeline.ConditionExecution.INDEPENDENT_VARIANTS,
            "grouping_reason": "Both variants verify one AUTO temperature-range rule.",
            "intermediate_reset_steps": [reset_step],
            "steps": [lower_step, reset_step, upper_step],
            "expected_results": expected_results,
        }
    )
    base_plan = agent3_plan()
    anchored_assertions = [
        assertion.model_copy(update={"after_action_id": "ACT-006"})
        for assertion in base_plan.assertions
    ]
    anchored_assertions.append(
        AutomationAssertion(
            result_id="ER-008",
            observation_layer=ObservationLayer.UI,
            strategy=AssertionStrategy.UI_TEMPERATURE,
            selector="#det-temp-display",
            expected_number=30.0,
            after_action_id="ACT-010",
        )
    )
    plan = base_plan.model_copy(
        update={
            "actions": [
                *base_plan.actions,
                AutomationAction(
                    action_id="ACT-007",
                    phase=AutomationPhase.TEST,
                    action_type=AutomationActionType.SET_TEMPERATURE,
                    selector="#det-temp-display",
                    value=30.0,
                    source_text=reset_step,
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase=AutomationPhase.TEST,
                    action_type=AutomationActionType.APPLY_COMMANDS,
                    selector=".btn-apply-cmd",
                    source_text=reset_step,
                ),
                AutomationAction(
                    action_id="ACT-009",
                    phase=AutomationPhase.TEST,
                    action_type=AutomationActionType.SET_TEMPERATURE,
                    selector="#det-temp-display",
                    value=31.0,
                    source_text=upper_step,
                ),
                AutomationAction(
                    action_id="ACT-010",
                    phase=AutomationPhase.TEST,
                    action_type=AutomationActionType.APPLY_COMMANDS,
                    selector=".btn-apply-cmd",
                    source_text=upper_step,
                ),
            ],
            "assertions": anchored_assertions,
        }
    )
    return test_case, plan


def test_agent3_grouped_tc_interleaves_assertions_before_next_condition() -> None:
    test_case, plan = grouped_agent3_case_and_plan()

    checkpoint = evaluate_checkpoint3_plan(test_case, plan, agent3_observation())
    code = compile_automation_candidate(
        "RUN-20260825-GROUPED-ABCDEF", test_case, plan
    )

    assert checkpoint.status == CheckStatus.PASS
    assert next(
        item for item in checkpoint.checks if item.rule_id == "CP3-003A"
    ).status == CheckStatus.PASS
    assert code.index("# ACT-006") < code.index("# EXPECTED_RESULT: ER-005")
    assert code.index("# EXPECTED_RESULT: ER-007") < code.index("# ACT-007")
    assert code.index("# ACT-010") < code.index("# EXPECTED_RESULT: ER-008")
    assert "_request_temperature(page, 17.0)" in code
    assert "_set_temperature(page, 30.0)" in code
    assert "_request_temperature(page, 31.0)" in code


def test_agent3_grouped_tc_rejects_unanchored_condition_results() -> None:
    test_case, plan = grouped_agent3_case_and_plan()
    unanchored = plan.model_copy(
        update={
            "assertions": [
                assertion.model_copy(update={"after_action_id": None})
                for assertion in plan.assertions
            ]
        }
    )

    checkpoint = evaluate_checkpoint3_plan(
        test_case, unanchored, agent3_observation()
    )

    assert checkpoint.status == CheckStatus.FAIL
    check = next(
        item for item in checkpoint.checks if item.rule_id == "CP3-003A"
    )
    assert check.status == CheckStatus.FAIL
    assert "no after_action_id" in check.message

    early_assertions = list(plan.assertions)
    early_assertions[0] = early_assertions[0].model_copy(
        update={"after_action_id": "ACT-005"}
    )
    early_checkpoint = evaluate_checkpoint3_plan(
        test_case,
        plan.model_copy(update={"assertions": early_assertions}),
        agent3_observation(),
    )
    early_check = next(
        item for item in early_checkpoint.checks if item.rule_id == "CP3-003A"
    )
    assert early_check.status == CheckStatus.FAIL
    assert "not anchored after the last action" in early_check.message


def test_legacy_central_plan_cannot_bypass_required_actions_with_generic_assertion() -> None:
    base = agent3_plan()
    plan = base.model_copy(
        update={
            "actions": [base.actions[-1]],
            "assertions": [
                base.assertions[0],
                base.assertions[1],
                AutomationAssertion(
                    result_id="ER-007",
                    observation_layer="NOTIFICATION",
                    strategy="UI_TEXT_CONTAINS",
                    selector="#global-toast",
                    expected_text="Toast",
                ),
            ],
        }
    )

    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(), plan, agent3_observation()
    )

    assert checkpoint.status == CheckStatus.FAIL
    sequence_check = next(
        item for item in checkpoint.checks if item.rule_id == "CP3-006A"
    )
    assert sequence_check.status == CheckStatus.FAIL
    assert "target device selection is missing" in sequence_check.message
    assert "requested temperature action is missing" in sequence_check.message


def test_specialized_action_source_text_must_be_an_approved_tc_line() -> None:
    base = agent3_plan()
    actions = list(base.actions)
    actions[0] = actions[0].model_copy(
        update={"source_text": "Model-invented setup step"}
    )

    checkpoint = evaluate_checkpoint3_plan(
        agent3_test_case(),
        base.model_copy(update={"actions": actions}),
        agent3_observation(),
    )

    assert checkpoint.status == CheckStatus.FAIL
    assert any(
        item.rule_id == "CP3-002"
        and "source_text is not an exact approved TC line" in item.message
        for item in checkpoint.checks
    )

def test_blocked_temperature_request_compiles_until_target_or_stall() -> None:
    code = compile_automation_candidate(
        "RUN-20260813-120000-ABCDEF", agent3_test_case(), agent3_plan()
    )
    assert "def _request_temperature(page, target):" in code
    assert "if after == before:" in code
    assert "_request_temperature(page, 17.0)" in code


def test_central_blocked_temperature_without_notification_uses_stall_request() -> None:
    test_case_payload = agent3_test_case().model_dump(mode="json")
    test_case_payload["expected_results"] = test_case_payload["expected_results"][:2]
    plan_payload = agent3_plan().model_dump(mode="json")
    plan_payload["assertions"] = plan_payload["assertions"][:2]

    test_case = ProductTestCaseCandidate.model_validate(test_case_payload)
    plan = Agent3AutomationPlan.model_validate(plan_payload)
    checkpoint = evaluate_checkpoint3_plan(test_case, plan, agent3_observation())
    code = compile_automation_candidate(
        "RUN-20260823-CENTRAL-ABCDEF", test_case, plan
    )

    assert checkpoint.status == CheckStatus.PASS
    assert "_request_temperature(page, 17.0)" in code
    assert "simulateLocalTemp" not in code
    assert "#qa-drawer-panel" not in code
    compile(code, "<central-candidate>", "exec")


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
                    source_text="Restore AUTO 18 and verify UI and internal state.",
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase="RESTORE",
                    action_type="APPLY_COMMANDS",
                    selector=".btn-apply-cmd",
                    source_text="Restore AUTO 18 and verify UI and internal state.",
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
                    source_text="Restore AUTO 18 and verify UI and internal state.",
                ),
                AutomationAction(
                    action_id="ACT-008",
                    phase="RESTORE",
                    action_type="APPLY_COMMANDS",
                    selector=".btn-apply-cmd",
                    source_text="Restore AUTO 18 and verify UI and internal state.",
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
    assert set(trial.evidence_sha256) == {
        "trial-stdout.txt",
        "trial-stderr.txt",
        "trial-final.png",
        "trial-trace.zip",
    }
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

    def fake_run(_command, *, cwd, env, timeout_seconds):
        assert timeout_seconds == 5
        captured_env.update(env)
        local_path = str(target.resolve())
        temp_path = str(Path(cwd).resolve())
        return SimpleNamespace(
            returncode=1,
            stdout=f"한글 실행 증거\n{local_path}\n{temp_path}",
            stderr="",
        )

    for name in ("OPENAI_API_KEY", "SLACK_WEBHOOK_URL", "NOTION_API_KEY", "NOTION_TOKEN", "GITHUB_TOKEN"):
        monkeypatch.setenv(name, "must-not-reach-trial")
    monkeypatch.setattr(pipeline, "_run_trial_subprocess", fake_run)

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


def test_agent3_timeout_discards_incomplete_unredacted_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    candidate = tmp_path / "candidate.py"
    candidate.write_text("def test_candidate():\n    pass\n", encoding="utf-8")
    target = tmp_path / "target.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    evidence = tmp_path / "evidence"

    def fake_timeout(command, *, cwd, env, timeout_seconds):
        trace = Path(env["QA_EVIDENCE_DIR"]) / "trial-trace.zip"
        trace.write_bytes(b"incomplete trace with unredacted local data")
        raise subprocess.TimeoutExpired(command, timeout_seconds)

    monkeypatch.setattr(pipeline, "_run_trial_subprocess", fake_timeout)
    result = run_candidate_trial(
        candidate,
        target,
        evidence,
        timeout_seconds=5,
    )

    assert result.outcome == TrialOutcome.TIMEOUT
    assert result.trace_file is None
    assert result.evidence_complete is False
    assert not (evidence / "trial-trace.zip").exists()


def test_trial_timeout_terminates_playwright_child_processes(tmp_path: Path) -> None:
    psutil = pytest.importorskip("psutil")
    child_pid_file = tmp_path / "child.pid"
    parent_script = (
        "import subprocess,sys,time; from pathlib import Path; "
        "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        "Path(sys.argv[1]).write_text(str(child.pid), encoding='utf-8'); time.sleep(30)"
    )

    with pytest.raises(subprocess.TimeoutExpired):
        pipeline._run_trial_subprocess(
            [sys.executable, "-c", parent_script, str(child_pid_file)],
            cwd=tmp_path,
            env=dict(os.environ),
            timeout_seconds=2,
        )

    child_pid = int(child_pid_file.read_text(encoding="utf-8"))
    for _ in range(20):
        if not psutil.pid_exists(child_pid):
            break
        time.sleep(0.05)
    assert not psutil.pid_exists(child_pid)


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
        screenshot_file="trial-final.png",
        trace_file="trial-trace.zip",
        evidence_sha256={
            "trial-stdout.txt": "a" * 64,
            "trial-stderr.txt": "b" * 64,
            "trial-final.png": "c" * 64,
            "trial-trace.zip": "d" * 64,
        },
        evidence_complete=True,
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
    incomplete = _trial(TrialOutcome.PASS).model_copy(
        update={"evidence_complete": False, "evidence_sha256": {}}
    )
    assert pipeline._agent3_cli_exit_code(
        _checkpoint3(CheckStatus.PASS), incomplete
    ) == 2
    extra_hash = _trial(TrialOutcome.PASS).model_copy(
        update={
            "evidence_sha256": {
                **_trial(TrialOutcome.PASS).evidence_sha256,
                "not-recorded.txt": "e" * 64,
            }
        }
    )
    assert pipeline._agent3_cli_exit_code(
        _checkpoint3(CheckStatus.PASS), extra_hash
    ) == 2


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


def test_model_usage_records_cache_and_reasoning_details() -> None:
    response = SimpleNamespace(
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=30,
            total_tokens=130,
            input_tokens_details=SimpleNamespace(
                cached_tokens=80,
                cache_write_tokens=20,
            ),
            output_tokens_details=SimpleNamespace(reasoning_tokens=12),
        )
    )

    usage = pipeline._response_usage_summary(response)

    assert usage == {
        "input_tokens": 100,
        "output_tokens": 30,
        "total_tokens": 130,
        "cached_input_tokens": 80,
        "cache_write_input_tokens": 20,
        "reasoning_output_tokens": 12,
    }
    assert pipeline._aggregate_model_usage(
        [{"usage": usage}, {"usage": usage}]
    )["cached_input_tokens"] == 160


def test_agent2_duplicate_technical_ids_are_normalized_without_semantic_changes() -> None:
    first = agent2_design().test_cases[0]
    second = first.model_copy(update={"title": "독립적인 두 번째 경계값 검증"})
    original = Agent2TestDesign(
        request_id="CR-TEST-001",
        test_cases=[first, second],
        coverage_summary="중복 기술 ID 정리 검증",
    )

    normalized, changes = pipeline._normalize_agent2_technical_ids(original)

    assert [item.tc_id for item in original.test_cases] == [
        "TC-CAND-001",
        "TC-CAND-001",
    ]
    assert [item.tc_id for item in normalized.test_cases] == [
        "TC-CAND-001",
        "TC-CAND-002",
    ]
    assert [
        result.result_id
        for item in normalized.test_cases
        for result in item.expected_results
    ] == [f"ER-{index:03d}" for index in range(1, 7)]
    assert changes

    def without_technical_ids(test_case):
        payload = test_case.model_dump(mode="json")
        payload.pop("tc_id")
        for result in payload["expected_results"]:
            result.pop("result_id")
        return payload

    assert [without_technical_ids(item) for item in normalized.test_cases] == [
        without_technical_ids(item) for item in original.test_cases
    ]


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
    assert args.timeout == 90
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


def test_agent3_selection_excludes_related_regression_candidates() -> None:
    changed = agent3_test_case()
    related = changed.model_copy(
        update={
            "tc_id": "TC-CAND-009",
            "purpose": TcPurpose.RELATED_REGRESSION,
        }
    )

    selected, summaries = pipeline._select_agent3_tcs(
        Agent2TestDesign(
            request_id="CR-TEST-001",
            test_cases=[related, changed],
            coverage_summary="변경분과 기존 회귀 분리",
        )
    )

    assert selected == [changed.tc_id]
    related_summary = next(item for item in summaries if item["tc_id"] == related.tc_id)
    assert related_summary["status"] == "NOT_AUTOMATABLE"
    assert "다시 구현하지 않고" in related_summary["missing_capabilities"][0]


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
        artifact_dir = Path(stage_args.artifact_dir)
        artifact_dir.mkdir(parents=True)
        _write_json(
            artifact_dir / "agent3_manifest.json",
            {
                "run_id": stage_args.run_id,
                "candidate_status": "PRODUCT_MISMATCH_DETECTED",
            },
        )
        _write_json(
            artifact_dir / "agent3_trial.json",
            {"outcome": "PRODUCT_MISMATCH_CANDIDATE"},
        )
        return 0

    monkeypatch.setattr(pipeline, "run_agent1", fake_agent1)
    monkeypatch.setattr(pipeline, "run_agent2", fake_agent2)
    monkeypatch.setattr(pipeline, "run_agent3", fake_agent3)
    monkeypatch.setattr(
        pipeline,
        "_select_agent3_tcs_from_run",
        lambda _run_dir, _run_id: (
            ["TC-CAND-003"],
            [
                {
                    "tc_id": "TC-CAND-003",
                    "automation_candidate": True,
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
    assert manifest["selected_tc_ids"] == ["TC-CAND-003"]
    assert manifest["executed_tc_ids"] == ["TC-CAND-003"]
    assert manifest["agent3_selection_sha256"] == _sha256_file(
        run_dir / "agent3_selection.json"
    )
    assert manifest["agent1_manifest_sha256"] == _sha256_file(
        run_dir / "run_manifest.json"
    )
    assert manifest["agent2_manifest_sha256"] == _sha256_file(
        run_dir / "agent2_manifest.json"
    )
    assert manifest["agent3_run_summary_sha256"] == _sha256_file(
        run_dir / "agent3_run_summary.json"
    )


def test_pipeline_continues_after_one_agent3_candidate_is_excluded(
    tmp_path: Path, monkeypatch
) -> None:
    args = _pipeline_args(tmp_path)
    Path(args.request).write_text("{}", encoding="utf-8")
    Path(args.target_html).write_text("<html></html>", encoding="utf-8")
    calls: list[str] = []

    def fake_agent1(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        run_dir.mkdir(parents=True)
        _write_json(run_dir / "run_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent2(stage_args) -> int:
        run_dir = Path(stage_args.runs_root) / stage_args.run_id
        _write_json(run_dir / "agent2_manifest.json", {"run_id": stage_args.run_id})
        return 0

    def fake_agent3(stage_args) -> int:
        calls.append(stage_args.tc_id)
        artifact_dir = Path(stage_args.artifact_dir)
        artifact_dir.mkdir(parents=True)
        if stage_args.tc_id == "TC-CAND-003":
            _write_json(
                artifact_dir / "agent3_automation_plan.json",
                {
                    "planning_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
                    "extension_reasons": ["화면 상태 관찰 방법이 없습니다."],
                },
            )
            _write_json(
                artifact_dir / "agent3_manifest.json",
                {
                    "run_id": stage_args.run_id,
                    "status": "REVIEW",
                    "candidate_status": "AUTOMATION_SUPPORT_EXTENSION_REQUIRED",
                },
            )
            return 2
        _write_json(
            artifact_dir / "agent3_manifest.json",
            {
                "run_id": stage_args.run_id,
                "status": "PASS",
                "candidate_status": "READY_FOR_EXECUTION",
            },
        )
        _write_json(artifact_dir / "agent3_trial.json", {"outcome": "PASS"})
        return 0

    monkeypatch.setattr(pipeline, "run_agent1", fake_agent1)
    monkeypatch.setattr(pipeline, "run_agent2", fake_agent2)
    monkeypatch.setattr(pipeline, "run_agent3", fake_agent3)
    monkeypatch.setattr(
        pipeline,
        "_select_agent3_tcs_from_run",
        lambda _run_dir, _run_id: (
            ["TC-CAND-003", "TC-CAND-004"],
            [
                {
                    "tc_id": tc_id,
                    "automation_candidate": True,
                    "status": "ELIGIBLE",
                    "missing_capabilities": [],
                }
                for tc_id in ("TC-CAND-003", "TC-CAND-004")
            ],
        ),
    )

    assert pipeline.run_pipeline(args) == 0
    assert calls == ["TC-CAND-003", "TC-CAND-004"]
    run_dir = next((tmp_path / "runs").iterdir())
    summary = json.loads(
        (run_dir / "agent3_run_summary.json").read_text(encoding="utf-8")
    )
    assert summary["status"] == "PARTIAL"
    assert summary["executed_tc_ids"] == ["TC-CAND-004"]
    assert [item["tc_id"] for item in summary["자동화_제외_TC"]] == [
        "TC-CAND-003"
    ]


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
    if source == pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE:
        source_outcome = {
            pipeline.NeutralExecutionStatus.PASSED: "PASS",
            pipeline.NeutralExecutionStatus.ASSERTION_FAILED: (
                "PRODUCT_MISMATCH_CANDIDATE"
            ),
            pipeline.NeutralExecutionStatus.EXECUTION_ERROR: "AUTOMATION_ERROR",
            pipeline.NeutralExecutionStatus.TIMEOUT: "TIMEOUT",
            pipeline.NeutralExecutionStatus.SKIPPED: "AUTOMATION_ERROR",
        }[status]
    else:
        source_outcome = {
            pipeline.NeutralExecutionStatus.PASSED: "PYTEST_PASSED",
            pipeline.NeutralExecutionStatus.ASSERTION_FAILED: "PYTEST_FAILED",
            pipeline.NeutralExecutionStatus.EXECUTION_ERROR: "PYTEST_ERROR",
            pipeline.NeutralExecutionStatus.TIMEOUT: "PYTEST_TIMEOUT",
            pipeline.NeutralExecutionStatus.SKIPPED: "PYTEST_SKIPPED",
        }[status]
    evidence_files = ["evidence/stdout.txt", "evidence/stderr.txt"]
    if source == pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE:
        evidence_files.extend(["evidence/final.png", "evidence/trace.zip"])
    return pipeline.NeutralExecutionResult(
        test_id=test_id,
        source=source,
        requirement_ids=["REQ-ENV-001"] if test_id == "TC-ENV-000" else ["REQ-TEMP-001"],
        status=status,
        source_outcome=source_outcome,
        exit_code=(
            None
            if status == pipeline.NeutralExecutionStatus.TIMEOUT
            else 0
            if status in {
                pipeline.NeutralExecutionStatus.PASSED,
                pipeline.NeutralExecutionStatus.SKIPPED,
            }
            else 1
        ),
        duration_ms=1,
        test_file="test_controller.py",
        test_sha256="a" * 64,
        target_sha256="b" * 64,
        reused=source == pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE,
        stdout_file="evidence/stdout.txt",
        stderr_file="evidence/stderr.txt",
        evidence_files=evidence_files,
        evidence_sha256={name: "c" * 64 for name in evidence_files},
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


def test_agent2_verify_regressions_are_added_deterministically() -> None:
    analysis = agent1_analysis().model_copy(
        update={
            "confirmed_conditions": [
                *agent1_analysis().confirmed_conditions,
                ConfirmedCondition(
                    condition_id="COND-002",
                    statement="화면과 내부 장비 상태의 공통 값이 같다.",
                    source_type=ConditionSource.SRS,
                    source_text="화면과 내부 장비 상태의 공통 값이 같습니다.",
                    requirement_ids=["REQ-STATE-001"],
                ),
            ],
            "requirement_effects": [
                *agent1_analysis().requirement_effects,
                RequirementEffect(
                    requirement_id="REQ-STATE-001",
                    relation=RequirementRelation.VERIFY,
                    reason="변경 뒤에도 기존 화면·내부 상태 정합성을 확인한다.",
                ),
            ],
        }
    )
    design = agent2_design().model_copy(update={"related_existing_tests": []})

    normalized, changes = pipeline._normalize_agent2_verify_regressions(
        analysis, design
    )
    repeated, repeated_changes = pipeline._normalize_agent2_verify_regressions(
        analysis, normalized
    )

    assert [item.tc_id for item in normalized.related_existing_tests] == [
        "TC-MODE-001"
    ]
    assert normalized.related_existing_tests[0].source_condition_ids == ["COND-002"]
    assert changes[0]["reason"] == "AGENT1_VERIFY_RELATION"
    assert repeated == normalized
    assert repeated_changes == []


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
    observation = agent3_observation()
    plan = agent3_plan()
    code = compile_automation_candidate(run_id, tc, plan)
    checkpoint = evaluate_checkpoint3_plan(tc, plan, observation)
    checkpoint.checks.extend(evaluate_compiled_candidate(tc, code))
    agent2_manifest = {"agent2_design_sha256": "b" * 64}
    _write_json(run_dir / "agent2_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_eligibility.json", {})
    _write_json(
        run_dir / "agent3_ui_observation.json",
        observation.model_dump(mode="json"),
    )
    _write_json(
        run_dir / "agent3_automation_plan.json", plan.model_dump(mode="json")
    )
    _write_json(
        run_dir / "checkpoint3.json",
        checkpoint.model_dump(mode="json"),
    )
    candidate = candidate_dir / "test_tc_cand_003.py"
    candidate.write_text(code, encoding="utf-8")
    (evidence_dir / "trial-stdout.txt").write_text("1 passed\n", encoding="utf-8")
    (evidence_dir / "trial-stderr.txt").write_text("", encoding="utf-8")
    (evidence_dir / "trial-final.png").write_bytes(b"png")
    (evidence_dir / "trial-trace.zip").write_bytes(b"zip")
    evidence_sha256 = {
        path.name: _sha256_file(path)
        for path in evidence_dir.iterdir()
        if path.is_file()
    }
    trial = _trial(TrialOutcome.PASS).model_copy(
        update={
            "exit_code": 0,
            "evidence_complete": True,
            "screenshot_file": "trial-final.png",
            "trace_file": "trial-trace.zip",
            "evidence_sha256": evidence_sha256,
        }
    )
    _write_json(run_dir / "agent3_trial.json", trial.model_dump(mode="json"))
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
            "trial_evidence_sha256": evidence_sha256,
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


def test_candidate_handoff_recomputes_current_cp3_rules(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, target, run_id = _build_candidate_execution_handoff(
        tmp_path, monkeypatch
    )
    plan_file = run_dir / "agent3_automation_plan.json"
    plan = Agent3AutomationPlan.model_validate_json(
        plan_file.read_text(encoding="utf-8")
    )
    weakened = plan.model_copy(update={"actions": [plan.actions[-1]]})
    _write_json(plan_file, weakened.model_dump(mode="json"))
    manifest_file = run_dir / "agent3_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["automation_plan_sha256"] = _sha256_file(plan_file)
    _write_json(manifest_file, manifest)

    with pytest.raises(ValueError, match="현재 CP3 규칙"):
        pipeline._candidate_execution_record(run_dir, run_id, target)


def test_candidate_handoff_rejects_evidence_changed_after_agent3(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, target, run_id = _build_candidate_execution_handoff(
        tmp_path, monkeypatch
    )
    evidence_file = run_dir / "evidence" / "TC-CAND-003" / "trial-stdout.txt"
    evidence_file.write_text("changed after Agent 3\n", encoding="utf-8")

    with pytest.raises(ValueError, match="시험 증거 SHA-256"):
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
    assert (
        run_dir / "validation_candidate_trials" / "TC-CAND-003.json"
    ).is_file()


def test_current_candidate_trial_returns_technical_failure_for_agent4(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-015500-ABCDEF"
    run_dir = tmp_path / run_id
    run_dir.mkdir()
    target = tmp_path / "virtual-controller.html"
    target.write_text("<!doctype html>", encoding="utf-8")
    test_case = agent3_test_case()
    plan = agent3_plan()
    _write_json(
        run_dir / "agent3_automation_plan.json", plan.model_dump(mode="json")
    )
    stored = _neutral_execution_result(
        test_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    ).model_copy(update={"test_sha256": "f" * 64})

    def failed_trial(_candidate_file, _target, evidence_dir, *, timeout_seconds):
        assert timeout_seconds == 10
        evidence_dir.mkdir(parents=True)
        stdout = evidence_dir / "trial-stdout.txt"
        stderr = evidence_dir / "trial-stderr.txt"
        stdout.write_text("locator failed\n", encoding="utf-8")
        stderr.write_text("PlaywrightError\n", encoding="utf-8")
        return pipeline.Agent3TrialResult(
            outcome=TrialOutcome.AUTOMATION_ERROR,
            exit_code=1,
            duration_ms=1,
            stdout_file=stdout.name,
            stderr_file=stderr.name,
            evidence_sha256={
                stdout.name: _sha256_file(stdout),
                stderr.name: _sha256_file(stderr),
            },
            evidence_complete=False,
        )

    monkeypatch.setattr(pipeline, "run_candidate_trial", failed_trial)
    result = pipeline._current_candidate_execution_record(
        run_dir,
        run_id,
        target,
        test_case,
        stored,
        timeout_seconds=10,
    )

    assert result.status == pipeline.NeutralExecutionStatus.EXECUTION_ERROR
    assert result.source_outcome == TrialOutcome.AUTOMATION_ERROR.value
    assert result.evidence_complete is False
    assert len(result.evidence_files) == 2


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
    _write_json(
        run_dir / "checkpoint1.json",
        pipeline.Checkpoint1Result(
            status=pipeline.CheckStatus.REVIEW,
            handoff_status=pipeline.HandoffStatus.CONTINUE,
            checks=[
                pipeline.CheckResult(
                    rule_id="CP1-004",
                    status=pipeline.CheckStatus.REVIEW,
                    message="변경 전 값의 SRS 근거를 최종 확인합니다.",
                )
            ],
            final_review_notes=["변경 전 값의 SRS 근거를 최종 확인합니다."],
        ).model_dump(mode="json"),
    )
    _write_json(
        run_dir / "agent2_test_design.json",
        cp2_valid_design()
        .model_copy(
            update={
                "final_review_notes": ["운영 반영 시점을 최종 확인합니다."],
                "excluded_scope": ["정확한 안내 문구"],
                "excluded_information_gaps": ["정확한 문구가 정의되지 않음"],
            }
        )
        .model_dump(mode="json"),
    )
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
    assert bundle.final_review_notes == [
        "CP1: 변경 전 값의 SRS 근거를 최종 확인합니다.",
        "CP2: 운영 반영 시점을 최종 확인합니다.",
    ]
    assert bundle.excluded_scope == ["정확한 안내 문구"]
    assert bundle.excluded_information_gaps == ["정확한 문구가 정의되지 않음"]
    assert manifest["validation_execution_sha256"] == _sha256_file(
        run_dir / "validation_execution.json"
    )
    assert manifest["project1_modified"] is False


def test_validation_execution_carries_multiple_candidates_and_exclusions(
    tmp_path: Path, monkeypatch
) -> None:
    run_id = "RUN-20260816-025000-ABCDEF"
    run_dir = tmp_path / "runs" / run_id
    run_dir.mkdir(parents=True)
    target = tmp_path / "project1" / "virtual-controller.html"
    baseline = tmp_path / "project1" / "tests" / "test_controller.py"
    baseline.parent.mkdir(parents=True)
    target.write_text("<!doctype html>", encoding="utf-8")
    baseline.write_text("def test_placeholder():\n    pass\n", encoding="utf-8")
    _write_json(
        run_dir / "agent2_test_design.json",
        cp2_valid_design().model_dump(mode="json", by_alias=True),
    )
    _write_json(run_dir / "agent3_run_summary.json", {"run_id": run_id})
    first_case = agent3_test_case()
    second_case = first_case.model_copy(update={"tc_id": "TC-CAND-004"})
    first_result = _neutral_execution_result(
        first_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    )
    second_result = _neutral_execution_result(
        second_case.tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
    )
    records = []
    for result, test_case in (
        (first_result, first_case),
        (second_result, second_case),
    ):
        artifact_dir = run_dir / "agent3_candidates" / test_case.tc_id
        artifact_dir.mkdir(parents=True)
        _write_json(artifact_dir / "agent3_manifest.json", {"run_id": run_id})
        _write_json(artifact_dir / "agent3_trial.json", {"outcome": "PASS"})
        records.append((result, test_case, {}, artifact_dir))
    exclusion = pipeline.AutomationExclusion(
        tc_id="TC-CAND-005",
        candidate_status=pipeline.AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED,
        reason="현재 관찰 방법으로 구현할 수 없습니다.",
    )
    monkeypatch.setattr(
        pipeline,
        "_candidate_execution_records",
        lambda *_args: (records, [exclusion], {"status": "PARTIAL"}),
    )
    monkeypatch.setattr(
        pipeline,
        "_current_candidate_execution_record",
        lambda _run_dir, _run_id, _target, _case, stored, **_kwargs: stored,
    )
    monkeypatch.setattr(
        pipeline,
        "run_existing_regression",
        lambda spec, *_args, source=pipeline.ExecutionSource.EXISTING_REGRESSION, **_kwargs: _neutral_execution_result(
            spec.tc_id, source
        ),
    )

    assert pipeline.run_validation_execution(
        _validation_execution_args(tmp_path, run_id, target, baseline)
    ) == 0
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        (run_dir / "validation_execution.json").read_text(encoding="utf-8")
    )
    assert [item.test_id for item in bundle.candidate_results] == [
        "TC-CAND-003",
        "TC-CAND-004",
    ]
    assert bundle.candidate_result == bundle.candidate_results[0]
    assert [item.tc_id for item in bundle.automation_exclusions] == [
        "TC-CAND-005"
    ]


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
    _write_json(
        run_dir / "agent2_test_design.json",
        cp2_valid_design().model_dump(mode="json", by_alias=True),
    )
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
    final_review_notes: list[str] | None = None,
    excluded_scope: list[str] | None = None,
    excluded_information_gaps: list[str] | None = None,
    automation_exclusions: list[pipeline.AutomationExclusion] | None = None,
    srs_revision_proposals: list[pipeline.SrsRevisionProposal] | None = None,
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
    candidate_dir = run_dir / "candidates"
    candidate_dir.mkdir()
    candidate_file = candidate_dir / candidate.test_file
    candidate_file.write_text("def test_candidate():\n    pass\n", encoding="utf-8")
    candidate = candidate.model_copy(
        update={"test_sha256": _sha256_file(candidate_file)}
    )
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
        excluded_scope=excluded_scope or [],
        excluded_information_gaps=excluded_information_gaps or [],
        final_review_notes=final_review_notes or [],
        srs_revision_proposals=srs_revision_proposals or [],
        automation_exclusions=automation_exclusions or [],
        created_at="2026-08-17T00:00:00+00:00",
    )
    execution_file = run_dir / "validation_execution.json"
    _write_json(execution_file, bundle.model_dump(mode="json"))
    _write_json(run_dir / "agent3_manifest.json", {"run_id": run_id})
    _write_json(run_dir / "agent3_trial.json", {"outcome": "PASS"})
    _write_json(
        run_dir / "agent2_test_design.json",
        pipeline.Agent2TestDesign(
            request_id="CR-AGENT4-TEST",
            test_cases=[agent3_test_case()],
            existing_tc_comparison_completed=True,
            coverage_summary="Agent 4 사람 최종 검토 문서용 후보입니다.",
            srs_revision_proposals=srs_revision_proposals or [],
        ).model_dump(mode="json", by_alias=True),
    )
    _write_json(
        run_dir / "validation_manifest.json",
        {
            "contract_version": "1.2",
            "run_id": run_id,
            "stage": "VALIDATION_EXECUTION",
            "status": bundle.status.value,
            "source_agent3_manifest_sha256": _sha256_file(
                run_dir / "agent3_manifest.json"
            ),
            "source_agent3_trial_sha256": _sha256_file(
                run_dir / "agent3_trial.json"
            ),
            "candidate_reused": candidate.reused,
            "validation_candidate_sha256": candidate.test_sha256,
            "validation_candidate_trial_sha256": None,
            "baseline_test_file": precheck.test_file,
            "baseline_test_sha256": precheck.test_sha256,
            "target_file": "virtual-controller.html",
            "target_sha256": candidate.target_sha256,
            "validation_execution_sha256": _sha256_file(execution_file),
            "project1_modified": False,
        },
    )
    return run_dir, run_id


def test_agent4_writes_consistent_pass_report_without_rerunning_tests(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path,
        excluded_scope=["정확한 차단 안내 문구"],
        excluded_information_gaps=["정확한 안내 문구가 정의되지 않음"],
    )

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
    delivery = pipeline.ExternalReportingResult.model_validate_json(
        (run_dir / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.PASS
    assert analysis.total_results == 3
    assert analysis.status_counts[pipeline.NeutralExecutionStatus.PASSED] == 3
    assert analysis.product_result_count == 2
    assert analysis.environment_result_count == 1
    assert analysis.pipeline_fixture_result_count == 0
    assert analysis.findings == []
    assert analysis.excluded_scope == ["정확한 차단 안내 문구"]
    assert analysis.excluded_information_gaps == ["정확한 안내 문구가 정의되지 않음"]
    assert report.recommendation == pipeline.FinalRecommendation.PASS
    assert report.total_results == analysis.total_results
    assert report.status_counts == analysis.status_counts
    assert report.product_result_count == 2
    assert report.environment_result_count == 1
    assert report.pipeline_fixture_result_count == 0
    assert report.excluded_scope == analysis.excluded_scope
    assert report.excluded_information_gaps == analysis.excluded_information_gaps
    assert delivery.mode == "DRY_RUN"
    assert delivery.allowed is True
    assert delivery.slack.status == pipeline.ExternalDeliveryStatus.PREVIEW
    assert delivery.notion.status == pipeline.ExternalDeliveryStatus.PREVIEW
    assert delivery.notion.item_count == 3
    assert (run_dir / "slack_payload.json").is_file()
    assert (run_dir / "notion_payload.json").is_file()
    raw_analysis = json.loads((run_dir / "agent4_analysis.json").read_text(encoding="utf-8"))
    raw_report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert "검토_항목" in raw_analysis
    assert "최종_확인_사항" in raw_analysis
    assert "제외_범위" in raw_analysis
    assert "제외된_정보_부족" in raw_analysis
    assert "검토_항목" in raw_report
    assert "최종_확인_사항" in raw_report
    assert "제외_범위" in raw_report
    assert "제외된_정보_부족" in raw_report


def test_agent4_send_delivers_only_after_cp4_pass(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    monkeypatch.setattr(
        pipeline,
        "_send_slack_report",
        lambda _payload: pipeline.ExternalDestinationResult(
            destination="SLACK",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=1,
            detail="sent",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_upsert_notion_reports",
        lambda records: pipeline.ExternalDestinationResult(
            destination="NOTION",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=len(records),
            detail="upserted",
        ),
    )

    assert pipeline.run_agent4(
        SimpleNamespace(
            run_id=run_id,
            runs_root=str(tmp_path / "runs"),
            send=True,
        )
    ) == 0

    delivery = pipeline.ExternalReportingResult.model_validate_json(
        (run_dir / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert delivery.mode == "SEND"
    assert delivery.slack.status == pipeline.ExternalDeliveryStatus.SENT
    assert delivery.notion.status == pipeline.ExternalDeliveryStatus.SENT
    assert delivery.notion.item_count == 3


def test_external_reporting_send_after_preview_preserves_first_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    first_report = run_dir / "external_reporting.json"
    first_bytes = first_report.read_bytes()
    first_hash = _sha256_file(first_report)
    monkeypatch.setattr(
        pipeline,
        "_send_slack_report",
        lambda _payload: pipeline.ExternalDestinationResult(
            destination="SLACK",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=1,
            detail="sent",
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_upsert_notion_reports",
        lambda records: pipeline.ExternalDestinationResult(
            destination="NOTION",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=len(records),
            detail="upserted",
        ),
    )

    assert pipeline.run_external_reporting(
        SimpleNamespace(
            run_id=run_id,
            runs_root=str(tmp_path / "runs"),
            send=True,
        )
    ) == 0

    assert first_report.read_bytes() == first_bytes
    attempts = list((run_dir / "external_reporting_attempts").iterdir())
    assert len(attempts) == 1
    sent = pipeline.ExternalReportingResult.model_validate_json(
        (attempts[0] / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert sent.mode == "SEND"
    assert sent.previous_reporting_sha256 == first_hash
    assert sent.slack.status == pipeline.ExternalDeliveryStatus.SENT
    assert sent.notion.status == pipeline.ExternalDeliveryStatus.SENT


def test_agent4_verifies_multiple_agent3_source_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "RUN-20260817-025000-ABCDEF"
    run_dir.mkdir()
    candidate_results = []
    source_artifacts = []
    for tc_id in ("TC-CAND-003", "TC-CAND-004"):
        artifact_dir = run_dir / "agent3_candidates" / tc_id
        candidate_dir = artifact_dir / "candidates"
        candidate_dir.mkdir(parents=True)
        candidate_file = candidate_dir / f"test_{tc_id.lower().replace('-', '_')}.py"
        candidate_file.write_text("def test_candidate():\n    pass\n", encoding="utf-8")
        agent3_manifest = artifact_dir / "agent3_manifest.json"
        agent3_trial = artifact_dir / "agent3_trial.json"
        _write_json(agent3_manifest, {"run_id": run_dir.name, "tc_id": tc_id})
        _write_json(agent3_trial, {"outcome": "PASS"})
        result = _neutral_execution_result(
            tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
        ).model_copy(
            update={
                "test_file": candidate_file.relative_to(run_dir).as_posix(),
                "test_sha256": _sha256_file(candidate_file),
            }
        )
        candidate_results.append(result)
        source_artifacts.append(
            {
                "tc_id": tc_id,
                "agent3_manifest_file": agent3_manifest.relative_to(run_dir).as_posix(),
                "agent3_manifest_sha256": _sha256_file(agent3_manifest),
                "agent3_trial_file": agent3_trial.relative_to(run_dir).as_posix(),
                "agent3_trial_sha256": _sha256_file(agent3_trial),
                "candidate_reused": True,
                "validation_candidate_sha256": result.test_sha256,
                "validation_candidate_trial_file": None,
                "validation_candidate_trial_sha256": None,
            }
        )
    summary_file = run_dir / "agent3_run_summary.json"
    _write_json(summary_file, {"run_id": run_dir.name, "status": "PASS"})
    precheck = _neutral_execution_result(
        "TC-ENV-000", pipeline.ExecutionSource.ENVIRONMENT_PRECHECK
    )
    bundle = pipeline.ValidationExecutionBundle(
        run_id=run_dir.name,
        status=pipeline.ValidationStageStatus.COMPLETED,
        candidate_results=candidate_results,
        environment_precheck=precheck,
        selected_regression_ids=[],
        regression_results=[],
        created_at="2026-08-17T00:00:00+00:00",
    )
    manifest = {
        "source_agent3_artifacts": source_artifacts,
        "source_agent3_run_summary_sha256": _sha256_file(summary_file),
    }

    assert pipeline._agent4_new_source_chain_matches(run_dir, bundle, manifest) is True
    source_artifacts[0]["agent3_trial_sha256"] = "f" * 64
    assert pipeline._agent4_new_source_chain_matches(run_dir, bundle, manifest) is False


def test_agent4_reports_automation_exclusion_without_blocking_executed_results(
    tmp_path: Path,
) -> None:
    exclusion = pipeline.AutomationExclusion(
        tc_id="TC-CAND-009",
        candidate_status=pipeline.AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED,
        reason="현재 UI 관찰 방법으로 실행할 수 없습니다.",
    )
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, automation_exclusions=[exclusion]
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.PASS
    assert report.findings == []
    assert report.automation_exclusions == [exclusion]
    raw_report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert "자동화_제외_TC" in raw_report


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
    review_file = run_dir / "사람_최종_검토.md"
    review_manifest = json.loads(
        (run_dir / "사람_최종_검토_manifest.json").read_text(encoding="utf-8")
    )
    review_text = review_file.read_text(encoding="utf-8")
    assert "# 사람 최종 검토서" in review_text
    assert "제품 동작 불일치 후보" in review_text
    assert "UI remains at 18 degrees." in review_text
    assert "요구사항이 맞으며 제품 구현 수정이 필요함" in review_text
    assert "검토자: ____________________" in review_text
    assert "사람이 작성한 문서는 `--refresh`가 덮어쓰지 않습니다" in review_text
    assert review_manifest["document_sha256"] == _sha256_file(review_file)
    assert pipeline.run_human_review_document(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0


def test_agent4_holds_candidate_automation_execution_issue(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, candidate_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HOLD
    assert report.findings[0].category == (
        pipeline.Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE
    )


def test_agent4_carries_non_blocking_review_notes_to_final_report(tmp_path: Path) -> None:
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="기존 기준",
        proposed_acceptance_criteria="변경 기준",
        reason="승인된 변경을 기준 문서에 반영한다.",
    )
    run_dir, run_id = _write_agent4_inputs(
        tmp_path,
        final_review_notes=["CP1: 변경 전 값의 SRS 근거를 최종 확인한다."],
        srs_revision_proposals=[proposal],
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )

    assert report.recommendation == pipeline.FinalRecommendation.PASS
    assert report.final_review_notes == [
        "CP1: 변경 전 값의 SRS 근거를 최종 확인한다."
    ]
    assert report.srs_revision_proposals == [proposal]
    review_text = (run_dir / "사람_최종_검토.md").read_text(encoding="utf-8")
    assert "## 4. 기준 SRS 개정 승인" in review_text
    assert "현재 인수 기준: 기존 기준" in review_text
    assert "제안 인수 기준: 변경 기준" in review_text


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


def test_agent4_holds_when_product_mismatch_and_automation_issue_coexist() -> None:
    findings = [
        pipeline.Agent4Finding(
            finding_id="FIND-001",
            category=pipeline.Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE,
            rationale="product mismatch",
        ),
        pipeline.Agent4Finding(
            finding_id="FIND-002",
            category=pipeline.Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE,
            rationale="automation issue",
        ),
    ]

    assert pipeline._agent4_recommendation(
        findings, pipeline.CheckStatus.PASS
    ) == pipeline.FinalRecommendation.HOLD


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
    delivery = pipeline.ExternalReportingResult.model_validate_json(
        (run_dir / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.FAIL
    assert delivery.allowed is False
    assert delivery.slack.status == pipeline.ExternalDeliveryStatus.BLOCKED
    assert delivery.notion.status == pipeline.ExternalDeliveryStatus.BLOCKED
    assert (run_dir / "agent4_error.json").exists() is False


def test_agent4_rejects_broken_manifest_or_candidate_chain(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["source_agent3_manifest_sha256"] = "0" * 64
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[1].rule_id == "CP4-002"
    assert checkpoint.checks[1].status == pipeline.CheckStatus.FAIL

    candidate_root = tmp_path / "candidate-tamper"
    candidate_run_dir, candidate_run_id = _write_agent4_inputs(candidate_root)
    candidate_file = candidate_run_dir / "candidates" / "test_controller.py"
    candidate_file.write_text("changed after validation\n", encoding="utf-8")

    assert pipeline.run_agent4(
        SimpleNamespace(
            run_id=candidate_run_id,
            runs_root=str(candidate_root / "runs"),
        )
    ) == 2
    candidate_checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (candidate_run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert candidate_checkpoint.checks[1].rule_id == "CP4-002"
    assert candidate_checkpoint.checks[1].status == pipeline.CheckStatus.FAIL


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


def test_agent4_rejects_passed_result_without_complete_evidence(
    tmp_path: Path,
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    execution_file = run_dir / "validation_execution.json"
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        execution_file.read_text(encoding="utf-8")
    )
    candidate = bundle.candidate_result.model_copy(
        update={
            "evidence_files": [
                bundle.candidate_result.stdout_file,
                bundle.candidate_result.stderr_file,
            ],
            "evidence_sha256": {
                name: bundle.candidate_result.evidence_sha256[name]
                for name in (
                    bundle.candidate_result.stdout_file,
                    bundle.candidate_result.stderr_file,
                )
            },
            "evidence_complete": False,
        }
    )
    bundle = bundle.model_copy(update={"candidate_result": candidate})
    _write_json(execution_file, bundle.model_dump(mode="json"))
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
    assert checkpoint.checks[5].rule_id == "CP4-006"
    assert checkpoint.checks[5].status == pipeline.CheckStatus.FAIL


def test_agent4_parser_exposes_rules_only_report_command() -> None:
    args = pipeline.build_parser().parse_args(
        ["agent4", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )

    assert args.handler is pipeline.run_agent4
    assert args.send is False

    reporting = pipeline.build_parser().parse_args(
        ["report", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )
    assert reporting.handler is pipeline.run_external_reporting
    assert reporting.send is False

    human_review = pipeline.build_parser().parse_args(
        ["human-review", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )
    assert human_review.handler is pipeline.run_human_review_document
    assert human_review.refresh is False


def test_v2_product_baseline_contains_only_runtime_assets() -> None:
    baseline_root = REPO_ROOT / "product_baseline"
    imported_files: list[str] = []
    for path in baseline_root.rglob("*"):
        if not path.is_file():
            continue
        relative_path = path.relative_to(baseline_root)
        if any(
            part in {".pytest_cache", "__pycache__", "reports"}
            for part in relative_path.parts
        ) or relative_path.name == "debug.log":
            continue
        imported_files.append(relative_path.as_posix())

    assert sorted(imported_files) == [
        "pytest.ini",
        "tests/conftest.py",
        "tests/test_controller.py",
        "virtual-controller.html",
    ]
    assert (baseline_root / "virtual-controller.html").is_file()


def test_success_fan_speed_request_is_grounded_in_v2_baseline() -> None:
    request = pipeline.ChangeRequest.model_validate_json(
        (REPO_ROOT / "examples" / "change_request.success-fan-speed.json").read_text(
            encoding="utf-8"
        )
    )
    requirements = pipeline.load_srs_requirements(
        REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"
    )
    product_html = (
        REPO_ROOT / "product_baseline" / "virtual-controller.html"
    ).read_text(encoding="utf-8")

    assert request.target_requirement_id == "REQ-FAN-001"
    assert request.target_requirement_id in requirements
    assert "HIGH" in request.after_value
    assert "fanSpeed" in request.after_value
    assert any("LOW" in note and "복원" in note for note in request.acceptance_notes)
    assert 'id="det-fan-high"' in product_html
    assert "setPanelFan('HIGH')" in product_html
    assert "device.fanSpeed = pendingState.fanSpeed" in product_html


def test_pipeline_ui_summarizes_real_run_artifacts(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    run_id = "RUN-20260829-120000-ABCDEF"
    run_dir = runs_root / run_id
    run_dir.mkdir(parents=True)
    _write_json(
        run_dir / "request.json",
        {
            "request_id": "CR-UI-001",
            "target_requirement_id": "REQ-FAN-001",
            "description": "실제 Run 표시 확인",
        },
    )
    _write_json(
        run_dir / "agent1_change_analysis.json",
        {
            "change_summary": "HIGH 표시 매핑을 변경한다.",
            "confirmed_conditions": [{"condition_id": "COND-001"}],
            "requirement_effects": [{"requirement_id": "REQ-FAN-001"}],
        },
    )
    _write_json(
        run_dir / "checkpoint1.json",
        {"status": "REVIEW", "final_review_notes": ["사람 확인 1건"]},
    )
    _write_json(
        run_dir / "agent2_test_design.json",
        {
            "test_cases": [
                {
                    "tc_id": "TC-CAND-001",
                    "title": "강풍 표시 검증",
                    "automation_candidate": True,
                }
            ],
            "제외_범위": ["실제 장비 통신"],
        },
    )
    _write_json(run_dir / "checkpoint2.json", {"status": "PASS"})
    _write_json(
        run_dir / "agent3_selection.json",
        {"status": "SELECTED", "selected_tc_ids": ["TC-CAND-001"]},
    )
    _write_json(
        run_dir / "agent3_run_summary.json",
        {
            "status": "PASS",
            "executed_tc_ids": ["TC-CAND-001"],
            "자동화_제외_TC": [],
        },
    )
    _write_json(
        run_dir / "validation_execution.json",
        {
            "status": "COMPLETED",
            "candidate_results": [{"test_id": "TC-CAND-001", "status": "PASSED"}],
            "regression_results": [],
            "environment_precheck": {"test_id": "TC-ENV-000", "status": "PASSED"},
        },
    )
    _write_json(
        run_dir / "agent4_analysis.json",
        {
            "recommendation": "PASS",
            "total_results": 2,
            "product_result_count": 1,
            "environment_result_count": 1,
        },
    )
    _write_json(run_dir / "checkpoint4.json", {"status": "PASS"})
    _write_json(
        run_dir / "final_report.json",
        {
            "recommendation": "PASS",
            "total_results": 2,
            "product_result_count": 1,
            "environment_result_count": 1,
            "검토_항목": [],
            "최종_확인_사항": ["CP1 사람 확인 1건"],
        },
    )
    _write_json(
        run_dir / "external_reporting.json",
        {
            "mode": "DRY_RUN",
            "slack": {"status": "PREVIEW"},
            "notion": {"status": "PREVIEW"},
        },
    )

    summary = pipeline_ui.summarize_run(runs_root, run_id)

    assert summary["request_id"] == "CR-UI-001"
    assert summary["overall_status"] == "PASS"
    assert summary["stages"]["agent1"]["status"] == "REVIEW"
    assert "설계 TC 1건" in summary["stages"]["agent2"]["summary"]
    assert "후보 시험 완료 1건" in summary["stages"]["agent3"]["summary"]
    assert summary["stages"]["agent4"]["summary"] == "최종 판정 PASS · 외부 보고 DRY_RUN"
    assert "Slack: PREVIEW / Notion: PREVIEW" in summary["stages"]["agent4"]["details"]


def build_approvable_ui_run(
    tmp_path: Path,
) -> tuple[Path, Path, Path, str, str, str]:
    runs_root = tmp_path / "runs"
    approved_root = tmp_path / "approved_assets"
    target_html = tmp_path / "virtual-controller.html"
    target_html.write_text("<!doctype html><title>V2 target</title>", encoding="utf-8")
    run_id = "RUN-20260829-140000-ABCDEF"
    tc_id = "TC-CAND-001"
    run_dir = runs_root / run_id
    candidate_dir = run_dir / "agent3_candidates" / tc_id
    candidate_file = candidate_dir / "candidates" / "test_tc_cand_001.py"
    candidate_file.parent.mkdir(parents=True)
    candidate_code = "def test_tc_cand_001():\n    assert True\n"
    candidate_file.write_text(candidate_code, encoding="utf-8")
    evidence_dir = candidate_dir / "evidence" / tc_id
    evidence_dir.mkdir(parents=True)
    evidence_files = []
    evidence_hashes = {}
    for name, content in (
        ("trial-stdout.txt", b"1 passed"),
        ("trial-stderr.txt", b""),
        ("trial-final.png", b"PNG"),
        ("trial-trace.zip", b"ZIP"),
    ):
        path = evidence_dir / name
        path.write_bytes(content)
        relative = path.relative_to(run_dir).as_posix()
        evidence_files.append(relative)
        evidence_hashes[relative] = _sha256_file(path)
    _write_json(
        run_dir / "agent2_test_design.json",
        {
            "test_cases": [
                {
                    "tc_id": tc_id,
                    "title": "검증된 풍량 변경",
                    "requirement_ids": ["REQ-FAN-001"],
                    "expected_results": [
                        {
                            "result_id": "ER-001",
                            "statement": "풍량 변경 결과가 화면에 표시된다.",
                        }
                    ],
                    "automation_candidate": True,
                }
            ]
        },
    )
    _write_json(
        run_dir / "agent3_run_summary.json",
        {
            "status": "PASS",
            "executed_tc_ids": [tc_id],
            "entries": [
                {"tc_id": tc_id, "status": "PASS", "checkpoint_status": "PASS"}
            ],
        },
    )
    candidate_sha256 = _sha256_file(candidate_file)
    _write_json(
        candidate_dir / "agent3_manifest.json",
        {
            "candidate_file": candidate_file.name,
            "candidate_sha256": candidate_sha256,
        },
    )
    _write_json(run_dir / "checkpoint4.json", {"status": "PASS"})
    _write_json(run_dir / "final_report.json", {"recommendation": "PASS"})
    _write_json(
        run_dir / "validation_execution.json",
        {
            "status": "COMPLETED",
            "candidate_results": [
                {
                    "test_id": tc_id,
                    "status": "PASSED",
                    "evidence_complete": True,
                    "test_file": candidate_file.relative_to(run_dir).as_posix(),
                    "test_sha256": candidate_sha256,
                    "target_sha256": _sha256_file(target_html),
                    "evidence_files": evidence_files,
                    "evidence_sha256": evidence_hashes,
                }
            ],
        },
    )
    return runs_root, approved_root, target_html, run_id, tc_id, candidate_code


def test_pipeline_ui_human_approval_registers_immutable_tc_and_automation(
    tmp_path: Path,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, candidate_code = (
        build_approvable_ui_run(tmp_path)
    )
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=tmp_path / "examples",
        target_html=target_html,
        allow_live_run=False,
        allow_asset_approval=True,
        approved_assets_root=approved_root,
    )

    record = bridge.decide_asset(
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="오세훈",
        note="실행 증거와 복원 결과 확인",
    )
    repeated = bridge.decide_asset(
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="다른 입력",
        note="중복 호출",
    )

    assert record["decision"] == "APPROVED"
    assert record["official_tc_id"] == "TC-V2-001"
    assert repeated == record
    registry = json.loads((approved_root / "registry.json").read_text(encoding="utf-8"))
    assert len(registry["assets"]) == 1
    asset = registry["assets"][0]
    assert asset["source_key"] == f"{run_id}:{tc_id}"
    assert (approved_root / asset["automation_file"]).read_text(encoding="utf-8") == candidate_code
    assert _sha256_file(approved_root / asset["automation_file"]) == asset["automation_sha256"]
    approved_tc = json.loads(
        (approved_root / asset["test_case_file"]).read_text(encoding="utf-8")
    )
    assert approved_tc["test_case"]["title"] == "검증된 풍량 변경"
    summary = pipeline_ui.summarize_run(
        runs_root,
        run_id,
        target_html=target_html,
    )
    assert summary["candidate_assets"][0]["decision"]["official_tc_id"] == "TC-V2-001"


def test_approved_tc_registry_is_loaded_and_official_automation_is_reusable(
    tmp_path: Path,
) -> None:
    approved_root = REPO_ROOT / "approved_assets"
    approved, snapshot = pipeline.load_approved_regression_catalog(approved_root)

    spec = next(item for item in approved if item.tc_id == "TC-V2-001")
    assert spec.source == "APPROVED"
    assert "REQ-FAN-001" in spec.requirement_ids
    assert "TC-V2-001" in pipeline.render_existing_regression_context(approved)
    assert snapshot["approved_assets"][0]["automation_sha256"] == spec.automation_sha256

    result = pipeline.run_existing_regression(
        spec,
        approved_root / str(spec.automation_file),
        REPO_ROOT / "product_baseline" / "virtual-controller.html",
        tmp_path / "approved-evidence",
        timeout_seconds=60,
    )

    assert result.status == pipeline.NeutralExecutionStatus.PASSED
    assert result.test_file == spec.automation_file
    assert result.test_sha256 == spec.automation_sha256
    assert result.evidence_complete is True
    assert any(path.endswith("trial-final.png") for path in result.evidence_files)
    assert any(path.endswith("trial-trace.zip") for path in result.evidence_files)


def test_pipeline_ui_requires_and_applies_srs_revision_with_asset_approval(
    tmp_path: Path,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    srs_file = tmp_path / "SRS.md"
    srs_file.write_text(
        "# SRS\n\n| ID | 요구사항 | 인수 기준 |\n"
        "|---|---|---|\n"
        "| REQ-FAN-001 | 풍량 설정 | 기존 풍량 기준 |\n",
        encoding="utf-8",
    )
    final_report_file = runs_root / run_id / "final_report.json"
    _write_json(
        final_report_file,
        {
            "recommendation": "PASS",
            "SRS_개정_제안": [
                {
                    "proposal_id": "SRS-REV-001",
                    "requirement_id": "REQ-FAN-001",
                    "source_condition_ids": ["COND-001"],
                    "current_acceptance_criteria": "기존 풍량 기준",
                    "proposed_acceptance_criteria": "변경 풍량 기준",
                    "reason": "승인된 풍량 변경을 기준 문서에 반영한다.",
                }
            ],
        },
    )

    with pytest.raises(ValueError, match="SRS 개정 포함 승인"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            srs_path=srs_file,
            decision="APPROVE",
            reviewer="검토자",
            note="",
        )

    record = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        srs_path=srs_file,
        decision="APPROVE",
        reviewer="검토자",
        note="SRS 개정 문구와 실행 증거 확인",
        approve_srs_revisions=True,
    )

    assert record["decision"] == "APPROVED"
    assert record["srs_revision_applied"] is True
    assert "변경 풍량 기준" in srs_file.read_text(encoding="utf-8")
    registry = json.loads((approved_root / "registry.json").read_text(encoding="utf-8"))
    asset = registry["assets"][0]
    assert asset["srs_revision_before_sha256"] != asset["srs_revision_after_sha256"]
    assert (approved_root / asset["srs_revision_file"]).is_file()
    assert (runs_root / run_id / "srs_revision_decision.json").is_file()


def test_pipeline_ui_hold_is_recorded_and_can_later_be_approved(tmp_path: Path) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )

    held = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        decision="HOLD",
        reviewer="검토자",
        note="요구사항 담당자 확인 필요",
    )
    approved = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="검토자",
        note="확인 완료",
    )

    assert held["decision"] == "HELD"
    assert not (approved_root / "registry.json").read_text(encoding="utf-8").count("HELD")
    assert approved["decision"] == "APPROVED"
    decisions = json.loads(
        (runs_root / run_id / "asset_decisions.json").read_text(encoding="utf-8")
    )
    assert decisions["decisions"] == [approved]


def test_pipeline_ui_blocks_asset_approval_for_failed_or_stale_evidence(
    tmp_path: Path,
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    _write_json(runs_root / run_id / "final_report.json", {"recommendation": "HOLD"})

    with pytest.raises(ValueError, match="최종 권고"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            decision="APPROVE",
            reviewer="검토자",
            note="",
        )

    _write_json(runs_root / run_id / "final_report.json", {"recommendation": "PASS"})
    target_html.write_text("<!doctype html><title>changed</title>", encoding="utf-8")
    with pytest.raises(ValueError, match="재검증"):
        pipeline_ui.decide_candidate_asset(
            runs_root,
            approved_root,
            target_html,
            run_id,
            tc_id,
            decision="APPROVE",
            reviewer="검토자",
            note="",
        )
    assert not (approved_root / "registry.json").exists()


def test_pipeline_ui_revalidates_stale_candidate_without_model_call(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root, approved_root, target_html, run_id, tc_id, _ = build_approvable_ui_run(
        tmp_path
    )
    target_html.write_text("<!doctype html><title>UI updated</title>", encoding="utf-8")

    def fake_trial(code_file, current_target, evidence_dir, *, timeout_seconds):
        evidence_dir.mkdir(parents=True)
        hashes = {}
        for name, content in (
            ("trial-stdout.txt", b"1 passed"),
            ("trial-stderr.txt", b""),
            ("trial-final.png", b"PNG2"),
            ("trial-trace.zip", b"ZIP2"),
        ):
            path = evidence_dir / name
            path.write_bytes(content)
            hashes[name] = _sha256_file(path)
        return pipeline.Agent3TrialResult(
            outcome=pipeline.TrialOutcome.PASS,
            exit_code=0,
            duration_ms=10,
            stdout_file="trial-stdout.txt",
            stderr_file="trial-stderr.txt",
            screenshot_file="trial-final.png",
            trace_file="trial-trace.zip",
            evidence_sha256=hashes,
            evidence_complete=True,
        )

    monkeypatch.setattr(pipeline, "run_candidate_trial", fake_trial)

    record = pipeline_ui.revalidate_candidate_asset(
        runs_root,
        target_html,
        run_id,
        tc_id,
    )
    summary = pipeline_ui.summarize_run(
        runs_root,
        run_id,
        target_html=target_html,
    )
    approved = pipeline_ui.decide_candidate_asset(
        runs_root,
        approved_root,
        target_html,
        run_id,
        tc_id,
        decision="APPROVE",
        reviewer="검토자",
        note="현재 화면 재검증 확인",
    )
    latest = runs_root / run_id / "asset_revalidation" / tc_id / "latest.json"

    assert record["outcome"] == "PASS"
    assert record["target_sha256"] == _sha256_file(target_html)
    assert summary["candidate_assets"][0]["approval_eligible"] is True
    assert summary["candidate_assets"][0]["revalidation_required"] is False
    assert approved["approval_revalidation_sha256"] == _sha256_file(latest)


def test_pipeline_ui_rejects_unscoped_run_and_request_paths(tmp_path: Path) -> None:
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=tmp_path / "runs",
        requests_root=tmp_path / "examples",
        target_html=tmp_path / "virtual-controller.html",
        allow_live_run=False,
    )

    with pytest.raises(ValueError, match="Run ID"):
        pipeline_ui.summarize_run(tmp_path / "runs", "../outside")
    with pytest.raises(ValueError, match="파일명"):
        bridge.request_path("../change_request.json")
    with pytest.raises(PermissionError, match="비활성화"):
        bridge.start_live_run("change_request.json")


def test_pipeline_ui_failure_message_is_safe_and_actionable(tmp_path: Path) -> None:
    run_dir = tmp_path / "RUN-20260829-130000-ABCDEF"
    run_dir.mkdir()
    _write_json(
        run_dir / "run_error.json",
        {
            "error_type": "Agent1Error",
            "message": f"모델 연결 실패: {pipeline_ui.REPO_ROOT / 'private-input.json'}",
        },
    )

    message = pipeline_ui._safe_run_error(run_dir)

    assert message == "모델 연결 실패: <REPO_ROOT>\\private-input.json"
    assert str(pipeline_ui.REPO_ROOT) not in message

    (run_dir / "run_error.json").unlink()
    nested = run_dir / "agent3_candidates" / "TC-CAND-001"
    nested.mkdir(parents=True)
    _write_json(
        nested / "agent3_error.json",
        {"tc_id": "TC-CAND-001", "message": "브라우저 종료 오류"},
    )
    assert pipeline_ui._safe_run_error(run_dir) == "TC-CAND-001: 브라우저 종료 오류"

    (nested / "agent3_error.json").unlink()
    _write_json(
        run_dir / "agent3_run_summary.json",
        {"entries": [{"tc_id": "TC-CAND-001", "trial_outcome": "TIMEOUT"}]},
    )
    assert pipeline_ui._safe_run_error(run_dir) == "TC-CAND-001: 후보 시험 TIMEOUT"


def test_pipeline_ui_live_run_is_disabled_by_default() -> None:
    args = pipeline_ui.build_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.allow_live_run is False
    assert args.allow_asset_approval is False


def test_pipeline_ui_prevents_parallel_live_runs_across_bridges(tmp_path: Path) -> None:
    runs_root = tmp_path / "runs"
    requests_root = tmp_path / "examples"
    requests_root.mkdir()
    _write_json(requests_root / "change_request.json", {"request_id": "CR-LOCK-001"})
    target_html = tmp_path / "virtual-controller.html"
    target_html.write_text("<!doctype html>", encoding="utf-8")
    first = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=requests_root,
        target_html=target_html,
        allow_live_run=True,
    )
    second = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=requests_root,
        target_html=target_html,
        allow_live_run=True,
    )

    assert first.live_run_lock.acquire() is True
    try:
        with pytest.raises(RuntimeError, match="다른 로컬 브리지"):
            second.start_live_run("change_request.json")
    finally:
        first.live_run_lock.release()
    assert second.live_run_lock.acquire() is True
    second.live_run_lock.release()


def test_pipeline_ui_live_run_uses_agent1_to_4_order_without_external_send(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runs_root = tmp_path / "runs"
    requests_root = tmp_path / "examples"
    requests_root.mkdir()
    request_file = requests_root / "change_request.success.json"
    _write_json(request_file, {"request_id": "CR-UI-LIVE-001"})
    target_html = tmp_path / "virtual-controller.html"
    target_html.write_text("<!doctype html>", encoding="utf-8")
    bridge = pipeline_ui.PipelineUiBridge(
        runs_root=runs_root,
        requests_root=requests_root,
        target_html=target_html,
        allow_live_run=True,
    )
    run_id = "RUN-20260829-130000-ABCDEF"
    commands: list[tuple[str, ...]] = []

    def fake_command(*arguments: str) -> SimpleNamespace:
        commands.append(arguments)
        if arguments[0] == "pipeline":
            (runs_root / run_id).mkdir(parents=True)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(bridge, "_command", fake_command)

    bridge._run_pipeline(request_file)

    assert [command[0] for command in commands] == ["pipeline", "execute", "agent4"]
    assert commands[0][-2:] == ("--timeout", "90")
    assert "--send" not in commands[-1]
    assert bridge.state.snapshot()["phase"] == "COMPLETED"
    assert bridge.state.snapshot()["run_id"] == run_id


def test_v2_product_ui_routes_agent_buttons_to_real_run_bridge() -> None:
    product_html = (
        REPO_ROOT / "product_baseline" / "virtual-controller.html"
    ).read_text(encoding="utf-8")

    assert 'id="qa-live-modal"' in product_html
    assert "qaLiveFetch('/api/qa/state')" in product_html
    assert "if (openQaLiveModal('agent1')) return;" in product_html
    assert "if (openQaLiveModal('agent2')) return;" in product_html
    assert "if (openQaLiveModal('agent3')) return;" in product_html
    assert "if (openQaLiveModal('agent4')) return;" in product_html
    assert "if (openQaLiveModal('overview')) return;" in product_html
    assert "function showQaLiveOverview()" in product_html
    assert "Agent 1→4 실제 Run 상태입니다." in product_html
    assert "setTowerStatus('실제 실행 실패', '#f87171')" in product_html
    assert "setTowerStatus('실제 실행 완료', '#34d399')" in product_html
    assert "확인: API Live 실행" in product_html
    assert "qaLiveState.startApprovalArmed && !overview.running" in product_html
    assert "window.confirm(" not in product_html
    assert "외부 보고는 미리보기만 생성" in product_html
    assert "저장 결과 보기" in product_html
    assert "AI API 사용 없음" in product_html
    assert "새 요구사항 실제 실행" in product_html
    assert "AI API 비용 발생" in product_html
    assert "후보 TC 공식 자산 판단" in product_html
    assert "공식 TC·자동화 등록 승인" in product_html
    assert "/asset-decision" in product_html
    assert "현재 화면에서 후보 재검증" in product_html
    assert "/asset-revalidation" in product_html
    assert "확인: 공식 자산 등록" in product_html
