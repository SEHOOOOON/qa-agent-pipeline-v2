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
- 차단 안내 TC는 단순 표시 여부만 보지 않고 제한된 차단 의미 신호를 함께 확인합니다. 성공 적용 Toast는 차단 안내로 취급하지 않습니다.

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

1. 실제 Project1 HTML 파일은 읽기 전용으로 열고 SHA-256을 기록합니다.
2. 선택 TC가 기존의 검증된 빠른 확인 대상인지, 처음 보는 UI를 동적으로 확인할 대상인지 구분합니다.
3. 기존 기능은 필요한 Selector와 `window.__vccs` 키만 확인하고, 신규 기능은 안정적인 ID·`data-testid`·접근성 이름을 가진 범용 UI와 읽기 가능한 내부 상태를 동적으로 확인합니다.
4. Agent 3 모델은 선택 TC·관련 SRS·TC 범위 UI 조사 JSON으로 구조화 계획만 만듭니다.
5. 모델이 Python 코드와 새 Selector·기대값·Requirement를 만들지 못하게 합니다.
6. CP3가 행동-Selector, Expected Result 1:1, 관찰 계층, 값, 단계 순서와 초기값 복원 Action을 검사합니다. 알림은 Expected Result 전체 자연어 문장을 실제 UI 문구로 사용할 수 없습니다.
7. 허용 목록 컴파일러가 Playwright Python 후보를 생성하고 복원 후 기존 온도와 범용 UI·내부 상태를 초기 관찰값과 다시 비교합니다.
8. UI 실제값과 `window.__vccs.devices` 내부 실제값을 TC의 고정 기대값과 비교합니다.
9. 후보는 원본과 분리된 임시 폴더에서 실행하고 Run 폴더에는 검토용 사본만 저장합니다.
10. 시험 프로세스에는 allowlist의 시스템 변수와 QA 대상·증거 경로만 전달합니다.
11. 범용 클릭·입력·선택·체크/해제와 화면·내부 값 비교로 구현할 수 없으면 `AUTOMATION_SUPPORT_EXTENSION_REQUIRED`로 기록하고 코드를 만들지 않습니다.
12. CP3 계획 실패만 최대 1회 재작성하고 시험 기술 오류 자동 수정은 하지 않습니다.
13. 기대값·검증 조건(Assertion)의 의미·Requirement ID는 수정하지 않습니다.
14. 시험 `PASS`와 `PRODUCT_MISMATCH_CANDIDATE`는 파이프라인 정상 완료로 종료합니다.
15. `NOT_AUTOMATABLE`, `AUTOMATION_ERROR`, `ENVIRONMENT_ERROR`, `TIMEOUT`, CP3 실패와 시험 미실행은 제품 판정 불가 상태이므로 CLI 실패 코드 `2`로 종료합니다.
16. 후속 `execute`는 저장 후보와 현재 컴파일러 출력을 비교하고 다르면 모델 호출 없이 현재 후보를 다시 시험합니다.
17. Project1 HTML과 기존 테스트를 임시 Workspace에 복사하고, 의미 분류 라벨을 주입하는 원본 `conftest.py` 대신 viewport만 고정한 중립 설정을 사용합니다.
18. TC-ENV-000이 통과한 경우에만 Requirement ID로 연결된 재사용 가능 회귀를 실행합니다.

Agent 3 API에는 시스템 지침, 선택 TC, 관련 SRS 행, 대상 파일명·SHA-256, 페이지 제목, **선택 TC에 필요한** Selector별 tag·text·visible·enabled·action_hint와 하네스 키만 전송합니다. API 키, 로컬 절대경로, HTML 원문, Screenshot과 Trace는 전송하지 않으며 API 키와 모델 Client를 요구하지 않는 `--preview-only` JSON으로 먼저 확인합니다.

UI 확인 목록은 Selector·표시·활성 상태·요소 역할과 읽기 가능한 내부 상태를 기록합니다. 기존 기능은 선택 TC 범위만 확인하고, 신규 기능만 범용 요소를 최대 120개까지 한 번 동적으로 확인하므로 매번 전체 UI를 조사하지 않습니다. 실제 조작과 기대 결과는 신규 자동화 후보 시험에서 검증합니다. 임시 시험 공간은 임시 폴더·제한 환경변수·별도 subprocess를 사용하지만 네트워크 차단, 컨테이너 또는 OS 권한 분리를 제공하지 않습니다.

신규 후보 시험의 자식 Python은 Windows의 기존 site-package 인코딩과 호환되도록 locale 기반 시작을 유지하고, 캡처할 stdout·stderr만 UTF-8로 고정합니다. Playwright Trace는 사용자 홈·대상 파일·임시 시험 공간·증거 폴더의 정확한 문자열, URI와 JSON escape 표현을 ZIP 내부에서 치환한 뒤 저장하며 Screenshot·DOM 등 다른 항목은 보존합니다. `agent3_error.json`이 생긴 실패 시도는 진단 증거로 보존하고 같은 Run 폴더에 성공 산출물을 덮어쓰지 않습니다. 재시도는 새 임시 시험 공간에서 실행합니다.

## 9. 증거 기록

V2 시험 실행에서는 실제로 생성한 증거만 기록합니다.

- 대상 파일명·SHA-256과 UI 조사 시각
- 자동화 가능성 사전 확인 결과와 범용 UI 동적 조사 필요 여부
- API 전송 예정 미리보기 JSON
- TC ID와 코드 후보 SHA-256
- Agent 2 Manifest·TC 설계 SHA-256
- 자동화 계획·Checkpoint 3 SHA-256
- exit code, stdout, stderr
- 시험 결과와 증거 완전성
- 모든 계획 시도 누적 토큰과 마지막 시도 토큰
- 실제 생성된 Screenshot·Trace 파일명
- 후속 검증의 후보 재사용 여부, 환경 사전 점검과 관련 기존 회귀 결과
- Project1 대상·테스트 소스 SHA-256과 실행 후 불변 여부

stdout·stderr의 로컬 절대경로와 `file://` 주소를 마스킹하고 Trace ZIP의 알려진 로컬 경로도 치환합니다. 저장하지 않은 Screenshot·Trace나 구현하지 않은 Restore 결과를 보고서에 표시하지 않습니다.
