# Budget Buddy — “Juggler” Cash‑Flow & Proactive Assistant

**Repository:** extend existing codebase at `github.com/richarddun/budget-buddy` (do **not** create a new repo).

## 0) Purpose & End State

**Intent:** Replace YNAB’s envelope/“month boundary” constraints with a **pay‑period cash‑flow simulator** and a **proactive assistant** designed for low‑buffer households. Use YNAB only as a read‑only transaction pipe. All budgeting logic, categorization, commitments, forecasts, and analysis live locally in Budget Buddy.

**Desired end state:**
- Deterministic, auditable **calendar forecast** of balances using only known items (inflows, commitments, and key spending events).
- Optional **blended forecast** (calendar + modest variable‑spend estimate) clearly toggled by the user.
- A **Daily Overview** (dashboard + digest) auto‑generated after each nightly sync with proactive alerts.
- A **Questionnaire mode** that answers lender‑style questions from deterministic queries (with drilldown evidence & export).
- Full **decoupling** from YNAB methodology: idempotent backfill, stable category mapping, and local source‑of‑truth DB.

---

## 1) Scope Summary

### 1.1 Technical Customizations
- **One‑way ingestion from YNAB** (API/CSV) into local tables with idempotent upserts and audit logging.
- **Category decoupling**: snapshot YNAB categories once, freeze mapping; maintain categories internally thereafter.
- **Data model** additions: commitments, scheduled inflows, key spending events, forecast snapshots, ingest cursors/audit.
- **Forecast engine**: calendar‑only (deterministic) + optional blended layer (μ/σ daily burn, weekday multipliers). No RNG initially.
- **Tooling boundaries**: strict JSON tools for the agent; LLM narrates only (never computes balances or edits data without confirmation).
- **Proactive digest**: nightly compute + dashboard render; event‑driven alerts on new transactions or threshold breaches.
- **Questionnaire packs**: lender‑style report bundles with period choice, proof transactions, and CSV/PDF export.

### 1.2 User Experience Customizations
- **Home screen** becomes **Daily Overview**: current cash, next payday runway chart, upcoming commitments & key events, health indicator, “safe‑to‑spend today,” and alerts.
- **Chat** retains history and gains quick actions for forecast, risk days, add key event, run questionnaire pack.
- **Toggle** between **Deterministic** and **Blended** forecasts; visual markers for commitments (📄) and key events (🎂/🎄).
- **Questionnaire tab** to run prebuilt packs or ask a directed question with drilldown and export.

---

## 2) Architecture Overview

**Data sources:** YNAB (read‑only API/CSV).  
**Core services:** FastAPI backend, Forecast engine module, Ingest workers (cron/systemd), SQLite/Postgres DB.  
**Assistant:** Tool‑using LLM restricted to read/query/what‑if endpoints; explicit user confirmation on writes (e.g., add key event).  
**Frontend:** Existing chat UI extended with Overview dashboard, charts, tables, and Questionnaire tab.

---

## 3) Data Model (DB)

> Use integer cents for currency. All timestamps are ISO dates (UTC day).

**accounts** `(id, name, type, currency, is_active)`

**transactions** `(idempotency_key, account_id, posted_at, amount_cents, payee, memo, external_id, source, category_id NULL, is_cleared, import_meta_json)`

**categories** `(id, name, parent_id NULL, is_archived, source, external_id NULL)`

**category_map** `(source, external_id, internal_category_id)`  
→ freeze YNAB→internal mapping at import; internal categories are the SoT.

**commitments** `(id, name, amount_cents, due_rule, next_due_date, priority INT, account_id, flexible_window_days INT, category_id, type)`

**scheduled_inflows** `(id, name, amount_cents, due_rule, next_due_date, account_id, type)`

**key_spend_events** `(id, name, event_date, repeat_rule NULL, planned_amount_cents, category_id, lead_time_days INT, priority INT)`

**forecast_snapshot** `(id, generated_at, mode, start_date, end_date, points_json, min_balance_cents, min_balance_date, next_cliff_date, assumptions_json)`

**source_cursor** `(source, cursor_token NULL, since_date NULL, last_run_at, stats_json)`

**ingest_audit** `(id, source, started_at, finished_at, rows_read, rows_inserted, rows_upserted, rows_ignored, errors_json)`

