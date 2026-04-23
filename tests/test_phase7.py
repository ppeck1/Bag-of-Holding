"""tests/test_phase7.py: Phase 7 tests — Document Reader, Related Engine, Atlas Graph.

Covers:
- GET /api/docs/{id}/content — raw markdown body
- GET /api/docs/{id}/related — semantic relatedness
- GET /api/graph             — graph nodes + edges
- app/core/related.py        — scoring functions
- Vendor files served at /vendor/*
"""

import json
import os
import uuid
import pytest

os.environ.setdefault("BOH_DB", os.path.join(os.path.dirname(__file__), "test_boh_v2.db"))
os.environ.setdefault("BOH_LIBRARY", os.path.join(os.path.dirname(__file__), "..", "library"))

from fastapi.testclient import TestClient
from app.api.main import app
from app.db import connection as db
from app.core.related import get_related, get_graph_data, _jaccard

client = TestClient(app, raise_server_exceptions=True)


@pytest.fixture(autouse=True, scope="module")
def init():
    db.init_db()
    client.post("/api/index", json={"library_root": os.environ["BOH_LIBRARY"]})


# ── Jaccard similarity ────────────────────────────────────────────────────────

def test_jaccard_identical_sets():
    assert _jaccard({'a','b','c'}, {'a','b','c'}) == 1.0

def test_jaccard_disjoint_sets():
    assert _jaccard({'a','b'}, {'c','d'}) == 0.0

def test_jaccard_partial_overlap():
    j = _jaccard({'a','b','c'}, {'b','c','d'})
    assert abs(j - 0.5) < 0.001  # |{b,c}| / |{a,b,c,d}| = 2/4

def test_jaccard_both_empty():
    assert _jaccard(set(), set()) == 0.0


# ── Related document scoring ──────────────────────────────────────────────────

def test_related_returns_structure():
    docs = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
    if not docs:
        pytest.skip("No docs indexed")
    result = get_related(docs[0]["doc_id"], limit=5)
    assert "doc_id" in result
    assert "related" in result
    assert "total_candidates" in result
    assert isinstance(result["related"], list)


def test_related_score_in_range():
    docs = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
    if not docs:
        pytest.skip("No docs indexed")
    result = get_related(docs[0]["doc_id"])
    for r in result["related"]:
        assert 0.0 < r["score"] <= 1.0, f"Score out of range: {r['score']}"


def test_related_has_score_breakdown():
    docs = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
    if not docs:
        pytest.skip("No docs indexed")
    result = get_related(docs[0]["doc_id"])
    for r in result["related"]:
        sb = r.get("score_breakdown", {})
        assert "topic_overlap" in sb
        assert "scope_overlap" in sb
        assert "lineage_bonus" in sb
        assert "shared_defs" in sb


def test_related_excludes_self():
    docs = db.fetchall("SELECT doc_id FROM docs LIMIT 1")
    if not docs:
        pytest.skip("No docs indexed")
    doc_id = docs[0]["doc_id"]
    result = get_related(doc_id)
    for r in result["related"]:
        assert r["doc_id"] != doc_id, "Source doc must not appear in its own related list"


def test_related_nonexistent_doc():
    result = get_related("nonexistent-id-xyz")
    assert "error" in result


# ── GET /api/docs/{id}/related ────────────────────────────────────────────────

def test_api_related_200():
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No docs")
    r = client.get(f"/api/docs/{docs[0]['doc_id']}/related")
    assert r.status_code == 200


def test_api_related_404():
    r = client.get("/api/docs/nonexistent-xyz/related")
    assert r.status_code == 404


def test_api_related_limit_respected():
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No docs")
    r = client.get(f"/api/docs/{docs[0]['doc_id']}/related?limit=3")
    assert r.status_code == 200
    assert len(r.json()["related"]) <= 3


# ── GET /api/docs/{id}/content ────────────────────────────────────────────────

def test_api_content_200():
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No docs")
    r = client.get(f"/api/docs/{docs[0]['doc_id']}/content")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")


def test_api_content_no_frontmatter():
    """Body returned must not include the YAML frontmatter block."""
    docs = client.get("/api/docs").json()["docs"]
    if not docs:
        pytest.skip("No docs")
    r = client.get(f"/api/docs/{docs[0]['doc_id']}/content")
    body = r.text
    assert not body.strip().startswith("---"), \
        "Content endpoint must strip YAML frontmatter"


def test_api_content_404():
    r = client.get("/api/docs/nonexistent-xyz/content")
    assert r.status_code == 404


# ── GET /api/graph ────────────────────────────────────────────────────────────

