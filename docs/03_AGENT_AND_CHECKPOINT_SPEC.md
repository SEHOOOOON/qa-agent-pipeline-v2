# Agent·Checkpoint 입출력 명세

## 1. 목적과 상태

V2 Agent 1~3, 기존 규칙 기반 Agent 4와 Checkpoint의 최소 계약을 정의합니다. **Agent 1·CP1과 Agent 2·CP2는 구현·Live 실행을 확인했고, Agent 3 이후는 아직 설계 명세입니다.**

다음 단계에는 화면 문구나 자유 형식 Markdown이 아니라 Schema 검증을 통과한 JSON만 전달합니다.

제품 요구사항은 Product SRS, 기존 구현 상태는 Project1 기준 자산 감사, QA Drawer·Register·window.__vccs 사용법은 QA 하네스 가이드를 각각 기준으로 합니다. Agent는 QA 하네스 기능을 제품 기능으로 추가할 수 없습니다.

## 2. 공통 Envelope

~~~json
{
  "contract_version": "2.0",
  "run_id": "RUN-...",
  "artifact_id": "ART-...",
  "component": "agent_1",
  "mode": "live",
  "created_at": "ISO-8601",
  "input_artifact_ids": ["ART-..."],
  "status": "COMPLETED"
}
~~~

### 공통 규칙

- 한 실행은 같은 run_id를 사용합니다.
- mode는 live 또는 fixture입니다.
- 입력 Artifact ID로 실제 인계를 기록합니다.
- 모델 원문과 정규화 JSON을 분리합니다.
- Schema 실패 시 다음 단계로 넘기지 않습니다.
- 모델명·Prompt 버전은 Manifest에 기록하되 비밀값은 저장하지 않습니다.

## 3. 상태와 판정

| 상태 | 의미 |
|---|---|
| PASS | 자동 규칙 충족 |
| FAIL | 명백한 계약·정책 위반 |
| REVIEW | 사람의 의미 판단 필요 |
| ERROR | 모델·파서·실행 오류 |
| BLOCKED | 선행 실패로 미실행 |
| NOT_APPLICABLE | 적용 대상 아님 |

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
    {"requirement_id": "REQ-...", "relation": "VERIFY", "reason": "..."}
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
- 대상 Requirement는 MODIFIED, 변경하지 않지만 함께 확인할 기존 기준은 VERIFY로 구분합니다.
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
| CP1-006 | MODIFIED·VERIFY Requirement가 SRS에 존재하고 확정 조건과 연결 | FAIL |
| CP1-007 | 확정 조건의 출처 원문이 변경 요청 또는 SRS에 존재 | FAIL |
| CP1-008 | 변경 요청의 모든 acceptance_notes가 확정 조건에 포함 | FAIL |
| CP1-009 | 확정 조건·제외 범위 분리 및 요청의 out_of_scope 보존 | FAIL |
| CP1-010 | 정보 부족·사용자 질문·진행 판정 일관성 및 불필요한 재확인 방지 | REVIEW |

CP1은 확정 조건의 출처와 누락을 검사하지만 자연어 의미의 완전한 타당성까지 보장하지 않습니다.

## 6. Agent 2 — Product Test Designer

### 현재 상태

- OpenAI Responses API 구조화 출력 구현
- CP1 PASS Run만 입력 가능
- 같은 Run 폴더에 TC 후보·CP2·manifest 저장
- CP2 FAIL 시 전체 TC 세트를 유지하며 최대 1회 재작업
- 기존 TC 구조화 목록이 없으므로 NEW·UPDATED·DEPRECATED 판정은 아직 하지 않음

### 입력

- CP1을 통과한 agent1_change_analysis.json
- Product SRS Requirement·Acceptance Criteria
- Agent 1의 MODIFIED·VERIFY·NO_IMPACT와 확정 조건

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
      "restore_steps": ["..."],
      "automation_candidate": true,
      "automation_reason": "..."
    }
  ],
  "coverage_summary": "..."
}
~~~

### 권한과 금지

- 제품 기능 TC의 목적과 기대 결과를 설계합니다.
- 모든 Agent 1 확정 조건을 최소 한 개 TC와 기대 결과에 연결합니다.
- 상태 정합성 TC는 UI·내부 상태를 함께 정의하고 알림 조건은 NOTIFICATION으로 구분합니다.
- CP1 범위 밖 ID, 근거 없는 수치·문구, Playwright·Python 코드를 생성할 수 없습니다.
- 기존 TC 비교 자산이 생기기 전에는 NEW·UPDATED·DEPRECATED를 주장하지 않습니다.

## 7. Checkpoint 2

