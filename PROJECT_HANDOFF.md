# QA Agent Pipeline 전체 작업 인수인계

최종 갱신: 2026-08-15
사용자: 오세훈
현재 주 작업: `qa-agent-pipeline-v2`

## 1. 이 문서의 목적

새 Codex 작업은 기존 대화 기록을 자동으로 이어받지 않습니다. 이 문서는 지금까지 합의한 배경, 현재 구현, 작업 규칙과 다음 순서를 새 작업에 전달하기 위한 기준 문서입니다.

새 작업에서는 가장 먼저 다음 문서를 읽어야 합니다.

1. `AGENTS.md` — 항상 적용할 작업·승인·보안·Git 규칙
2. `PROJECT_HANDOFF.md` — 전체 맥락과 현재 상태
3. `DECISION_LOG.md` — 사용자의 문제의식, 중요 가치와 설계 결정의 이유
4. `README.md` — 현재 코드 실행 방법과 공개 상태
5. `docs/02_V2_MVP_DESIGN.md` — V2 범위와 종료선

## 2. 전체 프로젝트 구성

### 프로젝트 1 — 포트폴리오와 기존 실행 기준

- 로컬 경로: `C:\Users\훈\.gemini\antigravity\scratch\industrial-qa\portfolio_export`
- GitHub: `https://github.com/SEHOOOOON/qa-agent-pipeline`
- 역할: 가상 중앙제어기, 사람이 작성한 Playwright 회귀 테스트, 4-Agent·4-Checkpoint QA Workflow 설명, 실행·분류·보고 포트폴리오
- 정확한 성격: **Fixture 기반 Workflow Prototype**

프로젝트 1에서 실제로 구현된 핵심 자산은 다음과 같습니다.

- `virtual-controller.html` 가상 중앙제어기
- 사람이 작성한 Playwright·Pytest 테스트
- UI와 내부 시뮬레이터 상태의 이중 검증
- 실행 결과 수집과 규칙 기반 분류·보고
- 프로젝트 상세 페이지와 구현 영상

프로젝트 1의 Agent 1·2 화면은 저장 산출물을 사용하는 시연이었고, Agent 3는 신규 TC 코드를 생성하는 Agent가 아니라 기존 테스트 실행기에 가까웠습니다. 이 차이를 발견한 뒤 실제 모델 기반 파이프라인을 V2로 분리했습니다.

프로젝트 1 포트폴리오 문구는 V2가 충분히 완성된 뒤 마지막에 함께 정합화합니다. 그전에는 사용자의 명시적 요청 없이 수정하지 않습니다.

### V2 — 현재 주 작업

- 로컬 경로: `C:\Users\훈\.gemini\antigravity\scratch\industrial-qa\qa-agent-pipeline-v2`
- GitHub: `https://github.com/SEHOOOOON/qa-agent-pipeline-v2`
- 목적: 운영 중인 가상 중앙제어 시스템에 변경 요청이 들어왔을 때 실제 모델 출력이 다음 단계와 자동화 후보에 영향을 주는 MVP 구현

V2가 우선 증명하려는 연결은 세 가지입니다.

1. 서로 다른 변경 요청은 서로 다른 Agent 분석·TC 결과를 만든다.
2. 앞 Agent의 검증된 JSON이 다음 Agent의 실제 입력이 된다.
3. Agent 2의 제품 기능 TC가 Agent 3의 Playwright 자동화 후보와 격리 시험으로 이어진다.

예시로 사용한 AUTO 온도 변경 요청은 연결 확인용일 뿐입니다. V2를 한 요구사항에 고정하지 않으며 다른 유효한 MODIFIED 요청도 같은 계약으로 처리해야 합니다.

### Agent 품질 평가 실험 — 현재 후순위

- 로컬 경로: `C:\Users\훈\.gemini\antigravity\scratch\industrial-qa\agent-evaluation-framework`
- 목적: Agent 규칙 준수, Grounding, 환각, 반복 안정성을 평가하는 로컬 Harness
- 현재 상태: 규칙 카탈로그, Fixture·Positive Control, 평가기 Self-test, 로컬 Dashboard까지 구현
- 핵심 한계: Agent 1·2 Live 반복 Adapter가 없어 현재 지표는 실제 Agent 성능이 아니라 평가기 자체 검증

