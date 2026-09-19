# 자동 테스트 카탈로그

최종 확인: 2026-09-19
실행 기준: `python -m pytest --collect-only -q` → **476건**
실제 정의 파일: `tests/test_srs_agent1.py`, `tests/test_agent2.py`, `tests/test_integrity_cli.py`, `tests/test_agent3.py`, `tests/test_orchestration_execution.py`, `tests/test_agent4_reporting.py`, `tests/test_pipeline_ui.py`

이 문서는 현재 수집되는 자동 테스트를 사람이 확인하기 쉽게 정리한 목록입니다. 실행의 기준은 항상 테스트 코드와 Pytest 수집 결과이며, 테스트를 추가·삭제할 때는 이 문서도 같은 변경에서 갱신합니다.

## 수량 구조

| 구성 | 수량 | 설명 |
|---|---:|---|
| 일반 테스트 함수 | 249 | 함수 하나가 Pytest 실행 1건 |
| 파라미터 테스트 함수 | 43 | 서로 다른 입력·실패 조합으로 실행 227건 |
| 합계 | **476** | 현재 Pytest 수집 수 |

### 최종 감사 반례: 추가 13개 실행 조합

- `test_agent3_complete_text_value_boundaries`: 한국어 조사·영문 코드·정상 한 글자 값·부분 단어 차단 8조합.
- `test_agent3_temperature_plan_preserves_approved_step_order`: 정상 순서·역순·중간 초기화 누락 3조합.
- `test_pipeline_ui_revalidation_rejects_files_changed_during_trial`: 제품 HTML·후보 코드의 시험 중 변경 2조합, 이전 유효 기록 보존.
- 기존 동적 풍량 문구 테스트에 현재 CP3의 부분 단어 차단을 추가하고, 후보 인계 테스트에 4.4 계획 충실성 계약 누락·미지원 값 차단을 추가했습니다.

### 검토 사유 화면 표시: 추가 4개 실행 조합

- `test_ui_review_item_preserves_rationale_without_raw_json`: 구조화 Finding의 TC ID·판단 근거, 과거 문자열, 미분류 코드, 근거 없는 항목을 구분합니다. 내부 증거 경로를 요약에 나열하지 않되 판단 근거와 결함 미확정 표현을 보존합니다. 원본 보고서·분류·승인 조건은 변경하지 않습니다.

### 사전조건별 모델 입력 안내: 추가 10개 실행 조합

- `test_agent3_context_bindings_are_source_specific_and_do_not_mutate_tc`: 한국어/영어 장비 상태, 풍량·온도 초기값, 불리언, 로그인 조건 7조합에서 원문별 허용 항목과 입력 불변 확인.
- `test_agent3_context_bindings_preserve_false_observations_without_inventing_evidence`: 관찰 false는 보존하고 미확보 상태 근거는 추가하지 않는 2조합.
- `test_agent3_sends_context_bindings_and_action_only_repair_guidance_without_weakening_cp`: 최초·재작성 실제 요청에 안내 포함, 정상 항목 보존 지침, 기존 잘못된 계획의 CP3 차단 유지 1건.

모델 안내 변경이며 실행 기준·컴파일러·기대값 검사를 완화하지 않습니다. 실제 모델 실행과 로컬 Fake Client 검증은 구분합니다.

### 대상별 복원 비교 기준: 추가 40개 실행 조합

- `test_restore_drafting_separates_ui_labels_and_internal_codes`: Agent 2의 화면/내부 코드 구분·초기 표시 근거·비교 기준 누락·연결 어미 5조합.
- `test_explicit_restore_basis_checks_display_and_internal_separately`: 한글 화면 표시와 내부 코드가 다른 로컬 제품에서 연결 표현 3종 × 정상/화면 복원 실패/내부 복원 실패 9조합.
- `test_explicit_restore_basis_rejects_ungrounded_or_missing_comparisons`: 비교 누락·중복·다른 ER·방법 오류·원문 변조·근거 없는 값·다른 대상·부정·가짜 조작·조작 누락·다른 구절의 근거 차용 등 13조합.
- 기존 `test_restore_linked_browser_comparisons_across_control_values`에 명시 비교 방식의 온도·풍량·모드 정상/복원 실패 12조합 추가(기존 방식 포함 총 24조합).
- `test_restore_comparison_supports_shared_target_without_borrowing_other_target_basis`: 같은 관찰 위치의 복수 ER 연결과 누락 차단 1건.

새 Agent 2 상세화 1.2 및 Agent 3 복원 1.2 계약·다운그레이드 차단은 기존 인계 테스트에 반영했습니다. 로컬 대역/저장 사본 검증과 새 모델 Live 결과는 구분합니다.

### 복원 확인 원문과 실제 비교 연결: 추가 33개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_restore_plan_links_preserve_sources_targets_and_fail_closed` | 정상 연결·누락·없는 ID·중복·원문 변조·대상 누락·새 알림/값·부정·가짜 조작 차단 12조합 |
| `test_restore_links_accept_observed_initial_state_wording` | 실행 전 확인/관찰/기록한 상태 표현 3조합 |
| `test_restore_linked_browser_comparisons_across_control_values` | 풍량·온도·모드의 일반/상세 문장과 정상/복원 실패를 실제 로컬 브라우저에서 검사 12조합 |
| `test_restore_linked_switch_checks_real_boolean_restoration` | 스위치 UI·내부 boolean 정상 복원·내부값 복원 실패 2조합 |
| `test_restore_links_do_not_claim_unsupported_or_unproved_comparisons` | 알림·미지원 전략·다른 초기값·다른 장비 증명 차단 4조합 |

기존 인계 시험에 새 4.2/복원 1.1 계약과 누락·다운그레이드 검사도 추가했습니다. 기능별 로컬 대역 시험이며 실제 제품의 모든 요구사항 또는 새 모델 전체 실행 검증을 뜻하지 않습니다.

### 요청 근거 연결과 추가 검사 구분: 추가 16개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_request_trace_only_keeps_requested_words_without_full_srs_scope` | 관련 SRS 전체 검증이 아닌 요청 원문 연결 허용·과거 계약 분리 2조합 |
| `test_request_trace_only_cannot_authorize_new_conditions` | 새 문장·SRS 조건·추가 조건·개정·끊긴 연결·허위 출처·제외 조건 차단 7조합 |
| `test_trace_only_expected_results_cannot_expand_original_request` | 원문 기대결과 허용, 추가 알림·변경 값·복합/없는 출처 반려 5조합 |
| `test_trace_reference_does_not_force_unrequested_notification_layer` | 관련 ID가 근거 연결일 때 요청하지 않은 알림 검사를 강제하지 않음 |
| `test_request_trace_run_handoff_requires_new_scope_contract` | 신규 실행 진입점·저장·재검증, 계약 누락·다운그레이드·불일치 차단 |

