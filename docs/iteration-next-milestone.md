# Budget Buddy — Next Iteration Plan (stabilization)

This document sequences small, targeted fixes to close gaps from the last batch of tasks and reach the next milestone.

Scope focuses on: runway chart reliability, chat digest preload (Task 12), and wiring exposed APIs into the UI.

## Summary of Findings

- Budget Health runway graph can render empty when the calendar has no entries for the horizon (balances are sparse-only). UI shows a blank chart with no fallback.
- Chat digest preload (Task 12) renders as a separate header block, but is not inserted into chat history as the first “system” message; SSE/history remain unchanged.
- Some APIs lack UI entry points or minimal flows:
  - Classifier review at `/unmatched` is not linked from the main UI.
  - iCal export (`GET /api/calendar/ical`) has no affordance in the UI.
  - Questionnaire pack endpoints (`/api/q/*` and `/api/q/export`) have no simple UI entry to trigger/download.
- Minor integration papercuts:
  - Key Events modal posts require admin/CSRF headers; UI JS looks for a `meta[name=csrf-token]` that isn’t present. Works only when tokens aren’t enforced.
  - Routers are included inside the `startup` event. It works under TestClient/app boot, but it’s non‑standard and can delay route availability.

## Iteration Steps (ordered)

1) Runway fallback when no entries
- Change: If `/api/overview`+`/api/forecast/calendar` return an empty `balances`, render a flat line using the opening balance across the horizon (e.g., start and end points). Also show a friendly hint to add commitments or key events.
- Files: `templates/budget_health.html` (JS `loadUI()`); optionally annotate API meta with an `empty_series` flag.
- Acceptance: With an empty DB, page renders a visible flat baseline with two points and explanatory text. No JS errors.

2) Digest as first chat message (Task 12 closure)
- Change: On `/` handler, if today’s digest exists and no stored digest message for today, insert a synthetic, non‑editable “system” message into `messages` (one per day). Render it via existing `messages.html` so history + SSE stay consistent.
- Files: `main.py` (index route: detect/insert system digest), `templates/messages.html` (add minimal styling if message starts with `[system]`), optional helper in `main.py` to upsert.
- Acceptance: Opening chat shows a digest as the first entry in history, persists across refresh, no duplicates per day.

3) Key Events modal — CSRF/admin headers
- Change: Provide a mechanism to pass `ADMIN_TOKEN` and `CSRF_TOKEN` to the browser and attach headers on POST/DELETE. Minimal option: inject a CSRF meta tag when `CSRF_TOKEN` is set; allow an optional Admin token via `localStorage` or prompt in dev. Keep default behavior when tokens aren’t configured.
- Files: `templates/budget_health.html` (add `<meta name="csrf-token" ...>` when available), `main.py` (template context injection), optional note in `README.md`.
- Acceptance: When tokens are set, creating/updating/deleting Key Events works via the UI without 401/403.

4) Surface Classifier Review UI
- Change: Add a sidebar link to “Unmatched Transactions” (`/unmatched`) in `chat.html`. Page already renders; ensure it calls `/api/classify/*` as intended.
- Files: `templates/chat.html`.
- Acceptance: Users can navigate to the unmatched review page from the main UI.

5) iCal export affordance
- Change: Add a “Download Calendar (.ics)” button on Budget Health that builds `from/to` from the loaded horizon and links to `/api/calendar/ical?from=...&to=...`.
- Files: `templates/budget_health.html` (JS after horizon load to construct link or button).
- Acceptance: Button downloads an .ics with commitments/key events for the horizon.

6) Minimal Questionnaire Export hook
- Change: Add a simple “Questionnaire Exports” section (link or small panel) that POSTs to `/api/q/export` for a default pack (e.g., `affordability_snapshot`, period = last 3 full months) and shows links to the generated files under `/exports`.
- Files: `templates/overview.html` or `templates/chat.html` (decide one spot), tiny fetch+render snippet.
- Acceptance: Clicking “Export” returns success and renders links to CSV/PDF artifacts.

7) Router inclusion timing (optional hardening)
- Change: Move `app.include_router(...)` calls out of the `startup` handler and into module import time after `app = FastAPI(...)`. This is the conventional pattern and avoids any race on early requests.
- Files: `main.py`.
- Acceptance: All `/api/*` routes are registered at app start; tests still pass.

## Nice-to-haves (next after this pass)

- Budget Health: Add Monte Carlo toggle when `MONTE_CARLO_ENABLED=true`, shaded bands overlay similar to blended baseline.
- Overview: Link to Budget Health and iCal from the header area for discoverability.
- SSE resiliency: Backoff/retry notices in the chat stream UI; fall back to non‑streamed response on persistent failure.

## Test/Validation Plan

- Unit/integration tests already cover forecast calendar and blended; add a small JS‑agnostic check by introducing a deterministic “no entries” case and verifying the API meta or a fallback branch.
- Manual flows to validate:
  - Budget Health page with and without any scheduled items (flat line fallback).
  - Chat landing shows digest once per day; message persists after navigating away and back.
  - Create/update/delete Key Events with tokens set (set `ADMIN_TOKEN`, `CSRF_TOKEN`) — confirm 2xx responses.
  - Unmatched review reachable from sidebar and calls `classify` APIs.
  - iCal button downloads a valid .ics for the current horizon.
  - Questionnaire default export creates artifacts under `/exports` and renders links.

## Implementation Notes

- Avoid schema changes for the digest message: prefix prompt with `[system] Daily Digest (YYYY‑MM‑DD)` and store the rendered summary as response. Style lightly in `messages.html` based on that prefix.
- For CSRF, expose `CSRF_TOKEN` via a template variable and render a meta tag only when set. Admin token can be provided through a simple dev prompt that stores `X-Admin-Token` in `localStorage` (optional), or rely on basic auth header configuration if running behind a proxy in prod.
- Keep payload sizes under the existing budgets by reusing downsampling in the chart and avoiding large JSON blobs in the digest message.

