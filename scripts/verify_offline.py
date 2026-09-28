"""API 없는 회귀검사. 모델 정확도나 Live 완료를 판정하지 않습니다."""
import argparse
from datetime import datetime
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]


def protected_hashes():
    names = subprocess.check_output(['git', 'ls-files', '-z', '--', 'src', 'product_baseline',
        'approved_assets', 'examples/results', 'docs/01_PRODUCT_SRS.md', 'project.html'], cwd=ROOT).decode('utf-8').strip('\0').split('\0')
    return {name: hashlib.sha256((ROOT / name).read_bytes()).hexdigest() for name in names if name}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--focus', action='store_true', help='분기·근거·보고·승인 검사만. 기본값은 전체 pytest입니다.')
    args = parser.parse_args()
    os.chdir(ROOT)
    sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'tests')]
    for key in tuple(os.environ):
        if key.startswith(('OPENAI_', 'NOTION_', 'SLACK_')):
            os.environ.pop(key, None)
    output = ROOT / 'runs/offline' / (datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:6])
    output.mkdir(parents=True, exist_ok=False)
    before = protected_hashes()
    blocked = []
    original_connect, original_connect_ex = socket.socket.connect, socket.socket.connect_ex
    def allow(address):
        if not isinstance(address, tuple):
            return
        host = str(address[0])
        try:
            local = ipaddress.ip_address(host).is_loopback
        except ValueError:
            local = host == 'localhost'
        if not local:
            blocked.append('external socket blocked')
            raise RuntimeError('Offline verification prohibits external Python connections')
    def connect(sock, address):
        allow(address)
        return original_connect(sock, address)
    def connect_ex(sock, address):
        allow(address)
        return original_connect_ex(sock, address)
    socket.socket.connect, socket.socket.connect_ex = connect, connect_ex
    # Browser assets may use CDNs; they are irrelevant to offline product checks.
    from playwright.sync_api import Browser
    original_context = Browser.new_context
    def local_context(browser, *a, **kw):
        context = original_context(browser, *a, **kw)
        from urllib.parse import urlsplit
        def route_request(route):
            url = urlsplit(route.request.url)
            if url.scheme in {'file', 'data', 'about'} or url.hostname in {'localhost', '127.0.0.1', '::1'}:
                route.continue_()
            else:
                route.abort()
        context.route('**/*', route_request)
        return context
    Browser.new_context = local_context
    import pytest
    options = ['-q', '--junitxml=' + str(output / 'tests.xml')]
    if args.focus:
        options += ['tests/test_grounding.py', 'tests/test_orchestration_execution.py',
                    'tests/test_agent4_reporting.py', 'tests/test_pipeline_ui.py']
    print('Offline tests: credentials removed; Python external sockets and browser external resources blocked.', flush=True)
    result = 1
    try:
        result = pytest.main(options)
    finally:
        socket.socket.connect, socket.socket.connect_ex = original_connect, original_connect_ex
        Browser.new_context = original_context
        after = protected_hashes()
        changed = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
        record = dict(mode='focus' if args.focus else 'full', pytest_exit=int(result), changed_protected_files=changed,
            hashes=after, blocked_python_connections=len(blocked), actual_model_evaluation=False,
            limitations='Regression fixtures/scripted reviewers, not model accuracy. Python socket guard is process-local; child processes inherit removed service credentials, not this socket patch. This is not an OS network sandbox.')
        (output / 'summary.json').write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        print('Offline evidence:', output, flush=True)
    return int(result) or bool(changed) or bool(blocked)


if __name__ == '__main__':
    raise SystemExit(main())
