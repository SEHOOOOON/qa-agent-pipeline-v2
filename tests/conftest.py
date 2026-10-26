import os
import stat

import pytest


@pytest.hookimpl(tryfirst=True)
def pytest_sessionfinish(session):
    # git 객체처럼 읽기 전용인 파일이 있으면 pytest의 tmp_path 삭제가 Windows에서 실패해
    # 실행 폴더가 남는다. 삭제 전에 쓰기 권한을 풀어 둔다.
    basetemp = session.config._tmp_path_factory._basetemp
    if basetemp is None or not basetemp.is_dir():
        return
    for directory, _, files in os.walk(basetemp):
        for name in files:
            path = os.path.join(directory, name)
            try:
                os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
            except OSError:
                pass
