# conftest.py
# pytest-html v4 compatible configuration for 가상 관제 시스템 QA Test Suite
# ※ Screenshot·Trace·상태 Snapshot 수집 기능은 향후 고도화 대상으로 관리합니다.

import pytest
import json
import re
import uuid
import html
from datetime import datetime
from pathlib import Path
from test_controller import SimulatorTimeoutError

# 프로젝트 루트 기준 reports 경로 (tests/ 폴더 한 단계 위)
REPORTS_DIR = Path(__file__).parent.parent / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
QA_RESULTS_PATH = REPORTS_DIR / "qa_results.json"

# TC-ENV-000은 사전 환경 검증(Pre-check) 단계로,
# 비즈니스 테스트 케이스가 아니므로 HTML 요약 카운트에서 제외합니다.
EXCLUDED_FROM_SUMMARY = {"TC-ENV-000"}

# Global test results collector
qa_results = []
session_run_id = ""

def pytest_sessionstart(session):
    global session_run_id
    qa_results.clear()
    session_run_id = str(uuid.uuid4())

# -- 1. Viewport fixture -------------------------------------------------------
@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    """가상 관제 시스템 dashboard 4-column grid optimal viewport (1600x900)."""
    return {
        **browser_context_args,
        "viewport": {"width": 1600, "height": 900},
    }

# -- 2. Extract docstring & Classify Failure -> report attributes ----------------
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()
    
    if report.when == "call":
        # Description
        doc = getattr(item.function, "__doc__", "") or ""
        first_line = next((line.strip() for line in doc.splitlines() if line.strip()), "")
        report.description = first_line
        
        # Failure Classification
        report.failure_reason = ""
        if report.outcome == "skipped":
            if "기획" in str(report.longrepr) or "요구사항" in str(report.longrepr):
                report.failure_reason = "기획·요구사항 확인 필요"
            else:
                report.failure_reason = "조건 부족으로 미실행"
        elif report.failed and call.excinfo:
            exc_type = call.excinfo.type
            if exc_type.__name__ == 'SimulatorTimeoutError':
                report.failure_reason = "테스트 환경·시뮬레이터 문제"
            elif exc_type is AssertionError:
                report.failure_reason = "제품 결함 후보"
            else:
                report.failure_reason = "자동화 코드 문제"

        # TC ID 추출: [TC-xxx-000] 형식 기준 (TC-ENV, TC-MODE, TC-LOCK, TC-ERR, TC-INT, TC-TEMP, TC-PIPE 등)
        tc_match = re.search(r'\[(TC-[^\]]+)\]', report.description)
        tc_id = tc_match.group(1) if tc_match else "UNKNOWN_TC"
        
        # Save to global array for JSON export
        qa_results.append({
            "run_id": session_run_id,
            "tc_id": tc_id,
            "test_id": item.name,
            "description": report.description,
            "result": report.outcome,
            "failure_reason": report.failure_reason,
            "executed_at": datetime.now().isoformat(),
            "duration": round(report.duration, 2),
            "evidence_path": ""
        })

def pytest_sessionfinish(session, exitstatus):
    with open(QA_RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(qa_results, f, ensure_ascii=False, indent=2)
    print(f"\n[OK] QA 결과 저장 완료: {QA_RESULTS_PATH}")

# -- 2.5 Fix pytest-html Summary Count (TC-ENV-000 제외) -----------------------
def pytest_html_results_summary(prefix, summary, postfix):
    """
    TC-ENV-000(사전 환경 검증)은 비즈니스 TC가 아닌 Pre-check 단계입니다.
    실제 비즈니스 TC 수(EXCLUDED_FROM_SUMMARY 제외)를 prefix에 별도 표기합니다.
    pytest-html 4.x에서는 summary 리스트 교체가 동작하지 않으므로,
    prefix에 안내 문구를 추가하는 방식으로 구현합니다.
    """
    business_tc_count = sum(
        1 for r in qa_results
        if r.get("tc_id") not in EXCLUDED_FROM_SUMMARY
    )
    env_check_count = len(qa_results) - business_tc_count
    if env_check_count > 0:
        prefix.extend([
            f'<p class="summary-note" style="color:#8b949e; font-size:0.9em;">'
            f'※ 전체 {len(qa_results)}건 중 사전 환경 검증(Pre-check) {env_check_count}건 제외 — '
            f'비즈니스 TC {business_tc_count}건 기준으로 결과를 분석합니다.'
            f'</p>'
        ])

# -- 3. Add Columns headers -----------------------------------------
def pytest_html_results_table_header(cells):
    cells.insert(2, '<th class="sortable" data-column-type="description">Description</th>')
    cells.insert(3, '<th class="sortable" data-column-type="failure_reason">Failure Classification</th>')

# -- 4. Add Columns cell per row ------------------------------------
def pytest_html_results_table_row(report, cells):
    description = getattr(report, "description", "")
    failure_reason = getattr(report, "failure_reason", "")
    
    # 실패 분류에 따른 색상 스타일링
    color_style = ""
    if "제품 결함 후보" in failure_reason:
        color_style = "color: #f85149; font-weight: bold;" # Red
    elif "기획" in failure_reason:
        color_style = "color: #db6d28; font-weight: bold;" # Orange
    elif "환경" in failure_reason or "자동화" in failure_reason:
        color_style = "color: #d29922; font-weight: bold;" # Yellow
    elif "조건 부족" in failure_reason:
        color_style = "color: #8b949e; font-style: italic;" # Gray
    
    safe_description = html.escape(description)
    safe_failure_reason = html.escape(failure_reason)
    cells.insert(2, f'<td class="col-description">{safe_description}</td>')
    cells.insert(3, f'<td class="col-failure-reason" style="{color_style}">{safe_failure_reason}</td>')

# -- 5. Report title -----------------------------------------------------------
def pytest_html_report_title(report):
    report.title = "Virtual Central Control System — QA Automation Report"
