# 시스템 요구사항 명세서 — 가상 중앙제어 시스템 Baseline 후보

## 문서 통제

| 항목 | 값 |
|---|---|
| 문서 ID | SRS-VCCS-BL-001 |
| 문서 버전 | 0.2 |
| 문서 상태 | CANDIDATE |
| 대상 시스템 | Virtual Central Control System |
| 기준 형상 | qa-agent-pipeline V1 화면·코드·Playwright TC |
| 작성 방식 | 화면·구현·테스트 역추적 |
| 문서 소유자 | QA |
| 승인 상태 | 미승인 |
| 작성일 | 2026-08-10 |

> 이 문서는 원본 기획 SRS가 아니라 현재 화면, JavaScript 구현과 Playwright 테스트에서 역추출한 Baseline 후보입니다. 구현된 동작을 무조건 정상 요구사항으로 간주하지 않으며, 미확정 정책은 TBD 또는 KNOWN_DEVIATION으로 분리합니다.

### 변경 이력

| 버전 | 변경 내용 | 승인 |
|---|---|---|
| 0.1 | 구현·화면·TC 기반 요구사항 목록 작성 | 미승인 |
| 0.2 | 문서 통제, 상태 모델, 우선순위, 정상·예외 흐름, 인수 조건과 추적성 추가 | 검토 요청 |

## 1. 목적

본 문서는 다음 두 목적을 가집니다.

1. 현재 가상 중앙제어 시스템의 승인 가능한 제품 기준을 사람이 검토할 수 있는 형태로 정의합니다.
2. V2 Agent 1이 변경 요청을 분석할 때 참조할 Baseline 후보를 제공합니다.

본 문서는 테스트 방법만을 설명하지 않습니다. 시스템이 어떤 조건에서 어떤 결과를 제공해야 하는지를 정의하고, 검증 수단은 각 요구사항의 추적성 항목으로 연결합니다.

## 2. 적용 범위

### 2.1 포함 범위

- 16대 가상 실내기의 초기 상태와 식별 체계
- 단일·복수 장비 선택
- 중앙 제어 패널의 Pending 상태와 적용
- 운전, 정지, 모드, 설정 온도, 풍량과 잠금
- 게이트웨이 온라인·오프라인
- CH05·CH21 오류 주입과 해제
- 현장 리모컨 전원·온도 조작
- 장치 카드, 내부 상태와 Register View 정합성
- 상태 저장·초기화
- QA 로그와 Playwright용 QA Bridge
- 테스트 지원 기능과 현재 구현 편차

### 2.2 제외 범위

- 실제 Modbus·MQTT 패킷 송수신
- 실제 장비·운영 서버·사용자 인증
- 다중 사용자 동시 제어와 충돌 해결
- 장기 이력 보관과 감사 서버
- 실제 네트워크 지연·재전송·장애 복구
- 모바일 앱과 현장 하드웨어 펌웨어
- 공기청정·권한·필터의 승인 Baseline 편입
- Agent 1~4 Workflow Demo의 제품 기능 요구사항화

## 3. 참조 자료와 증거 등급

### 3.1 참조 자료

| 참조 ID | 자료 | 용도 |
|---|---|---|
| SRC-UI-001 | virtual-controller.html | 화면·상태·업무 규칙 근거 |
| SRC-TC-001 | tests/test_controller.py | 자동화 검증 근거 |
| SRC-QA-001 | 기존 3-Tier QA 기준 | 테스트 품질과 Double-Assert 기준 |
| SRC-RPT-001 | V1 실행 결과와 Agent 4 보고 | 결과 분류·정합성 근거 |

### 3.2 증거 상태

| 상태 | 판정 기준 |
|---|---|
| AUTOMATED_VERIFIED | 구현과 자동화 테스트 결과가 확인됨 |
| PARTIALLY_VERIFIED | 일부 경로 또는 관측면만 자동화 확인 |
| IMPLEMENTED_UNTESTED | 코드 구현은 확인했으나 자동화 검증 없음 |
| SCREEN_ONLY | 화면 요소만 있고 동작 근거 없음 |
| DEMO_ONLY | Workflow 시연용 고정 데이터 또는 애니메이션 |
| KNOWN_DEVIATION | 후보 요구사항과 현재 구현이 불일치 |
| INCOMPLETE | 일부 함수 또는 UI만 있고 사용자 흐름이 완성되지 않음 |
| TBD | 정책·기대결과를 사람 승인으로 결정해야 함 |

증거 상태는 요구사항의 승인 상태와 다릅니다. 자동화가 통과해도 원본 정책 근거가 없으면 CANDIDATE일 수 있습니다.

## 4. 사용자와 시스템 Actor

| Actor | 역할 | 허용 범위 |
|---|---|---|
| 중앙 관제 사용자 | 장비 선택과 중앙 제어 명령 수행 | 승인된 제어 기능 |
| 현장 사용자 | 선택 장비의 로컬 전원·온도 조작 | 잠금·오류·모드 정책 적용 |
| QA 사용자 | 게이트웨이 전환, 오류 주입·해제, 상태 초기화 | 로컬 시뮬레이터 한정 |
| 가상 게이트웨이 | 중앙 명령 전달과 장비 상태 동기화 | 온라인 상태에서만 중앙 명령 전달 |
| 가상 실내기 | 상태·모드·온도·풍량·잠금·오류 보유 | 장비별 상태 전이 |
| Playwright 실행기 | UI·내부 상태·Register 검증 | QA Bridge 읽기와 허용된 조작 |
| Viewer 역할 후보 | 조회만 허용 | 사용자 전환 UI 미완성으로 Baseline 제외 |

