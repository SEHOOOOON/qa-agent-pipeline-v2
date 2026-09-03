# 테스트·추적성 계획

## 1. 목적

테스트는 V1의 QA 기준이 실제 모델 연결 뒤에도 유지되고, 각 단계의 값과 증거가 다음 단계까지 바뀌지 않는지 확인합니다.

현재 수집 결과:

~~~text
python -m pytest --collect-only -q
tests/test_agent2.py: 39
tests/test_agent3.py: 56
tests/test_agent4_reporting.py: 20
tests/test_integrity_cli.py: 5
tests/test_orchestration_execution.py: 20
tests/test_pipeline_ui.py: 16
tests/test_srs_agent1.py: 24
~~~

상세 목록은 [자동 테스트 카탈로그](07_TEST_CATALOG.md)에 있습니다.

## 2. 단계별 검증

| 영역 | 주요 검증 |
|---|---|
| 기준 자산·SRS·Agent 1 | V2 독립 실행 자산이 승인된 네 파일뿐인지 확인, 성공 후보의 SRS·UI 근거, SRS 파싱, 요청 값 보존, 확정/정보 부족 분리, CP1 인계 |
| Agent 2 | V1·승인 공식 TC의 Requirement·검증 동작 대조, Condition의 변경·유지·보조 역할, Requirement ID만으로 회귀를 자동 보충하지 않는 계약, 기존 TC만 재실행하는 흐름, 근거 없는 행동 성공 Expected Result 차단, 업무 규칙 단위 조건 묶음, 조건별 판정·초기화, SRS 개정 제안, 3단계 QA 기준, 추적성, 독립성, 이중 검증 |
| Agent 3 계획 | 신규·수정 후보만 선택, UI 근거 제한, TC 값·단계·Expected Result·조건 순서 보존, 처음 보는 기능의 범용 UI 연결 |
| Agent 3 코드·시험 | 조건 동작 직후 Assertion 배치, 허용 목록 컴파일, 금지 패턴, 고정값 또는 실행 직전 HVAC·검증 대상 내부 필드 복원, 증거, 오류 분류 |
| 전체 실행 조정 | Agent 1→3 순서, 여러 TC 독립 실행, 일부 또는 전부 제외 후에도 요약·후속 보고 계속 |
| 변경 검증 | 현재 CP3 재검사, 후보 재사용/재시험, 신규 후보 없는 기존 TC 전용 실행, 환경 점검, Agent 2가 선택한 V1·승인 공식 TC 실행과 자산 해시 확인, CP4의 기준 회귀·승인 카탈로그별 해시 출처 검증 |
| Agent 4 | 산출물 해시, 상태·증거·집계 정합성, 원인 분류, 최종 권고, 사람 최종 검토 양식, Slack·Notion 허용·차단·Payload 해시·재시도 증거 보존 |
| 중앙제어 Run 화면 | 실제 Run 단계 요약, 조회·API 실행 구분, Run·요청 경로 제한, 새 API 실행 기본 잠금, Agent 버튼 연결, 후보 승인·보류·현재 화면 재검증·자산 해시·SRS 개정 별도 승인 |

## 3. 필수 추적 체인

~~~text
변경 요청
  → Agent 1 확정 조건
  → Agent 2 변경분 Requirement/Condition/Step/Expected Result + 관련 기존 TC ID
  → Agent 3 Action/조건별 Assertion
  → 생성된 코드 표시자
  → 시험·회귀 증거
  → Agent 4 검토 항목·최종 보고·외부 보고 상태
~~~

자동 검사 대상은 요청·Requirement ID, 변경 전·후 값과 경계값, TC·Condition·Expected Result ID, 관찰 계층, 생성 코드와 증거 SHA-256, 실행 합계와 보고 수치입니다.

묶음 TC는 복수 입력값, 조건 실행 방식, 중간 초기화 단계, 각 Expected Result의 `verify_after_step`, Agent 3 Assertion의 `after_action_id`와 생성 코드 내 배치 순서를 추가로 검사합니다.

## 4. 여러 TC 처리

- 한 TC의 CP3 실패나 지원 범위 부족은 다른 TC 실행을 막지 않습니다.
- 완료된 TC는 변경 검증과 관련 회귀로 인계합니다.
- 제외된 TC는 사유와 함께 최종 보고에 남깁니다.
- 완료된 신규 TC가 없어도 Agent 3 요약을 만들고 기존 TC 실행·Agent 4 보고를 계속합니다. 자동화 제외가 있으면 최종 사람 검토 대상으로 남깁니다.

