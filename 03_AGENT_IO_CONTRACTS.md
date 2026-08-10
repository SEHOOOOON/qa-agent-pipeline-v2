# Agent·Checkpoint 입출력 및 Artifact 계약

## 문서 통제

| 항목 | 값 |
|---|---|
| 문서 ID | ICD-AGENT-001 |
| 버전 | 0.2 |
| 상태 | REVIEW_READY |
| 소유자 | QA |
| 관련 문서 | SRS-VCCS-BL-001, ICD-CHANGE-001, POL-GATE-001 |
| 적용 대상 | Agent 1~4, Checkpoint 1~4, QA Manager |

## 1. 목적

본 계약은 Agent와 Checkpoint가 주고받는 입력, 출력, 상태, 해시와 오류를 정의합니다. 목적은 모델 응답 형식을 보기 좋게 만드는 것이 아니라 다음을 보장하는 것입니다.

- 앞 단계의 실제 승인 Artifact가 다음 단계 입력이 됩니다.
- 모델 원본 응답과 시스템이 검증한 정규화 결과를 구분합니다.
- 요구사항·TC·코드·실행 결과의 추적성을 유지합니다.
- 모델이 자신의 권한 밖의 산출물을 만들거나 기존 기준을 변경하지 못하게 합니다.
- Fixture, Live, 결정론적 처리와 사람 결정을 명확히 표시합니다.

## 2. 공통 원칙

### 2.1 원본 보존

- 입력 원문과 모델 원본 응답은 수정하지 않습니다.
- 파싱·정규화·검증 결과는 별도 Artifact로 저장합니다.
- 재작업 결과는 새 revision으로 저장하며 이전 결과를 덮어쓰지 않습니다.

### 2.2 승인된 인계

- 다음 단계는 Checkpoint에서 전달 허용된 정규화 Artifact만 읽습니다.
- raw 응답, REVIEW, BLOCKED Artifact를 다음 Agent 입력으로 사용하지 않습니다.
- PARTIAL 범위는 passed_scope만 인계합니다.

### 2.3 권한 분리

| 구성요소 | 생성 가능 | 변경 금지 |
|---|---|---|
| Agent 1 | 변경 분석 | TC, 코드, 제품 결과 |
| Agent 2 | 제품 기능 TC Change Set | SRS, Locator, 코드 |
| Agent 3 | 자동화 계획·코드 후보 | TC 목적·기대결과·경계값 |
| Agent 4 | 결과 분류·보고 | 실행 원본·제품 상태 |
| Checkpoint | 검사 결과·판정 | 입력 Artifact 내용 |
| QA Manager | Run 상태·인계·해시 | 제품 기대결과 |
| Human Reviewer | 승인·반려·수정 요청 | 감사 이력 삭제 |

### 2.4 실행 사실성

모든 Artifact는 생성 주체를 다음 중 하나로 표시합니다.

- MODEL
- DETERMINISTIC_RULE
- EXECUTOR
- HUMAN
- FIXTURE

FIXTURE는 모델 실행으로 표시할 수 없고, EXECUTOR는 생성형 Agent로 표시할 수 없습니다.

## 3. 공통 Artifact Envelope

    {
      "schema_version": "artifact.v1",
      "artifact_id": "ART-...",
      "run_id": "RUN-...",
      "stage_id": "agent_1",
      "revision": 0,
      "mode": "FIXTURE|LIVE",
      "producer_type": "MODEL|DETERMINISTIC_RULE|EXECUTOR|HUMAN|FIXTURE",
      "input_artifact_ids": [],
      "input_hashes": {},
      "baseline_version": "",
      "baseline_hash": "sha256:...",
      "generator": {
        "provider": "",
        "model": "",
        "model_version": "",
        "prompt_id": "",
        "prompt_version": "",
        "prompt_hash": "",
        "temperature": null,
        "seed": null
      },
      "timing": {
        "started_at": "ISO-8601",
        "completed_at": "ISO-8601",
        "duration_ms": 0
      },
      "usage": {
        "input_tokens": null,
        "output_tokens": null,
        "estimated_cost": null,
        "currency": null
      },
      "content_hash": "sha256:...",
      "created_at": "ISO-8601"
    }

