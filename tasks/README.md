# Budget Buddy — Tasks Index

Use this checklist to track progress. Update the checkbox and add the commit hash that completes each task.

1. [01-foundations-db-migrations.md](01-foundations-db-migrations.md) — Initialize core schema and migrations.
   
   Complete : [X]
   
   Related Commit : e819f5b18e3bc6b53b573968efd2a9a8d5cdbee3
   
   Summary: Added db/migrations/0001_init.sql and migration runner (main.py)

2. [02-foundations-cli-skeleton-budgetctl.md](02-foundations-cli-skeleton-budgetctl.md) — Add `budgetctl` CLI with ingest/admin stubs.
   
   Complete : [X]
   
   Related Commit : 71f454b29b9ae92863ee2d58016310aa482b36c5
   
   Summary: Added `budgetctl` package with `python -m budgetctl` entrypoint. Implemented argparse-based subcommands for `ingest ynab` (delta/backfill/from-csv), `categories sync-ynab`, `reconcile`, and optional `db migrate`. Stubs print actionable messages and touch the SQLite DB (reads `source_cursor`).

3. [03-ingestion-backfill-ynab-idempotent.md](03-ingestion-backfill-ynab-idempotent.md) — Idempotent YNAB backfill with audit logging.
   
   Complete : [X]
   
   Related Commit : 587250801ecd6cad7a0b3eaf38d669493a4eb496
   
   Summary: Added `ingest/ynab_backfill.py` to perform idempotent backfill from YNAB. Builds `idempotency_key` as `source:ynab:{account_id}:{external_id}`, upserts accounts and transactions, maps categories via `category_map` when present, and writes `ingest_audit` with timing/rows/status. Wired into CLI via `budgetctl ingest ynab --backfill --months N`.

4. [04-ingestion-delta-sync-ynab.md](04-ingestion-delta-sync-ynab.md) — Delta sync using cursor/knowledge.
   
   Complete : [X]
   
   Related Commit : a2a2928f92bc31f33c9658853857a49ee26e8a86
   
   Summary: Added `ingest/ynab_delta.py` implementing date-based delta sync using a `source_cursor` (ISO date with 1-day overlap for clock skew). Upserts transactions idempotently, advances cursor transactionally on success, and logs runs to `ingest_audit`. Wired into CLI via `budgetctl ingest ynab --delta`.

5. [05-categories-snapshot-and-map.md](05-categories-snapshot-and-map.md) — Snapshot YNAB categories and build category_map.
  
   Complete : [X]
  
   Related Commit : 07e7cf897e29314e4dea7862a90b0288ccf93e8d
   
   Summary: Added `categories/sync_ynab.py` to fetch YNAB category groups and categories, upsert into `categories` with `source='ynab'` and hierarchy, and populate/refresh `category_map` by preferring existing mappings, then name-based internal matches, else mapping to a Holding category. Wired into CLI via `budgetctl categories sync-ynab`.

6. [06-ingestion-csv-fallback.md](06-ingestion-csv-fallback.md) — CSV importer for YNAB exports.
   
   Complete : [X]
   
   Related Commit : a3dc7d113f20b4b44655c0a86c4d08550ce1dc63
   
   Summary: Added `ingest/csv_importer.py` to parse YNAB CSVs, normalize dates/amounts, build deterministic idempotency keys, resolve categories via `category_map` (source=`ynab-csv`) with Holding fallback, upsert accounts/transactions, and write `ingest_audit`. Wired into CLI (`budgetctl ingest ynab --from-csv PATH [--account NAME]`) and handler.

7. [07-forecast-calendar-expansion.md](07-forecast-calendar-expansion.md) — Deterministic calendar expansion + balances.
  
   Complete : [X]
   
   Related Commit : 88d258e
   
   Summary: Added `forecast/calendar.py` with `Entry` dataclass, `expand_calendar(start, end)` that expands scheduled inflows, commitments, and key events from the DB with deterministic ordering and business-day shift policies (AS_SCHEDULED, PREV_BUSINESS_DAY, NEXT_BUSINESS_DAY). Commitments respect `flexible_window_days` when shifting earlier. Implemented `compute_balances(opening_balance_cents, entries)` to produce date→balance mapping. Added `tests/test_forecast_calendar.py` covering shift behavior and the balance equation.

8. [08-api-forecast-calendar-endpoint.md](08-api-forecast-calendar-endpoint.md) — GET /api/forecast/calendar.
  
   Complete : [X]
   
   Related Commit : aabda27
   
   Summary: Added `api/forecast.py` with FastAPI route `GET /api/forecast/calendar` that validates `start/end`, computes opening balance from cleared transactions across active accounts as of the day before `start`, expands entries via `forecast.calendar.expand_calendar`, computes balances and min balance/date, and returns deterministic JSON. Included router in `main.py`. Added `tests/test_api_forecast_calendar.py` seeding a temp DB and asserting opening balance, balances, and min balance/date.

