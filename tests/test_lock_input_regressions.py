"""Local reader/encoding checks, not evidence of live model judgment quality."""
from pipeline_test_support import *
import copy
import re
import qa_pipeline_agent3 as a3
import qa_pipeline_grounding as grounding
from test_grounding import focused_agent2_payload
from test_agent3 import mapped_controller_observation


def expand_tcs(payload):
    expanded = copy.deepcopy(payload)
    for item in expanded['items']:
        body = item['content']
        if item['kind'] == 'TC_DESIGN' and set(body) == {'tc_ref'}:
            item['content'] = copy.deepcopy(expanded['context'][body['tc_ref']])
        if item['kind'] == 'CONDITION_COVERAGE' and 'candidate_test_refs' in body:
            body['candidate_tests'] = [copy.deepcopy(expanded['context'][ref])
                                       for ref in body.pop('candidate_test_refs')]
    return expanded


@pytest.mark.parametrize('class_locked,icon_locked', [(False, False), (True, True), (False, True), (True, False)])
def test_card_lock_reader_uses_consistent_dom_not_internal_value(class_locked, icon_locked, monkeypatch, tmp_path):
    monkeypatch.setenv('QA_TARGET_URL', 'about:blank')
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path))
    case, plan = controller_lifecycle_fixture('locked', True, False)
    code = a3.compile_automation_candidate('LOCAL', case, plan)
    ui = {'card_classes': ['state-stop', 'mode-heat'] + (['locked'] if class_locked else []),
          'card_values': ['난방', '중풍', '27°C'], 'card_locked': icon_locked}
    class Page:
        def evaluate(self, *args):
            return {'state': {'locked': not icon_locked}, 'ui': ui}
    expected = icon_locked if class_locked == icon_locked else None
    namespace = {}
    exec(compile(code, 'new_candidate', 'exec'), namespace)
    assert namespace['_controller_ui_fields'](Page(), 1)['locked'] is expected
    if expected is None:
        assert not namespace['_qa_values_equal'](expected, False)
        assert not namespace['_qa_values_equal'](expected, True)


@pytest.mark.parametrize('initial,target', [(False, True), (True, False)])
def test_new_lock_candidate_executes_and_restores(initial, target, mapped_controller_observation,
        tmp_path, monkeypatch, capsys):
    case, _ = mapped_tc_fixture('locked', initial, target)
    plan = a3.ControllerMapAgent3().plan(case, mapped_controller_observation, {}).plan
    monkeypatch.setenv('QA_TARGET_URL', (REPO_ROOT / 'product_baseline/virtual-controller.html').as_uri())
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path / 'evidence'))
    namespace = {}
    exec(compile(a3.compile_automation_candidate('LOCAL-LOCK', case, plan), 'lock', 'exec'), namespace)
    namespace['test_tc_cand_090']()
    output = capsys.readouterr().out
    assert 'RESTORE_STATUS: RESTORED' in output
    assert 'PRODUCT_MISMATCH' not in output


def test_compact_input_is_lossless_and_preserves_review_items_sources_and_verdicts():
    new = focused_agent2_payload()
    expanded = expand_tcs(new)
    assert [i['item_id'] for i in expanded['items']] == [i['item_id'] for i in new['items']]
    assert all('tc_ref' not in i['content'] for i in expanded['items'] if i['kind'] == 'TC_DESIGN')
    assert new['source_documents'][-1]['source_id'] == 'REVIEW_INPUT_GUIDE'
    assert any('tc_ref' in i['content'] for i in new['items'] if i['kind'] == 'TC_DESIGN')
    for verdict, status in [('SUPPORTED','PASS'),('UNSUPPORTED','FAIL'),('UNCERTAIN','REVIEW')]:
        record = fake_grounding_record(new)
        record['review']['items'][0]['verdict'] = verdict
        assert grounding.check_review_record(new, record).status.value == status