기존 직접 요청·간접 영향 보류 반례도 유지합니다. 실제 모델·Notion 결과와 남은 제한은 PROJECT_HANDOFF.md에 별도로 기록합니다.

### 합의 예시 기반 절차·복원 확인: 추가 37개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_procedure_detail_accepts_explicit_selection_and_restore_without_new_product_results` | 온도·풍량의 명시 조작과 복원 확인, 제품 ER 불변 2조합 |
| `test_procedure_detail_rejects_missing_false_or_late_target_preparation` | 대상 선택 누락·값 선택 오인·부정·늦은 선택 7조합 |
| `test_procedure_detail_accepts_already_selected_target_without_extra_click` | 이미 선택됐다고 명시한 사전조건은 추가 클릭을 강제하지 않음 |
| `test_procedure_detail_rejects_vague_missing_or_negated_restore_verification` | 복원 확인 누락·막연한 문장·부정 확인 5조합 |
| `test_procedure_detail_accepts_observed_baseline_without_invented_initial_value` | 실행 전 관찰한 원상태 참조 허용 |
| `test_procedure_detail_preserves_read_only_existing_only_and_legacy_contracts` | 한글/영어 읽기 전용, 기존 TC 전용, 과거 1.0 검사 보존 |
| `test_procedure_detail_requires_a_named_or_observed_restoration_baseline` | 초기 기준 없는 문장 반려·관찰/기록 기준 허용 3조합 |
| `test_procedure_detail_does_not_invent_device_selection_for_standalone_control` | 장비와 무관한 범용 단일 제어에 장비 선택을 강제하지 않음 |
| `test_restore_confirmation_uses_existing_baselines_without_extra_actions` | 확인줄 추가 전후 코드 동일성·실제 로컬 UI/내부 상태 복원 |
| `test_restore_confirmation_rejects_unimplemented_or_ungrounded_checks` | 새 대상·새 값·증명 부족·복원 누락·순서·가짜 Action·부정 비교 7조합 |
| `test_restore_confirmation_explicit_value_needs_same_target_precondition_proof` | 동일 관찰 대상의 사전조건 증명과 명시 초기값 연결 |
| `test_restore_confirmation_matches_string_initial_value_not_feature_names` | 문자열 초기값 LOW의 증명, 다른 값·관찰 이름 속 값의 오인 차단 |
| `test_restore_confirmation_does_not_accept_proof_for_another_device` | 초기값이 같아도 다른 장비의 사전조건 증명은 반려 |
| `test_restore_check_action_is_not_mistaken_for_read_only_confirmation` | 실제 체크박스 조작과 읽기 전용 확인 문장 구분 |
| `test_restore_confirmation_legacy_temperature_uses_existing_fixed_checks` | 온도 복원 초기값과 실제 컴파일러 비교 연결 |
| `test_historical_restore_confirmation_uses_previous_checkpoint_rules` | 과거 복원 문장은 이전 계약으로 재검증, 최신 작성 기준과 구분 |
| `test_agent1_to_agent2_cli_handoff_with_frozen_inputs` | 기존 정상 외 재작성 해결·미해결 2조합 추가, 새 1.1 Manifest·누락/다운그레이드 차단·과거 1.0 호환 |

추가 Agent 3의 과거 검사 분기·다른 장비 초기값 증명 반례도 포함합니다. 기존 모델 대역 테스트는 예시 A/B/C가 최초/재작성 모두 전달됨을 확인하고, 기존 Notion 테스트는 복원 확인줄까지 보존합니다. 위 수치는 규칙·대역·로컬 브라우저 검사이며 실제 모델의 새 초안 품질 또는 Notion 실제 게시 완료를 뜻하지 않습니다.

### Notion 상세 TC 연결: 추가 7개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_notion_detail_preserves_saved_steps_results_and_restore` | 저장 명세·ER ID·단계 연결·복원을 보고 기록과 본문에 보존 |
| `test_notion_detail_does_not_guess_legacy_or_ambiguous_timing` | 과거·중복 단계의 기대결과를 임의 연결하지 않음 |
| `test_notion_detail_preserves_long_text_and_resumes_parts_without_duplicates` | 긴 한글·이모지 분할, 페이지네이션, 저장 후 응답 유실 재시도, 중복 방지·수동 편집 보존 |
| `test_notion_detail_upsert_counts_only_completed_bodies` | 본문 성공·권한 실패 2조합, 상세 전송이 끝난 건만 완료 집계 |
| `test_notion_get_does_not_send_json_body` | Notion 본문 조회 GET에 요청 본문을 넣지 않음 |
| `test_report_omits_unverified_legacy_design_from_notion_detail` | 인계 명세 없는 과거 기록의 상세 제외·알 수 없는 Manifest 차단 |

HTTP 대역으로 본문 생성·전송 계약을 검사합니다. 실제 Notion 계정에서의 권한·렌더링·게시 확인을 뜻하지 않습니다.

### 생성 TC 상세화: 추가 12개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_new_tc_detail_keeps_steps_observation_locations_and_shared_timing` | 상세 단계·확인 대상·UI/내부 공동 판정 시점·구조화 왕복 보존 |
| `test_new_tc_detail_rejects_compressed_or_unlinked_drafts` | 압축 절차 2종·판정 단계 누락/존재하지 않음/중복·대상 누락/불일치/일반어·빈 절차 9조합 |
| `test_tc_detail_preserves_legacy_read_only_and_existing_only_designs` | 과거 규칙, 읽기 전용·기존 TC 전용, 간결한 복원 허용 |
| `test_detailed_single_flow_requires_and_executes_explicit_assertion_anchor` | 새 단일 흐름의 판정 시점 강제·컴파일 위치·로컬 브라우저 실행·복원 |

기존 API 대역 테스트는 최초/재작성 지침을, CLI 테스트는 새 상세화 Manifest와 재로딩을 함께 확인합니다. 과거 CP2 단위 fixture는 공유 어댑터에서 상세화 규칙을 끄고, 새 상세화 테스트와 운영 진입점은 기본 강제 규칙을 검사합니다. 실제 모델 출력 품질이나 노션 상세 게시 완료를 의미하지 않습니다.

### 요청 밖 검사 범위 통제: 추가 18개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_scope_direct_request_passes_but_unrequested_dependency_pauses` | 두 종류 Requirement에서 직접 요청 통과·간접 영향 보류, PARTIAL_PROCEED로 우회하지 않음 |
| `test_scope_rejects_unfounded_evidence` | 근거 누락·SRS 조건 오용·존재하지 않거나 중복된 조건·허위 원문·잘못된 Requirement·제외/변경 전/준비 문구 차단 9조합 |
| `test_scope_does_not_accept_relabelled_dependency_or_shared_word_as_direct` | 간접 영향을 직접 요청으로 바꾸거나 공통 단어만 제시해도 자동 인계하지 않음 |
| `test_scope_explicit_requirement_reference_and_update_are_supported` | 직접 명시한 Requirement의 UPDATE_REQUIRED 처리 |
| `test_scope_guard_is_versioned_not_retroactive` | 과거 판정 계약 유지, 새 기본 검사의 누락 근거 차단 |
| `test_scope_gate_rewrite_and_pause_before_agent2` | 재작성 해결·미해결·범위 보류 3조합, Manifest와 최초/재작성 입력, Agent 2 진입 차단 |
| `test_scope_contract_loader_preserves_legacy_and_rejects_missing_new_contract` | 과거 Run 로딩, 새 계약 누락 거절 |

