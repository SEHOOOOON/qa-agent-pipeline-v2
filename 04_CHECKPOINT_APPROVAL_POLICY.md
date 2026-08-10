# Checkpoint·사람 승인·Baseline 보호 정책

## 문서 통제

| 항목 | 값 |
|---|---|
| 문서 ID | POL-GATE-001 |
| 버전 | 0.2 |
| 상태 | REVIEW_READY |
| 소유자 | QA |
| 관련 문서 | SRS-VCCS-BL-001, ICD-AGENT-001 |
| 적용 대상 | CP1~CP4, QA Manager, Human Promotion Gate |

## 1. 목적

본 정책은 Agent 산출물과 실행 결과에 대해 자동 진행, 재작업, 사람 검토, 차단과 Baseline 반영 조건을 정의합니다.

Checkpoint는 Agent의 결과를 대신 작성하지 않습니다. 구조·근거·정책·정합성을 검사하고 다음 행동을 결정합니다. 자연어 의미를 완벽히 판정할 수 없는 항목은 자동 PASS가 아니라 사람 검토 대상으로 남깁니다.

## 2. 기본 원칙

### GP-001 자동 진행과 정식 승인 분리

CP2 통과는 격리 코드 생성 자격이며 TC 정식 승인이 아닙니다. CP3 통과는 통합 검토 자격이며 제품 판정 사용 승인이 아닙니다.

### GP-002 정상 흐름의 단일 Promotion Gate

정상 위험 변경에서는 Agent 2와 Agent 3 뒤에 각각 사람을 멈춰 세우지 않습니다. TC 후보가 CP2를 통과하면 격리 코드 생성·시험까지 자동 진행하고, 제품 검증 전에 QA가 TC·코드·증거를 한 번에 승인합니다.

### GP-003 고위험 중간 검토

안전, 권한, 삭제, 핵심 기대결과 불명확, Baseline 충돌은 중간 사람 검토로 전환합니다.

### GP-004 Fail Closed

필수 근거, 해시, Restore 또는 Source Run 정합성이 없으면 PASS로 간주하지 않습니다.

### GP-005 입력 불변

Checkpoint는 입력 Artifact를 수정하지 않습니다. 수정이 필요하면 Rule ID와 근거를 포함해 담당 Agent로 최대 1회 반환합니다.

### GP-006 기존 Baseline 보호

사람 승인 전에는 SRS, 기존 TC, 승인 자동화와 추적성 원본을 수정하거나 삭제하지 않습니다.

## 3. 공통 Check 상태

| 상태 | 의미 | 집계 |
|---|---|---|
| PASS | 규칙 충족 | 통과 |
| FAIL | 명확한 규칙 위반 | Severity에 따라 차단·검토 |
| REVIEW | 자동 판정 불충분 | 사람 검토 |
| NOT_APPLICABLE | 현재 입력에 적용 안 됨 | 분모 제외 |
| ERROR | Grader 또는 실행기 오류 | 결과 신뢰 불가 |

FAIL은 대상 산출물의 문제이고 ERROR는 평가 시스템의 문제입니다.

## 4. Severity

| Severity | 정의 | 기본 처리 |
|---|---|---|
| CRITICAL | 잘못된 제품 판단·원본 손상·보안·추적성 상실 가능 | 즉시 BLOCKED |
| MAJOR | 핵심 품질 누락이나 의미 검토 필요 | REVISION 또는 REVIEW |
| MINOR | 가독성·설명·비핵심 메타데이터 문제 | 경고 후 진행 가능 |

Checkpoint별로 명시된 예외가 없으면 위 기본 처리를 적용합니다.

## 5. 상태 집계

### 5.1 Checkpoint 공통 집계

1. CRITICAL FAIL 또는 ERROR가 하나라도 있으면 BLOCKED입니다.
2. MAJOR FAIL이 있고 수정 가능하면 RETURN_ONCE 또는 REVISION_REQUIRED입니다.
3. 자동 의미 판단이 불충분하면 REVIEW입니다.
4. 적용 가능한 Check가 모두 PASS이고 ERROR가 없을 때만 통과 상태를 부여합니다.
5. NOT_APPLICABLE만 있는 경우 자동 PASS하지 않고 REVIEW합니다.

### 5.2 재작업 후 집계

- 동일 Rule의 CRITICAL·MAJOR 위반이 남으면 HUMAN_REVIEW 또는 BLOCKED입니다.
- 재작업으로 기대결과·Assertion이 바뀌면 자동 진행을 차단합니다.
- 수정본은 새 Artifact revision으로 저장합니다.

