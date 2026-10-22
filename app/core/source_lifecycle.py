"""Durable observations and conservative current-source eligibility.

Source observations never approve authority. Reads do not touch source files.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import stat
import time
import uuid

from app.db import connection as db


def initialize(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS source_lifecycle_roots (
            root_key TEXT PRIMARY KEY, root_path TEXT NOT NULL,
            scan_state TEXT NOT NULL, scan_id TEXT, observed_at INTEGER NOT NULL,
            completed_at INTEGER, reason TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS source_lifecycle_sources (
            doc_id TEXT PRIMARY KEY, root_key TEXT NOT NULL REFERENCES source_lifecycle_roots(root_key),
            path TEXT NOT NULL, origin_path TEXT NOT NULL, state TEXT NOT NULL,
            source_hash TEXT NOT NULL DEFAULT '', device TEXT NOT NULL DEFAULT '',
            inode TEXT NOT NULL DEFAULT '', source_size INTEGER, observed_at INTEGER,
            reason TEXT NOT NULL DEFAULT '', UNIQUE(root_key,path)
        );
        CREATE TABLE IF NOT EXISTS source_lifecycle_revisions (
            revision_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL, path TEXT NOT NULL,
            source_hash TEXT NOT NULL, observed_at INTEGER NOT NULL,
            raw_bytes BLOB, indexed_body TEXT NOT NULL, snapshot_json TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_source_lifecycle_revisions_doc ON source_lifecycle_revisions(doc_id);
        CREATE TABLE IF NOT EXISTS source_lifecycle_events (
            event_id INTEGER PRIMARY KEY, root_key TEXT NOT NULL REFERENCES source_lifecycle_roots(root_key),
            doc_id TEXT, kind TEXT NOT NULL, observed_at INTEGER NOT NULL, detail_json TEXT NOT NULL
        );
    """)


def root_identity(root):
    path = str(Path(root).absolute())
    return hashlib.sha256(os.path.normcase(path).encode('utf-8')).hexdigest(), path


def _root(conn, root):
    key, path = root_identity(root)
    conn.execute("INSERT OR IGNORE INTO source_lifecycle_roots(root_key,root_path,scan_state,observed_at) VALUES(?,?,'observed',?)",
                 (key, path, int(time.time())))
    return key


def _event(conn, key, kind, doc_id=None, **detail):
    conn.execute('INSERT INTO source_lifecycle_events(root_key,doc_id,kind,observed_at,detail_json) VALUES(?,?,?,?,?)',
                 (key, doc_id, kind, int(time.time()), json.dumps(detail, sort_keys=True)))


def observe_file(path, root):
    """Read a stable regular file beneath an unlinked root, without decoding it."""
    path, root = Path(path).absolute(), Path(root).absolute()
    relative = path.relative_to(root)
    if '..' in relative.parts:
        raise ValueError('SOURCE_PATH: traversal is not admitted')
    path.resolve().relative_to(root.resolve())
    current = root
    for part in (None, *relative.parts):
        if part is not None:
            current = current / part
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
            raise ValueError('SOURCE_PATH: linked/reparse source is not admitted')
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise ValueError('SOURCE_PATH: source must be a regular unlinked file')
    raw = path.read_bytes()
    after = path.stat()
    signature = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns)
    if signature(info) != signature(after):
        raise ValueError('SOURCE_CHANGED: source changed during observation')
    return {'raw': raw, 'hash': hashlib.sha256(raw).hexdigest(), 'info': signature(info),
            'device': str(info.st_dev), 'inode': str(info.st_ino), 'size': info.st_size,
            'path': relative.as_posix()}


def _superseded(doc_id):
    return f"""EXISTS(SELECT 1 FROM lineage sl JOIN docs successor ON successor.doc_id =
        CASE WHEN sl.relationship='supersedes' THEN sl.doc_id ELSE sl.related_doc_id END
        WHERE (sl.related_doc_id={doc_id} AND sl.relationship='supersedes')
           OR (sl.doc_id={doc_id} AND sl.relationship IN ('superseded_by','superseded')))"""


