# QA Agent Pipeline V2

기존 SRS와 테스트케이스(TC)가 있는 가상 중앙제어 시스템에서, 변경 요구사항을 분석하고 변경분을 시험한 뒤 사람이 재사용할 테스트 자산을 승인하는 프로젝트입니다.

V1의 QA 기준과 4-Agent 흐름에 실제 모델 호출·자동화 후보 생성·실행 증거를 연결한 MVP입니다.

[V2 포트폴리오 페이지](https://sehooooon.github.io/qa-agent-pipeline-v2/project.html)는 소개·QA 기준·실행 흐름·사례·승인·설계 경험을 세로 스크롤로 읽는 정적 소개 페이지입니다. 영상은 준비 중이며, 페이지를 여는 것만으로 API 호출이나 자산 승인을 수행하지 않습니다. [페이지 원본](project.html)은 이 저장소에서 관리합니다.

```text
변경 요청 → Agent 1 요구사항 분석 → Agent 2 기존 TC 대조·변경분 설계
         → Agent 3 자동화 계획·코드 생성·시험 → 관련 기존 TC 실행
         → Agent 4 결과 분류·보고 → 사람의 SRS·공식 TC 승인
```

## 먼저 읽을 문서 3개

| 문서 | 읽는 목적 |
|---|---|
| 이 README | 프로젝트 소개와 실행 방법 |
| [프로젝트 안내](docs/PROJECT_GUIDE.md) | 시나리오, QA 기준, Agent·Checkpoint 상세 로직, 사람 승인 |
| [현재 상태와 다음 작업](PROJECT_HANDOFF.md) | 최신 검증 결과, 실행 증거 위치, 남은 과제 |

제품 기준인 [SRS](docs/01_PRODUCT_SRS.md), [자동 테스트 목록](docs/07_TEST_CATALOG.md), [결정·시행착오 기록](DECISION_LOG.md), [작업 규칙](AGENTS.md)은 필요할 때 찾아보는 자료입니다. 현재 테스트 수와 최신 실행 결과는 인계 문서에서 관리합니다.

## V1과 달라진 부분

| 영역 | V1 | V2 |
|---|---|---|
| QA 기준 | 3단계 기준·추적성·독립성·UI/내부 상태 이중 검증 | 유지 |
| Agent 1·2 | 고정 산출물 시연 | 실제 OpenAI API로 분석·TC 생성 |
| Agent 3 | 사람이 작성한 기존 자동화 실행 | AI가 계획 작성, 허용 목록 컴파일러가 Python 생성·시험 |
| Agent 4 | 규칙 기반 분류·Slack/Notion 보고 | 유지하며 인계·증거·집계 확인 추가 |
| 최종 판단 | 시연 중심 | 사람이 SRS 개정·공식 TC 등록 승인 |

V1은 Fixture 기반 Workflow Prototype입니다. V2에서도 Agent 4는 규칙 기반 분석기이며, Checkpoint 통과와 사람의 공식 승인은 별개입니다.

현재 범위는 MODIFIED 요청, 중앙 관제 패널, 변경분 후보와 관련 기존 TC 실행입니다. ADDED·DELETED, 전체 회귀, 실제 장비 통신, 모든 UI 기술 지원과 무제한 자동 수정은 포함하지 않습니다. 반복 평가는 별도 프로젝트 2에서 다룹니다.

## 실행 방법

Python 3.10 이상이 필요합니다. OpenAI API 키는 실행 환경의 `OPENAI_API_KEY`에 설정합니다. 실제 모델 호출에는 비용이 발생합니다. 기본 모델은 `gpt-5.6-terra / medium`입니다.

```powershell
python -m pip install ".[agent3,test]"
python -m playwright install chromium

# 저장된 실제 Run 조회
python -m qa_pipeline_ui

# 새 API 실행과 사람 승인 기능 활성화
python -m qa_pipeline_ui --allow-live-run --allow-asset-approval
```

브라우저에서 `http://127.0.0.1:8765/`에 접속합니다. 새로 복제한 저장소에는 로컬 실행 기록이 없어 조회 목록이 비어 있을 수 있습니다. `pytest-playwright`는 agent3 설치 옵션에 포함됩니다. 실제 실행·승인 요청은 같은 로컬 페이지의 JSON 요청만 허용합니다.

HTML을 직접 열거나 공개 웹 주소에 접속하면 MED 풍량 정상 변경의 저장된 데모가 표시됩니다. 데모 승인은 화면 시연이며 파일에 반영되지 않습니다. 실제 시험은 로컬 서버가 별도 브라우저에서 수행하고, 관제 화면에는 실행 상태와 결과가 표시됩니다.

CLI에서는 다음 순서로 실행합니다.

```powershell
python -m qa_pipeline_v2 pipeline --request "examples/change_request.success-medium-fan.json" --target-html "product_baseline/virtual-controller.html"
python -m qa_pipeline_v2 execute --run-id "RUN-..." --target-html "product_baseline/virtual-controller.html"
python -m qa_pipeline_v2 agent4 --run-id "RUN-..."
```

`pipeline`은 Agent 1~3, `execute`는 완료 후보 확인·관련 기존 회귀, `agent4`는 분류·최종 보고를 담당합니다. 후자의 두 명령은 모델을 호출하지 않습니다. Slack·Notion은 기본 미리보기이며 CLI에서 `--send`를 명시할 때 실제 전송합니다. 화면에서 시작한 실행은 외부 보고 미리보기까지 진행합니다.

## 검증과 공개 증거

새 후보는 본 시험 직전에 사전조건의 실제 값을 확인합니다. 증명을 연결하지 못한 TC는 제외 사유를 남기고, 실제 준비 상태가 다르면 제품 결함과 구분해 보고합니다. 과거 성공 Run이 새 사전조건 검증까지 받았다는 뜻은 아닙니다.

```powershell
python -m pytest -q
python -m pytest --collect-only -q
git diff --check
```

[MED 성공 사례](examples/results/agent1-agent2-agent3-agent4-medium-fan/README.md)와 [잠금 불일치 사례](examples/results/agent1-agent2-agent3-agent4-lock-disable/README.md)는 실행 당시 공개 증거입니다. 최신 로컬 실행과 공개 예시의 날짜·상태는 [현재 상태](PROJECT_HANDOFF.md)에서 구분합니다. 자동 테스트 통과는 새 실제 API 실행의 성공을 뜻하지 않습니다.

[미정 조건이 남은 사례](examples/results/agent1-agent2-agent3-agent4-partial-information/README.md)는 실행한 시험이 통과해도 정보 부족이 남으면 사람 검토로 넘기는 흐름의 공개 요약입니다. 실행 통과와 요청 전체의 검증 완료를 구분합니다.
