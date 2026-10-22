# Public subset: private-corpus/operator harness checks are retained privately.
"""Current exact admission/coverage contracts; prior diagnostic results stay historical."""


import copy


import sys


import pytest





import public_retrieval_helpers as original


from tools.probes import retrieval_quality_baseline_v0_1 as historical


@pytest.fixture
def fixture_db():
    docs=[original.document('target',['quota.read is an exact target.'],library='beta')]
    with historical._temporary_fixture({'deck_id':'exact-unit','documents':docs}) as db, \
         historical._measurement_state(historical._epoch('2026-10-21T12:00:00+00:00')):
        yield db


def test_genuine_absence_is_complete_without_substitute(fixture_db):
    from app.core.retrieval import retrieve_governed
    result=retrieve_governed('absent.read',mode='exploration')
    assert result['count']==0
    assert result['retrieval']['exact_lookup']['state']=='complete'


def test_card_payload_coercion_matches_the_existing_field_contract(fixture_db):
    from app.core import retrieval
    historical._seed_fixture({'deck_id':'card-coercion','documents':[
        original.document('coerced',['Unrelated.'],card=True)]},fixture_db)
    conn=fixture_db.get_conn()
    try:
        conn.execute("UPDATE cards SET payload_json=json_set(payload_json,'$.title',json('true'),'$.text','Safe evidence') WHERE doc_id='coerced'")
        conn.commit()
    finally:
        conn.close()
    result=retrieval.retrieve_governed('`True`',mode='exploration')
    assert result['retrieval']['exact_lookup']['state']=='complete'
    assert {p['doc_id'] for p in result['context_packs']}=={'coerced'}


def test_ordinary_queries_keep_the_existing_contract(fixture_db):
    from app.core.retrieval import retrieve_governed
    result=retrieve_governed('exact target',mode='exploration')
    assert 'exact_lookup' not in result['retrieval']


@pytest.mark.parametrize('constant,value',[('MAX_CALLBACKS',0),('MAX_VM_STEPS',0),('MAX_SECONDS',0),
    ('MAX_MATERIALIZED_BYTES',1),('MAX_EXAMINED_BYTES',0),('MAX_MATERIALIZED_ROWS',0)])
def test_budget_cutoff_is_honest_and_connection_is_reusable(fixture_db,monkeypatch,constant,value):
    from app.core import exact_lookup,retrieval
    monkeypatch.setattr(exact_lookup,constant,value)
    result=retrieval.retrieve_governed('quota.read',mode='exploration')
    assert result['retrieval']['exact_lookup']['state'] in ('partial','unknown')
    assert 'complete' not in result['retrieval']['exact_lookup']['domains'].values()
    assert 'exact_lookup_incomplete' in result['warnings']
    assert result['count']==0
    assert fixture_db.fetchone('SELECT COUNT(*) AS n FROM docs')['n']==1


@pytest.mark.parametrize('filters',[{'doc_id':'target'},{'project':'Narrow project'}])
def test_card_scope_is_applied_before_matching_budget(monkeypatch,filters):
    from app.core import exact_lookup,retrieval
    monkeypatch.setattr(exact_lookup,'MAX_MATCHES',2)
    docs=[original.document(f'other-{i}',['Unrelated.'],title='scope.read',card=True) for i in range(5)]
    docs.append(original.document('target',['Unrelated.'],title='scope.read',card=True))
    with historical._temporary_fixture({'deck_id':'narrow-card-scope','documents':docs}) as db:
        conn=db.get_conn()
        try:
            conn.execute("UPDATE cards SET updated_ts=1 WHERE doc_id='target'")
            conn.execute("UPDATE cards SET payload_json=json_set(payload_json,'$.project','Narrow project') WHERE doc_id='target'")
            conn.execute("UPDATE docs SET project='Narrow project' WHERE doc_id='target'")
            conn.commit()
        finally:
            conn.close()
        result=retrieval.retrieve_governed('scope.read',mode='exploration',filters=filters)
    assert result['retrieval']['exact_lookup']['state']=='complete'
    assert {p['doc_id'] for p in result['context_packs']}=={'target'}