## 6. 전체 상태 흐름

    Input Validation
      → Agent 1
      → CP1: PASSED | PARTIAL | REVIEW | BLOCKED
      → Agent 2
      → CP2: SANDBOX_ELIGIBLE | REVIEW | BLOCKED
      → Agent 3
      → CP3: PROMOTION_READY | REVISION_REQUIRED | REVIEW | BLOCKED
      → Human Promotion Gate
      → APPROVED | REJECTED | REVISION_REQUESTED
      → Product Validation
      → Agent 4
      → CP4: VALIDATED | BLOCKED
      → PASS | HOLD | HUMAN_REVIEW

PARTIAL, SANDBOX_ELIGIBLE과 PROMOTION_READY는 승인 완료 상태가 아닙니다.

## 7. Checkpoint 1 — 변경 분석 품질

### 7.1 목적

Agent 1이 Baseline과 변경 요청을 근거로 변경 전후, 영향 범위와 정보 부족을 올바르게 분리했는지 검사합니다.

### 7.2 규칙

| Rule ID | Severity | 검사 |
|---|---|---|
| CP1-SCHEMA-001 | CRITICAL | 필수 필드·Enum·타입 |
| CP1-RUN-001 | CRITICAL | Run·Baseline·입력 해시 일치 |
| CP1-REQ-001 | CRITICAL | target Requirement ID 존재 |
| CP1-BEFORE-001 | CRITICAL | 변경 전 값이 Baseline 근거에 존재 |
| CP1-AFTER-001 | CRITICAL | 변경 후 값이 요청 원문에 존재 |
| CP1-SOURCE-001 | CRITICAL | confirmed fact의 Source Evidence |
| CP1-HALL-001 | CRITICAL | 근거 없는 기능·정책·기대값 생성 |
| CP1-GAP-001 | MAJOR | 정보 부족과 blocking 여부 분리 |
| CP1-SCOPE-001 | CRITICAL | passed·excluded 범위 충돌 없음 |
| CP1-IMPACT-001 | MAJOR | 직접·관련 영향 구분과 근거 |
| CP1-INVARIANT-001 | MAJOR | 상태 불변·회귀 위험 후보 |
| CP1-QUESTION-001 | MAJOR | 질문이 단일 쟁점·답변 가능 형태 |
| CP1-LEVEL-001 | MAJOR | 충분성 Level과 진행 상태 일치 |

### 7.3 자동 차단

- 필수 계약 오류
- Baseline 해시 불일치
- 존재하지 않는 Requirement를 확정 대상으로 사용
- 변경 전 값이 Baseline에 없음
- 변경 후 값이 요청에 없음
- 근거 없는 confirmed fact
- 정보 부족인데 전체 PROCEED
- 진행·제외 범위 충돌
- 운영 시스템·비밀값·위험 작업 포함

### 7.4 사람 검토

- 간접 영향의 업무적 타당성
- 의미상 충돌
- 핵심 기대결과의 정책 결정
- P0, 안전, 권한, 데이터 삭제 관련 변경
- CANDIDATE SRS의 TBD를 변경 대상으로 사용

### 7.5 결과

| 결과 | 조건 | 다음 단계 |
|---|---|---|
| PASSED | 전체 범위 검사 통과 | Agent 2 |
| PARTIAL | passed_scope만 확정 가능 | 해당 범위만 Agent 2 |
| REVIEW | 의미·정책 판단 필요 | 사람 검토 |
| BLOCKED | Critical 위반 | 중단 |

## 8. Checkpoint 2 — 제품 기능 TC 품질

### 8.1 목적

Agent 2가 변경 요구사항을 판정 가능한 제품 기능 TC로 바꾸었으며 추측, 중복과 검증 공백이 없는지 검사합니다.

### 8.2 3-Tier 기준

#### Tier 1 공통 QA 기준

- 정상·예외·경계값
- 명확한 사전조건
- 구체적 행동
- 판정 가능한 기대결과
- 상태 불변과 Cleanup

#### Tier 2 중앙제어 도메인 기준

- 모드·온도·풍량 제약
- 잠금·오류·게이트웨이 우선순위
- 단일·복수 장비
- 대상·비대상 장비
- UI·내부 상태·Register 정합성

#### Tier 3 기능·변경 기준

- Requirement·Change Item 근거
- 독립 실행·반복 실행
- 변경 전후와 회귀 영향
- 자동화 가능성
- 기존 TC와 추적성

### 8.3 규칙

