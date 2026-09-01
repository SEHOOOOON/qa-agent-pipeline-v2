"""로컬 중앙제어 화면과 QA Pipeline V2 Run 산출물을 연결하는 브리지."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RUNS_ROOT = REPO_ROOT / "runs"
DEFAULT_REQUESTS_ROOT = REPO_ROOT / "examples"
DEFAULT_TARGET_HTML = REPO_ROOT / "product_baseline" / "virtual-controller.html"
DEFAULT_APPROVED_ASSETS_ROOT = REPO_ROOT / "approved_assets"
DEFAULT_SRS = REPO_ROOT / "docs" / "01_PRODUCT_SRS.md"
RUN_ID_PATTERN = re.compile(r"^RUN-\d{8}-\d{6}-[A-F0-9]{6}$")
REQUEST_FILE_PATTERN = re.compile(r"^change_request(?:\.[a-z0-9-]+)?\.json$")
TC_ID_PATTERN = re.compile(r"^TC-CAND-\d{3}$")
LIVE_RUN_LOCK_FILE = ".qa-pipeline-live.lock"
ASSET_APPROVAL_LOCK_FILE = ".qa-pipeline-asset-approval.lock"
UI_CANDIDATE_TIMEOUT_SECONDS = 90


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload if isinstance(payload, dict) else {}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _safe_text(value: Any, *, field_name: str, required: bool, limit: int) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} 입력이 필요합니다.")
    normalized = " ".join(value.split())
    if required and not normalized:
        raise ValueError(f"{field_name} 입력이 필요합니다.")
    if len(normalized) > limit:
        raise ValueError(f"{field_name} 입력은 {limit}자 이하여야 합니다.")
    return normalized


def _safe_run_error(run_dir: Path) -> str | None:
    """브라우저에 로컬 경로나 긴 원문을 노출하지 않는 Run 오류 요약."""

    candidate_files = sorted(
        (run_dir / "agent3_candidates").glob("*/agent3_error.json")
    )
    root_files = [
        run_dir / filename
        for filename in (
            "run_error.json",
            "agent1_error.json",
            "agent2_error.json",
            "agent3_error.json",
            "agent4_error.json",
        )
    ]
    for path in [*root_files, *candidate_files]:
        payload = _read_json(path)
        message = payload.get("message")
        if not isinstance(message, str) or not message.strip():
            continue
        safe_message = message.strip()
        for local_root, replacement in (
            (str(REPO_ROOT), "<REPO_ROOT>"),
            (str(Path.home()), "<USER_HOME>"),
        ):
            safe_message = safe_message.replace(local_root, replacement)
            safe_message = safe_message.replace(local_root.replace("\\", "/"), replacement)
        tc_id = payload.get("tc_id")
        prefix = f"{tc_id}: " if isinstance(tc_id, str) else ""
        return (prefix + safe_message)[:500]
    summary = _read_json(run_dir / "agent3_run_summary.json")
    entries = summary.get("entries")
    if isinstance(entries, list):
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            tc_id = entry.get("tc_id")
            outcome = entry.get("trial_outcome")
            if isinstance(tc_id, str) and isinstance(outcome, str):
                return f"{tc_id}: 후보 시험 {outcome}"
    return None


class LiveRunFileLock:
    """같은 저장소에서 실행된 여러 UI 브리지 사이의 단일 Live Run 잠금."""

    def __init__(self, lock_file: Path) -> None:
        self.lock_file = lock_file
        self._handle: Any | None = None

    def acquire(self) -> bool:
        if self._handle is not None:
            return True
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)
        handle = self.lock_file.open("a+b")
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            handle.close()
            return False
        self._handle = handle
        return True

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()
            self._handle = None


def _run_directory(runs_root: Path, run_id: str) -> Path:
    if not RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("올바르지 않은 Run ID입니다.")
    root = runs_root.resolve()
    run_dir = (root / run_id).resolve()
    if run_dir.parent != root or not run_dir.is_dir():
        raise FileNotFoundError("Run을 찾을 수 없습니다.")
    return run_dir


def list_runs(runs_root: Path) -> list[str]:
    if not runs_root.is_dir():
        return []
    return sorted(
        (
            path.name
            for path in runs_root.iterdir()
            if path.is_dir() and RUN_ID_PATTERN.fullmatch(path.name)
        ),
        reverse=True,
    )


def list_requests(requests_root: Path) -> list[dict[str, str]]:
    if not requests_root.is_dir():
        return []
    requests: list[dict[str, str]] = []
    for path in sorted(requests_root.glob("change_request*.json")):
        if not REQUEST_FILE_PATTERN.fullmatch(path.name):
            continue
        payload = _read_json(path)
        if not payload.get("request_id"):
            continue
        requests.append(
            {
                "file": path.name,
                "request_id": str(payload["request_id"]),
                "description": str(payload.get("description", "")),
            }
        )
    return requests


def _candidate_test_case(run_dir: Path, tc_id: str) -> dict[str, Any]:
    design = _read_json(run_dir / "agent2_test_design.json")
    for item in design.get("test_cases") or []:
        if isinstance(item, dict) and item.get("tc_id") == tc_id:
            return item
    raise ValueError("선택한 후보 TC를 Agent 2 산출물에서 찾을 수 없습니다.")


def _candidate_validation(run_dir: Path, tc_id: str) -> dict[str, Any]:
    validation = _read_json(run_dir / "validation_execution.json")
    for item in validation.get("candidate_results") or []:
        if isinstance(item, dict) and item.get("test_id") == tc_id:
            return item
    raise ValueError("선택한 후보 TC의 변경 검증 결과를 찾을 수 없습니다.")


def _candidate_approval_check(
    run_dir: Path,
    tc_id: str,
    *,
    target_html: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path, list[str]]:
    """공식 자산 등록 전에 후보·실행·현재 제품 해시를 다시 확인합니다."""

    if not TC_ID_PATTERN.fullmatch(tc_id):
        raise ValueError("올바르지 않은 후보 TC ID입니다.")
    test_case = _candidate_test_case(run_dir, tc_id)
    result = _candidate_validation(run_dir, tc_id)
    candidate_dir = run_dir / "agent3_candidates" / tc_id
    manifest = _read_json(candidate_dir / "agent3_manifest.json")
    summary = _read_json(run_dir / "agent3_run_summary.json")
    checkpoint4 = _read_json(run_dir / "checkpoint4.json")
    final_report = _read_json(run_dir / "final_report.json")
    entry = next(
        (
            item
            for item in summary.get("entries") or []
            if isinstance(item, dict) and item.get("tc_id") == tc_id
        ),
        {},
    )
    candidate_name = manifest.get("candidate_file")
    candidate_root = (candidate_dir / "candidates").resolve()
    candidate_file = (candidate_root / str(candidate_name or "")).resolve()
    reasons: list[str] = []
    if final_report.get("recommendation") != "PASS":
        reasons.append("최종 권고가 PASS가 아닙니다.")
    if checkpoint4.get("status") != "PASS":
        reasons.append("검증 단계 4가 PASS가 아닙니다.")
    if entry.get("status") != "PASS" or entry.get("checkpoint_status") != "PASS":
        reasons.append("Agent 3 후보와 검증 단계 3이 모두 PASS가 아닙니다.")
    if result.get("status") != "PASSED":
        reasons.append("변경 검증 결과가 PASSED가 아닙니다.")
    current_target_sha256 = _sha256_file(target_html) if target_html.is_file() else None
    approval_result = dict(result)
    if current_target_sha256 and result.get("target_sha256") != current_target_sha256:
        revalidation = _read_json(
            run_dir / "asset_revalidation" / tc_id / "latest.json"
        )
        if (
            revalidation.get("outcome") == "PASS"
            and revalidation.get("evidence_complete") is True
            and revalidation.get("candidate_sha256") == manifest.get("candidate_sha256")
            and revalidation.get("target_sha256") == current_target_sha256
        ):
            approval_result.update(
                {
                    "target_sha256": current_target_sha256,
                    "evidence_complete": True,
                    "evidence_files": revalidation.get("evidence_files") or [],
                    "evidence_sha256": revalidation.get("evidence_sha256") or {},
                    "approval_revalidation_file": (
                        f"asset_revalidation/{tc_id}/latest.json"
                    ),
                }
            )
        else:
            reasons.append(
                "시험 뒤 중앙제어 HTML이 변경되어 현재 제품 기준으로 재검증이 필요합니다."
            )
    if approval_result.get("evidence_complete") is not True:
        reasons.append("필수 실행 증거가 완전하지 않습니다.")
    evidence_files = approval_result.get("evidence_files") or []
    evidence_hashes = approval_result.get("evidence_sha256") or {}
    if not isinstance(evidence_files, list) or not evidence_files:
        reasons.append("실행 증거 파일 목록이 없습니다.")
    else:
        evidence_names = {Path(str(relative)).name for relative in evidence_files}
        if not {"trial-final.png", "trial-trace.zip"}.issubset(evidence_names):
            reasons.append("필수 Screenshot 또는 Trace 증거가 없습니다.")
        run_root = run_dir.resolve()
        for relative in evidence_files:
            evidence_file = (run_root / str(relative)).resolve()
            try:
                evidence_file.relative_to(run_root)
            except ValueError:
                reasons.append("실행 증거 경로가 Run 폴더 밖을 가리킵니다.")
                continue
            expected_evidence_hash = evidence_hashes.get(relative)
            if (
                not evidence_file.is_file()
                or not expected_evidence_hash
                or _sha256_file(evidence_file) != expected_evidence_hash
            ):
                reasons.append(f"실행 증거 무결성이 맞지 않습니다: {Path(str(relative)).name}")
    if not candidate_file.is_file() or candidate_file.parent != candidate_root:
        reasons.append("승인할 자동화 후보 파일을 찾을 수 없습니다.")
    else:
        candidate_sha256 = _sha256_file(candidate_file)
        expected_hashes = {
            str(manifest.get("candidate_sha256") or ""),
            str(result.get("test_sha256") or ""),
        }
        if candidate_sha256 not in expected_hashes or "" in expected_hashes:
            reasons.append("자동화 후보 파일 해시가 실행 기록과 일치하지 않습니다.")
    if not target_html.is_file():
        reasons.append("현재 V2 중앙제어 HTML을 찾을 수 없습니다.")
    return test_case, approval_result, candidate_file, reasons


def revalidate_candidate_asset(
    runs_root: Path,
    target_html: Path,
    run_id: str,
    tc_id: str,
    *,
    timeout_seconds: int = UI_CANDIDATE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """기존 Run을 덮어쓰지 않고 현재 HTML에서 후보 자동화만 다시 실행합니다."""

    run_dir = _run_directory(runs_root, run_id)
    if not TC_ID_PATTERN.fullmatch(tc_id):
        raise ValueError("올바르지 않은 후보 TC ID입니다.")
    _candidate_test_case(run_dir, tc_id)
    validation = _candidate_validation(run_dir, tc_id)
    if validation.get("status") != "PASSED":
        raise ValueError("기존 변경 검증을 통과한 후보만 승인 전 재검증할 수 있습니다.")
    candidate_dir = run_dir / "agent3_candidates" / tc_id
    manifest = _read_json(candidate_dir / "agent3_manifest.json")
    candidate_root = (candidate_dir / "candidates").resolve()
    candidate_file = (
        candidate_root / str(manifest.get("candidate_file") or "")
    ).resolve()
    if candidate_file.parent != candidate_root or not candidate_file.is_file():
        raise ValueError("재검증할 자동화 후보 파일을 찾을 수 없습니다.")
    candidate_sha256 = _sha256_file(candidate_file)
    if candidate_sha256 != manifest.get("candidate_sha256"):
        raise ValueError("자동화 후보 파일 해시가 Agent 3 기록과 일치하지 않습니다.")
    if not target_html.is_file():
        raise ValueError("현재 V2 중앙제어 HTML을 찾을 수 없습니다.")

    from qa_pipeline_v2 import TrialOutcome, run_candidate_trial

    attempt_id = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S-%f")
    revalidation_root = run_dir / "asset_revalidation" / tc_id
    evidence_dir = revalidation_root / attempt_id / "evidence"
    trial = run_candidate_trial(
        candidate_file,
        target_html,
        evidence_dir,
        timeout_seconds=timeout_seconds,
    )
    evidence_files = [
        (evidence_dir / name).relative_to(run_dir).as_posix()
        for name in trial.evidence_sha256
    ]
    evidence_sha256 = {
        relative: trial.evidence_sha256[Path(relative).name]
        for relative in evidence_files
    }
    record = {
        "contract_version": "1.0",
        "run_id": run_id,
        "tc_id": tc_id,
        "attempt_id": attempt_id,
        "outcome": trial.outcome.value,
        "exit_code": trial.exit_code,
        "duration_ms": trial.duration_ms,
        "candidate_sha256": candidate_sha256,
        "target_sha256": _sha256_file(target_html),
        "evidence_complete": trial.evidence_complete,
        "evidence_files": evidence_files,
        "evidence_sha256": evidence_sha256,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json_atomic(revalidation_root / "latest.json", record)
    if trial.outcome != TrialOutcome.PASS or not trial.evidence_complete:
        raise ValueError(
            f"현재 화면 재검증 결과가 {trial.outcome.value}이며 공식 등록 조건을 충족하지 않습니다."
        )
    return record


def _read_asset_decisions(run_dir: Path) -> list[dict[str, Any]]:
    payload = _read_json(run_dir / "asset_decisions.json")
    decisions = payload.get("decisions")
    return [item for item in decisions or [] if isinstance(item, dict)]


def _run_srs_revision_proposals(run_dir: Path) -> list[Any]:
    from qa_pipeline_v2 import SrsRevisionProposal

    report = _read_json(run_dir / "final_report.json")
    raw_items = report.get("SRS_개정_제안") or report.get("srs_revision_proposals") or []
    return [SrsRevisionProposal.model_validate(item) for item in raw_items]


def _candidate_srs_revision_proposals(
    run_dir: Path, test_case: dict[str, Any]
) -> list[Any]:
    """Limit a Run's SRS proposals to the candidate being approved."""

    requirement_ids = set(test_case.get("requirement_ids") or [])
    condition_ids = set(test_case.get("source_condition_ids") or [])
    return [
        proposal
        for proposal in _run_srs_revision_proposals(run_dir)
        if proposal.requirement_id in requirement_ids
        and bool(set(proposal.source_condition_ids).intersection(condition_ids))
    ]


