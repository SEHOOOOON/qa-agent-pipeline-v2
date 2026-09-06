from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Annotated, Any

from openai import OpenAI
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator
from qa_pipeline_trace import redact_playwright_trace as _redact_playwright_trace
from qa_pipeline_io import *
from qa_pipeline_contracts import *
from qa_pipeline_agent1 import *
from qa_pipeline_agent2 import *
from qa_pipeline_agent3 import *
from qa_pipeline_execution import *

def _validation_results(bundle: ValidationExecutionBundle) -> list[NeutralExecutionResult]:
    return [*bundle.candidate_results, bundle.environment_precheck, *bundle.regression_results]


def _agent4_finding_for_result(
    result: NeutralExecutionResult, finding_number: int
) -> Agent4Finding | None:
    if result.status == NeutralExecutionStatus.PASSED:
        return None
    if result.source == ExecutionSource.ENVIRONMENT_PRECHECK:
        category = Agent4FindingCategory.ENVIRONMENT_ISSUE
        rationale = "환경 사전 점검이 통과하지 않아 제품 회귀 결과를 신뢰할 수 없습니다."
    elif result.source_outcome == TrialOutcome.ENVIRONMENT_ERROR.value:
        category = Agent4FindingCategory.ENVIRONMENT_ISSUE
        rationale = "신규 후보 실행 환경 오류로 제품 결과를 판정할 수 없습니다."
    elif result.status == NeutralExecutionStatus.ASSERTION_FAILED:
        category = Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE
        rationale = "기대 결과와 관찰 결과가 달라 제품 불일치 후보로 분류합니다. 제품 결함 확정은 아닙니다."
    elif result.status in {
        NeutralExecutionStatus.EXECUTION_ERROR,
        NeutralExecutionStatus.TIMEOUT,
    }:
        category = Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE
        rationale = "실행 기술 오류 또는 시간 초과로 제품 결과를 판정할 수 없습니다."
    else:
        category = Agent4FindingCategory.NOT_EXECUTED
        rationale = "이 TC는 실행되지 않았으므로 제품 결과 근거가 부족합니다."
    return Agent4Finding(
        finding_id=f"FIND-{finding_number:03d}",
        category=category,
        test_id=result.test_id,
        source=result.source,
        requirement_ids=result.requirement_ids,
        status=result.status,
        evidence_files=result.evidence_files,
        rationale=rationale,
    )


def _agent4_recommendation(
    findings: list[Agent4Finding], checkpoint_status: CheckStatus
) -> FinalRecommendation:
    if checkpoint_status != CheckStatus.PASS:
        return FinalRecommendation.HOLD
    blocking_categories = {
        Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE,
        Agent4FindingCategory.ENVIRONMENT_ISSUE,
        Agent4FindingCategory.INSUFFICIENT_EVIDENCE,
        Agent4FindingCategory.NOT_EXECUTED,
    }
    if any(finding.category in blocking_categories for finding in findings):
        return FinalRecommendation.HOLD
    if any(
        finding.category == Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE
        for finding in findings
    ):
        return FinalRecommendation.HUMAN_REVIEW
    return FinalRecommendation.PASS


def _agent4_evidence_issues(
    run_dir: Path, results: list[NeutralExecutionResult]
) -> list[str]:
    issues: list[str] = []
    for result in results:
        trusted_product_observation = result.status in {
            NeutralExecutionStatus.PASSED,
            NeutralExecutionStatus.ASSERTION_FAILED,
        }
        if trusted_product_observation and (
            not result.evidence_complete or not result.evidence_files
        ):
            issues.append(
                f"{result.test_id}: 제품 판정에 필요한 완전한 실행 증거가 없습니다"
            )
        elif not result.evidence_files:
            issues.append(f"{result.test_id}: 실행 상태를 설명할 증거가 없습니다")
        if (
            trusted_product_observation
            and result.source == ExecutionSource.NEW_AUTOMATION_CANDIDATE
        ):
            named_output = {result.stdout_file, result.stderr_file}
            candidate_evidence_complete = (
                None not in named_output
                and named_output <= set(result.evidence_files)
                and any(Path(name).suffix.casefold() == ".png" for name in result.evidence_files)
                and any(Path(name).suffix.casefold() == ".zip" for name in result.evidence_files)
            )
            if not candidate_evidence_complete:
                issues.append(
                    f"{result.test_id}: 신규 후보 제품 판정에 stdout·stderr·Screenshot·Trace가 모두 필요합니다"
                )
        if set(result.evidence_sha256) != set(result.evidence_files):
            issues.append(
                f"{result.test_id}: 증거 목록과 SHA-256 목록이 일치하지 않습니다"
            )
        for named_file in (result.stdout_file, result.stderr_file):
            if named_file is not None and named_file not in result.evidence_files:
                issues.append(
                    f"{result.test_id}: stdout 또는 stderr가 증거 목록에 없습니다"
                )
        for relative_name in result.evidence_files:
            relative_path = Path(relative_name)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                issues.append(f"{result.test_id}: 증거 경로가 Run 폴더 밖을 가리킵니다")
                continue
            evidence_file = (run_dir / relative_path).resolve()
            try:
                evidence_file.relative_to(run_dir.resolve())
            except ValueError:
                issues.append(f"{result.test_id}: 증거 경로가 Run 폴더 밖을 가리킵니다")
                continue
            expected_hash = result.evidence_sha256.get(relative_name)
            if not evidence_file.is_file():
                issues.append(f"{result.test_id}: 증거 파일이 없습니다: {relative_name}")
            elif expected_hash is None or _sha256_file(evidence_file) != expected_hash:
                issues.append(f"{result.test_id}: 증거 SHA-256이 일치하지 않습니다: {relative_name}")
    return issues


def _agent4_status_contract_issues(
    results: list[NeutralExecutionResult],
) -> list[str]:
    expected_status = {
        TrialOutcome.PASS.value: NeutralExecutionStatus.PASSED,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE.value: (
            NeutralExecutionStatus.ASSERTION_FAILED
        ),
        TrialOutcome.AUTOMATION_ERROR.value: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.ENVIRONMENT_ERROR.value: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.TIMEOUT.value: NeutralExecutionStatus.TIMEOUT,
        "PYTEST_PASSED": NeutralExecutionStatus.PASSED,
        "PYTEST_FAILED": NeutralExecutionStatus.ASSERTION_FAILED,
        "PYTEST_ERROR": NeutralExecutionStatus.EXECUTION_ERROR,
        "PYTEST_TIMEOUT": NeutralExecutionStatus.TIMEOUT,
        "PYTEST_SKIPPED": NeutralExecutionStatus.SKIPPED,
    }
    issues: list[str] = []
    for result in results:
        expected = expected_status.get(result.source_outcome)
        if expected is None or result.status != expected:
            issues.append(
                f"{result.test_id}: source_outcome과 중립 상태가 일치하지 않습니다"
            )
        if result.status in {
            NeutralExecutionStatus.PASSED,
            NeutralExecutionStatus.SKIPPED,
        } and result.exit_code != 0:
            issues.append(f"{result.test_id}: 통과 또는 건너뜀 종료 코드가 0이 아닙니다")
        if result.status in {
            NeutralExecutionStatus.ASSERTION_FAILED,
            NeutralExecutionStatus.EXECUTION_ERROR,
        } and result.exit_code in {None, 0}:
            issues.append(f"{result.test_id}: 실패 상태의 종료 코드가 유효하지 않습니다")
        if result.status == NeutralExecutionStatus.TIMEOUT and result.exit_code is not None:
            issues.append(f"{result.test_id}: 시간 초과 결과에 종료 코드가 기록됐습니다")
    return issues


