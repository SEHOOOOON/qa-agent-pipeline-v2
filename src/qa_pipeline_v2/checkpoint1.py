from __future__ import annotations

import re

from .models import (
    Agent1Analysis,
    AnalysisDecision,
    ChangeRequest,
    Checkpoint1Result,
    CheckResult,
    CheckStatus,
    SrsRequirement,
)


def _normalize(value: str) -> str:
    return re.sub(r"\s+", "", value).casefold()


def _contains(container: str, expected: str) -> bool:
    return _normalize(expected) in _normalize(container)


def _terms(value: str) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[가-힣A-Za-z0-9°%._~+·-]{2,}", value)
    }


def _is_redundant_reconfirmation(question: str, request: ChangeRequest) -> bool:
    reconfirmation = re.search(
        r"확정할\s*수\s*있|확정해\s*(?:도|주)|맞습니까|재확인|다시\s*확인|추가하는\s*것으로",
        question,
        flags=re.IGNORECASE,
    )
    if reconfirmation is None:
        return False

    authority_text = " ".join(
        filter(
            None,
            [
                request.target_requirement_id,
                request.after_value,
                request.description,
                request.reason,
                *request.acceptance_notes,
                *request.out_of_scope,
            ],
        )
    )
    question_terms = _terms(question)
    overlap = question_terms & _terms(authority_text)
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

    impact_ids = {
        impact.requirement_id
        for impact in analysis.direct_impacts + analysis.related_impacts
    }
    unknown_impacts = sorted(impact_ids - requirements.keys())
    if unknown_impacts:
        add(
            "CP1-006",
            CheckStatus.FAIL,
            f"SRS에 없는 영향 Requirement ID: {', '.join(unknown_impacts)}",
        )
    elif request.target_requirement_id not in {
        item.requirement_id for item in analysis.direct_impacts
    }:
        add("CP1-006", CheckStatus.FAIL, "직접 영향에 대상 Requirement가 없습니다.")
    else:
        add("CP1-006", CheckStatus.PASS, "영향 Requirement ID가 SRS 범위 안에 있습니다.")

    invalid_evidence: list[str] = []
    target_evidence_found = False
    for evidence in analysis.evidence:
        source = requirements.get(evidence.requirement_id)
        if source is None:
            invalid_evidence.append(evidence.requirement_id)
            continue
        if evidence.requirement_id == request.target_requirement_id:
            target_evidence_found = True
        if not _contains(
            f"{source.statement} {source.acceptance_criteria}", evidence.evidence_text
        ):
            invalid_evidence.append(evidence.requirement_id)

    if invalid_evidence:
        add(
            "CP1-007",
            CheckStatus.FAIL,
            "SRS 원문과 일치하지 않는 근거가 있습니다: "
            + ", ".join(sorted(set(invalid_evidence))),
        )
    elif not target_evidence_found:
        add("CP1-007", CheckStatus.FAIL, "대상 Requirement의 SRS 근거가 없습니다.")
    else:
        add("CP1-007", CheckStatus.PASS, "근거 문장이 실제 SRS 행에 존재합니다.")

    verified = {_normalize(item) for item in analysis.verified_scope}
    excluded = {_normalize(item) for item in analysis.excluded_scope}
    if verified & excluded:
        add("CP1-008", CheckStatus.FAIL, "검증 범위와 제외 범위가 겹칩니다.")
    else:
        add("CP1-008", CheckStatus.PASS, "검증 범위와 제외 범위가 분리됐습니다.")

    has_open_questions = bool(analysis.information_gaps or analysis.user_questions)
    if analysis.decision == AnalysisDecision.PROCEED and has_open_questions:
        add(
            "CP1-009",
            CheckStatus.REVIEW,
            "정보 부족 또는 질문이 있는데 PROCEED로 판정했습니다.",
        )
    elif analysis.decision == AnalysisDecision.WAITING_FOR_USER and not analysis.user_questions:
        add(
            "CP1-009",
            CheckStatus.REVIEW,
            "WAITING_FOR_USER이지만 사용자 질문이 없습니다.",
        )
    else:
        add("CP1-009", CheckStatus.PASS, "정보 부족과 진행 판정이 일관됩니다.")

    redundant_questions = [
        question
        for question in analysis.user_questions
        if _is_redundant_reconfirmation(question, request)
    ]
    if redundant_questions:
        add(
            "CP1-010",
            CheckStatus.REVIEW,
            "변경 요청에 이미 명시된 정책을 다시 확인하는 질문이 있습니다.",
        )
    else:
        add(
            "CP1-010",
            CheckStatus.PASS,
            "사용자 질문이 변경 요청의 명시 내용을 불필요하게 재확인하지 않습니다.",
        )

    statuses = {check.status for check in checks}
    if CheckStatus.ERROR in statuses:
        status = CheckStatus.ERROR
    elif CheckStatus.FAIL in statuses:
        status = CheckStatus.FAIL
    elif CheckStatus.REVIEW in statuses:
        status = CheckStatus.REVIEW
    else:
        status = CheckStatus.PASS
    return Checkpoint1Result(status=status, checks=checks)

