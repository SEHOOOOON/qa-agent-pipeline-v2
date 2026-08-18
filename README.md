# QA Agent Pipeline V2

운영 중인 가상 중앙제어 시스템에 **MODIFIED 변경 요청 1건**이 들어왔을 때, 실제 모델이 변경점을 분석하고 제품 기능 TC와 실제 UI 근거 기반 Playwright 자동화 후보를 만드는 흐름을 구현하는 MVP입니다.

> 현재 저장소는 **Agent 1·CP1 → Agent 2·CP2 → Agent 3·CP3·신규 자동화 후보 시험 → 변경 검증·관련 기존 회귀 실행 → Agent 4·CP4·최종 보고**까지 연결합니다. 기존 온도 제어는 필요한 UI만 확인하고, 처음 보는 기능은 버튼·입력·선택·체크·상태 표시 같은 범용 UI 구조를 동적으로 조사합니다. AI는 실제로 관찰한 요소로 실행 가능한 코드 의도를 만들며, 범용 조작으로 부족할 때는 자동화 지원 범위 확장 필요를 기록합니다. Agent 4는 API 호출이나 재실행 없이 검증 결과와 SHA-256을 규칙으로 확인해 보고를 만듭니다.

## 해결하려는 문제

프로젝트 1은 QA 기준, 가상 중앙제어기, 사람이 작성한 Playwright 테스트와 규칙 기반 보고를 보여줍니다. Agent 1·2 화면은 고정 산출물 시연이고 Agent 3는 기존 테스트 실행기이므로 새 입력이 새 분석·TC·코드로 이어지는 Live Pipeline은 아닙니다.

V2는 다음 세 연결만 우선 증명합니다.

1. 변경 요청에 따라 Agent 1·2의 실제 출력이 달라집니다.
2. 검증된 앞 단계 JSON이 다음 Agent의 실제 입력이 됩니다.
3. Agent 2의 TC를 Agent 3 코드 후보와 격리 시험 결과까지 연결합니다.

## 구현 상태

| 영역 | 현재 상태 |
|---|---|
| 가상 중앙제어기 | 프로젝트 1에 구현됨 |
| 기존 Playwright 제품 기능 TC | 7건 후보 중 6건 재사용 가능, TC-INT-002 보완 필요 |
| 환경 사전 점검 | V2 `execute`가 TC-ENV-000을 먼저 실행하고 미통과 시 기존 회귀를 차단 |
| 변경 검증·관련 기존 회귀 | 현재 컴파일러 후보를 재검증·필요 시 무API 재시험하고 Requirement ID로 기존 회귀 6건 중 관련 TC만 선택·격리 실행 |
| 분류·보고 | V2 Agent 4가 중립 실행 결과·Manifest SHA-256을 확인하고 제품 불일치 후보·자동화 실행·환경·근거 부족을 규칙 기반으로 분류해 CP4·최종 보고 JSON 생성 |
| Product SRS | 실제 화면·코드 기준 초기 제품 기준 문서 작성 |
| Agent 1 Live 모델 호출·CP1 | 구조화 분석, CP1 10개 규칙, 실행 계속 가능 확인 사항의 최종 보고 이관과 CONTINUE·PAUSE·BLOCKED 인계, 실패 시 최대 1회 재작업 구현 |
| Agent 2 Live 모델 호출 | CP1 PASS 또는 실행 계속 가능 확인 사항이 있어도 CONTINUE인 Run만 입력, 변경 요청·고정 SRS·Agent 1 분석으로 제품 TC 후보 생성, 실패 시 최대 1회 재작업 구현 |
| Agent 3 코드 후보 생성 | 기존 기능은 필요한 UI만 확인하고 신규 기능은 범용 UI를 동적 조사. AI가 관찰 근거 기반 실행 계획을 만들고 검증된 컴파일러가 Playwright 코드로 변환 |
| CP1·CP2·CP3·Run Orchestrator | 단계별 CLI·SHA-256 인계·CP3·격리 시험과 A1→A3 순차 실행·현재 Run의 적격 TC 자동 선택·중단·요약 Manifest 구현. 세 중단 Live와 정상 완료 Live 확인 |
| Agent 4·CP4·최종 보고 | 구현: 실행 재시작이나 API 호출 없이 결과·해시·중복·근거·집계 정합성을 검사하고 JSON 보고 생성 |
| 조건부 검토·정식 QA 자산 등록 승인 | 최종 확인 사항의 최종 보고 이관 구현, 요구사항 미확정 PAUSE 재개와 정식 등록 기록은 미구현 |

