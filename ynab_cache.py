import os
import json
from datetime import datetime, timedelta
from ynab_sdk_client import YNABSdkClient

CACHE_FILE = "cached_transactions.json"
CACHE_TTL_HOURS = 12

def load_cache():
    if not os.path.exists(CACHE_FILE):
        return None

    with open(CACHE_FILE, "r") as f:
        data = json.load(f)

    timestamp = datetime.fromisoformat(data.get("fetched_at"))
    if datetime.now() - timestamp > timedelta(hours=CACHE_TTL_HOURS):
        return None

    return data.get("transactions")

def save_cache(transactions):
    with open(CACHE_FILE, "w") as f:
        json.dump({
            "fetched_at": datetime.now().isoformat(),
            "transactions": [t.to_dict() for t in transactions]
        }, f, indent=2)

def get_transactions_cached():
    cached = load_cache()
    if cached:
        return cached

    client = YNABSdkClient()
    budget_id = client.get_first_budget_id()
    transactions = client.get_transactions(budget_id)

    save_cache(transactions)
    return [t.to_dict() for t in transactions]
