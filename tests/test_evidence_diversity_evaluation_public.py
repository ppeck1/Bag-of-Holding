# Public subset: private-corpus/operator harness checks are retained privately.
"""Measurement arithmetic and fail-closed judgments; no runtime state or DB."""


import copy


import hashlib


import pytest


def evaluator():
    from app.core import evidence_diversity_evaluation
    return evidence_diversity_evaluation


def fixture():
    texts={'a':'Alpha fact.','b':'Beta fact.','ab':'Alpha fact. Beta fact.',
           'a_copy':'A differently worded alpha.','context':'Nearby background.'}
    claims={'a':{'alpha':'Alpha fact.'},'b':{'beta':'Beta fact.'},
            'ab':{'alpha':'Alpha fact.','beta':'Beta fact.'},
            'a_copy':{'alpha':'A differently worded alpha.'},'context':{}}
    case={'case_id':'independent_hand_check','required_aspects':['alpha','beta'],'optional_aspects':[],
          'expects_no_answer':False,'conflict_unresolved':False,'passage_applicable':True,
          'evidence_judgments':{key:{'document_id':'doc-shared' if key in {'a','b','ab'} else 'doc-'+key,
               'text_sha256':hashlib.sha256(text.encode()).hexdigest(),'role':'direct' if claims[key] else 'context',
               'supports':claims[key],'policy_allowed':True} for key,text in texts.items()}}
    def observation(*keys,**overrides):
        value={'results':[{'evidence_id':key,'document_id':case['evidence_judgments'][key]['document_id'],
                           'text':texts[key],'policy_allowed':True} for key in keys],
               'boundary_failures':[],'prefix_stable':True}
        value.update(overrides)
        return value
    return case,observation


def test_same_document_complementary_claims_get_full_coverage():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('a','b'))
    assert result['required_aspect_coverage_at_k']==1
    assert result['new_aspects_by_rank']==[['alpha'],['beta']]
    assert result['redundant_slots']==0
    assert result['document_concentration_at_k']==1


def test_cross_document_paraphrase_is_redundant_by_reviewed_fact():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('a','a_copy'))
    assert result['required_aspect_coverage_at_k']==0.5
    assert result['redundant_slots']==1
    assert result['document_concentration_at_k']==0.5
    assert result['uncovered_required_aspects']==['beta']


def test_overlap_earns_only_its_additional_fact():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('a','ab'))
    assert result['new_aspects_by_rank']==[['alpha'],['beta']]
    assert result['repeated_aspects_by_rank']==[[],['alpha']]
    assert result['partially_repeated_slots']==1 and result['redundant_slots']==0


def test_reordered_evidence_changes_novelty_attribution_not_set_coverage():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('ab','a'))
    assert result['required_aspect_coverage_at_k']==1
    assert result['new_aspects_by_rank']==[['alpha','beta'],[]]
    assert result['redundant_slots']==1


def test_duplicate_identity_and_exact_text_are_separate_diagnostics():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('a','a','context','context'))
    assert result['duplicate_identity_slots']==2
    assert result['exact_text_repeat_slots']==2
    assert result['redundant_slots']==1
    assert result['nonanswer_context_slots']==2


def test_unknown_evidence_cannot_be_relevant_or_redundant_by_default():
    case,observed=fixture()
    obs=observed('a')
    obs['results'].append({'evidence_id':'new','document_id':'other','text':'Beta fact.','policy_allowed':True})
    result=evaluator().score_evidence(case,obs)
    assert result['unknown_slots']==1 and result['judged_slot_fraction']==0.5
    assert result['required_aspect_coverage_at_k']==0.5
    assert result['coverage_interpretation']=='judged_lower_bound'
    assert result['redundant_slots']==0


def test_known_unjudged_label_stays_unknown():
    case,observed=fixture()
    case['evidence_judgments']['context']['role']='unknown'
    result=evaluator().score_evidence(case,observed('context'))
    assert result['unknown_slots']==1 and result['judged_slot_fraction']==0
    assert result['redundancy_rate_over_judged_usable_slots'] is None


@pytest.mark.parametrize('deny_in',['judgment','observation','both'])
def test_policy_forbidden_claim_never_earns_usable_gain(deny_in):
    case,observed=fixture()
    obs=observed('a','b')
    if deny_in in {'judgment','both'}:
        case['evidence_judgments']['a']['policy_allowed']=False
    if deny_in in {'observation','both'}:
        obs['results'][0]['policy_allowed']=False
    result=evaluator().score_evidence(case,obs)
    assert result['required_aspect_coverage_at_k']==0.5
    assert result['forbidden_slots']==1
    assert result['boundary_failures']==['forbidden_evidence_exposed']
    assert result['new_aspects_by_rank']==[[],['beta']]


def test_boundary_and_prefix_failures_are_not_diluted_by_full_coverage():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('ab',boundary_failures=['library_scope_leak'],prefix_stable=False))
    assert result['required_aspect_coverage_at_k']==1
    assert result['boundary_failures']==['library_scope_leak']
    assert result['prefix_stable'] is False
    assert 'quality_passed' not in result


