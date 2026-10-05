# 자동 테스트 카탈로그

본시험 구조화 관찰 기록: `test_controller_common_lifecycle_on_unmodified_product`는 기존 다섯 관제점 조작·복원 검사에 더해 각 검사 정의·실제 값·일치 여부·완료 기록을 확인합니다. P2의 별도 로컬 대조 및 변조·누락·제품 불일치 반례는 P2 `test_execution_observations.py`에서 관리합니다. 실제 모델 채점 정확도와 구분합니다.

Slack 표시 회귀: test_readable_slack_report_preserves_verdict_and_does_not_invent_restore는 정상/불일치 제목, 네 요약 구역, 근거 없는 복원 성공 금지, 승인 경계와 메시지 길이를 확인합니다. 실제 외부 전송 시험은 아닙니다.

test_slack_readable_terms_only_change_display는 한글 표시 변환 시 TC 원문·부정 표현·수치·알 수 없는 코드 보존과 실패/미실행의 통과 표시 방지를 확인합니다.

이 문서는 파이프라인 코드의 회귀검사 목록입니다. **제품 TC 목록이나 실제 AI의 정확도·성공률이 아닙니다.** 현재 실행 수치와 성공/실패 증거는 [인계 문서](../PROJECT_HANDOFF.md)에 기록합니다.

## 1. 역할별 검사 위치

Windows 경로 사전 검사: `test_integrity_cli.py`의 path_guard/short_run_layout 검사는 Windows·다른 OS 구분, 임시 파일 여유 길이·유니코드, 호출/파일 생성 전 차단과 짧은 경로 허용을 확인한다. 기존 atomic_write 검사는 쓰기 실패 때 원본 보존을 확인한다. 실제 API 통신 시험은 아니다.

TC 실행 정합 회귀는 `test_agent2.py`와 `test_grounding.py`에서 유지/변경 재사용·잘못된 대상 연결·경계 상대 조작·필수 검사 누락·다섯 관제점 복원 근거·과거 버전/검토 해시 보존을 확인합니다. 복원 지원 설명을 실제 성공으로 표시하지 않는 반례를 포함하며 새 AI 응답 정확성 시험은 아닙니다.

| 역할 | 코드·테스트 연결 | 확인하는 것 |
|---|---|---|
| SRS·Agent 1 | [test_srs_agent1.py](../tests/test_srs_agent1.py) | SRS 파싱·원문 인용·조건/절차/제외 분류·CP1 |
| Agent 2 | [test_agent2.py](../tests/test_agent2.py) | 기존 TC 대조·상세 TC·실행 정의·SRS 제안·CP2 |
| 공통 인계·CLI | [test_integrity_cli.py](../tests/test_integrity_cli.py) | 파일·계약·해시·저장 인계·실행 명령·공개 자산 보존 |
| Agent 3 | [test_agent3.py](../tests/test_agent3.py) | UI 수집·지원 여부·TC 동일성·CP3·코드 생성·실제 로컬 제품 조작/복원 |
| 의미 검토 연결 | [test_grounding.py](../tests/test_grounding.py) | 검토 대상/근거 ID·응답 형식·변조·오류·대역 SDK 호출 |
| 실행 조정 | [test_orchestration_execution.py](../tests/test_orchestration_execution.py) | 후보 선택·제외·오류 중단·기존 회귀·실행 집계 |
| Agent 4 | [test_agent4_reporting.py](../tests/test_agent4_reporting.py) | 결과 분류·증거·CP4·사람 검토서·외부 보고 |
| UI·승인 | [test_pipeline_ui.py](../tests/test_pipeline_ui.py) | 조회/실행 권한·승인·재시험·동시성·SRS 반영·복구 |

공유 데이터와 대역은 [pipeline_test_support.py](../tests/pipeline_test_support.py)에서 관리합니다. 같은 테스트 함수도 입력 조합에 따라 여러 건으로 수집되므로 함수 수와 실행 건수를 혼동하지 않습니다.

