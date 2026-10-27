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


def test_trimmed_portfolio_keeps_core_story_and_evidence():
    """2026-10-16 사용자 결정: 프로젝트1 소개는 한 페이지에 핵심만 남긴다.
    전원 정지 상세 표·TC 설계 기준 패널은 본문에서 뺐고, 원본 증거 파일은 그대로 둔다.
    2026-10-25: 대표 사례는 날짜 대신 '무엇이 바뀌나 → 필수 시험 → 실행 결과' 순서로 쓴다.
    2026-10-27: '정답'은 '필수 시험·기대 결과'로 바꿨다(완전한 정답처럼 읽히지 않게)."""
    html = (ROOT / 'project.html').read_text(encoding='utf-8')
    for text in ('분석 → 시험 설계 → 실행 → 보고 → 사람 판단', '기준을 정해도 AI의 해석은 달랐습니다',
                 '무엇이 바뀌나', '이번 평가의 필수 시험 5개', '확인한 범위와 남은 한계',
                 'AI에게 QA 기준을 알려 주는 일', '필수 시험 5개 중 3개만', '8번 모두 5개가 다 있었습니다'):
        assert text in html
    # 2026-10-22 portfolio review: the 10/15 run was a DRY_RUN report, and the
    # status box must not carry an older date than the runs it lists.
    for stale in ('Slack·Notion으로 전달했습니다', '2026.10.09 확인 자료', 'submission-20261010/request.example.json'):
        assert stale not in html
    assert 'class="pf-bar"' in html and 'aria-current="page">프로젝트1<' in html
    for file in ('power-observations.json', 'power-trial-stdout.txt'):
        assert (ROOT / 'evidence/submission-20261010' / file).is_file()
    for word in ('시험하지 못', '전체 실행 미완료', '아직 하지 않았습니다'):
        assert word not in html