## 5. 시스템 구성과 관측면

    중앙 관제 사용자
          ↓
    장비 카드 / 제어 패널의 Pending 상태
          ↓ 적용
    권한 → 게이트웨이 → 오류 → 잠금 → 기능 제약 검사
          ↓
    내부 장비 상태
       ↙    ↓     ↘
    장치 카드  Register  QA 로그
          ↓
    Playwright와 window.__vccs 교차 검증

제품 상태의 기준은 JavaScript 내부 장비 상태이며, UI와 Register는 해당 상태를 표현하는 관측면입니다. QA 로그는 보조 증거이며 단독 판정 기준으로 사용하지 않습니다.

## 6. 데이터 모델

### 6.1 장비 식별

| 항목 | 규칙 |
|---|---|
| 장비 수 | 16대 |
| 내부 ID | 1부터 16까지의 정수 |
| 표시명 | IDU-00부터 IDU-15 |
| 매핑 | 내부 ID 1은 IDU-00이며 순차 증가 |
| 선택 식별자 | selectedUnitId와 selectedUnitIds |

### 6.2 장비 상태

| 필드 | 허용값 | 초기값 | 설명 |
|---|---|---|---|
| status | OPERATION, STOP, ERROR, OFFLINE | STOP | 운전 및 통신 상태 |
| mode | COOL, HEAT, FAN, DRY, AUTO | COOL | 운전 모드 |
| currentTemp | 실수 | 25.0°C | 현재 온도 표시 |
| setTemp | 실수 | 24.0°C | 내부 설정 온도 |
| fanSpeed | LOW, MED, HIGH, AUTO | LOW | 풍량 |
| locked | true, false | false | 중앙·현장 제어 잠금 |
| errorCode | null, CH05, CH21 | null | 오류 코드 |
| purify | true, false | false | 공기청정 후보 기능 |

### 6.3 Pending 상태

Pending 상태는 사용자가 제어 패널에서 선택한 값이며 적용 전 실제 장비 상태와 구분합니다.

| 규칙 | 설명 |
|---|---|
| 초기화 | 마지막으로 선택한 장비의 현재 상태를 복사 |
| 변경 | 패널 조작은 Pending만 변경 |
| 적용 | 적용 버튼에서 선택 장비에 반영 |
| 복수 선택 | 마지막 선택 장비 값을 Pending 초기값으로 사용 |
| 금지 | Pending 값을 제품 적용 결과로 보고하지 않음 |

### 6.4 Register 매핑

| 제품 필드 | Register | 표시 규칙 |
|---|---|---|
| status | OPER | OPERATION=ON, STOP·OFFLINE=OFF, ERROR=ERROR |
| mode | MODE | COOL, HEAT, FAN, DRY, AUTO |
| fanSpeed | FAN | MED는 MIDDLE, 나머지는 동일 |
| setTemp | TEMP | FAN·DRY는 --, 그 외 소수점 한 자리 °C |
| locked | LOCK | true=ON, false=OFF |

OFFLINE을 OPER=OFF로 표시하는 현재 구현은 통신 상태를 독립 Register로 제공하지 않으므로 해석상 한계가 있습니다.

## 7. 상태 전이와 제어 우선순위

### 7.1 장비 상태 전이

| 현재 상태 | 이벤트 | 다음 상태 | 비고 |
|---|---|---|---|
| STOP | 운전 적용 | OPERATION | 중앙 또는 정상 현장 제어 |
| OPERATION | 정지 적용 | STOP | 중앙 또는 정상 현장 제어 |
| STOP·OPERATION | 오류 주입 | ERROR | errorCode 설정 |
| ERROR | 오류 해제 | STOP | 이전 운전 상태 복원 안 함 |
| 모든 상태 | 게이트웨이 오프라인 | OFFLINE | 모든 장비 일괄 |
| OFFLINE | 게이트웨이 온라인 | STOP 또는 ERROR | errorCode 존재 시 ERROR |
| 잠금 해제 | 잠금 적용 | 기존 status 유지 | locked만 true |
| 잠금 | 잠금 해제 적용 | 기존 status 유지 | locked만 false |

### 7.2 중앙 명령 판정 순서

1. Viewer 역할 여부
2. 게이트웨이 온라인 여부
3. 선택 장비 존재 여부
4. 장비 오류 여부
5. 장비 잠금 여부
6. 모드·온도 등 기능별 제약
7. 실제 값 변경 여부
8. 상태 반영·로그·저장

상위 조건에서 차단되면 하위 제어를 적용하지 않아야 합니다.

### 7.3 현장 명령 판정 순서

1. 장비 잠금 여부
2. 장비 오류 여부
3. 게이트웨이 오프라인 정책
4. FAN·DRY 온도 제한
5. 온도 경계값
6. 상태 반영·로그·저장

오프라인 현장 제어는 주석과 실제 구현이 불일치하므로 승인 전 TBD입니다.

## 8. 공통 품질 규칙

### BR-COMMON-001 판정 가능한 결과

모든 상태 변경 요구사항은 적용 대상, 초기 상태, 입력, 변경 후 상태와 상태 불변 항목을 식별할 수 있어야 합니다.

### BR-COMMON-002 Double-Assert