9. [09-job-nightly-forecast-snapshot.md](09-job-nightly-forecast-snapshot.md) — Nightly snapshot + digest job.
   
   Complete : [X]
   
   Related Commit : 0f604c1
   
   Summary: Added `jobs/nightly_snapshot.py` with `run_nightly_snapshot` to compute a 120‑day calendar forecast using the same opening balance strategy as the API, persist a row in `forecast_snapshot` (payload + min balance/date), and return a digest including current balance, safe‑to‑spend today, next cliff date, min balance/date, top commitments (14 days), and upcoming key events within lead windows. Wired to run after daily ingestion in `jobs/daily_ingestion.py`. Added `tests/test_nightly_snapshot.py` integration test to seed DB, run job, and assert snapshot/digest.

10. [10-ui-overview-header-cards.md](10-ui-overview-header-cards.md) — Overview header cards (balance, safe-to-spend, health).
    
    Complete : [ ]
    
    Related Commit : _____

11. [11-ui-runway-chart-upcoming-alerts.md](11-ui-runway-chart-upcoming-alerts.md) — Runway chart, upcoming list, alerts panel.
    
    Complete : [ ]
    
    Related Commit : _____

12. [12-chat-preload-daily-digest.md](12-chat-preload-daily-digest.md) — Preload daily digest in chat.
    
    Complete : [ ]
    
    Related Commit : _____

13. [13-key-events-api-crud-and-ui-modal.md](13-key-events-api-crud-and-ui-modal.md) — Key spend events CRUD API + modal.
    
    Complete : [ ]
    
    Related Commit : _____

14. [14-forecast-markers-leadtime-key-events.md](14-forecast-markers-leadtime-key-events.md) — Markers + lead-time flags in forecast.
    
    Complete : [ ]
    
    Related Commit : _____

15. [15-blended-compute-mu-sigma-weekday-mults.md](15-blended-compute-mu-sigma-weekday-mults.md) — Compute μ/σ and weekday multipliers.
    
    Complete : [ ]
    
    Related Commit : _____

16. [16-api-forecast-blended-and-ui-toggle.md](16-api-forecast-blended-and-ui-toggle.md) — Blended forecast API + UI toggle.
    
    Complete : [ ]
    
    Related Commit : _____

17. [17-api-simulate-spend.md](17-api-simulate-spend.md) — POST /api/forecast/simulate-spend.
    
    Complete : [ ]
    
    Related Commit : _____

18. [18-ui-quick-can-i-spend-today.md](18-ui-quick-can-i-spend-today.md) — Quick “Can I spend X today?” UI.
    
    Complete : [ ]
    
    Related Commit : _____

19. [19-questionnaire-query-endpoints.md](19-questionnaire-query-endpoints.md) — Deterministic questionnaire query endpoints.
    
    Complete : [ ]
    
    Related Commit : _____

20. [20-questionnaire-packs-assembly.md](20-questionnaire-packs-assembly.md) — Pack assembly (Loan Basics, Affordability).
    
    Complete : [ ]
    
    Related Commit : _____

21. [21-questionnaire-exports-csv-pdf-hash.md](21-questionnaire-exports-csv-pdf-hash.md) — CSV/PDF exports with hash.
    
    Complete : [ ]
    
    Related Commit : _____

22. [22-alerts-event-triggers.md](22-alerts-event-triggers.md) — Alert triggers for thresholds/drift/large debits.
    
    Complete : [ ]
    
    Related Commit : _____

23. [23-ui-alert-feed-notifications.md](23-ui-alert-feed-notifications.md) — Alerts feed + optional notifications.
    
    Complete : [ ]
    
    Related Commit : _____

24. [24-testing-suite-and-performance-budgets.md](24-testing-suite-and-performance-budgets.md) — Test suite + performance budgets.
    
    Complete : [ ]
    
    Related Commit : _____

25. [25-security-review-hardening.md](25-security-review-hardening.md) — Auth, CSRF, rate limits, privacy.
    
    Complete : [ ]
    
    Related Commit : _____

26. [26-docs-admin-runbooks.md](26-docs-admin-runbooks.md) — Admin runbooks for ops.
    
    Complete : [ ]
    
    Related Commit : _____

27. [27-nice-monte-carlo-bands.md](27-nice-monte-carlo-bands.md) — Optional Monte Carlo bands (flagged).
    
    Complete : [ ]
    
    Related Commit : _____

28. [28-nice-classifier-suggestions.md](28-nice-classifier-suggestions.md) — Classifier-assisted category suggestions.
    
    Complete : [ ]
    
    Related Commit : _____

29. [29-nice-calendar-export-ical.md](29-nice-calendar-export-ical.md) — iCal export of commitments/events.
    
    Complete : [ ]
    
    Related Commit : _____
