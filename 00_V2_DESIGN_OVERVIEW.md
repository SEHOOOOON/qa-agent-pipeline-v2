# QA Agent Pipeline V2 설계 명세

## 문서 통제

| 항목 | 값 |
|---|---|
| 문서 ID | DES-V2-001 |
| 버전 | 0.2 |
| 상태 | REVIEW_READY |
| 소유자 | QA |
| 관련 SRS | SRS-VCCS-BL-001 |
| 구현 상태 | 설계 완료, Live Runtime 미구현 |
| 작성일 | 2026-08-10 |

## 1. 배경과 문제 정의

V1은 4-Agent·4-Checkpoint QA Workflow, 가상 중앙제어기와 기존 Playwright 실행을 하나의 포트폴리오 흐름으로 보여 줍니다. 그러나 다음 실행 간격이 있습니다.

- Agent 1·2 결과가 실제 모델 호출 결과가 아니라 저장된 Demo입니다.
- 자유 입력이 Agent 산출물과 실제 TC를 바꾸지 않습니다.
- Agent 2 산출물이 Agent 3 자동화 코드 생성의 실제 입력이 아닙니다.
- Agent 3은 사람이 작성한 기존 자동화를 실행하지만 신규 코드를 생성하지 않습니다.
- 화면의 Agent 3·4 진행 모달은 실제 실행 상태가 아닌 타이머 기반 Demo입니다.

V2의 핵심은 Agent 수를 늘리는 것이 아니라 입력, 근거, 산출물, 코드와 실행 결과 사이의 실제 인과관계를 구현하는 것입니다.

## 2. 프로젝트 목표

### 2.1 업무 목표

운영 중인 중앙제어 시스템에 변경 요청이 접수되었을 때 기존 승인 QA 자산을 보호하면서 다음 작업을 수행합니다.

1. 기존 Baseline과 변경 요청의 차이를 분석합니다.
2. 변경에 필요한 제품 기능 TC 변경안을 작성합니다.
3. 승인 가능한 TC를 Playwright 코드 후보로 구현합니다.
4. 생성 코드의 실행 가능성·의도 충실성·안정성·검출력을 검증합니다.
5. 사람이 통합 승인한 코드만 제품 검증에 사용합니다.
6. 실제 실행 결과를 근거로 제품·요구사항·자동화·환경 문제를 분리합니다.

### 2.2 품질 목표

- Agent가 근거 없는 요구사항이나 기대결과를 추가하지 않도록 합니다.
- 앞 단계 승인 산출물만 다음 단계 입력으로 사용합니다.
- 생성 코드가 TC 목적이나 Assertion을 변경하지 못하게 합니다.
- Fixture와 Live 실행을 사용자와 보고서에서 구분합니다.
- 제품 실패와 생성 코드 실패를 동일 결과로 처리하지 않습니다.
- 사람 승인 전 Baseline 원본을 변경하지 않습니다.

### 2.3 성공 지표

| 지표 | MVP 기준 |
|---|---|
| 입력 추적성 | 변경 원문부터 최종 보고까지 Artifact ID 연결 100% |
| Requirement 추적성 | 신규·수정 TC의 Requirement ID 연결 100% |
| Assertion 추적성 | 승인 기대결과와 코드 Assertion 매핑 100% |
| 코드 격리 | 원본 Baseline 수정 0건 |
| 정상 반복 | 승인 후보 1건을 동일 조건 3회 실행 |
| 오류 검출 | 대표 오류 프로필 1~2개에서 예상 FAIL 확인 |
| 결과 정합성 | 실행 원본·JSON·최종 보고 수치 일치 |
| 승인 통제 | 사람 승인 없는 Baseline 승격 0건 |

지표의 달성 여부는 실제 Run Artifact로 검증하며 화면 애니메이션으로 대체하지 않습니다.

## 3. 범위

### 3.1 MVP 포함

- 승인 후보 Baseline SRS와 기존 TC 입력
- MODIFIED 변경 요청 한 건
- Agent 1·2·3 실제 모델 호출
- Agent 1→2→3 Artifact 자동 인계
- Agent 2의 신규 또는 수정 제품 기능 TC 한 건 이상
- Agent 3의 Playwright 코드 후보 한 건
- Playwright 기반 화면 관찰과 Locator 근거
- QA Bridge를 통한 내부 상태 Assertion
- 정적 검사, 격리 시험, 정상 반복 3회
- 대표 오류 프로필 1~2개
- 사람의 통합 Promotion Gate
- 변경 검증과 기존 Core Regression
- Agent 4 결정론적 결과 분석
- Run Manifest와 최종 보고서

