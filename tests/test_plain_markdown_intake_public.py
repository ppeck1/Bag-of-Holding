# Public subset: private-corpus/operator harness checks are retained privately.
"""Native source admission, update preservation and actual governed-consumer gates."""


import copy


import hashlib


import json


import os


from pathlib import Path


import pytest





from tools.probes import retrieval_quality_baseline_v0_1 as historical


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
    with historical._measurement_state(historical._epoch('2026-10-20T12:00:00+00:00')):
        yield library, db


def write(library, relative='notes/source.md', content=b'# Source\n\nNative scope is amber.read.\n'):
    target = library / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(content)
    os.utime(target, (1792497600, 1792497600))
    return target


def counts(db):
    return {table: db.fetchone(f'SELECT COUNT(*) AS n FROM {table}')['n'] for table in
            ('docs', 'docs_fts', 'doc_chunks', 'doc_chunks_fts', 'doc_chunk_embeddings', 'cards')}


@pytest.mark.parametrize('suffix', ['.md', '.markdown'])
@pytest.mark.parametrize('content', [
    b'# Native title\n\nPlain Markdown without a header.\n',
    '# Unicode café\n\nRésumé text with Unicode.\n'.encode(),
    b'# CRLF title\r\n\r\nFull source with Windows endings.\r\n',
    b'\xef\xbb\xbf# BOM title\n\nA UTF-8 BOM does not add authority.\n',
    b'---\ntitle: Untrusted title\nstatus: canonical\nauthority_state: approved\n---\n# Foreign metadata\n\nInert source.\n',
])
def test_native_bytes_and_non_authority_are_preserved(owned, suffix, content):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library, 'notes/source' + suffix, content)
    result = index_file(target, library)
    assert result['indexed'], result
    doc = db.fetchone('SELECT * FROM docs WHERE doc_id=?', (result['doc_id'],))
    digest = hashlib.sha256(content).hexdigest()
    assert (doc['status'], doc['authority_state'], doc['canonical_layer'], doc['review_state']) == ('draft', 'non_authoritative', 'supporting', 'none')
    assert doc['source_hash'] == doc['text_hash'] == digest
    assert doc['document_id'] == doc['doc_id']
    provenance = json.loads(doc['provenance_json'])
    assert provenance['mode'] == 'plain_markdown_intake_v0_1'
    assert provenance['source_sha256'] == digest and provenance['source'] == 'notes/source' + suffix
    assert target.read_bytes() == content
    assert db.fetchone('SELECT content FROM docs_fts WHERE path=?', (doc['path'],))['content'] == content.decode()
    chunks = db.fetchall('SELECT * FROM doc_chunks WHERE doc_id=?', (doc['doc_id'],))
    assert chunks and all(c['chunk_type'] != 'frontmatter' and c['source_hash'] == digest for c in chunks)
    card = db.fetchone('SELECT * FROM cards WHERE doc_id=?', (doc['doc_id'],))
    assert card and json.loads(card['payload_json'])['non_authoritative'] is True


def test_reindex_keeps_identity_chunks_cards_and_complete_source(owned):
    library, db = owned
    from app.services.indexer import index_file
    content = b'# Long source\n\n' + b'An ordinary source line with useful evidence.\n' * 180 + b'\nTail marker amber.final.\n'
    target = write(library, content=content)
    first = index_file(target, library)
    assert first['indexed'], first
    before = counts(db)
    ids = db.fetchall('SELECT chunk_id FROM doc_chunks ORDER BY chunk_id')
    second = index_file(target, library)
    assert second['indexed'] and second['doc_id'] == first['doc_id']
    assert counts(db) == before and db.fetchall('SELECT chunk_id FROM doc_chunks ORDER BY chunk_id') == ids
    assert target.read_bytes() == content
    assert db.fetchone('SELECT content FROM docs_fts')['content'] == content.decode()
    from app.core.retrieval import retrieve_governed
    assert retrieve_governed('amber.final', mode='exploration')['context_packs']


