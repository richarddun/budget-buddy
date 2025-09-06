import os
import asyncio
import logging
from datetime import datetime, timedelta, time
from zoneinfo import ZoneInfo

from ynab_sdk_client import YNABSdkClient
from localdb import payee_db

# Optional: use the existing agent to let AI review/adjust
try:
    from agents.budget_agent import budget_agent  # type: ignore
except Exception:  # pragma: no cover
    budget_agent = None  # type: ignore

logger = logging.getLogger("uvicorn.error")


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


async def _ai_review_transactions_if_enabled(txns_text: str) -> None:
    if not os.getenv("ENABLE_DAILY_AI_REVIEW", "false").lower() in ("1", "true", "yes", "on"):  # noqa: E501
        return
    if budget_agent is None:
        logger.warning("ENABLE_DAILY_AI_REVIEW is on, but budget_agent is unavailable")
        return

    prompt = (
        "Daily review at 7:00 AM.\n"
        "You are connected to YNAB tools.\n"
        "1) Inspect the recent transactions listed below (most recent first).\n"
        "2) Identify any overspent categories or obvious mis-categorizations.\n"
        "3) If appropriate, adjust budgeted amounts for the current month to keep 'Available' non-negative in essential categories, "
        "   using update_month_category with conservative changes.\n"
        "4) Respond concisely with what you changed.\n\n"
        "Recent transactions:\n"
        f"{txns_text}\n"
    )
    try:
        # Non-streaming run; tools within agent will perform updates.
        await budget_agent.run(prompt)  # type: ignore[attr-defined]
    except Exception as e:  # pragma: no cover
        logger.exception(f"AI review failed: {e}")


async def run_daily_ingestion() -> None:
    """Fetch recent transactions and optionally let AI review/adjust budget."""
    budget_id = os.getenv("YNAB_BUDGET_ID")
    if not budget_id:
        logger.warning("YNAB_BUDGET_ID not set; skipping daily ingestion.")
        return

    client = YNABSdkClient()
    tz = _tz()
    today = datetime.now(tz).date()
    # Ingest transactions since yesterday (you can change this window)
    since_date = (today - timedelta(days=1)).isoformat()

    try:
        txns = client.get_transactions(budget_id, since_date)
        txns_text = client.slim_transactions_text(txns)
        logger.info(
            f"Daily ingestion: fetched {len(txns)} transactions since {since_date}"
        )
    except Exception as e:
        logger.exception(f"Failed to fetch transactions: {e}")
        return

    # Save locally and attempt auto-categorisation via payee rules
    for t in txns:
        payee = t.get("payee_name") or ""
        amount = float(t.get("amount", 0.0))
        date = t.get("date") or datetime.now(tz).date().isoformat()
        ynab_tx_id = t.get("id")

        match = payee_db.match_payee(payee, threshold=0.6) if payee else None
        if match:
            payee_db.record_local_transaction(
                ynab_tx_id=ynab_tx_id,
                date=date,
                payee=payee,
                amount=amount,
                matched_rule_id=match["rule_id"],
                assigned_category=match.get("suggested_category"),
                assigned_subcategory=match.get("suggested_subcategory"),
                confidence=match.get("confidence"),
                source="auto",
                notes=match.get("suggested_memo"),
            )
        else:
            payee_db.record_local_transaction(
                ynab_tx_id=ynab_tx_id,
                date=date,
                payee=payee,
                amount=amount,
                matched_rule_id=None,
                assigned_category=None,
                assigned_subcategory=None,
                confidence=None,
                source="import",
            )

    # Optional AI review pass (local-only suggestions/updates via tools)
    await _ai_review_transactions_if_enabled(txns_text)


async def scheduler_loop(hour: int = 7, minute: int = 0) -> None:
    """Simple asyncio scheduler that sleeps until the next run time, daily."""
    while True:
        run_at = _next_run_at(hour, minute)
        tz = _tz()
        now = datetime.now(tz)
        sleep_s = max(0.0, (run_at - now).total_seconds())
        logger.info(
            f"Daily scheduler sleeping {sleep_s:.0f}s until {run_at.isoformat()}"
        )
        try:
            await asyncio.sleep(sleep_s)
        except asyncio.CancelledError:  # graceful shutdown
            raise

        try:
            await run_daily_ingestion()
        except asyncio.CancelledError:
            raise
        except Exception as e:  # pragma: no cover
            logger.exception(f"Daily ingestion job crashed: {e}")
