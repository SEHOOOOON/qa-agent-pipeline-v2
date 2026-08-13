# QA Agent Pipeline V2

운영 중인 가상 중앙제어 시스템에 **MODIFIED 변경 요청 1건**이 들어왔을 때, 실제 모델이 변경점을 분석하고 제품 기능 TC와 실제 UI 근거 기반 Playwright 자동화 후보를 만드는 흐름을 구현하는 MVP입니다.

> 현재 저장소는 **Agent 1·CP1 → Agent 2·CP2 → Agent 3·CP3·격리 시험 구현 단계**입니다. Agent 1·2 v2.2 Live Run에서 TC 후보 12건과 CP2 PASS를 확인했습니다. Agent 3는 실제 UI 조사, 구조화 자동화 계획, 결정론적 코드 컴파일, CP3와 격리 시험까지 구현했으며 코드 회귀 테스트 46건이 통과합니다. Agent 3의 실제 모델 호출 결과는 아직 공개 Run으로 확정하지 않았습니다.

## 해결하려는 문제

프로젝트 1은 QA 기준, 가상 중앙제어기, 사람이 작성한 Playwright 테스트와 규칙 기반 보고를 보여줍니다. Agent 1·2 화면은 고정 산출물 시연이고 Agent 3는 기존 테스트 실행기이므로 새 입력이 새 분석·TC·코드로 이어지는 Live Pipeline은 아닙니다.

V2는 다음 세 연결만 우선 증명합니다.

1. 변경 요청에 따라 Agent 1·2의 실제 출력이 달라집니다.
2. 검증된 앞 단계 JSON이 다음 Agent의 실제 입력이 됩니다.
3. Agent 2의 TC를 Agent 3 코드 후보와 격리 시험 결과까지 연결합니다.

## 구현 상태

| 영역 | 현재 상태 |
|---|---|
| 가상 중앙제어기 | 프로젝트 1에 구현됨 |
| 기존 Playwright 제품 기능 TC | 7건 후보 중 6건 재사용 가능, TC-INT-002 보완 필요 |
| 환경 사전 점검 | TC-ENV-000 존재, 후속 차단 Gate는 미구현 |
| 분류·보고 | 프로젝트 1의 규칙 엔진 존재, V2 입력 계약 연동 필요 |
| Product SRS | 실제 화면·코드 기준 초기 제품 기준 문서 작성 |
| Agent 1 Live 모델 호출·CP1 | 구조화 분석, CP1 10개 규칙, CONTINUE·PAUSE·BLOCKED 인계, 실패 시 최대 1회 재작업 구현 |
| Agent 2 Live 모델 호출 | CP1 PASS+CONTINUE Run만 입력, 변경 요청·고정 SRS·Agent 1 분석으로 제품 TC 후보 생성, 실패 시 최대 1회 재작업 구현 |
| Agent 3 코드 후보 생성 | CP2 PASS 중앙 제어 TC 1건 선택, 실제 UI 조사, 모델의 구조화 실행 계획, 결정론적 Playwright 코드 컴파일 구현 |
| CP1·CP2·CP3·Run Orchestrator | 단계별 CLI와 SHA-256 인계, CP3 계획·코드 검사, 임시 폴더 1회 시험 구현. 전체 일괄 Orchestrator는 미구현 |
| 조건부 검토·정식 QA 자산 등록 승인·최종 보고 | 미구현 |

## MVP 프로세스

~~~text
변경 요청
  -> Agent 1 변경 분석
  -> CP1 ID·before·after·확정 조건 출처·인수 조건 누락 검사 + CONTINUE·PAUSE·BLOCKED 인계
  -> Agent 2 제품 기능 TC 설계
  -> CP2 구조·추적성·중앙/로컬 경로·시험 데이터·사람 검토 필요성 검사
  -> Agent 3 실제 화면 확인·Playwright 코드 후보 생성
  -> CP3 정적 검사·격리 시험
  -> CP 통과 후보의 변경 검증
  -> 기존 검증 가능 회귀 TC 실행
  -> Agent 4 규칙 기반 분류·보고
  -> 사람의 공식 SRS·TC·자동화 저장 승인 1회

공통 분기: CP1·CP2의 REVIEW 또는 PAUSE와 CP3 FAIL은 후속 자동 실행을 중단합니다. 재개 UI는 아직 미구현입니다.
~~~

## 문서

| 문서 | 역할 |
|---|---|
| [제품 SRS](docs/01_PRODUCT_SRS.md) | 변경 분석에 사용하는 제품 기대 동작과 인수 기준 |
| [V2 MVP 설계](docs/02_V2_MVP_DESIGN.md) | 구현 범위, 단계와 종료선 |
| [Agent·Checkpoint 명세](docs/03_AGENT_AND_CHECKPOINT_SPEC.md) | 입출력 계약과 최소 판정 규칙 |
| [테스트·추적성 계획](docs/04_TEST_AND_TRACEABILITY_PLAN.md) | V2 단계별 검증·증거·완료 기준 |
| [Project1 기준 자산 감사](docs/05_PROJECT1_BASELINE_AUDIT.md) | 기존 구현·13개 TC·Coverage·알려진 한계 |
| [QA 하네스 가이드](docs/06_TEST_HARNESS_GUIDE.md) | QA Drawer·Register·window.__vccs 사용 경계 |