## MVP 프로세스

~~~text
변경 요청
  -> Agent 1 변경 분석
  -> CP1 ID·before·after·확정 조건 출처·인수 조건 누락 검사 + CONTINUE·PAUSE·BLOCKED 인계
  -> Agent 2 제품 기능 TC 설계
  -> CP2 구조·추적성·중앙/로컬 경로·시험 데이터·사람 검토 필요성 검사
  -> Agent 3 실제 화면 확인·Playwright 코드 후보 생성
  -> CP3 정적 검사·격리 시험
  -> CP 통과 후보의 변경 검증
  -> 기존 검증 가능 회귀 TC 실행
  -> Agent 4 규칙 기반 분류·보고
  -> 사람의 공식 SRS·TC·자동화 저장 승인 1회

공통 분기: CP1의 `PROCEED` 상태에서 나온 보완 확인과 Agent 2의 `최종_확인_사항`은 실행을 계속하고 최종 보고에 모읍니다. 기대 결과를 확정할 수 없는 `WAITING_FOR_USER`·`PARTIAL_PROCEED`, Agent 2의 `중단_확인_사항`, CP3 FAIL 또는 자동화 지원 범위 확장 REVIEW만 후속 자동 실행을 중단합니다. 중단 Run 재개 UI는 아직 미구현입니다.
~~~

## 문서

| 문서 | 역할 |
|---|---|
| [제품 SRS](docs/01_PRODUCT_SRS.md) | 변경 분석에 사용하는 제품 기대 동작과 인수 기준 |
| [V2 MVP 설계](docs/02_V2_MVP_DESIGN.md) | 구현 범위, 단계와 종료선 |
| [Agent·Checkpoint 명세](docs/03_AGENT_AND_CHECKPOINT_SPEC.md) | 입출력 계약과 최소 판정 규칙 |
| [테스트·추적성 계획](docs/04_TEST_AND_TRACEABILITY_PLAN.md) | V2 단계별 검증·증거·완료 기준 |
| [자동 테스트 카탈로그](docs/07_TEST_CATALOG.md) | 현재 수집되는 97개 자동 테스트의 이름·목적·수량 구조 |
| [Project1 기준 자산 감사](docs/05_PROJECT1_BASELINE_AUDIT.md) | 기존 구현·13개 TC·Coverage·알려진 한계 |
| [QA 하네스 가이드](docs/06_TEST_HARNESS_GUIDE.md) | QA Drawer·Register·window.__vccs 사용 경계 |

## 용어

