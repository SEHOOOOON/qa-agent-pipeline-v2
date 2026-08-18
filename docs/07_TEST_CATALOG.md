# 자동 테스트 카탈로그

최종 확인: 2026-08-18
실행 기준: `python -m pytest --collect-only -q` → **97건**
실제 정의 파일: `tests/test_pipeline.py`

이 문서는 현재 수집되는 자동 테스트를 사람이 확인하기 쉽게 정리한 목록입니다. 실행의 기준은 항상 테스트 코드와 Pytest 수집 결과이며, 테스트를 추가·삭제할 때는 이 문서도 같은 변경에서 갱신합니다.

## 수량 구조

| 구성 | 수량 | 설명 |
|---|---:|---|
| 일반 테스트 함수 | 90 | 함수 하나가 Pytest 실행 1건 |
| 파라미터 테스트 함수 | 1 | 아래 5개 Trial 결과를 각각 독립 실행 |
| 합계 | **95** | 현재 Pytest 수집 수 |

파라미터 테스트 `test_agent3_cli_exit_code_reflects_trial_trustworthiness`는 다음 다섯 결과를 별도 실행합니다: `PASS`, `PRODUCT_MISMATCH_CANDIDATE`, `AUTOMATION_ERROR`, `ENVIRONMENT_ERROR`, `TIMEOUT`.

## 1. SRS·Agent 1·Checkpoint 1 (20건)

| 테스트 | 확인 내용 |
|---|---|
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
| `test_missing_requested_out_of_scope_is_rejected` | 요청된 제외 범위 누락 차단 |
| `test_redundant_reconfirmation_requires_review` | 불필요한 재확인 REVIEW |
| `test_legitimate_missing_detail_question_passes_checkpoint` | 정당한 세부 질문 허용 |
| `test_partial_proceed_pauses_agent2_handoff` | PARTIAL_PROCEED의 Agent 2 중단 |
| `test_blocked_decision_blocks_agent2_handoff` | BLOCKED의 후속 단계 차단 |
| `test_related_requirement_can_be_marked_update_required` | 연관 Requirement UPDATE_REQUIRED 허용 |
| `test_proceed_with_open_question_is_recorded_for_final_review` | PROCEED 보완 REVIEW의 최종 보고 이관 |

## 2. Agent 2·Checkpoint 2·인계 (19건)

| 테스트 | 확인 내용 |
|---|---|
| `test_agent2_uses_structured_responses_api` | Agent 2 구조화 API 계약 |
| `test_agent2_missing_api_key_fails_before_network` | API 키 누락 시 사전 차단 |
| `test_valid_design_passes_checkpoint2` | 유효 TC 설계의 CP2 통과 |
| `test_human_review_note_pauses_checkpoint2` | 사람 검토 메모의 PAUSE |
| `test_coverage_note_does_not_pause_checkpoint2` | 참고 메모 허용 |
| `test_final_review_note_does_not_pause_checkpoint2` | 최종 확인 사항의 자동 진행 |
| `test_control_requirement_cannot_use_local_path` | 중앙 제어 요구사항의 LOCAL 경로 차단 |
| `test_active_central_path_requires_direct_change_validation` | 중앙 직접 변경 검증 강제 |
| `test_structured_test_data_is_required_for_boundary_tc` | 경계 TC 구조화 시험 데이터 강제 |
| `test_boundary_tc_with_initial_mode_requires_requested_mode_for_agent3` | Agent 3용 요청 모드 데이터 강제 |
| `test_missing_condition_is_rejected` | Condition 추적 누락 차단 |
| `test_missing_internal_state_assertion_is_rejected` | 내부 상태 검증 누락 차단 |
| `test_state_consistency_type_without_internal_state_is_rejected` | 상태 정합성 내부 검증 강제 |
| `test_playwright_code_is_rejected` | TC 내 Playwright 코드 혼입 차단 |
| `test_verified_agent1_run_can_handoff_to_agent2` | 검증된 Agent 1 SHA 인계 |
| `test_modified_agent1_artifact_is_blocked_before_agent2` | 변조된 Agent 1 산출물 차단 |
| `test_paused_manifest_is_blocked_before_agent2` | PAUSE Manifest 차단 |
| `test_agent1_to_agent2_cli_handoff_with_frozen_inputs` | CLI 동결 입력 인계 |
| `test_agent2_rejects_an_active_run_reservation` | 동시 Agent 2 실행 예약 차단 |

