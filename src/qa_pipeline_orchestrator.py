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
from qa_pipeline_reporting import *

def _write_orchestrator_manifest(
    run_dir: Path,
    run_id: str,
    *,
    status: str,
    selected_tc_id: str | None,
    target_html: Path,
    stage_exit_codes: dict[str, int],
    stopped_at: str | None,
    error: Exception | None = None,
) -> None:
    """Write the one-command A1→A3 summary without replacing stage evidence."""
    stage_manifests = {
        "agent1_manifest_sha256": run_dir / "run_manifest.json",
        "agent2_manifest_sha256": run_dir / "agent2_manifest.json",
        "agent3_manifest_sha256": run_dir / "agent3_manifest.json",
    }
    payload: dict[str, Any] = {
        "contract_version": "1.0",
        "run_id": run_id,
        "stage": "ORCHESTRATOR_AGENT_1_TO_3",
        "status": status,
        "selected_tc_id": selected_tc_id,
        "target_file": target_html.name,
        "stage_exit_codes": stage_exit_codes,
        "completed_stages": [
            stage
            for stage in ("agent1", "agent2", "agent3")
            if stage_exit_codes.get(stage) == 0
        ],
        "stopped_at": stopped_at,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    for key, path in stage_manifests.items():
        payload[key] = _sha256_file(path) if path.is_file() else None
    agent3_manifest_file = run_dir / "agent3_manifest.json"
    if agent3_manifest_file.is_file():
        agent3_manifest = _read_json_payload(agent3_manifest_file)
        payload["candidate_status"] = agent3_manifest.get("candidate_status")
    trial_file = run_dir / "agent3_trial.json"
    if trial_file.is_file():
        payload["trial_outcome"] = _read_json_payload(trial_file).get("outcome")
    selection_file = run_dir / "agent3_selection.json"
    if selection_file.is_file():
        payload["agent3_selection_sha256"] = _sha256_file(selection_file)
        selection = _read_json_payload(selection_file)
        payload["selected_tc_ids"] = selection.get("selected_tc_ids", [])
    summary_file = run_dir / "agent3_run_summary.json"
    if summary_file.is_file():
        summary = _read_json_payload(summary_file)
        payload["agent3_run_summary_sha256"] = _sha256_file(summary_file)
        payload["executed_tc_ids"] = summary.get("executed_tc_ids", [])
        payload["자동화_제외_TC"] = summary.get("자동화_제외_TC", [])
    if error is not None:
        payload["error_type"] = type(error).__name__
    _write_json(run_dir / "orchestrator_manifest.json", payload)


def _orchestrator_status(exit_code: int) -> str:
    if exit_code == 0:
        return "PASS"
    if exit_code == 1:
        return "ERROR"
    return "STOPPED"


def _select_agent3_tc(
    design: Agent2TestDesign,
) -> tuple[str | None, list[dict[str, Any]]]:
    """Backward-compatible helper returning the first ordered Agent 3 TC."""
    selected, summaries = _select_agent3_tcs(design)
    return (selected[0] if selected else None), summaries


def _select_agent3_tcs(
    design: Agent2TestDesign,
) -> tuple[list[str], list[dict[str, Any]]]:
    """Order every current-Run TC that may proceed to Agent 3."""
    candidates: list[tuple[ProductTestCaseCandidate, Agent3EligibilityResult]] = []
    summaries: list[dict[str, Any]] = []
    for test_case in design.test_cases:
        if test_case.purpose != TcPurpose.CHANGE_VALIDATION:
            summaries.append(
                {
                    "tc_id": test_case.tc_id,
                    "purpose": test_case.purpose.value,
                    "test_type": test_case.test_type.value,
                    "control_path": test_case.control_path.value,
                    "target_role": test_case.target_role,
                    "automation_candidate": test_case.automation_candidate,
                    "status": Agent3EligibilityStatus.NOT_AUTOMATABLE.value,
                    "candidate_status": AutomationCandidateStatus.NOT_AUTOMATABLE.value,
                    "missing_capabilities": [
                        "관련 기존 TC는 Agent 3에서 다시 구현하지 않고 execute 단계에서 회귀 실행합니다."
                    ],
                    "generic_discovery_required": False,
                }
            )
            continue
        eligibility = evaluate_agent3_eligibility(test_case)
        summaries.append(
            {
                "tc_id": test_case.tc_id,
                "purpose": test_case.purpose.value,
                "test_type": test_case.test_type.value,
                "control_path": test_case.control_path.value,
                "target_role": test_case.target_role,
                "automation_candidate": test_case.automation_candidate,
                "status": eligibility.status.value,
                "candidate_status": (
                    eligibility.candidate_status.value
                    if eligibility.candidate_status is not None
                    else None
                ),
                "missing_capabilities": (
                    eligibility.missing_capabilities
                    if test_case.automation_candidate
                    else [test_case.automation_reason]
                ),
                "generic_discovery_required": (
                    eligibility.generic_discovery_required
                ),
            }
        )
        if eligibility.model_call_allowed:
            candidates.append((test_case, eligibility))
    if not candidates:
        return [], summaries

    def priority(
        item: tuple[ProductTestCaseCandidate, Agent3EligibilityResult],
    ) -> tuple[Any, ...]:
        test_case, eligibility = item
        layers = {result.observation_layer for result in test_case.expected_results}
        return (
            eligibility.status != Agent3EligibilityStatus.ELIGIBLE,
            test_case.purpose != TcPurpose.CHANGE_VALIDATION,
            ObservationLayer.NOTIFICATION not in layers,
            test_case.restore_required,
            test_case.test_type != TcType.BOUNDARY,
            test_case.tc_id,
        )

    selected = [item[0].tc_id for item in sorted(candidates, key=priority)]
    return selected, summaries


def _select_agent3_tc_from_run(
    run_dir: Path,
    run_id: str,
) -> tuple[str | None, list[dict[str, Any]]]:
    _, _, _, design, _, _ = _load_verified_agent2_run(run_dir, run_id)
    return _select_agent3_tc(design)


def _select_agent3_tcs_from_run(
    run_dir: Path,
    run_id: str,
) -> tuple[list[str], list[dict[str, Any]]]:
    _, _, _, design, _, _ = _load_verified_agent2_run(run_dir, run_id)
    return _select_agent3_tcs(design)


def _agent3_run_entry(
    run_dir: Path,
    tc_id: str,
    artifact_dir: Path,
    exit_code: int,
    error: Exception | None = None,
) -> dict[str, Any]:
    relative_dir = artifact_dir.relative_to(run_dir).as_posix()
    entry: dict[str, Any] = {
        "tc_id": tc_id,
        "artifact_dir": relative_dir,
        "exit_code": exit_code,
        "status": "ERROR" if error is not None else _orchestrator_status(exit_code),
        "candidate_status": None,
        "trial_outcome": None,
        "reason": None,
        "manifest_sha256": None,
        "trial_sha256": None,
    }
    manifest_file = artifact_dir / "agent3_manifest.json"
    if manifest_file.is_file():
        manifest = _read_json_payload(manifest_file)
        entry["checkpoint_status"] = manifest.get("status")
        entry["candidate_status"] = manifest.get("candidate_status")
        entry["manifest_sha256"] = _sha256_file(manifest_file)
        trial_file = artifact_dir / "agent3_trial.json"
        if trial_file.is_file():
            entry["trial_outcome"] = _read_json_payload(trial_file).get("outcome")
            entry["trial_sha256"] = _sha256_file(trial_file)
        plan_file = artifact_dir / "agent3_automation_plan.json"
        if plan_file.is_file():
            plan = _read_json_payload(plan_file)
            reasons = plan.get("extension_reasons")
            if isinstance(reasons, list) and reasons:
                entry["reason"] = " / ".join(str(item) for item in reasons)
    eligibility_file = artifact_dir / "agent3_eligibility.json"
    if entry["reason"] is None and eligibility_file.is_file():
        eligibility = _read_json_payload(eligibility_file)
        missing = eligibility.get("missing_capabilities")
        if isinstance(missing, list) and missing:
            entry["reason"] = " / ".join(str(item) for item in missing)
    if error is not None:
        entry["reason"] = str(error)
        entry["candidate_status"] = AutomationCandidateStatus.BLOCKED.value
    if entry["reason"] is None and exit_code != 0:
        entry["reason"] = "Agent 3 후보 시험이 신뢰 가능한 완료 상태에 도달하지 못했습니다."
    return entry


def _automation_exclusion_from_run_entry(entry: dict[str, Any]) -> dict[str, Any]:
    raw_status = entry.get("candidate_status") or AutomationCandidateStatus.BLOCKED.value
    try:
        status = AutomationCandidateStatus(raw_status)
    except ValueError:
        status = AutomationCandidateStatus.BLOCKED
    return AutomationExclusion(
        tc_id=entry["tc_id"],
        candidate_status=status,
        reason=entry.get("reason") or "자동화 실행에서 제외됐습니다.",
        artifact_dir=entry.get("artifact_dir"),
    ).model_dump(mode="json")


def run_pipeline(args: argparse.Namespace) -> int:
    """Run Agent 1→2 and continue every eligible Agent 3 candidate."""
    run_id = _new_run_id()
    runs_root = Path(args.runs_root).resolve()
    run_dir = runs_root / run_id
    target_html = Path(args.target_html).resolve()
    if not target_html.is_file():
        raise ValueError(f"Agent 3 target HTML does not exist: {target_html.name}")
    explicit_tc_id = None if args.tc_id in {None, "AUTO"} else args.tc_id
    selected_tc_id = explicit_tc_id
    stage_exit_codes: dict[str, int] = {}
    current_stage = "agent1"
    try:
        agent1_exit = run_agent1(
            argparse.Namespace(
                request=args.request,
                srs=args.srs,
                runs_root=str(runs_root),
                model=args.model,
                run_id=run_id,
            )
        )
        stage_exit_codes["agent1"] = agent1_exit
        if agent1_exit != 0:
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status=_orchestrator_status(agent1_exit),
                selected_tc_id=selected_tc_id,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at="agent1",
            )
            return agent1_exit

        current_stage = "agent2"
        agent2_exit = run_agent2(
            argparse.Namespace(
                run_id=run_id,
                runs_root=str(runs_root),
                model=args.model,
                approved_assets_root=getattr(
                    args, "approved_assets_root", DEFAULT_APPROVED_ASSETS_ROOT
                ),
            )
        )
        stage_exit_codes["agent2"] = agent2_exit
        if agent2_exit != 0:
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status=_orchestrator_status(agent2_exit),
                selected_tc_id=selected_tc_id,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at="agent2",
            )
            return agent2_exit

        current_stage = "agent3"
        auto_selected_ids, selection_candidates = _select_agent3_tcs_from_run(
            run_dir, run_id
        )
        selected_tc_ids = (
            [explicit_tc_id] if explicit_tc_id is not None else auto_selected_ids
        )
        selected_tc_id = selected_tc_ids[0] if selected_tc_ids else None
        prefiltered_exclusions: list[dict[str, Any]] = []
        if explicit_tc_id is None:
            selected_set = set(selected_tc_ids)
            for item in selection_candidates:
                if item.get("tc_id") not in selected_set:
                    prefiltered_exclusions.append(
                        AutomationExclusion(
                            tc_id=item["tc_id"],
                            candidate_status=AutomationCandidateStatus.NOT_AUTOMATABLE,
                            reason=(
                                " / ".join(item.get("missing_capabilities") or [])
                                or "현재 자동화 실행 범위에 포함되지 않습니다."
                            ),
                        ).model_dump(mode="json")
                    )
        selection_file = run_dir / "agent3_selection.json"
        _write_json(
            selection_file,
            {
                "contract_version": "1.1",
                "run_id": run_id,
                "stage": "AGENT_3_SELECTION",
                "status": (
                    "SELECTED"
                    if selected_tc_ids
                    else "NOT_AUTOMATABLE"
                    if selection_candidates
                    else "NOT_REQUIRED"
                ),
                "selected_tc_id": selected_tc_id,
                "selected_tc_ids": selected_tc_ids,
                "candidates": selection_candidates,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        if not selected_tc_ids:
            summary_status = (
                "EXCLUDED" if prefiltered_exclusions else "NOT_REQUIRED"
            )
            _write_json(
                run_dir / "agent3_run_summary.json",
                {
                    "contract_version": "1.1",
                    "run_id": run_id,
                    "stage": "AGENT_3_RUN_SUMMARY",
                    "status": summary_status,
                    "selected_tc_ids": [],
                    "executed_tc_ids": [],
                    "entries": [],
                    "자동화_제외_TC": prefiltered_exclusions,
                    "target_file": target_html.name,
                    "target_sha256": _sha256_file(target_html),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            stage_exit_codes["agent3"] = 0
            pipeline_status = "PARTIAL" if prefiltered_exclusions else "PASS"
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status=pipeline_status,
                selected_tc_id=None,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at=None,
            )
            print(f"Run ID: {run_id}")
            print(
                "Agent 3 selection: "
                + ("ALL CANDIDATES EXCLUDED" if prefiltered_exclusions else "NOT REQUIRED")
            )
            print("Agent 3 model call: NOT EXECUTED")
            print(f"Orchestrator manifest: {run_dir / 'orchestrator_manifest.json'}")
            return 0

        print("Agent 3 selected TCs: " + ", ".join(selected_tc_ids))
        candidates_root = run_dir / "agent3_candidates"
        run_entries: list[dict[str, Any]] = []
        for tc_id in selected_tc_ids:
            artifact_dir = candidates_root / tc_id
            candidate_error: Exception | None = None
            try:
                candidate_exit = run_agent3(
                    argparse.Namespace(
                        run_id=run_id,
                        tc_id=tc_id,
                        target_html=str(target_html),
                        runs_root=str(runs_root),
                        model=args.model,
                        timeout=args.timeout,
                        preview_only=False,
                        artifact_dir=str(artifact_dir),
                    )
                )
            except Exception as exc:
                candidate_error = exc
                candidate_exit = 1
            run_entries.append(
                _agent3_run_entry(
                    run_dir, tc_id, artifact_dir, candidate_exit, candidate_error
                )
            )

        successful_entries = [item for item in run_entries if item["exit_code"] == 0]
        automation_exclusions = [
            *prefiltered_exclusions,
            *[
                _automation_exclusion_from_run_entry(item)
                for item in run_entries
                if item["exit_code"] != 0
            ],
        ]
        run_status = (
            "PASS"
            if successful_entries and not automation_exclusions
            else "PARTIAL"
            if automation_exclusions
            else "PASS"
        )
        summary_file = run_dir / "agent3_run_summary.json"
        _write_json(
            summary_file,
            {
                "contract_version": "1.0",
                "run_id": run_id,
                "stage": "AGENT_3_RUN_SUMMARY",
                "status": run_status,
                "selected_tc_ids": selected_tc_ids,
                "executed_tc_ids": [item["tc_id"] for item in successful_entries],
                "entries": run_entries,
                "자동화_제외_TC": automation_exclusions,
                "target_file": target_html.name,
                "target_sha256": _sha256_file(target_html),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        agent3_exit = 0
        stage_exit_codes["agent3"] = agent3_exit
        status = run_status
        _write_orchestrator_manifest(
            run_dir,
            run_id,
            status=status,
            selected_tc_id=selected_tc_id,
            target_html=target_html,
            stage_exit_codes=stage_exit_codes,
            stopped_at=None,
        )
        print(f"Orchestrator status: {status}")
        print(f"Agent 3 completed candidates: {len(successful_entries)}")
        print(f"Agent 3 excluded candidates: {len(automation_exclusions)}")
        print(f"Orchestrator manifest: {run_dir / 'orchestrator_manifest.json'}")
        return agent3_exit
    except Exception as exc:
        if run_dir.is_dir():
            _write_orchestrator_manifest(
                run_dir,
                run_id,
                status="ERROR",
                selected_tc_id=selected_tc_id,
                target_html=target_html,
                stage_exit_codes=stage_exit_codes,
                stopped_at=current_stage,
                error=exc,
            )
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qa-pipeline-v2",
        description="변경 요구사항 기반 QA Pipeline V2",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    agent1 = subparsers.add_parser("agent1", help="Agent 1과 Checkpoint 1 실행")
    agent1.add_argument("--request", required=True, help="변경 요청 JSON 경로")
    agent1.add_argument("--srs", default=str(DEFAULT_SRS), help="제품 SRS Markdown 경로")
    agent1.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent1.add_argument(
        "--model",
        default=None,
        help="OpenAI 모델 ID. 미지정 시 OPENAI_MODEL 또는 gpt-5.6-terra",
    )
    agent1.set_defaults(handler=run_agent1)

    agent2 = subparsers.add_parser("agent2", help="Agent 2와 Checkpoint 2 실행")
    agent2.add_argument("--run-id", required=True, help="CP1을 통과한 Run ID")
    agent2.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent2.add_argument(
        "--model",
        default=None,
        help="OpenAI 모델 ID. 미지정 시 OPENAI_MODEL 또는 gpt-5.6-terra",
    )
    agent2.set_defaults(handler=run_agent2)

    agent3 = subparsers.add_parser("agent3", help="Run Agent 3, CP3, and the isolated trial")
    agent3.add_argument("--run-id", required=True, help="Run ID whose CP2 status is PASS")
    agent3.add_argument("--tc-id", required=True, help="One CP2-approved automation candidate TC ID")
    agent3.add_argument("--target-html", required=True, help="Read-only local virtual controller HTML path")
    agent3.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT), help="Run artifact root")
    agent3.add_argument("--model", default=None, help="OpenAI model ID")
    agent3.add_argument("--timeout", type=int, default=90, help="Isolated trial timeout in seconds")
    agent3.add_argument("--preview-only", action="store_true", help="Inspect UI and write the exact model-input preview without calling the API")
    agent3.set_defaults(handler=run_agent3)

    pipeline = subparsers.add_parser(
        "pipeline",
        help="Agent 1→2→3, CP1→3, and the candidate trial in one command",
    )
    agent2.add_argument(
        "--approved-assets-root",
        default=str(DEFAULT_APPROVED_ASSETS_ROOT),
        help="사람 승인 공식 TC·자동화 Registry 폴더",
    )
    pipeline.add_argument("--request", required=True, help="Change-request JSON path")
    pipeline.add_argument(
        "--tc-id",
        default="AUTO",
        help="Current-Run TC ID, or AUTO to select one eligible CP2 candidate",
    )
    pipeline.add_argument(
        "--target-html",
        required=True,
        help="Read-only local virtual controller HTML path",
    )
    pipeline.add_argument("--srs", default=str(DEFAULT_SRS), help="Product SRS Markdown path")
    pipeline.add_argument("--runs-root", default=str(DEFAULT_RUNS_ROOT), help="Run artifact root")
    pipeline.add_argument(
        "--approved-assets-root",
        default=str(DEFAULT_APPROVED_ASSETS_ROOT),
        help="Human-approved TC and automation registry root",
    )
    pipeline.add_argument("--model", default=None, help="OpenAI model ID shared by Agent 1→3")
    pipeline.add_argument("--timeout", type=int, default=90, help="Isolated trial timeout in seconds")
    pipeline.set_defaults(handler=run_pipeline)

    execute = subparsers.add_parser(
        "execute",
        help="신규 자동화 후보 시험 결과를 재사용하고 관련 기존 회귀 TC 실행",
    )
    execute.add_argument("--run-id", required=True, help="Agent 3 시험이 완료된 Run ID")
    execute.add_argument(
        "--target-html",
        required=True,
        help="읽기 전용 V2 기준 제품 virtual-controller.html 경로",
    )
    execute.add_argument(
        "--baseline-tests",
        default=None,
        help="기준 제품 tests/test_controller.py 경로. 생략 시 대상 HTML 옆 tests 폴더 사용",
    )
    execute.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    execute.add_argument(
        "--approved-assets-root",
        default=str(DEFAULT_APPROVED_ASSETS_ROOT),
        help="사람 승인 공식 TC·자동화 Registry 폴더",
    )
    execute.add_argument(
        "--timeout", type=int, default=60, help="기존 TC 한 건당 제한 시간(초)"
    )
    execute.set_defaults(handler=run_validation_execution)
    agent4 = subparsers.add_parser(
        "agent4",
        help="검증 실행 결과를 재실행 없이 규칙 기반으로 분류하고 최종 보고 생성",
    )
    agent4.add_argument("--run-id", required=True, help="검증 실행이 완료된 Run ID")
    agent4.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    agent4.add_argument(
        "--send",
        action="store_true",
        help="CP4 통과 후 Slack·Notion에 실제 전송. 기본값은 Dry-run",
    )
    agent4.set_defaults(handler=run_agent4)
    reporting = subparsers.add_parser(
        "report",
        help="이미 완료된 Agent 4 최종 보고의 Slack·Notion Payload 생성 또는 전송",
    )
    reporting.add_argument("--run-id", required=True, help="Agent 4가 완료된 Run ID")
    reporting.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    reporting.add_argument(
        "--send",
        action="store_true",
        help="Slack·Notion에 실제 전송. 기본값은 Dry-run",
    )
    reporting.set_defaults(handler=run_external_reporting)
    human_review = subparsers.add_parser(
        "human-review",
        help="완료된 Agent 4 결과에서 사람이 작성할 최종 검토 Markdown 생성",
    )
    human_review.add_argument("--run-id", required=True, help="Agent 4가 완료된 Run ID")
    human_review.add_argument(
        "--runs-root", default=str(DEFAULT_RUNS_ROOT), help="실행 결과 저장 폴더"
    )
    human_review.add_argument(
        "--refresh",
        action="store_true",
        help="기존 자동 생성 문서와 Manifest 해시를 확인한 뒤 현재 양식으로 갱신",
    )
    human_review.set_defaults(handler=run_human_review_document)
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError, Agent1Error, Agent2Error, Agent3Error) as exc:
        parser.error(str(exc))
    return 1

if __name__ == "__main__":
    raise SystemExit(main())

__all__ = [name for name in globals() if not name.startswith("__")]