- **제품 기능 TC**: Agent 2가 만드는 조건·행동·기대 결과
- **자동화 코드 후보**: Agent 3가 Checkpoint를 통과한 TC를 Playwright Python으로 구현한 검증 전 코드
- **신규 자동화 후보 시험(Candidate Trial)**: Agent 3가 만든 자동화 코드 후보를 실제 화면에서 한 번 실행해 코드 동작·제품 관찰·복원·증거 생성을 확인하는 절차. 기존 관련 회귀 TC 실행과는 구분합니다.
- **초기 제품 기준 문서**: 화면 정책과 확인 가능한 제품 근거로 정리한 기대 동작으로, 현재 코드와 다르면 감사 문서에 구현 불일치를 남기는 변경 전 출발점
- **기존 기준 자동화 코드**: 프로젝트 1에서 사람이 작성했고 기존 회귀 검증에 재사용하는 Playwright 코드
- **제품 기능 회귀 후보**: 기존 7건 중 파이프라인 검증용 고정 사례와 근거 부족 TC를 제외한 테스트
- **파이프라인 검증용 고정 사례**: 결과 분류·차단 흐름을 확인하기 위해 의도적으로 유지하는 사례
- **실행 단위(Run)**: 변경 요청 한 건이 Agent 1부터 최종 보고까지 처리되는 한 번의 전체 실행
- **Checkpoint 통과**: 사람이 승인했다는 뜻이 아니라, 미리 정한 자동 검사 규칙을 충족했다는 뜻
- **최종 확인 사항**: 기대 결과와 실행 범위는 이미 확정되어 Run은 계속 진행하되, 정식 QA 자산으로 등록하기 전 사람이 마지막으로 살펴볼 메모입니다. 오류나 중단 사유가 아닙니다.
- **중단 확인 사항**: 기대 결과·경계값·실행 범위를 확정할 수 없어 자동 실행을 멈추고 사람 답변을 기다려야 하는 항목입니다.
- **조건부 검토**: 중단 확인 사항이 있을 때만 사람이 답변해 해당 단계부터 다시 진행하는 절차입니다.
- **정식 QA 자산 등록**: 검증이 끝난 SRS·TC·Playwright 코드를 다음 변경에서도 재사용할 공식 버전으로 저장하는 작업
- **자동화 지원 범위**: 코드가 현재 수행할 수 있는 범용 조작·관찰 목록. 내부 JSON의 기존 필드명 `capabilities`는 호환을 위해 유지합니다.
- **자동화 가능성 사전 확인**: TC가 기존 기능의 빠른 확인 대상인지, 처음 보는 UI를 동적으로 조사해야 하는지, 자동화 후보가 아닌지를 나누는 단계. 내부 파일명은 `agent3_eligibility.json`입니다.
- **검증 조건(Assertion)**: 실제 관찰값과 TC 기대 결과를 비교하는 코드입니다.
- **UI 확인 목록**: 실제 화면에서 찾은 Selector·표시·활성 상태·역할 정보입니다. 기존 문서의 UI Inventory와 같은 뜻입니다.
- **임시 시험 공간**: 원본과 분리해 신규 코드를 실행하는 폴더입니다. 컨테이너나 OS 보안 격리는 아닙니다.

## MVP 포함

- MODIFIED 요청 1건
- Agent 1·2 실제 모델 Adapter
- Agent 1→2 구조화 JSON 전달
- 신규 또는 수정 TC 최소 1건
- Agent 3 Playwright Python 코드 후보 최소 1건
- 기존 UI Selector와 테스트 전용 `window.__vccs` 읽기 인터페이스 활용
- CP1~3의 구조·근거·금지 패턴 검사
- 임시 폴더에서 후보 코드 1회 시험
- Checkpoint 통과 시 중간 승인 없이 자동 진행
- 실행 가능한 REVIEW는 최종 보고에 기록하고, 기대 결과를 확정할 수 없는 근거 부족·정책 충돌에만 조건부 사람 검토
- 검증 후보 변경 실행과 기존 검증 가능 회귀 TC 실행
- 규칙 기반 결과 분류와 Run 보고
- 정식 QA 자산 등록 승인 1회

## MVP 제외

- ADDED·DELETED 자동 처리
- 모든 TC 자동 생성·자동화
- 자유로운 Agent 토론
- 자연어 의미의 완전 자동 판정
- 무제한 자동 수정·Self-Healing
- 정식 QA 자산 자동 등록·버전 갱신
- Full Regression 전체 구현
- 다중 모델 비교·대규모 반복 평가
- 운영 장비·외부 서비스 연결

## 사실성 원칙

- 문서의 계획을 구현 완료로 표현하지 않습니다.
- Agent 1·2는 구조화 결과를 직접 생성하고, Agent 3 모델은 구조화 실행 계획만 생성합니다. Python 코드는 허용 목록 기반 컴파일러가 결정론적으로 만듭니다.
- Agent 4는 규칙 기반 분석기로 표시합니다.
- 기존 13건의 8 Pass·3 Fail·2 Skipped는 제품 회귀 성공률이 아니라 분류 데모 Dataset입니다.
- Register는 실제 프로토콜 레지스터가 아니라 HTML 시뮬레이터입니다.
- Project1 원본의 TC-ENV-000은 일반 테스트지만 V2 `execute` 단계에서는 이를 별도 사전 점검 Gate로 실행합니다.
- 정식 QA 자산 등록 승인 전 기존 SRS·TC·자동화를 덮어쓰지 않습니다.
- Project1은 Fixture 기반 Workflow Prototype이며, Agent 1·2 Live 생성과 Agent 3 코드 생성은 V2에서 보완합니다.
- 제품 SRS와 QA 하네스·기존 구현 감사 내용을 별도 문서로 관리합니다.

