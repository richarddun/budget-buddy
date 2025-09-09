-- 0002_account_anchors.sql — Per-account anchor balance and overdraft floor
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS account_anchors (
  account_id INTEGER PRIMARY KEY REFERENCES accounts(id),
  anchor_date TEXT NOT NULL,
  anchor_balance_cents INTEGER NOT NULL,
  min_floor_cents INTEGER
);

