-- 0004_budget_targets.sql — Monthly budget targets per category
-- Enables the envelope budgeting system: set monthly caps, track progress,
-- optionally roll over unused amounts, and get warnings when approaching limits.
PRAGMA foreign_keys = ON;

-- Monthly budget targets per category
CREATE TABLE IF NOT EXISTS budget_targets (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  month INTEGER NOT NULL,           -- YYYYMM format, e.g. 202605 for May 2026
  target_amount_cents INTEGER NOT NULL DEFAULT 0,  -- Monthly budget cap
  rollover INTEGER NOT NULL DEFAULT 0,  -- 0 = reset monthly, 1 = carry over unused
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(category_id, month)
);

CREATE INDEX IF NOT EXISTS idx_budget_targets_month
  ON budget_targets(month);

CREATE INDEX IF NOT EXISTS idx_budget_targets_category
  ON budget_targets(category_id, month);

-- Rollover tracking: stores the unused amount carried from previous month
CREATE TABLE IF NOT EXISTS budget_rollovers (
  id INTEGER PRIMARY KEY,
  category_id INTEGER NOT NULL REFERENCES categories(id),
  from_month INTEGER NOT NULL,      -- YYYYMM of the month being rolled over
  to_month INTEGER NOT NULL,        -- YYYYMM of the month receiving the rollover
  rollover_amount_cents INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE(category_id, from_month, to_month)
);

CREATE INDEX IF NOT EXISTS idx_budget_rollovers_to_month
  ON budget_rollovers(to_month);