## 구현 순서

1. Product SRS 초기 기준 확정과 변경 요청 Schema
2. Agent 1 Adapter·CP1
3. Agent 2 Adapter·CP2·자동 인계
4. 실제 화면 확인 자료·Agent 3·CP3·격리 시험 — 구현
5. Agent 1→2→3 최소 Orchestrator — 구현, 중단·정상 완료 Live 검증 완료
6. 최종 확인 사항 최종 보고 이관 — 구현, 조건부 HUMAN_REVIEW 재개 기록은 미구현
7. 변경 검증·기존 회귀 후보 실행 — 구현, 기존 정상 Run에서 무API 실행 확인
8. Agent 4 입력 정합화·최종 보고 — 구현, 저장된 실제 Agent 1~3·회귀 Run 재연결과 새 API 전체 Run `RUN-20260817-054536-678B65`에서 CP4·최종 보고 PASS 확인
9. 정식 QA 자산 등록 승인 기록
10. 서로 다른 변경 요청 2건으로 End-to-End 재검증

## 저장소 구조

~~~text
qa-agent-pipeline-v2/
├─ docs/                         # SRS·MVP 설계·Agent/Checkpoint 계약·테스트 계획
├─ examples/
│  └─ results/                  # API 키를 제외한 공개 실행 결과
├─ src/
│  └─ qa_pipeline_v2.py         # 데이터 계약·Agent 1/2/3·CP1/2/3·CLI·후보/회귀 격리 실행
├─ tests/
│  └─ test_pipeline.py          # SRS·Agent·Checkpoint·실제 브라우저 격리 시험 회귀 테스트
├─ runs/                        # 로컬 원본 실행 결과(Git 제외)
├─ pyproject.toml               # 의존성·실행 명령·테스트 설정
└─ README.md
~~~

현재 구현 규모에서는 한 핵심 모듈과 한 테스트 파일이 역할을 찾기 가장 쉽습니다. Agent 3 격리 실행처럼 독립 보안 경계가 실제로 생길 때만 파일을 다시 분리합니다.

v2.2 Agent 1·2 공개 Live 산출물은 [examples/results/agent1-agent2-auto-temperature](examples/results/agent1-agent2-auto-temperature/)에서 확인할 수 있습니다. Agent 2의 1차 반려와 재작업 결과도 함께 보존했습니다.

현재 `agent3-3.4`까지 연결한 공개 Live 산출물은 [examples/results/agent1-agent2-agent3-auto-temperature](examples/results/agent1-agent2-agent3-auto-temperature/)에서 확인할 수 있습니다. Agent 3 계획은 첫 시도에 CP3 PASS했고 input 2,533·output 594·total 3,127 tokens를 사용했습니다. 신규 자동화 후보 시험은 UI `17.0°C`, 내부 `setTemp=17`, 성공 적용 Toast를 관찰해 ER-005·006·007을 `PRODUCT_MISMATCH_CANDIDATE`로 기록했습니다. 모든 인계 SHA-256과 Project1 대상 해시가 일치했고, 공개 텍스트와 Trace에서 비밀정보·로컬 경로 패턴은 탐지되지 않았습니다.

2026-08-15 Agent 3 진단 Live Run에서는 `TC-CAND-003`의 첫 계획이 잘못된 온도 Action Selector로 CP3 FAIL, 두 번째 계획이 CP3 PASS가 된 뒤 신규 자동화 후보 시험이 `PRODUCT_MISMATCH_CANDIDATE`를 반환했습니다. Project1의 기존 16~30°C 구현에서 17°C가 UI와 내부 `setTemp`에 반영돼 변경 요청의 18°C 하한 기대와 달랐고, Toast는 표시됐습니다. 이는 제품 결함 확정이 아니라 기대 결과 차이 후보입니다. 두 모델 호출의 실제 누적 사용량은 input 5,494·output 2,162·total 7,656 tokens였습니다. 이 Run은 연결 실패 오류 파일, 보완 전 `expected_text`, 마지막 시도만 집계한 Manifest가 함께 있어 공개하지 않습니다.

