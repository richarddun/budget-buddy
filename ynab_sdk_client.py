import os
from dotenv import load_dotenv
from ynab import Configuration, ApiClient, BudgetsApi, TransactionsApi, AccountsApi
from datetime import datetime, timedelta
import json

load_dotenv()
ACCESS_TOKEN = os.getenv("YNAB_TOKEN")

class YNABSdkClient:
    def __init__(self):
        self.config = Configuration(access_token=ACCESS_TOKEN)
        self.api_client = ApiClient(self.config)
        self.budgets_api = BudgetsApi(self.api_client)
        self.transactions_api = TransactionsApi(self.api_client)
        self.accounts_api = AccountsApi(self.api_client)

    def get_all_budgets(self):
        budgets = self.budgets_api.get_budgets().data.budgets
        return budgets

    def get_first_budget_id(self):
        budgets = self.budgets_api.get_budgets().data.budgets
        return budgets[0].id if budgets else None

    def get_budget_details(self, budget_id):
        return self.budgets_api.get_budget_by_id(budget_id).data.budget

    def get_accounts(self, budget_id):
        return self.accounts_api.get_accounts(budget_id).data.accounts

    def get_transactions(self, budget_id, since_date=None):
        """Get transactions from YNAB API.  Check for local cache first and 
           create cache with results if not already present.
           Return from cache or API depending on whether TTL has been exceeded"""
        
        CACHE_FILE = "cached_transactions.json"
        CACHE_TTL_HOURS = 12
        client = YNABSdkClient()

        if not os.path.exists(CACHE_FILE):
            budget_id = client.get_first_budget_id()
            transactions = client.get_transactions(budget_id)
            with open(CACHE_FILE, "w") as f:
                json.dump({
                "fetched_at": datetime.now().isoformat(),
                "transactions": [t.to_dict() for t in transactions]
                }, f, indent=2)
                return [t.to_dict() for t in transactions]
            
        with open(CACHE_FILE, "r") as f:
            data = json.load(f)
            timestamp = datetime.fromisoformat(data.get("fetched_at"))
            if datetime.now() - timestamp > timedelta(hours=CACHE_TTL_HOURS):
                budget_id = client.get_first_budget_id()
                transactions = client.get_transactions(budget_id)
                # yes yes, I know, just this once I can enjoy typing =/
                with open(CACHE_FILE, "w") as f:
                    json.dump({
                    "fetched_at": datetime.now().isoformat(),
                    "transactions": [t.to_dict() for t in transactions]
                    }, f, indent=2)
                return [t.to_dict() for t in transactions]
            return data.get("transactions")
