from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional, Tuple


def _default_db_path() -> Path:
    env = os.getenv("BUDGET_DB_PATH")
    return Path(env) if env else Path("localdb/budget.db")


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _buffer_floor_cents() -> int:
    try:
        return int(os.getenv("BUFFER_FLOOR_CENTS", "0"))
    except Exception:
        return 0


def _large_debit_threshold_cents() -> int:
    try:
        return abs(int(os.getenv("LARGE_DEBIT_CENTS", "50000")))  # default $500
    except Exception:
        return 50000


def _insert_alert(
    conn: sqlite3.Connection,
    *,
    type_: str,
    dedupe_key: str,
    severity: str,
    title: str,
    message: str,
    details: Optional[Dict[str, Any]] = None,
) -> bool:
    """Insert an alert if not already present (dedup by type+key).

    Returns True if inserted, False if deduped.
    """
    created_at = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    try:
        conn.execute(
            """
            INSERT INTO alerts(created_at, type, dedupe_key, severity, title, message, details_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                type_,
                dedupe_key,
                severity,
                title,
                message,
                json.dumps(details or {}, separators=(",", ":")),
            ),
        )
        return True
    except sqlite3.IntegrityError:
        # Duplicate per unique index
        return False


def _last_two_snapshots(conn: sqlite3.Connection) -> Tuple[Optional[sqlite3.Row], Optional[sqlite3.Row]]:
    cur = conn.execute(
        """
        SELECT created_at, min_balance_cents, min_balance_date
        FROM forecast_snapshot
        ORDER BY datetime(created_at) DESC
        LIMIT 2
        """
    )
    rows = cur.fetchall()
    current = rows[0] if len(rows) >= 1 else None
    previous = rows[1] if len(rows) >= 2 else None
    return current, previous


def _iso_date(s: Any) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(str(s))
    except Exception:
        return None


def check_threshold_breach(conn: sqlite3.Connection) -> bool:
    """Create an alert when projected min balance crosses below buffer vs previous snapshot."""
    threshold = _buffer_floor_cents()
    cur, prev = _last_two_snapshots(conn)
    if not cur or threshold <= 0:
        return False

    cur_min = int(cur["min_balance_cents"]) if cur["min_balance_cents"] is not None else None
    prev_min = int(prev["min_balance_cents"]) if (prev and prev["min_balance_cents"] is not None) else None

    if cur_min is None:
        return False

    # Only alert on crossing from above/equal to below threshold
    crossed = (prev_min is not None and prev_min >= threshold and cur_min < threshold) or (
        prev_min is None and cur_min < threshold
    )
    if not crossed:
        return False

    dedupe_key = f"{threshold}:{_iso_date(cur['min_balance_date']) or ''}:{cur_min}"
    title = "Projected balance below buffer"
    msg = "Min projected balance fell below the configured buffer since the last snapshot."
    return _insert_alert(
        conn,
        type_="threshold_breach",
        dedupe_key=dedupe_key,
        severity="warning" if cur_min >= 0 else "critical",
        title=title,
        message=msg,
        details={
            "buffer_floor_cents": threshold,
            "current_min_balance_cents": cur_min,
            "current_min_balance_date": cur["min_balance_date"],
            "previous_min_balance_cents": prev_min,
        },
    )


def check_large_unplanned_debits(conn: sqlite3.Connection, *, window_hours: int = 36) -> int:
    """Create alerts for large debits in the recent window.

    Uses the `transactions` table; dedupes on the transaction idempotency_key.
    """
    threshold = _large_debit_threshold_cents()
    # SQLite datetime uses UTC strings; we compare DATE(posted_at) against a window.
    now = datetime.utcnow()
    since = now - timedelta(hours=window_hours)
    # Select recent negative transactions above threshold
    cur = conn.execute(
        """
        SELECT idempotency_key, posted_at, amount_cents, payee, memo
        FROM transactions
        WHERE datetime(posted_at) >= datetime(?) AND amount_cents < 0 AND ABS(amount_cents) >= ?
        ORDER BY datetime(posted_at) DESC
        """,
        (since.isoformat(timespec="seconds"), threshold),
    )
    created = 0
    for r in cur:
        ik = r["idempotency_key"] or f"tx@{r['posted_at']}@{r['amount_cents']}"
        title = "Large debit detected"
        amt = int(r["amount_cents"]) if r["amount_cents"] is not None else 0
        payee = r["payee"] or ""
        msg = f"A large debit of {amt/100:.2f} occurred" + (f" at {payee}." if payee else ".")
        ok = _insert_alert(
            conn,
            type_="large_debit",
            dedupe_key=str(ik),
            severity="warning",
            title=title,
            message=msg,
            details={
                "amount_cents": amt,
                "posted_at": r["posted_at"],
                "payee": payee,
                "memo": r["memo"],
                "threshold_cents": threshold,
            },
        )
        if ok:
            created += 1
    return created


def check_commitment_amount_drift(conn: sqlite3.Connection, *, months: int = 3, tolerance: float = 0.1) -> int:
    """Naive commitment drift detector by category over recent months.

    For commitments with a category_id, compute expense totals by month for the
    last `months` full months, and compare each month to the planned amount.
    If all observed months deviate by more than `tolerance` proportion, emit an alert.
    """
    # Determine target months (last `months` full calendar months)
    today = date.today().replace(day=1)
    periods: list[Tuple[date, date]] = []
    d = today
    for _ in range(months):
        # previous month start
        prev_month_end = d - timedelta(days=1)
        start = prev_month_end.replace(day=1)
        end = prev_month_end
        periods.append((start, end))
        d = start

    # For each commitment with category_id, evaluate drift
    cur = conn.execute(
        """
        SELECT id, name, amount_cents, category_id
        FROM commitments
        WHERE category_id IS NOT NULL
        """
    )
    created = 0
    for r in cur:
        cid = int(r["id"])
        cat_id = int(r["category_id"]) if r["category_id"] is not None else None
        planned = abs(int(r["amount_cents"]))
        if planned <= 0 or cat_id is None:
            continue

        # For each recent month, sum expenses in that category
        ok_months = 0
        all_deviate = True
        for start, end in periods:
            row = conn.execute(
                """
                SELECT COALESCE(SUM(amount_cents), 0) AS total
                FROM transactions
                WHERE category_id = ? AND amount_cents < 0 AND DATE(posted_at) BETWEEN ? AND ?
                """,
                (cat_id, start.isoformat(), end.isoformat()),
            ).fetchone()
            actual = abs(int(row["total"])) if row and row["total"] is not None else 0
            ok_months += 1
            # Compare amounts; if within tolerance, not drifting
            # Avoid division by zero: if planned==0 handled above
            dev_ratio = abs(actual - planned) / float(planned)
            if dev_ratio <= tolerance:
                all_deviate = False
        if ok_months == months and all_deviate:
            dedupe_key = f"commitment:{cid}:m{months}:tol{tolerance}"
            title = "Commitment amount drift detected"
            msg = (
                f"Observed monthly spend for '{r['name']}' deviates > {int(tolerance*100)}% from planned amount for {months} months."
            )
            if _insert_alert(
                conn,
                type_="commitment_drift",
                dedupe_key=dedupe_key,
                severity="info",
                title=title,
                message=msg,
                details={
                    "commitment_id": cid,
                    "planned_amount_cents": planned,
                    "months": months,
                    "tolerance": tolerance,
                },
            ):
                created += 1
    return created


def run_alert_checks(*, db_path: Optional[Path] = None) -> Dict[str, Any]:
    """Run all alert checks and persist new alerts.

    Returns counts by alert type.
    """
    dbp = db_path or _default_db_path()
    with _connect(dbp) as conn:
        # Ensure migration ran for alerts table; if not, attempts will fail.
        # It's acceptable for this to raise if migrations aren't applied yet.
        inserted_threshold = 1 if check_threshold_breach(conn) else 0
        inserted_large = check_large_unplanned_debits(conn)
        inserted_drift = check_commitment_amount_drift(conn)
        conn.commit()
        return {
            "threshold_breach": inserted_threshold,
            "large_debit": inserted_large,
            "commitment_drift": inserted_drift,
        }

