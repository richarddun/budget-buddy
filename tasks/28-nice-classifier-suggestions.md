Title: Nice-to-Have – Classifier-Assisted Category Suggestions

Context
- Provide suggestions for unknown categories; human-in-the-loop confirmation.

Objective
- Add a classifier that suggests internal categories for unmatched imports; never auto-apply without confirmation.

Deliverables
- Module `classification/suggester.py` producing (suggested_category_id, confidence, notes).
- API/UI to surface suggestion and accept/override.

Dependencies
- Tasks 05, ingestion tasks.

Implementation Notes
- Start with simple heuristics (payee rules, text features) before ML.
- Record accepted suggestions in mapping or payee rules table.

Acceptance Criteria
- Suggestions appear for unmapped items; acceptance updates mapping appropriately.

Test Guidance
- Unit tests with payee patterns; verify no writes without explicit accept.

Affected/Added Files
- New: `classification/suggester.py`, API/UI touchpoints.

