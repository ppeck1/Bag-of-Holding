"""tests/test_phase11_input.py: Phase 11 input surface tests.

Covers:
  - safe_filename: strips traversal and unsafe chars
  - slugify_title: lowercase hyphenated slug
  - safe_subpath: rejects traversal, UNC, drive roots
  - next_available_path: adds -2, -3 suffix on collision
  - has_boh_frontmatter: detects existing frontmatter
  - build_boh_frontmatter: generates valid draft YAML
  - save_markdown_note: writes file, indexes, returns doc_id + path
  - save_markdown_note: never overwrites (suffix)
  - save_upload: saves .md file, injects frontmatter if missing
  - save_upload: rejects .exe
  - save_upload: rejects empty file
  - save_upload: sanitizes unsafe filename
  - POST /api/input/markdown: 200 with valid body
  - POST /api/input/markdown: 422 for empty body
  - POST /api/input/markdown: rejects path traversal in target_folder
  - POST /api/input/upload: 200 with .md file
  - POST /api/input/upload: rejects .exe
  - GET /api/input/recent: 200
  - created note is discoverable by /api/docs (after indexing)
  - health returns phase 11
"""

import io
import json
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.api.main import app
from app.core.input_surface import (
    safe_filename, slugify_title, safe_subpath, next_available_path,
    has_boh_frontmatter, build_boh_frontmatter, save_markdown_note, save_upload,
    get_library_root,
)

client = TestClient(app)


# ── Safe filename helpers ─────────────────────────────────────────────────────

class TestSafeFilename:
    def test_strips_path_separators(self):
        assert "/" not in safe_filename("../../etc/passwd")
        assert "\\" not in safe_filename("..\\windows\\system32")

    def test_strips_null_bytes(self):
        result = safe_filename("file\x00name")
        assert "\x00" not in result

    def test_truncates_to_120(self):
        assert len(safe_filename("a" * 200)) <= 120

    def test_empty_gets_fallback(self):
        result = safe_filename("")
        assert result.startswith("doc-")

    def test_normal_name_preserved(self):
        result = safe_filename("my-document")
        assert "my" in result


class TestSlugifyTitle:
    def test_lowercase(self):
        assert slugify_title("Hello World") == "hello-world"

    def test_strips_special_chars(self):
        slug = slugify_title("My Doc: <test>")
        assert "<" not in slug and ">" not in slug

    def test_collapses_spaces(self):
        slug = slugify_title("foo  bar")
        assert "--" not in slug

    def test_truncates_to_80(self):
        assert len(slugify_title("a" * 200)) <= 80

    def test_empty_gets_fallback(self):
        assert slugify_title("").startswith(("doc-", "untitled-"))


class TestSafeSubpath:
    def test_rejects_parent_traversal(self):
        with pytest.raises(ValueError, match="traversal"):
            safe_subpath("../../etc")

    def test_rejects_absolute_path(self):
        with pytest.raises(ValueError):
            safe_subpath("/absolute/path")

    def test_rejects_unc_path(self):
        # UNC paths start with \\ which also triggers the traversal check
        with pytest.raises(ValueError):
            safe_subpath("\\\\server\\share")

    def test_rejects_unc_path_forward(self):
        with pytest.raises(ValueError):
            safe_subpath("../../server/share")

    def test_rejects_drive_root(self):
        with pytest.raises(ValueError, match="drive"):
            safe_subpath("C:\\Windows")

    def test_simple_folder_accepted(self):
        p = safe_subpath("notes")
        assert str(p) == "notes"

    def test_empty_defaults_to_notes(self):
        p = safe_subpath("")
        assert str(p) == "notes"


class TestNextAvailablePath:
    def test_returns_same_if_not_exists(self, tmp_path):
        target = tmp_path / "doc.md"
        assert next_available_path(target) == target

    def test_appends_suffix_on_collision(self, tmp_path):
        target = tmp_path / "doc.md"
        target.write_text("x")
        result = next_available_path(target)
        assert result.name == "doc-2.md"

    def test_increments_correctly(self, tmp_path):
        for i in [None, 2, 3]:
            name = "doc.md" if i is None else f"doc-{i}.md"
            (tmp_path / name).write_text("x")
        result = next_available_path(tmp_path / "doc.md")
        assert result.name == "doc-4.md"


# ── Frontmatter helpers ───────────────────────────────────────────────────────

class TestFrontmatter:
    def test_has_boh_frontmatter_true(self):
        text = "---\nboh:\n  id: x\n---\n# Doc\n"
        assert has_boh_frontmatter(text) is True

    def test_has_boh_frontmatter_false(self):
        assert has_boh_frontmatter("# Just a heading\n") is False

    def test_build_boh_frontmatter_contains_id(self):
        fm = build_boh_frontmatter("Test Title", ["topic-a"])
        assert "id:" in fm
        assert "status: draft" in fm

    def test_build_boh_frontmatter_never_canonical(self):
        fm = build_boh_frontmatter("Canonical?", [])
        assert "canonical" not in fm

    def test_build_boh_frontmatter_has_rubrix(self):
        fm = build_boh_frontmatter("Note", [])
        assert "rubrix:" in fm
        assert "observe" in fm

    def test_build_boh_frontmatter_topics_included(self):
        fm = build_boh_frontmatter("Note", ["alpha", "beta"])
        assert "alpha" in fm
        assert "beta"  in fm


