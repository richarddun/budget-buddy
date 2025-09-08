Title: Forecast – Markers and Lead-Time Visibility for Key Events

Context
- Key events need markers in the chart and visibility within lead_time windows.

Objective
- Enhance forecast/calendar payload to include visual markers and lead-time flags.

Deliverables
- Extend calendar entries with `ui_marker` for commitments (📄) and key events (🎂/🎄).
- Add `is_within_lead_window` for key events to support upcoming list and alerts.

Dependencies
- Tasks 07, 11, 13.

Implementation Notes
- Choose a simple marker set; keep icons or marker types in the payload for UI mapping.
- Lead time: event_date - today <= lead_time_days.

Acceptance Criteria
- UI shows appropriate markers; upcoming list includes key events within lead time.

Test Guidance
- Unit test for lead window computation around boundaries.

Affected/Added Files
- Touch: `forecast/calendar.py`, `api/forecast.py` to enrich payload, UI rendering code.