def current_clause(doc_id='d.doc_id'):
    """Apply before candidate LIMIT; untracked legacy rows retain their contract."""
    return f""" AND NOT EXISTS(SELECT 1 FROM source_lifecycle_sources ls
        JOIN source_lifecycle_roots lr ON lr.root_key=ls.root_key
        WHERE ls.doc_id={doc_id} AND (ls.state!='present' OR lr.scan_state NOT IN ('observed','complete')
        OR {_superseded(doc_id)}))"""


def card_clause(alias='card'):
    """A stale source-derived cache cannot stand in for its newer backing row."""
    return f""" AND NOT EXISTS(SELECT 1 FROM source_lifecycle_sources cs
        JOIN docs cd ON cd.doc_id=cs.doc_id WHERE cs.doc_id={alias}.doc_id
        AND ({alias}.card_type='source_document' OR
            json_extract({alias}.context_ref_json,'$.source_id')='DOC:boh:'||cd.doc_id)
        AND (COALESCE(json_extract({alias}.payload_json,'$.title'),'')!=COALESCE(cd.title,'')
            OR COALESCE(json_extract({alias}.payload_json,'$.summary'),'')!=substr(COALESCE(cd.summary,''),1,220)
            OR COALESCE(json_extract({alias}.payload_json,'$.path'),'')!=cd.path
            OR (COALESCE(json_extract({alias}.payload_json,'$.text'),'')!='' AND NOT EXISTS(
                SELECT 1 FROM source_lifecycle_revisions cr WHERE cr.doc_id=cd.doc_id
                AND cr.path=cd.path AND cr.source_hash=cs.source_hash AND cr.raw_bytes IS NOT NULL
                AND instr(cr.indexed_body,json_extract({alias}.payload_json,'$.text'))>0))))"""


def payload_sql(doc_id='d.doc_id'):
    return f"""(SELECT json_object('availability', CASE WHEN ls.state='present' AND
        lr.scan_state NOT IN ('observed','complete') THEN 'unknown' ELSE ls.state END,
        'observation_state',ls.state,'root_scan_state',lr.scan_state,
        'reason',CASE WHEN ls.state='present' AND lr.scan_state NOT IN ('observed','complete')
            THEN 'root_scan_uncertain' ELSE ls.reason END,
        'observed_at',ls.observed_at,'source_hash',ls.source_hash,'path',ls.path,
        'superseded',CASE WHEN {_superseded(doc_id)} THEN 1 ELSE 0 END,
        'superseded_by',(SELECT successor.doc_id FROM lineage sl JOIN docs successor ON successor.doc_id=
            CASE WHEN sl.relationship='supersedes' THEN sl.doc_id ELSE sl.related_doc_id END
            WHERE (sl.related_doc_id={doc_id} AND sl.relationship='supersedes')
               OR (sl.doc_id={doc_id} AND sl.relationship IN ('superseded_by','superseded'))
            ORDER BY sl.detected_ts DESC,sl.id DESC LIMIT 1),
        'current_evidence',CASE WHEN ls.state='present' AND lr.scan_state IN ('observed','complete')
            AND NOT {_superseded(doc_id)} THEN 1 ELSE 0 END)
        FROM source_lifecycle_sources ls JOIN source_lifecycle_roots lr ON lr.root_key=ls.root_key
        WHERE ls.doc_id={doc_id})"""


def decode_status(value):
    if not value:
        return {'availability': 'untracked', 'current_evidence': None, 'superseded': False,
                'reason': 'no_source_observation', 'observed_at': None}
    result = json.loads(value) if isinstance(value, str) else dict(value)
    result['superseded'] = bool(result['superseded'])
    result['current_evidence'] = bool(result['current_evidence'])
    return result