상태 변경 기능은 가능한 경우 다음 두 관측면 이상을 검증해야 합니다.

- 사용자 관측면: 장치 카드, 제어 패널, Toast
- 시스템 관측면: 내부 장비 상태, Register, command result

단순 CSS 존재 여부만으로 제품 상태를 확정하지 않습니다.

### BR-COMMON-003 차단 시 불변성

권한·오프라인·오류·잠금·경계값으로 명령이 차단되면 해당 명령이 변경하려던 제품 상태는 유지되어야 합니다.

### BR-COMMON-004 부분 성공

복수 제어는 장비별 조건을 평가하며 일부 장비가 차단되어도 적용 가능한 장비의 결과를 별도로 기록할 수 있습니다. 단, 처리 수와 장비별 사유가 구분되어야 합니다.

### BR-COMMON-005 테스트 독립성

각 자동화 TC는 이전 TC의 상태를 전제로 하지 않으며 실행 전 초기화와 실행 후 필요한 복원을 정의해야 합니다.

## 9. 기능 요구사항

### REQ-ENV-001 장비 초기 로드

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | SRC-UI-001, SRC-TC-001 |
| 증거 | AUTOMATED_VERIFIED |
| 연결 TC | TC-ENV-000 |

시스템은 최초 정상 로드 시 내부 ID 1~16에 대응하는 16대의 장비를 제공해야 합니다. 각 장비는 STOP, COOL, 현재 25.0°C, 설정 24.0°C, LOW, 잠금 해제, 오류 없음으로 초기화되어야 합니다.

인수 조건:

- 최초 로드 후 장비 배열과 카드 수가 각각 16이어야 합니다.
- 각 내부 ID와 IDU 표시명이 중복 없이 매핑되어야 합니다.
- 모든 장비의 필수 상태 필드가 존재해야 합니다.
- 초기 Register 값이 장비 초기 상태와 일치해야 합니다.

### REQ-STATE-001 테스트 상태 초기화

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | resetSimulatorState, load_clean_simulator |
| 증거 | AUTOMATED_VERIFIED |
| 연결 TC | 모든 자동화 TC의 공통 Setup |

사용자가 초기화를 확인하면 시스템은 저장된 장비, 게이트웨이, 선택 장비와 복수 선택 상태를 제거하고 기본 상태로 다시 로드해야 합니다. 취소하면 기존 상태를 유지해야 합니다.

인수 조건:

- 확인 후 관련 LocalStorage 키가 제거되어야 합니다.
- 재로드 후 REQ-ENV-001의 초기값을 만족해야 합니다.
- 이전 테스트의 선택·오류·잠금·게이트웨이 상태가 남지 않아야 합니다.
- 초기화 실패 시 후속 자동화 결과를 유효로 판정하지 않아야 합니다.

### REQ-STATE-002 상태 저장과 복원

| 속성 | 값 |
|---|---|
| 우선순위 | Medium |
| 근거 | saveStateToLocalStorage |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | 없음 |

시스템은 장비 상태, 게이트웨이 상태, 선택 장비 목록과 복수 선택 모드를 LocalStorage에 저장해야 합니다. 동일 브라우저에서 재진입하면 저장 상태를 화면과 내부 모델에 복원해야 합니다.

인수 조건:

- 저장 대상 네 종류가 독립 키로 기록되어야 합니다.
- 손상되거나 누락된 저장값은 기본값으로 안전하게 복구되어야 합니다. 현재 예외 처리는 확인 필요합니다.
- 복원 후 장치 카드, 제어 패널과 Register가 동일 상태를 표시해야 합니다.

### REQ-SELECT-001 단일 장비 선택

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | selectUnit, updatePanelUI |
| 증거 | PARTIALLY_VERIFIED |
| 연결 TC | TC-MODE-001 등 기능 TC 공통 |

단일 선택 모드에서 장비를 선택하면 이전 선택을 해제하고 한 대만 제어 대상으로 표시해야 합니다. 선택 장비의 상태는 Pending 상태에 복사되어야 하며 실제 장비 값은 변경되지 않아야 합니다.

인수 조건:

- selectedUnitIds에는 선택한 장비 ID 하나만 있어야 합니다.
- 선택 카드 한 개만 selected 상태여야 합니다.
- 패널 헤더는 장비명, ID, 상태와 오류 코드를 표시해야 합니다.
- 선택만으로 내부 장비 상태와 Register가 변경되지 않아야 합니다.

### REQ-CONTROL-001 Pending과 실제 적용 분리

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | setPanel 계열 함수, applyPanelCommands |
| 증거 | PARTIALLY_VERIFIED |
| 연결 TC | TC-MODE-001, TC-MODE-002, TC-MODE-003 |

패널 조작은 Pending 상태만 변경해야 하며 적용 버튼 실행 전에는 장비 상태를 변경하지 않아야 합니다. 적용 시에는 제어 우선순위를 통과한 항목만 실제 장비에 반영해야 합니다.

인수 조건:

- 패널에서 모드·온도·풍량을 변경한 직후 내부 장비 값은 유지되어야 합니다.
- 적용 후 장치 카드, 내부 상태와 Register 값이 갱신되어야 합니다.
- 변경 항목이 없으면 장비 상태를 재기록하지 않고 사용자에게 알림을 제공해야 합니다.
- 적용된 장비 수와 차단된 오류·잠금 장비 수를 구분해야 합니다.

