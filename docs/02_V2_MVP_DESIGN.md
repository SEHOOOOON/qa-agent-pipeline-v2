# QA Agent Pipeline V2 MVP 설계

## 1. 목적

프로젝트 1을 다시 만드는 것이 아니라, **변경 요청→실제 모델 산출물→TC→코드 후보→실행 결과**의 인과관계를 최소 범위로 구현합니다.

## 2. 현재 출발점

### 프로젝트 1에서 이미 있는 것

- 16대 가상 중앙제어기
- 사람이 작성한 Playwright 테스트 13건
- 화면·내부 상태 일부 대조
- 규칙 기반 결과 분류·보고 코드
- Agent 1~4 역할과 Checkpoint UI 시연

### 아직 없는 것

- Agent 1·2의 실제 모델 호출
- Agent 1 출력의 Agent 2 자동 전달
- Agent 2 TC 기반 Agent 3 코드 생성
- 생성 코드의 격리 실행
- CP1~3 실행 코드, 조건부 검토와 정식 QA 자산 등록 승인 기록
- V2 Run 단위 최종 보고

## 3. MVP 목표와 비목표

### 목표

1. MODIFIED 요청 한 건을 실제 모델에 전달합니다.
2. Agent 1이 SRS와 요청을 비교한 JSON을 생성합니다.
3. Agent 2가 검증된 Agent 1 JSON으로 TC Change Set을 만듭니다.
4. Agent 3가 TC 한 건의 Playwright Python 코드 후보를 만듭니다.
5. CP1~3이 명백한 계약·근거·금지 패턴 위반을 찾습니다.
6. 후보를 임시 폴더에서 한 번 실행합니다.
7. CP1~3과 격리 시험을 통과한 후보는 중간 사람 승인 없이 현재 Run 검증으로 자동 전달합니다.
8. REVIEW·근거 부족·정책 충돌만 사람에게 조건부 검토를 요청합니다.
9. 기존 검증 가능 회귀 TC와 함께 결과를 보고하고, 마지막에 정식 QA 자산 등록 여부를 한 번 승인합니다.

### 비목표

- 모든 변경 유형과 모든 TC 지원
- 완전 자율 Agent 팀
- 자연어 의미의 완전 자동 판정
- Full Regression 전체 구현
- 정식 QA 자산 자동 등록·버전 갱신
- 반복 안정성·결함 주입·다중 모델 비교
- 운영 장비와 외부 서비스 연결

## 4. 전체 흐름

~~~text
[사람] 변경 요청 입력
  -> [Agent 1 / 모델] 변경 분석 JSON
  -> [CP1 / 코드] ID·before·after·근거 검사
  -> [Agent 2 / 모델] 제품 기능 TC Change Set
  -> [CP2 / 코드] 구조·추적성·제품 기준 검사
  -> [Agent 3 / 모델] 실제 화면 확인 + Playwright Python 코드 후보
  -> [CP3 / 코드] 구문·금지 패턴·TC 매핑 검사
  -> [격리 실행] 임시 폴더에서 후보 1회 시험
  -> [실행기] CP 통과 후보 변경 검증 + 기존 회귀 후보
  -> [Agent 4 / 규칙] 분류·정합성·보고
  -> [사람] 공식 SRS·TC·자동화 저장 승인 1회

공통 분기: CP1~3에서 REVIEW 발생 시에만 사람 검토 후 PROCEED·REVISION_REQUIRED·REJECTED
~~~

Checkpoint는 생성형 Agent가 아니라 결정론 검사기입니다. PASS 후보는 자동으로 다음 단계에 전달하고, 자동 판정이 불충분한 REVIEW만 사람에게 보냅니다. 사람의 필수 승인은 최종 결과를 기존 SRS·TC·자동화의 공식 버전으로 저장할 때 한 번만 수행합니다.

## 5. 지원 입력

| 필드 | 필수 | 설명 |
|---|---|---|
| change_request_id | Y | 변경 요청 ID |
| title | Y | 변경 제목 |
| description | Y | 변경 내용 |
| target_requirement_ids | Y | 기존 SRS ID |
| change_type | Y | MVP는 MODIFIED |
| requested_behavior | Y | 변경 후 기대 동작 |
| acceptance_notes | N | 추가 인수 조건 |
| out_of_scope | N | 제외 범위 |