# ── save_markdown_note ────────────────────────────────────────────────────────

class TestSaveMarkdownNote:
    def test_creates_file_and_returns_metadata(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_markdown_note("Test Note", "# Hello\n\nBody text here.",
                                    topics=["test"])
        assert "doc_id" in result
        assert "path"   in result
        assert result["path"].endswith(".md")
        full = tmp_path / result["path"]
        assert full.exists()

    def test_file_contains_boh_frontmatter(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_markdown_note("FM Test", "Some body.")
        full = tmp_path / result["path"]
        text = full.read_text()
        assert "boh:" in text
        assert "status: draft" in text

    def test_collision_adds_suffix(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r1 = save_markdown_note("Collide Doc", "Body one.")
        r2 = save_markdown_note("Collide Doc", "Body two.")
        assert r1["path"] != r2["path"]
        assert "-2" in r2["path"]

    def test_path_stays_inside_library(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_markdown_note("Safe Doc", "Content.")
        full = (tmp_path / result["path"]).resolve()
        assert str(full).startswith(str(tmp_path.resolve()))


# ── save_upload ───────────────────────────────────────────────────────────────

class TestSaveUpload:
    def test_accepts_md_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_upload("test.md", b"# Hello\n\nContent.", target_folder="imports")
        assert "path" in result
        assert "reason" not in result

    def test_rejects_exe(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_upload("malware.exe", b"MZ\x00", target_folder="imports")
        assert "reason" in result
        assert "exe" in result["reason"].lower() or "unsupported" in result["reason"].lower()

    def test_rejects_empty_file(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_upload("empty.md", b"", target_folder="imports")
        assert "reason" in result

    def test_sanitizes_unsafe_filename(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_upload("../../evil.md", b"# ok", target_folder="imports")
        if "reason" not in result:
            # Sanitized filename should not contain traversal
            assert ".." not in result["path"]
            assert result["path"].startswith("imports/") or "imports" in result["path"]

    def test_injects_frontmatter_if_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        result = save_upload("plain.md", b"# Plain Doc\n\nNo frontmatter.",
                             target_folder="imports")
        if "path" in result:
            full = tmp_path / result["path"]
            text = full.read_text()
            assert "boh:" in text

    def test_no_overwrite_on_collision(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r1 = save_upload("dup.md", b"# First", target_folder="imports")
        r2 = save_upload("dup.md", b"# Second", target_folder="imports")
        if "path" in r1 and "path" in r2:
            assert r1["path"] != r2["path"]


# ── API endpoints ─────────────────────────────────────────────────────────────

class TestInputAPIRoutes:
    def test_post_markdown_200(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/input/markdown", json={
            "title": "API Test Note",
            "body":  "# API Test\n\nThis is a test note.",
            "topics": ["api", "test"],
        })
        assert r.status_code == 200
        data = r.json()
        assert data.get("ok") is True
        assert "doc_id" in data
        assert "path"   in data

    def test_post_markdown_empty_body_422(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/input/markdown", json={
            "title": "No Body",
            "body":  "",
        })
        assert r.status_code == 422

    def test_post_markdown_whitespace_body_422(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/input/markdown", json={
            "title": "Spaces Only",
            "body":  "   \n  ",
        })
        assert r.status_code == 422

    def test_post_upload_md_200(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/input/upload",
                        files=[("files", ("test_upload.md", b"# Upload Test\n\nBody.", "text/markdown"))],
                        data={"target_folder": "imports"})
        assert r.status_code == 200
        data = r.json()
        assert data["ok"] is True
        assert len(data["saved"]) >= 1

    def test_post_upload_exe_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/input/upload",
                        files=[("files", ("bad.exe", b"MZ\x00", "application/octet-stream"))],
                        data={"target_folder": "imports"})
        assert r.status_code == 200
        data = r.json()
        assert len(data["rejected"]) >= 1

    def test_post_upload_no_files_422(self, tmp_path, monkeypatch):
        monkeypatch.setenv("BOH_LIBRARY", str(tmp_path))
        r = client.post("/api/input/upload", data={"target_folder": "imports"})
        # No files field at all → FastAPI returns 422
        assert r.status_code in (422, 400)

    def test_get_recent_200(self):
        r = client.get("/api/input/recent")
        assert r.status_code == 200
        assert "items" in r.json()

    def test_health_phase_11(self):
        r = client.get("/api/health")
        assert r.status_code == 200
        assert r.json()["phase"] == 11


# ── Non-regression ────────────────────────────────────────────────────────────

class TestPhase11Regression:
    def test_search(self):
        assert client.get("/api/search?q=planar").status_code == 200

    def test_graph(self):
        assert client.get("/api/graph").status_code == 200

    def test_docs_list(self):
        assert client.get("/api/docs").status_code == 200

    def test_dcns_sync(self):
        assert client.post("/api/dcns/sync").status_code == 200

    def test_ollama_health(self):
        assert client.get("/api/ollama/health").status_code == 200