### 3.2 제외

- ADDED·DELETED를 포함한 모든 변경 유형의 완전 지원
- 전체 TC와 전체 자동화의 자동 재작성
- Full Regression Suite 전체 구현
- 무제한 Agent 대화와 재작업
- 사람 없는 자동 Baseline 반영
- 운영 시스템·실제 장비 접근
- 다중 사용자·병렬 Run
- 모든 결함 유형에 대한 자동 Fault Injection
- 완전한 Self-Healing
- 여러 모델 비교와 외부 협업 도구 연동

## 4. 설계 원칙

### DP-001 Baseline 우선

AI 출력이 아니라 사람이 승인한 Baseline이 제품 기대결과의 기준입니다.

### DP-002 후보와 승인 자산 분리

Agent가 생성한 TC와 코드는 후보입니다. Checkpoint 통과는 격리 실행 자격이며 정식 승인을 의미하지 않습니다.

### DP-003 생성과 판정 분리

생성형 모델은 분석·TC·코드 후보를 제안합니다. 계약 검사, 해시, 금지 코드, 수치 집계와 최종 상태 전이는 결정론적 코드가 담당합니다.

### DP-004 최소 권한

Agent는 자신의 단계 산출물만 작성할 수 있습니다. Agent 3은 승인 TC의 목적·기대결과·경계값을 바꿀 수 없습니다.

### DP-005 Fail Closed

필수 근거, Run ID, Restore 또는 증거가 불완전하면 자동 PASS가 아니라 REVIEW 또는 BLOCKED로 처리합니다.

### DP-006 재현 가능성

모델, Prompt, 입력, 출력, 해시, 실행 환경과 증거를 저장해 같은 Run의 판단 근거를 다시 확인할 수 있어야 합니다.

### DP-007 정직한 실행 표기

Fixture, Live Model, 실제 Playwright, 저장된 결과 재생을 명확히 구분합니다.

## 5. 시스템 구성

| 구성요소 | 유형 | 책임 |
|---|---|---|
| Dashboard | 표시·입력 계층 | 변경 접수, 단계 상태, 승인과 증거 조회 |
| QA Manager | 결정론적 상태 머신 | 단계 제어, Artifact 인계, 재작업 횟수, Run 상태 |
| Baseline Store | 읽기 전용 입력 | SRS, 기존 TC, Reference Automation, 추적성 |
| Agent 1 | 생성형 모델 | 변경 분석 |
| Checkpoint 1 | 규칙·사람 검토 | 근거·충분성·범위 판정 |
| Agent 2 | 생성형 모델 | 제품 기능 TC Change Set |
| Checkpoint 2 | 규칙·사람 검토 | 3-Tier·추적성·독립성 판정 |
| Agent 3 | 모델+Playwright 도구 | 자동화 계획과 코드 후보 |
| Checkpoint 3 | 규칙+격리 실행 | 코드·TC 일치, 안정성, 검출력 |
| Promotion Gate | 사람 승인 | TC·코드·증거 통합 승인 |
| Regression Executor | Pytest·Playwright | 승인 자동화 실행 |
| Agent 4 | 결정론적 Python | 실패 분류·수치 집계·보고 |
| Checkpoint 4 | 결정론적 검사 | Source Run·결과·증거 정합성 |
| Run Store | append-only 저장 | 원본·정규화·검사·증거·보고 |

## 6. 실행 Lane

### 6.1 Change Authoring Lane

    Baseline Snapshot
      + Change Request
      → Agent 1
      → CP1
      → Agent 2
      → CP2
      → Agent 3
      → CP3
      → Promotion Gate
      → Baseline 반영 권고

이 Lane은 변경 요청이 접수된 시점에만 실행합니다. 매 회귀 실행마다 TC나 코드를 다시 만들지 않습니다.

### 6.2 Product Validation Lane

    승인된 변경 자동화
      → Change Validation
      → Feature Regression
      → Core Regression
      → Agent 4
      → CP4
      → PASS | HOLD | HUMAN_REVIEW

제품 판정에는 Promotion Gate를 통과한 자동화만 사용합니다.