특정 온도나 기능을 코드에 고정하지 않습니다. SRS에 없는 기능, 변경 전 값 불일치와 정보 부족은 CP1 또는 사람 검토로 보냅니다.

## 6. 단계별 책임

### Agent 1 — 변경 분석

- SRS의 기존 조건과 요청의 변경 후 조건을 분리합니다.
- 직접 영향과 관련 영향 후보를 근거와 함께 냅니다.
- 정책을 새로 만들거나 SRS를 수정하지 않습니다.

### Agent 2 — 제품 기능 TC 설계

- 무엇을 검증할지 정의합니다.
- NEW·UPDATED·REGRESSION 후보를 구분합니다.
- 사전조건, 행동, 기대 결과와 Requirement 근거를 작성합니다.
- 상태 변경은 가능한 경우 UI와 내부 상태를 모두 기대 결과로 둡니다.

### Agent 3 — 자동화 코드 후보 생성

- Agent 2가 확정한 테스트 목적과 기대 결과를 Playwright Python으로 구현합니다.
- 새 테스트 아이디어나 기대값을 추가하지 않습니다.
- 코드 생성 전에 실제 로컬 화면의 접근성 구조, role·name·test id와 상태 변화를 확인합니다.
- 프로젝트 1의 기존 기준 자동화 코드와 실제 화면 확인 자료를 참고합니다.
- 내부 상태는 기존 `window.__vccs` 읽기 인터페이스를 사용합니다.
- Playwright MCP는 실제 화면 조작과 Locator 확인을 돕는 개발 시점 도구입니다. 사용할 수 없으면 Python Playwright 조사 스크립트로 같은 근거를 수집합니다.
- 생성·검증을 마친 코드는 Python Playwright 파일로 저장하며, 이후 회귀 실행에서는 모델이나 MCP를 다시 호출하지 않고 저장된 코드를 재사용합니다.

### Agent 4 — 결과 분석

- 생성형 Agent가 아니라 규칙 기반 Python 분석기입니다.
- V2의 중립 실행 결과를 입력받아 제품·자동화·환경·근거 부족을 구분합니다.
- Project1의 사전 라벨 문자열을 분류 정확도 근거로 사용하지 않습니다.

## 7. 코드 후보 검증

### 실행 가능성

- Python 구문, pytest·Playwright Fixture, 허용 URL을 검사합니다.
- Locator는 실제 로컬 페이지에서 확인합니다.
- Timeout 안에 한 번 종료되는지 확인합니다.

### 의도 충실성

- 모든 핵심 Step과 Expected Result가 코드에 매핑되어야 합니다.
- Assertion 누락·삭제·약화와 기대값 변경을 차단합니다.
- UI 검증만으로 부족한 상태 변경은 `window.__vccs` 대조를 요구합니다.

### 안전성

- 원본 테스트와 제품 파일을 수정하지 않습니다.
- 외부 URL, Shell, 임의 삭제, API Key 하드코딩을 금지합니다.
- 새 브라우저 Context와 명시적 사전조건으로 시험을 시작합니다.
- 일반 Snapshot/Restore API는 현재 없으므로 구현된 것처럼 전제하지 않습니다.

### 자동 수정 범위

문법, Locator, Wait, Fixture 참조만 최대 1회 수정할 수 있습니다. 기대값, 경계값, Requirement, Assertion 의미는 수정할 수 없습니다.

## 8. 조건부 검토와 정식 QA 자산 등록 승인

정상 흐름에서는 TC와 코드 후보를 사람이 매번 승인하지 않습니다. CP1~3과 격리 시험이 PASS이면 현재 Run 검증으로 자동 진행합니다.

다음 경우에만 조건부 검토를 요청합니다.

- 자연어 의미 또는 제품 정책을 코드만으로 확정할 수 없음
- Requirement 근거가 일부 부족하거나 서로 충돌함
- TC 의도와 코드 매핑에 REVIEW Finding이 존재함
- 기술 수정이 기대값·Assertion 의미에 영향을 줄 가능성이 있음

조건부 검토 판정:

