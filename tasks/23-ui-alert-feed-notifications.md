Title: UI – Alerts Feed and Optional Notifications

Context
- Show alerts on Overview; enable optional browser notifications.

Objective
- Render an alerts feed and (optional) browser notifications on new alerts.

Deliverables
- Alerts panel rendering list of alerts (newest first) with click→drilldown.
- Optional: request notification permission and show notification when a new alert arrives.

Dependencies
- Task 22 and existing Overview UI.

Implementation Notes
- Ensure accessible roles for list and items; include timestamps.
- Allow dismiss/hide per session.

Acceptance Criteria
- Alerts appear and update; notifications respect permission and user setting.

Test Guidance
- UI test with mocked alert payload; verify click→drilldown.

Affected/Added Files
- Touch: `templates/budget_health.html` + JS to poll/fetch alerts or use digest snapshot.

