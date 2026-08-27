# QA Agent Pipeline V2

프로젝트 1의 QA 절차를 유지하면서, 고정 예시였던 Agent 산출물을 실제 모델 호출과 실행 증거로 연결한 MVP입니다.

핵심 흐름은 다음과 같습니다.

~~~text
변경 요청
  → Agent 1: 요구사항 분석
  → Agent 2: 기존 TC 대조·변경분 TC 설계
  → Agent 3: 신규·수정 후보 TC 자동화·시험
  → 기존 관련 회귀 실행
  → Agent 4: 결과 분류·최종 보고·Slack·Notion 전달
  → 사람의 최종 확인
~~~

## 프로젝트 1과 V2의 관계

| 구분 | 프로젝트 1 | V2 |
|---|---|---|
| QA 기준 | 3단계 기준, 추적성, 독립성, UI·내부 이중 검증 | 그대로 유지 |
| Agent 1·2 | 고정 산출물 시연 | OpenAI API 구조화 호출 |
| Agent 3 | 사람이 작성한 기존 TC 실행 | AI가 실행 계획을 만들고 허용 목록 컴파일러가 Python 생성 |
| Agent 4 | 규칙 기반 결과 분류와 Slack·Notion 보고 | 분류·외부 보고를 유지하고 인계·증거 정합성 확인 추가 |
| 실행 증거 | 고정 예시 중심 | 변경 요청별 Run 산출물과 SHA-256 |

V2의 목적은 새로운 QA 방법론을 만드는 것이 아닙니다. 프로젝트 1의 절차에서 실제 모델 연결에 필요한 최소 보완만 추가합니다.

## 단계별 동작

| 단계 | 하는 일 | 계속 진행 조건 |
|---|---|---|
| Agent 1 / CP1 | 변경 전·후, 관련 요구사항, 확정 내용과 정보 부족을 구분 | 확정된 시험 범위가 있음 |
| Agent 2 / CP2 | 기존 사람 TC와 확정 조건을 대조해 변경분 후보와 관련 기존 TC를 분리 | 3단계 QA 기준·추적성·독립성·조건별 판정·기존 TC 대조 충족 |
| Agent 3 / CP3 | 신규·수정 후보만 필요한 UI를 확인하고 자동화 계획·코드·시험 증거 생성 | 계획·정적 검사 통과 및 신뢰 가능한 시험 결과 |
| 기존 회귀 | Agent 2가 영향 관계를 기록한 기존 TC만 실행 | 환경 사전 점검 통과 |
| Agent 4 / CP4 | 제품 불일치 후보, 자동화 오류, 환경 오류, 근거 부족을 분리하고 외부 보고 | 산출물·증거·집계 정합성 충족 뒤에만 전달 허용 |

불명확한 요구사항 전체를 억지로 실행하지 않습니다. 확정된 범위는 계속 진행하고, 불명확한 범위나 자동화할 수 없는 TC만 제외해 최종 보고에 남깁니다. 실행 가능한 TC가 여러 건이면 서로 영향을 주지 않도록 한 건씩 처리합니다.

기존 TC 카탈로그는 Requirement ID만 제공하지 않고 각 TC가 실제로 검증하는 동작을 함께 제공합니다. Agent 2는 이 동작이 현재 확정 조건을 그대로 검증할 때만 기존 TC를 재사용하며, 부족한 변경 조건만 신규·수정 후보로 만듭니다. 모든 확정 Condition은 변경분 후보 또는 관련 기존 TC에 연결되어야 하므로 모델이 조건을 조용히 생략할 수 없습니다. 기존 TC가 변경 전 정책에 고정돼 재사용할 수 없으면 억지로 선택하지 않고 사유를 남깁니다.

Agent 1이 유지 검증 대상으로 `VERIFY`를 확정한 Requirement에 연결된 기존 TC는 모델 문구 차이로 사라지지 않도록 카탈로그 기준으로 결정론적으로 보충합니다. 직접 변경된 Requirement의 기존 TC는 변경 후 기대와 맞지 않을 수 있으므로 자동 보충하지 않고 Agent 2의 검증 동작 대조 결과를 따릅니다.

TC는 입력값 하나마다 분리하지 않고 **하나의 관제점에서 하나의 업무 규칙을 검증하는 단위**로 설계합니다. 같은 범위의 하한·상한 또는 같은 비활성 규칙을 공유하는 여러 모드처럼 입력 조건만 다른 경우에는 한 TC의 독립 조건 구간으로 묶을 수 있습니다. 각 구간은 입력·행동·기대 결과를 분리하고, 필요한 중간 초기화와 결과 판정 시점을 명시합니다. Expected Result를 관찰값별로 나누는 것은 TC를 별도 생성한다는 뜻이 아닙니다.

기존 중앙 관제 온도·모드 묶음 TC에서 초기 모드와 설정 온도가 요구사항에 고정되지 않았으면 값을 임의로 만들지 않습니다. 컴파일러가 시험 직전 실제 `mode`·`setTemp`를 저장하고 조건 실행 뒤 그 값으로 복원·적용한 다음 내부 상태가 원래 값과 같은지 확인합니다. 이 제한된 복원은 처음 보는 일반 기능의 내부 상태를 임의로 바꾸는 규칙으로 확대하지 않습니다.

