# Agent·Checkpoint 명세

## 1. 공통 계약

- 모든 Agent 산출물은 Pydantic 구조화 JSON입니다.
- 다음 단계는 앞 단계 Manifest와 주요 산출물의 SHA-256을 확인합니다.
- 모델은 변경 요청의 Requirement ID, 변경 전·후 값, 경계값을 바꿀 수 없습니다.
- Checkpoint 통과는 자동 규칙 통과이며 사람의 최종 승인이 아닙니다.
- 모델 실패 또는 Checkpoint 의미 규칙 실패는 최대 한 번만 재작업합니다.

## 2. Agent 1 / CP1

입력은 변경 요청 JSON과 관련 Product SRS 행입니다. 변경 전·후 조건, 출처가 있는 확정 조건, 관련 Requirement 영향, 제외 범위, 정보 부족, 진행 판정을 출력합니다. UI·하네스·자동화 지원 여부는 Requirement 영향도를 낮추거나 확정 조건을 제외하는 근거로 사용하지 않습니다.

CP1 핵심 검사:

| 범위 | 검사 |
|---|---|
| 입력 보존 | 요청 ID, 대상 Requirement, 변경 유형, 변경 전·후 값 |
| 근거 | 확정 조건의 요청 또는 SRS 출처 |
| 범위 | 관련 Requirement 검토, 제외 범위 분리 |
| 실행 가능성 | 인수 조건과 정보 부족·질문·진행 판정의 일관성 |

인계:

- PROCEED → CONTINUE
- PARTIAL_PROCEED → 확정 범위만 CONTINUE
- WAITING_FOR_USER → PAUSE
- BLOCKED 또는 CP1 FAIL → BLOCKED

REVIEW는 확정 범위가 있으면 최종 확인 사항으로 남기고 실행을 막지 않습니다.

## 3. Agent 2 / CP2

입력은 검증된 Agent 1 산출물, 확정 조건, 관련 SRS와 허용된 기존 사람 작성·자동화 TC 카탈로그입니다. 기존 TC 카탈로그에는 V1 기준 회귀와 사람 승인 Registry 자산의 TC ID·Requirement ID·함수명과 실제 검증 동작이 함께 제공됩니다. 승인 자산은 Registry 경로·파일 SHA-256·구조화 TC·단일 테스트 함수를 검증하고 Run별 `approved_regression_catalog.json` Snapshot으로 고정합니다. Agent 1은 각 Condition을 `변경`·`유지`·`보조_근거`로 표시하며 단어 집합 비교로 매핑·순서 변경을 유지로 추정하지 않습니다. 관련 기존 TC가 담당하는 유지 조건만으로 신규 Expected Result를 다시 만들면 CP2가 차단합니다.

제품 기능 TC는 TC ID·목적·유형, Requirement·조건 ID, 중앙 관제 패널 경로, 대상 역할·시험 데이터, 조건 실행 방식, 초기 조건·단계·기대 결과, 3단계 QA 기준, 독립 실행·복원, 이중 검증 정책을 가집니다.

TC 구성 기준:

- 하나의 TC는 입력값 하나가 아니라 하나의 관제점에서 하나의 업무 규칙을 검증합니다.
- 같은 업무 규칙의 하한·상한, 같은 비활성 규칙을 공유하는 여러 모드처럼 입력 조건만 다르면 한 TC로 묶을 수 있습니다.
- 독립 조건은 `INDEPENDENT_VARIANTS`로 표시하고 조건 사이의 재준비 절차를 `intermediate_reset_steps`에 기록합니다.
- 순서 자체가 검증 대상인 전환은 `SEQUENTIAL_TRANSITION`으로 표시합니다. 단일 구간은 `SINGLE_FLOW`입니다.
- 묶음 TC의 복수 모드·온도는 `requested_modes`·`requested_temperatures_c`에 빠짐없이 기록합니다.
- 각 Expected Result는 관찰값 하나만 가지며 `verify_after_step`으로 판정할 단계에 연결합니다. Expected Result 분리는 TC 분리를 뜻하지 않습니다.
- Condition 원문에 없는 `선택하고 적용할 수 있다` 같은 실행 행동 성공 문장은 Expected Result로 추가하지 않습니다. 요구사항 자체가 기능 가능 여부를 요구하면 이를 삭제하지 않고 적용 뒤 표시·값·활성 상태 같은 판정 가능한 관찰값으로 구체화합니다.
- 서로 다른 Requirement 목적·제어 경로·무관한 실패 원인은 별도 TC로 분리합니다.

