# Agent·Checkpoint 입출력 명세

## 1. 목적과 상태

V2 Agent 1~3, 기존 규칙 기반 Agent 4와 Checkpoint의 최소 계약을 정의합니다. **Agent 1·CP1과 Agent 2·CP2는 v2.2 Live Run에서 최종 PASS와 TC 후보 12건을 확인했습니다. Agent 3·CP3·격리 시험은 구현했고 자동 테스트 46건을 통과했으나 Agent 3 실제 모델 공개 Run은 아직 확정하지 않았습니다.**

다음 단계에는 화면 문구나 자유 형식 Markdown이 아니라 Schema 검증을 통과한 JSON만 전달합니다.

제품 요구사항은 Product SRS, 기존 구현 상태는 Project1 기준 자산 감사, QA Drawer·Register·window.__vccs 사용법은 QA 하네스 가이드를 각각 기준으로 합니다. Agent는 QA 하네스 기능을 제품 기능으로 추가할 수 없습니다.

## 2. 현재 Run Manifest와 확장 계약

Agent 1~3 현재 구현은 별도 Artifact ID 대신 파일 이름과 SHA-256으로 동일 Run의 입력·출력을 고정합니다.

~~~json
{
  "contract_version": "2.2",
  "prompt_version": "agent1-2.2",
  "run_id": "RUN-...",
  "stage": "AGENT_1_CP1",
  "status": "PASS",
  "handoff_status": "CONTINUE",
  "request_sha256": "64자리 SHA-256",
  "srs_sha256": "64자리 SHA-256",
  "agent1_analysis_sha256": "64자리 SHA-256",
  "checkpoint1_sha256": "64자리 SHA-256"
}
~~~

### 현재 규칙

- 한 실행은 같은 `run_id`를 사용합니다.
- Agent 1 시작 시 `request.json`과 `srs_snapshot.md`를 저장합니다.
- Agent 2는 요청·SRS·Agent 1 분석·CP1의 SHA-256을 확인하고 CP1을 현재 규칙으로 재계산합니다.
- 저장된 CP1과 재계산 결과가 다르거나 `PASS + CONTINUE`가 아니면 Agent 2를 실행하지 않습니다.
- 모델명·Prompt 버전·토큰 사용량은 Manifest에 기록하되 API 키와 인증 값은 저장하지 않습니다.
- Agent 3는 UI·계획·코드·Checkpoint·시험 파일의 SHA-256을 Manifest에 연결합니다. 다수 후보를 동시에 처리할 때 `artifact_id`와 `input_artifact_ids` 도입을 검토합니다.

## 3. 상태와 판정

| 상태 | 의미 |
|---|---|
| PASS | 자동 규칙 충족 |
| FAIL | 명백한 계약·정책 위반 |
| REVIEW | 사람의 의미 판단 필요 |
| ERROR | 모델·파서·실행 오류 |
| BLOCKED | 선행 실패로 미실행 |
| NOT_APPLICABLE | 적용 대상 아님 |

Checkpoint의 `status`는 규칙 검사 결과이고, `handoff_status`는 다음 단계 실행 가능 여부입니다. `CONTINUE`만 자동 진행하고, `PAUSE`는 REVIEW·PARTIAL_PROCEED·WAITING_FOR_USER처럼 현재 MVP가 자동 재개할 수 없는 상태, `BLOCKED`는 FAIL·ERROR·BLOCKED 결정 상태입니다.

Checkpoint는 구조와 명백한 근거 위반을 검사합니다. 간접 영향의 완전성, 자연어 의미와 제품 정책의 타당성을 완전 자동 판정한다고 주장하지 않습니다.

## 4. Agent 1 — Change Analyst

### 입력

- 변경 요청 JSON
- 초기 제품 기준 문서에서 파싱한 Requirement 행
- 지원 유형 MODIFIED

현재 SRS는 변경 전 제품 상태의 기준이고, 변경 요청의 `after_value`·`description`·`acceptance_notes`는 변경 후 정책의 권한 있는 입력입니다. 변경 요청의 신규 값이나 UI 동작이 현재 SRS에 없다는 이유만으로 정보 부족으로 판정하지 않습니다.

### 출력 최소형

