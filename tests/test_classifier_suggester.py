from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from classification.suggester import suggest


def _init_db(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        cur = conn.cursor()
        cur.executescript(
            """
            PRAGMA foreign_keys = ON;
            CREATE TABLE IF NOT EXISTS categories (
              id INTEGER PRIMARY KEY,
              name TEXT NOT NULL,
              parent_id INTEGER NULL,
              is_archived INTEGER NOT NULL DEFAULT 0,
              source TEXT,
              external_id TEXT
            );
            CREATE TABLE IF NOT EXISTS category_map (
              source TEXT NOT NULL,
              external_id TEXT NOT NULL,
              internal_category_id INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS uq_category_map_source_external
              ON category_map(source, external_id);
            """
        )
        # Insert an internal category "Coffee"
        cur.execute(
            "INSERT INTO categories(name, parent_id, is_archived, source, external_id) VALUES(?,?,?,?,?)",
            ("Coffee", None, 0, "internal", None),
        )
        conn.commit()
    finally:
        conn.close()


def test_suggest_uses_payee_rules(tmp_path):
    db_path = tmp_path / "budget_classifier.db"
    _init_db(db_path)

    # Seed a payee rule: icontains("starbucks") -> subcategory "Coffee"
    from localdb import payee_db

    payee_db.upsert_rule(
        pattern="starbucks",
        match_type="icontains",
        suggested_category=None,
        suggested_subcategory="Coffee",
        suggested_memo=None,
        confidence=0.9,
    )

    s = suggest(db_path, payee="STARBUCKS STORE 1234", memo=None, csv_category=None)
    assert s.category_id is not None, "Expected a suggested category id"
    assert s.category_name == "Coffee"
    assert s.confidence >= 0.6
    assert "payee rule" in s.notes

    # Ensure no writes occurred to category_map (suggester should be read-only)
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.execute("SELECT COUNT(*) FROM category_map")
        cnt = cur.fetchone()[0]
        assert cnt == 0
    finally:
        conn.close()

