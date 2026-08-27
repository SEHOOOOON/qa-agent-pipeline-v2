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

입력은 검증된 Agent 1 산출물, 확정 조건, 관련 SRS와 허용된 기존 사람 작성·자동화 TC 카탈로그입니다. 기존 TC 카탈로그에는 TC ID·Requirement ID·함수명과 실제 검증 동작이 함께 제공됩니다.

제품 기능 TC는 TC ID·목적·유형, Requirement·조건 ID, 중앙 관제 패널 경로, 대상 역할·시험 데이터, 조건 실행 방식, 초기 조건·단계·기대 결과, 3단계 QA 기준, 독립 실행·복원, 이중 검증 정책을 가집니다.

TC 구성 기준:

- 하나의 TC는 입력값 하나가 아니라 하나의 관제점에서 하나의 업무 규칙을 검증합니다.
- 같은 업무 규칙의 하한·상한, 같은 비활성 규칙을 공유하는 여러 모드처럼 입력 조건만 다르면 한 TC로 묶을 수 있습니다.
- 독립 조건은 `INDEPENDENT_VARIANTS`로 표시하고 조건 사이의 재준비 절차를 `intermediate_reset_steps`에 기록합니다.
- 순서 자체가 검증 대상인 전환은 `SEQUENTIAL_TRANSITION`으로 표시합니다. 단일 구간은 `SINGLE_FLOW`입니다.
- 묶음 TC의 복수 모드·온도는 `requested_modes`·`requested_temperatures_c`에 빠짐없이 기록합니다.
- 각 Expected Result는 관찰값 하나만 가지며 `verify_after_step`으로 판정할 단계에 연결합니다. Expected Result 분리는 TC 분리를 뜻하지 않습니다.
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
| 기존 TC 대조 | Requirement ID와 검증 동작을 함께 대조해 그대로 유효한 기존 TC만 선택하고 기존 회귀의 후보 재생성 금지 |
| 조건 처리 경로 | 모든 확정 Condition을 변경분 후보 또는 관련 기존 TC에 연결하고 조용한 누락 차단 |

Agent 1이 `VERIFY`로 확정한 Requirement와 카탈로그 검증 동작이 연결되면 해당 기존 TC를 결정론적으로 보충합니다. 모델이 직접 변경된 Requirement의 기존 TC를 제외한 판단은 자동으로 뒤집지 않습니다. 보충 내역은 `agent2_regression_selection_normalization.json`에 Requirement·Condition·TC ID와 함께 기록하며 제품 기대 결과는 바꾸지 않습니다.

중복 기술 ID는 의미·값·단계·Requirement를 바꾸지 않는 경우에만 결정론적으로 다시 번호를 매깁니다.

CP2는 복수 입력값·단계 연결·초기화·판정 시점 같은 구조적 계약을 자동 검사하지만, 자연어로 표현된 두 조건이 실제로 완전히 같은 업무 규칙인지를 모든 경우에 확정한다고 주장하지 않습니다. Agent 2는 변경 요청·SRS 근거로 묶음 이유를 기록하고, 사람은 최종 보고에서 TC 분리 수준이 현업 기준에 맞는지 확인합니다. 서로 다른 UI 관찰값을 한 Expected Result에 합치는 것은 계속 차단하지만, `FAN 모드에서 온도 버튼은 비활성화된다`처럼 모드가 시험 조건을 나타낼 뿐 별도 화면 모드 표시를 검증하지 않는 문장은 복합 관찰로 보지 않습니다.

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

이 유연성은 자유 코드 실행을 뜻하지 않습니다. 실제 UI에서 관찰되지 않은 Selector, TC에 없는 값·Expected Result, 임의 JavaScript·쉘·파일·외부 네트워크 조작은 계속 차단합니다. 관찰된 표준 조작으로 표현할 수 없는 기술이 실제로 필요한 경우에만 자동화 지원 범위 확장 사유를 남깁니다.

시험 결과:

- PASS: 코드와 제품 관찰이 기대와 일치
- PRODUCT_MISMATCH_CANDIDATE: 코드·환경 증거는 신뢰 가능하지만 관찰이 기대와 다름
- AUTOMATION_ERROR: 자동화 코드 또는 실행 문제
- ENVIRONMENT_ERROR: 브라우저·의존성·대상 환경 문제
- TIMEOUT: 제한 시간 초과

앞의 두 결과만 증거가 완전할 때 실행 완료 후보로 인계합니다. 자동화할 수 없는 TC는 자동화_제외_TC에 사유를 남기고 다른 TC를 계속 처리합니다.

