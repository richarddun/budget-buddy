Title: UI – iCal Export Affordance on Budget Health

Context
- `/api/calendar/ical` is implemented but not accessible from the UI.

Objective
- Provide a button on the Budget Health page to download an .ics file for the active forecast horizon.

Deliverables
- After loading `/api/overview`, construct a link to `/api/calendar/ical?from=...&to=...` and render a “Download Calendar (.ics)” button.

Dependencies
- `/api/overview` for start/end; `/api/calendar/ical` for ICS stream.

Implementation Notes
- Ensure the link is updated after each `loadUI()` refresh so the dates stay in sync.

Acceptance Criteria
- Clicking the button downloads an .ics matching the current horizon.

Test Guidance
- Manual: Inspect the .ics for expected events; verify dates match horizon.

Affected/Added Files
- Touch: `templates/budget_health.html`

