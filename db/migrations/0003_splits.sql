-- 0003_splits.sql — Split transactions support
PRAGMA foreign_keys = ON;

-- Transaction splits: one payment can be split across multiple categories
CREATE TABLE IF NOT EXISTS transaction_splits (
  id INTEGER PRIMARY KEY,
  transaction_idempotency_key TEXT NOT NULL REFERENCES transactions(idempotency_key),
  category_id INTEGER NOT NULL REFERENCES categories(id),
  amount_cents INTEGER NOT NULL,
  memo TEXT,
  sort_order INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_splits_transaction_key
  ON transaction_splits(transaction_idempotency_key);

-- Constraint: sum of split amounts must not exceed the parent transaction's absolute amount
-- (Enforced at application layer since SQLite doesn't support CHECK subqueries)

-- Add splits_total to transactions for quick reference
-- (rolled into the query layer instead of a column to avoid schema migration on the main table)
