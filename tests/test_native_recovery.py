"""Shared native-test recovery: before preparation, actual UI/internal comparison."""
import json
from pathlib import Path
from types import SimpleNamespace
import pytest
from playwright.sync_api import sync_playwright
from pipeline_test_support import pipeline as p

ROOT=Path(__file__).resolve().parents[1]

def test_native_skip_without_recovery_is_not_pass_or_execution_error(tmp_path, monkeypatch):
    monkeypatch.setitem(p.run_existing_regression.__globals__, '_run_trial_subprocess',
        lambda *a, **kw: SimpleNamespace(returncode=0, stdout='1 skipped in 0.1s', stderr=''))
    row=p.run_existing_regression(p.EXISTING_REGRESSION_CATALOG[0], ROOT/'product_baseline/tests/test_controller.py',
        ROOT/'product_baseline/virtual-controller.html', tmp_path/'evidence', timeout_seconds=10)
    assert row.status.value=='SKIPPED'
    assert row.evidence_complete is False

def test_no_saved_contract_does_not_upgrade_historical_execution(tmp_path):
    catalog, _ = p._verified_existing_catalog_for_execution(tmp_path, ROOT/'approved_assets')
    assert all(s.recovery_contract is None for s in catalog)

@pytest.mark.parametrize('failure', [False, True])
def test_native_runner_does_not_report_missing_recovery_or_cleanup_failure_as_pass(tmp_path, monkeypatch, failure):
    def result(*args, **kwargs):
        return SimpleNamespace(returncode=1 if failure else 0,
            stdout='AssertionError: product\nRESTORE_STATUS: FAILED\n' if failure else '1 passed', stderr='')
    monkeypatch.setitem(p.run_existing_regression.__globals__, '_run_trial_subprocess', result)
    row=p.run_existing_regression(p.EXISTING_REGRESSION_CATALOG[0],ROOT/'product_baseline/tests/test_controller.py',
        ROOT/'product_baseline/virtual-controller.html',tmp_path/'evidence',timeout_seconds=10)
    assert row.status.value=='EXECUTION_ERROR'
    assert row.source_outcome==('RESTORE_MISMATCH' if failure else 'NATIVE_RECOVERY_EVIDENCE_MISSING')

@pytest.mark.parametrize('kind', ['pass', 'product_failure', 'unchanged', 'internal_fault', 'ui_fault'])
def test_native_recovery_keeps_original_and_failure_meaning(tmp_path, monkeypatch, kind):
    monkeypatch.setenv('QA_NATIVE_RECOVERY','1')
    monkeypatch.setenv('QA_TARGET_URL',(ROOT/'product_baseline/virtual-controller.html').as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR',str(tmp_path))
    namespace={'__file__':__file__}
    exec(p._BASELINE_VIEWPORT_CONFTEST+p._NATIVE_RECOVERY_PLUGIN,namespace)
    with sync_playwright() as pw:
        browser=pw.chromium.launch()
        context=browser.new_context(viewport={'width':1600,'height':900})
        context.route('**/*',lambda route: route.continue_() if route.request.url.startswith(('file:','data:')) else route.abort())
        page=context.new_page()
        page.goto((ROOT/'product_baseline/virtual-controller.html').as_uri(),wait_until='load')
        page.evaluate("""() => {const d=window.__vccs.devices[0]; Object.assign(d,{mode:'HEAT',setTemp:27,fanSpeed:'AUTO',locked:true}); window.__vccs.saveStateToLocalStorage();}""")
        def body(page):
            if kind!='unchanged':
                page.evaluate("""() => {for(const d of window.__vccs.devices) Object.assign(d,{status:'ERROR',mode:'COOL',setTemp:18,locked:true,fanSpeed:'HIGH'});window.__vccs.renderGrid();}""")
            if kind=='product_failure': raise AssertionError('PRODUCT_SENTINEL')
        if kind.endswith('fault'):
            restore=namespace['_native_restore']
            def corrupt(page, original):
                restore(page,original)
                if kind=='internal_fault': page.evaluate("() => window.__vccs.devices[15].locked=true")
                else: page.locator('#device-card-16').evaluate("e=>e.classList.add('locked')")
            namespace['_native_restore']=corrupt
        item=SimpleNamespace(funcargs={'page':page},name='native-fixture',obj=body,_fixtureinfo=SimpleNamespace(argnames=['page']))
        if kind.endswith('fault'):
            with pytest.raises(RuntimeError,match='RESTORE_MISMATCH'): namespace['pytest_pyfunc_call'](item)
            assert not context.pages
        elif kind=='product_failure':
            with pytest.raises(AssertionError,match='PRODUCT_SENTINEL'): namespace['pytest_pyfunc_call'](item)
        else: assert namespace['pytest_pyfunc_call'](item) is True
        record=json.loads((tmp_path/'native-restoration.json').read_text(encoding='utf-8'))
        assert len(record['original']['devices'])==16
        assert record['original']['devices'][0]['setTemp']==27
        if kind.endswith('fault'): assert record['status']=='FAILED'
        else:
            assert record['original']==record['restored']
            assert record['status']==('UNCHANGED' if kind=='unchanged' else 'RESTORED')
        browser.close()