## 3. Agent 3 조사·계획 계약 (18건)

| 테스트 | 확인 내용 |
|---|---|
| `test_agent3_uses_structured_plan_api` | Agent 3 구조화 계획 Schema·시스템 지침 |
| `test_agent3_model_input_preview_is_minimal_and_has_no_local_path` | Preview 최소 전송·경로 제외 |
| `test_agent3_eligibility_scopes_ui_inventory_to_selected_tc` | 선택 TC 범위 UI 조사 |
| `test_agent3_scoped_inventory_still_blocks_a_required_selector` | 필수 Selector 누락 차단 |
| `test_agent3_inspection_waits_for_delayed_required_selector` | 비동기 UI 초기화 대기 |
| `test_agent3_unknown_internal_state_uses_generic_discovery` | 미지 내부 상태의 동적 조사 |
| `test_agent3_registered_device_fields_are_grounded_and_compiled` | 등록 장비 필드·TC 근거·컴파일 |
| `test_agent3_rejects_unobserved_or_ungrounded_device_fields` | 미관찰·무근거 장비 필드 차단 |
| `test_agent3_non_hvac_mode_values_use_generic_discovery` | 비 HVAC 상태값의 동적 조사 |
| `test_agent3_textual_link_tolerates_korean_particles` | 한국어 조사·어미 의미 연결 |
| `test_agent3_notification_rejects_the_whole_expected_result_as_ui_text` | 알림 Expected Result 전체 문구 오사용 차단 |
| `test_agent3_generic_discovery_compiles_and_runs_a_new_control` | 신규 범용 제어의 조사·컴파일·시험 |
| `test_agent3_records_support_extension_without_generating_code` | 지원 범위 확장 REVIEW·코드 미생성 |
| `test_agent3_non_candidate_records_not_automatable_before_ui_or_model` | 자동화 후보 아님 사전 종료 |
| `test_agent3_preview_does_not_require_api_key_or_create_model_client` | Preview 무API 보장 |
| `test_valid_agent3_plan_passes_cp3_and_compiles` | 유효 계획 CP3·코드 생성 |
| `test_blocked_temperature_request_compiles_until_target_or_stall` | 차단 온도 요청 반복·정지 계약 |
| `test_restore_contract_requires_initial_temperature_and_apply` | 복원 계약 누락 차단 |

## 4. Agent 3 CP3·후보 시험·증거 (29건)