def test_content_update_replaces_old_search_text_under_same_id(owned):
    library, db = owned
    from app.services.indexer import index_file
    from app.core.retrieval import retrieve_governed
    target = write(library, content=b'# Source\n\nOld marker amber.first.\n')
    first = index_file(target, library)
    assert first['indexed'], first
    write(library, content=b'# Source\n\nNew marker amber.second.\n')
    second = index_file(target, library)
    assert second['indexed'] and second['doc_id'] == first['doc_id']
    assert counts(db)['docs'] == counts(db)['cards'] == counts(db)['docs_fts'] == 1
    assert retrieve_governed('amber.first', mode='exploration')['context_packs'] == []
    assert {p['doc_id'] for p in retrieve_governed('amber.second', mode='exploration')['context_packs']} == {first['doc_id']}
    assert all('amber.first' not in r['text'] for r in db.fetchall('SELECT text FROM doc_chunks'))


def test_same_filename_in_distinct_folders_has_distinct_identity(owned):
    library, db = owned
    from app.services.indexer import index_file
    first = index_file(write(library, 'alpha/note.md'), library)
    second = index_file(write(library, 'beta/note.md'), library)
    assert first['indexed'] and second['indexed']
    assert first['doc_id'] != second['doc_id'] and counts(db)['docs'] == 2


@pytest.mark.parametrize('content', [b'', b' \r\n\t', b'# Binary\n\x00payload', b'# Invalid\n\xff',
    b'---\nboh: [unterminated\n---\nBody\n', b'---\nboh:\n  id: unfinished\n',
    b'---\n- a\n- b\n---\nBody\n', b'---\nboh: true\n---\nBody\n',
    b'---\nboh: {}\n---\nBody\n', b'---\nboh: null\n---\nBody\n'])
def test_malformed_empty_or_binary_source_rejected_without_db_writes(owned, content):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library, content=content)
    result = index_file(target, library)
    assert not result['indexed'] and result['lint_errors']
    assert all(n == 0 for n in counts(db).values())
    assert target.read_bytes() == content


@pytest.mark.parametrize('field,value', [('scope', 'not-a-map'), ('scope', ['not-a-map']),
                                        ('rubrix', 'not-a-map'), ('rubrix', ['not-a-map'])])
def test_malformed_nested_explicit_metadata_is_structured_rejection(owned, field, value):
    library, db = owned
    from app.services.indexer import index_file
    metadata = {'id': 'explicit-shape', 'type': 'note', 'purpose': 'Explicit source', 'status': 'draft',
                'updated': '2026-10-20T12:00:00+00:00',
                'rubrix': {'operator_state': 'observe', 'operator_intent': 'capture'}}
    metadata[field] = value
    content = ('---\n' + json.dumps({'boh': metadata}) + '\n---\n# Source\n').encode()
    result = index_file(write(library, content=content), library)
    assert not result['indexed'] and result['lint_errors']
    assert all(n == 0 for n in counts(db).values())


def test_incomplete_explicit_metadata_keeps_legacy_lint_path_without_plain_defaults(owned):
    library, db = owned
    from app.services.indexer import index_file
    result = index_file(write(library, content=b'---\nboh:\n  id: legacy-explicit\n---\n# Source\n'), library)
    assert result['indexed'] and result['lint_errors']
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', ('legacy-explicit',))
    assert stored and json.loads(stored['provenance_json']).get('mode') != 'plain_markdown_intake_v0_1'
    assert stored['project'] != 'Plain Markdown Imports'


@pytest.mark.parametrize('replacement', [None, b'', b'\x00binary', b'---\nboh: [bad\n---\n'])
def test_invalid_or_missing_update_retains_last_indexed_snapshot(owned, replacement):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library)
    first = index_file(target, library)
    assert first['indexed'], first
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', (first['doc_id'],))
    before = counts(db)
    if replacement is None:
        target.unlink()  # Only this test-owned source; production intake never deletes it.
    else:
        target.write_bytes(replacement)
    failed = index_file(target, library)
    assert not failed['indexed'] and failed['lint_errors']
    assert failed['path'] == 'notes/source.md'
    assert counts(db) == before and db.fetchone('SELECT * FROM docs WHERE doc_id=?', (first['doc_id'],)) == stored