## AI와 코드 생성의 역할

- Agent 1·2는 구조화 JSON을 직접 생성합니다.
- Agent 3 AI는 승인 TC와 실제 UI 확인 결과를 바탕으로 동작·검증 계획을 만들며, 묶음 TC는 각 조건 직후 검증한 다음 다음 조건으로 진행합니다.
- Playwright Python은 AI가 자유롭게 작성하지 않고 허용 목록 기반 컴파일러가 생성합니다.
- Agent 4는 생성형 AI가 아니라 규칙 기반 분석기입니다.

이 구조는 AI의 의미 판단을 사용하면서도 Requirement ID, 기대값, 경계값, Assertion을 임의로 바꾸지 못하게 하기 위한 최소 통제입니다.

## 유지하는 내부 안전장치

사용자가 매번 이해해야 하는 별도 절차는 아니지만 다음 검사는 유지합니다.

- Pydantic 구조화 계약
- 앞 단계 산출물과 SHA-256 인계 확인
- TC와 자동화 계획의 값·근거 추적
- 허용된 UI 조작·검증만 코드로 변환
- 원본과 분리된 임시 위치에서 신규 코드 시험
- 기존 SRS·TC·자동화 원본 비수정
- API 전송 Preview와 비밀정보 제외

UI 확인은 모든 화면을 매번 조사하지 않습니다. 기존 지원 기능은 TC에 필요한 요소만 확인하고, 처음 보는 유사 기능만 안정적인 Selector와 읽기 가능한 상태를 제한적으로 동적 조사합니다.

제품 규칙은 코드에 추가하지 않고 변경 요청·SRS·승인 TC에서 매번 받습니다. 신규 기능은 실제로 관찰한 UI 요소를 CLICK·FILL·SELECT_OPTION·CHECK 같은 공통 조작과 텍스트·값·활성 상태 검증으로 연결합니다. 처음 보는 기능명·값·Selector라는 이유만으로 제외하지 않으며, 실제 관찰한 표준 조작으로 구현 가능한지 먼저 판단합니다. V1 온도 전용 조작은 기존 기준 화면 호환에만 사용하며, 범용 TC의 생성 코드에는 사용하지 않는 온도 Selector나 helper를 넣지 않습니다.

## 현재 범위

포함:

- `MODIFIED` 변경 요청
- Agent 1~3 실제 모델 호출
- 확정 범위의 다중 TC 독립 처리
- 중앙 관제 패널 UI 기반 Playwright 후보 생성·시험
- 관련 기존 회귀 선택 실행
- Agent 4 규칙 기반 분류, 최종 보고와 Slack·Notion Dry-run/명시적 전송

제외:

- `ADDED`, `DELETED` 자동 처리
- 벽면 리모컨·로컬 조작 경로
- 모든 UI 기술의 자동 지원
- 무제한 자동 수정과 Self-Healing
- Full Regression 전체 실행
- 정식 QA 자산 자동 등록
- 중단된 Run을 이어 붙이는 재개 UI
- 다중 모델 비교와 대규모 반복 평가

## 실행 방법

OpenAI Python SDK는 `OPENAI_API_KEY` 환경변수를 읽습니다. 키를 코드·JSON·Git에 저장하지 않습니다.

~~~powershell
python -m pip install ".[agent3,test]"
$env:OPENAI_API_KEY="본인의 API 키"

# Agent 1~3과 신규 자동화 시험
python -m qa_pipeline_v2 pipeline `
  --request "변경 요청 JSON 경로" `
  --target-html "프로젝트1 virtual-controller.html 경로"

# 완료된 신규 자동화와 관련 기존 회귀 실행(API 미호출)
python -m qa_pipeline_v2 execute `
  --run-id "RUN-..." `
  --target-html "프로젝트1 virtual-controller.html 경로"

# 규칙 기반 Agent 4 보고(기본 Slack·Notion Dry-run·테스트 재실행 없음)
python -m qa_pipeline_v2 agent4 --run-id "RUN-..."

# CP4 통과 결과를 실제 Slack·Notion으로 전송
python -m qa_pipeline_v2 agent4 --run-id "RUN-..." --send

# 이미 Agent 4가 끝난 Run의 외부 보고만 Preview 또는 전송
python -m qa_pipeline_v2 report --run-id "RUN-..."
python -m qa_pipeline_v2 report --run-id "RUN-..." --send

# 사람이 작성할 최종 검토 양식 생성
python -m qa_pipeline_v2 human-review --run-id "RUN-..."
~~~

Agent 3 입력을 먼저 확인하려면 개별 명령의 `--preview-only`를 사용합니다. Preview는 API를 호출하지 않습니다.

~~~powershell
python -m qa_pipeline_v2 agent3 `
  --run-id "RUN-..." `
  --tc-id "TC-CAND-..." `
  --target-html "프로젝트1 virtual-controller.html 경로" `
  --preview-only
~~~

