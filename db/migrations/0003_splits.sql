-- 0003_splits.sql — Split transactions support
PRAGMA foreign_keys = ON;

-- Transaction splits: one payment can be split across multiple categories
CREATE TABLE IF NOT EXISTS transaction_splits (
  id INTEGER PRIMARY KEY,
  idempotency_key TEXT NOT NULL,            -- References transactions.idempotency_key
  category_id INTEGER NOT NULL REFERENCES categories(id),
  amount_cents INTEGER NOT NULL,            -- Always positive (split amount)
  memo TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_splits_idempotency_key
  ON transaction_splits(idempotency_key);

-- Constraint: sum of split amounts must not exceed the parent transaction's absolute amount
-- (Enforced at application layer since SQLite doesn't support CHECK subqueries)

-- Add splits_total to transactions for quick reference
-- (rolled into the query layer instead of a column to avoid schema migration on the main table)