현재 우선순위는 V2 완성입니다. V2에서 실제 반복 실행 가능한 Agent가 확보된 뒤 평가 프로젝트와 연결합니다.

## 3. V2의 최종 MVP 흐름

```text
변경 요청 JSON
  ↓
Agent 1 — 기존 SRS와 비교한 변경 분석
  ↓
CP1 — ID·before/after·근거·범위·인수 조건 검사
  ↓
Agent 2 — 제품 기능 TC 후보 설계
  ↓
CP2 — 구조·추적성·테스트 데이터·Double-Assert·자동화 가능성 검사
  ↓
Agent 3 — 실제 UI Inventory + 제한된 자동화 실행 계획 생성
  ↓
허용 목록 컴파일러 — Playwright Python 후보 생성
  ↓
CP3 — 계획·코드 추적성·금지 패턴 검사
  ↓
Candidate Workspace — 후보 1회 시험
  ↓
변경 검증 + 기존 검증 가능 회귀 실행
  ↓
Agent 4 — 규칙 기반 결과 분류와 보고
  ↓
조건부 검토 및 사람의 정식 QA 자산 등록 승인 1회
```

사람 검토는 매 단계의 일반 통과 절차가 아닙니다. Checkpoint가 `REVIEW`, `PAUSE`, `FAIL`을 반환하거나 최종 정식 QA 자산 등록이 필요할 때만 개입하는 방향입니다.

## 4. Agent별 책임과 현재 구현

| 구성요소 | 역할 | 현재 상태 |
|---|---|---|
| Product SRS | 실제 화면·코드에서 확인 가능한 제품 기대 동작 | 구현 |
| Agent 1 | 변경 요청과 SRS를 비교해 구조화 변경 분석 생성 | 실제 OpenAI API 연결 구현 |
| CP1 | 10개 결정론 규칙으로 구조·근거·인계 판단 | 구현 |
| Agent 2 | CP1 통과 분석을 기반으로 제품 기능 TC 후보 생성 | 실제 OpenAI API 연결 구현 |
| CP2 | 11개 결정론 규칙으로 TC 품질·추적성 검사 | 구현 |
| Agent 3 | 실제 UI Inventory를 참고해 제한된 행동·Assertion 계획 생성 | 구현, `agent3-3.4` 공개 Live 확인 |
| Compiler | Agent 3 계획을 허용 목록 기반 Playwright Python으로 변환 | 구현 |
| CP3 | 계획·코드 추적성과 금지 패턴 검사 | 구현 |
| Candidate Trial | 원본과 분리된 임시 위치에서 후보 1회 시험 | 구현 |
| 최소 Orchestrator | Agent 1→2→3·CP1→3·Candidate Trial을 한 명령으로 실행 | 구현·세 중단 Live와 정상 완료 Live 확인 |
| 조건부 검토 재개 | REVIEW 답변 후 중단 단계에서 재개 | 미구현 |
| 변경·회귀 실행 | 검증 후보와 기존 회귀 TC 실행 연결 | 미구현 |
| Agent 4 V2 | V2 중립 결과 계약을 분류·보고 | 미구현 |
| 최종 등록 승인 | SRS·TC·자동화를 공식 재사용 자산으로 저장 | 미구현 |

## 5. 현재 코드와 파일 구조

```text
qa-agent-pipeline-v2/
├─ AGENTS.md                         # 지속 작업 규칙
├─ PROJECT_HANDOFF.md                # 전체 인수인계
├─ DECISION_LOG.md                   # 사용자 의도와 설계 결정 기록
├─ README.md                         # 공개 프로젝트 설명과 실행법
├─ docs/
│  ├─ 01_PRODUCT_SRS.md              # 제품 요구사항 기준
│  ├─ 02_V2_MVP_DESIGN.md            # 범위·프로세스·종료선
│  ├─ 03_AGENT_AND_CHECKPOINT_SPEC.md # 입출력 계약·Checkpoint 규칙
│  ├─ 04_TEST_AND_TRACEABILITY_PLAN.md# 테스트·증거·추적성
│  ├─ 05_PROJECT1_BASELINE_AUDIT.md  # 프로젝트 1 자산·한계
│  └─ 06_TEST_HARNESS_GUIDE.md       # UI 조사·QA 하네스 경계
├─ examples/
│  ├─ change_request.example.json    # 고정 대표값이 아닌 연결 예시
│  └─ results/                       # 비밀정보 제거한 공개 Run
├─ src/qa_pipeline_v2.py             # 계약·Agent 1~3·CP1~3·CLI·시험
├─ tests/test_pipeline.py            # 현재 회귀 테스트
├─ runs/                             # 로컬 원본 Run, Git 제외
└─ pyproject.toml
```

