import os
import sqlite3
from pathlib import Path
from datetime import datetime, timedelta, date

from db.migrate import run_migrations
from alerts.engine import run_alert_checks


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def test_threshold_breach_alert(tmp_path: Path, monkeypatch):
    dbp = tmp_path / "budget.db"
    os.environ["BUDGET_DB_PATH"] = str(dbp)
    os.environ["BUFFER_FLOOR_CENTS"] = "10000"  # $100

    # Run migrations
    run_migrations(db_path=dbp)

    # Insert two snapshots: previous above buffer, current below
    with _connect(dbp) as conn:
        conn.execute(
            """
            INSERT INTO forecast_snapshot(created_at, horizon_start, horizon_end, json_payload, min_balance_cents, min_balance_date)
            VALUES (?,?,?,?,?,?)
            """,
            (
                (datetime.utcnow() - timedelta(hours=2)).isoformat(timespec="seconds") + "Z",
                date.today().isoformat(),
                (date.today() + timedelta(days=30)).isoformat(),
                "{}",
                20000,
                (date.today() + timedelta(days=10)).isoformat(),
            ),
        )
        conn.execute(
            """
            INSERT INTO forecast_snapshot(created_at, horizon_start, horizon_end, json_payload, min_balance_cents, min_balance_date)
            VALUES (?,?,?,?,?,?)
            """,
            (
                (datetime.utcnow() - timedelta(minutes=10)).isoformat(timespec="seconds") + "Z",
                date.today().isoformat(),
                (date.today() + timedelta(days=30)).isoformat(),
                "{}",
                5000,
                (date.today() + timedelta(days=12)).isoformat(),
            ),
        )
        conn.commit()

    counts = run_alert_checks(db_path=dbp)
    assert counts["threshold_breach"] == 1

    # Running again should dedupe
    counts = run_alert_checks(db_path=dbp)
    assert counts["threshold_breach"] == 0

    with _connect(dbp) as conn:
        row = conn.execute("SELECT COUNT(*) AS n FROM alerts WHERE type='threshold_breach'").fetchone()
        assert int(row["n"]) == 1


def test_large_debit_alert(tmp_path: Path, monkeypatch):
    dbp = tmp_path / "budget.db"
    os.environ["BUDGET_DB_PATH"] = str(dbp)
    os.environ["LARGE_DEBIT_CENTS"] = "40000"  # $400

    run_migrations(db_path=dbp)

    # Need a minimal account to satisfy FK constraints in some setups
    with _connect(dbp) as conn:
        conn.execute("INSERT INTO accounts(id, name, type, currency, is_active) VALUES (1,'Checking','checking','USD',1)")
        # Recent large debit transaction
        conn.execute(
            """
            INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, is_cleared)
            VALUES (?,?,?,?,?,?)
            """,
            (
                "ik-large-1",
                1,
                (datetime.utcnow() - timedelta(hours=1)).isoformat(timespec="seconds"),
                -60000,
                "test",
                1,
            ),
        )
        conn.commit()

    counts = run_alert_checks(db_path=dbp)
    assert counts["large_debit"] == 1

    # Dedupe on idempotency_key
    counts = run_alert_checks(db_path=dbp)
    assert counts["large_debit"] == 0


def test_commitment_drift_amount(tmp_path: Path):
    dbp = tmp_path / "budget.db"
    os.environ["BUDGET_DB_PATH"] = str(dbp)
    run_migrations(db_path=dbp)

    today = date.today().replace(day=1)
    # Helper to get last full month start/end
    def month_start_end(months_ago: int):
        d = today
        for _ in range(months_ago + 1):
            prev_end = d - timedelta(days=1)
            start = prev_end.replace(day=1)
            d = start
        end = d + timedelta(days=(d.replace(day=28) - d.replace(day=27)).days)  # not used
        prev_end = (today - timedelta(days=1)) if months_ago == 0 else (d - timedelta(days=1))
        return d, prev_end

    with _connect(dbp) as conn:
        # Minimal categories and account
        conn.execute("INSERT INTO accounts(id,name,type,currency,is_active) VALUES (1,'Chk','checking','USD',1)")
        conn.execute("INSERT INTO categories(id,name,is_archived) VALUES (1,'Internet',0)")
        # Commitment: planned $100
        conn.execute(
            "INSERT INTO commitments(id,name,amount_cents,due_rule,next_due_date,account_id,category_id,type) VALUES (1,'Internet Plan',10000,'MONTHLY',?,?,?,? , 'bill')",
            (today.isoformat(), 1, 1, 'bill'),
        )
        # For each of last 3 full months, add expenses totaling $150
        for m in range(3):
            # choose 2 transactions per month
            start, end = month_start_end(m)
            ts = datetime.combine(end, datetime.min.time()).isoformat()
            conn.execute(
                "INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, category_id, is_cleared) VALUES (?,?,?,?,?,?,1)",
                (f"ik-m{m}-a", 1, ts, -8000, 'test', 1),
            )
            conn.execute(
                "INSERT INTO transactions(idempotency_key, account_id, posted_at, amount_cents, source, category_id, is_cleared) VALUES (?,?,?,?,?,?,1)",
                (f"ik-m{m}-b", 1, ts, -7000, 'test', 1),
            )
        conn.commit()

    counts = run_alert_checks(db_path=dbp)
    assert counts["commitment_drift"] == 1