def _restore_files_after_error(backups: dict[Path, bytes | None]) -> None:
    """Compensate a failed multi-file asset approval without broad deletion."""

    rollback_errors: list[str] = []
    for path, original in reversed(list(backups.items())):
        try:
            if original is None:
                path.unlink(missing_ok=True)
                continue
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_name(path.name + ".rollback.tmp")
            temporary.write_bytes(original)
            temporary.replace(path)
        except OSError as exc:
            rollback_errors.append(f"{path.name}: {exc}")
    if rollback_errors:
        raise RuntimeError(
            "공식 자산 승인 실패 뒤 원상 복구도 완료하지 못했습니다: "
            + "; ".join(rollback_errors)
        )


def _next_official_tc_id(registry: list[dict[str, Any]]) -> str:
    used = {
        int(match.group(1))
        for item in registry
        if isinstance(item, dict)
        and (match := re.fullmatch(r"TC-V2-(\d{3})", str(item.get("official_tc_id", ""))))
    }
    number = 1
    while number in used:
        number += 1
    return f"TC-V2-{number:03d}"


def _decide_candidate_asset_impl(
    runs_root: Path,
    approved_assets_root: Path,
    target_html: Path,
    run_id: str,
    tc_id: str,
    *,
    srs_path: Path = DEFAULT_SRS,
    decision: str,
    reviewer: str,
    note: str,
    approve_srs_revisions: bool = False,
) -> dict[str, Any]:
    """사람의 후보 승인·보류를 기록하고 승인 시 불변 공식 자산으로 복사합니다."""

    run_dir = _run_directory(runs_root, run_id)
    if not TC_ID_PATTERN.fullmatch(tc_id):
        raise ValueError("올바르지 않은 후보 TC ID입니다.")
    normalized_decision = str(decision).upper()
    if normalized_decision not in {"APPROVE", "HOLD"}:
        raise ValueError("승인 또는 보류만 선택할 수 있습니다.")
    reviewer_text = _safe_text(reviewer, field_name="검토자", required=True, limit=80)
    note_text = _safe_text(
        note,
        field_name="판단 메모",
        required=normalized_decision == "HOLD",
        limit=500,
    )
    test_case = _candidate_test_case(run_dir, tc_id)
    validation = _candidate_validation(run_dir, tc_id)
    candidate_file = run_dir / str(validation.get("test_file") or "")
    reasons: list[str] = []
    srs_revision_proposals = _candidate_srs_revision_proposals(
        run_dir, test_case
    )
    srs_revision_preview: dict[str, Any] | None = None
    if normalized_decision == "APPROVE":
        test_case, validation, candidate_file, reasons = _candidate_approval_check(
            run_dir,
            tc_id,
            target_html=target_html,
        )
        if reasons:
            raise ValueError("공식 등록 조건을 충족하지 않습니다: " + " ".join(reasons))
        if srs_revision_proposals:
            from qa_pipeline_v2 import apply_srs_revision_proposals

            srs_revision_preview = apply_srs_revision_proposals(
                srs_path,
                srs_revision_proposals,
                write=False,
            )
            if (
                srs_revision_preview["changed_requirement_ids"]
                and not approve_srs_revisions
            ):
                raise ValueError(
                    "SRS 개정 제안이 남아 있습니다. 제안 문구를 검토하고 SRS 개정 포함 승인을 선택해야 합니다."
                )

    decisions = _read_asset_decisions(run_dir)
    existing = next((item for item in decisions if item.get("tc_id") == tc_id), None)
    if existing and existing.get("decision") == "APPROVED":
        if normalized_decision == "HOLD":
            raise ValueError("이미 공식 등록된 자산은 화면에서 보류로 되돌릴 수 없습니다.")
        return existing

    created_at = datetime.now(timezone.utc).isoformat()
    record: dict[str, Any] = {
        "run_id": run_id,
        "tc_id": tc_id,
        "decision": "HELD" if normalized_decision == "HOLD" else "APPROVED",
        "reviewer": reviewer_text,
        "note": note_text,
        "created_at": created_at,
    }
    if normalized_decision == "APPROVE":
        registry_file = approved_assets_root / "registry.json"
        registry_payload = _read_json(registry_file)
        registry = [
            item
            for item in registry_payload.get("assets") or []
            if isinstance(item, dict)
        ]
        source_key = f"{run_id}:{tc_id}"
        registered = next(
            (item for item in registry if item.get("source_key") == source_key),
            None,
        )
        if registered:
            record.update(
                {
                    "official_tc_id": registered.get("official_tc_id"),
                    "test_case_sha256": registered.get("test_case_sha256"),
                    "automation_sha256": registered.get("automation_sha256"),
                }
            )
        else:
            official_tc_id = _next_official_tc_id(registry)
            slug = official_tc_id.lower().replace("-", "_")
            test_case_file = approved_assets_root / "test_cases" / f"{official_tc_id}.json"
            automation_file = approved_assets_root / "automation" / f"test_{slug}.py"
            if test_case_file.exists() or automation_file.exists():
                raise ValueError(
                    "Registry에 없는 동일 공식 TC 파일이 이미 있어 안전하게 등록할 수 없습니다."
                )
            srs_revision_result: dict[str, Any] | None = None
            srs_revision_asset_file: Path | None = (
                approved_assets_root / "srs_revisions" / f"{official_tc_id}.json"
                if srs_revision_proposals
                else None
            )
            if (
                srs_revision_asset_file is not None
                and srs_revision_asset_file.exists()
            ):
                raise ValueError(
                    "동일 공식 TC의 SRS 개정 기록 파일이 이미 있습니다."
                )
            if srs_revision_proposals:
                from qa_pipeline_v2 import apply_srs_revision_proposals

                srs_revision_result = apply_srs_revision_proposals(
                    srs_path,
                    srs_revision_proposals,
                    write=True,
                )
                srs_decision_file = run_dir / "srs_revision_decision.json"
                _write_json_atomic(
                    srs_decision_file,
                    {
                        "contract_version": "1.0",
                        "run_id": run_id,
                        "reviewer": reviewer_text,
                        "note": note_text,
                        "proposals": [
                            item.model_dump(mode="json")
                            for item in srs_revision_proposals
                        ],
                        **srs_revision_result,
                        "created_at": created_at,
                    },
                )
                assert srs_revision_asset_file is not None
                _write_json_atomic(
                    srs_revision_asset_file,
                    {
                        "contract_version": "1.0",
                        "official_tc_id": official_tc_id,
                        "source_run_id": run_id,
                        "source_tc_id": tc_id,
                        "reviewer": reviewer_text,
                        "approval_note": note_text,
                        "proposals": [
                            item.model_dump(mode="json")
                            for item in srs_revision_proposals
                        ],
                        **srs_revision_result,
                        "approved_at": created_at,
                    },
                )
            approved_test_case = {
                "contract_version": "1.0",
                "official_tc_id": official_tc_id,
                "source_run_id": run_id,
                "source_tc_id": tc_id,
                "reviewer": reviewer_text,
                "approval_note": note_text,
                "approved_at": created_at,
                "srs_revision_applied": bool(srs_revision_proposals),
                "srs_revision_file": (
                    srs_revision_asset_file.relative_to(
                        approved_assets_root
                    ).as_posix()
                    if srs_revision_asset_file is not None
                    else None
                ),
                "test_case": test_case,
            }
            _write_json_atomic(test_case_file, approved_test_case)
            automation_file.parent.mkdir(parents=True, exist_ok=True)
            temporary_automation = automation_file.with_name(
                automation_file.name + ".tmp"
            )
            shutil.copy2(candidate_file, temporary_automation)
            temporary_automation.replace(automation_file)
            test_case_sha256 = _sha256_file(test_case_file)
            automation_sha256 = _sha256_file(automation_file)
            revalidation_file_value = validation.get("approval_revalidation_file")
            revalidation_file = (
                run_dir / str(revalidation_file_value)
                if revalidation_file_value
                else None
            )
            revalidation_sha256 = (
                _sha256_file(revalidation_file)
                if revalidation_file is not None and revalidation_file.is_file()
                else None
            )
            asset = {
                "source_key": source_key,
                "official_tc_id": official_tc_id,
                "source_run_id": run_id,
                "source_tc_id": tc_id,
                "title": str(test_case.get("title") or ""),
                "requirement_ids": list(test_case.get("requirement_ids") or []),
                "test_case_file": test_case_file.relative_to(approved_assets_root).as_posix(),
                "test_case_sha256": test_case_sha256,
                "automation_file": automation_file.relative_to(approved_assets_root).as_posix(),
                "automation_sha256": automation_sha256,
                "target_sha256": str(validation.get("target_sha256") or ""),
                "approval_revalidation_file": revalidation_file_value,
                "approval_revalidation_sha256": revalidation_sha256,
                "reviewer": reviewer_text,
                "approval_note": note_text,
                "approved_at": created_at,
                "srs_revision_applied": bool(srs_revision_proposals),
                "srs_revision_file": (
                    srs_revision_asset_file.relative_to(
                        approved_assets_root
                    ).as_posix()
                    if srs_revision_asset_file is not None
                    else None
                ),
                "srs_revision_sha256": (
                    _sha256_file(srs_revision_asset_file)
                    if srs_revision_asset_file is not None
                    else None
                ),
                "srs_revision_before_sha256": (
                    srs_revision_result["before_sha256"]
                    if srs_revision_result is not None
                    else None
                ),
                "srs_revision_after_sha256": (
                    srs_revision_result["after_sha256"]
                    if srs_revision_result is not None
                    else None
                ),
            }
            registry.append(asset)
            _write_json_atomic(
                registry_file,
                {"contract_version": "1.0", "assets": registry},
            )
            record.update(
                {
                    "official_tc_id": official_tc_id,
                    "test_case_sha256": test_case_sha256,
                    "automation_sha256": automation_sha256,
                    "approval_revalidation_sha256": revalidation_sha256,
                    "srs_revision_applied": bool(srs_revision_proposals),
                }
            )

    if existing:
        decisions[decisions.index(existing)] = record
    else:
        decisions.append(record)
    _write_json_atomic(
        run_dir / "asset_decisions.json",
        {"contract_version": "1.0", "run_id": run_id, "decisions": decisions},
    )
    return record