### REQ-POWER-001 운전 상태 제어

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | setPanelPower, applyPanelCommands |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | TC-MODE-001의 사전·후속 흐름 |

온라인이며 오류·잠금이 없는 선택 장비는 OPERATION 또는 STOP으로 변경할 수 있어야 합니다.

인수 조건:

- 운전 적용 후 status는 OPERATION, Register OPER는 ON이어야 합니다.
- 정지 적용 후 status는 STOP, Register OPER는 OFF여야 합니다.
- 다른 관제점 값은 명시적으로 변경하지 않은 경우 유지되어야 합니다.
- 차단 조건에서는 기존 status와 OPER 값을 유지해야 합니다.

### REQ-MODE-001 운전 모드

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | setPanelMode, applyPanelCommands |
| 증거 | AUTOMATED_VERIFIED |
| 연결 TC | TC-MODE-001, TC-MODE-003, TC-INT-002 |

시스템은 COOL, HEAT, FAN, DRY, AUTO 모드를 제공해야 합니다. 승인된 모드 변경은 장치 카드, 내부 mode와 Register MODE에 동일하게 반영되어야 합니다.

인수 조건:

- 선택한 모드가 Pending에 표시되어야 합니다.
- 적용 전 실제 mode는 유지되어야 합니다.
- 적용 후 세 관측면의 mode가 동일해야 합니다.
- 허용 목록 외 값은 입력 계약 단계에서 거부되어야 합니다.

### REQ-MODE-002 FAN·DRY 온도 조작 제한

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | updatePanelUI, applyPanelCommands |
| 증거 | UI AUTOMATED_VERIFIED, Register 미검증 |
| 연결 TC | TC-MODE-002, TC-MODE-003 |

Pending 모드가 FAN 또는 DRY이면 온도 증가·감소 조작을 비활성화하고 온도 표시를 ---로 표현해야 합니다. COOL, HEAT 또는 AUTO로 복귀하면 온도 조작을 다시 활성화하고 저장된 섭씨 설정값을 표시해야 합니다.

인수 조건:

- FAN·DRY에서 온도 버튼이 disabled여야 합니다.
- FAN·DRY 적용 시 기존 setTemp가 변경되지 않아야 합니다.
- Register TEMP는 --로 표시되어야 합니다.
- 온도 제어 가능 모드 복귀 시 °C 또는 °F 값과 단위를 표시해야 합니다.

### REQ-TEMP-001 설정 온도 상한

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | adjustPanelTemp, 화면 범위 |
| 증거 | AUTOMATED_VERIFIED |
| 연결 TC | TC-TEMP-001 |

섭씨 설정 온도의 상한 후보는 30.0°C입니다. 상한 초과 요청은 차단하고 Pending·장비·Register 값을 유지하며 허용 범위를 알려야 합니다.

인수 조건:

- 30.0°C는 허용되어야 합니다.
- 30.0°C에서 추가 증가 시 30.0°C를 유지해야 합니다.
- 범위 안내 Toast가 표시되어야 합니다.
- 적용 전·후 내부 값이 상한을 초과하지 않아야 합니다.

### REQ-TEMP-002 설정 온도 하한 후보

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | 화면 범위 16.0°C, 3-Tier 기준 |
| 증거 | KNOWN_DEVIATION |
| 연결 TC | 제품 기능 Baseline TC 없음 |

섭씨 설정 온도의 하한 후보는 16.0°C입니다. 현재 구현은 15.0°C까지 허용하므로 후보 요구사항과 불일치합니다.

인수 조건 후보:

- 16.0°C는 허용되어야 합니다.
- 16.0°C에서 추가 감소 시 16.0°C를 유지해야 합니다.
- 차단 시 Toast와 상태 불변을 확인해야 합니다.
- 모드별 별도 하한 정책은 정의하지 않습니다.

주의:

- 기존 TC-TEMP-002의 AUTO 18.0°C 조건은 제품 Baseline이 아니라 제품 결함 분류 Fixture입니다.
- 공식 하한은 사람 승인 전까지 CANDIDATE이며 Agent가 임의 변경할 수 없습니다.

### REQ-TEMP-003 온도 단위

| 속성 | 값 |
|---|---|
| 우선순위 | Medium |
| 근거 | switchTempUnit, adjustPanelTemp |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | 없음 |

사용자는 °C와 °F 표시 단위를 전환할 수 있어야 합니다. 내부 장비 setTemp는 섭씨를 기준으로 유지하며 °F 화면 값은 섭씨 값을 변환해 정수로 표시해야 합니다.

인수 조건:

- 단위 전환만으로 내부 섭씨 값이 변경되지 않아야 합니다.
- 16~30°C는 화면에서 61~86°F로 표시되어야 합니다.
- °F 조작 후 내부 섭씨 값으로 역변환되어야 합니다.
- 반복 전환 시 허용 오차와 반올림 정책은 TBD입니다.

### REQ-FAN-001 풍량

| 속성 | 값 |
|---|---|
| 우선순위 | Medium |
| 근거 | setPanelFan, Register 매핑 |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | 일부 모드 TC에서 간접 사용 |

시스템은 LOW, MED, HIGH, AUTO 풍량을 제공해야 합니다. 화면은 약풍·중풍·강풍·자동으로 표시하고 Register는 MED를 MIDDLE로 표현해야 합니다.

인수 조건:

