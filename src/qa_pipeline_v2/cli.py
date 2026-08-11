from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from .agent1 import Agent1Error, OpenAIAgent1
from .checkpoint1 import evaluate_checkpoint1
from .models import ChangeRequest, CheckStatus
from .srs import load_srs_requirements


DEFAULT_SRS = Path("docs") / "01_PRODUCT_SRS.md"
DEFAULT_RUNS_ROOT = Path("runs")


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


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"RUN-{stamp}-{uuid.uuid4().hex[:6].upper()}"


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def run_agent1(args: argparse.Namespace) -> int:
    request = _read_request(Path(args.request).resolve())
    requirements = load_srs_requirements(Path(args.srs).resolve())
    agent = OpenAIAgent1(model=args.model)
    run_id = _new_run_id()
    run_dir = Path(args.runs_root).resolve() / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    _write_json(run_dir / "request.json", request.model_dump(mode="json"))
    try:
        response = agent.analyze(request, requirements)
        checkpoint = evaluate_checkpoint1(request, response.analysis, requirements)

        _write_json(
            run_dir / "agent1_change_analysis.json",
            response.analysis.model_dump(mode="json"),
        )
        _write_json(
            run_dir / "checkpoint1.json", checkpoint.model_dump(mode="json")
        )
        _write_json(
            run_dir / "run_manifest.json",
            {
                "run_id": run_id,
                "stage": "AGENT_1_CP1",
                "status": checkpoint.status.value,
                "model": response.model,
                "response_id": response.response_id,
                "usage": response.usage,
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
    print(f"결과 위치: {run_dir}")
    return 0 if checkpoint.status == CheckStatus.PASS else 2


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
    return parser


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.handler(args)
    except (OSError, ValueError, Agent1Error) as exc:
        parser.error(str(exc))
    return 1

