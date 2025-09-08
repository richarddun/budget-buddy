Title: UI – Runway Fallback When No Entries

Context
- The runway chart depends on sparse balances keyed only on dates with entries. When there are no entries in the requested horizon, the series is empty and the chart appears blank.

Objective
- Render a flat baseline using the opening balance across the start and end dates when balances are empty, and show a friendly hint to add commitments or key events.

Deliverables
- Update `templates/budget_health.html` `loadUI()`:
  - If `balances` is empty, synthesize two points `[start, opening]` and `[end, opening]`.
  - Display a small note near the legend indicating “No scheduled items in this horizon. Showing flat baseline.”

Dependencies
- Forecast endpoints: `/api/overview`, `/api/forecast/calendar`.

Implementation Notes
- Keep existing downsampling; the fallback series should piggyback the same render path to avoid branching complexity.
- Consider annotating meta in the chart state to conditionally show the hint text; avoid layout shifts.

Acceptance Criteria
- With an empty DB (or no entries in range), the chart renders a visible line with the opening balance from start→end.
- No JS errors in console; legend and alerts continue to function.

Test Guidance
- Manual: Run with an empty `localdb/budget.db` (post‑migrations) and open `/budget-health`.
- Automated: optional small UI test stub that forces `balances = {}` path and asserts fallback branch executed.

Affected/Added Files
- Touch: `templates/budget_health.html` (JS only)