## 용어

- **제품 기능 TC**: Agent 2가 만드는 조건·행동·기대 결과
- **자동화 코드 후보**: Agent 3가 Checkpoint를 통과한 TC를 Playwright Python으로 구현한 검증 전 코드
- **초기 제품 기준 문서**: 화면 정책과 확인 가능한 제품 근거로 정리한 기대 동작으로, 현재 코드와 다르면 감사 문서에 구현 불일치를 남기는 변경 전 출발점
- **기존 기준 자동화 코드**: 프로젝트 1에서 사람이 작성했고 기존 회귀 검증에 재사용하는 Playwright 코드
- **제품 기능 회귀 후보**: 기존 7건 중 파이프라인 검증용 고정 사례와 근거 부족 TC를 제외한 테스트
- **파이프라인 검증용 고정 사례**: 결과 분류·차단 흐름을 확인하기 위해 의도적으로 유지하는 사례
- **실행 단위(Run)**: 변경 요청 한 건이 Agent 1부터 최종 보고까지 처리되는 한 번의 전체 실행
- **Checkpoint 통과**: 사람이 승인했다는 뜻이 아니라, 미리 정한 자동 검사 규칙을 충족했다는 뜻
- **조건부 검토**: 자동 검사만으로 의미를 확정할 수 없는 REVIEW 항목이 생겼을 때만 사람이 확인하는 절차
- **정식 QA 자산 등록**: 검증이 끝난 SRS·TC·Playwright 코드를 다음 변경에서도 재사용할 공식 버전으로 저장하는 작업

## MVP 포함

- MODIFIED 요청 1건
- Agent 1·2 실제 모델 Adapter
- Agent 1→2 구조화 JSON 전달
- 신규 또는 수정 TC 최소 1건
- Agent 3 Playwright Python 코드 후보 최소 1건
- 기존 UI Selector와 테스트 전용 `window.__vccs` 읽기 인터페이스 활용
- CP1~3의 구조·근거·금지 패턴 검사
- 임시 폴더에서 후보 코드 1회 시험
- Checkpoint 통과 시 중간 승인 없이 자동 진행
- REVIEW·근거 부족·정책 충돌에만 조건부 사람 검토
- 검증 후보 변경 실행과 기존 검증 가능 회귀 TC 실행
- 규칙 기반 결과 분류와 Run 보고
- 정식 QA 자산 등록 승인 1회

## MVP 제외

- ADDED·DELETED 자동 처리
- 모든 TC 자동 생성·자동화
- 자유로운 Agent 토론
- 자연어 의미의 완전 자동 판정
- 무제한 자동 수정·Self-Healing
- 정식 QA 자산 자동 등록·버전 갱신
- Full Regression 전체 구현
- 다중 모델 비교·대규모 반복 평가
- 운영 장비·외부 서비스 연결

## 사실성 원칙

- 문서의 계획을 구현 완료로 표현하지 않습니다.
- Agent 1·2는 구조화 결과를 직접 생성하고, Agent 3 모델은 구조화 실행 계획만 생성합니다. Python 코드는 허용 목록 기반 컴파일러가 결정론적으로 만듭니다.
- Agent 4는 규칙 기반 분석기로 표시합니다.
- 기존 13건의 8 Pass·3 Fail·2 Skipped는 제품 회귀 성공률이 아니라 분류 데모 Dataset입니다.
- Register는 실제 프로토콜 레지스터가 아니라 HTML 시뮬레이터입니다.
- TC-ENV-000은 현재 사전 점검 사례이며 후속 차단 Gate가 아닙니다.
- 정식 QA 자산 등록 승인 전 기존 SRS·TC·자동화를 덮어쓰지 않습니다.
- Project1은 Fixture 기반 Workflow Prototype이며, Agent 1·2 Live 생성과 Agent 3 코드 생성은 V2에서 보완합니다.
- 제품 SRS와 QA 하네스·기존 구현 감사 내용을 별도 문서로 관리합니다.

## 구현 순서

1. Product SRS 초기 기준 확정과 변경 요청 Schema
2. Agent 1 Adapter·CP1
3. Agent 2 Adapter·CP2·자동 인계
4. 실제 화면 확인 자료·Agent 3·CP3·격리 시험 — 구현
5. 조건부 HUMAN_REVIEW 분기와 재개 기록
6. 변경 검증·기존 회귀 후보 실행
7. Agent 4 입력 정합화·최종 보고
8. 정식 QA 자산 등록 승인 기록
9. 서로 다른 변경 요청 2건으로 End-to-End 재검증

## 저장소 구조