### 6.3 Offline Evaluation Lane

프로젝트 2는 Agent 1·2·3을 동일 입력으로 반복 호출해 규칙 준수, 환각, 결과 변동, 비용과 지연을 평가합니다. Product Validation Run과 결과를 섞지 않습니다.

## 7. 단계별 책임

### 7.1 QA Manager

- Run ID와 Baseline Snapshot을 생성합니다.
- 입력 원문과 파일 해시를 기록합니다.
- Checkpoint 통과 Artifact만 다음 단계에 전달합니다.
- Agent별 재작업을 최대 1회로 제한합니다.
- WAITING_FOR_USER, REVIEW, BLOCKED 상태를 관리합니다.
- Agent가 Baseline 경로를 직접 수정하지 못하게 합니다.
- 최종 승인 결과와 감사 이력을 보존합니다.

QA Manager는 LLM이 아니라 Python 상태 머신으로 구현합니다.

### 7.2 Agent 1 — Change Analyst

할 수 있는 일:

- 기존 SRS와 변경 원문 비교
- 변경 유형과 대상 Requirement 후보 식별
- 직접·관련 영향과 불변 조건 제안
- 확정·추정·정보 부족 분리
- 진행·부분 진행·질문·차단 권고

할 수 없는 일:

- 제품 기능 TC 또는 코드 작성
- 없는 Requirement를 확정 사실로 생성
- TBD를 임의 정책으로 결정
- 제품 PASS/FAIL과 릴리즈 결정

### 7.3 Agent 2 — Test Designer

할 수 있는 일:

- NEW, UPDATED, REGRESSION, DEPRECATION_PROPOSED, NO_IMPACT 제안
- 3-Tier 기준과 도메인 규칙을 적용한 제품 기능 TC 작성
- UI·내부 상태·Register·불변 Assertion 정의
- 실행 세트 추천

할 수 없는 일:

- Agent 1 제외 범위 테스트
- 근거 없는 경계값·문구·색상 생성
- 기존 TC 물리 삭제
- Locator·Playwright 코드 작성

### 7.4 Agent 3 — Automation Engineer

할 수 있는 일:

- 승인 TC를 구현 계획과 Playwright 코드 후보로 변환
- Playwright 도구로 실제 요소와 Locator 확인
- QA Bridge로 내부 상태 Assertion 구성
- Locator, 대기, Fixture 등 기술 문제 최대 1회 수정

할 수 없는 일:

- 테스트 목적·경계값·기대결과 변경
- Assertion 삭제 또는 실패 무시
- 실제 제품 값을 기대값으로 재사용
- Shell, 외부 URL, 임의 파일 삭제, 원본 자산 수정

### 7.5 Agent 4 — Result Analysis Engine

- 실제 실행 원본을 정규화합니다.
- 제품·요구사항·생성 코드·실행 코드·환경·증거 부족을 분류합니다.
- 변경·회귀·Pipeline Fixture 결과를 분리합니다.
- Source Run과 보고 수치를 대조합니다.
- Baseline 반영 여부를 권고합니다.

V2에서도 Agent 4는 결정론적 Python 분석기이며 생성형 AI Agent라고 표현하지 않습니다.

## 8. Artifact 흐름

각 단계는 다음 공통 원칙을 따릅니다.

- 원본 입력은 수정하지 않습니다.
- 모델 원본 응답과 정규화 결과를 분리합니다.
- 모든 Artifact는 Run ID, Stage ID, 입력 Artifact ID와 해시를 가집니다.
- 다음 단계는 Checkpoint를 통과한 정규화 Artifact만 읽습니다.
- 수정본은 새 Artifact로 저장하고 이전 버전을 보존합니다.
- Dashboard는 저장된 Manifest와 Artifact만 표시합니다.

    change_request
      → agent1/raw + agent1/normalized
      → checkpoint1
      → agent2/raw + agent2/tc_changeset
      → checkpoint2
      → agent3/plan + candidate code + manifest
      → checkpoint3 + trial evidence
      → human_approval
      → product_validation
      → agent4_summary
      → checkpoint4
      → final_report

## 9. Run 상태 모델

