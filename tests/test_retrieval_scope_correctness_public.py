# Public subset: private-corpus/operator harness checks are retained privately.
"""Retrieval precision/scope regressions; all state is synthetic and disposable."""


from __future__ import annotations


import json


from pathlib import Path


import pytest


from tools.probes import retrieval_quality_baseline_v0_1 as baseline


DECK = Path(__file__).parent/'fixtures/retrieval_quality/judged_deck_v0_1.json'


@pytest.fixture
def corpus():
    deck, _ = baseline.load_deck(DECK)
    with baseline._temporary_fixture(deck) as db:
        with baseline._measurement_state(baseline._epoch(deck['as_of'])):
            yield deck, db


def case(deck, identity):
    return next(c for c in deck['cases'] if c['case_id'] == identity)


def test_expired_identifier_cannot_be_answered_by_unmatching_lineage(corpus):
    from app.core import current_context_brief, retrieval
    deck, _ = corpus
    query = case(deck, 'stale_current_02_historical')['query']
    result = retrieval.retrieve_governed(query, mode='audit_provenance')
    assert result['context_packs'] == []
    assert {e['reason'] for e in result['excluded_summary']} == {'card_expired'}
    brief = current_context_brief.build_current_context_brief(query, mode='audit_provenance')
    assert brief['answerable_now'] is False
    assert brief['best_evidence'] == []


@pytest.mark.parametrize('identity', ['exact_phrase_01_cobalt','exact_phrase_02_orchid','exact_phrase_03_river'])
def test_quoted_phrase_is_required_in_every_candidate_lane(corpus, identity):
    from app.core import retrieval
    deck, _ = corpus
    judged = case(deck, identity)
    result = retrieval.retrieve_governed(judged['query'], mode='exploration')
    assert {p['doc_id'] for p in result['context_packs']} == {
        item['doc_id'] for item in judged['expected']['graded_relevance']
    }


@pytest.mark.parametrize('filters', [{'private':False},{'library_id':'missing-library'},
    {'dimension':'risk'},{'project':['unexpected']},{'scope':'private'},{'project':' '}])
def test_unsupported_or_invalid_scope_is_rejected(corpus, filters):
    from app.core import retrieval
    with pytest.raises(ValueError):
        retrieval.retrieve_governed('rotation', filters=filters)


def scope_fixture(db):
    """Separate two path scopes and link them to exercise augmentation."""
    from app.core import logical_libraries
    conn = db.get_conn()
    try:
        conn.execute("UPDATE docs SET path = 'alpha/' || doc_id || '.md' WHERE doc_id = 'doc-helios-v1'")
        conn.execute("UPDATE docs SET path = 'beta/' || doc_id || '.md' WHERE doc_id != 'doc-helios-v1'")
        conn.commit()
    finally:
        conn.close()
    return next(x.id for x in logical_libraries.list_logical_libraries() if x.prefix == 'alpha')


def test_library_scope_excludes_lineage_cards_and_brief_metadata(corpus):
    from app.core import context_object, current_context_brief, retrieval
    deck, db = corpus
    lib = scope_fixture(db)
    query = case(deck, 'conflict_supersession_03_helios_history')['query']
    filters = {'library_id':lib}
    result = retrieval.retrieve_governed(query, mode='exploration', filters=filters, limit=1)
    # Only the expired scoped document matches: neither its live replacement nor
    # a high-authority out-of-scope card may become an answer.
    assert result['context_packs'] == []
    assert {p['doc_id'] for p in result['excluded_summary']} == {'doc-helios-v1'}
    brief = current_context_brief.build_current_context_brief(query, filters=filters)
    assert brief['answerable_now'] is False
    assert brief['best_evidence'] == []
    assert 'doc-helios-v2' not in json.dumps(brief)
    context = context_object.assemble('query', query, filters=filters)
    assert context['evidence'] == []
    assert 'doc-helios-v2' not in json.dumps(context)


def test_scoped_card_augmentation_is_filtered_before_its_limit(corpus):
    from app.core import retrieval
    _, db = corpus
    lib = scope_fixture(db)
    conn = db.get_conn()
    try:
        # Keep one valid card in alpha with no matching chunk. Newer beta cards
        # must not starve it from the bounded card candidate lane.
        conn.execute("UPDATE cards SET valid_until='2030-01-01T00:00:00Z', topic='unique atlas scope', updated_ts=1 WHERE doc_id='doc-helios-v1'")
        conn.execute("DELETE FROM doc_chunks_fts WHERE doc_id='doc-helios-v1'")
        for number in range(30):
            conn.execute("INSERT INTO cards (id,plane,card_type,topic,payload_json,authority_json,doc_id,updated_ts) VALUES (?,'evidence','note','unique atlas scope',?,?,'doc-helios-v2',?)",
                (f'scope-decoy-{number}',json.dumps({'confidence':.9}),json.dumps({'state':'approved'}),2000000000+number))
        conn.commit()
    finally:
        conn.close()
    result = retrieval.retrieve_governed('unique atlas scope', mode='exploration', filters={'library_id':lib}, limit=1)
    assert [p['doc_id'] for p in result['context_packs']] == ['doc-helios-v1']


