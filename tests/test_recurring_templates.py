"""Tests for jobs/recurring_templates.py — recurring transaction auto-creation."""

import json
import sqlite3
import tempfile
import os
from datetime import date, timedelta
from pathlib import Path

import pytest

from db.migrate import run_migrations

# Ensure the DB module can find migrations
_MIGRATIONS_DIR = Path("db/migrations")


@pytest.fixture
def db_path():
    """Create a fresh SQLite DB with all migrations applied."""
    tmp = Path(tempfile.mktemp(suffix=".budget.db"))
    run_migrations(tmp, _MIGRATIONS_DIR)
    conn = sqlite3.connect(str(tmp))
    conn.execute(
        "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (1, 'Current', 'checking', 'EUR', 1)"
    )
    conn.execute(
        "INSERT INTO accounts(id, name, type, currency, is_active) VALUES (2, 'Savings', 'savings', 'EUR', 1)"
    )
    conn.execute(
        "INSERT INTO categories(id, name) VALUES (1, 'Bills')"
    )
    conn.execute(
        "INSERT INTO categories(id, name) VALUES (2, 'Entertainment')"
    )
    conn.commit()
    conn.close()
    yield tmp
    if tmp.exists():
        tmp.unlink()


def _seed_commitment(conn: sqlite3.Connection, **kw):
    defaults = {
        "name": "Rent",
        "amount_cents": 120000,
        "due_rule": "MONTHLY",
        "next_due_date": date.today().isoformat(),
        "priority": 1,
        "account_id": 1,
        "flexible_window_days": 0,
        "category_id": 1,
        "type": "bill",
    }
    vals = {**defaults, **kw}
    conn.execute(
        """INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
           VALUES (:name, :amount_cents, :due_rule, :next_due_date, :priority, :account_id, :flexible_window_days, :category_id, :type)""",
        vals,
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def _seed_template(conn: sqlite3.Connection, **kw):
    defaults = {
        "name": "Netflix",
        "amount_cents": 1499,
        "due_rule": "MONTHLY",
        "next_due_date": date.today().isoformat(),
        "account_id": 1,
        "category_id": 2,
        "payee": None,
        "memo": None,
        "type": "expense",
        "auto_create": 1,
        "source_commitment_id": None,
        "source_inflow_id": None,
    }
    vals = {**defaults, **kw}
    if vals["payee"] is None:
        vals["payee"] = vals["name"]
    conn.execute(
        """INSERT INTO recurring_templates(
            name, amount_cents, due_rule, next_due_date,
            account_id, category_id, payee, memo, type,
            auto_create, source_commitment_id, source_inflow_id
        ) VALUES (
            :name, :amount_cents, :due_rule, :next_due_date,
            :account_id, :category_id, :payee, :memo, :type,
            :auto_create, :source_commitment_id, :source_inflow_id
        )""",
        vals,
    )
    conn.commit()
    return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_generate_templates_from_commitments(db_path):
    """Syncing from commitments creates templates for unlinked commitments."""
    conn = sqlite3.connect(str(db_path))
    cid = _seed_commitment(conn, name="Electric Ireland", amount_cents=8500,
                           next_due_date=(date.today() + timedelta(days=5)).isoformat())
    conn.close()

    from jobs.recurring_templates import generate_templates_from_commitments, list_templates

    result = generate_templates_from_commitments(db_path)
    assert result["status"] == "ok"
    assert result["created"] == 1
    assert result["skipped"] == 0

    templates = list_templates(db_path)
    assert len(templates) == 1
    assert templates[0]["name"] == "Electric Ireland"
    assert templates[0]["source_commitment_id"] == cid
    assert templates[0]["auto_create"] is True


def test_generate_skips_linked_commitments(db_path):
    """Already-linked commitments are not duplicated."""
    conn = sqlite3.connect(str(db_path))
    cid = _seed_commitment(conn, name="Internet", amount_cents=4500,
                           next_due_date=(date.today() + timedelta(days=3)).isoformat())
    # Create a template already linked
    conn.execute(
        """INSERT INTO recurring_templates(name, amount_cents, due_rule, next_due_date, account_id, type, auto_create, source_commitment_id)
           VALUES ('Internet', 4500, 'MONTHLY', ?, 1, 'expense', 1, ?)""",
        ((date.today() + timedelta(days=3)).isoformat(), cid),
    )
    conn.commit()
    conn.close()

    from jobs.recurring_templates import generate_templates_from_commitments

    result = generate_templates_from_commitments(db_path)
    assert result["created"] == 0
    assert result["skipped"] == 0  # skipped because already linked


def test_generate_skips_name_duplicates(db_path):
    """If a template with the same name already exists, skip."""
    conn = sqlite3.connect(str(db_path))
    _seed_commitment(conn, name="Duplicate Name", amount_cents=5000,
                     next_due_date=date.today().isoformat())
    # Create a template with the same name manually (not linked)
    conn.execute(
        """INSERT INTO recurring_templates(name, amount_cents, due_rule, next_due_date, account_id, type, auto_create)
           VALUES ('Duplicate Name', 5000, 'MONTHLY', ?, 1, 'expense', 1)""",
        (date.today().isoformat(),),
    )
    conn.commit()
    conn.close()

    from jobs.recurring_templates import generate_templates_from_commitments

    result = generate_templates_from_commitments(db_path)
    assert result["created"] == 0
    # Should be 1 skipped (name exists)
    assert result["skipped"] == 1


def test_auto_creates_transaction_when_due(db_path):
    """A due template creates a transaction and advances next_due_date."""
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Netflix", amount_cents=1499,
                   due_rule="MONTHLY", next_due_date=yesterday,
                   account_id=1, category_id=2, type="expense")
    conn.close()

    from jobs.recurring_templates import run_recurring_auto_create

    result = run_recurring_auto_create(db_path)
    assert result["status"] == "ok"
    assert result["created"] == 1
    assert result["dry_run"] is False

    # Verify transaction exists
    conn2 = sqlite3.connect(str(db_path))
    tx = conn2.execute("SELECT * FROM transactions WHERE source = 'recurring'").fetchone()
    assert tx is not None
    # amount_cents is positive for expense
    assert tx[3] == 1499  # amount_cents
    assert tx[4] == "Netflix"  # payee

    # Verify instance recorded
    inst = conn2.execute("SELECT * FROM recurring_instances").fetchone()
    assert inst is not None
    assert inst[5] == "created"  # status

    # Verify next_due_date advanced
    updated = conn2.execute("SELECT next_due_date FROM recurring_templates WHERE id = 1").fetchone()
    assert updated[0] is not None
    # Should have advanced beyond yesterday (into next month)
    assert updated[0] > yesterday, f"Expected next_due_date > {yesterday}, got {updated[0]}"

    conn2.close()


