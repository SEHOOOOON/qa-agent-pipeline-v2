# V2 테스트 및 추적성 계획

## 1. 목적과 현재 상태

이 문서는 QA Agent Pipeline V2의 구현 단계별 검증 방법과 증거 연결 규칙을 정의합니다. Project1의 기존 TC 분류·Coverage·알려진 한계는 [Project1 기준 자산 감사](05_PROJECT1_BASELINE_AUDIT.md)에서 관리합니다.

| 영역 | 현재 상태 | 검증 근거 |
|---|---|---|
| Product SRS 파서 | 구현 | tests/test_pipeline.py |
| Agent 1 OpenAI Adapter | 구현 | tests/test_pipeline.py, 로컬 Live Run |
| Checkpoint 1 | 구현 | tests/test_pipeline.py |
| Agent 2·Checkpoint 2 | 구현 | tests/test_pipeline.py, 같은 Run의 Live 인계 |
| Agent 3·Checkpoint 3 | 구현 | 자동화 가능성 사전 확인·기존 기능 좁은 UI 확인·신규 기능 범용 UI 동적 조사·AI 코드 의도·결정론적 코드 컴파일·CP3·격리 시험 |
| V2 Orchestrator | 구현·Live 확인 | API 미호출 테스트 4건, 실제 세 중단 경로와 CP1→CP2→CP3→Trial PASS 정상 완료, Manifest 해시 확인 |
| 변경 검증·관련 기존 회귀 | 구현·무API 실행 확인 | 현재 후보 재검증/재시험, TC-ENV-000 Gate, Requirement 기반 회귀 선택, 복사 Workspace 실행, Project1 불변 확인 |
| Agent 4 V2 연동 | 설계 | Project1 규칙 엔진은 있으나 V2 중립 계약 미연결 |

현재 자동 테스트는 기존 범위에 특정 제품 기능명을 코드에 고정하지 않은 신규 UI 동적 조사·범용 코드 생성/실행/복원·비 HVAC 상태값·한국어 조사 의미 연결·알림 문장 전체 오사용 차단·지원 범위 확장 필요 분기를 추가한 83건입니다. `agent3-3.7` 범용 선택·적용 실제 API 시험도 PASS했지만 Agent 4와 최종 보고가 없어 전체 End-to-End 완료를 의미하지 않습니다.

## 2. 검증 원칙

- 문서의 계획과 구현 완료 상태를 구분합니다.
- 제품 Requirement, 테스트 하네스, 기존 회귀 코드와 Pipeline Fixture를 별도 자산으로 관리합니다.
- 현재 Agent 1~3은 요청·SRS 스냅샷·구조화 JSON·검증 단계·자동화 가능성 사전 확인·UI 확인 목록·코드·시험 결과를 파일 SHA-256으로 연결합니다.
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
- 자연어 의미 검색은 아직 없지만 Agent 1 시작 시 SRS 스냅샷과 SHA-256 고정은 구현했습니다.
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
- Agent 2 전달용 확정 조건과 MODIFIED·UPDATE_REQUIRED·VERIFY Requirement 연결 검사
- 확정 조건의 변경 요청·SRS 원문 출처 검사
- 변경 요청 acceptance_notes 전체 전달 여부 검사
- 확정 조건과 제외 범위 중복 및 out_of_scope 보존 검사
- 정보 부족·질문·진행 판정 일관성과 불필요한 재확인 탐지

**현재 제한**

- CP1은 영향 Requirement가 존재하는지는 확인하지만 영향 관계의 의미적 타당성을 보장하지 않습니다.
- CP1 규칙 결과와 후속 인계를 분리해 PASS라도 WAITING_FOR_USER·PARTIAL_PROCEED는 PAUSE, BLOCKED 결정은 BLOCKED로 처리합니다.
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