~~~json
{
  "request_id": "CR-...",
  "change_type": "MODIFIED",
  "target_requirement_id": "REQ-...",
  "change_summary": "Agent 2가 바로 이해할 수 있는 변경 요약",
  "before_condition": "SRS의 기존 조건",
  "after_condition": "요청의 변경 후 조건",
  "confirmed_conditions": [
    {
      "condition_id": "COND-001",
      "statement": "TC 판정 기준으로 사용할 확정 조건",
      "source_type": "CHANGE_REQUEST",
      "source_text": "변경 요청의 원문 전체",
      "requirement_ids": ["REQ-..."]
    }
  ],
  "requirement_effects": [
    {"requirement_id": "REQ-...", "relation": "MODIFIED", "reason": "..."},
    {"requirement_id": "REQ-...", "relation": "UPDATE_REQUIRED", "reason": "기존 SRS 문구 수정 필요"},
    {"requirement_id": "REQ-...", "relation": "VERIFY", "reason": "기존 동작 회귀 확인"}
  ],
  "excluded_scope": ["..."],
  "information_gaps": [],
  "user_questions": [],
  "decision": "PROCEED"
}
~~~

### 권한과 금지

- 변경 요약과 확정 조건을 Agent 2가 제품 기능 TC의 입력으로 사용할 수 있게 정리합니다.
- 변경 요청의 모든 인수 조건을 각각 하나의 확정 조건으로 전달합니다.
- 확정 조건에는 변경 요청 또는 SRS의 실제 원문 출처를 붙입니다.
- 대상 Requirement는 MODIFIED, 변경으로 기존 SRS 문구 수정이 필요한 연관 기준은 UPDATE_REQUIRED, 문서는 유지하며 회귀 확인만 필요한 기준은 VERIFY로 구분합니다.
- 영향 후보는 제안할 수 있지만 SRS를 직접 수정하지 않습니다.
- 현재 SRS와 변경 요청 모두에 없는 Requirement ID, 값과 기능을 만들 수 없습니다.
- 변경 요청에 이미 명시된 정책을 SRS에 없다는 이유만으로 다시 확인하지 않습니다.
- 테스트케이스·테스트 절차·Playwright 코드를 작성하지 않습니다.

## 5. Checkpoint 1

| Rule ID | 검사 | 결과 |
|---|---|---|
| CP1-001 | 분석 결과의 요청 ID가 입력과 일치 | FAIL |
| CP1-002 | 대상 Requirement ID가 SRS에 존재하고 입력과 일치 | FAIL |
| CP1-003 | change_type이 MODIFIED로 유지 | FAIL |
| CP1-004 | before가 입력·대상 SRS 근거와 연결 | REVIEW 또는 FAIL |
| CP1-005 | after가 변경 요청과 일치 | FAIL |
| CP1-006 | MODIFIED·UPDATE_REQUIRED·VERIFY Requirement가 SRS에 존재하고 확정 조건과 연결 | FAIL |
| CP1-007 | 확정 조건의 출처 원문이 변경 요청 또는 SRS에 존재 | FAIL |
| CP1-008 | 모든 acceptance_notes 원문과 after_value·description의 변경 후 온도 범위가 확정 조건에 포함 | FAIL |
| CP1-009 | 확정 조건·제외 범위 분리 및 요청의 out_of_scope 보존 | FAIL |
| CP1-010 | 정보 부족·사용자 질문·진행 판정 일관성 및 불필요한 재확인 방지 | REVIEW |

CP1은 확정 조건의 출처와 누락을 검사하지만 자연어 의미의 완전한 타당성까지 보장하지 않습니다.

## 6. Agent 2 — Product Test Designer

### 현재 상태

- OpenAI Responses API 구조화 출력 구현
- CP1 `PASS + CONTINUE` Run만 입력 가능
- 같은 Run 폴더에 TC 후보·CP2·manifest 저장
- CP2 FAIL 시 전체 TC 세트를 유지하며 최대 1회 재작업
- 기존 TC 구조화 목록이 없으므로 NEW·UPDATED·DEPRECATED 판정은 아직 하지 않음

### 입력

