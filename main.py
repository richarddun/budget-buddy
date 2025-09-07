# main.py
import pdb
import logging
logger = logging.getLogger("uvicorn.error")
from fastapi import FastAPI, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from agents.budget_agent import budget_agent
import uvicorn
import html
import sqlite3
from pathlib import Path
from typing import List
import asyncio
from ynab_sdk_client import YNABSdkClient as ynab
import os
import json
from datetime import datetime
from dotenv import load_dotenv
from db.migrate import run_migrations
load_dotenv()
from config import BASE_PATH
from jobs.daily_ingestion import scheduler_loop
from jobs.backfill_payee_rules import backfill_from_ynab
from forecast.calendar import Entry as FcEntry
from datetime import date as _date
from jobs.nightly_snapshot import _compute_digest as _compute_digest_from_snapshot

def check_api_keys():
    """Return a warning message if API keys are missing."""
    if os.getenv("OAI_KEY") is None:
        logger.info("OpenAI API key missing. Returning instructional message.")
        return (
            "Looks like you don't have a valid OpenAI API key.  Go to platform.openai.com "
            "and generate a new key, then add it to your .env file (in the root folder of the repository you cloned).  "
            "Please try again then."
        )
    if os.getenv("YNAB_TOKEN") is None:
        logger.info("YNAB API token missing. Returning instructional message.")
        return (
            "It looks like you haven't added a YNAB API token to your .env file, I can't view your budget without it.  "
            "Go to https://api.ynab.com/ and generate a token, and add to your .env file.  Please try again then."
        )
    return None
# Import budget health analyzer
from budget_health_analyzer import BudgetHealthAnalyzer



# --- Template Setup ---
templates = Jinja2Templates(directory="templates")
# Simple currency formatter for templates
def _money(cents: int | None) -> str:
    try:
        if cents is None:
            return "—"
        return f"$ {cents/100:,.2f}"
    except Exception:
        return str(cents)

templates.env.filters["money"] = _money
# Use a global configuration for base path (see config.py)
app = FastAPI(root_path=BASE_PATH)
app.mount("/static", StaticFiles(directory="static"), name="static")
LOG_FILE = "chat_history_log.json"
DB_PATH = Path("chat_history.db")
# Local source-of-truth database (for tasks/migrations schema)
SOT_DB_PATH = Path("localdb/budget.db")

# Routers
try:
    from api.forecast import router as forecast_router
except Exception:
    forecast_router = None
try:
    from api.overview import router as overview_router
except Exception:
    overview_router = None

# --- File upload Setup ---
UPLOAD_DIR = Path("uploaded_receipts")
UPLOAD_DIR.mkdir(exist_ok=True)
app.mount("/receipts", StaticFiles(directory=UPLOAD_DIR), name="receipts")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt TEXT NOT NULL,
            response TEXT NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    conn.commit()
    conn.close()

BUDGET_ID = os.getenv("YNAB_BUDGET_ID")

def store_message(prompt: str, response: str):
    # Ensure database and table exist
    if not DB_PATH.exists():
        init_db()

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO messages (prompt, response) VALUES (?, ?)", (prompt, response))
    conn.commit()
    conn.close()
    # === Also append to .json log ===
    entry = {
        "timestamp": datetime.now().isoformat(),
        "prompt": prompt,
        "response": response
    }

    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w") as f:
            json.dump([entry], f, indent=2)
    else:
        with open(LOG_FILE, "r+") as f:
            data = json.load(f)
            data.append(entry)
            f.seek(0)
            json.dump(data, f, indent=2)

def format_chat_history(limit=10):
    history = load_recent_messages(limit)
    return "\n".join([
        f"You: {m['prompt']}\nAgent: {m['response']}" for m in history
    ])

def load_recent_messages(limit=10):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT prompt, response FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    messages = [{"prompt": row[0], "response": html.unescape(row[1])} for row in reversed(c.fetchall())]
    conn.close()
    return messages

