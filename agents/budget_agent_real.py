from pydantic_ai import Agent
from pydantic import BaseModel, field_validator, model_validator
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai import Agent
import time
import asyncio
import os
from datetime import date, timedelta
from typing import Optional, Any, Dict, List
from dotenv import load_dotenv
from ynab_sdk_client import YNABSdkClient  # your wrapper
from ynab.exceptions import ApiException, BadRequestException
from urllib3.exceptions import ProtocolError
import socket
from ynab.models.post_scheduled_transaction_wrapper import PostScheduledTransactionWrapper
from ynab.models.save_scheduled_transaction import SaveScheduledTransaction
from ynab.models.patch_month_category_wrapper import PatchMonthCategoryWrapper
from ynab.models.scheduled_transaction_frequency import ScheduledTransactionFrequency
from ynab.models.transaction_flag_color import TransactionFlagColor
from ynab.models.post_transactions_wrapper import PostTransactionsWrapper
from ynab.models.save_transaction_with_optional_fields import SaveTransactionWithOptionalFields
from ynab.models.save_transaction_with_id_or_import_id import SaveTransactionWithIdOrImportId


import logging
logger = logging.getLogger("uvicorn.error")

load_dotenv()
oai_key = os.getenv("OAI_KEY", "")
budget_id_env = os.getenv("YNAB_BUDGET_ID")
if budget_id_env is None:
    logger.info("YNAB_BUDGET_ID environment variable is not set. YNAB features will be disabled.")
BUDGET_ID: str | None = budget_id_env

# --- LLM Setup ---
oai_model = OpenAIModel(
    #model_name='gpt-4.1-mini-2025-04-14',
    model_name='gpt-4.1-2025-04-14',
    
    provider=OpenAIProvider(api_key=oai_key or "")
)


today = date.today().strftime("%B %d, %Y")


budget_agent = Agent(
    model=oai_model,
system_prompt = (
    "You are a proactive budgeting assistant with specialized financial insight. "
    f"Today is {today}. When reasoning about dates, assume today's date is accurate.\n"

    "Default behavior assumptions:\n"
    "- Default account name is 'CURRENT-166' unless the user specifies another.\n"
    "- All transaction-related tools (create_transaction, delete_transaction, etc.) require **account_id** in **UUID format** — not the account name.\n"
    "- If you only have the account name, call get_accounts first to retrieve the correct UUID before proceeding.\n"

    "If the user asks for a budget review or mentions terms like 'review', 'overspent', 'missed payments', or 'flatline', "
    "immediately call get_budget_details to provide an overview.\n"

    "Budget summaries will include hints. Always call the matching tool to get full details if needed.\n"
    "For questions about specific expenses or transactions, use get_transactions, filtering by date if relevant.\n"
    "You have full access to the user's budget ID — there is no need to ask them for it.\n"

    "To create an expected upcoming transaction (e.g., a monthly bill, recurring charge), use create_scheduled_transaction. "
    "Supply account ID, date, and amount. Optionally include payee name or category. "
    "Scheduled transactions must have dates no more than 7 days in the past and no more than 5 years into the future. "
    "If unsure, default to the 1st of next month.\n"

    "You can get all scheduled transactions with get_all_scheduled_transactions.\n"

    "Use available tools freely and confidently. "
    "Avoid unnecessary repetition or redundant calls.\n"

    "If the user asks about overspending, overbudgeting, or mentions 'where am I overspending', call get_overspent_categories.\n"
    "If the user mentions modifying or canceling a scheduled payment, use update_scheduled_transaction or delete_scheduled_transaction as appropriate.\n"
    "If the user wants to log a real-world transaction, use create_transaction, using today's date if not otherwise specified.\n"
    "If the user wants to delete a real transaction, use delete_transaction.\n"

    'If the user mentions saving for something or setting a target goal (e.g., "save €500 for vacation"), call update_category.\n'
    'If the user mentions adjusting a monthly category budget (e.g., "increase groceries budget for May"), call update_month_category.\n'

    "When interpreting amounts, assume euros unless otherwise stated.\n"
    "If no month is specified, assume the current month.\n"

    "When suggesting actions, be proactive but respectful — e.g., 'Would you like me to help you log that transaction?' or 'Would you like me to update that for you?'\n"
)

)

# --- Instantiate YNAB SDK Client Once ---
client = YNABSdkClient()
from localdb import payee_db
import sqlite3
from forecast.calendar import _default_db_path
from budget_health_analyzer import BudgetHealthAnalyzer
from forecast.calendar import expand_calendar, compute_balances
from api.forecast import compute_opening_balance_cents
from q import queries as Q

# --- Tool Input Schemas and Bindings ---
class GetAccountsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_accounts(input: GetAccountsInput):
    """Get the list of accounts for a given YNAB budget."""
    logger.info(f"[TOOL] get_accounts called with budget_id={BUDGET_ID}")
    return {
        "status": "Retrieving your full budget overview...",
        "data": client.slim_accounts_text(client.get_accounts(BUDGET_ID) )
    }

class GetBudgetDetailsInput(BaseModel):
    budget_id: str

#@budget_agent.tool_plain
#def get_budget_details(input: GetBudgetDetailsInput):
#    """Fetch detailed information about a specific budget."""
#    logger.info(f"[TOOL] get_budget_details called with budget_id={BUDGET_ID}")
#    return client.get_budget_details(BUDGET_ID)

