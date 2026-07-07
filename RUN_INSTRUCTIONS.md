# Run Instructions

Bag of Holding is a local-first FastAPI application. These instructions are for
source checkout evaluation and portfolio review, not hosted production use.

## Requirements

- Python 3.11 or newer
- A local shell with access to the repository checkout
- Optional: Ollama, if you want local LLM proposal generation

## Install

```bash
pip install -r requirements.txt
```

## Start

```bash
python launcher.py
```

The launcher starts the API and governed UI at:

```text
http://127.0.0.1:8000
```

Use `--no-browser` to avoid opening a browser automatically, or `--port` to
choose a different local port.

## Verify

```bash
python -m pytest tests -q
```

For a read-only capability tour against a running server:

```bash
python demo_capability_tour.py
```

## Local State

Runtime data is intentionally local and untracked:

- `boh.db`
- `library/`
- `export/`
- quarantine and generated review artifacts

Set `BOH_LIBRARY` and `BOH_DB` if you want those files somewhere other than the
checkout defaults.