~~~text
qa-agent-pipeline-v2/
├─ docs/                         # SRS·MVP 설계·Agent/Checkpoint 계약·테스트 계획
├─ examples/
│  └─ results/                  # API 키를 제외한 공개 실행 결과
├─ src/
│  └─ qa_pipeline_v2.py         # 데이터 계약·Agent 1/2/3·CP1/2/3·CLI·격리 시험
├─ tests/
│  └─ test_pipeline.py          # SRS·Agent·Checkpoint·실제 브라우저 격리 시험 회귀 테스트
├─ runs/                        # 로컬 원본 실행 결과(Git 제외)
├─ pyproject.toml               # 의존성·실행 명령·테스트 설정
└─ README.md
~~~

현재 구현 규모에서는 한 핵심 모듈과 한 테스트 파일이 역할을 찾기 가장 쉽습니다. Agent 3 격리 실행처럼 독립 보안 경계가 실제로 생길 때만 파일을 다시 분리합니다.

v2.2 공개 Live 산출물은 [examples/results/agent1-agent2-auto-temperature](examples/results/agent1-agent2-auto-temperature/)에서 확인할 수 있습니다. Agent 2의 1차 반려와 재작업 결과도 함께 보존했습니다.
## Agent 1·2·3 로컬 실행

OpenAI Python SDK는 `OPENAI_API_KEY` 환경변수를 자동으로 읽습니다. API 키를 코드, JSON, Git 설정에 저장하지 않습니다.

~~~powershell
python -m pip install ".[agent3,test]"
$env:OPENAI_API_KEY="본인의 API 키"
python -m qa_pipeline_v2 agent1 --request examples/change_request.example.json
python -m qa_pipeline_v2 agent2 --run-id "Agent 1이 출력한 RUN-..."
python -m qa_pipeline_v2 agent3 --run-id "Agent 2가 완료된 RUN-..." --tc-id "TC-CAND-..." --target-html "프로젝트1 virtual-controller.html 경로" --preview-only
python -m qa_pipeline_v2 agent3 --run-id "Agent 2가 완료된 RUN-..." --tc-id "TC-CAND-..." --target-html "프로젝트1 virtual-controller.html 경로"
~~~

기본 모델은 `gpt-5.6-terra`입니다. 다른 모델을 시험할 때만 `--model` 또는 `OPENAI_MODEL`을 사용합니다.
Agent 3 모델 호출에는 시스템 지침, 선택한 CP2 TC, 관련 SRS 행, 대상 파일명·SHA-256, 페이지 제목, Selector별 tag·text·visible·enabled·action_hint와 하네스 키가 전송됩니다. API 키, 로컬 절대경로, HTML 원문, Screenshot과 Trace는 보내지 않습니다. 먼저 `--preview-only`로 `agent3_model_input_preview.json`을 확인해야 합니다.

현재 Agent 3 MVP는 실제로 조사한 **CENTRAL 제어 패널 TC 1건**만 지원합니다. LOCAL 제어 TC는 별도 실제 UI 대상을 조사하기 전까지 실행하지 않습니다. 격리 시험의 `PRODUCT_MISMATCH_DETECTED`는 자동화가 기대와 다른 제품 상태를 관찰했다는 후보 판정이며, 그 자체로 최종 제품 결함 확정을 뜻하지 않습니다.


결과는 Git에서 제외되는 `runs/RUN-.../`에 저장됩니다.

- `request.json`: 실제 입력과 SHA-256 검증 대상
- `agent1_change_analysis.json`: 모델의 구조화 분석
- `checkpoint1.json`: 규칙별 PASS·REVIEW·FAIL
- `run_manifest.json`: 모델·Prompt 버전·상태·인계 상태와 요청/SRS/Agent 1/CP1 SHA-256
- `agent2_test_design.json`: Agent 2가 만든 제품 기능 TC 후보
- `checkpoint2.json`: CP2 규칙별 판정
- `agent2_manifest.json`: Agent 2 상태와 앞 단계·Agent 2·CP2 SHA-256 체인
- `agent3_model_input_preview.json`: 실제 API 전송 예정 데이터와 제외 항목
- `agent3_ui_observation.json`: 파일명·SHA-256과 실제 확인 Selector·하네스 목록
- `agent3_automation_plan.json`: 모델이 만든 제한된 행동·Assertion 계획
- `candidates/test_<tc-id>.py`: 허용 목록 컴파일러가 만든 Playwright 후보
- `checkpoint3.json`: 계획·코드 추적성과 금지 패턴 검사 결과
- `agent3_trial.json`: 격리 시험 결과와 증거 완전성
- `agent3_manifest.json`: Agent 2 입력 체인·UI·계획·코드·시험 SHA-256

예시 JSON의 변경 내용은 연결 확인용이며 대표 요구사항으로 고정하지 않습니다.

## MVP 완료 기준

- 서로 다른 요청에서 서로 다른 Agent 1·2 결과가 생성됩니다.
- Agent 1 시작 시 저장한 요청·SRS 스냅샷·분석·CP1의 SHA-256이 Agent 2 실행 전에 재검증됩니다.
- TC Step·Expected Result가 코드 Assertion에 추적됩니다.
- 후보는 원본과 분리된 임시 위치에서 실행됩니다.
- CP가 잡지 못하는 의미 판단만 조건부 사람 검토로 전환됩니다.
- 제품·자동화·환경 오류를 구분합니다.
- 실행 결과와 보고 수치가 일치합니다.
