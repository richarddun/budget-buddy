Title: Categories – Snapshot YNAB and Build `category_map`

Context
- Decouple internal categories from YNAB. Snapshot once and freeze mapping.

Objective
- Implement `budgetctl categories sync-ynab` to ingest YNAB categories, write to `categories(source='ynab')`, and populate `category_map` linking to internal categories.

Deliverables
- Command that:
  - Fetches YNAB categories and inserts/updates into `categories` with `source='ynab'` and `external_id` set.
  - Establishes or refreshes `category_map` to existing internal categories, without changing internal IDs.
  - Unknown mappings route imported transactions to a holding/internal catch-all category.

Dependencies
- Tasks 01–04.

Implementation Notes
- Consider storing a parallel set of internal categories (`source='internal'`, external_id NULL).
- Provide a simple mapping file/editor later; for now, bootstrap 1:1 where sensible and place others in holding.
- Do not mutate internal category IDs once assigned.

Acceptance Criteria
- Running sync twice does not change internal ids.
- New YNAB categories are added and mapped or placed into holding.

Test Guidance
- Mock YNAB returning categories A/B; run sync; assert categories table contains rows and `category_map` has source/external_id keys.

Affected/Added Files
- New: `categories/sync_ynab.py`
- Touch: `cli/budgetctl.py` to wire subcommand.

