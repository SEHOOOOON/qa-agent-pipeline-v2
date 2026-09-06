# QA Agent Pipeline V2

프로젝트 1의 QA 절차를 유지하면서, 고정 예시였던 Agent 산출물을 실제 모델 호출과 실행 증거로 연결한 MVP입니다.

최신 기준: **2026-09-06 / V2** — TC 상세 결과 표·실행별 보고 보완. [현재 구현·검증·남은 작업](PROJECT_HANDOFF.md)과 [최신 커밋 이력](https://github.com/SEHOOOOON/qa-agent-pipeline-v2/commits/main/)을 함께 확인하세요. V1 포트폴리오의 고정 시연과 이 저장소의 현재 구현은 구분합니다.

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

V2는 새로운 QA 방법론을 추가한 것이 아니라 V1 절차에 실제 모델 호출, 단계별 JSON 인계, 자동화 후보 생성과 실행 증거를 연결한 버전입니다. 독립 실행에 필요한 가상 중앙제어 HTML과 사람이 작성한 기존 회귀 자산만 `product_baseline/`에 두며 Project1 원본은 변경하지 않습니다.

## 단계별 동작

| 단계 | 하는 일 | 계속 진행 조건 |
|---|---|---|
| Agent 1 / CP1 | 변경 전·후, 관련 요구사항, 확정 내용과 정보 부족을 구분 | 확정된 시험 범위가 있음 |
| Agent 2 / CP2 | 기존 사람 TC와 확정 조건을 대조해 변경분 후보와 관련 기존 TC를 분리 | 3단계 QA 기준·추적성·독립성·조건별 판정·기존 TC 대조 충족 |
| Agent 3 / CP3 | 신규·수정 후보만 필요한 UI를 확인하고 자동화 계획·코드·시험 증거 생성 | 계획·정적 검사 통과 및 신뢰 가능한 시험 결과 |
| 기존 회귀 | Agent 2가 영향 관계를 기록한 기존 TC만 실행 | 환경 사전 점검 통과 |
| Agent 4 / CP4 | 제품 불일치 후보, 자동화 오류, 환경 오류, 근거 부족을 분리하고 외부 보고 | 산출물·증거·집계 정합성 충족 뒤에만 전달 허용 |

운영 원칙은 세 가지입니다.

- 앞 단계 계약을 통과한 확정 범위는 계속 실행하고, 불명확하거나 자동화할 수 없는 TC는 제외해 마지막 보고에 남깁니다. 인계 손상이나 Checkpoint 실패까지 무시하고 진행하지는 않습니다.
- Agent 2는 Requirement ID뿐 아니라 실제 검증 동작을 비교해 유지되는 기존 TC는 재사용하고 변경분만 신규 후보로 만듭니다.
- TC는 입력값 하나가 아니라 하나의 관제점·업무 규칙 단위로 설계하고, 각 조건 직후 판정과 시험 종료 후 상태 복원을 확인합니다.

## AI와 코드 생성의 역할

- Agent 1·2는 구조화 JSON을 직접 생성합니다.
- Agent 3 AI는 승인 TC와 실제 UI 확인 결과를 바탕으로 동작·검증 계획을 만들며, 묶음 TC는 각 조건 직후 검증한 다음 다음 조건으로 진행합니다.
- Playwright Python은 AI가 자유롭게 작성하지 않고 허용 목록 기반 컴파일러가 생성합니다.
- Agent 4는 생성형 AI가 아니라 규칙 기반 분석기입니다.

이 구조는 AI의 의미 판단을 사용하되 Requirement ID, 기대값, 경계값, Assertion의 변경을 검사하는 통제입니다. 구조·명시 값 검사는 자연어 의미의 완전한 일치나 모든 오생성의 차단을 보장하지 않습니다.

## 코드 구조

`qa_pipeline_v2`는 기존 import와 명령행 사용법을 유지하는 호환 진입점입니다. 실제 구현은 공통 계약, Agent 1, Agent 2, Agent 3, 실행·회귀, Agent 4·보고, Orchestrator로 나뉩니다. 테스트도 같은 역할 기준의 7개 파일로 분리하고 공통 fixture와 builder만 별도 지원 파일에서 공유합니다. 이 분리는 파일 위치만 바꾸며 Agent 계약·Checkpoint 판정·CLI 명령은 변경하지 않습니다.

## 유지하는 내부 안전장치

사용자가 매번 이해해야 하는 별도 절차는 아니지만 다음 검사는 유지합니다.

- Pydantic 구조화 계약
- 앞 단계 산출물과 SHA-256 인계 확인
- TC와 자동화 계획의 값·근거 추적
- 허용된 UI 조작·검증만 코드로 변환
- 원본과 분리된 임시 위치에서 신규 코드 시험
- 자동 생성·시험 중 기존 SRS·TC·자동화 원본 비수정(사람이 동의한 SRS 개정은 승인 절차에서 별도 반영)
- API 전송 Preview와 비밀정보 제외

UI 조사는 선택한 TC에 필요한 요소로 제한합니다. 제품 규칙은 코드에 하드코딩하지 않고 변경 요청·SRS·승인 TC에서 받으며, 처음 보는 기능도 실제 화면에서 확인한 표준 UI 조작과 읽기 가능한 상태로 구현 가능한지 판단합니다.

## 현재 범위

포함:

- `MODIFIED` 변경 요청
- Agent 1~3 실제 모델 호출
- 확정 범위의 다중 TC 독립 처리
- 중앙 관제 패널 UI 기반 Playwright 후보 생성·시험
- 관련 기존 회귀 선택 실행
- Agent 4 규칙 기반 분류, 최종 보고와 Slack·Notion Dry-run/명시적 전송
- PASS 후보의 현재 화면 재검증과 사람 승인 기반 공식 TC·자동화 자산 등록
- 승인 공식 TC의 다음 Run 대조·선택·관련 회귀 재실행
- MODIFIED·UPDATE_REQUIRED Requirement의 SRS 개정 제안, 최종 검토 전달과 자산 승인 시 동시 반영

제외:

- `ADDED`, `DELETED` 자동 처리
- 벽면 리모컨·로컬 조작 경로
- 모든 UI 기술의 자동 지원
- 무제한 자동 수정과 Self-Healing
- Full Regression 전체 실행
- Checkpoint PASS만으로 사람 판단 없이 수행하는 정식 QA 자산 자동 등록
- 중단된 Run을 이어 붙이는 재개 UI
- 다중 모델 비교와 대규모 반복 평가

## 실행 방법

OpenAI Python SDK는 `OPENAI_API_KEY` 환경변수를 읽습니다. 키를 코드·JSON·Git에 저장하지 않습니다.

~~~powershell
python -m pip install ".[agent3,test]" pytest-playwright
python -m playwright install chromium
$env:OPENAI_API_KEY="본인의 API 키"

# Agent 1~3과 신규 자동화 시험
python -m qa_pipeline_v2 pipeline `
  --request "변경 요청 JSON 경로" `
  --target-html "product_baseline/virtual-controller.html"

# 완료된 신규 자동화와 관련 기존 회귀 실행(API 미호출)
python -m qa_pipeline_v2 execute `
  --run-id "RUN-..." `
  --target-html "product_baseline/virtual-controller.html"

# 규칙 기반 Agent 4 보고(기본 Slack·Notion Dry-run·테스트 재실행 없음)
python -m qa_pipeline_v2 agent4 --run-id "RUN-..."

# 이미 끝난 Run의 외부 보고 또는 사람 검토 문서
python -m qa_pipeline_v2 report --run-id "RUN-..."
python -m qa_pipeline_v2 human-review --run-id "RUN-..."

# 가상 중앙제어 화면에서 저장된 실제 Run 조회(API 미호출)
python -m qa_pipeline_ui
# 브라우저에서 http://127.0.0.1:8765/ 열기

# 새 AI 실행과 사람 승인·보류를 모두 허용
python -m qa_pipeline_ui --allow-live-run --allow-asset-approval
~~~

중앙제어 UI의 기본 모드는 저장된 Run 조회 전용입니다. `--allow-live-run`에서만 새 API 실행을 허용하고, `--allow-asset-approval`에서만 검증된 PASS 후보의 공식 자산 승인·보류를 허용합니다. 화면에서 실행하는 Agent 4 외부 보고는 미리보기이며 실제 전송은 CLI의 `--send`를 명시했을 때만 수행합니다.

Python 3.10 이상이 필요합니다. 현재 패키지의 선택 의존성에는 기존 회귀 실행에 필요한 `pytest-playwright`가 빠져 있어 위 명령에서 별도 설치합니다. Chromium도 별도 설치가 필요합니다. 설치 절차는 [Playwright 공식 안내](https://playwright.dev/python/docs/intro)를 참고하세요.

새로 복제한 저장소에는 로컬 `runs/`가 없어 저장 결과 목록이 비어 있을 수 있습니다. 공개 예시는 자동으로 불러오는 실행 원본이 아닙니다. HTML 파일만 직접 열면 고정 데모이며, 실제 Run 조회·API 실행·사람 승인은 위 로컬 서버를 통해 사용합니다. GitHub에서 코드를 보는 것만으로 서버가 실행되지는 않습니다. CLI에서는 `pipeline`이 Agent 1~3까지 담당하며 이후 `execute`, `agent4`를 순서대로 실행합니다.

Agent 3 입력을 먼저 확인하려면 개별 명령의 `--preview-only`를 사용합니다. Preview는 API를 호출하지 않습니다.

~~~powershell
python -m qa_pipeline_v2 agent3 `
  --run-id "RUN-..." `
  --tc-id "TC-CAND-..." `
  --target-html "product_baseline/virtual-controller.html" `
  --preview-only
~~~

기본 모델은 `gpt-5.6-terra`, 추론 강도는 `medium`입니다. 실제 API 호출은 비용을 발생시킵니다.

## 주요 산출물

결과는 Git에서 제외되는 `runs/RUN-.../`에 저장됩니다.

| 산출물 | 의미 |
|---|---|
| `agent1_change_analysis.json`, `agent2_test_design.json` | 요구사항 분석과 제품 기능 TC |
| `checkpoint1.json` ~ `checkpoint4.json` | 단계별 자동 검사 결과 |
| `agent3_candidates/<tc-id>/`, `agent3_run_summary.json` | 자동화 계획·코드·시험 증거와 실행 요약 |
| `validation_execution.json` | 신규 후보와 관련 기존 회귀 실행 결과 |
| `agent4_analysis.json`, `final_report.json` | 원인 분류와 최종 권고 |
| `사람_최종_검토.md` | 사람이 최종 판단할 항목과 증거 링크 |
| `external_reporting.json`, `external_reporting_attempts/` | 최초 외부 보고와 후속 전송·미리보기 기록. 화면은 최신 상태와 이전 전송을 구분 |
| `approved_assets/registry.json` | 사람이 승인한 공식 TC·자동화와 SHA-256 |

`PRODUCT_MISMATCH_CANDIDATE`는 제품 결함 확정이 아니라 기대 결과와 다른 관찰 후보입니다. Checkpoint 통과 역시 사람의 최종 승인을 뜻하지 않습니다.

## 공개 실행 증거

| 공개 예시 | 확인 범위 |
|---|---|
| [Agent 1→3 AUTO 온도 실행](examples/results/agent1-agent2-agent3-auto-temperature/README.md) | 실제 모델 계획, 결정론적 후보 코드, Candidate Trial과 증거 |
| [Agent 1→4 잠금 설정 실행](examples/results/agent1-agent2-agent3-agent4-lock-disable/README.md) | 단계별 상태·사용량, 관련 기존 회귀, Agent 4 분류, 사람 검토 양식, Slack·Notion 실제 전송 상태 |
| [Agent 1→4 MED 풍량 실행](examples/results/agent1-agent2-agent3-agent4-medium-fan/README.md) | 2026-09-03 당시 계약의 실제 모델 실행, 신규 후보와 승인 TC 재사용 분리, 3건 PASS, SRS 개정 승인 대기 |

실행 원본은 로컬 `runs/`에 보존하고 Git에서 제외합니다. 위 표는 공개 폴더 5개 중 대표 3개입니다. 잠금·MED 예시는 원본 전체가 아닌 정제한 최소 요약이며 `public_manifest.json`으로 공개 파일의 SHA-256을 확인할 수 있습니다. 이전 AUTO Agent 1→3 예시는 상세 JSON·Screenshot·Trace를 포함한 당시 묶음이며 같은 공개 Manifest 형식은 사용하지 않습니다. 각 예시의 상태·테스트 수·미구현 설명은 실행 당시 기록으로 읽어야 합니다. 과거 증거를 현재 계약으로 다시 실행한 결과로 바꾸지 않습니다.

## 알려진 제한

- 기존 TC만 선택한 경우, 요청의 준비·복원 메모를 검사하는 CP2가 신규 후보의 절차만 찾아 실행을 막을 수 있습니다.
- SRS 반영은 신규 후보의 공식 자산 승인에 연결돼 있어, 기존 TC만 실행한 Run의 SRS를 단독 승인하는 경로는 없습니다.
- 제품 기대값 불일치와 복원 실패가 동시에 발생하면 제품 불일치가 우선 분류됩니다. 복원 실패를 별도 원인으로 집계하는 보완은 남아 있습니다.

이는 해결된 기능이 아니라 현재 구현의 제한입니다. 세부 조건은 [Agent·Checkpoint 명세](docs/03_AGENT_AND_CHECKPOINT_SPEC.md)를 참고하세요.

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
| [V2 기준 화면](product_baseline/virtual-controller.html) | V1 제품 제어 동작·기존 회귀 인터페이스와 V2 실제 Run 조회 패널을 가진 가상 중앙제어 HTML |

## 검증

~~~powershell
python -m pytest -q
python -m pytest --collect-only -q
git diff --check
~~~

현재 자동 테스트는 **187건**입니다. 전체 통과 1회를 확인했지만, 추가 전체 실행은 186건 통과·기존 Agent 3 시험 1건 시간 초과였고 해당 건의 단독 재실행은 통과했습니다. 반복 안정성 문제가 해결됐다는 뜻은 아닙니다. 9월 6일에는 수동 TC 제외 인계·기존 TC의 명시 값 대조·보고 문구·Notion 실행별 보존과 중앙제어 TC 상세 표를 보완했습니다. 새 API Live·외부 전송은 수행하지 않았습니다. 최근 실제 Live `RUN-20260903-125732-ECE88F`에서는 Agent 1·3의 첫 산출물 오류를 Checkpoint가 차단해 재작성한 뒤, 신규 후보·환경 점검·승인 회귀와 CP4·최종 권고가 모두 PASS였습니다. Trace의 로컬 경로·키 패턴도 0건이었습니다.

공개 증거는 위 세 가지 성공·실패 사례에서 확인할 수 있습니다. 상세 Checkpoint 규칙과 시행착오는 [Agent·Checkpoint 명세](docs/03_AGENT_AND_CHECKPOINT_SPEC.md)와 [의사결정 기록](DECISION_LOG.md)에 보존합니다. Checkpoint PASS는 사람의 SRS·공식 자산 승인과 구분됩니다.