기존 연관 UPDATE_REQUIRED 테스트도 근거 없는 확장을 차단하도록 바꿨습니다. 위 시험은 규칙·모델 대역 검증이며 새 실제 모델 실행 성공을 의미하지 않습니다. 현재 파일별 수집은 Agent 1 53·Agent 2 95·Agent 3 195·Agent 4 35·인계/CLI 13·실행 34·UI 51건입니다.

### 승인 TC 재사용 입력: 추가 3건

| 테스트 | 확인 내용 |
|---|---|
| `test_approved_reuse_context_preserves_spec_without_registration_metadata` | 승인 TC의 사전조건·조작·기대결과·판정 시점·복원 원문 전달, 등록 메타정보·경로 제외 |
| `test_reuse_context_snapshot_roundtrip_and_legacy_compatibility` | 새 카탈로그 상세 정보 왕복 보존, 상세 정보 없는 과거 Snapshot 호환 |
| `test_agent2_sends_approved_procedures_on_initial_and_rewrite_calls` | 최초 설계와 재작성의 실제 입력 구성에 승인 TC 명세 포함, 모델 대역 사용 |

### 긴 임시 경로 저장 오류: 추가 1건

| 테스트 | 확인 내용 |
|---|---|
| `test_atomic_write_short_temp_preserves_original_on_failure` | 최종 경로는 유효하지만 이전 임시 이름이 260자를 넘는 경우 저장, 같은 폴더의 고유 임시 이름 사용, 교체 실패 시 원본 보존·임시 파일 정리 |

기존 Agent 3 진입점·재작성 테스트에 검사 예외 전 첫 계획 보존과 두 번째 계획 보존도 추가했습니다. 새 제품 TC를 추가한 것은 아닙니다.

### 사전조건 재작성 안내: 추가 1건

| 테스트 | 확인 내용 |
|---|---|
| `test_agent3_precondition_feedback_repairs_only_unstated_context` | 오류 항목·원문·사유 전달, 모델 대역 재작성 뒤 시험 연결, 불필요한 온라인·표시 확인 제거와 필수 잠금 확인 누락 차단 구분, TC·첫 계획 원문 보존 |

기존 `test_agent3_uses_structured_plan_api`도 최신 지침·재작성 안내의 실제 API 입력 구성 검사를 포함합니다. 실제 유료 모델을 호출하는 테스트는 아닙니다.

### 사전조건 증명 계약: 추가 18개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_precondition_proof_rejects_unverified_plans` | 기본 CP3 증명 강제, 누락·원문·Selector·값·약한 문자·로그인 누락·상태 전략·판정 순서 8조합 |
| `test_baseline_context_cannot_prove_administrator_login` | 장비 표시 문맥을 관리자 로그인 증명으로 대신하지 않음 |
| `test_compound_baseline_precondition_needs_each_observed_fact` | 온라인·표시·오류·잠금 복합 문맥의 일부 확인만으로 통과시키지 않음 |
| `test_narrow_inventory_exposes_target_initial_values_without_full_discovery` | 전체 UI 조사 없이 초기 대상 ID·모드·온도·온라인 문맥 관찰 |
| `test_precondition_internal_device_reference_must_match_target_identity` | 다른 장비 배열 위치에서 읽은 값을 대상 장비 증명으로 사용하지 않음 |
| `test_runtime_precondition_is_verified_before_product_test` | 실제 브라우저의 초기 상태 일치/불일치 2조합, 성공 관찰값 기록·본 시험 전 차단·필수 증거·제품 오분류 방지 |
| `test_precondition_multiple_explicit_values_need_multiple_checks` | ADMIN·SOUTH처럼 한 문장의 여러 명시 값 중 하나만 증명하지 못함 |
| `test_agent4_reports_precondition_failure_as_unexecuted_product_test` | 사전조건 불충족을 제품 결함 아닌 자동화 문제·HOLD로 보고하고 사람 문서에 표시 |
| `test_agent3_requires_proof_on_new_runs_and_records_it` | 새 Agent 3 진입점의 증명 강제·기술 재작성 1회·미실행 제외·계약 Manifest 2조합 |

기존 CP3 부문 단위 테스트는 사전조건 계약이 없는 과거 계획 fixture를 test-support 어댑터로 검사합니다. 운영 CP3 기본값은 증명 필수이며, 위 신규 테스트와 실제 실행 진입점에서는 이를 끄지 않습니다. 모델 대역으로 실행 순서를 확인한 테스트와 실제 브라우저 시험을 새 API Live로 해석하지 않습니다.

### 9/12 후속 감사 보완: 18개 실행 조합

| 테스트 | 확인 내용 |
|---|---|
| `test_new_tc_expected_value_requires_its_own_condition` | 연결 조건에 없는 코드·수치 기대값 차단 3조합 |
| `test_new_tc_med_to_high_is_rejected_without_rejecting_med` | MED 정상 통과·HIGH 변경 차단·과거 계약 분리 |
| `test_new_tc_range_allows_in_range_value_but_not_opposite_policy` | 범위 내 값 허용, 허용·차단 반전 차단 |
| `test_boundary_input_in_expectation_is_not_confused_with_output` | 차단할 경계 입력과 허용된 출력값을 구분 |
| `test_cp3_rejects_static_label_in_place_of_switch_state` | 상태 대신 고정 명칭만 검사하는 계획 차단 |
| `test_cp3_rejects_disabled_strategy_for_enabled_expectation` | 활성 기대에 비활성 검사 전략을 연결하지 못함 |
| `test_generic_restore_snapshot_follows_preparation` | 실제 브라우저에서 준비 전 ON→준비 OFF→시험 ON→복원 OFF 확인 |
| `test_report_consumers_reject_changed_sources` | 실행 원본·최종 보고 변경 시 외부 보고와 검토 문서 재생성 차단 2조합 |
| `test_shared_lock_rejects_overlapping_thread_and_is_reusable` | 같은 잠금 객체의 동시 진입 거절 및 정상 해제 후 재사용 |
| `test_approval_rejects_unverified_pass_labels` | PASS 표시만 있는 불완전 기록의 승인 연결 검증 거절 |
| `test_missing_observed_interface_is_tc_exclusion_not_internal_error` | UI 인터페이스 누락을 TC 제외로 기록, 내부 오류와 구분 |
| `test_browser_ignores_previous_run_post_response` | 승인·재검증 성공/실패 지연 응답이 선택된 Run을 덮지 않음 4조합 |