현재 규모에서는 한 핵심 모듈과 한 테스트 파일을 유지합니다. 보안 경계나 독립 재사용 단위가 실제로 커질 때만 분리합니다.

## 6. 실제 실행과 공개 증거

### Agent 1·2 Live Run

- 공개 Run: `RUN-20260813-125229-31EB5F`
- 위치: `examples/results/agent1-agent2-auto-temperature/`
- 결과:
  - Agent 1: `PASS + CONTINUE`
  - Agent 2: 1차 CP2 반려 후 최대 1회 재작업
  - 최종 CP2: `PASS`
  - 제품 기능 TC 후보: 12건

이 Run은 Agent 1·2 실제 API 호출과 자동 인계를 증명합니다. 특정 AUTO 요구사항만 지원한다는 의미는 아닙니다.

### Agent 3

- 구현됨: CP2 PASS TC의 Capability 사전 판정, 선택 TC 범위 UI Inventory, API 입력 Preview, 구조화 계획, 결정론적 코드 컴파일, CP3, Candidate Trial
- 공개 증거: `examples/results/agent1-agent2-agent3-auto-temperature/`에 `agent3-3.4` 실제 모델 계획·CP3·Candidate Trial과 Screenshot·Trace 보존
- 현재 지원 범위: 조사된 CENTRAL 제어 패널의 모드·온도·적용과 온도 UI·내부 `setTemp`·Toast·온도 비활성 표시 Capability
- LOCAL 또는 현재 Assertion으로 표현할 수 없는 TC: UI 조사·API 호출 전에 `NOT_AUTOMATABLE`과 누락 Capability 기록
- 2026-08-15 로컬 Preview 확인: `TC-CAND-003` `ELIGIBLE`, 관련 Selector 7개·하네스 키 2개만 포함, 대상 SHA-256 일치, API 호출 없음, 로컬 절대경로·HTML 원문·비밀 토큰 없음
- 2026-08-15 진단 Live 확인: `gpt-5.6-terra`, 1차 계획 CP3 FAIL(온도 Action Selector 불일치), 1회 재작업 후 CP3 PASS, Trial `PRODUCT_MISMATCH_CANDIDATE`, Screenshot·Trace 생성, Project1 SHA-256 불변
- 관찰값: AUTO에서 17°C 요청 후 UI `17.0`, 내부 `setTemp=17`, Toast 표시. 변경 요청의 18°C 하한 기대와 다르지만 최종 제품 결함 확정은 아님
- 실제 누적 사용량: input 5,494·output 2,162·total 7,656 tokens. 당시 Manifest top-level은 마지막 시도 4,296 tokens만 기록했으며 이후 누적 집계로 수정
- 진단 Run 위치: `runs/live-agent3-20260815-attempt1/RUN-20260813-125229-31EB5F/`(Git 제외). 최초 연결 실패의 `agent3_error.json`, 보완 전 `expected_text`, 성공 산출물이 혼재하므로 공개하지 않음
- 첫 보완 후 두 번째 진단 Live: `runs/live-agent3-20260815-attempt2/RUN-20260813-125229-31EB5F/`(Git 제외). Action Selector·`expected_text`는 준수했지만 1차 계획이 `window.__vccs.devices[1].setTemp`를 사용해 CP3 FAIL, 재작업 후 PASS
- 두 번째 누적 사용량: input 5,648·output 1,580·total 7,228 tokens. Manifest 누적·마지막 시도 집계와 모든 SHA-256은 일치했고 최종 Trial 관찰도 동일
- 추가 발견: 두 번째 Trace ZIP 내부에 대상 `file:///` URL과 사용자 홈·Trial stack/source 경로가 남아 공개 불가. `agent3-3.2`에서 Assertion 전략별 Selector 고정과 Trace 경로 치환을 구현
- 세 번째 진단 Live: `runs/live-agent3-20260815-attempt3/RUN-20260813-125229-31EB5F/`(Git 제외), `agent3-3.2`, 첫 계획 CP3 PASS, input 2,493·output 615·total 3,108 tokens, Trial `PRODUCT_MISMATCH_CANDIDATE`
- 세 번째 증거 감사: 모든 SHA-256 일치, Project1 불변, Trace 141개 항목 정상, 로컬 경로 0건, Screenshot·Trace 완전, 비밀정보·깨진 UTF-8 없음
- 세 번째 후속 발견: `target_device_id=1`이나 `SELECT_DEVICE value=null`. 컴파일러 실행에는 영향이 없었지만 계약 불일치이므로 현재 `agent3-3.3` CP3에서 대상 ID·선택 Action 값을 함께 검사
- 세 번째 Screenshot 후속 발견: “성공적으로 적용되었습니다” Toast를 기존 `TOAST_VISIBLE`이 ER-007 차단 안내로 통과시킨 거짓 PASS
- 현재 `agent3-3.4`: 차단 기대 결과는 `TOAST_BLOCKING`을 강제하고 표시 상태와 제한된 차단 의미 신호를 함께 검사. 로컬 재시험에서 ER-005·006·007 불일치와 Trace 로컬 경로 0건 확인
- 네 번째 공개 Live: `runs/live-agent3-20260815-attempt4/RUN-20260813-125229-31EB5F/`에서 첫 계획 CP3 PASS, input 2,533·output 594·total 3,127 tokens, Trial `PRODUCT_MISMATCH_CANDIDATE`
- 공개 Run 감사: `SELECT_DEVICE value=1`, `TOAST_BLOCKING`, 모든 인계 SHA-256과 Project1 대상 해시 일치, Project1 불변, 공개 텍스트·Trace의 비밀정보·로컬 경로 패턴 0건
- 공개 관찰: UI `17.0°C`, 내부 `setTemp=17`, 성공 적용 Toast로 ER-005·006·007 불일치 후보 기록. 제품 결함 확정은 아님

