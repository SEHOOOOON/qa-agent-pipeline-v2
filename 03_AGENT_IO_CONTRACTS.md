# Agent 1~4 입출력 계약

> 구현 전 계약 초안. 실제 구현에서는 JSON Schema 또는 Pydantic으로 강제한다.

## 1. 공통 Artifact Envelope

```json
{
  "schema_version": "artifact.v1",
  "artifact_id": "ART-...",
  "run_id": "RUN-...",
  "stage_id": "agent_1",
  "mode": "FIXTURE|LIVE",
  "input_artifact_ids": [],
  "input_hashes": {},
  "generator": {
    "type": "MODEL|DETERMINISTIC_RULE|HUMAN",
    "provider": "",
    "model": "",
    "prompt_version": ""
  },
  "created_at": "ISO-8601"
}
```

원본 응답과 정규화 출력은 분리한다. 다음 Agent는 Checkpoint를 통과한 정규화 출력만 사용한다.

## 2. Agent 1 — Change Analyst

### 입력

- Approved Baseline SRS
- 변경 요청 원문
- 시스템 지원 기능과 Requirement ID
- 기존 TC·Domain Rule
- 분석 정책과 이전 사용자 답변

### 출력

```json
{
  "change_id": "",
  "input_assessment": {
    "level": "LEVEL_1|LEVEL_2|LEVEL_3",
    "reason": ""
  },
  "analysis_status": "PROCEED|PARTIAL_PROCEED|WAITING_FOR_USER|BLOCKED",
  "changes": [
    {
      "change_item_id": "",
      "change_type": "ADDED|MODIFIED|DELETED|UNCHANGED|AMBIGUOUS",
      "target_requirement_ids": [],
      "before": {},
      "after": {},
      "changed_fields": [],
      "direct_impacts": [],
      "related_impacts": [],
      "source_evidence": []
    }
  ],
  "confirmed_facts": [],
  "inferred_facts": [],
  "information_gaps": [],
  "clarification_questions": [],
  "control_points": [],
  "testable_scope": [],
  "excluded_scope": [],
  "integration_assessment": {
    "required": false,
    "reason": "",
    "risks": [],
    "required_invariants": []
  },
  "recommendation": {
    "passed_scope": [],
    "excluded_scope": [],
    "blocking_gaps": [],
    "reason": ""
  }
}
```

### 금지

- TC·Playwright 코드 작성
- 추정·정보 부족을 기대결과로 확정
- 존재하지 않는 Requirement 생성
- 제품 PASS/FAIL·릴리즈 결정

## 3. Agent 2 — TC Change Set

### 입력

- Checkpoint 1 승인 Artifact
- 관련 Baseline Requirement·기존 TC
- 3-Tier QA 기준과 Core Regression 목록

### 출력

```json
{
  "change_id": "",
  "tc_changes": [
    {
      "tc_id": "",
      "action": "NEW|UPDATED|REGRESSION|DEPRECATION_PROPOSED|NO_IMPACT",
      "requirement_ids": [],
      "change_rationale": "",
      "category": "PRECHECK|HAPPY_PATH|EDGE|NEGATIVE|INTEGRATION",
      "title": "",
      "qa_criteria": [],
      "quality_standard_ids": [],
      "risk_covered": [],
      "initial_state": {},
      "preconditions": [],
      "setup": [],
      "steps": [],
      "expected_ui": [],
      "expected_device_state": [],
      "negative_assertions": [],
      "unchanged_state_assertions": [],
      "excluded_assertions": [],
      "cleanup": [],
      "source_evidence": [],
      "double_assert_policy": "REQUIRED|UI_ONLY|REGISTER_ONLY|NOT_APPLICABLE",
      "automation_level": "AUTOMATED|MANUAL|REVIEW_NEEDED",
      "independent_execution": true,
      "automation_candidate": true
    }
  ],
  "recommended_execution_sets": {
    "change_validation": [],
    "feature_regression": [],
    "core_regression": []
  }
}
```

`independent_execution`은 Setup으로 상태 구성 가능, 이전 TC 비참조, Cleanup·Restore 존재, 테스트 데이터 명시 조건을 모두 만족할 때만 `true`다.

### 금지

- Agent 1 제외 범위의 TC 생성
- 근거 없는 색상·문구·시간·경계값 생성
- 기존 TC 물리 삭제
- Selector·코드 작성
- 하나의 TC에 무관한 목적 결합

## 4. Agent 3 — Automation Engineer

### 입력

