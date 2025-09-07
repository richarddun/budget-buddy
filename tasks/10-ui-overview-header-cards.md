Title: UI – Overview Header Cards (Balance, Safe-to-Spend, Health)

Context
- The Overview screen leads with: total cleared balance, safe-to-spend today, health band.
- Digest data is produced nightly (Task 09).

Objective
- Render header cards on the home/overview screen using snapshot/digest data.

Deliverables
- Frontend elements (templates or JS) displaying:
  - Total cleared balance (from snapshot/digest)
  - Safe-to-spend today
  - Health band indicator (0–100 mapped to 🟢/🟡/🔴)

Dependencies
- Task 09 for digest data availability; an endpoint to fetch digest (reuse forecast or add `/api/overview` minimal JSON).

Implementation Notes
- Use existing templating (`templates/`) and add API call or server-rendered JSON.
- Ensure accessible labels and responsive layout.

Acceptance Criteria
- Header cards render with real data and degrade gracefully if snapshot is stale (show timestamp/badge).

Test Guidance
- UI test with mocked API response verifying card values render and health band ARIA label exists.

Affected/Added Files
- Touch: `templates/budget_health.html` or new `templates/overview.html` and related route.
- New: optional `api/overview.py` endpoint returning digest.

