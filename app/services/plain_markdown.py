"""Derived metadata for native Markdown; source files are never rewritten."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import stat
import uuid

MODE = 'plain_markdown_intake_v0_1'


class PlainMarkdownError(ValueError):
    """Admission failed before any index mutation."""


def read_source(path: Path, root: Path):
    """Read a regular, unlinked UTF-8 Markdown file inside the named root."""
    try:
        relative = path.absolute().relative_to(root.absolute())
        if '..' in relative.parts:
            raise PlainMarkdownError('PLAIN_MARKDOWN_PATH: traversal is not allowed')
        path.resolve().relative_to(root.resolve())
        current = root.absolute()
        info = None
        for part in relative.parts:
            current = current / part
            info = current.lstat()
            if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                raise PlainMarkdownError('PLAIN_MARKDOWN_PATH: linked/reparse sources are not admitted')
        if info is None or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise PlainMarkdownError('PLAIN_MARKDOWN_PATH: source must be a regular, unlinked file')
        raw = path.read_bytes()
        after = path.stat()
        if (info.st_size, info.st_mtime_ns, info.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
            raise PlainMarkdownError('PLAIN_MARKDOWN_CHANGED: source changed during read')
        text = raw.decode('utf-8')
        if any((ord(c) < 32 and c not in '\t\r\n') or ord(c) == 127 for c in text):
            raise PlainMarkdownError('PLAIN_MARKDOWN_BINARY: unsupported control bytes')
        return raw, text, info
    except PlainMarkdownError:
        raise
    except UnicodeDecodeError as exc:
        raise PlainMarkdownError('PLAIN_MARKDOWN_ENCODING: UTF-8 codec error') from exc
    except FileNotFoundError as exc:
        raise PlainMarkdownError('PLAIN_MARKDOWN_MISSING: source file is missing; retained index is unchanged') from exc
    except (OSError, ValueError) as exc:
        raise PlainMarkdownError('PLAIN_MARKDOWN_PATH: source is unreadable or outside the library root') from exc


def _provenance(row):
    try:
        value = json.loads(row.get('provenance_json') or '{}')
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def derive_metadata(relative: str, raw: bytes, text: str, info, raw_header: dict, errors: list[str], db):
    """Defaults are explicit policy, never authority inferred from source prose."""
    if not text.removeprefix('\ufeff').strip():
        raise PlainMarkdownError('PLAIN_MARKDOWN_EMPTY: source has no text')
    if 'boh' in raw_header:
        raise PlainMarkdownError('PLAIN_MARKDOWN_METADATA: explicit invalid BOH metadata is not a plain source')
    allowed = ('LINT_MISSING_HEADER:', 'LINT_MISSING_BOH_KEY:')
    if any(not error.startswith(allowed) for error in errors):
        raise PlainMarkdownError('PLAIN_MARKDOWN_METADATA: malformed YAML/header is not admitted')
    first_line = text.removeprefix('\ufeff').splitlines()[0].rstrip()
    if first_line == '---' and any(error.startswith('LINT_MISSING_HEADER:') for error in errors):
        raise PlainMarkdownError('PLAIN_MARKDOWN_METADATA: unclosed YAML frontmatter is not admitted')
    doc_id = 'plain-md-' + uuid.uuid5(uuid.NAMESPACE_URL, 'boh:plain-markdown:v0.1:' + relative).hex
    # A ledger-proven rename retains the original relative-path identity.
    renamed = db.fetchone('SELECT doc_id,origin_path FROM source_lifecycle_sources WHERE path=?', (relative,))
    if renamed:
        original_id = 'plain-md-' + uuid.uuid5(uuid.NAMESPACE_URL, 'boh:plain-markdown:v0.1:' + renamed['origin_path']).hex
        if renamed['doc_id'] == original_id:
            doc_id = original_id
    existing = db.fetchall('SELECT * FROM docs WHERE path=?', (relative,))
    if existing:
        row = existing[0]
        if len(existing) != 1 or row['doc_id'] != doc_id or _provenance(row).get('mode') != MODE:
            raise PlainMarkdownError('PLAIN_MARKDOWN_IDENTITY: existing governed identity requires an explicit migration')
        if (row.get('status'), row.get('authority_state'), row.get('canonical_layer'), row.get('review_state'), row.get('corpus_class')) != (
                'draft', 'non_authoritative', 'supporting', 'none', 'CORPUS_CLASS:DRAFT'):
            raise PlainMarkdownError('PLAIN_MARKDOWN_PROTECTED: curated/canonical/promoted state requires governed handling')
    collision = db.fetchone('SELECT path FROM docs WHERE doc_id=?', (doc_id,))
    if collision and collision['path'] != relative:
        raise PlainMarkdownError('PLAIN_MARKDOWN_IDENTITY: generated identity already belongs to another path')
    title = Path(relative).stem.replace('-', ' ').replace('_', ' ')
    for line in text.removeprefix('\ufeff').splitlines():
        match = re.match(r'^#{1,6}\s+(.+?)\s*#*\s*$', line)
        if match:
            title = match.group(1)
            break
    title = title[:120] or 'Untitled Markdown'
    digest = hashlib.sha256(raw).hexdigest()
    return {'id': doc_id, 'document_id': doc_id, 'type': 'note', 'document_class': 'note',
            'title': title, 'purpose': title, 'project': 'Plain Markdown Imports',
            'status': 'draft', 'authority_state': 'non_authoritative', 'canonical_layer': 'supporting',
            'review_state': 'none', 'version': '0.1.0', 'source_hash': digest,
            'updated': datetime.fromtimestamp(info.st_mtime, timezone.utc).isoformat(),
            'provenance': {'mode': MODE, 'source': relative, 'source_sha256': digest,
                           'source_size': len(raw), 'metadata_policy': 'derived_draft_defaults',
                           'foreign_frontmatter': bool(raw_header)},
            'scope': {'plane_scope': [], 'field_scope': [], 'node_scope': []}, 'topics': [],
            'rubrix': {'operator_state': 'observe', 'operator_intent': 'capture'}}


def guard_explicit_identity(relative: str, doc_id: str, db):
    """Do not orphan a native index when a source is manually given BOH metadata."""
    rows = db.fetchall('SELECT doc_id,provenance_json FROM docs WHERE path=?', (relative,))
    if any(_provenance(row).get('mode') == MODE and row['doc_id'] != doc_id for row in rows):
        raise PlainMarkdownError('PLAIN_MARKDOWN_IDENTITY: explicit metadata must retain the indexed document ID')
