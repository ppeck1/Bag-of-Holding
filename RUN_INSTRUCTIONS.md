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
python launcher.py --no-mcp
```

The launcher starts the API and governed UI at:

```text
http://127.0.0.1:8000
```

Use `--no-browser` to avoid opening a browser automatically, `--port` to choose
a different local port, or `--no-mcp` to skip an otherwise enabled MCP
connector for one launch.

## Local Credentials

Open **Settings -> Security & Advanced** to configure BOH without editing shell
environment variables:

- **Operator token:** first local bootstrap is allowed only while BOH is
  developer-open. BOH stores a salted PBKDF2 verifier; plaintext stays in the
  current browser tab.
- **Retrieval token:** requires the operator credential and independently gates
  retrieval/Current Context reads.

`BOH_OPERATOR_TOKEN` and `BOH_RETRIEVAL_TOKEN` remain supported and take
precedence over Settings-managed verifiers. Use **Load tab only** for their
plaintext values. Environment-owned credentials cannot be replaced by the UI.

## MCP Source Boundary

The public export retains app-side MCP configuration and fail-soft lifecycle
logic for review, but intentionally excludes the operational adapter, gateway,
tunnel startup helper, profiles, and smoke tool. Start this checkout with
`--no-mcp`. The Security & Advanced controls document the complete deployment
contract; they cannot create a working remote connector from the public tree
alone.

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