**question_category_alias** `(alias, category_id)`  
Maps plain terms like “childcare”, “fitness”, “transport” to internal category IDs for questionnaire tools.

Indices: composite on `(transactions.posted_at, account_id)`, unique on `transactions.idempotency_key`, and on `category_map (source, external_id)`.

---

## 4) Ingestion & Decoupling

### 4.1 Idempotency key
`sha256("{source}:{external_transaction_id}:{posted_at}:{amount_cents}")`

### 4.2 Modes
- **Delta sync**: use YNAB `server_knowledge` or `since_date`; upsert by idempotency key.
- **Backfill**: paged historical import; safe to re‑run anytime.
- **CSV fallback**: import YNAB exports when API throttles.

### 4.3 Commands (CLI)
- `budgetctl ingest ynab --delta`
- `budgetctl ingest ynab --backfill --months N`
- `budgetctl ingest ynab --from-csv path.csv`
- `budgetctl categories sync-ynab` (optional mapping refresh)
- `budgetctl reconcile` (diffs vs last forecast snapshot)

### 4.4 Category mapping
- Snapshot YNAB categories → `categories(source='ynab')` + `category_map` once.
- On ingest, resolve YNAB category via `category_map` into **internal** category.
- Unknowns go to a holding category; classifier may **suggest** a category (human confirm required).

---

## 5) Forecast Engine

### 5.1 Calendar (Deterministic) Forecast
For each date `t` in `[start, end]`:
```
balance[t+1] = balance[t]
            + Σ(scheduled_inflows due on t+1)
            - Σ(commitments due on t+1)
            - Σ(key_spend_events on t+1)
```
Policies:
- **Shift policies** per item: `AS_SCHEDULED | PREV_BUSINESS_DAY | NEXT_BUSINESS_DAY`.
- **Flexible windows** for some bills (`flexible_window_days`).
- **Partial payments** supported by split rules (future enhancement acceptable).

### 5.2 Blended Forecast (Optional)
```
baseline_blended[t] = baseline_calendar[t] - E[variable_spend(t)]
E[variable_spend(t)] = μ_daily * weekday_multiplier[t.weekday]
Bands: lower/upper = baseline_blended ± k * σ_daily
```
No RNG in v1.

### 5.3 Safety Check & What‑If
- **simulate_spend_on(date, amount)**: returns safe/unsafe, new min balance, tight days, and `max_safe_today` via binary search.

---

## 6) Proactive Digest & Alerts

- Nightly job (post‑YNAB sync) runs: build calendar, compute forecast(s), store `forecast_snapshot`.
- Digest payload: current balance, safe‑to‑spend today, next cliff date, min balance/date, top commitments within 14 days, upcoming key events inside lead window.
- Alerts when:
  - New transaction drops `min_balance` below threshold.
  - Large unplanned debit (`>|X|`).
  - Commitment amount/date drift persists ≥ 3 cycles (suggest update).

---

## 7) Questionnaire Mode

### 7.1 Query Tools (deterministic)
- `q_monthly_total_by_category(category_id, period)`
- `q_monthly_average_by_category(category_id, months)`
- `q_active_loans()`
- `q_monthly_commitment_total(kind, period)`
- `q_income_summary(period)`
- `q_statement_balances(period)`
- `q_category_breakdown(period, top_n)`
- `q_supporting_transactions(category_id, period)`
- `q_subscription_list()`
- `q_household_fixed_costs(period)`

Each returns: `{value_cents, window_start, window_end, method, evidence_ids[]}` or typed rows.

### 7.2 Packs
- **Loan Application Basics**: income (last 3 full months), active loans, housing cost, utilities avg(3m), childcare avg(3m), transport avg(3m), subscriptions monthly total, discretionary avg(3m).
- **Affordability Snapshot**: net income vs fixed costs, monthly volatility (std dev), min buffer last 60 days.

### 7.3 Exports
- CSV (one file with sections or multi‑sheet‑CSV structure) + PDF. Footer includes an **export hash** (sha256 of dataset + timestamp).

---

## 8) Backend API (FastAPI)

> All monetary values in cents; all endpoints return JSON; writes require CSRF/session auth.

