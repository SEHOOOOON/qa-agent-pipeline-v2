# Agent 1→4 Live Run — 잠금 설정 시 온도 조작 비활성화

이 폴더는 `RUN-20260827-114925-507176`의 실제 모델·브라우저 실행 결과를
GitHub에서 확인할 수 있도록 정리한 공개용 최소 증거 묶음입니다. 원본 Run은
`runs/`에 보존하며 Git에서 제외합니다.

## 실행 결과

- Agent 1: `REVIEW + CONTINUE`, 6,419 tokens
- Agent 2: CP2 `PASS`, 변경분 후보 1건과 관련 기존 회귀 2건 분리
- Agent 3: CP3 `PASS`, 후보 1건 실행, 자동화 제외 0건, 18,589 tokens
- 변경 검증: 제품 결과 3건, 환경 점검 1건
- Agent 4: CP4 `PASS`, 최종 권고 `HUMAN_REVIEW`
- 전체 결과: `PASSED` 3건, `ASSERTION_FAILED` 1건
- 외부 보고: Slack 1건·Notion 4건 실제 `SENT`

## 사람이 판단할 항목

요구사항은 잠금 설정 시 온도 내림·올림 조작이 비활성화되는 것입니다. 실행에서는
내부 `locked=true`가 확인됐지만 두 온도 버튼은 모두 `enabled=True`였습니다.
Agent 4는 이를 제품 결함으로 확정하지 않고 `PRODUCT_MISMATCH_CANDIDATE`로
분류했습니다. 최종 사람 판정은 아직 `PENDING`입니다.

[사람 최종 검토 공개본](사람_최종_검토_공개본.md)에서 기대 결과, 실제 관찰,
판정 선택지와 후속 조치란을 확인할 수 있습니다.

## 공개 범위

- `public_result.json`: 단계별 상태·사용량·결과와 원본 SHA-256
- `external_reporting_summary.json`: 실제 전송 상태와 원본 전송 증거 SHA-256
- `evidence/TC-CAND-001/trial-observation.txt`: 핵심 Assertion 관찰 요약
- `public_manifest.json`: 이 공개 묶음 파일의 SHA-256

Screenshot·Trace·전체 모델 산출물은 로컬 원본 Run에만 보존합니다. 이 공개본에는
API 키, Slack Webhook, Notion 자격정보, 로컬 절대경로를 포함하지 않습니다.
