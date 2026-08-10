# 프로젝트 1 V2 문서 커버리지 감사

> 검토 기준: 중앙제어기 화면 소스, Playwright TC, Agent 1·2 Prompt, Checkpoint 2, 3-Tier 기준, Agent 4 코드

## 1. 구현·화면·테스트 구분

| 영역 | 현재 사실 | V2 처리 |
|---|---|---|
| Agent 1 입력창 | 자유 입력 UI 존재 | Live API 입력으로 연결 예정 |
| Jira·파일 연동 | 고정 텍스트를 채우는 Demo | 실제 연동 주장 금지 |
| Agent 1 분석 | 타이머·고정 로그 | 실제 모델 Adapter 필요 |
| Agent 2 TC | 고정 TC-21·22 | Agent 1 승인 Artifact 입력 필요 |
| Agent 3 화면 | 저장된 `tcData`를 시간차 표시 | 실제 코드 생성·격리 Pytest 필요 |
| Agent 4 화면 | 고정 `cicdStages` 표시 | 실제 Agent 4 JSON 표시 필요 |
| 실제 Playwright | 별도 Pytest에서 동작 | V2 Executor로 재사용 |
| 결과 분석 | Python 규칙 엔진 동작 | V2 Run 계약으로 확장 |

## 2. SRS 보완 결과

- 장비 ID·표시명과 초기 상태
- 장비 선택·Pending·Apply 분리
- 운전·풍량·온도 단위
- 복수 선택·상태 저장·초기화
- 게이트웨이·오류 주입·현장 리모컨
- 장치 카드·내부 상태·Register 정합성
- 운전 현황·QA 로그·QA Bridge
- 화면만 있거나 미완성인 권한·필터·공기청정 분리

## 3. Agent 계약 보완 결과

### Agent 1

- Level 1~3 충분성
- 확정·추정·정보 부족
- Control Point·테스트 가능·제외 범위
- 통합 위험·필수 불변 조건
- Proceed·Partial·Waiting·Blocked

### Agent 2

- 3-Tier·Risk·Source 추적성
- Initial State·Setup·Cleanup
- UI·Device·Negative·Unchanged Assertion
- Double-Assert 정책·독립 실행·자동화 수준
- 복수 제어 비대상 불변

### Agent 3

- 승인 TC Snapshot 해시
- 기대결과·Assertion 1:1 매핑
- Locator 근거·Sandbox
- 정상 반복·대표 오류·Restore
- 기술 수정 최대 1회

### Agent 4

- Analysis Run과 Source Run 분리
- 변경·회귀·Pipeline Fixture 구분
- 생성 오류와 실행 오류 분리
- Baseline 반영은 권고까지만 수행

## 4. 확인된 불일치·미완성

| 항목 | 확인 내용 | 처리 |
|---|---|---|
| 온도 하한 | 화면·3-Tier 16°C, 구현 15°C 허용 | `KNOWN_DEVIATION` |
| TC-TEMP-002 | 특정 18°C 제품 결함 분류 Fixture | Baseline 요구사항과 분리 |
| 복수 제어 | 비대상 장비 불변 Assertion 없음 | V2 CP2·CP3 필수 |
| 권한 | 함수·Overlay는 있지만 전환 버튼 없음 | `INCOMPLETE`, 제외 |
| 공기청정 | 기본 숨김, Demo 후 노출 | Baseline 제외 |
| HEAT·공기청정 상호배타 | Demo TC 문구만 있고 차단 코드 없음 | `DEMO_ONLY` |
| 로컬 오프라인 | 주석은 로컬 작동, 구현은 상태 변경 없이 반환 | 정책 확인 |
| Agent 3 모달 | 실제 Pytest가 아닌 타이머 | Live 증거 금지 |
| Agent 4 모달 | 실제 Python 실행이 아닌 타이머 | Live 증거 금지 |

## 5. 문서 추적성

| 질문 | 기준 문서 |
|---|---|
| V2 목적·범위 | `00_V2_DESIGN_OVERVIEW.md` |
| 현재 제품 기준 | `01_REVERSE_ENGINEERED_BASELINE_SRS.md` |
| 변경 입력 | `02_CHANGE_REQUEST_INPUT_CONTRACT.md` |
| Agent 입출력 | `03_AGENT_IO_CONTRACTS.md` |
| 차단·승인 | `04_CHECKPOINT_APPROVAL_POLICY.md` |
| 기존 프로젝트 누락 | 본 문서 |

## 6. 아직 문서화만 된 항목

- 실제 모델 API Adapter
- QA Manager 상태 머신
- JSON Schema·Pydantic 검증
- Agent 1→2→3 실제 Artifact 전달
- Playwright 도구 기반 화면 관찰
- 코드 후보 생성·격리 실행
- 최종 통합 승인 화면
- V2 Run Manifest·Dashboard

구현 전에는 V2를 완성 또는 Live Agent Pipeline이라고 표현하지 않는다.
