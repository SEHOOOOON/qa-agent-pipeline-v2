# QA Agent Pipeline V2 인계 문서

최종 갱신: 2026-09-10

## 1. 현재 방향

이 저장소는 프로젝트 1의 Fixture 기반 Workflow Prototype을 실제 모델 기반 QA 실행으로 보완합니다. V1의 4-Agent 절차와 QA 기준을 유지하고, 실제 모델 연결에 필요한 구조화 계약·제한된 코드 생성·실행 증거만 추가합니다.

현재 사용자 흐름:

~~~text
변경 요청
  → Agent 1 요구사항 분석
  → Agent 2 기존 TC 대조·변경분 TC 설계
  → Agent 3 신규·수정 후보 자동화·시험
  → 관련 기존 회귀 실행
  → Agent 4 규칙 기반 분류·최종 보고·Slack·Notion 전달
  → 사람의 최종 확인
~~~

## 2. 현재 구현 상태

| 영역 | 상태 |
|---|---|
| Agent 1 / CP1 | 실제 구조화 모델 호출, Requirement 영향도·확정 범위와 정보 부족 분리, 자동화 지원 여부와 영향도 판단 분리, 최대 1회 재작업 |
| Agent 2 / CP2 | Condition의 변경·유지·보조 역할, 기존 TC의 Requirement·검증 동작 대조, 기존 TC 전용 실행, 변경분 후보·관련 기존 TC 분리, 업무 규칙 묶음, 3단계 QA 기준·추적성·독립성·이중 검증 |
| Agent 3 / CP3 | 신규·수정 후보만 TC별 모델 호출, 필요한 UI 확인, 조건 순서를 보존한 계획, 결정론적 Python, 제한된 실행 전 HVAC 상태 저장·복원, 시험 증거 |
| 변경 검증 | 완료 후보 재검사, 신규 후보 없음·전체 제외 인계, 환경 사전 점검, Agent 2가 선택한 관련 기존 TC만 회귀 |
| Agent 4 / CP4 | 규칙 기반 원인 분류, 전체 산출물·증거·집계 정합성 검사, 사람 최종 검토 양식, Slack·Notion Dry-run/명시적 전송 |
| 다중 TC | 앞 단계 계약을 통과한 TC를 독립 처리하고 불명확·미지원 TC는 제외해 최종 보고. 인계 손상·Checkpoint 실패까지 무시하지 않음 |
| 제품 경계 | 중앙 관제 패널만 지원, 벽면 리모컨·로컬 경로 제외 |
| V2 기준 실행 자산 | V1 커밋 `ba62b611...`의 HTML·Pytest 설정·사람 작성 기존 회귀 테스트 네 파일만 `product_baseline/`에 가져옴 |
| 중앙제어 Run 화면 | 저장 결과 조회·API 새 실행·후보 공식 자산 판단을 분리. 팀장·Agent 1~4 버튼이 실제 Run 산출물 조회, 새 API 실행과 사람 자산 승인은 각각 기본 잠금, Agent 4 외부 보고는 미리보기 고정 |

## 3. 2026-08-25 단순화

현재 실행에 쓰이지 않던 과거 Agent 3 일괄 모델 호출 계층을 제거했습니다.

제거:

- Agent3BatchAutomationPlans
- Agent3BatchResponse
- PreparedAgent3Batch
- OpenAIAgent3.plan_many
- 일괄 입력·계획·모델 호출 산출물과 전용 인계 검증
- 현재 문서의 중단 Run 재개·정식 자산 등록 필수 절차 표현
- README의 긴 진단 Run 연대기

유지:

- 실행 가능한 여러 TC의 독립 처리
- 3단계 QA 기준과 TC 독립성
- 조건부 UI·내부 상태 이중 검증
- 처음 보는 유사 UI의 제한적 동적 조사
- CP3·컴파일러·증거·SHA-256 안전장치
- 관련 기존 회귀와 Agent 4 분류

새 실행 요약 파일은 agent3_run_summary.json입니다. 제거한 일괄 호출 전용 산출물은 역사적 증거로만 보존하며 현재 실행 계약에서 사용하지 않습니다. 이는 모든 과거 Run의 조회·호환 읽기를 제거했다는 뜻은 아닙니다.

