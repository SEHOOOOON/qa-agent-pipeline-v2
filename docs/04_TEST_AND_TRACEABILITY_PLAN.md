# 테스트·추적성 계획

## 1. 목적

테스트는 V1의 QA 기준이 실제 모델 연결 뒤에도 유지되고, 각 단계의 값과 증거가 다음 단계까지 바뀌지 않는지 확인합니다.

현재 수집 결과:

~~~text
python -m pytest --collect-only -q
tests/test_pipeline.py: 180
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
python -m py_compile src/qa_pipeline_v2.py src/qa_pipeline_ui.py tests/test_pipeline.py
git diff --check
git status --short
~~~

실제 API Live Run은 자동 테스트와 별도입니다. API 호출 전에 입력 Preview와 비밀정보 포함 여부를 확인합니다. `RUN-20260827-114925-507176`은 Agent 1 REVIEW·CONTINUE, Agent 2 PASS, Agent 3 CP3 PASS·후보 시험, 환경 점검, 관련 기존 회귀 2건과 Agent 4를 완료했습니다. 최초 Slack·Notion Dry-run을 보존한 뒤 별도 전송 시도에서 Slack 1건·Notion 4건이 `SENT`였고, `사람_최종_검토.md`와 Manifest도 생성했습니다. Run 텍스트 검사에서는 API 키·로컬 사용자 경로 0건이었고 Project1 대상 HTML SHA-256은 `5D7649F401B1E721372E4ABDB8FDC65E4A3BD2D4E0FD0BD9E2C7161C9AA9B93C`으로 유지됐습니다. GitHub에서 최신 수치를 대조할 수 있도록 `examples/results/agent1-agent2-agent3-agent4-lock-disable/`에 단계별 상태, 핵심 관찰, 사람 검토 공개본, 실제 전송 상태와 원본·공개 파일 SHA-256을 포함한 최소 공개 증거 묶음을 둡니다.

최신 성공 흐름 `RUN-20260829-054330-A18942`은 실제 중앙제어 Run 화면에서 시작했습니다. Agent 1은 첫 응답의 인수 조건 누락을 CP1이 차단해 1회 재작업한 뒤 REVIEW·CONTINUE, Agent 2·CP2와 Agent 3·CP3 및 신규 후보 Trial은 PASS였습니다. `execute`는 같은 후보 증거를 해시 확인 후 재사용하고 환경 점검을 통과했으며, Agent 4는 제품 결과 1건·환경 결과 1건을 모두 PASSED로 분류해 CP4·최종 권고 PASS, 검토 항목·자동화 제외 0건을 생성했습니다. 시험은 장비 카드 `강풍`과 내부 `fanSpeed=HIGH`를 확인한 뒤 LOW로 복원했으며, Slack·Notion은 Preview만 생성했습니다.

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

테스트 통과는 실제 Live Run 성공을 뜻하지 않습니다. 과거 묶음 Live에서는 실행 직전 모드·온도 복원 계약이 없어 3건을 기술적으로 제외했지만, 현재는 V1 중앙 관제 온도·모드 흐름에 한해 런타임 `mode`·`setTemp` 저장·복원을 구현하고 실제 Playwright 시험으로 원상 복구를 확인했습니다. 이 보완 계약을 실제 모델이 생성하는 새 API Run으로 다시 확인하는 작업은 별도 비용을 발생시키므로 자동 테스트 결과와 구분합니다.

잠금 변경 Run은 제품 불일치 후보인 실패 증거로 그대로 유지합니다.
`examples/change_request.success-fan-speed.json`은 현재 V2 기준 제품에서 관찰되는
`강풍` UI와 내부 `fanSpeed=HIGH`를 근거로 만든 변경 요청은 위 Live Run에서 실제 성공 결과를 확보했습니다. 오세훈 검토자 승인 뒤 `TC-V2-001` 정식 TC·자동화를 등록했습니다.

중앙제어 Run·승인 화면 변경 뒤 최신 성공 후보를 현재 HTML에 API 호출 없이 다시 실행해
54,781ms PASS와 완전한 Screenshot·Trace 증거를 확보했습니다. 재검증 증거와 Manifest의
비밀정보·로컬 절대경로 패턴은 0건입니다. 등록된 자동화 파일도 현재 V2 HTML에 직접
실행해 PASS했습니다.

Registry 등록 자산은 파일·SHA-256·구조화 TC를 검증한 뒤 Agent 2 기존 TC 입력과 Run
Snapshot에 합쳐집니다. 선택된 승인 자산은 `execute`에서 승인 Python으로 실제
Playwright 재실행하며, `TC-V2-001`의 PASS와 Screenshot·Trace 생성을 자동 테스트에서
확인했습니다. MODIFIED·UPDATE_REQUIRED의 SRS 개정 제안은 최종 사람 검토와 승인 화면에
전달되며, 별도 SRS 동의 없이 공식 등록할 수 없습니다. 승인 시 기준 SRS 인수 기준과
개정 기록의 전·후 해시를 함께 남기는 흐름도 자동 테스트로 확인했습니다.
