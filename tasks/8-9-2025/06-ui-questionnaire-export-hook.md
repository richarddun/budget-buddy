Title: UI – Minimal Questionnaire Export Hook

Context
- Questionnaire pack assembly and export endpoints exist but lack a simple UI action to trigger/download artifacts.

Objective
- Add a small control to trigger an export for a default pack and list resulting CSV/PDF links under `/exports`.

Deliverables
- Add a section in `overview.html` (or `chat.html`) that POSTs to `/api/q/export` with a default pack/period and renders links on success.

Dependencies
- `/api/q/*` and `/api/q/export`.

Implementation Notes
- Reuse existing CSRF header helper if present; keep the UI minimal.

Acceptance Criteria
- Clicking “Export” returns success and displays links to generated files with hashes.

Test Guidance
- Manual: Trigger export and download files; verify hashes and contents.

Affected/Added Files
- Touch: `templates/overview.html` (preferred), or `templates/chat.html`.

