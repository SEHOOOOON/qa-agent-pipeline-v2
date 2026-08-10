# 변경 요청 입력 및 접수 계약

## 문서 통제

| 항목 | 값 |
|---|---|
| 문서 ID | ICD-CHANGE-001 |
| 버전 | 0.2 |
| 상태 | REVIEW_READY |
| 소유자 | QA |
| 소비자 | QA Manager, Agent 1, Checkpoint 1 |
| 관련 SRS | SRS-VCCS-BL-001 |

## 1. 목적

본 계약은 사용자의 변경 요청을 원문 그대로 보존하면서 Agent 1이 분석할 수 있는 입력으로 접수하기 위한 형식, 검증, 충분성 판정과 오류 처리를 정의합니다.

특정 예시 요구사항을 코드·Prompt·기본값에 고정하지 않습니다. 샘플은 Fixture일 뿐이며 실제 입력 결과를 결정하지 않습니다.

## 2. 적용 범위

### 포함

- 대시보드 직접 입력
- 로컬 JSON 파일
- 로컬 API 요청
- SRS·이슈·이메일·회의 합의의 출처 표시
- 텍스트 첨부와 허용 파일의 해시
- Baseline 버전·해시 결합
- 정보 충분성 판정
- 추가 질문과 부분 진행

### 제외

- Jira·Notion·Slack 실제 API 연동
- 이미지 OCR과 대용량 문서 파싱
- 여러 변경 요청의 병렬 병합
- 운영 시스템의 승인 Workflow
- 입력 원문 자동 수정

## 3. 역할과 책임

| 역할 | 책임 |
|---|---|
| 요청자 | 변경 원문, 목적, 대상 범위와 알려진 인수 근거 제공 |
| QA Manager | 형식·해시·중복·보안 검사, Baseline Snapshot 연결 |
| Agent 1 | 의미 분석, 확정·추정·정보 부족 분리 |
| Checkpoint 1 | Baseline 근거와 진행 가능 범위 검증 |
| QA | 핵심 기대결과·안전·삭제·권한 관련 모호성 결정 |

QA Manager와 Agent는 요청자의 원문을 덮어쓰지 않습니다. 정규화·요약·질문은 별도 Artifact로 저장합니다.

## 4. 입력 채널

| 채널 | 사용 | 제약 |
|---|---|---|
| Dashboard | MVP 기본 | 텍스트와 메타데이터 입력 |
| JSON File | 테스트·재현 | UTF-8, 허용 Schema 버전 |
| Local API | 자동 실행 | localhost, 인증·CORS 정책 별도 |
| 외부 Issue 연동 | 제외 | source_reference만 기록 |

모든 채널은 동일한 Canonical Change Request 구조로 정규화합니다.

## 5. Canonical Change Request

    {
      "schema_version": "change-request.v1",
      "change_id": "CHG-YYYYMMDD-001",
      "title": "변경 제목",
      "description": "요청자가 입력한 변경 요구사항 원문",
      "business_reason": "변경 목적 또는 배경",
      "source_type": "SRS|ISSUE|EMAIL|MEETING|MANUAL",
      "source_reference": "원본 문서 또는 이슈 식별자",
      "priority": "P0|P1|P2|P3|UNASSESSED",
      "requested_at": "ISO-8601",
      "requested_by": {
        "name": "",
        "role": ""
      },
      "target_scope": [],
      "out_of_scope": [],
      "known_acceptance_criteria": [],
      "known_constraints": [],
      "risk_notes": [],
      "additional_context": [],
      "attachments": [
        {
          "artifact_id": "ART-IN-...",
          "file_name": "",
          "media_type": "text/plain",
          "sha256": "sha256:...",
          "description": ""
        }
      ]
    }

## 6. 필드 정의

| 필드 | 필수 | 규칙 | 오류 처리 |
|---|---:|---|---|
| schema_version | Y | change-request.v1 | 미지원 버전 BLOCKED |
| change_id | Y | CHG-YYYYMMDD-NNN, Run 내 유일 | 형식·중복 오류 BLOCKED |
| title | Y | 공백 제외 5~120자 | 누락 BLOCKED |
| description | Y | 원문 보존, 공백 제외 최소 10자 | 누락 BLOCKED |
| business_reason | N | 요청 목적, 모르면 빈 값 허용 | Agent 1 Gap 후보 |
| source_type | Y | 허용 Enum | 오류 BLOCKED |
| source_reference | 조건부 | SRS·ISSUE·EMAIL이면 필수 | 누락 REVIEW |
| priority | Y | 허용 Enum | 미평가 시 UNASSESSED |
| requested_at | Y | timezone 포함 ISO-8601 | 오류 BLOCKED |
| requested_by.name | Y | 빈 값 금지 | 누락 REVIEW |
| requested_by.role | Y | 자유 문자열, 빈 값 금지 | 누락 REVIEW |
| target_scope | N | Requirement·기능·장비 후보 | 미지정 시 Agent 1 분석 |
| out_of_scope | N | 이번 변경에서 제외할 범위 | target 충돌 시 BLOCKED |
| known_acceptance_criteria | N | 요청자가 아는 결과만 작성 | 근거 없는 보완 금지 |
| known_constraints | N | 일정·환경·기술 제약 | Agent 1 전달 |
| risk_notes | N | 안전·권한·데이터 위험 | P0 검토 입력 |
| additional_context | N | 원문과 구분된 보조 정보 | 사실 상태 분리 |
| attachments | N | Artifact ID·해시·허용 형식 | 경로·해시 오류 BLOCKED |