**Forecast**
- `GET /api/forecast/calendar?start=YYYY-MM-DD&end=YYYY-MM-DD&buffer_floor=5000`
- `GET /api/forecast/blended?...&mu_daily=...&sigma_daily=...&weekday_mult=[...]&band_k=0.8`
- `POST /api/forecast/simulate-spend` `{date, amount_cents, mode}`

**Calendar build**
- `GET /api/calendar?start=...&end=...` → dated entries with type/name/amount/source_id

**Key spend events**
- `GET /api/key-events?from=...&to=...`
- `POST /api/key-events` (upsert)
- `DELETE /api/key-events/{id}`

**Questionnaire**
- `GET /api/q/monthly-total-by-category?...`
- `GET /api/q/monthly-average-by-category?...`
- `GET /api/q/active-loans`
- `GET /api/q/summary/income?...`
- `GET /api/q/subscriptions`
- `POST /api/q/export` `{pack, period, options}` → returns file handle/url

**Ingest & admin**
- `POST /api/ingest/ynab/delta`
- `POST /api/ingest/ynab/backfill` `{months}`
- `POST /api/ingest/ynab/from-csv` `{path}` (local‑only / admin)
- `GET /api/admin/ingest/audit`

---

## 9) Frontend (Web/JS) & UX

### 9.1 Overview Screen
- **Header cards:** total cleared balance, safe‑to‑spend today, health band (0–100 mapped to 🟢/🟡/🔴).
- **Runway chart:** line for deterministic baseline; optional shaded band for blended. Markers for commitments (📄) & key events (🎂/🎄).
- **Upcoming list (next 14–30 days):** commitments and key events, sorted by date with priority badges.
- **Alerts panel:** newest first (click→drilldown).

### 9.2 Chat Enhancements
- Preloaded “Daily digest” message on open.
- Quick actions: Run forecast, Risky days, Add key event, Run Loan Application Pack.

### 9.3 Questionnaire Tab
- Buttons for prebuilt packs; custom question input w/ typeahead for category aliases.
- Drilldown modal: shows method, window, and evidence transactions.
- Export buttons: CSV, PDF.

### 9.4 Accessibility & Responsiveness
- Keyboard‑navigable components, ARIA labels on icons, large‑tap targets on mobile.

---

## 10) Security, Privacy, Observability
- **Security**: read‑only ingestion tokens; server‑side auth for writes; CSRF on POST; rate limit admin routes. Never expose raw YNAB tokens.
- **Privacy**: redact PII in exports by default; include toggle for memos.
- **Logging**: ingest audit trails; forecast generation timings; alert triggers; export hashes.
- **Metrics**: ingestion latency, rows upserted, forecast time, API p95 latency.

---

## 11) Testing Strategy

### 11.1 Unit Tests
- Ingestion: idempotent upsert, mapping resolution, cursor advancement.
- Forecast: calendar math correctness, shift policies, flexible windows, key events application.
- Simulate spend: binary search returns correct `max_safe_today` against buffer constraint.
- Questionnaire queries: each SQL/view returns expected totals on fixtures.

### 11.2 Property/Invariant Tests
- **Determinism**: calendar forecast equals initial balance + Σ(dated inflows) − Σ(dated outflows).
- **Idempotence**: repeated ingest runs produce identical row counts and balances.
- **Toggle integrity**: deterministic vs blended differ only by variable‑spend subtraction and bands; dated items set is identical.

### 11.3 Integration Tests
- End‑to‑end backfill (API → DB → forecast → snapshot → dashboard JSON).
- Drift detection workflow: modified commitment amounts across 3 cycles → suggestion emitted.
- Questionnaire pack export: totals equal component queries; export hash stable for same dataset.

### 11.4 UI/UX Tests
- Cypress/Playwright: Overview renders after mocked API; toggling blended updates chart; alerts are clickable; screenreader announces health band.

### 11.5 Performance Budgets
- Forecast ≤ 150ms for 120‑day horizon on Pi‑class hardware.
- Dashboard JSON ≤ 200KB; charts virtualize > 180 points gracefully.

### 11.6 Test Data Fixtures
- Synthetic dataset with: monthly salary, 6–12 subscriptions, utilities w/ small variance, one loan, birthdays (2), Christmas event. Include edge cases (weekend shifts, zero‑day buffer).

---

## 12) Roadmap & Checkpoints (Sequenced, With Dependencies)