### 3.1 필수 공통 필드

| 필드 | 규칙 |
|---|---|
| artifact_id | Run 내 유일 |
| run_id | 실행 Envelope과 일치 |
| stage_id | 허용 Stage Enum |
| revision | 0 또는 허용된 1회 수정 |
| mode | FIXTURE 또는 LIVE |
| producer_type | 실제 생성 방식과 일치 |
| input_artifact_ids | 직접 입력 Artifact만 기록 |
| input_hashes | 인계 시점 파일 해시 |
| baseline_hash | Run 시작 Snapshot과 일치 |
| content_hash | 저장된 정규화 본문 해시 |
| generator | 모델 사용 시 필수, 그 외 유형에 맞게 기록 |
| timing | 시작·종료와 0 이상 duration |
| usage | 제공 가능한 모델 호출 비용·Token 기록 |

### 3.2 공통 오류 Envelope

    {
      "error_id": "ERR-...",
      "run_id": "RUN-...",
      "stage_id": "agent_2",
      "error_type": "INPUT|MODEL|PARSE|CONTRACT|TOOL|EXECUTION|TIMEOUT|SECURITY",
      "retryable": false,
      "message": "",
      "raw_evidence_ref": "",
      "occurred_at": "ISO-8601"
    }

오류를 빈 출력이나 PASS로 대체하지 않습니다.

## 4. Agent 1 — Change Analyst

### 4.1 목표

승인된 Baseline SRS와 변경 요청을 비교해 변경 대상, 변경 전후, 영향 범위, 불변 조건과 정보 부족을 식별합니다.

### 4.2 입력

| 입력 | 필수 | 조건 |
|---|---:|---|
| Change Request Artifact | Y | ICD-CHANGE-001 통과 |
| Baseline SRS Snapshot | Y | 버전·해시 고정 |
| Requirement Index | Y | 유효 ID와 상태 |
| Existing TC Index | Y | 영향 분석 참고 |
| Domain Rule | Y | SRS 공통 규칙 |
| Prior Answers | N | 동일 Run의 승인 답변만 |
| Analysis Policy | Y | Prompt 외부 고정 규칙 |

