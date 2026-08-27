# 테스트·추적성 계획

## 1. 목적

테스트는 V1의 QA 기준이 실제 모델 연결 뒤에도 유지되고, 각 단계의 값과 증거가 다음 단계까지 바뀌지 않는지 확인합니다.

현재 수집 결과:

~~~text
python -m pytest --collect-only -q
tests/test_pipeline.py: 145
~~~

상세 목록은 [자동 테스트 카탈로그](07_TEST_CATALOG.md)에 있습니다.

## 2. 단계별 검증

| 영역 | 주요 검증 |
|---|---|
| SRS·Agent 1 | SRS 파싱, 요청 값 보존, 확정/정보 부족 분리, CP1 인계 |
| Agent 2 | 기존 TC Requirement·검증 동작 대조, Agent 1 VERIFY 회귀의 결정론적 보충, 변경분 후보·관련 기존 TC 분리, 확정 Condition 처리 경로, 업무 규칙 단위 조건 묶음, 조건별 판정·초기화, 3단계 QA 기준, 추적성, 독립성, 이중 검증 |
| Agent 3 계획 | 신규·수정 후보만 선택, UI 근거 제한, TC 값·단계·Expected Result·조건 순서 보존, 처음 보는 기능의 범용 UI 연결 |
| Agent 3 코드·시험 | 조건 동작 직후 Assertion 배치, 허용 목록 컴파일, 금지 패턴, 고정값 또는 실행 직전 HVAC 상태 복원, 증거, 오류 분류 |
| 전체 실행 조정 | Agent 1→3 순서, 여러 TC 독립 실행, 일부 제외 후 계속 진행 |
| 변경 검증 | 현재 CP3 재검사, 후보 재사용/재시험, 환경 점검, Agent 2가 선택한 관련 기존 TC 실행 |
| Agent 4 | 산출물 해시, 상태·증거·집계 정합성, 원인 분류, 최종 권고, 사람 최종 검토 양식, Slack·Notion 허용·차단·Payload 해시·재시도 증거 보존 |

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
- 완료된 TC가 하나도 없을 때만 Agent 3 전체가 중단됩니다.

과거 일괄 모델 호출과 그 전용 변조 테스트는 제거했습니다. 기능 검증 범위는 TC별 실행 요약·인계·Agent 4 테스트로 유지합니다.

## 5. 실행 명령

~~~powershell
python -m pytest -q
python -m pytest --collect-only -q
python -m py_compile src/qa_pipeline_v2.py tests/test_pipeline.py
git diff --check
git status --short
~~~

실제 API Live Run은 자동 테스트와 별도입니다. API 호출 전에 입력 Preview와 비밀정보 포함 여부를 확인합니다. `RUN-20260827-114925-507176`은 Agent 1 REVIEW·CONTINUE, Agent 2 PASS, Agent 3 CP3 PASS·후보 시험, 환경 점검, 관련 기존 회귀 2건과 Agent 4를 완료했습니다. 최초 Slack·Notion Dry-run을 보존한 뒤 별도 전송 시도에서 Slack 1건·Notion 4건이 `SENT`였고, `사람_최종_검토.md`와 Manifest도 생성했습니다. Run 텍스트 검사에서는 API 키·로컬 사용자 경로 0건이었고 Project1 대상 HTML SHA-256은 `5D7649F401B1E721372E4ABDB8FDC65E4A3BD2D4E0FD0BD9E2C7161C9AA9B93C`으로 유지됐습니다. GitHub에서 최신 수치를 대조할 수 있도록 `examples/results/agent1-agent2-agent3-agent4-lock-disable/`에 단계별 상태, 핵심 관찰, 사람 검토 공개본, 실제 전송 상태와 원본·공개 파일 SHA-256을 포함한 최소 공개 증거 묶음을 둡니다.

## 6. 완료 판정

- 자동 테스트 전체 통과
- 테스트 수와 카탈로그 일치
- 코드와 문서의 상태·산출물 이름 일치
- Project1 원본 파일 불변
- 비밀정보 패턴 없음
- README·내부 문서의 최신 수치와 공개 실행 증거 일치
- git diff --check 통과

테스트 통과는 실제 Live Run 성공을 뜻하지 않습니다. 과거 묶음 Live에서는 실행 직전 모드·온도 복원 계약이 없어 3건을 기술적으로 제외했지만, 현재는 V1 중앙 관제 온도·모드 흐름에 한해 런타임 `mode`·`setTemp` 저장·복원을 구현하고 실제 Playwright 시험으로 원상 복구를 확인했습니다. 이 보완 계약을 실제 모델이 생성하는 새 API Run으로 다시 확인하는 작업은 별도 비용을 발생시키므로 자동 테스트 결과와 구분합니다.
