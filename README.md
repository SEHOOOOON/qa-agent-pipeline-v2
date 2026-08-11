# QA Agent Pipeline V2

운영 중인 가상 중앙제어 시스템에 **MODIFIED 변경 요청 1건**이 들어왔을 때, 실제 모델이 변경점을 분석하고 제품 기능 TC와 Playwright 자동화 코드 후보를 생성하는 흐름을 구현하려는 MVP입니다.

> 현재 저장소는 **Agent 1·CP1 구현 단계**입니다. Agent 1 Live 모델 호출과 결정론적 CP1 검증은 실제 API로 확인했으며, Agent 2 이후 인계·코드 생성 실행기는 아직 구현되지 않았습니다.

## 해결하려는 문제

프로젝트 1은 QA 기준, 가상 중앙제어기, 사람이 작성한 Playwright 테스트와 규칙 기반 보고를 보여줍니다. Agent 1·2 화면은 고정 산출물 시연이고 Agent 3는 기존 테스트 실행기이므로 새 입력이 새 분석·TC·코드로 이어지는 Live Pipeline은 아닙니다.

V2는 다음 세 연결만 우선 증명합니다.

1. 변경 요청에 따라 Agent 1·2의 실제 출력이 달라집니다.
2. 검증된 앞 단계 JSON이 다음 Agent의 실제 입력이 됩니다.
3. Agent 2의 TC가 Agent 3 코드 후보와 격리 시험 결과로 추적됩니다.

## 구현 상태

| 영역 | 현재 상태 |
|---|---|
| 가상 중앙제어기 | 프로젝트 1에 구현됨 |
| 기존 Playwright 제품 기능 TC | 7건 후보 중 6건 재사용 가능, TC-INT-002 보완 필요 |
| 환경 사전 점검 | TC-ENV-000 존재, 후속 차단 Gate는 미구현 |
| 분류·보고 | 프로젝트 1의 규칙 엔진 존재, V2 입력 계약 연동 필요 |
| Product SRS | 실제 화면·코드 기준 초기 제품 기준 문서 작성 |
| Agent 1 Live 모델 호출·CP1 | 실제 API 호출과 CP1 10개 규칙 PASS 검증 완료 |
| Agent 2 Live 모델 호출 | 미구현 |
| Agent 3 코드 후보 생성 | 미구현 |
| CP1·CP2·CP3·Run Orchestrator | CP1 구현, CP2·CP3·Orchestrator 미구현 |
| 조건부 검토·정식 QA 자산 등록 승인·최종 보고 | 미구현 |

## MVP 프로세스

~~~text
변경 요청
  -> Agent 1 변경 분석
  -> CP1 ID·before·after·근거 검사
  -> Agent 2 제품 기능 TC 설계
  -> CP2 구조·추적성·제품 기준 검사
  -> Agent 3 실제 화면 확인·Playwright 코드 후보 생성
  -> CP3 정적 검사·격리 시험
  -> CP 통과 후보의 변경 검증
  -> 기존 검증 가능 회귀 TC 실행
  -> Agent 4 규칙 기반 분류·보고
  -> 사람의 공식 SRS·TC·자동화 저장 승인 1회

공통 분기: CP1~3에서 REVIEW 발생 시에만 사람 검토 후 재개·수정·종료
~~~

## 문서

| 문서 | 역할 |
|---|---|
| [제품 SRS](docs/01_PRODUCT_SRS.md) | 실제 프로젝트 1 화면·코드에서 확인한 초기 제품 기준 문서 |
| [V2 MVP 설계](docs/02_V2_MVP_DESIGN.md) | 구현 범위, 단계와 종료선 |
| [Agent·Checkpoint 명세](docs/03_AGENT_AND_CHECKPOINT_SPEC.md) | 입출력 계약과 최소 판정 규칙 |
| [테스트·추적성 계획](docs/04_TEST_AND_TRACEABILITY_PLAN.md) | 기존 13개 TC 분리와 V2 검증 계획 |

## 용어

- **제품 기능 TC**: Agent 2가 만드는 조건·행동·기대 결과
- **자동화 코드 후보**: Agent 3가 Checkpoint를 통과한 TC를 Playwright Python으로 구현한 검증 전 코드
- **초기 제품 기준 문서**: 현재 화면·코드에서 확인한 SRS·TC로, 변경 전후를 비교할 출발점
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
- 기존 UI Selector와 `window.__vccs` 읽기 인터페이스 활용
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
- Agent 1·2·3만 생성형 모델 대상으로 정의합니다.
- Agent 4는 규칙 기반 분석기로 표시합니다.
- 기존 13건의 8 Pass·3 Fail·2 Skipped는 제품 회귀 성공률이 아니라 분류 데모 Dataset입니다.
- Register는 실제 프로토콜 레지스터가 아니라 HTML 시뮬레이터입니다.
- TC-ENV-000은 현재 사전 점검 사례이며 후속 차단 Gate가 아닙니다.
- 정식 QA 자산 등록 승인 전 기존 SRS·TC·자동화를 덮어쓰지 않습니다.

## 구현 순서

1. Product SRS 초기 기준 확정과 변경 요청 Schema
2. Agent 1 Adapter·CP1
3. Agent 2 Adapter·CP2·자동 인계
4. 실제 화면 확인 자료·Agent 3·CP3·격리 시험
5. 조건부 HUMAN_REVIEW 분기와 재개 기록
6. 변경 검증·기존 회귀 후보 실행
7. Agent 4 입력 정합화·최종 보고
8. 정식 QA 자산 등록 승인 기록
9. 서로 다른 변경 요청 2건으로 End-to-End 재검증

## Agent 1 로컬 실행

OpenAI Python SDK는 `OPENAI_API_KEY` 환경변수를 자동으로 읽습니다. API 키를 코드, JSON, Git 설정에 저장하지 않습니다.

~~~powershell
python -m pip install ".[test]"
$env:OPENAI_API_KEY="본인의 API 키"
python -m qa_pipeline_v2 agent1 --request examples/change_request.example.json
~~~

기본 모델은 `gpt-5.6-terra`입니다. 다른 모델을 시험할 때만 `--model` 또는 `OPENAI_MODEL`을 사용합니다.

결과는 Git에서 제외되는 `runs/RUN-.../`에 저장됩니다.

- `request.json`: 실제 입력
- `agent1_change_analysis.json`: 모델의 구조화 분석
- `checkpoint1.json`: 규칙별 PASS·REVIEW·FAIL
- `run_manifest.json`: 모델·토큰 수·최종 상태

예시 JSON의 변경 내용은 연결 확인용이며 대표 요구사항으로 고정하지 않습니다.

## MVP 완료 기준

- 서로 다른 요청에서 서로 다른 Agent 1·2 결과가 생성됩니다.
- Agent 1 Artifact ID가 Agent 2 입력에 기록됩니다.
- TC Step·Expected Result가 코드 Assertion에 추적됩니다.
- 후보는 원본과 분리된 임시 위치에서 실행됩니다.
- CP가 잡지 못하는 의미 판단만 조건부 사람 검토로 전환됩니다.
- 제품·자동화·환경 오류를 구분합니다.
- 실행 결과와 보고 수치가 일치합니다.