def decide_candidate_asset(
    runs_root: Path,
    approved_assets_root: Path,
    target_html: Path,
    run_id: str,
    tc_id: str,
    *,
    srs_path: Path = DEFAULT_SRS,
    decision: str,
    reviewer: str,
    note: str,
    approve_srs_revisions: bool = False,
) -> dict[str, Any]:
    """Apply one approval as a compensating multi-file transaction."""

    run_dir = _run_directory(runs_root, run_id)
    approved_assets_root = approved_assets_root.resolve()
    registry_file = approved_assets_root / "registry.json"
    registry_payload = _read_json(registry_file)
    registry = [
        item
        for item in registry_payload.get("assets") or []
        if isinstance(item, dict)
    ]
    source_key = f"{run_id}:{tc_id}"
    registered = next(
        (item for item in registry if item.get("source_key") == source_key),
        None,
    )
    official_tc_id = (
        str(registered.get("official_tc_id"))
        if registered is not None
        else _next_official_tc_id(registry)
    )
    slug = official_tc_id.lower().replace("-", "_")
    watched_paths = [
        srs_path.resolve(),
        registry_file,
        run_dir / "asset_decisions.json",
        run_dir / "srs_revision_decision.json",
        approved_assets_root / "test_cases" / f"{official_tc_id}.json",
        approved_assets_root / "automation" / f"test_{slug}.py",
        approved_assets_root / "srs_revisions" / f"{official_tc_id}.json",
    ]
    watched_paths.extend(
        [path.with_name(path.name + ".tmp") for path in watched_paths]
    )
    backups = {
        path: path.read_bytes() if path.is_file() else None
        for path in dict.fromkeys(watched_paths)
    }
    try:
        return _decide_candidate_asset_impl(
            runs_root,
            approved_assets_root,
            target_html,
            run_id,
            tc_id,
            srs_path=srs_path,
            decision=decision,
            reviewer=reviewer,
            note=note,
            approve_srs_revisions=approve_srs_revisions,
        )
    except Exception as original_error:
        try:
            _restore_files_after_error(backups)
        except Exception as rollback_error:
            raise RuntimeError(
                f"공식 자산 승인 실패: {original_error}; 원상 복구 실패: {rollback_error}"
            ) from original_error
        raise


