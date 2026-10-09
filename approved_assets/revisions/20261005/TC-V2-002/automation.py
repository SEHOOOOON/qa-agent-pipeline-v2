from __future__ import annotations

import os
import json
from time import monotonic
import re
from pathlib import Path

from playwright.sync_api import sync_playwright

# RUN_ID: LOCAL-TC-REFRESH-20261005
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


def _qa_values_equal(actual, expected):
    # JSON numbers may be int/float; booleans are not numbers in this contract.
    if type(actual) in (int, float) and type(expected) in (int, float):
        return actual == expected
    if type(actual) is not type(expected):
        return False
    if isinstance(actual, dict):
        return actual.keys() == expected.keys() and all(_qa_values_equal(actual[k], expected[k]) for k in actual)
    if isinstance(actual, list):
        return len(actual) == len(expected) and all(_qa_values_equal(a, b) for a, b in zip(actual, expected))
    return actual == expected

def _displayed_temperature(page, selector):
    text = page.locator(selector).inner_text()
    match = re.search(r'-?\d+(?:\.\d+)?', text)
    return float(match.group(0)) if match else None

def _temperature(page):
    return _displayed_temperature(page, '#det-temp-display')

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

_CONTROLLER_BUTTONS = {'status': {'OPERATION': '#det-power-on-btn', 'STOP': '#det-power-off-btn'}, 'mode': {'AUTO': '#det-mode-auto', 'COOL': '#det-mode-cool', 'HEAT': '#det-mode-heat', 'FAN': '#det-mode-fan', 'DRY': '#det-mode-dry'}, 'fanSpeed': {'LOW': '#det-fan-low', 'MED': '#det-fan-med', 'HIGH': '#det-fan-high', 'AUTO': '#det-fan-auto'}, 'locked': {True: '#det-lock-on-btn', False: '#det-lock-off-btn'}}

def _controller_ui_fields(page, device_id, location='card'):
    ui = _controller_snapshot(page, device_id)['ui']
    if location == 'panel':
        values = {}
        for field, choices in _CONTROLLER_BUTTONS.items():
            active = [value for value, selector in choices.items() if ui[field][selector]]
            values[field] = active[0] if len(active) == 1 else None
        temperature = re.search(r'-?\d+(?:\.\d+)?', ui['temperature'])
        values['setTemp'] = float(temperature.group()) if temperature else None
        return values
    classes = ui['card_classes']
    power = [value for css, value in (('state-run', 'OPERATION'), ('state-stop', 'STOP')) if css in classes]
    mode_labels = {'COOL': '냉방', 'HEAT': '난방', 'FAN': '송풍', 'DRY': '제습', 'AUTO': '자동'}
    mode = [value for value, label in mode_labels.items() if 'mode-' + value.lower() in classes and ui['card_values'][0].strip().endswith(label)]
    fan_text = ' '.join(ui['card_values'][1].split())
    fan = {'약풍': 'LOW', '중풍': 'MED', '강풍': 'HIGH', 'A 자동': 'AUTO', '자동': 'AUTO'}.get(fan_text)
    temperature = re.search(r'-?\d+(?:\.\d+)?', ui['card_values'][2])
    return {'status': power[0] if len(power) == 1 else None,
            'mode': mode[0] if len(mode) == 1 else None, 'fanSpeed': fan,
            'locked': 'locked' in classes and ui['card_locked'],
            'setTemp': float(temperature.group()) if temperature else None}

