# Project1 QA 하네스 가이드

## 1. 목적과 경계

이 문서는 가상 중앙제어기의 상태를 만들고 관찰하기 위한 **테스트 지원 인터페이스**를 설명합니다. 여기에 적힌 버튼, DOM, JavaScript 함수와 저장 방식은 제품 요구사항이 아니며 [제품 SRS](01_PRODUCT_SRS.md)의 기대 동작을 대신하지 않습니다.

| 구분 | 제품 동작 | QA 하네스 |
|---|---|---|
| 중앙제어 | 사용자가 장비를 선택하고 명령 적용 | 허용·차단 결과를 관찰 |
| 게이트웨이 | 연결 상태에 따라 중앙 명령 허용 여부 결정 | 온라인·오프라인 상태 생성 |
| 장비 오류 | 오류 장비 표시와 제어 차단 | CH05·CH21 상태 주입·해제 |
| 현장 조작 | 로컬 조작 결과가 중앙 상태에 반영 | 현장 전원·온도 이벤트 생성 |
| 내부 상태 | 화면과 일치해야 하는 시뮬레이션 상태 | window.__vccs와 Register로 조회 |

## 2. QA Drawer

virtual-controller.html의 QA Drawer는 다음 기능을 제공합니다.

| 영역 | 화면 기능 | 용도 | 제품 요구사항 여부 |
|---|---|---|---|
| 게이트웨이 통신 상태 | 온라인·오프라인 버튼 | 연결 상태 시나리오 생성 | 아니요 |
| 물리 에러 강제 주입 | CH05·CH21·Clear | 오류 장비 시나리오 생성 | 아니요 |
| 현장 리모컨 | 전원 토글·온도 ± | 현장 상태 변화 시뮬레이션 | 아니요 |
| 시뮬레이터 초기화 | Reset | 저장된 테스트 상태 제거 | 아니요 |
| 이벤트 로그 | 시각·출처·레벨·메시지 | 실행 흐름 관찰 | 아니요 |

QA Drawer 조작으로 확인되는 제품 규칙은 Product SRS에 남기지만 버튼명과 함수 호출 방법은 이 문서에서만 관리합니다.

## 3. H/W Register 시뮬레이터

페이지 하단 Register Memory View는 16대 장비의 POWER, MODE, FAN, TEMP와 LOCK 값을 HTML로 표현합니다.

- 실제 장비 레지스터나 Modbus 주소가 아닙니다.
- 화면과 내부 상태를 대조하기 위한 관찰 수단입니다.
- Register에 값이 보인다는 사실만으로 실제 통신 성공을 주장하지 않습니다.
- FAN·DRY의 TEMP 표시는 값 대신 --를 사용할 수 있습니다.

Register 화면 자체는 제품 Requirement로 관리하지 않고, 제품의 상태 정합성은 REQ-STATE-001로 판정합니다.

## 4. Playwright 전용 window.__vccs

페이지 로드 후 다음 읽기·호출 인터페이스가 전역 Namespace에 노출됩니다.

| 항목 | 성격 | 주요 용도 |
|---|---|---|
| devices | 상태 조회 | 장비별 status·mode·setTemp·fanSpeed·locked·errorCode 확인 |
| pendingState | 상태 조회 | 적용 전 제어 패널 대기값 확인 |
| selectedUnitIds | 상태 조회 | 복수 선택 목록 확인 |
| selectedUnitId | 상태 조회 | 대표 선택 장비 확인 |
| isGatewayOnline | 상태 조회 | 게이트웨이 상태 확인 |
| getRegisterSnapshot | 상태 조회 | Register 표시값 Snapshot |
| selectUnit | 조작 함수 | 테스트 사전조건 설정 |
| applyPanelCommands | 조작 함수 | 중앙 명령 실행 |
| renderGrid·updatePanelUI | 렌더 함수 | 테스트 지원 |
| saveStateToLocalStorage | 저장 함수 | 상태 저장 |
| updateHardwareRegisters·initHardwareView | Register 함수 | Register 갱신·초기화 |