- 적용 전에는 Pending만 변경되어야 합니다.
- 적용 후 내부 fanSpeed와 Register FAN이 매핑 규칙에 일치해야 합니다.
- 모드 변경만으로 풍량을 임의 변경하지 않아야 합니다. 공기청정 후보 기능은 제외합니다.

### REQ-LOCK-001 중앙·현장 제어 차단

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | applyPanelCommands, simulateLocalPower, simulateLocalTemp |
| 증거 | AUTOMATED_VERIFIED |
| 연결 TC | TC-LOCK-001 |

잠금 장비는 잠금 해제를 제외한 중앙 운전·모드·온도·풍량 명령과 현장 전원·온도 명령을 차단해야 합니다.

인수 조건:

- 잠금 적용은 status, mode, setTemp와 fanSpeed를 변경하지 않아야 합니다.
- 잠금 상태에서 중앙·현장 명령 시 대상 장비 상태가 유지되어야 합니다.
- 잠금 해제 명령은 허용되어야 합니다.
- 차단 사유가 Toast 또는 QA 로그에 기록되어야 합니다.
- 복수 제어에서는 잠금 장비만 차단하고 나머지 장비 처리를 계속해야 합니다.

### REQ-ERROR-001 오류 주입과 제어 차단

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | injectSelectedError, 제어 차단 로직 |
| 증거 | CH05 AUTOMATED_VERIFIED, CH21 미검증 |
| 연결 TC | TC-ERR-001 |

QA 사용자는 온라인 상태에서 선택 장비에 CH05 또는 CH21 오류를 주입할 수 있어야 합니다. 오류 주입 후 status는 ERROR, errorCode는 입력 코드가 되어야 하며 중앙·현장 제어를 차단해야 합니다.

인수 조건:

- 오프라인에서는 오류 주입 요청을 거부해야 합니다.
- 오류 주입 후 장치 카드와 Register OPER는 오류를 표현해야 합니다.
- 차단된 명령은 장비 값을 변경하지 않아야 합니다.
- 오류 코드와 대상 장비가 QA 로그에 기록되어야 합니다.

### REQ-ERROR-002 오류 해제

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | clearSelectedError |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | 없음 |

게이트웨이가 온라인이고 선택 장비에 오류 코드가 있으면 오류를 해제할 수 있어야 합니다. 해제 후 errorCode는 null, status는 STOP이 되어야 합니다.

인수 조건:

- 오프라인에서는 해제를 거부하고 오류 상태를 유지해야 합니다.
- 오류가 없는 장비의 해제 요청은 상태를 변경하지 않아야 합니다.
- 해제 로그는 이전 오류 코드를 포함해야 합니다.
- 오류 이전 OPERATION 상태는 복원하지 않습니다. 이 정책은 승인 필요 항목입니다.

### REQ-GATEWAY-001 게이트웨이 상태

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | setGatewayState |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | TC-PIPE-002는 분류 Fixture이며 기능 검증이 아님 |

QA 사용자는 게이트웨이를 온라인 또는 오프라인으로 전환할 수 있어야 합니다. 오프라인이면 모든 장비를 OFFLINE으로 표시하고 중앙 명령, 오류 주입과 오류 해제를 차단해야 합니다.

인수 조건:

- 오프라인 전환 후 16대 status가 OFFLINE이어야 합니다.
- 네트워크 오류 표시와 QA 로그가 갱신되어야 합니다.
- 온라인 복구 시 errorCode가 있는 장비는 ERROR가 되어야 합니다.
- 나머지 OFFLINE 장비는 STOP으로 동기화되어야 합니다.
- 복구 시 오프라인 이전 OPERATION 상태를 복원하지 않습니다.

### REQ-LOCAL-001 현장 리모컨 전원 제어

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | simulateLocalPower |
| 증거 | 잠금·오류 차단 일부 검증, 오프라인 KNOWN_DEVIATION |
| 연결 TC | TC-LOCK-001, TC-ERR-001의 일부 |

현장 리모컨 전원 조작은 정상 상태에서 OPERATION과 STOP을 토글해야 합니다. 잠금 또는 오류 상태에서는 차단해야 합니다.

인수 조건:

- 정상 조작 후 내부 status와 장치 카드가 변경되어야 합니다.
- 잠금·오류 차단 시 기존 status를 유지해야 합니다.
- 조작 결과와 차단 사유를 LOCAL 로그로 기록해야 합니다.
- 오프라인에서 로컬 동작을 허용할지 여부는 TBD입니다. 현재 코드는 동작 로그만 남기고 상태를 바꾸지 않습니다.

### REQ-LOCAL-002 현장 리모컨 온도 제어

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | simulateLocalTemp |
| 증거 | PARTIALLY_VERIFIED |
| 연결 TC | TC-LOCK-001의 차단 경로 |

현장 온도 조작은 잠금·오류가 없고 모드가 FAN·DRY가 아닐 때 허용해야 합니다. 중앙 제어와 동일한 승인 온도 범위를 적용해야 합니다.

인수 조건:

- 허용 범위 내 요청은 내부 setTemp와 화면을 갱신해야 합니다.
- 잠금·오류·FAN·DRY·범위 초과는 상태를 변경하지 않아야 합니다.
- 현재 15.0°C 허용 결함은 REQ-TEMP-002와 동일한 편차로 관리해야 합니다.

### REQ-BATCH-001 복수 선택

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | toggleMultiSelectMode, selectUnit |
| 증거 | PARTIALLY_VERIFIED |
| 연결 TC | TC-INT-002 |