### 테스트

- 2026-08-15 확인 결과: `python -m pytest -q` **71 passed**
- 테스트 범위: Product SRS 파서, Agent 1~3 Adapter, CP1~3, SHA-256 인계, Capability 사전 판정, 선택 TC 범위 UI 조사, 금지 패턴, 실제 브라우저 Candidate Trial, CLI 종료 코드, 비지원 `expected_text`, 전략별 Assertion Selector, 선택 장비 값, 차단 Toast 의미, Agent 1~3 누적/마지막 시도 토큰, 실패 Run 재사용 차단, UTF-8 로그, Trace 경로 치환, 최소 Orchestrator 순서·중단·Manifest 해시·모델 호출 전 대상 검사

71개 테스트 통과와 `agent3-3.4` 공개 Agent 3 Live Run은 각각 코드 회귀와 실제 A1→A3·시험 연결 증거입니다. 최소 Orchestrator는 CP1 PAUSE·Agent 3 비지원 후보·재작업 후 CP2 FAIL의 세 중단 경로와 `RUN-20260815-092107-0C075E`의 CP1·2·3·Trial PASS를 Live로 확인했습니다. Agent 4와 최종 보고가 없어 전체 End-to-End 완성을 의미하지 않습니다.

## 7. 로컬 실행 방법

```powershell
cd C:\Users\훈\.gemini\antigravity\scratch\industrial-qa\qa-agent-pipeline-v2
python -m pip install ".[agent3,test]"

# API 키는 사용자 환경변수로만 설정
$env:OPENAI_API_KEY="본인의 API 키"

python -m qa_pipeline_v2 agent1 --request examples/change_request.example.json
python -m qa_pipeline_v2 agent2 --run-id "Agent 1이 출력한 RUN-..."

# Agent 3는 반드시 Preview부터 확인
python -m qa_pipeline_v2 agent3 --run-id "Agent 2 완료 RUN-..." --tc-id "TC-CAND-..." --target-html "프로젝트1 virtual-controller.html 절대경로" --preview-only
python -m qa_pipeline_v2 agent3 --run-id "Agent 2 완료 RUN-..." --tc-id "TC-CAND-..." --target-html "프로젝트1 virtual-controller.html 절대경로"

# 최소 A1→A3 한 명령 실행: 현재 Run의 적격 TC 자동 선택
python -m qa_pipeline_v2 pipeline --request "구체 변경 요청 JSON 경로" --target-html "프로젝트1 virtual-controller.html 절대경로"

python -m pytest -q
```