def test_foreign_library_rows_do_not_consume_exact_callback_budget(monkeypatch):
    from app.core import exact_lookup,retrieval
    from app.core.logical_libraries import _library_id_for_segment
    monkeypatch.setattr(exact_lookup,'MAX_CALLBACKS',2)
    docs=[original.document(f'foreign-{i}',['scope.read'],library='alpha') for i in range(40)]
    docs.append(original.document('target',['scope.read'],library='beta'))
    with historical._temporary_fixture({'deck_id':'scoped-callbacks','documents':docs}):
        result=retrieval.retrieve_governed('scope.read',mode='exploration',filters={'library_id':_library_id_for_segment('beta')})
    assert result['retrieval']['exact_lookup']['state']=='complete'
    assert {p['doc_id'] for p in result['context_packs']}=={'target'}


def test_default_matching_boundary_is_honest_for_dense_population():
    from app.core import exact_lookup,retrieval
    docs=[original.document(f'dense-{i}',['dense.read']) for i in range(exact_lookup.MAX_MATCHES+1)]
    with historical._temporary_fixture({'deck_id':'default-match-boundary','documents':docs}):
        result=retrieval.retrieve_governed('dense.read',mode='exploration',limit=25)
    assert result['retrieval']['exact_lookup']['state']=='partial'
    assert 0<result['count']<=25


def test_matching_evidence_limit_reports_partial(monkeypatch):
    from app.core import exact_lookup,retrieval
    monkeypatch.setattr(exact_lookup,'MAX_MATCHES',2)
    docs=[original.document(f'doc-{i}',['many.read']) for i in range(8)]
    with historical._temporary_fixture({'deck_id':'matching-cutoff','documents':docs}),historical._measurement_state(historical._epoch('2026-10-21T12:00:00+00:00')):
        result=retrieval.retrieve_governed('many.read',mode='exploration',limit=25)
    assert result['retrieval']['exact_lookup']['state']=='partial'
    assert result['retrieval']['exact_lookup']['continuation_available'] is False


def test_oversized_field_is_not_claimed_exhaustively_checked(monkeypatch):
    from app.core import exact_lookup,retrieval
    docs=[original.document('oversize',['large.read '+('x'*1000)])]
    monkeypatch.setattr(exact_lookup,'MAX_FIELD_BYTES',128)
    with historical._temporary_fixture({'deck_id':'field-cutoff','documents':docs}):
        result=retrieval.retrieve_governed('large.read',mode='exploration')
    assert result['retrieval']['exact_lookup']['state']=='partial'
    assert result['count']==0
    assert result['retrieval']['exact_lookup']['domains']['chunks']=='partial'


def test_unexpected_sql_failures_are_not_silenced(fixture_db,monkeypatch):
    from app.core import retrieval
    def broken(*args,**kwargs):
        raise RuntimeError('synthetic SQL defect')
    monkeypatch.setattr(retrieval._RetrievalReadSnapshot,'fetchall',broken)
    with pytest.raises(RuntimeError,match='synthetic SQL defect'):
        retrieval.retrieve_governed('quota.read',mode='exploration')


def test_coverage_domains_share_one_read_snapshot(fixture_db,monkeypatch):
    from app.core import retrieval
    original_metadata=retrieval._batch_metadata
    injected=[False]
    def metadata(*args,**kwargs):
        if not injected[0]:
            injected[0]=True
            historical._seed_fixture({'deck_id':'concurrent-writer','documents':[
                original.document('late',['later.read'],card=True)]},fixture_db)
        return original_metadata(*args,**kwargs)
    monkeypatch.setattr(retrieval,'_batch_metadata',metadata)
    first=retrieval.retrieve_governed('later.read',mode='exploration')
    assert first['retrieval']['exact_lookup']['state']=='complete' and first['count']==0
    second=retrieval.retrieve_governed('later.read',mode='exploration')
    assert second['count']>0
