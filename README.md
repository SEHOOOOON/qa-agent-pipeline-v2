# QA Agent Pipeline V2

운영 중인 가상 중앙제어 시스템의 승인된 QA 자산을 기준으로 변경 요청을 분석하고, 제품 기능 테스트케이스와 Playwright 자동화 코드 후보를 생성·검증하기 위한 **Governed Agentic QA Pipeline** 설계 저장소입니다.

> 문서 기준 버전: 0.2
> 현재 단계: BASELINE_CANDIDATE
> 구현 상태: 문서·계약 설계 완료, Live AI Runtime 미구현

## 1. 저장소 목적

V1은 4단계 QA Workflow와 기존 Playwright 회귀 실행을 시연하는 Fixture 기반 프로토타입입니다. V2는 다음 간격을 해소하는 것을 목표로 합니다.

- 사용자가 입력한 변경 요청이 실제 분석 결과를 변경해야 합니다.
- 앞 단계의 승인 산출물이 다음 단계의 실제 입력이어야 합니다.
- Agent 2가 승인한 제품 기능 TC가 Agent 3의 자동화 코드 후보로 연결되어야 합니다.
- 생성 코드는 제품 판정 전에 격리 실행·반복 안정성·오류 검출력·사람 승인을 통과해야 합니다.
- 일반 회귀 실행에서는 AI가 TC나 Assertion을 다시 생성하지 않고 승인된 고정 자동화만 사용해야 합니다.

## 2. 문서 체계

| 순서 | 문서 | 목적 | 현재 상태 |
|---:|---|---|---|
| 1 | [V2 설계 개요](00_V2_DESIGN_OVERVIEW.md) | 목표, 범위, 시스템 구성, 실행 Lane과 종료 기준 | REVIEW_READY |
| 2 | [Baseline SRS 후보](01_REVERSE_ENGINEERED_BASELINE_SRS.md) | 중앙제어 시스템의 검증 가능한 기준과 알려진 편차 | CANDIDATE |
| 3 | [변경 요청 입력 계약](02_CHANGE_REQUEST_INPUT_CONTRACT.md) | 변경 접수 데이터, 충분성 판정과 입력 검증 | REVIEW_READY |
| 4 | [Agent 입출력 계약](03_AGENT_IO_CONTRACTS.md) | Agent·Checkpoint 간 Artifact와 인계 규칙 | REVIEW_READY |
| 5 | [Checkpoint·승인 정책](04_CHECKPOINT_APPROVAL_POLICY.md) | 자동 차단, 사람 검토, 재작업과 Baseline 보호 | REVIEW_READY |
| 6 | [검증·추적성 감사](05_PROJECT1_COVERAGE_AUDIT.md) | Requirement–구현–TC 연결과 구현 우선순위 | LIVING_DOCUMENT |

문서의 순서는 의도적입니다. SRS가 제품 기준을 정의하고, 입력 계약과 Agent 계약은 그 기준을 임의로 변경하지 못하도록 제한하며, Checkpoint 정책과 추적성 감사가 실제 준수 여부를 확인합니다.

## 3. 핵심 용어

| 용어 | 정의 |
|---|---|
| Baseline | 사람이 승인한 특정 버전의 SRS·TC·자동화 묶음 |
| Change Request | 기존 Baseline에 추가·수정·삭제를 요청하는 원문 입력 |
| Product Functional TC | 제품 기능과 기대결과를 정의한 테스트케이스. Agent 2 산출물 |
| Automation Candidate | 승인 TC를 Playwright로 구현한 검증 전 코드 후보. Agent 3 산출물 |
| Fixture | 저장된 입력·산출물을 재생하는 데모 또는 회귀용 고정 데이터 |
| Live | 실제 모델 또는 실행기를 호출해 새 산출물을 생성한 실행 |
| Checkpoint | 산출물을 수정하지 않고 계약·정책 위반을 판정하는 품질 게이트 |
| Promotion Gate | 제품 판정 또는 Baseline 반영 전 QA가 TC·코드·증거를 통합 검토하는 승인 단계 |

## 4. 목표 프로세스

    Approved Baseline + Change Request
      → Agent 1: 변경 분석
      → Checkpoint 1: 근거·충분성 검사
      → Agent 2: 제품 기능 TC Change Set
      → Checkpoint 2: TC 품질 검사
      → Agent 3: Playwright 자동화 코드 후보 생성
      → Checkpoint 3: 정적 검사·격리 시험·반복 실행·오류 검출
      → Human Promotion Gate
      → 승인된 자동화로 변경 검증·Core Regression
      → Agent 4: 결정론적 결과 분류·보고
      → Checkpoint 4: Run·수치·증거 정합성 검사
      → PASS | HOLD | HUMAN_REVIEW

## 5. 사실성 원칙

