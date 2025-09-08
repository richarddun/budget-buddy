# Budget Buddy — Tasks Index (2025-09-08)

Use this checklist to track progress for today’s iteration. Update the checkbox and add the commit hash that completes each task. Link back to docs/iteration-next-milestone.md for the context of this pass.

1. [01-ui-runway-fallback-empty-series.md](01-ui-runway-fallback-empty-series.md) — Show a flat baseline when calendar is empty.
   
   Complete : [X]
   
   Related Commit : a8348cbd87c937cf523112251a3c659c1d778d14
   
   Summary: When `/api/forecast/calendar` returns no balances (no entries in horizon), render a flat line using opening balance across start/end, with a hint to add commitments/key events. Prevents empty chart.
   
   Work Done: Added fallback in `templates/budget_health.html` `loadUI()` to synthesize a two‑point series `[start, opening]` → `[end, opening]` when balances are empty, and toggled a legend note: “No scheduled items in this horizon. Showing flat baseline.”

2. [02-chat-digest-system-message-preload.md](02-chat-digest-system-message-preload.md) — Insert daily digest as first chat message.
   
   Complete : [X]
   
   Related Commit : 2e676bfdc1913d828abbfc0067a895cc7245bdc7
   
   Summary: Implemented idempotent preload of a `[system] Daily Digest (YYYY-MM-DD)` message on index load when a digest is available. The index route now computes the latest digest and upserts a single system message per day before rendering history. Added compact HTML summary (balances, safe-to-spend, next cliff, min balance, top commitments). Styled system messages in `templates/messages.html` with a muted “system” badge and subtle text color.

3. [03-key-events-csrf-admin-wiring.md](03-key-events-csrf-admin-wiring.md) — CSRF/Admin headers for Key Events modal.
   
   Complete : [ ]
   
   Related Commit : 
   
   Summary: Inject CSRF meta when configured and attach headers on POST/DELETE; optional dev helper for Admin token (localStorage). Ensures UI works under auth.

4. [04-ui-link-unmatched-classifier.md](04-ui-link-unmatched-classifier.md) — Add sidebar link to Unmatched Review.
   
   Complete : [ ]
   
   Related Commit : 
   
   Summary: Link to `/unmatched` from the main chat sidebar for quick triage of classifier suggestions.

5. [05-ui-ical-export-affordance.md](05-ui-ical-export-affordance.md) — Add iCal export button to Budget Health.
   
   Complete : [ ]
   
   Related Commit : 
   
   Summary: Provide a “Download .ics” affordance using the active horizon to call `/api/calendar/ical?from=...&to=...`.

6. [06-ui-questionnaire-export-hook.md](06-ui-questionnaire-export-hook.md) — Minimal UI to trigger pack export.
   
   Complete : [ ]
   
   Related Commit : 
   
   Summary: Add a small action to POST to `/api/q/export` for a default pack and show links to generated files under `/exports`.

7. [07-main-router-include-cleanup.md](07-main-router-include-cleanup.md) — Register routers outside startup.
   
   Complete : [ ]
   
   Related Commit : 
   
   Summary: Move `include_router` calls to module load time (post `app = FastAPI(...)`) for conventional startup and route availability.