CP2 핵심 검사:

| 범위 | 검사 |
|---|---|
| 추적성 | 입력 범위 밖 ID 금지, 모든 확정 조건 반영 |
| TC 품질 | ID 고유성, 업무 규칙 단위 묶음, 단계·기대 결과 연결, 관찰값별 Expected Result |
| V1 기준 | 공통·도메인·기능별 QA 기준, 독립성, 조건부 이중 검증 |
| 조건 실행 | 단일·독립 조건·순차 전환 구분, 복수 입력값, 중간 초기화, 조건별 판정 시점 |
| 제품/자동화 분리 | TC에 Selector·Python·구현 지시 금지 |
| 제품 경계 | 중앙 관제 패널 경로, 대상·시험 데이터 명시 |
| 정보 부족 | 불명확 범위를 TC로 만들지 않고 제외 목록으로 전달 |
| 기존 TC 대조 | 모델이 검증 동작의 의미를 대조하고 CP2는 ID·조건 연결·명시 값 및 기존 회귀의 후보 재생성 여부를 검사(완전한 의미 동등성 판정은 아님) |
| 조건 처리 경로 | 모든 확정 Condition을 변경분 후보 또는 관련 기존 TC에 연결하고 조용한 누락 차단 |
| SRS 개정 | MODIFIED·UPDATE_REQUIRED Requirement별 개정 전·후 인수 기준과 Condition 근거의 누락·중복·원문 불일치 차단 |

기존 회귀는 Agent 2가 Condition과 검증 동작을 대조해 `관련_기존_TC`에 명시한 선택만 사용합니다. Requirement ID만으로 다른 동작의 TC를 자동 보충하지 않으며, 빠진 Condition은 CP2 실패와 최대 1회 재작업으로 드러냅니다. 변경 후 동작을 기존 TC가 모두 검증하면 `test_cases=[]`와 관련 기존 TC만으로 CP2를 통과할 수 있습니다.

중복 기술 ID는 의미·값·단계·Requirement를 바꾸지 않는 경우에만 결정론적으로 다시 번호를 매깁니다.

CP2는 복수 입력값·단계 연결·초기화·판정 시점 같은 구조적 계약을 자동 검사하지만, 자연어로 표현된 두 조건이 실제로 완전히 같은 업무 규칙인지를 모든 경우에 확정한다고 주장하지 않습니다. Agent 2는 변경 요청·SRS 근거로 묶음 이유를 기록하고, 사람은 최종 보고에서 TC 분리 수준이 현업 기준에 맞는지 확인합니다. 서로 다른 UI 관찰값을 한 Expected Result에 합치는 것은 계속 차단하지만, `FAN 모드에서 온도 버튼은 비활성화된다`처럼 모드가 시험 조건을 나타낼 뿐 별도 화면 모드 표시를 검증하지 않는 문장은 복합 관찰로 보지 않습니다.

변경 요청의 acceptance_notes 중 명시적인 시험 시작 전 확인과 시험 종료 후 복원은 제품 판정 Condition이나 제외 범위가 아닙니다. Agent 2는 준비 문장을 preconditions 또는 steps에, 복원 문장을 restore_steps에 원문 그대로 보존하고 `restore_required=true`로 기록합니다. CP2-014는 실제 제외 범위·정보 부족 인계와 이 시험 절차 보존을 분리해 검사합니다.

현재 제한: CP2-014의 준비·복원 문장 검사는 신규 후보 `test_cases`의 절차만 읽습니다. 따라서 해당 메모가 있는 요청에서 `test_cases=[]`로 기존 TC만 선택하면 기존 자동화에 준비·복원이 있더라도 누락으로 차단될 수 있습니다. 기존 TC 전용 실행이 모든 요청에서 지원된다고 해석하지 않습니다.