# --- Digest preload helpers ---
def _connect_localdb() -> sqlite3.Connection:
    SOT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(SOT_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def load_latest_snapshot_row():
    try:
        with _connect_localdb() as conn:
            cur = conn.execute(
                """
                SELECT created_at, json_payload
                FROM forecast_snapshot
                ORDER BY created_at DESC
                LIMIT 1
                """
            )
            row = cur.fetchone()
            if not row:
                return None
            return {"created_at": row["created_at"], "json_payload": row["json_payload"]}
    except Exception as e:
        logger.exception(f"[DIGEST] Failed loading latest snapshot: {e}")
        return None

def compute_latest_digest():
    """Compute digest from most recent snapshot payload. Returns dict or None."""
    snap = load_latest_snapshot_row()
    if not snap:
        return None
    try:
        payload = json.loads(snap["json_payload"]) if isinstance(snap["json_payload"], str) else snap["json_payload"]
        # Rehydrate entries
        entries: list[FcEntry] = []
        for e in payload.get("entries", []):
            try:
                entries.append(
                    FcEntry(
                        date=_date.fromisoformat(e.get("date")),
                        type=e.get("type"),
                        name=e.get("name"),
                        amount_cents=int(e.get("amount_cents", 0)),
                        source_id=int(e.get("source_id", 0)),
                        shift_applied=bool(e.get("shift_applied", False)),
                        policy=e.get("policy"),
                    )
                )
            except Exception:
                continue
        # Rehydrate balances
        balances: dict[_date, int] = {}
        for k, v in (payload.get("balances", {}) or {}).items():
            try:
                balances[_date.fromisoformat(k)] = int(v)
            except Exception:
                continue
        meta = payload.get("meta", {})
        horizon = meta.get("horizon", {})
        start_iso = horizon.get("start")
        end_iso = horizon.get("end")
        start = _date.fromisoformat(start_iso) if start_iso else _date.today()
        end = _date.fromisoformat(end_iso) if end_iso else start
        opening = int(payload.get("opening_balance_cents", 0))
        digest = _compute_digest_from_snapshot(
            today=_date.today(),
            start=start,
            end=end,
            opening_balance_cents=opening,
            entries=entries,
            balances=balances,
            db_path=SOT_DB_PATH,
        )
        return digest
    except Exception as e:
        logger.exception(f"[DIGEST] Failed computing digest from snapshot: {e}")
        return None

@app.on_event("startup")
async def startup():
    # Run foundational DB migrations for local SoT schema
    try:
        applied = run_migrations(SOT_DB_PATH)
        if applied:
            logger.info(f"[MIGRATIONS] Applied: {', '.join(applied)}")
        else:
            logger.info("[MIGRATIONS] No pending migrations")
    except Exception as e:
        logger.exception(f"[MIGRATIONS] Failed to run migrations: {e}")

    # Initialize chat history DB used by the app
    init_db()
    logger.info("[INIT] Budget Buddy (SSE) startup complete.")
    # Include routers after app init
    if forecast_router is not None:
        app.include_router(forecast_router)
    if overview_router is not None:
        app.include_router(overview_router)
    # Optionally start the daily ingestion scheduler
    enable = os.getenv("ENABLE_DAILY_INGESTION", "false").lower() in ("1", "true", "yes", "on")
    leader = os.getenv("SCHEDULER_LEADER", "true").lower() in ("1", "true", "yes", "on")
    if enable and leader:
        hour = int(os.getenv("DAILY_INGESTION_HOUR", "7"))
        minute = int(os.getenv("DAILY_INGESTION_MINUTE", "0"))
        logger.info(f"[INIT] Starting daily scheduler for {hour:02d}:{minute:02d}")
        app.state.daily_task = asyncio.create_task(scheduler_loop(hour=hour, minute=minute))
    else:
        if not enable:
            logger.info("[INIT] Daily scheduler disabled (set ENABLE_DAILY_INGESTION=true to enable)")
        elif not leader:
            logger.info("[INIT] Daily scheduler not leader on this instance (SCHEDULER_LEADER=false)")

@app.on_event("shutdown")
async def shutdown():
    # Gracefully stop scheduler task if running
    task = getattr(app.state, "daily_task", None)
    if task and not task.done():
        logger.info("[SHUTDOWN] Cancelling daily scheduler task...")
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    chat_history = load_recent_messages()
    digest = compute_latest_digest()
    return templates.TemplateResponse(
        "chat.html",
        {"request": request, "chat_history": chat_history, "digest": digest},
    )

@app.get("/overview", response_class=HTMLResponse)
async def overview(request: Request):
    return templates.TemplateResponse("overview.html", {"request": request})

@app.get("/budgets")
def get_budget():
    buddy = ynab()
    return buddy.get_budget_details(BUDGET_ID)

@app.post("/local/backfill-payee-rules")
async def backfill_payee_rules_endpoint(
    months: int = 12,
    min_occurrences: int = 2,
    generalize: bool = True,
    dry_run: bool = False,
):
    if not BUDGET_ID:
        return {"error": "YNAB_BUDGET_ID not configured"}
    try:
        summary = backfill_from_ynab(
            budget_id=BUDGET_ID,
            months=months,
            min_occurrences=min_occurrences,
            generalize=generalize,
            dry_run=dry_run,
        )
        return summary
    except Exception as e:
        logger.exception(f"Backfill failed: {e}")
        return {"error": str(e)}

@app.get("/budget-health", response_class=HTMLResponse)
async def get_budget_health(request: Request):
    """Generate budget health report via Jinja template"""
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)
        html_report = analyzer.generate_html_report()
        return templates.TemplateResponse(
            "budget_health.html",
            {"request": request, "report_html": html_report},
        )
    except Exception as e:
        logger.error(f"Error generating budget health report: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "title": "Budget Health - Error", "error_message": str(e)},
            status_code=500,
        )

