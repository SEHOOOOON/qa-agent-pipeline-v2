# 변경 요청 입력 계약

> 특정 변경 요구사항을 코드·Prompt·핵심 설계에 고정하지 않는다.

## 1. 입력 채널

- 대시보드 입력
- JSON 파일 입력
- 로컬 API 요청

샘플 요구사항은 Fixture로 둘 수 있지만 고정 결과를 결정해서는 안 된다.

## 2. 사용자 입력

```json
{
  "schema_version": "change-request.v1",
  "change_id": "CHG-YYYYMMDD-001",
  "title": "변경 제목",
  "description": "사용자가 입력한 변경 요구사항 원문",
  "source_type": "SRS|JIRA|EMAIL|MANUAL",
  "source_reference": "원본 문서 또는 이슈 식별자",
  "priority": "P0|P1|P2|P3",
  "requested_at": "ISO-8601",
  "requested_by": "사용자 또는 조직 역할",
  "target_scope": [],
  "out_of_scope": [],
  "acceptance_evidence": [],
  "additional_context": [],
  "attachments": [
    {
      "artifact_id": "",
      "file_name": "",
      "media_type": "",
      "sha256": ""
    }
  ]
}
```

## 3. 실행 Envelope

사용자 원문은 수정하지 않고 QA Manager가 별도 실행 정보를 추가한다.

```json
{
  "run_id": "RUN-...",
  "mode": "FIXTURE|LIVE",
  "baseline_version": "V1.0",
  "baseline_hash": "sha256:...",
  "change_request_hash": "sha256:...",
  "created_at": "ISO-8601",
  "max_agent_revision": 1,
  "approval_policy": "RISK_BASED_SINGLE_PROMOTION_GATE"
}
```

## 4. 모델 호출 전 검사

- 필수 필드와 타입
- 빈 설명 차단
- Schema 버전·Enum
- Change ID 형식과 중복
- Baseline 버전·해시
- `target_scope`와 `out_of_scope` 충돌
- 첨부 Artifact ID·해시·허용 경로
- 비밀값·API Key Redaction
- 입력 원문과 저장본 해시

## 5. 정보 충분성

- 형식이 맞으면 Agent 1 분석을 시작한다.
- 핵심 기대결과가 없으면 `WAITING_FOR_USER`를 권고한다.
- 확정 가능한 일부 범위가 있으면 `PARTIAL_PROCEED`로 분리한다.
- 정보 부족을 특정 샘플 요구사항으로 대체하지 않는다.

## 6. 금지 원칙

- 입력을 대표 요구사항으로 자동 대체하지 않는다.
- 정보 부족을 임의 기대결과로 보완하지 않는다.
- Agent가 Baseline 원본을 직접 수정하지 않는다.
- Fixture 결과를 Live 결과로 표시하지 않는다.