def get_status(doc_id):
    row = db.fetchone('SELECT ' + payload_sql('d.doc_id') + ' AS state FROM (SELECT ? AS doc_id) d', (doc_id,))
    return decode_status(row['state'])


def get_revisions(doc_id):
    """Explicit trusted-local history read; never used as default answer evidence."""
    return db.fetchall('SELECT revision_id,doc_id,path,source_hash,observed_at,raw_bytes,indexed_body,snapshot_json '
                       'FROM source_lifecycle_revisions WHERE doc_id=? ORDER BY rowid', (doc_id,))


def _revision(conn, doc_id, path, source_hash, raw):
    document = conn.execute('SELECT * FROM docs WHERE doc_id=?', (doc_id,)).fetchone()
    body = conn.execute('SELECT content FROM docs_fts WHERE path=?', (path,)).fetchone()
    chunks = conn.execute('SELECT * FROM doc_chunks WHERE doc_id=? ORDER BY chunk_index', (doc_id,)).fetchall()
    revision_id = hashlib.sha256((doc_id + '\0' + source_hash + '\0' + path + ('\0raw' if raw is not None else '\0legacy')).encode()).hexdigest()
    snapshot = {'document': dict(document), 'chunks': [dict(row) for row in chunks], 'raw_observed': raw is not None}
    conn.execute('INSERT OR IGNORE INTO source_lifecycle_revisions VALUES(?,?,?,?,?,?,?,?)',
                 (revision_id, doc_id, path, source_hash, int(time.time()), raw,
                  body['content'] if body else '', json.dumps(snapshot, sort_keys=True)))
    return revision_id


def guard_identity(doc_id, root, observation):
    existing_paths = db.fetchall('SELECT doc_id FROM docs WHERE path=?', (observation['path'],))
    if any(item['doc_id'] != doc_id for item in existing_paths):
        raise ValueError('SOURCE_IDENTITY: indexed path already belongs to another governed identity')
    row = db.fetchone('SELECT * FROM source_lifecycle_sources WHERE doc_id=?', (doc_id,))
    if row and row['path'] != observation['path']:
        raise ValueError('SOURCE_IDENTITY: existing document belongs to another path; confirmed reconciliation is required')
    if row and row['root_key'] != root_identity(root)[0] and row['source_hash'] != observation['hash']:
        raise ValueError('SOURCE_IDENTITY: physical-root rebind requires identical source bytes')
    collision = db.fetchone('SELECT doc_id FROM source_lifecycle_sources WHERE root_key=? AND path=?',
                            (root_identity(root)[0], observation['path']))
    if collision and collision['doc_id'] != doc_id:
        raise ValueError('SOURCE_IDENTITY: path is bound to another document')


def record_success(conn, doc_id, path, root, raw, observation):
    after = Path(path).stat()
    if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) != observation['info'] or raw != observation['raw']:
        raise ValueError('SOURCE_CHANGED: source changed before index commit')
    key = _root(conn, root)
    old = conn.execute('SELECT origin_path FROM source_lifecycle_sources WHERE doc_id=?', (doc_id,)).fetchone()
    origin = old['origin_path'] if old else observation['path']
    conn.execute('''INSERT INTO source_lifecycle_sources
        (doc_id,root_key,path,origin_path,state,source_hash,device,inode,source_size,observed_at,reason)
        VALUES(?,?,?,?,'present',?,?,?,?,?,'observed') ON CONFLICT(doc_id) DO UPDATE SET
        root_key=excluded.root_key,path=excluded.path,state='present',source_hash=excluded.source_hash,
        device=excluded.device,inode=excluded.inode,source_size=excluded.source_size,
        observed_at=excluded.observed_at,reason='observed' ''',
        (doc_id, key, observation['path'], origin, observation['hash'], observation['device'],
         observation['inode'], observation['size'], int(time.time())))
    revision_id = _revision(conn, doc_id, observation['path'], observation['hash'], raw)
    _event(conn, key, 'observed', doc_id, path=observation['path'], revision_id=revision_id)