@pytest.mark.parametrize('status,authority,corpus', [
    ('canonical', 'canonical', 'CORPUS_CLASS:CANON'), ('draft', 'approved', 'CORPUS_CLASS:DRAFT'),
    ('draft', 'draft', 'CORPUS_CLASS:PROMOTED_INTAKE'), ('draft', 'draft', 'CORPUS_CLASS:DRAFT')])
def test_plain_file_cannot_replace_existing_governed_identity(owned, status, authority, corpus):
    library, db = owned
    from app.services.indexer import index_file
    template, _ = historical.load_deck(historical.default_deck_path())
    document = copy.deepcopy(template['documents'][0])
    document.update(doc_id='existing-governed', path='notes/source.md', status=status, authority_state=authority, corpus_class=corpus)
    historical._seed_fixture({'deck_id': 'existing-governed-control', 'documents': [document]}, db)
    stored = db.fetchone('SELECT * FROM docs WHERE doc_id=?', ('existing-governed',))
    before = counts(db)
    result = index_file(write(library), library)
    assert not result['indexed'] and result['lint_errors']
    assert counts(db) == before and db.fetchone('SELECT * FROM docs WHERE doc_id=?', ('existing-governed',)) == stored


def test_generated_identity_collision_fails_closed(owned):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library)
    first = index_file(target, library)
    assert first['indexed'], first
    db.execute('UPDATE docs SET path=? WHERE doc_id=?', ('other/source.md', first['doc_id']))
    before = counts(db)
    result = index_file(target, library)
    assert not result['indexed'] and counts(db) == before


@pytest.mark.parametrize('change', [{'status': 'canonical'}, {'authority_state': 'approved'}, {'review_state': 'pending'}])
def test_curated_native_record_is_not_silently_reset_by_reindex(owned, change):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library)
    first = index_file(target, library)
    assert first['indexed']
    key, value = next(iter(change.items()))
    db.execute(f'UPDATE docs SET {key}=? WHERE doc_id=?', (value, first['doc_id']))
    before = db.fetchone('SELECT * FROM docs WHERE doc_id=?', (first['doc_id'],))
    result = index_file(target, library)
    assert not result['indexed']
    assert db.fetchone('SELECT * FROM docs WHERE doc_id=?', (first['doc_id'],)) == before


@pytest.mark.parametrize('retain_id', [False, True])
def test_manual_boh_metadata_conversion_must_retain_native_identity(owned, retain_id):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library)
    first = index_file(target, library)
    assert first['indexed']
    incoming = first['doc_id'] if retain_id else 'different-explicit-id'
    header = {'boh': {'id': incoming, 'title': 'Explicit source', 'purpose': 'Explicit source', 'type': 'note',
                     'status': 'draft', 'version': '0.1.0', 'updated': '2026-10-20T12:00:00+00:00',
                     'rubrix': {'operator_state': 'observe', 'operator_intent': 'capture'}}}
    target.write_bytes(('---\n' + json.dumps(header) + '\n---\n# Explicit source\n\nBody.\n').encode())
    result = index_file(target, library)
    assert result['indexed'] is retain_id
    assert counts(db)['docs'] == 1
    assert db.fetchone('SELECT doc_id FROM docs')['doc_id'] == first['doc_id']


def test_source_changed_during_read_rejects_before_index_mutation(owned, monkeypatch):
    library, db = owned
    from app.services.indexer import index_file
    target = write(library)
    original = Path.read_bytes
    def changed_read(path):
        raw = original(path)
        if path == target:
            target.write_bytes(b'# Deliberate concurrent update\n')
        return raw
    monkeypatch.setattr(Path, 'read_bytes', changed_read)
    result = index_file(target, library)
    assert not result['indexed'] and 'CHANGED' in result['lint_errors'][0]
    assert all(n == 0 for n in counts(db).values())