def _controller_snapshot(page, device_id):
    # One read-only observation turn. UI is read from DOM, never synthesized
    # from device fields. No product event or internal mutation is invoked.
    return page.evaluate("""({id, buttons}) => {
        const d = window.__vccs.devices.find(d => d.id === id);
        const state = d ? {status:d.status, mode:d.mode, fanSpeed:d.fanSpeed, setTemp:d.setTemp, locked:d.locked} : null;
        const card = document.querySelector('#device-card-' + id);
        const ui = Object.fromEntries(Object.entries(buttons).map(([field, choices]) =>
            [field, Object.fromEntries(Object.values(choices).map(selector => [selector, document.querySelector(selector).classList.contains('active')]))]));
        ui.temperature = document.querySelector('#det-temp-display').innerText;
        ui.temperature_enabled = ['#det-temp-up-btn','#det-temp-down-btn'].map(s => !document.querySelector(s).disabled);
        ui.card_classes = Array.from(card.classList).filter(c => c !== 'selected').sort();
        ui.card_values = ['.card-mode-text','.fan-speed-indicator','.card-set-temp'].map(s => card.querySelector(s).innerText);
        const lock = card.querySelector('.card-lock-indicator');
        ui.card_locked = getComputedStyle(lock).visibility !== 'hidden' && !!(lock.offsetWidth || lock.offsetHeight || lock.getClientRects().length);
        return {state, ui};
    }""", {'id': device_id, 'buttons': {field: list(choices.values()) for field, choices in _CONTROLLER_BUTTONS.items()}})

def _controller_baseline(page, device_id):
    selectors = [s for choices in _CONTROLLER_BUTTONS.values() for s in choices.values()]
    selectors += ['.btn-apply-cmd', '#det-temp-display', '#det-temp-limit-text', '#det-temp-up-btn', '#det-temp-down-btn', f'#device-card-{device_id}']
    if not page.evaluate('selectors => selectors.every(s => document.querySelectorAll(s).length === 1)', selectors):
        raise RuntimeError('controller interface is missing or ambiguous; no write started')
    snapshot = _controller_snapshot(page, device_id)
    state = snapshot['state']
    if not state or any(state.get(k) not in choices for k, choices in _CONTROLLER_BUTTONS.items()):
        raise RuntimeError('controller baseline is unavailable or unsupported')
    if type(state['locked']) is not bool or type(state['setTemp']) not in (int, float):
        raise RuntimeError('controller baseline has unsupported value types')
    if '°C' not in page.locator('#det-temp-limit-text').inner_text():
        raise RuntimeError('controller restoration currently requires Celsius')
    if page.evaluate("id => !!window.__vccs.devices.find(d => d.id === id).purify", device_id):
        raise RuntimeError('purification recovery is outside the five-control adapter')
    print('CONTROLLER_ORIGINAL: ' + repr(snapshot))
    return snapshot

def _restore_controller(page, device_id, original):
    target = original['state']
    # Re-select through the UI to discard an unapplied pending command.
    page.locator(f'#device-card-{device_id} .card-body-split').click()
    current = _controller_snapshot(page, device_id)['state']
    if _qa_values_equal(current, target):
        return
    if current['locked']:
        page.locator(_CONTROLLER_BUTTONS['locked'][False]).click()
        page.locator('.btn-apply-cmd').click()
        if _controller_snapshot(page, device_id)['state']['locked']:
            raise RuntimeError('controller unlock failed; restoration stopped')
    # FAN/DRY hide temperature. Only use a writable mode when temperature
    # really changed; no fixed initial values or direct internal writes.
    current = _controller_snapshot(page, device_id)['state']
    if current['setTemp'] != target['setTemp']:
        writable = target['mode'] if target['mode'] not in ('FAN', 'DRY') else 'COOL'
        page.locator(_CONTROLLER_BUTTONS['mode'][writable]).click()
        _set_temperature(page, float(target['setTemp']))
        page.locator('.btn-apply-cmd').click()
        if _controller_snapshot(page, device_id)['state']['setTemp'] != target['setTemp']:
            raise RuntimeError('controller temperature restoration failed')
    for field in ('status', 'mode', 'fanSpeed', 'locked'):
        page.locator(_CONTROLLER_BUTTONS[field][target[field]]).click()
    page.locator('.btn-apply-cmd').click()