@app.get("/debug-budget-health")
async def debug_budget_health():
    """Debug budget health analysis step by step"""
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)

        result = {"step": "starting"}

        # Step 1: Load data
        #pdb.set_trace()
        analyzer._load_data()
        result["step_1_data_loaded"] = True

        # Step 2: Calculate budget totals
        total_budgeted, total_spent, total_remaining = analyzer._calculate_budget_totals()
        result["step_2_budget_totals"] = {
            "budgeted": total_budgeted,
            "spent": total_spent,
            "remaining": total_remaining
        }

        # Step 3: Find overspent categories
        overspent = analyzer._find_overspent_categories()
        result["step_3_overspent_count"] = len(overspent)

        # Step 4: Find underfunded goals
        underfunded = analyzer._find_underfunded_goals()
        result["step_4_underfunded_count"] = len(underfunded)

        # Step 5: Analyze spending trends
        trends = analyzer._analyze_spending_trends()
        result["step_5_spending_trends"] = trends

        # Step 6: Account summary
        accounts = analyzer._summarize_accounts()
        result["step_6_account_count"] = len(accounts)

        # Step 7: Category analysis
        categories = analyzer._analyze_categories()
        result["step_7_category_count"] = len(categories)

        # Step 8: Top spending categories
        top_spending = analyzer._get_top_spending_categories()
        result["step_8_top_spending_count"] = len(top_spending)

        # Step 9: Spending by payee
        spending_by_payee = analyzer._analyze_spending_by_payee()
        result["step_9_payee_count"] = len(spending_by_payee)

        # Step 10: Recurring transactions
        recurring = analyzer._detect_recurring_transactions()
        result["step_10_recurring_count"] = len(recurring)

        # Step 11: Calendar heat map
        calendar_data = analyzer._generate_calendar_heat_map()
        result["step_11_calendar_generated"] = True

        result["status"] = "success"
        return result

    except Exception as e:
        logger.error(f"Debug budget health error at step {result.get('step', 'unknown')}: {e}")
        return {
            "error": str(e),
            "error_type": str(type(e)),
            "last_successful_step": result.get("step", "none")
        }

