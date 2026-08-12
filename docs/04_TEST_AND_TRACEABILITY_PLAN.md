# V2 테스트 및 추적성 계획

## 1. 목적과 현재 상태

이 문서는 QA Agent Pipeline V2의 구현 단계별 검증 방법과 증거 연결 규칙을 정의합니다. Project1의 기존 TC 분류·Coverage·알려진 한계는 [Project1 기준 자산 감사](05_PROJECT1_BASELINE_AUDIT.md)에서 관리합니다.

| 영역 | 현재 상태 | 검증 근거 |
|---|---|---|
| Product SRS 파서 | 구현 | tests/test_pipeline.py |
| Agent 1 OpenAI Adapter | 구현 | tests/test_pipeline.py, 로컬 Live Run |
| Checkpoint 1 | 구현 | tests/test_pipeline.py |
| Agent 2·Checkpoint 2 | 구현 | tests/test_pipeline.py, 같은 Run의 Live 인계 |
| Agent 3·Checkpoint 3 | 설계 | 아직 코드 생성·격리 실행기 없음 |
| V2 Orchestrator | 설계 | 아직 End-to-End Run 없음 |
| Agent 4 V2 연동 | 설계 | Project1 규칙 엔진은 있으나 V2 중립 계약 미연결 |

현재 자동 테스트는 Product SRS·Agent 1·CP1·Agent 2·CP2 범위 22건입니다. 로컬 Live Run 1건에서 Agent 1·2의 실제 호출과 자동 인계를 확인했지만, 반복 안정성이나 Agent 3 이후 전체 파이프라인 완성을 의미하지 않습니다.

## 2. 검증 원칙

- 문서의 계획과 구현 완료 상태를 구분합니다.
- 제품 Requirement, 테스트 하네스, 기존 회귀 코드와 Pipeline Fixture를 별도 자산으로 관리합니다.
- 모델 원문, 정규화 JSON, Checkpoint 결과와 다음 단계 입력을 Artifact ID로 연결합니다.
- Checkpoint 자동 검사는 구조·정확한 ID·명백한 정책 위반을 확인합니다.
- 자연어 의미의 타당성, 간접 영향의 완전성과 제품 정책 선택은 완전 자동 판정하지 않습니다.
- 저장하지 않은 Screenshot·Trace나 실행하지 않은 시험을 증거로 표시하지 않습니다.
- 정식 QA 자산 등록 결정 전에는 Project1 원본을 변경하지 않습니다.

## 3. 단계별 테스트

### 3.1 Product SRS 파서

**현재 구현**

- Markdown 요구사항 표에서 REQ ID·요구사항·인수 기준을 읽습니다.
- 중복 Requirement ID와 요구사항 미검출을 차단합니다.
- 모델에는 SRS 전체 설명이 아니라 파싱된 요구사항 행만 전달합니다.

**현재 제한**

- 모든 요구사항 행을 전달하며 관련 Requirement 검색은 아직 없습니다.
- 자연어 의미 검색과 문서 버전 Hash는 아직 구현하지 않았습니다.
- Requirement 간 관계는 표의 ID 존재만으로 자동 검증하지 않습니다.

**필수 회귀 테스트**

- Requirement 20개 이상 로드
- REQ-TEMP-001 문장과 인수 기준 유지
- 신규 REQ-NOTIFY-001 로드
- 중복 ID 입력 실패
- 요구사항 표가 없는 문서 실패

### 3.2 Agent 1·Checkpoint 1

**현재 구현**

- MODIFIED 변경 요청 Schema 검증
- OpenAI Responses API의 구조화 출력
- store=false 호출
- 요청 ID·대상 Requirement·변경 유형·before·after 검사
- Agent 2 전달용 확정 조건과 MODIFIED·VERIFY Requirement 연결 검사
- 확정 조건의 변경 요청·SRS 원문 출처 검사
- 변경 요청 acceptance_notes 전체 전달 여부 검사
- 확정 조건과 제외 범위 중복 및 out_of_scope 보존 검사
- 정보 부족·질문·진행 판정 일관성과 불필요한 재확인 탐지

**현재 제한**

- CP1은 영향 Requirement가 존재하는지는 확인하지만 영향 관계의 의미적 타당성을 보장하지 않습니다.
- Agent 1 결과를 한 입력으로 1회 공개 검증했으며 반복 일관성 평가는 아직 하지 않았습니다.
- 현재 SRS의 모든 요구사항 행을 전달합니다.

