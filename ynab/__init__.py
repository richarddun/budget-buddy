class Configuration:
    def __init__(self, access_token=None):
        self.access_token = access_token

class ApiClient:
    def __init__(self, config):
        self.config = config

class BudgetsApi:
    def __init__(self, client):
        pass

class TransactionsApi:
    def __init__(self, client):
        pass

class AccountsApi:
    def __init__(self, client):
        pass

class ScheduledTransactionsApi:
    def __init__(self, client):
        pass

class CategoriesApi:
    def __init__(self, client):
        pass

class ApiException(Exception):
    pass

class BadRequestException(Exception):
    pass
