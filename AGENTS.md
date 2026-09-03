# QA Agent Pipeline V2 작업 규칙

이 문서는 이 저장소에서 작업하는 모든 Codex 작업에 적용됩니다. 새 작업을 시작하면 먼저 이 문서와 `PROJECT_HANDOFF.md`, `DECISION_LOG.md`, `README.md`를 읽고 현재 Git 상태를 확인합니다.

## 1. 사용자와 프로젝트 방향

- 이 저장소의 목적은 프로젝트 1의 고정 산출물 시연을 실제 모델 기반 변경관리 QA 파이프라인으로 보완하는 것입니다.
- 핵심 가치는 기능 수가 아니라 **입력 → Agent 산출물 → Checkpoint → 다음 단계 → 실행 증거**의 실제 연결과 사실성입니다.
- 지나치게 감정적이거나 과장된 표현을 피합니다. `장난감`, `치열하게`, `심도 있게`, `완벽`, `완전 자율`, `품질 보장` 같은 표현 대신 `예시`, `검증`, `구현 범위`, `확인`, `제한`처럼 객관적인 용어를 사용합니다.

## 2. 수정 승인 규칙

1. 수정이 필요하면 먼저 다음 내용을 사용자에게 설명합니다.
   - 현재 문제
   - 수정 전 상태
   - 수정 후 예상 상태
   - 영향받는 파일과 검증 방법
2. 사용자가 같은 요청에서 이미 `수정해줘`, `진행해줘`, `작성해줘`처럼 명확히 명령했다면 다시 승인받지 않고 해당 범위만 수정합니다.
3. 사용자가 평가·검토·설명만 요청했다면 파일을 수정하지 않습니다.
4. 요청 범위를 넘어 구조를 확대하거나 새 기능을 추가하지 않습니다. 추가 아이디어는 구현하지 말고 제안으로 분리합니다.
5. 수정 후에는 실제 변경 내용, 테스트 결과, 남은 한계를 다시 설명합니다.

## 3. 프로젝트 경계

- 현재 주 작업 저장소: 이 저장소의 루트(`.`)
- 프로젝트 1 기준 자산: 형제 저장소 `../portfolio_export`
- Agent 평가 실험 저장소: 형제 저장소 `../agent-evaluation-framework`

프로젝트 1은 사용자의 명시적인 수정 명령이 없는 한 **읽기 전용 기준 자산**으로 취급합니다. V2 구현을 위해 프로젝트 1의 HTML·테스트·문서를 조사할 수 있지만 임의로 수정하거나 실행 산출물을 덮어쓰지 않습니다.

V2의 독립 실행에 필요한 V1 기준 자산은 `product_baseline/`에 둡니다. 복사 범위는
`virtual-controller.html`, `pytest.ini`, `tests/conftest.py`,
`tests/test_controller.py` 네 파일로 제한합니다. V1 포트폴리오 페이지·보고서·영상·
Agent 4 코드·`.env`는 복사하지 않습니다. 이후 제품 변경은 사용자의 명시적 지시가
있을 때 V2 HTML 복사본에만 적용합니다.

Agent 평가 실험은 별도 저장소의 범위입니다. 사용자가 명시적으로 요청하지 않으면 이 저장소 작업과 섞지 않습니다.

## 4. 사실성 및 용어 규칙

- 프로젝트 1은 `Fixture 기반 Workflow Prototype`으로 설명합니다.
- V2의 Agent 1·2는 OpenAI API를 사용하는 실제 구조화 모델 호출입니다.
- V2의 Agent 3 모델은 승인된 TC를 제한된 행동·Assertion 계획으로 변환합니다. Playwright Python 코드는 허용 목록 기반 컴파일러가 결정론적으로 생성합니다.
- Agent 3의 UI Inventory는 Selector·표시·활성 상태·테스트 하네스 존재를 확인하는 단계이며, 제품 동작 검증은 Candidate Trial에서 수행합니다.
- Agent 4는 현재 생성형 AI가 아니라 **규칙 기반 결과 분석기**입니다.
- Checkpoint 통과는 사람의 최종 승인이 아니라 자동 검사 규칙 통과입니다.
- `PRODUCT_MISMATCH_CANDIDATE`는 제품 결함 확정이 아니라 기대 결과와 다른 관찰 후보입니다.
- Candidate Workspace는 원본과 분리된 임시 실행 위치이지 컨테이너나 OS 권한 격리를 제공하는 보안 Sandbox가 아닙니다.
- `examples/change_request.example.json`과 공개 Run의 AUTO 온도 변경은 연결 검증용 예시입니다. 대표 요구사항으로 고정하거나 코드에 하드코딩하지 않습니다.
- 공개 잠금 Run은 제품 불일치 후보인 실패 증거로 유지합니다.
- 공개 성공 Run은 실제 Live 실행과 CP4까지 완료된 결과만 사용하며, 사람의 SRS·공식 자산 승인은 자동 권고와 구분합니다.