기존 중앙 관제 온도·모드 묶음 TC에서 고정 초기값이 없으면 `restore_observed_hvac_state=true`를 사용합니다. Agent 3 계획은 RESTORE 단계에 `RESTORE_OBSERVED_HVAC` 한 건만 두며, 컴파일러가 실행 직전 대상 장비의 `mode`·`setTemp`를 저장하고 시험 뒤 모드 선택·온도 조정·적용을 수행합니다. 복원 후 두 내부 값이 저장값과 다르면 `RESTORE_MISMATCH`로 시험을 신뢰하지 않습니다. 고정 초기값 복원과 동적 복원을 섞거나 이 동작을 일반 기능에 사용하는 계획은 CP3에서 차단합니다.

## 5. 변경 검증과 기존 회귀

execute는 API를 호출하지 않습니다.

- Agent 3 Manifest·시험·증거 해시 확인
- 저장 계획을 현재 CP3 규칙으로 재검사
- 현재 컴파일러 출력과 같으면 시험 결과 재사용
- 다르면 현재 코드로 다시 컴파일해 별도 위치에서 재시험
- Agent 2가 확정 조건과 기존 TC를 대조해 기록한 관련 기존 TC ID 선택
- TC-ENV-000 환경 사전 점검 후 기존 회귀 실행
- Project1 원본 해시 불변 확인

결과는 성공·Assertion 실패·실행 오류·시간 초과·건너뜀의 중립 상태로 기록합니다.

## 6. Agent 4 / CP4

Agent 4는 규칙 기반 분석기입니다.

CP4는 Run ID·입력 해시, TC ID 중복, 실패 결과의 종료 코드·메시지·증거, 제품과 환경 결과 분리, Agent 3부터 검증 실행까지의 산출물 해시, 결과 합계와 보고 수치, 자동화 제외 TC의 비제품 집계를 검사합니다.

최종 보고에는 제품·환경·고정 사례별 합계, 검토 항목, 제외 범위, 제외된 정보 부족, 자동화 제외 TC, 최종 확인 사항과 PASS·HOLD·HUMAN_REVIEW 권고가 들어갑니다.

CP4 PASS와 최종 보고 해시가 일치할 때만 외부 보고를 허용합니다. 기본 실행은 `slack_payload.json`과 `notion_payload.json`을 생성하는 Dry-run이며, `--send`에서만 환경변수의 Slack Webhook과 Notion 자격정보를 사용합니다. Notion은 TC ID로 조회한 뒤 기존 페이지는 PATCH, 없는 TC는 POST합니다. 첫 `external_reporting.json`은 덮어쓰지 않으며 이후 시도는 `external_reporting_attempts/<ATTEMPT-ID>/`에 별도 저장하고 이전 보고 SHA-256을 참조합니다. 각 기록은 PREVIEW·SENT·SKIPPED·FAILED·BLOCKED 상태와 Payload SHA-256을 포함합니다.

`사람_최종_검토.md`는 최종 보고를 사람이 확정하기 위한 작성 양식입니다. 각 검토 항목의 기대 결과, Pytest 실패 메시지에서 추출한 실제 관찰, 상대 경로 증거 링크, 제품 수정·요구사항 보완·자동화 재검토·환경 재실행·종결 선택지와 검토자·기한란을 제공합니다. `사람_최종_검토_manifest.json`은 최종 보고·검증 실행과 자동 생성 원본 문서의 해시를 연결합니다. 사람이 작성란을 채워 문서 해시가 달라지면 그 변경은 정상적인 사람 판단 기록으로 취급하고 `human-review --refresh`는 덮어쓰기를 차단합니다. 아직 사람이 편집하지 않은 자동 생성 문서만 기존 Manifest 해시가 일치할 때 `--refresh`로 갱신할 수 있습니다.

## 7. Run 요약

다중 TC를 한 번의 모델 응답으로 묶지 않습니다. 각 TC는 독립 모델 요청과 독립 산출물 폴더를 사용합니다.

- agent3_selection.json: 대상 TC와 사전 제외 사유
- agent3_candidates/<tc-id>/: TC별 계획·코드·시험
- agent3_run_summary.json: 완료 TC와 자동화 제외 TC 요약
- orchestrator_manifest.json: Agent 1~3 전체 종료 상태와 주요 해시

과거 일괄 호출용 agent3_batch_* 계약은 현재 실행에서 사용하지 않습니다.