기본 모델은 `gpt-5.6-terra`입니다. 다른 모델을 사용할 때만 `--model` 또는 `OPENAI_MODEL`을 지정합니다.

## 8. Run 산출물과 추적성

로컬 원본은 `runs/RUN-.../`에 저장되고 Git에서 제외됩니다.

- `request.json`
- `srs_snapshot.md`
- `agent1_change_analysis.json`
- `checkpoint1.json`
- `run_manifest.json`
- `agent2_test_design.json`
- `checkpoint2.json`
- `agent2_manifest.json`
- `agent3_selection.json` (Orchestrator AUTO 선택 시 현재 CP2 후보별 Eligibility)
- `agent3_eligibility.json`
- `agent3_model_input_preview.json`
- `agent3_ui_observation.json`
- `agent3_automation_plan.json`
- `candidates/test_<tc-id>.py`
- `checkpoint3.json`
- `agent3_trial.json`
- `agent3_manifest.json`
- `orchestrator_manifest.json` (한 명령 실행 시 단계 종료 코드·중단 위치·단계 Manifest SHA-256)

Agent 2와 Agent 3는 앞 단계 Manifest와 산출물 SHA-256을 재검증합니다. Agent 3 Manifest는 Eligibility SHA-256, 모든 계획 시도의 누적 토큰과 마지막 시도 토큰도 기록합니다. `agent3_error.json`이 생긴 시도는 같은 폴더에서 재사용하지 않습니다. 원본이 변경되면 다음 단계가 시작되어서는 안 됩니다.

## 9. 현재 Git 상태

- 브랜치: `main`
- 원격: `https://github.com/SEHOOOOON/qa-agent-pipeline-v2.git`
- 마지막 커밋: `9c29405 Agent 3 자동화 후보 생성과 격리 검증 구현`
- 2026-08-15 현재 미커밋 변경 32개 파일(추적 8, 미추적 24):
  - `.gitignore`
  - `README.md`
  - `docs/02_V2_MVP_DESIGN.md`
  - `docs/03_AGENT_AND_CHECKPOINT_SPEC.md`
  - `docs/04_TEST_AND_TRACEABILITY_PLAN.md`
  - `docs/06_TEST_HARNESS_GUIDE.md`
  - `src/qa_pipeline_v2.py`
  - `tests/test_pipeline.py`
  - `AGENTS.md` (미추적)
  - `DECISION_LOG.md` (미추적)
  - `PROJECT_HANDOFF.md` (미추적)
  - `examples/results/agent1-agent2-agent3-auto-temperature/` 공개 Run 21개 파일 (미추적)

미커밋 변경의 핵심은 Agent 3 CLI 결과 의미와 모델 호출 전 지원 경계를 명확히 한 것입니다.