## 4. 현재 검증

- 9월 10일 문서 작성·커밋 전 `python -m pytest -q` 전체 통과(종료 코드 0), 수집 201건 재확인. 새 모델 호출·외부 전송·공식 등록 없이 검증
- 9월 10일 최신 CLI Live `RUN-20260910-101352-9C9021`: CP1~CP4·최종 권고 PASS, MED 신규 후보·환경 점검·승인 HIGH 회귀 3건 PASSED. Agent 1 대상 사전조건 전달 누락으로 1회 재작성, Agent 2·3 첫 산출물 통과. 모델 `gpt-5.6-terra / medium`, 총 4회·43,419토큰(12,781 + 11,699 + 18,939). 자동화 제외·정보 부족 0건, SRS 승인 확인 사항 1건. HTML 해시 불변, 입력 미리보기·두 Trace의 사용자 경로·키 패턴 검출 없음. Slack·Notion PREVIEW, MED 공식 등록·SRS 승인 미수행. 원본은 로컬 보존하며 새 공개 Run 묶음은 추가하지 않음
- [시나리오와 처리 흐름 안내](docs/08_SCENARIOS_AND_FLOW_GUIDE.md)를 추가. 실제 성공·과거 잠금 실패·미실행 누락 사례와 공식 등록 흐름을 구분. 함수 미사용 조사 내용은 이 안내서 범위에서 제외

- 9월 9일 최종 전체 201건 통과(87.17초), 수집 201건. 마지막 화면 문구 변경 뒤 브라우저 승인 1건 재통과(6.80초). SRS 승인 테스트는 임시 파일과 고정 입력이며 Agent 1/2 인계 로더를 대체한 범위 검증으로, 새 Live 전체 실행을 뜻하지 않음

- 9월 9일 합의한 마지막 보완: 일부 후보가 통과해도 자동화 제외·정보 부족이 남으면 최종 HUMAN_REVIEW, 개별 TC 상태는 보존. 화면·사람 검토서·Slack/Notion 미리보기에 검증 범위 표시
- Agent 3는 동일 판정 단계의 결과를 최대 2초 동안 재관찰하고 같은 단계의 UI·내부 상태를 한 회차에서 확인. 조작은 재실행하지 않으며 복원 검사에도 적용. 실제 장비의 비동기 완료·미변경 지속 검증은 별도 인터페이스가 필요한 제한
- 기존 TC 전용 SRS 승인: 현재 제품·검증 증거·Agent 1/2 인계·SRS 제안 연결 확인 후 검토자·메모·동의로 문구만 반영. 공식 TC 미생성, 별도 SRS 기록 보존, 실패 시 원상복구. 브라우저→HTTP→임시 SRS 반영 검증 완료. 실제 제품 SRS·공식 자산 승인·새 API·외부 전송 없음

- 9월 8일 수정 후 전체 193건 통과(68.07초), 수집 193건. Agent 2 이중 검증 판정 단계 일치와 단일 Agent 3 CLI 인계를 보완. 과거 CP2는 신규 double_assert_timing_contract=1.0 규칙을 소급 적용하지 않음
- 수정 전 실제 API RUN-20260908-102657-0698C9는 Agent 1·2 각 1회 재작성 뒤 Agent 3 전송 보조 검사기의 오탐으로 후보 제외. 보조 스크립트 수정 뒤 검증된 Agent 1·2 파일을 별도 진단 위치에 복사해 Agent 3부터 실행. 총 모델 호출 5회, 신규·환경·승인 회귀 통과지만 TC가 UI·내부 검사를 반복 조작으로 분리했고 CP4 단일 인계 검사 FAIL. 원본·진단 기록을 전체 Live 성공으로 표현하지 않음
- 수정 후 그 산출물의 읽기 전용 재검사에서 새 CP2는 잘못된 판정 단계 분리를 차단하고 Agent 4 단일·기존 회귀 인계 검사는 통과. 새 모델 재생성·전체 Live·외부 전송은 미수행. 다음 검증은 새 프롬프트의 실제 TC 생성과 Agent 4까지 연결이며 기존 TC 전용 요청도 별도 확인 필요