@pytest.mark.parametrize('value', [True, False, 1, 1.0, '1', None, 0, ''])
def test_compaction_never_coerces_types_or_repairs_different_copies(value):
    payload = {'context': {'TC/0': {'value': True}}, 'items': [
        {'kind': 'TC_DESIGN', 'content': {'value': value}},
        {'kind': 'CONDITION_COVERAGE', 'content': {'candidate_tests': [{'value': value}]}}]}
    original = copy.deepcopy(payload)
    compact = grounding.compact_review_tcs(payload)
    assert json.dumps(expand_tcs(compact), sort_keys=True) == json.dumps(payload, sort_keys=True)
    assert payload == original
    assert ('tc_ref' in compact['items'][0]['content']) is (value is True)


def test_compaction_ambiguous_copies_empty_coverage_and_broken_body_stay_explicit():
    payload = {'context': {'TC/0': {'value': False}, 'TC/1': {'value': False}}, 'items': [
        {'kind': 'TC_DESIGN', 'content': {'value': False}},
        {'kind': 'CONDITION_COVERAGE', 'content': {'candidate_tests': []}},
        {'kind': 'CONDITION_COVERAGE', 'content': {'candidate_tests': [{'value': True}]}}]}
    assert grounding.compact_review_tcs(payload) == payload


def test_new_review_transport_sends_exact_compact_payload_and_guidance():
    payload = focused_agent2_payload()
    sent = []
    def parse(**kwargs):
        sent.append(kwargs)
        return SimpleNamespace(output_parsed=None)
    with pytest.raises(ValueError, match='구조화 응답'):
        grounding.OpenAIGroundingReviewer(model='fake', client=SimpleNamespace(
            responses=SimpleNamespace(parse=parse))).review(payload)
    # Exact content; only the transport order is static-first-1.0 (2026-10-17).
    assert json.loads(sent[0]['input'][1]['content']) == grounding.static_first_wire(payload)
    assert sorted(map(json.dumps, grounding.static_first_wire(payload)['source_documents'])) == sorted(
        map(json.dumps, payload['source_documents']))
    assert grounding.COMPACT_REVIEW_GUIDANCE in sent[0]['input'][0]['content']
    assert sent[0]['store'] is False


def test_interface_versions_preserve_old_facts_and_pin_new_lock_semantics():
    case, plan = controller_lifecycle_fixture('locked', True, False)
    obs = generic_control_guard_fixture()[2]
    old = a3.execution_interface_facts(plan, obs, contract='1.1')
    new = a3.execution_interface_facts(plan, obs, contract='1.2')
    assert old['readers'] == new['readers']
    assert '서로 다르면 null' in new['ui_decoders'][plan.assertions[0].selector]['locked']
    assert '서로 다르면 null' not in old['ui_decoders'][plan.assertions[0].selector]['locked']


def test_lock_conflicting_display_in_real_dom(monkeypatch, tmp_path):
    from playwright.sync_api import sync_playwright
    monkeypatch.setenv('QA_TARGET_URL', 'about:blank')
    monkeypatch.setenv('QA_EVIDENCE_DIR', str(tmp_path))
    case, plan = controller_lifecycle_fixture('locked', True, False)
    namespace = {}
    exec(compile(a3.compile_automation_candidate('LOCAL-DOM', case, plan), 'lock_dom', 'exec'), namespace)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto((REPO_ROOT / 'product_baseline/virtual-controller.html').as_uri())
        page.wait_for_selector('#device-card-1')
        original = page.evaluate('() => JSON.stringify(window.__vccs.devices)')
        for class_locked, icon_locked in [(False, False), (True, True), (False, True), (True, False)]:
            page.evaluate('''([css, icon]) => {
                const card = document.querySelector('#device-card-1');
                card.classList.toggle('locked', css);
                const marker = card.querySelector('.card-lock-indicator');
                marker.style.visibility = icon ? 'visible' : 'hidden';
                marker.style.display = 'block';
            }''', [class_locked, icon_locked])
            value = namespace['_controller_ui_fields'](page, 1)['locked']
            expected = icon_locked if class_locked == icon_locked else None
            assert value is expected
            if value is None:
                assert not namespace['_qa_values_equal']({'locked': value}, {'locked': False})
                assert not namespace['_qa_values_equal']({'locked': value}, {'locked': True})
        assert page.evaluate('() => JSON.stringify(window.__vccs.devices)') == original
        browser.close()