@app.get("/subscriptions")
async def get_subscriptions(filter_view: str = "all"):
    """Detect subscriptions and scheduled payments (JSON response)"""
    import json
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)
        analyzer._load_data()  # Load data first
        all_subscriptions = analyzer.detect_subscriptions_and_scheduled_payments()

        # Apply filter based on view
        if filter_view == "rest_of_month":
            today = datetime.now().day
            subscriptions = [
                sub for sub in all_subscriptions
                if sub.get('most_common_day', 0) > today and sub.get('most_common_day', 0) <= 28
            ]
        else:
            subscriptions = all_subscriptions

        # Clean subscriptions to ensure JSON serialization
        clean_subscriptions = []
        for sub in subscriptions:
            try:
                clean_sub = {
                    "payee_name": sub.get('payee_name', 'Unknown'),
                    "avg_amount": float(sub.get('avg_amount', 0)),
                    "avg_amount_display": sub.get('avg_amount_display', '€0.00'),
                    "amount_range_display": sub.get('amount_range_display', '€0.00'),
                    "occurrence_count": int(sub.get('occurrence_count', 0)),
                    "month_span": int(sub.get('month_span', 0)),
                    "subscription_type": sub.get('subscription_type', 'Unknown'),
                    "confidence_score": int(sub.get('confidence_score', 0)),
                    "avg_interval_days": float(sub.get('avg_interval_days', 0)),
                    "first_seen": sub.get('first_seen', ''),
                    "last_seen": sub.get('last_seen', ''),
                    "months_covered": sub.get('months_covered', [])
                }
                # Test JSON serialization of this item
                json.dumps(clean_sub)
                clean_subscriptions.append(clean_sub)
            except Exception as clean_error:
                logger.warning(f"Skipping subscription due to serialization error: {clean_error}")
                continue

        response_data = {
            "subscription_count": len(clean_subscriptions),
            "subscriptions": clean_subscriptions,
            "generated_at": datetime.now().isoformat(),
            "criteria": {
                "min_occurrences": 2,
                "min_months": 2,
                "amount_tolerance": "±3 euros"
            }
        }

        # Final serialization test
        json.dumps(response_data)
        return response_data

    except Exception as e:
        logger.error(f"Error detecting subscriptions: {e}")
        return {
            "error": str(e),
            "subscriptions": [],
            "subscription_count": 0,
            "generated_at": datetime.now().isoformat()
        }

@app.get("/subscriptions-rest-of-month")
async def get_subscriptions_rest_of_month():
    """Convenient route for rest-of-month subscriptions (JSON)"""
    return await get_subscriptions(filter_view="rest_of_month")

@app.get("/subscriptions-rest-of-month-report", response_class=HTMLResponse)
async def get_subscriptions_rest_of_month_report(request: Request):
    """Convenient route for rest-of-month subscriptions report (HTML)"""
    return await get_subscriptions_report(request, filter_view="rest_of_month")

@app.get("/subscriptions-report", response_class=HTMLResponse)
async def get_subscriptions_report(request: Request, filter_view: str = "all"):
    """Generate subscriptions report as HTML with filtering options"""
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)
        analyzer._load_data()  # Load data first
        all_subscriptions = analyzer.detect_subscriptions_and_scheduled_payments()

        # Apply filter based on view
        if filter_view == "rest_of_month":
            today = datetime.now().day
            subscriptions = [
                sub for sub in all_subscriptions
                if sub.get('most_common_day', 0) > today and sub.get('most_common_day', 0) <= 28
            ]
        else:
            subscriptions = all_subscriptions

        # Prepare data for Jinja template
        norm = []
        for s in subscriptions:
            norm.append({
                'payee_name': s.get('payee_name', 'Unknown'),
                'amount_range_display': s.get('amount_range_display', s.get('avg_amount_display', '€0.00')),
                'subscription_type': s.get('subscription_type', 'Unknown'),
                'occurrence_count': int(s.get('occurrence_count', 0)),
                'month_span': int(s.get('month_span', 0)),
                'confidence_score': int(s.get('confidence_score', 0)),
                'avg_interval_days': s.get('avg_interval_days', 0),
                'first_seen': s.get('first_seen', ''),
                'last_seen': s.get('last_seen', ''),
                'months_covered': s.get('months_covered', []),
            })

        context = {
            'request': request,
            'filter_view': filter_view,
            'subscriptions': norm,
            'today_day': datetime.now().day,
            'generated_at_str': datetime.now().strftime('%Y-%m-%d at %H:%M:%S'),
        }

        return templates.TemplateResponse("subscriptions_report.html", context)

    except Exception as e:
        logger.error(f"Error generating subscriptions report: {e}")
        return templates.TemplateResponse(
            "error.html",
            {"request": request, "title": "Subscriptions Report - Error", "error_message": str(e)},
            status_code=500,
        )