def test_api_graph_200():
    r = client.get("/api/graph")
    assert r.status_code == 200


def test_api_graph_structure():
    body = client.get("/api/graph").json()
    assert "nodes" in body
    assert "edges" in body
    assert isinstance(body["nodes"], list)
    assert isinstance(body["edges"], list)


def test_api_graph_node_fields():
    body = client.get("/api/graph").json()
    if not body["nodes"]:
        pytest.skip("No nodes")
    node = body["nodes"][0]
    required = {"id", "label", "path", "type", "status", "corpusClass", "canonScore", "topics"}
    missing = required - set(node.keys())
    assert not missing, f"Node missing fields: {missing}"


def test_api_graph_edge_fields():
    body = client.get("/api/graph").json()
    if not body["edges"]:
        pytest.skip("No edges")
    edge = body["edges"][0]
    required = {"source", "target", "type", "relationship", "weight"}
    missing = required - set(edge.keys())
    assert not missing, f"Edge missing fields: {missing}"


def test_api_graph_edges_reference_valid_nodes():
    body = client.get("/api/graph").json()
    node_ids = {n["id"] for n in body["nodes"]}
    for edge in body["edges"]:
        assert edge["source"] in node_ids, f"Edge source {edge['source']} not in nodes"
        assert edge["target"] in node_ids, f"Edge target {edge['target']} not in nodes"


def test_api_graph_max_nodes_param():
    body = client.get("/api/graph?max_nodes=10").json()
    assert len(body["nodes"]) <= 10


def test_api_graph_canon_nodes_sized():
    """Canon nodes must have higher canonScore than archived nodes."""
    body = client.get("/api/graph").json()
    canon_scores = [n["canonScore"] for n in body["nodes"] if n.get("status") == "canonical"]
    arch_scores  = [n["canonScore"] for n in body["nodes"] if n.get("status") == "archived"]
    if canon_scores and arch_scores:
        assert max(canon_scores) > max(arch_scores), \
            "Canon nodes should have higher canonScore than archived"


# ── get_graph_data() unit test ────────────────────────────────────────────────

def test_graph_data_no_self_edges():
    data = get_graph_data(max_nodes=50)
    for edge in data["edges"]:
        assert edge["source"] != edge["target"], "Self-edges not allowed in graph"


def test_graph_data_edge_types():
    data = get_graph_data(max_nodes=50)
    # Phase 8 expanded edge types to include DCNS explicit edges
    valid_types = {"lineage", "related", "duplicate_content", "supersedes",
                   "conflicts", "canon_relates_to", "derives"}
    for edge in data["edges"]:
        assert edge["type"] in valid_types, f"Invalid edge type: {edge['type']!r}"


# ── Vendor files served ───────────────────────────────────────────────────────

def test_vendor_marked_served():
    r = client.get("/vendor/marked.min.js")
    assert r.status_code == 200
    assert "javascript" in r.headers.get("content-type", "")


def test_vendor_katex_js_served():
    r = client.get("/vendor/katex.min.js")
    assert r.status_code == 200


def test_vendor_katex_css_served():
    r = client.get("/vendor/katex.min.css")
    assert r.status_code == 200
    assert "css" in r.headers.get("content-type", "")


def test_vendor_katex_font_served():
    from pathlib import Path
    font_dir = Path(__file__).parent.parent / "app" / "ui" / "vendor" / "fonts"
    if not any(font_dir.glob("*.woff2")):
        pytest.skip("No KaTeX fonts found")
    # Just verify the fonts directory exists and has files
    fonts = list(font_dir.glob("*.woff2"))
    assert len(fonts) > 0


# ── All Phase 7 routes return 200 ────────────────────────────────────────────

def test_graph_route_200():
    assert client.get("/api/graph").status_code == 200

def test_all_prior_routes_still_200():
    """Regression: ensure Phase 7 additions haven't broken existing routes."""
    for path in ["/api/health", "/api/dashboard", "/api/docs", "/api/conflicts", "/api/lineage"]:
        r = client.get(path)
        assert r.status_code == 200, f"Regression: {path} → {r.status_code}"


# ── Fix 3: Atlas structural + activation tests ───────────────────────────────

def test_atlas_panel_has_no_inline_display_none():
    """#panel-atlas must not carry display:none in its inline style — that blocks .panel.active."""
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "ui" / "index.html").read_text()

    # Find the atlas panel tag
    start = html.find('id="panel-atlas"')
    assert start != -1, "#panel-atlas not found in index.html"

    # Extract the opening tag (up to the first >)
    tag = html[start:html.find('>', start)]
    assert "display:none" not in tag, (
        f"#panel-atlas has display:none in its inline style.\n"
        f"Tag fragment: {tag[:200]}"
    )


