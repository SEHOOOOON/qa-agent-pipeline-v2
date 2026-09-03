# Agent 1→4 Live Run — MED 풍량 표시와 승인 TC 재사용

이 폴더는 최신 로직 보완 뒤 실행한 `RUN-20260903-121213-4CCC7A`의 실제
모델·브라우저 결과를 GitHub에서 확인할 수 있도록 정리한 공개용 최소 증거
묶음입니다. 원본 Run은 `runs/`에 보존하며 Git에서 제외합니다.

## 실행 결과

- Agent 1: 첫 결과의 인수 조건 누락을 CP1이 차단한 뒤 1회 재작업, 최종 `PASS + CONTINUE`, 11,561 tokens
- Agent 2: 첫 시도 CP2 `PASS`, 신규 MED 후보 1건과 승인 HIGH 회귀 `TC-V2-001` 1건 분리, 10,622 tokens
- Agent 3: 첫 계획 CP3 `PASS`, 신규 후보 1건 시험 `PASS`, 자동화 제외 0건, 19,028 tokens
- 변경 검증: 신규 MED 후보, 환경 점검, 승인 HIGH 회귀가 모두 `PASSED`
- Agent 4: CP4 `PASS`, 검토 항목 0건, 최종 권고 `PASS`
- 전체 실제 모델 사용량: 41,211 tokens
- 외부 보고: Slack 1건·Notion 3건 `PREVIEW`, 실제 전송 0건

## 확인된 연결

Agent 2는 MED의 카드 표시 `중풍`과 내부 `fanSpeed=MED`를 신규 후보로
만들었습니다. 변경되지 않은 HIGH의 카드 표시 `강풍`과 내부
`fanSpeed=HIGH`는 같은 내용을 다시 만들지 않고, 사람이 승인해 등록한
`TC-V2-001`을 관련 기존 회귀로 선택했습니다.

Agent 3가 만든 신규 후보는 UI와 내부 상태를 같은 적용 시점에 확인하고,
시험 뒤 LOW 상태로 복원했습니다. 검증 실행은 Agent 3 시험 증거를 해시로
확인해 재사용하고, 승인 Registry와 Run 시점 카탈로그의 해시가 일치하는
`TC-V2-001`을 별도로 실행했습니다.

## 사람에게 남은 판단

자동 검토 Finding은 없습니다. 다만 MED 표시 규칙을 기준 SRS에 반영하고
신규 후보를 공식 TC·자동화 자산으로 등록할지는 사람의 별도 승인 대상입니다.
이번 실행에서는 SRS·공식 자산을 변경하지 않았습니다.

[사람 최종 검토 공개본](사람_최종_검토_공개본.md)에서 SRS 개정 전·후 문구와
승인란을 확인할 수 있습니다.

## 공개 범위

- `public_result.json`: 단계별 상태·사용량·실행 결과와 원본 SHA-256
- `external_reporting_summary.json`: Slack·Notion 미리보기 상태와 원본 보고 SHA-256
- `evidence/TC-CAND-001/trial-observation.txt`: 신규 후보와 승인 회귀의 핵심 관찰 요약
- `public_manifest.json`: 이 공개 묶음 파일의 SHA-256

Screenshot·Trace·전체 모델 산출물은 로컬 원본 Run에만 보존합니다. 이
공개본에는 API 키, Slack Webhook, Notion 자격정보, 로컬 절대경로를 포함하지
않습니다.
