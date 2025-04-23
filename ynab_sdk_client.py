import os
from dotenv import load_dotenv
from ynab import Configuration, ApiClient, BudgetsApi, TransactionsApi, AccountsApi
from datetime import datetime, timedelta
import json

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

    # 🔸 Public method that uses caching
    def get_transactions(self, budget_id, since_date=None):
        if self._cache_expired():
            transactions = self._fetch_and_cache_transactions(budget_id, since_date)
        else:
            with open(self.CACHE_FILE, "r") as f:
                data = json.load(f)
                transactions = data.get("transactions")
        return transactions

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


    def get_budget_details(self, budget_id):
        return self.budgets_api.get_budget_by_id(budget_id).data.budget

    def get_accounts(self, budget_id):
        return self.accounts_api.get_accounts(budget_id).data.accounts