**추가할 테스트**

- SRS에 없는 대상 Requirement 차단
- 변경 전 값이 대상 SRS에 없을 때 REVIEW
- 변경 후 값 변경·누락 차단
- 확정 조건의 출처 원문이 요청·SRS에 없을 때 차단
- acceptance_notes 중 하나라도 Agent 2 전달 조건에서 누락되면 차단
- 요청 out_of_scope 누락과 확정 조건 중복 차단
- 무관하지만 존재하는 Requirement를 VERIFY로 제시했을 때 의미 검토 후보 생성
- 서로 다른 변경 요청 2건에서 변경 분석 차이 확인

### 3.3 Agent 2·Checkpoint 2

**현재 구현**

- CP1 PASS Run의 Agent 1 JSON을 실제 입력으로 사용합니다.
- Pydantic 구조화 출력으로 제품 기능 TC 후보를 생성합니다.
- Requirement·Condition·Expected Result의 ID 추적을 검사합니다.
- 모든 확정 조건 및 MODIFIED·VERIFY Requirement 반영을 검사합니다.
- 상태 정합성 유형은 UI·내부 상태, 알림 조건은 NOTIFICATION 결과를 강제합니다.
- 제품 TC에 Playwright·Python 코드가 섞이면 차단합니다.
- CP2 FAIL 시 이전 전체 TC를 유지하며 최대 1회 재작업합니다.

**검증된 테스트**

- 구조화 Responses API와 API 키 사전 검사
- 확정 조건 누락 FAIL
- UI·내부 상태 이중 검증 누락 FAIL
- STATE_CONSISTENCY 유형의 내부 상태 누락 FAIL
- Playwright 코드 혼입 FAIL
- 전체 유효 설계 PASS

**현재 제한**

- 기존 TC 구조화 목록이 없어 NEW·UPDATED·DEPRECATED와 의미 중복을 판정하지 않습니다.
- CP2는 자연어 의미 및 모드×경계 조합의 충분성을 완전히 판정하지 않습니다.
- Live 결과의 COOL·HEAT 범위 TC는 각 모드의 양 경계를 모두 검증하는지 사람 검토가 필요합니다.

### 3.4 Agent 3·Checkpoint 3

**계획**

- Agent 2가 정한 Step과 Expected Result를 Playwright Python 코드 후보로 구현합니다.
- 실제 로컬 페이지 조사로 Locator 후보를 확인합니다.
- TC 항목과 코드 줄의 Mapping을 저장합니다.
- Python 구문, Fixture, 허용 URL, Assertion과 금지 패턴을 검사합니다.
- 새 브라우저 Context에서 후보를 한 번 시험합니다.
- Locator·Wait·Fixture 기술 오류만 최대 1회 수정합니다.

**최소 테스트**

- 모든 핵심 Expected Result의 Assertion 매핑
- Assertion 누락·약화·assert True 차단
- 무조건 skip·예외 전체 무시 차단
- 외부 URL·Shell·임의 삭제·원본 수정 차단
- UI 실제값과 window.__vccs 내부 실제값 대조
- 시험 exit code·stdout·stderr 저장
- 시험 실패를 제품 결함으로 분류하지 않음

Snapshot·Restore, 3회 반복 안정성, 결함 주입과 Self-Healing은 현재 MVP 완료 조건이 아닙니다.

### 3.5 Agent 4·Checkpoint 4

**계획**

- 현재 Run의 중립 실행 결과만 입력받습니다.
- 제품 기능 TC, 기존 회귀와 Pipeline Fixture를 구분합니다.
- 단일 Run ID, 중복 TC, 결과 합계와 보고 수치를 검사합니다.
- 제품·요구사항·자동화 생성·자동화 실행·환경·근거 부족·미실행을 구분합니다.

**필수 선행 조건**

Project1 conftest의 failure_reason에는 이미 의미 라벨이 들어 있으므로 이 값을 분류 정확도 평가에 사용하지 않습니다. V2에서는 phase, exception_type, raw_message, Assertion 결과처럼 중립적인 신호를 별도 Schema로 저장해야 합니다.

## 4. End-to-End 대표 시나리오