## 7. QA Manager 실행 Envelope

    {
      "run_id": "RUN-YYYYMMDD-HHMMSS-XXXXXX",
      "mode": "FIXTURE|LIVE",
      "sut_executed": false,
      "model_invoked": false,
      "baseline": {
        "document_id": "SRS-VCCS-BL-001",
        "version": "0.2",
        "approval_status": "CANDIDATE|APPROVED",
        "source_commit": "",
        "sha256": "sha256:..."
      },
      "change_request_artifact_id": "ART-IN-...",
      "change_request_hash": "sha256:...",
      "created_at": "ISO-8601",
      "max_agent_revision": 1,
      "approval_policy": "RISK_BASED_PROMOTION_GATE"
    }

Envelope은 사용자 입력과 분리합니다. 사용자가 작성하지 않은 실행 정보, 해시와 모드를 QA Manager가 추가합니다.

## 8. 접수 전 검증

### 8.1 구조 검사

- 필수 필드 존재
- 문자열·배열·객체 타입
- 허용 Enum과 ID 형식
- 배열 내 빈 항목 제거
- 날짜·시간 형식
- Change ID 중복
- 첨부 Artifact ID 중복

### 8.2 Baseline 검사

- Baseline 문서와 버전 존재
- 파일 해시 일치
- 승인 상태 기록
- target_scope의 Requirement ID 존재 여부
- 변경 전 값이 Baseline에 존재하는지 여부
- Baseline의 TBD·KNOWN_DEVIATION 포함 여부

CANDIDATE Baseline으로 실행할 수는 있지만 결과는 Baseline 승인 권고가 아니라 설계 검증 용도로 표시해야 합니다.

### 8.3 범위 검사

- target_scope와 out_of_scope가 겹치지 않아야 합니다.
- 전체 장비·전체 기능 같은 광범위 표현은 경고합니다.
- 운영 장비·외부 URL·실데이터 요청은 차단합니다.
- MODIFIED MVP에서 ADDED·DELETED가 포함되면 REVIEW로 보냅니다.

### 8.4 보안 검사

- API Key, Token, 비밀번호와 개인식별정보를 Redaction합니다.
- 첨부 경로는 서버 허용 디렉터리의 Artifact ID로만 참조합니다.
- 절대 경로와 상위 경로 이동 문자열을 API 입력으로 허용하지 않습니다.
- 실행 Prompt에 비밀 환경변수를 포함하지 않습니다.
- 입력 원문과 Redaction 사본을 접근 권한에 따라 분리합니다.

## 9. 정보 충분성 모델

Agent 1은 구조 검사를 통과한 입력을 세 수준으로 평가합니다.

| 수준 | 기준 | 기본 처리 |
|---|---|---|
| LEVEL_1 | 대상·변경 내용·기대결과·범위가 명확 | PROCEED 후보 |
| LEVEL_2 | 일부는 확정 가능하나 제한·예외가 부족 | PARTIAL_PROCEED 또는 질문 |
| LEVEL_3 | 대상·변경 전후·핵심 기대결과를 결정 불가 | WAITING_FOR_USER |

형식이 완전하다고 의미가 충분한 것은 아닙니다. Schema PASS는 Agent 1 실행 자격만 의미합니다.

## 10. 진행 상태

### PROCEED

다음 조건을 모두 충족할 때 권고합니다.

- 대상 Baseline Requirement를 식별할 수 있습니다.
- 변경 전후 값 또는 동작을 구분할 수 있습니다.
- 테스트 가능한 결과를 도출할 근거가 있습니다.
- Critical 정보 부족이 없습니다.

### PARTIAL_PROCEED

확정 가능한 범위와 모호한 범위를 분리할 수 있을 때 사용합니다.

- passed_scope와 excluded_scope가 겹치면 안 됩니다.
- 제외 사유와 질문을 남겨야 합니다.
- Agent 2는 passed_scope에 대해서만 TC를 생성합니다.