승인 파일 등록·원상복구 UI 단위 테스트는 원본 연결 검증 경계를 대체한 작은 fixture를 사용합니다. 그 테스트 통과를 전체 실행 증거의 진위 검증으로 해석하지 않습니다. 원본 검증 거절 테스트와 실제 Run 사본 대조 결과는 별도로 확인합니다.

파라미터 테스트 `test_agent3_cli_exit_code_reflects_trial_trustworthiness`는 다음 다섯 결과를 별도 실행합니다: `PASS`, `PRODUCT_MISMATCH_CANDIDATE`, `AUTOMATION_ERROR`, `ENVIRONMENT_ERROR`, `TIMEOUT`.

`test_agent4_reports_restore_failure_without_hiding_product_observation`는 복원 단독 실패와 제품 불일치·복원 동시 실패를 각각 검사합니다. 9월 7일 증가한 4건은 이 두 조합과 로그 오인·변조 방지, 기존 TC 절차 메모의 최종 보고 연결이며 제품 TC가 새로 생성된 수가 아닙니다.

## 1. 기준 자산·SRS·Agent 1·Checkpoint 1 (27건)

| 테스트 | 확인 내용 |
|---|---|
| `test_partial_unresolved_acceptance_is_handed_off_as_gap_not_condition` | 원문에 미정이 명시된 인수 조건의 제외 인계 허용, 제외 기록 누락·명확한 조건 무단 제외 차단 |
| `test_v2_product_baseline_contains_only_runtime_assets` | V2의 V1 복사 자산이 독립 실행에 필요한 네 파일뿐인지 확인 |
| `test_success_fan_speed_request_is_grounded_in_v2_baseline` | 새 풍량 성공 후보의 SRS Requirement·UI Selector·내부 적용 근거 존재 |
| `test_loads_product_requirements_from_markdown` | Product SRS 요구사항 로딩 |
| `test_rendered_context_contains_ids_and_acceptance_criteria` | Agent 1 입력 문맥의 ID·인수기준 |
| `test_product_srs_excludes_test_harness_requirements` | 제품 SRS와 테스트 하네스 분리 |
| `test_agent1_uses_structured_responses_api` | Agent 1 구조화 API 계약 |
| `test_agent1_missing_api_key_fails_before_network` | API 키 누락 시 네트워크 전 차단 |
| `test_valid_analysis_passes_checkpoint1` | 유효 분석의 CP1 통과 |
| `test_missing_change_request_range_is_rejected` | 변경 범위 누락 차단 |
| `test_unknown_requirement_is_rejected` | 알 수 없는 Requirement 차단 |
| `test_missing_related_requirement_review_is_rejected` | 연관 Requirement 검토 누락 차단 |
| `test_condition_requirement_missing_from_effects_is_rejected` | 확정 조건 영향 누락 차단 |
| `test_unverified_before_value_requires_review` | 변경 전 값 불일치 REVIEW |
| `test_ungrounded_confirmed_condition_is_rejected` | 근거 없는 확정 조건 차단 |
| `test_missing_acceptance_note_is_rejected` | 인수 기준 누락 차단 |
| `test_checkpoint1_does_not_require_setup_or_restore_as_product_conditions` | 시험 준비·종료 후 복원을 제품 기대 결과로 강제하지 않음 |
| `test_missing_requested_out_of_scope_is_rejected` | 요청된 제외 범위 누락 차단 |
| `test_redundant_reconfirmation_requires_review` | 불필요한 재확인 REVIEW |
| `test_legitimate_missing_detail_question_passes_checkpoint` | 정당한 세부 질문 허용 |
| `test_partial_proceed_continues_confirmed_scope_and_preserves_exclusions` | PARTIAL_PROCEED의 확정 범위 계속 실행 |
| `test_partial_proceed_without_excluded_scope_is_rejected` | 제외 범위 없는 PARTIAL_PROCEED 차단 |
| `test_blocked_decision_blocks_agent2_handoff` | BLOCKED의 후속 단계 차단 |
| `test_related_update_without_scope_evidence_is_rejected` | 연관 UPDATE_REQUIRED의 범위 근거 누락 차단 |
| `test_proceed_with_open_question_is_recorded_for_final_review` | PROCEED 보완 REVIEW의 최종 보고 이관 |
| `test_scope_limited_acceptance_note_is_only_excluded` | 범위 제한 인수 조건을 확정 조건이 아닌 제외 범위로 전달 |
| `test_scope_limited_acceptance_note_cannot_be_confirmed_condition` | 범위 제한 문구의 확정 조건 혼입 차단 |

## 2. Agent 2·Checkpoint 2·인계 (49건)

