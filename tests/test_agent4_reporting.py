"""qa_pipeline_v2 역할별 자동 회귀 테스트."""

from pipeline_test_support import *


def test_agent4_reports_precondition_failure_as_unexecuted_product_test(tmp_path):
    run_dir, run_id = _write_agent4_inputs(tmp_path,
        candidate_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR,
        candidate_stdout="E AssertionError: PRECONDITION_NOT_MET: check 1 expected=False actual=True\n")
    assert pipeline.run_agent4(SimpleNamespace(run_id=run_id, runs_root=str(run_dir.parent))) == 0
    report = pipeline.FinalReport.model_validate_json((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert report.recommendation == pipeline.FinalRecommendation.HOLD
    assert any("사전조건" in finding.rationale for finding in report.findings)
    assert all(finding.category != pipeline.Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE for finding in report.findings)
    assert "사전조건 불충족·본 시험 미실행" in (run_dir / "사람_최종_검토.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("changed_file", ["validation_execution.json", "final_report.json"])
def test_report_consumers_reject_changed_sources(tmp_path, changed_file):
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    args = SimpleNamespace(run_id=run_id, runs_root=str(run_dir.parent), send=False)
    assert pipeline.run_agent4(args) == 0
    payload = json.loads((run_dir / changed_file).read_text(encoding="utf-8"))
    if changed_file == "final_report.json":
        payload["total_results"] += 1
    else:
        payload["created_at"] = "2026-09-12T12:00:00Z"
    _write_json(run_dir / changed_file, payload)
    assert pipeline.run_external_reporting(args) == 2
    with pytest.raises(ValueError):
        pipeline.run_human_review_document(args)


def test_notion_preserves_separate_runs_and_retries_same_tc_without_reclassification(monkeypatch) -> None:
    monkeypatch.setenv("NOTION_API_KEY", "test-only-not-a-secret")
    monkeypatch.setenv("NOTION_DATA_SOURCE_ID", "test-data-source")
    pages, writes, queries = {}, [], []

    def fake_http(method, url, payload, **kwargs):
        if url.endswith("/query"):
            key = payload["filter"]["title"]["equals"]
            queries.append(key)
            return 200, {"results": [{"id": pages[key]}] if key in pages else []}
        key = payload["properties"]["TC-ID"]["title"][0]["text"]["content"]
        pages.setdefault(key, f"page-{len(pages) + 1}")
        writes.append((method, payload["properties"]))
        return 200, {"id": pages[key]}

    monkeypatch.setattr(pipeline_reporting, "_http_json_request", fake_http)
    record = {
        "run_id": "RUN-A", "tc_id": "TC-CAND-001", "result": "ASSERTION_FAILED",
        "finding_category": "PRODUCT_MISMATCH_CANDIDATE", "recommendation": "HUMAN_REVIEW",
        "test_category": "해피패스", "title": "정상 표시 검증", "priority": "미지정",
    }
    for run_id in ("RUN-A", "RUN-B", "RUN-A"):
        result = pipeline_reporting._upsert_notion_reports([{**record, "run_id": run_id}])
        assert result.status == pipeline.ExternalDeliveryStatus.SENT
    assert queries == ["RUN-A:TC-CAND-001", "RUN-B:TC-CAND-001", "RUN-A:TC-CAND-001"]
    assert [method for method, _ in writes] == ["POST", "POST", "PATCH"]
    assert len(pages) == 2
    assert all(props["구분"]["select"]["name"] == "해피패스" for _, props in writes)
    assert all("우선 순위" not in props for _, props in writes)


def test_agent4_writes_consistent_pass_report_without_rerunning_tests(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path,
        excluded_scope=["정확한 차단 안내 문구"],
        excluded_information_gaps=["정확한 안내 문구가 정의되지 않음"],
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    analysis = pipeline.Agent4Analysis.model_validate_json(
        (run_dir / "agent4_analysis.json").read_text(encoding="utf-8")
    )
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    delivery = pipeline.ExternalReportingResult.model_validate_json(
        (run_dir / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.PASS
    assert analysis.total_results == 3
    assert analysis.status_counts[pipeline.NeutralExecutionStatus.PASSED] == 3
    assert analysis.product_result_count == 2
    assert analysis.environment_result_count == 1
    assert analysis.pipeline_fixture_result_count == 0
    assert analysis.findings == []
    assert analysis.excluded_scope == ["정확한 차단 안내 문구"]
    assert analysis.excluded_information_gaps == ["정확한 안내 문구가 정의되지 않음"]
    assert report.recommendation == pipeline.FinalRecommendation.HUMAN_REVIEW
    assert report.total_results == analysis.total_results
    assert report.status_counts == analysis.status_counts
    assert report.product_result_count == 2
    assert report.environment_result_count == 1
    assert report.pipeline_fixture_result_count == 0
    assert report.excluded_scope == analysis.excluded_scope
    assert report.excluded_information_gaps == analysis.excluded_information_gaps
    assert delivery.mode == "DRY_RUN"
    assert delivery.allowed is True
    assert delivery.slack.status == pipeline.ExternalDeliveryStatus.PREVIEW
    assert delivery.notion.status == pipeline.ExternalDeliveryStatus.PREVIEW
    assert delivery.notion.item_count == 3
    assert (run_dir / "slack_payload.json").is_file()
    assert (run_dir / "notion_payload.json").is_file()
    raw_analysis = json.loads((run_dir / "agent4_analysis.json").read_text(encoding="utf-8"))
    raw_report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert "검토_항목" in raw_analysis
    assert "최종_확인_사항" in raw_analysis
    assert "제외_범위" in raw_analysis
    assert "제외된_정보_부족" in raw_analysis
    assert "검토_항목" in raw_report
    assert "최종_확인_사항" in raw_report
    assert "제외_범위" in raw_report
    assert "제외된_정보_부족" in raw_report

def test_agent4_accepts_approved_regression_automation_hash(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    execution_file = run_dir / "validation_execution.json"
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        execution_file.read_text(encoding="utf-8")
    )
    approved_hash = "a" * 64
    approved_result = bundle.regression_results[0].model_copy(
        update={
            "test_id": "TC-V2-001",
            "test_file": "automation/test_tc_v2_001.py",
            "test_sha256": approved_hash,
        }
    )
    bundle = bundle.model_copy(
        update={
            "selected_regression_ids": ["TC-V2-001"],
            "regression_results": [approved_result],
        }
    )
    _write_json(execution_file, bundle.model_dump(mode="json"))

    catalog_file = run_dir / "approved_regression_catalog.json"
    _write_json(
        catalog_file,
        {
            "contract_version": "1.0",
            "approved_assets": [
                {
                    "tc_id": "TC-V2-001",
                    "test_function": "test_tc_v2_001",
                    "requirement_ids": ["REQ-FAN-001"],
                    "covered_behaviors": ["승인된 풍량 변경 검증"],
                    "source": "APPROVED",
                    "test_case_file": "test_cases/TC-V2-001.json",
                    "test_case_sha256": "b" * 64,
                    "automation_file": "automation/test_tc_v2_001.py",
                    "automation_sha256": approved_hash,
                }
            ],
        },
    )
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest.update(
        {
            "approved_regression_catalog_sha256": _sha256_file(catalog_file),
            "approved_regression_assets": [
                {
                    "tc_id": "TC-V2-001",
                    "automation_file": "automation/test_tc_v2_001.py",
                    "automation_sha256": approved_hash,
                }
            ],
            "validation_execution_sha256": _sha256_file(execution_file),
        }
    )
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.PASS
    assert checkpoint.checks[1].status == pipeline.CheckStatus.PASS

def test_agent4_rejects_approved_regression_without_catalog_hash(tmp_path: Path) -> None:
    run_dir, _ = _write_agent4_inputs(tmp_path)
    execution_file = run_dir / "validation_execution.json"
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        execution_file.read_text(encoding="utf-8")
    )
    approved_hash = "a" * 64
    approved_result = bundle.regression_results[0].model_copy(
        update={
            "test_id": "TC-V2-001",
            "test_file": "automation/test_tc_v2_001.py",
            "test_sha256": approved_hash,
        }
    )
    bundle = bundle.model_copy(
        update={
            "selected_regression_ids": ["TC-V2-001"],
            "regression_results": [approved_result],
        }
    )
    manifest = json.loads(
        (run_dir / "validation_manifest.json").read_text(encoding="utf-8")
    )
    manifest["approved_regression_assets"] = [
        {
            "tc_id": "TC-V2-001",
            "automation_file": "automation/test_tc_v2_001.py",
            "automation_sha256": approved_hash,
        }
    ]

    assert (
        pipeline._agent4_regression_source_chain_matches(run_dir, bundle, manifest)
        is False
    )

def test_agent4_send_delivers_only_after_cp4_pass(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    monkeypatch.setattr(
        pipeline_reporting,
        "_send_slack_report",
        lambda _payload: pipeline.ExternalDestinationResult(
            destination="SLACK",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=1,
            detail="sent",
        ),
    )
    monkeypatch.setattr(
        pipeline_reporting,
        "_upsert_notion_reports",
        lambda records: pipeline.ExternalDestinationResult(
            destination="NOTION",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=len(records),
            detail="upserted",
        ),
    )

    assert pipeline.run_agent4(
        SimpleNamespace(
            run_id=run_id,
            runs_root=str(tmp_path / "runs"),
            send=True,
        )
    ) == 0

    delivery = pipeline.ExternalReportingResult.model_validate_json(
        (run_dir / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert delivery.mode == "SEND"
    assert delivery.slack.status == pipeline.ExternalDeliveryStatus.SENT
    assert delivery.notion.status == pipeline.ExternalDeliveryStatus.SENT
    assert delivery.notion.item_count == 3

def test_external_reporting_send_after_preview_preserves_first_evidence(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    first_report = run_dir / "external_reporting.json"
    first_bytes = first_report.read_bytes()
    first_hash = _sha256_file(first_report)
    monkeypatch.setattr(
        pipeline_reporting,
        "_send_slack_report",
        lambda _payload: pipeline.ExternalDestinationResult(
            destination="SLACK",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=1,
            detail="sent",
        ),
    )
    monkeypatch.setattr(
        pipeline_reporting,
        "_upsert_notion_reports",
        lambda records: pipeline.ExternalDestinationResult(
            destination="NOTION",
            status=pipeline.ExternalDeliveryStatus.SENT,
            item_count=len(records),
            detail="upserted",
        ),
    )

    assert pipeline.run_external_reporting(
        SimpleNamespace(
            run_id=run_id,
            runs_root=str(tmp_path / "runs"),
            send=True,
        )
    ) == 0

    assert first_report.read_bytes() == first_bytes
    attempts = list((run_dir / "external_reporting_attempts").iterdir())
    assert len(attempts) == 1
    sent = pipeline.ExternalReportingResult.model_validate_json(
        (attempts[0] / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert sent.mode == "SEND"
    assert sent.previous_reporting_sha256 == first_hash
    assert sent.slack.status == pipeline.ExternalDeliveryStatus.SENT
    assert sent.notion.status == pipeline.ExternalDeliveryStatus.SENT

def test_agent4_verifies_multiple_agent3_source_artifacts(tmp_path: Path) -> None:
    run_dir = tmp_path / "RUN-20260817-025000-ABCDEF"
    run_dir.mkdir()
    candidate_results = []
    source_artifacts = []
    for tc_id in ("TC-CAND-003", "TC-CAND-004"):
        artifact_dir = run_dir / "agent3_candidates" / tc_id
        candidate_dir = artifact_dir / "candidates"
        candidate_dir.mkdir(parents=True)
        candidate_file = candidate_dir / f"test_{tc_id.lower().replace('-', '_')}.py"
        candidate_file.write_text("def test_candidate():\n    pass\n", encoding="utf-8")
        agent3_manifest = artifact_dir / "agent3_manifest.json"
        agent3_trial = artifact_dir / "agent3_trial.json"
        _write_json(agent3_manifest, {"run_id": run_dir.name, "tc_id": tc_id})
        _write_json(agent3_trial, {"outcome": "PASS"})
        result = _neutral_execution_result(
            tc_id, pipeline.ExecutionSource.NEW_AUTOMATION_CANDIDATE
        ).model_copy(
            update={
                "test_file": candidate_file.relative_to(run_dir).as_posix(),
                "test_sha256": _sha256_file(candidate_file),
            }
        )
        candidate_results.append(result)
        source_artifacts.append(
            {
                "tc_id": tc_id,
                "agent3_manifest_file": agent3_manifest.relative_to(run_dir).as_posix(),
                "agent3_manifest_sha256": _sha256_file(agent3_manifest),
                "agent3_trial_file": agent3_trial.relative_to(run_dir).as_posix(),
                "agent3_trial_sha256": _sha256_file(agent3_trial),
                "candidate_reused": True,
                "validation_candidate_sha256": result.test_sha256,
                "validation_candidate_trial_file": None,
                "validation_candidate_trial_sha256": None,
            }
        )
    summary_file = run_dir / "agent3_run_summary.json"
    _write_json(summary_file, {"run_id": run_dir.name, "status": "PASS"})
    precheck = _neutral_execution_result(
        "TC-ENV-000", pipeline.ExecutionSource.ENVIRONMENT_PRECHECK
    )
    bundle = pipeline.ValidationExecutionBundle(
        run_id=run_dir.name,
        status=pipeline.ValidationStageStatus.COMPLETED,
        candidate_results=candidate_results,
        environment_precheck=precheck,
        selected_regression_ids=[],
        regression_results=[],
        created_at="2026-08-17T00:00:00+00:00",
    )
    manifest = {
        "source_agent3_artifacts": source_artifacts,
        "source_agent3_run_summary_sha256": _sha256_file(summary_file),
    }

    assert pipeline._agent4_new_source_chain_matches(run_dir, bundle, manifest) is True
    valid_hash = source_artifacts[0]["agent3_trial_sha256"]
    source_artifacts[0]["agent3_trial_sha256"] = "f" * 64
    assert pipeline._agent4_new_source_chain_matches(run_dir, bundle, manifest) is False
    source_artifacts[0]["agent3_trial_sha256"] = valid_hash
    summary_file.unlink()
    manifest["source_agent3_run_summary_sha256"] = None
    assert pipeline._agent4_new_source_chain_matches(run_dir, bundle, manifest) is False

    # A single nested candidate is still a summary-based run, not a CLI root run.
    single_bundle = bundle.model_copy(update={"candidate_results": candidate_results[:1]})
    manifest["source_agent3_artifacts"] = source_artifacts[:1]
    assert pipeline._agent4_new_source_chain_matches(run_dir, single_bundle, manifest) is False
    item = source_artifacts[0]
    for name in ("agent3_manifest", "agent3_trial"):
        relative = item[f"{name}_file"]
        (run_dir / f"{name}.json").write_bytes((run_dir / relative).read_bytes())
        item[f"{name}_file"] = f"{name}.json"
        manifest[f"source_{name}_sha256"] = item[f"{name}_sha256"]
    assert pipeline._agent4_new_source_chain_matches(run_dir, single_bundle, manifest) is True
    (run_dir / "agent3_trial.json").write_text("{}", encoding="utf-8")
    assert pipeline._agent4_new_source_chain_matches(run_dir, single_bundle, manifest) is False

def test_agent4_reports_automation_exclusion_without_blocking_executed_results(
    tmp_path: Path,
) -> None:
    exclusion = pipeline.AutomationExclusion(
        tc_id="TC-CAND-009",
        candidate_status=pipeline.AutomationCandidateStatus.AUTOMATION_SUPPORT_EXTENSION_REQUIRED,
        reason="현재 UI 관찰 방법으로 실행할 수 없습니다.",
    )
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, automation_exclusions=[exclusion]
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HUMAN_REVIEW
    assert report.findings == []
    assert report.automation_exclusions == [exclusion]
    assert "미확인 항목 있음" in (run_dir / "사람_최종_검토.md").read_text(encoding="utf-8")
    raw_report = json.loads((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert "자동화_제외_TC" in raw_report

def test_agent4_reports_all_excluded_candidates_for_human_review(
    tmp_path: Path,
) -> None:
    exclusion = pipeline.AutomationExclusion(
        tc_id="TC-CAND-009",
        candidate_status=pipeline.AutomationCandidateStatus.NOT_AUTOMATABLE,
        reason="현재 화면에서 필요한 관찰값을 확인할 수 없습니다.",
    )
    run_dir, run_id = _write_agent4_inputs(
        tmp_path,
        include_candidate=False,
        automation_exclusions=[exclusion],
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )

    assert report.recommendation == pipeline.FinalRecommendation.HUMAN_REVIEW
    assert report.automation_exclusions == [exclusion]
    assert report.total_results == 2

def test_agent4_passes_existing_only_execution_without_new_candidate(
    tmp_path: Path,
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path, include_candidate=False)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )

    assert report.recommendation == pipeline.FinalRecommendation.PASS
    assert report.automation_exclusions == []
    assert report.total_results == 2

def test_agent4_marks_assertion_failure_as_product_mismatch_candidate(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, candidate_status=pipeline.NeutralExecutionStatus.ASSERTION_FAILED
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HUMAN_REVIEW
    assert report.findings[0].category == pipeline.Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE
    assert "확정" in report.findings[0].rationale
    review_file = run_dir / "사람_최종_검토.md"
    review_manifest = json.loads(
        (run_dir / "사람_최종_검토_manifest.json").read_text(encoding="utf-8")
    )
    review_text = review_file.read_text(encoding="utf-8")
    assert "# 사람 최종 검토서" in review_text
    assert "제품 동작 불일치 후보" in review_text
    assert "UI remains at 18 degrees." in review_text
    assert "개별 판정이 확인되지 않습니다" in review_text
    assert "불일치가 기록되지 않아 해당 자동 검증은 통과" not in review_text
    assert "요구사항이 맞으며 제품 구현 수정이 필요함" in review_text
    assert "검토자: ____________________" in review_text
    assert "사람이 작성한 문서는 `--refresh`가 덮어쓰지 않습니다" in review_text
    assert review_manifest["document_sha256"] == _sha256_file(review_file)
    assert pipeline.run_human_review_document(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

@pytest.mark.parametrize("combined", [False, True])
def test_agent4_reports_restore_failure_without_hiding_product_observation(tmp_path: Path, combined: bool) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path,
        candidate_status=(pipeline.NeutralExecutionStatus.ASSERTION_FAILED if combined else pipeline.NeutralExecutionStatus.EXECUTION_ERROR),
        candidate_stdout="E   AssertionError: PRODUCT_MISMATCH: ER-005: observed=17 expected=18\n" if combined else "",
        candidate_stderr="RESTORE_MISMATCH: internal state was not restored\n",
    )
    assert pipeline.run_agent4(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))) == 0
    report = pipeline.FinalReport.model_validate_json((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert report.checkpoint_status == pipeline.CheckStatus.PASS
    assert report.recommendation == pipeline.FinalRecommendation.HOLD
    assert report.total_results == 3
    assert len(report.findings) == 1  # 같은 TC의 두 관찰을 두 번 실행한 것으로 집계하지 않습니다.
    assert report.findings[0].category == pipeline.Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE
    assert "복원 실패" in report.findings[0].rationale
    review = (run_dir / "사람_최종_검토.md").read_text(encoding="utf-8")
    assert "복원 실패" in review and "internal state was not restored" in review
    if combined:
        assert "제품 불일치 관찰" in review and "observed=17 expected=18" in review
        assert "제품 기대값 불일치 관찰도 함께 보존" in report.findings[0].rationale
    notion = (run_dir / "notion_payload.json").read_text(encoding="utf-8")
    assert "AUTOMATION_EXECUTION_ISSUE" in notion


def test_agent4_ignores_restore_marker_in_source_code_and_unverified_logs(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, candidate_status=pipeline.NeutralExecutionStatus.ASSERTION_FAILED,
        candidate_stdout="    restore_message = 'RESTORE_MISMATCH: ' + details\nE   AssertionError: PRODUCT_MISMATCH: ER-005: wrong value\n",
    )
    bundle = pipeline.ValidationExecutionBundle.model_validate_json((run_dir / "validation_execution.json").read_text(encoding="utf-8"))
    result = bundle.candidate_results[0]
    assert "RESTORE_MISMATCH" not in pipeline._execution_failure_observations(run_dir, result)
    (run_dir / result.stderr_file).write_text("RESTORE_MISMATCH: forged\n", encoding="utf-8")
    assert "RESTORE_MISMATCH" not in pipeline._execution_failure_observations(run_dir, result)
    assert pipeline.run_agent4(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))) == 2
    report = pipeline.FinalReport.model_validate_json((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert report.checkpoint_status == pipeline.CheckStatus.FAIL
    assert report.recommendation == pipeline.FinalRecommendation.HOLD


def test_existing_only_procedure_notes_reach_final_human_review(tmp_path: Path, monkeypatch) -> None:
    # This fixture exercises note propagation, not the Agent 1/2 handoff.
    monkeypatch.setattr(pipeline_reporting, "_load_verified_agent2_run", lambda *_: None)
    run_dir, run_id = _write_agent4_inputs(tmp_path, include_candidate=False)
    request = cp1_request().model_copy(update={"acceptance_notes": [
        "첫 실행 기본 상태인 LOW 풍량을 확인한 뒤 시험을 시작한다.",
        "시험 뒤 대상 장비를 LOW 풍량으로 복원하고 적용한다.",
    ]})
    _write_json(run_dir / "request.json", request.model_dump(mode="json"))
    design = pipeline.Agent2TestDesign.model_validate_json((run_dir / "agent2_test_design.json").read_text(encoding="utf-8"))
    design.related_existing_tests = [pipeline.ExistingTestSelection(
        tc_id="TC-TEMP-001", source_condition_ids=["COND-001"], selection_reason="기존 TC 재사용",
    )]
    _write_json(run_dir / "agent2_test_design.json", design.model_dump(mode="json", by_alias=True))
    _write_json(run_dir / "agent2_manifest.json", {
        "existing_procedure_review_contract": "1.0", "request_sha256": _sha256_file(run_dir / "request.json"),
    })
    notes = pipeline._final_review_notes_for_validation(run_dir)
    assert len(notes) == 2
    execution_file = run_dir / "validation_execution.json"
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(execution_file.read_text(encoding="utf-8"))
    bundle.final_review_notes = notes
    _write_json(execution_file, bundle.model_dump(mode="json", by_alias=True))
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["validation_execution_sha256"] = _sha256_file(execution_file)
    _write_json(manifest_file, manifest)
    assert pipeline.run_agent4(SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))) == 0
    report = pipeline.FinalReport.model_validate_json((run_dir / "final_report.json").read_text(encoding="utf-8"))
    assert report.final_review_notes == notes
    review = (run_dir / "사람_최종_검토.md").read_text(encoding="utf-8")
    assert all(note in review for note in request.acceptance_notes)
    assert "자동 확정하지 않았습니다" in review
    _write_json(run_dir / "request.json", cp1_request().model_dump(mode="json"))
    with pytest.raises(ValueError, match="변경"):
        pipeline._final_review_notes_for_validation(run_dir)


def test_agent4_holds_candidate_automation_execution_issue(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, candidate_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0
    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HOLD
    assert report.findings[0].category == (
        pipeline.Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE
    )

def test_agent4_carries_non_blocking_review_notes_to_final_report(tmp_path: Path) -> None:
    proposal = pipeline.SrsRevisionProposal(
        proposal_id="SRS-REV-001",
        requirement_id="REQ-TEMP-001",
        source_condition_ids=["COND-001"],
        current_acceptance_criteria="기존 기준",
        proposed_acceptance_criteria="변경 기준",
        reason="승인된 변경을 기준 문서에 반영한다.",
    )
    run_dir, run_id = _write_agent4_inputs(
        tmp_path,
        final_review_notes=["CP1: 변경 전 값의 SRS 근거를 최종 확인한다."],
        srs_revision_proposals=[proposal],
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )

    assert report.recommendation == pipeline.FinalRecommendation.PASS
    assert report.final_review_notes == [
        "CP1: 변경 전 값의 SRS 근거를 최종 확인한다."
    ]
    assert report.srs_revision_proposals == [proposal]
    review_text = (run_dir / "사람_최종_검토.md").read_text(encoding="utf-8")
    assert "## 4. 기준 SRS 개정 승인" in review_text
    assert "현재 인수 기준: 기존 기준" in review_text
    assert "제안 인수 기준: 변경 기준" in review_text

def test_agent4_holds_when_environment_precheck_blocks_regressions(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(
        tmp_path, precheck_status=pipeline.NeutralExecutionStatus.EXECUTION_ERROR
    )

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 0

    report = pipeline.FinalReport.model_validate_json(
        (run_dir / "final_report.json").read_text(encoding="utf-8")
    )
    assert report.recommendation == pipeline.FinalRecommendation.HOLD
    assert {finding.category for finding in report.findings} == {
        pipeline.Agent4FindingCategory.ENVIRONMENT_ISSUE,
        pipeline.Agent4FindingCategory.INSUFFICIENT_EVIDENCE,
    }

def test_agent4_holds_when_product_mismatch_and_automation_issue_coexist() -> None:
    findings = [
        pipeline.Agent4Finding(
            finding_id="FIND-001",
            category=pipeline.Agent4FindingCategory.PRODUCT_MISMATCH_CANDIDATE,
            rationale="product mismatch",
        ),
        pipeline.Agent4Finding(
            finding_id="FIND-002",
            category=pipeline.Agent4FindingCategory.AUTOMATION_EXECUTION_ISSUE,
            rationale="automation issue",
        ),
    ]

    assert pipeline._agent4_recommendation(
        findings, pipeline.CheckStatus.PASS
    ) == pipeline.FinalRecommendation.HOLD

def test_agent4_rejects_validation_execution_hash_mismatch(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["validation_execution_sha256"] = "0" * 64
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    delivery = pipeline.ExternalReportingResult.model_validate_json(
        (run_dir / "external_reporting.json").read_text(encoding="utf-8")
    )
    assert checkpoint.status == pipeline.CheckStatus.FAIL
    assert delivery.allowed is False
    assert delivery.slack.status == pipeline.ExternalDeliveryStatus.BLOCKED
    assert delivery.notion.status == pipeline.ExternalDeliveryStatus.BLOCKED
    assert (run_dir / "agent4_error.json").exists() is False

def test_agent4_rejects_broken_manifest_or_candidate_chain(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["source_agent3_manifest_sha256"] = "0" * 64
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[1].rule_id == "CP4-002"
    assert checkpoint.checks[1].status == pipeline.CheckStatus.FAIL

    candidate_root = tmp_path / "candidate-tamper"
    candidate_run_dir, candidate_run_id = _write_agent4_inputs(candidate_root)
    candidate_file = candidate_run_dir / "candidates" / "test_controller.py"
    candidate_file.write_text("changed after validation\n", encoding="utf-8")

    assert pipeline.run_agent4(
        SimpleNamespace(
            run_id=candidate_run_id,
            runs_root=str(candidate_root / "runs"),
        )
    ) == 2
    candidate_checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (candidate_run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert candidate_checkpoint.checks[1].rule_id == "CP4-002"
    assert candidate_checkpoint.checks[1].status == pipeline.CheckStatus.FAIL

def test_agent4_rejects_mismatched_execution_source_contract(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    execution_file = run_dir / "validation_execution.json"
    execution = json.loads(execution_file.read_text(encoding="utf-8"))
    execution["environment_precheck"]["source"] = "EXISTING_REGRESSION"
    _write_json(execution_file, execution)
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["validation_execution_sha256"] = _sha256_file(execution_file)
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2

    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[3].rule_id == "CP4-004"
    assert checkpoint.checks[3].status == pipeline.CheckStatus.FAIL

def test_agent4_rejects_missing_or_changed_evidence_file(tmp_path: Path) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    (run_dir / "evidence" / "stdout.txt").unlink()

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2

    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[5].rule_id == "CP4-006"
    assert checkpoint.checks[5].status == pipeline.CheckStatus.FAIL

def test_agent4_rejects_passed_result_without_complete_evidence(
    tmp_path: Path,
) -> None:
    run_dir, run_id = _write_agent4_inputs(tmp_path)
    execution_file = run_dir / "validation_execution.json"
    bundle = pipeline.ValidationExecutionBundle.model_validate_json(
        execution_file.read_text(encoding="utf-8")
    )
    candidate = bundle.candidate_result.model_copy(
        update={
            "evidence_files": [
                bundle.candidate_result.stdout_file,
                bundle.candidate_result.stderr_file,
            ],
            "evidence_sha256": {
                name: bundle.candidate_result.evidence_sha256[name]
                for name in (
                    bundle.candidate_result.stdout_file,
                    bundle.candidate_result.stderr_file,
                )
            },
            "evidence_complete": False,
        }
    )
    bundle = bundle.model_copy(update={"candidate_result": candidate})
    _write_json(execution_file, bundle.model_dump(mode="json"))
    manifest_file = run_dir / "validation_manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    manifest["validation_execution_sha256"] = _sha256_file(execution_file)
    _write_json(manifest_file, manifest)

    assert pipeline.run_agent4(
        SimpleNamespace(run_id=run_id, runs_root=str(tmp_path / "runs"))
    ) == 2
    checkpoint = pipeline.Checkpoint4Result.model_validate_json(
        (run_dir / "checkpoint4.json").read_text(encoding="utf-8")
    )
    assert checkpoint.checks[5].rule_id == "CP4-006"
    assert checkpoint.checks[5].status == pipeline.CheckStatus.FAIL

def test_agent4_parser_exposes_rules_only_report_command() -> None:
    args = pipeline.build_parser().parse_args(
        ["agent4", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )

    assert args.handler is pipeline.run_agent4
    assert args.send is False

    reporting = pipeline.build_parser().parse_args(
        ["report", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )
    assert reporting.handler is pipeline.run_external_reporting
    assert reporting.send is False

    human_review = pipeline.build_parser().parse_args(
        ["human-review", "--run-id", "RUN-20260817-030000-ABCDEF"]
    )
    assert human_review.handler is pipeline.run_human_review_document
    assert human_review.refresh is False
