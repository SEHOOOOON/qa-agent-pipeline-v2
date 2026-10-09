"""Frozen approved revisions and current compilation share the TC/plan contract."""
import ast
import json
from pathlib import Path
import shutil
import pytest

from pipeline_test_support import pipeline
from qa_pipeline_agent3 import resolve_controller_bindings, assemble_tc_bindings, tc_plan_handoff_errors

ROOT = Path(__file__).resolve().parents[1]


def test_current_approved_refresh_contract_and_original_preservation():
    assets = ROOT / 'approved_assets'
    catalog, snapshot = pipeline.load_approved_regression_catalog(assets)
    registry = json.loads((assets / 'registry.json').read_text(encoding='utf-8'))
    refreshed = [a for a in registry['assets'] if a.get('maintenance_revision')]
    assert refreshed, 'Refresh assets must be registered, not only test fixtures'
    for asset in refreshed:
        record = json.loads((assets / asset['test_case_file']).read_text(encoding='utf-8'))
        maintenance = record['maintenance_revision']
        original = json.loads((assets / maintenance['previous_test_case_file']).read_text(encoding='utf-8'))
        assert pipeline._sha256_file(assets / maintenance['previous_test_case_file']) == maintenance['previous_test_case_sha256']
        assert pipeline._sha256_file(assets / maintenance['previous_automation_file']) == maintenance['previous_automation_sha256']
        tc = pipeline.LiveProductTestCaseCandidate.model_validate(record['test_case'])
        assert tc.execution_spec.binding_contract == 'controller-map-1.0'
        assert not pipeline._structured_restoration_errors(tc)
        assert tc.requirement_ids == original['test_case']['requirement_ids']
        assert len(tc.expected_results) == len(original['test_case']['expected_results'])
        for result, before in zip(tc.expected_results, original['test_case']['expected_results']):
            for key in ('result_id', 'statement', 'observation_layer', 'source_condition_ids'):
                assert result.model_dump(mode='json')[key] == before[key]
        plan = assemble_tc_bindings(tc, resolve_controller_bindings(tc))
        assert not tc_plan_handoff_errors(tc, plan)
        revision_dir = (assets / asset['test_case_file']).parent
        verification = json.loads((revision_dir / 'verification.json').read_text(encoding='utf-8'))
        assert verification['automation_sha256'] == asset['automation_sha256']
        assert verification['testcase_sha256'] == asset['test_case_sha256']
        assert pipeline._sha256_file(revision_dir / 'plan.json') == verification['plan_sha256']
        saved_plan = pipeline.Agent3AutomationPlan.model_validate(
            json.loads((revision_dir / 'plan.json').read_text(encoding='utf-8')))
        assert not tc_plan_handoff_errors(tc, saved_plan)
        saved_code = (assets / asset['automation_file']).read_text(encoding='utf-8')
        # Registry hashes above pin approved files. Later compiler improvements
        # must not require silently rebuilding or replacing those frozen files.
        code = pipeline.compile_automation_candidate(maintenance['compilation_id'], tc, plan,
            explicit_expectations_only=True, typed_values=True)
        for candidate in (saved_code, code):
            ast.parse(candidate)
            assert 'RESTORE_STATUS:' in candidate and 'QA_ASSERTION_OBSERVED:' in candidate
        snap = next(s for s in snapshot['approved_assets'] if s['tc_id'] == asset['official_tc_id'])
        assert json.loads(snap['test_case_json'])['test_case'] == record['test_case']
        assert any(s.tc_id == asset['official_tc_id'] for s in catalog)


@pytest.mark.parametrize('file_key', ['test_case_file', 'automation_file'])
def test_frozen_approved_revision_rejects_byte_changes(tmp_path, file_key):
    assets = tmp_path / 'assets'
    shutil.copytree(ROOT / 'approved_assets', assets)
    registry = json.loads((assets / 'registry.json').read_text(encoding='utf-8'))
    asset = next(a for a in registry['assets'] if a.get('maintenance_revision'))
    changed = assets / asset[file_key]
    changed.write_bytes(changed.read_bytes() + b'\n')
    with pytest.raises(ValueError, match='SHA-256'):
        pipeline.load_approved_regression_catalog(assets)