복수 선택 모드에서는 장비를 개별 선택·해제하고 선택 목록을 유지해야 합니다. 단일 선택 모드로 복귀하면 마지막 선택 장비 한 대만 유지해야 합니다.

인수 조건:

- 동일 장비 재선택 시 목록에서 제거되어야 합니다.
- 마지막으로 클릭한 장비가 Pending 초기화 기준이어야 합니다.
- 선택 장비 수와 헤더의 대상 수가 일치해야 합니다.
- 복수 선택 상태는 LocalStorage에 저장되어야 합니다.

### REQ-BATCH-002 일괄 적용

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | applyPanelCommands |
| 증거 | 대상 3대 모드 적용 AUTOMATED_VERIFIED, 불변성 미검증 |
| 연결 TC | TC-INT-002 |

일괄 적용은 선택 장비 각각에 동일한 Pending 값을 평가해야 합니다. 오류·잠금 장비는 개별 차단하고 적용 가능한 장비는 처리해야 합니다.

인수 조건:

- 적용 성공·오류 차단·잠금 차단 수를 구분해야 합니다.
- 대상 장비 각각의 UI와 내부 상태가 결과에 일치해야 합니다.
- 비대상 장비는 모든 상태를 유지해야 합니다.
- 변경 요청과 무관한 비대상 필드는 유지되어야 합니다.
- 부분 성공 결과에는 장비별 성공·차단 사유가 필요합니다. 현재는 집계 중심이므로 보완 필요합니다.

### REQ-TRACE-001 UI·내부 상태·Register 정합성

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | renderGrid, updateHardwareRegisters, window.__vccs |
| 증거 | UI·내부 AUTOMATED_VERIFIED, 3중 대조 일부 |
| 연결 TC | TC-MODE-001, TC-MODE-002, TC-MODE-003 |

적용된 장비 상태는 장치 카드 UI, 내부 장비 객체와 Register View에서 정의된 매핑에 따라 일치해야 합니다.

인수 조건:

- 동일 Run과 동일 장비의 값을 비교해야 합니다.
- FAN·DRY TEMP와 MED·MIDDLE처럼 명시된 표시 변환만 허용합니다.
- 불일치 시 UI만 기준으로 제품 PASS를 확정하지 않아야 합니다.
- Register 갱신 시각은 보조 증거로 기록할 수 있습니다.

### REQ-OVERVIEW-001 운전 현황

| 속성 | 값 |
|---|---|
| 우선순위 | Medium |
| 근거 | calculateOverview |
| 증거 | IMPLEMENTED_UNTESTED |
| 연결 TC | 없음 |

시스템은 전체 장비의 운전·정지·오류 수와 비율을 표시해야 합니다.

인수 조건:

- 각 집계 합이 전체 장비 수와 일치해야 합니다.
- 현재 OFFLINE은 정지 집계에 포함됩니다.
- OFFLINE을 별도 집계할지 여부는 승인 필요 항목입니다.
- 상태 변경 후 집계와 Progress 표시가 갱신되어야 합니다.

### REQ-LOG-001 QA 이벤트 로그

| 속성 | 값 |
|---|---|
| 우선순위 | High |
| 근거 | appendQALog |
| 증거 | PARTIALLY_VERIFIED |
| 연결 TC | TC-MODE-001, TC-LOCK-001, TC-ERR-001 |

시스템은 주요 제어·차단·게이트웨이·현장 이벤트를 최신순으로 표시해야 합니다. 각 로그는 시각, 출처, 레벨과 메시지를 포함해야 합니다.

인수 조건:

- 출처는 SYSTEM, GATEWAY 또는 LOCAL이어야 합니다.
- 차단 로그는 대상·명령·사유를 식별할 수 있어야 합니다.
- 로그 삭제는 화면 로그만 제거하며 제품 상태를 변경하지 않아야 합니다.
- 로그는 제품 상태의 단독 SSOT로 사용하지 않아야 합니다.

### REQ-BRIDGE-001 QA Bridge

| 속성 | 값 |
|---|---|
| 우선순위 | Critical |
| 근거 | window.__vccs, getRegisterSnapshot |
| 증거 | PARTIALLY_VERIFIED |
| 연결 TC | 다수 Playwright TC |

시스템은 로컬 테스트 환경에서 Playwright가 장비·Pending·선택·게이트웨이 상태와 Register Snapshot을 조회할 수 있는 QA Bridge를 제공해야 합니다.

인수 조건:

- 장비 ID로 내부 상태와 Register Snapshot을 조회할 수 있어야 합니다.
- Bridge는 일반 사용자 UI와 분리되어야 합니다.
- Bridge 조회가 제품 상태를 변경하지 않아야 합니다.
- V2 Agent 3은 허용된 Bridge 함수만 사용해야 합니다.
- 실제 운영 환경에 동일 인터페이스가 존재한다고 주장하지 않습니다.

## 10. Baseline 제외 요구사항

### REQ-AUTH-001 사용자 권한 후보

ADMIN·VIEWER 전환 함수와 Viewer 차단 Overlay는 구현되어 있으나 전환 버튼이 현재 화면에 존재하지 않습니다. 사용 가능한 전체 흐름과 자동화가 없어 INCOMPLETE로 분류하고 Baseline에서 제외합니다.

승인 전 결정 항목:

- 사용자 인증과 역할 전환 방식
- Viewer가 조회할 수 있는 범위
- QA 기능 접근 권한
- 권한 변경 감사 로그