def note_failure(path, root, reason):
    try:
        relative = Path(path).absolute().relative_to(Path(root).absolute()).as_posix()
        if '..' in Path(relative).parts:
            return
    except ValueError:
        return
    key = root_identity(root)[0]
    row = db.fetchone('SELECT doc_id FROM source_lifecycle_sources WHERE root_key=? AND path=?', (key, relative))
    if not row:
        return
    # Read/missing/path failures do not establish content invalidity or deletion.
    uncertain = any(word in reason.lower() for word in ('missing', 'not found', 'permission', 'path:', 'changed', 'unreadable'))
    state = 'unknown' if uncertain else 'invalid'
    conn = db.get_conn()
    try:
        conn.execute('UPDATE source_lifecycle_sources SET state=?,reason=? WHERE doc_id=?', (state, reason[:300], row['doc_id']))
        _event(conn, key, state, row['doc_id'], reason=reason[:300])
        conn.commit()
    finally:
        conn.close()


def begin_scan(root):
    conn = db.get_conn()
    try:
        key = _root(conn, root)
        scan_id = uuid.uuid4().hex
        conn.execute("UPDATE source_lifecycle_roots SET scan_state='scanning',scan_id=?,observed_at=?,reason='scan_in_progress' WHERE root_key=?",
                     (scan_id, int(time.time()), key))
        _event(conn, key, 'scan_started', scan_id=scan_id)
        conn.commit()
        return scan_id
    finally:
        conn.close()


def enroll_legacy(root, in_scope):
    """Explicit single-library scan enrollment; missing raw bytes stay unknown."""
    conn = db.get_conn()
    try:
        key = _root(conn, root)
        rows = conn.execute('SELECT * FROM docs WHERE doc_id NOT IN (SELECT doc_id FROM source_lifecycle_sources)').fetchall()
        for row in rows:
            path = row['path']
            if not in_scope(path):
                continue
            conn.execute("INSERT INTO source_lifecycle_sources(doc_id,root_key,path,origin_path,state,source_hash,reason) VALUES(?,?,?,?,'unknown',?,'legacy_unobserved')",
                         (row['doc_id'], key, path, path, row['source_hash'] or row['text_hash'] or ''))
            _revision(conn, row['doc_id'], path, row['source_hash'] or row['text_hash'] or '', None)
            _event(conn, key, 'legacy_enrolled', row['doc_id'], path=path)
        conn.commit()
    finally:
        conn.close()


def reobserve(path, root):
    observation = observe_file(path, root)
    row = db.fetchone('SELECT d.* FROM docs d JOIN source_lifecycle_sources s ON s.doc_id=d.doc_id WHERE s.root_key=? AND s.path=?',
                       (root_identity(root)[0], observation['path']))
    if not row:
        return False
    previous = db.fetchone('SELECT source_hash FROM source_lifecycle_sources WHERE doc_id=?', (row['doc_id'],))
    # Legacy enrollment may have a transformed text hash; only a known raw hash or
    # exact unchanged document hash is sufficient to skip an index operation.
    if observation['hash'] not in {previous['source_hash'], row['text_hash']}:
        return False
    conn = db.get_conn()
    try:
        record_success(conn, row['doc_id'], path, root, observation['raw'], observation)
        conn.commit()
    finally:
        conn.close()
    return True


