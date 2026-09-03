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

# CLI
# ---------------------------------------------------------------------------
DEFAULT_SRS = Path("docs") / "01_PRODUCT_SRS.md"
DEFAULT_RUNS_ROOT = Path("runs")
DEFAULT_APPROVED_ASSETS_ROOT = Path("approved_assets")
_RUN_ID_PATTERN = re.compile(r"^RUN-\d{8}-\d{6}-[A-F0-9]{6}$")


def _read_request(path: Path) -> ChangeRequest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return ChangeRequest.model_validate(payload)
    except FileNotFoundError as exc:
        raise ValueError(f"변경 요청 파일을 찾을 수 없습니다: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"변경 요청 JSON 형식이 잘못됐습니다: {exc}") from exc
    except ValidationError as exc:
        raise ValueError(f"변경 요청 Schema 검증에 실패했습니다:\n{exc}") from exc


def _read_json_payload(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"필수 실행 산출물을 찾을 수 없습니다: {path.name}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"실행 산출물 JSON 형식이 잘못됐습니다: {path.name}\n{exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"실행 산출물은 JSON 객체여야 합니다: {path.name}")
    return payload


def _read_json_model(path: Path, model_type):
    try:
        return model_type.model_validate(_read_json_payload(path))
    except ValidationError as exc:
        raise ValueError(f"실행 산출물 Schema 검증에 실패했습니다: {path.name}\n{exc}") from exc


def _resolve_run_dir(runs_root: Path, run_id: str) -> Path:
    if not _RUN_ID_PATTERN.fullmatch(run_id):
        raise ValueError("Run ID 형식이 올바르지 않습니다.")
    root = runs_root.resolve()
    run_dir = (root / run_id).resolve()
    try:
        run_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("Run ID가 runs 폴더 밖을 가리킬 수 없습니다.") from exc
    if not run_dir.is_dir():
        raise ValueError(f"Run 폴더를 찾을 수 없습니다: {run_dir}")
    return run_dir


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"RUN-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def run_agent1(args: argparse.Namespace) -> int:
    request_path = Path(args.request).resolve()
    srs_path = Path(args.srs).resolve()
    request = _read_request(request_path)
    requirements = load_srs_requirements(srs_path)
    srs_text = srs_path.read_text(encoding="utf-8")
    agent = OpenAIAgent1(model=args.model)
    run_id = getattr(args, "run_id", None) or _new_run_id()
    run_dir = Path(args.runs_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    request_file = run_dir / "request.json"
    srs_snapshot_file = run_dir / "srs_snapshot.md"
    analysis_file = run_dir / "agent1_change_analysis.json"
    checkpoint_file = run_dir / "checkpoint1.json"
    _write_json(request_file, request.model_dump(mode="json"))
    _write_text_atomic(srs_snapshot_file, srs_text)
    try:
        response = agent.analyze(request, requirements)
        checkpoint = evaluate_checkpoint1(request, response.analysis, requirements)
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint.status.value,
                "handoff_status": checkpoint.handoff_status.value,
                "model": response.model,
                "usage": response.usage,
            }
        ]
        if checkpoint.status == CheckStatus.FAIL:
            _write_json(
                run_dir / "agent1_change_analysis_attempt_1.json",
                response.analysis.model_dump(mode="json"),
            )
            _write_json(
                run_dir / "checkpoint1_attempt_1.json",
                checkpoint.model_dump(mode="json", by_alias=True),
            )
            response = agent.analyze(
                request,
                requirements,
                previous_analysis=response.analysis,
                checkpoint_feedback=[
                    item.message
                    for item in checkpoint.checks
                    if item.status == CheckStatus.FAIL
                ],
            )
            checkpoint = evaluate_checkpoint1(request, response.analysis, requirements)
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint.status.value,
                    "handoff_status": checkpoint.handoff_status.value,
                    "model": response.model,
                    "usage": response.usage,
                }
            )

        _write_json(analysis_file, response.analysis.model_dump(mode="json"))
        _write_json(checkpoint_file, checkpoint.model_dump(mode="json"))
        _write_json(
            run_dir / "run_manifest.json",
            {
                "contract_version": "2.4",
                "prompt_version": "agent1-2.4",
                "run_id": run_id,
                "stage": "AGENT_1_CP1",
                "status": checkpoint.status.value,
                "handoff_status": checkpoint.handoff_status.value,
                "model": response.model,
                "usage": _aggregate_model_usage(attempts),
                "final_attempt_usage": response.usage,
                "attempts": attempts,
                "request_file": request_file.name,
                "request_sha256": _sha256_file(request_file),
                "srs_snapshot_file": srs_snapshot_file.name,
                "srs_sha256": _sha256_file(srs_snapshot_file),
                "agent1_analysis_sha256": _sha256_file(analysis_file),
                "checkpoint1_sha256": _sha256_file(checkpoint_file),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        _write_json(
            run_dir / "run_error.json",
            {
                "run_id": run_id,
                "stage": "AGENT_1_CP1",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"실행 실패: {exc}\n기록 위치: {run_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {run_id}")
    print(f"Agent 1 model: {response.model}")
    print(f"Checkpoint 1: {checkpoint.status.value}")
    print(f"Agent 2 handoff: {checkpoint.handoff_status.value}")
    print(f"결과 위치: {run_dir}")
    return 0 if checkpoint.handoff_status == HandoffStatus.CONTINUE else 2


def _load_verified_agent1_run(run_dir: Path, run_id: str) -> tuple[
    ChangeRequest,
    dict[str, SrsRequirement],
    Agent1Analysis,
    Checkpoint1Result,
    dict[str, Any],
]:
    manifest_file = run_dir / "run_manifest.json"
    manifest = _read_json_payload(manifest_file)
    if manifest.get("run_id") != run_id or manifest.get("stage") != "AGENT_1_CP1":
        raise ValueError("run_manifest가 요청한 Agent 1 Run과 일치하지 않습니다.")
    if manifest.get("status") not in {
        CheckStatus.PASS.value,
        CheckStatus.REVIEW.value,
    }:
        raise ValueError(f"Checkpoint 1이 {manifest.get('status')}이므로 Agent 2를 실행할 수 없습니다.")
    if manifest.get("handoff_status") != HandoffStatus.CONTINUE.value:
        raise ValueError(
            f"Agent 2 인계 상태가 {manifest.get('handoff_status')}이므로 실행을 계속할 수 없습니다."
        )

    request_file = run_dir / "request.json"
    srs_snapshot_file = run_dir / "srs_snapshot.md"
    analysis_file = run_dir / "agent1_change_analysis.json"
    checkpoint_file = run_dir / "checkpoint1.json"
    _verify_sha256(request_file, manifest.get("request_sha256"), "변경 요청")
    _verify_sha256(srs_snapshot_file, manifest.get("srs_sha256"), "SRS 스냅샷")
    _verify_sha256(analysis_file, manifest.get("agent1_analysis_sha256"), "Agent 1 분석")
    _verify_sha256(checkpoint_file, manifest.get("checkpoint1_sha256"), "Checkpoint 1")

    request = _read_request(request_file)
    requirements = load_srs_requirements(srs_snapshot_file)
    analysis = _read_json_model(analysis_file, Agent1Analysis)
    checkpoint = _read_json_model(checkpoint_file, Checkpoint1Result)
    recomputed = evaluate_checkpoint1(request, analysis, requirements)
    if recomputed.model_dump(mode="json") != checkpoint.model_dump(mode="json"):
        raise ValueError("현재 CP1 규칙으로 재검증한 결과가 저장된 Checkpoint 1과 다릅니다.")
    if checkpoint.status not in {CheckStatus.PASS, CheckStatus.REVIEW} or checkpoint.handoff_status != HandoffStatus.CONTINUE:
        raise ValueError("Checkpoint 1이 Agent 2 실행을 허용하지 않습니다.")
    return request, requirements, analysis, checkpoint, manifest


def run_agent2(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    reservation_file = run_dir / "agent2_in_progress.json"
    approved_catalog_file = run_dir / "approved_regression_catalog.json"
    immutable_outputs = [
        run_dir / "agent2_test_design.json",
        run_dir / "checkpoint2.json",
        run_dir / "agent2_manifest.json",
        run_dir / "agent2_technical_id_normalization.json",
        approved_catalog_file,
        reservation_file,
    ]
    if any(path.exists() for path in immutable_outputs):
        raise ValueError("이 Run에는 Agent 2 산출물 또는 진행 표시가 이미 존재합니다. 새 Agent 1 Run을 사용하세요.")
    request, requirements, analysis, _, source_manifest = _load_verified_agent1_run(
        run_dir, args.run_id
    )
    approved_assets_root = Path(
        getattr(args, "approved_assets_root", DEFAULT_APPROVED_ASSETS_ROOT)
    ).resolve()
    approved_catalog, approved_snapshot = load_approved_regression_catalog(
        approved_assets_root
    )
    existing_catalog = (*EXISTING_REGRESSION_CATALOG, *approved_catalog)
    try:
        with reservation_file.open("x", encoding="utf-8") as handle:
            json.dump(
                {
                    "run_id": args.run_id,
                    "stage": "AGENT_2_CP2",
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
                handle,
                ensure_ascii=False,
                indent=2,
            )
            handle.write("\n")
    except FileExistsError as exc:
        raise ValueError("이 Run의 Agent 2가 이미 진행 중입니다. 새 Agent 1 Run을 사용하세요.") from exc

    _write_json(approved_catalog_file, approved_snapshot)

    agent = OpenAIAgent2(model=args.model)
    try:
        response = agent.design(
            request,
            analysis,
            requirements,
            existing_catalog=existing_catalog,
        )
        raw_design = response.design
        normalized_design, first_normalizations = _normalize_agent2_technical_ids(
            raw_design
        )
        normalization_attempts: list[dict[str, Any]] = []
        if first_normalizations:
            raw_file = run_dir / "agent2_test_design_model_raw_attempt_1.json"
            _write_json(
                raw_file,
                raw_design.model_dump(mode="json", by_alias=True),
            )
            normalization_attempts.append(
                {
                    "attempt": 1,
                    "raw_design_file": raw_file.name,
                    "raw_design_sha256": _sha256_file(raw_file),
                    "changes": first_normalizations,
                }
            )
            response = Agent2Response(
                design=normalized_design,
                response_id=response.response_id,
                model=response.model,
                usage=response.usage,
            )
        checkpoint2 = evaluate_checkpoint2(
            request,
            analysis,
            response.design,
            requirements,
            existing_catalog=existing_catalog,
            require_srs_revision_proposals=True,
        )
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint2.status.value,
                "model": response.model,
                "usage": response.usage,
            }
        ]
        if checkpoint2.status == CheckStatus.FAIL:
            _write_json(
                run_dir / "agent2_test_design_attempt_1.json",
                response.design.model_dump(mode="json", by_alias=True),
            )
            _write_json(
                run_dir / "checkpoint2_attempt_1.json",
                checkpoint2.model_dump(mode="json"),
            )
            response = agent.design(
                request,
                analysis,
                requirements,
                existing_catalog=existing_catalog,
                previous_design=response.design,
                checkpoint_feedback=[
                    f"{item.rule_id} {item.status.value}: {item.message}"
                    for item in checkpoint2.checks
                ],
            )
            raw_design = response.design
            normalized_design, retry_normalizations = (
                _normalize_agent2_technical_ids(raw_design)
            )
            if retry_normalizations:
                raw_file = run_dir / "agent2_test_design_model_raw_attempt_2.json"
                _write_json(
                    raw_file,
                    raw_design.model_dump(mode="json", by_alias=True),
                )
                normalization_attempts.append(
                    {
                        "attempt": 2,
                        "raw_design_file": raw_file.name,
                        "raw_design_sha256": _sha256_file(raw_file),
                        "changes": retry_normalizations,
                    }
                )
                response = Agent2Response(
                    design=normalized_design,
                    response_id=response.response_id,
                    model=response.model,
                    usage=response.usage,
                )
            checkpoint2 = evaluate_checkpoint2(
                request,
                analysis,
                response.design,
                requirements,
                existing_catalog=existing_catalog,
                require_srs_revision_proposals=True,
            )
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint2.status.value,
                    "model": response.model,
                    "usage": response.usage,
                }
            )

        normalization_file = run_dir / "agent2_technical_id_normalization.json"
        if normalization_attempts:
            _write_json(
                normalization_file,
                {
                    "contract_version": "1.0",
                    "run_id": args.run_id,
                    "stage": "AGENT_2_TECHNICAL_ID_NORMALIZATION",
                    "scope": "TC and Expected Result identifiers only",
                    "semantic_fields_changed": False,
                    "attempts": normalization_attempts,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )

        design_file = run_dir / "agent2_test_design.json"
        checkpoint2_file = run_dir / "checkpoint2.json"
        _write_json(design_file, response.design.model_dump(mode="json", by_alias=True))
        _write_json(checkpoint2_file, checkpoint2.model_dump(mode="json"))
        _write_json(
            run_dir / "agent2_manifest.json",
            {
                "contract_version": "3.0",
                "prompt_version": "agent2-2.14",
                "run_id": args.run_id,
                "source_stage": "AGENT_1_CP1",
                "stage": "AGENT_2_CP2",
                "status": checkpoint2.status.value,
                "model": response.model,
                "usage": _aggregate_model_usage(attempts),
                "final_attempt_usage": response.usage,
                "attempts": attempts,
                "technical_id_normalization_sha256": (
                    _sha256_file(normalization_file)
                    if normalization_file.is_file()
                    else None
                ),
                "source_run_manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
                "request_sha256": source_manifest["request_sha256"],
                "srs_sha256": source_manifest["srs_sha256"],
                "agent1_analysis_sha256": source_manifest["agent1_analysis_sha256"],
                "checkpoint1_sha256": source_manifest["checkpoint1_sha256"],
                "approved_regression_catalog_sha256": _sha256_file(
                    approved_catalog_file
                ),
                "srs_revision_contract": "1.0",
                "agent2_design_sha256": _sha256_file(design_file),
                "checkpoint2_sha256": _sha256_file(checkpoint2_file),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        reservation_file.unlink()
    except Exception as exc:
        _write_json(
            run_dir / "agent2_error.json",
            {
                "run_id": args.run_id,
                "stage": "AGENT_2_CP2",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"실행 실패: {exc}\n기록 위치: {run_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {args.run_id}")
    print(f"Agent 2 model: {response.model}")
    print(f"Checkpoint 2: {checkpoint2.status.value}")
    print(f"TC candidates: {len(response.design.test_cases)}")
    print(f"결과 위치: {run_dir}")
    return 0 if checkpoint2.status == CheckStatus.PASS else 2



def _load_verified_agent2_run(
    run_dir: Path, run_id: str
) -> tuple[
    ChangeRequest,
    dict[str, SrsRequirement],
    Agent1Analysis,
    Agent2TestDesign,
    Checkpoint2Result,
    dict[str, Any],
]:
    request, requirements, analysis, _, source_manifest = _load_verified_agent1_run(run_dir, run_id)
    manifest_file = run_dir / "agent2_manifest.json"
    manifest = _read_json_payload(manifest_file)
    if manifest.get("run_id") != run_id or manifest.get("stage") != "AGENT_2_CP2":
        raise ValueError("agent2_manifest does not match the requested Run.")
    if manifest.get("status") != CheckStatus.PASS.value:
        raise ValueError("Checkpoint 2 must PASS before Agent 3 can run.")
    _verify_sha256(
        run_dir / "run_manifest.json",
        manifest.get("source_run_manifest_sha256"),
        "Agent 1 Run manifest",
    )
    for key in ("request_sha256", "srs_sha256", "agent1_analysis_sha256", "checkpoint1_sha256"):
        if manifest.get(key) != source_manifest.get(key):
            raise ValueError(f"Agent 2 source chain mismatch: {key}")
    design_file = run_dir / "agent2_test_design.json"
    checkpoint_file = run_dir / "checkpoint2.json"
    _verify_sha256(design_file, manifest.get("agent2_design_sha256"), "Agent 2 design")
    _verify_sha256(checkpoint_file, manifest.get("checkpoint2_sha256"), "Checkpoint 2")
    design = _read_json_model(design_file, Agent2TestDesign)
    checkpoint = _read_json_model(checkpoint_file, Checkpoint2Result)
    catalog_file = run_dir / "approved_regression_catalog.json"
    catalog_hash = manifest.get("approved_regression_catalog_sha256")
    if catalog_hash is not None:
        _verify_sha256(catalog_file, catalog_hash, "승인 TC 카탈로그 Snapshot")
        existing_catalog = _catalog_from_snapshot(_read_json_payload(catalog_file))
    else:
        existing_catalog = EXISTING_REGRESSION_CATALOG
    recomputed = evaluate_checkpoint2(
        request,
        analysis,
        design,
        requirements,
        existing_catalog=existing_catalog,
        require_srs_revision_proposals=(
            manifest.get("srs_revision_contract") == "1.0"
        ),
    )
    if recomputed.model_dump(mode="json") != checkpoint.model_dump(mode="json"):
        raise ValueError("Stored Checkpoint 2 differs from the current CP2 rules.")
    if checkpoint.status != CheckStatus.PASS:
        raise ValueError("Checkpoint 2 does not allow Agent 3 execution.")
    return request, requirements, analysis, design, checkpoint, manifest


_AGENT3_TRIAL_ENV_ALLOWLIST = (
    "PATH",
    "PATHEXT",
    "SYSTEMROOT",
    "WINDIR",
    "TEMP",
    "TMP",
    "LOCALAPPDATA",
    "USERPROFILE",
    "HOME",
    "PYTHONUTF8",
    "PYTHONIOENCODING",
)


def run_candidate_trial(
    code_file: Path,
    target_html: Path,
    evidence_dir: Path,
    *,
    timeout_seconds: int,
) -> Agent3TrialResult:
    evidence_dir.mkdir(parents=True, exist_ok=True)
    stdout_file = evidence_dir / "trial-stdout.txt"
    stderr_file = evidence_dir / "trial-stderr.txt"
    started = time.monotonic()
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    outcome = TrialOutcome.AUTOMATION_ERROR

    def redact_output(value: str, *paths: Path) -> str:
        redacted = value
        for path in paths:
            resolved = str(path.resolve())
            redacted = redacted.replace(resolved, "<LOCAL_PATH>")
            redacted = redacted.replace(path.resolve().as_uri(), "<LOCAL_FILE_URL>")
        return redacted

    with tempfile.TemporaryDirectory(prefix="qa-agent3-") as temp_name:
        temp_root = Path(temp_name)
        isolated_candidate = temp_root / code_file.name
        shutil.copy2(code_file, isolated_candidate)
        env = {name: os.environ[name] for name in _AGENT3_TRIAL_ENV_ALLOWLIST if name in os.environ}
        # PYTHONUTF8=1 also changes how Windows decodes legacy site-package
        # .pth files and can prevent Python from starting. Keep locale-mode
        # startup while making the captured stdout/stderr encoding explicit.
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        env["QA_TARGET_URL"] = target_html.resolve().as_uri()
        env["QA_EVIDENCE_DIR"] = str(evidence_dir.resolve())
        command = [sys.executable, "-m", "pytest", isolated_candidate.name, "-q"]
        try:
            completed = _run_trial_subprocess(
                command,
                cwd=temp_root,
                env=env,
                timeout_seconds=timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = redact_output(completed.stdout[-20000:], temp_root, target_html, evidence_dir)
            stderr = redact_output(completed.stderr[-20000:], temp_root, target_html, evidence_dir)
            combined = stdout + "\n" + stderr
            if exit_code == 0:
                outcome = TrialOutcome.PASS
            elif "PRODUCT_MISMATCH:" in combined:
                outcome = TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
            elif any(
                marker in combined
                for marker in (
                    "Executable doesn't exist",
                    "BrowserType.launch",
                    "ERR_FILE_NOT_FOUND",
                    "Target page, context or browser has been closed",
                )
            ):
                outcome = TrialOutcome.ENVIRONMENT_ERROR
            else:
                outcome = TrialOutcome.AUTOMATION_ERROR
        except subprocess.TimeoutExpired as exc:
            stdout = redact_output((exc.stdout or "")[-20000:], temp_root, target_html, evidence_dir) if isinstance(exc.stdout, str) else ""
            stderr = redact_output((exc.stderr or "")[-20000:], temp_root, target_html, evidence_dir) if isinstance(exc.stderr, str) else ""
            outcome = TrialOutcome.TIMEOUT
    _write_text_atomic(stdout_file, stdout)
    _write_text_atomic(stderr_file, stderr)
    screenshot = evidence_dir / "trial-final.png"
    trace = evidence_dir / "trial-trace.zip"
    if trace.is_file():
        try:
            _redact_playwright_trace(
                trace,
                {
                    temp_root: "<TRIAL_WORKSPACE>",
                    Path.home(): "<USER_HOME>",
                    target_html: "<QA_TARGET_FILE>",
                    evidence_dir: "<EVIDENCE_DIR>",
                    code_file: "<CANDIDATE_FILE>",
                },
            )
        except zipfile.BadZipFile:
            # 시간 초과로 쓰기가 중단된 Trace는 비밀정보 제거를 보장할 수
            # 없으므로 신뢰 가능한 증거에 포함하지 않는다.
            trace.unlink()
    evidence_files = [stdout_file, stderr_file]
    if screenshot.is_file():
        evidence_files.append(screenshot)
    if trace.is_file():
        evidence_files.append(trace)
    return Agent3TrialResult(
        outcome=outcome,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        stdout_file=stdout_file.name,
        stderr_file=stderr_file.name,
        screenshot_file=screenshot.name if screenshot.is_file() else None,
        trace_file=trace.name if trace.is_file() else None,
        evidence_sha256={path.name: _sha256_file(path) for path in evidence_files},
        evidence_complete=screenshot.is_file() and trace.is_file(),
    )


def _terminate_trial_process_tree(process: subprocess.Popen[str]) -> None:
    """시간 초과된 pytest와 Playwright 자식 프로세스를 함께 정리한다."""

    try:
        import psutil
    except ImportError:
        process.kill()
        process.wait(timeout=5)
        return

    try:
        root = psutil.Process(process.pid)
        processes = root.children(recursive=True) + [root]
    except psutil.NoSuchProcess:
        return
    for item in reversed(processes):
        try:
            item.terminate()
        except psutil.NoSuchProcess:
            continue
    _, alive = psutil.wait_procs(processes, timeout=3)
    for item in alive:
        try:
            item.kill()
        except psutil.NoSuchProcess:
            continue
    psutil.wait_procs(alive, timeout=3)


def _run_trial_subprocess(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    timeout_seconds: int,
) -> subprocess.CompletedProcess[str]:
    """Candidate Trial을 실행하고 제한 초과 시 전체 프로세스 트리를 종료한다."""

    process = subprocess.Popen(
        command,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        shell=False,
    )
    try:
        stdout, stderr = process.communicate(timeout=timeout_seconds)
    except subprocess.TimeoutExpired:
        _terminate_trial_process_tree(process)
        stdout, stderr = process.communicate()
        raise subprocess.TimeoutExpired(
            command,
            timeout_seconds,
            output=stdout,
            stderr=stderr,
        )
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


def _agent3_cli_exit_code(
    checkpoint: Checkpoint3Result,
    trial: Agent3TrialResult | None,
) -> int:
    """Return success only when the evaluation flow completed meaningfully.

    A product mismatch is a valid QA finding, so the pipeline itself completed
    successfully. Automation, environment, and timeout failures mean that the
    product result is not trustworthy and must not be reported as CLI success.
    """
    if checkpoint.status != CheckStatus.PASS or trial is None:
        return 2
    required_evidence = {
        trial.stdout_file,
        trial.stderr_file,
        trial.screenshot_file,
        trial.trace_file,
    }
    evidence_is_complete = (
        trial.evidence_complete
        and None not in required_evidence
        and required_evidence == set(trial.evidence_sha256)
    )
    if trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    } and evidence_is_complete:
        return 0
    return 2


def _aggregate_model_usage(
    attempts: list[dict[str, Any]],
) -> dict[str, int | None]:
    """Sum model-token usage across every structured model attempt."""
    aggregate: dict[str, int | None] = {}
    required_keys = ("input_tokens", "output_tokens", "total_tokens")
    detail_keys = sorted(
        {
            key
            for attempt in attempts
            if isinstance((usage := attempt.get("usage")), dict)
            for key, value in usage.items()
            if key not in required_keys and isinstance(value, int)
        }
    )
    for key in (*required_keys, *detail_keys):
        values = [
            usage[key]
            for attempt in attempts
            if isinstance((usage := attempt.get("usage")), dict)
            and isinstance(usage.get(key), int)
        ]
        aggregate[key] = sum(values) if values else None
    return aggregate


def _aggregate_agent3_usage(
    attempts: list[dict[str, Any]],
) -> dict[str, int | None]:
    """Backward-compatible Agent 3 name for the shared usage aggregator."""
    return _aggregate_model_usage(attempts)


def run_agent3(args: argparse.Namespace) -> int:
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    artifact_dir_arg = getattr(args, "artifact_dir", None)
    artifact_dir = Path(artifact_dir_arg).resolve() if artifact_dir_arg else run_dir
    if artifact_dir != run_dir:
        try:
            artifact_dir.relative_to(run_dir)
        except ValueError as exc:
            raise ValueError("Agent 3 후보 산출물 경로는 현재 Run 안에 있어야 합니다.") from exc
        artifact_dir.mkdir(parents=True, exist_ok=False)
    final_outputs = [
        artifact_dir / "agent3_automation_plan.json",
        artifact_dir / "checkpoint3.json",
        artifact_dir / "agent3_trial.json",
        artifact_dir / "agent3_manifest.json",
        artifact_dir / "agent3_error.json",
    ]
    candidate_dir = artifact_dir / "candidates"
    evidence_dir = artifact_dir / "evidence" / args.tc_id
    if any(path.exists() for path in final_outputs) or candidate_dir.exists():
        raise ValueError("This Run already contains final Agent 3 artifacts.")

    _, requirements, _, design, _, source_manifest = _load_verified_agent2_run(
        run_dir, args.run_id
    )
    matches = [item for item in design.test_cases if item.tc_id == args.tc_id]
    if len(matches) != 1:
        raise ValueError(f"Exactly one CP2-approved TC is required: {args.tc_id}")
    test_case = matches[0]
    eligibility = evaluate_agent3_eligibility(test_case)
    eligibility_file = artifact_dir / "agent3_eligibility.json"
    _write_json(
        eligibility_file,
        {
            "contract_version": "3.2",
            "run_id": args.run_id,
            "stage": "AGENT_3_ELIGIBILITY",
            "source_agent2_manifest_sha256": _sha256_file(
                run_dir / "agent2_manifest.json"
            ),
            "source_agent2_design_sha256": source_manifest[
                "agent2_design_sha256"
            ],
            **eligibility.model_dump(mode="json"),
            "created_at": datetime.now(timezone.utc).isoformat(),
        },
    )
    if not eligibility.model_call_allowed:
        print(f"Run ID: {args.run_id}")
        print("자동화 후보 상태: 현재 TC가 자동화 후보로 승인되지 않음")
        print("Agent 3 model call: NOT EXECUTED")
        print("자동화 불가 사유: " + ", ".join(eligibility.missing_capabilities))
        print(f"Artifacts: {artifact_dir}")
        return 2

    target_html = Path(args.target_html).resolve()
    try:
        observation = inspect_target_ui(
            target_html,
            required_selectors=set(eligibility.required_selectors),
            required_harness_keys=set(eligibility.required_harness_keys),
            discover_generic=eligibility.generic_discovery_required,
        )
        observation_file = artifact_dir / "agent3_ui_observation.json"
        _write_json(observation_file, observation.model_dump(mode="json"))
        preview_payload = build_agent3_model_input(test_case, observation, requirements)
        preview_payload["model"] = args.model or os.getenv("OPENAI_MODEL", "gpt-5.6-terra")
        preview_file = artifact_dir / "agent3_model_input_preview.json"
        _write_json(preview_file, preview_payload)
        if getattr(args, "preview_only", False):
            print(f"Run ID: {args.run_id}")
            print("Agent 3 model call: NOT EXECUTED")
            print(f"Preview: {preview_file}")
            return 0

        agent = OpenAIAgent3(model=args.model)
        response = agent.plan(test_case, observation, requirements)
        checkpoint = evaluate_checkpoint3_plan(test_case, response.plan, observation)
        attempts = [
            {
                "attempt": 1,
                "status": checkpoint.status.value,
                "model": response.model,
                "usage": response.usage,
                "usage_source": "AGENT_3_MODEL_CALL",
            }
        ]
        if checkpoint.status == CheckStatus.FAIL:
            _write_json(artifact_dir / "agent3_automation_plan_attempt_1.json", response.plan.model_dump(mode="json"))
            _write_json(artifact_dir / "checkpoint3_attempt_1.json", checkpoint.model_dump(mode="json"))
            response = agent.plan(
                test_case,
                observation,
                requirements,
                previous_plan=response.plan,
                checkpoint_feedback=[item.message for item in checkpoint.checks if item.status == CheckStatus.FAIL],
            )
            checkpoint = evaluate_checkpoint3_plan(test_case, response.plan, observation)
            attempts.append(
                {
                    "attempt": 2,
                    "status": checkpoint.status.value,
                    "model": response.model,
                    "usage": response.usage,
                    "usage_source": "AGENT_3_INDIVIDUAL_REPAIR_CALL",
                }
            )

        plan_file = artifact_dir / "agent3_automation_plan.json"
        checkpoint_file = artifact_dir / "checkpoint3.json"
        _write_json(plan_file, response.plan.model_dump(mode="json"))
        trial: Agent3TrialResult | None = None
        candidate_file: Path | None = None
        if checkpoint.status == CheckStatus.PASS:
            candidate_dir.mkdir(parents=True, exist_ok=False)
            candidate_file = candidate_dir / f"test_{args.tc_id.lower().replace('-', '_')}.py"
            code = compile_automation_candidate(args.run_id, test_case, response.plan)
            static_checks = evaluate_compiled_candidate(test_case, code)
            checkpoint.checks.extend(static_checks)
            if any(item.status == CheckStatus.FAIL for item in static_checks):
                checkpoint.status = CheckStatus.FAIL
                checkpoint.candidate_status = AutomationCandidateStatus.REVISION_REQUIRED
            else:
                _write_text_atomic(candidate_file, code)
                trial = run_candidate_trial(
                    candidate_file,
                    target_html,
                    evidence_dir,
                    timeout_seconds=args.timeout,
                )
                if _sha256_file(target_html) != observation.target_sha256:
                    raise Agent3Error(
                        "The read-only baseline target changed during the isolated trial."
                    )
                if trial.outcome == TrialOutcome.PASS:
                    checkpoint.candidate_status = AutomationCandidateStatus.READY_FOR_EXECUTION
                elif trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE:
                    checkpoint.candidate_status = AutomationCandidateStatus.PRODUCT_MISMATCH_DETECTED
                else:
                    checkpoint.candidate_status = AutomationCandidateStatus.TRIAL_FAILED
        _write_json(checkpoint_file, checkpoint.model_dump(mode="json"))
        if trial is not None:
            _write_json(artifact_dir / "agent3_trial.json", trial.model_dump(mode="json"))

        manifest_payload = {
            "contract_version": "4.0",
            "prompt_version": "agent3-3.12",
            "run_id": args.run_id,
            "source_stage": "AGENT_2_CP2",
            "stage": "AGENT_3_CP3_TRIAL",
            "tc_id": args.tc_id,
            "status": checkpoint.status.value,
            "candidate_status": checkpoint.candidate_status.value,
            "model": response.model,
            "usage": _aggregate_agent3_usage(attempts),
            "final_attempt_usage": response.usage,
            "attempts": attempts,
            "source_agent2_manifest_sha256": _sha256_file(run_dir / "agent2_manifest.json"),
            "source_agent2_design_sha256": source_manifest["agent2_design_sha256"],
            "eligibility_sha256": _sha256_file(eligibility_file),
            "ui_observation_sha256": _sha256_file(observation_file),
            "target_file": target_html.name,
            "target_sha256": observation.target_sha256,
            "automation_plan_sha256": _sha256_file(plan_file),
            "checkpoint3_sha256": _sha256_file(checkpoint_file),
            "candidate_file": candidate_file.name if candidate_file and candidate_file.is_file() else None,
            "candidate_sha256": _sha256_file(candidate_file) if candidate_file and candidate_file.is_file() else None,
            "trial_file": "agent3_trial.json" if trial is not None else None,
            "trial_sha256": _sha256_file(artifact_dir / "agent3_trial.json") if trial is not None else None,
            "trial_evidence_sha256": (
                trial.evidence_sha256 if trial is not None else {}
            ),
            "project1_modified": _sha256_file(target_html) != observation.target_sha256,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(artifact_dir / "agent3_manifest.json", manifest_payload)
    except Exception as exc:
        _write_json(
            artifact_dir / "agent3_error.json",
            {
                "run_id": args.run_id,
                "stage": "AGENT_3_CP3_TRIAL",
                "tc_id": args.tc_id,
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Agent 3 failed: {exc}\nArtifacts: {artifact_dir}", file=sys.stderr)
        return 1

    print(f"Run ID: {args.run_id}")
    print(f"Agent 3 모델: {response.model}")
    print(f"검증 단계 3: {checkpoint.status.value}")
    print(f"자동화 후보 상태: {checkpoint.candidate_status.value}")
    if trial is not None:
        print(f"신규 자동화 후보 시험 결과: {trial.outcome.value}")
    print(f"Artifacts: {artifact_dir}")
    return _agent3_cli_exit_code(checkpoint, trial)


def select_existing_regressions(
    requirement_ids: list[str] | set[str] | tuple[str, ...],
    catalog: tuple[ExistingRegressionSpec, ...] = EXISTING_REGRESSION_CATALOG,
) -> list[ExistingRegressionSpec]:
    """Select only reusable baseline regressions related to the approved TC."""
    approved = set(requirement_ids)
    return [
        spec
        for spec in catalog
        if approved.intersection(spec.requirement_ids)
    ]


def _safe_artifact_child(parent: Path, name: str, label: str) -> Path:
    if Path(name).name != name:
        raise ValueError(f"{label} 파일명은 하위 경로를 포함할 수 없습니다.")
    path = (parent / name).resolve()
    try:
        path.relative_to(parent.resolve())
    except ValueError as exc:
        raise ValueError(f"{label} 파일이 허용된 폴더 밖을 가리킵니다.") from exc
    if not path.is_file():
        raise ValueError(f"{label} 파일을 찾을 수 없습니다: {name}")
    return path


def _last_output_line(stdout: str, stderr: str) -> str | None:
    lines = [line.strip() for line in (stdout + "\n" + stderr).splitlines() if line.strip()]
    return lines[-1][-1000:] if lines else None


def _exception_type_from_output(stdout: str, stderr: str) -> str | None:
    combined = stdout + "\n" + stderr
    match = re.search(
        r"\b(AssertionError|SimulatorTimeoutError|TimeoutError|PlaywrightError|Error)\b",
        combined,
    )
    return match.group(1) if match else None


def _neutral_status_from_trial(outcome: TrialOutcome) -> NeutralExecutionStatus:
    return {
        TrialOutcome.PASS: NeutralExecutionStatus.PASSED,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE: (
            NeutralExecutionStatus.ASSERTION_FAILED
        ),
        TrialOutcome.AUTOMATION_ERROR: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.ENVIRONMENT_ERROR: NeutralExecutionStatus.EXECUTION_ERROR,
        TrialOutcome.TIMEOUT: NeutralExecutionStatus.TIMEOUT,
    }[outcome]


def _candidate_execution_record(
    run_dir: Path,
    run_id: str,
    target_html: Path,
    artifact_dir: Path | None = None,
) -> tuple[NeutralExecutionResult, ProductTestCaseCandidate, dict[str, Any]]:
    artifact_dir = artifact_dir or run_dir
    try:
        artifact_dir.resolve().relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("Agent 3 후보 산출물은 현재 Run 안에 있어야 합니다.") from exc
    _, _, _, design, _, agent2_manifest = _load_verified_agent2_run(run_dir, run_id)
    agent2_manifest_file = run_dir / "agent2_manifest.json"
    agent3_manifest_file = artifact_dir / "agent3_manifest.json"
    agent3_manifest = _read_json_payload(agent3_manifest_file)
    if agent3_manifest.get("run_id") != run_id:
        raise ValueError("Agent 3 Manifest의 Run ID가 현재 Run과 다릅니다.")
    if agent3_manifest.get("stage") != "AGENT_3_CP3_TRIAL":
        raise ValueError("Agent 3 Manifest 단계가 신규 자동화 후보 시험이 아닙니다.")
    if agent3_manifest.get("status") != CheckStatus.PASS.value:
        raise ValueError("Agent 3가 PASS 상태가 아니어서 실행 결과를 인계할 수 없습니다.")
    _verify_sha256(
        agent2_manifest_file,
        agent3_manifest.get("source_agent2_manifest_sha256"),
        "Agent 2 Manifest",
    )
    if agent3_manifest.get("source_agent2_design_sha256") != agent2_manifest.get(
        "agent2_design_sha256"
    ):
        raise ValueError("Agent 3가 참조한 Agent 2 설계 해시가 현재 Manifest와 다릅니다.")

    tc_id = agent3_manifest.get("tc_id")
    test_case = next((item for item in design.test_cases if item.tc_id == tc_id), None)
    if test_case is None:
        raise ValueError("Agent 3 선택 TC가 현재 Agent 2 설계에 없습니다.")

    artifact_hashes = (
        ("agent3_eligibility.json", "eligibility_sha256", "Agent 3 Eligibility"),
        ("agent3_ui_observation.json", "ui_observation_sha256", "UI Observation"),
        ("agent3_automation_plan.json", "automation_plan_sha256", "Agent 3 계획"),
        ("checkpoint3.json", "checkpoint3_sha256", "Checkpoint 3"),
        ("agent3_trial.json", "trial_sha256", "Agent 3 시험 결과"),
    )
    for filename, key, label in artifact_hashes:
        _verify_sha256(artifact_dir / filename, agent3_manifest.get(key), label)

    observation = _read_json_model(
        artifact_dir / "agent3_ui_observation.json", UiObservation
    )
    plan = _read_json_model(
        artifact_dir / "agent3_automation_plan.json", Agent3AutomationPlan
    )
    current_checkpoint3 = evaluate_checkpoint3_plan(test_case, plan, observation)
    current_code = compile_automation_candidate(run_id, test_case, plan)
    current_static_checks = evaluate_compiled_candidate(test_case, current_code)
    current_checkpoint3.checks.extend(current_static_checks)
    if any(check.status == CheckStatus.FAIL for check in current_static_checks):
        current_checkpoint3.status = CheckStatus.FAIL
        current_checkpoint3.candidate_status = (
            AutomationCandidateStatus.REVISION_REQUIRED
        )
    if current_checkpoint3.status != CheckStatus.PASS:
        failed_rules = ", ".join(
            check.rule_id
            for check in current_checkpoint3.checks
            if check.status == CheckStatus.FAIL
        )
        raise ValueError(
            "저장된 Agent 3 계획이 현재 CP3 규칙을 통과하지 못했습니다: "
            + failed_rules
        )

    checkpoint3 = _read_json_model(artifact_dir / "checkpoint3.json", Checkpoint3Result)
    if checkpoint3.status != CheckStatus.PASS:
        raise ValueError("Checkpoint 3가 PASS가 아니어서 실행 결과를 인계할 수 없습니다.")
    trial = _read_json_model(artifact_dir / "agent3_trial.json", Agent3TrialResult)
    trusted_product_observation = trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    }
    if trusted_product_observation and (
        not trial.evidence_complete
        or trial.screenshot_file is None
        or trial.trace_file is None
    ):
        raise ValueError("신규 자동화 후보 시험 증거가 완전하지 않습니다.")

    target_html = target_html.resolve()
    if not target_html.is_file():
        raise ValueError("검증 대상 HTML을 찾을 수 없습니다.")
    target_sha256 = _sha256_file(target_html)
    if target_html.name != agent3_manifest.get("target_file"):
        raise ValueError("검증 대상 파일명이 Agent 3 Manifest와 다릅니다.")
    if target_sha256 != agent3_manifest.get("target_sha256"):
        raise ValueError("검증 대상 HTML이 신규 자동화 후보 시험 후 변경됐습니다.")
    if agent3_manifest.get("project1_modified") is not False:
        raise ValueError("Agent 3 실행에서 기준 제품 불변을 확인하지 못했습니다.")

    candidate_name = agent3_manifest.get("candidate_file")
    if not isinstance(candidate_name, str):
        raise ValueError("Agent 3 Candidate 파일명이 없습니다.")
    candidate_file = _safe_artifact_child(
        artifact_dir / "candidates", candidate_name, "Agent 3 Candidate"
    )
    _verify_sha256(
        candidate_file,
        agent3_manifest.get("candidate_sha256"),
        "Agent 3 Candidate",
    )

    evidence_dir = artifact_dir / "evidence" / test_case.tc_id
    evidence_names = [trial.stdout_file, trial.stderr_file]
    if trial.screenshot_file:
        evidence_names.append(trial.screenshot_file)
    if trial.trace_file:
        evidence_names.append(trial.trace_file)
    if set(trial.evidence_sha256) != set(evidence_names):
        raise ValueError("Agent 3 Trial의 증거 목록과 SHA-256 목록이 다릅니다.")
    evidence_files = [
        _safe_artifact_child(evidence_dir, name, "신규 후보 시험 증거")
        for name in evidence_names
    ]
    evidence_paths = [path.relative_to(run_dir).as_posix() for path in evidence_files]
    evidence_hashes = {
        relative: _sha256_file(path)
        for relative, path in zip(evidence_paths, evidence_files, strict=True)
    }
    manifest_evidence_hashes = agent3_manifest.get("trial_evidence_sha256")
    if not isinstance(manifest_evidence_hashes, dict):
        raise ValueError("Agent 3 Manifest에 시험 증거 SHA-256이 없습니다.")
    if manifest_evidence_hashes != trial.evidence_sha256:
        raise ValueError("Agent 3 Manifest와 Trial의 증거 SHA-256이 다릅니다.")
    for evidence_file in evidence_files:
        expected_hash = trial.evidence_sha256.get(evidence_file.name)
        if expected_hash is None or _sha256_file(evidence_file) != expected_hash:
            raise ValueError(
                f"Agent 3 시험 증거 SHA-256이 일치하지 않습니다: {evidence_file.name}"
            )
    stdout = (evidence_dir / trial.stdout_file).read_text(encoding="utf-8")
    stderr = (evidence_dir / trial.stderr_file).read_text(encoding="utf-8")
    status = _neutral_status_from_trial(trial.outcome)
    return (
        NeutralExecutionResult(
            test_id=test_case.tc_id,
            source=ExecutionSource.NEW_AUTOMATION_CANDIDATE,
            requirement_ids=test_case.requirement_ids,
            status=status,
            source_outcome=trial.outcome.value,
            exit_code=trial.exit_code,
            duration_ms=trial.duration_ms,
            test_file=candidate_file.relative_to(run_dir).as_posix(),
            test_sha256=_sha256_file(candidate_file),
            target_sha256=target_sha256,
            reused=True,
            stdout_file=(evidence_dir / trial.stdout_file).relative_to(run_dir).as_posix(),
            stderr_file=(evidence_dir / trial.stderr_file).relative_to(run_dir).as_posix(),
            evidence_files=evidence_paths,
            evidence_sha256=evidence_hashes,
            evidence_complete=trial.evidence_complete,
            exception_type=(
                "AssertionError"
                if trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
                else _exception_type_from_output(stdout, stderr)
            ),
            raw_message=_last_output_line(stdout, stderr),
        ),
        test_case,
        agent3_manifest,
    )


def _candidate_file_for_result(
    run_dir: Path, result: NeutralExecutionResult
) -> Path:
    relative = Path(result.test_file)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("Candidate 파일 경로가 현재 Run 밖을 가리킵니다.")
    candidate_file = (
        run_dir / "candidates" / relative
        if relative.name == result.test_file
        else run_dir / relative
    ).resolve()
    try:
        candidate_file.relative_to(run_dir.resolve())
    except ValueError as exc:
        raise ValueError("Candidate 파일 경로가 현재 Run 밖을 가리킵니다.") from exc
    return candidate_file


def _candidate_execution_records(
    run_dir: Path,
    run_id: str,
    target_html: Path,
) -> tuple[
    list[tuple[NeutralExecutionResult, ProductTestCaseCandidate, dict[str, Any], Path]],
    list[AutomationExclusion],
    dict[str, Any] | None,
]:
    summary_file = run_dir / "agent3_run_summary.json"
    if not summary_file.is_file():
        result, test_case, manifest = _candidate_execution_record(
            run_dir, run_id, target_html
        )
        return [(result, test_case, manifest, run_dir)], [], None

    summary = _read_json_payload(summary_file)
    if (
        summary.get("run_id") != run_id
        or summary.get("stage") != "AGENT_3_RUN_SUMMARY"
    ):
        raise ValueError("Agent 3 실행 요약의 Run ID 또는 단계가 다릅니다.")
    if summary.get("target_file") != target_html.name:
        raise ValueError("Agent 3 실행 요약의 대상 파일명이 현재 검증 대상과 다릅니다.")
    if summary.get("target_sha256") != _sha256_file(target_html):
        raise ValueError("Agent 3 실행 이후 검증 대상 HTML이 변경됐습니다.")
    raw_entries = summary.get("entries")
    if not isinstance(raw_entries, list):
        raise ValueError("Agent 3 실행 결과 목록이 없습니다.")
    records = []
    for entry in raw_entries:
        if not isinstance(entry, dict) or entry.get("exit_code") != 0:
            continue
        relative_dir = entry.get("artifact_dir")
        if not isinstance(relative_dir, str):
            raise ValueError("Agent 3 산출물 경로가 없습니다.")
        relative_path = Path(relative_dir)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError("Agent 3 산출물 경로가 현재 Run 밖을 가리킵니다.")
        artifact_dir = (run_dir / relative_path).resolve()
        try:
            artifact_dir.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError("Agent 3 산출물 경로가 현재 Run 밖을 가리킵니다.") from exc
        if not artifact_dir.is_dir():
            raise ValueError("Agent 3 산출물 폴더를 찾을 수 없습니다.")
        manifest_file = artifact_dir / "agent3_manifest.json"
        _verify_sha256(
            manifest_file, entry.get("manifest_sha256"), "Agent 3 후보 Manifest"
        )
        result, test_case, manifest = _candidate_execution_record(
            run_dir, run_id, target_html, artifact_dir
        )
        records.append((result, test_case, manifest, artifact_dir))
    exclusions = [
        AutomationExclusion.model_validate(item)
        for item in summary.get("자동화_제외_TC", [])
    ]
    return records, exclusions, summary


def _current_candidate_execution_record(
    run_dir: Path,
    run_id: str,
    target_html: Path,
    test_case: ProductTestCaseCandidate,
    stored_result: NeutralExecutionResult,
    *,
    timeout_seconds: int,
    artifact_dir: Path | None = None,
) -> NeutralExecutionResult:
    """Reuse an identical candidate or recompile and retrial without a model call."""
    artifact_dir = artifact_dir or run_dir
    plan = _read_json_model(
        artifact_dir / "agent3_automation_plan.json", Agent3AutomationPlan
    )
    current_code = compile_automation_candidate(run_id, test_case, plan)
    stored_candidate_file = _candidate_file_for_result(run_dir, stored_result)
    if (
        stored_candidate_file.is_file()
        and _sha256_file(stored_candidate_file) == stored_result.test_sha256
        and stored_candidate_file.read_text(encoding="utf-8") == current_code
    ):
        return stored_result

    candidate_dir = run_dir / "validation_candidates"
    candidate_dir.mkdir(parents=True, exist_ok=True)
    candidate_file = candidate_dir / f"test_{test_case.tc_id.lower().replace('-', '_')}.py"
    _write_text_atomic(candidate_file, current_code)
    evidence_dir = run_dir / "validation_evidence" / test_case.tc_id
    trial = run_candidate_trial(
        candidate_file,
        target_html,
        evidence_dir,
        timeout_seconds=timeout_seconds,
    )
    trial_dir = run_dir / "validation_candidate_trials"
    trial_dir.mkdir(parents=True, exist_ok=True)
    trial_file = trial_dir / f"{test_case.tc_id}.json"
    _write_json(trial_file, trial.model_dump(mode="json"))
    if trial.outcome in {
        TrialOutcome.PASS,
        TrialOutcome.PRODUCT_MISMATCH_CANDIDATE,
    } and not trial.evidence_complete:
        raise ValueError("현재 컴파일러의 신규 자동화 후보 시험 증거가 완전하지 않습니다.")

    evidence_names = [trial.stdout_file, trial.stderr_file]
    if trial.screenshot_file:
        evidence_names.append(trial.screenshot_file)
    if trial.trace_file:
        evidence_names.append(trial.trace_file)
    evidence_files = [
        _safe_artifact_child(evidence_dir, name, "현재 Candidate 시험 증거")
        for name in evidence_names
    ]
    evidence_paths = [path.relative_to(run_dir).as_posix() for path in evidence_files]
    stdout = (evidence_dir / trial.stdout_file).read_text(encoding="utf-8")
    stderr = (evidence_dir / trial.stderr_file).read_text(encoding="utf-8")
    return NeutralExecutionResult(
        test_id=test_case.tc_id,
        source=ExecutionSource.NEW_AUTOMATION_CANDIDATE,
        requirement_ids=test_case.requirement_ids,
        status=_neutral_status_from_trial(trial.outcome),
        source_outcome=trial.outcome.value,
        exit_code=trial.exit_code,
        duration_ms=trial.duration_ms,
        test_file=candidate_file.relative_to(run_dir).as_posix(),
        test_sha256=_sha256_file(candidate_file),
        target_sha256=_sha256_file(target_html),
        reused=False,
        stdout_file=(evidence_dir / trial.stdout_file).relative_to(run_dir).as_posix(),
        stderr_file=(evidence_dir / trial.stderr_file).relative_to(run_dir).as_posix(),
        evidence_files=evidence_paths,
        evidence_sha256={
            relative: _sha256_file(path)
            for relative, path in zip(evidence_paths, evidence_files, strict=True)
        },
        evidence_complete=trial.evidence_complete,
        exception_type=(
            "AssertionError"
            if trial.outcome == TrialOutcome.PRODUCT_MISMATCH_CANDIDATE
            else _exception_type_from_output(stdout, stderr)
        ),
        raw_message=_last_output_line(stdout, stderr),
    )


_BASELINE_VIEWPORT_CONFTEST = """import pytest

@pytest.fixture(scope=\"session\")
def browser_context_args(browser_context_args):
    return {**browser_context_args, \"viewport\": {\"width\": 1600, \"height\": 900}}
"""


def run_existing_regression(
    spec: ExistingRegressionSpec,
    baseline_test_file: Path,
    target_html: Path,
    evidence_root: Path,
    *,
    timeout_seconds: int,
    source: ExecutionSource = ExecutionSource.EXISTING_REGRESSION,
) -> NeutralExecutionResult:
    """Run one allowlisted baseline test from a copied, neutral workspace."""
    baseline_test_file = baseline_test_file.resolve()
    target_html = target_html.resolve()
    evidence_dir = evidence_root / spec.tc_id
    evidence_dir.mkdir(parents=True, exist_ok=False)
    stdout_file = evidence_dir / "stdout.txt"
    stderr_file = evidence_dir / "stderr.txt"
    started = time.monotonic()
    exit_code: int | None = None
    stdout = ""
    stderr = ""
    status = NeutralExecutionStatus.EXECUTION_ERROR
    source_outcome = "PYTEST_ERROR"

    def redact(value: str, *paths: Path) -> str:
        redacted = value
        for path in paths:
            resolved = path.resolve()
            redacted = redacted.replace(str(resolved), "<LOCAL_PATH>")
            redacted = redacted.replace(resolved.as_uri(), "<LOCAL_FILE_URL>")
        return redacted

    with tempfile.TemporaryDirectory(prefix="qa-regression-") as temp_name:
        temp_root = Path(temp_name)
        tests_dir = temp_root / "tests"
        tests_dir.mkdir()
        isolated_test = tests_dir / "test_controller.py"
        isolated_target = temp_root / "virtual-controller.html"
        shutil.copy2(baseline_test_file, isolated_test)
        shutil.copy2(target_html, isolated_target)
        _write_text_atomic(tests_dir / "conftest.py", _BASELINE_VIEWPORT_CONFTEST)
        env = {
            name: os.environ[name]
            for name in _AGENT3_TRIAL_ENV_ALLOWLIST
            if name in os.environ
        }
        env["PYTHONUTF8"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        env["QA_TARGET_URL"] = isolated_target.as_uri()
        env["QA_EVIDENCE_DIR"] = str(evidence_dir.resolve())
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    f"tests/test_controller.py::{spec.test_function}",
                    "-q",
                    "--browser",
                    "chromium",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=temp_root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout_seconds,
                shell=False,
            )
            exit_code = completed.returncode
            stdout = redact(
                completed.stdout[-20000:],
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            stderr = redact(
                completed.stderr[-20000:],
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            combined = stdout + "\n" + stderr
            if exit_code == 0 and re.search(r"\bskipped\b", combined, re.IGNORECASE):
                status = NeutralExecutionStatus.SKIPPED
                source_outcome = "PYTEST_SKIPPED"
            elif exit_code == 0:
                status = NeutralExecutionStatus.PASSED
                source_outcome = "PYTEST_PASSED"
            elif "AssertionError" in combined:
                status = NeutralExecutionStatus.ASSERTION_FAILED
                source_outcome = "PYTEST_FAILED"
            else:
                status = NeutralExecutionStatus.EXECUTION_ERROR
                source_outcome = "PYTEST_ERROR"
        except subprocess.TimeoutExpired as exc:
            stdout = redact(
                (exc.stdout or "")[-20000:] if isinstance(exc.stdout, str) else "",
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            stderr = redact(
                (exc.stderr or "")[-20000:] if isinstance(exc.stderr, str) else "",
                temp_root,
                baseline_test_file,
                target_html,
                evidence_dir,
                Path.home(),
            )
            status = NeutralExecutionStatus.TIMEOUT
            source_outcome = "PYTEST_TIMEOUT"

    _write_text_atomic(stdout_file, stdout)
    _write_text_atomic(stderr_file, stderr)
    trace_file = evidence_dir / "trial-trace.zip"
    if trace_file.is_file():
        try:
            _redact_playwright_trace(
                trace_file,
                {
                    temp_root: "<REGRESSION_WORKSPACE>",
                    Path.home(): "<USER_HOME>",
                    baseline_test_file: "<REGRESSION_TEST_FILE>",
                    target_html: "<QA_TARGET_FILE>",
                    evidence_dir: "<EVIDENCE_DIR>",
                },
            )
        except zipfile.BadZipFile:
            # 쓰기가 중단되거나 손상된 Trace는 경로 정제를 보장할 수 없으므로
            # 신뢰 가능한 증거 목록에 포함하지 않는다.
            trace_file.unlink()
    evidence_items = [stdout_file, stderr_file]
    for name in ("trial-final.png", "trial-trace.zip"):
        optional_evidence = evidence_dir / name
        if optional_evidence.is_file():
            evidence_items.append(optional_evidence)
    evidence_paths = [
        path.relative_to(evidence_root.parent).as_posix() for path in evidence_items
    ]
    return NeutralExecutionResult(
        test_id=spec.tc_id,
        source=source,
        requirement_ids=list(spec.requirement_ids),
        status=status,
        source_outcome=source_outcome,
        exit_code=exit_code,
        duration_ms=int((time.monotonic() - started) * 1000),
        test_file=spec.automation_file or baseline_test_file.name,
        test_sha256=_sha256_file(baseline_test_file),
        target_sha256=_sha256_file(target_html),
        reused=False,
        stdout_file=evidence_paths[0],
        stderr_file=evidence_paths[1],
        evidence_files=evidence_paths,
        evidence_sha256={
            relative: _sha256_file(path)
            for relative, path in zip(evidence_paths, evidence_items, strict=True)
        },
        evidence_complete=(
            stdout_file.is_file()
            and stderr_file.is_file()
            and (
                spec.source != "APPROVED"
                or {"trial-final.png", "trial-trace.zip"}.issubset(
                    {path.name for path in evidence_items}
                )
            )
        ),
        exception_type=_exception_type_from_output(stdout, stderr),
        raw_message=_last_output_line(stdout, stderr),
    )


def _final_review_notes_for_validation(run_dir: Path) -> list[str]:
    """검증된 이전 단계의 최종 확인 사항만 수집합니다."""
    notes: list[str] = []
    checkpoint1_file = run_dir / "checkpoint1.json"
    if checkpoint1_file.is_file():
        checkpoint1 = _read_json_model(checkpoint1_file, Checkpoint1Result)
        notes.extend(f"CP1: {note}" for note in checkpoint1.final_review_notes)
    design_file = run_dir / "agent2_test_design.json"
    if design_file.is_file():
        design = _read_json_model(design_file, Agent2TestDesign)
        notes.extend(f"CP2: {note}" for note in design.final_review_notes)
    return list(dict.fromkeys(notes))


def _srs_revision_proposals_for_validation(
    run_dir: Path,
) -> list[SrsRevisionProposal]:
    design = _read_json_model(run_dir / "agent2_test_design.json", Agent2TestDesign)
    return list(design.srs_revision_proposals)


def _excluded_scope_for_validation(run_dir: Path) -> tuple[list[str], list[str]]:
    """검증된 Agent 2 인계에 보존된 실행 제외 범위를 읽습니다."""
    design = _read_json_model(run_dir / "agent2_test_design.json", Agent2TestDesign)
    return list(design.excluded_scope), list(design.excluded_information_gaps)


def _verified_existing_catalog_for_execution(
    run_dir: Path, approved_assets_root: Path
) -> tuple[tuple[ExistingRegressionSpec, ...], dict[str, Path]]:
    """Rehydrate the Agent 2 catalog snapshot and verify selected file sources."""

    manifest_file = run_dir / "agent2_manifest.json"
    if not manifest_file.is_file():
        return EXISTING_REGRESSION_CATALOG, {}
    manifest = _read_json_payload(manifest_file)
    snapshot_hash = manifest.get("approved_regression_catalog_sha256")
    if snapshot_hash is None:
        return EXISTING_REGRESSION_CATALOG, {}
    snapshot_file = run_dir / "approved_regression_catalog.json"
    _verify_sha256(snapshot_file, snapshot_hash, "승인 TC 카탈로그 Snapshot")
    catalog = _catalog_from_snapshot(_read_json_payload(snapshot_file))
    approved_assets_root = approved_assets_root.resolve()
    files: dict[str, Path] = {}
    for spec in catalog:
        if spec.source != "APPROVED":
            continue
        if not spec.automation_file or not spec.automation_sha256:
            raise ValueError(f"{spec.tc_id} 승인 자동화 Snapshot이 불완전합니다.")
        automation_file = (approved_assets_root / spec.automation_file).resolve()
        try:
            automation_file.relative_to(approved_assets_root)
        except ValueError as exc:
            raise ValueError(f"{spec.tc_id} 승인 자동화 경로가 자산 폴더 밖입니다.") from exc
        if (
            not automation_file.is_file()
            or _sha256_file(automation_file) != spec.automation_sha256
        ):
            raise ValueError(f"{spec.tc_id} 승인 자동화가 Agent 2 Snapshot과 다릅니다.")
        files[spec.tc_id] = automation_file
    return catalog, files


def run_validation_execution(args: argparse.Namespace) -> int:
    """Reuse the trusted new-candidate trial and run related baseline regressions."""
    run_dir = _resolve_run_dir(Path(args.runs_root), args.run_id)
    target_html = Path(args.target_html).resolve()
    baseline_test_file = (
        Path(args.baseline_tests).resolve()
        if args.baseline_tests
        else target_html.parent / "tests" / "test_controller.py"
    )
    approved_assets_root = Path(
        getattr(args, "approved_assets_root", DEFAULT_APPROVED_ASSETS_ROOT)
    ).resolve()
    if not target_html.is_file():
        raise ValueError("검증 대상 HTML을 찾을 수 없습니다.")
    if not baseline_test_file.is_file():
        raise ValueError("기준 제품의 기존 테스트 파일을 찾을 수 없습니다.")
    final_outputs = (
        run_dir / "validation_execution.json",
        run_dir / "validation_manifest.json",
        run_dir / "validation_error.json",
        run_dir / "validation_evidence",
        run_dir / "validation_candidates",
        run_dir / "validation_candidate_trial.json",
        run_dir / "validation_candidate_trials",
    )
    if any(path.exists() for path in final_outputs):
        raise ValueError("이 Run에는 이미 검증 실행 산출물이 있습니다. 기존 증거를 덮어쓸 수 없습니다.")

    target_before = _sha256_file(target_html)
    baseline_before = _sha256_file(baseline_test_file)
    try:
        existing_catalog, approved_automation_files = (
            _verified_existing_catalog_for_execution(
                run_dir, approved_assets_root
            )
        )
        existing_by_id = _existing_regression_by_id(existing_catalog)
        stored_records, automation_exclusions, run_summary = (
            _candidate_execution_records(run_dir, args.run_id, target_html)
        )
        candidate_results: list[NeutralExecutionResult] = []
        test_cases: list[ProductTestCaseCandidate] = []
        source_artifacts: list[dict[str, Any]] = []
        for stored_result, test_case, _, artifact_dir in stored_records:
            candidate_result = _current_candidate_execution_record(
                run_dir,
                args.run_id,
                target_html,
                test_case,
                stored_result,
                timeout_seconds=args.timeout,
                artifact_dir=artifact_dir,
            )
            candidate_results.append(candidate_result)
            test_cases.append(test_case)
            agent3_manifest_file = artifact_dir / "agent3_manifest.json"
            agent3_trial_file = artifact_dir / "agent3_trial.json"
            validation_trial_file = (
                run_dir / "validation_candidate_trials" / f"{test_case.tc_id}.json"
            )
            source_artifacts.append(
                {
                    "tc_id": test_case.tc_id,
                    "agent3_manifest_file": agent3_manifest_file.relative_to(run_dir).as_posix(),
                    "agent3_manifest_sha256": _sha256_file(agent3_manifest_file),
                    "agent3_trial_file": agent3_trial_file.relative_to(run_dir).as_posix(),
                    "agent3_trial_sha256": _sha256_file(agent3_trial_file),
                    "candidate_reused": candidate_result.reused,
                    "validation_candidate_sha256": candidate_result.test_sha256,
                    "validation_candidate_trial_file": (
                        validation_trial_file.relative_to(run_dir).as_posix()
                        if validation_trial_file.is_file()
                        else None
                    ),
                    "validation_candidate_trial_sha256": (
                        _sha256_file(validation_trial_file)
                        if validation_trial_file.is_file()
                        else None
                    ),
                }
            )
        design = _read_json_model(
            run_dir / "agent2_test_design.json", Agent2TestDesign
        )
        if design.existing_tc_comparison_completed:
            selected = [
                existing_by_id[item.tc_id]
                for item in design.related_existing_tests
            ]
        else:
            # Historical Run compatibility: older Agent 2 contracts did not
            # carry explicit existing-TC selections.
            requirement_ids = {
                requirement_id
                for test_case in test_cases
                for requirement_id in test_case.requirement_ids
            }
            selected = select_existing_regressions(requirement_ids, existing_catalog)
        evidence_root = run_dir / "validation_evidence"
        precheck = run_existing_regression(
            ENVIRONMENT_PRECHECK,
            baseline_test_file,
            target_html,
            evidence_root,
            timeout_seconds=args.timeout,
            source=ExecutionSource.ENVIRONMENT_PRECHECK,
        )
        regression_results: list[NeutralExecutionResult] = []
        blocked_reason: str | None = None
        if precheck.status == NeutralExecutionStatus.PASSED:
            for spec in selected:
                regression_test_file = approved_automation_files.get(
                    spec.tc_id, baseline_test_file
                )
                regression_results.append(
                    run_existing_regression(
                        spec,
                        regression_test_file,
                        target_html,
                        evidence_root,
                        timeout_seconds=args.timeout,
                    )
                )
            stage_status = ValidationStageStatus.COMPLETED
        else:
            stage_status = ValidationStageStatus.BLOCKED
            blocked_reason = "ENVIRONMENT_PRECHECK_NOT_PASSED"

        if _sha256_file(target_html) != target_before:
            raise RuntimeError("검증 실행 중 기준 제품 HTML이 변경됐습니다.")
        if _sha256_file(baseline_test_file) != baseline_before:
            raise RuntimeError("검증 실행 중 기준 제품 테스트 파일이 변경됐습니다.")
        for spec in selected:
            approved_file = approved_automation_files.get(spec.tc_id)
            if (
                approved_file is not None
                and _sha256_file(approved_file) != spec.automation_sha256
            ):
                raise RuntimeError(
                    f"검증 실행 중 승인 자동화 {spec.tc_id}가 변경됐습니다."
                )

        excluded_scope, excluded_information_gaps = _excluded_scope_for_validation(run_dir)
        bundle = ValidationExecutionBundle(
            run_id=args.run_id,
            status=stage_status,
            candidate_result=(candidate_results[0] if candidate_results else None),
            candidate_results=candidate_results,
            environment_precheck=precheck,
            selected_regression_ids=[item.tc_id for item in selected],
            regression_results=regression_results,
            blocked_reason=blocked_reason,
            excluded_scope=excluded_scope,
            excluded_information_gaps=excluded_information_gaps,
            final_review_notes=_final_review_notes_for_validation(run_dir),
            srs_revision_proposals=_srs_revision_proposals_for_validation(run_dir),
            automation_exclusions=automation_exclusions,
            created_at=datetime.now(timezone.utc).isoformat(),
        )
        execution_file = run_dir / "validation_execution.json"
        _write_json(execution_file, bundle.model_dump(mode="json", by_alias=True))
        agent3_manifest_file = run_dir / "agent3_manifest.json"
        agent3_trial_file = run_dir / "agent3_trial.json"
        _write_json(
            run_dir / "validation_manifest.json",
            {
                "contract_version": "1.3",
                "run_id": args.run_id,
                "stage": "VALIDATION_EXECUTION",
                "status": stage_status.value,
                "source_agent3_manifest_sha256": (
                    _sha256_file(agent3_manifest_file)
                    if agent3_manifest_file.is_file()
                    else None
                ),
                "source_agent3_trial_sha256": (
                    _sha256_file(agent3_trial_file)
                    if agent3_trial_file.is_file()
                    else None
                ),
                "source_agent3_run_summary_sha256": (
                    _sha256_file(run_dir / "agent3_run_summary.json")
                    if run_summary is not None
                    else None
                ),
                "source_agent3_artifacts": source_artifacts,
                "candidate_reused": (
                    candidate_results[0].reused if candidate_results else None
                ),
                "validation_candidate_sha256": (
                    candidate_results[0].test_sha256 if candidate_results else None
                ),
                "validation_candidate_trial_sha256": None,
                "baseline_test_file": baseline_test_file.name,
                "baseline_test_sha256": baseline_before,
                "approved_regression_catalog_sha256": (
                    _sha256_file(run_dir / "approved_regression_catalog.json")
                    if (run_dir / "approved_regression_catalog.json").is_file()
                    else None
                ),
                "approved_regression_assets": [
                    {
                        "tc_id": spec.tc_id,
                        "automation_file": spec.automation_file,
                        "automation_sha256": spec.automation_sha256,
                    }
                    for spec in selected
                    if spec.source == "APPROVED"
                ],
                "target_file": target_html.name,
                "target_sha256": target_before,
                "validation_execution_sha256": _sha256_file(execution_file),
                "project1_modified": False,
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
    except Exception as exc:
        _write_json(
            run_dir / "validation_error.json",
            {
                "run_id": args.run_id,
                "stage": "VALIDATION_EXECUTION",
                "error_type": type(exc).__name__,
                "message": str(exc),
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        raise

    print(f"Run ID: {args.run_id}")
    print(f"Validation execution: {stage_status.value}")
    print(
        "Candidate results: "
        + (", ".join(item.test_id for item in candidate_results) or "NONE")
    )
    print(f"Candidate trials reused: {sum(item.reused for item in candidate_results)}/{len(candidate_results)}")
    print(f"Automation exclusions: {len(automation_exclusions)}")
    print(f"Related regressions selected: {len(selected)}")
    print(f"Related regressions executed: {len(regression_results)}")
    print(f"Artifacts: {run_dir}")
    return 0 if stage_status == ValidationStageStatus.COMPLETED else 2

__all__ = [name for name in globals() if not name.startswith("__")]
