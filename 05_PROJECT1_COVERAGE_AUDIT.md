# 프로젝트 1 V2 검증·추적성·Gap Register

## 문서 통제

| 항목 | 값 |
|---|---|
| 문서 ID | VTR-V2-001 |
| 버전 | 0.2 |
| 상태 | LIVING_DOCUMENT |
| 소유자 | QA |
| 기준 SRS | SRS-VCCS-BL-001 v0.2 |
| 대상 형상 | qa-agent-pipeline V1 main |
| 검토일 | 2026-08-10 |

## 1. 목적

본 문서는 Baseline SRS 후보의 각 Requirement를 현재 화면, 구현 함수, Playwright TC와 연결하고 검증 공백을 관리합니다. 또한 V1 Workflow Demo와 V2 목표 구현 사이의 차이를 우선순위로 관리합니다.

이 문서는 테스트가 많아 보이게 만드는 목록이 아닙니다. 다음 질문에 답해야 합니다.

- Requirement가 실제 구현 또는 화면 어디에 존재하는가
- 현재 자동화가 어떤 관측면을 검증하는가
- 무엇이 아직 미검증 또는 불일치인가
- V2 구현 전에 무엇을 결정·보완해야 하는가
- 포트폴리오에서 어디까지 사실로 표현할 수 있는가

## 2. 검토 기준

### 2.1 소스

| Source | 확인 범위 |
|---|---|
| virtual-controller.html | UI, 상태 모델, 제어·차단·저장·QA Bridge |
| tests/test_controller.py | 13개 Pytest/Playwright 시나리오 |
| tests/conftest.py | 실행 결과 수집과 분류 입력 |
| scripts/agent4_reporting.py | 결정론적 분류·보고·Checkpoint 4 |
| 기존 3-Tier 문서 | TC 품질 기준 |
| 포트폴리오 화면 | 프로젝트 주장과 Demo 표시 |

### 2.2 검증 상태

| 상태 | 정의 |
|---|---|
| VERIFIED | 요구사항 핵심 결과가 자동화로 확인 |
| PARTIAL | 일부 경로·관측면·장비만 확인 |
| IMPLEMENTED | 코드만 있고 자동화 없음 |
| GAP | 요구사항 또는 필수 Assertion이 없음 |
| DEVIATION | 후보 기준과 구현 불일치 |
| EXCLUDED | 승인 Baseline 범위 밖 |
| FIXTURE_ONLY | 제품 검증이 아니라 분류·Pipeline 시연 데이터 |

## 3. 제품 Requirement 추적성