기본 모델은 `gpt-5.6-terra`, 추론 강도는 `medium`입니다. 실제 API 호출은 비용을 발생시킵니다.

## 주요 산출물

결과는 Git에서 제외되는 `runs/RUN-.../`에 저장됩니다.

| 산출물 | 의미 |
|---|---|
| `agent1_change_analysis.json`, `checkpoint1.json` | 변경 분석과 CP1 결과 |
| `agent2_test_design.json`, `checkpoint2.json` | 제품 기능 TC와 CP2 결과 |
| `agent2_regression_selection_normalization.json` | Agent 1 VERIFY 관계의 기존 회귀 결정론적 보충 증거 |
| `agent3_selection.json` | 실행 대상 TC와 제외 사유 |
| `agent3_candidates/<tc-id>/` | TC별 UI 확인, 계획, 코드, 시험, 증거 |
| `agent3_run_summary.json` | Agent 3 전체 실행·제외 요약 |
| `validation_execution.json` | 신규 자동화와 관련 기존 회귀 결과 |
| `agent4_analysis.json`, `checkpoint4.json` | 규칙 기반 분류와 CP4 결과 |
| `final_report.json` | 사람에게 전달할 최종 결과 |
| `사람_최종_검토.md`, `사람_최종_검토_manifest.json` | 기대·관찰·증거·판정 선택란과 자동 생성 원본 해시를 포함한 사람 최종 판단 양식. 사람이 작성한 뒤에는 자동 갱신이 덮어쓰지 않음 |
| `slack_payload.json`, `notion_payload.json` | 비밀정보를 제외한 외부 보고 Payload |
| `external_reporting.json` | Slack·Notion Preview·전송·차단·실패 상태와 Payload 해시 |

`PRODUCT_MISMATCH_CANDIDATE`는 제품 결함 확정이 아니라 기대 결과와 다른 관찰 후보입니다. Checkpoint 통과 역시 사람의 최종 승인을 뜻하지 않습니다.

## 공개 실행 증거

| 공개 예시 | 확인 범위 |
|---|---|
| [Agent 1→3 AUTO 온도 실행](examples/results/agent1-agent2-agent3-auto-temperature/README.md) | 실제 모델 계획, 결정론적 후보 코드, Candidate Trial과 증거 |
| [Agent 1→4 잠금 설정 실행](examples/results/agent1-agent2-agent3-agent4-lock-disable/README.md) | 단계별 상태·사용량, 관련 기존 회귀, Agent 4 분류, 사람 검토 양식, Slack·Notion 실제 전송 상태 |

실행 원본은 `runs/`에 보존하고 Git에서 제외합니다. 공개 예시는 비밀정보·로컬 절대경로·불필요한 대용량 증거를 제외한 최소 묶음이며, `public_manifest.json`으로 공개 파일의 SHA-256을 확인할 수 있습니다.

## 문서

| 문서 | 역할 |
|---|---|
| [제품 SRS](docs/01_PRODUCT_SRS.md) | 제품 기대 동작과 인수 기준 |
| [V2 MVP 설계](docs/02_V2_MVP_DESIGN.md) | V1 대비 유지·추가·제외 범위 |
| [Agent·Checkpoint 명세](docs/03_AGENT_AND_CHECKPOINT_SPEC.md) | 단계별 입력·출력·판정 규칙 |
| [테스트·추적성 계획](docs/04_TEST_AND_TRACEABILITY_PLAN.md) | 검증 범위와 완료 기준 |
| [Project1 기준 자산 감사](docs/05_PROJECT1_BASELINE_AUDIT.md) | 기존 자산과 알려진 한계 |
| [테스트 하네스 가이드](docs/06_TEST_HARNESS_GUIDE.md) | UI·내부 상태 확인 경계 |
| [자동 테스트 카탈로그](docs/07_TEST_CATALOG.md) | 현재 수집되는 자동 테스트 목록 |

## 검증

~~~powershell
python -m pytest -q
python -m pytest --collect-only -q
git diff --check
~~~

현재 자동 테스트 수는 **145건**입니다. 기존 TC 대조·변경분 후보 분리, Agent 1 `VERIFY` 회귀의 결정론적 보충, 기존 회귀의 Agent 3 재구현 차단, 실행 직전 모드·설정 온도 저장·복원, 사람 최종 검토 양식, Agent 4 외부 보고 허용·차단과 최초 보고 증거 보존을 확인했습니다. 최종 Live `RUN-20260827-114925-507176`은 Agent 1~4, 신규 후보 시험, 환경 점검과 관련 기존 회귀까지 완료했고 Slack 1건·Notion 4건을 실제 `SENT`로 기록했습니다. 최초 Dry-run은 보존되고 실제 전송은 별도 시도 증거와 SHA-256으로 연결되며, 전송 증거의 비밀정보·로컬 절대경로는 0건입니다. 같은 Run의 잠금 뒤 온도 버튼 `enabled=True` 관찰과 사람 판정 선택란은 [공개 증거 묶음](examples/results/agent1-agent2-agent3-agent4-lock-disable/README.md)에서도 확인할 수 있습니다.
