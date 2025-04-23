#Deprecated, keeping for reference only
import requests
import os
from dotenv import load_dotenv

load_dotenv()
ACCESS_TOKEN = os.getenv("YNAB_TOKEN")

class YNABClient:
    def __init__(self):
        self.base_url = "https://api.ynab.com/v1"
        self.headers = {
            "Authorization": f"Bearer {ACCESS_TOKEN}",
            "Accept": "application/json"
        }

    def get_budgets(self):
        return requests.get(f"{self.base_url}/budgets", headers=self.headers).json()

    def get_budget_details(self, budget_id):
        return requests.get(f"{self.base_url}/budgets/{budget_id}", headers=self.headers).json()

    def get_transactions(self, budget_id, since_date=None):
        url = f"{self.base_url}/budgets/{budget_id}/transactions"
        if since_date:
            url += f"?since_date={since_date}"
        return requests.get(url, headers=self.headers).json()

    def get_accounts(self, budget_id):
        return requests.get(f"{self.base_url}/budgets/{budget_id}/accounts", headers=self.headers).json()