신규 Agent 2 실행은 `existing_behavior_values_contract=1.0`을 기록합니다. CP2-019는 신규 후보 없이 기존 TC만 맡은 변경 조건의 명시적인 상태 코드·수치가 선택된 기존 TC의 검증 동작에 포함되는지 추가 검사합니다. Requirement ID만 같고 값이 다른 재사용은 차단하지만, 값의 포함 관계가 자연어 의미·매핑·순서의 완전한 일치를 증명하지는 않습니다. 모델의 의미 대조와 사람 검토는 유지합니다. 해당 계약이 없는 역사적 Run의 CP2를 소급 변경하지 않습니다.

## 4. Agent 3 / CP3

입력은 CP2를 통과한 신규·수정 후보 TC 한 건, 관련 SRS 행, 해당 TC에 필요한 UI 확인 결과입니다. 관련 기존 회귀는 Agent 3 입력이 아니며 execute 단계에서 기존 코드를 실행합니다. API 키, 로컬 절대경로, 전체 HTML, Screenshot, Trace는 모델 입력에서 제외합니다.

처리 순서:

1. 자동화 가능성 확인
2. 필요한 UI 확인
3. AI 계획 생성
4. CP3 검사
5. 필요 시 기술 계획 1회 재작성
6. 결정론적 Python 생성
7. 정적 검사
8. 신규 자동화 시험과 증거 저장

CP3 핵심 검사:

| 범위 | 검사 |
|---|---|
| TC 보존 | TC ID, 단계, Expected Result, 값, 관찰 계층 |
| UI 근거 | 실제 확인한 Selector와 내부 상태 필드만 사용 |
| 실행 순서 | 초기 조건 → 시험 조작 → 검증 → 복원 |
| 코드 안전 | 문법, 허용 조작, 외부 호출·파일 변경·Assertion 우회 금지 |
| 추적성 | 모든 Expected Result가 정확한 코드 Assertion으로 연결 |

묶음 TC에서는 Assertion의 `after_action_id`가 해당 Expected Result의 `verify_after_step`을 구현한 마지막 Action을 가리켜야 합니다. 컴파일러는 해당 Action 직후 Assertion을 배치하므로 앞 조건을 다음 조건 실행 뒤에 잘못 판정하지 않습니다. CP3는 모든 기대 결과의 1:1 연결, 유효한 판정 위치, 중간 초기화 Action과 승인 순서를 검사합니다.

신규 제품 동작은 공통 계약에 기능명·값·Selector를 추가하는 방식으로 지원하지 않습니다. Agent 3는 처음 보는 기능명이라는 이유로 거부하지 않고, 승인 TC의 단계와 기대 결과를 실제 관찰한 안정적인 UI에 연결해 공통 클릭·입력·선택·체크와 UI·읽기 전용 상태 검증을 먼저 시도합니다. 컴파일러는 해당 TC가 사용한 공통 조작과 검증만 코드에 배치합니다. 기존 V1 온도 전용 조작은 해당 기준 화면을 사용하는 TC에만 남는 호환 경로입니다.

동적 UI 문구는 실행 전 관찰값에 아직 존재하지 않을 수 있습니다. CP3는 승인 Expected Result가 대상 장비 카드를 명시하고 Assertion Selector가 계획의 정확한 대상 장비 카드일 때만 실행 후 텍스트 검증을 허용합니다. 다른 카드나 임의 컨테이너에는 이 예외를 적용하지 않습니다.

이 유연성은 자유 코드 실행을 뜻하지 않습니다. 실제 UI에서 관찰되지 않은 Selector, TC에 없는 값·Expected Result, 임의 JavaScript·쉘·파일·외부 네트워크 조작은 계속 차단합니다. 관찰된 표준 조작으로 표현할 수 없는 기술이 실제로 필요한 경우에만 자동화 지원 범위 확장 사유를 남깁니다.

시험 결과:

- PASS: 코드와 제품 관찰이 기대와 일치
- PRODUCT_MISMATCH_CANDIDATE: 시험 로그에서 제품 기대값 불일치 표식을 관찰함. 제품 결함 확정이나 다른 실행 오류의 부재를 뜻하지 않음
- AUTOMATION_ERROR: 자동화 코드 또는 실행 문제
- ENVIRONMENT_ERROR: 브라우저·의존성·대상 환경 문제
- TIMEOUT: 제한 시간 초과

