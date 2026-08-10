# 역설계 Baseline SRS 후보

> 상태: 사람 승인 전 `CANDIDATE`  
> 근거: `virtual-controller.html`, `tests/test_controller.py`, 기존 3-Tier QA 기준  
> 주의: 원본 기획 SRS가 아니라 화면·구현·테스트에서 역추출한 후보 기준이다.

## 1. 증거 상태

| 상태 | 의미 |
|---|---|
| `AUTOMATED_VERIFIED` | 화면·구현과 자동화 테스트로 확인 |
| `IMPLEMENTED_UNTESTED` | 구현은 있으나 자동화 검증 없음 |
| `SCREEN_ONLY` | 화면 표시만 존재하고 동작 검증 없음 |
| `DEMO_ONLY` | Workflow 시연용 고정 화면·데이터 |
| `KNOWN_DEVIATION` | 기대 기준과 현재 구현이 불일치 |
| `INCOMPLETE` | 함수·일부 UI만 있고 사용자 흐름 미완성 |

현재 동작을 무조건 정답으로 간주하지 않으며, Baseline 승인 전 QA가 기대값과 근거를 확정한다.

## 2. 시스템과 데이터 모델

- 대상: 브라우저 기반 가상 중앙제어 시스템
- 장비: 16대
- 내부 ID: 1~16
- 표시명: IDU-00~IDU-15
- ID 매핑: 내부 ID 1은 IDU-00이며 순차 증가
- 상태: OPERATION, STOP, ERROR, OFFLINE
- 모드: COOL, HEAT, FAN, DRY, AUTO
- 풍량: LOW, MED, HIGH, AUTO
- 관제점: 운전 상태, 운전 모드, 설정 온도, 풍량, 잠금, 오류 코드
- 관측면: 장치 카드, 제어 패널, QA 로그, Register View, `window.__vccs`

## 3. 장비·상태 관리

### REQ-ENV-001 장비 초기 로드

- 최초 로드 시 16대 장비를 제공한다.
- 초기값은 STOP, COOL, 설정 24°C, 현재 25°C, LOW, 잠금 해제, 오류 없음이다.
- 증거: 장치 배열, TC-ENV-000
- 상태: `AUTOMATED_VERIFIED`

### REQ-STATE-001 테스트 상태 초기화

- 초기화 확인 후 저장된 장비·게이트웨이·선택·복수 선택 상태를 제거하고 다시 로드한다.
- 각 TC는 이전 TC에 의존하지 않아야 한다.
- 증거: `resetSimulatorState`, `load_clean_simulator`
- 상태: `AUTOMATED_VERIFIED`

### REQ-STATE-002 상태 저장과 복원

- 장비, 게이트웨이, 선택 장비와 복수 선택 상태를 LocalStorage에 저장한다.
- 재진입 시 저장된 상태를 화면과 내부 상태에 복원한다.
- 상태: `IMPLEMENTED_UNTESTED`

## 4. 선택·Pending·Apply

### REQ-SELECT-001 단일 장비 선택

- 단일 선택 모드에서는 이전 선택을 해제하고 선택 장비를 제어 대상으로 표시한다.
- 선택 장비 상태를 제어 패널의 Pending 상태로 복사한다.
- 상태: 일부 `AUTOMATED_VERIFIED`

### REQ-CONTROL-001 Pending과 실제 적용 분리

- 제어 패널 선택만으로 실제 장비가 바뀌지 않는다.
- `적용` 실행 시 권한·통신·오류·잠금 조건을 통과한 변경만 반영한다.
- 적용 결과는 장치 카드, 내부 상태, Register와 로그에 반영되어야 한다.
- 상태: 주요 모드 경로 `AUTOMATED_VERIFIED`

### REQ-POWER-001 운전 상태 제어

- 선택 장비를 OPERATION 또는 STOP으로 설정할 수 있다.
- 결과는 장치 카드와 Register의 OPER 값에 반영되어야 한다.
- 상태: `IMPLEMENTED_UNTESTED`

## 5. 모드·온도·풍량

### REQ-MODE-001 운전 모드

