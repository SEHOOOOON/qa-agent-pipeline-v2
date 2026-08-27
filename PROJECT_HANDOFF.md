# QA Agent Pipeline V2 인계 문서

최종 갱신: 2026-08-27

## 1. 현재 방향

이 저장소는 프로젝트 1의 Fixture 기반 Workflow Prototype을 실제 모델 기반 QA 실행으로 보완합니다. V1의 4-Agent 절차와 QA 기준을 유지하고, 실제 모델 연결에 필요한 구조화 계약·제한된 코드 생성·실행 증거만 추가합니다.

현재 사용자 흐름:

~~~text
변경 요청
  → Agent 1 요구사항 분석
  → Agent 2 기존 TC 대조·변경분 TC 설계
  → Agent 3 신규·수정 후보 자동화·시험
  → 관련 기존 회귀 실행
  → Agent 4 규칙 기반 분류·최종 보고·Slack·Notion 전달
  → 사람의 최종 확인
~~~

## 2. 현재 구현 상태

| 영역 | 상태 |
|---|---|
| Agent 1 / CP1 | 실제 구조화 모델 호출, Requirement 영향도·확정 범위와 정보 부족 분리, 자동화 지원 여부와 영향도 판단 분리, 최대 1회 재작업 |
| Agent 2 / CP2 | 기존 TC의 Requirement·검증 동작 대조, Agent 1 VERIFY 회귀 결정론적 보충, 변경분 후보·관련 기존 TC 분리, Condition 처리 경로, 업무 규칙 묶음, 3단계 QA 기준·추적성·독립성·이중 검증 |
| Agent 3 / CP3 | 신규·수정 후보만 TC별 모델 호출, 필요한 UI 확인, 조건 순서를 보존한 계획, 결정론적 Python, 제한된 실행 전 HVAC 상태 저장·복원, 시험 증거 |
| 변경 검증 | 완료 후보 재검사, 환경 사전 점검, Agent 2가 선택한 관련 기존 TC만 회귀 |
| Agent 4 / CP4 | 규칙 기반 원인 분류, 전체 산출물·증거·집계 정합성 검사, 사람 최종 검토 양식, Slack·Notion Dry-run/명시적 전송 |
| 다중 TC | 실행 가능 TC는 계속 실행, 불명확·미지원 TC만 제외해 최종 보고 |
| 제품 경계 | 중앙 관제 패널만 지원, 벽면 리모컨·로컬 경로 제외 |

## 3. 2026-08-25 단순화

현재 실행에 쓰이지 않던 과거 Agent 3 일괄 모델 호출 계층을 제거했습니다.

제거:

- Agent3BatchAutomationPlans
- Agent3BatchResponse
- PreparedAgent3Batch
- OpenAIAgent3.plan_many
- 일괄 입력·계획·모델 호출 산출물과 전용 인계 검증
- 현재 문서의 중단 Run 재개·정식 자산 등록 필수 절차 표현
- README의 긴 진단 Run 연대기

유지:

- 실행 가능한 여러 TC의 독립 처리
- 3단계 QA 기준과 TC 독립성
- 조건부 UI·내부 상태 이중 검증
- 처음 보는 유사 UI의 제한적 동적 조사
- CP3·컴파일러·증거·SHA-256 안전장치
- 관련 기존 회귀와 Agent 4 분류

새 실행 요약 파일은 agent3_run_summary.json입니다. 과거 공개 Run 파일은 역사적 증거로 남지만 현재 실행 계약에서 읽지 않습니다.

## 4. 현재 검증

