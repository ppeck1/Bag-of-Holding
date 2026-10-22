# Portable lifecycle checks; adapter-only surface omitted.
"""Source availability is independent from retained observations and authority."""


import hashlib


import importlib


import json


import os


from pathlib import Path


import pytest


from tools.probes import retrieval_quality_baseline_v0_1 as historical








SURFACES = ('api_retrieve', 'current_context_brief', 'query_context_object', 'keyword_search')


@pytest.fixture
def owned(tmp_path, monkeypatch):
    library = tmp_path / 'library'
    library.mkdir()
    for key, value in {'BOH_DB': str(tmp_path / 'boh.db'), 'BOH_LIBRARY': str(library),
                       'BOH_DATA_ROOT': str(tmp_path / 'data'), 'BOH_AUTO_INDEX': 'false',
                       'BOH_DETERMINISTIC_REVIEW_ON_INDEX': 'false', 'BOH_LLM_REVIEW_ON_INDEX': 'false',
                       'BOH_ANALYZE_ON_INDEX': 'false', 'BOH_INTAKE_SCHEDULER_ENABLED': 'false'}.items():
        monkeypatch.setenv(key, value)
    from app.db import connection as db
    monkeypatch.setattr(db, 'DB_PATH', str(tmp_path / 'boh.db'))
    db.init_db()
    with historical._measurement_state(historical._epoch('2026-10-21T12:00:00+00:00')):
        yield library, db


def write(library, relative='operations/source.md', raw=b'# Source\n\nLifecycle marker amber.retained.\n'):
    path = library / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(raw)
    return path


def index(library, path):
    from app.services.indexer import index_file
    result = index_file(path, library)
    assert result['indexed'], result
    return result['doc_id']


def scan(library, **kwargs):
    from app.core.autoindex import run_auto_index
    return run_auto_index(str(library), **kwargs)


def availability(doc_id):
    from app.core.source_lifecycle import get_status
    return get_status(doc_id)


def revisions(doc_id):
    from app.core.source_lifecycle import get_revisions
    return get_revisions(doc_id)


@pytest.mark.parametrize('surface', SURFACES)
def test_completed_scan_deletion_withholds_default_evidence_and_keeps_history(owned, surface):
    library, db = owned
    path = write(library)
    raw = path.read_bytes()
    doc_id = index(library, path)
    assert observed(surface, 'amber.retained', db)
    path.unlink()  # Owned fixture only. The reconciler never deletes source files.
    result = scan(library)
    assert observed(surface, 'amber.retained', db) == []
    assert result['source_lifecycle']['scan_complete'] is True
    assert availability(doc_id)['availability'] == 'missing'
    assert revisions(doc_id)[0]['raw_bytes'] == raw
    assert db.fetchone('SELECT status FROM docs WHERE doc_id=?', (doc_id,))['status'] == 'draft'
    assert db.fetchone('SELECT COUNT(*) AS n FROM doc_chunks WHERE doc_id=?', (doc_id,))['n'] > 0


@pytest.mark.parametrize('raw', [b'', b'\x00binary', b'\xff', b'---\nboh: [bad\n---\n'])
def test_invalid_update_preserves_snapshot_but_not_current_eligibility(owned, raw):
    library, db = owned
    from app.services.indexer import index_file
    path = write(library)
    original = path.read_bytes()
    doc_id = index(library, path)
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,))
    path.write_bytes(raw)
    assert not index_file(path, library)['indexed']
    assert observed('api_retrieve', 'amber.retained', db) == []
    assert observed('keyword_search', 'amber.retained', db) == []
    assert availability(doc_id)['availability'] == 'invalid'
    assert db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,)) == stored
    assert revisions(doc_id)[0]['raw_bytes'] == original
    assert path.read_bytes() == raw


def test_direct_missing_observation_is_uncertain_until_complete_scan(owned):
    library, db = owned
    from app.services.indexer import index_file
    path = write(library)
    doc_id = index(library, path)
    path.unlink()
    assert not index_file(path, library)['indexed']
    assert availability(doc_id)['availability'] == 'unknown'
    assert observed('api_retrieve', 'amber.retained', db) == []
    scan(library)
    assert availability(doc_id)['availability'] == 'missing'


