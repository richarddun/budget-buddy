Title: Server – Move Router Registration out of Startup

Context
- Routers are currently included during the FastAPI `startup` event. This works but is non‑standard and may delay early route availability.

Objective
- Register all routers at module import time, directly after `app = FastAPI(...)`.

Deliverables
- Update `main.py` to include routers outside of the `@app.on_event("startup")` handler.

Dependencies
- None functionally; ensure import ordering remains safe.

Implementation Notes
- Keep startup logic for migrations/scheduler. Route inclusion should be unconditional and idempotent on import.

Acceptance Criteria
- All `/api/*` routes present immediately after app load; existing tests continue to pass.

Test Guidance
- Manual: Start app and hit an `/api` endpoint before any other interaction.

Affected/Added Files
- Touch: `main.py`

