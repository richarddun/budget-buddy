import hashlib
import shutil
import json
from pathlib import Path
import os
from dotenv import load_dotenv
from datetime import datetime, timedelta, date
import logging

from ynab import (
    Configuration,
    ApiClient,
    BudgetsApi,
    TransactionsApi,
    AccountsApi,
    ScheduledTransactionsApi,
    CategoriesApi,
)

logger = logging.getLogger("uvicorn.error")

load_dotenv()
STAGING = os.getenv("STAGING", "false").lower() in {"1", "true", "yes"}

class YNABSdkClient:
    # 🔹 Class-level constants (shared across all instances)
    CACHE_TTL_HOURS = 6

    def __init__(self):
        """Initialize either a real or dummy YNAB client depending on STAGING."""
        if STAGING:
            # Pre-built dummy data to allow the app to run without credentials
            self._dummy_budget = {
                "id": "dummy-budget-id",
                "name": "Staging Budget",
                "first_month": "2024-01-01",
                "last_month": "2024-12-01",
                "currency_format": {"iso_code": "USD"},
                "accounts": [
                    {"id": "acct-1", "name": "Checking", "type": "checking", "balance": 100000},
                    {"id": "acct-2", "name": "Savings", "type": "savings", "balance": 250000},
                ],
            }
            self._dummy_transactions = [
                {
                    "id": "txn-1",
                    "account_id": "acct-1",
                    "date": "2024-10-01",
                    "amount": -5000,
                    "payee_name": "Coffee Shop",
                    "memo": "Latte",
                },
                {
                    "id": "txn-2",
                    "account_id": "acct-2",
                    "date": "2024-10-02",
                    "amount": 200000,
                    "payee_name": "Paycheck",
                    "memo": "",
                },
            ]

            # Expose dummy read methods through cache wrapper for compatibility
            self.get_budget = self.cacheable(self._get_budget_staging)
            self.get_budget_details = self.cacheable(self._get_budget_details_staging)
            self.get_transactions = self.cacheable(self._get_transactions_staging)
            self.get_accounts = self.cacheable(self._get_accounts_staging)
            return

        # 🔸 Instance-level configuration (specific to this client)
        # NOTE:
        # Only pure read methods are wrapped with self.cacheable().
        # All write/mutation operations (create/update/delete) are left as direct API calls.

        access_token = os.getenv("YNAB_TOKEN")
        if access_token is None:
            logger.info("YNAB_TOKEN not found in environment. YNAB API access will be disabled.")
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
        self.get_scheduled_transactions = self.cacheable(self.get_scheduled_transactions)
        self.get_transactions = self.cacheable(self.get_transactions)

    def _get_budget_details_uncached(self, budget_id):
        raw_budget = self.budgets_api.get_budget_by_id(budget_id).data.budget
        return self._normalize_currency_fields(raw_budget.to_dict())

    # --- Staging helpers -------------------------------------------------

    def _get_budget_staging(self):
        """Return a minimal budgets list for staging."""
        return {"budgets": [{"id": self._dummy_budget["id"], "name": self._dummy_budget["name"]}]}

    def _get_budget_details_staging(self, budget_id):
        return self._normalize_currency_fields(self._dummy_budget)

    def _get_transactions_staging(self, budget_id, since_date=None):
        return self._normalize_currency_fields(self._dummy_transactions)

    def _get_accounts_staging(self, budget_id):
        return self._normalize_currency_fields(self._dummy_budget.get("accounts", []))

    def get_accounts(self, budget_id):
        return self._normalize_currency_fields([a.to_dict() for a in self.accounts_api.get_accounts(budget_id).data.accounts])
    
    # --- 🔹 Transaction Management ---

    def get_transactions(self, budget_id, since_date=None):
        transactions = self.transactions_api.get_transactions(budget_id, since_date).data.transactions
        txns_dict = [t.to_dict() for t in transactions]
        normalized = self._normalize_currency_fields(txns_dict)
        return normalized
   
    def get_scheduled_transactions(self, budget_id):
        return self._normalize_currency_fields([a.to_dict() for a in self.scheduled_transactions_api.get_scheduled_transactions(budget_id).data.scheduled_transactions])

    def create_scheduled_transaction(self, budget_id, data):
        response = self.scheduled_transactions_api.create_scheduled_transaction(budget_id, data)
        self.invalidate_cache_for('get_scheduled_transactions', budget_id)
        return self._normalize_currency_fields(response)

    def get_scheduled_transaction_by_id(self, budget_id, scheduled_transaction_id):
        return self._normalize_currency_fields(
            self.scheduled_transactions_api.get_scheduled_transaction_by_id(budget_id, scheduled_transaction_id).data.scheduled_transaction.to_dict()
        )

    def update_scheduled_transaction(self, budget_id, scheduled_transaction_id, data):
        updated = self.scheduled_transactions_api.update_scheduled_transaction(budget_id, scheduled_transaction_id, data)
        self.invalidate_cache_for('get_scheduled_transactions', budget_id)
        return updated

    def delete_scheduled_transaction(self, budget_id, scheduled_transaction_id):
        deleted = self.scheduled_transactions_api.delete_scheduled_transaction(budget_id, scheduled_transaction_id)
        self.invalidate_cache_for('get_scheduled_transactions', budget_id)
        return deleted
 
    def create_transaction(self, budget_id, transaction_data):
        created = self.transactions_api.create_transaction(budget_id, transaction_data)
        self.invalidate_cache_for('get_transactions', budget_id)
        return created

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


    # --- token compression --- # 

    # === Slim Text Summarizers for YNAB ===

    def slim_accounts_text(self, accounts):
        """Slim down accounts with ID and balance info."""
        return "\n".join(
            f"{acct['name']}: {acct.get('balance_display', 'unknown')} (id: {acct.get('id', 'missing_id')})"
            for acct in accounts
        )

    def slim_scheduled_transactions_text(self, scheduled_txns):
        """Slim down scheduled transactions with payee, amount, date, and id."""
        return "\n".join(
            f"Linked Account ID : {txn.get('account_id', 'Unknown Account')}, Next date for transaction : {txn.get('date_next', 'Unknown Date')}, Payee: {txn.get('payee_name', 'Unnamed Payee')}, Amount: {txn.get('amount_display', 'Unknown Amount')} Specific Transaction ID : (transaction_id: {txn.get('id', 'missing_id')})"
            for txn in scheduled_txns
        )

    def slim_categories_text(self, categories):
        """Slim down categories with name, balance, and id."""
        lines = []
        for group in categories:
            group_name = group.get('name', 'Unnamed Group')
            lines.append(f"\n{group_name}:")
            for cat in group.get('categories', []):
                name = cat.get('name', 'Unnamed Category')
                balance = cat.get('balance_display', 'unknown')
                category_id = cat.get('id', 'missing_id')
                lines.append(f"  {name}: {balance} (id: {category_id})")
        return "\n".join(lines)

    def slim_transactions_text(self, transactions):
        """Slim down real transactions with basic details and id."""
        return "\n".join(
            f"{txn.get('date', 'Unknown Date')}: {txn.get('payee_name', 'Unnamed Payee')} - {txn.get('amount_display', 'Unknown Amount')} (id: {txn.get('id', 'missing_id')})"
            for txn in transactions
        )

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

    def _save_cache(self, key, value, source=None):
        path = self._get_cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(".tmp")
        with open(tmp_path, "w") as f:
            json.dump({
                "fetched_at": datetime.now().isoformat(),
                "source": source or "unknown",
                "schema_version": 1,
                "value": value
            }, f, indent=2)
        os.replace(tmp_path, path)  # atomic replacement


    def invalidate_cache_for(self, func_name, *args, **kwargs):
        """Invalidate (delete) cache for a specific function call."""
        key = self._cache_key(func_name, args, kwargs)
        path = self._get_cache_path(key)
        if path.exists():
            path.unlink()
            logger.info(f"[CACHE INVALIDATED] {func_name} with args={args}")
        else:
            logger.info(f"[CACHE INVALIDATION SKIPPED] No cache found for {func_name} with args={args}")

    def cacheable(self, func):
        def wrapper(*args, **kwargs):
            key = self._cache_key(func.__name__, args, kwargs)
            cached = self._load_cache(key)
            if cached is not None:
                logger.info(f"[CACHE HIT] {func.__name__}")
                return cached
            logger.info(f"[CACHE MISS] {func.__name__}")
            result = func(*args, **kwargs)
            self._save_cache(key, result, source=func.__name__)
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


