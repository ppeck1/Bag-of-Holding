from pathlib import Path


def test_save_upload_accepts_expanded_safe_text_types(tmp_path, monkeypatch):
    monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
    from app.core.input_surface import save_upload

    for name in [
        "notes.mdx",
        "settings.toml",
        "app.env.example",
        "analysis.ipynb",
        "document.docx",
    ]:
        content = b'{"cells":[{"cell_type":"markdown","source":["hello words here"]}]}' if name.endswith(".ipynb") else b"plain words here"
        result = save_upload(name, content, target_folder="imports")
        assert "reason" not in result, result
        assert Path(tmp_path, "library", result["path"]).exists()


def test_save_upload_still_rejects_archives_and_executables(tmp_path, monkeypatch):
    monkeypatch.setenv("BOH_LIBRARY", str(tmp_path / "library"))
    from app.core.input_surface import save_upload

    assert "unsupported extension" in save_upload("archive.zip", b"x")["reason"]
    assert "unsupported extension" in save_upload("run.exe", b"x")["reason"]