def _checkpoint_stage(
    name: str,
    checkpoint: dict[str, Any],
    *,
    summary: str,
    details: list[str],
) -> dict[str, Any]:
    status = str(checkpoint.get("status") or "대기")
    return {
        "name": name,
        "status": status,
        "summary": summary,
        "details": [item for item in details if item],
    }


def summarize_run(
    runs_root: Path,
    run_id: str,
    *,
    target_html: Path = DEFAULT_TARGET_HTML,
) -> dict[str, Any]:
    """허용된 산출물만 읽어 브라우저 표시용 요약을 만듭니다."""

    run_dir = _run_directory(runs_root, run_id)
    request = _read_json(run_dir / "request.json")
    analysis = _read_json(run_dir / "agent1_change_analysis.json")
    checkpoint1 = _read_json(run_dir / "checkpoint1.json")
    design = _read_json(run_dir / "agent2_test_design.json")
    checkpoint2 = _read_json(run_dir / "checkpoint2.json")
    selection = _read_json(run_dir / "agent3_selection.json")
    agent3_summary = _read_json(run_dir / "agent3_run_summary.json")
    validation = _read_json(run_dir / "validation_execution.json")
    analysis4 = _read_json(run_dir / "agent4_analysis.json")
    checkpoint4 = _read_json(run_dir / "checkpoint4.json")
    report = _read_json(run_dir / "final_report.json")
    reporting = _read_json(run_dir / "external_reporting.json")
    manifest = _read_json(run_dir / "orchestrator_manifest.json")
    decisions = {
        item.get("tc_id"): item
        for item in _read_asset_decisions(run_dir)
        if item.get("tc_id")
    }

    test_cases = design.get("test_cases") or []
    selected_ids = selection.get("selected_tc_ids") or []
    executed_ids = agent3_summary.get("executed_tc_ids") or []
    exclusions = agent3_summary.get("자동화_제외_TC") or []
    validation_results = [
        *(validation.get("candidate_results") or []),
        *(validation.get("regression_results") or []),
    ]
    environment = validation.get("environment_precheck")
    if isinstance(environment, dict):
        validation_results.insert(0, environment)

    stage1 = _checkpoint_stage(
        "요구사항 정제",
        checkpoint1,
        summary=str(analysis.get("change_summary") or "Agent 1 산출물이 아직 없습니다."),
        details=[
            f"요청: {request.get('request_id', '-')} / {request.get('target_requirement_id', '-')}",
            f"확정 조건: {len(analysis.get('confirmed_conditions') or [])}건",
            f"영향 요구사항: {len(analysis.get('requirement_effects') or [])}건",
            *[f"최종 확인: {item}" for item in checkpoint1.get("final_review_notes") or []],
        ],
    )
    stage2 = _checkpoint_stage(
        "TC 설계",
        checkpoint2,
        summary=(
            f"설계 TC {len(test_cases)}건 · 자동화 후보 "
            f"{sum(bool(item.get('automation_candidate')) for item in test_cases)}건"
            if design
            else "Agent 2 산출물이 아직 없습니다."
        ),
        details=[
            *[
                f"{item.get('tc_id', '-')}: {item.get('title', '')}"
                for item in test_cases
            ],
            *[f"제외 범위: {item}" for item in design.get("제외_범위") or []],
        ],
    )
    stage3_status = str(
        validation.get("status")
        or agent3_summary.get("status")
        or selection.get("status")
        or "대기"
    )
    stage3 = {
        "name": "자동화 실행",
        "status": stage3_status,
        "summary": (
            f"선택 {len(selected_ids)}건 · 후보 시험 완료 {len(executed_ids)}건 · "
            f"자동화 제외 {len(exclusions)}건"
            if selection
            else "Agent 3 산출물이 아직 없습니다."
        ),
        "details": [
            *[f"선택 TC: {item}" for item in selected_ids],
            *[
                f"{item.get('test_id', '-')}: {item.get('status', '-')}"
                for item in validation_results
            ],
            *[
                f"자동화 제외: {item.get('tc_id', '-')} / {item.get('reason', '')}"
                for item in exclusions
                if isinstance(item, dict)
            ],
        ],
    }
    recommendation = str(
        report.get("recommendation") or analysis4.get("recommendation") or "대기"
    )
    report_mode = str(reporting.get("mode") or "미생성")
    stage4 = _checkpoint_stage(
        "결과 분석·보고",
        checkpoint4,
        summary=(
            f"최종 판정 {recommendation} · 외부 보고 {report_mode}"
            if report or analysis4
            else "Agent 4 산출물이 아직 없습니다."
        ),
        details=[
            f"전체 결과: {report.get('total_results', analysis4.get('total_results', 0))}건",
            f"제품 결과: {report.get('product_result_count', analysis4.get('product_result_count', 0))}건",
            f"환경 점검: {report.get('environment_result_count', analysis4.get('environment_result_count', 0))}건",
            *[f"사람 검토: {item}" for item in report.get("검토_항목") or []],
            *[f"최종 확인: {item}" for item in report.get("최종_확인_사항") or []],
            (
                f"기준 SRS 개정 제안: {len(report.get('SRS_개정_제안') or [])}건"
                if report.get("SRS_개정_제안")
                else ""
            ),
            (
                f"Slack: {reporting.get('slack', {}).get('status', '-')} / "
                f"Notion: {reporting.get('notion', {}).get('status', '-')}"
                if reporting
                else ""
            ),
        ],
    )

    candidate_assets: list[dict[str, Any]] = []
    for test_case in test_cases:
        if not isinstance(test_case, dict) or not test_case.get("automation_candidate"):
            continue
        tc_id = str(test_case.get("tc_id") or "")
        reasons: list[str]
        try:
            _, _, _, reasons = _candidate_approval_check(
                run_dir,
                tc_id,
                target_html=target_html,
            )
        except (ValueError, OSError, json.JSONDecodeError) as exc:
            reasons = [str(exc)]
        decision = decisions.get(tc_id)
        candidate_assets.append(
            {
                "tc_id": tc_id,
                "title": str(test_case.get("title") or ""),
                "approval_eligible": not reasons,
                "eligibility_reasons": reasons,
                "revalidation_required": any("재검증이 필요" in item for item in reasons),
                "srs_revision_proposals": report.get("SRS_개정_제안") or [],
                "decision": decision,
            }
        )

    overall = recommendation if report else str(manifest.get("status") or stage3_status)
    return {
        "run_id": run_id,
        "request_id": request.get("request_id"),
        "description": request.get("description"),
        "target_requirement_id": request.get("target_requirement_id"),
        "overall_status": overall,
        "stages": {
            "agent1": stage1,
            "agent2": stage2,
            "agent3": stage3,
            "agent4": stage4,
        },
        "human_review_document": "사람_최종_검토.md" if (run_dir / "사람_최종_검토.md").is_file() else None,
        "candidate_assets": candidate_assets,
    }


