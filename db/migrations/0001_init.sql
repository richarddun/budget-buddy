-- 0001_init.sql — Foundations schema (SQLite-first, portable SQL)
PRAGMA foreign_keys = ON;

-- Accounts
CREATE TABLE IF NOT EXISTS accounts (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  type TEXT NOT NULL,
  currency TEXT NOT NULL,
  is_active INTEGER NOT NULL DEFAULT 1
);

-- Categories (hierarchical)
CREATE TABLE IF NOT EXISTS categories (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  parent_id INTEGER NULL REFERENCES categories(id),
  is_archived INTEGER NOT NULL DEFAULT 0,
  source TEXT,
  external_id TEXT
);

-- Mapping external category ids to internal category ids
CREATE TABLE IF NOT EXISTS category_map (
  source TEXT NOT NULL,
  external_id TEXT NOT NULL,
  internal_category_id INTEGER NOT NULL REFERENCES categories(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_category_map_source_external
  ON category_map(source, external_id);

-- Transactions (idempotent via idempotency_key)
CREATE TABLE IF NOT EXISTS transactions (
  idempotency_key TEXT NOT NULL,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  posted_at TEXT NOT NULL, -- ISO date/time (UTC)
  amount_cents INTEGER NOT NULL, -- integer cents only
  payee TEXT,
  memo TEXT,
  external_id TEXT,
  source TEXT NOT NULL,
  category_id INTEGER NULL REFERENCES categories(id),
  is_cleared INTEGER NOT NULL DEFAULT 0,
  import_meta_json TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_transactions_idem_key
  ON transactions(idempotency_key);
CREATE INDEX IF NOT EXISTS idx_transactions_posted_at
  ON transactions(posted_at);
CREATE INDEX IF NOT EXISTS idx_transactions_account_id
  ON transactions(account_id);

-- Commitments (recurring/fixed obligations)
CREATE TABLE IF NOT EXISTS commitments (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  due_rule TEXT NOT NULL,
  next_due_date TEXT,
  priority INTEGER,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  flexible_window_days INTEGER,
  category_id INTEGER REFERENCES categories(id),
  type TEXT NOT NULL
);

-- Scheduled inflows (income etc.)
CREATE TABLE IF NOT EXISTS scheduled_inflows (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  due_rule TEXT NOT NULL,
  next_due_date TEXT,
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  type TEXT NOT NULL
);

-- Key spend events
CREATE TABLE IF NOT EXISTS key_spend_events (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  event_date TEXT NOT NULL,
  repeat_rule TEXT,
  planned_amount_cents INTEGER,
  category_id INTEGER REFERENCES categories(id),
  lead_time_days INTEGER,
  shift_policy TEXT,
  account_id INTEGER REFERENCES accounts(id)
);

-- Forecast snapshots
CREATE TABLE IF NOT EXISTS forecast_snapshot (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  horizon_start TEXT NOT NULL,
  horizon_end TEXT NOT NULL,
  json_payload TEXT NOT NULL,
  min_balance_cents INTEGER,
  min_balance_date TEXT
);
CREATE INDEX IF NOT EXISTS idx_forecast_snapshot_created_at
  ON forecast_snapshot(created_at);

-- Source cursor for incremental sync
CREATE TABLE IF NOT EXISTS source_cursor (
  source TEXT NOT NULL UNIQUE,
  last_cursor TEXT,
  updated_at TEXT
);

-- Ingestion audit log
CREATE TABLE IF NOT EXISTS ingest_audit (
  id INTEGER PRIMARY KEY,
  source TEXT NOT NULL,
  run_started_at TEXT NOT NULL,
  run_finished_at TEXT,
  rows_upserted INTEGER,
  status TEXT,
  notes TEXT
);

-- Question/category aliases
CREATE TABLE IF NOT EXISTS question_category_alias (
  id INTEGER PRIMARY KEY,
  alias TEXT NOT NULL,
  category_id INTEGER NOT NULL REFERENCES categories(id)
);

