# Project1 기준 자산 감사

## 1. 목적

이 문서는 V2가 참조하는 프로젝트 1의 화면, 테스트, 결과 보고 코드가 **실제로 무엇을 구현했고 무엇을 구현하지 않았는지** 기록합니다. 제품 기대 동작은 [제품 SRS](01_PRODUCT_SRS.md), 테스트 도구 사용법은 [QA 하네스 가이드](06_TEST_HARNESS_GUIDE.md)에서 분리합니다.

| 항목 | 내용 |
|---|---|
| 감사 기준일 | 2026-08-12 |
| 대상 화면 | portfolio_export/virtual-controller.html |
| 대상 테스트 | portfolio_export/tests/test_controller.py |
| 결과 수집 | portfolio_export/tests/conftest.py |
| 결과 분석 | portfolio_export/scripts/agent4_reporting.py |
| 감사 성격 | 코드·화면·기존 결과의 정적 대조이며 회사 인증이나 운영 검증이 아님 |

Project1의 Agent 4 보고 스크립트는 기본 Dry-run과 명시적 `--send`를 구분하고 Slack Webhook·Notion TC-ID Upsert를 수행합니다. V2도 이 외부 보고 순서를 복원하되, V2의 CP4·최종 보고 SHA-256을 전송 허용 조건으로 추가합니다.

## 2. Project1의 정확한 성격

프로젝트 1은 QA 판단 기준, 가상 중앙제어기, 사람이 작성한 Playwright 테스트와 규칙 기반 결과 보고를 연결한 **Fixture 기반 Workflow Prototype**입니다.

| 구성 | 실제 상태 | 표현 가능한 범위 |
|---|---|---|
| Agent 1 | Prompt·샘플·Workflow Demo | 요구사항 분석 역할과 출력 형식을 설계함 |
| Checkpoint 1 | 문서·UI 시연 | 요구사항 검토 기준을 구조화함 |
| Agent 2 | 기존 TC·샘플·Workflow Demo | 3-Tier TC 설계 기준과 사례를 구성함 |
| Checkpoint 2 | 문서·UI 시연 | TC 검토 기준과 승인·반려 사례를 구성함 |
| Agent 3 | 사람이 작성한 Playwright 13건 실행 | 기존 자동화 실행과 결과 수집을 구현함 |
| Checkpoint 3 | 환경 점검 TC와 결과 설명 | 독립 실행 Gate나 코드 생성 검증기는 구현되지 않음 |
| Agent 4 | Python 규칙 기반 집계·분류·보고 | 기존 결과의 집계, 정해진 분류 규칙과 Dry-run 보고를 구현함 |
| Checkpoint 4 | JSON·HTML 수치 및 필드 검사 | 제한된 정합성 검사를 구현함 |

따라서 Project1만으로 다음을 주장하지 않습니다.

- 새 요구사항에 따라 Agent 1·2 결과가 매번 동적으로 생성됨
- Agent 2 TC가 Agent 3 Playwright 코드로 자동 변환됨
- 네 개 생성형 Agent가 실제로 협업함
- Checkpoint가 자연어 의미를 완전 자동 검증함
- Agent 4 분류 정확도가 독립 Ground Truth로 입증됨

이 간격을 실제 모델 호출과 구조화 인계로 보완하는 작업이 V2입니다.

## 3. 제품 구현 확인

### 확인된 제품 동작

- IDU-00~IDU-15 카드 16개와 내부 숫자 ID 1~16
- 단일·복수 장비 선택
- 전원, 5개 모드, 설정 온도, 4개 풍량과 잠금 대기값
- 적용 버튼 이후 허용 대상 상태 반영
- 오프라인·오류·잠금 상태의 제어 제한
- 코드로 주입된 VIEWER 역할 상태의 중앙 제어 차단
- 장비별 부분 적용
- °C·°F 표시 전환
- 상태 저장과 새로고침 후 복원
- 사용자 Toast
- HTML 기반 내부 상태 및 Register 시뮬레이션

### 화면에 보이지만 제품 기능으로 확정하지 않은 UI

