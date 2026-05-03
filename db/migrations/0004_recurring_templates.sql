-- 0004_recurring_templates.sql — Recurring transaction template system
-- Auto-create transactions from commitments/scheduled_inflows when due
PRAGMA foreign_keys = ON;

-- Recurring templates linked to commitments or scheduled_inflows
CREATE TABLE IF NOT EXISTS recurring_templates (
  id INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  amount_cents INTEGER NOT NULL,
  due_rule TEXT NOT NULL,           -- MONTHLY, WEEKLY, BIWEEKLY, ANNUAL, ONE_OFF
  next_due_date TEXT,               -- YYYY-MM-DD, the next date this should fire
  account_id INTEGER NOT NULL REFERENCES accounts(id),
  category_id INTEGER REFERENCES categories(id),
  payee TEXT,                        -- Override payee name (defaults to name if null)
  memo TEXT,                         -- Optional memo for auto-created transactions
  type TEXT NOT NULL DEFAULT 'expense',  -- expense or income
  source_commitment_id INTEGER REFERENCES commitments(id),     -- Linked commitment (optional)
  source_inflow_id INTEGER REFERENCES scheduled_inflows(id),   -- Linked scheduled inflow (optional)
  auto_create INTEGER NOT NULL DEFAULT 1,  -- 1 = auto-create on due, 0 = prompt/confirm only
  last_created_date TEXT,            -- YYYY-MM-DD of last auto-created transaction
  is_active INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  updated_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_recurring_templates_next_due
  ON recurring_templates(next_due_date);

CREATE INDEX IF NOT EXISTS idx_recurring_templates_active
  ON recurring_templates(is_active, next_due_date);

-- Deduplication: track which template instances have been generated
CREATE TABLE IF NOT EXISTS recurring_instances (
  id INTEGER PRIMARY KEY,
  template_id INTEGER NOT NULL REFERENCES recurring_templates(id),
  due_date TEXT NOT NULL,            -- The due date this instance was for
  idempotency_key TEXT NOT NULL,     -- The transaction's idempotency key if auto-created
  created_at TEXT NOT NULL DEFAULT (datetime('now')),
  status TEXT NOT NULL DEFAULT 'pending'  -- pending, created, skipped, error
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_recurring_instance
  ON recurring_instances(template_id, due_date);

CREATE INDEX IF NOT EXISTS idx_recurring_instances_status
  ON recurring_instances(status);