Candidate Trial의 기본 제한은 90초입니다. 시간 초과 시 pytest와 Playwright 자식 프로세스를 함께 정리하며, 쓰기가 중단된 Trace는 경로·비밀정보 제거를 보장할 수 없으므로 증거에서 제외합니다.

앞의 두 결과만 증거가 완전할 때 실행 완료 후보로 인계합니다. 자동화할 수 없는 TC는 자동화_제외_TC에 사유를 남기고 다른 TC를 계속 처리합니다.

기존 중앙 관제 온도·모드 묶음 TC에서 고정 초기값이 없으면 `restore_observed_hvac_state=true`를 사용합니다. Agent 3 계획은 RESTORE 단계에 `RESTORE_OBSERVED_HVAC` 한 건만 두며, 컴파일러가 실행 직전 대상 장비의 `mode`·`setTemp`를 저장하고 시험 뒤 모드 선택·온도 조정·적용을 수행합니다. 복원 후 두 내부 값이 저장값과 다르면 `RESTORE_MISMATCH`로 시험을 신뢰하지 않습니다. 고정 초기값 복원과 동적 복원을 섞거나 이 동작을 일반 기능에 사용하는 계획은 CP3에서 차단합니다.

단, 현재 실행 분류는 `PRODUCT_MISMATCH` 로그를 우선합니다. 제품 Assertion 실패와 복원 불일치가 함께 발생하면 복원 로그가 있어도 제품 불일치 후보로 분류될 수 있습니다. 복원 실패를 독립 원인으로 집계하는 처리는 미구현이며, 이 결과만으로 복원 성공이나 코드·환경의 정상 상태를 단정하지 않습니다.

## 5. 변경 검증과 기존 회귀

execute는 API를 호출하지 않습니다.

- Agent 3 Manifest·시험·증거 해시 확인
- 저장 계획을 현재 CP3 규칙으로 재검사
- 현재 컴파일러 출력과 같으면 시험 결과 재사용
- 다르면 현재 코드로 다시 컴파일해 별도 위치에서 재시험
- Agent 2가 확정 조건과 V1·승인 공식 TC를 대조해 기록한 관련 기존 TC ID 선택
- 신규 후보가 없거나 모두 제외돼도 선택된 기존 TC 실행과 제외 사유 보고 계속
- TC-ENV-000 환경 사전 점검 후 기존 회귀 실행
- V2 기준 HTML, V1 회귀 파일과 승인 자동화의 Snapshot·현재 Registry 해시 불변 확인

결과는 성공·Assertion 실패·실행 오류·시간 초과·건너뜀의 중립 상태로 기록합니다.
Agent 3 기본 대상은 `product_baseline/virtual-controller.html`입니다. `execute`에서
`--baseline-tests`를 생략하면 같은 폴더의 `tests/test_controller.py`를 사용합니다.
기존 회귀 코드와 V2 HTML을 임시 Workspace에 복사해 선택된 함수만 실행하며 V2의
기준 파일은 수정하지 않습니다.

## 6. Agent 4 / CP4

Agent 4는 규칙 기반 분석기입니다.

CP4는 Run ID·입력 해시, TC ID 중복, 실패 결과의 종료 코드·메시지·증거, 제품과 환경 결과 분리, Agent 3부터 검증 실행까지의 산출물 해시, 결과 합계와 보고 수치, 자동화 제외 TC의 비제품 집계를 검사합니다. V1 기준 회귀는 기준 테스트 파일 SHA-256으로 검증합니다. 승인 공식 TC는 승인 카탈로그 Snapshot 자체의 SHA-256과 해당 항목의 자동화 경로·SHA-256을 모두 확인하며, 승인 자산이 있는데 카탈로그 해시가 없으면 CP4가 차단합니다. 실행된 신규 후보가 없고 자동화 제외만 있으면 결과가 모두 통과해도 최종 권고는 `HUMAN_REVIEW`입니다.

최종 보고에는 제품·환경·고정 사례별 합계, 검토 항목, 제외 범위, 제외된 정보 부족, 자동화 제외 TC, 최종 확인 사항과 PASS·HOLD·HUMAN_REVIEW 권고가 들어갑니다.