@dataclass
class LiveRunState:
    allow_live_run: bool
    allow_asset_approval: bool
    running: bool = False
    phase: str = "IDLE"
    run_id: str | None = None
    request_file: str | None = None
    message: str = "저장된 Run을 조회할 수 있습니다."
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, Any]:
        with self.lock:
            return {
                "allow_live_run": self.allow_live_run,
                "allow_asset_approval": self.allow_asset_approval,
                "running": self.running,
                "phase": self.phase,
                "run_id": self.run_id,
                "request_file": self.request_file,
                "message": self.message,
            }

    def update(self, **changes: Any) -> None:
        with self.lock:
            for key, value in changes.items():
                setattr(self, key, value)


class PipelineUiBridge:
    def __init__(
        self,
        *,
        runs_root: Path,
        requests_root: Path,
        target_html: Path,
        allow_live_run: bool,
        allow_asset_approval: bool = False,
        approved_assets_root: Path = DEFAULT_APPROVED_ASSETS_ROOT,
        srs_path: Path = DEFAULT_SRS,
    ) -> None:
        self.runs_root = runs_root.resolve()
        self.requests_root = requests_root.resolve()
        self.target_html = target_html.resolve()
        self.approved_assets_root = approved_assets_root.resolve()
        self.srs_path = srs_path.resolve()
        self.state = LiveRunState(
            allow_live_run=allow_live_run,
            allow_asset_approval=allow_asset_approval,
        )
        self.live_run_lock = LiveRunFileLock(self.runs_root / LIVE_RUN_LOCK_FILE)
        self.asset_approval_lock = LiveRunFileLock(
            self.runs_root / ASSET_APPROVAL_LOCK_FILE
        )

    def overview(self) -> dict[str, Any]:
        runs = list_runs(self.runs_root)
        return {
            **self.state.snapshot(),
            "latest_run_id": runs[0] if runs else None,
            "run_count": len(runs),
        }

    def request_path(self, filename: str) -> Path:
        if not REQUEST_FILE_PATTERN.fullmatch(filename):
            raise ValueError("허용된 변경 요청 파일명이 아닙니다.")
        path = (self.requests_root / filename).resolve()
        if path.parent != self.requests_root or not path.is_file():
            raise FileNotFoundError("변경 요청 파일을 찾을 수 없습니다.")
        return path

    def decide_asset(
        self,
        run_id: str,
        tc_id: str,
        *,
        decision: str,
        reviewer: str,
        note: str,
        approve_srs_revisions: bool = False,
    ) -> dict[str, Any]:
        if not self.state.allow_asset_approval:
            raise PermissionError(
                "공식 자산 승인은 비활성화 상태입니다. 서버를 --allow-asset-approval로 다시 시작해야 합니다."
            )
        if not self.asset_approval_lock.acquire():
            raise RuntimeError("다른 로컬 브리지에서 자산 승인 처리가 진행 중입니다.")
        try:
            return decide_candidate_asset(
                self.runs_root,
                self.approved_assets_root,
                self.target_html,
                run_id,
                tc_id,
                srs_path=self.srs_path,
                decision=decision,
                reviewer=reviewer,
                note=note,
                approve_srs_revisions=approve_srs_revisions,
            )
        finally:
            self.asset_approval_lock.release()

    def revalidate_asset(self, run_id: str, tc_id: str) -> dict[str, Any]:
        if not self.state.allow_asset_approval:
            raise PermissionError(
                "공식 자산 승인은 비활성화 상태입니다. 서버를 --allow-asset-approval로 다시 시작해야 합니다."
            )
        if not self.asset_approval_lock.acquire():
            raise RuntimeError("다른 로컬 브리지에서 자산 승인 처리가 진행 중입니다.")
        try:
            return revalidate_candidate_asset(
                self.runs_root,
                self.target_html,
                run_id,
                tc_id,
            )
        finally:
            self.asset_approval_lock.release()

    def start_live_run(self, request_file: str) -> None:
        if not self.state.allow_live_run:
            raise PermissionError(
                "새 Live 실행은 비활성화 상태입니다. 서버를 --allow-live-run으로 다시 시작해야 합니다."
            )
        request_path = self.request_path(request_file)
        with self.state.lock:
            if self.state.running:
                raise RuntimeError("이미 Live Run이 실행 중입니다.")
            if not self.live_run_lock.acquire():
                raise RuntimeError("다른 로컬 브리지에서 Live Run이 실행 중입니다.")
            self.state.running = True
            self.state.phase = "AGENT_1_TO_3"
            self.state.run_id = None
            self.state.request_file = request_file
            self.state.message = "Agent 1→3 및 후보 시험을 실행 중입니다."
        try:
            thread = threading.Thread(
                target=self._run_pipeline,
                args=(request_path,),
                daemon=True,
                name="qa-pipeline-live-run",
            )
            thread.start()
        except Exception:
            self.state.update(
                running=False,
                phase="FAILED",
                message="Live Run 시작에 실패했습니다.",
            )
            self.live_run_lock.release()
            raise

    def _command(self, *arguments: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "src" / "qa_pipeline_v2.py"), *arguments],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )

    def _run_pipeline(self, request_path: Path) -> None:
        before = set(list_runs(self.runs_root))
        try:
            pipeline_result = self._command(
                "pipeline",
                "--request",
                str(request_path),
                "--target-html",
                str(self.target_html),
                "--runs-root",
                str(self.runs_root),
                "--timeout",
                str(UI_CANDIDATE_TIMEOUT_SECONDS),
            )
            created = [run_id for run_id in list_runs(self.runs_root) if run_id not in before]
            run_id = created[0] if created else None
            self.state.update(run_id=run_id)
            if pipeline_result.returncode != 0 or run_id is None:
                detail = (
                    _safe_run_error(self.runs_root / run_id)
                    if run_id is not None
                    else None
                )
                raise RuntimeError(
                    f"Agent 1→3 실행 실패: {detail}"
                    if detail
                    else f"Agent 1→3 실행 종료 코드: {pipeline_result.returncode}"
                )

            self.state.update(
                phase="VALIDATION_EXECUTION",
                message="후보 시험 증거를 재사용하고 관련 검증을 실행 중입니다.",
            )
            validation_result = self._command(
                "execute",
                "--run-id",
                run_id,
                "--target-html",
                str(self.target_html),
                "--runs-root",
                str(self.runs_root),
            )
            if validation_result.returncode != 0:
                raise RuntimeError(f"검증 실행 종료 코드: {validation_result.returncode}")

            self.state.update(
                phase="AGENT_4",
                message="규칙 기반 결과 분석과 외부 보고 미리보기를 생성 중입니다.",
            )
            agent4_result = self._command(
                "agent4",
                "--run-id",
                run_id,
                "--runs-root",
                str(self.runs_root),
            )
            if agent4_result.returncode != 0:
                raise RuntimeError(f"Agent 4 실행 종료 코드: {agent4_result.returncode}")
            self.state.update(
                running=False,
                phase="COMPLETED",
                message="Agent 1→4 실행과 보고 미리보기 생성이 완료됐습니다.",
            )
        except Exception as exc:  # 브리지 상태로 안전하게 전달
            self.state.update(running=False, phase="FAILED", message=str(exc))
        finally:
            self.live_run_lock.release()