| 상태 | 의미 |
|---|---|
| CREATED | 입력·Baseline Snapshot 생성 |
| VALIDATING_INPUT | 형식·해시·충분성 사전 검사 |
| RUNNING | Agent 또는 실행 단계 수행 |
| WAITING_FOR_USER | 핵심 정보 부족으로 답변 대기 |
| HUMAN_REVIEW | 의미 판단 또는 승인 필요 |
| REVISION | 허용된 1회 재작업 |
| BLOCKED | 안전·계약·환경 조건으로 진행 중단 |
| COMPLETED | 모든 필수 단계 종료 |
| ERROR | 시스템 오류로 Run 비정상 종료 |

단계 상태와 최종 제품 판정은 구분합니다. 예를 들어 Run은 COMPLETED이면서 최종 판정은 HOLD일 수 있습니다.

## 10. 사람 승인 설계

정상 흐름에서 Agent 2와 Agent 3 뒤에 각각 사람을 멈춰 세우지 않습니다. CP2를 통과한 TC는 원본을 건드리지 않는 격리 환경에서 코드 후보 생성과 시험까지 진행할 수 있습니다.

Promotion Gate에서 QA는 다음을 한 화면에서 검토합니다.

- 원본 변경 요청과 Baseline
- Agent 1 분석·제외 범위·미확정 정보
- Agent 2 TC 변경안
- Agent 3 코드 Diff
- 기대결과–Assertion 매핑
- 정상 반복 결과
- 대표 오류 검출 결과
- Restore 결과와 Core Regression 영향

단, 안전·권한·삭제·핵심 기대결과 불명확과 같은 고위험 변경은 중간 사람 검토로 전환합니다.

## 11. 자동화 코드 신뢰성

자동화 후보는 세 축을 모두 통과해야 합니다.

| 축 | 확인 내용 |
|---|---|
| 실행 가능성 | 문법, Locator, Timeout, 브라우저 완주, 증거 생성 |
| 의도 충실성 | 사전조건·행동·모든 기대결과와 Assertion 1:1 연결 |
| 안정성·검출성 | 반복 일관성, 상태 복원, 대표 오류 조건 FAIL |

정상 환경에서 PASS하는 것만으로는 승인하지 않습니다. 대표 오류에서 실패하지 않는 코드는 검출력이 부족하므로 Promotion 대상이 아닙니다.

## 12. 격리와 보안

- 후보 코드는 Run 전용 임시 디렉터리에서 실행합니다.
- 승인 자동화와 Baseline 파일은 읽기 전용으로 제공합니다.
- 외부 네트워크와 운영 시스템 접근을 차단합니다.
- 허용 URL은 로컬 시뮬레이터로 제한합니다.
- subprocess는 shell을 사용하지 않고 시간 제한을 둡니다.
- stdout, stderr, Trace와 Screenshot 크기를 제한합니다.
- API Key와 환경변수 원문을 Artifact에 저장하지 않습니다.
- Restore 실패 시 후속 제품 판정을 차단합니다.
- 동시 Run은 MVP에서 1개로 제한합니다.

## 13. 관측성과 보고

모든 Run은 최소한 다음을 제공해야 합니다.

- Run ID, 모드, 시작·종료 시각
- Baseline 버전·해시
- 변경 요청 해시
- Agent·모델·Prompt 버전
- 단계별 입력·출력 Artifact
- Checkpoint Rule 결과
- 사람 결정과 사유
- 실행 TC·PASS·FAIL·BLOCKED·NOT_EXECUTED 수
- Screenshot·Trace·상태 Snapshot
- Restore 결과
- 최종 PASS, HOLD 또는 HUMAN_REVIEW

UI 애니메이션과 색상은 증거가 아닙니다. 최종 수치는 JSON 원본을 기준으로 렌더링합니다.

## 14. 오류 처리

| 오류 | 처리 |
|---|---|
| 입력 Schema 오류 | Agent 호출 전 BLOCKED |
| 모델 응답 파싱 실패 | 1회 형식 수정 요청 후 HUMAN_REVIEW |
| 근거 없는 제품 기대값 | 해당 Artifact 차단 |
| Locator·대기 기술 오류 | Agent 3 최대 1회 수정 |
| Assertion 변경 감지 | 즉시 BLOCKED |
| 후보 시험 실패 | 제품 판정 금지, 자동화 문제로 분류 |
| Restore 실패 | 후속 실행 차단 |
| Source Run 혼합 | 보고·외부 전송 차단 |
| Agent 4 정합성 오류 | HOLD |
| 사람 승인 거절 | 후보 폐기, 기존 Baseline 유지 |