| Rule ID | Severity | 검사 |
|---|---|---|
| CP2-SCHEMA-001 | CRITICAL | TC 필수 필드·Enum·ID 유일성 |
| CP2-TRACE-001 | CRITICAL | Requirement·Change Item 연결 |
| CP2-SOURCE-001 | CRITICAL | 기대결과별 Source Evidence |
| CP2-OBJECTIVE-001 | MAJOR | TC당 단일 주목적 |
| CP2-PRE-001 | MAJOR | 초기 상태·사전조건·Setup |
| CP2-STEP-001 | MAJOR | 재현 가능한 행동 |
| CP2-EXPECT-001 | CRITICAL | 판정 가능한 기대결과 |
| CP2-DOUBLE-001 | CRITICAL | Double-Assert 또는 승인 예외 |
| CP2-NEGATIVE-001 | MAJOR | 차단 시 상태 불변 |
| CP2-INVARIANT-001 | CRITICAL | 복수 제어 비대상 불변 |
| CP2-INDEPENDENT-001 | MAJOR | 이전 TC 비의존·Cleanup·Restore |
| CP2-DUP-001 | MAJOR | 기존 TC와 의미 중복 |
| CP2-AUTO-001 | MAJOR | 자동화 후보의 구체값·관측면 |
| CP2-DELETE-001 | CRITICAL | 물리 삭제 금지 |
| CP2-HALL-001 | CRITICAL | 근거 없는 경계값·문구·색상·시간 |

### 8.4 자동 차단

- Requirement 연결 또는 기대결과 근거 없음
- 사전조건·행동·기대결과 누락
- inferred fact를 확정 기대결과로 사용
- Double-Assert 누락과 예외 사유 없음
- 복수 제어에서 비대상 불변 누락
- 기존 TC 물리 삭제
- CP1 제외 범위 TC 생성
- 해결되지 않은 Critical Gap

### 8.5 자동화 적격성

다음 조건을 모두 만족하면 SANDBOX_ELIGIBLE입니다.

- 제품 기능 TC 계약 통과
- 기대결과 ID와 관측 대상 존재
- Setup과 Restore 방법 존재
- 로컬 환경에서 필요한 관측면 접근 가능
- 외부 시스템·위험 동작 없음
- 의미상 Critical 경고 없음

SANDBOX_ELIGIBLE은 자동화 후보 생성 자격일 뿐 TC 승인 완료가 아닙니다.

## 9. Checkpoint 3 — 자동화 코드 후보 품질

### 9.1 세 평가 축

| 축 | 확인 |
|---|---|
| 실행 가능성 | 문법, Import, Locator, Timeout, 브라우저 완주, 증거 |
| 의도 충실성 | 사전조건·행동·모든 기대결과와 Assertion 연결 |
| 안정성·검출성 | 정상 반복, 상태 격리, Restore, 대표 오류 FAIL |

어느 한 축만 통과해도 PROMOTION_READY가 될 수 없습니다.

### 9.2 정적 규칙

| Rule ID | Severity | 검사 |
|---|---|---|
| CP3-HASH-001 | CRITICAL | TC Snapshot 해시 일치 |
| CP3-SYNTAX-001 | CRITICAL | Python 문법·Import |
| CP3-TEST-001 | CRITICAL | 테스트 함수와 Playwright Fixture |
| CP3-ASSERT-001 | CRITICAL | expected_result별 Assertion 존재 |
| CP3-SETUP-001 | MAJOR | 사전조건 구현 |
| CP3-RESTORE-001 | CRITICAL | Restore 구현 |
| CP3-LOCATOR-001 | MAJOR | 실제 화면 Locator 근거 |
| CP3-TIMEOUT-001 | MAJOR | 시간 제한과 무제한 대기 금지 |
| CP3-SKIP-001 | CRITICAL | 무조건 Skip·실패 무시 금지 |
| CP3-TRUE-001 | CRITICAL | assert True·무조건 PASS 금지 |
| CP3-EXPECTED-001 | CRITICAL | 실제값을 기대값으로 재사용 금지 |
| CP3-SHELL-001 | CRITICAL | Shell·외부 URL·임의 삭제 금지 |
| CP3-BASELINE-001 | CRITICAL | 원본 파일 수정 금지 |
| CP3-SECRET-001 | CRITICAL | API Key·비밀값 포함 금지 |

### 9.3 시험 실행 규칙

- 후보 전용 임시 디렉터리
- 로컬 시뮬레이터만 허용
- 동시 실행 1개
- 실행 전 Snapshot
- Trial별 초기화
- 정상 조건 3회
- 대표 오류 조건 1~2개
- Screenshot, Trace, stdout, stderr
- 실행 후 Restore
- child process Timeout과 종료