| Requirement | 구현·화면 근거 | 연결 TC | 상태 | 주요 Gap | V2 처리 |
|---|---|---|---|---|---|
| REQ-ENV-001 | devices 초기 배열, renderGrid | TC-ENV-000 | VERIFIED | 초기 Register 전체 비교 제한 | Baseline 유지 |
| REQ-STATE-001 | resetSimulatorState, load_clean_simulator | 공통 Setup | VERIFIED | Reset 실패 Gate 없음 | Executor에서 차단 |
| REQ-STATE-002 | saveStateToLocalStorage | 없음 | IMPLEMENTED | 재진입·손상 데이터 검증 없음 | 회귀 후보 |
| REQ-SELECT-001 | selectUnit, updatePanelUI | 다수 TC 간접 | PARTIAL | 선택만으로 상태 불변 명시 부족 | 독립 TC 후보 |
| REQ-CONTROL-001 | setPanel 계열, applyPanelCommands | TC-MODE-001~003 | PARTIAL | 모든 필드의 Apply 전 불변 미검증 | Agent 2 기준 반영 |
| REQ-POWER-001 | setPanelPower | TC-MODE-001 간접 | PARTIAL | STOP·차단·비대상 불변 전용 TC 없음 | 회귀 후보 |
| REQ-MODE-001 | setPanelMode, Register MODE | TC-MODE-001, 003, TC-INT-002 | VERIFIED | 5개 모드 전체 조합은 미검증 | Core 유지 |
| REQ-MODE-002 | updatePanelUI, TEMP -- | TC-MODE-002, 003 | PARTIAL | Register TEMP와 내부 불변 전체 대조 부족 | Assertion 보강 |
| REQ-TEMP-001 | adjustPanelTemp 상한 | TC-TEMP-001 | VERIFIED | 내부·Register 상한 동시 검증 제한 | Double-Assert 보강 |
| REQ-TEMP-002 | 화면 16°C, 코드 15°C | 없음 | DEVIATION | 공식 하한 미승인·구현 결함 | 사람 결정 후 수정 |
| REQ-TEMP-003 | switchTempUnit | 없음 | IMPLEMENTED | 반올림·왕복 변환·경계 미검증 | 별도 TC 후보 |
| REQ-FAN-001 | setPanelFan, MED→MIDDLE | 없음 | IMPLEMENTED | 풍량 전체 매핑·적용 미검증 | 별도 TC 후보 |
| REQ-LOCK-001 | 중앙·현장 차단 | TC-LOCK-001 | VERIFIED | 복수 선택 부분 잠금 상세 결과 제한 | Core 유지·확장 |
| REQ-ERROR-001 | injectSelectedError | TC-ERR-001 | PARTIAL | CH21·복수 오류·Register 상세 미검증 | Feature 회귀 |
| REQ-ERROR-002 | clearSelectedError | 없음 | IMPLEMENTED | STOP 복구 정책 미승인 | 정책 결정 후 TC |
| REQ-GATEWAY-001 | setGatewayState | 제품 TC 없음 | IMPLEMENTED | TC-PIPE-002는 환경 Fixture일 뿐 | 제품 TC 신규 |
| REQ-LOCAL-001 | simulateLocalPower | 차단 경로 일부 | PARTIAL | 정상 토글·오프라인 정책 미검증 | 정책 결정 |
| REQ-LOCAL-002 | simulateLocalTemp | TC-LOCK-001 일부 | PARTIAL | 오류·모드·경계 조합 미검증 | Feature TC |
| REQ-BATCH-001 | toggleMultiSelectMode, selectUnit | TC-INT-002 | PARTIAL | 해제·단일 복귀·저장 미검증 | TC 분리 |
| REQ-BATCH-002 | applyPanelCommands 반복 처리 | TC-INT-002 | PARTIAL | 비대상 장비·필드 불변 누락 | P0 Assertion 보강 |
| REQ-TRACE-001 | renderGrid, Register, QA Bridge | TC-MODE-001~003 | PARTIAL | 전 TC 3중 대조 아님 | 관측 정책 명시 |
| REQ-OVERVIEW-001 | calculateOverview | 없음 | IMPLEMENTED | OFFLINE 집계 정책·합계 미검증 | 정책 결정·TC |
| REQ-LOG-001 | appendQALog | 다수 TC 일부 | PARTIAL | 로그 Schema·순서·삭제 미검증 | 증거 계약 보강 |
| REQ-BRIDGE-001 | window.__vccs, getRegisterSnapshot | 다수 TC | PARTIAL | 허용 함수·타입·읽기 전용 계약 없음 | Agent 3 계약화 |
| REQ-AUTH-001 | switchUserRole, Overlay | 없음 | EXCLUDED | 역할 전환 버튼 없음 | Baseline 제외 |
| REQ-PURIFY-001 | 숨김 UI·부분 로직 | 없음 | EXCLUDED | Demo 후 노출, 정책·TC 없음 | 별도 변경 요청 |
| REQ-FILTER-001 | Select UI | 없음 | EXCLUDED | 필터 동작 없음 | 별도 변경 요청 |

## 4. 기존 TC 자산 분류

### 4.1 Product Core Regression 후보

| TC ID | 목적 | 주요 Requirement | 현재 판정 |
|---|---|---|---|
| TC-ENV-000 | 환경·장비 사전 점검 | REQ-ENV-001, REQ-STATE-001 | Core 후보 |
| TC-MODE-001 | HEAT 적용과 상태 정합성 | REQ-CONTROL-001, REQ-MODE-001, REQ-TRACE-001 | Core 후보 |
| TC-MODE-002 | FAN 온도 비활성 | REQ-MODE-002 | Core 후보 |
| TC-MODE-003 | DRY 비활성 후 COOL 복귀 | REQ-MODE-001, 002 | Core 후보 |
| TC-LOCK-001 | 16대 잠금·중앙·현장 차단 | REQ-LOCK-001 | Core 후보 |
| TC-ERR-001 | CH05 오류와 제어 차단 | REQ-ERROR-001 | Core 후보 |
| TC-INT-002 | 3대 복수 HEAT 적용 | REQ-BATCH-001, 002 | 수정 필요 |
| TC-TEMP-001 | 30°C 상한 | REQ-TEMP-001 | Core 후보 |