## 15. MVP 대표 시나리오

특정 온도 변경 문구를 코드나 Prompt에 고정하지 않습니다. 사용자는 SRS의 기존 Requirement를 대상으로 한 MODIFIED 변경 요청을 입력합니다.

MVP는 다음 결과를 보여야 합니다.

1. Agent 1이 대상 Requirement와 변경 전후 값을 근거와 함께 식별합니다.
2. CP1이 Baseline 존재 여부와 정보 충분성을 검사합니다.
3. Agent 2가 신규 또는 수정 TC와 회귀 후보를 만듭니다.
4. CP2가 3-Tier·Double-Assert·불변 조건을 검사합니다.
5. Agent 3이 승인 TC 한 건의 코드 후보를 만듭니다.
6. CP3이 정적 검사, 정상 3회와 대표 오류 1~2개를 실행합니다.
7. QA가 TC·코드·증거를 통합 승인합니다.
8. 변경 검증과 기존 Core Regression을 실행합니다.
9. Agent 4와 CP4가 동일 Source Run의 결과를 보고합니다.

## 16. 완료 기준

### DESIGNED

- SRS, 입력 계약, Agent 계약, Checkpoint와 승인 정책이 일치합니다.
- 요구사항과 구현·TC의 현재 차이를 기록합니다.

### IMPLEMENTED

- QA Manager, 모델 Adapter, Artifact Store와 Agent 1→3 인계가 코드로 동작합니다.
- Agent 3 후보 생성과 격리 시험이 실제로 실행됩니다.

### LIVE_VERIFIED

- 실제 모델과 브라우저 실행 증거가 있습니다.
- 서로 다른 변경 요청이 다른 분석·TC·코드 후보를 생성합니다.
- 동일 입력 반복 결과와 실패 사례를 재현할 수 있습니다.

### PORTFOLIO_SYNCED

- 포트폴리오 설명, 코드, 영상, 보고서와 GitHub 상태가 일치합니다.
- Fixture와 Live 범위를 정확하게 설명합니다.

## 17. 구현 순서

1. Baseline SRS와 변경 요청 입력 검증
2. Run Manifest와 Artifact Store
3. Agent 1 모델 Adapter와 CP1
4. Agent 2 모델 Adapter와 CP2
5. Agent 3 모델·Playwright 도구 Adapter
6. 후보 코드 정적 검사와 격리 Executor
7. Promotion Gate
8. Product Validation과 Agent 4 연계
9. Dashboard와 최종 보고서
10. 프로젝트 2 반복 평가 연계

## 18. 주요 위험과 통제

| 위험 | 영향 | 통제 |
|---|---|---|
| 요구사항 근거 부족 | 환각·잘못된 TC | Source ID 강제, TBD 분리 |
| 모델 결과 변동 | 품질 편차 | 정규화·Checkpoint·오프라인 반복 평가 |
| 생성 코드 위험 | 원본 손상·오탐 | Sandbox, 금지 코드, 사람 승인 |
| 테스트가 제품에 맞춰짐 | 결함 은폐 | 기대결과 해시, Assertion 변경 차단 |
| Fixture를 Live로 오해 | 포트폴리오 신뢰 저하 | 실행 모드·호출 여부 표시 |
| 자동화 오류의 제품 오분류 | 잘못된 결함 보고 | 생성·실행·제품 실패 분리 |
| 상태 오염 | Flaky·오판 | Snapshot, Restore, 실패 시 차단 |
| Scope 확장 | 프로젝트 미완료 | MODIFIED 한 건과 자동화 한 건으로 MVP 제한 |

## 19. 포트폴리오 표현 기준

권장 표현:

> 변경 요청과 승인된 Baseline을 실제 Agent 입력으로 연결하고, 생성된 제품 기능 TC와 Playwright 코드 후보를 품질 게이트와 격리 실행으로 검증하는 V2를 설계했습니다. 생성 코드는 사람의 통합 승인 후에만 제품 검증에 사용합니다.

구현 전 금지 표현:

- 완전 자율 멀티 에이전트 QA 팀
- 생성 코드의 신뢰성 보장
- 모든 변경 요구사항 자동 처리
- 사람 없이 자동 승인·배포
- Full Regression 자동화 완성
- Agent 4가 생성형 AI로 원인을 추론
