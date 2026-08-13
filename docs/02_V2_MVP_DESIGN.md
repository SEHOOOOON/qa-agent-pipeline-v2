# QA Agent Pipeline V2 MVP 설계

## 1. 목적

프로젝트 1을 다시 만드는 것이 아니라, **변경 요청→실제 모델 산출물→TC→코드 후보→실행 결과**의 인과관계를 최소 범위로 구현합니다.

## 2. 현재 출발점

### 프로젝트 1에서 이미 있는 것

- 16대 가상 중앙제어기와 QA 전용 상태 관찰 인터페이스
- 사람이 작성한 Playwright 테스트 13건
- 화면·내부 상태 일부 대조
- 규칙 기반 결과 분류·보고 코드
- Agent 1~4 역할과 Checkpoint의 Fixture 기반 UI 시연

### 아직 없는 것

- 구조화된 기존 TC 목록과 Agent 2의 NEW·UPDATED·REGRESSION 비교
- 조건부 검토 UI와 정식 QA 자산 등록 승인 기록
- V2 Run 단위 최종 보고

## 현재 구현 경계

- 구현 완료: Product SRS·연관 요구사항 파서, Agent 1·2 OpenAI Adapter, Agent 3 구조화 계획 Adapter·결정론적 코드 컴파일러, CP1 10개·CP2 11개·CP3 계획/코드 규칙, 격리 시험, 요청·SRS·단계 산출물 SHA-256 고정
- 실행 확인: v2.2 Live Run `RUN-20260813-125229-31EB5F`에서 Agent 1 `PASS + CONTINUE`, Agent 2·CP2 `PASS`, TC 후보 12건을 확인했습니다. 실제 Project1 화면을 읽기 전용으로 조사한 로컬 검증에서 CP3와 격리 시험까지 확인했고 자동 테스트 46건을 통과했습니다.
- 미구현: 기존 TC 비교, Agent 3 실제 모델 공개 Run, 전체 Orchestrator, 조건부 검토 재개 UI, V2 Agent 4 입력 계약과 End-to-End 실행
- Project1 기존 구현 상태와 한계는 [Project1 기준 자산 감사](05_PROJECT1_BASELINE_AUDIT.md), 테스트 지원 인터페이스는 [QA 하네스 가이드](06_TEST_HARNESS_GUIDE.md)를 기준으로 합니다.

## 3. MVP 목표와 비목표

### 목표

1. MODIFIED 요청 한 건을 실제 모델에 전달합니다.
2. Agent 1이 SRS와 요청을 비교한 JSON을 생성합니다.
3. Agent 2가 검증된 변경 요청·고정 SRS·Agent 1 JSON으로 제품 기능 TC 후보를 만듭니다.
4. Agent 3가 TC 한 건의 구조화 실행 계획을 만들고, 컴파일러가 Playwright Python 후보로 변환합니다.
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
  -> [CP1 / 코드] ID·before·after·근거 검사 + 후속 인계 상태
  -> [Agent 2 / 모델] 제품 기능 TC 후보
  -> [CP2 / 코드] 구조·추적성·제어 경로·시험 데이터 검사
  -> [UI 조사기 / 코드] Project1 실제 Selector·window.__vccs 목록 확인
  -> [Agent 3 / 모델] 승인 TC를 제한된 행동·Assertion 계획으로 변환
  -> [컴파일러·CP3 / 코드] Playwright Python 후보 생성 + 추적성·금지 패턴 검사
  -> [격리 실행] 비밀 환경변수를 제거한 임시 폴더에서 후보 1회 시험
  -> [실행기] CP 통과 후보 변경 검증 + 기존 회귀 후보
  -> [Agent 4 / 규칙] 분류·정합성·보고
  -> [사람] 공식 SRS·TC·자동화 저장 승인 1회

공통 분기: CP1~3에서 REVIEW 발생 시에만 사람 검토 후 PROCEED·REVISION_REQUIRED·REJECTED
~~~

Checkpoint는 생성형 Agent가 아니라 결정론 검사기입니다. PASS 후보는 자동으로 다음 단계에 전달하고, 자동 판정이 불충분한 REVIEW만 사람에게 보냅니다. 사람의 필수 승인은 최종 결과를 기존 SRS·TC·자동화의 공식 버전으로 저장할 때 한 번만 수행합니다.

## 5. 지원 입력

| 필드 | 필수 | 설명 |
|---|---|---|
| request_id | Y | 변경 요청 ID |
| change_type | Y | MVP는 MODIFIED |
| target_requirement_id | Y | 변경 대상 기존 SRS ID |
| before_value | Y | 변경 전 값·조건 |
| after_value | Y | 변경 후 값·조건 |
| description | Y | 변경 내용을 설명한 원문 |
| reason | N | 변경 이유 |
| acceptance_notes | N | 추가 인수 조건 |
| out_of_scope | N | 제외 범위 |

특정 온도나 기능을 코드에 고정하지 않습니다. 변경 요청에 명시된 신규 정책은 변경 후 기준으로 인정하며, 현재 SRS와 변경 요청 모두에 없는 기능, 변경 전 값 불일치와 실제 정보 부족만 CP1 또는 사람 검토로 보냅니다.

## 6. 단계별 책임

### Agent 1 — 변경 분석