@pytest.mark.parametrize('replace', [False, True])
def test_valid_observation_recovers_invalid_source_without_losing_history(owned, replace):
    library, db = owned
    from app.services.indexer import index_file
    path = write(library)
    old = path.read_bytes()
    doc_id = index(library, path)
    path.write_bytes(b'\x00invalid')
    index_file(path, library)
    new = b'# Restored\n\nNew marker amber.recovered.\n' if replace else old
    path.write_bytes(new)
    assert index(library, path) == doc_id
    assert availability(doc_id)['availability'] == 'present'
    assert {r['raw_bytes'] for r in revisions(doc_id)} == {old, new}
    assert observed('api_retrieve', 'amber.recovered' if replace else 'amber.retained', db)
    if replace:
        assert observed('api_retrieve', 'amber.retained', db) == []


def test_updates_are_atomic_and_prior_source_bytes_are_immutable(owned):
    library, db = owned
    path = write(library)
    old = path.read_bytes()
    doc_id = index(library, path)
    first = revisions(doc_id)
    new = b'# Update\n\nMarker amber.replaced.\n'
    path.write_bytes(new)
    assert index(library, path) == doc_id
    assert first[0] in revisions(doc_id)
    assert {r['raw_bytes'] for r in revisions(doc_id)} == {old, new}
    assert observed('api_retrieve', 'amber.retained', db) == []
    assert observed('api_retrieve', 'amber.replaced', db)


@pytest.mark.parametrize('destination', ['operations/renamed.md', 'research/renamed.md'])
def test_proven_rename_preserves_identity_and_updates_all_path_projections(owned, destination):
    library, db = owned
    path = write(library)
    doc_id = index(library, path)
    raw = path.read_bytes()
    other = library / destination
    other.parent.mkdir(exist_ok=True)
    path.rename(other)
    result = scan(library)
    assert result['source_lifecycle']['renamed'] == 1
    assert db.fetchone('SELECT COUNT(*) AS n FROM docs')['n'] == 1
    assert db.fetchone('SELECT path FROM docs WHERE doc_id=?', (doc_id,))['path'] == destination
    assert not db.fetchone('SELECT path FROM docs_fts WHERE path=?', ('operations/source.md',))
    assert {r['path'] for r in db.fetchall('SELECT path FROM doc_chunks WHERE doc_id=?', (doc_id,))} == {destination}
    card = db.fetchone('SELECT payload_json, context_ref_json FROM cards WHERE doc_id=?', (doc_id,))
    assert json.loads(card['payload_json'])['path'] == destination
    assert json.loads(card['context_ref_json'])['path'] == destination
    assert {r['path'] for r in revisions(doc_id)} == {'operations/source.md', destination}
    assert all(r['raw_bytes'] == raw for r in revisions(doc_id)) and other.read_bytes() == raw
    assert index(library, other) == doc_id
    if destination.startswith('research/'):
        from app.core.logical_libraries import _library_id_for_segment
        from app.core.retrieval import retrieve_governed
        index(library, write(library, 'operations/anchor.md', b'# Anchor\n\nMarker onyx.unrelated.\n'))
        assert not retrieve_governed('amber.retained', mode='exploration', filters={'library_id': _library_id_for_segment('operations')})['context_packs']
        assert {p['doc_id'] for p in retrieve_governed('amber.retained', mode='exploration', filters={'library_id': _library_id_for_segment('research')})['context_packs']} == {doc_id}


def test_content_match_without_file_identity_does_not_merge_copy_delete(owned):
    library, db = owned
    path = write(library)
    old_id = index(library, path)
    raw = path.read_bytes()
    copy = write(library, 'operations/copied.md', raw)
    path.unlink()
    result = scan(library)
    assert result['source_lifecycle']['renamed'] == 0
    assert db.fetchone('SELECT COUNT(*) AS n FROM docs')['n'] == 2
    new_id = db.fetchone('SELECT doc_id FROM docs WHERE path=?', ('operations/copied.md',))['doc_id']
    assert new_id != old_id and availability(old_id)['availability'] == 'missing'
    assert {r['source_id'] for r in observed('api_retrieve', 'amber.retained', db)} == {new_id}


def test_duplicate_bodies_keep_distinct_identity_during_one_proven_rename(owned):
    library, db = owned
    path = write(library)
    old_id = index(library, path)
    copy = write(library, 'operations/copy.md', path.read_bytes())
    other_id = index(library, copy)
    path.rename(library / 'operations/renamed.md')
    assert scan(library)['source_lifecycle']['renamed'] == 1
    assert {r['doc_id'] for r in db.fetchall('SELECT doc_id FROM docs')} == {old_id, other_id}


