"""Frozen literal judgments through public surfaces; no operator adapter or corpus."""
import hashlib
import json
from pathlib import Path

import pytest

from tools.probes import retrieval_quality_baseline_v0_1 as historical

DECK_PATH = Path(__file__).parent/'fixtures/retrieval_quality/identifier_precision_v0_1.json'
RAW = DECK_PATH.read_bytes()
assert hashlib.sha256(RAW).hexdigest() == '377a96057619cee5939613e60d4678feab30a192d59b400b2083a9e8d4a86b62'
DECK = json.loads(RAW)
SURFACES = ('api_retrieve','current_context_brief','query_context_object')
PAIRS = [(case, surface) for case in DECK['cases'] for surface in SURFACES
         if case['mode']=='exploration' or surface in SURFACES[:2]]


@pytest.fixture(scope='module')
def corpus():
    with historical._temporary_fixture(DECK):
        with historical._measurement_state(historical._epoch(DECK['as_of'])):
            yield


def invoke(surface, case, limit):
    from app.core import context_object, current_context_brief, retrieval
    filters = dict(case['filters'])
    if filters.get('library_id'):
        filters['library_id'] = historical._search_library_id(filters['library_id'])
    args = dict(filters=filters, include_promoted=case['include_promoted'])
    if surface=='api_retrieve':
        return retrieval.retrieve_governed(case['query'], mode=case['mode'], limit=limit, **args)
    if surface=='current_context_brief':
        return current_context_brief.build_current_context_brief(case['query'], mode=case['mode'], limit=limit, **args)
    return context_object.assemble('query',case['query'], evidence_limit=limit, question_type='exploratory', **args)


@pytest.mark.parametrize('case,surface', PAIRS, ids=[c['id']+'-'+s for c,s in PAIRS])
def test_original_literal_judgments_and_prefixes(corpus, case, surface):
    identity=lambda rows:[(r['doc_id'],r.get('chunk_id')) for r in rows]
    with historical._promoted_gate(case['server_promoted_gate']):
        long=historical._ranked_items(surface,invoke(surface,case,25))
        for limit in (1,2,3,5,8,13,25):
            response=invoke(surface,case,limit)
            rows=historical._ranked_items(surface,response)
            assert {row['doc_id'] for row in rows} == set(case['expected_doc_ids'])
            assert identity(rows) == identity(long[:limit])
            answerable=historical._answerable(surface,response)
            if answerable is not None:
                assert answerable == bool(case['expected_doc_ids'])
