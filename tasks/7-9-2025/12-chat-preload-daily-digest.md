Title: Chat – Preload Daily Digest Message

Context
- Chat retains history and should preload a “Daily digest” message on open.

Objective
- Inject the latest digest snapshot into chat as a system/opening message.

Deliverables
- On chat view load, add a message summarizing:
  - Current balance, safe-to-spend today, next cliff date, min balance/date.
  - Top commitments within 14 days and key events in lead window.

Dependencies
- Task 09 (digest production) and the chat template/view.

Implementation Notes
- Use existing chat history storage in `main.py` or inject via template rendering.
- Mark the digest message distinctly (non-editable, timestamped).

Acceptance Criteria
- Opening chat shows a digest summary without user action; content matches latest snapshot.

Test Guidance
- UI test: open chat route; assert digest sections present.

Affected/Added Files
- Touch: `templates/chat.html`, `main.py` route handler for chat, optional helper.

