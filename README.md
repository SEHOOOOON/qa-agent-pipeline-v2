# Project 1 V2 설계 문서

Project 1의 Fixture 기반 Workflow를 실제 변경 요구사항, 모델 호출과 자동화 코드 후보 생성이 연결되는 **Governed Agentic QA Pipeline**으로 확장하기 위한 설계 기준이다.

> 현재 상태: `DESIGNED`  
> 실제 AI API와 Live Agent 실행은 아직 구현되지 않았다.

## 문서 순서

1. [V2 설계 개요](00_V2_DESIGN_OVERVIEW.md)
2. [역설계 Baseline SRS 후보](01_REVERSE_ENGINEERED_BASELINE_SRS.md)
3. [변경 요청 입력 계약](02_CHANGE_REQUEST_INPUT_CONTRACT.md)
4. [Agent 1~4 입출력 계약](03_AGENT_IO_CONTRACTS.md)
5. [Checkpoint·사람 승인 정책](04_CHECKPOINT_APPROVAL_POLICY.md)
6. [프로젝트 1 커버리지 감사](05_PROJECT1_COVERAGE_AUDIT.md)

## 현재 구현 경계

- Agent 1·2: Prompt와 고정 Workflow Demo
- Agent 3: 기존 Pytest/Playwright 실행은 실제, 코드 후보 생성은 미구현
- Agent 4: 결정론적 Python 분석은 실제
- V2 Live Agent Runtime: 미구현

문서·화면 애니메이션·고정 Fixture는 Live 실행 증거로 간주하지 않는다.