def test_atlas_panel_has_correct_inline_style():
    """#panel-atlas inline style should have padding:0 and height but no display:none."""
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "ui" / "index.html").read_text()
    start = html.find('id="panel-atlas"')
    tag = html[start:html.find('>', start)]
    assert "padding:0" in tag, "#panel-atlas must have padding:0"
    assert "height:" in tag, "#panel-atlas must have height specification"
    assert "display:none" not in tag, "#panel-atlas must not have display:none"


def test_atlas_nav_item_exists():
    """The Atlas nav item must be present in the HTML."""
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "ui" / "index.html").read_text()
    assert 'data-panel="atlas"' in html, "Atlas nav item missing from index.html"
    assert "Atlas" in html, "Atlas label missing from nav"


def test_atlas_panel_section_exists():
    """The #panel-atlas section must exist in index.html."""
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "ui" / "index.html").read_text()
    assert 'id="panel-atlas"' in html, "#panel-atlas section missing"
    assert 'id="graph-canvas"' in html, "graph canvas element missing"
    assert 'id="reader-content"' in html, "reader content element missing"
    assert 'id="reader-pane"' in html, "reader pane missing"


def test_nav_function_contains_atlas_init():
    """nav() must contain the Atlas init call — not rely on a post-boot monkey-patch."""
    from pathlib import Path
    js = (Path(__file__).parent.parent / "app" / "ui" / "app.js").read_text()

    # Find nav() function body (between function nav( and the next top-level function)
    nav_start = js.find("function nav(panelId)")
    assert nav_start != -1, "nav() function not found in app.js"
    # Extract until the closing brace of nav()
    nav_body = js[nav_start:js.find("\n// Handle keyboard nav", nav_start)]
    assert "atlas" in nav_body, (
        "nav() must contain Atlas init logic. "
        "Found nav() body: " + nav_body[:300]
    )
    assert "initAtlas" in nav_body, "nav() must call initAtlas()"
    assert "_graph" in nav_body, "nav() must guard Atlas init with !_graph"


def test_no_monkey_patch_of_window_nav():
    """The late monkey-patch override of window.nav must be removed."""
    from pathlib import Path
    js = (Path(__file__).parent.parent / "app" / "ui" / "app.js").read_text()
    assert "window.nav = function" not in js, (
        "window.nav monkey-patch is still present — it runs after boot() "
        "and causes Atlas to not initialize on direct hash load."
    )


def test_css_panel_active_not_overridden():
    """style.css must define .panel.active without display:none override path."""
    from pathlib import Path
    css = (Path(__file__).parent.parent / "app" / "ui" / "style.css").read_text()
    # panel.active should set display:block (or flex for atlas)
    assert ".panel.active" in css, ".panel.active not defined in style.css"
    # Atlas override: display:flex
    assert "#panel-atlas.active" in css, "#panel-atlas.active override not in style.css"


def test_atlas_panel_dom_structure_complete():
    """All required Atlas DOM elements must be present."""
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "ui" / "index.html").read_text()
    required_ids = [
        "graph-canvas", "graph-pane", "graph-toolbar", "graph-legend",
        "graph-stats", "graph-filter-class", "graph-show-related",
        "reader-pane", "reader-header", "reader-title", "reader-meta",
        "reader-toggle", "reader-content", "reader-related",
        "btn-rendered", "btn-raw",
    ]
    for elem_id in required_ids:
        assert f'id="{elem_id}"' in html, f"Missing required DOM element: #{elem_id}"


def test_vendor_scripts_in_html_head():
    """KaTeX and marked.js must be loaded via <script> tags before app.js."""
    from pathlib import Path
    html = (Path(__file__).parent.parent / "app" / "ui" / "index.html").read_text()
    assert "/vendor/katex.min.js" in html, "KaTeX script not linked in HTML"
    assert "/vendor/marked.min.js" in html, "marked.js script not linked in HTML"
    assert "/vendor/katex.min.css" in html, "KaTeX CSS not linked in HTML"

    # Scripts must appear BEFORE app.js (order matters)
    katex_pos  = html.find("/vendor/katex.min.js")
    marked_pos = html.find("/vendor/marked.min.js")
    appjs_pos  = html.find("/app.js")
    assert katex_pos  < appjs_pos, "katex.min.js must load before app.js"
    assert marked_pos < appjs_pos, "marked.min.js must load before app.js"
