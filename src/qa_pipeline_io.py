"""파이프라인 산출물의 원자적 기록과 SHA-256 검증 공통 함수."""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from pathlib import Path
from typing import Any


_WINDOWS_PATH_LIMIT = 260 if os.name == "nt" else None


def _check_output_paths(*paths: Path) -> None:
    """Check output and same-directory atomic temporary names before paid work."""
    if _WINDOWS_PATH_LIMIT is None:
        return
    for path in paths:
        absolute = path.resolve()
        temporary = absolute.with_name("." + "0" * 32 + ".tmp")
        if any(len(str(item).encode("utf-16-le")) // 2 >= _WINDOWS_PATH_LIMIT
               for item in (absolute, temporary)):
            raise ValueError(
                "Windows 실행 산출물 경로가 너무 깁니다. "
                "--runs-root를 저장소 바로 아래의 짧은 폴더로 지정하세요. "
                "기존 Run은 덮어쓰지 않으며 자동 이동하지 않습니다."
            )


def _write_text_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Keep the sibling name short: repeating the target name can exceed Windows'
    # path limit even when the final artifact itself fits. Same-directory replace
    # still preserves atomic publication and the original on write failure.
    temp_path = path.with_name(f".{uuid.uuid4().hex}.tmp")
    try:
        temp_path.write_text(text, encoding="utf-8")
        os.replace(temp_path, path)
    finally:
        if temp_path.exists():
            temp_path.unlink()


def _write_json(path: Path, payload: Any) -> None:
    _write_text_atomic(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_sha256(path: Path, expected: Any, label: str) -> None:
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise ValueError(f"run_manifest의 {label} SHA-256 값이 올바르지 않습니다.")
    actual = _sha256_file(path)
    if actual != expected:
        raise ValueError(f"{label} 파일이 Agent 1 실행 후 변경되어 Agent 2를 차단했습니다.")


__all__ = [name for name in globals() if not name.startswith("__")]