- CP1 `PASS + CONTINUE` Run만 사용하며 원본 변경 요청·고정 SRS·Agent 1 JSON을 Agent 2 실제 입력으로 전달합니다.
- Pydantic 구조화 출력으로 제품 기능 TC 후보를 생성합니다.
- Requirement·Condition·Expected Result의 ID 추적을 검사합니다.
- 모든 확정 조건 및 MODIFIED·UPDATE_REQUIRED·VERIFY Requirement 반영을 검사합니다.
- 상태 정합성 유형은 UI·내부 상태, 알림 조건은 NOTIFICATION 결과를 강제합니다.
- 중앙·로컬 제어 경로, 대상 역할과 구조화 시험 데이터 누락을 검사합니다.
- 비차단 참고는 `coverage_notes`에 기록하고, 기대 결과를 확정할 수 없는 `human_review_notes`만 CP2 REVIEW로 전환합니다.
- 제품 TC에 Playwright·Python 코드가 섞이면 차단합니다.
- CP2 FAIL 시 이전 전체 TC를 유지하며 최대 1회 재작업합니다.

**검증된 테스트**

- 구조화 Responses API와 API 키 사전 검사
- 확정 조건 누락 FAIL
- UI·내부 상태 이중 검증 누락 FAIL
- STATE_CONSISTENCY 유형의 내부 상태 누락 FAIL
- Playwright 코드 혼입 FAIL
- 전체 유효 설계 PASS
- WAITING_FOR_USER·PARTIAL_PROCEED 인계 PAUSE와 BLOCKED 인계 차단
- 중앙 Requirement의 LOCAL 경로 오용 및 활성 CENTRAL·LOCAL 직접 변경 검증 누락 FAIL
- 구조화 시험 데이터 누락 FAIL, 비차단 참고 PASS, 사람 검토 노트 REVIEW
- Agent 1 산출물 해시 변조와 PAUSE Manifest의 Agent 2 인계 차단

**현재 제한**

- 기존 TC 구조화 목록이 없어 NEW·UPDATED·DEPRECATED와 의미 중복을 판정하지 않습니다.
- CP2는 자연어 의미 및 모드×경계 조합의 충분성을 완전히 판정하지 않습니다.
- 현재 Live 결과는 한 변경 요청에 대한 단일 Run이며 다른 변경 유형과 반복 안정성은 아직 검증하지 않았습니다.

### 3.4 Agent 3·Checkpoint 3

**현재 구현**

- CP2 PASS 자동화 후보 TC는 기존 빠른 확인 또는 범용 UI 동적 조사 경로로 나눕니다. 자동화 후보가 아닌 경우만 모델 호출 전에 `NOT_AUTOMATABLE`로 종료합니다.
- 지원 TC에 필요한 실제 Project1 Selector와 `window.__vccs` 키만 확인하고 모델 입력도 같은 범위로 제한합니다.
- 모델은 실제 UI 확인 목록을 근거로 Selector·조작 순서·검증 조건·복원을 담은 실행 가능한 코드 의도를 생성합니다. 자유 형식 Python 대신 이 구조를 사용해 기대값 변경을 차단합니다.
- CP3는 Selector-행동 대응, Expected Result 1:1, 관찰 계층, 값 근거, 단계 순서와 초기값 복원 Action을 검사합니다. 컴파일러는 복원 후 기존 온도뿐 아니라 범용 UI·내부 상태도 초기 관찰값과 비교합니다.
- 허용 목록 컴파일러가 Python Playwright 후보를 결정론적으로 생성합니다.
- Python 구문 트리로 import·Shell·파일 변경·skip·`assert True`와 검증 조건 표식을 검사합니다.
- 허용된 시스템 변수와 QA 대상·증거 경로만 전달한 임시 폴더에서 후보를 한 번 시험합니다.
- 시험 로그의 로컬 절대경로를 마스킹하고 실제 생성된 Screenshot·Trace만 기록합니다.

**검증된 테스트**

