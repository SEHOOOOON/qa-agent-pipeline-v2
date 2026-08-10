# Project 1 V2 설계 개요

> 상태: 설계 초안  
> 범위: 문서 계약 정의. AI API·오케스트레이터·코드 생성기는 아직 구현되지 않았다.

## 1. 프로젝트 정의

프로젝트 1 V2는 운영 중인 가상 중앙제어 시스템의 승인된 QA 자산을 기준으로 변경 요청을 분석하고, 제품 기능 테스트케이스와 Playwright 자동화 코드 후보를 생성·검증하는 **요구사항 변경 기반 Governed Agentic QA Pipeline**이다.

AI가 매 회귀 실행마다 모든 TC를 다시 만드는 구조가 아니다. 변경 요청이 접수된 시점에만 후보 산출물을 만들고, 품질 게이트와 사람의 승인을 통과한 자산을 Baseline 후보로 제안한다. 일반 회귀 실행은 승인된 고정 자동화를 사용한다.

## 2. V1과 V2의 차이

| 구분 | 현재 V1 | 목표 V2 |
|---|---|---|
| Agent 1 | Prompt·고정 분석 Demo | 실제 모델이 Baseline과 변경 요청 분석 |
| Agent 2 | Prompt·고정 TC Demo | Agent 1 승인 Artifact로 TC Change Set 생성 |
| Agent 3 | 사람이 작성한 Playwright 실행 | 승인 TC로 코드 후보 생성·시험 |
| Agent 4 | 결정론적 Python 분석기 | 현재 구조 유지 후 V2 Run 계약 수용 |
| Agent 인계 | 화면상 단계 표현 | JSON Artifact의 실제 자동 전달 |
| 입력 영향 | 고정 시연 | 사용자 입력에 따라 산출물 변경 |
| 실행 구분 | 일부 Demo 표기 | Fixture / Live / Regression 전 구간 표시 |

## 3. 세 가지 실행 Lane

### Change Authoring

```text
Baseline + Change Request
→ Agent 1 변경 분석
→ Checkpoint 1
→ Agent 2 TC Change Set
→ Checkpoint 2
→ Agent 3 자동화 코드 후보
→ Checkpoint 3 및 격리 실행
→ 사람의 최종 통합 승인
→ Baseline 반영 권고
```

### Regression

승인된 Baseline 자동화만 결정론적으로 실행한다. 모델 API를 호출하거나 TC·Assertion을 다시 생성하지 않는다.

```text
Approved Automation
→ Pytest / Playwright
→ Agent 4 규칙 기반 분석
→ Checkpoint 4
→ PASS / HOLD / HUMAN_REVIEW
```

### Offline Agent Evaluation

프로젝트 2에서 동일 입력으로 Agent 1·2·3을 반복 호출해 규칙 준수, 환각, 결과 변동, 비용과 지연을 평가한다. 제품 검증 Run과 섞지 않는다.

## 4. 역할과 권한

### QA Manager

LLM이 아니라 Python 상태 머신으로 구현한다. 단계 실행, Artifact 전달, 입력·출력 해시, 재작업 횟수와 상태 전이를 관리한다.

### Agent 1 — Change Analyst

승인된 Baseline SRS와 변경 요청을 비교한다. TC나 코드는 작성하지 않는다.

### Agent 2 — Test Designer

Checkpoint 1을 통과한 범위와 기존 TC를 바탕으로 제품 기능 TC Change Set을 만든다. 자동화 코드는 작성하지 않는다.

### Agent 3 — Automation Engineer

Checkpoint 2를 통과한 TC의 목적과 기대결과를 바꾸지 않고, GPT와 Playwright 도구를 사용해 Playwright 코드 후보를 작성한다.

### Agent 4 — Result Analysis Engine

현재 V1처럼 결정론적 Python 규칙으로 실행 결과를 분류하고 보고한다. 생성형 모델이 연결되기 전까지 AI Agent라고 주장하지 않는다.

## 5. 현재 프로젝트에서 재사용할 자산

- 16대 가상 장비와 중앙제어 화면
- Pending 상태를 구성하고 `적용`에서 실제 상태를 변경하는 제어 흐름
- 운전·모드·온도·풍량·잠금·오류·복수 제어
- 장치 카드, H/W Register View, `window.__vccs` QA Bridge
- 기존 Pytest·Playwright 기능 테스트와 Pipeline Control Fixture
- 결과 JSON·HTML Report·Agent 4 결정론적 분류

## 6. 화면 Demo와 Live 실행의 경계

현재 `virtual-controller.html`의 Agent 1~4 모달은 Workflow Demo이다. Agent 1·2 결과와 Agent 3·4 진행 화면은 JavaScript에 저장된 데이터와 타이머로 표시된다.

V2 Live 화면은 서버가 저장한 Run Manifest와 단계별 Artifact만 표시하고 다음 값을 노출한다.

- `FIXTURE` 또는 `LIVE`
- 실제 모델 호출 여부
- 실제 Playwright 실행 여부
- Run ID와 실행 시각
- Agent·Prompt·Model 버전
- 입력·출력 Artifact ID와 해시

## 7. MVP 종료선

- Baseline SRS와 기존 TC가 실제 입력이다.
- 사용자가 입력한 MODIFIED 변경 요청 한 건을 처리한다.
- Agent 1·2·3이 실제 모델을 호출한다.
- 앞 단계의 승인 Artifact가 다음 단계 입력이 된다.
- Agent 3이 자동화 코드 후보 한 건을 생성한다.
- 후보 코드는 승인 자산과 분리된 임시 공간에서 실행한다.
- 정상 프로필 3회와 대표 오류 프로필 1~2개를 실행한다.
- 기존 Core Regression을 실행한다.
- Agent 4가 동일 Source Run만 분석한다.
- 마지막 사람 승인 전에는 Baseline 파일을 바꾸지 않는다.

## 8. 제외 범위

- 모든 변경 유형의 완전 지원
- 전체 TC·자동화 재생성
- Full Regression Suite 구현 주장
- 자유로운 Agent 간 토론
- 무제한 자동 수정
- 자동 Baseline 승격 또는 물리 삭제
- 모든 자동화의 결함 주입
- 완전한 Self-Healing
- 여러 모델 비교와 Slack·Notion 확장

## 9. 완료 판정

- `DESIGNED`: 계약·설계만 존재
- `FIXTURE`: 저장된 샘플로만 동작
- `IMPLEMENTED`: 코드 구현
- `LIVE_VERIFIED`: 실제 모델·브라우저 실행 증거 존재
- `PORTFOLIO_SYNCED`: 설명·코드·영상·산출물 일치

핵심 단계가 모두 `LIVE_VERIFIED`이고 재현 절차가 확인된 후에만 V2를 완성으로 부른다.