- SHA-256 검증을 통과한 원본 변경 요청 `request.json`
- Agent 1 시작 시 고정한 `srs_snapshot.md`의 Requirement·Acceptance Criteria
- CP1을 통과한 `agent1_change_analysis.json`
- Agent 1의 MODIFIED·UPDATE_REQUIRED·VERIFY·NO_IMPACT와 확정 조건

### 출력 최소형

~~~json
{
  "request_id": "CR-...",
  "test_cases": [
    {
      "tc_id": "TC-CAND-001",
      "title": "...",
      "purpose": "CHANGE_VALIDATION",
      "test_type": "BOUNDARY",
      "requirement_ids": ["REQ-..."],
      "source_condition_ids": ["COND-..."],
      "control_path": "LOCAL",
      "target_role": "PRIMARY_TEST_DEVICE",
      "test_data": {
        "initial_mode": "AUTO",
        "requested_mode": "AUTO",
        "initial_temperature_c": 18,
        "requested_temperature_c": 17
      },
      "preconditions": ["..."],
      "steps": ["..."],
      "expected_results": [
        {
          "result_id": "ER-001",
          "statement": "...",
          "observation_layer": "UI",
          "source_condition_ids": ["COND-..."]
        }
      ],
      "restore_required": false,
      "restore_steps": [],
      "automation_candidate": true,
      "automation_reason": "..."
    }
  ],
  "coverage_summary": "...",
  "coverage_notes": [],
  "human_review_notes": []
}
~~~

### 권한과 금지

- 제품 기능 TC의 목적과 기대 결과를 설계합니다.
- 모든 Agent 1 확정 조건을 최소 한 개 TC와 기대 결과에 연결합니다.
- 상태 정합성 TC는 UI·내부 상태를 함께 정의하고 알림 조건은 NOTIFICATION으로 구분합니다.
- 제어 경로(CENTRAL·LOCAL), 대상 역할, 요청 모드·온도와 복원 필요 여부를 구조화합니다.
- 현재 TC를 설계할 수 있는 문서 개정·표현 참고는 `coverage_notes`, 기대 결과를 확정할 수 없는 차단 사유만 `human_review_notes`에 남깁니다.
- CP1 범위 밖 ID, 근거 없는 수치·문구, Playwright·Python 코드를 생성할 수 없습니다.
- 기존 TC 비교 자산이 생기기 전에는 NEW·UPDATED·DEPRECATED를 주장하지 않습니다.

## 7. Checkpoint 2

| Rule ID | 현재 검사 | 결과 |
|---|---|---|
| CP2-001 | 변경 요청·Agent 1·Agent 2 요청 ID 일치 | FAIL |
| CP2-002 | TC·Expected Result ID와 제목 고유성 | FAIL |
| CP2-003 | Requirement·Condition이 CP1 활성 범위에 존재 | FAIL |
| CP2-004 | 모든 Agent 1 확정 조건의 TC 반영 | FAIL |
| CP2-005 | TC→Requirement·Condition→Expected Result 추적 연결 | FAIL |
| CP2-006 | REQ-STATE-001 또는 STATE_CONSISTENCY 유형의 UI·내부 상태 이중 검증 | FAIL |
| CP2-007 | REQ-NOTIFY-001 조건의 NOTIFICATION 기대 결과 | FAIL |
| CP2-008 | 활성 Requirement 범위, 대상 변경 검증, CENTRAL·LOCAL 각각의 직접 변경 검증 TC | FAIL |
| CP2-009 | 제품 TC에 Playwright·Python·무효 Assertion 혼입 금지 | FAIL |
| CP2-010 | 경계·예외·상태 TC의 구조화 요청 시험 데이터 존재 | FAIL |
| CP2-011 | `coverage_notes`는 PASS 기록, `human_review_notes`만 REVIEW | PASS/REVIEW |

기준 미달 시 Rule ID와 실패 메시지만 제시해 최대 1회 재작업합니다. 재작업은 이전 전체 TC 세트를 반환해야 하며, Checkpoint가 삭제를 요구하지 않은 TC를 제거할 수 없습니다.

CP2 PASS는 구조·ID·명시적 추적 규칙 통과를 뜻합니다. 자연어 의미, 모드·경계 조합의 충분성, 간접 영향의 최종 타당성은 사람의 마지막 검토 범위입니다.

## 8. Agent 3 — Automation Engineer

