# QA Agent Pipeline V2 인계 문서

최종 갱신: 2026-08-30

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
| V2 기준 실행 자산 | V1 커밋 `ba62b611...`의 HTML·Pytest 설정·사람 작성 기존 회귀 테스트 네 파일만 `product_baseline/`에 가져옴 |
| 중앙제어 Run 화면 | 저장 결과 조회·API 새 실행·후보 공식 자산 판단을 분리. 팀장·Agent 1~4 버튼이 실제 Run 산출물 조회, 새 API 실행과 사람 자산 승인은 각각 기본 잠금, Agent 4 외부 보고는 미리보기 고정 |

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

- python -m pytest: 167건 통과
- python -m pytest --collect-only -q: 167건
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
- 2026-08-29 V2 기준 실행 자산 원복: HTML·Pytest 설정·기존 테스트 네 파일을 V2에 유지해 외부 V1 경로 없이 독립 실행, 포트폴리오·보고서·Agent 4·`.env`는 제외, Project1 Git 무변경
- 성공 Live `RUN-20260829-035050-2FF59B`: HIGH 풍량의 UI 한글 라벨 `강풍`·내부 `fanSpeed=HIGH`를 적용 직후 함께 확인하고 LOW 복원까지 완료. Agent 1 REVIEW·CONTINUE, CP2·CP3·후보 Trial·환경 점검·CP4 PASS, 최종 권고 PASS, 검토 항목·자동화 제외 0건
- 성공 Live 실제 모델 사용량: Agent 1 5,393 + Agent 2 9,289 + Agent 3 18,756 = 33,438 tokens. Slack·Notion은 PREVIEW이며 외부 전송하지 않음
- Live에서 발견한 절차 손실과 동적 UI 오탐 보완: 시험 준비·복원을 제품 기대 결과나 제외 범위로 바꾸지 않고 TC 절차로 보존하며, 실행 전 문구가 아직 없는 대상 장비 카드도 정확한 대상 Selector에 한해 변경 후 검증 허용
- V2 중앙제어 실제 Run 연결: `qa_pipeline_ui` 조회 전용 서버와 Agent 1~4 단계 패널을 추가해 성공 Run `RUN-20260829-035050-2FF59B`을 표시. `--allow-live-run` 없이는 API 실행 불가, 외부 보고는 항상 Dry-run
- 최신 UI Live `RUN-20260829-054330-A18942`: Agent 1 재작업 1회 뒤 REVIEW·CONTINUE, Agent 2·CP2 PASS, Agent 3 CP3·후보 Trial PASS, 환경 점검 PASS, Agent 4·CP4·최종 권고 PASS. Slack·Notion PREVIEW, 자동화 제외·검토 항목 0건, CP1 최종 확인 1건
- 최신 Live 모델 사용량: Agent 1 11,069 + Agent 2 9,699 + Agent 3 18,885 = 39,653 tokens
- 실행 안정성 보완: Candidate Trial 기본 제한 90초, 시간 초과 시 pytest·Playwright 자식 프로세스 트리 정리, 불완전·미정제 Trace 폐기, 여러 로컬 브리지 사이 저장소 단위 Live Run 잠금, UI 비용 확인 상태의 자동 새로고침 보존
- V2 기준 제품의 기존 13개 회귀 전체 확인: 정상 기능 8건 PASS, 정보 부족·미실행 Fixture 2건 SKIP, 의도적 환경 오류·자동화 오류 Fixture 2건과 기존 AUTO 18°C 하한 제품 불일치 후보 1건 FAIL. `docs/05_PROJECT1_BASELINE_AUDIT.md`의 기존 분류와 일치하며 Run 패널 추가로 새로 깨진 정상 기능은 없음
- 후보 공식 자산 흐름: `--allow-asset-approval`에서만 승인·보류 허용. 실패·증거 누락·대상 HTML 변경 후보는 등록 차단하고, HTML 변경 시 API 없이 후보만 별도 재검증. 승인 시 `approved_assets/`에 TC·Python·Registry 해시를 남기며 기존 Run·사람 회귀는 비수정
- 최신 성공 후보 공식 등록: 중앙제어 Run·승인 UI 변경 후 `RUN-20260829-054330-A18942 / TC-CAND-001`을 현재 HTML에서 API 없이 다시 실행해 54,781ms PASS, Screenshot·Trace 포함 완전한 증거와 비밀정보·로컬 경로 0건 확인. 오세훈 검토자 승인으로 `TC-V2-001`을 `approved_assets/`에 등록했고 복사된 자동화 파일도 현재 V2 HTML에서 독립 실행 PASS
- 공식 자산 재사용 연결 완료: Registry의 TC·Python·SRS 개정 기록 SHA-256과 구조화 TC를 확인해 다음 Agent 2의 기존 TC 대조 입력 및 Run Snapshot에 합침. 선택된 공식 TC는 `execute`가 승인 Python으로 실행하고 실행 중 해시 불변도 다시 확인함. `TC-V2-001`을 이 경로로 실제 Playwright 재실행해 PASS·Screenshot·Trace를 확인
- SRS 개정 연결 완료: MODIFIED·UPDATE_REQUIRED Requirement마다 Agent 2가 개정 전·후 인수 기준과 Condition 근거를 만들고 CP2가 검사함. 제안은 검증 실행·Agent 4·사람 최종 검토·중앙제어 승인 화면까지 전달되며, 별도 SRS 승인 뒤에만 공식 TC와 기준 SRS를 함께 반영하고 Run·공식 개정 기록에 전·후 SHA-256을 남김
- 기존 `TC-V2-001` 승인 시 누락됐던 기준 문서 변경은 `REQ-CONTROL-001`, `REQ-FAN-001`, `REQ-STATE-001`의 관찰된 UI·내부 상태 의미를 반영했고 `approved_assets/srs_revisions/SRS-REV-001.json` 및 Registry 해시로 연결함