### WAITING_FOR_USER

답변 없이는 제품 기대결과를 확정할 수 없을 때 사용합니다.

- 질문은 한 번에 이해 가능한 단일 쟁점으로 작성합니다.
- 질문 전까지 기존 Baseline을 변경하지 않습니다.
- 답변은 원문과 별도 Artifact로 저장합니다.
- 답변 후 같은 Run 또는 명시된 재개 Run으로 이어갑니다.

### BLOCKED

다음에 해당하면 자동 진행하지 않습니다.

- Baseline 또는 입력 해시 불일치
- 존재하지 않는 Requirement를 확정 대상으로 지정
- target_scope와 out_of_scope 충돌
- 운영 시스템·비밀값·위험한 작업 요청
- 승인 권한 없는 Baseline 직접 삭제·덮어쓰기
- 지원하지 않는 변경 유형을 강제 실행

## 11. 추가 질문 계약

질문은 다음 항목을 가져야 합니다.

    {
      "question_id": "Q-001",
      "related_change_item_id": "CI-001",
      "reason": "왜 답변이 필요한지",
      "question": "한 번에 하나의 판단을 요구하는 질문",
      "answer_type": "CHOICE|TEXT|NUMBER|BOOLEAN",
      "options": [],
      "blocking": true,
      "default_assumption": null
    }

규칙:

- 기본 가정으로 질문을 자동 통과시키지 않습니다.
- 선택지는 Baseline과 입력 근거에서 도출합니다.
- 답변하지 않은 항목을 confirmed_fact로 승격하지 않습니다.
- 질문과 답변은 최종 보고서에 포함합니다.

## 12. 정규화 규칙

QA Manager는 다음 기계적 정규화만 수행할 수 있습니다.

- 선행·후행 공백 정리
- 빈 배열 항목 제거
- Enum 대소문자 통일
- 날짜를 ISO-8601로 변환
- 파일을 Artifact ID로 치환
- 비밀값 Redaction

다음 의미 변경은 금지합니다.

- 경계값 자동 보정
- 동의어를 공식 Requirement로 자동 매핑
- 누락된 기대결과 생성
- 사용자 원문 요약으로 원문 대체
- 변경 유형 임의 확정

## 13. 오류 코드

| 코드 | 의미 | 상태 |
|---|---|---|
| IN-001 | 필수 필드 누락 | BLOCKED |
| IN-002 | Schema 버전 미지원 | BLOCKED |
| IN-003 | Change ID 중복 | BLOCKED |
| IN-004 | Baseline 없음 또는 해시 불일치 | BLOCKED |
| IN-005 | 범위 충돌 | BLOCKED |
| IN-006 | 첨부 해시·경로 오류 | BLOCKED |
| IN-007 | 비밀값 탐지 | REDACTED 또는 BLOCKED |
| IN-008 | 핵심 기대결과 부족 | WAITING_FOR_USER |
| IN-009 | 일부 범위만 확정 가능 | PARTIAL_PROCEED |
| IN-010 | MVP 미지원 변경 유형 | HUMAN_REVIEW |

## 14. 감사 기록

입력 접수 시 다음을 보존합니다.

- 수신 시각과 채널
- 사용자 원문 Artifact
- 정규화 결과 Artifact
- Redaction 기록
- Baseline 버전·커밋·해시
- 구조 검사 결과
- 충분성 판정과 질문
- 사람 답변과 결정
- 최종 입력 해시

## 15. 입력 계약 인수 조건

- 같은 원문과 Baseline은 동일한 입력 해시를 생성해야 합니다.
- 입력 원문은 정규화 과정에서 의미가 변경되지 않아야 합니다.
- 필수 필드 오류는 모델 호출 전에 차단되어야 합니다.
- target_scope와 out_of_scope 충돌은 모델 호출 전에 차단되어야 합니다.
- 비밀값이 모델 Prompt와 Dashboard에 노출되지 않아야 합니다.
- PARTIAL_PROCEED는 진행·제외 범위를 분리해야 합니다.
- WAITING_FOR_USER는 답변 전 Agent 2를 실행하지 않아야 합니다.
- FIXTURE와 LIVE 모드가 Run Manifest에 기록되어야 합니다.

## 16. 변경 입력 금지 원칙

- 입력을 대표 요구사항으로 자동 대체하지 않습니다.
- 특정 온도·모드·장비 요구사항을 기본 시나리오로 고정하지 않습니다.
- 정보 부족을 모델의 일반 지식으로 보완하지 않습니다.
- Agent가 Baseline 원본을 직접 수정하지 않습니다.
- Fixture 응답을 Live 결과로 표시하지 않습니다.
- 승인되지 않은 사용자 답변을 공식 Requirement로 승격하지 않습니다.
