Title: Key Events – CSRF/Admin Header Wiring

Context
- The Key Events modal requires `ADMIN_TOKEN` and `CSRF_TOKEN` in headers for writes when security is enabled. The UI looks for a CSRF meta tag which is not currently rendered.

Objective
- Make the modal POST/DELETE work when tokens are set by exposing a CSRF meta tag and attaching required headers.

Deliverables
- Render `<meta name="csrf-token" content="...">` when `CSRF_TOKEN` is set on the server.
- Optional dev helper: allow storing an admin token in `localStorage` and include it as `X-Admin-Token` on requests.

Dependencies
- `security/deps.py` enforcement.

Implementation Notes
- Inject tokens conditionally in the template context; do not leak tokens to clients unless explicitly configured.
- Keep behavior unchanged when tokens are not set.

Acceptance Criteria
- With tokens configured, create/update/delete Key Events via the UI without 401/403.

Test Guidance
- Manual: Set `ADMIN_TOKEN` and `CSRF_TOKEN`, reload `/budget-health`, create and delete a test event.

Affected/Added Files
- Touch: `templates/budget_health.html`, `main.py`