- 장치 필터: 모든 장치/상태 한 항목만 있고 필터 처리 이벤트가 없습니다.
- 장치정보 탭: 탭 모양은 있으나 전환 이벤트와 별도 정보 화면이 없습니다.
- 도움말 버튼: 클릭 동작이 연결되어 있지 않습니다.
- 역할 전환: VIEWER 차단 함수와 안내 Overlay는 있으나 ADMIN·VIEWER 전환 버튼이 HTML에 없습니다.

따라서 위 항목은 구현 완료 기능으로 주장하지 않고, 정식 요구사항으로 확정하려면 별도 UI와 동작을 먼저 구현해야 합니다.

### 제품 기준으로 확정하지 않은 항목

- 숨김 공기청정 기능: Workflow Demo에서 표시되는 확장 사례
- 실제 Modbus·MQTT 통신
- 오프라인 장비의 현장 조작 성공
- 실제 운영 장비 알람으로서의 CH05·CH21 의미
- 실제 서버 저장과 다중 사용자 상태 동기화
- 수치화된 성능·응답시간 SLA

## 4. 기존 13개 TC 분류

기존 결과의 8 Pass·3 Fail·2 Skipped는 제품 회귀 성공률이 아니라 제품 기능 TC와 분류용 고정 사례가 섞인 데모 Dataset입니다.

| 분류 | 수 | TC |
|---|---:|---|
| 환경 사전 점검 사례 | 1 | TC-ENV-000 |
| 제품 기능 후보 | 7 | TC-MODE-001~003, TC-LOCK-001, TC-ERR-001, TC-INT-002, TC-TEMP-001 |
| 제품 결함 분류 Fixture | 1 | TC-TEMP-002 |
| Pipeline Control Fixture | 4 | TC-PIPE-001~004 |
| 합계 | 13 | 프로젝트 1 자산 |

### TC와 제품 요구사항 연결

| TC ID | 실제 검증 목적 | 연결 요구사항 | V2 처리 |
|---|---|---|---|
| TC-ENV-000 | 페이지와 장비 16대, QA 패널 확인 | REQ-ENV-001 | 사전 점검 사례 |
| TC-MODE-001 | HEAT·24°C 적용과 화면·내부 상태 | REQ-CONTROL-001, REQ-MODE-001, REQ-STATE-001 | 회귀 후보 |
| TC-MODE-002 | FAN 온도 입력 비활성 | REQ-MODE-002 | 회귀 후보 |
| TC-MODE-003 | DRY 비활성 후 COOL 재활성 | REQ-MODE-001, REQ-MODE-002 | 회귀 후보 |
| TC-LOCK-001 | 16대 잠금과 중앙·현장 차단 | REQ-LOCK-001 | 회귀 후보 |
| TC-ERR-001 | CH05 오류와 중앙 제어 차단 | REQ-ERROR-001 | 회귀 후보 |
| TC-INT-002 | 선택 3대 HEAT 적용 | REQ-BATCH-001 | 비대상 불변 보완 전 회귀 제외 |
| TC-TEMP-001 | 30°C 상한 초과 차단 | REQ-TEMP-001 | 회귀 후보 |
| TC-TEMP-002 | AUTO 18°C 하한 위반 분류 | 기존 제품 SRS 근거 없음 | 제품 회귀 제외 |
| TC-PIPE-001 | 알람 UI 기준 부족 | 해당 없음 | REQUIREMENT_REVIEW Fixture |
| TC-PIPE-002 | 시뮬레이터 미응답 | 해당 없음 | ENVIRONMENT_ISSUE Fixture |
| TC-PIPE-003 | 존재하지 않는 Locator | 해당 없음 | AUTOMATION_EXECUTION_ERROR Fixture |
| TC-PIPE-004 | 지원 밖 17번째 장비 | 해당 없음 | NOT_EXECUTED Fixture |

## 5. 요구사항 Coverage

| Coverage | Requirement |
|---|---|
| EXISTING_TC | REQ-ENV-001, REQ-CONTROL-001, REQ-BATCH-001, REQ-MODE-001, REQ-MODE-002, REQ-TEMP-001, REQ-LOCK-001, REQ-ERROR-001, REQ-STATE-001 |
| PARTIAL | REQ-BATCH-002, REQ-NOTIFY-001 |
| CODE_OBSERVED_WITHOUT_DEDICATED_TC | REQ-SELECT-001, REQ-OVERVIEW-001, REQ-MONITOR-001, REQ-POWER-001, REQ-AUTH-001, REQ-TEMP-002, REQ-FAN-001, REQ-ERROR-002, REQ-GATEWAY-001, REQ-GATEWAY-002, REQ-LOCAL-001, REQ-LOCAL-002, REQ-PERSIST-001 |