def test_offline_root_is_uncertain_without_mass_missing_and_recovers(owned, tmp_path):
    library, db = owned
    path = write(library)
    doc_id = index(library, path)
    offline = tmp_path / 'owned-offline'
    library.rename(offline)
    result = scan(library)
    assert result['source_lifecycle']['scan_complete'] is False
    assert availability(doc_id)['availability'] == 'unknown'
    assert observed('api_retrieve', 'amber.retained', db) == []
    assert db.fetchone('SELECT state FROM source_lifecycle_sources WHERE doc_id=?', (doc_id,))['state'] == 'present'
    offline.rename(library)
    scan(library)
    assert availability(doc_id)['availability'] == 'present'
    assert observed('api_retrieve', 'amber.retained', db)


def test_limited_scan_does_not_infer_deletions(owned):
    library, db = owned
    old_id = index(library, write(library))
    for name in ('second', 'third'):
        index(library, write(library, f'operations/{name}.md'))
    (library / 'operations/source.md').unlink()
    result = scan(library, max_files=1)
    assert result['source_lifecycle']['scan_complete'] is False
    assert availability(old_id)['availability'] == 'unknown'
    assert not db.fetchone("SELECT doc_id FROM source_lifecycle_sources WHERE state='missing'")
    scan(library)
    assert availability(old_id)['availability'] == 'missing'


def test_permission_error_during_enumeration_preserves_uncertainty(owned, monkeypatch):
    library, db = owned
    from app.core import autoindex
    doc_id = index(library, write(library))
    def broken_walk(*args, **kwargs):
        raise PermissionError('owned traversal failure')
        yield
    monkeypatch.setattr(autoindex.os, 'walk', broken_walk)
    result = scan(library)
    assert result['source_lifecycle']['scan_complete'] is False
    assert availability(doc_id)['availability'] == 'unknown'
    assert db.fetchone('SELECT state FROM source_lifecycle_sources WHERE doc_id=?', (doc_id,))['state'] == 'present'


def test_persisted_interrupted_scan_is_uncertain_after_restart(owned):
    library, db = owned
    from app.core import source_lifecycle
    doc_id = index(library, write(library))
    source_lifecycle.begin_scan(library)
    db.init_db()
    importlib.reload(source_lifecycle)
    assert availability(doc_id)['availability'] == 'unknown'
    assert observed('api_retrieve', 'amber.retained', db) == []
    scan(library)
    assert availability(doc_id)['availability'] == 'present'


def test_interrupted_index_loop_keeps_persisted_uncertainty(owned, monkeypatch):
    library, db = owned
    from app.services import indexer
    doc_id = index(library, write(library))
    def interrupted(*args, **kwargs):
        raise KeyboardInterrupt('owned interruption')
    monkeypatch.setattr(indexer, 'index_file', interrupted)
    with pytest.raises(KeyboardInterrupt):
        scan(library, changed_only=False)
    assert availability(doc_id)['availability'] == 'unknown'
    assert revisions(doc_id)


def test_scratch_exclusion_does_not_become_an_absence_claim(owned):
    library, db = owned
    path = write(library, 'scratch/source.md')
    doc_id = index(library, path)
    scan(library, include_scratch=False)
    assert availability(doc_id)['availability'] == 'unknown'
    assert availability(doc_id)['reason'] == 'excluded_from_scan'
    assert revisions(doc_id) and path.exists()


def test_unchanged_rescan_reobserves_without_duplicate_revisions(owned):
    library, db = owned
    doc_id = index(library, write(library))
    old = revisions(doc_id)
    first, second = scan(library), scan(library)
    assert first['skipped'] == second['skipped'] == 1
    assert first['source_lifecycle']['scan_complete'] and second['source_lifecycle']['scan_complete']
    assert revisions(doc_id) == old and availability(doc_id)['availability'] == 'present'


@pytest.mark.parametrize('stage', ['chunks', 'revision'])
def test_failed_index_transaction_retains_prior_evidence_and_history(owned, monkeypatch, stage):
    library, db = owned
    from app.core import retrieval, source_lifecycle
    from app.services.indexer import index_file
    path = write(library)
    doc_id = index(library, path)
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,))
    old = revisions(doc_id)
    path.write_bytes(b'# Failing update\n\nMarker amber.failed.\n')
    def fail(*args, **kwargs):
        raise RuntimeError('owned atomic failure')
    monkeypatch.setattr(retrieval if stage == 'chunks' else source_lifecycle,
                        'replace_doc_chunks' if stage == 'chunks' else 'record_success', fail)
    with pytest.raises(RuntimeError):
        index_file(path, library)
    assert db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,)) == stored
    assert revisions(doc_id) == old and availability(doc_id)['availability'] != 'present'
    assert observed('api_retrieve', 'amber.retained', db) == []


