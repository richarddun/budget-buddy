Title: Nice-to-Have – Calendar Export (iCal)

Context
- Export commitments/key events as iCal for calendar apps.

Objective
- Provide an endpoint to download iCal of commitments and key events.

Deliverables
- Endpoint `GET /api/calendar/ical?from=...&to=...` streaming an .ics file.

Dependencies
- Tasks 07, 13.

Implementation Notes
- Use a lightweight ical generator or manual formatting.
- Include shift policies applied dates.

Acceptance Criteria
- Importing .ics into a calendar shows expected items in the date range.

Affected/Added Files
- New: `api/calendar_export.py`

