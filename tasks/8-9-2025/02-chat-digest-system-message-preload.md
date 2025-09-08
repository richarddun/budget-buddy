Title: Chat – Insert Daily Digest as First System Message

Context
- Task 12 added a digest block to the chat template but does not store it in chat history, so SSE/history flows aren’t aware of it.

Objective
- On landing, if a digest exists and there is no digest message stored for today, insert a synthetic, non‑editable system message into `messages` so it appears at the top of the chat and persists.

Deliverables
- `main.py` index route: compute latest digest; upsert a message with prompt `[system] Daily Digest (YYYY-MM-DD)` and response as a compact summary.
- `templates/messages.html`: Add light styling for messages where `prompt` begins with `[system]` (e.g., muted tag).

Dependencies
- Nightly snapshot digest computation in `jobs/nightly_snapshot.py` (or live fallback if not present).

Implementation Notes
- Ensure idempotence: only one system digest per calendar day.
- Keep message small; avoid embedding large JSON.

Acceptance Criteria
- Opening the chat shows the digest as the first entry, once per day. It persists across refresh and does not duplicate.

Test Guidance
- Manual: Clear messages, ensure a digest exists, load `/` twice and confirm only one system entry is added for that day.

Affected/Added Files
- Touch: `main.py`, `templates/messages.html`