def test_audit_history_is_labelled_and_cannot_bypass_scope_or_promoted_policy(owned, monkeypatch):
    library, db = owned
    from app.core.retrieval import retrieve_governed
    from app.core.logical_libraries import _library_id_for_segment
    path = write(library)
    doc_id = index(library, path)
    path.unlink()
    scan(library)
    audit = retrieve_governed('amber.retained', mode='audit_provenance')
    assert audit['context_packs']
    for pack in audit['context_packs']:
        state = pack['source_lifecycle']
        assert state['availability'] == 'missing' and state['current_evidence'] is False
        assert pack['do_not_treat_as_canonical'] and 'historical_source_evidence' in pack['warnings']
    index(library, write(library, 'research/anchor.md', b'# Anchor\n\nMarker onyx.unrelated.\n'))
    assert not retrieve_governed('amber.retained', mode='audit_provenance', filters={'library_id': _library_id_for_segment('research')})['context_packs']
    monkeypatch.setenv('BOH_RETRIEVAL_INCLUDE_PROMOTED', 'false')
    db.execute("UPDATE docs SET corpus_class='CORPUS_CLASS:PROMOTED_INTAKE' WHERE doc_id=?", (doc_id,))
    assert not retrieve_governed('amber.retained', mode='audit_provenance', include_promoted=True)['context_packs']


def test_known_supersession_filters_old_managed_evidence_without_authorizing_new(owned):
    library, db = owned
    from app.core.retrieval import retrieve_governed
    def version(doc_id, number):
        data = {'boh': {'id': doc_id, 'title': 'Versioned source', 'purpose': 'Versioned source', 'type': 'note',
                       'status': 'working', 'version': number, 'updated': '2026-10-21T12:00:00+00:00',
                       'topics': ['lifecycle-version'], 'scope': {},
                       'rubrix': {'operator_state': 'observe', 'operator_intent': 'capture'}}}
        return ('---\n' + json.dumps(data) + '\n---\n# Versioned source\n\nMarker amber.version.\n').encode()
    old = index(library, write(library, 'operations/old.md', version('version-old', '1.0.0')))
    new = index(library, write(library, 'operations/new.md', version('version-new', '2.0.0')))
    assert {p['doc_id'] for p in retrieve_governed('amber.version', mode='exploration')['context_packs']} == {new}
    assert availability(old)['superseded'] and not availability(old)['current_evidence']
    assert availability(new)['availability'] == 'present'
    assert not retrieve_governed('amber.version', mode='strict_answer')['context_packs']
    audit = retrieve_governed('amber.version', mode='audit_provenance')['context_packs']
    assert old in {p['doc_id'] for p in audit}
    assert all(p['freshness']['superseded'] and p['freshness']['superseded_by'] == new for p in audit if p['doc_id'] == old)


def test_canonical_metadata_is_unchanged_by_disappearance_and_reappearance(owned):
    library, db = owned
    path = write(library)
    raw = path.read_bytes()
    doc_id = index(library, path)
    db.execute("UPDATE docs SET status='canonical',authority_state='canonical',review_state='approved' WHERE doc_id=?", (doc_id,))
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,))
    path.unlink()
    scan(library)
    assert db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,)) == stored
    write(library, raw=raw)
    scan(library)
    assert availability(doc_id)['availability'] == 'present'
    assert db.fetchone('SELECT * FROM docs WHERE doc_id=?', (doc_id,)) == stored


def test_complete_scan_enrolls_legacy_absent_path_without_fabricating_raw_bytes(owned):
    library, db = owned
    path = write(library)
    doc_id = index(library, path)
    # Simulate the pre-ledger schema's document rows in this owned database.
    for table in ('source_lifecycle_events', 'source_lifecycle_revisions', 'source_lifecycle_sources', 'source_lifecycle_roots'):
        db.execute('DELETE FROM ' + table)
    path.unlink()
    scan(library)
    assert availability(doc_id)['availability'] == 'missing'
    assert observed('api_retrieve', 'amber.retained', db) == []
    history = revisions(doc_id)
    assert history and history[0]['raw_bytes'] is None
    assert 'amber.retained' in history[0]['indexed_body']