- COOL, HEAT, FAN, DRY, AUTO를 지원한다.
- 적용된 모드는 UI, 내부 상태와 Register MODE에 일치해야 한다.
- 상태: `AUTOMATED_VERIFIED`

### REQ-MODE-002 FAN·DRY 온도 조작 제한

- FAN·DRY에서는 온도 증가·감소 버튼을 비활성화한다.
- 제어 패널, 장치 카드와 Register에서 온도 비활성 상태를 표현한다.
- 온도 제어 가능 모드로 복귀하면 다시 활성화한다.
- 상태: UI는 `AUTOMATED_VERIFIED`, Register는 `IMPLEMENTED_UNTESTED`

### REQ-TEMP-001 섭씨 상한

- 섭씨 상한은 30.0°C이다.
- 초과 입력을 차단하고 허용 범위를 알리며 표시값을 유지한다.
- 상태: `AUTOMATED_VERIFIED`

### REQ-TEMP-002 섭씨 하한 후보

- 화면과 3-Tier 기준은 16.0°C를 표시한다.
- 현재 구현은 의도적 결함으로 15.0°C까지 허용한다.
- 원본 SRS가 없으므로 승인 전 정책 확인이 필요하다.
- 상태: `KNOWN_DEVIATION`

### REQ-TEMP-003 온도 단위

- °C와 °F 화면 표시를 전환할 수 있다.
- °F는 내부 섭씨 값을 변환해 정수로 표시한다.
- 화면 범위는 16~30°C 또는 61~86°F이다.
- 내부 장치 기준 단위는 섭씨다.
- 상태: `IMPLEMENTED_UNTESTED`

### REQ-FAN-001 풍량

- LOW, MED, HIGH, AUTO를 지원한다.
- 화면은 약풍·중풍·강풍·자동, Register는 MED를 MIDDLE로 표시한다.
- 상태: `IMPLEMENTED_UNTESTED`

## 6. 잠금·오류·통신

### REQ-LOCK-001 중앙·현장 제어 차단

- 잠금 상태에서는 잠금 해제를 제외한 중앙 관제 명령을 차단한다.
- 현장 리모컨의 전원·온도 조작도 차단한다.
- 상태를 변경하지 않고 로그 또는 알림을 남긴다.
- 상태: `AUTOMATED_VERIFIED`

### REQ-ERROR-001 오류 주입과 차단

- QA 도구는 선택 장비에 CH05·CH21 오류를 주입할 수 있다.
- 오류 상태 장비의 중앙·현장 제어를 차단하고 오류 코드와 사유를 표시한다.
- 상태: CH05는 `AUTOMATED_VERIFIED`, CH21은 `IMPLEMENTED_UNTESTED`

### REQ-ERROR-002 오류 해제

- 게이트웨이가 온라인이면 오류를 해제할 수 있다.
- 오류 코드를 제거하고 장비 상태를 STOP으로 설정한다.
- 상태: `IMPLEMENTED_UNTESTED`

### REQ-GATEWAY-001 게이트웨이 상태

- QA 도구에서 온라인·오프라인 전환이 가능하다.
- 오프라인이면 모든 장비를 OFFLINE으로 표시하고 중앙 제어를 차단한다.
- 온라인 복구 시 오류 장비는 ERROR, 다른 OFFLINE 장비는 STOP으로 동기화한다.
- 상태: `IMPLEMENTED_UNTESTED`

### REQ-LOCAL-001 현장 리모컨

- 선택 장비의 전원 토글과 온도 증감을 제공한다.
- 잠금·오류·FAN·DRY 제한을 적용한다.
- 오프라인 경로는 주석과 실제 상태 갱신이 일치하지 않아 승인 범위에서 제외한다.
- 상태: 잠금 차단 일부 `AUTOMATED_VERIFIED`, 오프라인 `KNOWN_DEVIATION`

## 7. 복수 제어·정합성

### REQ-BATCH-001 복수 선택

- 복수 선택 모드에서 장비를 선택·해제할 수 있다.
- 단일 선택 복귀 시 마지막 선택 장비 한 대만 유지한다.
- 선택 목록을 저장한다.
- 상태: 일부 `AUTOMATED_VERIFIED`