- PROCEED: 현재 Run을 중단 지점부터 재개
- REVISION_REQUIRED: 담당 Agent로 최대 1회 반환
- REJECTED: 현재 Run 중단

Agent 4의 최종 보고 뒤에는 사람이 **정식 QA 자산 등록 승인 1회**를 수행합니다. 이는 검증이 끝난 SRS·TC·Playwright 코드를 다음 변경에서도 재사용할 공식 버전으로 저장해도 되는지를 결정하는 단계입니다. 승인 전에는 기존 자산을 덮어쓰지 않으며, 실제 파일 자동 등록과 기존 TC 비활성화는 MVP에서 수행하지 않습니다.

## 9. 실행 세트

1. 환경 사전 점검
2. Checkpoint를 통과한 변경 검증
3. 관련 기능 회귀
4. 기존 검증 가능 제품 기능 TC
5. Agent 4 결과 분석

TC-ENV-000은 현재 일반 테스트이므로 V2 Orchestrator가 결과를 읽어 후속 단계 차단 여부를 결정해야 합니다. 기존 TC-INT-002는 비대상 불변 검증을 보완하기 전까지 제품 회귀 세트에서 제외합니다.

## 10. 실패 분류

| 분류 | 의미 |
|---|---|
| PRODUCT_DEFECT | 환경과 자동화가 유효하고 제품 결과가 기대와 다름 |
| REQUIREMENT_REVIEW | SRS 또는 변경 요청의 기대 근거 부족 |
| AUTOMATION_GENERATION_ERROR | 코드 후보가 TC 의도를 구현하지 못함 |
| AUTOMATION_EXECUTION_ERROR | 구문·Locator·Timeout·Fixture 문제 |
| ENVIRONMENT_ISSUE | 페이지·브라우저·사전 상태 문제 |
| NEEDS_MORE_EVIDENCE | 현재 증거로 판정 불가 |
| NOT_EXECUTED | 선행 조건 또는 Gate 실패로 미실행 |

## 11. Run 산출물

~~~text
runs/RUN-<id>/
  request.json
  agent1_change_analysis.json
  checkpoint1.json
  agent2_tc_change_set.json
  checkpoint2.json
  candidates/test_candidate.py
  candidate_manifest.json
  checkpoint3.json
  trial_result.json
  conditional_review.json       # REVIEW 발생 시에만 생성
  asset_registration_decision.json
  execution_results.json
  final_report.json
~~~

모든 파일은 같은 Run ID와 실제 입력 Artifact ID를 가져야 합니다.

## 12. 구현 순서

1. SRS 초기 기준 확정·변경 요청 Schema
2. Agent 1 모델 Adapter·CP1
3. Agent 2 모델 Adapter·CP2·자동 인계
4. 실제 화면 확인 자료·Agent 3·CP3
5. 임시 폴더 격리 실행
6. 조건부 HUMAN_REVIEW 분기·재개 기록
7. 기존 회귀 후보 실행
8. Agent 4 입력 정합화·최종 보고
9. 정식 QA 자산 등록 승인 기록

## 13. MVP 완료 기준

- 서로 다른 변경 요청 2건이 서로 다른 Agent 1·2 결과를 만듭니다.
- Agent 1 Artifact가 Agent 2 실제 입력으로 기록됩니다.
- Agent 2 TC 한 건이 Agent 3 코드 후보 한 건으로 이어집니다.
- TC의 핵심 기대 결과가 Assertion과 내부 상태 대조에 매핑됩니다.
- 후보는 원본과 분리된 위치에서 실행됩니다.
- 중간 필수 승인 없이 정상 Run이 자동 진행됩니다.
- REVIEW 항목만 조건부 사람 검토로 분기됩니다.
- 정식 QA 자산 등록 승인 전 기존 자산을 변경하지 않습니다.
- 제품·자동화·환경 오류와 근거 부족을 구분합니다.
- 실제 실행 건수와 최종 보고 수치가 일치합니다.

## 14. MVP 이후 후보

- 같은 요청 3회 반복 평가
- 코드 후보 반복 안정성
- 대표 결함 검출성
- ADDED·DELETED 지원
- 질문 후 재개
- 승인 결과의 자동 등록·버전 관리
- Agent 평가 프로젝트 연결
