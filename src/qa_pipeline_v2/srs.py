from __future__ import annotations

import re
from pathlib import Path

from .models import SrsRequirement


_REQUIREMENT_ROW = re.compile(
    r"^\|\s*(REQ-[A-Z]+-\d{3})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*$"
)


def load_srs_requirements(path: Path) -> dict[str, SrsRequirement]:
    """Load requirement rows from the product SRS Markdown tables."""
    if not path.is_file():
        raise FileNotFoundError(f"SRS 파일을 찾을 수 없습니다: {path}")

    requirements: dict[str, SrsRequirement] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = _REQUIREMENT_ROW.match(line)
        if not match:
            continue
        requirement_id, statement, acceptance_criteria = match.groups()
        if requirement_id in requirements:
            raise ValueError(f"중복 Requirement ID: {requirement_id}")
        requirements[requirement_id] = SrsRequirement(
            requirement_id=requirement_id,
            statement=statement,
            acceptance_criteria=acceptance_criteria,
        )

    if not requirements:
        raise ValueError(f"SRS에서 Requirement를 찾지 못했습니다: {path}")
    return requirements


def render_srs_context(requirements: dict[str, SrsRequirement]) -> str:
    """Render only the machine-verifiable requirement rows for the model."""
    rows = ["ID | 요구사항 | 인수 기준"]
    for requirement_id in sorted(requirements):
        item = requirements[requirement_id]
        rows.append(
            f"{item.requirement_id} | {item.statement} | {item.acceptance_criteria}"
        )
    return "\n".join(rows)