def _agent4_candidate_artifact_matches(
    run_dir: Path, result: NeutralExecutionResult
) -> bool:
    try:
        candidate_file = _candidate_file_for_result(run_dir, result)
    except ValueError:
        return False
    return (
        candidate_file.is_file()
        and _sha256_file(candidate_file) == result.test_sha256
    )


def _safe_run_file(run_dir: Path, relative_name: Any) -> Path | None:
    if not isinstance(relative_name, str):
        return None
    relative = Path(relative_name)
    if relative.is_absolute() or ".." in relative.parts:
        return None
    path = (run_dir / relative).resolve()
    try:
        path.relative_to(run_dir.resolve())
    except ValueError:
        return None
    return path if path.is_file() else None


def _agent4_new_source_chain_matches(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    manifest: dict[str, Any],
) -> bool | None:
    raw_artifacts = manifest.get("source_agent3_artifacts")
    if not isinstance(raw_artifacts, list):
        return None
    artifacts = {
        item.get("tc_id"): item for item in raw_artifacts if isinstance(item, dict)
    }
    if set(artifacts) != {item.test_id for item in bundle.candidate_results}:
        return False
    summary_hash = manifest.get("source_agent3_run_summary_sha256")
    summary_file = run_dir / "agent3_run_summary.json"
    if (
        not isinstance(summary_hash, str)
        or not summary_file.is_file()
        or _sha256_file(summary_file) != summary_hash
    ):
        return False
    for result in bundle.candidate_results:
        item = artifacts[result.test_id]
        agent3_manifest = _safe_run_file(
            run_dir, item.get("agent3_manifest_file")
        )
        agent3_trial = _safe_run_file(run_dir, item.get("agent3_trial_file"))
        if (
            agent3_manifest is None
            or agent3_trial is None
            or _sha256_file(agent3_manifest) != item.get("agent3_manifest_sha256")
            or _sha256_file(agent3_trial) != item.get("agent3_trial_sha256")
            or item.get("candidate_reused") != result.reused
            or item.get("validation_candidate_sha256") != result.test_sha256
            or not _agent4_candidate_artifact_matches(run_dir, result)
        ):
            return False
        validation_trial = _safe_run_file(
            run_dir, item.get("validation_candidate_trial_file")
        )
        validation_trial_hash = item.get("validation_candidate_trial_sha256")
        if result.reused:
            if item.get("validation_candidate_trial_file") is not None or validation_trial_hash is not None:
                return False
        elif (
            validation_trial is None
            or not isinstance(validation_trial_hash, str)
            or _sha256_file(validation_trial) != validation_trial_hash
        ):
            return False
    return True


def _agent4_regression_source_chain_matches(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    manifest: dict[str, Any],
) -> bool:
    baseline_hash = manifest.get("baseline_test_sha256")
    if (
        not isinstance(baseline_hash, str)
        or bundle.environment_precheck.test_sha256 != baseline_hash
    ):
        return False

    raw_approved = manifest.get("approved_regression_assets", [])
    if not isinstance(raw_approved, list):
        return False
    approved_by_id: dict[str, dict[str, Any]] = {}
    for item in raw_approved:
        if not isinstance(item, dict) or not isinstance(item.get("tc_id"), str):
            return False
        tc_id = item["tc_id"]
        if tc_id in approved_by_id:
            return False
        approved_by_id[tc_id] = item

    regression_ids = {result.test_id for result in bundle.regression_results}
    if not set(approved_by_id).issubset(regression_ids):
        return False
    for result in bundle.regression_results:
        approved = approved_by_id.get(result.test_id)
        if approved is None:
            if result.test_sha256 != baseline_hash:
                return False
            continue
        if (
            approved.get("automation_file") != result.test_file
            or approved.get("automation_sha256") != result.test_sha256
        ):
            return False

    catalog_hash = manifest.get("approved_regression_catalog_sha256")
    if approved_by_id and not isinstance(catalog_hash, str):
        return False
    if catalog_hash is not None:
        catalog_file = run_dir / "approved_regression_catalog.json"
        if (
            not isinstance(catalog_hash, str)
            or not catalog_file.is_file()
            or _sha256_file(catalog_file) != catalog_hash
        ):
            return False
        try:
            snapshot_by_id = {
                item.tc_id: item
                for item in _catalog_from_snapshot(
                    _read_json_payload(catalog_file)
                )
                if item.source == "APPROVED"
            }
        except (TypeError, ValueError, ValidationError):
            return False
        for tc_id, approved in approved_by_id.items():
            snapshot = snapshot_by_id.get(tc_id)
            if (
                snapshot is None
                or snapshot.automation_file != approved.get("automation_file")
                or snapshot.automation_sha256
                != approved.get("automation_sha256")
            ):
                return False
    return True


_HUMAN_REVIEW_DOCUMENT = "사람_최종_검토.md"
_HUMAN_REVIEW_MANIFEST = "사람_최종_검토_manifest.json"


def _markdown_text(value: Any) -> str:
    return str(value).replace("\\", "\\\\").replace("|", "\\|").replace("\r", " ").replace("\n", " ").strip()


def _human_review_observation(
    run_dir: Path, result: NeutralExecutionResult | None
) -> str:
    if result is None:
        return "실행 결과 상세가 연결되지 않았습니다."
    for relative_name in (result.stdout_file, result.stderr_file):
        if not relative_name:
            continue
        candidate = (run_dir / relative_name).resolve()
        try:
            candidate.relative_to(run_dir.resolve())
        except ValueError:
            continue
        if not candidate.is_file():
            continue
        text = candidate.read_text(encoding="utf-8", errors="replace")[-12000:]
        mismatch = re.search(
            r"AssertionError:\s*PRODUCT_MISMATCH:\s*(.+)$",
            text,
            flags=re.MULTILINE,
        )
        if mismatch:
            return _markdown_text(mismatch.group(1)[:2000])
        restore = re.search(
            r"(?:AssertionError:\s*)?RESTORE_MISMATCH:\s*(.+)$",
            text,
            flags=re.MULTILINE,
        )
        if restore:
            return _markdown_text(restore.group(1)[:2000])
    return _markdown_text(result.raw_message or result.source_outcome)


