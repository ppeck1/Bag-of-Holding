"""events.py: Event management and ICS export for Bag of Holding v0P."""

import time
from datetime import datetime, timezone

import db


def list_events(doc_id: str = None) -> list[dict]:
    if doc_id:
        return db.fetchall("SELECT * FROM events WHERE doc_id = ? ORDER BY start_ts", (doc_id,))
    return db.fetchall("SELECT * FROM events ORDER BY start_ts")


def epoch_to_ics_dt(ts: int | None, tz: str = "UTC") -> str:
    if not ts:
        return ""
    dt = datetime.fromtimestamp(ts, tz=timezone.utc)
    return dt.strftime("%Y%m%dT%H%M%SZ")


def export_ics(doc_id: str = None) -> str:
    """Export events as ICS string."""
    events = list_events(doc_id)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//Bag of Holding v0P//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
    ]
    for ev in events:
        dtstart = epoch_to_ics_dt(ev.get("start_ts"))
        dtend = epoch_to_ics_dt(ev.get("end_ts")) or dtstart
        if not dtstart:
            continue
        lines += [
            "BEGIN:VEVENT",
            f"UID:{ev['event_id']}@boh",
            f"DTSTART:{dtstart}",
            f"DTEND:{dtend}",
            f"SUMMARY:{ev.get('doc_id', 'Event')}",
            f"STATUS:{(ev.get('status') or 'CONFIRMED').upper()}",
            "END:VEVENT",
        ]
    lines.append("END:VCALENDAR")
    return "\r\n".join(lines)
