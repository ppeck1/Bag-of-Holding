# Variable Matrix

Project: Bag of Holding

Secret policy: names only. Secret values must never be recorded.

| Name | Type | Location | Default | Required | Secret | Used By | Notes | Last Verified |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| project_root | path | `.project/launchpad.json` | repository root | yes | no | Dev Launchpad | Folder containing `.project/launchpad.json`. | 2026-06-30 |
| runtime_path | path | `.project/launchpad.json` | `.` | yes | no | Dev Launchpad | Command working directory is the repository root. | 2026-06-30 |
| start_command | command | `.project/launchpad.json` | `python launcher.py` | yes | no | Dev Launchpad | Starts the local BOH launcher. | 2026-06-30 |
| test_command | command | `.project/launchpad.json` | `python -m pytest tests/ -q` | yes | no | Dev Launchpad | Runs the project test suite. | 2026-06-30 |
| port | integer | `.project/launchpad.json` | `8000` | yes | no | Dev Launchpad / BOH | Local BOH server port. | 2026-06-30 |
| health_url | URL | `.project/launchpad.json` | `http://127.0.0.1:8000/api/health` | yes | no | Dev Launchpad / BOH | Local health probe. | 2026-06-30 |
| BOH_LIBRARY | environment variable | runtime environment | `./library` | no | no | BOH app | Server-owned document library boundary. Runtime corpus data stays out of commits. | 2026-06-30 |
| BOH_DB | environment variable | runtime environment | `boh.db` | no | no | BOH app | SQLite path. Database files are ignored. | 2026-06-30 |
| BOH_OPERATOR_TOKEN | environment variable | runtime environment | unset | production/local ops only | yes | BOH protected routes | Secret value must never be recorded. | 2026-06-30 |
| BOH_RETRIEVAL_TOKEN | environment variable | runtime environment | unset | connector use only | yes | BOH retrieval routes | Secret value must never be recorded. | 2026-06-30 |

## Maintenance Rule

Keep this matrix aligned with `.project/launchpad.json`, `README.md`, and runtime
environment documentation whenever commands, ports, paths, or operator variables
change.
