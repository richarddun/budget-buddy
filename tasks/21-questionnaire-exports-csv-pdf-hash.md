Title: Questionnaire – CSV/PDF Export with Hash

Context
- Export packs with a footer hash for integrity.

Objective
- Implement `POST /api/q/export` {pack, period, options} → returns file handle/url.

Deliverables
- CSV export (multi-section CSV or multi-sheet-like structure).
- PDF export (simple templated render is fine) with footer including sha256(dataset + timestamp).

Dependencies
- Task 20.

Implementation Notes
- Create a stable serialization of the pack JSON; compute sha256 and embed.
- Redact PII by default; include toggles for memos.

Acceptance Criteria
- Exported files download, hash appears in footer/metadata, and identical data produces identical hash.

Test Guidance
- Unit test hash stability; integration test file generation.

Affected/Added Files
- New: `api/q_export.py`, `templates/q_export.pdf.html` (or similar)

