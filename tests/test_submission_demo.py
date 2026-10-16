"""Submission link behavior: static demo is explicit, live outage stays visible."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import threading
from urllib.parse import urlsplit
import pytest
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]

@pytest.mark.parametrize('mode', ['portfolio', 'live'])
def test_static_portfolio_demo_does_not_hide_live_connection_failure(mode):
    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT)))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            context.route('https://**/*', lambda r: r.abort())
            page = context.new_page()
            requests = []
            page.on('request', lambda r: requests.append((r.method, urlsplit(r.url).path)))
            origin = f'http://127.0.0.1:{server.server_port}'
            if mode == 'portfolio':
                page.goto(origin + '/project.html')
                expect(page.get_by_text('중앙제어 화면은 PC에서 체험해 주세요.', exact=False)).to_be_visible()
                page.get_by_role('link', name='저장 데모 보기 ↗').click()
                page.wait_for_function('qaLiveState.demoMode && qaLiveState.run !== null')
                assert 'mode=demo' in page.url
                page.locator('#tab-qa').click()
                page.locator('#agent-1-btn').click()
                expect(page.locator('#qa-live-title')).to_contain_text('데모')
                expect(page.locator('#qa-live-start-btn')).to_be_disabled()
                assert not [(method, path) for method, path in requests if path.startswith('/api/')]
            else:
                page.goto(origin + '/product_baseline/virtual-controller.html?mode=live')
                page.wait_for_function("document.getElementById('qa-live-connection').textContent.includes('연결 끊김')")
                assert page.evaluate('qaLiveState.demoMode') is False
                expect(page.locator('#qa-live-start-btn')).to_be_disabled()
                assert any(path.startswith('/api/') for _, path in requests)
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_public_power_observations_match_the_preserved_raw_log():
    import ast
    import hashlib
    import json
    folder = ROOT / 'evidence/submission-20261010'
    data = json.loads((folder / 'power-observations.json').read_text(encoding='utf-8'))
    source = folder / data['source_stdout']['file']
    assert hashlib.sha256(source.read_bytes()).hexdigest() == data['source_stdout']['sha256']
    lines = source.read_text(encoding='utf-8').splitlines()
    for key, prefix in [('before_setup', 'CONTROLLER_ORIGINAL:'), ('prepared', 'CONTROLLER_PREPARED:')]:
        assert data[key] == ast.literal_eval(next(x.split(': ', 1)[1] for x in lines if x.startswith(prefix)))
    observed = [json.loads(x.split(': ', 1)[1]) for x in lines if x.startswith('QA_ASSERTION_OBSERVED:')]
    assert data['test_assertions'] == observed
    assert len(observed) == 3
    assert all(x['run_id'] == data['run_id'] and x['tc_id'] == data['tc_id'] and x['target_device_id'] == data['target_device_id'] for x in observed)
    assert all(x['matched'] and x['actual'] == {'status': 'STOP'} for x in observed)
    assert data['before_setup']['state']['status'] == 'STOP'
    assert data['prepared']['state']['status'] == 'OPERATION'
    assert data['restoration']['after_values_recorded'] is None
    assert 'RESTORE_STATUS: RESTORED' in lines
    assert 'RESTORE_CONFIRMATIONS_VERIFIED: ' + ','.join(data['restoration']['verified_result_ids']) in lines
    assert data['kind'] == 'DERIVED_VIEW_OF_SAVED_EXECUTION_NOT_NEW_TEST'
    assert data['final_execution_used_saved_candidate_trial'] is True


def test_portfolio_marks_restoration_as_comparison_not_a_new_value_dump():
    html = (ROOT / 'project.html').read_text(encoding='utf-8')
    table = html.split('id="power-observations"', 1)[1].split('class="qa-run-ending"', 1)[0]
    assert '<th scope="row">준비 전</th><td>정지</td><td>정지</td><td>STOP</td>' in table
    assert '<th scope="row">운전 준비 후</th><td>운전</td><td>운전</td><td>OPERATION</td>' in table
    assert '<th scope="row">정지 적용 후</th><td>정지</td><td>정지</td><td>STOP</td>' in table
    assert '<th scope="row">복원 확인</th><td>비교 통과</td><td>비교 통과</td><td>비교 통과</td>' in table
    # 2026-10-16 사용자 결정: 포트폴리오 본문에는 상태·면책 문장을 두지 않는다(근거 파일 링크로 대신).
    for file in ('power-observations.json', 'power-trial-stdout.txt'):
        assert f'href="evidence/submission-20261010/{file}"' in table


def test_portfolio_separates_test_scope_from_common_tc_checks():
    html = (ROOT / 'project.html').read_text(encoding='utf-8')
    assert '정상·예외·경계값 등 시험 유형은 요청과 영향 범위에 맞춰 정합니다' in html
    assert '선택한 TC의 공통 검토 항목' in html
    assert 'TC의 근거·독립 실행 절차·기대결과·확인 시점은 공통으로 검토' in html
    assert '상태를 바꾸는 시험은 준비 전 상태로의 복원과 확인도 필요합니다' in html
    assert '위 항목을 모든 TC에 일괄 추가하지 않습니다' not in html
