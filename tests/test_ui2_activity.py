"""Tests for activity.js ICS export functionality."""

from __future__ import annotations

import importlib
from contextlib import contextmanager

from fastapi.testclient import TestClient


@contextmanager
def _client(tmp_path, monkeypatch):
    """Create a test client with isolated DB."""
    library = tmp_path / "library"
    library.mkdir()
    db_path = tmp_path / "boh.db"
    monkeypatch.setenv("BOH_LIBRARY", str(library))
    monkeypatch.setenv("BOH_DB", str(db_path))
    monkeypatch.setenv("BOH_OPERATOR_TOKEN", "test-token")

    import app.db.connection as db
    db.DB_PATH = str(db_path)
    db.init_db()
    import app.core.auth as auth
    import app.api.main as main
    importlib.reload(auth)
    importlib.reload(main)
    main.db.DB_PATH = str(db_path)
    main.db.init_db()
    with TestClient(main.app) as client:
        yield client


class TestActivityScreenICSExport:
    """Test suite for ICS calendar export from activity.js."""

    def test_ics_export_happy_path_returns_valid_rfc5545(self, tmp_path, monkeypatch):
        """Test GET /api/events/export.ics returns valid RFC 5545 format."""
        with _client(tmp_path, monkeypatch) as client:
            response = client.get("/api/events/export.ics")
            assert response.status_code == 200
            # Content-type should be text/plain or text/calendar
            content_type = response.headers.get("content-type", "").lower()
            assert "text" in content_type, f"Expected text/* content-type, got {content_type}"

            content = response.text
            # Validate RFC 5545 structure
            assert "BEGIN:VCALENDAR" in content
            assert "VERSION:2.0" in content
            assert "PRODID:-//Bag of Holding v2//EN" in content
            assert "END:VCALENDAR" in content
            assert "CALSCALE:GREGORIAN" in content
            assert "METHOD:PUBLISH" in content

    def test_ics_export_contains_valid_events_structure(self, tmp_path, monkeypatch):
        """Test ICS export contains properly formatted VEVENT blocks with required fields."""
        with _client(tmp_path, monkeypatch) as client:
            response = client.get("/api/events/export.ics")
            assert response.status_code == 200

            content = response.text
            lines = content.split("\r\n")

            # Verify structure is well-formed
            assert lines[0] == "BEGIN:VCALENDAR"
            assert lines[-1] == "END:VCALENDAR"

            # RFC 5545 requires VEVENT blocks to be balanced
            vevent_begin = content.count("BEGIN:VEVENT")
            vevent_end = content.count("END:VEVENT")
            assert vevent_begin == vevent_end, "Unbalanced VEVENT blocks"

            # If events exist, verify required VEVENT fields
            if "BEGIN:VEVENT" in content:
                assert "UID:" in content, "Missing UID field in VEVENT"
                assert "DTSTART:" in content, "Missing DTSTART field in VEVENT"
                assert "DTEND:" in content, "Missing DTEND field in VEVENT"
                assert "SUMMARY:" in content, "Missing SUMMARY field in VEVENT"
                assert "STATUS:" in content, "Missing STATUS field in VEVENT"

    def test_ics_export_response_plaintext_not_json(self, tmp_path, monkeypatch):
        """Test that ICS export returns plaintext response, not JSON, for browser download."""
        with _client(tmp_path, monkeypatch) as client:
            response = client.get("/api/events/export.ics")
            assert response.status_code == 200

            # Verify content type is text/calendar or text/plain, not application/json
            content_type = response.headers.get("content-type", "").lower()
            assert "json" not in content_type, f"Response should not be JSON, got {content_type}"

            # Verify response is NOT JSON-formatted
            assert not response.text.startswith("{"), "Response should not be JSON"

            # Verify it's plaintext ICS format
            assert response.text.startswith("BEGIN:VCALENDAR"), "Response should start with BEGIN:VCALENDAR"
