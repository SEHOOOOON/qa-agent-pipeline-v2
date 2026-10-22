"""Program-owned SRS copies must not hide changes to proposed requirements."""
from pipeline_test_support import *
from qa_pipeline_contracts import Agent2TransportDesign, SrsRevisionDraft, materialize_srs_revision_sources

def draft_fixture():
    data = agent2_design().model_dump(mode='json', by_alias=True)
    data['test_cases'] = []
    data['SRS_개정_제안'] = [dict(proposal_id='SRS-REV-001', requirement_id='REQ-TEMP-001',
        source_condition_ids=['COND-001'], proposed_acceptance_criteria='냉방 20~30°C, 난방 16~30°C 유지', reason='정책 변경')]
    return Agent2TransportDesign.model_validate(data)

def test_model_schema_excludes_current_text_but_saved_schema_retains_it():
    assert 'current_acceptance_criteria' not in SrsRevisionDraft.model_json_schema()['properties']
    assert 'current_acceptance_criteria' in pipeline.SrsRevisionProposal.model_json_schema()['properties']
    data=draft_fixture().model_dump(mode='json', by_alias=True)
    data['SRS_개정_제안'][0]['current_acceptance_criteria']='잘못된 원문'
    with pytest.raises(ValueError): Agent2TransportDesign.model_validate(data)

@pytest.mark.parametrize('proposed', ['냉방 20~30°C, 난방 16~30°C 유지', '틀린 제안 99°C'])
def test_materialization_copies_only_frozen_original(proposed):
    draft=draft_fixture(); draft.srs_revision_proposals[0].proposed_acceptance_criteria=proposed
    raw=draft.model_dump()
    requirements=cp2_requirements()
    result, records=materialize_srs_revision_sources(draft,requirements)
    p=result.srs_revision_proposals[0]
    assert p.current_acceptance_criteria==requirements['REQ-TEMP-001'].acceptance_criteria
    assert p.proposed_acceptance_criteria==proposed
    assert draft.model_dump()==raw
    assert records[0]['source']=='FROZEN_SRS_PROGRAM_COPY'
    assert Agent2TestDesign.model_validate(result.model_dump())==result

def test_unknown_requirement_never_guessed():
    with pytest.raises(ValueError, match='고정 SRS'):
        materialize_srs_revision_sources(draft_fixture(),{})

@pytest.mark.parametrize('rewrite',[False,True])
def test_api_initial_and_rewrite_use_transport_and_keep_provenance(rewrite):
    draft=draft_fixture()
    class Responses:
        def parse(self, **kwargs):
            self.kwargs=kwargs
            assert kwargs['text_format'] is Agent2TransportDesign
            return SimpleNamespace(output_parsed=draft,id='resp-source',usage=None)
    responses=Responses()
    agent=OpenAIAgent2(model='gpt-6.1-sol',client=SimpleNamespace(responses=responses))
    response=agent.design(cp1_request(),cp2_analysis(),cp2_requirements(),
        previous_design=cp2_valid_design() if rewrite else None,
        checkpoint_feedback=['누락 확인'] if rewrite else None)
    assert response.raw_model_output==draft.model_dump(mode='json',by_alias=True)
    assert response.srs_source_attachments[0]['source']=='FROZEN_SRS_PROGRAM_COPY'
    assert 'current_acceptance_criteria' not in response.raw_model_output['SRS_개정_제안'][0]
    assert cp2_requirements()['REQ-TEMP-001'].acceptance_criteria in responses.kwargs['input'][1]['content']

def test_approval_still_rejects_changed_srs(tmp_path):
    draft=draft_fixture(); requirements=cp2_requirements()
    result,_=materialize_srs_revision_sources(draft,requirements)
    original=requirements['REQ-TEMP-001'].acceptance_criteria
    path=tmp_path/'srs.md'
    path.write_text(f'| REQ-TEMP-001 | 온도 기준 | {original} |\n',encoding='utf-8')
    pipeline.apply_srs_revision_proposals(path,result.srs_revision_proposals,write=False)
    changed='| REQ-TEMP-001 | 온도 기준 | 다른 정책 15~31°C |\n'
    path.write_text(changed,encoding='utf-8')
    with pytest.raises(ValueError,match='기준 원문'):
        pipeline.apply_srs_revision_proposals(path,result.srs_revision_proposals,write=True)
    assert path.read_text(encoding='utf-8')==changed

def test_source_record_retains_transport_and_snapshot(tmp_path):
    from qa_pipeline_execution import _record_agent2_srs_source
    draft=draft_fixture(); result,records=materialize_srs_revision_sources(draft,cp2_requirements())
    response=pipeline.Agent2Response(result,'resp-test','TEST_DOUBLE',{},draft.model_dump(mode='json',by_alias=True),records)
    _record_agent2_srs_source(tmp_path,response,1,{'srs_sha256':'frozen-test'})
    saved=json.loads((tmp_path/'agent2_srs_source_attempt_1.json').read_text(encoding='utf-8'))
    assert saved['srs_sha256']=='frozen-test' and saved['capture_status']=='CAPTURED'
    assert 'current_acceptance_criteria' not in saved['raw_model_output']['SRS_개정_제안'][0]
    assert saved['attachments']==records
