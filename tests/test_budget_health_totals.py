import pytest

from budget_health_analyzer import BudgetHealthAnalyzer


def test_calculate_budget_totals_ignores_category_balances():
    analyzer = BudgetHealthAnalyzer(budget_id="dummy")
    analyzer._budget_data = {
        "categories": [
            {"deleted": False, "hidden": False, "budgeted": 100, "activity": -40, "balance": 60},
            {"deleted": False, "hidden": False, "budgeted": 0, "activity": 20, "balance": 20},
            {"deleted": False, "hidden": False, "budgeted": 0, "activity": 0, "balance": 1000},
        ]
    }

    budgeted, spent, remaining = analyzer._calculate_budget_totals()

    assert budgeted == 100
    assert spent == 20  # Net spending 40 with a 20 refund
    assert remaining == 80  # 100 budgeted - 20 spent