TC-INT-002는 핵심 위험인 비대상 장비 불변을 검증하지 않아 CP2 기준상 그대로 승인하기 어렵습니다.

### 4.2 Product Classification Fixture

| TC ID | 목적 | 처리 |
|---|---|---|
| TC-TEMP-002 | AUTO 18°C 조건 실패를 제품 결함 후보로 분류 | 제품 Baseline에서 분리, Agent 4 분류 Fixture |

AUTO 18°C는 현재 Baseline SRS의 공식 정책이 아닙니다. 해당 TC를 제품 회귀 성공률에 포함하지 않습니다.

### 4.3 Pipeline Control Fixture

| TC ID | 기대 분류 | 의미 |
|---|---|---|
| TC-PIPE-001 | REQUIREMENT_REVIEW | 기대결과 근거 부족 |
| TC-PIPE-002 | ENVIRONMENT_ISSUE | 시뮬레이터 미응답 |
| TC-PIPE-003 | AUTOMATION_EXECUTION_ERROR | 요소 식별 정보 불일치 |
| TC-PIPE-004 | NOT_EXECUTED | 실행 전제 부족 |

Pipeline Fixture는 제품 기능 테스트 수, PASS Rate와 분리해 보고합니다.

## 5. V1 Workflow 사실 감사

| 영역 | 화면 표현 | 현재 실제 | V2 요구 |
|---|---|---|---|
| 변경 입력 | 자유 입력·Jira·파일 | Jira·파일은 고정 문자열 Demo | Canonical Input 연결 |
| Agent 1 | 요구사항 정제 | 타이머·고정 분석 | 실제 모델 Adapter |
| CP1 | 충분성 판단 | 화면 Demo | 결정론적 Grader |
| Agent 2 | TC 생성 | 고정 TC 데이터 | Agent 1 Artifact 입력 |
| CP2 | TC 승인·반려 | Prompt·Sample | Rule별 구조화 결과 |
| Agent 3 | 자동화 실행 | 기존 수동 작성 Pytest 실행 | 코드 후보 생성·격리 |
| CP3 | 실행 증거 신뢰 | 독립 Gate 미구현 | 정적·반복·오류 검출 |
| Agent 4 | 분석·보고 | Python 규칙 엔진 실제 | V2 Run 계약 수용 |
| CP4 | 수치 일관성 | 일부 실제 검사 | Source Run 교차대조 |
| Dashboard | Agent 진행 | 타이머 기반 Demo 모달 | Run Manifest 표시 |
| Slack·Notion | 보고 연동 | 별도 실행·Demo 자료 | V2 MVP 제외 |

## 6. 확인된 제품 편차와 미확정 정책

### GAP-PROD-001 온도 하한

- 후보 정책: 화면·3-Tier 기준 16.0°C
- 현재 구현: 15.0°C까지 허용
- 위험: 화면 안내와 실제 제어가 불일치
- 조치: DEC-001 승인 후 구현 또는 문서 수정
- 우선순위: P0

### GAP-PROD-002 복수 제어 불변성

- TC-INT-002는 선택 3대의 HEAT 적용만 확인합니다.
- 비대상 장비 4~16과 비대상 필드 불변을 확인하지 않습니다.
- 위험: 상태 오염을 놓칠 수 있음
- 조치: Snapshot 기반 unchanged assertion 추가
- 우선순위: P0

### GAP-PROD-003 게이트웨이 제품 TC 부재

- Gateway 함수는 구현되어 있지만 제품 기능 TC가 없습니다.
- TC-PIPE-002는 원인 분류 Fixture이므로 대체할 수 없습니다.
- 조치: 오프라인 차단·온라인 복구·상태 동기화 TC 설계
- 우선순위: P1