코드가 존재한다고 검증 완료인 것은 아니며 전용 TC가 없다고 미구현인 것도 아닙니다.

## 6. 알려진 불일치와 한계

| ID | 확인 내용 | 영향 | V2 원칙 |
|---|---|---|---|
| GAP-TEMP-001 | 화면 정책은 16°C 하한이지만 중앙·현장 온도 코드가 15°C까지 허용 | SRS와 구현 불일치 | 정상 기대값은 16°C로 유지하고 결함으로 기록 |
| GAP-BATCH-001 | TC-INT-002가 선택 3대만 확인하고 비대상 13대 불변을 검증하지 않음 | REQ-BATCH-002 증거 부족 | 보완 전 회귀 세트 제외 |
| GAP-LOCAL-001 | 오프라인 현장 조작 로그는 작동을 표현하지만 실제 상태는 변경되지 않음 | 메시지와 실제 동작 불일치 | 제품 기대 결과 확정 보류 |
| GAP-GATE-001 | Project1 자체에서는 TC-ENV-000 실패가 후속 테스트를 자동 차단하지 않음 | Project1 단독 실행을 Gate로 주장할 수 없음 | V2 `execute`가 복사 Workspace에서 TC-ENV-000을 먼저 실행하고 미통과 시 관련 회귀를 차단 |
| GAP-EVIDENCE-001 | 기존 결과의 evidence_path가 빈 값 | Screenshot·Trace 완전성 근거 없음 | 존재하는 증거만 보고 |
| GAP-CLASS-001 | conftest가 예외 유형을 의미 라벨 failure_reason으로 먼저 작성하고 Agent 4가 이를 다시 분류 | 독립 분류 정확도 평가 불가 | V2는 중립 신호와 Gold Label을 분리 |
| GAP-CP4-001 | Project1 Agent 4는 검증 차단 여부 확인 전에 요약·포트폴리오 동기화를 수행 | Fail-closed 보장 부족 | V2에서는 검증 통과 뒤에만 후속 쓰기 |
| GAP-A1A2-001 | Agent 1·2는 저장된 Prompt·샘플·Demo이며 Live 모델 실행기가 없음 | 입력과 산출물의 동적 인과관계 없음 | V2 Agent 1부터 실제 호출 구현 |
| GAP-A3-001 | Agent 3는 기존 사람이 작성한 테스트를 실행하며 TC 기반 코드 생성은 하지 않음 | End-to-End 생성 파이프라인 아님 | V2에서 코드 후보 생성·검증을 별도 구현 |
| GAP-AUTH-001 | VIEWER 차단 로직은 있으나 화면에 역할 전환 버튼이 없음 | 일반 사용자 흐름으로 권한 전환을 검증할 수 없음 | 직접 함수 주입을 제품 UI 검증으로 포장하지 않고 UI 구현 전까지 미완료로 표시 |
| GAP-UI-SHELL-001 | 필터·장치정보 탭·도움말 버튼에 실제 동작이 연결되지 않음 | 화면만 보고 구현 기능으로 오해할 수 있음 | 요구사항·Coverage에서 제외하고 UI 껍데기로 기록 |

## 7. 사실성 표현 가이드

### 사용 가능한 표현

- QA 판단 기준 기반 Agent Workflow Prototype을 설계했습니다.
- 가상 중앙제어기와 사람이 작성한 Playwright 회귀 테스트를 구현했습니다.
- 기존 실행 결과를 Python 규칙으로 집계하고 5개 원인 범주로 매핑했습니다.
- Agent 역할과 Checkpoint 검토 기준을 UI와 문서로 시연했습니다.
- Project1의 구현 간격을 확인하고 V2에서 Agent 1 Live 실행부터 보완하고 있습니다.

### 피해야 할 표현

- 네 개 AI Agent가 새 요구사항을 실제로 End-to-End 처리했습니다.
- AI가 새로운 TC와 Playwright 코드를 자동 생성해 실행했습니다.
- Checkpoint 3가 환경 실패 시 모든 후속 실행을 차단했습니다.
- Agent 4의 분류 정확도를 검증했습니다.
- False Positive를 0%로 만들었습니다.
- 기존 13건 결과가 제품 회귀 품질을 나타냅니다.

