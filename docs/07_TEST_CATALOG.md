# 자동 테스트 카탈로그

최종 확인: 2026-09-06
실행 기준: `python -m pytest --collect-only -q` → **187건**
실제 정의 파일: `tests/test_srs_agent1.py`, `tests/test_agent2.py`, `tests/test_integrity_cli.py`, `tests/test_agent3.py`, `tests/test_orchestration_execution.py`, `tests/test_agent4_reporting.py`, `tests/test_pipeline_ui.py`

이 문서는 현재 수집되는 자동 테스트를 사람이 확인하기 쉽게 정리한 목록입니다. 실행의 기준은 항상 테스트 코드와 Pytest 수집 결과이며, 테스트를 추가·삭제할 때는 이 문서도 같은 변경에서 갱신합니다.

## 수량 구조

| 구성 | 수량 | 설명 |
|---|---:|---|
| 일반 테스트 함수 | 182 | 함수 하나가 Pytest 실행 1건 |
| 파라미터 테스트 함수 | 1 | 아래 5개 Trial 결과를 각각 독립 실행 |
| 합계 | **187** | 현재 Pytest 수집 수 |

파라미터 테스트 `test_agent3_cli_exit_code_reflects_trial_trustworthiness`는 다음 다섯 결과를 별도 실행합니다: `PASS`, `PRODUCT_MISMATCH_CANDIDATE`, `AUTOMATION_ERROR`, `ENVIRONMENT_ERROR`, `TIMEOUT`.

## 1. 기준 자산·SRS·Agent 1·Checkpoint 1 (26건)

| 테스트 | 확인 내용 |
|---|---|
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
| `test_related_requirement_can_be_marked_update_required` | 연관 Requirement UPDATE_REQUIRED 허용 |
| `test_proceed_with_open_question_is_recorded_for_final_review` | PROCEED 보완 REVIEW의 최종 보고 이관 |
| `test_scope_limited_acceptance_note_is_only_excluded` | 범위 제한 인수 조건을 확정 조건이 아닌 제외 범위로 전달 |
| `test_scope_limited_acceptance_note_cannot_be_confirmed_condition` | 범위 제한 문구의 확정 조건 혼입 차단 |

## 2. Agent 2·Checkpoint 2·인계 (47건)

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
| `test_checkpoint2_allows_existing_tc_only_when_behavior_covers_change` | 변경 후 동작을 이미 검증하는 기존 TC만으로 CP2 통과 |
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

## 4. Agent 3 CP3·후보 시험·증거 (40건)

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

## 6. Agent 4·CP4·최종 보고·외부 전달 (21건)

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

## 7. 중앙제어 실제 Run 연동·후보 자산 승인 (18건)

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
| `test_pipeline_ui_live_run_uses_agent1_to_4_order_without_external_send` | 허용 모드의 Agent 1→3·검증·Agent 4 순서와 외부 전송 금지 |
| `test_v2_product_ui_routes_agent_buttons_to_real_run_bridge` | 팀장·Agent 1~4 버튼의 실제 Run 패널 연결과 외부 보고 미리보기 고정 |
| `test_pipeline_ui_human_approval_registers_immutable_tc_and_automation` | 사람 승인 시 후보 TC·자동화·Registry SHA-256 등록과 중복 승인 멱등성 |
| `test_approved_tc_registry_is_loaded_and_official_automation_is_reusable` | 승인 Registry 자산 로딩·해시 검증과 공식 Python의 실제 Playwright 재실행·증거 생성 |
| `test_pipeline_ui_requires_and_applies_srs_revision_with_asset_approval` | 현재 후보에 연결된 SRS 제안만 표시·동의·개정하고 다른 후보 제안은 보존 |
| `test_pipeline_ui_rolls_back_all_asset_files_when_approval_copy_fails` | SRS·TC·자동화·Registry 승인 중 실패 시 본 파일과 임시 파일 원상복구 |
| `test_pipeline_ui_hold_is_recorded_and_can_later_be_approved` | 보류 사유 기록, 공식 자산 미생성, 후속 승인 전환 |
| `test_pipeline_ui_blocks_asset_approval_for_failed_or_stale_evidence` | 최종 실패·현재 HTML 해시 불일치 후보의 공식 등록 차단 |
| `test_pipeline_ui_revalidates_stale_candidate_without_model_call` | HTML 변경 뒤 모델 호출 없는 후보 재검증과 승인 가능 상태 복구 |

## 갱신 규칙

1. 새 테스트를 추가하거나 삭제하면 이 목록의 항목과 수량을 함께 갱신합니다.
2. 변경 후 `python -m pytest --collect-only -q`의 수가 이 문서의 합계와 같은지 확인합니다.
3. 테스트 함수 이름이 비슷해도 검증 계층(입력 계약·Checkpoint·컴파일·브라우저 시험·증거·보고)이 다르면 합치지 않습니다.