- python -m pytest: 145건 통과
- python -m pytest --collect-only -q: 145건
- 첫 Live `RUN-20260825-122801-18C8C0`: Agent 2 독립성 문구 오탐으로 중단, Agent 1·2 35,167 tokens
- 보완 Live `RUN-20260825-123313-41B570`: Agent 1·2 PASS, Agent 3 완료 6건·자동화 제외 3건, 환경 점검·관련 기존 회귀 3건·CP4 PASS
- 보완 Live 실제 모델 사용량: Agent 1 6,218 + Agent 2 29,228 + Agent 3 58,795 = 94,241 tokens
- 묶음 계약 첫 Live `RUN-20260826-111634-2DA7C8`: 모드가 조건 문맥인 UI 기대 결과를 CP2-006이 복합 관찰로 오탐해 중단, Agent 1·2 39,338 tokens
- 오탐 보완 Live `RUN-20260826-112212-6F777F`: Agent 1·2 PASS, 업무 규칙 TC 4건 생성, Agent 3 실행 1건·자동화 제외 3건, 환경 점검 1건·관련 기존 회귀 2건 PASS, CP4 PASS·최종 `HUMAN_REVIEW`
- 오탐 보완 Live 실제 모델 사용량: Agent 1 6,093 + Agent 2 30,394 + Agent 3 40,330 = 76,817 tokens
- 기존 TC 검증 동작 계약 첫 Live `RUN-20260827-113728-D0832E`: Agent 2가 잠금 변경분 TC 1건을 만들었으나 CP2-010의 무관한 모드·온도 TestData 강제로 중단, 31,052 tokens
- CP2 보완 Live `RUN-20260827-114232-78DC4E`: Agent 2 첫 시도 PASS·변경분 TC 1건·`TC-LOCK-001` 회귀 선택, Agent 3가 공통 적용 버튼 관찰 누락으로 자동화 제외, 36,526 tokens
- 최종 Live `RUN-20260827-114925-507176`: Agent 1 REVIEW·CONTINUE, Agent 2 첫 시도 PASS·변경분 TC 1건·기존 회귀 2건 선택, Agent 3 CP3 PASS·실제 후보 시험 완료·자동화 제외 0건
- 최종 Live 실행 결과: 내부 `locked=true` PASS, 온도 내림·올림 버튼은 실제 `enabled=True`로 제품 불일치 후보, 환경 점검과 `TC-LOCK-001`·`TC-MODE-001` 회귀 PASS, CP4 PASS·최종 `HUMAN_REVIEW`
- 최종 Live 실제 모델 사용량: Agent 1 6,419 + Agent 2 11,119 + Agent 3 18,589 = 36,127 tokens. 이번 진단 3개 Run 합계 103,705 tokens
- 최종 Run의 최초 Slack·Notion 결과는 PREVIEW로 보존하고, 사용자 승인 뒤 `ATTEMPT-20260827-120544-570581-57E798`에서 Slack 1건·Notion TC-ID Upsert 4건을 실제 `SENT`로 완료
- 실제 전송은 V1 `.env` 자격정보를 프로세스에서만 읽었으며 별도 시도 증거의 비밀정보·로컬 절대경로 0건과 이전 Preview SHA-256 연결을 확인
- 같은 Run에 `사람_최종_검토.md`와 Manifest 생성: 잠금 뒤 온도 버튼 `enabled=True` 2건, 통과한 내부 `locked=true`, 증거 링크, 사람 판정 선택지·검토자·기한란과 자동 생성 원본 보고 SHA-256 포함. 사람이 작성한 뒤에는 자동 갱신이 판단 기록을 덮어쓰지 않음
- 푸시 전 최종 감사: 자동 테스트 145건 통과, 테스트 카탈로그 145건 일치, Python 컴파일·`git diff --check` 통과, 실제 키·인증정보 포함 URL 0건, Project1 Git 무변경과 대상 HTML SHA-256 유지
- GitHub 공개 정합성: `examples/results/agent1-agent2-agent3-agent4-lock-disable/`에 최신 Run의 단계별 상태·핵심 관찰·사람 검토 공개본·Slack/Notion 전송 상태·원본 및 공개 파일 SHA-256을 포함한 최소 증거 묶음 추가
- Git 반영 기준: 이 문서의 최신 수치, 구현, 자동 테스트 카탈로그와 공개 증거 묶음을 같은 커밋으로 `main`에 반영

과거 일괄 호출 전용 테스트 2건을 제거했고, Live에서 발견한 CP2 독립성 문구 오탐 회귀 테스트 2건을 추가했습니다. 2026-08-26에는 동일 업무 규칙의 조건 묶음 CP2 테스트 2건과 Agent 3 조건별 Assertion 배치 테스트 2건을 추가했습니다. 같은 날 CP2-006이 `FAN 모드에서 버튼은 비활성화된다`처럼 모드를 조건으로 쓴 문장을 별도 모드 표시 검증으로 오인하지 않도록 좁혔고, 실제 복합 관찰은 계속 차단합니다. 현재 TC별 실행·인계·Agent 4 검증은 유지합니다.

2026-08-26 온도 정책 Live의 실행된 제품 결과는 신규 후보 1건과 관련 회귀 2건입니다. 관련 회귀 2건은 PASS했지만 신규 후보는 차단돼야 할 17°C가 적용되고 성공 Toast가 표시되어 제품 불일치 후보가 됐습니다. 당시 묶음 TC 3건은 실행 전 모드·온도를 동적으로 기억해 복원하는 안전한 계약이 없어 제외됐습니다. 현재는 V1 중앙 관제 온도·모드 흐름에 한해 실행 직전 `mode`·`setTemp`를 저장하고 조건 실행 뒤 원래 값으로 복원·적용·재검증하는 계약을 구현했으며 실제 Playwright 시험으로 통과했습니다.

