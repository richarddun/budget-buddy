"""Daily ingestion scheduler — local DB freshness checks only.

This module has been rewritten to remove all YNAB API calls (P4.3).
Instead of fetching from YNAB, it:
- Checks freshness of the local database (last CSV import date)
- Runs nightly forecast snapshots
- Executes alert checks
- Reports data staleness

The scheduler loop shell is preserved for future re-activation as a
general data-refresh tick.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timedelta, time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from jobs.nightly_snapshot import run_nightly_snapshot_async

try:
    from alerts.engine import run_alert_checks  # type: ignore[import-untyped]
except Exception:
    run_alert_checks = None

logger = logging.getLogger("uvicorn.error")

DEFAULT_DB_PATH = Path("localdb/budget.db")
DEFAULT_STALE_AFTER_HOURS = 48


def _tz() -> ZoneInfo:
    tz_name = os.getenv("SCHED_TZ") or os.getenv("TZ") or "UTC"
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning(f"Invalid timezone '{tz_name}', falling back to UTC")
        return ZoneInfo("UTC")


def _next_run_at(hour: int, minute: int) -> datetime:
    tz = _tz()
    now = datetime.now(tz)
    today_target = datetime.combine(now.date(), time(hour=hour, minute=minute, tzinfo=tz))
    if now >= today_target:
        return today_target + timedelta(days=1)
    return today_target


def _last_import_time(db_path: Path) -> datetime | None:
    """Return the most recent CSV import timestamp from the ingest_audit table.

    Returns None if no CSV imports have been recorded or the table is missing.
    """
    if not db_path.exists():
        return None
    try:
        import sqlite3

        conn = sqlite3.connect(str(db_path))
        try:
            cur = conn.execute(
                "SELECT run_started_at FROM ingest_audit "
                "WHERE source = 'csv' OR source = 'ynab-csv' "
                "ORDER BY run_started_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            if row:
                raw = row[0]
                if raw:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        finally:
            conn.close()
    except Exception as exc:
        logger.warning(f"Could not read last import time: {exc}")
    return None


def _staleness_summary(db_path: Path) -> dict[str, Any]:
    """Return a staleness indicator dict for the local database.

    Keys:
        last_import_at: ISO timestamp or None
        hours_since_import: hours elapsed (or None)
        is_stale: True if > STALE_AFTER_HOURS since last import
        stale_threshold_hours: the configured threshold
    """
    stale_hours = int(os.getenv("STALE_AFTER_HOURS", str(DEFAULT_STALE_AFTER_HOURS)))
    last = _last_import_time(db_path)
    now = datetime.now().astimezone()
    hours_since: float | None = None
    is_stale = True

    if last is not None:
        delta = now - last
        hours_since = delta.total_seconds() / 3600
        is_stale = hours_since > stale_hours

    return {
        "last_import_at": last.isoformat() if last else None,
        "hours_since_import": round(hours_since, 1) if hours_since is not None else None,
        "is_stale": is_stale,
        "stale_threshold_hours": stale_hours,
    }


async def run_daily_ingestion(
    db_path: str | Path = DEFAULT_DB_PATH,
) -> dict[str, Any]:
    """Check database freshness, run snapshots and alert checks.

    Returns a summary dict with status, staleness info, and snapshot result.
    """
    path = Path(db_path)
    staleness = _staleness_summary(path)

    logger.info(
        f"Daily ingestion check — DB: {path} "
        f"| last import: {staleness['last_import_at']} "
        f"| stale: {staleness['is_stale']}"
    )

    # Generate a freshness label for the UI
    if staleness["last_import_at"] is None:
        freshness = "never_imported"
    elif staleness["is_stale"]:
        freshness = "stale"
    else:
        freshness = "fresh"

    # Run nightly forecast snapshot (async)
    try:
        snapshot_result = await run_nightly_snapshot_async()
    except Exception as exc:
        logger.exception(f"Nightly snapshot failed: {exc}")
        snapshot_result = {"status": "error", "reason": str(exc)}

    # Run alert checks on existing data
    try:
        if run_alert_checks is not None:
            run_alert_checks()
    except Exception as exc:
        logger.exception(f"Alert checks failed: {exc}")

    # Auto-create recurring transactions from due templates
    try:
        from jobs.recurring_templates import run_recurring_auto_create
        recurring_result = run_recurring_auto_create(path)
        if recurring_result["created"] > 0:
            logger.info(f"Auto-created {recurring_result['created']} recurring transactions")
    except Exception as exc:
        logger.exception(f"Recurring auto-create failed: {exc}")
        recurring_result = {"status": "error", "reason": str(exc)}

    return {
        "status": "ok",
        "freshness": freshness,
        "staleness": staleness,
        "snapshot": snapshot_result,
        "recurring_auto_create": recurring_result,
    }


async def scheduler_loop(hour: int = 7, minute: int = 0) -> None:
    """Simple asyncio scheduler that sleeps until the next run time, daily."""
    while True:
        run_at = _next_run_at(hour, minute)
        tz = _tz()
        now = datetime.now(tz)
        sleep_s = max(0.0, (run_at - now).total_seconds())
        logger.info(
            f"Daily ingestion scheduler — sleeping {sleep_s:.0f}s until {run_at.isoformat()}"
        )
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:
            raise

        try:
            await run_daily_ingestion()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Daily ingestion job crashed (scheduler continues)")
            # Don't break the loop — still try snapshot
        try:
            await run_nightly_snapshot_async()
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Nightly snapshot job failed (scheduler continues)")