@app.get("/test-subscriptions")
async def test_subscriptions():
    """Test route to verify subscription detection and JSON serialization"""
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)
        result = analyzer.test_subscription_detection()
        return result
    except Exception as e:
        logger.error(f"Error in subscription test: {e}")
        return {"status": "error", "error": str(e)}

@app.get("/debug-subscriptions")
async def debug_subscriptions():
    """Simple debug route to isolate JSON serialization issues"""
    import json
    #pdb.set_trace()
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)

        # Test 1: Can we create the analyzer?
        result = {"step_1_analyzer_created": True}

        # Test 2: Can we load data?
        analyzer._load_data()
        result["step_2_data_loaded"] = True

        # Test 3: Check transaction data type and count
        tx_data = analyzer._transaction_data
        result["step_3_transaction_count"] = len(tx_data) if tx_data else 0
        result["step_3_transaction_type"] = str(type(tx_data))

        # Test 4: Try to serialize a simple transaction
        if tx_data and len(tx_data) > 0:
            first_tx = tx_data[0]
            result["step_4_first_tx_keys"] = list(first_tx.keys()) if hasattr(first_tx, 'keys') else "not_dict"

            # Try to serialize just payee name and amount
            simple_data = {
                "payee": first_tx.get('payee_name', 'unknown'),
                "amount": first_tx.get('amount', 0)
            }
            json.dumps(simple_data)
            result["step_4_simple_serialize"] = True

        # Test 5: Return result without calling detect_subscriptions
        json.dumps(result)
        return result

    except Exception as e:
        return {
            "error": str(e),
            "error_type": str(type(e)),
            "step_failed": "unknown"
        }

@app.get("/simple-subscriptions")
async def get_simple_subscriptions():
    """Very basic subscription detection without date processing"""
    import json
    from collections import defaultdict

    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)
        analyzer._load_data()

        if not analyzer._transaction_data:
            return {"subscriptions": [], "count": 0}

        # Group by payee and amount without date processing
        payee_amounts = defaultdict(list)

        for tx in analyzer._transaction_data:
            if tx.get('amount', 0) < 0:  # Only spending
                payee = tx.get('payee_name', 'Unknown')
                amount = abs(tx.get('amount', 0))

                if payee != 'Unknown':
                    payee_amounts[payee].append({
                        'amount': amount,
                        'date_string': tx.get('date', ''),
                        'id': tx.get('id', '')
                    })

        # Find potential subscriptions (2+ similar amounts)
        subscriptions = []
        for payee, transactions in payee_amounts.items():
            if len(transactions) >= 2:
                # Group by similar amounts (within 3 euros)
                amount_groups = defaultdict(list)
                for tx in transactions:
                    amount = tx['amount']
                    # Find similar amount group
                    found = False
                    for group_amount in amount_groups.keys():
                        if abs(amount - group_amount) <= 3.0:
                            amount_groups[group_amount].append(tx)
                            found = True
                            break
                    if not found:
                        amount_groups[amount].append(tx)

                # Check for groups with 2+ transactions
                for base_amount, similar_txs in amount_groups.items():
                    if len(similar_txs) >= 2:
                        avg_amount = sum(tx['amount'] for tx in similar_txs) / len(similar_txs)

                        subscriptions.append({
                            'payee_name': payee,
                            'avg_amount': round(avg_amount, 2),
                            'avg_amount_display': f'€{avg_amount:.2f}',
                            'occurrence_count': len(similar_txs),
                            'amounts': [tx['amount'] for tx in similar_txs]
                        })

        # Sort by average amount
        subscriptions.sort(key=lambda x: x['avg_amount'], reverse=True)

        result = {
            'subscriptions': subscriptions,
            'count': len(subscriptions),
            'status': 'success'
        }

        # Test JSON serialization
        json.dumps(result)
        return result

    except Exception as e:
        logger.error(f"Error in simple subscriptions: {e}")
        return {
            'error': str(e),
            'subscriptions': [],
            'count': 0,
            'status': 'error'
        }

@app.post("/htmx-chat", response_class=HTMLResponse)
async def htmx_chat(request: Request, prompt: str = Form(...)):
    return HTMLResponse(f"""
    <p><strong>You:</strong> {prompt}</p>
    <p><strong>Agent:</strong>
        <span id="stream-content"><em>Thinking...</em></span>
        <span id="status-spinner" class="spinner"></span>
    </p>
    <hr>
    """)