@budget_agent.tool_plain
def get_budget_details(input: GetBudgetDetailsInput):
    logger.info(f"[TOOL] get_budget_details called with budget_id={BUDGET_ID}")
    
    budget = client.get_budget_details(BUDGET_ID)
    name = budget.get('name', 'Unknown')
    first_month = budget.get('first_month', 'Unknown')
    last_month = budget.get('last_month', 'Unknown')
    currency = budget.get('currency_format', {}).get('iso_code', 'EUR')

    id = budget.get('id', 'Unkown')
    
    summary = (
        f"Budget Name: {name}\n"
        f"From: {first_month} to {last_month}\n"
        f"Currency: {currency}\n\n"
        "This budget contains the following account IDs :\n"
        ''.join([f"Account Name:{x['name']} - Account ID: {x['id']}, " for x in budget['accounts']])+"\n\n"
        "Detailed sections:\n"
        "- To view account balances, call `get_accounts`.\n"
        "- To view recent transactions, call `get_transactions`.\n"
        "- To view your categories and budgets, call `get_categories`.\n"
        "- To check upcoming scheduled payments, call `get_all_scheduled_transactions`.\n"
    )
    
    return {
        "status": "Here's a high-level overview of your budget.",
        "data": summary
    }


class GetTransactionsInput(BaseModel):
    budget_id: str
    since_date: str | None = None

@budget_agent.tool_plain
def get_transactions(input: GetTransactionsInput):
    try:
        logger.info(f"[TOOL] get_transactions called with budget_id={BUDGET_ID}, since_date={input.since_date}")
        return {
            "status": "Fetching transaction history...",
            "data": client.slim_transactions_text(client.get_transactions(BUDGET_ID, input.since_date))
        }
    except (ApiException, ProtocolError, socket.timeout, ConnectionError) as e:
        logger.warning(f"[TOOL ERROR] Network failure: {e}")
        return {
            "error": "Network issue while contacting YNAB. You can try again shortly.",
        }


#@budget_agent.tool_plain
#def get_transactions(input: GetTransactionsInput):
#    try:
#        logger.info(f"[TOOL] get_transactions called with budget_id={BUDGET_ID}, since_date={input.since_date}")
#        return client.get_transactions(BUDGET_ID, input.since_date)
#    except (ApiException, ProtocolError, socket.timeout, ConnectionError) as e:
#        logger.warning(f"[TOOL ERROR] Network failure: {e}")
#        return {
#            "error": "There was a network issue contacting the YNAB API. The remote connection was closed unexpectedly. You may try again shortly or ask to continue later."
#        }

# --- Key Events Tools ---
class AddKeyEventInput(BaseModel):
    name: str
    event_date: date
    planned_amount_eur: float | None = None
    repeat_rule: str | None = None
    category_id: int | None = None
    lead_time_days: int | None = None
    shift_policy: str | None = "AS_SCHEDULED"  # AS_SCHEDULED | PREV_BUSINESS_DAY | NEXT_BUSINESS_DAY
    account_id: int | None = None