def make_handler(bridge: PipelineUiBridge) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "QaPipelineUi/1.0"

        def log_message(self, format: str, *args: Any) -> None:
            return

        def _send_json(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_error_json(self, status: HTTPStatus, message: str) -> None:
            self._send_json({"error": message}, status)

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/":
                    body = bridge.target_html.read_bytes()
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/qa/state":
                    self._send_json(bridge.overview())
                    return
                if path == "/api/qa/runs":
                    self._send_json({"runs": list_runs(bridge.runs_root)})
                    return
                if path == "/api/qa/requests":
                    self._send_json({"requests": list_requests(bridge.requests_root)})
                    return
                prefix = "/api/qa/runs/"
                if path.startswith(prefix):
                    self._send_json(
                        summarize_run(
                            bridge.runs_root,
                            path[len(prefix) :],
                            target_html=bridge.target_html,
                        )
                    )
                    return
                self._send_error_json(HTTPStatus.NOT_FOUND, "요청한 경로를 찾을 수 없습니다.")
            except FileNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except (ValueError, json.JSONDecodeError) as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            path = unquote(urlparse(self.path).path)
            decision_match = re.fullmatch(
                r"/api/qa/runs/(RUN-\d{8}-\d{6}-[A-F0-9]{6})/asset-decision",
                path,
            )
            revalidation_match = re.fullmatch(
                r"/api/qa/runs/(RUN-\d{8}-\d{6}-[A-F0-9]{6})/asset-revalidation",
                path,
            )
            if (
                path != "/api/qa/runs"
                and decision_match is None
                and revalidation_match is None
            ):
                self._send_error_json(HTTPStatus.NOT_FOUND, "요청한 경로를 찾을 수 없습니다.")
                return
            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > 16_384:
                    raise ValueError("요청 본문 크기가 허용 범위를 벗어났습니다.")
                payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON 객체가 필요합니다.")
                if path == "/api/qa/runs":
                    request_file = payload.get("request_file")
                    if not isinstance(request_file, str):
                        raise ValueError("request_file이 필요합니다.")
                    bridge.start_live_run(request_file)
                    self._send_json(bridge.overview(), HTTPStatus.ACCEPTED)
                    return
                if revalidation_match is not None:
                    tc_id = str(payload.get("tc_id") or "")
                    record = bridge.revalidate_asset(
                        revalidation_match.group(1),
                        tc_id,
                    )
                    self._send_json(
                        {
                            "revalidation": record,
                            "run": summarize_run(
                                bridge.runs_root,
                                revalidation_match.group(1),
                                target_html=bridge.target_html,
                            ),
                        }
                    )
                    return
                assert decision_match is not None
                record = bridge.decide_asset(
                    decision_match.group(1),
                    str(payload.get("tc_id") or ""),
                    decision=str(payload.get("decision") or ""),
                    reviewer=payload.get("reviewer"),
                    note=payload.get("note", ""),
                    approve_srs_revisions=(
                        payload.get("approve_srs_revisions") is True
                    ),
                )
                self._send_json(
                    {
                        "decision": record,
                        "run": summarize_run(
                            bridge.runs_root,
                            decision_match.group(1),
                            target_html=bridge.target_html,
                        ),
                    }
                )
            except PermissionError as exc:
                self._send_error_json(HTTPStatus.FORBIDDEN, str(exc))
            except RuntimeError as exc:
                self._send_error_json(HTTPStatus.CONFLICT, str(exc))
            except FileNotFoundError as exc:
                self._send_error_json(HTTPStatus.NOT_FOUND, str(exc))
            except (ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
                self._send_error_json(HTTPStatus.BAD_REQUEST, str(exc))

    return Handler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QA Pipeline V2 로컬 중앙제어 UI 브리지")
    parser.add_argument("--host", default="127.0.0.1", choices=["127.0.0.1", "localhost"])
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--requests-root", type=Path, default=DEFAULT_REQUESTS_ROOT)
    parser.add_argument("--target-html", type=Path, default=DEFAULT_TARGET_HTML)
    parser.add_argument(
        "--allow-live-run",
        action="store_true",
        help="화면에서 새 OpenAI API Run 시작을 허용합니다. 기본값은 저장 Run 조회 전용입니다.",
    )
    parser.add_argument(
        "--allow-asset-approval",
        action="store_true",
        help="화면에서 검증된 후보 TC·자동화의 사람 승인·보류 기록을 허용합니다.",
    )
    parser.add_argument(
        "--approved-assets-root",
        type=Path,
        default=DEFAULT_APPROVED_ASSETS_ROOT,
    )
    parser.add_argument("--srs", type=Path, default=DEFAULT_SRS)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.target_html.is_file():
        raise SystemExit("V2 중앙제어 HTML을 찾을 수 없습니다.")
    bridge = PipelineUiBridge(
        runs_root=args.runs_root,
        requests_root=args.requests_root,
        target_html=args.target_html,
        allow_live_run=args.allow_live_run,
        allow_asset_approval=args.allow_asset_approval,
        approved_assets_root=args.approved_assets_root,
        srs_path=args.srs,
    )
    server = ThreadingHTTPServer((args.host, args.port), make_handler(bridge))
    print(f"QA Pipeline V2 UI: http://{args.host}:{args.port}/")
    print(
        "새 Live 실행: 허용"
        if args.allow_live_run
        else "새 Live 실행: 비활성화 (저장된 Run 조회 전용)"
    )
    print(
        "공식 자산 승인: 허용"
        if args.allow_asset_approval
        else "공식 자산 승인: 비활성화"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