def test_no_relevant_denominator_never_becomes_perfect_coverage():
    case,observed=fixture()
    case.update(required_aspects=[],optional_aspects=[],expects_no_answer=True)
    case['evidence_judgments']={k:{**v,'supports':{},'role':'irrelevant'} for k,v in case['evidence_judgments'].items()}
    result=evaluator().score_evidence(case,observed('a'))
    assert result['required_aspect_coverage_at_k'] is None
    assert result['no_answer_false_positive'] is True
    assert result['irrelevant_slots']==1


def test_empty_results_preserve_missing_facts_and_null_denominators():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed())
    assert result['required_aspect_coverage_at_k']==0
    assert result['uncovered_required_aspects']==['alpha','beta']
    assert result['judged_slot_fraction'] is None
    assert result['document_concentration_at_k'] is None


def test_discovery_has_no_passage_metrics():
    case,observed=fixture()
    case.update(required_aspects=[],optional_aspects=[],passage_applicable=False,evidence_judgments={})
    obs={'results':[{'evidence_id':'doc','document_id':'document','text':None,'policy_allowed':True}]}
    result=evaluator().score_evidence(case,obs)
    assert result['passage_applicable'] is False
    assert result['required_aspect_coverage_at_k'] is None
    assert result['redundant_slots'] is None and result['unknown_slots'] is None
    assert result['discovery_result_count']==1


def test_conflicting_positions_never_establish_authority():
    case,observed=fixture(); case['conflict_unresolved']=True
    result=evaluator().score_evidence(case,observed('a','b'))
    assert result['required_aspect_coverage_at_k']==1
    assert result['conflict_unresolved'] is True
    assert result['answer_authority_inferred'] is False


def test_optional_aspects_do_not_inflate_required_coverage():
    case,observed=fixture()
    case.update(required_aspects=['alpha'],optional_aspects=['beta'])
    result=evaluator().score_evidence(case,observed('b'))
    assert result['required_aspect_coverage_at_k']==0
    assert result['covered_optional_aspects']==['beta']


def test_top_k_consumes_actual_slots_including_irrelevant_context():
    case,observed=fixture()
    result=evaluator().score_evidence(case,observed('context','a','b'),k=2)
    assert result['required_aspect_coverage_at_k']==0.5
    assert result['returned_slots']==2 and result['nonanswer_context_slots']==1


def test_raw_anchor_matching_cannot_backfill_undeclared_claims():
    case,observed=fixture()
    case['evidence_judgments']['ab']['supports']={'alpha':'Alpha fact.'}
    result=evaluator().score_evidence(case,observed('ab'))
    assert result['required_aspect_coverage_at_k']==0.5
    assert result['covered_required_aspects']==['alpha']


@pytest.mark.parametrize('change',[
    lambda c:c.update(required_aspects=['alpha','alpha']),
    lambda c:c.update(optional_aspects=['alpha']),
    lambda c:c.update(expects_no_answer=True),
    lambda c:c.update(passage_applicable=False),
    lambda c:c.update(conflict_unresolved=1),
    lambda c:c['evidence_judgments']['a'].update(role='guessed'),
    lambda c:c['evidence_judgments']['a'].update(role=[]),
    lambda c:c['evidence_judgments']['a'].update(policy_allowed=1),
    lambda c:c['evidence_judgments']['a'].update(text_sha256='bad'),
    lambda c:c['evidence_judgments']['a'].update(supports={'unknown':'Alpha fact.'}),
    lambda c:c['evidence_judgments']['a'].update(supports={'alpha':''}),
    lambda c:c['evidence_judgments']['a'].update(role='unknown'),
    lambda c:c['evidence_judgments']['a'].update(role='context'),
    lambda c:c['evidence_judgments']['a'].update(role='direct',supports={}),
])
def test_ambiguous_or_malformed_judgments_fail_closed(change):
    case,_=fixture(); change(case)
    api=evaluator()
    with pytest.raises(api.EvaluationError):
        api.validate_case(case)


@pytest.mark.parametrize('change',[
    lambda o:o['results'][0].update(text='Beta fact.'),
    lambda o:o['results'][0].update(document_id='other'),
    lambda o:o['results'][0].update(policy_allowed=1),
    lambda o:o['results'][0].update(text=None),
    lambda o:o.update(boundary_failures='not a list'),
    lambda o:o.update(prefix_stable='yes'),
    lambda o:o.update(results='not a list'),
])
def test_changed_or_malformed_delivery_cannot_reuse_old_judgments(change):
    case,observed=fixture(); obs=observed('a'); change(obs)
    api=evaluator()
    with pytest.raises(api.EvaluationError):
        api.score_evidence(case,obs)


@pytest.mark.parametrize('k',[0,26,True,1.5])
def test_invalid_horizon_rejected(k):
    case,observed=fixture(); api=evaluator()
    with pytest.raises(api.EvaluationError):
        api.score_evidence(case,observed('a'),k=k)


def test_input_judgments_and_observations_are_not_mutated():
    case,observed=fixture(); obs=observed('a','b'); before=copy.deepcopy((case,obs))
    evaluator().score_evidence(case,obs)
    assert (case,obs)==before


def test_clipping_cannot_keep_a_claim_even_with_a_matching_new_digest():
    case,observed=fixture(); obs=observed('ab')
    obs['results'][0]['text']='Alpha fact.'
    case['evidence_judgments']['ab']['text_sha256']=hashlib.sha256(b'Alpha fact.').hexdigest()
    api=evaluator()
    with pytest.raises(api.EvaluationError,match='claim absent'):
        api.score_evidence(case,obs)
