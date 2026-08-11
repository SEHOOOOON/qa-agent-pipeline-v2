from pathlib import Path

from qa_pipeline_v2.checkpoint1 import evaluate_checkpoint1
from qa_pipeline_v2.models import (
    Agent1Analysis,
    AnalysisDecision,
    ChangeRequest,
    CheckStatus,
    Evidence,
    Impact,
)
from qa_pipeline_v2.srs import load_srs_requirements


REPO_ROOT = Path(__file__).resolve().parents[1]


def request() -> ChangeRequest:
    return ChangeRequest(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_value="16~30°C",
        after_value="18~30°C",
        description="섭씨 설정 범위를 18~30°C로 변경한다.",
    )


def valid_analysis() -> Agent1Analysis:
    return Agent1Analysis(
        request_id="CR-TEST-001",
        change_type="MODIFIED",
        target_requirement_id="REQ-TEMP-001",
        before_condition="현재 섭씨 설정 범위는 16~30°C다.",
        after_condition="변경 후 섭씨 설정 범위는 18~30°C다.",
        changed_fields=["섭씨 설정 범위"],
        direct_impacts=[Impact(requirement_id="REQ-TEMP-001", reason="설정 범위가 직접 변경된다.")],
        related_impacts=[],
        verified_scope=["섭씨 설정 범위 변경"],
        excluded_scope=["화씨 표시 정책"],
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


def requirements():
    return load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")


def test_valid_analysis_passes_checkpoint1() -> None:
    result = evaluate_checkpoint1(request(), valid_analysis(), requirements())

    assert result.status == CheckStatus.PASS
    assert all(check.status == CheckStatus.PASS for check in result.checks)


def test_unknown_requirement_is_rejected() -> None:
    analysis = valid_analysis().model_copy(
        update={"related_impacts": [Impact(requirement_id="REQ-FAKE-999", reason="존재하지 않는 기능")]}
    )

    result = evaluate_checkpoint1(request(), analysis, requirements())

    assert result.status == CheckStatus.FAIL
    assert next(check for check in result.checks if check.rule_id == "CP1-006").status == CheckStatus.FAIL


def test_unverified_before_value_requires_review() -> None:
    changed_request = request().model_copy(update={"before_value": "17~30°C"})
    analysis = valid_analysis().model_copy(update={"before_condition": "현재 섭씨 설정 범위는 17~30°C다."})

    result = evaluate_checkpoint1(changed_request, analysis, requirements())

    assert result.status == CheckStatus.REVIEW
    assert next(check for check in result.checks if check.rule_id == "CP1-004").status == CheckStatus.REVIEW


def test_redundant_reconfirmation_requires_review() -> None:
    analysis = valid_analysis().model_copy(
        update={
            "information_gaps": ["변경 정책을 다시 확인해야 함"],
            "user_questions": [
                "섭씨 설정 범위를 18~30°C로 변경하는 것으로 확정할 수 있습니까?"
            ],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(request(), analysis, requirements())

    assert result.status == CheckStatus.REVIEW
    assert next(
        check for check in result.checks if check.rule_id == "CP1-010"
    ).status == CheckStatus.REVIEW


def test_legitimate_missing_detail_question_passes_checkpoint() -> None:
    analysis = valid_analysis().model_copy(
        update={
            "information_gaps": ["기존 저장 데이터의 적용 시점이 요청에 없음"],
            "user_questions": ["기존에 저장된 장비에도 즉시 소급 적용합니까?"],
            "decision": AnalysisDecision.WAITING_FOR_USER,
        }
    )

    result = evaluate_checkpoint1(request(), analysis, requirements())

    assert result.status == CheckStatus.PASS
    assert next(
        check for check in result.checks if check.rule_id == "CP1-010"
    ).status == CheckStatus.PASS


def test_proceed_with_open_question_requires_review() -> None:
    analysis = valid_analysis().model_copy(
        update={
            "information_gaps": ["경계값 적용 시점이 불명확함"],
            "user_questions": ["기존 저장값에도 즉시 적용합니까?"],
        }
    )

    result = evaluate_checkpoint1(request(), analysis, requirements())

    assert result.status == CheckStatus.REVIEW
    assert next(check for check in result.checks if check.rule_id == "CP1-009").status == CheckStatus.REVIEW