첫 보완 뒤 두 번째 진단 Live Run도 최종 CP3 PASS와 동일한 제품 불일치 후보를 재현했습니다. Action Selector와 `expected_text`는 바로 준수했지만 1차 계획이 내부 상태 대상을 `window.__vccs.devices[1].setTemp`로 확장해 CP3에서 차단됐고, 1회 재작업을 포함해 input 5,648·output 1,580·total 7,228 tokens를 사용했습니다. 이 결과를 반영해 Assertion 전략별 Selector를 고정하고, Trace ZIP의 사용자 홈·대상 파일·Trial Workspace 경로도 저장 전에 치환합니다. 두 진단 Run은 보완 전 증거이므로 공개하지 않습니다.

`agent3-3.2` 세 번째 진단 Live Run은 첫 계획에서 CP3 PASS했고 input 2,493·output 615·total 3,108 tokens를 사용했습니다. Trace 로컬 경로는 0건이었고 제품 관찰은 동일했습니다. 다만 계획의 `target_device_id=1`과 달리 `SELECT_DEVICE` Action 값이 `null`이어도 당시 CP3가 통과했고, 성공 적용 Toast를 차단 안내로 통과시킨 것을 후속 감사에서 발견했습니다. 현재 `agent3-3.4`는 대상 장비 값과 `TOAST_BLOCKING` 의미를 함께 검사합니다. 로컬 재시험에서는 ER-005·006뿐 아니라 `ER-007: toast does not indicate blocking`도 기록했습니다.

## Agent 1·2·3 로컬 실행

OpenAI Python SDK는 `OPENAI_API_KEY` 환경변수를 자동으로 읽습니다. API 키를 코드, JSON, Git 설정에 저장하지 않습니다.

~~~powershell
python -m pip install ".[agent3,test]"
$env:OPENAI_API_KEY="본인의 API 키"
python -m qa_pipeline_v2 agent1 --request examples/change_request.example.json
python -m qa_pipeline_v2 agent2 --run-id "Agent 1이 출력한 RUN-..."
python -m qa_pipeline_v2 agent3 --run-id "Agent 2가 완료된 RUN-..." --tc-id "TC-CAND-..." --target-html "프로젝트1 virtual-controller.html 경로" --preview-only
python -m qa_pipeline_v2 agent3 --run-id "Agent 2가 완료된 RUN-..." --tc-id "TC-CAND-..." --target-html "프로젝트1 virtual-controller.html 경로"

# 현재 CP2 결과에서 실행 가능한 TC를 자동 선택해 Agent 1→3을 한 번에 실행
python -m qa_pipeline_v2 pipeline --request "구체 변경 요청 JSON 경로" --target-html "프로젝트1 virtual-controller.html 경로"

# 완료된 Agent 3 Run의 현재 후보와 관련 기존 회귀를 실행(API 미호출)
python -m qa_pipeline_v2 execute --run-id "Agent 3가 완료된 RUN-..." --target-html "프로젝트1 virtual-controller.html 경로"

# 위 실행 결과를 규칙 기반으로 분석하고 CP4·최종 보고 생성(API 미호출, 테스트 재실행 없음)
python -m qa_pipeline_v2 agent4 --run-id "검증 실행이 완료된 RUN-..."
~~~

기본 모델은 `gpt-5.6-terra`입니다. 다른 모델을 시험할 때만 `--model` 또는 `OPENAI_MODEL`을 사용합니다.
`pipeline` 명령은 대상 HTML 존재를 모델 호출 전에 확인하고 Agent 1→2→3을 같은 Run ID로 순차 실행합니다. 각 단계의 비정상 종료 시 후속 Agent를 호출하지 않으며 `orchestrator_manifest.json`에 단계별 종료 코드와 기존 Manifest SHA-256을 기록합니다. `--tc-id`를 생략하면 **현재 Run의** CP2 후보를 자동화 가능성 사전 확인으로 평가합니다. 기존 지원 범위에 맞는 후보를 먼저 선택하고, 없으면 범용 UI 동적 조사가 필요한 후보를 선택합니다. 이전 Run의 임시 TC ID는 재사용하지 않습니다.

