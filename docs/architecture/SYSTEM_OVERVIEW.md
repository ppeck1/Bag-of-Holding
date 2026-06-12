# System Overview

This is a factual scaffold based on visible source files.

Bag of Holding is a local-first FastAPI application with a static browser UI. It manages a document library under a server-owned root, indexes documents into SQLite, exposes document/retrieval/governance APIs, and keeps authority-sensitive actions behind operator authorization.

## Main Runtime Pieces

- `launcher.py`: local launcher.
- `app/api/main.py`: FastAPI app and router registration.
- `app/api/routes/`: route modules.
- `app/core/`: domain logic, auth, retrieval, indexing helpers, PlaneCards, governance primitives.
- `app/db/connection.py`: SQLite connection and schema initialization.
- `app/db/schema.sql`: base schema.
- `app/services/`: indexing, parsing, review, migration/report helpers.
- `app/ui/`: static SPA.

## Current Caveat

The route and schema surface is large. Generated OpenAPI and actual database initialization code should be treated as current authority over older handwritten route inventories.
