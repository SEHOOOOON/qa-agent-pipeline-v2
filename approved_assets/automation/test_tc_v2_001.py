from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import sync_playwright

# RUN_ID: RUN-20260829-054330-A18942
# SOURCE_TC: TC-CAND-001
TARGET_URL = os.environ['QA_TARGET_URL']
EVIDENCE_DIR = Path(os.environ['QA_EVIDENCE_DIR'])

def test_tc_cand_001():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    mismatches = []
    test_completed = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        try:
            page.goto(TARGET_URL, wait_until='domcontentloaded')
            page.evaluate('() => localStorage.clear()')
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('body', timeout=5000)
            restore_baseline_0 = page.locator('#device-card-1').inner_text()
            # ACT-001 TEST: 중앙 관제 패널에서 대상 장비에 HIGH 풍량을 선택하고 적용한다.
            page.locator('#device-card-1 .card-body-split').click()
            page.wait_for_function("() => window.__vccs.selectedUnitId === 1")
            # ACT-002 TEST: 중앙 관제 패널에서 대상 장비에 HIGH 풍량을 선택하고 적용한다.
            page.locator('#det-fan-high').click()
            # ACT-003 TEST: 중앙 관제 패널에서 대상 장비에 HIGH 풍량을 선택하고 적용한다.
            page.locator('.btn-apply-cmd').click()
            page.wait_for_timeout(100)
            # EXPECTED_RESULT: ER-001
            actual = page.locator('#device-card-1').inner_text()
            if '강풍' not in actual:
                mismatches.append('ER-001' + f': expected text missing: {actual}')
            # EXPECTED_RESULT: ER-002
            actual = page.evaluate("({id, fields}) => { const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }", {'id': 1, 'fields': ['fanSpeed']})
            if actual != {'fanSpeed': 'HIGH'}:
                mismatches.append('ER-002' + f': internal device fields={actual}')
            page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)
            assert not mismatches, 'PRODUCT_MISMATCH: ' + ' | '.join(mismatches)
            test_completed = True
        finally:
            restore_mismatches = []
            try:
                # ACT-004 RESTORE: 시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다.
                page.locator('#det-fan-low').click()
                # ACT-005 RESTORE: 시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다.
                page.locator('.btn-apply-cmd').click()
                page.wait_for_timeout(100)
                restore_actual = page.locator('#device-card-1').inner_text()
                if restore_actual != restore_baseline_0:
                    restore_mismatches.append('#device-card-1' + f' baseline={restore_baseline_0}, actual={restore_actual}')
            except Exception as restore_error:
                restore_mismatches.append(f'exception={type(restore_error).__name__}: {restore_error}')
            finally:
                context.tracing.stop(path=str(EVIDENCE_DIR / 'trial-trace.zip'))
                context.close()
                browser.close()
            if restore_mismatches:
                restore_message = 'RESTORE_MISMATCH: ' + ' | '.join(restore_mismatches)
                print(restore_message)
                if test_completed:
                    raise AssertionError(restore_message)