| 테스트 | 확인 내용 |
|---|---|
| `test_agent2_uses_structured_responses_api` | Agent 2 구조화 API 계약 |
| `test_agent2_missing_api_key_fails_before_network` | API 키 누락 시 사전 차단 |
| `test_checkpoint2_rejects_existing_only_reuse_with_different_explicit_values` | 기존 TC 명시 값 불일치 차단·역사적 계약 보존·신규 후보 정상 통과 |
| `test_agent2_duplicate_technical_ids_are_normalized_without_semantic_changes` | 중복 기술 ID만 정리하고 TC 의미 필드 불변 확인 |
| `test_checkpoint2_does_not_invent_regression_from_requirement_id_alone` | Requirement ID만으로 다른 동작의 기존 회귀를 조용히 자동 추가하지 않음 |
| `test_existing_test_selection_accepts_versioned_official_tc_id` | 숫자가 포함된 승인 공식 TC ID의 기존 회귀 선택 계약 |
| `test_request_diff_recognizes_repeated_existing_clause_as_unchanged` | 변경 후 문구에 반복된 기존 절과 새 변경 절의 전·후 분리 |
| `test_request_diff_treats_mapping_or_order_change_as_changed_without_explicit_role` | 단어가 비슷한 매핑·순서 변경을 유지로 오인하지 않는 안전 기본값 |
| `test_valid_design_passes_checkpoint2` | 유효 TC 설계의 CP2 통과 |
| `test_checkpoint2_allows_existing_tc_only_when_behavior_covers_change` | 기존 TC 전용 CP2 통과·준비/복원 메모 최종 검토 인계·신규 후보 검사 유지·역사적 계약 보존 |
| `test_checkpoint2_requires_grounded_srs_revision_proposal_for_modified_requirement` | MODIFIED Requirement의 근거 있는 SRS 개정 제안 필수 계약 |
| `test_srs_revision_preview_apply_and_conflict_detection` | SRS 개정 미리보기·적용·멱등성과 원문 충돌 차단 |
| `test_checkpoint2_routes_unchanged_condition_to_existing_tc` | 유지 조건을 신규 후보가 아닌 기존 TC ID로 연결 |
| `test_checkpoint2_rejects_existing_regression_regenerated_as_candidate` | 기존 회귀를 신규 후보로 다시 만드는 설계 차단 |
| `test_checkpoint2_allows_incompatible_target_regression_to_be_omitted` | 변경 후 기대와 맞지 않는 대상 기존 TC의 비강제 선택 |
| `test_checkpoint2_rejects_compound_ui_expected_result` | 서로 다른 UI 관찰값을 한 기대 결과에 묶은 설계는 차단하고 모드가 시험 조건인 문장은 허용 |
| `test_checkpoint2_rejects_procedural_selection_expected_result` | 준비용 장비 선택을 제품 기대 결과로 확장하는 설계 차단 |
| `test_checkpoint2_rejects_action_success_as_expected_result` | 선택·적용 가능성 같은 실행 행동 자체의 기대 결과화 차단 |
| `test_checkpoint2_keeps_grounded_product_capability_result` | Condition 원문에 있는 제품 기능 가능 요구를 일괄 삭제하지 않음 |
| `test_checkpoint2_rejects_ui_display_not_present_in_condition_source` | Condition 원문에 없는 UI 표시 기대 차단 |
| `test_checkpoint2_accepts_related_boundaries_as_one_grouped_tc` | 동일 업무 규칙의 하한·상한 조건을 한 TC로 허용 |
| `test_checkpoint2_pairs_double_assertions_at_the_same_step` | UI·내부 판정 시점 분리 차단과 역사적 계약 유지 |
| `test_checkpoint2_accepts_single_operation_with_separate_observations` | 단일 조작의 분리된 UI·내부 기대 결과 허용 |
| `test_checkpoint2_rejects_grouped_tc_without_reset_or_result_timing` | 묶음 TC의 중간 초기화·조건별 판정 시점 누락 차단 |
| `test_checkpoint2_requires_explicit_runtime_restore_for_unknown_grouped_hvac_baseline` | 고정 초기값 없는 묶음 HVAC TC의 명시적 실행 전 상태 저장·복원 계약 |
| `test_human_review_note_pauses_checkpoint2` | 사람 검토 메모의 PAUSE |
| `test_coverage_note_does_not_pause_checkpoint2` | 참고 메모 허용 |
| `test_final_review_note_does_not_pause_checkpoint2` | 최종 확인 사항의 자동 진행 |
| `test_control_requirement_cannot_use_local_path` | 중앙 제어 요구사항의 LOCAL 경로 차단 |
| `test_verify_central_path_can_use_existing_regression_without_new_candidate` | VERIFY 유지 경로의 기존 TC 재사용 허용 |
| `test_verify_only_requirement_cannot_be_duplicated_as_new_candidate` | VERIFY 전용 동작의 신규 후보 중복 생성 차단 |
| `test_structured_test_data_is_required_for_boundary_tc` | 경계 TC 구조화 시험 데이터 강제 |
| `test_state_consistency_without_mode_or_temperature_data_is_allowed` | 잠금 같은 상태 TC에 무관한 모드·온도 TestData를 강제하지 않음 |
| `test_boundary_tc_allows_initial_mode_as_execution_context` | 사전조건 모드를 불필요한 요청 행동으로 복제하지 않음 |
| `test_missing_condition_is_rejected` | Condition 추적 누락 차단 |
| `test_missing_internal_state_assertion_is_rejected` | 내부 상태 검증 누락 차단 |
| `test_state_consistency_type_without_internal_state_is_rejected` | 상태 정합성 내부 검증 강제 |
| `test_missing_three_tier_quality_criteria_is_rejected` | TC별 3단계 QA 기준 누락 차단 |
| `test_tc_declared_non_independent_is_rejected` | 독립 실행 근거 없는 TC 차단 |
| `test_tc_negative_cross_tc_reference_is_accepted_as_independence_evidence` | 다른 TC 비의존 문장을 실제 의존으로 오탐하지 않음 |
| `test_tc_positive_cross_tc_dependency_is_rejected` | 다른 TC 결과를 이어받는 실제 의존 차단 |
| `test_partial_scope_exclusions_must_be_preserved_by_agent2` | Agent 1 제외 범위·정보 부족의 Agent 2 인계 |
| `test_agent2_preserves_setup_and_restore_notes_as_tc_procedures` | 시험 준비·종료 후 복원을 제외하지 않고 TC 절차로 보존 |
| `test_playwright_code_is_rejected` | TC 내 Playwright 코드 혼입 차단 |
| `test_verified_agent1_run_can_handoff_to_agent2` | 검증된 Agent 1 SHA 인계 |
| `test_modified_agent1_artifact_is_blocked_before_agent2` | 변조된 Agent 1 산출물 차단 |
| `test_paused_manifest_is_blocked_before_agent2` | PAUSE Manifest 차단 |
| `test_agent1_to_agent2_cli_handoff_with_frozen_inputs` | CLI 동결 입력 인계 |
| `test_agent2_rejects_an_active_run_reservation` | 동시 Agent 2 실행 예약 차단 |

## 3. Agent 3 조사·계획 계약 (29건)