과거 일괄 모델 호출과 그 전용 변조 테스트는 제거했습니다. 기능 검증 범위는 TC별 실행 요약·인계·Agent 4 테스트로 유지합니다.

## 5. 실행 명령

~~~powershell
python -m pytest -q
python -m pytest --collect-only -q
python -m compileall -q src tests
git diff --check
git status --short
~~~

실제 API Live Run은 자동 테스트와 별도입니다. 최신 공개 `RUN-20260903-121213-4CCC7A`은 API 입력 재료의 비밀정보·로컬 경로 검사를 먼저 통과한 뒤 Agent 1~3을 실제 호출했습니다. Agent 1 첫 결과의 누락은 CP1 재작업으로 보완됐고, Agent 2는 신규 MED 검증과 승인 HIGH 회귀를 분리했습니다. 신규 후보·환경 점검·`TC-V2-001`이 모두 PASSED였으며 CP4·최종 권고 PASS, 자동화 제외·Finding 0건, Slack·Notion PREVIEW를 확인했습니다. 공개 최소 증거는 `examples/results/agent1-agent2-agent3-agent4-medium-fan/`에 둡니다.

역할별 파일 분리 후 로컬 Live `RUN-20260903-125732-ECE88F`로 같은 연결을 다시 검증했습니다. CP1·CP3가 첫 산출물 오류를 각각 차단하고 1회 재작성 뒤 전체 PASS가 됐으며, 신규 후보·환경 점검·승인 회귀 3건과 CP4·최종 권고가 모두 PASS였습니다. 재작성 2회를 포함한 Agent 1~3 누적 사용량은 63,022 tokens입니다. Candidate와 승인 기존 회귀 Trace ZIP의 사용자 경로·임시 작업폴더명·키 패턴은 모두 0건이었습니다.

잠금 실패 사례와 실제 Slack·Notion 전송 증거는 `examples/results/agent1-agent2-agent3-agent4-lock-disable/`에 별도로 유지합니다. 성공·실패 Run의 상세 시행착오와 계약 변경 이유는 `DECISION_LOG.md`를 기준으로 하며 이 문서에는 현재 검증 범위만 둡니다.

## 6. 완료 판정

- 자동 테스트 전체 통과
- 테스트 수와 카탈로그 일치
- 코드와 문서의 상태·산출물 이름 일치
- Project1 원본 파일 불변
- `product_baseline/`의 V1 복사 자산이 HTML·Pytest 설정·기존 회귀 테스트 네 파일뿐인지 확인
- V2 HTML의 팀장·Agent 버튼이 로컬 브리지에서 실제 Run을 표시하고 직접 파일 실행에서는 기존 데모로 안전하게 대체되는지 확인
- 사람 승인 전에는 공식 자산이 생성되지 않고, 실패·증거 누락·현재 HTML 해시 불일치 후보는 등록되지 않으며 승인 뒤 Registry·TC·자동화 해시가 일치하는지 확인
- 승인 공식 TC가 다음 Agent 2 카탈로그에 포함되고 선택 시 같은 승인 Python으로 재실행되는지 확인
- SRS 개정 제안이 CP2·Agent 4·사람 검토·승인 화면까지 유지되고 별도 동의 뒤 기준 SRS와 변경 기록의 해시가 일치하는지 확인
- 비밀정보 패턴 없음
- README·내부 문서의 최신 수치와 공개 실행 증거 일치
- git diff --check 통과

테스트 통과는 실제 Live Run 성공을 뜻하지 않습니다. 자동 테스트 180건과 위 최신 Live를 모두 완료했기 때문에 현재 계약의 코드 검증과 실제 모델 연결 증거를 구분해 제시할 수 있습니다.

Registry 등록 자산은 파일·SHA-256·구조화 TC를 검증한 뒤 Agent 2 기존 TC 입력과 Run Snapshot에 합칩니다. 최신 Live에서 `TC-V2-001`의 검증 동작을 MED 신규 후보와 분리해 선택하고 승인 Python으로 다시 실행하는 흐름을 확인했습니다. SRS 개정 제안과 신규 후보 공식 등록은 자동 권고 PASS만으로 반영하지 않으며 사람의 별도 승인이 필요합니다.