### 사용 원칙

- V2 Agent 3는 제품 기대값을 window.__vccs에서 새로 만들지 않습니다.
- 기대값은 승인된 제품 기능 TC에서 가져오고 window.__vccs는 실제값 관찰에만 사용합니다.
- 외부 페이지나 운영 장비에 이 인터페이스가 존재한다고 가정하지 않습니다.
- 원본 페이지를 수정하는 수단으로 사용하지 않습니다.
- 일반적인 Snapshot·Restore API가 있다고 표현하지 않습니다.

## 5. 상태 저장과 초기화

현재 구현은 브라우저 저장소에 다음 상태를 보관합니다.

- 장비 배열
- 게이트웨이 연결 상태
- 선택 장비 목록
- 복수 선택 여부

Reset은 사용자 확인 후 해당 저장값을 지우고 페이지를 다시 로드합니다.

### 제한

- 저장 Schema 버전과 마이그레이션은 없습니다.
- 손상된 저장값의 복구 정책은 정의되어 있지 않습니다.
- Reset은 전체 제품 초기화 기능이 아니라 로컬 시뮬레이터 테스트 지원 기능입니다.
- V2 후보 실행은 가능한 한 새 브라우저 Context와 명시적 사전조건으로 시작합니다.

## 6. 이벤트 로그와 Toast

### Toast

- 사용자에게 적용·차단·상태 변경 결과를 짧게 안내합니다.
- 제품 요구사항 REQ-NOTIFY-001의 관찰 대상입니다.
- 정확한 문자열은 변경 요청이나 TC가 문구 일치를 요구한 경우에만 검증합니다.

### 이벤트 로그

- QA Drawer 안의 DOM 목록입니다.
- SYSTEM, GATEWAY, LOCAL 출처와 시각·레벨·메시지를 표시합니다.
- 영구 파일 로그나 서버 감사 로그가 아닙니다.
- 코드가 setTimeout으로 DOM을 갱신하므로 로그 존재만으로 장비 상태 변경 성공을 단정하지 않습니다.

## 7. 현재 알려진 하네스 한계

- 오프라인 현장 조작은 로그 문구와 실제 상태 변경이 일치하지 않습니다.
- 기존 자동화 결과의 evidence_path가 비어 있습니다.
- TC-ENV-000은 일반 테스트이며 후속 테스트를 차단하는 실행 Gate가 아닙니다.
- TC-INT-002는 비대상 13대 상태 불변을 확인하지 않습니다.
- 숨김 공기청정 UI는 Agent Workflow Demo 중에 표시되는 확장 사례입니다.
- QA 하네스는 운영 장비, 실제 통신과 실제 서버 상태를 대체하지 않습니다.

## 8. V2 Agent 3 사용 기준

1. 허용된 로컬 URL만 엽니다.
2. 실제 접근성 구조와 Locator를 확인합니다.
3. 승인된 TC의 사전조건과 행동만 코드로 구현합니다.
4. UI 실제값과 window.__vccs 내부 실제값을 각각 수집합니다.
5. 두 실제값을 TC의 고정 기대값과 비교합니다.
6. 후보 코드는 원본 프로젝트와 분리된 Run 폴더에 저장합니다.
7. Locator·Wait·Fixture 오류만 제한적으로 수정합니다.
8. 기대값·Assertion 의미·Requirement ID는 수정하지 않습니다.

## 9. 증거 기록

V2 시험 실행에서는 실제로 생성한 증거만 기록합니다.

- 대상 URL과 실행 시각
- TC ID와 코드 후보 ID
- exit code, stdout, stderr
- UI Assertion 결과
- 내부 상태 Assertion 결과
- 필요 시 Screenshot·Trace 파일 경로
- 시험 전후 상태와 정리 결과

저장하지 않은 Screenshot·Trace나 구현하지 않은 Restore 결과를 보고서에 표시하지 않습니다.
