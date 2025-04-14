import os
from dotenv import load_dotenv
from ynab import Configuration, ApiClient, BudgetsApi, TransactionsApi, AccountsApi

load_dotenv()
ACCESS_TOKEN = os.getenv("YNAB_TOKEN")

class YNABSdkClient:
    def __init__(self):
        self.config = Configuration(access_token=ACCESS_TOKEN)
        self.api_client = ApiClient(self.config)
        self.budgets_api = BudgetsApi(self.api_client)
        self.transactions_api = TransactionsApi(self.api_client)
        self.accounts_api = AccountsApi(self.api_client)

    def get_first_budget_id(self):
        budgets = self.budgets_api.get_budgets().data.budgets
        return budgets[0].id if budgets else None

    def get_budget_details(self, budget_id):
        return self.budgets_api.get_budget_by_id(budget_id).data.budget

    def get_accounts(self, budget_id):
        return self.accounts_api.get_accounts(budget_id).data.accounts

    def get_transactions(self, budget_id, since_date=None):
        return self.transactions_api.get_transactions(budget_id, since_date).data.transactions
