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
   
   Complete : [ ]
   
   Related Commit : _____

4. [04-ingestion-delta-sync-ynab.md](04-ingestion-delta-sync-ynab.md) — Delta sync using cursor/knowledge.
   
   Complete : [ ]
   
   Related Commit : _____

5. [05-categories-snapshot-and-map.md](05-categories-snapshot-and-map.md) — Snapshot YNAB categories and build category_map.
   
   Complete : [ ]
   
   Related Commit : _____

6. [06-ingestion-csv-fallback.md](06-ingestion-csv-fallback.md) — CSV importer for YNAB exports.
   
   Complete : [ ]
   
   Related Commit : _____

7. [07-forecast-calendar-expansion.md](07-forecast-calendar-expansion.md) — Deterministic calendar expansion + balances.
   
   Complete : [ ]
   
   Related Commit : _____

8. [08-api-forecast-calendar-endpoint.md](08-api-forecast-calendar-endpoint.md) — GET /api/forecast/calendar.
   
   Complete : [ ]
   
   Related Commit : _____

9. [09-job-nightly-forecast-snapshot.md](09-job-nightly-forecast-snapshot.md) — Nightly snapshot + digest job.
   
   Complete : [ ]
   
   Related Commit : _____

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