`execute`는 모델을 호출하지 않습니다. Agent 3 인계·해시·증거를 다시 확인하고, 저장 후보가 현재 결정론적 컴파일러 출력과 같을 때만 기존 시험 결과를 재사용합니다. 다르면 `validation_candidates/`에서 현재 후보를 다시 시험합니다. 이후 복사한 Project1 HTML·테스트와 중립 `conftest.py`를 임시 폴더에 두고 TC-ENV-000을 먼저 실행하며, 통과한 경우에만 Requirement ID로 선택한 기존 회귀를 실행합니다. Project1 원본 파일은 수정하지 않습니다.

이 명령은 여러 실제 모델 호출을 연속 수행하므로 API 승인과 비용 확인 후 사용합니다. `examples/change_request.example.json`은 `after_value`가 자리표시자이므로 실제 Live에서 CP1 `PASS + PAUSE`가 되었고 Agent 2·3은 호출되지 않았습니다. 구체 요청 Run `RUN-20260815-063800-3B624C`은 Agent 1·2까지 PASS했지만 당시 지정한 `TC-CAND-003`이 새 Run에서는 LOCAL TC여서 Agent 3 API 전에 `NOT_AUTOMATABLE`로 중단됐습니다. Agent 1 1회·Agent 2 2회의 실제 누적 사용량은 total 34,814 tokens였고 Project1은 변경되지 않았습니다. 이 결과를 반영해 Agent 2 Prompt `agent2-2.3`은 CENTRAL 변경 검증에 단일 장비 자동화 후보를 최소 한 건 포함하도록 명시하고, Orchestrator는 현재 Run에서 적격 TC를 자동 선택합니다.

보완 후 Run `RUN-20260815-090130-F023B1`은 Agent 1 `PASS + CONTINUE`였지만 Agent 2가 첫 시도의 중복·추적 오류를 재작업하면서 LOCAL 직접 변경 Requirement 연결을 누락해 최종 CP2 FAIL로 중단됐습니다. Agent 1 1회·Agent 2 2회의 실제 누적 사용량은 total 30,227 tokens였고 Agent 3는 호출되지 않았습니다. 이 감사에서 Agent 1·2 Manifest의 최상위 `usage`도 마지막 시도만 기록하던 문제를 찾아 계약 2.3부터 모든 시도의 누적으로 바꾸고 `final_attempt_usage`를 분리했습니다.

Agent 2 재작업에는 실패 규칙만 보내던 방식도 보완했습니다. 현재는 CP2 전체 `rule_id + PASS/FAIL + message`를 전달하고 PASS 규칙과 근거를 보존해 새 FAIL을 만들지 않도록 명시합니다. 재작업 횟수는 최대 1회로 유지합니다.

네 번째 Orchestrator `RUN-20260815-092107-0C075E`은 Agent 1·2·3과 CP1·2·3을 모두 통과하고 AUTO가 `TC-CAND-001`을 선택해 신규 자동화 후보 시험 `PASS`로 완료됐습니다. Agent 1 total 5,607, Agent 2 두 시도 누적 27,752, Agent 3 total 3,194로 전체 36,553 tokens를 사용했습니다. 모든 단계·선택·시험 Manifest SHA-256과 Project1 대상 해시가 일치했고, 텍스트·Trace에서 비밀정보와 로컬 경로 패턴은 탐지되지 않았습니다. 후속 감사에서 복원 명령만 실행하고 초기 온도를 재확인하지 않던 틈을 발견해 CP3가 초기값 복원 Action을 검사하고 컴파일러가 복원 후 UI·내부 `setTemp`를 확인하도록 보완했으며, 동일 계획의 무API 로컬 재시험도 PASS했습니다.

