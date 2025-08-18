# main.py
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
load_dotenv()

# Import budget health analyzer
from budget_health_analyzer import BudgetHealthAnalyzer



# --- Template Setup ---
templates = Jinja2Templates(directory="templates")
app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")
LOG_FILE = "chat_history_log.json"
DB_PATH = Path("chat_history.db")

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

@app.on_event("startup")
async def startup():
    init_db()
    logger.info("[INIT] Budget Buddy (SSE) startup complete.")

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    chat_history = load_recent_messages()
    return templates.TemplateResponse("chat.html", {"request": request, "chat_history": chat_history})

@app.get("/budgets")
def get_budget():
    buddy = ynab()
    return buddy.get_budget_details(BUDGET_ID)

@app.get("/budget-health", response_class=HTMLResponse)
async def get_budget_health():
    """Generate budget health report as HTML"""
    try:
        analyzer = BudgetHealthAnalyzer(BUDGET_ID)
        html_report = analyzer.generate_html_report()
        return HTMLResponse(content=html_report)
    except Exception as e:
        logger.error(f"Error generating budget health report: {e}")
        error_html = f"""
        <html>
        <head><title>Budget Health - Error</title></head>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
        <h1>Budget Health Report - Error</h1>
        <p>Sorry, there was an error generating your budget health report:</p>
        <p style="color: red;">{str(e)}</p>
        <a href="/" style="display: inline-block; margin-top: 20px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;">← Back to Chat</a>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=500)

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
async def get_subscriptions_rest_of_month_report():
    """Convenient route for rest-of-month subscriptions report (HTML)"""
    return await get_subscriptions_report(filter_view="rest_of_month")

@app.get("/subscriptions-report", response_class=HTMLResponse)
async def get_subscriptions_report(filter_view: str = "all"):
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

        # Create button styles based on active filter
        all_btn_bg = '#007bff' if filter_view == 'all' else '#fff'
        all_btn_color = 'white' if filter_view == 'all' else '#007bff'
        month_btn_bg = '#28a745' if filter_view == 'rest_of_month' else '#fff'
        month_btn_color = 'white' if filter_view == 'rest_of_month' else '#28a745'

        # Generate HTML report
        html_content = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Subscriptions & Scheduled Payments</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); padding: 30px; }}
                .header {{ background: linear-gradient(135deg, #28a745 0%, #20c997 100%); color: white; padding: 30px; text-align: center; border-radius: 10px; margin: -30px -30px 30px -30px; }}
                .subscription-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(350px, 1fr)); gap: 20px; }}
                .subscription-card {{ border: 1px solid #ddd; border-radius: 8px; padding: 20px; background: #f8f9fa; }}
                .subscription-card h3 {{ margin-top: 0; color: #28a745; }}
                .confidence-high {{ border-left: 4px solid #28a745; }}
                .confidence-medium {{ border-left: 4px solid #ffc107; }}
                .confidence-low {{ border-left: 4px solid #dc3545; }}
                .badge {{ padding: 3px 8px; border-radius: 12px; font-size: 12px; color: white; }}
                .badge-monthly {{ background: #007bff; }}
                .badge-weekly {{ background: #17a2b8; }}
                .badge-quarterly {{ background: #6610f2; }}
                .badge-other {{ background: #6c757d; }}
                .amount-display {{ font-size: 24px; font-weight: bold; color: #dc3545; }}
                .back-link {{ display: inline-block; margin-bottom: 20px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px; }}
                .summary {{ background: #e7f3ff; padding: 15px; border-radius: 8px; margin-bottom: 20px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>🔄 Subscriptions & Scheduled Payments</h1>
                    <p>Detected recurring payments based on amount similarity (±€3) over 2+ months</p>
                </div>

                <!-- Filter Controls -->
                <div style="text-align: center; margin: 20px 0; padding: 15px; background: #f8f9fa; border-radius: 8px;">
                    <strong>📋 View Filter:</strong>
                    <button onclick="location.href='/subscriptions-report?filter_view=all'"
                            style="margin: 0 5px; padding: 8px 16px; border-radius: 4px; border: 1px solid #007bff; background: {all_btn_bg}; color: {all_btn_color}; cursor: pointer;">
                        🗂️ All Subscriptions
                    </button>
                    <button onclick="location.href='/subscriptions-report?filter_view=rest_of_month'"
                            style="margin: 0 5px; padding: 8px 16px; border-radius: 4px; border: 1px solid #28a745; background: {month_btn_bg}; color: {month_btn_color}; cursor: pointer;">
                        📅 Rest of This Month
                    </button>
                </div>

                <div class="summary">
                    <strong>📊 Summary:</strong> {f"Showing {len(subscriptions)} subscriptions for rest of month (day {datetime.now().day + 1}-28)" if filter_view == "rest_of_month" else f"Found {len(subscriptions)} potential subscriptions/scheduled payments"}
                    <br><strong>🔍 Detection Criteria:</strong> 2+ occurrences, 2+ months, ±€3 amount tolerance
                    <br><strong>📅 Generated:</strong> {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}
                    {f'<br><strong>🎯 Filter:</strong> Showing only subscriptions due after today (day {datetime.now().day}) through day 28' if filter_view == "rest_of_month" else ''}
                </div>

                <div class="subscription-grid">
        """

        if subscriptions:
            for sub in subscriptions:
                confidence_class = "confidence-high" if sub['confidence_score'] >= 70 else ("confidence-medium" if sub['confidence_score'] >= 50 else "confidence-low")

                # Determine badge class
                badge_class = "badge-other"
                if "Monthly" in sub['subscription_type']:
                    badge_class = "badge-monthly"
                elif "Weekly" in sub['subscription_type']:
                    badge_class = "badge-weekly"
                elif "Quarterly" in sub['subscription_type']:
                    badge_class = "badge-quarterly"

                html_content += f"""
                    <div class="subscription-card {confidence_class}">
                        <h3>{sub['payee_name']}</h3>
                        <div class="amount-display">{sub['amount_range_display']}</div>
                        <p><strong>Type:</strong> <span class="badge {badge_class}">{sub['subscription_type']}</span></p>
                        <p><strong>Occurrences:</strong> {sub['occurrence_count']} times over {sub['month_span']} months</p>
                        <p><strong>Confidence:</strong> {sub['confidence_score']}%</p>
                        <p><strong>Average Interval:</strong> {sub['avg_interval_days']} days</p>
                        <p><strong>Period:</strong> {sub['first_seen']} to {sub['last_seen']}</p>
                        <p><strong>Months:</strong> {', '.join(sub['months_covered'])}</p>
                    </div>
                """
        else:
            no_subs_title = "No Upcoming Subscriptions" if filter_view == "rest_of_month" else "No Subscriptions Detected"
            no_subs_desc = f"No recurring payments found for the rest of this month (days {datetime.now().day + 1}-28)." if filter_view == "rest_of_month" else "No recurring payment patterns found matching the criteria (2+ occurrences over 2+ months with ±€3 amount tolerance)."
            no_subs_tip = '<p><em>💡 Try the "All Subscriptions" filter to see your complete subscription list.</em></p>' if filter_view == "rest_of_month" else ''

            html_content += f"""
                    <div class="subscription-card">
                        <h3>{no_subs_title}</h3>
                        <p>{no_subs_desc}</p>
                        {no_subs_tip}
                    </div>
            """

        html_content += """
                </div>
            </div>
        </body>
        </html>
        """

        return HTMLResponse(content=html_content)

    except Exception as e:
        logger.error(f"Error generating subscriptions report: {e}")
        error_html = f"""
        <html>
        <head><title>Subscriptions Report - Error</title></head>
        <body style="font-family: Arial, sans-serif; margin: 20px;">
        <h1>Subscriptions Report - Error</h1>
        <p>Sorry, there was an error generating your subscriptions report:</p>
        <p style="color: red;">{str(e)}</p>
        <a href="/" style="display: inline-block; margin-top: 20px; padding: 10px 20px; background: #007bff; color: white; text-decoration: none; border-radius: 5px;">← Back to Chat</a>
        </body>
        </html>
        """
        return HTMLResponse(content=error_html, status_code=500)

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
async def view_uploads():
    files = [f.name for f in UPLOAD_DIR.iterdir() if f.is_file()]

    # Generate HTML gallery
    images_html = ""
    for file in files:
        images_html += f"""
        <div style="display:inline-block; margin:10px; text-align:center;">
            <a href="/receipts/{file}" target="_blank">
                <img src="/receipts/{file}" style="width:150px; height:auto; border-radius:8px; box-shadow:0 0 5px #aaa;">
            </a>
            <div style="margin-top:5px; font-size:0.9em; color:#ccc;">{file}</div>
        </div>
        """

    page_html = f"""
    <html>
    <head>
    <title>Uploaded Receipts</title>
    <style>
        body {{
            background-color: #1e1e2f;
            color: #ddd;
            font-family: 'Segoe UI', sans-serif;
            text-align: center;
        }}
        h1 {{
            margin-top: 20px;
        }}
    </style>
    </head>
    <body>
    <div id="backlink"><a href="/" style="display:inline-block; margin:15px; padding:10px 20px; background:#4477dd; color:white; text-decoration:none; border-radius:8px;">⬅️ Back to Chat</a></div>
    <h1>📂 Uploaded Receipts</h1>
    {images_html if images_html else "<p>No receipts uploaded yet.</p>"}
    </body>
    </html>
    """
    return HTMLResponse(content=page_html)

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