| Rule ID | 현재 검사 | 결과 |
|---|---|---|
| CP2-001 | Agent 1·2 요청 ID 일치 | FAIL |
| CP2-002 | TC·Expected Result ID와 제목 고유성 | FAIL |
| CP2-003 | Requirement·Condition이 CP1 활성 범위에 존재 | FAIL |
| CP2-004 | 모든 Agent 1 확정 조건의 TC 반영 | FAIL |
| CP2-005 | TC→Requirement·Condition→Expected Result 추적 연결 | FAIL |
| CP2-006 | REQ-STATE-001 또는 STATE_CONSISTENCY 유형의 UI·내부 상태 이중 검증 | FAIL |
| CP2-007 | REQ-NOTIFY-001 조건의 NOTIFICATION 기대 결과 | FAIL |
| CP2-008 | MODIFIED·VERIFY Requirement 범위와 변경 검증 TC 존재 | FAIL |
| CP2-009 | 제품 TC에 Playwright·Python·무효 Assertion 혼입 금지 | FAIL |

기준 미달 시 Rule ID와 실패 메시지만 제시해 최대 1회 재작업합니다. 재작업은 이전 전체 TC 세트를 반환해야 하며, Checkpoint가 삭제를 요구하지 않은 TC를 제거할 수 없습니다.

CP2 PASS는 구조·ID·명시적 추적 규칙 통과를 뜻합니다. 자연어 의미, 모드·경계 조합의 충분성, 간접 영향의 최종 타당성은 사람의 마지막 검토 범위입니다.

## 8. Agent 3 — Automation Engineer

### 입력

- CP2 통과 TC
- 관련 Product SRS Requirement
- 프로젝트 1 기존 기준 자동화 코드
- 실제 UI Selector Inventory
- `window.__vccs`에서 읽을 수 있는 필드
- 허용 URL·Fixture·금지 정책

### 출력 최소형

~~~json
{
  "source_tc_artifact_id": "ART-...",
  "candidate_id": "AUTO-CAND-...",
  "language": "python",
  "framework": "pytest-playwright",
  "file_path": "runs/RUN-.../candidates/test_candidate.py",
  "tc_ids": ["TC-CAND-..."],
  "mapping": [
    {
      "tc_item": "AR-001",
      "code_reference": "test_candidate.py:42",
      "implementation": "UI Assertion"
    }
  ],
  "technical_revision_count": 0
}
~~~

### 권한과 금지

- TC의 사전조건·행동·기대 결과를 코드로 구현합니다.
- 새 테스트 목적, 경계값과 Requirement를 만들 수 없습니다.
- Assertion 삭제·약화, `assert True`, 무조건 skip, 예외 전체 무시를 금지합니다.
- 외부 URL, Shell, 임의 파일 삭제와 원본 프로젝트 수정을 금지합니다.
- 문법·Locator·Wait·Fixture 오류만 최대 1회 수정합니다.

Agent 3는 코드 생성 전에 실제 로컬 화면을 열어 접근성 구조, role·name·test id, 입력 가능 상태와 제어 후 변화를 확인합니다. Playwright MCP는 이 조사와 Locator 검증을 돕는 개발 시점 도구이며, 사용할 수 없으면 Python Playwright 조사 스크립트로 같은 근거를 수집합니다.

MVP의 실제 실행기는 Python Playwright입니다. 생성·검증을 마친 코드는 파일로 저장하고 이후 회귀 실행에서는 모델이나 MCP를 다시 호출하지 않습니다. MCP 사용 여부 자체를 코드 품질 보장이나 구현 완료의 근거로 사용하지 않습니다.

## 9. Checkpoint 3과 격리 시험

### 자동 검사

- Python 구문과 테스트 함수 존재
- pytest·Playwright Fixture 사용
- 허용 URL만 사용
- TC Step·Expected Result와 코드 매핑 존재
- 핵심 기대 결과의 Assertion 존재
- 기대값·Requirement 불변
- 금지 패턴 없음

### 실제 확인

- 새 브라우저 Context에서 로컬 페이지를 엽니다.
- 명시된 사전조건을 설정합니다.
- 후보를 한 번 실행하고 종료 코드·stdout·stderr를 저장합니다.
- Locator·Fixture 기술 오류만 한 번 수정할 수 있습니다.
- 일반 Snapshot/Restore와 결함 주입 검증은 MVP 완료 조건이 아닙니다.

결과는 READY_FOR_EXECUTION, HUMAN_REVIEW, REVISION_REQUIRED, TRIAL_FAILED, NOT_AUTOMATABLE, BLOCKED 중 하나입니다. CP3와 격리 시험이 PASS이면 READY_FOR_EXECUTION으로 자동 전환합니다.

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
- 다음 Agent는 검증된 Artifact만 입력으로 사용합니다.
- Run ID와 input_artifact_ids가 불일치하면 차단합니다.
- CP1~3과 격리 시험을 통과한 후보만 현재 Run 제품 검증 세트에 넣습니다.
- REVIEW가 발생하면 사람의 조건부 판정 전까지 해당 단계와 후속 단계를 중지합니다.
- 정식 QA 자산 등록 승인 전에는 기존 SRS·TC·자동화 자산을 덮어쓰지 않습니다.
- 필수 필드 누락과 Agent 3의 기대값 변경이 실제 Checkpoint 테스트로 탐지되어야 합니다.
