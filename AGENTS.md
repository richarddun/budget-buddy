# AGENTS

- Run tests with `PYTHONPATH=. STAGING=true pytest -q`.
- When writing tests that depend on FastAPI startup logic (DB migrations, seeders), use `with TestClient(app) as client:` so startup/shutdown events run.
- The SSE endpoint's missing-key helper is bypassed when `STAGING=true`. Set `STAGING=false` in tests to exercise missing-key messaging.
- `main.SOT_DB_PATH` controls which SQLite DB is migrated on startup. Patch it in tests when using a temporary DB.