같은 감사에서 Agent 2 Prompt가 “기존 TC 자산이 없다”고 가정해 유지 조건까지 `RELATED_REGRESSION` 후보로 다시 만들고 Agent 3로 보내는 V1 이탈을 확인했습니다. 현재 계약은 기존 TC ID·Requirement뿐 아니라 V1 코드에서 확인한 검증 동작을 Agent 2 입력으로 제공합니다. 검증 동작이 현재 조건을 그대로 확인할 때만 `관련_기존_TC`로 선택하고, 부족한 변경분만 `test_cases`에 둡니다. 모든 확정 Condition은 두 경로 중 최소 한 곳에 연결되어야 하며, 재사용할 수 없는 기존 TC는 억지로 선택하지 않고 이유를 남깁니다. CP2-016과 Agent 3 선택 방어 규칙은 기존 회귀 재구현을 차단하고, execute는 새 Run에서 명시적으로 선택된 기존 TC만 실행합니다. 최종 Live에서 변경분 후보 1건, 기존 `TC-LOCK-001`·`TC-MODE-001` 회귀 분리와 실제 실행을 확인했습니다. 이후 Agent 1이 `VERIFY`로 확정한 유지 Requirement의 기존 TC는 결정론적으로 보충하도록 해 보조 회귀의 조용한 누락을 줄였습니다. 직접 변경된 Requirement의 기존 TC 호환성은 계속 검증 동작 의미 대조를 따릅니다.

## 5. 중요한 제품·사실성 규칙

- Project1은 읽기 전용 기준 자산입니다.
- Agent 1~3만 생성형 모델을 사용합니다.
- Agent 3 모델은 계획을 만들고 Python은 허용 목록 컴파일러가 생성합니다.
- Agent 4는 규칙 기반 분석기입니다.
- Checkpoint PASS는 사람 승인과 다릅니다.
- PRODUCT_MISMATCH_CANDIDATE는 결함 확정이 아닙니다.
- 중앙 관제 패널 외 로컬·벽면 리모컨 경로를 만들지 않습니다.
- 예시 기능과 값은 일반 규칙으로 하드코딩하지 않습니다.
- 제품 규칙은 변경 요청·SRS·승인 TC에서 받고, 신규 기능은 관찰된 UI 기반 공통 조작·검증으로 구현합니다.
- TC는 입력값 하나가 아니라 하나의 관제점·업무 규칙 단위로 만들며, 관련 조건은 중간 초기화와 조건별 판정 시점을 명시해 한 TC로 묶을 수 있습니다.
- Agent 3는 처음 보는 기능명이라는 이유로 제외하지 않고 실제 관찰한 범용 UI 조작을 먼저 사용합니다. 묶음 TC는 각 조건 직후 Assertion을 실행합니다.
- Agent 3는 변경으로 새로 필요하거나 수정되는 후보만 구현하며, 유지되는 기존 TC는 다시 만들지 않고 관련 회귀 단계에서 기존 코드를 실행합니다.
- Agent 4 외부 보고는 CP4 PASS 뒤에만 허용되고 기본은 Dry-run입니다. 실제 Slack·Notion 전송은 `--send`에서만 수행합니다.
- V1 온도 호환 코드는 해당 TC에서만 생성하며 범용 TC 코드에는 사용하지 않는 제품 전용 Selector를 넣지 않습니다.
- OPENAI_API_KEY와 로컬 절대경로를 산출물·전송 데이터에 넣지 않습니다.

## 6. 주요 파일

| 파일 | 역할 |
|---|---|
| README.md | 현재 목적·흐름·실행 방법 |
| docs/01_PRODUCT_SRS.md | 제품 기대 동작 |
| docs/02_V2_MVP_DESIGN.md | V1 대비 유지·추가·제외 범위 |
| docs/03_AGENT_AND_CHECKPOINT_SPEC.md | 단계별 계약 |
| docs/04_TEST_AND_TRACEABILITY_PLAN.md | 검증·추적 체인 |
| docs/05_PROJECT1_BASELINE_AUDIT.md | Project1 기준 자산과 한계 |
| docs/06_TEST_HARNESS_GUIDE.md | UI·내부 상태 확인 경계 |
| docs/07_TEST_CATALOG.md | 자동 테스트 목록 |
| src/qa_pipeline_v2.py | 전체 구현 |
| tests/test_pipeline.py | 자동 테스트 |

## 7. 다음 작업

1. `RUN-20260827-114925-507176/사람_최종_검토.md`에서 FIND-001을 사람이 최종 판정
2. 새 묶음 온도 정책을 실제 모델로 다시 실행할 필요가 있으면 API 비용 승인 뒤 `restore_observed_hvac_state` 생성 여부 확인
3. 사람 판정을 GitHub 공개 이력에도 남길 필요가 있으면 공개 검토본의 `PENDING` 상태를 별도 변경으로 갱신

API 호출, 커밋, 푸시는 사용자의 명시적 지시가 있을 때만 수행합니다.

## 8. 작업 시작 체크

다음 작업자는 AGENTS.md, 이 문서, DECISION_LOG.md, README.md를 모두 읽고 Git 상태를 먼저 확인해야 합니다. 미커밋 변경은 사용자 작업으로 보고 보존합니다.