| 테스트 | 확인 내용 |
|---|---|
| `test_agent3_uses_structured_plan_api` | Agent 3 구조화 계획 Schema·시스템 지침 |
| `test_agent3_accepts_atomic_temperature_up_disabled_assertion` | 독립 온도 올림 버튼 비활성 기대의 범용 활성 상태 Assertion |
| `test_agent3_eligibility_keeps_atomic_temperature_button_selectors` | 일반 잠금 TC의 대상 장비·내부 상태·온도 버튼 조사 범위 보존 |
| `test_agent3_allows_observed_initial_mode_without_reapplying` | 관찰된 초기 모드를 불필요하게 다시 적용하지 않음 |
| `test_agent3_model_input_preview_is_minimal_and_has_no_local_path` | Preview 최소 전송·경로 제외·한국어 내부 설정 온도와 전용 `setTemp` 연결 |
| `test_agent3_eligibility_scopes_ui_inventory_to_selected_tc` | 선택 TC 범위 UI 조사 |
| `test_agent3_scoped_inventory_still_blocks_a_required_selector` | 필수 Selector 누락 차단 |
| `test_agent3_observation_records_verified_clean_execution_context` | 초기화·장비 표시·오류 없음·잠금 해제 실행 문맥 확인 |
| `test_agent3_inspection_waits_for_delayed_required_selector` | 비동기 UI 초기화 대기 |
| `test_agent3_verified_context_is_captured_after_delayed_interfaces` | 필수 UI·하네스 준비 후 초기 실행 문맥 기록 |
| `test_agent3_local_control_path_is_excluded_before_ui_or_model` | 역사 LOCAL 후보를 UI 조사·API 전에 제외 |
| `test_agent3_unknown_internal_state_uses_generic_discovery` | 미지 내부 상태의 동적 조사 |
| `test_agent3_registered_device_fields_are_grounded_and_compiled` | 등록 장비 필드·TC 근거·컴파일 |
| `test_agent3_rejects_unobserved_or_ungrounded_device_fields` | 미관찰·무근거 장비 필드 차단 |
| `test_agent3_non_hvac_mode_values_use_generic_discovery` | 비 HVAC 상태값의 동적 조사 |
| `test_agent3_textual_link_tolerates_korean_particles` | 한국어 조사·어미 의미 연결 |
| `test_agent3_allows_dynamic_text_on_the_approved_target_device_card` | 정확한 대상 장비 카드의 변경 후 동적 문구와 내부 `fanSpeed` 복원 검증 허용 |
| `test_agent3_notification_rejects_the_whole_expected_result_as_ui_text` | 알림 Expected Result 전체 문구 오사용 차단 |
| `test_agent3_generic_discovery_compiles_and_runs_a_new_control` | 신규 범용 제어의 조사·컴파일·시험 |
| `test_agent3_records_support_extension_without_generating_code` | 지원 범위 확장 REVIEW·코드 미생성 |
| `test_agent3_non_candidate_records_not_automatable_before_ui_or_model` | 자동화 후보 아님 사전 종료 |
| `test_agent3_preview_does_not_require_api_key_or_create_model_client` | Preview 무API 보장 |
| `test_valid_agent3_plan_passes_cp3_and_compiles` | 유효 계획 CP3·코드 생성·첫 TEST 장비 선택 허용·늦은 선택 차단 |
| `test_agent3_grouped_tc_interleaves_assertions_before_next_condition` | 묶음 TC의 조건 동작 직후 Assertion 배치와 다음 조건 순서 보존 |
| `test_agent3_grouped_tc_rejects_unanchored_condition_results` | 조건별 판정 위치가 없는 Agent 3 계획 차단 |
| `test_blocked_temperature_request_compiles_until_target_or_stall` | 차단 온도 요청 반복·정지 계약 |
| `test_restore_contract_requires_initial_temperature_and_apply` | 복원 계약 누락 차단 |
| `test_legacy_central_plan_cannot_bypass_required_actions_with_generic_assertion` | 전용·범용 혼합 계획의 필수 중앙제어 순서 우회 차단 |
| `test_specialized_action_source_text_must_be_an_approved_tc_line` | 전용 Action도 승인 TC 원문만 근거로 허용 |

## 4. Agent 3 CP3·후보 시험·증거 (41건)

추가: `test_compiled_observation_wait_handles_delayed_browser_state_without_reclicking` — 실제 브라우저의 지연 반영 허용, 조작 한 번 유지, 지속 불일치 반환.