- 모든 핵심 Expected Result의 Assertion 매핑
- 무관한 Selector 누락은 허용하고 선택 TC 필수 Selector 누락은 차단
- 신규 기능의 범용 UI·내부 상태 동적 발견과 `DISCOVERY_REQUIRED` 분기
- 드래그 등 새로운 기술이 필요한 계획의 `AUTOMATION_SUPPORT_EXTENSION_REQUIRED` REVIEW와 코드 미생성
- 미관찰 Selector와 관찰됐지만 행동에 맞지 않는 Selector 차단
- TC에 없는 수치 기대값과 Expected Result 누락 차단
- 컴파일러가 지원하지 않는 `expected_text` 차단
- 관찰됐더라도 Assertion 전략과 다른 Selector 차단
- `target_device_id`와 `SELECT_DEVICE` Action 값 불일치·누락 차단
- 차단 안내 기대 결과에 일반 표시 전략 사용 차단, 성공 Toast의 거짓 PASS 검출
- Assertion 누락·assert True·금지 import·Shell·파일 변경 차단
- UI 실제값과 `window.__vccs` 내부 실제값 대조
- 시험 exit code·stdout·stderr 저장
- 제품 불일치와 자동화·환경·Timeout 오류 분리
- 시험 프로세스 환경변수 allowlist와 임의 토큰 차단
- Trial UTF-8 stdout·stderr와 실패 Run 재사용 차단
- 계획 재작업을 포함한 누적 토큰 사용량 계산
- Trace ZIP의 경로·URI·JSON escape 치환과 비경로 증거 보존
- Agent 2 산출물 해시 변조 시 Agent 3 시작 전 차단

**현재 제한**

