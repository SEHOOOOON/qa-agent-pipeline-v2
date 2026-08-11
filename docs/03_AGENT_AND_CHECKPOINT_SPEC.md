# Agent·Checkpoint 입출력 명세

## 1. 목적과 상태

V2에서 새로 구현할 Agent 1~3, 기존 규칙 기반 Agent 4와 Checkpoint의 최소 계약을 정의합니다. **현재는 설계 명세이며 실행 코드가 완료된 상태가 아닙니다.**

다음 단계에는 화면 문구나 자유 형식 Markdown이 아니라 Schema 검증을 통과한 JSON만 전달합니다.

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
- 초기 제품 기준 문서
- 지원 유형 MODIFIED

### 출력 최소형

~~~json
{
  "change_request_id": "CR-...",
  "change_type": "MODIFIED",
  "target_requirements": [
    {
      "requirement_id": "REQ-...",
      "before": "SRS의 기존 조건",
      "after": "요청의 변경 후 조건",
      "changed_fields": ["..."],
      "evidence": [
        {"source": "product_srs", "reference": "REQ-..."},
        {"source": "change_request", "reference": "requested_behavior"}
      ]
    }
  ],
  "direct_impacts": ["REQ-..."],
  "related_impacts": [
    {"requirement_id": "REQ-...", "reason": "..."}
  ],
  "confirmed_scope": ["..."],
  "excluded_scope": ["..."],
  "open_questions": [],
  "recommended_disposition": "PROCEED"
}
~~~

### 권한과 금지

- 영향 후보는 제안할 수 있지만 SRS를 수정하지 않습니다.
- 없는 Requirement ID, 요청에 없는 after 값과 근거 없는 기능을 만들 수 없습니다.
- 알려진 GAP을 정상 정책으로 확정할 수 없습니다.

## 5. Checkpoint 1

| Rule ID | 검사 | 결과 |
|---|---|---|
| CP1-001 | Requirement ID가 SRS에 존재 | FAIL |
| CP1-002 | before가 SRS와 일치 | FAIL |
| CP1-003 | after가 변경 요청에 존재 | FAIL |
| CP1-004 | change_type이 MODIFIED | FAIL |
| CP1-005 | 모든 변경에 source·reference 존재 | FAIL |
| CP1-006 | confirmed·excluded scope 미중복 | FAIL |
| CP1-007 | GAP 정책 임의 확정 없음 | REVIEW 또는 FAIL |
| CP1-008 | JSON Schema 유효 | ERROR |

간접 영향이 충분한지는 자동 PASS로 확정하지 않고 Finding으로 남깁니다.

## 6. Agent 2 — Product Test Designer

### 입력

- CP1 통과 Agent 1 Artifact
- 관련 SRS Requirement와 Acceptance Criteria
- 기존 TC 목록
- 3-Tier QA 기준

### 출력 최소형

~~~json
{
  "source_change_analysis_id": "ART-...",
  "test_cases": [
    {
      "tc_id": "TC-CAND-...",
      "change_action": "NEW",
      "requirement_ids": ["REQ-..."],
      "title": "...",
      "purpose": "...",
      "preconditions": ["..."],
      "steps": [{"order": 1, "action": "..."}],
      "expected_results": [
        {
          "assertion_id": "AR-001",
          "observable": "ui",
          "expected": "...",
          "source_requirement_id": "REQ-..."
        }
      ],
      "cleanup": ["브라우저 Context 종료"],
      "automation_candidate": true
    }
  ],
  "regression_candidates": ["TC-..."]
}
~~~

### 3-Tier 기준

1. 공통 QA: 정상·예외·경계, 명확한 조건·행동·기대 결과
2. 중앙제어: 모드·온도·잠금·오류·대상·비대상·상태 전이
3. 기능 품질: 요구사항 근거·독립성·자동화 가능성·추적성

### 권한과 금지

- 제품 기능 TC의 목적과 기대 결과를 설계합니다.
- CP1이 검증한 범위 밖 동작, 알려진 결함을 정상값으로 사용하거나 근거 없는 UI 표현을 기대값으로 확정할 수 없습니다.
- 기존 TC를 직접 삭제하지 않습니다.

## 7. Checkpoint 2

| Rule ID | 검사 | 결과 |
|---|---|---|
| CP2-001 | TC ID·change_action 유효 | FAIL |
| CP2-002 | Requirement가 CP1 검증 범위에 존재 | FAIL |
| CP2-003 | precondition·step·expected result 존재 | FAIL |
| CP2-004 | 기대 결과별 Requirement 근거 존재 | FAIL |
| CP2-005 | 상태 변경에 UI·내부 상태 관찰 정의 | FAIL 또는 REVIEW |
| CP2-006 | GAP을 정상 기대값으로 사용하지 않음 | FAIL |
| CP2-007 | 기존 TC와 명시적 중복 | REVIEW |
| CP2-008 | 비대상 불변 등 변경 위험 반영 | REVIEW |
| CP2-009 | Schema 유효 | ERROR |

기준 미달 시 Rule ID와 누락 항목만 제시해 Agent 2에 최대 1회 재작업을 요청합니다. Checkpoint가 기대값을 대신 작성하지 않습니다.

## 8. Agent 3 — Automation Engineer

### 입력

- CP2 통과 TC
- 관련 SRS
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
