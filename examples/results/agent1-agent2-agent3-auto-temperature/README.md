# Agent 1→3 Live Run — AUTO 온도 하한 변경

이 폴더는 `RUN-20260813-125229-31EB5F`의 Agent 1·2 공개 입력 체인에
`agent3-3.4` 실제 모델 계획, CP3, 결정론적 Playwright 후보와 Candidate Trial
증거를 연결한 공개 Run입니다.

## 결과

- Agent 1: `PASS + CONTINUE`
- Agent 2: 최종 CP2 `PASS`, 제품 기능 TC 후보 12건
- Agent 3 대상: `TC-CAND-003`
- Agent 3 모델: `gpt-5.6-terra`
- Agent 3 계획: 첫 시도 CP3 `PASS`, 재호출 없음
- 모델 사용량: input 2,533 / output 594 / total 3,127 tokens
- Candidate 상태: `PRODUCT_MISMATCH_DETECTED`
- Trial: `PRODUCT_MISMATCH_CANDIDATE`
- Trial 증거: Screenshot·Trace 생성 완료

Trial은 변경 요청의 AUTO 하한 18°C 기대와 달리 다음 상태를 관찰했습니다.

- ER-005: 사용자 화면 설정 온도 `17.0°C`
- ER-006: 내부 `setTemp=17`
- ER-007: 차단 안내 대신 성공 적용 Toast 표시

이 결과는 기대 결과와 다른 관찰 후보이며, 그 자체로 최종 제품 결함 확정을
뜻하지 않습니다.

## 계약과 보안 확인

- `SELECT_DEVICE value=1`, `TOAST_BLOCKING`, Action·Assertion Selector 계약 준수
- Agent 1→2→3 입력·출력과 Project1 대상 SHA-256 일치
- Trial 전후 Project1 대상 파일 불변
- API Preview에 로컬 절대경로·HTML 원문·Screenshot·Trace·API 키 없음
- stdout·stderr의 로컬 경로 마스킹
- Trace ZIP 내부 사용자 홈·대상 파일·Trial Workspace 경로 치환
- 공개 텍스트 산출물에서 비밀정보와 로컬 절대경로 패턴 미탐지

## 주요 파일

- `request.json`, `srs_snapshot.md`: 변경 요청과 제품 기준
- `agent1_change_analysis.json`, `checkpoint1.json`, `run_manifest.json`
- `agent2_test_design.json`, `checkpoint2.json`, `agent2_manifest.json`
- `agent3_eligibility.json`, `agent3_ui_observation.json`
- `agent3_model_input_preview.json`, `agent3_automation_plan.json`
- `candidates/test_tc_cand_003.py`, `checkpoint3.json`
- `agent3_trial.json`, `agent3_manifest.json`
- `evidence/TC-CAND-003/`: stdout·stderr·Screenshot·Trace