과거 일괄 호출 전용 테스트 2건을 제거했고, Live에서 발견한 CP2 독립성 문구 오탐 회귀 테스트 2건을 추가했습니다. 2026-08-26에는 동일 업무 규칙의 조건 묶음 CP2 테스트 2건과 Agent 3 조건별 Assertion 배치 테스트 2건을 추가했습니다. 같은 날 CP2-006이 `FAN 모드에서 버튼은 비활성화된다`처럼 모드를 조건으로 쓴 문장을 별도 모드 표시 검증으로 오인하지 않도록 좁혔고, 실제 복합 관찰은 계속 차단합니다. 현재 TC별 실행·인계·Agent 4 검증은 유지합니다.

2026-08-26 온도 정책 Live의 실행된 제품 결과는 신규 후보 1건과 관련 회귀 2건입니다. 관련 회귀 2건은 PASS했지만 신규 후보는 차단돼야 할 17°C가 적용되고 성공 Toast가 표시되어 제품 불일치 후보가 됐습니다. 당시 묶음 TC 3건은 실행 전 모드·온도를 동적으로 기억해 복원하는 안전한 계약이 없어 제외됐습니다. 현재는 V1 중앙 관제 온도·모드 흐름에 한해 실행 직전 `mode`·`setTemp`를 저장하고 조건 실행 뒤 원래 값으로 복원·적용·재검증하는 계약을 구현했으며 실제 Playwright 시험으로 통과했습니다.

같은 감사에서 Agent 2 Prompt가 “기존 TC 자산이 없다”고 가정해 유지 조건까지 `RELATED_REGRESSION` 후보로 다시 만들고 Agent 3로 보내는 V1 이탈을 확인했습니다. 현재 계약은 기존 TC ID·Requirement뿐 아니라 V1 코드에서 확인한 검증 동작을 Agent 2 입력으로 제공합니다. 검증 동작이 현재 조건을 그대로 확인할 때만 `관련_기존_TC`로 선택하고, 부족한 변경분만 `test_cases`에 둡니다. 모든 확정 Condition은 두 경로 중 최소 한 곳에 연결되어야 하며, 재사용할 수 없는 기존 TC는 억지로 선택하지 않고 이유를 남깁니다. CP2-016과 Agent 3 선택 방어 규칙은 기존 회귀 재구현을 차단하고, execute는 새 Run에서 명시적으로 선택된 기존 TC만 실행합니다. 최종 Live에서 변경분 후보 1건, 기존 `TC-LOCK-001`·`TC-MODE-001` 회귀 분리와 실제 실행을 확인했습니다. 이후 Agent 1이 `VERIFY`로 확정한 유지 Requirement의 기존 TC는 결정론적으로 보충하도록 해 보조 회귀의 조용한 누락을 줄였습니다. 직접 변경된 Requirement의 기존 TC 호환성은 계속 검증 동작 의미 대조를 따릅니다.

## 5. 중요한 제품·사실성 규칙

- Project1은 읽기 전용 기준 자산입니다.
- V2 Agent 3 실행·향후 제품 보완의 대상은 `product_baseline/virtual-controller.html`입니다.
- 기존 TC·Playwright 자동화는 `product_baseline/tests/test_controller.py`에서 선택 실행하며, 실제 실행은 원본과 분리된 임시 Workspace에서 수행합니다.
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
| product_baseline/ | V2 가상 중앙제어 HTML·Pytest 설정·사람 작성 기존 회귀 테스트 |
| src/qa_pipeline_v2.py | 전체 구현 |
| src/qa_pipeline_ui.py | 중앙제어 HTML 정적 제공, 실제 Run 요약, 선택적 Live 실행 연결부 |
| tests/test_pipeline.py | 자동 테스트 |

## 7. 다음 작업

1. 새 계약을 실제 API Live Run에서 한 번 확인해 Agent 2의 SRS 개정 제안과 승인 공식 TC 대조가 실제 모델 출력에서도 유지되는지 검증
2. 성공 Run 최소 공개 증거 묶음과 로컬 실제 Run·승인 시연 영상을 만들되, Slack·Notion PREVIEW와 실제 전송을 구분해 표시
3. 잠금 Run은 실패 증거로 유지하고 `RUN-20260827-114925-507176/사람_최종_검토.md`의 FIND-001을 사람이 최종 판정

API 호출, 커밋, 푸시는 사용자의 명시적 지시가 있을 때만 수행합니다.

## 8. 작업 시작 체크

다음 작업자는 AGENTS.md, 이 문서, DECISION_LOG.md, README.md를 모두 읽고 Git 상태를 먼저 확인해야 합니다. 미커밋 변경은 사용자 작업으로 보고 보존합니다.