Agent 3의 클릭 관찰 회귀는 `test_observed_card_and_generic_direct_handler`(지정/일반 요소의 inline·property handler와 조회·위임 이벤트 구분), `test_observed_direct_handler_preserves_specialized_controls`(입력 종류 보존), `test_controller_device_select_hint_reaches_semantic_review`(검토 입력까지 동일 힌트 전달), `test_compiled_device_selection_checks_effect_not_just_handler`(기존 실행 코드의 대상 ID 확인)을 포함합니다. 핸들러 존재만으로 시험 성공을 인정하지 않으며 실제 AI의 재검토 결과는 이 검사에서 확인하지 않습니다.

## 2. 유지해야 하는 반례

저장 후 인계 회귀: `test_execution_interface_saved_handoff_preserves_results_and_integrity`는 다섯 관제점의 연결표/실행 정의 없는 경로에서 A3 저장 후 실제 인계 검사기로 다시 읽습니다. 통과·제품 불일치·실행 오류·시간 초과의 구분, TC 원문 보존, 정책 표시 누락/변조 및 검토 기록·후보 코드·증거 변조 차단을 확인합니다. AI·UI 수집·시험 결과는 명시적인 대역이며, 브라우저 조작 검사는 아래 별도 테스트가 담당합니다. 제품 불일치를 발견한 QA 절차의 정상 종료를 제품 PASS로 해석하지 않습니다.

실행 시점 회귀: `test_execution_interface_preparation_changes_actionability`는 처음 선택된 장비와 시험 대상이 같은/다른 경우, 송풍/제습에서 냉방 준비 후 상대/절대 온도 조작, 실제 하한 불일치와 복원을 대조합니다. `test_execution_interface_unusable_at_execution_is_not_skipped`는 실제 조작 때 비활성/숨김이면 성공으로 건너뛰지 않는지 확인합니다. `test_execution_interface_*` 근거 검사는 과거 입력 불변·새 계약 누락/변조 차단·TC 및 검토 대상 보존·이전 검토 재사용 금지를 확인합니다. 대역 검토를 실제 AI 판정으로 세지 않습니다.

사용자 확인 대기 표시: `test_ui_distinguishes_verified_waiting_from_failure`는 온도·풍량·잠금 질문 원문, 저장 해시·Run·종료 단계 일치, 질문 누락·변조·내부/통신 오류·검토 실패를 대조합니다. 대기 후 추가 명령 없음·실행 잠금 해제·기록 불변도 확인합니다. `test_ui_waiting_message_is_not_failure_or_completion_in_browser`는 로컬 실행 모드의 대기 표시를 검사하며 공개 데모 모드와 구분합니다. 실제 모델이 적절한 질문을 작성했는지를 평가하는 시험은 아닙니다.

TC 자산 비교 회귀는 `tests/test_pipeline_ui.py`의 `test_tc_comparison_*`에서 다섯 관제점에 같은 추가/대체 처리가 적용되는지, 기본 TC와 승인 TC 제외·과거 Snapshot/원본 보존, 잘못된 선택·중복 선택·사유 누락·오래된 비교 해시·파일 변조 차단, 미등록/보류 불변, 저장 실패 복구와 실제 브라우저→HTTP 전달을 검사한다. 대체 전 선택을 저장한 Run의 회귀 실행 차단도 포함한다. 시험용 후보와 일부 출처 검증 대역을 쓰므로 실제 모델의 의미 판단·공식 자산 승인 결과로 세지 않는다.

추가 반례: `test_registered_source_without_local_decision_cannot_record_new_intent`는 공식 등록은 남았지만 실행별 승인 기록이 누락되거나 보류인 경우 새 승인·대체·미등록·보류 기록을 차단한다. `test_multiple_replacements_preserve_existing_assets_and_rollback`은 복수 TC 대체의 목록 반영·원본 보존과 기존 자산이 있는 상태의 저장 실패 복구를 확인한다. 복수 선택 처리 시험이지 서로 다른 시험의 의미적 대체 가능성을 판정하는 검사는 아니다.