### 4.3 출력 구조

    {
      "change_id": "",
      "input_assessment": {
        "level": "LEVEL_1|LEVEL_2|LEVEL_3",
        "reason": "",
        "missing_critical_fields": []
      },
      "analysis_status": "PROCEED|PARTIAL_PROCEED|WAITING_FOR_USER|BLOCKED",
      "changes": [
        {
          "change_item_id": "CI-001",
          "change_type": "ADDED|MODIFIED|DELETED|UNCHANGED|AMBIGUOUS",
          "target_requirement_ids": [],
          "before": {},
          "after": {},
          "changed_fields": [],
          "direct_impacts": [],
          "related_impacts": [],
          "required_invariants": [],
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

### 4.4 출력 규칙

- confirmed_fact는 입력 또는 Baseline Source ID를 가져야 합니다.
- inferred_fact는 추론 근거와 확정 금지 표시를 가져야 합니다.
- information_gap은 영향 Requirement와 blocking 여부를 가져야 합니다.
- before 값은 Baseline에서, after 값은 변경 원문에서 확인되어야 합니다.
- 관련 영향은 직접 영향과 구분하고 이유를 기록해야 합니다.
- passed_scope와 excluded_scope는 겹치면 안 됩니다.
- 존재하지 않는 Requirement는 candidate_reference로만 제안하고 확정 ID로 만들지 않습니다.

### 4.5 금지

- 제품 기능 TC와 Playwright 코드 작성
- 근거 없는 기대결과·색상·시간·경계값 추가
- TBD를 확정 사실로 승격
- 원본 SRS 수정
- 제품 PASS·FAIL과 릴리즈 결정

### 4.6 완료 조건

- CP1 입력 계약을 통과합니다.
- 모든 변경 Item이 Source Evidence를 가집니다.
- 정보 부족과 실행 범위가 분리됩니다.
- 다음 단계에 전달할 passed_scope가 명시됩니다.

## 5. Checkpoint 1 출력

    {
      "checkpoint_id": "CP1",
      "run_id": "",
      "input_artifact_ids": [],
      "status": "PASSED|PARTIAL|REVIEW|BLOCKED",
      "passed_scope": [],
      "excluded_scope": [],
      "checks": [],
      "next_action": "AUTO_CONTINUE|WAIT_FOR_USER|HUMAN_REVIEW|RETURN_ONCE|STOP",
      "created_at": "ISO-8601"
    }

CP1은 Agent 1 내용을 고치지 않습니다. 오류를 발견하면 rule_id, evidence_ref와 반환 사유를 기록합니다.

## 6. Agent 2 — Test Designer

### 6.1 목표

CP1에서 승인된 변경 범위와 기존 TC를 바탕으로 제품 기능 TC의 신규·수정·회귀·비활성화 후보를 제안합니다.

### 6.2 입력

| 입력 | 필수 | 조건 |
|---|---:|---|
| CP1 승인 Artifact | Y | passed_scope 존재 |
| 관련 Baseline Requirement | Y | 해시 고정 |
| Existing TC Snapshot | Y | 중복·수정 비교 |
| 3-Tier Quality Standard | Y | 버전 기록 |
| Core Regression Index | Y | 실행 세트 추천 |
| Past Defect Reference | N | Source 존재 시만 |

### 6.3 TC Change Set

    {
      "change_id": "",
      "tc_changes": [
        {
          "tc_id": "",
          "action": "NEW|UPDATED|REGRESSION|DEPRECATION_PROPOSED|NO_IMPACT",
          "requirement_ids": [],
          "change_item_ids": [],
          "change_rationale": "",
          "category": "PRECHECK|HAPPY_PATH|EDGE|NEGATIVE|INTEGRATION",
          "priority": "P0|P1|P2|P3",
          "title": "",
          "test_objective": "",
          "qa_criteria": [],
          "quality_standard_ids": [],
          "risk_covered": [],
          "initial_state": {},
          "preconditions": [],
          "setup": [],
          "steps": [],
          "expected_results": [
            {
              "expected_result_id": "ER-001",
              "observation_target": "UI|DEVICE_STATE|REGISTER|COMMAND_RESULT|LOG",
              "expected_value": "",
              "source_evidence": []
            }
          ],
          "negative_assertions": [],
          "unchanged_state_assertions": [],
          "excluded_assertions": [],
          "cleanup": [],
          "source_evidence": [],
          "double_assert_policy": "REQUIRED|EXCEPTION_APPROVED|NOT_APPLICABLE",
          "independent_execution": true,
          "automation_candidate": true,
          "automation_constraints": []
        }
      ],
      "recommended_execution_sets": {
        "change_validation": [],
        "feature_regression": [],
        "core_regression": []
      },
      "unresolved_items": []
    }

### 6.4 TC 품질 규칙

- 하나의 TC는 하나의 주된 테스트 목적을 가집니다.
- Requirement와 Change Item 연결이 있어야 합니다.
- 사전조건, 행동, 기대결과는 구체적이고 실행 가능해야 합니다.
- 상태 변경은 UI와 시스템 관측면을 함께 정의해야 합니다.
- 차단 테스트는 상태 불변 Assertion을 가져야 합니다.
- 통합·복수 제어는 비대상 장비와 비대상 필드 불변을 정의해야 합니다.
- Setup·Cleanup으로 독립 실행이 가능해야 합니다.
- 기존 TC와 중복이면 신규 생성 대신 UPDATED 또는 REGRESSION을 검토합니다.
- DELETED 요청도 물리 삭제하지 않고 DEPRECATION_PROPOSED로 기록합니다.

### 6.5 금지

- CP1 제외 범위의 TC 생성
- Baseline과 변경 원문에 없는 기대값 생성
- Selector·DOM ID·Playwright 코드 작성
- 기존 TC 즉시 삭제
- 실행 결과를 미리 PASS로 작성
- automation_candidate를 근거 없이 true로 설정

### 6.6 완료 조건

- CP2의 구조·추적성·Double-Assert 규칙을 통과합니다.
- 모든 expected_result가 고유 ID와 근거를 가집니다.
- 실행 세트의 각 TC가 Change·Feature·Core 중 어디에 속하는지 명확합니다.

## 7. Checkpoint 2 출력

    {
      "checkpoint_id": "CP2",
      "run_id": "",
      "input_artifact_ids": [],
      "status": "SANDBOX_ELIGIBLE|REVIEW|BLOCKED",
      "per_tc": [
        {
          "tc_id": "",
          "decision": "PASS|NEEDS_REVISION|REJECT",
          "checks": [],
          "automation_scope": "FULL|PARTIAL|MANUAL"
        }
      ],
      "next_action": "GENERATE_CANDIDATE|HUMAN_REVIEW|RETURN_ONCE|STOP"
    }

SANDBOX_ELIGIBLE은 정식 TC 승인이 아니라 원본을 변경하지 않는 환경에서 코드 후보를 생성해 볼 수 있다는 의미입니다.

## 8. Agent 3 — Automation Engineer

### 8.1 목표

CP2를 통과한 제품 기능 TC의 목적과 기대결과를 변경하지 않고 GPT와 Playwright 도구를 사용해 실행 가능한 Playwright 코드 후보를 생성합니다.

### 8.2 입력

| 입력 | 필수 | 조건 |
|---|---:|---|
| CP2 통과 TC Snapshot | Y | 해시 고정 |
| Reference Automation | Y | 읽기 전용 |
| Selector Registry | N | 존재하는 근거만 사용 |
| Playwright Tool Contract | Y | 허용 URL·동작 |
| QA Bridge Contract | Y | 허용 함수 |
| Sandbox Policy | Y | 파일·네트워크 제한 |
| Fault Profile | Y | 대표 오류 1~2개 |
| Runtime Profile | Y | Python·브라우저·Timeout |

### 8.3 구현 계획

    {
      "tc_id": "",
      "tc_snapshot_hash": "sha256:...",
      "implementation_plan": [],
      "locator_evidence": [
        {
          "target": "",
          "locator": "",
          "evidence_type": "ACCESSIBILITY|DOM|REFERENCE",
          "observed_at": "ISO-8601"
        }
      ],
      "assertion_mapping": [
        {
          "expected_result_id": "ER-001",
          "implementation_target": "UI|DEVICE_STATE|REGISTER|COMMAND_RESULT|LOG",
          "planned_assertion": "",
          "source_line_hint": ""
        }
      ],
      "setup_plan": [],
      "restore_plan": [],
      "unresolved_items": []
    }

### 8.4 코드 후보 Manifest

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

### 8.5 GPT와 Playwright 역할

GPT:

- 승인 TC와 Reference Automation을 해석합니다.
- 구현 계획과 코드 후보를 작성합니다.
- Playwright 도구의 관찰 결과로 Locator를 선택합니다.
- 기술적 오류 수정안을 최대 1회 작성합니다.

Playwright 도구:

- 로컬 중앙제어기 페이지를 엽니다.
- 접근성 구조와 실제 요소를 관찰합니다.
- Locator의 존재와 조작 가능성을 확인합니다.
- UI 변화와 Trace를 반환합니다.

QA Bridge:

- 내부 장비 상태를 조회합니다.
- Register Snapshot을 조회합니다.
- 허용된 초기화·복원 기능을 제공합니다.
- 제품 기대결과를 결정하지 않습니다.

### 8.6 허용 수정

- Locator 오류
- 대기 조건과 Timeout
- Fixture 참조
- 초기화·복원 코드 누락
- 내부 상태 조회 연결
- 문법·Import 오류

### 8.7 금지 수정

- TC 목적·Requirement ID
- 경계값·기대값
- expected_result 삭제
- 실패 Assertion 삭제·완화
- 제품 실제값을 기대값으로 사용
- 무조건 PASS·Skip
- 광범위 예외 삼키기
- Shell, 외부 URL, 임의 파일 삭제
- 승인 자산과 포트폴리오 파일 수정

### 8.8 후보 검증 결과

각 Trial은 다음을 기록합니다.

- Trial ID와 실행 순서
- Runtime·브라우저 버전
- 시작·종료·duration
- exit code
- stdout·stderr Artifact
- TC 결과
- Assertion별 결과
- Screenshot·Trace
- 실행 전·후 Snapshot
- Restore 결과
- Fault Profile ID

정상 Trial 3회가 모두 PASS해야 안정성 후보가 됩니다. 대표 오류 프로필은 설계된 Assertion에서 FAIL해야 합니다.

## 9. Checkpoint 3 출력

    {
      "checkpoint_id": "CP3",
      "run_id": "",
      "candidate_id": "",
      "status": "PROMOTION_READY|REVISION_REQUIRED|REVIEW|BLOCKED",
      "execution_viability": {},
      "intent_fidelity": {},
      "stability_and_detection": {},
      "security_checks": [],
      "assertion_diff": [],
      "next_action": "PROMOTION_GATE|RETURN_ONCE|HUMAN_REVIEW|STOP"
    }

PROMOTION_READY는 제품 판정에 즉시 사용 가능한 상태가 아닙니다. Human Promotion Gate 대상이 되었다는 뜻입니다.

## 10. Human Promotion Artifact

    {
      "approval_id": "APR-...",
      "run_id": "",
      "reviewed_artifact_ids": [],
      "reviewer": {
        "name": "",
        "role": "QA"
      },
      "decision": "APPROVED|REJECTED|REVISION_REQUESTED",
      "approved_tc_ids": [],
      "approved_candidate_ids": [],
      "conditions": [],
      "reason": "",
      "decided_at": "ISO-8601"
    }

사람 승인은 Agent 2 TC와 Agent 3 코드 후보를 함께 검토합니다. 승인하지 않은 코드는 Product Validation Lane에 들어갈 수 없습니다.

## 11. Product Validation Executor

### 입력

- Human Promotion APPROVED Artifact
- 승인된 변경 자동화 복사본
- 기존 승인 Feature·Core Regression
- Runtime Profile
- 초기화·복원 정책

### 출력

    {
      "source_execution_run_id": "EXEC-...",
      "suite_results": {
        "change_validation": {},
        "feature_regression": {},
        "core_regression": {}
      },
      "environment": {},
      "restore_status": "PASSED|FAILED",
      "artifacts": []
    }

실행기는 Agent가 아니며 승인 코드를 결정론적으로 실행합니다.

## 12. Agent 4 — Result Analysis Engine

### 12.1 성격

Agent 4는 현재와 V2 모두 Python 규칙 기반 결과 분석기입니다. LLM 추론을 사용하지 않는 한 producer_type은 DETERMINISTIC_RULE입니다.

### 12.2 입력

- Agent 1·2 승인 Artifact
- Agent 3 후보·검증 결과
- Human Promotion Artifact
- Product Validation 실행 원본
- Screenshot·Trace·상태·Register·로그
- Restore 결과
- 단일 Source Execution Run ID

### 12.3 결과 분류

- PRODUCT_DEFECT
- REQUIREMENT_REVIEW
- AUTOMATION_GENERATION_ERROR
- AUTOMATION_EXECUTION_ERROR
- ENVIRONMENT_ISSUE
- NEEDS_MORE_EVIDENCE
- NOT_EXECUTED

분류 정확도 평가용 Gold Label은 입력 failure_reason에 포함하지 않습니다.

### 12.4 출력

    {
      "analysis_run_id": "",
      "source_execution_run_id": "",
      "checkpoint4_status": "PENDING|VALIDATED|BLOCKED",
      "execution_result": "PASSED|FAILED|INCOMPLETE",
      "release_decision": "PASS|HOLD|HUMAN_REVIEW",
      "classification_summary": {},
      "results": [],
      "automation_candidate_summary": {},
      "baseline_promotion_recommendation": {
        "decision": "RECOMMEND|DO_NOT_RECOMMEND|REVIEW",
        "reason": ""
      },
      "evidence_refs": []
    }

Agent 4는 Baseline을 직접 변경하거나 외부 보고를 먼저 전송하지 않습니다.

## 13. Checkpoint 4 출력

    {
      "checkpoint_id": "CP4",
      "run_id": "",
      "analysis_run_id": "",
      "source_execution_run_id": "",
      "status": "VALIDATED|BLOCKED",
      "checks": [],
      "reporting_allowed": false,
      "baseline_recommendation_allowed": false,
      "created_at": "ISO-8601"
    }

CP4가 VALIDATED인 경우에만 최종 보고서 생성과 Baseline 권고를 허용합니다.

## 14. 공통 Check 구조

    {
      "rule_id": "CP2-TRACE-001",
      "severity": "CRITICAL|MAJOR|MINOR",
      "status": "PASS|FAIL|REVIEW|NOT_APPLICABLE|ERROR",
      "message": "",
      "expected": "",
      "actual": "",
      "evidence_refs": [],
      "recommended_action": ""
    }

규칙:

- FAIL과 ERROR를 같은 의미로 사용하지 않습니다.
- NOT_APPLICABLE은 PASS 분모에서 제외합니다.
- 의미 판단이 부족하면 PASS가 아니라 REVIEW입니다.
- Critical FAIL은 자동 진행을 차단합니다.

## 15. Handoff 규칙

| From | To | 필수 조건 |
|---|---|---|
| Input Validator | Agent 1 | 구조 검사 PASS |
| Agent 1 | CP1 | normalized Artifact 생성 |
| CP1 | Agent 2 | PASSED 또는 승인된 PARTIAL |
| Agent 2 | CP2 | TC Change Set 계약 PASS |
| CP2 | Agent 3 | SANDBOX_ELIGIBLE |
| Agent 3 | CP3 | 코드·Manifest·시험 결과 존재 |
| CP3 | Human Gate | PROMOTION_READY |
| Human Gate | Executor | APPROVED |
| Executor | Agent 4 | Restore 포함 실행 원본 |
| Agent 4 | CP4 | Summary와 단일 Source Run |
| CP4 | Final Report | VALIDATED |

## 16. 저장 구조

    runs/<run_id>/
    ├─ manifest.json
    ├─ input/
    │  ├─ change_request.raw.json
    │  ├─ change_request.normalized.json
    │  └─ baseline_manifest.json
    ├─ agent1/
    │  ├─ raw.json
    │  └─ normalized.json
    ├─ checkpoint1.json
    ├─ agent2/
    │  ├─ raw.json
    │  └─ tc_changeset.json
    ├─ checkpoint2.json
    ├─ agent3/
    │  ├─ raw.json
    │  ├─ automation_plan.json
    │  └─ candidate_manifest.json
    ├─ candidate-tests/
    ├─ checkpoint3.json
    ├─ trial-results/
    ├─ human_approval.json
    ├─ product-validation/
    ├─ agent4/
    │  └─ summary.json
    ├─ checkpoint4.json
    ├─ evidence/
    └─ final-report.json

Run 디렉터리는 append-only입니다. latest 포인터는 편의 기능이며 판정 SSOT가 아닙니다.

## 17. 계약 인수 조건

- 모든 Artifact는 유일한 Artifact ID, Run ID와 content hash를 가져야 합니다.
- 모델 원본과 정규화 결과가 별도 보존되어야 합니다.
- Checkpoint 미통과 Artifact가 다음 단계 입력이 되면 안 됩니다.
- Agent 2 기대결과와 Agent 3 Assertion 매핑이 100%여야 합니다.
- Agent 3 코드가 TC Snapshot 해시와 다르면 차단되어야 합니다.
- 사람 승인 없는 후보 코드가 Product Validation에 사용되면 안 됩니다.
- Agent 4는 단일 Source Run만 집계해야 합니다.
- CP4 BLOCKED이면 보고와 Baseline 권고를 생성하면 안 됩니다.
- Fixture Artifact는 LIVE로 표시되면 안 됩니다.
- 오류는 빈 결과나 PASS로 변환되면 안 됩니다.
