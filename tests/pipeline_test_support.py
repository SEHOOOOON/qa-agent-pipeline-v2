"""역할별 테스트가 공유하는 fixture, builder와 import."""

import json

import os

import subprocess

import sys

import time

import zipfile

from pathlib import Path

from qa_pipeline_v2 import load_srs_requirements, render_srs_context

REPO_ROOT = Path(__file__).resolve().parents[1]

from types import SimpleNamespace

import pytest

import qa_pipeline_ui as pipeline_ui

import qa_pipeline_execution as pipeline_execution
import qa_pipeline_orchestrator as pipeline_orchestrator

import qa_pipeline_reporting as pipeline_reporting

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
    ConditionChangeRole,
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
    _is_unchanged_condition_for_request,
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

import qa_pipeline_v2 as pipeline

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
        pipeline_execution,
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

def _write_agent4_inputs(
    tmp_path: Path,
    *,
    include_candidate: bool = True,
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
    candidate = (
        _neutral_execution_result(
            "TC-CAND-003",
            pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE,
            candidate_status,
        )
        if include_candidate
        else None
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

    if candidate is not None:
        candidate = materialize_evidence(candidate)
    precheck = materialize_evidence(precheck)
    regressions = [materialize_evidence(result) for result in regressions]
    if candidate is not None:
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
    if candidate is not None:
        _write_json(run_dir / "agent3_manifest.json", {"run_id": run_id})
        _write_json(run_dir / "agent3_trial.json", {"outcome": "PASS"})
    else:
        _write_json(
            run_dir / "agent3_run_summary.json",
            {
                "contract_version": "1.1",
                "run_id": run_id,
                "stage": "AGENT_3_RUN_SUMMARY",
                "status": "EXCLUDED" if automation_exclusions else "NOT_REQUIRED",
                "selected_tc_ids": [],
                "executed_tc_ids": [],
                "entries": [],
                "자동화_제외_TC": [
                    item.model_dump(mode="json")
                    for item in automation_exclusions or []
                ],
            },
        )
    _write_json(
        run_dir / "agent2_test_design.json",
        pipeline.Agent2TestDesign(
            request_id="CR-AGENT4-TEST",
            test_cases=[agent3_test_case()] if candidate is not None else [],
            existing_tc_comparison_completed=True,
            coverage_summary="Agent 4 사람 최종 검토 문서용 후보입니다.",
            srs_revision_proposals=srs_revision_proposals or [],
        ).model_dump(mode="json", by_alias=True),
    )
    validation_manifest = {
            "contract_version": "1.2",
            "run_id": run_id,
            "stage": "VALIDATION_EXECUTION",
            "status": bundle.status.value,
            "baseline_test_file": precheck.test_file,
            "baseline_test_sha256": precheck.test_sha256,
            "target_file": "virtual-controller.html",
            "target_sha256": precheck.target_sha256,
            "validation_execution_sha256": _sha256_file(execution_file),
            "project1_modified": False,
        }
    if candidate is not None:
        validation_manifest.update(
            {
                "source_agent3_manifest_sha256": _sha256_file(
                    run_dir / "agent3_manifest.json"
                ),
                "source_agent3_trial_sha256": _sha256_file(
                    run_dir / "agent3_trial.json"
                ),
                "candidate_reused": candidate.reused,
                "validation_candidate_sha256": candidate.test_sha256,
                "validation_candidate_trial_sha256": None,
            }
        )
    else:
        validation_manifest.update(
            {
                "source_agent3_run_summary_sha256": _sha256_file(
                    run_dir / "agent3_run_summary.json"
                ),
                "source_agent3_artifacts": [],
                "candidate_reused": None,
                "validation_candidate_sha256": None,
                "validation_candidate_trial_sha256": None,
            }
        )
    _write_json(run_dir / "validation_manifest.json", validation_manifest)
    return run_dir, run_id

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
                    "source_condition_ids": ["COND-001"],
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

__all__ = [name for name in globals() if not name.startswith("__")]