- 9월 7일 `python -m pytest -o addopts= -q`: 전체 191건 통과, 68.13초. 관련 65건 및 실행·보고 46건도 통과. 새 모델 API·실제 외부 전송 없음
- 9월 7일 보완: 기존 TC 전용 요청은 신규 후보의 준비·복원 필드를 강제하지 않고, 검증된 요청 메모를 최종 사람 검토로 전달. 기존 코드의 수행 완료로 추정하지 않음. Agent 4는 해시가 맞는 실제 복원 실패 로그가 있으면 자동화 실행 문제·HOLD로 판단하고 제품 불일치 관찰도 함께 보존. Trial 원본 상태·과거 Run은 변경하지 않음
- 9월 6일 python -m pytest -q: 전체 187건 통과 1회 확인
- 추가 전체 실행(`-o addopts= -q`): 186건 통과·1건 TIMEOUT, 260.69초. `test_agent3_trial_distinguishes_product_mismatch` 내부 후보 시험의 20초 제한 초과이며, 동일 테스트 단독 재실행은 1건 통과(34.45초). 정확한 시간 초과 원인은 미확정이고 반복 안정성 해결로 표현하지 않음. 기대값·분류 기준·시간 제한을 변경하지 않음
- python -m pytest --collect-only -q: 191건, 고유 테스트 함수 186개와 카탈로그 일치. 컴파일·diff 검사 통과
- 9월 6일 보완: 수동 TC 제외 사유 보존, 기존 TC 전용 변경 조건의 명시 코드·수치 대조(CP2-019, 신규 계약만), 실패 로그에 없는 개별 기대 결과의 PASS 추정 제거, Notion Run ID+TC ID 키. 중앙제어에 유형 필터·행 펼침 TC 표를 추가하고 저장된 성공·실패 Run으로 확인. 기존 기준 회귀의 미기록 상세·유형과 모든 미지정 우선순위는 추정하지 않음
- 이번 변경은 새 API Live·실제 외부 전송·공식 승인 없이 검증. HTML은 보고 UI만 변경했지만 전체 파일 해시가 바뀌므로, 기존 후보를 공식 승인하려면 현행 정책대로 모델 호출 없는 재검증이 필요함
- 9월 4일 최소 보완: 화면에 후속 외부 전송 이력 반영, 유효한 환경 실패 결과의 Agent 4 보고 연결, 후보별 SRS 제안 표시 범위 일치. QA 판정 규칙·제품 HTML·공식 자산·기존 Run은 변경하지 않음
- 위 보완은 UI 관련 19건과 전체 183건 자동 테스트로 검증. 기존 잠금 Run의 SENT와 최신 MED Run의 PREVIEW도 읽기 전용 확인. 새 모델 API 호출·외부 전송·사람 자산 승인은 없음
- 역할별 파일 분리 후 Live `RUN-20260903-125732-ECE88F`: Agent 1 첫 결과의 실행 조건 누락과 Agent 3 첫 계획의 조건별 판정 위치 오류를 각각 CP1·CP3가 차단했고 1회 재작성 뒤 Agent 1→4 전체 PASS
- 분리 후 변경 검증: 신규 MED 후보·환경 점검·승인 기존 회귀 `TC-V2-001` 3건 모두 PASSED, 검토 항목·자동화 제외 0건, Slack·Notion PREVIEW
- 분리 후 실제 모델 사용량: Agent 1 13,056 + Agent 2 11,101 + Agent 3 38,865 = 63,022 tokens. Agent 1·3 재작성 각 1회가 포함된 누적값
- 분리 후 Trace 검사: Candidate와 승인 기존 회귀 ZIP 모두 사용자 절대경로·`file:///C:/Users`·임시 작업폴더명·키 패턴 0건
- 최신 공개 Live `RUN-20260903-121213-4CCC7A`: Agent 1 첫 결과의 인수 조건 누락을 CP1이 차단하고 1회 재작업 뒤 PASS·CONTINUE, Agent 2·CP2와 Agent 3 첫 계획·CP3·후보 Trial PASS
- Agent 2 결과: MED 카드 `중풍`·내부 `fanSpeed=MED`는 신규 후보 1건, 변경되지 않은 HIGH `강풍`·내부 `fanSpeed=HIGH`는 승인 자산 `TC-V2-001` 회귀 1건으로 분리
- 검증 실행과 Agent 4: 신규 후보·환경 점검·승인 기존 회귀 3건 모두 PASSED, CP4·최종 권고 PASS, 자동화 제외·검토 Finding 0건
- 실제 모델 사용량: Agent 1 11,561 + Agent 2 10,622 + Agent 3 19,028 = 41,211 tokens
- 외부 보고: Slack 1건·Notion 3건 PREVIEW, 실제 전송 0건. SRS 개정과 신규 후보 공식 등록은 사람 승인 전 상태
- 대상 HTML SHA-256 `37576e40...700c47`과 승인 자산은 실행 전·후 동일
- 공개 증거: `examples/results/agent1-agent2-agent3-agent4-medium-fan/`
- 공개 전 검사: Run 텍스트와 공개 묶음의 비밀정보·로컬 절대경로 0건. 최신 Live 당시 승인 기존 TC의 로컬 원본 Trace에는 임시 `file://` 실행 경로가 남아 공개 묶음에서 제외했습니다. 현재 코드는 신규 후보와 기존 회귀 Trace에 같은 ZIP 내부 경로 정제를 적용하며, 역사적 Run은 덮어쓰지 않습니다.