def test_untracked_governed_path_cannot_be_replaced_by_a_different_explicit_id(owned):
    library, db = owned
    from app.services.indexer import index_file
    def content(doc_id):
        header = {'boh': {'id': doc_id, 'type': 'note', 'purpose': 'Governed identity', 'status': 'draft',
                         'updated': '2026-10-21T12:00:00+00:00',
                         'rubrix': {'operator_state': 'observe', 'operator_intent': 'capture'}}}
        return ('---\n' + json.dumps(header) + '\n---\n# Source\n\nOriginal.\n').encode()
    path = write(library, raw=content('governed-original'))
    index(library, path)
    for table in ('source_lifecycle_events', 'source_lifecycle_revisions', 'source_lifecycle_sources', 'source_lifecycle_roots'):
        db.execute('DELETE FROM ' + table)
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', ('governed-original',))
    path.write_bytes(content('different-incoming'))
    assert not index_file(path, library)['indexed']
    assert db.fetchone('SELECT COUNT(*) AS n FROM docs')['n'] == 1
    assert db.fetchone('SELECT * FROM docs WHERE doc_id=?', ('governed-original',)) == stored


def test_unavailable_file_identity_refuses_hash_only_rename(owned):
    library, db = owned
    path = write(library)
    old_id = index(library, path)
    db.execute("UPDATE source_lifecycle_sources SET inode='0' WHERE doc_id=?", (old_id,))
    path.rename(library / 'operations/new-name.md')
    result = scan(library)
    assert result['source_lifecycle']['renamed'] == 0
    assert db.fetchone('SELECT COUNT(*) AS n FROM docs')['n'] == 2
    assert availability(old_id)['availability'] == 'missing'


def test_changed_inventory_does_not_retire_absent_records(owned, monkeypatch):
    library, db = owned
    from app.core import autoindex
    doc_id = index(library, write(library))
    original = autoindex.discover_inventory
    calls = 0
    def changed(*args, **kwargs):
        nonlocal calls
        calls += 1
        result = original(*args, **kwargs)
        if calls == 2:
            result['manifest'] = []
        return result
    monkeypatch.setattr(autoindex, 'discover_inventory', changed)
    result = scan(library)
    assert result['source_lifecycle']['scan_complete'] is False
    assert availability(doc_id)['availability'] == 'unknown'
    assert db.fetchone('SELECT state FROM source_lifecycle_sources WHERE doc_id=?', (doc_id,))['state'] == 'present'


def test_overlapping_scan_tokens_fail_closed(owned):
    library, db = owned
    from app.core import source_lifecycle
    doc_id = index(library, write(library))
    first = source_lifecycle.begin_scan(library)
    source_lifecycle.begin_scan(library)
    with pytest.raises(ValueError):
        source_lifecycle.finish_scan(library, first, set(), True, 'complete', lambda path: True)
    assert availability(doc_id)['availability'] == 'unknown'
    assert db.fetchone('SELECT state FROM source_lifecycle_sources WHERE doc_id=?', (doc_id,))['state'] == 'present'


def test_failed_card_refresh_cannot_reexpose_previous_source_text(owned, monkeypatch):
    library, db = owned
    from app.core import plane_card
    path = write(library)
    doc_id = index(library, path)
    previous = db.fetchone('SELECT payload_json FROM cards WHERE doc_id=?', (doc_id,))
    def failed_refresh(*args, **kwargs):
        raise RuntimeError('owned projection refresh failure')
    monkeypatch.setattr(plane_card, 'wrap_and_persist', failed_refresh)
    path.write_bytes(b'# New source\n\nMarker amber.fresh is the replacement observation.\n')
    assert index(library, path) == doc_id
    assert db.fetchone('SELECT payload_json FROM cards WHERE doc_id=?', (doc_id,)) == previous
    assert observed('api_retrieve', 'amber.retained', db) == []
    assert observed('api_retrieve', 'amber.fresh', db)

def observed(surface, query, db):
    # Same lifecycle assertions, direct public surfaces; no private adapter/harness.
    from app.core import retrieval, current_context_brief, context_object, search
    if surface == 'api_retrieve':
        response = retrieval.retrieve_governed(query, mode='exploration', limit=5, filters={}, include_promoted=False)
    elif surface == 'current_context_brief':
        response = current_context_brief.build_current_context_brief(query, mode='exploration', limit=5, filters={}, include_promoted=False)
    elif surface == 'query_context_object':
        response = context_object.assemble('query', query, evidence_limit=5, filters={}, include_promoted=False, question_type='exploratory')
    elif surface == 'keyword_search':
        response = search.search(query, limit=5)
    else:
        raise ValueError('unsupported public surface')
    assert isinstance(response, (dict, list))
    assert not isinstance(response, dict) or not response.get('error'), response
    rows = historical._ranked_items(surface, response)
    ids = {r['doc_id'] for r in db.fetchall('SELECT doc_id FROM docs')}
    assert all(row['doc_id'] in ids for row in rows)
    return [{'source_id':row['doc_id'],'chunk_id':row.get('chunk_id')} for row in rows]
