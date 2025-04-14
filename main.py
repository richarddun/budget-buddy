from fastapi import FastAPI
from ynab_client import YNABClient
from ynab_cache import get_transactions_cached
from fastapi.responses import HTMLResponse
from fastapi import Request
from collections import defaultdict
from ynab_client import YNABClient
from datetime import datetime
import statistics

app = FastAPI()
ynab = YNABClient()

@app.get("/")
def read_root():
    return {"hello": "budget buddy"}

@app.get("/budgets")
def list_budgets():
    return ynab.get_budgets()

@app.get("/budgets/{budget_id}")
def get_budget(budget_id: str):
    return ynab.get_budget_details(budget_id)

@app.get("/budgets/{budget_id}/transactions")
def get_transactions(budget_id: str, since_date: str = None):
    return ynab.get_transactions(budget_id, since_date)

@app.get("/budgets/{budget_id}/accounts")
def get_accounts(budget_id: str):
    return ynab.get_accounts(budget_id)

@app.get("/recurring", response_class=HTMLResponse)
def recurring_transactions_html():
    budget_id = ynab.get_budgets()["data"]["budgets"][0]["id"]
    txns = get_transactions_cached()
    #txns = ynab.get_transactions(budget_id)["data"]["transactions"]

    # Step 1: Group by payee + amount band
    buckets = defaultdict(list)
    for txn in txns:
        if txn["deleted"] or not txn["approved"]:
            continue
        key = (
            txn["payee_name"].lower().strip() if txn["payee_name"] else "unknown",
            round(txn["amount"] / 1000)  # normalize to nearest €1
        )
        buckets[key].append(txn)

    # Step 2: Filter to recurring ones
    recurring = {k: v for k, v in buckets.items() if len(v) >= 2}

    # Step 3: Build HTML
    html = "<h1>🧾 Recurring Transaction Suspects</h1>"
    for (payee, amt_band), txns in sorted(recurring.items(), key=lambda x: len(x[1]), reverse=True):
        dates = [datetime.fromisoformat(t["date"]).strftime("%b %d") for t in txns]
        avg_amt = statistics.mean([t["amount"] for t in txns]) / 1000.0
        html += f"<h3>{payee.title()} – approx €{abs(avg_amt):.2f}</h3>"
        html += f"<p><strong>Dates:</strong> {', '.join(dates)}</p>"

    return html

@app.get("/big-spends", response_class=HTMLResponse)
def big_spends():
    txns = get_transactions_cached()
    biggies = [
        t for t in txns
        if t["amount"] <= -50000 and not t["deleted"] and t["approved"]
    ]

    # Sort by date descending
    biggies.sort(key=lambda t: t["date"], reverse=True)

    html = "<h1>💸 Big Spends (≥ €50)</h1>"
    for t in biggies:
        date = t["date"]
        amount_eur = abs(t["amount"]) / 1000
        payee = t.get("payee_name", "Unknown")
        category = t.get("category_name", "Uncategorized")
        html += f"<p><strong>{date}</strong> — €{amount_eur:.2f} to {payee} <em>({category})</em></p>"

    return html