def test_tc_cand_001():
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    mismatches = []
    test_completed = False
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)
        page = context.new_page()
        state_change_started = False
        preparation_started = False
        test_state_started = False
        try:
            page.goto(TARGET_URL, wait_until='domcontentloaded')
            page.evaluate('() => localStorage.clear()')
            page.reload(wait_until='domcontentloaded')
            page.wait_for_selector('body', timeout=5000)
            def observe_restoration():
                changes = []
                actual = {k: v for k, v in _controller_ui_fields(page, 1, 'card').items() if k in ['fanSpeed']}
                if not _qa_values_equal(actual, prepared_restore_baseline_0):
                    changes.append('ER-001' + ' state differs from pre-test observation')
                actual = page.evaluate('({id, fields}) => { const d = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(f => [f, d ? d[f] : null])); }', {'id': 1, 'fields': ['fanSpeed']})
                if not _qa_values_equal(actual, prepared_restore_baseline_1):
                    changes.append('ER-002' + ' state differs from pre-test observation')
                actual_controller = _controller_snapshot(page, 1)
                if not _qa_values_equal(actual_controller['state'], controller_prepared['state']) or any(not _qa_values_equal(actual_controller['ui'][k], controller_prepared['ui'][k]) for k in ('card_classes', 'card_values', 'card_locked')):
                    changes.append('controller applied state differs from prepared observation')
                return changes
            # ACT-001 PRECONDITION: 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 한다.
            page.locator('#device-card-1 .card-body-split').click()
            page.wait_for_function("() => window.__vccs.selectedUnitId === 1")
            controller_original = _controller_baseline(page, 1)
            restore_baseline_0 = {k: v for k, v in _controller_ui_fields(page, 1, 'card').items() if k in ['fanSpeed']}
            restore_baseline_1 = page.evaluate('({id, fields}) => { const d = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(f => [f, d ? d[f] : null])); }', {'id': 1, 'fields': ['fanSpeed']})
            prepared_restore_baseline_0 = restore_baseline_0
            prepared_restore_baseline_1 = restore_baseline_1
            controller_prepared = controller_original
            state_change_started = True
            preparation_started = True
            # ACT-002 PRECONDITION: 대상 장비를 선택하고 LOW 풍량을 적용한 뒤 장비 카드와 내부 fanSpeed가 LOW인지 확인한다.
            page.locator('#det-fan-low').click()
            state_change_started = True
            preparation_started = True
            # ACT-003 PRECONDITION: 대상 장비를 선택하고 LOW 풍량을 적용한 뒤 장비 카드와 내부 fanSpeed가 LOW인지 확인한다.
            page.locator('.btn-apply-cmd').click()
            prepared_restore_baseline_0 = {k: v for k, v in _controller_ui_fields(page, 1, 'card').items() if k in ['fanSpeed']}
            prepared_restore_baseline_1 = page.evaluate('({id, fields}) => { const d = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(f => [f, d ? d[f] : null])); }', {'id': 1, 'fields': ['fanSpeed']})
            controller_prepared = _controller_snapshot(page, 1)
            print('CONTROLLER_PREPARED: ' + repr(controller_prepared))
            precondition_values = {}
            def observe_preconditions():
                precondition_errors = []
                # PRECONDITION: 1 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 한다.
                precondition_actual = page.locator('#device-card-1 .card-body-split').is_visible()
                precondition_values[1] = precondition_actual
                if not (type(precondition_actual) is type(True) and precondition_actual == True):
                    precondition_errors.append('check 1 expected=' + repr(True) + ' actual=' + repr(precondition_actual))
                # PRECONDITION: 2 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 한다.
                precondition_actual = page.evaluate("id => { const d = window.__vccs?.devices?.find(item => item.id === id); return !!d && (['STOP', 'OPERATION', 'OFFLINE'].includes(d.status) && d.errorCode === null); }", 1)
                precondition_values[2] = precondition_actual
                if not (type(precondition_actual) is type(True) and precondition_actual == True):
                    precondition_errors.append('check 2 expected=' + repr(True) + ' actual=' + repr(precondition_actual))
                # PRECONDITION: 3 중앙 관제 패널에서 오류와 잠금이 없는 단일 장비를 대상으로 한다.
                precondition_actual = page.evaluate('id => { const d = window.__vccs?.devices?.find(item => item.id === id); return !!d && (d.locked === false); }', 1)
                precondition_values[3] = precondition_actual
                if not (type(precondition_actual) is type(True) and precondition_actual == True):
                    precondition_errors.append('check 3 expected=' + repr(True) + ' actual=' + repr(precondition_actual))
                # PRECONDITION: 4 대상 장비를 선택하고 LOW 풍량을 적용한 뒤 장비 카드와 내부 fanSpeed가 LOW인지 확인한다.
                precondition_actual = _controller_ui_fields(page, 1, 'card')['fanSpeed']
                precondition_values[4] = precondition_actual
                if not (type(precondition_actual) is type('LOW') and precondition_actual == 'LOW'):
                    precondition_errors.append('check 4 expected=' + repr('LOW') + ' actual=' + repr(precondition_actual))
                # PRECONDITION: 5 대상 장비를 선택하고 LOW 풍량을 적용한 뒤 장비 카드와 내부 fanSpeed가 LOW인지 확인한다.
                precondition_actual = page.evaluate('() => window.__vccs.devices[0]?.id === 1 ? window.__vccs.devices[0].fanSpeed : null')
                precondition_values[5] = precondition_actual
                if not (type(precondition_actual) is type('LOW') and precondition_actual == 'LOW'):
                    precondition_errors.append('check 5 expected=' + repr('LOW') + ' actual=' + repr(precondition_actual))
                return precondition_errors
            precondition_errors = _wait_for_observations(page, observe_preconditions)
            for check_index, observed_value in precondition_values.items():
                print('PRECONDITION_OBSERVED: ' + str(check_index) + ' ' + repr(observed_value))
            if precondition_errors:
                page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)
                raise AssertionError('PRECONDITION_NOT_MET: ' + ' | '.join(precondition_errors))
            print('PRECONDITIONS_VERIFIED: 5')
            # ACT-004 TEST: 중앙 관제 패널에서 대상 장비 카드를 선택한다.
            page.locator('#device-card-1 .card-body-split').click()
            page.wait_for_function("() => window.__vccs.selectedUnitId === 1")
            state_change_started = True
            test_state_started = True
            # ACT-005 TEST: 대상 장비의 MED 풍량을 선택한다.
            page.locator('#det-fan-med').click()
            state_change_started = True
            test_state_started = True
            # ACT-006 TEST: 선택한 풍량을 적용한다.
            page.locator('.btn-apply-cmd').click()
            observations = {}
            def observe():
                observations.clear()
                mismatches = []
                # EXPECTED_RESULT: ER-001
                mismatch_count_before = len(mismatches)
                actual = {k: v for k, v in _controller_ui_fields(page, 1, 'card').items() if k in ['fanSpeed']}
                if not _qa_values_equal(actual, {'fanSpeed': 'MED'}):
                    mismatches.append('ER-001' + ': controller UI=' + repr(actual))
                observation = {'version': 'assertion-observations-1.0', 'run_id': 'LOCAL-TC-REFRESH-20261005', 'tc_id': 'TC-CAND-001', 'target_device_id': 1, 'assertion': {'result_id': 'ER-001', 'observation_layer': 'UI', 'strategy': 'CONTROLLER_UI_FIELDS_EQUALS', 'selector': '#device-card-1', 'expected_number': None, 'expected_text': None, 'expected_value': None, 'expected_fields': [{'field_name': 'fanSpeed', 'expected_value': 'MED'}], 'after_action_id': 'ACT-006'}}
                observation.update(actual=actual, matched=len(mismatches) == mismatch_count_before)
                observations['ER-001'] = observation
                # EXPECTED_RESULT: ER-002
                mismatch_count_before = len(mismatches)
                actual = page.evaluate("({id, fields}) => { const device = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(field => [field, device ? device[field] : null])); }", {'id': 1, 'fields': ['fanSpeed']})
                if not _qa_values_equal(actual, {'fanSpeed': 'MED'}):
                    mismatches.append('ER-002' + f': internal device fields={actual}')
                observation = {'version': 'assertion-observations-1.0', 'run_id': 'LOCAL-TC-REFRESH-20261005', 'tc_id': 'TC-CAND-001', 'target_device_id': 1, 'assertion': {'result_id': 'ER-002', 'observation_layer': 'INTERNAL_STATE', 'strategy': 'INTERNAL_DEVICE_FIELDS_EQUALS', 'selector': 'window.__vccs.devices', 'expected_number': None, 'expected_text': None, 'expected_value': None, 'expected_fields': [{'field_name': 'fanSpeed', 'expected_value': 'MED'}], 'after_action_id': 'ACT-006'}}
                observation.update(actual=actual, matched=len(mismatches) == mismatch_count_before)
                observations['ER-002'] = observation
                return mismatches
            try:
                mismatches.extend(_wait_for_observations(page, observe))
            finally:
                for observation in observations.values():
                    print('QA_ASSERTION_OBSERVED: ' + json.dumps(observation, ensure_ascii=True, allow_nan=False))
            page.screenshot(path=str(EVIDENCE_DIR / 'trial-final.png'), full_page=True)
            print('QA_ASSERTIONS_COMPLETE: ' + json.dumps({'version': 'assertion-observations-1.0', 'run_id': 'LOCAL-TC-REFRESH-20261005', 'tc_id': 'TC-CAND-001'}))
            assert not mismatches, 'PRODUCT_MISMATCH: ' + ' | '.join(mismatches)
            test_completed = True
        finally:
            restore_mismatches = []
            try:
                if state_change_started:
                    changes = observe_restoration() if test_state_started else []
                    # ACT-007 RESTORE: 준비와 시험으로 바뀐 관제점 값을 준비 전 기록한 원래 상태로 복원하고 적용한다.
                    _restore_controller(page, 1, controller_original)
                    observations = {}
                    def observe():
                        observations.clear()
                        restore_mismatches = []
                        restored_controller = _controller_snapshot(page, 1)
                        if not _qa_values_equal(restored_controller, controller_original):
                            restore_mismatches.append('controller original=' + repr(controller_original) + ', actual=' + repr(restored_controller))
                        restore_actual = {k: v for k, v in _controller_ui_fields(page, 1, 'card').items() if k in ['fanSpeed']}
                        if not _qa_values_equal(restore_actual, restore_baseline_0):
                            restore_mismatches.append('#device-card-1' + f' baseline={restore_baseline_0}, actual={restore_actual}')
                        restore_actual = page.evaluate('({id, fields}) => { const d = window.__vccs.devices.find(d => d.id === id); return Object.fromEntries(fields.map(f => [f, d ? d[f] : null])); }', {'id': 1, 'fields': ['fanSpeed']})
                        if not _qa_values_equal(restore_actual, restore_baseline_1):
                            restore_mismatches.append('window.__vccs.devices' + f' baseline={restore_baseline_1}, actual={restore_actual}')
                        return restore_mismatches
                    try:
                        restore_mismatches.extend(_wait_for_observations(page, observe))
                    finally:
                        for observation in observations.values():
                            print('QA_ASSERTION_OBSERVED: ' + json.dumps(observation, ensure_ascii=True, allow_nan=False))
                    print('RESTORE_STATUS: ' + ('FAILED' if restore_mismatches else 'RESTORED'))
                else:
                    print('RESTORE_STATUS: NOT_STARTED')
            except Exception as restore_error:
                restore_mismatches.append(f'exception={type(restore_error).__name__}: {restore_error}')
            finally:
                try:
                    context.tracing.stop(path=str(EVIDENCE_DIR / 'trial-trace.zip'))
                finally:
                    try:
                        context.close()
                    finally:
                        browser.close()
            if restore_mismatches:
                restore_message = 'RESTORE_MISMATCH: ' + ' | '.join(restore_mismatches)
                print(restore_message)
                print('RESTORE_STATUS: FAILED')
                print('ENVIRONMENT_RETIRED: restoration failed; browser context closed')
                if test_completed:
                    raise AssertionError(restore_message)

            if not restore_mismatches and test_completed:
                print('RESTORE_CONFIRMATIONS_VERIFIED: ' + 'ER-001,ER-002')