- Agent 3 진단 Live Run 3건은 수행했지만 실행에서 찾은 계약·Trace 경로·선택 장비 값·Toast 의미 문제의 보완 전 산출물이므로 공개하지 않았습니다.
- `TC-CAND-003` 로컬 Preview에서 Eligibility `ELIGIBLE`, 관련 Selector 7개·하네스 키 2개, 대상 SHA-256 일치와 API 미호출·로컬 경로·HTML 원문·비밀 토큰 제외를 확인했습니다.
- 진단 Live Run은 첫 계획 CP3 FAIL, 1회 재작업 후 CP3 PASS, Trial `PRODUCT_MISMATCH_CANDIDATE`였습니다. Project1 원본은 변경되지 않았고 두 호출 누적 사용량은 input 5,494·output 2,162·total 7,656 tokens입니다.
- 첫 보완 뒤 두 번째 Run은 Action Selector와 `expected_text`를 준수했지만 내부 상태 Selector를 속성 경로로 확장해 1차 CP3 FAIL, 재작업 후 PASS였습니다. 누적 사용량은 input 5,648·output 1,580·total 7,228 tokens이며 최종 Trial 관찰은 동일했습니다.
- `agent3-3.2` 세 번째 Run은 첫 계획 CP3 PASS, input 2,493·output 615·total 3,108 tokens, Trace 경로 0건이었습니다. 후속 감사에서 `SELECT_DEVICE value=null`을 발견해 현재 CP3는 대상 장비 값까지 검사합니다.
- 세 번째 Screenshot의 성공 적용 Toast가 ER-007 차단 안내를 거짓 통과한 것을 발견했습니다. `agent3-3.4` 로컬 재시험은 ER-005·006과 함께 ER-007 Toast 의미 불일치도 기록했고 Trace 로컬 경로는 0건이었습니다.
- 현재 `agent3-3.4` 공개 Live Run은 첫 계획 CP3 PASS, input 2,533·output 594·total 3,127 tokens를 기록했습니다. `SELECT_DEVICE value=1`과 `TOAST_BLOCKING` 계약을 준수했고 Trial은 ER-005·006·007을 `PRODUCT_MISMATCH_CANDIDATE`로 분류했습니다. 모든 인계 SHA-256과 Project1 대상 해시가 일치했으며 공개 텍스트와 Trace에서 비밀정보·로컬 경로 패턴은 탐지되지 않았습니다.
- 기존 CENTRAL 온도 경로는 검증된 전용 조작을 유지하고, 신규 기능은 범용 UI 조작과 발견된 읽기 전용 내부 상태를 사용합니다. 범용 조작으로 부족한 경우는 지원 범위 확장 필요로 기록합니다.
- 2026-08-17 로컬 범용 선택·적용 Live는 Agent 1 첫 시도 PASS, Agent 2 1회 재작업 후 PASS, 최종 `agent3-3.7` 첫 계획 CP3·Python·Trial·복원 PASS를 기록했습니다. 최종 Agent 3는 4,391 tokens, 연결 오류와 진단 재시도를 포함한 전체 실제 모델 호출은 44,334 tokens를 사용했습니다. 실패 Run은 원인 증거로 보존하고 최종 산출물은 아직 공개 폴더로 복사하지 않았습니다.
- CP3 계획 실패는 최대 1회 재작성하지만, 시험 실행의 기술 오류 자동 수정은 구현하지 않았습니다.
- 일반 Snapshot·Restore, 3회 반복 안정성, 결함 주입과 Self-Healing은 현재 MVP 완료 조건이 아닙니다.

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
| E2E-001 | 명확한 MODIFIED 요청 | A1→CP1→A2→CP2→A3→CP3→시험→보고 | 부분 구현: A1→A3·신규 후보·환경 사전 점검·관련 기존 회귀 실행 확인, Agent 4·최종 보고 미완료 |
| E2E-002 | SRS에 없는 Requirement | CP1 FAIL, 후속 미실행 | CP1 범위 구현 |
| E2E-003 | 변경 전 값 불일치 | CP1 REVIEW 또는 FAIL | CP1 범위 구현 |
| E2E-004 | 근거 없는 TC 기대값 | CP2 FAIL 또는 REVIEW | 계획 |
| E2E-005 | 코드에서 Assertion 누락 | CP3 FAIL | 구현 |
| E2E-006 | Locator·Fixture 기술 오류 | 제품 판정 보류 | 오류 분류 구현, 자동 수정 미구현 |
| E2E-007 | REVIEW Finding | 조건부 사람 검토 후 재개·수정·종료 | 계획 |
| E2E-008 | 정식 등록 반려 | Run 증거 보존, 기존 자산 불변 | 계획 |

End-to-End 완료를 주장하려면 E2E-001이 현재 계약의 실제 Run 파일과 실행 결과로 확인되어야 합니다.

## 5. 추적성 체인

변경 요청 한 건은 다음 연결을 유지합니다.

~~~text
Change Request
  -> Agent 1 Analysis
  -> CP1 Rules
  -> Agent 2 TC Change Set
  -> CP2 Rules
  -> Agent 3 Structured Automation Plan
  -> Deterministic Code Candidate
  -> CP3 Rules + Isolated Trial
  -> Neutral Candidate + Environment Precheck + Related Regression Results
  -> Agent 4 Finding
  -> Final Report
  -> Asset Registration Decision
~~~

각 산출물은 현재 단계에서 다음 공통 정보를 가집니다.

- run_id
- contract_version·prompt_version
- stage·status·handoff_status
- created_at
- 입력·출력 파일 SHA-256

Agent 1~3 Manifest는 재작업을 포함한 누적 토큰과 마지막 시도 토큰을 분리합니다. Agent 3는 자동화 가능성 사전 확인·UI 확인 목록·코드 의도·코드·Checkpoint·시험 파일을 `agent3_manifest.json`의 SHA-256으로 연결합니다. 내부 파일·필드의 기존 영문명은 산출물 호환을 위해 유지합니다.