def test_auto_create_deduplication(db_path):
    """Running auto-create twice doesn't create duplicates."""
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Spotify", amount_cents=1099,
                   due_rule="MONTHLY", next_due_date=yesterday,
                   account_id=1, type="expense")
    conn.close()

    from jobs.recurring_templates import run_recurring_auto_create

    # First run
    r1 = run_recurring_auto_create(db_path)
    assert r1["created"] == 1

    # Second run should create 0 — the next_due_date was advanced past today
    # so the template no longer matches the query. Dedup is proven by the fact
    # that only one transaction was created in total.
    r2 = run_recurring_auto_create(db_path)
    assert r2["created"] == 0

    # Verify only one transaction exists total
    conn2 = sqlite3.connect(str(db_path))
    tx_count = conn2.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert tx_count == 1, f"Expected 1 transaction, got {tx_count}"
    conn2.close()


def test_dry_run_does_not_create_transactions(db_path):
    """Dry run mode should report what would be created without actually doing it."""
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Dry Run Test", amount_cents=2000,
                   due_rule="MONTHLY", next_due_date=yesterday,
                   account_id=1, type="expense")
    conn.close()

    from jobs.recurring_templates import run_recurring_auto_create

    result = run_recurring_auto_create(db_path, dry_run=True)
    assert result["dry_run"] is True
    assert result["created"] == 1
    assert result["results"][0]["action"] == "dry_run_would_create"

    # No transaction should exist
    conn2 = sqlite3.connect(str(db_path))
    tx_count = conn2.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
    assert tx_count == 0

    # No instance recorded
    inst_count = conn2.execute("SELECT COUNT(*) FROM recurring_instances").fetchone()[0]
    assert inst_count == 0
    conn2.close()


def test_income_templates_create_negative_amounts(db_path):
    """Income/inflow templates should create transactions with negative amounts."""
    today = date.today()
    yesterday = (today - timedelta(days=1)).isoformat()

    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Salary", amount_cents=250000,
                   due_rule="MONTHLY", next_due_date=yesterday,
                   account_id=1, type="income")
    conn.close()

    from jobs.recurring_templates import run_recurring_auto_create

    result = run_recurring_auto_create(db_path)
    assert result["created"] == 1

    conn2 = sqlite3.connect(str(db_path))
    tx = conn2.execute("SELECT * FROM transactions WHERE source = 'recurring'").fetchone()
    assert tx is not None
    # Income should be negative (inflow)
    assert tx[3] < 0, f"Expected negative amount for income, got {tx[3]}"
    assert tx[3] == -250000
    conn2.close()


def test_lookahead_catches_upcoming_templates(db_path):
    """Templates due within the lookahead window are also processed."""
    today = date.today()
    tomorrow = (today + timedelta(days=1)).isoformat()

    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Upcoming Bill", amount_cents=5000,
                   due_rule="MONTHLY", next_due_date=tomorrow,
                   account_id=1, type="expense")
    conn.close()

    from jobs.recurring_templates import run_recurring_auto_create

    # Default lookahead is 1 day, tomorrow is within that
    result = run_recurring_auto_create(db_path)
    assert result["created"] == 1

    # Without lookahead of 0, it shouldn't catch tomorrow's
    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Future Bill", amount_cents=3000,
                   due_rule="MONTHLY", next_due_date=tomorrow,
                   account_id=1, type="expense")
    conn.close()

    result2 = run_recurring_auto_create(db_path, lookahead_days=0)
    assert result2["created"] == 0


def test_list_templates(db_path):
    """List templates includes account name and all fields."""
    conn = sqlite3.connect(str(db_path))
    _seed_template(conn, name="Test Template", amount_cents=999,
                   due_rule="WEEKLY", next_due_date=date.today().isoformat(),
                   account_id=1, type="expense")
    conn.close()

    from jobs.recurring_templates import list_templates

    templates = list_templates(db_path)
    assert len(templates) == 1
    t = templates[0]
    assert t["name"] == "Test Template"
    assert t["amount_cents"] == 999
    assert t["due_rule"] == "WEEKLY"
    assert t["account_name"] == "Current"
    assert t["auto_create"] is True
    assert t["is_active"] is True
    assert "created_at" in t
    assert "updated_at" in t
