import hashlib
import shutil
import json
from pathlib import Path
import os
from dotenv import load_dotenv
from ynab import Configuration, ApiClient, BudgetsApi, TransactionsApi, AccountsApi, ScheduledTransactionsApi, CategoriesApi

from datetime import datetime, timedelta, date
import json
import logging
logger = logging.getLogger("uvicorn.error")

load_dotenv()

class YNABSdkClient:
    # 🔹 Class-level constants (shared across all instances)
    CACHE_TTL_HOURS = 12

    def __init__(self):
        # 🔸 Instance-level configuration (specific to this client)
        access_token = os.getenv("YNAB_TOKEN")
        self.config = Configuration(access_token=access_token)
        self.api_client = ApiClient(self.config)

        # 🔸 Set up the client interfaces
        self.budgets_api = BudgetsApi(self.api_client)
        self.transactions_api = TransactionsApi(self.api_client)
        self.accounts_api = AccountsApi(self.api_client)
        self.scheduled_transactions_api = ScheduledTransactionsApi(self.api_client)
        self.categories_api = CategoriesApi(self.api_client)

        # 🔸 Read APIs (not caching scheduled_transactions at this time) 
        self.get_accounts = self.cacheable(self.get_accounts)
        self.get_budget_details = self.cacheable(self._get_budget_details_uncached)
        self.get_transactions = self.cacheable(self.get_transactions)

        # 🔸 Write APIs 
        # 


    def _get_budget_details_uncached(self, budget_id):
        raw_budget = self.budgets_api.get_budget_by_id(budget_id).data.budget
        return self._normalize_currency_fields(raw_budget.to_dict())

    def get_accounts(self, budget_id):
        return self._normalize_currency_fields([a.to_dict() for a in self.accounts_api.get_accounts(budget_id).data.accounts])
    
    def get_scheduled_transactions(self, budget_id):
        return self._normalize_currency_fields([a.to_dict() for a in self.scheduled_transactions_api.get_scheduled_transactions(budget_id).data.scheduled_transactions])

    def create_scheduled_transaction(self, budget_id, data):
        response = self.scheduled_transactions_api.create_scheduled_transaction(budget_id, data)
        return self._normalize_currency_fields(response)

    def get_scheduled_transaction_by_id(self, budget_id, scheduled_transaction_id):
        return self._normalize_currency_fields(
            self.scheduled_transactions_api.get_scheduled_transaction_by_id(budget_id, scheduled_transaction_id).data.scheduled_transaction.to_dict()
        )

    def update_scheduled_transaction(self, budget_id, scheduled_transaction_id, data):
        return self.scheduled_transactions_api.update_scheduled_transaction(budget_id, scheduled_transaction_id, data)

    def delete_scheduled_transaction(self, budget_id, scheduled_transaction_id):
        return self.scheduled_transactions_api.delete_scheduled_transaction(budget_id, scheduled_transaction_id)

    # --- 🔹 Category Management (NEW) ---

    def get_categories(self, budget_id):
        return self._normalize_currency_fields(
            [g.to_dict() for g in self.categories_api.get_categories(budget_id).data.category_groups]
        )

    def get_category_by_id(self, budget_id, category_id):
        return self._normalize_currency_fields(
            self.categories_api.get_category_by_id(budget_id, category_id).data.category.to_dict()
        )

    def update_category(self, budget_id, category_id, data):
        return self.categories_api.update_category(budget_id, category_id, data)

    def update_month_category(self, budget_id, month, category_id, data):
        return self.categories_api.update_month_category(budget_id, month, category_id, data)

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
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump({
                "fetched_at": datetime.now().isoformat(),
                "value": value
            }, f, indent=2)
        os.replace(tmp_path, path)  # atomic replacement

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
                elif isinstance(v, (datetime,date)):
                    new_obj[k] = v.isoformat()
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
        normalized = self._normalize_currency_fields(txns_dict)
        key = self._cache_key("get_transactions", (budget_id, since_date), {})
        self._save_cache(key, normalized)
        return normalized

    # 🔸 Public method that uses caching
    def get_transactions(self, budget_id, since_date=None):
        key = self._cache_key("get_transactions", (budget_id, since_date), {})
        cached = self._load_cache(key)
        if cached is not None:
            logger.info(f"[CACHE HIT] get_transactions")
            return cached
        logger.info(f"[CACHE MISS] get_transactions")
        return self._fetch_and_cache_transactions(budget_id, since_date)