| 검사 묶음 | 정상 허용 | 계속 막아야 할 경우 |
|---|---|---|
| 요청과 조건 | 준비값·목표값·허용 범위·복수 원문 인용 | 없는 근거·확정 조건 누락·미정 기준 추정 |
| TC 설계 | 필요한 상세 단계와 기존 TC의 실제 재사용 | 요청 밖 기대값·검사 누락·중복 SRS 수정안 |
| 직접 실행 인계 | 같은 TC 값·순서·시점의 조립 | 대상/값/ER/시점·복원 연결 변조 |
| UI 수집·조작 | 존재/종류/장비를 미리 확인, 준비 후 실제 조작 가능 여부 확인 | 중복 요소·누락 내부값·다른 장비·실행 시 사용할 수 없는 요소를 성공 처리 |
| 검토 응답 | 정확한 원본 ID·원문·판정 보존 | 부모/결합/없는 ID·누락·변조·잘못된 응답으로 재작성 |
| 제품·복원 | 요청한 판정과 준비 전 상태 복원 구분 | 제품 불일치 은폐·복원 실패 뒤 동일 환경 진행 |
| 보고·승인 | 유효한 실패 보고·별도 사람 승인 | 환경만으로 제품 PASS·과거 PASS로 최신 실패 승인·미동의 SRS 변경 |

특정 시나리오용 예외를 늘리기보다 다른 관제점·값·표현에서도 같은 보호가 적용되는지 확인합니다. 전체 분기 규칙은 [판단 지도](PROJECT_GUIDE.md#logic-map)에서 봅니다.

## 3. 검증 종류와 한계

- 순수 코드/대역 검사: 정해진 출력에서 진행·재작성·중단·보고가 맞는지 확인합니다. 모델이 실제로 같은 출력을 낸다는 증거는 아닙니다.
- 로컬 브라우저 검사: 운영 수집·컴파일·제품 조작·복원을 확인합니다. 새 API 생성/의미 검토를 생략한 경우 전체 AI 흐름이라고 부르지 않습니다.
- 저장 Run 재현: 과거 TC·계획·증거의 유지와 현재 실행 경로를 비교합니다. 원본 실패를 수정해 성공으로 바꾸지 않습니다.
- 실제 API 검사: 별도 사용자 승인으로 새 생성·검토를 수행합니다. 여기의 로컬 수집 건수에 합치지 않습니다.
- 정적 색인: 코드 위치와 문서 검사 번호를 대조합니다. 커버리지·모든 경로 실행의 증명이 아닙니다.

## 4. 실행과 수집

```powershell
python scripts/verify_offline.py
python scripts/verify_offline.py --focus
python -m pytest --collect-only -q
python scripts/audit_logic_inventory.py --self-test
python scripts/audit_logic_inventory.py --check
git diff --check
```

기본 offline 명령은 전체 Pytest, focus는 근거 검토·실행 조정·보고·UI 승인 검사입니다. 서비스 키 제거와 외부 연결 차단은 프로세스 수준 보호이며 OS 격리나 모든 자식 프로세스의 네트워크 차단 보장이 아닙니다.

실패·오류·skip·중복·수집 수를 구분해 기록합니다. 여러 부분 실행의 합을 전체 검증률로 표시하지 않습니다. 오래된 [분기 감사](../archive/2026-09-28/branch_audit.json)의 미실행 목록을 안 쓰는 코드라는 이유로 삭제하지 않습니다.

## 5. 제품 TC와 공개 자산

보고 CLI 설정 회귀는 test_integrity_cli.py에서 전송 명령만 .env 로딩, 기존 환경변수 우선, UTF-8 BOM, 명시 경로 누락, 작업 디렉터리 독립성, 오프라인 로딩 차단을 확인합니다. 실제 서비스 인증·수신 검증은 별도입니다.

V1 기준 제품 테스트는 [test_controller.py](../product_baseline/tests/test_controller.py), 공식 승인 TC는 [registry.json](../approved_assets/registry.json)에서 확인합니다. 환경 점검·제품 TC·고정 분류 시연은 별도 집계하며 자동 테스트 목록과 합산하지 않습니다.

[정리 전 테스트 추가 이력](../archive/2026-09-28/07_TEST_CATALOG.md)은 과거 변경 근거입니다. 추가 N건을 모두 더해 현재 수량으로 사용하지 않습니다. 테스트 추가/삭제 시 이 문서의 역할·반례 범위와 인계 문서의 수집 상태를 함께 갱신합니다.