### 입력

- CP2 `PASS`인 CENTRAL 제어 TC 한 건
- 해당 TC의 Requirement ID와 연결된 Product SRS 행
- 실제 Project1 페이지에서 읽은 Selector·`window.__vccs` 목록
- 허용 행동·Assertion·컴파일·격리 정책

### 출력 최소형

~~~json
{
  "tc_id": "TC-CAND-...",
  "target_device_id": 1,
  "summary": "승인 TC 구현 계획",
  "actions": [
    {
      "action_id": "ACT-001",
      "phase": "PRECONDITION",
      "action_type": "SELECT_DEVICE",
      "selector": "#device-card-1 .card-body-split",
      "value": 1,
      "source_text": "승인 TC 사전조건"
    }
  ],
  "assertions": [
    {
      "result_id": "ER-001",
      "observation_layer": "UI",
      "strategy": "UI_TEMPERATURE",
      "selector": "#det-temp-display",
      "expected_number": 18
    }
  ]
}
~~~

이 JSON은 Python 코드가 아니라 자동화 **계획**입니다. 허용 목록 컴파일러가 CP3 PASS 계획을 `candidates/test_<tc-id>.py`로 변환하고, 코드의 `# EXPECTED_RESULT: <result_id>` 표식으로 TC 기대 결과를 Assertion에 연결합니다.

### 권한과 금지

- 모델은 TC의 사전조건·행동·기대 결과를 제한된 계획으로만 옮깁니다.
- 모델은 Python, 새 테스트 목적, 경계값, Selector와 Requirement를 만들 수 없습니다.
- 컴파일러는 허용된 행동·Assertion 코드 조각만 조합합니다.
- Assertion 삭제·약화, `assert True`, 무조건 skip, 예외 전체 무시를 금지합니다.
- 외부 URL, Shell, 임의 파일 삭제와 원본 프로젝트 수정을 금지합니다.
- CP3 계획 실패만 최대 1회 재작성하며 시험 실행의 기술 오류 자동 수정은 아직 구현하지 않았습니다.

UI 조사기는 코드 생성 전에 실제 로컬 화면에서 허용 Selector와 `window.__vccs` 키의 존재·가시성·활성 상태를 확인합니다. 현재 구현은 Python Playwright를 사용하며 Project1 파일을 수정하지 않습니다.

Agent 3 모델에는 시스템 지침, 선택 TC, 관련 SRS 행과 UI 조사 JSON(대상 파일명·SHA-256, 페이지 제목, Selector별 tag·text·visible·enabled·action_hint, 하네스 키)을 전송합니다. API 키, 로컬 절대경로, HTML 원문, Screenshot과 Trace는 제외하며 `--preview-only` 결과를 먼저 검토할 수 있습니다.

MVP의 실제 실행기는 Python Playwright입니다. 생성·검증을 마친 코드는 파일로 저장하고 이후 재실행에서는 모델을 다시 호출하지 않습니다. Playwright MCP는 현재 필수 의존성이 아니며 향후 조사 보조 수단으로만 봅니다.

## 9. Checkpoint 3과 격리 시험

### 자동 검사

- CP3-001: 승인 TC ID 보존
- CP3-002: Action ID 유일성, 실제 확인 Selector, 행동 유형과 Selector 일치
- CP3-003: 모든 Expected Result와 Assertion의 정확한 1:1 매핑
- CP3-004: UI·내부 상태·알림 관찰 계층과 Assertion 전략·대상·기대 수치 근거 보존
- CP3-005: TC에 없는 모드·온도 값 추가 금지
- CP3-006·006A: PRECONDITION→TEST→RESTORE 순서와 복원 계약
- CP3-007: Python 구문과 테스트 함수
- CP3-008: 허용 import, Shell·파일 변경·동적 실행·skip·assert True 금지
- CP3-009: 모든 Expected Result의 코드 Assertion 표식
- LOCAL 제어 TC는 별도 UI 조사 전까지 Agent 3 시작 단계에서 명시적으로 차단

### 실제 확인