@budget_agent.tool_plain
def add_key_event(input: AddKeyEventInput):
    """Add a key spending event for the runway forecast. Accepts name, date, optional amount (EUR), repeat_rule, lead_time_days, shift_policy, category_id, account_id."""
    dbp = _default_db_path()
    amt_cents = None if input.planned_amount_eur is None else int(round(float(input.planned_amount_eur) * 100))
    with sqlite3.connect(dbp) as conn:
        cur = conn.execute(
            """
            INSERT INTO key_spend_events(name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id)
            VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                input.name.strip(),
                input.event_date.isoformat(),
                input.repeat_rule,
                amt_cents,
                input.category_id,
                input.lead_time_days,
                (input.shift_policy or "AS_SCHEDULED").strip().upper(),
                input.account_id,
            ),
        )
        event_id = int(cur.lastrowid)
        row = conn.execute(
            "SELECT id, name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id FROM key_spend_events WHERE id = ?",
            (event_id,),
        ).fetchone()
    return {
        "status": "key_event_saved",
        "event": {
            "id": int(row[0]),
            "name": row[1],
            "event_date": row[2],
            "repeat_rule": row[3],
            "planned_amount_cents": int(row[4]) if row[4] is not None else None,
            "category_id": int(row[5]) if row[5] is not None else None,
            "lead_time_days": int(row[6]) if row[6] is not None else None,
            "shift_policy": row[7],
            "account_id": int(row[8]) if row[8] is not None else None,
        },
    }


class DeleteKeyEventInput(BaseModel):
    id: int


@budget_agent.tool_plain
def delete_key_event(input: DeleteKeyEventInput):
    """Delete a key spending event by id."""
    dbp = _default_db_path()
    with sqlite3.connect(dbp) as conn:
        cur = conn.execute("DELETE FROM key_spend_events WHERE id = ?", (int(input.id),))
        deleted = cur.rowcount
    if deleted == 0:
        return {"status": "not_found", "id": int(input.id)}
    return {"status": "deleted", "id": int(input.id)}


# --- Commitments Tools ---
class AddCommitmentInput(BaseModel):
    name: str
    # Accept multiple forms for amount; prefer amount_eur but tolerate amount or amount_cents
    amount_eur: float | None = None
    amount: float | None = None
    amount_cents: int | None = None
    due_rule: str = "MONTHLY"  # e.g., MONTHLY, WEEKLY, ONE_OFF
    next_due_date: date
    # Accept local account id (int) or YNAB UUID string for convenience; also optional name fallback
    account_id: int | str | None = None
    account_uuid: str | None = None
    account_name: str | None = None
    priority: int | None = 1
    flexible_window_days: int | None = 0
    category_id: int | None = None
    type: str = "bill"  # e.g., bill, rent, mortgage, loan, utility

    @field_validator('amount_eur', mode='before')
    @classmethod
    def _parse_amount_eur(cls, v):
        if v is None:
            return None
        if isinstance(v, (int, float)):
            return float(v)
        try:
            cleaned = str(v).replace("€", "").replace(",", "").strip()
            return float(cleaned)
        except Exception:
            return None

    @model_validator(mode='before')
    @classmethod
    def _coerce_amount_fields(cls, data: dict):
        # If amount_eur not provided, fall back to amount or amount_cents
        if data.get('amount_eur') is None:
            if data.get('amount') is not None:
                data['amount_eur'] = data.get('amount')
            elif data.get('amount_cents') is not None:
                try:
                    data['amount_eur'] = float(data.get('amount_cents')) / 100.0
                except Exception:
                    pass
        return data


@budget_agent.tool_plain
def add_commitment(input: AddCommitmentInput):
    """Add a recurring commitment (e.g., rent, mortgage, utilities). Amount in EUR, stored as integer cents. Defaults: MONTHLY, AS PREV_BUSINESS_DAY shift is applied by forecast engine.

    Accepts amount_eur, or amount, or amount_cents; also accepts account_id (local int), account_uuid (YNAB UUID), or account_name.
    """
    dbp = _default_db_path()
    if input.amount_eur is None:
        return {"error": "amount_eur_missing", "hint": "Provide amount_eur (e.g., 1200.00) or 'amount' or 'amount_cents'."}
    amt_cents = int(round(float(input.amount_eur) * 100))
    # Resolve account: supports local int id, YNAB UUID, or account name
    acct_id: int | None = None
    with sqlite3.connect(dbp) as conn:
        conn.row_factory = sqlite3.Row
        def _ensure_local_account_by_name(name: str, type_: str | None = None, currency: str | None = None) -> int:
            r = conn.execute("SELECT id FROM accounts WHERE name = ?", (name,)).fetchone()
            if r:
                return int(r["id"])
            conn.execute(
                "INSERT INTO accounts(name, type, currency, is_active) VALUES (?,?,?,1)",
                (name, type_ or "depository", currency or "USD"),
            )
            return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])

        # If explicit local id provided as int
        if isinstance(input.account_id, int):
            acct_id = int(input.account_id)
        # If UUID string provided via account_id or account_uuid, resolve using YNAB and upsert by name
        uuid = None
        if isinstance(input.account_id, str):
            uuid = input.account_id
        if input.account_uuid and not uuid:
            uuid = input.account_uuid
        if uuid:
            try:
                accts = client.get_accounts(BUDGET_ID)  # type: ignore[arg-type]
            except Exception:
                accts = []
            match = None
            for a in accts or []:
                if str(a.get("id")) == str(uuid):
                    match = a
                    break
            if match:
                name = match.get("name") or f"YNAB {str(uuid)[:8]}"
                type_ = match.get("type") or "depository"
                currency = match.get("currency") or match.get("currency_code") or "USD"
                acct_id = _ensure_local_account_by_name(name, type_, currency)
        # If still unresolved and we have a name
        if acct_id is None and input.account_name:
            acct_id = _ensure_local_account_by_name(input.account_name)
        # Fallback: first active account or create a default one
        if acct_id is None:
            row = conn.execute("SELECT id FROM accounts WHERE is_active = 1 ORDER BY id LIMIT 1").fetchone()
            acct_id = int(row["id"]) if row else _ensure_local_account_by_name("Checking")
        cur = conn.execute(
            """
            INSERT INTO commitments(name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type)
            VALUES (?,?,?,?,?,?,?,?,?)
            """,
            (
                input.name.strip(),
                amt_cents,
                input.due_rule.strip().upper(),
                input.next_due_date.isoformat(),
                int(input.priority) if input.priority is not None else None,
                int(acct_id),
                int(input.flexible_window_days) if input.flexible_window_days is not None else None,
                int(input.category_id) if input.category_id is not None else None,
                input.type.strip().lower(),
            ),
        )
        cid = int(cur.lastrowid)
        row = conn.execute(
            "SELECT id, name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type FROM commitments WHERE id = ?",
            (cid,),
        ).fetchone()
    return {
        "status": "commitment_saved",
        "commitment": {k: (int(row[k]) if isinstance(row[k], (int,)) or (row[k] is not None and str(row[k]).isdigit()) else row[k]) for k in row.keys()}
    }


class DeleteCommitmentInput(BaseModel):
    id: int


@budget_agent.tool_plain
def delete_commitment(input: DeleteCommitmentInput):
    """Delete a commitment by id."""
    dbp = _default_db_path()
    with sqlite3.connect(dbp) as conn:
        cur = conn.execute("DELETE FROM commitments WHERE id = ?", (int(input.id),))
        deleted = cur.rowcount
    if deleted == 0:
        return {"status": "not_found", "id": int(input.id)}
    return {"status": "deleted", "id": int(input.id)}


class DetectCommitmentCandidatesInput(BaseModel):
    min_confidence: int | None = 60
    min_avg_amount_eur: float | None = 10.0
    limit: int | None = 10


@budget_agent.tool_plain
def detect_commitment_candidates(input: DetectCommitmentCandidatesInput):
    """Identify likely recurring commitments (mortgage, rent, loans, utilities) from recent transactions and return candidates without writing.

    Uses a lenient subscription detector and recurring-pattern helper to estimate day-of-month.
    """
    analyzer = BudgetHealthAnalyzer(BUDGET_ID)
    analyzer._load_data()
    subs = analyzer.detect_subscriptions_and_scheduled_payments()
    rec = analyzer._detect_recurring_transactions()
    # Map payee -> most_common_day when available
    dom_map: dict[str, int] = {}
    for r in rec:
        n = (r.get('payee_name') or '').strip()
        if n and isinstance(r.get('most_common_day'), int):
            dom_map[n] = int(r['most_common_day'])

    KEYWORDS = [
        'mortgage', 'rent', 'loan', 'internet', 'broadband', 'fiber', 'wifi',
        'electric', 'power', 'gas', 'water', 'utility', 'utilities', 'phone', 'mobile', 'cable'
    ]

    def classify_type(name: str) -> str:
        s = name.lower()
        if 'mortgage' in s:
            return 'mortgage'
        if 'rent' in s:
            return 'rent'
        if 'loan' in s:
            return 'loan'
        if any(k in s for k in ['electric','power','gas','water','utility','utilities']):
            return 'utility'
        if any(k in s for k in ['internet','broadband','fiber','wifi','phone','mobile','cable']):
            return 'utility'
        return 'bill'

    out = []
    for s in subs:
        name = s.get('payee_name') or ''
        if not name:
            continue
        amount = float(s.get('avg_amount') or 0.0)
        conf = int(s.get('confidence_score') or 0)
        if input.min_avg_amount_eur is not None and amount < float(input.min_avg_amount_eur):
            continue
        if input.min_confidence is not None and conf < int(input.min_confidence):
            continue
        if not any(k in name.lower() for k in KEYWORDS):
            # Keep high-confidence, high-amount subscriptions even if keywords not matched
            if conf < 80 or amount < 20:
                continue
        dom = dom_map.get(name)
        out.append({
            "name": name,
            "amount_eur": round(amount, 2),
            "due_rule": "MONTHLY",
            "suggested_day_of_month": dom,
            "type": classify_type(name),
        })

    out.sort(key=lambda x: (x.get('amount_eur', 0), x.get('name','')), reverse=True)
    if input.limit:
        out = out[: int(input.limit)]
    return {"candidates": out, "note": "Use add_commitment to save specific items."}


# --- Listing Tools (readability) ---
class ListKeyEventsInput(BaseModel):
    from_date: date | None = None
    to_date: date | None = None


@budget_agent.tool_plain
def list_key_events(input: ListKeyEventsInput):
    """List existing key spending events, optionally filtered by from/to dates (inclusive)."""
    dbp = _default_db_path()
    where = []
    params: list = []
    if input.from_date:
        where.append("DATE(event_date) >= ?")
        params.append(input.from_date.isoformat())
    if input.to_date:
        where.append("DATE(event_date) <= ?")
        params.append(input.to_date.isoformat())
    sql = (
        "SELECT id, name, event_date, repeat_rule, planned_amount_cents, category_id, lead_time_days, shift_policy, account_id "
        "FROM key_spend_events"
    )
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY DATE(event_date) ASC, id ASC"
    rows = []
    with sqlite3.connect(dbp) as conn:
        conn.row_factory = sqlite3.Row
        for r in conn.execute(sql, params):
            rows.append(
                {
                    "id": int(r["id"]),
                    "name": r["name"],
                    "event_date": r["event_date"],
                    "repeat_rule": r["repeat_rule"],
                    "planned_amount_cents": int(r["planned_amount_cents"]) if r["planned_amount_cents"] is not None else None,
                    "category_id": int(r["category_id"]) if r["category_id"] is not None else None,
                    "lead_time_days": int(r["lead_time_days"]) if r["lead_time_days"] is not None else None,
                    "shift_policy": r["shift_policy"],
                    "account_id": int(r["account_id"]) if r["account_id"] is not None else None,
                }
            )
    return {"items": rows, "count": len(rows)}


class ListCommitmentsInput(BaseModel):
    type: str | None = None  # bill, rent, mortgage, loan, utility, etc.


@budget_agent.tool_plain
def list_commitments(input: ListCommitmentsInput):
    """List commitments. Optionally filter by type (case-insensitive)."""
    dbp = _default_db_path()
    rows = []
    with sqlite3.connect(dbp) as conn:
        conn.row_factory = sqlite3.Row
        if input.type:
            cur = conn.execute(
                "SELECT id, name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type FROM commitments WHERE LOWER(type) = LOWER(?) ORDER BY id",
                (input.type.strip(),),
            )
        else:
            cur = conn.execute(
                "SELECT id, name, amount_cents, due_rule, next_due_date, priority, account_id, flexible_window_days, category_id, type FROM commitments ORDER BY id"
            )
        for r in cur:
            rows.append({k: (int(r[k]) if isinstance(r[k], (int,)) or (r[k] is not None and str(r[k]).isdigit()) else r[k]) for k in r.keys()})
    return {"items": rows, "count": len(rows)}


# --- Forecast/Overview Tools ---
class ForecastCalendarInput(BaseModel):
    start: date
    end: date
    buffer_floor_cents: int | None = 0
    accounts: list[int] | None = None


@budget_agent.tool_plain
def forecast_calendar(input: ForecastCalendarInput):
    """Compute deterministic calendar forecast between start and end using local DB, returning opening, balances, entries, and min balance/date."""
    dbp = _default_db_path()
    opening_as_of = input.start - timedelta(days=1)
    acc_set = set(input.accounts) if input.accounts else None
    opening = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp, accounts=acc_set)
    entries = expand_calendar(input.start, input.end, db_path=dbp, accounts=acc_set)
    balances = compute_balances(opening, entries)
    min_balance_cents = None
    min_balance_date = None
    if balances:
        for d in sorted(balances.keys()):
            if min_balance_cents is None or balances[d] < min_balance_cents:
                min_balance_cents = balances[d]
                min_balance_date = d
    return {
        "opening_balance_cents": int(opening),
        "balances": {d.isoformat(): int(v) for d, v in balances.items()},
        "entries": [
            {
                "date": e.date.isoformat(),
                "type": e.type,
                "name": e.name,
                "amount_cents": int(e.amount_cents),
                "source_id": int(e.source_id),
                "shift_applied": bool(e.shift_applied),
                "policy": e.policy,
            }
            for e in entries
        ],
        "min_balance_cents": int(min_balance_cents) if min_balance_cents is not None else None,
        "min_balance_date": min_balance_date.isoformat() if min_balance_date else None,
    }


class ForecastHistoryInput(BaseModel):
    start: date
    end: date
    accounts: list[int] | None = None


@budget_agent.tool_plain
def forecast_history(input: ForecastHistoryInput):
    """Return ledger-based balances between start and end (cleared transactions, active accounts)."""
    from api.forecast import _ledger_daily_deltas  # reuse tested helper
    dbp = _default_db_path()
    opening_as_of = input.start - timedelta(days=1)
    acc_set = set(input.accounts) if input.accounts else None
    opening = compute_opening_balance_cents(as_of=opening_as_of, db_path=dbp, accounts=acc_set)
    # Build deltas via helper, with account filter path when provided
    conn = sqlite3.connect(dbp)
    conn.row_factory = sqlite3.Row
    try:
        if acc_set:
            qmarks = ",".join(["?"] * len(acc_set))
            rows = conn.execute(
                f"""
                SELECT DATE(t.posted_at) AS d, COALESCE(SUM(t.amount_cents), 0) AS delta
                FROM transactions t
                JOIN accounts a ON a.id = t.account_id
                WHERE a.is_active = 1 AND t.is_cleared = 1
                  AND a.id IN ({qmarks})
                  AND DATE(t.posted_at) >= ? AND DATE(t.posted_at) <= ?
                GROUP BY DATE(t.posted_at)
                ORDER BY DATE(t.posted_at)
                """,
                (*[int(x) for x in sorted(acc_set)], input.start.isoformat(), input.end.isoformat()),
            ).fetchall()
            deltas = {date.fromisoformat(str(r["d"])): int(r["delta"]) for r in rows}
        else:
            deltas = _ledger_daily_deltas(conn, input.start, input.end)
    finally:
        conn.close()

    balances = {}
    running = int(opening)
    d = input.start
    while d <= input.end:
        running = running + int(deltas.get(d, 0))
        balances[d.isoformat()] = running
        d = d + timedelta(days=1)
    return {
        "opening_balance_cents": int(opening),
        "balances": balances,
        "meta": {"source": "ledger", "accounts": sorted(list(acc_set)) if acc_set else None},
    }


class OverviewDigestInput(BaseModel):
    pass


@budget_agent.tool_plain
def overview_digest(input: OverviewDigestInput):
    """Return the overview digest (current balance, safe-to-spend today, health score)."""
    from api.overview import get_overview_digest
    return get_overview_digest()


# --- Q (Query) Tools ---
class QMonthlyByCategoryInput(BaseModel):
    start: date
    end: date
    category_id: int | None = None
    category: str | None = None


@budget_agent.tool_plain
def q_monthly_total_by_category(input: QMonthlyByCategoryInput):
    return Q.monthly_total_by_category(input.start, input.end, category_id=input.category_id, category=input.category)


@budget_agent.tool_plain
def q_monthly_average_by_category(input: QMonthlyByCategoryInput):
    return Q.monthly_average_by_category(input.start, input.end, category_id=input.category_id, category=input.category)


class QWindowInput(BaseModel):
    start: date
    end: date


@budget_agent.tool_plain
def q_subscriptions(input: QWindowInput):
    return Q.subscriptions(input.start, input.end)


@budget_agent.tool_plain
def q_category_breakdown(input: QWindowInput):
    return Q.category_breakdown(input.start, input.end)


class QSupportingTransactionsInput(BaseModel):
    start: date
    end: date
    category_id: int | None = None
    category: str | None = None
    page: int = 1
    page_size: int = 50


@budget_agent.tool_plain
def q_supporting_transactions(input: QSupportingTransactionsInput):
    return Q.supporting_transactions(
        input.start, input.end,
        category_id=input.category_id, category=input.category,
        page=input.page, page_size=input.page_size,
    )


class QNoInput(BaseModel):
    pass


@budget_agent.tool_plain
def q_active_loans(input: QNoInput):
    return Q.active_loans()


@budget_agent.tool_plain
def q_household_fixed_costs(input: QNoInput):
    return Q.household_fixed_costs()


class QPackInput(BaseModel):
    pack: str
    period: str | None = None


@budget_agent.tool_plain
def q_pack(input: QPackInput):
    from q.packs import assemble_pack
    return assemble_pack(input.pack, input.period)

class GetAllScheduledTransactionsInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_all_scheduled_transactions(input: GetAllScheduledTransactionsInput):
    """Retrieve a list of all scheduled transactions from the budget.  Useful to see upcoming costs"""
    logger.info(f"[TOOL] get_all_scheduled_transactions called with budget_id={BUDGET_ID}")
    return {
        "status": "Checking scheduled transactions...",
        "data": client.slim_scheduled_transactions_text(client.get_scheduled_transactions(BUDGET_ID))
    }

class CreateScheduledTransactionInput(BaseModel):
    account_id: str
    var_date: date
    amount_eur: float  # now type-safe, thanks to validator
    frequency: str = "monthly"
    payee_id: Optional[str] = None
    payee_name: Optional[str] = None
    category_id: Optional[str] = None
    memo: Optional[str] = None
    flag_color: Optional[str] = None

    @field_validator('amount_eur', mode='before')
    @classmethod
    def parse_amount_eur(cls, v):
        if isinstance(v, (int, float)):
            return float(v)
        try:
            cleaned = str(v).replace("€", "").replace(",", "").strip()
            return float(cleaned)
        except Exception as e:
            raise ValueError(f"Could not parse amount_eur: {v} ({e})")


@budget_agent.tool_plain
def create_scheduled_transaction(input: CreateScheduledTransactionInput):
    """Create a scheduled transaction for a future recurring payment or event. Frequency, amount, date and account are required."""
    logger.info(f"[TOOL] Creating scheduled transaction on account {input.account_id} for €{input.amount_eur} on {input.var_date}")

    amount_milliunits = int(input.amount_eur * 1000)
    
    # Map string frequency to enum value
    frequency_map = {
        "monthly": ScheduledTransactionFrequency.MONTHLY,
        "weekly": ScheduledTransactionFrequency.WEEKLY,
        "yearly": ScheduledTransactionFrequency.YEARLY,
        "every_other_month": ScheduledTransactionFrequency.EVERYOTHERMONTH,
        "every_other_week": ScheduledTransactionFrequency.EVERYOTHERWEEK,
        "every_4_weeks": ScheduledTransactionFrequency.EVERY4WEEKS,
        "twice_a_month": ScheduledTransactionFrequency.TWICEAMONTH,
        "daily": ScheduledTransactionFrequency.DAILY,
        "never": ScheduledTransactionFrequency.NEVER
    }
    
    # Default to monthly if not found
    frequency_enum = frequency_map.get(input.frequency.lower(), ScheduledTransactionFrequency.MONTHLY)
    # Handle flag color enum conversion
    flag_color_enum = None
    if input.flag_color:
        # Common flag colors in YNAB are: red, orange, yellow, green, blue, purple
        flag_color_map = {
            "red": TransactionFlagColor.RED,
            "orange": TransactionFlagColor.ORANGE,
            "yellow": TransactionFlagColor.YELLOW,
            "green": TransactionFlagColor.GREEN,
            "blue": TransactionFlagColor.BLUE,
            "purple": TransactionFlagColor.PURPLE
        }
        flag_color_enum = flag_color_map.get(input.flag_color.lower())
    
    detail = SaveScheduledTransaction(
        account_id=input.account_id,
        date=input.var_date,
        amount=amount_milliunits,
        payee_id=input.payee_id,
        payee_name=input.payee_name,
        category_id=input.category_id,
        memo=input.memo,
        flag_color=flag_color_enum,
        frequency=frequency_enum
    )
    wrapper = PostScheduledTransactionWrapper(scheduled_transaction=detail)
    try:
        response: Any = client.create_scheduled_transaction(BUDGET_ID, wrapper)
    except BadRequestException as e:
        logger.warning(f"[TOOL ERROR] YNAB rejected scheduled transaction: {e}")
        logger.warning(f"[TOOL ERROR] Payload was: {wrapper.to_dict()}")
        return {
    "status": "Attempt to create scheduled transaction failed.",
    "error": "YNAB rejected the scheduled transaction — the date may be out of range. Please confirm the date is no more than 7 days in the past and not more than 5 years into the future."
}
    return {
    "status": "Scheduled transaction created successfully!",
    "data": response.to_dict() if hasattr(response, 'to_dict') else response
} 

class GetOverspentCategoriesInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_overspent_categories(input: GetOverspentCategoriesInput):
    """List all categories that have been overspent this month."""
    logger.info(f"[TOOL] get_overspent_categories called with budget_id={BUDGET_ID}")
    
    categories = client.get_categories(BUDGET_ID)
    overspent = []

    for cat_group in categories:
        for cat in cat_group.get("categories", []):
            if cat.get("activity", 0) < 0 and cat.get("balance", 0) < 0:
                overspent.append(
                    f"{cat['name']}: {cat.get('balance_display', 'unknown')} spent {cat.get('activity_display', 'unknown')} (id: {cat.get('id', 'missing_id')})"
                )

    overspent_text = "\n".join(overspent) if overspent else "No categories are overspent! 🎉"

    return {
        "status": f"Found {len(overspent)} overspent categories.",
        "data": overspent_text
    }

class UpdateScheduledTransactionInput(BaseModel):
    account_id: str
    scheduled_transaction_id: str
    amount_eur: Optional[float] = None
    memo: Optional[str] = None
    var_date: Optional[date] = None

@budget_agent.tool_plain
def update_scheduled_transaction(input: UpdateScheduledTransactionInput):
    """Update amount, memo, or date for an existing scheduled transaction. Account ID (uid, not account name) is required """
    logger.info(f"[TOOL] update_scheduled_transaction called for ID {input.scheduled_transaction_id}")

    try:
        from ynab.models.put_scheduled_transaction_wrapper import PutScheduledTransactionWrapper
        from ynab.models.save_scheduled_transaction import SaveScheduledTransaction

        kwargs = {}
        if input.account_id is None:
            return {"error": "the account ID, a UID, not account name, is required"}
        kwargs['account_id'] = input.account_id
        if input.amount_eur is not None:
            kwargs['amount'] = int(input.amount_eur * 1000)

        if input.memo is not None:
            kwargs['memo'] = input.memo

        if input.var_date is not None:
            if input.var_date > date.today() + timedelta(days=5*365):
                return {
                    "error": "Scheduled transaction date must be within 5 years from today."
                }
            kwargs['var_date'] = input.var_date.isoformat()

        if not kwargs:
            return {"error": "No fields provided to update. Specify amount, memo, or date."}

        update_detail = SaveScheduledTransaction(**kwargs)
        wrapper = PutScheduledTransactionWrapper(scheduled_transaction=update_detail)

        updated = client.scheduled_transactions_api.update_scheduled_transaction(
            BUDGET_ID,
            input.scheduled_transaction_id,
            wrapper
        )

        return {
            "status": "Scheduled transaction updated successfully.",
            "data": updated.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to update scheduled transaction: {e}")
        return {"error": "Unable to update the scheduled transaction."}



class DeleteScheduledTransactionInput(BaseModel):
    scheduled_transaction_id: str

@budget_agent.tool_plain
def delete_scheduled_transaction(input: DeleteScheduledTransactionInput):
    """Delete an existing scheduled transaction."""
    logger.info(f"[TOOL] delete_scheduled_transaction called for ID {input.scheduled_transaction_id}")

    try:
        client.scheduled_transactions_api.delete_scheduled_transaction(BUDGET_ID, input.scheduled_transaction_id)
        return {
            "status": "Scheduled transaction deleted successfully."
        }
    except Exception as e:
        logger.error(f"Failed to delete scheduled transaction: {e}")
        return {"error": "Unable to delete the scheduled transaction."}

class CreateTransactionInput(BaseModel):
    account_id: str
    date: date
    amount_eur: float
    payee_name: Optional[str] = None
    memo: Optional[str] = None
    cleared: str = "cleared"  # or "uncleared"

@budget_agent.tool_plain
def create_transaction(input: CreateTransactionInput):
    """Log a new real-world transaction into the budget. Requires account_id UUID, not account name."""
    logger.info(f"[TOOL] create_transaction called for account {input.account_id} on {input.date}")

    # 🔥 Validate and auto-fix account_id if needed
    if "-" not in input.account_id:
        logger.warning("[TOOL] Provided account_id does not look like a UUID. Attempting lookup...")
        accounts = client.get_accounts(BUDGET_ID)
        matching_account = next((acct for acct in accounts if acct.get("name") == input.account_id), None) # type: ignore
        if matching_account:
            input.account_id = matching_account["id"] # type: ignore
            logger.info(f"[TOOL] Matched account name to UUID: {input.account_id}")
        else:
            logger.error(f"[TOOL ERROR] No account found matching name {input.account_id}")
            return {"error": f"No account found matching name {input.account_id}. Please check your account names."}

    amount_milliunits = int(input.amount_eur * 1000)

    transaction = {
        "transaction": {
            "account_id": input.account_id,
            "date": input.date.isoformat(),
            "amount": amount_milliunits,
            "payee_name": input.payee_name,
            "memo": input.memo,
            "cleared": input.cleared
        }
    }

    try:
        created = client.transactions_api.create_transaction(BUDGET_ID, transaction) #type: ignore
        return {
            "status": "Transaction created successfully.",
            "data": created.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to create transaction: {e}")
        return {"error": "Unable to create the transaction."}



class DeleteTransactionInput(BaseModel):
    transaction_id: str

@budget_agent.tool_plain
def delete_transaction(input: DeleteTransactionInput):
    """Delete an existing real-world transaction."""
    logger.info(f"[TOOL] delete_transaction called for transaction ID {input.transaction_id}")

    try:
        client.transactions_api.delete_transaction(BUDGET_ID, input.transaction_id)
        return {
            "status": "Transaction deleted successfully."
        }
    except Exception as e:
        logger.error(f"Failed to delete transaction: {e}")
        return {"error": "Unable to delete the transaction."}

class GetCategoriesInput(BaseModel):
    budget_id: str

@budget_agent.tool_plain
def get_categories(input: GetCategoriesInput):
    """Retrieve all categories grouped by their group name."""
    logger.info(f"[TOOL] get_categories called with budget_id={BUDGET_ID}")
    return {
        "status": "Fetching list of categories...",
        "data": client.slim_categories_text(client.get_categories(BUDGET_ID))
    }

# --- Local Payee Knowledge Tools ---

class MatchLocalPayeeInput(BaseModel):
    raw_payee: str
    threshold: float | None = 0.6


@budget_agent.tool_plain
def match_local_payee(input: MatchLocalPayeeInput):
    """Search local payee rules for a best match and suggested category. Uses exact, icontains, then regex with confidence scoring."""
    try:
        res = payee_db.match_payee(input.raw_payee, threshold=input.threshold or 0.6)
        if not res:
            return {"status": "no-match", "message": "No local rule matched above threshold"}
        return {"status": "match", "data": res}
    except Exception as e:
        logger.error(f"match_local_payee failed: {e}")
        return {"error": "Local payee match failed"}


class UpsertLocalPayeeRuleInput(BaseModel):
    pattern: str
    match_type: str = "icontains"  # exact|icontains|regex
    suggested_category: str | None = None
    suggested_subcategory: str | None = None
    suggested_memo: str | None = None
    confidence: float | None = 0.8


@budget_agent.tool_plain
def upsert_local_payee_rule(input: UpsertLocalPayeeRuleInput):
    """Create or update a local payee rule mapping a pattern to a suggested category/subcategory/memo."""
    try:
        rule_id = payee_db.upsert_rule(
            pattern=input.pattern,
            match_type=input.match_type,
            suggested_category=input.suggested_category,
            suggested_subcategory=input.suggested_subcategory,
            suggested_memo=input.suggested_memo,
            confidence=input.confidence or 0.8,
        )
        return {"status": "ok", "rule_id": rule_id}
    except Exception as e:
        logger.error(f"upsert_local_payee_rule failed: {e}")
        return {"error": "Failed to upsert local payee rule"}


class RecordLocalFeedbackInput(BaseModel):
    raw_payee: str
    chosen_category: str | None = None
    chosen_subcategory: str | None = None
    memo: str | None = None
    generalize: bool | None = False
    confidence: float | None = 0.9


@budget_agent.tool_plain
def record_local_feedback(input: RecordLocalFeedbackInput):
    """Record user feedback by creating/updating a local rule (exact match by default, generalized 'icontains' if requested)."""
    try:
        rule_id = payee_db.record_feedback(
            raw_payee=input.raw_payee,
            chosen_category=input.chosen_category,
            chosen_subcategory=input.chosen_subcategory,
            memo=input.memo,
            generalize=bool(input.generalize),
            confidence=input.confidence or 0.9,
        )
        return {"status": "ok", "rule_id": rule_id}
    except Exception as e:
        logger.error(f"record_local_feedback failed: {e}")
        return {"error": "Failed to record feedback"}

class GetCategoryByIdInput(BaseModel):
    budget_id: str
    category_id: str

@budget_agent.tool_plain
def get_category_by_id(input: GetCategoryByIdInput):
    """Fetch details for a single category."""
    logger.info(f"[TOOL] get_category_by_id called with category_id={input.category_id}")
    return {
        "status": f"Retrieving category {input.category_id}...",
        "data": client.get_category_by_id(BUDGET_ID, input.category_id)
    }


class UpdateCategoryInput(BaseModel):
    category_id: str
    budgeted_amount_eur: float
    goal_type: Optional[str] = None  # e.g., "TB", "TBD", "MF", "NEED"
    goal_target: Optional[float] = None  # Amount in euros

@budget_agent.tool_plain
def update_category(input: UpdateCategoryInput):
    """Update the target or type of a category (e.g., setting a savings goal)."""
    logger.info(f"[TOOL] update_category called for {input.category_id}")

    data = {
        "category": {
               "budgeted": int(input.budgeted_amount_eur * 1000)  # Convert to milliunits
        }
    }

    if input.goal_type:
        data["category"]["goal_type"] = input.goal_type #type: ignore
    if input.goal_target is not None:
        # Convert euros to milliunits
        data["category"]["goal_target"] = int(input.goal_target * 1000)

    try:
        response = client.update_category(BUDGET_ID, input.category_id, data)
        return {
            "status": "Category updated successfully!",
            "data": response.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to update category: {e}")
        return {"error": "Unable to update the category."}


class UpdateMonthCategoryInput(BaseModel):
    category_id: str
    month: date
    budgeted_amount_eur: float

@budget_agent.tool_plain
def update_month_category(input: UpdateMonthCategoryInput):
    """Adjust the budgeted amount for a specific month and category."""
    logger.info(f"[TOOL] update_month_category called for {input.category_id} in month {input.month}")

    data = {
        "category": {
            "budgeted": int(input.budgeted_amount_eur * 1000)  # Convert to milliunits
        }
    }

    try:
        response = client.update_month_category(BUDGET_ID, input.month.isoformat(), input.category_id, data)
        return {
            "status": "Monthly category budget updated successfully!",
            "data": response.to_dict()
        }
    except Exception as e:
        logger.error(f"Failed to update month category: {e}")
        return {"error": "Unable to update the monthly budgeted amount."}

#class GetFirstBudgetIdInput(BaseModel):
#    pass
#
#@budget_agent.tool_plain
#def get_first_budget_id(input: GetFirstBudgetIdInput):
#    "Get the ID of the first budget associated with the account."
#    return client.get_first_budget_id()

#class GetAllBudgetsOnAccount(BaseModel):
#    pass
#
#@budget_agent.tool_plain
#def get_all_budgets(input: GetAllBudgetsOnAccount):
#    """Retrieve all budget details for high level overview, e.g. Budget ID(s), name, currency settings"""
#    return client.get_all_budgets()