- 현재 virtual-controller.html의 Agent 1~4 모달은 Workflow Demo입니다.
- V1의 Agent 1·2는 저장된 Prompt·Sample이며 반복 모델 호출기가 아닙니다.
- V1의 Agent 3은 사람이 작성한 Playwright를 실행하며, 신규 코드를 생성하지 않습니다.
- V1의 Agent 4는 생성형 AI가 아니라 Python 규칙 기반 결과 분석기입니다.
- 문서, 애니메이션, Fixture 결과는 Live 실행 증거로 간주하지 않습니다.
- 각 실행은 FIXTURE 또는 LIVE, 모델 호출 여부, 실제 브라우저 실행 여부를 명시해야 합니다.

## 6. 문서 상태와 승인

| 상태 | 의미 |
|---|---|
| DRAFT | 작성 중이며 검토 기준으로 사용 불가 |
| CANDIDATE | 근거를 수집한 승인 후보. 미확정 정책 포함 |
| REVIEW_READY | 구조와 필수 항목이 갖춰져 사람 검토 가능 |
| APPROVED | 승인자·버전·시각이 기록된 적용 기준 |
| SUPERSEDED | 새 버전으로 대체되었으나 감사 목적으로 보존 |

현재 SRS는 원본 기획서가 아니라 화면·코드·테스트에서 역추출한 문서이므로 CANDIDATE입니다. 승인 전에는 미확정 값을 모델이 임의로 확정하거나 Baseline 원본을 변경할 수 없습니다.

## 7. 변경 관리 원칙

1. 문서 변경은 관련 Requirement ID와 변경 사유를 기록합니다.
2. 요구사항 변경은 연결 TC와 자동화 영향 범위를 함께 검토합니다.
3. DELETED 요청도 즉시 삭제하지 않고 DEPRECATION_PROPOSED로 보존합니다.
4. 승인 전 생성 산출물은 Run 전용 디렉터리에 append-only로 저장합니다.
5. 승인된 Baseline은 새 버전으로 승격하고 이전 버전은 유지합니다.
6. 구현이 문서와 다르면 문서를 구현에 맞춰 자동 수정하지 않고 KNOWN_DEVIATION으로 등록합니다.

## 8. 현재 구현 경계

| 구성요소 | 현재 | V2 목표 |
|---|---|---|
| Agent 1 | 고정 Demo | 실제 모델 기반 변경 분석 |
| Agent 2 | 고정 TC Demo | 승인 분석 기반 TC Change Set |
| Agent 3 | 기존 Pytest 실행 | 승인 TC 기반 코드 후보 생성·격리 검증 |
| Agent 4 | 결정론적 Python 분석 | V2 Run 계약과 동일 Source Run 검증 |
| QA Manager | 화면상 순서 제어 | Python 상태 머신과 Artifact 인계 |
| Dashboard | Demo 모달 | 실제 Run Manifest 표시 |

## 9. MVP 완료 조건

V2는 다음이 모두 증명될 때만 LIVE_VERIFIED로 평가합니다.

- 특정 예시에 고정되지 않은 MODIFIED 변경 요청 한 건을 입력할 수 있습니다.
- Agent 1·2·3이 실제 모델을 호출하고 원본 응답과 정규화 결과를 보존합니다.
- Checkpoint를 통과한 Artifact만 다음 단계로 전달됩니다.
- Agent 3이 승인 TC 한 건의 자동화 코드 후보를 생성합니다.
- 후보 코드는 원본과 분리된 환경에서 정상 프로필 3회와 대표 오류 1~2개를 실행합니다.
- QA가 TC·코드·Assertion 매핑·실행 증거를 확인해 통합 승인합니다.
- 승인된 변경 자동화와 기존 Core Regression을 실행합니다.
- Agent 4와 Checkpoint 4가 동일 Source Run의 결과만 집계합니다.
- 보고서 수치와 원본 JSON·실행 증거가 일치합니다.

## 10. 제외 범위

- 모든 변경 유형과 모든 제품 기능의 자동 처리
- 매 회귀 실행마다 전체 TC·코드 재생성
- 자유로운 Agent 간 토론과 무제한 자동 수정
- 사람 승인 없는 Baseline 승격
- 완전한 Self-Healing 또는 모든 오류 자동 복구
- Full Regression 전체 구현 주장
- Slack·Notion·다중 모델 비교

## 11. 저장소 운영

현재 저장소는 설계 문서를 관리합니다. 구현이 시작되면 문서와 코드를 같은 저장소에서 버전 관리하되, 실행 결과와 비밀값은 커밋하지 않습니다.

    qa-agent-pipeline-v2/
    ├─ README.md
    ├─ 00_V2_DESIGN_OVERVIEW.md
    ├─ 01_REVERSE_ENGINEERED_BASELINE_SRS.md
    ├─ 02_CHANGE_REQUEST_INPUT_CONTRACT.md
    ├─ 03_AGENT_IO_CONTRACTS.md
    ├─ 04_CHECKPOINT_APPROVAL_POLICY.md
    └─ 05_PROJECT1_COVERAGE_AUDIT.md