현재 Agent 3는 Agent 2가 `PASS`이고 Agent 1·2 Manifest SHA-256 및 CP1·CP2 재계산 결과가 일치하는 Run만 입력으로 사용합니다.

## 6. Run 증거

### 항상 저장

- 원본 변경 요청
- 구조화 모델 출력 JSON
- 사용 모델·Prompt 버전·토큰 사용량
- Checkpoint Rule별 상태·메시지
- Agent 1~3 입력·출력 SHA-256 체인
- Agent 3 자동화 가능성 사전 확인·UI 확인 목록·구조화 코드 의도·코드 후보
- TC Expected Result·검증 조건 연결
- 시험 exit code·stdout·stderr
- Agent 3 시험 결과와 증거 완전성
- 현재 후보 재사용/재시험 여부와 후보 SHA-256
- 환경 사전 점검·선택된 기존 회귀와 중립 실행 결과
- Project1 대상·기존 테스트의 실행 전 SHA-256과 실행 후 불변 확인

### 발생한 경우만 저장

- 조건부 사람 검토 결과
- 자동 기술 수정 전후 Diff
- 실제 생성된 Screenshot·Trace
- 최종 보고 JSON
- 정식 QA 자산 등록 결정

API 키, 환경변수 원문, 인증 Header와 전체 로컬 절대경로는 Run 산출물에 저장하지 않습니다.

## 7. 단계별 완료 기준

### 구현 완료 단계: Agent 1·CP1 → Agent 2·CP2 → Agent 3·CP3·격리 시험

- 실제 모델이 구조화 Agent 1·2 JSON을 반환합니다.
- CP1 10개 규칙과 CP2 11개 규칙이 실행됩니다.
- CP1 `PASS + CONTINUE`이며 요청·SRS·분석·CP1 SHA-256과 CP1 재계산 결과가 일치할 때만 Agent 2가 실행됩니다.
- v2.2 Live Run에서 Agent 1 `PASS + CONTINUE`, Agent 2 1차 FAIL→1회 재작업→CP2 PASS, TC 후보 12건을 확인했습니다.
- Agent 1~3의 구조화 결과는 Checkpoint FAIL 시 최대 1회 재작업합니다.
- API 키가 코드와 Run 산출물에 포함되지 않습니다.
- 자연어 의미와 조합 충분성은 사람의 마지막 검토 범위로 남깁니다.

### Agent 3 공개 Live Run 확인 결과

- `agent3_eligibility.json`에서 `ELIGIBLE`, 관련 Selector 7개·하네스 키 2개와 모델 호출 허용을 확인했습니다.
- API 키와 모델 Client를 생성하지 않는 `--preview-only`로 시스템 지침, 선택 TC, 관련 SRS와 선택 TC 범위 UI 조사 JSON의 실제 전송 예정 값을 확인했습니다.
- API 키·로컬 절대경로·HTML 원문·Screenshot·Trace가 미리보기에 없음을 확인했습니다.
- CP3 Rule·코드 후보·격리 시험·Screenshot·Trace를 `examples/results/agent1-agent2-agent3-auto-temperature/`에 함께 보존했습니다.

### 구현 완료 단계: 변경·기존 회귀 연결

- Agent 3 성공 Run의 인계·해시·시험 증거를 다시 검증합니다.
- 현재 컴파일러 출력이 저장 후보와 다르면 모델 없이 현재 후보를 다시 시험합니다.
- TC-ENV-000 미통과 시 기존 회귀를 실행하지 않습니다.
- 기존 13건 중 환경 사례·분류 Fixture·근거 부족 TC를 제외한 6건만 재사용 목록으로 고정하고 Requirement ID가 연결된 TC만 실행합니다.
- Project1 `conftest.py`의 의미 라벨을 가져오지 않는 복사 Workspace에서 실행합니다.

### 다음 단계: Agent 4

### V2 MVP

- 완료된 검증 실행의 중립 결과를 Agent 4와 최종 보고에 연결합니다.
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