- Checkpoint 2 통과 TC Snapshot과 해시
- Reference Automation·Selector Registry
- Playwright 도구·QA Bridge 계약
- Sandbox·금지 코드 정책

### 구현 계획

```json
{
  "tc_id": "",
  "tc_snapshot_hash": "sha256:...",
  "implementation_plan": [],
  "locator_evidence": [],
  "assertion_mapping": [
    {
      "expected_result_id": "",
      "implementation_target": "UI|DEVICE_STATE|REGISTER|COMMAND_RESULT|LOG",
      "planned_assertion": ""
    }
  ],
  "setup_plan": [],
  "restore_plan": [],
  "unresolved_items": []
}
```

### 코드 후보 Manifest

```json
{
  "candidate_id": "CAND-...",
  "tc_id": "",
  "tc_snapshot_hash": "sha256:...",
  "candidate_path": "runs/.../candidate-tests/test_candidate.py",
  "source_hash": "sha256:...",
  "used_tools": [],
  "static_check_status": "PENDING|PASSED|FAILED",
  "trial_status": "NOT_RUN|PASSED|FAILED|ERROR",
  "revision_count": 0,
  "changed_assertions": false,
  "sandbox_profile": "",
  "normal_trial_results": [],
  "fault_profile_results": [],
  "restore_status": "NOT_RUN|PASSED|FAILED",
  "evidence_refs": []
}
```

### 허용

- 실제 화면 관찰·Locator 선택
- 승인 TC의 사전조건·행동·기대결과 구현
- QA Bridge 내부 상태 조회
- Locator·대기·Fixture 기술 문제 최대 1회 수정

### 금지

- 목적·경계값·기대결과 변경
- Assertion 삭제·실패 무시
- `assert True`, 무조건 Skip, 광범위 예외 삼키기
- Shell·임의 파일 삭제·외부 URL
- 승인 자산 덮어쓰기

## 5. Agent 4 — Result Analysis Engine

### 입력

- Agent 1·2 승인 Artifact
- Agent 3 후보·검증 결과
- 변경·기능·Core Regression 결과
- Screenshot·Trace·UI·내부 상태·Register·로그
- Restore 결과와 동일 Source Run ID

### 출력

```json
{
  "analysis_run_id": "",
  "source_execution_run_id": "",
  "checkpoint4_status": "VALIDATED|BLOCKED",
  "execution_result": "PASSED|FAILED|INCOMPLETE",
  "release_decision": "PASS|HOLD|HUMAN_REVIEW",
  "classification_summary": {},
  "results": [],
  "automation_candidate_summary": {},
  "baseline_promotion_recommendation": {
    "decision": "RECOMMEND|DO_NOT_RECOMMEND|REVIEW",
    "reason": ""
  }
}
```

분류: PRODUCT_DEFECT, REQUIREMENT_REVIEW, AUTOMATION_GENERATION_ERROR, AUTOMATION_EXECUTION_ERROR, ENVIRONMENT_ISSUE, NEEDS_MORE_EVIDENCE, NOT_EXECUTED.

현재 Agent 4는 결정론적 규칙 엔진이다.

## 6. Checkpoint 공통 출력

```json
{
  "checkpoint_id": "CP-...",
  "run_id": "RUN-...",
  "input_artifact_ids": [],
  "status": "PASSED|REVIEW|BLOCKED",
  "checks": [
    {
      "rule_id": "",
      "severity": "CRITICAL|MAJOR|MINOR",
      "status": "PASS|FAIL|NOT_APPLICABLE",
      "message": "",
      "evidence_refs": []
    }
  ],
  "next_action": "AUTO_CONTINUE|HUMAN_REVIEW|RETURN_ONCE|STOP",
  "created_at": "ISO-8601"
}
```

Checkpoint는 입력을 수정하거나 새 제품 기대값을 만들지 않는다.

## 7. 저장 구조

```text
runs/<run_id>/
├─ manifest.json
├─ change_request.json
├─ agent1/raw.json
├─ agent1/normalized.json
├─ checkpoint1.json
├─ agent2/raw.json
├─ agent2/tc_changeset.json
├─ checkpoint2.json
├─ agent3/automation_plan.json
├─ agent3/candidate_manifest.json
├─ candidate-tests/
├─ checkpoint3.json
├─ trial-results/
├─ human_approval.json
├─ product-validation/
├─ core-regression/
├─ checkpoint4.json
└─ final-report.json
```

Run 산출물은 append-only로 보존한다.
