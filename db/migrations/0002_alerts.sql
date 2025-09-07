-- 0002_alerts.sql — Alerts table for event triggers
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS alerts (
  id INTEGER PRIMARY KEY,
  created_at TEXT NOT NULL,
  type TEXT NOT NULL,
  dedupe_key TEXT NOT NULL,
  severity TEXT NOT NULL, -- info, warning, critical
  title TEXT NOT NULL,
  message TEXT NOT NULL,
  details_json TEXT,
  resolved_at TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_alerts_type_key
  ON alerts(type, dedupe_key);

