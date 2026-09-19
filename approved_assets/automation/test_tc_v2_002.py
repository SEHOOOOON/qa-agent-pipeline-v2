from __future__ import annotations

import os
from time import monotonic
from pathlib import Path

from playwright.sync_api import sync_playwright

# RUN_ID: RUN-20260918-110541-4102E0
# SOURCE_TC: TC-CAND-001
TARGET_URL = os.environ['QA_TARGET_URL']
EVIDENCE_DIR = Path(os.environ['QA_EVIDENCE_DIR'])

def _wait_for_observations(page, observe):
    deadline = monotonic() + 2.0
    while True:
        errors = observe()
        if not errors or monotonic() >= deadline:
            return errors
        page.wait_for_timeout(50)

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
            restore_baseline_1 = page.evaluate("({id, fields}) => { const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }", {'id': 1, 'fields': ['fanSpeed']})
            precondition_values = {}
            def observe_preconditions():
                precondition_errors = []
                # PRECONDITION: 1 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다.
                precondition_actual = page.evaluate("id => { const d = window.__vccs?.devices?.find(item => item.id === id); return !!d && (['STOP', 'OPERATION', 'OFFLINE'].includes(d.status) && d.errorCode === null); }", 1)
                precondition_values[1] = precondition_actual
                if not (type(precondition_actual) is type(True) and precondition_actual == True):
                    precondition_errors.append('check 1 expected=' + repr(True) + ' actual=' + repr(precondition_actual))
                # PRECONDITION: 2 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 합니다.
                precondition_actual = page.evaluate('id => { const d = window.__vccs?.devices?.find(item => item.id === id); return !!d && (d.locked === false); }', 1)
                precondition_values[2] = precondition_actual
                if not (type(precondition_actual) is type(True) and precondition_actual == True):
                    precondition_errors.append('check 2 expected=' + repr(True) + ' actual=' + repr(precondition_actual))
                # PRECONDITION: 3 첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작합니다.
                precondition_actual = page.evaluate('() => window.__vccs.devices[0]?.id === 1 ? window.__vccs.devices[0].fanSpeed : null')
                precondition_values[3] = precondition_actual
                if not (type(precondition_actual) is type('LOW') and precondition_actual == 'LOW'):
                    precondition_errors.append('check 3 expected=' + repr('LOW') + ' actual=' + repr(precondition_actual))
                return precondition_errors
            precondition_errors = _wait_for_observations(page, observe_preconditions)
            for check_index, observed_value in precondition_values.items():
                print('PRECONDITION_OBSERVED: ' + str(check_index) + ' ' + repr(observed_value))
            if precondition_errors:
                page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)
                raise AssertionError('PRECONDITION_NOT_MET: ' + ' | '.join(precondition_errors))
            print('PRECONDITIONS_VERIFIED: 3')
            # ACT-001 TEST: 중앙 관제 패널에서 시험할 대상 장비 카드를 선택한다.
            page.locator('#device-card-1 .card-body-split').click()
            page.wait_for_function("() => window.__vccs.selectedUnitId === 1")
            # ACT-002 TEST: 선택한 대상 장비의 풍량을 MED로 선택한다.
            page.locator('#det-fan-med').click()
            # ACT-003 TEST: 선택한 대상 장비에 선택한 MED 풍량을 적용한다.
            page.locator('.btn-apply-cmd').click()
            def observe():
                mismatches = []
                # EXPECTED_RESULT: ER-001
                actual = page.locator('#device-card-1').inner_text()
                if '중풍' not in actual:
                    mismatches.append('ER-001' + f': expected text missing: {actual}')
                # EXPECTED_RESULT: ER-002
                actual = page.evaluate("({id, fields}) => { const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }", {'id': 1, 'fields': ['fanSpeed']})
                if actual != {'fanSpeed': 'MED'}:
                    mismatches.append('ER-002' + f': internal device fields={actual}')
                return mismatches
            mismatches.extend(_wait_for_observations(page, observe))
            page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)
            assert not mismatches, 'PRODUCT_MISMATCH: ' + ' | '.join(mismatches)
            test_completed = True
        finally:
            restore_mismatches = []
            try:
                # ACT-004 RESTORE: 시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용합니다.
                page.locator('#det-fan-low').click()
                # ACT-005 RESTORE: 시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용합니다.
                page.locator('.btn-apply-cmd').click()
                def observe():
                    restore_mismatches = []
                    restore_actual = page.locator('#device-card-1').inner_text()
                    if restore_actual != restore_baseline_0:
                        restore_mismatches.append('#device-card-1' + f' baseline={restore_baseline_0}, actual={restore_actual}')
                    restore_actual = page.evaluate("({id, fields}) => { const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }", {'id': 1, 'fields': ['fanSpeed']})
                    if restore_actual != restore_baseline_1:
                        restore_mismatches.append('window.__vccs.devices' + f' baseline={restore_baseline_1}, actual={restore_actual}')
                    return restore_mismatches
                restore_mismatches.extend(_wait_for_observations(page, observe))
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

            if not restore_mismatches and test_completed:
                print('RESTORE_CONFIRMATIONS_VERIFIED: ' + 'ER-001,ER-002')