### GAP-PROD-004 오프라인 현장 제어 정책

- 코드 주석은 로컬 제어 작동을 설명합니다.
- 실제 함수는 로그만 남기고 상태를 변경하지 않습니다.
- 조치: DEC-005 사람 결정 후 SRS·구현·TC 동기화
- 우선순위: P1

### GAP-PROD-005 오류·복구 상태

- 오류 해제와 게이트웨이 복구는 STOP으로 돌아갑니다.
- 이전 OPERATION 복원 여부의 원본 정책이 없습니다.
- 조치: DEC-003·004 결정
- 우선순위: P1

### GAP-PROD-006 화면만 있는 후보 기능

- 권한은 함수·Overlay가 있지만 전환 UI가 없습니다.
- 공기청정은 Demo 후 노출되고 정책 검증이 없습니다.
- 필터는 화면 요소만 있고 동작이 없습니다.
- 조치: V2 MVP Baseline에서 제외
- 우선순위: P2

## 7. Agentic Runtime Gap

### P0 — Live Pipeline 성립에 필수

| ID | Gap | 완료 증거 |
|---|---|---|
| GAP-AI-001 | 실제 모델 Adapter 없음 | 다른 입력에 다른 Agent 1 결과 |
| GAP-AI-002 | Agent 1→2 실제 인계 없음 | CP1 승인 Artifact ID가 Agent 2 입력에 존재 |
| GAP-AI-003 | Agent 2→3 실제 인계 없음 | TC Snapshot 해시가 코드 Manifest에 존재 |
| GAP-AI-004 | Agent 3 코드 후보 생성 없음 | Run별 candidate test 파일 |
| GAP-AI-005 | 후보 격리·Restore 없음 | 정상 3회·오류 프로필·복원 증거 |
| GAP-AI-006 | 사람 Promotion Gate 없음 | 승인 Artifact 없이는 Executor 차단 |
| GAP-AI-007 | Run Manifest·Artifact Store 없음 | 입력부터 보고까지 ID 추적 |
| GAP-AI-008 | Dashboard가 실제 상태를 표시하지 않음 | Backend Manifest 기반 단계 상태 |

### P1 — 신뢰성 강화

| ID | Gap | 완료 증거 |
|---|---|---|
| GAP-QA-001 | CP1·2 구조화 Grader 없음 | Rule별 PASS·FAIL·REVIEW |
| GAP-QA-002 | CP3 Assertion 매핑 없음 | expected_result 100% 연결 |
| GAP-QA-003 | Agent 4 Source Run 교차대조 부족 | A3·A4·CP4 단일 Run 검증 |
| GAP-QA-004 | 실패 증거 경로 미완성 | FAIL마다 Trace·Screenshot·상태 |
| GAP-QA-005 | setup·teardown 결과 수집 제한 | 모든 pytest phase 기록 |
| GAP-QA-006 | Agent 반복 품질 데이터 없음 | 프로젝트 2 Eval Dataset |

### P2 — MVP 이후

- ADDED·DELETED 지원
- Full Regression 조건부 실행기
- 사용자 질문 후 중단 단계 재개
- 여러 모델·Prompt 비교
- Failure Triage 확장
- 외부 협업 도구 보고

## 8. Requirement Coverage 요약

| 분류 | 수량 | 비고 |
|---|---:|---|
| SRS Requirement | 27 | 제외 후보 포함 |
| VERIFIED | 5 | 핵심 자동화 확인 |
| PARTIAL | 12 | 일부 경로·관측면 |
| IMPLEMENTED | 6 | 전용 자동화 없음 |
| DEVIATION | 1 | 온도 하한 |
| EXCLUDED | 3 | 권한·공기청정·필터 |

분류는 요구사항별 대표 상태입니다. 부분 검증을 완료로 계산하지 않습니다.

## 9. 검증 우선순위

### 9.1 SRS 승인 전

1. DEC-001 공식 온도 하한
2. DEC-003·004 오류·Gateway 복구 상태
3. DEC-005 오프라인 현장 제어
4. DEC-006 OFFLINE 집계
5. DEC-007 복수 제어 부분 성공 계약

