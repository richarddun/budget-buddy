"""Minimal YNAB API client used for testing without the real SDK."""

import requests


class Configuration:
    def __init__(self, access_token=None, base_url="https://api.youneedabudget.com/v1"):
        self.access_token = access_token
        self.base_url = base_url

class ApiClient:
    def __init__(self, config: Configuration):
        self.config = config

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.config.access_token}",
            "accept": "application/json",
        }

    def get(self, endpoint, params=None):
        url = f"{self.config.base_url}{endpoint}"
        resp = requests.get(url, headers=self.headers, params=params)
        resp.raise_for_status()
        return resp.json()

    def post(self, endpoint, payload=None):
        url = f"{self.config.base_url}{endpoint}"
        resp = requests.post(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def put(self, endpoint, payload=None):
        url = f"{self.config.base_url}{endpoint}"
        resp = requests.put(url, json=payload, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

    def delete(self, endpoint):
        url = f"{self.config.base_url}{endpoint}"
        resp = requests.delete(url, headers=self.headers)
        resp.raise_for_status()
        return resp.json()

class _SimpleObject:
    """Wrapper that exposes a to_dict method for raw data."""

    def __init__(self, data):
        self._data = data

    def to_dict(self):
        return self._data


class _Response:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


class BudgetsApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_budget_by_id(self, budget_id: str):
        resp = self.client.get(f"/budgets/{budget_id}")
        budget = _SimpleObject(resp.get("data", {}).get("budget", {}))
        return _Response(data=_Response(budget=budget))

class TransactionsApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_transactions(self, budget_id: str, since_date: str | None = None):
        params = {"since_date": since_date} if since_date else None
        resp = self.client.get(f"/budgets/{budget_id}/transactions", params=params)
        txns = [
            _SimpleObject(t) for t in resp.get("data", {}).get("transactions", [])
        ]
        return _Response(data=_Response(transactions=txns))

    def create_transaction(self, budget_id: str, payload):
        body = payload.to_dict() if hasattr(payload, "to_dict") else payload
        resp = self.client.post(f"/budgets/{budget_id}/transactions", body)
        return _SimpleObject(resp)

class AccountsApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_accounts(self, budget_id: str):
        resp = self.client.get(f"/budgets/{budget_id}/accounts")
        accts = [
            _SimpleObject(a) for a in resp.get("data", {}).get("accounts", [])
        ]
        return _Response(data=_Response(accounts=accts))

class ScheduledTransactionsApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_scheduled_transactions(self, budget_id: str):
        resp = self.client.get(f"/budgets/{budget_id}/scheduled_transactions")
        txns = [
            _SimpleObject(t)
            for t in resp.get("data", {}).get("scheduled_transactions", [])
        ]
        return _Response(data=_Response(scheduled_transactions=txns))

    def create_scheduled_transaction(self, budget_id: str, payload):
        body = payload.to_dict() if hasattr(payload, "to_dict") else payload
        resp = self.client.post(
            f"/budgets/{budget_id}/scheduled_transactions", body
        )
        return _SimpleObject(resp)

    def get_scheduled_transaction_by_id(self, budget_id: str, st_id: str):
        resp = self.client.get(
            f"/budgets/{budget_id}/scheduled_transactions/{st_id}"
        )
        txn = _SimpleObject(resp.get("data", {}).get("scheduled_transaction", {}))
        return _Response(data=_Response(scheduled_transaction=txn))

    def update_scheduled_transaction(self, budget_id: str, st_id: str, payload):
        body = payload.to_dict() if hasattr(payload, "to_dict") else payload
        resp = self.client.put(
            f"/budgets/{budget_id}/scheduled_transactions/{st_id}", body
        )
        return _SimpleObject(resp)

    def delete_scheduled_transaction(self, budget_id: str, st_id: str):
        return self.client.delete(
            f"/budgets/{budget_id}/scheduled_transactions/{st_id}"
        )

class CategoriesApi:
    def __init__(self, client: ApiClient):
        self.client = client

    def get_categories(self, budget_id: str):
        resp = self.client.get(f"/budgets/{budget_id}/categories")
        groups = [
            _SimpleObject(g)
            for g in resp.get("data", {}).get("category_groups", [])
        ]
        return _Response(data=_Response(category_groups=groups))

    def get_category_by_id(self, budget_id: str, category_id: str):
        resp = self.client.get(
            f"/budgets/{budget_id}/categories/{category_id}"
        )
        cat = _SimpleObject(resp.get("data", {}).get("category", {}))
        return _Response(data=_Response(category=cat))

    def update_category(self, budget_id: str, category_id: str, payload):
        body = payload.to_dict() if hasattr(payload, "to_dict") else payload
        resp = self.client.put(
            f"/budgets/{budget_id}/categories/{category_id}", body
        )
        return _SimpleObject(resp)

    def update_month_category(self, budget_id: str, month: str, category_id: str, payload):
        body = payload.to_dict() if hasattr(payload, "to_dict") else payload
        resp = self.client.put(
            f"/budgets/{budget_id}/months/{month}/categories/{category_id}", body
        )
        return _SimpleObject(resp)

class ApiException(Exception):
    pass

class BadRequestException(Exception):
    pass