def reconcile_renames(root, candidate_paths):
    key = root_identity(root)[0]
    rows = db.fetchall('SELECT s.* FROM source_lifecycle_sources s JOIN docs d ON d.doc_id=s.doc_id WHERE root_key=?', (key,))
    by_path = {row['path']: row for row in rows}
    absent = [row for row in rows if row['path'] not in candidate_paths and not (Path(root) / row['path']).exists()]
    observations = {}
    for relative in sorted(set(candidate_paths) - set(by_path)):
        try:
            observations[relative] = observe_file(Path(root) / relative, root)
        except (OSError, ValueError):
            continue
    pairs = []
    for old in absent:
        if old['device'] in ('', '0') or old['inode'] in ('', '0'):
            continue
        matches = [(relative, ob) for relative, ob in observations.items()
                   if (ob['device'], ob['inode'], ob['hash']) == (old['device'], old['inode'], old['source_hash'])]
        if len(matches) == 1:
            pairs.append((old, *matches[0]))
    renamed = 0
    for old, relative, observation in pairs:
        if sum(pair[1] == relative for pair in pairs) != 1:
            continue
        if db.fetchone('SELECT doc_id FROM docs WHERE path=?', (relative,)):
            continue
        if (Path(root) / old['path']).exists():
            continue
        conn = db.get_conn()
        try:
            conn.execute('BEGIN IMMEDIATE')
            # Current paths change; historic source bytes/metadata remain immutable.
            conn.execute('UPDATE docs SET path=? WHERE doc_id=?', (relative, old['doc_id']))
            conn.execute('UPDATE docs_fts SET path=? WHERE path=?', (relative, old['path']))
            conn.execute('UPDATE doc_chunks SET path=? WHERE doc_id=?', (relative, old['doc_id']))
            for card in conn.execute('SELECT id,payload_json,context_ref_json FROM cards WHERE doc_id=?', (old['doc_id'],)).fetchall():
                payload, context = json.loads(card['payload_json'] or '{}'), json.loads(card['context_ref_json'] or '{}')
                payload['path'] = relative
                if isinstance(context, dict) and 'path' in context:
                    context['path'] = relative
                conn.execute('UPDATE cards SET payload_json=?,context_ref_json=? WHERE id=?',
                             (json.dumps(payload), json.dumps(context), card['id']))
            conn.execute('UPDATE source_lifecycle_sources SET path=? WHERE doc_id=?', (relative, old['doc_id']))
            record_success(conn, old['doc_id'], Path(root) / relative, root, observation['raw'], observation)
            _event(conn, key, 'renamed', old['doc_id'], previous_path=old['path'], path=relative)
            conn.commit()
            renamed += 1
        finally:
            conn.close()
    return renamed


def finish_scan(root, scan_id, seen_paths, complete, reason, in_scope):
    conn = db.get_conn()
    try:
        key = root_identity(root)[0]
        active = conn.execute('SELECT scan_id FROM source_lifecycle_roots WHERE root_key=?', (key,)).fetchone()
        if not active or active['scan_id'] != scan_id:
            if active:
                conn.execute("UPDATE source_lifecycle_roots SET scan_state='unknown',reason='concurrent_scan' WHERE root_key=?", (key,))
                _event(conn, key, 'scan_uncertain', scan_id=scan_id, reason='concurrent_scan')
                conn.commit()
            raise ValueError('SOURCE_SCAN: concurrent scan changed ownership')
        if complete:
            rows = conn.execute('SELECT * FROM source_lifecycle_sources WHERE root_key=?', (key,)).fetchall()
            for row in rows:
                if not in_scope(row['path']):
                    conn.execute("UPDATE source_lifecycle_sources SET state='unknown',reason='excluded_from_scan' WHERE doc_id=?", (row['doc_id'],))
                elif row['path'] not in seen_paths:
                    conn.execute("UPDATE source_lifecycle_sources SET state='missing',reason='absent_from_complete_scan' WHERE doc_id=?", (row['doc_id'],))
                    _event(conn, key, 'missing', row['doc_id'], path=row['path'], scan_id=scan_id)
        conn.execute('UPDATE source_lifecycle_roots SET scan_state=?,reason=?,completed_at=? WHERE root_key=?',
                     ('complete' if complete else 'unknown', reason, int(time.time()) if complete else None, key))
        _event(conn, key, 'scan_completed' if complete else 'scan_uncertain', scan_id=scan_id, reason=reason)
        conn.commit()
    finally:
        conn.close()