def _human_review_markdown(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    report: FinalReport,
    design: Agent2TestDesign | None,
) -> str:
    results_by_id = {
        result.test_id: result for result in _validation_results(bundle)
    }
    candidates_by_id = (
        {test_case.tc_id: test_case for test_case in design.test_cases}
        if design is not None
        else {}
    )
    existing_by_id = {item.tc_id: item for item in EXISTING_REGRESSION_CATALOG}
    category_labels = {
        Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE: "제품 동작 불일치 후보",
        Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE: "자동화 실행 문제",
        Agent4FindingCategory.ENVIRONMENT_ISSUE: "실행 환경 문제",
        Agent4FindingCategory.INSUFFICIENT_EVIDENCE: "판정 근거 부족",
        Agent4FindingCategory.NOT_EXECUTED: "미실행",
    }
    lines = [
        "# 사람 최종 검토서",
        "",
        "> 이 문서는 자동 판정을 사람이 최종 확정하기 위한 양식입니다. `제품 동작 불일치 후보`는 제품 결함 확정이 아닙니다.",
        "> 아래 작성란을 사람이 채우면 Manifest의 문서 SHA-256과 달라지는 것이 정상입니다. Manifest 해시는 자동 생성 원본을 식별하며, 사람이 작성한 문서는 `--refresh`가 덮어쓰지 않습니다.",
        "",
        "## 1. 전체 결론 작성란",
        "",
        "- [ ] 변경 승인",
        "- [ ] 제품 수정 후 재검증",
        "- [ ] 요구사항 보완 후 새 Run 실행",
        "- [ ] 자동화 또는 환경 보완 후 재실행",
        "- [ ] 이번 변경 보류",
        "",
        "- 검토자: ____________________",
        "- 검토일: ____________________",
        "- 최종 결론과 근거: ____________________",
        "- 후속 조치 담당자·기한: ____________________",
        "",
        "## 2. 자동 실행 요약",
        "",
        "| 항목 | 결과 |",
        "|---|---|",
        f"| Run ID | `{_markdown_text(report.run_id)}` |",
        f"| Checkpoint 4 | `{report.checkpoint_status.value}` |",
        f"| 자동 권고 | `{report.recommendation.value}` |",
        f"| 전체 실행 결과 | {report.total_results}건 |",
        f"| 제품 결과 | {report.product_result_count}건 |",
        f"| 환경 점검 | {report.environment_result_count}건 |",
        f"| 사람이 판단할 항목 | {len(report.findings)}건 |",
        "",
        "## 3. 항목별 사람 판정",
        "",
    ]
    if not report.findings:
        lines.extend(["사람이 별도로 판정할 자동 검토 항목이 없습니다.", ""])
    for index, finding in enumerate(report.findings, start=1):
        result = results_by_id.get(finding.test_id or "")
        test_case = candidates_by_id.get(finding.test_id or "")
        existing = existing_by_id.get(finding.test_id or "")
        requirements = finding.requirement_ids or (
            result.requirement_ids if result is not None else []
        )
        lines.extend(
            [
                f"### 3.{index} {category_labels[finding.category]} — `{_markdown_text(finding.finding_id)}`",
                "",
                "| 구분 | 내용 |",
                "|---|---|",
                f"| 관련 TC | `{_markdown_text(finding.test_id or '연결 없음')}` |",
                f"| TC 제목 | {_markdown_text(test_case.title if test_case is not None else '기존 회귀 또는 제목 정보 없음')} |",
                f"| 관련 Requirement | {', '.join(f'`{item}`' for item in requirements) or '없음'} |",
                f"| 실행 상태 | `{result.status.value if result is not None else finding.status.value if finding.status else '없음'}` |",
                f"| 자동 분류 근거 | {_markdown_text(finding.rationale)} |",
                "",
                "#### 기대 결과",
                "",
            ]
        )
        if test_case is not None:
            for expected in test_case.expected_results:
                timing = (
                    f" — 확인 시점: {_markdown_text(expected.verify_after_step)}"
                    if expected.verify_after_step
                    else ""
                )
                lines.append(
                    f"- `{expected.result_id}` {_markdown_text(expected.statement)}{timing}"
                )
        elif existing is not None:
            lines.extend(
                f"- {_markdown_text(behavior)}" for behavior in existing.covered_behaviors
            )
        else:
            lines.append("- 구조화된 기대 결과가 연결되지 않았습니다.")
        observation_detail = _human_review_observation(run_dir, result)
        lines.extend(
            [
                "",
                "#### 실제 관찰",
                "",
                f"- {observation_detail}",
            ]
        )
        if "enabled=True" in observation_detail:
            lines.append(
                "- `enabled=True`는 비활성화 기대와 달리 버튼이 실제로 활성 상태였음을 뜻합니다."
            )
        if (
            test_case is not None
            and result is not None
            and result.status == NeutralExecutionStatus.ASSERTION_FAILED
        ):
            mismatch_result_ids = set(re.findall(r"ER-\d{3}", observation_detail))
            lines.extend(
                f"- `{expected.result_id}`: 이 요약에서 개별 판정이 확인되지 않습니다. 원본 실행 증거를 확인해 주세요."
                for expected in test_case.expected_results
                if expected.result_id not in mismatch_result_ids
            )
        lines.extend(["", "#### 실행 증거", ""])
        evidence_files = finding.evidence_files or (
            result.evidence_files if result is not None else []
        )
        if evidence_files:
            lines.extend(
                f"- [{_markdown_text(Path(item).name)}]({_markdown_text(item)})"
                for item in evidence_files
            )
        else:
            lines.append("- 연결된 증거 파일이 없습니다.")
        lines.extend(
            [
                "",
                "#### 사람 판정",
                "",
                "- [ ] 요구사항이 맞으며 제품 구현 수정이 필요함",
                "- [ ] 제품 동작이 맞으며 요구사항 수정 또는 명확화가 필요함",
                "- [ ] 자동화 계획·코드·Selector를 재검토해야 함",
                "- [ ] 실행 환경을 보완해 다시 실행해야 함",
                "- [ ] 현재 근거로 종결 가능함",
                "",
                "- 선택 근거: ____________________",
                "- 후속 조치: ____________________",
                "- 재검증 필요 여부·조건: ____________________",
                "",
            ]
        )
    lines.extend(["## 4. 기준 SRS 개정 승인", ""])
    if report.srs_revision_proposals:
        lines.extend(
            [
                "> 아래 문구는 Agent 2의 제안이며 자동으로 SRS에 반영되지 않습니다. 현재 문구와 제안 문구를 검토한 뒤 공식 자산 승인 화면에서 SRS 개정 포함 여부를 사람이 결정합니다.",
                "",
            ]
        )
        for proposal in report.srs_revision_proposals:
            lines.extend(
                [
                    f"### `{_markdown_text(proposal.proposal_id)}` · `{_markdown_text(proposal.requirement_id)}`",
                    "",
                    f"- 현재 인수 기준: {_markdown_text(proposal.current_acceptance_criteria)}",
                    f"- 제안 인수 기준: {_markdown_text(proposal.proposed_acceptance_criteria)}",
                    f"- 근거 Condition: {', '.join(f'`{item}`' for item in proposal.source_condition_ids)}",
                    f"- 개정 이유: {_markdown_text(proposal.reason)}",
                    "- [ ] 이 인수 기준 개정을 승인함",
                    "- 검토 메모: ____________________",
                    "",
                ]
            )
    else:
        lines.extend(["SRS 개정 제안이 없습니다.", ""])
    lines.extend(["## 5. 추가 확인 사항", ""])
    if report.final_review_notes:
        lines.extend(f"- {_markdown_text(item)}" for item in report.final_review_notes)
    else:
        lines.append("- 없음")
    lines.extend(["", "## 6. 실행에서 제외된 항목", ""])
    if report.excluded_information_gaps:
        lines.append("### 정보 부족으로 제외")
        lines.append("")
        lines.extend(
            f"- {_markdown_text(item)}" for item in report.excluded_information_gaps
        )
        lines.append("")
    if report.automation_exclusions:
        lines.append("### 자동화 지원 범위로 실행하지 못한 TC")
        lines.append("")
        lines.extend(
            f"- `{item.tc_id}` {_markdown_text(item.reason)}"
            for item in report.automation_exclusions
        )
        lines.append("")
    if not report.excluded_information_gaps and not report.automation_exclusions:
        lines.extend(["정보 부족 또는 자동화 한계로 제외된 TC가 없습니다.", ""])
    lines.extend(
        [
            "## 7. 범위 경계",
            "",
            *(f"- {_markdown_text(item)}" for item in report.excluded_scope),
            "",
            "## 8. 원본 무결성 참조",
            "",
            f"- `final_report.json` SHA-256: `{_sha256_file(run_dir / 'final_report.json')}`",
            f"- `validation_execution.json` SHA-256: `{_sha256_file(run_dir / 'validation_execution.json')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _write_human_review_document(
    run_dir: Path,
    bundle: ValidationExecutionBundle,
    report: FinalReport,
    design: Agent2TestDesign | None,
    *,
    refresh: bool = False,
) -> tuple[Path, Path]:
    document_file = run_dir / _HUMAN_REVIEW_DOCUMENT
    manifest_file = run_dir / _HUMAN_REVIEW_MANIFEST
    document = _human_review_markdown(run_dir, bundle, report, design)
    document_changed = (
        document_file.exists()
        and document_file.read_text(encoding="utf-8") != document
    )
    if document_changed and not refresh:
        raise ValueError(
            "기존 사람 최종 검토 문서와 현재 생성 결과가 다릅니다. "
            "검증된 자동 생성 문서를 갱신하려면 --refresh를 사용하세요."
        )
    if document_changed and refresh:
        if not manifest_file.is_file():
            raise ValueError("기존 사람 최종 검토 문서의 Manifest가 없어 안전하게 갱신할 수 없습니다.")
        previous_manifest = _read_json_payload(manifest_file)
        if (
            previous_manifest.get("document_sha256") != _sha256_file(document_file)
            or previous_manifest.get("final_report_sha256")
            != _sha256_file(run_dir / "final_report.json")
        ):
            raise ValueError("기존 사람 최종 검토 문서 또는 원본 보고 해시가 달라 갱신을 차단했습니다.")
    if not document_file.exists() or document_changed:
        document_file.write_text(document, encoding="utf-8", newline="\n")
    manifest_payload = {
        "contract_version": "1.0",
        "run_id": report.run_id,
        "stage": "HUMAN_FINAL_REVIEW_DOCUMENT",
        "document_file": document_file.name,
        "document_sha256": _sha256_file(document_file),
        "final_report_sha256": _sha256_file(run_dir / "final_report.json"),
        "validation_execution_sha256": _sha256_file(
            run_dir / "validation_execution.json"
        ),
        "created_at": report.created_at,
    }
    if manifest_file.exists():
        existing_manifest = _read_json_payload(manifest_file)
        if existing_manifest != manifest_payload:
            if not refresh:
                raise ValueError("기존 사람 최종 검토 Manifest와 현재 검증 결과가 다릅니다.")
            _write_json(manifest_file, manifest_payload)
    else:
        _write_json(manifest_file, manifest_payload)
    return document_file, manifest_file


def run_human_review_document(args: argparse.Namespace) -> int:
    """Create an idempotent, human-readable decision form from verified results."""
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    report = _read_json_model(run_dir / "final_report.json", FinalReport)
    checkpoint = _read_json_model(run_dir / "checkpoint4.json", Checkpoint4Result)
    analysis_file = run_dir / "agent4_analysis.json"
    if (
        report.run_id != args.run_id
        or report.analysis_sha256 != _sha256_file(analysis_file)
        or report.checkpoint4_sha256 != _sha256_file(run_dir / "checkpoint4.json")
        or checkpoint.status != report.checkpoint_status
    ):
        raise ValueError("Checkpoint 4 또는 최종 보고 무결성이 일치하지 않습니다.")
    bundle = _read_json_model(
        run_dir / "validation_execution.json", ValidationExecutionBundle
    )
    design_file = run_dir / "agent2_test_design.json"
    design = (
        _read_json_model(design_file, Agent2TestDesign)
        if design_file.is_file()
        else None
    )
    document_file, manifest_file = _write_human_review_document(
        run_dir,
        bundle,
        report,
        design,
        refresh=getattr(args, "refresh", False),
    )
    print(f"사람 최종 검토 문서: {document_file.relative_to(run_dir).as_posix()}")
    print(f"문서 무결성 증거: {manifest_file.relative_to(run_dir).as_posix()}")
    return 0


def _slack_report_payload(report: FinalReport) -> dict[str, Any]:
    status_lines = [
        f"{status.value}: {report.status_counts.get(status, 0)}"
        for status in NeutralExecutionStatus
    ]
    finding_lines = [
        f"• {item.finding_id} | {item.category.value} | {item.test_id or '-'}"
        for item in report.findings
    ] or ["• 검토 항목 없음"]
    exclusion_lines = [
        f"• {item.tc_id} | {item.candidate_status.value}"
        for item in report.automation_exclusions
    ] or ["• 자동화 제외 없음"]
    return {
        "blocks": [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": f"QA 변경 검증 결과 · {report.recommendation.value}",
                },
            },
            {
                "type": "section",
                "fields": [
                    {"type": "mrkdwn", "text": f"*Run ID*\n{report.run_id}"},
                    {
                        "type": "mrkdwn",
                        "text": f"*Checkpoint 4*\n{report.checkpoint_status.value}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*제품 결과*\n{report.product_result_count}",
                    },
                    {
                        "type": "mrkdwn",
                        "text": f"*환경 점검*\n{report.environment_result_count}",
                    },
                ],
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*상태 집계*\n" + "\n".join(status_lines),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*검토 항목*\n" + "\n".join(finding_lines),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "*자동화 제외 TC*\n" + "\n".join(exclusion_lines),
                },
            },
        ]
    }


