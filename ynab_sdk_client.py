import hashlib
import shutil
import json
from pathlib import Path
import os
from dotenv import load_dotenv
from ynab import Configuration, ApiClient, BudgetsApi, TransactionsApi, AccountsApi
from datetime import datetime, timedelta
import json
import logging
logger = logging.getLogger("uvicorn.error")

load_dotenv()

class YNABSdkClient:
    # 🔹 Class-level constants (shared across all instances)
    CACHE_FILE = "cached_transactions.json"
    CACHE_TTL_HOURS = 12

    def __init__(self):
        # 🔸 Instance-level configuration (specific to this client)
        access_token = os.getenv("YNAB_TOKEN")
        self.config = Configuration(access_token=access_token)
        self.api_client = ApiClient(self.config)

        # 🔸 These are bound to this client (and should remain instance-specific)
        self.budgets_api = BudgetsApi(self.api_client)
        self.transactions_api = TransactionsApi(self.api_client)
        self.accounts_api = AccountsApi(self.api_client)
        self.get_accounts = self.cacheable(self.get_accounts)
        self.get_budget_details = self.cacheable(self._get_budget_details_uncached)
        self.get_transactions = self.cacheable(self.get_transactions)

    def _cache_key(self, func_name, args, kwargs):
        raw = json.dumps({
            "func": func_name,
            "args": args,
            "kwargs": kwargs
        }, sort_keys=True)
        return hashlib.sha256(raw.encode()).hexdigest()

    def _get_cache_path(self, key):
        return Path(f".ynab_cache/{key}.json")

    def _load_cache(self, key):
        path = self._get_cache_path(key)
        if not path.exists():
            return None
        with open(path, "r") as f:
            data = json.load(f)
        timestamp = datetime.fromisoformat(data["fetched_at"])
        if datetime.now() - timestamp > timedelta(hours=self.CACHE_TTL_HOURS):
            return None
        return data["value"]

    def _save_cache(self, key, value):
        path = self._get_cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump({
                "fetched_at": datetime.now().isoformat(),
                "value": value
            }, f, indent=2)

    def cacheable(self, func):
        def wrapper(*args, **kwargs):
            key = self._cache_key(func.__name__, args, kwargs)
            cached = self._load_cache(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] {func.__name__}")
                return cached
            logger.info(f"[CACHE MISS] {func.__name__}")
            result = func(*args, **kwargs)
            self._save_cache(key, result)
            return result
        return wrapper

    def clear_cache(self):
        shutil.rmtree(".ynab_cache", ignore_errors=True)

    def _normalize_currency_fields(self, obj):
        """
        Recursively normalize all relevant milliunit fields:
        - Replace raw integer with float euros (2 decimal places)
        - Add a 'display' key like 'amount_display': '€123.45'
        """
        currency_keywords = ["amount", "balance", "goal", "budgeted", "activity", "value"]

        if isinstance(obj, dict):
            new_obj = {}
            for k, v in obj.items():
                lowered = k.lower()
                if isinstance(v, int) and any(kw in lowered for kw in currency_keywords):
                    euro_val = round(v / 1000.0, 2)
                    new_obj[k] = euro_val
                    new_obj[f"{k}_display"] = f"€{euro_val:,.2f}"
                else:
                    new_obj[k] = self._normalize_currency_fields(v)
            return new_obj

        elif isinstance(obj, list):
            return [self._normalize_currency_fields(i) for i in obj]

        return obj

    # 🔸 Private utility for fetching fresh data and updating cache
    def _fetch_and_cache_transactions(self, budget_id, since_date=None):
        transactions = self.transactions_api.get_transactions(budget_id, since_date).data.transactions
        txns_dict = [t.to_dict() for t in transactions]
        with open(self.CACHE_FILE, "w") as f:
            json.dump({
                "fetched_at": datetime.now().isoformat(),
                "transactions": txns_dict
            }, f, indent=2)
        return txns_dict

    def _cache_expired(self):
        if not os.path.exists(self.CACHE_FILE):
            return True
        with open(self.CACHE_FILE, "r") as f:
            data = json.load(f)
        timestamp = datetime.fromisoformat(data.get("fetched_at"))
        return datetime.now() - timestamp > timedelta(hours=self.CACHE_TTL_HOURS)

    # 🔸 Public method that uses caching
    def get_transactions(self, budget_id, since_date=None):
        if self._cache_expired():
            transactions = self._fetch_and_cache_transactions(budget_id, since_date)
        else:
            with open(self.CACHE_FILE, "r") as f:
                data = json.load(f)
                transactions = data.get("transactions")
        return self._normalize_currency_fields(transactions) # convert amounts from milliunits 

    def _get_budget_details_uncached(self, budget_id):
        raw_budget = self.budgets_api.get_budget_by_id(budget_id).data.budget
        return self._normalize_currency_fields(raw_budget.to_dict())

    def get_accounts(self, budget_id):
        return self._normalize_currency_fields([a.to_dict() for a in self.accounts_api.get_accounts(budget_id).data.accounts])