| 테스트 | 확인 내용 |
|---|---|
| `test_compiler_verifies_restored_ui_and_internal_temperature` | 복원 후 UI·내부 온도 재확인 |
| `test_unobserved_selector_is_rejected_by_cp3` | 미관찰 Action Selector 차단 |
| `test_observed_but_wrong_action_selector_is_rejected_by_cp3` | 행동과 맞지 않는 Selector 차단 |
| `test_missing_select_device_value_is_rejected_by_cp3` | 선택 장비 값 누락 차단 |
| `test_observed_but_wrong_assertion_selector_is_rejected_by_cp3` | 잘못된 Assertion 대상 차단 |
| `test_ungrounded_numeric_expectation_is_rejected_by_cp3` | 무근거 숫자 기대값 차단 |
| `test_unsupported_expected_text_is_rejected_by_cp3` | 컴파일러 미지원 텍스트 기대값 차단 |
| `test_generic_visible_toast_is_rejected_for_blocking_expected_result` | 차단 Toast 의미 약화 차단 |
| `test_missing_expected_result_mapping_is_rejected_by_cp3` | Expected Result 매핑 누락 차단 |
| `test_agent3_trial_distinguishes_product_mismatch` | 제품 불일치 후보 분류·복합 내부 필드 관찰 |
| `test_agent3_trace_redaction_handles_path_uri_and_json_escapes` | Trace 경로·URI·JSON escape 치환 |
| `test_agent3_trial_strips_secrets_and_redacts_local_paths` | Trial 증거 비밀정보·로컬 경로 제거 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[PASS]` | 신뢰 가능한 PASS 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[PRODUCT_MISMATCH_CANDIDATE]` | 제품 불일치 후보 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[AUTOMATION_ERROR]` | 자동화 오류 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[ENVIRONMENT_ERROR]` | 환경 오류 종료 코드 |
| `test_agent3_cli_exit_code_reflects_trial_trustworthiness[TIMEOUT]` | 시간 초과 종료 코드 |
| `test_agent3_cli_exit_code_blocks_missing_trial_or_failed_checkpoint` | Trial/CP3 누락 종료 차단 |
| `test_agent3_usage_aggregates_all_planning_attempts` | 재계획 시도 사용량 누적 |
| `test_agent3_error_artifact_requires_a_fresh_attempt_workspace` | 오류 Run 재사용 차단 |
| `test_modified_agent2_artifact_is_blocked_before_agent3` | 변조된 Agent 2 산출물 차단 |
| `test_pipeline_parser_exposes_one_command_agent1_to_agent3` | Agent 1→3 CLI Parser |
| `test_pipeline_runs_stages_in_order_and_hashes_manifests` | 오케스트레이터 순서·SHA 연결 |
| `test_pipeline_stops_after_checkpoint_block_without_later_calls` | Checkpoint 차단 시 후속 호출 금지 |
| `test_pipeline_rejects_missing_target_before_any_model_stage` | 대상 파일 누락 사전 차단 |
| `test_related_regression_selection_is_grounded_and_excludes_demo_cases` | 관련 회귀 선택·데모 제외 |
| `test_existing_regression_runs_from_a_copied_neutral_workspace` | 원본과 분리된 회귀 Workspace |
| `test_candidate_trial_is_reused_only_after_hash_and_evidence_checks` | 후보 재사용 전 해시·증거 확인 |
| `test_current_compiler_reuses_identical_code_and_retrials_stale_code` | 코드 동일성 재사용·변경 시 재시험 |

## 5. 변경 검증·기존 회귀 실행 (3건)

| 테스트 | 확인 내용 |
|---|---|
| `test_validation_execution_reuses_candidate_and_runs_related_regressions` | 후보 재사용과 관련 회귀 실행 |
| `test_validation_execution_stops_regressions_when_precheck_is_not_passed` | 환경 점검 실패 시 회귀 차단 |
| `test_execute_parser_exposes_validation_execution_command` | `execute` CLI Parser |

## 6. Agent 4·CP4·최종 보고 (8건)

| 테스트 | 확인 내용 |
|---|---|
| `test_agent4_writes_consistent_pass_report_without_rerunning_tests` | 무재실행 PASS 보고 정합성 |
| `test_agent4_marks_assertion_failure_as_product_mismatch_candidate` | Assertion 실패의 제품 불일치 후보 분류 |
| `test_agent4_carries_non_blocking_review_notes_to_final_report` | 최종 확인 사항의 최종 보고 전달 |
| `test_agent4_holds_when_environment_precheck_blocks_regressions` | 환경 차단 시 HOLD 권고 |
| `test_agent4_rejects_validation_execution_hash_mismatch` | 실행 결과 SHA 불일치 차단 |
| `test_agent4_rejects_mismatched_execution_source_contract` | 실행 출처 계약 불일치 차단 |
| `test_agent4_rejects_missing_or_changed_evidence_file` | 증거 파일 누락·변조 차단 |
| `test_agent4_parser_exposes_rules_only_report_command` | `agent4` CLI Parser |

## 갱신 규칙

1. 새 테스트를 추가하거나 삭제하면 이 목록의 항목과 수량을 함께 갱신합니다.
2. 변경 후 `python -m pytest --collect-only -q`의 수가 이 문서의 합계와 같은지 확인합니다.
3. 테스트 함수 이름이 비슷해도 검증 계층(입력 계약·Checkpoint·컴파일·브라우저 시험·증거·보고)이 다르면 합치지 않습니다.