과거 Live의 시행착오와 설계 변경 이유는 `DECISION_LOG.md`에 보존합니다. 이 문서는 현재 재현 가능한 상태와 다음 작업만 유지합니다.

## 5. 중요한 제품·사실성 규칙

- Project1은 읽기 전용 기준 자산입니다.
- V2 Agent 3 실행·향후 제품 보완의 대상은 `product_baseline/virtual-controller.html`입니다.
- 기존 TC·Playwright 자동화는 `product_baseline/tests/test_controller.py`에서 선택 실행하며, 실제 실행은 원본과 분리된 임시 Workspace에서 수행합니다.
- Agent 1~3만 생성형 모델을 사용합니다.
- Agent 3 모델은 계획을 만들고 Python은 허용 목록 컴파일러가 생성합니다.
- Agent 4는 규칙 기반 분석기입니다.
- Checkpoint PASS는 사람 승인과 다릅니다.
- PRODUCT_MISMATCH_CANDIDATE는 결함 확정이 아닙니다.
- 중앙 관제 패널 외 로컬·벽면 리모컨 경로를 만들지 않습니다.
- 예시 기능과 값은 일반 규칙으로 하드코딩하지 않습니다.
- 제품 규칙은 변경 요청·SRS·승인 TC에서 받고, 신규 기능은 관찰된 UI 기반 공통 조작·검증으로 구현합니다.
- TC는 입력값 하나가 아니라 하나의 관제점·업무 규칙 단위로 만들며, 관련 조건은 중간 초기화와 조건별 판정 시점을 명시해 한 TC로 묶을 수 있습니다.
- Agent 3는 처음 보는 기능명이라는 이유로 제외하지 않고 실제 관찰한 범용 UI 조작을 먼저 사용합니다. 묶음 TC는 각 조건 직후 Assertion을 실행합니다.
- Agent 3는 변경으로 새로 필요하거나 수정되는 후보만 구현하며, 유지되는 기존 TC는 다시 만들지 않고 관련 회귀 단계에서 기존 코드를 실행합니다.
- Agent 4 외부 보고는 CP4 PASS 뒤에만 허용되고 기본은 Dry-run입니다. 실제 Slack·Notion 전송은 `--send`에서만 수행합니다.
- V1 온도 호환 코드는 해당 TC에서만 생성하며 범용 TC 코드에는 사용하지 않는 제품 전용 Selector를 넣지 않습니다.
- OPENAI_API_KEY와 로컬 절대경로를 산출물·전송 데이터에 넣지 않습니다.

## 6. 주요 파일