| 테스트 | 확인 내용 |
|---|---|
| `test_compiler_verifies_restored_ui_and_internal_temperature` | 복원 후 UI·내부 온도 재확인 |
| `test_grouped_hvac_trial_restores_runtime_baseline` | 묶음 모드·온도 조건 실행 전 상태 저장·실제 Playwright 복원 |
| `test_unobserved_selector_is_rejected_by_cp3` | 미관찰 Action Selector 차단 |
| `test_observed_but_wrong_action_selector_is_rejected_by_cp3` | 행동과 맞지 않는 Selector 차단 |
| `test_missing_select_device_value_is_rejected_by_cp3` | 선택 장비 값 누락 차단 |
| `test_observed_but_wrong_assertion_selector_is_rejected_by_cp3` | 잘못된 Assertion 대상 차단 |
| `test_ungrounded_numeric_expectation_is_rejected_by_cp3` | 무근거 숫자 기대값 차단 |
| `test_unsupported_expected_text_is_rejected_by_cp3` | 컴파일러 미지원 텍스트 기대값 차단 |
| `test_generic_visible_toast_is_rejected_for_blocking_expected_result` | 차단 Toast 의미 약화 차단 |
| `test_missing_expected_result_mapping_is_rejected_by_cp3` | Expected Result 매핑 누락 차단 |
| `test_agent3_trial_distinguishes_product_mismatch` | 제품 불일치 후보 분류·복합 내부 필드 관찰 |
| `test_central_blocked_temperature_without_notification_uses_stall_request` | 알림 기대 결과가 없어도 중앙 패널 차단 요청을 정지형 조작으로 컴파일 |
| `test_agent3_trace_redaction_handles_path_uri_and_json_escapes` | Trace 경로·URI·JSON escape 치환 |
| `test_agent3_trial_strips_secrets_and_redacts_local_paths` | Trial 증거 비밀정보·로컬 경로 제거 |
| `test_agent3_timeout_discards_incomplete_unredacted_trace` | 시간 초과로 미완성된 미정제 Trace의 증거 제외 |
| `test_trial_timeout_terminates_playwright_child_processes` | 시간 초과 시 pytest·Playwright 자식 프로세스 트리 정리 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[PASS]` | 신뢰 가능한 PASS 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[PRODUCT_MISMATCH_CANDIDATE]` | 제품 불일치 후보 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[AUTOMATION_ERROR]` | 자동화 오류 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[ENVIRONMENT_ERROR]` | 환경 오류 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[TIMEOUT]` | 시간 초과 종료 코드 |
| `test_agent3_cli_exit_code_blocks_missing_trial_or_failed_checkpoint` | Trial/CP3 누락 종료 차단 |
| `test_agent3_usage_aggregates_all_planning_attempts` | 재계획 시도 사용량 누적 |
| `test_model_usage_records_cache_and_reasoning_details` | 캐시 입력·캐시 기록·추론 토큰 상세 집계 |
| `test_agent3_error_artifact_requires_a_fresh_attempt_workspace` | 오류 Run 재사용 차단 |
| `test_modified_agent2_artifact_is_blocked_before_agent3` | 변조된 Agent 2 산출물 차단 |
| `test_pipeline_parser_exposes_one_command_agent1_to_agent3` | Agent 1→3 CLI Parser |
| `test_agent3_selection_excludes_related_regression_candidates` | 관련 기존 회귀의 Agent 3 재구현·모델 호출 차단 |
| `test_pipeline_runs_stages_in_order_and_hashes_manifests` | 오케스트레이터 순서·SHA 연결 |
| `test_pipeline_continues_after_one_agent3_candidate_is_excluded` | 실행 불가 후보 제외 후 다음 후보 계속 실행 |
| `test_pipeline_reports_all_agent3_candidates_excluded_without_stopping` | 모든 신규 후보가 제외돼도 중단하지 않고 후속 보고용 요약 생성 |
| `test_pipeline_keeps_manual_candidates_in_exclusions_without_agent3_call` | 수동 TC의 제외 사유 인계와 Agent 3 모델 미호출 |
| `test_pipeline_stops_after_checkpoint_block_without_later_calls` | Checkpoint 차단 시 후속 호출 금지 |
| `test_pipeline_rejects_missing_target_before_any_model_stage` | 대상 파일 누락 사전 차단 |
| `test_related_regression_selection_is_grounded_and_excludes_demo_cases` | 관련 회귀 선택·데모 제외 |
| `test_existing_regression_runs_from_a_copied_neutral_workspace` | 원본과 분리된 회귀 Workspace와 Trace 내부 로컬 경로 정제 |
| `test_candidate_trial_is_reused_only_after_hash_and_evidence_checks` | 후보 재사용 전 해시·증거 확인 |
| `test_current_compiler_reuses_identical_code_and_retrials_stale_code` | 코드 동일성 재사용·변경 시 재시험 |
| `test_candidate_handoff_recomputes_current_cp3_rules` | 검증 실행 인계 전 현재 CP3 규칙 재계산 |
| `test_candidate_handoff_rejects_evidence_changed_after_agent3` | Agent 3 기록 뒤 변경된 증거 파일 차단 |

## 5. 변경 검증·기존 회귀 실행 (6건)

| 테스트 | 확인 내용 |
|---|---|
| `test_validation_execution_reuses_candidate_and_runs_related_regressions` | 후보 재사용과 관련 회귀 실행 |
| `test_validation_execution_carries_multiple_candidates_and_exclusions` | 여러 신규 후보 결과와 자동화 제외 목록 인계 |
| `test_validation_execution_runs_existing_tc_when_no_new_candidate_is_needed` | 신규 후보 없이 선택된 기존 TC만 환경 점검 뒤 실행 |
| `test_validation_execution_stops_regressions_when_precheck_is_not_passed` | 환경 점검 실패 시 회귀 차단 |
| `test_execute_parser_exposes_validation_execution_command` | `execute` CLI Parser |
| `test_current_candidate_trial_returns_technical_failure_for_agent4` | 후보 기술 실패를 예외 대신 중립 결과로 Agent 4에 전달 |

## 6. Agent 4·CP4·최종 보고·외부 전달 (25건)

| 테스트 | 확인 내용 |
|---|---|
| `test_agent4_writes_consistent_pass_report_without_rerunning_tests` | 무재실행 PASS 보고 정합성 |
| `test_notion_preserves_separate_runs_and_retries_same_tc_without_reclassification` | Run별 페이지 분리·같은 실행 재전송·실패로 TC 유형/우선순위 재분류 금지 |
| `test_agent4_accepts_approved_regression_automation_hash` | 승인 공식 TC의 별도 자동화 경로·해시를 기준 회귀 해시와 구분해 CP4 검증 |
| `test_agent4_rejects_approved_regression_without_catalog_hash` | 승인 자산이 있는데 카탈로그 Snapshot 해시가 없으면 CP4 출처 체인 차단 |
| `test_agent4_send_delivers_only_after_cp4_pass` | CP4 PASS 뒤에만 Slack·Notion 명시적 전송 허용 |
| `test_external_reporting_send_after_preview_preserves_first_evidence` | Dry-run 뒤 실제 전송 시 최초 증거 보존과 별도 시도 SHA 연결 |
| `test_agent4_verifies_multiple_agent3_source_artifacts` | 여러 Agent 3 후보 Manifest·Trial·Candidate 해시 체인 검사 |
| `test_agent4_reports_automation_exclusion_without_blocking_executed_results` | 자동화 제외 TC 보고와 실행 완료 결과의 비차단 분리 |
| `test_agent4_reports_all_excluded_candidates_for_human_review` | 실행된 신규 후보가 없고 제외만 있으면 최종 사람 검토 권고 |
| `test_agent4_passes_existing_only_execution_without_new_candidate` | 신규 후보가 필요 없는 기존 TC 전용 실행은 최종 PASS 가능 |
| `test_agent4_marks_assertion_failure_as_product_mismatch_candidate` | Assertion 실패의 제품 불일치 후보 분류 |
| `test_agent4_reports_restore_failure_without_hiding_product_observation` | 복원 단독·제품 불일치 동시 발생 2건의 HOLD 분류·두 관찰 보존·중복 집계 방지 |
| `test_agent4_ignores_restore_marker_in_source_code_and_unverified_logs` | 소스 문자열을 실제 복원 실패로 오인하지 않고 변조 로그는 CP4 차단 |
| `test_existing_only_procedure_notes_reach_final_human_review` | 기존 TC의 준비·복원 메모 원문이 최종 보고·검토서에 전달되고 요청 변조는 차단 |
| `test_agent4_carries_non_blocking_review_notes_to_final_report` | 최종 확인 사항의 최종 보고 전달 |
| `test_agent4_holds_when_environment_precheck_blocks_regressions` | 환경 차단 시 HOLD 권고 |
| `test_agent4_rejects_validation_execution_hash_mismatch` | 실행 결과 SHA 불일치 차단 |
| `test_agent4_rejects_mismatched_execution_source_contract` | 실행 출처 계약 불일치 차단 |
| `test_agent4_rejects_missing_or_changed_evidence_file` | 증거 파일 누락·변조 차단 |
| `test_agent4_parser_exposes_rules_only_report_command` | `agent4` CLI Parser |
| `test_agent4_holds_candidate_automation_execution_issue` | 후보 자동화 실행 오류의 HOLD 권고 |
| `test_agent4_holds_when_product_mismatch_and_automation_issue_coexist` | 제품 불일치와 자동화 오류가 함께 있으면 HOLD 우선 |
| `test_agent4_rejects_broken_manifest_or_candidate_chain` | Agent 3→검증 Manifest 또는 실제 후보 파일 체인 불일치 차단 |
| `test_agent4_rejects_passed_result_without_complete_evidence` | 완전한 증거 없는 PASS 결과 차단 |

## 7. 중앙제어 공개 데모·실제 Run 연동·후보 자산 승인 (32건)

추가한 SRS 단독 승인 테스트:

- `test_existing_srs_approval_requires_consent_and_creates_no_tc`: 기본 잠금·동의·보류·승인·멱등성과 TC 미생성
- `test_existing_srs_approval_rejects_changed_inputs`: 현재 화면·증거·제안·SRS 변경 차단 4건
- `test_existing_srs_approval_rolls_back_on_record_failure`: 기록 실패 시 SRS 원상복구
- `test_existing_srs_approval_works_through_browser_and_http`: 실제 브라우저→HTTP→임시 SRS 승인, 두 단계 확인

| 테스트 | 확인 내용 |
|---|---|
| `test_pipeline_ui_summarizes_real_run_artifacts` | Agent 1~4·검증·외부 보고 JSON을 실제 Run 표시용으로 일관되게 요약 |
| `test_run_test_rows_keep_design_type_failure_reason_and_manual_exclusions_separate` | 실제 TC 상세 표의 설계 유형·실패 원인·수동 확인·미실행 분리 |
| `test_pipeline_ui_shows_latest_delivery_and_preserves_prior_send_history` | 후속 전송 상태 반영, 이후 미리보기와 과거 전송 기록 구분, 최초 파일 보존 |
| `test_pipeline_ui_reports_environment_block_without_external_send` | 환경 실패 후 실제 Agent 4·CP4 코드로 HOLD 보고 생성, 외부 전송 없음 |
| `test_pipeline_ui_stops_on_missing_or_damaged_failure_bundle` | 유효한 실패 결과가 없으면 보고 단계로 우회하지 않고 중단 |
| `test_pipeline_ui_rejects_unscoped_run_and_request_paths` | Run ID·변경 요청 파일 경로 우회와 기본 Live 실행 차단 |
| `test_pipeline_ui_failure_message_is_safe_and_actionable` | 로컬 경로를 숨긴 Agent 3 TC별 실패·시간 초과 원인 표시 |
| `test_pipeline_ui_live_run_is_disabled_by_default` | 로컬 브리지의 새 API 실행 기본 잠금 |
| `test_pipeline_ui_prevents_parallel_live_runs_across_bridges` | 여러 로컬 브리지에서 같은 저장소 Live Run 중복 실행 차단 |
| `test_pipeline_ui_live_run_uses_agent1_to_4_order_without_external_send` | 순서·외부 전송 금지·설정 경로 전달·다른 Run 혼입 방지 |
| `test_pipeline_ui_browser_recovers_polling_and_preserves_selected_run` | 브라우저 재접속·창 닫기·통신 장애 복구, 조회 선택과 응답 순서 보호 |
| `test_public_demo_shows_one_v2_normal_change_without_api_or_file_registration` | 공개 MED 정상 변경 데모의 Agent 1~4·TC 상세·승인 미리보기와 API 호출·파일 등록 없음 |
| `test_ui_waits_for_final_report_before_overall_pass` | Agent 3 통과를 전체 통과로 표시하지 않고 최종 보고 전 대기·중단 및 최종 권고를 구분 |
| `test_asset_approval_rejects_different_executed_code` | 다른 코드 해시의 실행 기록으로 공식 승인·재검증하지 않음 |
| `test_report_uses_verified_tc_snapshot_and_legacy_custom_root` | TC 원문 보존·해시 확인, 과거 기록의 지정 폴더 사용 |
| `test_browser_resets_cross_run_consent_and_separates_timeouts` | Run 변경 시 동의 초기화, 조회/처리 대기시간 분리, 설명 겹침 방지 |
| `test_pipeline_explicit_run_id_is_forwarded_and_cannot_overwrite` | 명시 Run ID 인계·기존 ID 및 경로 우회 거부 |
| `test_v2_product_ui_routes_agent_buttons_to_real_run_bridge` | 팀장·Agent 1~4 버튼의 실제 Run 패널 연결과 외부 보고 미리보기 고정 |
| `test_pipeline_ui_human_approval_registers_immutable_tc_and_automation` | 사람 승인 시 후보 TC·자동화·Registry SHA-256 등록과 중복 승인 멱등성 |
| `test_approved_tc_registry_is_loaded_and_official_automation_is_reusable` | 승인 Registry·공개 재검증 요약 해시 검증과 공식 Python의 실제 Playwright 재실행·증거 생성 |
| `test_pipeline_ui_requires_and_applies_srs_revision_with_asset_approval` | 현재 후보에 연결된 SRS 제안만 표시·동의·개정하고 다른 후보 제안은 보존 |
| `test_pipeline_ui_rolls_back_all_asset_files_when_approval_copy_fails` | SRS·TC·자동화·Registry 승인 중 실패 시 본 파일과 임시 파일 원상복구 |
| `test_pipeline_ui_hold_is_recorded_and_can_later_be_approved` | 보류 사유 기록, 공식 자산 미생성, 후속 승인 전환 |
| `test_pipeline_ui_blocks_asset_approval_for_failed_or_stale_evidence` | 최종 실패·현재 HTML 해시 불일치 후보의 공식 등록 차단 |
| `test_pipeline_ui_revalidates_stale_candidate_without_model_call` | HTML 변경 뒤 모델 호출 없는 후보 재검증, 공개 요약·원본 해시 기록과 승인 가능 상태 복구 |

## 8. 코드 감사 후 명백한 오류 방지 (36건)

기존 1~7절의 209건에 추가된 검증입니다. 제품 후보 TC가 늘어난 것이 아니라 검사기의 오류 차단·정상 허용 조합을 추가했습니다.

| 테스트 | 실행 수 | 확인 내용 |
|---|---:|---|
| `test_cp1_rejects_explicit_meaning_and_source_errors` | 4 | 의미 반전·근거 밖 숫자·유지 역할·Requirement 출처 오류 차단, 과거 계약 구분 |
| `test_source_quote_respects_code_and_number_boundaries` | 1 | ON/NONE·30/130 구분과 정상 한국어 조사 허용 |
| `test_cp2_rejects_opposite_existing_behavior_and_srs_value` | 1 | 반대 동작 기존 TC 재사용과 잘못된 SRS 값 차단 |
| `test_cp3_rejects_false_pass_plans` | 5 | 활성 반전·시험/복원 누락·약한 텍스트·중복 요소 차단, 정상 계획 통과 |
| `test_scalar_guard_distinguishes_values` | 10 | 한국어·영어 긍정/부정, 명시 boolean과 필드명, 코드·숫자 구분 |
| `test_inventory_counts_duplicate_selectors_and_target_only_fields` | 1 | 실제 브라우저의 중복 Selector 수집과 대상 장비 필드 한정 |
| `test_orchestrator_records_internal_errors_and_explicit_scope` | 4 | 예외·저장 오류의 비정상 종료, 다른 후보 계속 처리, 명시 선택·없는 ID |
| `test_error_manifest_preserves_original_error_with_broken_summary` | 1 | 손상 요약이 있어도 원래 오류 기록 |
| `test_regression_skip_uses_result_summary_not_warning` | 2 | 경고문 skipped는 PASS 유지, 실제 요약 skipped는 미실행 |
| `test_regression_timeout_uses_process_tree_cleanup` | 1 | 기존 회귀 시간 초과의 공통 프로세스 정리 호출·TIMEOUT 기록 |
| `test_local_mutations_require_same_origin_json` | 6 | 정상 동일 출처 허용, 외부/null/누락 Origin·Host 위조·text/plain 거부 |

## 갱신 규칙

1. 새 테스트를 추가하거나 삭제하면 이 목록의 항목과 수량을 함께 갱신합니다.
2. 변경 후 `python -m pytest --collect-only -q`의 수가 이 문서의 합계와 같은지 확인합니다.
3. 테스트 함수 이름이 비슷해도 검증 계층(입력 계약·Checkpoint·컴파일·브라우저 시험·증거·보고)이 다르면 합치지 않습니다.