### REQ-BATCH-002 일괄 적용

- 선택 장비 각각에 같은 Pending 값을 처리한다.
- 오류·잠금 장비는 개별 차단하고 처리 수를 알린다.
- 비대상 장비와 비대상 필드는 변경되지 않아야 한다.
- 상태: 대상 3대 모드 반영은 `AUTOMATED_VERIFIED`; 비대상 불변과 부분 실패 격리는 미검증

### REQ-TRACE-001 UI·내부 상태·Register 정합성

- 장치 카드 UI, 내부 장치 상태와 Register View를 교차 검증한다.
- Register는 OPER, MODE, FAN, TEMP, LOCK을 제공한다.
- UI만 보고 제품 상태를 확정하지 않는다.
- 상태: UI·내부는 `AUTOMATED_VERIFIED`, Register까지 3중 대조는 `IMPLEMENTED_UNTESTED`

## 8. 관측·테스트 지원

### REQ-OVERVIEW-001 운전 현황

- 운전·정지·오류 수와 비율을 표시한다.
- OFFLINE은 현재 정지 집계에 포함한다.
- 상태: `IMPLEMENTED_UNTESTED`

### REQ-LOG-001 QA 이벤트 로그

- SYSTEM, GATEWAY, LOCAL 출처와 시각·레벨·메시지를 최신순으로 표시한다.
- 로그는 보조 증거이며 제품 상태의 단독 SSOT가 아니다.
- 상태: 일부 `AUTOMATED_VERIFIED`

### REQ-BRIDGE-001 QA Bridge

- `window.__vccs`는 장비·Pending·선택·게이트웨이 상태와 Register Snapshot 접근을 제공한다.
- Playwright 전용 인터페이스이며 일반 사용자 기능이 아니다.
- 상태: 일부 `AUTOMATED_VERIFIED`

## 9. Baseline 제외·보류

### REQ-AUTH-001 권한 후보

- ADMIN·VIEWER 함수와 Viewer Overlay가 있으나 권한 전환 버튼이 없다.
- 상태: `INCOMPLETE`, Baseline 제외

### REQ-PURIFY-001 공기청정 후보

- UI는 최초 숨김이며 Agent Demo 완료 후 노출된다.
- 일부 운전·복원 코드는 있지만 자동화 검증이 없다.
- Demo의 HEAT·공기청정 상호배타 문구는 실제 차단 코드에서 확인되지 않는다.
- 상태: `DEMO_ONLY`와 `IMPLEMENTED_UNTESTED`, Baseline 제외

### REQ-FILTER-001 장비 필터 후보

- `모든 장치/상태` 선택 요소는 있지만 실제 필터 로직이 없다.
- 상태: `SCREEN_ONLY`, Baseline 제외

## 10. TC 자산 구분

### Core Regression 후보

- TC-ENV-000
- TC-MODE-001
- TC-MODE-002
- TC-MODE-003
- TC-LOCK-001
- TC-ERR-001
- TC-INT-002
- TC-TEMP-001

### 제품 결함 분류 Fixture

- TC-TEMP-002: 특정 18°C 조건을 공식 Baseline으로 고정하지 않고 Agent 4 제품 결함 분류 Fixture로 분리 검토

### Pipeline Control Fixture

- TC-PIPE-001: 요구사항 확인 필요
- TC-PIPE-002: 환경 문제
- TC-PIPE-003: 자동화 코드 문제
- TC-PIPE-004: 조건 부족 미실행

Fixture는 제품 기능 회귀 성공률과 분리한다.

## 11. 승인 전 결정 목록

- 공식 섭씨 하한과 모드별 범위
- TC-TEMP-002 Fixture 분리 방식
- 복수 제어의 비대상 불변 조건
- 게이트웨이 오프라인 현장 제어 정책
- 권한·공기청정·화씨·풍량의 Baseline 포함 여부
- 오류 해제 복원 범위와 OFFLINE 집계 정책

결정 전에는 본 문서를 `Approved SRS V1.0`이라고 부르지 않는다.
