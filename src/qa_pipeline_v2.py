"""QA Agent Pipeline V2의 공개 호환 진입점.

구현은 역할별 모듈로 분리되어 있으며 기존 import와 CLI 이름은 유지합니다.
"""

from __future__ import annotations

import qa_pipeline_orchestrator as _implementation
from qa_pipeline_contracts import __version__
from qa_pipeline_orchestrator import *


if __name__ == "__main__":
    raise SystemExit(_implementation.main())