### 9.4 안정성 판정

| 결과 | 판정 |
|---|---|
| 정상 3회 모두 PASS, Restore PASS | 안정성 후보 |
| 정상 결과 혼합 | UNSTABLE, REVIEW |
| 1회 이상 자동화 ERROR | REVISION 또는 REVIEW |
| Restore FAIL | BLOCKED |
| 증거 누락 | REVIEW 또는 BLOCKED |
| 대표 오류에서 예상 FAIL | 검출력 확인 |
| 대표 오류에서 PASS | 검출력 부족, BLOCKED |

반복 PASS는 코드 안정성을 보여 주지만 테스트 목적의 정확성을 단독 보장하지 않습니다.

### 9.5 자동 수정

Agent 3은 Locator, 대기, Fixture, Import, 내부 상태 조회와 Restore 같은 기술 문제만 최대 1회 수정할 수 있습니다.

다음 변경이 감지되면 자동 진행을 차단합니다.

- 기대값 변경
- Assertion 삭제·완화
- Requirement·TC 목적 변경
- 경계값 변경
- 제품 FAIL을 PASS로 만드는 분기

### 9.6 결과

| 결과 | 조건 | 다음 단계 |
|---|---|---|
| PROMOTION_READY | 세 축 통과 | Human Promotion Gate |
| REVISION_REQUIRED | 기술 수정 가능, 0회 수정 상태 | Agent 3 1회 반환 |
| REVIEW | 의미·환경 판단 필요 | 사람 검토 |
| BLOCKED | Critical·보안·Restore·검출력 위반 | 중단 |

## 10. Human Promotion Gate

### 10.1 검토 범위

QA는 다음을 함께 확인합니다.

- 변경 요청 원문과 Baseline
- Agent 1 분석과 제외 범위
- Agent 2 TC 목적·사전조건·기대결과
- Agent 3 코드 Diff
- expected_result–Assertion 매핑
- Locator 근거
- 정상 반복 3회
- 대표 오류 검출
- 상태 Snapshot·Restore
- 예상 Core Regression 영향

### 10.2 판정

| 판정 | 처리 |
|---|---|
| APPROVED | 승인된 TC·코드만 Product Validation에 사용 |
| REJECTED | 후보 폐기, 기존 Baseline 유지 |
| REVISION_REQUESTED | 지정 단계로 1회 반환 |
| CONDITIONAL_APPROVAL | MVP에서는 사용하지 않음. 모호한 승인 방지 |

### 10.3 중간 승인 필수 조건

- 핵심 기대결과가 모호함
- P0·안전·권한 관련 변경
- Requirement 또는 TC 비활성화 제안
- 데이터 삭제·외부 시스템 접근
- Agent 간 판단 충돌
- 오류 프로필이 제품 정책을 새로 정의함
- CANDIDATE SRS의 TBD를 확정해야 함

## 11. Product Validation Gate

사람이 승인한 변경 자동화와 기존 승인 회귀 자동화만 실행합니다.

실행 순서:

1. Change Validation
2. Feature Regression
3. Core Regression
4. 조건부 Full Regression 권고

Core Regression 실행 여부는 변경 TC PASS가 아니라 환경과 Restore 신뢰성으로 결정합니다.

| 상황 | Core Regression |
|---|---|
| 제품 기능 FAIL, 환경 정상 | 계속 실행해 영향 확인 |
| 자동화 후보 오류 | 승인 기존 자동화만 실행 가능 |
| 환경 오류 | 중단 |
| Restore 실패 | 중단 |
| 게이트웨이·초기화 불가 | 중단 |

## 12. Checkpoint 4 — 결과·보고 정합성

### 12.1 규칙

| Rule ID | Severity | 검사 |
|---|---|---|
| CP4-SCHEMA-001 | CRITICAL | 실행·요약 필수 필드·타입 |
| CP4-RUN-001 | CRITICAL | 단일 Source Execution Run |
| CP4-ID-001 | CRITICAL | test_id·tc_id 유일성 |
| CP4-COUNT-001 | CRITICAL | 총수와 상태 합계 |
| CP4-CROSS-001 | CRITICAL | A3 실행 원본과 A4 행·상태 대조 |
| CP4-SUITE-001 | MAJOR | Change·Feature·Core·Fixture 구분 |
| CP4-EVIDENCE-001 | CRITICAL | 실패별 증거 연결 |
| CP4-RESTORE-001 | CRITICAL | Restore 실패 이후 결과 무효 |
| CP4-CLASS-001 | CRITICAL | 자동화 오류의 제품 결함 오분류 |
| CP4-MODE-001 | CRITICAL | Fixture·Live 구분 |
| CP4-REPORT-001 | CRITICAL | JSON·HTML·Dashboard 수치 일치 |
| CP4-WRITE-001 | CRITICAL | 검증 전 외부 보고·Baseline 수정 금지 |

