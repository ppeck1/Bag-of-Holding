"""app/services/events.py: Event management and ICS export for Bag of Holding v2.

Phase 6: IC5 adapted — ICS SUMMARY now uses doc title (path basename) instead of doc_id.
"""

from datetime import datetime, timezone
from app.db import connection as db


def list_events(doc_id: str = None) -> list[dict]:
    """List all events, optionally filtered by doc_id. Ordered by start_ts."""
    if doc_id:
        return db.fetchall("SELECT * FROM events WHERE doc_id = ? ORDER BY start_ts", (doc_id,))
    return db.fetchall("SELECT * FROM events ORDER BY start_ts")


def epoch_to_ics_dt(ts: int | None) -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _get_event_summary(ev: dict) -> str:
    """IC5: Use doc path basename as SUMMARY; fall back to doc_id."""
    doc = db.fetchone("SELECT path FROM docs WHERE doc_id = ?", (ev.get("doc_id"),))
    if doc and doc.get("path"):
        import os
        return os.path.basename(doc["path"]).replace(".md", "")
    return ev.get("doc_id", "Event")


def export_ics(doc_id: str = None) -> str:
    """Export events as RFC 5545 ICS string."""
    events = list_events(doc_id)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Bag of Holding v2//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for ev in events:
        dtstart = epoch_to_ics_dt(ev.get("start_ts"))
        dtend   = epoch_to_ics_dt(ev.get("end_ts")) or dtstart
        if not dtstart:
            continue
        summary = _get_event_summary(ev)
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev['event_id']}@boh",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{summary}",
            f"STATUS:{(ev.get('status') or 'CONFIRMED').upper()}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