def build_run_test_rows(run_dir: Path) -> list[dict[str, Any]]:
    """저장된 Run의 설계·실행·분류를 합칩니다. 미실행을 통과로 추정하지 않습니다."""
    def read(name: str) -> dict[str, Any]:
        path = run_dir / name
        return _read_json_payload(path) if path.is_file() else {}

    design = read("agent2_test_design.json")
    bundle = read("validation_execution.json")
    report = read("final_report.json")
    summary = read("agent3_run_summary.json")
    cases = {item["tc_id"]: item for item in design.get("test_cases", [])}
    catalog = _catalog_from_snapshot(read("approved_regression_catalog.json"))
    specs = {item.tc_id: item for item in (*catalog, ENVIRONMENT_PRECHECK)}
    approved_root = Path(__file__).resolve().parents[1] / "approved_assets"
    for spec in catalog:
        if spec.source != "APPROVED" or not spec.test_case_file:
            continue
        path = (approved_root / spec.test_case_file).resolve()
        if (path.is_relative_to(approved_root.resolve()) and path.is_file()
                and _sha256_file(path) == spec.test_case_sha256):
            cases[spec.tc_id] = _read_json_payload(path).get("test_case", {})
    results = {
        item["test_id"]: item for item in [
            *bundle.get("candidate_results", []),
            *([bundle["candidate_result"]] if not bundle.get("candidate_results") and bundle.get("candidate_result") else []),
            *([bundle["environment_precheck"]] if bundle.get("environment_precheck") else []),
            *bundle.get("regression_results", []),
        ]
    }
    exclusions = {
        item["tc_id"]: item for item in (
            bundle.get("자동화_제외_TC") or summary.get("자동화_제외_TC") or []
        )
    }
    findings = {item.get("test_id"): item for item in report.get("검토_항목", [])}
    labels = {
        "PRODUCT_MISMATCH_CANDIDATE": "제품 동작 불일치 후보",
        "AUTOMATION_EXECUTION_ISSUE": "자동화 실행 문제",
        "ENVIRONMENT_ISSUE": "실행 환경 문제",
        "INSUFFICIENT_EVIDENCE": "판정 근거 부족", "NOT_EXECUTED": "미실행",
    }
    types = {"NORMAL": "해피패스", "BOUNDARY": "엣지케이스", "EXCEPTION": "예외/결함", "STATE_CONSISTENCY": "상태 정합성"}
    selected = design.get("관련_기존_TC") or design.get("related_existing_tests") or []
    ids = list(dict.fromkeys([
        *(["TC-ENV-000"] if "TC-ENV-000" in results else []),
        *[item["tc_id"] for item in design.get("test_cases", [])],
        *[item["tc_id"] for item in selected], *results, *exclusions,
    ]))
    rows = []
    for tc_id in ids:
        case, result, finding = cases.get(tc_id, {}), results.get(tc_id, {}), findings.get(tc_id, {})
        spec = specs.get(tc_id)
        excluded = exclusions.get(tc_id)
        manual = case.get("automation_candidate") is False and tc_id.startswith("TC-CAND-")
        status = result.get("status") or ("MANUAL_REVIEW" if manual else "NOT_EXECUTED")
        category = "사전 점검" if tc_id == "TC-ENV-000" else types.get(case.get("test_type"), "미분류")
        classification = labels.get(finding.get("category"), "")
        if not classification:
            classification = "정상 동작" if status == "PASSED" else "수동 확인 필요" if manual else "자동화 제외" if excluded else "분류 전" if result else "미실행"
        expected = [item["statement"] for item in case.get("expected_results", [])]
        if not expected and spec:
            expected = list(spec.covered_behaviors)
        rows.append({
            "tc_id": tc_id, "category": category,
            "title": case.get("title") or (spec.covered_behaviors[0] if spec and spec.covered_behaviors else tc_id),
            "status": status, "priority": case.get("priority") or "미지정",
            "classification": classification,
            "reason": (finding.get("rationale") or (excluded or {}).get("reason")
                       or (case.get("automation_reason") if manual else "") or result.get("raw_message") or ""),
            "preconditions": case.get("preconditions") or [], "steps": case.get("steps") or [],
            "expected_results": expected, "restore_steps": case.get("restore_steps") or [],
            "requirement_ids": case.get("requirement_ids") or result.get("requirement_ids") or (list(spec.requirement_ids) if spec else []),
            "source": "환경 점검" if tc_id == "TC-ENV-000" else "신규·수정 후보" if tc_id.startswith("TC-CAND-") else "기존 TC",
            "executed_at": bundle.get("created_at") if result else None,
            "duration_ms": result.get("duration_ms"),
            "evidence_files": [name for name in result.get("evidence_files", []) if _safe_run_file(run_dir, name)],
        })
    return rows