2026-08-17 범용 전원 선택·적용 진단은 기존 SRS의 `REQ-POWER-001`과 일회성 개발 UI를 사용해 Agent 1→2→3 실제 연결을 실행했습니다. Agent 1은 첫 시도 PASS, Agent 2는 중복·추적 실패를 1회 재작업해 PASS했습니다. Agent 3 Live에서 비 HVAC 상태값 오인, 한국어 조사 의미 연결, 알림 문장 전체 오사용과 범용 복원 미확인을 찾아 `agent3-3.7`까지 보완했습니다. 최종 호출은 첫 계획에서 CP3 10개 규칙, 결정론적 Python, 브라우저 시험과 선택값·화면 상태·내부 `status`의 STOP 복원을 모두 PASS했고 4,391 tokens를 사용했습니다. 연결 오류와 진단 재시도를 포함한 실제 모델 누적은 44,334 tokens입니다. 이 Run은 로컬 진단 증거이며 아직 `examples/results/`에 공개 복사하지 않았습니다.

Agent 3 모델 호출에는 시스템 지침, 선택한 CP2 TC, 관련 SRS 행, 대상 파일명·SHA-256, 페이지 제목, **해당 TC에 필요한** Selector별 tag·text·visible·enabled·action_hint와 하네스 키만 전송됩니다. API 키, 로컬 절대경로, HTML 원문, Screenshot과 Trace는 보내지 않습니다. 먼저 `--preview-only`로 `agent3_model_input_preview.json`을 확인해야 합니다. Preview는 API 키와 모델 Client를 요구하지 않으며 실제 API를 호출하지 않습니다.

현재 Agent 3는 기존 온도 제어에는 검증된 전용 조작을 재사용하고, 처음 보는 기능에는 `CLICK`, `FILL`, `SELECT_OPTION`, `CHECK`, `UNCHECK`와 범용 화면·내부 상태 검증을 사용합니다. 장비 내부 상태는 UI 조사에서 실제로 확인한 스칼라 필드명만 목록으로 전송하며, TC Expected Result에 그 필드명과 값이 함께 있는 경우에만 `INTERNAL_DEVICE_FIELDS_EQUALS`가 `[{"field_name":"mode","expected_value":"AUTO"}]` 같은 고정 항목 목록으로 대상 장비의 해당 필드를 함께 비교합니다. 모델은 임의 JavaScript·경로·필드를 만들 수 없습니다. TC 단계와 요소 명칭의 연결 및 Expected Result와 기대값 근거를 CP3가 검사합니다. 드래그·Canvas처럼 새로운 기술이 필요하면 억지 코드를 만들지 않고 `AUTOMATION_SUPPORT_EXTENSION_REQUIRED`로 사람 검토에 넘깁니다.

Agent 3 CLI는 시험 `PASS`와 `PRODUCT_MISMATCH_CANDIDATE`만 정상 완료(`exit code 0`)로 반환합니다. `NOT_AUTOMATABLE`, `AUTOMATION_ERROR`, `ENVIRONMENT_ERROR`, `TIMEOUT`, CP3 실패와 시험 미실행은 제품 판정에 사용할 수 없으므로 실패 종료(`exit code 2`)합니다. CP3 계획 위반은 최대 한 번 재작성하지만 시험 실행의 기술 오류 자동 수정은 아직 구현하지 않았습니다.

기존 온도 전용 검증은 CP3가 행동·검증 전략별 Selector를 계속 고정합니다. 복합 장비 상태는 고정된 `window.__vccs.devices` 대상과 UI 조사에서 확인된 필드명으로만 비교합니다. 신규 범용 검증은 실제 UI 확인 목록의 Selector와 읽기 전용 내부 상태 경로만 사용합니다. 모델 호출 실패로 `agent3_error.json`이 생성된 Run은 종료된 시도로 간주하므로 재실행에는 새 임시 시험 공간이 필요합니다. 시험 자식 Python은 Windows 시작 호환성을 유지한 채 stdout·stderr를 UTF-8로 고정하고, Trace ZIP은 알려진 로컬 경로 표현을 원자적으로 치환합니다.