CP4 PASS와 최종 보고 해시가 일치할 때만 외부 보고를 허용합니다. 기본 실행은 `slack_payload.json`과 `notion_payload.json`을 생성하는 Dry-run이며, `--send`에서만 환경변수의 Slack Webhook과 Notion 자격정보를 사용합니다. Notion의 TC-ID 열에는 `Run ID:TC ID`를 저장하고 같은 실행의 같은 TC만 PATCH하며 다른 Run은 POST합니다. 기존 TC ID 단독 키의 과거 페이지는 수정하지 않습니다. 첫 `external_reporting.json`은 덮어쓰지 않으며 이후 시도는 `external_reporting_attempts/<ATTEMPT-ID>/`에 별도 저장하고 이전 보고 SHA-256을 참조합니다. 각 기록은 PREVIEW·SENT·SKIPPED·FAILED·BLOCKED 상태와 Payload SHA-256을 포함합니다.

`automation_candidate=false`인 수동 확인 TC도 자동화 제외 목록에 사유와 함께 인계합니다. 모델을 호출하지 않으며, 다른 실행 가능 TC와 Agent 4 보고는 계속합니다. 실패 로그에 나오지 않은 개별 기대 결과는 통과로 추정하지 않고 판정 미확인으로 안내합니다. TC 유형(해피패스·엣지케이스·예외/결함·상태 정합성)은 설계값이고 실행 후 원인 분류와 별개입니다. Notion도 실패 여부로 TC 유형이나 우선순위를 새로 정하지 않습니다.

`사람_최종_검토.md`는 최종 보고를 사람이 확정하기 위한 작성 양식입니다. 각 검토 항목의 기대 결과, Pytest 실패 메시지에서 추출한 실제 관찰, 상대 경로 증거 링크, 제품 수정·요구사항 보완·자동화 재검토·환경 재실행·종결 선택지와 검토자·기한란을 제공합니다. `사람_최종_검토_manifest.json`은 최종 보고·검증 실행과 자동 생성 원본 문서의 해시를 연결합니다. 사람이 작성란을 채워 문서 해시가 달라지면 그 변경은 정상적인 사람 판단 기록으로 취급하고 `human-review --refresh`는 덮어쓰기를 차단합니다. 아직 사람이 편집하지 않은 자동 생성 문서만 기존 Manifest 해시가 일치할 때 `--refresh`로 갱신할 수 있습니다.

## 7. 중앙제어 실제 Run 연결

로컬 `qa_pipeline_ui`는 새 Agent나 Checkpoint가 아닙니다. `runs/<Run ID>`의 허용된
`request`, Agent 1·2 산출물, Agent 3 선택·요약·검증 실행, Agent 4 최종 보고·외부 보고
JSON을 읽어 네 단계로 요약하는 표시 계층입니다. 브라우저에는 로컬 절대경로·비밀정보·
원본 전체 산출물을 전달하지 않습니다.

기본 서버는 조회 전용이며 새 API Run을 시작할 수 없습니다. `--allow-live-run`을 명시한
경우에도 허용된 `examples/change_request*.json`만 선택할 수 있고 임의 명령·경로를 받지
않습니다. 실행 순서는 `pipeline` → `execute` → `agent4`이며 Agent 4는 `--send` 없이
호출하므로 Slack·Notion은 Dry-run입니다.
`execute` 종료 코드 2 중 환경 점검 실패로 저장된 BLOCKED 결과는 Run ID·상태·결과 해시를
확인한 뒤 Agent 4로 넘깁니다. CP4의 증거 검사는 그대로 적용하며, 결과 누락·손상이나
다른 실행 오류는 중단합니다. 보고 완료는 테스트 성공과 구분합니다.
외부 보고 조회는 최초 파일과 `external_reporting_attempts/`의 후속 기록 중 최신 상태를
표시하며, 이전 SEND 기록도 함께 표시해 후속 미리보기가 과거 전송 사실을 가리지 않게 합니다.