@app.get("/sse")
async def sse(prompt: str, fresh: bool = False):
    logger.info(f"[SSE] Incoming stream request with prompt: {prompt}")

    incoming_prompt = prompt.strip()  # capture clean user input

    missing_msg = check_api_keys()
    if missing_msg:
        async def event_stream_missing():
            logger.info("[SSE] Missing API keys; sending static message")
            lnbrk = "\n"
            yield "retry: 1000\n\n"
            yield f"event: message{lnbrk}data: {missing_msg}{lnbrk}{lnbrk}"
            store_message(incoming_prompt, missing_msg)
            yield f"event: done{lnbrk}data: done{lnbrk}{lnbrk}"

        return StreamingResponse(event_stream_missing(), media_type="text/event-stream")

    if not fresh:
        history = format_chat_history(limit=10)
        if not incoming_prompt.lower().startswith("you:"):
            formatted_prompt = f"You: {incoming_prompt}"
        else:
            formatted_prompt = incoming_prompt
        prompt = f"{history}\n{formatted_prompt}"

    logger.info(f"[SSE] Final prompt sent to agent: {repr(prompt[:120])}...")

    async def event_stream():
        logger.info("[SSE] Stream started")
        full_response = ""
        lnbrk = "\n"
        yield "retry: 1000\n\n"
        yield "event: open\n\n"
        logger.info("[SSE] Heading into agent-runstream..")
        async with budget_agent.run_stream(prompt) as result:
            # Emit status messages from tool responses if present
            if hasattr(result, "tool_calls") and result.tool_calls:
                for call in result.tool_calls:
                    tool_output = call.output
                    if isinstance(tool_output, dict) and "status" in tool_output:
                        status_msg = tool_output["status"]
                        logger.info(f"[SSE] Status from tool: {status_msg}")
                        yield f"event: status{lnbrk}data: {status_msg}{lnbrk}{lnbrk}"
                        await asyncio.sleep(0.1)  # slight pause to let UI update

            # Begin token streaming
            async for token in result.stream_text(delta=True):
                logger.info(f"[SSE] Token received: {repr(token)}")
                safe_token = token.replace('\n', '<br>')
                #safe_token = token
                yield f"event: message{lnbrk}data: {safe_token}{lnbrk}{lnbrk}"
                full_response += safe_token
                await asyncio.sleep(0.01)

        logger.info("[SSE] Full response assembled, storing...")
        store_message(incoming_prompt, full_response)
        yield f"event: done\ndata: done\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")

@app.post("/reset-session")
async def reset_session():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()
    logger.info("[SESSION] Chat history cleared.")
    return {"status": "ok", "message": "Session reset."}

@app.post("/upload-receipt")
async def upload_receipt(files: List[UploadFile] = File(...)):
    uploaded_filenames = []

    for file in files:
        try:
            contents = await file.read()
            file_path = UPLOAD_DIR / file.filename
            with open(file_path, "wb") as f:
                f.write(contents)
            uploaded_filenames.append(file.filename)
            logger.info(f"[UPLOAD] Saved receipt to {file_path}")
        except Exception as e:
            logger.error(f"[UPLOAD ERROR] {e}")
            return {"status": "error", "detail": str(e)}

    return {"status": "success", "filenames": uploaded_filenames}

from fastapi.responses import HTMLResponse

@app.get("/uploads", response_class=HTMLResponse)
async def view_uploads(request: Request):
    files = [f.name for f in UPLOAD_DIR.iterdir() if f.is_file()]
    return templates.TemplateResponse("uploads.html", {"request": request, "files": files})

@app.get("/sse-test")
async def sse_test():
    async def event_stream():
        yield "data: Hello from plain test\n\n"
        await asyncio.sleep(0.5)
        yield "data: This is a working stream\n\n"
        await asyncio.sleep(0.5)
        yield "data: Done\n\n"
    return StreamingResponse(event_stream(), media_type="text/event-stream")

# Optional CLI testing
async def main():
    user_prompt = "What accounts are tied to my budget right now?"
    async with budget_agent.run_stream(user_prompt) as result:
        async for message in result.stream_text(delta=True):
            for char in message:
                print(char, end="", flush=True)

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