| 파일 | 역할 |
|---|---|
| README.md | 현재 목적·흐름·실행 방법 |
| docs/01_PRODUCT_SRS.md | 제품 기대 동작 |
| docs/02_V2_MVP_DESIGN.md | V1 대비 유지·추가·제외 범위 |
| docs/03_AGENT_AND_CHECKPOINT_SPEC.md | 단계별 계약 |
| docs/04_TEST_AND_TRACEABILITY_PLAN.md | 검증·추적 체인 |
| docs/05_PROJECT1_BASELINE_AUDIT.md | Project1 기준 자산과 한계 |
| docs/06_TEST_HARNESS_GUIDE.md | UI·내부 상태 확인 경계 |
| docs/07_TEST_CATALOG.md | 자동 테스트 목록 |
| product_baseline/ | V2 가상 중앙제어 HTML·Pytest 설정·사람 작성 기존 회귀 테스트 |
| src/qa_pipeline_v2.py | 기존 import·CLI를 유지하는 공개 호환 진입점 |
| src/qa_pipeline_contracts.py | Pydantic 계약·SRS·기존 TC 카탈로그 |
| src/qa_pipeline_agent1.py, src/qa_pipeline_agent2.py | 요구사항 분석·TC 설계와 CP1·CP2 |
| src/qa_pipeline_agent3.py | UI 조사·자동화 계획·CP3·결정론적 컴파일러 |
| src/qa_pipeline_execution.py | Agent 실행·후보 Trial·기존 관련 회귀·변경 검증 |
| src/qa_pipeline_reporting.py | Agent 4·CP4·사람 검토·Slack·Notion 보고 |
| src/qa_pipeline_orchestrator.py | 전체 순서와 CLI Parser |
| src/qa_pipeline_io.py, src/qa_pipeline_trace.py | 원자적 파일·해시와 Trace 경로 정제 공통 함수 |
| src/qa_pipeline_ui.py | 중앙제어 HTML 정적 제공, 실제 Run 요약, 선택적 Live 실행 연결부 |
| tests/test_*.py | 역할별 자동 테스트 7개 파일 |
| tests/pipeline_test_support.py | 테스트 공통 fixture·builder·import |

## 7. 다음 작업

1. 신규 MED 후보·관련 기존 TC·Agent 4의 새 실제 연결은 9월 10일 확인 완료. 포폴용 일부 정보 누락 사례, 최신 페이지 버튼 시작 경로와 기존 TC 전용 요청은 별도 확인 필요. SRS 단독 승인 UI/API는 구현했지만 실제 공식 문서 반영은 별도 사람 결정. 기존 코드의 준비·복원 절차 적합성은 자동 증명하지 않음
2. Agent 3 시험의 간헐적 시간 초과는 시작·브라우저 실행·종료 구간을 구분해 원인을 조사한 뒤 수정 필요성을 판단. 설치 안내에는 별도 `pytest-playwright`·Chromium 설치를 명시했지만 패키지 의존성 정의 자체는 변경하지 않음
3. 사용자 요청 시 미커밋 변경을 커밋·푸시한 뒤 중앙제어 Run·공식 자산 승인 흐름을 포함한 시연 영상을 제작

포폴은 V1의 QA 기준 설명을 유지하고 실제 V2 사례·영상·공식 등록 흐름을 보충하는 방향입니다. 공개 API 실행 서버 운영은 추가하지 않습니다. 사전조건 분류 지침과 CP1 검사 사이의 해석 차이, 카드 전체 텍스트 복원 비교, UI의 별도 SRS·자산 경로 전달·연결 모드 안내·진행 조회는 검토 사항이며 아직 수정 완료로 표현하지 않습니다. 이번 문서·커밋 요청은 이 후속 코드 수정을 포함하지 않습니다.

`RUN-20260903-121213-4CCC7A`의 MED SRS 개정과 신규 후보 공식 등록, 잠금 Run의 사람 최종 판정은 자동 실행 완료와 별개의 사람 결정입니다. 사용자가 명시적으로 승인할 때만 반영합니다.

API 호출, 커밋, 푸시는 사용자의 명시적 지시가 있을 때만 수행합니다.

## 8. 작업 시작 체크

다음 작업자는 AGENTS.md, 이 문서, DECISION_LOG.md, README.md를 모두 읽고 Git 상태를 먼저 확인해야 합니다. 미커밋 변경은 사용자 작업으로 보고 보존합니다.