## 8. 공개 포트폴리오 표현 재점검

Project1 원본은 이번 문서 개편에서 수정하지 않았습니다. 다음 표현은 현재 구현보다 강하므로 포트폴리오 개편 시 수정 대상으로 관리합니다.

| 우선순위 | 위치·표현 | 실제 구현 | 권장 표현 |
|---|---|---|---|
| P0 | project.html의 Checkpoint 3가 사전 환경 점검 후 실행 증거를 승인·인계했다는 Before·After 사례 | TC-ENV-000은 일반 테스트이며 후속 차단 Gate와 독립 증거 승인 로직이 없음 | 환경 사전 점검과 실행 결과 검토 기준을 설계한 사례로 표시 |
| P0 | project.html의 Agent 4 오분류를 Checkpoint 4가 재분류했다는 Before·After 사례 | Agent 4는 conftest의 의미 라벨을 규칙으로 매핑하며 CP4에 의미 재분류 루프가 없음 | 규칙 기반 분류와 JSON·HTML 집계 정합성 검사로 표시 |
| P0 | interview 문서의 False Positive 0% 표현 | 독립 Ground Truth와 반복 평가가 없음 | 오분류 위험을 줄이기 위한 통제 기준을 설계했다고 표현 |
| P1 | Agent 1·2가 AI 산출물을 생성·검토해 다음 단계로 전달했다는 완료형 표현 | Prompt·샘플·Workflow Demo이며 실제 Live 인계가 아님 | Fixture 기반 역할·Checkpoint 시연이라고 표시 |
| P1 | Agent 1~4 QA 파이프라인 구동 영상 표현 | Agent 1~3 화면 일부는 Workflow Demo, Playwright와 Agent 4 규칙 코드는 실제 실행 | Demo와 실제 실행 구간을 분리 표기 |
| P1 | Agent 4 자동 분류를 품질 정확도 성과로 해석할 수 있는 표현 | 5개 범주 매핑은 구현됐지만 label leakage로 분류 정확도는 평가 불가 | 규칙 기반 원인 범주 매핑으로 한정 |
| P0 | `checkpoint2_review_after.md`의 모든 TC가 코드와 완벽히 일치하고 독립 실행이 보장된다는 표현 | TC-INT-002 비대상 불변 검증이 빠져 있고 일부 TC 계약·근거도 불완전함 | 검토 예시 문서이며 발견된 공백은 미해결 상태라고 표시 |
| P0 | `traceability_matrix.md`에서 전 TC의 Checkpoint 3 Pre-check 통과와 실행 증거를 완료형으로 표시 | 실제 독립 CP3 Gate가 없고 `evidence_path`도 비어 있음 | 기존 Test Run 매핑과 Report·JSON 기록만 사실로 표시 |
| P1 | project.html Hero의 AI가 동일한 품질 기준으로 테스트를 수행하도록 구조화했다는 표현 | Agent 1·2는 Fixture, Agent 3은 사람이 작성한 코드 실행임 | AI 역할·검토 기준을 시연했고 실제 실행은 Playwright·규칙 엔진이라고 분리 |
| P1 | README의 4-Agent·4-Checkpoint 및 Agent 1~4 흐름 설명 | 역할 구조는 있으나 네 단계 Live 인계가 구현된 것은 아님 | Fixture 기반 역할 시연과 실제 실행 구간을 같은 문단에서 구분 |

V2가 End-to-End로 구현되기 전에는 Project1 페이지에 Live Agent Pipeline 완료 표현을 추가하지 않습니다.

## 9. V2 사용 원칙

- Project1 원본 파일을 V2 실행 중 덮어쓰지 않습니다.
- 제품 SRS, 기존 TC, 테스트 하네스와 Pipeline Fixture를 서로 다른 입력 유형으로 표시합니다.
- 기존 자동화는 사람이 작성한 Reference Automation으로 부릅니다.
- Product SRS Requirement와 연결되지 않는 Fixture를 제품 결과에 포함하지 않습니다.
- 알려진 불일치를 정상 정책이나 Agent 정답으로 사용하지 않습니다.