def _notion_report_records(
    bundle: ValidationExecutionBundle, report: FinalReport, run_dir: Path | None = None
) -> list[dict[str, Any]]:
    findings_by_test = {
        item.test_id: item for item in report.findings if item.test_id is not None
    }
    rows = {item["tc_id"]: item for item in build_run_test_rows(run_dir)} if run_dir else {}
    records: list[dict[str, Any]] = []
    for result in _validation_results(bundle):
        finding = findings_by_test.get(result.test_id)
        records.append(
            {
                "run_id": report.run_id,
                "tc_id": result.test_id,
                "source": result.source.value,
                "requirement_ids": result.requirement_ids,
                "result": result.status.value,
                "finding_category": (
                    finding.category.value if finding is not None else "NONE"
                ),
                "recommendation": report.recommendation.value,
                "evidence_complete": result.evidence_complete,
                "title": rows.get(result.test_id, {}).get("title", result.test_id),
                "test_category": rows.get(result.test_id, {}).get("category", "미분류"),
                "priority": rows.get(result.test_id, {}).get("priority", "미지정"),
            }
        )
    return records


def _http_json_request(
    method: str,
    url: str,
    payload: dict[str, Any],
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
) -> tuple[int, Any]:
    request_headers = {"Content-Type": "application/json", **(headers or {})}
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method=method,
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read().decode("utf-8", errors="replace")
        try:
            body: Any = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            body = raw
        return int(response.status), body


def _send_slack_report(payload: dict[str, Any]) -> ExternalDestinationResult:
    webhook_url = os.getenv("SLACK_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.SKIPPED,
            detail="SLACK_WEBHOOK_URL 환경변수가 없어 전송하지 않았습니다.",
        )
    try:
        status, _ = _http_json_request("POST", webhook_url, payload, timeout=15)
        if not 200 <= status < 300:
            raise RuntimeError(f"HTTP {status}")
        return ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.SENT,
            item_count=1,
            detail="검증된 최종 보고를 Slack으로 전송했습니다.",
        )
    except Exception as exc:
        return ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.FAILED,
            detail=f"Slack 전송 실패: {type(exc).__name__}",
        )


