# Interface Contracts

This is a detected-interface scaffold.

## Launch

```bash
python launcher.py
python launcher.py --port 9000
```

## Health

```text
GET /api/health
GET /api/status
```

## UI

Static UI is served from `app/ui` by FastAPI static mounting.

## Important API Groups

- `/api/docs/*`
- `/api/graph*`
- `/api/input/*`
- `/api/workspace/*`
- `/api/autoindex/*`
- `/api/retrieve`
- `/api/planes/*`
- `/api/governance/*`
- `/api/actors/*`
- `/api/ollama/*`

## Source Of Truth

Use `/openapi.json` or `/docs` from the running app for the live route surface. Handwritten route inventories may be stale.