- `PASS`, `PRODUCT_MISMATCH_CANDIDATE` → 정상 완료 `exit code 0`
- `NOT_AUTOMATABLE`, `AUTOMATION_ERROR`, `ENVIRONMENT_ERROR`, `TIMEOUT`, CP3 실패, 시험 미실행 → 제품 판정 불가이므로 `exit code 2`
- 선택 TC Capability만 UI 조사·모델 입력에 사용하고 무관한 Selector 누락은 차단하지 않음
- LOCAL·미지원 Assertion은 API 호출 전에 누락 Capability와 함께 구조화 기록
- 기존 Agent 3 기술 보완 범위 65개에 최소 Orchestrator 4개와 복원 계약 2개를 추가해 전체 71개 통과
- UI Inventory와 Candidate Workspace의 실제 한계를 문서에 명시
- 진단 Live에서 확인한 Action Selector 프롬프트, 비지원 `expected_text`, 누적 토큰, 실패 시도 불변성, Windows UTF-8 로그 문제 보완
- 두 번째 진단에서 확인한 Assertion 전략별 Selector와 Trace 로컬 경로 치환 보완
- 세 번째 진단에서 확인한 대상 장비 ID와 `SELECT_DEVICE` Action 값 일치 검사 보완
- 세 번째 Screenshot에서 확인한 성공 Toast의 차단 안내 거짓 PASS를 `TOAST_BLOCKING`으로 보완
- 현재 `agent3-3.4` 공개 Live Run과 감사 산출물 21개를 `examples/results/`에 추가
- 최소 Orchestrator가 같은 Run ID로 Agent 1→2→3을 순차 실행하고, 비정상 종료 시 후속 Agent를 차단하며 단계 Manifest 해시를 요약하도록 구현
- 실제 Orchestrator `RUN-20260815-062606-E36A76`: 자리표시자 요청으로 CP1 `PASS + PAUSE`, Agent 1 3,865 tokens, Agent 2·3 미호출, 모든 입력·산출물·요약 Manifest 해시 일치, 비밀정보·로컬 경로 0건, Project1 불변
- 구체 요청 Orchestrator `RUN-20260815-063800-3B624C`: Agent 1·2 PASS, Agent 1 1회·Agent 2 2회·실제 누적 total 34,814 tokens, 지정 `TC-CAND-003`이 새 Run에서는 LOCAL이라 Agent 3 API 전 `NOT_AUTOMATABLE`, 모든 해시 일치·Project1 불변
- Run 간 TC ID 재사용을 제거하기 위해 `pipeline --tc-id AUTO`를 기본화하고 현재 CP2 후보에서 적격 TC를 결정론적으로 선택. 적격 후보가 없으면 전체 누락 Capability를 기록하고 Agent 3 API 전 중단
- Agent 2 Prompt `agent2-2.3`에 CENTRAL 변경 검증의 `PRIMARY_TEST_DEVICE` 자동화 후보 최소 1건을 명시하되 LOCAL·복수 장비 TC는 보존
- 보완 후 Orchestrator `RUN-20260815-090130-F023B1`: Agent 1 PASS, Agent 2 첫 시도 CP2 중복·추적 FAIL, 재작업 후 LOCAL 직접 변경 Requirement 누락으로 최종 CP2 FAIL, 실제 누적 total 30,227 tokens, Agent 3 미호출, 모든 해시 일치·Project1 불변
- 비용 감사에서 Agent 1·2 Manifest 최상위 `usage`의 마지막 시도만 기록하는 문제를 확인. 계약 2.3부터 모든 시도 누적과 `final_attempt_usage`를 분리
- Agent 2 재작업 입력을 실패 메시지만 전달하던 방식에서 CP2 전체 `rule_id + PASS/FAIL + message` 전달로 바꾸고 PASS 규칙 보존·새 FAIL 금지를 명시. 최대 1회 재작업은 유지
- 정상 완료 Orchestrator `RUN-20260815-092107-0C075E`: Agent 1·2·3과 CP1·2·3 PASS, AUTO `TC-CAND-001`, Trial PASS, Agent 1 5,607·Agent 2 누적 27,752·Agent 3 3,194로 총 36,553 tokens, 모든 Manifest 해시 일치·Project1 불변·텍스트/Trace 민감정보 및 로컬 경로 0건
- 후속 감사에서 복원 절차가 초기 온도를 적용만 하고 재확인하지 않던 틈을 확인. CP3가 변경된 초기값과 CENTRAL 복원 적용을 검사하고 컴파일러가 복원 후 UI·내부 `setTemp`를 확인하도록 보완했으며, 같은 TC·계획의 무API 재시험 PASS
- Chromium이 생성하는 루트 `debug.log`는 테스트 부산물로 Git에서 제외

이 변경은 사용자 작업으로 보존해야 하며 임의로 되돌리면 안 됩니다. `AGENTS.md`, `PROJECT_HANDOFF.md`, `DECISION_LOG.md`도 인수인계 작업에서 새로 추가된 미커밋 파일입니다.

## 10. 현재 부족한 부분

P0 수준의 즉시 붕괴 문제라기보다 MVP를 완성하기 위해 남은 연결입니다.