### 12.2 차단 시 처리

CP4가 BLOCKED이면 다음만 저장합니다.

- Checkpoint 결과
- 실패 Rule과 증거
- 분석 Run 상태
- 사람 검토 권고

다음은 수행하지 않습니다.

- 최종 PASS 보고서
- Slack·Notion 전송
- 포트폴리오 수치 동기화
- Baseline 반영 권고
- 기존 Summary를 현재 성공 결과로 재사용

## 13. 최종 Run Gate

| 조건 | 판정 |
|---|---|
| Critical 제품 결함 또는 Critical Check FAIL | HOLD |
| 실행 신뢰 불가, ERROR, Restore 실패, Source Run 혼합 | HOLD |
| 자동 판정 불충분, 의미 충돌, 미처리 Review | HUMAN_REVIEW |
| 모든 필수 Check PASS, 승인·증거·회귀 기준 충족 | PASS |

Run이 기술적으로 COMPLETED여도 판정은 HOLD일 수 있습니다.

## 14. 재작업 정책

- Agent별 최대 1회
- 같은 Run 안에서 revision 증가
- 원본·수정본·Diff·반환 Rule·모델 정보를 보존
- 이미 통과한 Artifact를 직접 덮어쓰지 않음
- 기대결과·Assertion 변경 감지 시 자동 재작업 금지
- 1회 후 MAJOR 이상 위반은 HUMAN_REVIEW 또는 BLOCKED
- 시스템 오류 재시도와 내용 재작업 횟수를 구분

## 15. Baseline 보호

### 15.1 승인 전

- Baseline SRS·TC·자동화는 읽기 전용
- 후보는 Run 디렉터리에만 저장
- DELETED는 DEPRECATION_PROPOSED로 기록
- 기존 TC·코드를 물리 삭제하지 않음

### 15.2 승인 시

- 승인자, 역할, 시각, 입력·출력 해시 기록
- 새 Baseline 버전과 Patch 후보 생성
- 이전 버전 보존
- Requirement–TC–Automation 추적성 갱신
- 실제 반영은 별도 명시적 명령으로 수행

### 15.3 승인 후

- 승인되지 않은 추가 변경 금지
- 실행 결과로 기대값 자동 수정 금지
- 새 변경은 새 Change Request와 Run으로 시작

## 16. 감사 기록

각 Checkpoint는 다음을 보존합니다.

- Checkpoint ID와 Rule 버전
- 입력 Artifact ID·해시
- Check별 expected·actual·evidence
- Severity와 상태
- 자동·사람 판정 주체
- 반환 대상과 사유
- 재작업 revision
- 최종 next_action
- 생성 시각

사람 결정은 Reviewer, 역할, 결정, 조건, 사유와 시각을 기록합니다.

## 17. 정책 인수 조건

- Critical FAIL이 자동 진행 상태로 집계되면 안 됩니다.
- ERROR를 제품 FAIL로 변환하면 안 됩니다.
- NOT_APPLICABLE을 PASS로 계산하면 안 됩니다.
- CP2 SANDBOX_ELIGIBLE을 정식 승인으로 표시하면 안 됩니다.
- CP3 PROMOTION_READY 후보가 사람 승인 없이 제품 검증에 사용되면 안 됩니다.
- Restore 실패 이후 결과가 유효 보고에 포함되면 안 됩니다.
- CP4 BLOCKED 상태에서 외부 보고나 Baseline 권고를 생성하면 안 됩니다.
- 재작업이 1회를 초과하면 안 됩니다.
- 원본과 수정본, Diff와 사유가 보존되어야 합니다.
- 승인 전 기존 Baseline 파일이 변경되면 안 됩니다.

## 18. 포트폴리오 표현

권장:

> Agent 산출물이 계약 기반 Checkpoint를 통과하면 격리 검증까지 자동 진행되고, 제품 판정 전에 QA가 TC·코드·반복 실행·오류 검출 증거를 통합 승인합니다.

금지:

- 사람 없이 자동 승인
- 완전 자율 QA 조직
- 생성 코드 신뢰성 보장
- Checkpoint가 자연어 의미를 완벽히 판정
- 모든 결함 자동 검출