현재 UI 조사는 두 경로입니다. 이미 아는 기능은 선택 TC에 필요한 요소만 좁게 확인하고, 처음 보는 기능은 안정적인 ID·`data-testid`·접근성 이름을 가진 범용 조작·상태 요소를 최대 120개까지 한 번 동적으로 확인합니다. 전체 HTML은 모델에 보내지 않습니다. 실제 제어 동작과 기대 결과는 이후 신규 자동화 후보 시험에서 검증합니다. 임시 시험 공간은 제한 환경변수·별도 subprocess를 사용하지만 네트워크 차단이나 컨테이너·OS 권한 분리를 제공하는 보안 Sandbox는 아닙니다.


결과는 Git에서 제외되는 `runs/RUN-.../`에 저장됩니다.

- `request.json`: 실제 입력과 SHA-256 검증 대상
- `agent1_change_analysis.json`: 모델의 구조화 분석
- `checkpoint1.json`: 규칙별 PASS·REVIEW·FAIL과 `최종_확인_사항`
- `run_manifest.json`: 모델·Prompt 버전·상태·인계 상태, 누적/마지막 시도 토큰과 요청/SRS/Agent 1/CP1 SHA-256
- `agent2_test_design.json`: Agent 2가 만든 제품 기능 TC 후보와 `최종_확인_사항`·`중단_확인_사항`
- `checkpoint2.json`: CP2 규칙별 판정
- `agent2_manifest.json`: Agent 2 상태·누적/마지막 시도 토큰과 앞 단계·Agent 2·CP2 SHA-256 체인
- `agent3_selection.json`: 전체 실행 조정기의 현재 CP2 후보별 자동화 가능성 사전 확인과 선택 결과
- `agent3_eligibility.json`: 자동화 가능성 사전 확인 결과. 기존 빠른 경로·범용 UI 동적 조사 필요·자동화 후보 아님을 구분
- `agent3_model_input_preview.json`: 실제 API 전송 예정 데이터와 제외 항목
- `agent3_ui_observation.json`: 파일명·SHA-256과 실제 확인 Selector·하네스 목록
- `agent3_automation_plan.json`: 모델이 만든 실행 가능한 코드 의도. 범용 조작으로 부족하면 자동화 지원 범위 확장 사유만 기록
- `candidates/test_<tc-id>.py`: 허용 목록 컴파일러가 만든 Playwright 후보
- `checkpoint3.json`: 계획·코드 추적성과 금지 패턴 검사 결과
- `agent3_trial.json`: 격리 시험 결과와 증거 완전성
- `agent3_manifest.json`: Agent 2 입력 체인·자동화 가능성 사전 확인·UI·코드 의도·코드·시험 SHA-256과 모델 사용량
- `validation_candidate_trial.json`: 현재 컴파일러 출력이 달라졌을 때 수행한 무API 후보 재시험 결과
- `validation_execution.json`: 신규 후보·환경 사전 점검·선택된 기존 회귀의 중립 실행 결과
- `validation_manifest.json`: Agent 3 입력, 현재 후보·재시험, Project1 기준 파일과 실행 결과 SHA-256
- `agent4_analysis.json`: 중립 결과 집계와 규칙 기반 `검토_항목`
- `checkpoint4.json`: Run ID·해시·중복 TC·실패 근거·제품/고정 사례 분리 검사
- `final_report.json`: CP4와 일치하는 실행 합계·`검토_항목`·`최종_확인_사항`·PASS/HOLD/HUMAN_REVIEW 권고

예시 JSON의 변경 내용은 연결 확인용이며 대표 요구사항으로 고정하지 않습니다.

## MVP 완료 기준

- 서로 다른 요청에서 서로 다른 Agent 1·2 결과가 생성됩니다.
- Agent 1 시작 시 저장한 요청·SRS 스냅샷·분석·CP1의 SHA-256이 Agent 2 실행 전에 재검증됩니다.
- TC Step·Expected Result가 코드 Assertion에 추적됩니다.
- 후보는 원본과 분리된 임시 위치에서 실행됩니다.
- CP가 잡지 못하는 의미 판단만 조건부 사람 검토로 전환됩니다.
- 제품·자동화·환경 오류를 구분합니다.
- 실행 결과와 보고 수치가 일치합니다.