### REQ-PURIFY-001 공기청정 후보

공기청정 UI는 기본적으로 숨김이며 Agent Demo 완료 후 노출됩니다. 단독운전·부가운전·상태 복원 코드가 존재하지만 제품 기능으로 노출되는 정상 경로와 자동화 근거가 없습니다.

- 상태: DEMO_ONLY와 IMPLEMENTED_UNTESTED
- HEAT 상호배타 정책은 Demo 문구만 있고 차단 코드 근거가 없습니다.
- 사람 승인과 별도 기능 TC가 마련되기 전 Baseline에서 제외합니다.

### REQ-FILTER-001 장비 필터 후보

화면에 모든 장치와 상태 선택 요소가 있으나 실제 필터 처리 로직이 확인되지 않습니다.

- 상태: SCREEN_ONLY
- 필터 조건, 조합, 결과 없음 표시와 선택 유지 정책이 정의되지 않았습니다.
- 구현·TC·승인 전 Baseline에서 제외합니다.

## 11. 인터페이스 요구사항

### IF-UI-001 중앙 제어 화면

- 장비 카드, 제어 패널, 상태 요약, QA 도구와 Register View를 제공해야 합니다.
- 제어 불가능한 상태는 단순 색상 외에 disabled 또는 설명 텍스트로 표현해야 합니다.
- 선택 장비가 없으면 제어 패널 입력을 비활성화해야 합니다.

### IF-STORAGE-001 LocalStorage

| 키 | 저장 내용 |
|---|---|
| vccs_simulator_devices | 장비 배열 |
| vccs_simulator_gateway | 게이트웨이 상태 |
| vccs_simulator_selected_ids | 선택 장비 ID 배열 |
| vccs_simulator_multiselect | 복수 선택 모드 |

저장값 Schema 버전과 손상 데이터 복구 정책은 현재 없으며 V2 구현 전 정의가 필요합니다.

### IF-QA-001 테스트 인터페이스

QA Bridge는 로컬 시뮬레이터 자동화 지원용입니다. 허용 함수, 반환 타입과 읽기·쓰기 권한은 Agent 3 Sandbox 정책에서 제한해야 합니다.

## 12. 비기능 요구사항 후보

### NFR-REL-001 실행 독립성

각 자동화 TC는 초기 상태를 명시적으로 구성하고 이전 TC 결과에 의존하지 않아야 합니다.

### NFR-REL-002 상태 복원

후보 자동화 실행 전 Snapshot을 저장하고 실행 후 복원해야 합니다. 복원 실패 이후 결과는 오염 가능성이 있으므로 후속 실행과 제품 판정을 차단해야 합니다.

### NFR-OBS-001 추적성

중요 제어와 차단 결과는 대상 장비, 명령, 사유와 실행 시각을 추적할 수 있어야 합니다.

### NFR-OBS-002 다중 증거

제품 판정은 UI, 내부 상태, Register, 로그 또는 Trace 중 요구사항에 적합한 복수 증거를 사용해야 합니다.

### NFR-SEC-001 로컬 격리

QA Bridge, 오류 주입과 Agent 생성 코드 실행은 로컬 시뮬레이터 범위로 제한해야 하며 외부 URL·운영 장비·비밀값에 접근하면 안 됩니다.

### NFR-PERF-001 응답 기준

현재 코드 주석에는 로그 500ms 이내 목표가 있으나 공식 근거와 자동화 측정이 없습니다. 성능 기준은 TBD이며 승인 전 합격 기준으로 사용하지 않습니다.

### NFR-USAB-001 상태 식별

오류·잠금·오프라인·선택·비활성 상태는 텍스트 또는 제어 상태와 함께 식별 가능해야 합니다. 색상만으로 판정하지 않습니다.

### NFR-AUDIT-001 Baseline 보존

V2가 생성한 SRS·TC·코드 변경안은 승인 전 원본을 덮어쓰지 않아야 하며 입력·출력 해시와 승인 이력을 보존해야 합니다.

## 13. 업무 규칙 결정표

### 13.1 중앙 제어

| 조건 | 결과 | 상태 변경 | 필수 증거 |
|---|---|---|---|
| Viewer | 전체 명령 차단 | 없음 | Toast, SYSTEM 로그 |
| Gateway Offline | 전체 명령 차단 | 없음 | Toast, SYSTEM 로그 |
| 선택 없음 | 적용 차단 | 없음 | Toast |
| 장비 ERROR | 해당 장비 차단 | 없음 | 오류 코드, 로그 |
| 장비 LOCK | 잠금 해제만 허용 | locked만 변경 가능 | 장비별 로그 |
| FAN·DRY 온도 | 온도 변경 무시 | setTemp 유지 | UI disabled, Register -- |
| 정상 | 변경값 적용 | 지정 필드 변경 | UI·내부·Register |

### 13.2 게이트웨이 복구

| errorCode | 오프라인 상태 | 온라인 복구 상태 |
|---|---|---|
| 존재 | OFFLINE | ERROR |
| 없음 | OFFLINE | STOP |

오프라인 이전 OPERATION 상태를 복원하지 않는 현재 정책은 승인 대상입니다.

### 13.3 복수 제어

