from pathlib import Path

from qa_pipeline_v2.srs import load_srs_requirements, render_srs_context


REPO_ROOT = Path(__file__).resolve().parents[1]


def test_loads_product_requirements_from_markdown() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    assert len(requirements) >= 20
    assert requirements["REQ-TEMP-001"].statement == "섭씨 설정 범위는 16~30°C여야 합니다."
    assert "범위 밖 요청" in requirements["REQ-TEMP-001"].acceptance_criteria


def test_rendered_context_contains_ids_and_acceptance_criteria() -> None:
    requirements = load_srs_requirements(REPO_ROOT / "docs" / "01_PRODUCT_SRS.md")

    context = render_srs_context(requirements)

    assert "REQ-LOCK-001" in context
    assert "상태 불변과 차단 로그" in context

