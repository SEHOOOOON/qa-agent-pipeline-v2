# Agent 1 → CP1 → Agent 2 → CP2 실제 실행 결과

- Run ID: **RUN-20260812-132412-687EC2**
- 실행 방식: OpenAI API를 사용한 Live Run
- 모델: **gpt-5.6-terra**
- 최종 결과: Agent 1·CP1 **PASS**, Agent 2·CP2 **PASS**
- Agent 2 산출물: 제품 기능 테스트케이스 후보 5건
- 재작업: Agent 1과 Agent 2 모두 첫 자동 검사 실패 후 피드백을 입력으로 받아 1회 재생성하여 통과

## 파일

- **request.json**: 사용자가 입력한 변경 요청
- **agent1_change_analysis.json**: Agent 1의 최종 변경 분석
- **checkpoint1.json**: CP1 규칙별 최종 판정
- **run_manifest.json**: Agent 1 실행 상태·모델·토큰·시도 이력
- **agent2_test_design.json**: Agent 2의 최종 제품 기능 TC 후보
- **checkpoint2.json**: CP2 규칙별 최종 판정
- **agent2_manifest.json**: Agent 2 실행 상태·모델·토큰·시도 이력

## 공개 범위

API 키는 실행 결과에 기록하지 않습니다. OpenAI 응답 식별자(response_id)도 공개 예시에서는 제거했습니다. 원본 실행 폴더의 중간 실패 산출물은 로컬 감사용으로만 유지하고, Git에는 최종 산출물과 시도별 PASS·FAIL·토큰 요약만 포함합니다.

## 해석 시 주의

Checkpoint 통과는 구조·근거·필수 검증 계층 등 구현된 자동 규칙을 충족했다는 뜻입니다. 자연어 의미의 완전성이나 TC 조합의 충분성을 보장하지 않으므로, 정식 QA 자산 등록 전 마지막 사람 승인이 필요합니다.
