# Agent 1 → CP1 → Agent 2 → CP2 v2.2 실제 실행 결과

- Run ID: **RUN-20260813-125229-31EB5F**
- 실행 방식: OpenAI API를 사용한 Live Run
- 모델: **gpt-5.6-terra**
- 최종 결과: Agent 1·CP1 **PASS + CONTINUE**, Agent 2·CP2 **PASS**
- Agent 2 산출물: 제품 기능 테스트케이스 후보 **12건**
- Agent 1: 첫 시도 PASS
- Agent 2: 첫 자동 검사 FAIL 후 피드백 기반 1회 재생성하여 PASS

## 이번 Run에서 확인한 동작

- 변경 후 `AUTO 18~30°C` 범위와 요청의 인수 조건 6개가 Agent 1 확정 조건으로 전달됐습니다.
- Agent 2가 AUTO 하한·상한·18°C 미만 차단을 CENTRAL·LOCAL 경로에 각각 설계했습니다.
- COOL·HEAT 16~30°C, FAN·DRY 온도 설정 비활성화를 관련 회귀 후보로 분리했습니다.
- CP2가 1차 결과의 중복 ID, FAN·DRY 이중 검증 누락과 구조화 시험 데이터 누락을 찾아 재작업시켰습니다.
- SRS 후속 개정과 Toast 정확한 문구 미지정은 `coverage_notes`로 남기되 후속 실행을 차단하지 않았습니다.

## 파일

- **request.json**: 사용자가 입력한 변경 요청
- **srs_snapshot.md**: Run 시작 시 고정한 제품 SRS
- **agent1_change_analysis.json**: Agent 1의 최종 변경 분석
- **checkpoint1.json**: CP1 규칙별 최종 판정
- **run_manifest.json**: Agent 1 실행 상태·모델·토큰·시도 및 SHA-256
- **agent2_test_design_attempt_1.json**, **checkpoint2_attempt_1.json**: CP2 재작업 전 결과와 반려 근거
- **agent2_test_design.json**: Agent 2의 최종 제품 기능 TC 후보
- **checkpoint2.json**: CP2 규칙별 최종 판정
- **agent2_manifest.json**: Agent 2 실행 상태·모델·토큰·시도 및 SHA-256 체인

## 공개 범위

API 키와 OpenAI 응답 식별자는 산출물에 저장하지 않습니다. 공개 파일은 로컬 Run에서 생성된 JSON과 SRS 스냅샷을 그대로 복사해 Manifest 해시를 유지했습니다.

## 해석 시 주의

Checkpoint 통과는 현재 구현된 구조·근거·추적·경로 규칙을 충족했다는 뜻입니다. 자연어 의미의 완전성이나 모든 위험 조합을 보장하지 않으며, Agent 3 이후 자동화 코드 생성·격리 실행은 아직 구현 전입니다.