def _notion_status_name(status: str) -> str:
    return {
        NeutralExecutionStatus.PASSED.value: "Pass",
        NeutralExecutionStatus.ASSERTION_FAILED.value: "Fail",
        NeutralExecutionStatus.EXECUTION_ERROR.value: "Blocker",
        NeutralExecutionStatus.TIMEOUT.value: "Blocker",
        NeutralExecutionStatus.SKIPPED.value: "Review Needed",
    }.get(status, "Review Needed")


def _upsert_notion_reports(
    records: list[dict[str, Any]],
) -> ExternalDestinationResult:
    notion_token = os.getenv("NOTION_API_KEY", "").strip()
    data_source_id = os.getenv("NOTION_DATA_SOURCE_ID", "").strip()
    if not notion_token or not data_source_id:
        return ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.SKIPPED,
            detail="NOTION_API_KEY 또는 NOTION_DATA_SOURCE_ID 환경변수가 없어 전송하지 않았습니다.",
        )
    headers = {
        "Authorization": f"Bearer {notion_token}",
        "Notion-Version": "2026-03-11",
    }
    completed = 0
    try:
        for record in records:
            tc_id = str(record["tc_id"])
            execution_key = f"{record['run_id']}:{tc_id}"
            query_status, query_body = _http_json_request(
                "POST",
                f"https://api.notion.com/v1/data_sources/{data_source_id}/query",
                {
                    "filter": {
                        "property": "TC-ID",
                        "title": {"equals": execution_key},
                    },
                    "page_size": 1,
                },
                headers=headers,
            )
            if not 200 <= query_status < 300 or not isinstance(query_body, dict):
                raise RuntimeError(f"Notion query HTTP {query_status}")
            finding = str(record["finding_category"])
            category = record.get("test_category", "미분류")
            properties = {
                "TC-ID": {"title": [{"text": {"content": execution_key}}]},
                "테스트 제목": {
                    "rich_text": [{"text": {"content": str(record.get("title") or tc_id)[:2000]}}]
                },
                "실행 결과": {
                    "select": {"name": _notion_status_name(str(record["result"]))}
                },
                "결과 ": {
                    "rich_text": [
                        {
                            "text": {
                                "content": (
                                    f"Run {record['run_id']} | {record['result']} | "
                                    f"{finding} | {record['recommendation']}"
                                )[:2000]
                            }
                        }
                    ]
                },
                "구분": {"select": {"name": category}},
            }
            if record.get("priority") in {"P1", "P2", "P3"}:
                properties["우선 순위"] = {"select": {"name": record["priority"]}}
            results = query_body.get("results", [])
            if results:
                url = f"https://api.notion.com/v1/pages/{results[0]['id']}"
                method = "PATCH"
                payload = {"properties": properties}
            else:
                url = "https://api.notion.com/v1/pages"
                method = "POST"
                payload = {
                    "parent": {"type": "data_source_id", "data_source_id": data_source_id},
                    "properties": properties,
                }
            mutation_status, _ = _http_json_request(
                method, url, payload, headers=headers
            )
            if not 200 <= mutation_status < 300:
                raise RuntimeError(f"Notion mutation HTTP {mutation_status}")
            completed += 1
        return ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.SENT,
            item_count=completed,
            detail=f"Run ID와 TC ID 기준으로 Notion {completed}건을 Upsert했습니다.",
        )
    except Exception as exc:
        return ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.FAILED,
            item_count=completed,
            detail=f"Notion Upsert 실패: {type(exc).__name__}",
        )