### 9.2 V2 구현 전

1. Baseline Snapshot·해시
2. Run Manifest·Artifact ID
3. Agent 1·2 계약 Grader
4. Agent 3 Sandbox·금지 코드
5. Human Promotion Gate
6. Source Run 교차대조

### 9.3 포트폴리오 동기화 전

1. Fixture·Live 배지
2. 실제 모델·Playwright 호출 여부
3. Run ID·모델·Prompt 버전
4. 실제 생성 TC·코드 Diff
5. 정상 반복·오류 검출 증거
6. 보고 수치와 원본 JSON 대조

## 10. V2 MVP 추적성 종료선

다음 연결이 한 변경 Run에서 모두 확인되어야 합니다.

    Change Request
      → Baseline Requirement
      → Agent 1 Change Item
      → Agent 2 Product Functional TC
      → Expected Result
      → Agent 3 Assertion
      → Candidate Trial
      → Human Approval
      → Product Validation Result
      → Agent 4 Classification
      → CP4 Final Report

각 화살표는 Artifact ID 또는 Source ID를 가져야 합니다.

## 11. 검토 시나리오

### Scenario A — 명확한 MODIFIED 요청

- Baseline Requirement 존재
- 변경 전후와 기대결과 명확
- Agent 1 PROCEED
- Agent 2 TC 변경안
- Agent 3 코드 후보
- Promotion Gate와 제품 검증

### Scenario B — 핵심 기대결과 부족

- 대상 기능은 식별 가능
- 복원·예외 정책이 없음
- Agent 1 WAITING_FOR_USER 또는 PARTIAL
- 답변 전 모호한 범위 TC 생성 금지

### Scenario C — 근거 없는 Agent 출력

- Baseline·요청에 없는 경계값 생성
- CP1 또는 CP2 Critical FAIL
- 1회 수정 후에도 남으면 BLOCKED

### Scenario D — 코드가 기대값을 변경

- TC 기대결과와 Assertion 상수 불일치
- CP3 Critical FAIL
- 제품 판정 사용 금지

### Scenario E — 정상 PASS지만 오류를 검출하지 못함

- 정상 3회 PASS
- 대표 오류 프로필도 PASS
- 검출력 부족으로 PROMOTION 차단

## 12. 포트폴리오 Claim 경계

현재 말할 수 있음:

- 중앙제어 도메인 규칙을 3-Tier QA 기준과 Playwright TC로 구조화했습니다.
- 기존 V1은 Fixture 기반 Workflow와 실제 회귀 실행을 결합한 프로토타입입니다.
- V2는 변경 입력, Agent 산출물, 코드 후보와 실행 증거를 실제 Artifact로 연결하도록 설계했습니다.
- Agent 4는 결정론적 규칙 기반 결과 분석기입니다.

Live 구현 후에만 말할 수 있음:

- 새 변경 요청으로 Agent 1·2·3이 실제 산출물을 생성합니다.
- 생성 TC가 실제 Playwright 코드 후보로 연결됩니다.
- 반복 실행과 대표 오류로 코드 후보를 검증합니다.
- 사람 승인 후 변경 검증과 회귀를 실행합니다.

말하면 안 됨:

- V1에서 AI Agent 4개가 실제로 협업해 TC와 코드를 생성함
- 생성 코드가 신뢰성을 보장함
- 모든 변경과 결함을 자동 처리함
- Full Regression과 운영 시스템 연동 완료
- Checkpoint가 자연어 의미를 완벽히 판정함

## 13. 업데이트 규칙

- SRS Requirement가 변경되면 본 매트릭스를 같은 커밋에서 검토합니다.
- TC가 추가·수정되면 Requirement와 검증 관측면을 기록합니다.
- 구현과 SRS가 다르면 자동으로 SRS를 구현에 맞추지 않습니다.
- Gap 해결 시 코드·TC·실행 Artifact를 증거로 연결합니다.
- 상태는 실제 증거 없이 VERIFIED로 승격하지 않습니다.
- 문서 검토일과 기준 커밋을 갱신합니다.