- 비밀 환경변수를 제거한 임시 폴더에서 새 브라우저 Context를 엽니다.
- 원본 후보와 Project1 파일을 수정하지 않습니다.
- 종료 코드·stdout·stderr와 실제 생성된 Screenshot·Trace를 저장합니다.
- stdout·stderr의 로컬 절대경로와 `file://` 주소를 마스킹합니다.
- 기대 불일치는 `PRODUCT_MISMATCH_CANDIDATE`, 코드 오류는 `AUTOMATION_ERROR`, 브라우저·페이지 문제는 `ENVIRONMENT_ERROR`, 시간 초과는 `TIMEOUT`으로 분리합니다.
- 일반 Snapshot/Restore와 결함 주입 검증은 MVP 완료 조건이 아닙니다.

후보 상태는 `READY_FOR_EXECUTION`, `PRODUCT_MISMATCH_DETECTED`, `REVISION_REQUIRED`, `TRIAL_FAILED`, `NOT_AUTOMATABLE`, `BLOCKED` 중 하나입니다. CP3 PASS와 시험 PASS는 `READY_FOR_EXECUTION`, CP3 PASS와 제품 기대 불일치는 `PRODUCT_MISMATCH_DETECTED`입니다.

`PRODUCT_MISMATCH_DETECTED`는 자동화 후보가 제품 기대 불일치를 재현했다는 뜻이며 최종 제품 결함 확정은 아닙니다. CP3 PASS는 코드가 TC를 충실히 구현했음을 뜻하지만 제품 동작의 정당성을 보장하지 않습니다.

## 10. 조건부 검토와 정식 QA 자산 등록 승인

REVIEW가 발생한 경우에만 다음 기록을 생성합니다.

~~~json
{
  "review_id": "REV-...",
  "run_id": "RUN-...",
  "trigger_rule_ids": ["CP2-007"],
  "artifact_ids": ["ART-..."],
  "decision": "PROCEED",
  "reviewed_at": "ISO-8601",
  "resume_from": "AGENT_3"
}
~~~

사람은 Finding과 근거를 확인하고 PROCEED, REVISION_REQUIRED 또는 REJECTED를 선택합니다. 정상 PASS 흐름에는 이 기록이 필요하지 않습니다.

Agent 4 최종 보고 후에는 asset_registration_decision.json에 APPROVED 또는 REJECTED를 한 번 기록합니다. APPROVED는 검증이 끝난 SRS·TC·Playwright 코드를 다음 변경에서도 재사용할 정식 QA 자산으로 저장해도 된다는 뜻입니다. 자동 파일 등록은 MVP 범위가 아닙니다.

## 11. Agent 4 — Result Analysis Engine

Agent 4는 생성형 모델이 아니라 규칙 기반 Python 분석기입니다.

### 입력

- 현재 Run의 변경 검증·기존 회귀 결과
- TC·Requirement 연결
- exit code, phase, exception type, raw message
- UI·내부 상태 Assertion 결과

### 출력

- 실행 합계와 실패 분류
- Finding과 근거
- PASS·HOLD·HUMAN_REVIEW 권고
- 최종 보고 JSON

### Checkpoint 4 최소 검사

- 단일 Run ID, 중복 TC 없음
- 결과 수와 합계 일치
- 실패 근거 존재
- 제품 TC와 파이프라인 검증용 고정 사례 분리
- 보고 JSON과 표시 수치 일치

기존 Project1의 의미 라벨이 포함된 `failure_reason`은 분류 정확도 평가용 정답 데이터로 사용하지 않습니다.

## 12. Handoff·인수 기준

- BLOCKED이면 다음 단계를 실행하지 않습니다.
- Agent 2는 SHA-256과 재계산 검증을 통과한 Agent 1 Run만 입력으로 사용합니다.
- Run ID, 입력 파일 SHA-256 또는 재계산한 CP1이 저장 결과와 다르면 차단합니다.
- CP1~3과 격리 시험을 통과한 후보만 현재 Run 제품 검증 세트에 넣습니다.
- REVIEW가 발생하면 사람의 조건부 판정 전까지 해당 단계와 후속 단계를 중지합니다.
- 정식 QA 자산 등록 승인 전에는 기존 SRS·TC·자동화 자산을 덮어쓰지 않습니다.
- 필수 필드 누락과 Agent 3의 기대값 변경이 실제 Checkpoint 테스트로 탐지되어야 합니다.