## 5. 코드·문서 정합성 규칙

코드 동작이나 상태가 변경되면 같은 작업에서 관련 문서를 함께 점검합니다.

- 구현 상태·실행 방법: `README.md`
- 범위·완료 기준: `docs/02_V2_MVP_DESIGN.md`
- Agent·Checkpoint 계약: `docs/03_AGENT_AND_CHECKPOINT_SPEC.md`
- 테스트 수·추적성·증거: `docs/04_TEST_AND_TRACEABILITY_PLAN.md`
- Project1 기준 자산과 한계: `docs/05_PROJECT1_BASELINE_AUDIT.md`
- Agent 3 UI·하네스·격리 실행 경계: `docs/06_TEST_HARNESS_GUIDE.md`

문서의 계획을 구현 완료로 바꾸지 않습니다. 테스트 개수, 지원 범위, Run ID, 공개 산출물 수치는 실제 결과와 대조한 뒤 수정합니다.

## 6. 구현 원칙

- 공개 진입점 `src/qa_pipeline_v2.py`와 CLI 호환성은 유지하고, 구현은 공통 계약·Agent 1·Agent 2·Agent 3·실행·Agent 4 보고·Orchestrator 경계로 분리합니다.
- 테스트도 같은 역할 경계로 나누되 공유 builder와 fixture는 `tests/pipeline_test_support.py` 한 곳에서 관리합니다. 이 경계보다 더 작은 파일 분할은 명확한 재사용 필요가 생기기 전에는 추가하지 않습니다.
- Agent 출력은 자유 형식 Markdown이 아니라 Pydantic 구조화 계약을 사용합니다.
- 다음 단계는 앞 단계의 Checkpoint 통과 상태와 SHA-256 인계 무결성을 확인해야 합니다.
- Agent가 제품 기대 결과, Requirement ID, 경계값을 임의로 바꾸지 못하게 합니다.
- 자동 수정은 기술적 범위로 제한하고 Assertion 삭제나 기대값 변경을 허용하지 않습니다.
- 기존 SRS·TC·승인 자동화는 사람의 최종 등록 승인 전 덮어쓰지 않습니다.
- 첫 MVP는 MODIFIED 요청을 우선 지원합니다. ADDED·DELETED, Full Regression, 다중 모델 비교, 완전한 Self-Healing은 범위 밖입니다.

## 7. 검증 규칙

변경 후 가능한 범위에서 다음을 수행합니다.

1. `python -m pytest -q`
2. 필요한 경우 CLI Preview 또는 Fixture/Fake Client 테스트
3. 실제 API 호출 전 전송 Preview와 비밀정보 포함 여부 확인
4. `git diff --check`
5. `git status --short`

실제 API 호출은 비용과 외부 상태를 발생시키므로 사용자의 지시 범위에서만 실행합니다. 테스트 통과와 실제 Live Run 성공을 같은 의미로 표현하지 않습니다.

## 8. 민감정보 규칙

- `OPENAI_API_KEY`는 사용자 환경변수에서만 읽습니다.
- API 키를 코드, 문서, JSON, 로그, Screenshot, Git URL, 커밋에 저장하지 않습니다.
- 커밋 전 `sk-`, `OPENAI_API_KEY=`, 토큰 포함 URL 등 민감정보 패턴을 확인합니다.
- API 전송 데이터에는 로컬 절대경로, 전체 HTML, API 키를 포함하지 않습니다.
- 공개 Run은 비밀정보와 불필요한 로컬 정보가 없음을 확인한 뒤 `examples/results/`에 복사합니다.

## 9. Git 규칙

- 기존 사용자 변경을 보존하며 관련 없는 파일을 되돌리지 않습니다.
- `git reset --hard`, 무단 삭제, 강제 푸시는 사용하지 않습니다.
- 커밋 메시지는 항상 한글로 작성합니다.
- 커밋이나 푸시는 사용자가 명시적으로 요청했을 때만 수행합니다.
- 커밋 전 변경 파일, 테스트 결과, 민감정보, 문서 정합성을 확인합니다.
- 푸시 전 원격 주소에 인증정보가 포함되지 않았는지 확인합니다.

## 10. 새 작업 시작 순서

1. `AGENTS.md`, `PROJECT_HANDOFF.md`, `DECISION_LOG.md`를 읽습니다.
2. `git status --short --branch`와 최근 커밋을 확인합니다.
3. `README.md`의 현재 구현 상태를 코드와 대조합니다.
4. 미커밋 변경을 사용자 작업으로 간주하고 보존합니다.
5. 이번 요청의 수정 전·후와 영향 범위를 설명합니다.
6. 허가된 범위만 구현하고 테스트합니다.
7. 결과·남은 한계·커밋 여부를 보고합니다.