- SRS의 기존 조건과 요청의 변경 후 조건을 분리합니다.
- 변경 요청의 after 값·동작·인수 조건을 변경 후 정책의 권한 있는 입력으로 사용합니다.
- 대상은 MODIFIED, 기존 문구 수정이 필요한 연관 기준은 UPDATE_REQUIRED, 회귀 확인만 필요한 기준은 VERIFY로 구분합니다.
- 두 입력 어디에도 없는 정책을 새로 만들거나 SRS를 직접 수정하지 않습니다.

### Agent 2 — 제품 기능 TC 설계

- 무엇을 검증할지 정의합니다.
- 현재는 기존 TC 구조화 목록이 없으므로 CHANGE_VALIDATION·RELATED_REGRESSION 목적만 구분합니다.
- 사전조건, 행동, 기대 결과와 Requirement·Condition 근거를 작성합니다.
- 중앙·로컬 제어 경로, 대상 역할, 모드·온도 시험 데이터, 복원 필요 여부를 구조화합니다.
- 상태 변경은 가능한 경우 UI와 내부 상태를 모두 기대 결과로 둡니다.

### Agent 3 — 자동화 코드 후보 생성

- UI 조사기가 실제 Project1 페이지에서 허용 Selector와 `window.__vccs` 키를 먼저 수집합니다.
- Agent 3 모델은 Agent 2가 확정한 TC를 행동·Assertion의 구조화 계획으로만 변환합니다.
- 모델은 Python 코드를 직접 작성하지 않으며 새 테스트 목적, 기대값, Selector와 Requirement를 추가할 수 없습니다.
- CP3는 행동 유형과 Selector의 대응, 모든 Expected Result의 1:1 Assertion, 관찰 계층, 모드·온도 값, 단계 순서와 복원 계약을 검사합니다.
- 허용 목록 컴파일러가 CP3 PASS 계획을 Python Playwright 후보로 결정론적으로 만듭니다.
- 내부 상태는 기존 `window.__vccs.devices` 읽기 인터페이스를 사용합니다.
- 현재 MVP는 조사된 CENTRAL 제어 패널 TC 한 건만 지원하며 LOCAL 경로는 별도 실제 화면을 조사할 때까지 차단합니다.
- 생성·검증을 마친 코드는 Run 폴더에 저장하며 이후 재실행에서는 모델을 다시 호출하지 않습니다.
- Playwright MCP는 향후 조사 보조 도구일 뿐, 현재 구현의 실행 조건이나 품질 보장 근거가 아닙니다.

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

CP3가 구조화 계획을 반려하면 같은 TC와 실패 Rule만 전달해 계획을 최대 1회 재작성합니다. 컴파일된 후보의 시험 실행에서 발생한 Locator·Wait·Fixture 오류는 현재 자동 수정하지 않고 `TRIAL_FAILED`로 보존합니다. 기대값, 경계값, Requirement와 Assertion 의미는 어떤 경우에도 수정하지 않습니다.

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
  request.json                   # 현재 구현
  srs_snapshot.md                # 현재 구현
  agent1_change_analysis.json    # 현재 구현
  checkpoint1.json               # 현재 구현
  run_manifest.json              # 현재 구현: 입력·출력 SHA-256
  agent2_test_design.json        # 현재 구현
  checkpoint2.json               # 현재 구현
  agent2_manifest.json           # 현재 구현: 단계 간 SHA-256 체인
  agent3_ui_observation.json      # 구현: 파일명·해시·Selector·하네스 목록
  agent3_model_input_preview.json # 구현: API 전송 예정 데이터
  agent3_automation_plan.json     # 구현: 모델의 제한된 행동·Assertion 계획
  candidates/test_<tc-id>.py     # 구현: 결정론적 Playwright 후보
  checkpoint3.json               # 구현: 계획·코드 규칙 판정
  agent3_trial.json               # 구현: 격리 시험 결과
  agent3_manifest.json            # 구현: 단계 입력·출력 SHA-256
  evidence/<tc-id>/               # 구현: stdout·stderr·Screenshot·Trace
  conditional_review.json        # REVIEW 재개 기능 계획
  asset_registration_decision.json
  execution_results.json
  final_report.json
~~~

현재 Agent 1~3 파일은 같은 Run ID를 사용합니다. Agent 3 시작 전 Agent 1·2 Manifest와 산출물 SHA-256 및 CP1·CP2 재계산 결과를 다시 확인하며, `agent3_manifest.json`에 UI·계획·코드·시험 SHA-256을 기록합니다. Artifact ID는 다수 후보를 동시에 처리할 때 검토합니다.

## 12. 구현 순서

1. SRS 초기 기준 확정·변경 요청 Schema
2. Agent 1 모델 Adapter·CP1
3. Agent 2 모델 Adapter·CP2·자동 인계
4. 실제 화면 확인 자료·Agent 3·CP3 — 구현
5. 임시 폴더 격리 실행 — 구현
6. 조건부 HUMAN_REVIEW 분기·재개 기록
7. 기존 회귀 후보 실행
8. Agent 4 입력 정합화·최종 보고
9. 정식 QA 자산 등록 승인 기록

## 13. MVP 완료 기준

- 서로 다른 변경 요청 2건이 서로 다른 Agent 1·2 결과를 만듭니다.
- Agent 1의 요청·SRS 스냅샷·분석·CP1 SHA-256이 Agent 2 실행 전에 다시 검증됩니다.
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
