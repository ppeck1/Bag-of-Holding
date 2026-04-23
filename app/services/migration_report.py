"""app/services/migration_report.py: Corpus migration report generator for Bag of Holding v2.

Generates docs/migration_report.md after a full index run.
Read-only — queries DB only, writes one markdown file.
See docs/corpus_migration_doctrine.md §8 (migration checklist).
"""

import time
from pathlib import Path

from app.db import connection as db
from app.core.corpus import get_class_distribution
from app.core.lineage import get_all_lineage


def generate_migration_report(output_path: str = "docs/migration_report.md") -> dict:
    """Query DB state and write a markdown migration report.

    Returns the report as a dict (also written to disk).
    """
    now_ts = int(time.time())
    now_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(now_ts))

    # Corpus class distribution
    class_dist = get_class_distribution()

    # Document counts by status
    status_rows = db.fetchall("SELECT status, COUNT(*) as count FROM docs GROUP BY status")
    status_dist = {r["status"]: r["count"] for r in status_rows}

    # Total docs
    total_docs = sum(class_dist.values())

    # Conflict summary
    conflicts = db.fetchall("SELECT conflict_type, acknowledged, COUNT(*) as count FROM conflicts GROUP BY conflict_type, acknowledged")
    open_conflicts = db.fetchall("SELECT * FROM conflicts WHERE acknowledged = 0 ORDER BY detected_ts DESC")
    ack_conflicts  = db.fetchall("SELECT * FROM conflicts WHERE acknowledged = 1")

    # Lineage summary
    lineage_rows = get_all_lineage(limit=500)
    lineage_by_type: dict[str, int] = {}
    for r in lineage_rows:
        lineage_by_type[r["relationship"]] = lineage_by_type.get(r["relationship"], 0) + 1

    # Docs with lint errors (no status = couldn't validate)
    no_status = db.fetchall("SELECT path FROM docs WHERE status IS NULL LIMIT 50")

    # Schema version
    schema_versions = db.fetchall("SELECT version, applied_ts FROM schema_version ORDER BY applied_ts")

    # Build markdown
    lines = [
        "# Corpus Migration Report — Bag of Holding v2",
        f"**Generated:** {now_str}",
        "",
        "---",
        "",
        "## 1. Corpus Class Distribution",
        "",
        "| Class | Count |",
        "|-------|-------|",
    ]
    for cls, count in sorted(class_dist.items()):
        lines.append(f"| `{cls}` | {count} |")
    lines.append(f"| **Total** | **{total_docs}** |")

    lines += [
        "",
        "## 2. Document Status Distribution",
        "",
        "| Status | Count |",
        "|--------|-------|",
    ]
    for status, count in sorted(status_dist.items(), key=lambda x: x[1], reverse=True):
        lines.append(f"| {status or 'null'} | {count} |")

    lines += [
        "",
        "## 3. Conflict Summary",
        "",
        f"- **Open conflicts:** {len(open_conflicts)}",
        f"- **Acknowledged conflicts:** {len(ack_conflicts)}",
        f"- **Total conflicts:** {len(open_conflicts) + len(ack_conflicts)}",
        "",
    ]
    if open_conflicts:
        lines += [
            "### Open Conflicts",
            "",
            "| Type | Term | Plane | Doc IDs |",
            "|------|------|-------|---------|",
        ]
        for c in open_conflicts[:20]:
            lines.append(
                f"| {c['conflict_type']} | {c['term'] or '—'} | {c['plane_path'] or '—'} | {(c['doc_ids'] or '')[:60]} |"
            )
        if len(open_conflicts) > 20:
            lines.append(f"| *(and {len(open_conflicts)-20} more…)* | | | |")

    lines += [
        "",
        "## 4. Lineage Summary",
        "",
        f"- **Total lineage records:** {len(lineage_rows)}",
        "",
        "| Relationship | Count |",
        "|-------------|-------|",
    ]
    for rel, count in sorted(lineage_by_type.items()):
        lines.append(f"| {rel} | {count} |")

    if no_status:
        lines += [
            "",
            "## 5. Documents with Validation Issues",
            "",
            "These documents have no `status` field (could not be fully validated):",
            "",
        ]
        for row in no_status:
            lines.append(f"- `{row['path']}`")

    lines += [
        "",
        "## 6. Schema Version History",
        "",
        "| Version | Applied |",
        "|---------|---------|",
    ]
    for sv in schema_versions:
        applied = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(sv["applied_ts"]))
        lines.append(f"| {sv['version']} | {applied} |")

    lines += [
        "",
        "## 7. Invariant Verification",
        "",
        "| Check | Result |",
        "|-------|--------|",
    ]

    # Run invariant checks
    checks = []

    # topics_tokens always lowercase
    bad_tokens = db.fetchone(
        "SELECT COUNT(*) as n FROM docs WHERE topics_tokens != '' AND topics_tokens != lower(topics_tokens)"
    )
    checks.append(("topics_tokens always lowercase", (bad_tokens["n"] == 0) if bad_tokens else True))

    # defs plane_scope_json always valid JSON
    import json
    defs_sample = db.fetchall("SELECT plane_scope_json FROM defs LIMIT 200")
    bad_json = sum(1 for d in defs_sample if not _is_valid_json_list(d["plane_scope_json"]))
    checks.append(("defs.plane_scope_json always valid JSON array", bad_json == 0))

    # No canonical doc in observe state
    bad_canon = db.fetchone(
        "SELECT COUNT(*) as n FROM docs WHERE status='canonical' AND operator_state='observe'"
    )
    checks.append(("No canonical doc in observe state", (bad_canon["n"] == 0) if bad_canon else True))

    # No archived doc not in release state
    bad_archived = db.fetchone(
        "SELECT COUNT(*) as n FROM docs WHERE status='archived' AND operator_state != 'release'"
    )
    checks.append(("All archived docs in release state", (bad_archived["n"] == 0) if bad_archived else True))

    for label, passed in checks:
        lines.append(f"| {label} | {'✓ PASS' if passed else '✗ FAIL'} |")

    lines += ["", "---", "", "*Report generated by Bag of Holding v2 migration_report.py*"]

    content = "\n".join(lines)

    # Write to disk
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")

    return {
        "generated_at": now_ts,
        "output_path": str(out),
        "total_docs": total_docs,
        "class_distribution": class_dist,
        "open_conflicts": len(open_conflicts),
        "lineage_records": len(lineage_rows),
        "invariants_passed": all(p for _, p in checks),
        "invariant_results": [{"check": l, "passed": p} for l, p in checks],
    }


def _is_valid_json_list(val: str) -> bool:
    try:
        import json
        return isinstance(json.loads(val), list)
    except Exception:
        return False