**Phase 0 — Foundations**
- [ ] Create DB migrations for new tables (categories, category_map, commitments, scheduled_inflows, key_spend_events, forecast_snapshot, source_cursor, ingest_audit, question_category_alias).
- [ ] CLI skeleton `budgetctl` (ingest, categories, reconcile).

**Phase 1 — Ingestion & Decoupling** *(depends: Phase 0)*
- [ ] Implement idempotent YNAB backfill (`--months N`) + audit rows.
- [ ] Implement delta sync using `server_knowledge`/`since_date`.
- [ ] Snapshot categories + build `category_map`; route imports through mapping.
- [ ] CSV fallback importer.

**Phase 2 — Deterministic Forecast** *(depends: Phase 1)*
- [ ] Implement calendar expansion (inflows, commitments, key events) with shift policies.
- [ ] `GET /api/forecast/calendar` endpoint + minimal runway JSON.
- [ ] Nightly job: compute snapshot + store.

**Phase 3 — Overview Dashboard** *(depends: Phase 2)*
- [ ] UI header cards (balance, safe‑to‑spend today, health band).
- [ ] Runway chart (baseline + markers), upcoming list, alerts panel.
- [ ] Chat preload: daily digest message.

**Phase 4 — Key Spending Events** *(depends: Phase 2)*
- [ ] CRUD API + UI modal to add birthdays/holidays (repeat + lead_time).
- [ ] Markers & lead‑time visibility in forecast.

**Phase 5 — Blended Forecast Toggle** *(depends: Phase 2)*
- [ ] Compute μ/σ from last 90–180 days; weekday multipliers.
- [ ] `GET /api/forecast/blended` + shaded bands; UI toggle.

**Phase 6 — Safety Checks & What‑If** *(depends: Phase 2)*
- [ ] `POST /api/forecast/simulate-spend` (returns safe/notes/max_safe_today).
- [ ] UI: quick “Can I spend €X today?” with instant answer.

**Phase 7 — Questionnaire Mode** *(depends: Phase 1)*
- [ ] Deterministic query endpoints (income, loans, childcare, etc.).
- [ ] Packs: Loan Application Basics, Affordability Snapshot.
- [ ] Drilldown modals + CSV/PDF export with hash.

**Phase 8 — Proactive Alerts** *(depends: Phases 2–3)*
- [ ] Event triggers on new transactions / threshold breaches.
- [ ] UI alert feed; optional browser notifications.

**Phase 9 — Hardening & QA** *(depends: 0–8)*
- [ ] Full test suite green; performance budgets met on target hardware.
- [ ] Security review (tokens, CSRF, rate limit admin).
- [ ] Docs: admin runbooks (ingest, backfill, reconcile, export).

**Phase 10 — Nice‑to‑Haves**
- [ ] Monte Carlo P10/P90 bands (optional, behind flag).
- [ ] Classifier‑assisted category suggestions (human‑in‑the‑loop).
- [ ] Calendar export (iCal of commitments/key events).

---

## 13) Acceptance Criteria (Go/No‑Go)
- **Deterministic forecast equals** balances + Σ(known inflows) − Σ(known outflows) over the horizon.
- **Backfill idempotent** across repeated runs and CSV/API parity.
- **Category decoupling** verified: deleting YNAB budgets/categories does not change internal category IDs or forecast results after re‑ingest.
- **Dashboard** renders under 1s and matches latest snapshot.
- **Questionnaire numbers** match underlying transactions for the declared window and method; exports embed hash.

---

## 14) Implementation Notes
- Favor **SQLite** for Pi simplicity; leave adapters to Postgres ready via SQLAlchemy.
- Use **integer cents** everywhere; formatting at the UI layer only.
- Keep the LLM sandboxed behind tool endpoints; no direct DB writes from the agent.
- Persist last successful forecast; if a run fails, display “stale” badge with timestamp.
- Document all shift policies and buffer floors in a single config file for transparency.

---

**This spec is designed to be iterative:** ship Phase 2–3 quickly to realize immediate value (deterministic runway + digest), then layer in blended forecasts, what‑ifs, and questionnaires. The system remains useful even if the statistical layer is turned off, ensuring reliability under low‑buffer, high‑latency decision pressure—the exact real‑world scenario this app is built to serve.

