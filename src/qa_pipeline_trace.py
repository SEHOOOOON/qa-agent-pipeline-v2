"""Playwright Trace에서 알려진 로컬 경로를 제거하는 공통 보안 유틸리티."""

from __future__ import annotations

import json
import os
import tempfile
import zipfile
from pathlib import Path


def redact_playwright_trace(
    trace_file: Path,
    redactions: dict[Path, str],
) -> None:
    """ZIP 구조를 유지하면서 알려진 로컬 경로 표현을 치환한다."""

    replacements: set[tuple[bytes, bytes]] = set()
    for path, placeholder in redactions.items():
        resolved = path.resolve()
        values = {
            str(resolved),
            resolved.as_posix(),
            resolved.as_uri(),
        }
        for value in tuple(values):
            values.add(json.dumps(value, ensure_ascii=False)[1:-1])
            values.add(json.dumps(value, ensure_ascii=True)[1:-1])
        for value in values:
            replacements.add((value.encode("utf-8"), placeholder.encode("utf-8")))

    ordered_replacements = sorted(replacements, key=lambda item: len(item[0]), reverse=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{trace_file.stem}-",
        suffix=".zip",
        dir=trace_file.parent,
        delete=False,
    ) as temp_handle:
        temp_trace = Path(temp_handle.name)
    try:
        with zipfile.ZipFile(trace_file, "r") as source, zipfile.ZipFile(
            temp_trace, "w"
        ) as destination:
            for info in source.infolist():
                payload = source.read(info.filename)
                for raw_value, placeholder in ordered_replacements:
                    payload = payload.replace(raw_value, placeholder)
                destination.writestr(info, payload)
        os.replace(temp_trace, trace_file)
    finally:
        if temp_trace.exists():
            temp_trace.unlink()