| ID | 시나리오 | 기대 결과 | 상태 |
|---|---|---|---|
| E2E-001 | 명확한 MODIFIED 요청 | A1→CP1→A2→CP2→A3→CP3→시험→보고 | 계획 |
| E2E-002 | SRS에 없는 Requirement | CP1 FAIL, 후속 미실행 | CP1 범위 구현 |
| E2E-003 | 변경 전 값 불일치 | CP1 REVIEW 또는 FAIL | CP1 범위 구현 |
| E2E-004 | 근거 없는 TC 기대값 | CP2 FAIL 또는 REVIEW | 계획 |
| E2E-005 | 코드에서 Assertion 누락 | CP3 FAIL | 계획 |
| E2E-006 | Locator·Fixture 기술 오류 | 제품 판정 보류, 기술 수정 최대 1회 | 계획 |
| E2E-007 | REVIEW Finding | 조건부 사람 검토 후 재개·수정·종료 | 계획 |
| E2E-008 | 정식 등록 반려 | Run 증거 보존, 기존 자산 불변 | 계획 |

End-to-End 완료를 주장하려면 E2E-001이 실제 Run Artifact와 실행 결과로 확인되어야 합니다.

## 5. 추적성 체인

변경 요청 한 건은 다음 연결을 유지합니다.

~~~text
Change Request
  -> Agent 1 Analysis
  -> CP1 Rules
  -> Agent 2 TC Change Set
  -> CP2 Rules
  -> Agent 3 Code Candidate
  -> CP3 Rules + Trial
  -> Execution Result
  -> Agent 4 Finding
  -> Final Report
  -> Asset Registration Decision
~~~

각 산출물은 다음 공통 정보를 가져야 합니다.

- run_id
- artifact_id
- contract_version
- component
- created_at
- input_artifact_ids
- status

다음 단계는 PASS 또는 조건부 검토에서 PROCEED로 결정된 Artifact만 입력으로 사용합니다.

## 6. Run 증거

### 항상 저장

- 원본 변경 요청
- 모델 원문과 정규화 JSON
- 사용 모델·Prompt 버전·토큰 사용량
- Checkpoint Rule별 상태·메시지
- Agent 간 input_artifact_ids
- TC·코드 줄 Mapping
- 시험 exit code·stdout·stderr
- 현재 Run 실행 결과
- 최종 보고 JSON

### 발생한 경우만 저장

- 조건부 사람 검토 결과
- 자동 기술 수정 전후 Diff
- Screenshot·Playwright Trace
- 정식 QA 자산 등록 결정

API 키, 환경변수 원문, 인증 Header와 전체 로컬 절대경로는 Run 산출물에 저장하지 않습니다.

## 7. 단계별 완료 기준

### 구현 완료 단계: Agent 1·CP1 → Agent 2·CP2

- 실제 모델이 구조화 Agent 1·2 JSON을 반환합니다.
- CP1 10개 규칙과 CP2 9개 규칙이 실행됩니다.
- CP1 PASS Agent 1 산출물이 같은 Run의 Agent 2 실제 입력으로 사용됩니다.
- 제품 기능 TC 후보 5건이 생성됐고 구조·추적성 CP2 PASS를 확인했습니다.
- 각 Agent는 Checkpoint FAIL 시 최대 1회 재작업합니다.
- API 키가 코드와 Run 산출물에 포함되지 않습니다.
- 자연어 의미와 조합 충분성은 사람의 마지막 검토 범위로 남깁니다.

### 다음 단계: Agent 3·CP3
### Agent 3·CP3

- 제품 기능 TC 한 건이 코드 후보 한 건으로 이어집니다.
- 핵심 기대 결과가 Assertion에 추적됩니다.
- 후보가 원본과 분리된 위치에서 한 번 실행됩니다.
- 기술 오류와 제품 결과를 구분합니다.

### V2 MVP

- E2E-001 실제 Run이 완료됩니다.
- Project1 회귀 후보와 Pipeline Fixture가 분리 집계됩니다.
- 제품·자동화·환경·근거 부족을 구분합니다.
- 실행 결과와 최종 보고 수치가 일치합니다.
- 정식 등록 결정 전 Project1 원본을 변경하지 않습니다.

## 8. MVP 이후 재평가할 항목

1. 같은 요청 3회 반복 평가
2. 코드 후보 반복 안정성
3. 대표 결함 검출성
4. 관련 Requirement 검색
5. 질문 후 중단 단계 재개
6. ADDED·DELETED 지원
7. 정식 QA 자산 자동 등록·버전 관리
8. Agent Evaluation Framework 연결