@pytest.mark.parametrize('consumer', ['brief','context'])
def test_supplied_result_cannot_override_requested_scope(corpus, consumer):
    from app.core import context_object, current_context_brief, retrieval
    _, db = corpus
    lib = scope_fixture(db)
    wide = retrieval.retrieve_governed_result('Helios rotation', mode='exploration')
    with pytest.raises(ValueError):
        if consumer == 'brief':
            current_context_brief.build_current_context_brief('Helios rotation', filters={'library_id':lib}, governed_result=wide)
        else:
            context_object.assemble('query','Helios rotation', filters={'library_id':lib}, governed_result=wide)


@pytest.mark.parametrize('path,body', [
    ('/api/retrieve', {'query':'Helios','private':False}),
    ('/api/current-context-brief', {'topic':'Helios','library_id':'unknown'}),
    ('/api/context-object', {'scope':{'type':'query','query':'Helios','private':False}}),
])
def test_api_body_scope_cannot_be_silently_ignored(corpus, path, body):
    from fastapi.testclient import TestClient
    from app.api.main import app
    from app.core import retrieval
    app.dependency_overrides[retrieval.require_retrieval_token] = lambda:'test'
    try:
        with TestClient(app) as client:
            response = client.post(path,json=body)
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(retrieval.require_retrieval_token,None)


@pytest.mark.parametrize('path', ['/api/retrieve?q=Helios','/api/current-context-brief?topic=Helios','/api/context-object?scope=doc:doc-helios-v2','/api/search?q=Helios'])
def test_api_query_scope_cannot_be_silently_ignored(corpus, path):
    from fastapi.testclient import TestClient
    from app.api.main import app
    from app.core import retrieval
    app.dependency_overrides[retrieval.require_retrieval_token] = lambda:'test'
    try:
        with TestClient(app) as client:
            response = client.get(path+'&private=false')
        assert response.status_code == 422
    finally:
        app.dependency_overrides.pop(retrieval.require_retrieval_token,None)


def test_closed_promoted_gate_has_no_matching_existence_or_reference_leak(corpus):
    from app.core import retrieval
    deck, db = corpus
    query = case(deck,'promoted_only_02_request_closed')['query']
    with baseline._promoted_gate(True):
        before = retrieval.retrieve_governed(query,mode='exploration',include_promoted=False)
        conn = db.get_conn()
        try:
            conn.execute("DELETE FROM docs WHERE doc_id='doc-promoted-lattice'")
            conn.commit()
        finally:
            conn.close()
        after = retrieval.retrieve_governed(query,mode='exploration',include_promoted=False)
    assert before == after
    assert 'doc-promoted-lattice' not in json.dumps(before)


def test_unknown_core_filter_fails_before_database_or_audit(monkeypatch):
    from app.core import retrieval
    def forbidden(*args,**kwargs):
        raise AssertionError('unsupported scope reached retrieval or audit')
    monkeypatch.setattr(retrieval._RetrievalReadSnapshot,'__enter__',forbidden)
    monkeypatch.setattr(retrieval,'log_storage_event',forbidden)
    with pytest.raises(ValueError,match='unsupported retrieval filter'):
        retrieval.retrieve_governed('Helios',filters={'private':False})


@pytest.mark.parametrize('endpoint', ['retrieve_get','retrieve_post','brief_get','brief_post','context_post'])
def test_api_transports_preserve_requested_library(corpus,endpoint):
    from fastapi.testclient import TestClient
    from app.api.main import app
    from app.core import retrieval
    _, db = corpus
    lib = scope_fixture(db)
    app.dependency_overrides[retrieval.require_retrieval_token] = lambda:'test'
    try:
        with TestClient(app) as client:
            if endpoint == 'retrieve_get':
                response = client.get('/api/retrieve',params={'q':'Helios rotation','mode':'exploration','library_id':lib})
            elif endpoint == 'retrieve_post':
                response = client.post('/api/retrieve',json={'query':'Helios rotation','mode':'exploration','library_id':lib})
            elif endpoint == 'brief_get':
                response = client.get('/api/current-context-brief',params={'topic':'Helios rotation','library_id':lib})
            elif endpoint == 'brief_post':
                response = client.post('/api/current-context-brief',json={'topic':'Helios rotation','library_id':lib})
            else:
                response = client.post('/api/context-object',json={'scope':{'type':'query','query':'Helios rotation'},'filters':{'library_id':lib}})
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload.get('context_packs',payload.get('best_evidence',payload.get('evidence'))) == []
        assert 'doc-helios-v2' not in json.dumps(payload)
    finally:
        app.dependency_overrides.pop(retrieval.require_retrieval_token,None)
