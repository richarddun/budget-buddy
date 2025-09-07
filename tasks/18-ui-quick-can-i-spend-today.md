Title: UI – Quick “Can I spend X today?”

Context
- Provide a fast input on Overview to call simulate-spend.

Objective
- Add a small form or control to input amount and show immediate answer.

Deliverables
- Input + submit that calls `POST /api/forecast/simulate-spend` and displays safe/unsafe, max_safe_today, and notes.

Dependencies
- Task 17.

Implementation Notes
- Validate integer-cents amount; format currency on display only.
- Accessible labels and keyboard submit.

Acceptance Criteria
- Submitting a valid amount shows response; errors display friendly messages.

Test Guidance
- UI test mocking API to ensure rendering of safe vs unsafe cases.

Affected/Added Files
- Touch: `templates/budget_health.html` or a new component template/JS.

