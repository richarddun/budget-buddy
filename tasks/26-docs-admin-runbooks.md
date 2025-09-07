Title: Docs – Admin Runbooks (Ingest, Backfill, Reconcile, Export)

Context
- Operators need clear instructions for routine tasks.

Objective
- Add concise runbooks covering ingestion, backfill, category sync, reconcile, and exports.

Deliverables
- Markdown docs with:
  - How to run backfill and delta.
  - Category sync workflow and holding category handling.
  - Reconciling diffs vs last snapshot.
  - Exporting packs and verifying hashes.

Dependencies
- After corresponding features exist.

Implementation Notes
- Place under `docs/` and link from `README.md`.

Acceptance Criteria
- Docs are accurate, actionable, and match CLI/API behaviors.

Affected/Added Files
- New: `docs/runbooks.md`; touch `README.md` to link.

