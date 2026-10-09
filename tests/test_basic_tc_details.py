"""Native baseline checks remain native; detailed metadata is immutable per Run."""
import copy
import hashlib
import json
from pathlib import Path
import pytest
from pipeline_test_support import pipeline as p

ROOT = Path(__file__).resolve().parents[1]

def test_all_basic_details_match_unchanged_source_and_reach_catalog_and_report(tmp_path):
    detail = p._baseline_detail_snapshot()
    assert detail['source_sha256'] == p._sha256_file(ROOT/'product_baseline/tests/test_controller.py')
    snapshot = {'approved_assets': [], 'baseline_details': detail}
    cases = p._baseline_cases_from_snapshot(snapshot)
    assert len(cases) == 6
    catalog = p._catalog_from_snapshot(snapshot)
    for spec in catalog:
        case = cases[spec.tc_id]
        assert json.loads(spec.reuse_context_json) == case
        assert case['steps'] and case['expected_results'] and case['preconditions']
        assert case['restore_steps']
        assert case['restoration_status'] == 'RUNTIME_VERIFICATION_REQUIRED'
        assert case['test_function'] == spec.test_function
    p._write_json(tmp_path/'approved_regression_catalog.json', snapshot)
    p._write_json(tmp_path/'agent2_test_design.json', {'related_existing_tests': [{'tc_id':s.tc_id} for s in catalog]})
    rows = p.build_run_test_rows(tmp_path)
    assert len(rows) == 6
    assert all(r['steps'] and r['expected_results'] and r['status']=='NOT_EXECUTED' for r in rows)
    assert all(r['restoration_note'] and r['restore_steps'] for r in rows)

@pytest.mark.parametrize('fault', ['text', 'duplicate', 'missing', 'id'])
def test_basic_snapshot_rejects_partial_or_changed_details(fault):
    snap = {'baseline_details': p._baseline_detail_snapshot()}
    rows = snap['baseline_details']['cases']
    if fault == 'text': rows[0]['test_case_json'] += ' '
    elif fault == 'duplicate': rows[-1] = copy.deepcopy(rows[0])
    elif fault == 'missing': rows.pop()
    else: rows[0]['tc_id'] = 'TC-UNKNOWN-001'
    with pytest.raises(ValueError): p._baseline_cases_from_snapshot(snap)

def test_old_snapshot_does_not_inherit_current_details(tmp_path):
    assert p._baseline_cases_from_snapshot({'approved_assets': []}) == {}
    assert all(s.reuse_context_json is None for s in p._catalog_from_snapshot({'approved_assets': []}))
    assert all(s.recovery_contract is None for s in p._catalog_from_snapshot({'approved_assets': []}))
    p._write_json(tmp_path/'agent2_test_design.json', {'related_existing_tests':[{'tc_id':'TC-TEMP-001'}]})
    assert p.build_run_test_rows(tmp_path)[0]['steps'] == []

def test_scope_does_not_turn_selection_into_application_or_drop_special_checks():
    cases = p._baseline_cases_from_snapshot({'baseline_details': p._baseline_detail_snapshot()})
    for key in ('TC-MODE-002', 'TC-MODE-003', 'TC-TEMP-001'):
        assert '적용 버튼은 누르지 않는다' in ' '.join(cases[key]['steps'])
    assert '1~16번' in ' '.join(cases['TC-LOCK-001']['steps'])
    assert '물리 전원' in ' '.join(cases['TC-LOCK-001']['steps'])
    assert '4번' in ' '.join(cases['TC-ERR-001']['steps'])
    assert '현장 조작 후 내부값을 별도로' in json.dumps(cases['TC-LOCK-001'], ensure_ascii=False)

def test_changed_native_code_cannot_silently_keep_old_description(monkeypatch):
    monkeypatch.setitem(p._baseline_detail_snapshot.__globals__, '_sha256_file', lambda _: '0'*64)
    with pytest.raises(ValueError, match='기본 시험 코드가 바뀌었습니다'):
        p._baseline_detail_snapshot()