def run_external_reporting(args: argparse.Namespace) -> int:
    """Preview or send a previously validated Agent 4 report."""

    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    base_output_file = run_dir / "external_reporting.json"
    base_payload_files = (
        run_dir / "slack_payload.json",
        run_dir / "notion_payload.json",
    )
    if not base_output_file.exists() and any(
        path.exists() for path in base_payload_files
    ):
        raise ValueError("완료 결과가 없는 기존 외부 보고 Payload가 있어 덮어쓸 수 없습니다.")
    previous_reporting_sha256: str | None = None
    attempt_id: str | None = None
    if base_output_file.exists():
        previous = _read_json_model(base_output_file, ExternalReportingResult)
        if previous.run_id != args.run_id:
            raise ValueError("기존 외부 보고 Run ID가 요청과 다릅니다.")
        previous_reporting_sha256 = _sha256_file(base_output_file)
        attempt_id = (
            "ATTEMPT-"
            + datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
            + "-"
            + uuid.uuid4().hex[:6].upper()
        )
        output_dir = run_dir / "external_reporting_attempts" / attempt_id
    else:
        output_dir = run_dir
    output_file = output_dir / "external_reporting.json"
    slack_payload_file = output_dir / "slack_payload.json"
    notion_payload_file = output_dir / "notion_payload.json"
    if output_dir != run_dir and output_dir.exists():
        raise ValueError("동일한 외부 보고 시도 폴더가 이미 존재합니다.")
    final_report_file = run_dir / "final_report.json"
    checkpoint_file = run_dir / "checkpoint4.json"
    analysis_file = run_dir / "agent4_analysis.json"
    execution_file = run_dir / "validation_execution.json"
    report = _read_json_model(final_report_file, FinalReport)
    checkpoint = _read_json_model(checkpoint_file, Checkpoint4Result)
    bundle = _read_json_model(execution_file, ValidationExecutionBundle)
    allowed = (
        report.run_id == args.run_id == bundle.run_id
        and report.checkpoint_status == CheckStatus.PASS
        and checkpoint.status == CheckStatus.PASS
        and checkpoint.handoff_status == HandoffStatus.CONTINUE
        and report.analysis_sha256 == _sha256_file(analysis_file)
        and report.checkpoint4_sha256 == _sha256_file(checkpoint_file)
    )
    mode = "SEND" if getattr(args, "send", False) else "DRY_RUN"
    if not allowed:
        slack = ExternalDestinationResult(
            destination="SLACK",
            status=ExternalDeliveryStatus.BLOCKED,
            detail="Checkpoint 4 또는 최종 보고 무결성이 통과하지 않아 전송을 차단했습니다.",
        )
        notion = ExternalDestinationResult(
            destination="NOTION",
            status=ExternalDeliveryStatus.BLOCKED,
            detail="Checkpoint 4 또는 최종 보고 무결성이 통과하지 않아 전송을 차단했습니다.",
        )
    else:
        slack_payload = _slack_report_payload(report)
        notion_records = _notion_report_records(bundle, report, run_dir)
        _write_json(slack_payload_file, slack_payload)
        _write_json(notion_payload_file, {"records": notion_records})
        if mode == "SEND":
            slack = _send_slack_report(slack_payload)
            notion = _upsert_notion_reports(notion_records)
        else:
            slack = ExternalDestinationResult(
                destination="SLACK",
                status=ExternalDeliveryStatus.PREVIEW,
                item_count=1,
                detail="Slack Payload를 생성했으며 외부 전송은 하지 않았습니다.",
            )
            notion = ExternalDestinationResult(
                destination="NOTION",
                status=ExternalDeliveryStatus.PREVIEW,
                item_count=len(notion_records),
                detail="Notion Upsert Payload를 생성했으며 외부 변경은 하지 않았습니다.",
            )
        slack = slack.model_copy(
            update={
                "payload_file": slack_payload_file.relative_to(run_dir).as_posix(),
                "payload_sha256": _sha256_file(slack_payload_file),
            }
        )
        notion = notion.model_copy(
            update={
                "payload_file": notion_payload_file.relative_to(run_dir).as_posix(),
                "payload_sha256": _sha256_file(notion_payload_file),
            }
        )
    result = ExternalReportingResult(
        run_id=args.run_id,
        mode=mode,
        final_report_sha256=_sha256_file(final_report_file),
        checkpoint4_sha256=_sha256_file(checkpoint_file),
        attempt_id=attempt_id,
        previous_reporting_sha256=previous_reporting_sha256,
        allowed=allowed,
        slack=slack,
        notion=notion,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    _write_json(output_file, result.model_dump(mode="json"))
    print(f"Slack 보고: {slack.status.value}")
    print(f"Notion 보고: {notion.status.value}")
    print(f"외부 보고 증거: {output_file.relative_to(run_dir).as_posix()}")
    if not allowed:
        return 2
    if ExternalDeliveryStatus.FAILED in {slack.status, notion.status}:
        return 3
    return 0


def run_agent4(args: argparse.Namespace) -> int:
    """Analyze one verified validation bundle without rerunning tests or calling a model."""
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    outputs = (
        run_dir / "agent4_analysis.json",
        run_dir / "checkpoint4.json",
        run_dir / "final_report.json",
        run_dir / _HUMAN_REVIEW_DOCUMENT,
        run_dir / _HUMAN_REVIEW_MANIFEST,
        run_dir / "agent4_error.json",
    )
    if any(path.exists() for path in outputs):
        raise ValueError("이 Run에는 이미 Agent 4 보고 산출물이 있습니다. 기존 증거를 덮어쓸 수 없습니다.")
    try:
        execution_file = run_dir / "validation_execution.json"
        bundle = _read_json_model(execution_file, ValidationExecutionBundle)
        manifest = _read_json_payload(run_dir / "validation_manifest.json")
        checks: list[CheckResult] = []
        manifest_hash = manifest.get("validation_execution_sha256")
        execution_hash_matches = (
            isinstance(manifest_hash, str)
            and manifest_hash == _sha256_file(execution_file)
        )
        source_agent3_manifest = run_dir / "agent3_manifest.json"
        source_agent3_trial = run_dir / "agent3_trial.json"
        common_source_chain_matches = (
            manifest.get("stage") == "VALIDATION_EXECUTION"
            and manifest.get("status") == bundle.status.value
            and manifest.get("project1_modified") is False
            and all(
                result.target_sha256 == manifest.get("target_sha256")
                for result in bundle.candidate_results
            )
            and all(
                result.target_sha256 == manifest.get("target_sha256")
                for result in _validation_results(bundle)
            )
            and _agent4_regression_source_chain_matches(
                run_dir, bundle, manifest
            )
        )
        new_source_chain_matches = _agent4_new_source_chain_matches(
            run_dir, bundle, manifest
        )
        if new_source_chain_matches is None:
            source_chain_matches = (
                common_source_chain_matches
                and source_agent3_manifest.is_file()
                and source_agent3_trial.is_file()
                and manifest.get("source_agent3_manifest_sha256")
                == _sha256_file(source_agent3_manifest)
                and manifest.get("source_agent3_trial_sha256")
                == _sha256_file(source_agent3_trial)
                and manifest.get("candidate_reused") == bundle.candidate_result.reused
                and manifest.get("validation_candidate_sha256")
                == bundle.candidate_result.test_sha256
                and _agent4_candidate_artifact_matches(
                    run_dir, bundle.candidate_result
                )
            )
            validation_trial_hash = manifest.get("validation_candidate_trial_sha256")
            validation_trial_file = run_dir / "validation_candidate_trial.json"
            validation_trial_matches = (
                bundle.candidate_result.reused
                and validation_trial_hash is None
                and not validation_trial_file.exists()
                or not bundle.candidate_result.reused
                and isinstance(validation_trial_hash, str)
                and validation_trial_file.is_file()
                and validation_trial_hash == _sha256_file(validation_trial_file)
            )
        else:
            source_chain_matches = (
                common_source_chain_matches and new_source_chain_matches
            )
            validation_trial_matches = True
        hash_matches = (
            execution_hash_matches
            and source_chain_matches
            and validation_trial_matches
        )
        checks.append(
            CheckResult(
                rule_id="CP4-001",
                status=CheckStatus.PASS if bundle.run_id == args.run_id and manifest.get("run_id") == args.run_id else CheckStatus.FAIL,
                message="단일 Run ID가 실행 결과와 Manifest에 일치합니다."
                if bundle.run_id == args.run_id and manifest.get("run_id") == args.run_id
                else "실행 결과 또는 Manifest의 Run ID가 요청 Run ID와 다릅니다.",
            )
        )
        checks.append(
            CheckResult(
                rule_id="CP4-002",
                status=CheckStatus.PASS if hash_matches else CheckStatus.FAIL,
                message="검증 실행·Agent 3·후보·대상·기존 테스트 SHA-256 체인이 Manifest와 일치합니다."
                if hash_matches
                else "검증 실행 또는 이전 단계 SHA-256 체인이 Manifest와 일치하지 않습니다.",
            )
        )
        results = _validation_results(bundle)
        test_ids = [result.test_id for result in results]
        duplicate_ids = sorted({test_id for test_id in test_ids if test_ids.count(test_id) > 1})
        checks.append(
            CheckResult(
                rule_id="CP4-003",
                status=CheckStatus.PASS if not duplicate_ids else CheckStatus.FAIL,
                message="실행 결과에 중복 TC가 없습니다."
                if not duplicate_ids
                else f"실행 결과에 중복 TC가 있습니다: {', '.join(duplicate_ids)}",
            )
        )
        source_contract_ok = (
            all(
                result.source == ExecutionSource.NEW_AUTOMATION_CANDIDATE
                for result in bundle.candidate_results
            )
            and bundle.environment_precheck.source == ExecutionSource.ENVIRONMENT_PRECHECK
            and all(
                result.source == ExecutionSource.EXISTING_REGRESSION
                for result in bundle.regression_results
            )
        )
        status_contract_issues = _agent4_status_contract_issues(results)
        source_contract_issues = [] if source_contract_ok else [
            "후보·환경 사전 점검·기존 회귀의 출처가 계약과 다릅니다"
        ]
        source_contract_issues.extend(status_contract_issues)
        source_contract_ok = source_contract_ok and not status_contract_issues
        checks.append(
            CheckResult(
                rule_id="CP4-004",
                status=CheckStatus.PASS if source_contract_ok else CheckStatus.FAIL,
                message="후보·환경 사전 점검·기존 회귀의 출처·상태·종료 코드가 계약과 일치합니다."
                if source_contract_ok
                else (
                    "실행 결과 출처 또는 상태 계약이 일치하지 않습니다: "
                    + "; ".join(source_contract_issues)
                ),
            )
        )
        regression_ids = [result.test_id for result in bundle.regression_results]
        regression_execution_ok = (
            (
                bundle.status == ValidationStageStatus.COMPLETED
                and bundle.environment_precheck.status
                == NeutralExecutionStatus.PASSED
                and bundle.blocked_reason is None
                and regression_ids == bundle.selected_regression_ids
            )
            or (
                bundle.status == ValidationStageStatus.BLOCKED
                and bundle.environment_precheck.status
                != NeutralExecutionStatus.PASSED
                and not regression_ids
                and bundle.blocked_reason == "ENVIRONMENT_PRECHECK_NOT_PASSED"
            )
        )
        checks.append(
            CheckResult(
                rule_id="CP4-005",
                status=CheckStatus.PASS if regression_execution_ok else CheckStatus.FAIL,
                message="선택된 기존 회귀의 실행 수와 차단 상태가 실행 결과와 일치합니다."
                if regression_execution_ok
                else "선택된 기존 회귀의 실행 결과 또는 차단 상태가 일치하지 않습니다.",
            )
        )
        evidence_issues = _agent4_evidence_issues(run_dir, results)
        checks.append(
            CheckResult(
                rule_id="CP4-006",
                status=CheckStatus.PASS if not evidence_issues else CheckStatus.FAIL,
                message="실행 증거 파일의 경로·존재·SHA-256이 계약과 일치합니다."
                if not evidence_issues
                else f"실행 증거 검증 실패: {'; '.join(evidence_issues)}",
            )
        )
        environment_results = [
            result
            for result in results
            if result.source == ExecutionSource.ENVIRONMENT_PRECHECK
        ]
        fixture_results = [
            result
            for result in results
            if result.source != ExecutionSource.ENVIRONMENT_PRECHECK
            and result.test_id.startswith("TC-PIPE-")
        ]
        product_results = [
            result
            for result in results
            if result.source != ExecutionSource.ENVIRONMENT_PRECHECK
            and not result.test_id.startswith("TC-PIPE-")
        ]
        checks.append(
            CheckResult(
                rule_id="CP4-007",
                status=CheckStatus.PASS,
                message=(
                    "제품 TC와 파이프라인 고정 사례를 분리했습니다. "
                    f"제품 TC {len(product_results)}건, 환경 점검 {len(environment_results)}건, "
                    f"고정 사례 {len(fixture_results)}건입니다."
                ),
            )
        )
        checkpoint_status = (
            CheckStatus.PASS
            if all(check.status == CheckStatus.PASS for check in checks)
            else CheckStatus.FAIL
        )
        checkpoint = Checkpoint4Result(
            status=checkpoint_status,
            handoff_status=(HandoffStatus.CONTINUE if checkpoint_status == CheckStatus.PASS else HandoffStatus.BLOCKED),
            checks=checks,
        )
        findings: list[Agent4Finding] = []
        for result in results:
            finding = _agent4_finding_for_result(result, len(findings) + 1)
            if finding is not None:
                findings.append(finding)
        if bundle.status == ValidationStageStatus.BLOCKED:
            findings.append(
                Agent4Finding(
                    finding_id=f"FIND-{len(findings) + 1:03d}",
                    category=Agent4FindingCategory.INSUFFICIENT_EVIDENCE,
                    rationale="환경 사전 점검 차단으로 선택된 관련 회귀가 실행되지 않았습니다.",
                )
            )
        status_counts = {status: sum(result.status == status for result in results) for status in NeutralExecutionStatus}
        recommendation = _agent4_recommendation(findings, checkpoint_status)
        if (
            recommendation == FinalRecommendation.PASS
            and not bundle.candidate_results
            and bundle.automation_exclusions
        ):
            recommendation = FinalRecommendation.HUMAN_REVIEW
        analysis = Agent4Analysis(
            run_id=args.run_id,
            validation_execution_sha256=_sha256_file(execution_file),
            total_results=len(results),
            status_counts=status_counts,
            product_result_count=len(product_results),
            environment_result_count=len(environment_results),
            pipeline_fixture_result_count=len(fixture_results),
            findings=findings,
            excluded_scope=bundle.excluded_scope,
            excluded_information_gaps=bundle.excluded_information_gaps,
            final_review_notes=bundle.final_review_notes,
            srs_revision_proposals=bundle.srs_revision_proposals,
            automation_exclusions=bundle.automation_exclusions,
            recommendation=recommendation,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        analysis_file = run_dir / "agent4_analysis.json"
        checkpoint_file = run_dir / "checkpoint4.json"
        _write_json(analysis_file, analysis.model_dump(mode="json", by_alias=True))
        _write_json(checkpoint_file, checkpoint.model_dump(mode="json", by_alias=True))
        report = FinalReport(
            run_id=args.run_id,
            analysis_sha256=_sha256_file(analysis_file),
            checkpoint4_sha256=_sha256_file(checkpoint_file),
            total_results=analysis.total_results,
            status_counts=analysis.status_counts,
            product_result_count=analysis.product_result_count,
            environment_result_count=analysis.environment_result_count,
            pipeline_fixture_result_count=analysis.pipeline_fixture_result_count,
            findings=analysis.findings,
            excluded_scope=analysis.excluded_scope,
            excluded_information_gaps=analysis.excluded_information_gaps,
            final_review_notes=analysis.final_review_notes,
            srs_revision_proposals=analysis.srs_revision_proposals,
            automation_exclusions=analysis.automation_exclusions,
            recommendation=analysis.recommendation,
            checkpoint_status=checkpoint.status,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        _write_json(run_dir / "final_report.json", report.model_dump(mode="json", by_alias=True))
        design_file = run_dir / "agent2_test_design.json"
        design = (
            _read_json_model(design_file, Agent2TestDesign)
            if design_file.is_file()
            else None
        )
        _write_human_review_document(run_dir, bundle, report, design)
    except Exception as exc:
        _write_json(
            run_dir / "agent4_error.json",
            {"run_id": args.run_id, "stage": "AGENT_4_ANALYSIS", "error_type": type(exc).__name__, "message": str(exc), "created_at": datetime.now(timezone.utc).isoformat()},
        )
        raise
    print(f"Run ID: {args.run_id}")
    print(f"Checkpoint 4: {checkpoint.status.value}")
    print(f"최종 권고: {report.recommendation.value}")
    print(f"검토 항목: {len(report.findings)}")
    print(f"사람 최종 검토 문서: {_HUMAN_REVIEW_DOCUMENT}")
    print(f"산출물 위치: {run_dir}")
    delivery_exit = run_external_reporting(
        argparse.Namespace(
            run_id=args.run_id,
            runs_root=args.runs_root,
            send=getattr(args, "send", False),
        )
    )
    return delivery_exit if checkpoint.status == CheckStatus.PASS else 2

__all__ = [name for name in globals() if not name.startswith("__")]
