# Checkpoint와 사람 승인 정책

## 1. 기본 원칙

TC와 코드 승인 책임은 필요하지만 정상 흐름에서 사람에게 두 번 멈춰 묻지 않는다.

> Checkpoint 2를 통과한 TC 후보는 격리된 코드 후보 생성·시험까지 자동 진행한다. 제품 판정 또는 Baseline 반영 전 사람이 TC·코드·실행 증거를 한 번에 승인한다.

자동 진행 권한과 정식 승인 권한을 분리한다.

## 2. 상태 흐름

```text
Agent 1
→ CP1: AUTO_CONTINUE | REVIEW | BLOCKED
→ Agent 2
→ CP2: SANDBOX_ELIGIBLE | REVIEW | BLOCKED
→ Agent 3 후보 생성
→ CP3 정적 검사·격리 실행
→ PROMOTION_READY | REVISION_REQUIRED | BLOCKED
→ Human Promotion Gate
→ APPROVED | REJECTED | REVISION_REQUESTED
```

`SANDBOX_ELIGIBLE`은 정식 승인 상태가 아니라 원본을 바꾸지 않는 격리 환경에서 코드 후보를 생성해 볼 수 있다는 뜻이다.

## 3. Checkpoint 1

### 자동 차단

- 필수 필드·Schema 오류
- 존재하지 않는 Requirement ID
- 변경 전 값이 Baseline에 없음
- 근거 없는 확정 정보
- 정보 부족인데 전체 진행
- 승인·제외 범위 충돌

### 사람 검토

- 의미상 충돌 가능성
- 간접 영향 타당성 불확실
- 핵심 기대결과 부족
- P0·안전 관련 변경

## 4. Checkpoint 2

### 9대 기준

1. 기대결과 모호성
2. Double-Assert 또는 예외 사유
3. 정보 부족 분리
4. 추측·환각
5. Requirement·Source·QA Criterion 추적성
6. 자동화 가능한 구체값
7. 독립 실행 가능성
8. 통합 TC 비대상 불변 검증
9. 중복 TC

### 자동 차단

- Requirement 연결 없음
- 사전조건·행동·기대결과 누락
- 추정 정보를 기대결과로 사용
- Double-Assert 누락과 사유 없음
- 중복 TC 또는 Cleanup·Restore 없음
- 물리 삭제 요청

모든 구조 규칙을 통과하고 중대한 의미 경고가 없으면 `SANDBOX_ELIGIBLE`이다.

## 5. Checkpoint 3

### 평가 축

1. 실행 가능성: 문법, Locator, 시간 제한, Restore, 증거
2. 의도 충실성: 모든 사전조건·행동·기대결과와 Assertion 연결
3. 관찰 안정성·검출성: 정상 반복, 상태 격리, 대표 오류 검출

### 자동 차단

- Assertion 삭제·변경
- TC Snapshot 해시 불일치
- 금지 API·Shell·외부 URL·원본 수정
- 실제값을 기대값으로 재사용
- 실패 무시·무조건 통과
- Restore 실패
- 대표 오류를 검출하지 못함

## 6. Checkpoint 4

- 동일 Source Run ID인지 확인
- JSON·HTML 결과의 TC ID·상태·건수 대조
- 변경·회귀·Pipeline Fixture 구분
- 실패마다 분류와 증거 연결
- Restore 실패 이후 결과 무효 처리
- 자동화 오류를 제품 결함으로 분류하지 않음
- Fixture와 Live 결과 구분

정합성이 깨지면 보고·외부 전송·Baseline 권고를 차단한다.

## 7. 최종 통합 승인

사람은 한 화면에서 다음을 확인한다.

- 원본 변경 요청
- Agent 1 분석·제외 범위
- Agent 2 TC 변경안
- Agent 3 코드 Diff
- 기대결과·Assertion 매핑
- 정상 반복·대표 오류 결과
- Core Regression
- Agent 4 분류·권고

판정:

- `APPROVED`: Baseline 반영 후보 승인
- `REJECTED`: 후보 폐기, 기존 Baseline 유지
- `REVISION_REQUESTED`: 지정 단계로 최대 1회 반환

## 8. 중간 승인 필수 조건

- 핵심 기대결과가 모호함
- P0·안전·권한·데이터 삭제 관련 변경
- Requirement·TC 비활성화 제안
- Agent 간 판단 충돌
- 의미 판단을 규칙만으로 확정 불가
- 오류 프로필 설계가 불확실함

## 9. 재작업 정책

기존 V1 Checkpoint 2 Prompt는 최대 2회 재작성을 정의한다. V2 MVP는 비용·범위를 통제하기 위해 Agent별 최대 1회로 제한한다.

- 1회 후 Critical 위반: `HUMAN_REVIEW` 또는 `BLOCKED`
- 이미 통과한 Artifact 임의 변경 금지
- 원본·수정본·Diff·사유·Model 정보 보존
- 기대결과·Assertion 변경 감지 시 자동 진행 금지

## 10. Baseline 보호

- 승인 전 SRS·TC·승인 자동화 원본을 수정하지 않는다.
- `DELETED`도 즉시 삭제하지 않고 `DEPRECATION_PROPOSED`로 기록한다.
- 승인 시 새 버전과 Patch를 만들고 기존 버전을 보존한다.
- 승인자·시각·입력 해시를 감사 기록으로 남긴다.

## 11. 포트폴리오 표현

권장:

> Agent 산출물이 품질 게이트를 통과하면 격리 검증까지 자동 진행되며, 제품 판정과 Baseline 반영 전 QA가 TC·코드·반복 실행·오류 검출 증거를 한 번에 검토합니다.

금지:

- 완전 자율 멀티 에이전트 팀
- 사람 없이 자동 승인
- 생성 코드 신뢰성 보장
- Checkpoint의 자연어 의미 완전 판정
