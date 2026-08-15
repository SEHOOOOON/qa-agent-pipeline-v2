from __future__ import annotations

import os
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

# RUN_ID: RUN-20260813-125229-31EB5F
# SOURCE_TC: TC-CAND-003
TARGET_URL = os.environ['QA_TARGET_URL']
EVIDENCE_DIR = Path(os.environ['QA_EVIDENCE_DIR'])

def _temperature(page):
    text = page.locator('#det-temp-display').inner_text()
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None

def _set_temperature(page, target):
    for _ in range(40):
        current = _temperature(page)
        if current == target:
            return
        selector = '#det-temp-up-btn' if current < target else '#det-temp-down-btn'
        page.locator(selector).click()
    raise RuntimeError(f'temperature setup failed: target={target}, actual={_temperature(page)}')

def _request_temperature(page, target):
    for _ in range(40):
        before = _temperature(page)
        if before == target:
            return
        selector = '#det-temp-up-btn' if before < target else '#det-temp-down-btn'
        page.locator(selector).click()
        after = _temperature(page)
        if after == before:
            return
    raise RuntimeError(f'temperature request did not settle: target={target}, actual={_temperature(page)}')

def test_tc_cand_003():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    mismatches = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        try:
            page.goto(TARGET_URL, wait_until='domcontentloaded')
            page.evaluate('() => localStorage.clear()')
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('#device-card-1', timeout=5000)
            # ACT-001 PRECONDITION: 중앙 명령이 허용되는 역할로 제어 패널에 접근한다.
            page.locator('#device-card-1 .card-body-split').click()
            page.wait_for_function("() => window.__vccs.selectedUnitId === 1")
            # ACT-002 PRECONDITION: 선택된 허용 장비는 AUTO 모드이고 설정 온도는 18°C이다.
            page.locator('#det-mode-auto').click()
            # ACT-003 PRECONDITION: 선택된 허용 장비는 AUTO 모드이고 설정 온도는 18°C이다.
            _set_temperature(page, 18.0)
            # ACT-004 PRECONDITION: 선택 장비는 중앙 제어 패널의 적용 대상이다.
            page.locator('.btn-apply-cmd').click()
            page.wait_for_timeout(100)
            # ACT-005 TEST: 제어 패널에서 대기 설정 온도를 17°C로 지정한다.
            _request_temperature(page, 17.0)
            # ACT-006 TEST: 제어 패널을 통해 선택된 허용 장비에 대기값을 일괄 적용한다.
            page.locator('.btn-apply-cmd').click()
            page.wait_for_timeout(100)
            # EXPECTED_RESULT: ER-005
            actual = _temperature(page)
            if actual != 18.0:
                mismatches.append('ER-005' + f': UI temperature={actual}')
            # EXPECTED_RESULT: ER-006
            actual = page.evaluate("id => window.__vccs.devices.find(d => d.id === id).setTemp", 1)
            if actual != 18.0:
                mismatches.append('ER-006' + f': internal setTemp={actual}')
            # EXPECTED_RESULT: ER-007
            toast = page.locator('#global-toast')
            toast_text = toast.inner_text().strip().lower()
            if 'show' not in (toast.get_attribute('class') or '').split():
                mismatches.append('ER-007' + ': toast not visible')
            elif not any(term in toast_text for term in ('block', 'blocked', 'blocking', 'reject', 'denied', 'invalid', 'out of range', 'failed', '차단', '범위', '초과', '거부', '실패', '허용되지', '할 수 없')):
                mismatches.append('ER-007' + f': toast does not indicate blocking: {toast_text}')
            page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)
            assert not mismatches, 'PRODUCT_MISMATCH: ' + ' | '.join(mismatches)
        finally:
            context.tracing.stop(path=str(EVIDENCE_DIR / 'trial-trace.zip'))
            context.close()
            browser.close()