def test_identity_depends_on_relative_path_not_physical_root(owned, tmp_path):
    library, db = owned
    from app.services.indexer import index_file
    first = index_file(write(library), library)
    assert first['indexed']
    other = tmp_path / 'other-owned-library'
    other.mkdir()
    second = index_file(write(other), other)
    assert second['indexed'] and second['doc_id'] == first['doc_id']
    assert counts(db)['docs'] == 1


def test_hard_link_and_outside_root_are_not_admitted(owned, tmp_path):
    library, db = owned
    from app.services.indexer import index_file
    outside = tmp_path / 'outside.md'
    outside.write_bytes(b'# Owned outside canary\n')
    linked = library / 'linked.md'
    os.link(outside, linked)
    for path in (outside, linked):
        result = index_file(path, library)
        assert not result['indexed'] and result['lint_errors']
    assert all(n == 0 for n in counts(db).values())


def test_autoindex_uses_raw_hash_to_skip_unchanged_native_file(owned):
    library, db = owned
    from app.core.autoindex import run_auto_index
    target = write(library)
    first = run_auto_index(str(library))
    second = run_auto_index(str(library))
    assert first['indexed'] == 1 and first['failed'] == 0
    assert second['indexed'] == 0 and second['skipped'] == 1 and second['failed'] == 0
    assert db.fetchone('SELECT text_hash FROM docs')['text_hash'] == hashlib.sha256(target.read_bytes()).hexdigest()


@pytest.mark.parametrize('content', [b'', b'\x00binary', b'---\nboh: {}\n---\nBody\n'])
def test_autoindex_reports_rejected_admission_as_failure(owned, content):
    library, db = owned
    from app.core.autoindex import run_auto_index
    write(library, content=content)
    result = run_auto_index(str(library))
    assert result['indexed'] == 0 and result['failed'] == 1
    assert result['manifest'][0]['action'] == 'failed'
    assert all(n == 0 for n in counts(db).values())


class _EmptyIntakeIndex:
    def fetchone(self, *args):
        return None

    def fetchall(self, *args):
        return []


@pytest.mark.parametrize('raw', [
    b'    ---\n    title: Foreign\n    ---\n\n    # Indented source\n\nUseful evidence.\n',
    b'\t---\n\ttitle: Foreign\n\t---\n\n# Tabbed source\n\nUseful evidence.\n',
    b'    ---\n    boh:\n      status: canonical\n      authority_state: approved\n    ---\n\n# Inert code\n',
])
def test_indented_delimiter_is_inert_plain_body(tmp_path, raw):
    from app.services.parser import parse_frontmatter_full
    from app.services.plain_markdown import derive_metadata

    path = tmp_path/'source.md'
    path.write_bytes(raw)
    _, header, _, errors = parse_frontmatter_full(raw.decode())
    metadata = derive_metadata('notes/source.md', raw, raw.decode(), path.stat(), header, errors, _EmptyIntakeIndex())
    assert (metadata['status'], metadata['authority_state'], metadata['canonical_layer'], metadata['review_state']) == (
        'draft', 'non_authoritative', 'supporting', 'none')
    assert metadata['source_hash'] == hashlib.sha256(raw).hexdigest()
    assert path.read_bytes() == raw


@pytest.mark.parametrize('opening', [b'---', b'---   '])
def test_column_zero_unclosed_frontmatter_still_rejected(tmp_path, opening):
    from app.services.parser import parse_frontmatter_full
    from app.services.plain_markdown import PlainMarkdownError, derive_metadata

    raw = opening+b'\ntitle: broken\n# Unclosed source\n'
    path = tmp_path/'source.md'
    path.write_bytes(raw)
    _, header, _, errors = parse_frontmatter_full(raw.decode())
    with pytest.raises(PlainMarkdownError, match='unclosed YAML'):
        derive_metadata('notes/source.md', raw, raw.decode(), path.stat(), header, errors, _EmptyIntakeIndex())