| 장비 조건 | 처리 |
|---|---|
| 정상 | Pending 적용 |
| ERROR | 해당 장비만 차단 |
| LOCK, 해제 요청 아님 | 해당 장비만 차단 |
| LOCK, 해제 요청 | locked=false만 적용 |
| OFFLINE | 패널 전체 비활성화 또는 명령 차단 |
| 비대상 장비 | 모든 상태 불변 |

## 14. Requirement–TC 추적성

| Requirement | 연결 TC | 현재 자동화 범위 |
|---|---|---|
| REQ-ENV-001 | TC-ENV-000 | 장비·환경 사전 점검 |
| REQ-STATE-001 | 공통 Fixture | 테스트 전 초기화 |
| REQ-STATE-002 | 없음 | 미검증 |
| REQ-SELECT-001 | 다수 기능 TC | 단일 선택 간접 검증 |
| REQ-CONTROL-001 | TC-MODE-001~003 | Pending·Apply 일부 |
| REQ-POWER-001 | TC-MODE-001 | 간접 검증 |
| REQ-MODE-001 | TC-MODE-001, 003, TC-INT-002 | HEAT·COOL·복수 적용 |
| REQ-MODE-002 | TC-MODE-002, 003 | FAN·DRY 비활성·복귀 |
| REQ-TEMP-001 | TC-TEMP-001 | 30°C 상한 |
| REQ-TEMP-002 | 없음 | 16°C 후보와 구현 편차 |
| REQ-TEMP-003 | 없음 | 미검증 |
| REQ-FAN-001 | 없음 | 미검증 |
| REQ-LOCK-001 | TC-LOCK-001 | 16대 잠금·차단 |
| REQ-ERROR-001 | TC-ERR-001 | CH05 주입·차단 |
| REQ-ERROR-002 | 없음 | 미검증 |
| REQ-GATEWAY-001 | 없음 | Pipeline Fixture만 존재 |
| REQ-LOCAL-001 | TC-LOCK-001, TC-ERR-001 | 차단 경로 일부 |
| REQ-LOCAL-002 | TC-LOCK-001 | 잠금 차단 일부 |
| REQ-BATCH-001 | TC-INT-002 | 3대 선택 |
| REQ-BATCH-002 | TC-INT-002 | 대상 반영, 비대상 불변 누락 |
| REQ-TRACE-001 | TC-MODE-001~003 | UI·내부, 일부 Register |
| REQ-OVERVIEW-001 | 없음 | 미검증 |
| REQ-LOG-001 | 다수 기능 TC | 특정 로그 존재 |
| REQ-BRIDGE-001 | 다수 기능 TC | 내부 상태 조회 |
| REQ-AUTH-001 | 없음 | Baseline 제외 |
| REQ-PURIFY-001 | 없음 | Baseline 제외 |
| REQ-FILTER-001 | 없음 | Baseline 제외 |

## 15. 제품 TC와 Pipeline Fixture 구분

### Core Regression 후보

- TC-ENV-000
- TC-MODE-001
- TC-MODE-002
- TC-MODE-003
- TC-LOCK-001
- TC-ERR-001
- TC-INT-002
- TC-TEMP-001

### Product Classification Fixture

- TC-TEMP-002는 AUTO 18.0°C를 공식 Baseline 요구사항으로 만들지 않습니다.
- 해당 TC는 Agent 4의 제품 결함 분류 시연 Fixture로 분리합니다.

### Pipeline Control Fixture

- TC-PIPE-001: 요구사항 검토 필요 분류
- TC-PIPE-002: 환경 문제 분류
- TC-PIPE-003: 자동화 코드 문제 분류
- TC-PIPE-004: 조건 부족 미실행 분류

Pipeline Fixture는 제품 기능 회귀의 성공률과 분리해 보고해야 합니다.

## 16. 승인 전 결정 목록

| ID | 결정 항목 | 영향 |
|---|---|---|
| DEC-001 | 공식 섭씨 하한 16.0°C 승인 여부 | 온도 TC·구현 |
| DEC-002 | °F 반올림과 반복 전환 허용 오차 | 단위 변환 TC |
| DEC-003 | 오류 해제 후 STOP 고정 또는 이전 상태 복원 | 오류 해제 |
| DEC-004 | Gateway 복구 후 STOP 고정 또는 이전 상태 복원 | 복구 TC |
| DEC-005 | Gateway Offline에서 현장 제어 허용 여부 | 현장 제어 |
| DEC-006 | OFFLINE을 정지 집계에 포함할지 | Overview |
| DEC-007 | 복수 제어 부분 성공 메시지와 장비별 결과 계약 | Batch |
| DEC-008 | 권한·공기청정·필터 Baseline 편입 여부 | 향후 범위 |
| DEC-009 | LocalStorage 손상 데이터 복구 정책 | 상태 복원 |
| DEC-010 | 공식 응답 시간·로그 기록 시간 기준 | 비기능 |

## 17. Baseline 승인 조건

본 문서를 Approved Baseline으로 승격하려면 다음이 필요합니다.

- DEC-001~010 중 MVP 영향 항목에 대한 사람 결정
- KNOWN_DEVIATION의 결함 또는 승인 예외 처리
- Critical·High 요구사항의 최소 검증 계획
- Requirement–TC 연결 누락 검토
- 제품 기능 TC와 Pipeline Fixture 물리·논리 분리
- 문서 버전, 승인자, 승인 시각과 기준 소스 커밋 기록

승인 전에는 본 문서를 Approved SRS V1.0이라고 부르지 않으며, Agent 1은 TBD를 확정 사실로 사용할 수 없습니다.