후보 자산 판단은 별도 `--allow-asset-approval`에서만 활성화합니다. 등록 가능 조건은
최종 권고 PASS, CP3·CP4 PASS, 변경 검증 PASSED, 완전한 Screenshot·Trace, 후보 Python·
증거·현재 대상 HTML SHA-256 일치입니다. 대상 HTML이 Run 뒤 변경됐으면 기존 검증
산출물을 덮어쓰지 않고 `asset_revalidation/<TC ID>/`에서 같은 후보를 현재 HTML에 다시
실행합니다. 이 경로는 모델이나 외부 보고 API를 호출하지 않습니다.

사람이 승인하면 원본 Agent 2 TC와 Agent 3 Python을 별도 공식 자산으로 복사하고 출처
Run·후보 TC·대상 HTML·자산 해시와 검토자·메모를 Registry에 기록합니다. 같은 Run·TC의
중복 승인은 같은 기록을 반환하고 기존 공식 파일을 덮어쓰지 않습니다. 보류는 사유만
Run에 남기며 공식 자산을 만들지 않고, 이미 승인된 자산은 화면에서 보류로 되돌릴 수
없습니다. Checkpoint PASS 자체는 이 사람 승인을 대신하지 않습니다.

현재 Registry의 공식 TC는 다음 Agent 2 실행의 기존 TC 카탈로그에 합쳐집니다. 모델이
확정 조건과 검증 동작을 대조해 선택한 공식 TC만 `execute`가 승인 Python 원본으로
실행하며, Agent 2 Snapshot과 현재 파일 SHA-256이 다르면 중단합니다.

Agent 2의 `SRS_개정_제안`은 MODIFIED·UPDATE_REQUIRED Requirement마다 현재 인수 기준,
제안 인수 기준, 근거 Condition과 사유를 가집니다. Agent 2→검증 실행→Agent 4 최종
보고→`사람_최종_검토.md`까지 같은 구조로 전달합니다. 승인 화면은 개정 전·후를 표시하고,
변경할 문구가 남아 있으면 별도 SRS 동의 없이는 공식 TC 승인을 차단합니다. 후보의
Requirement·Condition과 연결된 제안만 화면 표시와 적용 대상으로 삼습니다. 동의 시 해당 Requirement
행의 인수 기준만 원문 일치 조건으로 교체하고, Run 결정 기록과 공식 SRS 개정 기록에 전·후
SHA-256을 남깁니다. TC·자동화·Registry 기록까지 모두 성공해야 승인이 완료되며 중간 오류가
나면 이 승인에서 바뀐 본 파일과 임시 파일을 원상복구합니다. 이미 반영된 동일 제안은 멱등
처리하며 다른 문구로 바뀐 SRS에는 적용하지 않습니다.

현재 SRS 반영은 신규 후보의 공식 자산 승인에 연결됩니다. 신규 후보 없이 기존 TC만 실행한 Run은 SRS 제안을 보고할 수 있지만, 이를 단독 승인·반영하는 UI/API 경로는 없습니다.

## 8. Run 요약

중앙제어 화면의 TC 표는 `agent2_test_design.json`, 실행 결과, 자동화 제외 목록과 최종 분류를 결합한 `test_rows`를 사용합니다. 신규·관련 기존 TC 및 실제 실행된 환경 점검을 표시하고 유형 필터와 전제조건·절차·기대 결과·복원·관찰·증거 파일명 상세를 제공합니다. 승인 기존 TC의 상세 명세는 카탈로그에 기록된 해시와 현재 승인 파일이 일치할 때만 읽습니다. 기준 회귀에 상세 명세·유형이 없으면 미기록·미분류, 우선순위가 없으면 미지정으로 표시합니다. 시각은 개별 TC 수정일이 아니라 실행 묶음 기록 시각입니다.

다중 TC를 한 번의 모델 응답으로 묶지 않습니다. 각 TC는 독립 모델 요청과 독립 산출물 폴더를 사용합니다.

- agent3_selection.json: 대상 TC와 사전 제외 사유
- agent3_candidates/<tc-id>/: TC별 계획·코드·시험
- agent3_run_summary.json: 완료 TC와 자동화 제외 TC 요약
- orchestrator_manifest.json: Agent 1~3 전체 종료 상태와 주요 해시

과거 일괄 호출용 agent3_batch_* 계약은 현재 실행에서 사용하지 않습니다.
