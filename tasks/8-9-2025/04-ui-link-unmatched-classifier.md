Title: UI – Link to Unmatched Transactions Review

Context
- Classifier endpoints and `/unmatched` page exist but are not discoverable from the main UI.

Objective
- Add a sidebar link from the chat page to `/unmatched` for quick triage.

Deliverables
- Add a “Unmatched Transactions” button/link in `templates/chat.html` sidebar.

Dependencies
- `/api/classify/*` endpoints.

Implementation Notes
- Keep styling consistent with existing sidebar buttons.

Acceptance Criteria
- Link is visible and opens `/unmatched` in the same tab.

Test Guidance
- Manual: Click through and verify page loads and actions work.

Affected/Added Files
- Touch: `templates/chat.html`