1. CP의 REVIEW·PAUSE 이후 사용자 답변을 저장하고 해당 단계부터 재개하는 기능이 없습니다.
2. Agent 3 후보가 검증된 뒤 변경 검증과 기존 회귀 TC를 실행하는 연결이 없습니다.
3. Agent 4가 V2의 중립 실행 결과를 받아 제품·자동화·환경 문제를 분류하는 계약이 없습니다.
4. 최종 보고와 정식 QA 자산 등록 승인 기록이 없습니다.
5. 서로 다른 변경 요청 최소 2건으로 동적 결과 차이를 End-to-End 검증하지 않았습니다.

## 11. 다음 권장 순서

현재 범위를 지나치게 넓히지 않고 다음 순서로 진행합니다.

### 1단계 — Agent 3 공개 후보 Live Run — 완료

- `--preview-only` 전송 데이터 검사
- `agent3-3.4` 실제 모델 계획·Compiler·CP3·Candidate Trial
- 선택 장비 값·차단 Toast 의미·Trace·비용·비밀정보 감사
- 공개 가능한 Run을 `examples/results/`에 복사

### 2단계 — 최소 Orchestrator 구현 — 완료

- 입력 한 건으로 Agent 1→CP1→Agent 2→CP2→Agent 3→CP3를 순차 실행
- REVIEW·FAIL이면 후속 실행 중단
- 각 단계의 Manifest·SHA-256 보존

### 3단계 — 최소 Orchestrator 정상 완료 Live 재검증 — 완료

- 구체 변경값이 있는 요청과 AUTO TC 선택으로 `pipeline` 한 명령 Agent 1→3 실제 모델 호출과 Candidate Trial 실행
- 단계별 토큰·Checkpoint·Manifest SHA-256·Project1 불변 감사
- 실패 시 중단 위치와 후속 API 미호출 확인
- `RUN-20260815-092107-0C075E` 정상 완료와 후속 복원 재확인 무API Trial PASS

### 4단계 — 변경 검증과 기존 회귀 연결

- 검증된 Candidate 자동화만 변경 검증에 사용
- 프로젝트 1의 재사용 가능한 기존 회귀 TC 실행
- 환경 신뢰성이 깨졌을 때만 후속 실행 중단

### 5단계 — Agent 4·최종 보고

- V2 중립 실행 결과 계약으로 제품·자동화·환경·근거 부족 분류
- 실행 결과와 보고 수치 정합성 검사
- 정식 QA 자산 등록 승인 기록

### 6단계 — 최종 검증·커밋·푸시

- 전체 `git diff`와 문서 정합성·민감정보 검사
- 전체 자동 테스트와 대표 End-to-End 재확인
- 사용자 지시에 따라 한글 커밋 후 푸시

### 7단계 — V2 완료 후

- 서로 다른 변경 요청 2건으로 동적 결과 검증
- 프로젝트 1 포트폴리오 설명을 V1/V2 사실에 맞게 정리
- 그다음 Agent 평가 프로젝트에 Live 반복 Adapter 연결

## 12. 하지 말아야 할 확장

V2 MVP가 끝나기 전에는 다음 항목을 우선 구현하지 않습니다.

- 모든 변경 유형 자동 처리
- 모든 TC 자동화
- 자유로운 Agent 간 토론
- Full Regression 전체 구현
- 여러 모델 비교
- 대규모 반복 평가
- 완전 자동 Baseline 갱신
- 완전한 Self-Healing
- 운영 장비·Slack·Notion 연결
- 탐색적 테스트 Agent

좋은 추가 기능이 보여도 우선 제안으로만 기록하고, 현재 MVP 종료선을 달성한 뒤 사용자와 범위를 다시 정합니다.

## 13. 새 작업에 전달할 첫 메시지 예시

```text
이 저장소의 AGENTS.md, PROJECT_HANDOFF.md, DECISION_LOG.md를 먼저 전부 읽어 주세요.
현재 미커밋 변경을 보존하고 git status와 테스트 상태를 확인한 뒤 진행해 주세요.
수정이 필요하면 수정 전·후, 영향 파일과 검증 방법을 먼저 설명하고 제가 명령한 범위만 수정해 주세요.
Project1은 명시적인 지시가 없으면 읽기 전용이고, 현재 주 작업은 V2입니다.
```
