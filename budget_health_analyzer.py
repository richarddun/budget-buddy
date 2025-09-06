#!/usr/bin/env python3
"""
Budget Health Analyzer

A standalone script that analyzes YNAB budget data and generates an HTML health report.
This can be integrated into FastAPI routes or run independently.
"""

from datetime import datetime, timedelta
from collections import defaultdict
from typing import Dict, List, Any, Tuple, Optional
from dataclasses import dataclass
import logging

from ynab_sdk_client import YNABSdkClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class BudgetHealthMetrics:
    """Container for budget health analysis results"""
    total_budgeted: float
    total_spent: float
    total_remaining: float
    overspent_categories: List[Dict[str, Any]]
    underfunded_goals: List[Dict[str, Any]]
    recent_spending_trend: Dict[str, float]  # last 7, 14, 30 days
    account_summary: List[Dict[str, Any]]
    category_analysis: List[Dict[str, Any]]
    top_spending_categories: List[Dict[str, Any]]
    spending_by_payee: List[Dict[str, Any]]
    recurring_transactions: List[Dict[str, Any]]  # detected recurring payments
    calendar_heat_map: Dict[str, Any]  # calendar data with transaction frequency
    health_score: float  # 0-100 overall health score


class BudgetHealthAnalyzer:
    def __init__(self, budget_id: Optional[str] = None):
        """
        Initialize the budget health analyzer

        Args:
            budget_id: YNAB budget ID. If None, will use the first available budget
        """
        self.client = YNABSdkClient()
        self.budget_id = budget_id
        self._budget_data = None
        self._transaction_data = None

    def _get_budget_id(self) -> str:
        """Get budget ID, using first available if not specified"""
        if self.budget_id:
            return self.budget_id

        # This would need to be implemented in the client if not available
        # For now, assume we have the budget ID
        raise ValueError("Budget ID must be provided")

    def _load_data(self) -> None:
        """Load budget and transaction data from YNAB"""
        budget_id = self._get_budget_id()

        logger.info("Loading budget data...")
        self._budget_data = self.client.get_budget_details(budget_id)

        logger.info("Loading transaction data...")
        # Prefer loading transactions from the budget's first available month for fuller cashflow
        since_date = None
        try:
            since_date = self._budget_data.get('first_month')  # e.g., '2024-08-01'
        except Exception:
            since_date = None

        # Fallback: last 90 days if first_month is missing
        if not since_date:
            since_date = (datetime.now() - timedelta(days=90)).date().isoformat()

        self._transaction_data = self.client.get_transactions(budget_id, since_date)

        logger.info(f"Loaded {len(self._transaction_data or [])} transactions")

    def analyze(self) -> BudgetHealthMetrics:
        """Perform comprehensive budget health analysis"""
        if not self._budget_data or not self._transaction_data:
            self._load_data()

        logger.info("Analyzing budget health...")

        # Calculate core metrics
        total_budgeted, total_spent, total_remaining = self._calculate_budget_totals()
        overspent_categories = self._find_overspent_categories()
        underfunded_goals = self._find_underfunded_goals()
        recent_trends = self._analyze_spending_trends()
        account_summary = self._summarize_accounts()
        category_analysis = self._analyze_categories()
        top_spending = self._get_top_spending_categories()
        spending_by_payee = self._analyze_spending_by_payee()
        recurring_transactions = self._detect_recurring_transactions()
        calendar_heat_map = self._generate_calendar_heat_map()
        health_score = self._calculate_health_score(
            total_budgeted, total_spent, overspent_categories, underfunded_goals
        )

        return BudgetHealthMetrics(
            total_budgeted=total_budgeted,
            total_spent=abs(total_spent),  # Make spending positive for display
            total_remaining=total_remaining,
            overspent_categories=overspent_categories,
            underfunded_goals=underfunded_goals,
            recent_spending_trend=recent_trends,
            account_summary=account_summary,
            category_analysis=category_analysis,
            top_spending_categories=top_spending,
            spending_by_payee=spending_by_payee,
            recurring_transactions=recurring_transactions,
            calendar_heat_map=calendar_heat_map,
            health_score=health_score
        )

    def _calculate_cashflow_totals(self) -> Dict[str, float]:
        """
        Calculate inflows, outflows, and net from transactions.
        Returns a dict with keys: inflows_all, outflows_all, net_all,
        inflows_mtd, outflows_mtd, net_mtd
        """
        inflows_all = 0.0
        outflows_all = 0.0
        inflows_mtd = 0.0
        outflows_mtd = 0.0

        if not self._transaction_data:
            return {
                'inflows_all': 0.0,
                'outflows_all': 0.0,
                'net_all': 0.0,
                'inflows_mtd': 0.0,
                'outflows_mtd': 0.0,
                'net_mtd': 0.0,
            }

        now = datetime.now()
        month_start = now.replace(day=1).date()

        for tx in self._transaction_data:
            amt = tx.get('amount', 0) or 0.0
            # Parse date safely
            try:
                tx_date = datetime.fromisoformat(tx.get('date', '')).date()
            except Exception:
                tx_date = None

            if amt > 0:
                inflows_all += amt
                if tx_date and tx_date >= month_start:
                    inflows_mtd += amt
            elif amt < 0:
                outflows_all += abs(amt)
                if tx_date and tx_date >= month_start:
                    outflows_mtd += abs(amt)

        return {
            'inflows_all': inflows_all,
            'outflows_all': outflows_all,
            'net_all': inflows_all - outflows_all,
            'inflows_mtd': inflows_mtd,
            'outflows_mtd': outflows_mtd,
            'net_mtd': inflows_mtd - outflows_mtd,
        }

    def _render_cashflow_section(self) -> str:
        """Render HTML snippet for the cashflow card"""
        cf = self._calculate_cashflow_totals()
        return (
            f"""
            <div class=\"metric\">
                <span>All-time Inflows:</span>
                <span class=\"metric-value\">€{cf['inflows_all']:,.2f}</span>
            </div>
            <div class=\"metric\">
                <span>All-time Outflows:</span>
                <span class=\"metric-value negative\">€{cf['outflows_all']:,.2f}</span>
            </div>
            <div class=\"metric\">
                <span>All-time Net:</span>
                <span class=\"metric-value {('positive' if cf['net_all'] >= 0 else 'negative')}\">€{cf['net_all']:,.2f}</span>
            </div>
            <div class=\"metric\" style=\"margin-top:12px; color:#666\">
                <span>Month-to-date Inflows:</span>
                <span class=\"metric-value\">€{cf['inflows_mtd']:,.2f}</span>
            </div>
            <div class=\"metric\">
                <span>Month-to-date Outflows:</span>
                <span class=\"metric-value negative\">€{cf['outflows_mtd']:,.2f}</span>
            </div>
            <div class=\"metric\">
                <span>Month-to-date Net:</span>
                <span class=\"metric-value {('positive' if cf['net_mtd'] >= 0 else 'negative')}\">€{cf['net_mtd']:,.2f}</span>
            </div>
            """
        )

    def _calculate_budget_totals(self) -> Tuple[float, float, float]:
        """Calculate total budgeted, spent, and remaining amounts"""
        total_budgeted = 0
        total_activity = 0
        total_balance = 0

        if self._budget_data:
            for category in self._budget_data.get('categories', []):
                if not category.get('deleted', False) and not category.get('hidden', False):
                    total_budgeted += category.get('budgeted', 0) or 0
                    total_activity += category.get('activity', 0) or 0
                    total_balance += category.get('balance', 0) or 0

        return total_budgeted, total_activity, total_balance

    def _find_overspent_categories(self) -> List[Dict[str, Any]]:
        """Find categories that are overspent (negative balance)"""
        overspent = []

        if self._budget_data:
            for category in self._budget_data.get('categories', []):
                if (not category.get('deleted', False) and
                    not category.get('hidden', False) and
                    category.get('balance', 0) < 0):

                    overspent.append({
                        'name': category.get('name', 'Unknown'),
                        'budgeted': category.get('budgeted', 0),
                        'spent': abs(category.get('activity', 0)),
                        'overspent_amount': abs(category.get('balance', 0)),
                        'overspent_display': category.get('balance_display', '€0.00')
                    })

        return sorted(overspent, key=lambda x: x.get('overspent_amount', 0) or 0, reverse=True)

    def _find_underfunded_goals(self) -> List[Dict[str, Any]]:
        """Find categories with goals that are underfunded"""
        underfunded = []

        if self._budget_data:
            for category in self._budget_data.get('categories', []):
                goal_under_funded = category.get('goal_under_funded', 0) or 0
                if (not category.get('deleted', False) and
                    category.get('goal_type') and
                    goal_under_funded > 0):

                    underfunded.append({
                        'name': category.get('name', 'Unknown'),
                        'goal_target': category.get('goal_target', 0),
                        'goal_target_display': category.get('goal_target_display', '€0.00'),
                        'under_funded': goal_under_funded,
                        'under_funded_display': category.get('goal_under_funded_display', '€0.00'),
                        'percentage_complete': category.get('goal_percentage_complete', 0)
                    })

        return sorted(underfunded, key=lambda x: x.get('under_funded', 0) or 0, reverse=True)

    def _analyze_spending_trends(self) -> Dict[str, float]:
        """Analyze spending trends over different time periods"""
        now = datetime.now().date()
        trends: Dict[str, float] = {
            'last_7_days': 0.0,
            'last_14_days': 0.0,
            'last_30_days': 0.0
        }

        if self._transaction_data:
            for transaction in self._transaction_data:
                if transaction.get('amount', 0) >= 0:  # Skip income transactions
                    continue

                tx_date = datetime.fromisoformat(transaction.get('date', '')).date()
                amount = abs(transaction.get('amount', 0))

                days_ago = (now - tx_date).days

                if days_ago <= 7:
                    trends['last_7_days'] += amount
                if days_ago <= 14:
                    trends['last_14_days'] += amount
                if days_ago <= 30:
                    trends['last_30_days'] += amount

        return trends

    def _summarize_accounts(self) -> List[Dict[str, Any]]:
        """Summarize account balances and status"""
        accounts = []

        if self._budget_data:
            for account in self._budget_data.get('accounts', []):
                if not account.get('deleted', False) and account.get('on_budget', True):
                    accounts.append({
                        'name': account.get('name', 'Unknown'),
                        'type': account.get('type', 'unknown'),
                        'balance': account.get('balance', 0),
                        'balance_display': account.get('balance_display', '€0.00'),
                        'cleared_balance': account.get('cleared_balance', 0),
                        'cleared_balance_display': account.get('cleared_balance_display', '€0.00')
                    })

        return sorted(accounts, key=lambda x: x.get('balance', 0) or 0, reverse=True)

    def _analyze_categories(self) -> List[Dict[str, Any]]:
        """Analyze category performance"""
        categories = []

        # Group categories by category group for better organization
        category_groups = defaultdict(list)

        if self._budget_data:
            for category in self._budget_data.get('categories', []):
                if not category.get('deleted', False) and not category.get('hidden', False):
                    category_data = {
                        'name': category.get('name', 'Unknown'),
                        'budgeted': category.get('budgeted', 0),
                        'budgeted_display': category.get('budgeted_display', '€0.00'),
                        'activity': category.get('activity', 0),
                        'activity_display': category.get('activity_display', '€0.00'),
                        'balance': category.get('balance', 0),
                        'balance_display': category.get('balance_display', '€0.00'),
                        'utilization': self._calculate_utilization(
                            category.get('budgeted', 0),
                            category.get('activity', 0)
                        )
                    }

                    categories.append(category_data)

        return sorted(categories, key=lambda x: abs(x.get('activity', 0) or 0), reverse=True)

    def _calculate_utilization(self, budgeted: float, activity: float) -> float:
        """Calculate budget utilization percentage"""
        if budgeted <= 0:
            return 0 if activity >= 0 else 100
        return min(100, (abs(activity) / budgeted) * 100)

    def _get_top_spending_categories(self) -> List[Dict[str, Any]]:
        """Get top spending categories from recent transactions"""
        category_spending = defaultdict(float)
        category_names = {}

        # Build category name lookup
        if self._budget_data:
            for category in self._budget_data.get('categories', []):
                category_names[category.get('id')] = category.get('name', 'Unknown')

        # Aggregate spending by category
        if self._transaction_data:
            for transaction in self._transaction_data:
                if transaction.get('amount', 0) < 0:  # Only spending transactions
                    category_id = transaction.get('category_id')
                    if category_id:
                        amount = abs(transaction.get('amount', 0))
                        category_spending[category_id] += amount

        # Convert to list and sort
        top_categories = []
        for category_id, amount in category_spending.items():
            top_categories.append({
                'name': category_names.get(category_id, 'Unknown'),
                'amount': amount,
                'amount_display': f'€{amount:,.2f}'
            })

        return sorted(top_categories, key=lambda x: x.get('amount', 0) or 0, reverse=True)[:10]

    def _analyze_spending_by_payee(self) -> List[Dict[str, Any]]:
        """Analyze spending by payee"""
        payee_spending = defaultdict(float)

        if self._transaction_data:
            for transaction in self._transaction_data:
                if transaction.get('amount', 0) < 0:  # Only spending
                    payee_name = transaction.get('payee_name', 'Unknown')
                    amount = abs(transaction.get('amount', 0))
                    payee_spending[payee_name] += amount

        payees = []
        for payee, amount in payee_spending.items():
            payees.append({
                'name': payee,
                'amount': amount,
                'amount_display': f'€{amount:,.2f}'
            })

        return sorted(payees, key=lambda x: x.get('amount', 0) or 0, reverse=True)[:10]

    def _calculate_health_score(self, budgeted: float, spent: float,
                              overspent_categories: List, underfunded_goals: List) -> float:
        """Calculate overall budget health score (0-100)"""
        score = 100

        # Deduct for overspending
        if budgeted > 0:
            overspend_ratio = min(1.0, abs(spent) / budgeted)
            if overspend_ratio > 1:
                score -= (overspend_ratio - 1) * 50

        # Deduct for overspent categories
        score -= min(30, len(overspent_categories) * 5)

        # Deduct for underfunded goals
        score -= min(20, len(underfunded_goals) * 3)

        return max(0, score)

    def _detect_recurring_transactions(self) -> List[Dict[str, Any]]:
        """Detect recurring transactions by analyzing patterns in payee and amount"""
        recurring = []

        if not self._transaction_data:
            return recurring

        # Group transactions by payee and amount (rounded to avoid minor variations)
        payee_patterns = defaultdict(lambda: defaultdict(list))

        for transaction in self._transaction_data:
            if transaction.get('amount', 0) >= 0:  # Skip income
                continue

            payee_name = transaction.get('payee_name', 'Unknown')
            amount = abs(transaction.get('amount', 0))
            rounded_amount = round(amount, 0)  # Round to nearest euro for grouping
            date_str = transaction.get('date', '')

            if date_str and payee_name != 'Unknown':
                try:
                    tx_date = datetime.fromisoformat(date_str).date()
                    payee_patterns[payee_name][rounded_amount].append({
                        'date': tx_date,
                        'amount': amount,
                        'transaction_id': transaction.get('id'),
                        'day_of_month': tx_date.day
                    })
                except ValueError:
                    continue

        # Identify recurring patterns (3+ transactions with same payee/amount)
        for payee_name, amount_groups in payee_patterns.items():
            for amount, transactions in amount_groups.items():
                if len(transactions) >= 3:  # Need at least 3 instances to be considered recurring
                    # Calculate average days between transactions
                    dates = [tx['date'] for tx in transactions]
                    dates.sort()

                    if len(dates) >= 2:
                        intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
                        avg_interval = sum(intervals) / len(intervals)

                        # Consider it recurring if average interval is between 25-35 days (monthly)
                        # or 6-8 days (weekly) or around 90 days (quarterly)
                        is_recurring = (25 <= avg_interval <= 35 or
                                      6 <= avg_interval <= 8 or
                                      85 <= avg_interval <= 95)

                        if is_recurring:
                            # Get most common day of month
                            days_of_month = [tx['day_of_month'] for tx in transactions]
                            most_common_day = max(set(days_of_month), key=days_of_month.count)

                            recurring.append({
                                'payee_name': payee_name,
                                'amount': amount,
                                'amount_display': f'€{amount:,.2f}',
                                'frequency_count': len(transactions),
                                'avg_interval_days': round(avg_interval, 1),
                                'most_common_day': most_common_day,
                                'frequency_type': self._classify_frequency(avg_interval),
                                'last_transaction_date': max(dates).isoformat(),
                                'transactions': transactions[-3:]  # Keep last 3 transactions as examples
                            })

        return sorted(recurring, key=lambda x: x.get('amount', 0) or 0, reverse=True)

    def _classify_frequency(self, avg_interval: float) -> str:
        """Classify transaction frequency based on average interval"""
        if 6 <= avg_interval <= 8:
            return "Weekly"
        elif 25 <= avg_interval <= 35:
            return "Monthly"
        elif 85 <= avg_interval <= 95:
            return "Quarterly"
        else:
            return f"Every {avg_interval:.0f} days"

    def _generate_calendar_heat_map(self) -> Dict[str, Any]:
        """Generate calendar heat map data showing transaction frequency by day of month"""
        if not self._transaction_data:
            return {'days': {}, 'max_frequency': 0}

        # Count transactions by day of month
        day_counts = defaultdict(int)
        day_amounts = defaultdict(float)

        for transaction in self._transaction_data:
            if transaction.get('amount', 0) >= 0:  # Skip income
                continue

            date_str = transaction.get('date', '')
            if date_str:
                try:
                    tx_date = datetime.fromisoformat(date_str).date()
                    day_of_month = tx_date.day
                    amount = abs(transaction.get('amount', 0))

                    day_counts[day_of_month] += 1
                    day_amounts[day_of_month] += amount
                except ValueError:
                    continue

        max_frequency = max(day_counts.values()) if day_counts else 0
        max_amount = max(day_amounts.values()) if day_amounts else 0

        # Generate heat map data for all 31 possible days
        heat_map_days = {}
        for day in range(1, 32):
            frequency = day_counts.get(day, 0)
            total_amount = day_amounts.get(day, 0)

            # Calculate intensity (0-1) based on frequency
            intensity = frequency / max_frequency if max_frequency and max_frequency > 0 else 0

            heat_map_days[str(day)] = {
                'day': day,
                'frequency': frequency,
                'total_amount': total_amount,
                'total_amount_display': f'€{total_amount:,.2f}',
                'intensity': intensity,
                'color_opacity': min(0.1 + (intensity * 0.8), 0.9)  # 0.1 to 0.9 opacity
            }

        return {
            'days': heat_map_days,
            'max_frequency': max_frequency,
            'max_amount': max_amount,
            'max_amount_display': f'€{max_amount:,.2f}' if max_amount > 0 else '€0.00',
            'total_transaction_days': len(day_counts)
        }

    def generate_html_report(self, metrics: Optional[BudgetHealthMetrics] = None) -> str:
        """Generate HTML budget health report"""
        if metrics is None:
            metrics = self.analyze()

        # Determine health status color and message
        if metrics.health_score >= 80:
            health_color = "#4CAF50"
            health_status = "Excellent"
        elif metrics.health_score >= 60:
            health_color = "#FF9800"
            health_status = "Good"
        elif metrics.health_score >= 40:
            health_color = "#FF5722"
            health_status = "Fair"
        else:
            health_color = "#F44336"
            health_status = "Poor"

        html = f"""
        <!DOCTYPE html>
        <html lang="en">
        <head>
            <meta charset="UTF-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Budget Health Report</title>
            <style>
                body {{ font-family: Arial, sans-serif; margin: 0; padding: 20px; background-color: #f5f5f5; }}
                .container {{ max-width: 1200px; margin: 0 auto; background: white; border-radius: 10px; box-shadow: 0 2px 10px rgba(0,0,0,0.1); }}
                .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
                .health-score {{ font-size: 48px; font-weight: bold; color: {health_color}; }}
                .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; padding: 20px; }}
                .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1);width: fit-content; }}
                .card h3 {{ margin-top: 0; color: #333; border-bottom: 2px solid #667eea; padding-bottom: 10px; }}
                .metric {{ display: flex; justify-content: space-between; margin: 10px 0; }}
                .metric-value {{ font-weight: bold; }}
                .positive {{ color: #4CAF50; }}
                .negative {{ color: #F44336; }}
                .warning {{ color: #FF9800; }}
                .table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                .table th, .table td {{ text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }}
                .table th {{ background-color: #f8f9fa; }}
                .progress-bar {{ background: #ddd; border-radius: 4px; height: 20px; overflow: hidden; margin: 5px 0; }}
                .progress {{ height: 100%; background: #4CAF50; transition: width 0.3s ease; }}
                .alert {{ padding: 15px; margin: 10px 0; border-radius: 4px; }}
                .alert-danger {{ background-color: #f8d7da; color: #721c24; border: 1px solid #f5c6cb; }}
                .alert-warning {{ background-color: #fff3cd; color: #856404; border: 1px solid #ffeaa7; }}
                .alert-success {{ background-color: #d4edda; color: #155724; border: 1px solid #c3e6cb; }}
                .timestamp {{ text-align: center; color: #666; font-size: 12px; padding: 10px; }}
                .calendar-container {{ display: flex; justify-content: center; margin: 20px 0; }}
                .calendar-grid {{ display: grid; grid-template-columns: repeat(7, 50px); gap: 5px; }}
                .calendar-day {{
                    width: 50px; height: 50px; border: 1px solid #ddd; border-radius: 8px;
                    display: flex; align-items: center; justify-content: center;
                    font-weight: bold; position: relative; cursor: pointer;
                    transition: all 0.3s ease;
                }}
                .calendar-day:hover {{ transform: scale(1.1); z-index: 10; }}
                .calendar-day.active {{ background-color: rgba(220, 53, 69, var(--opacity)); color: white; }}
                .calendar-day.medium {{ background-color: rgba(255, 193, 7, var(--opacity)); }}
                .calendar-day.low {{ background-color: rgba(108, 117, 125, 0.1); }}
                .calendar-tooltip {{
                    position: absolute; bottom: 60px; left: 50%; transform: translateX(-50%);
                    background: rgba(0,0,0,0.9); color: white; padding: 8px 12px;
                    border-radius: 4px; font-size: 12px; white-space: nowrap;
                    display: none; z-index: 20;
                }}
                .calendar-day:hover .calendar-tooltip {{ display: block; }}
                .calendar-legend {{ text-align: center; margin-top: 15px; font-size: 14px; }}
            </style>
        </head>
        <body>
            <div class="container">
                <div class="header">
                    <h1>Budget Health Report</h1>
                    <div class="health-score">{metrics.health_score:.0f}/100</div>
                    <div style="font-size: 18px; margin-top: 10px;">Status: {health_status}</div>
                </div>

                <div class="grid">
                    <!-- Budget Overview -->
                    <div class="card">
                        <h3>📊 Budget Overview</h3>
                        <div class="metric">
                            <span>Total Budgeted:</span>
                            <span class="metric-value">€{metrics.total_budgeted:,.2f}</span>
                        </div>
                        <div class="metric">
                            <span>Total Spent:</span>
                            <span class="metric-value negative">€{metrics.total_spent:,.2f}</span>
                        </div>
                        <div class="metric">
                            <span>Remaining:</span>
                            <span class="metric-value {'positive' if metrics.total_remaining >= 0 else 'negative'}">€{metrics.total_remaining:,.2f}</span>
                        </div>
                        <div class="progress-bar">
                            <div class="progress" style="width: {min(100, (metrics.total_spent / metrics.total_budgeted * 100) if metrics.total_budgeted > 0 else 0):.1f}%"></div>
                        </div>
                    </div>

                    <!-- Cashflow Overview (Transactions) -->
                    <div class=\"card\">
                        <h3>💵 Cashflow Overview (Transactions)</h3>
                        {self._render_cashflow_section()}
                    </div>

                    <!-- Recent Spending Trends -->
                    <div class="card">
                        <h3>📈 Spending Trends</h3>
                        <div class="metric">
                            <span>Last 7 days:</span>
                            <span class="metric-value">€{metrics.recent_spending_trend['last_7_days']:,.2f}</span>
                        </div>
                        <div class="metric">
                            <span>Last 14 days:</span>
                            <span class="metric-value">€{metrics.recent_spending_trend['last_14_days']:,.2f}</span>
                        </div>
                        <div class="metric">
                            <span>Last 30 days:</span>
                            <span class="metric-value">€{metrics.recent_spending_trend['last_30_days']:,.2f}</span>
                        </div>
                        <div class="metric">
                            <span>Daily average (30d):</span>
                            <span class="metric-value">€{metrics.recent_spending_trend['last_30_days']/30:,.2f}</span>
                        </div>
                    </div>

                    <!-- Account Summary -->
                    <div class="card">
                        <h3>💰 Account Balances</h3>
                        <table class="table">
                            <thead>
                                <tr><th>Account</th><th>Balance</th><th>Cleared</th></tr>
                            </thead>
                            <tbody>
                                {self._generate_account_rows(metrics.account_summary)}
                            </tbody>
                        </table>
                    </div>
        """

        # Add overspent categories alert if any
        if metrics.overspent_categories:
            html += f"""
                    <!-- Overspent Categories Alert -->
                    <div class="card">
                        <h3>⚠️ Overspent Categories</h3>
                        <div class="alert alert-danger">
                            <strong>Warning:</strong> {len(metrics.overspent_categories)} categories are overspent!
                        </div>
                        <table class="table">
                            <thead>
                                <tr><th>Category</th><th>Budgeted</th><th>Spent</th><th>Overspent</th></tr>
                            </thead>
                            <tbody>
                                {self._generate_overspent_rows(metrics.overspent_categories[:5])}
                            </tbody>
                        </table>
                    </div>
            """

        # Add underfunded goals if any
        if metrics.underfunded_goals:
            html += f"""
                    <!-- Underfunded Goals -->
                    <div class="card">
                        <h3>🎯 Underfunded Goals</h3>
                        <div class="alert alert-warning">
                            <strong>Notice:</strong> {len(metrics.underfunded_goals)} goals need funding.
                        </div>
                        <table class="table">
                            <thead>
                                <tr><th>Category</th><th>Target</th><th>Need</th><th>Progress</th></tr>
                            </thead>
                            <tbody>
                                {self._generate_underfunded_rows(metrics.underfunded_goals[:5])}
                            </tbody>
                        </table>
                    </div>
            """

        # Add top spending categories
        if metrics.top_spending_categories:
            html += f"""
                    <!-- Top Spending Categories -->
                    <div class="card">
                        <h3>🏷️ Top Spending Categories</h3>
                        <table class="table">
                            <thead>
                                <tr><th>Category</th><th>Amount</th></tr>
                            </thead>
                            <tbody>
                                {self._generate_top_spending_rows(metrics.top_spending_categories[:5])}
                            </tbody>
                        </table>
                    </div>
            """

        # Add top payees
        if metrics.spending_by_payee:
            html += f"""
                    <!-- Top Payees -->
                    <div class="card">
                        <h3>🏪 Top Payees</h3>
                        <table class="table">
                            <thead>
                                <tr><th>Payee</th><th>Amount</th></tr>
                            </thead>
                            <tbody>
                                {self._generate_payee_rows(metrics.spending_by_payee[:5])}
                            </tbody>
                        </table>
                    </div>
            """

        # Add recurring transactions section
        if metrics.recurring_transactions:
            html += f"""
                    <!-- Recurring Transactions -->
                    <div class="card">
                        <h3>🔄 Recurring Transactions</h3>
                        <p style="margin-bottom: 15px; color: #666;">Detected {len(metrics.recurring_transactions)} recurring payment patterns</p>
                        <table class="table">
                            <thead>
                                <tr><th>Payee</th><th>Amount</th><th>Frequency</th><th>Usual Day</th></tr>
                            </thead>
                            <tbody>
                                {self._generate_recurring_rows(metrics.recurring_transactions[:8])}
                            </tbody>
                        </table>
                    </div>
            """

        # Add calendar heat map
        html += f"""
                    <!-- Transaction Calendar Heat Map -->
                    <div class="card" style="grid-column: 1 / -1;">
                        <h3>📅 Transaction Calendar Heat Map</h3>
                        <p style="margin-bottom: 20px; color: #666;">Days with more frequent transactions are highlighted in red. Hover over days for details.</p>
                        <div class="calendar-container">
                            {self._generate_calendar_html(metrics.calendar_heat_map)}
                        </div>
                        <div class="calendar-legend">
                            <span style="margin-right: 20px;">💡 <strong>Legend:</strong></span>
                            <span style="margin-right: 15px;">🔴 High activity</span>
                            <span style="margin-right: 15px;">🟡 Medium activity</span>
                            <span>⚪ Low/No activity</span>
                        </div>
                    </div>
        """

        # Add success message if budget is healthy
        if metrics.health_score >= 80:
            html += """
                    <div class="card">
                        <div class="alert alert-success">
                            <strong>Great job!</strong> Your budget is in excellent health. Keep up the good work!
                        </div>
                    </div>
            """

        html += """
                </div>
                <div class="timestamp">
                    Report generated on """ + datetime.now().strftime('%Y-%m-%d at %H:%M:%S') + """
                </div>
            </div>
        </body>
        </html>
        """

        return html

    def _generate_account_rows(self, accounts: List[Dict]) -> str:
        """Generate HTML table rows for accounts"""
        rows = []
        for account in accounts[:10]:  # Limit to top 10
            rows.append(f"""
                <tr>
                    <td>{account['name']}</td>
                    <td class="{'positive' if account['balance'] >= 0 else 'negative'}">{account['balance_display']}</td>
                    <td>{account['cleared_balance_display']}</td>
                </tr>
            """)
        return ''.join(rows)

    def _generate_recurring_rows(self, recurring: List[Dict]) -> str:
        """Generate HTML table rows for recurring transactions"""
        rows = []
        for transaction in recurring:
            frequency_badge = f"<span style='background: #17a2b8; color: white; padding: 2px 8px; border-radius: 12px; font-size: 11px;'>{transaction['frequency_type']}</span>"
            rows.append(f"""
                <tr>
                    <td>{transaction['payee_name']}</td>
                    <td class="negative">{transaction['amount_display']}</td>
                    <td>{frequency_badge} ({transaction['frequency_count']}x)</td>
                    <td style="text-align: center;">{transaction['most_common_day']}</td>
                </tr>
            """)
        return ''.join(rows)

    def _generate_calendar_html(self, calendar_data: Dict[str, Any]) -> str:
        """Generate HTML for calendar heat map"""
        if not calendar_data or not calendar_data.get('days'):
            return "<p>No transaction data available for calendar visualization.</p>"

        days = calendar_data['days']
        max_frequency = calendar_data.get('max_frequency', 0)

        # Create calendar grid (7 columns for days of week, up to 5 rows)
        calendar_html = '<div class="calendar-grid">'

        # Generate all 31 possible days
        for day in range(1, 32):
            day_data = days.get(str(day), {})
            frequency = day_data.get('frequency', 0)
            intensity = day_data.get('intensity', 0)
            total_amount = day_data.get('total_amount_display', '€0.00')

            # Determine CSS class based on intensity
            if intensity >= 0.7:
                css_class = "active"
                opacity = day_data.get('color_opacity', 0.8)
            elif intensity >= 0.3:
                css_class = "medium"
                opacity = day_data.get('color_opacity', 0.5)
            else:
                css_class = "low"
                opacity = 0.1

            tooltip_text = f"Day {day}: {frequency} transactions, {total_amount}"

            calendar_html += f"""
                <div class="calendar-day {css_class}" style="--opacity: {opacity};">
                    {day}
                    <div class="calendar-tooltip">{tooltip_text}</div>
                </div>
            """

        calendar_html += '</div>'
        return calendar_html

    def detect_subscriptions_and_scheduled_payments(self) -> List[Dict[str, Any]]:
        """
        Detect potential subscriptions and scheduled payments with lenient criteria.

        Looks for amounts (±3 euro tolerance) appearing 2+ times over 2+ months.
        More lenient than recurring transaction detection for catching variable subscriptions.

        Returns:
            List of detected subscription patterns with details
        """
        subscriptions = []

        if not self._transaction_data:
            return subscriptions

        # Group transactions by payee
        payee_groups = defaultdict(list)

        for transaction in self._transaction_data:
            if transaction.get('amount', 0) >= 0:  # Skip income transactions
                continue

            payee_name = transaction.get('payee_name', 'Unknown')
            amount = abs(transaction.get('amount', 0))
            date_str = transaction.get('date', '')

            if date_str and payee_name != 'Unknown':
                try:
                    # Extract year-month without creating date objects
                    year, month, day = date_str.split('-')
                    month_year = f"{year}-{month}"

                    payee_groups[payee_name].append({
                        'date': date_str,
                        'amount': amount,
                        'transaction_id': transaction.get('id'),
                        'month_year': month_year,
                        'year': int(year),
                        'month': int(month),
                        'day': int(day)
                    })
                except (ValueError, IndexError):
                    continue

        # Analyze each payee for subscription patterns
        for payee_name, transactions in payee_groups.items():
            if len(transactions) < 2:  # Need at least 2 transactions
                continue

            # Sort transactions by date
            transactions.sort(key=lambda x: x['date'])

            # Group similar amounts (within ±3 euro tolerance)
            amount_groups = defaultdict(list)

            for transaction in transactions:
                amount = transaction['amount']

                # Find existing group with similar amount (±3 euro)
                found_group = False
                for existing_amount in amount_groups.keys():
                    if abs(amount - existing_amount) <= 3.0:
                        amount_groups[existing_amount].append(transaction)
                        found_group = True
                        break

                if not found_group:
                    amount_groups[amount].append(transaction)

            # Check each amount group for subscription criteria
            for base_amount, similar_transactions in amount_groups.items():
                if len(similar_transactions) >= 2:  # 2+ occurrences
                    # Check if transactions span 2+ different months
                    unique_months = set(tx['month_year'] for tx in similar_transactions)

                    if len(unique_months) >= 2:  # Span 2+ months
                        # Calculate statistics
                        amounts = [tx['amount'] for tx in similar_transactions]
                        date_strings = [tx['date'] for tx in similar_transactions]

                        avg_amount = sum(amounts) / len(amounts)
                        min_amount = min(amounts)
                        max_amount = max(amounts)

                        # Calculate average interval between transactions using string dates
                        if len(date_strings) >= 2:
                            sorted_dates = sorted(date_strings)
                            intervals = []
                            for i in range(len(sorted_dates)-1):
                                try:
                                    date1 = datetime.fromisoformat(sorted_dates[i]).date()
                                    date2 = datetime.fromisoformat(sorted_dates[i+1]).date()
                                    intervals.append((date2 - date1).days)
                                except ValueError:
                                    continue
                            avg_interval = sum(intervals) / len(intervals) if intervals else 0
                        else:
                            avg_interval = 0

                        # Determine likely subscription type
                        subscription_type = self._classify_subscription_type(avg_interval, len(similar_transactions), unique_months)

                        # Calculate confidence score (0-100)
                        confidence = self._calculate_subscription_confidence(
                            similar_transactions, avg_interval, min_amount, max_amount
                        )

                        # Create clean transaction samples (JSON serializable)
                        clean_samples = []
                        for tx in similar_transactions[-3:]:
                            clean_tx = {
                                'date': tx['date'],
                                'amount': tx['amount'],
                                'transaction_id': tx['transaction_id'],
                                'month_year': tx['month_year']
                            }
                            clean_samples.append(clean_tx)

                        # Calculate first and last seen dates
                        first_seen = min(date_strings)
                        last_seen = max(date_strings)

                        subscriptions.append({
                            'payee_name': payee_name,
                            'avg_amount': avg_amount,
                            'avg_amount_display': f'€{avg_amount:,.2f}',
                            'min_amount': min_amount,
                            'max_amount': max_amount,
                            'amount_range_display': f'€{min_amount:,.2f} - €{max_amount:,.2f}' if min_amount != max_amount else f'€{avg_amount:,.2f}',
                            'occurrence_count': len(similar_transactions),
                            'month_span': len(unique_months),
                            'months_covered': sorted(list(unique_months)),
                            'avg_interval_days': round(avg_interval, 1),
                            'subscription_type': subscription_type,
                            'confidence_score': confidence,
                            'first_seen': first_seen,
                            'last_seen': last_seen,
                            'sample_transactions': clean_samples
                        })

        # Sort by confidence score and average amount
        return sorted(subscriptions, key=lambda x: (x.get('confidence_score', 0) or 0, x.get('avg_amount', 0) or 0), reverse=True)

    def _classify_subscription_type(self, avg_interval: float, count: int, unique_months: set) -> str:
        """Classify the type of subscription based on patterns"""
        if 25 <= avg_interval <= 35:
            return "Monthly Subscription"
        elif 6 <= avg_interval <= 10:
            return "Weekly Service"
        elif 85 <= avg_interval <= 95:
            return "Quarterly Payment"
        elif avg_interval > 180:
            return "Annual/Bi-annual"
        elif count >= 4 and len(unique_months) >= 3:
            return "Regular Service"
        elif avg_interval <= 5:
            return "Frequent Payment"
        else:
            return "Scheduled Payment"

    def _calculate_subscription_confidence(self, transactions: List[Dict], avg_interval: float,
                                         min_amount: float, max_amount: float) -> int:
        """Calculate confidence score (0-100) for subscription detection"""
        score = 50  # Base score

        # More occurrences = higher confidence
        score += min(30, len(transactions) * 5)

        # Consistent amounts = higher confidence
        amount_variance = (max_amount - min_amount) / max_amount if max_amount > 0 else 0
        if amount_variance <= 0.05:  # Within 5%
            score += 15
        elif amount_variance <= 0.10:  # Within 10%
            score += 10

        # Regular intervals = higher confidence
        if 25 <= avg_interval <= 35:  # Monthly-ish
            score += 10
        elif 6 <= avg_interval <= 10:   # Weekly-ish
            score += 8

        # Longer observation period = higher confidence
        date_strings = [tx['date'] for tx in transactions]
        try:
            first_date = datetime.fromisoformat(min(date_strings)).date()
            last_date = datetime.fromisoformat(max(date_strings)).date()
            observation_period = (last_date - first_date).days
            if observation_period >= 60:  # 2+ months
                score += 5
        except ValueError:
            pass  # Skip if date parsing fails

        return min(100, max(0, score))

    def test_subscription_detection(self) -> Dict[str, Any]:
        """
        Test method to verify subscription detection works and is JSON serializable.
        Returns a simplified version for testing purposes.
        """
        try:
            if not self._transaction_data:
                self._load_data()

            subscriptions = self.detect_subscriptions_and_scheduled_payments()

            # Test JSON serialization
            import json
            json_test = json.dumps({
                "count": len(subscriptions),
                "first_subscription": subscriptions[0] if subscriptions else None,
                "test_status": "success"
            })

            return {
                "status": "success",
                "subscription_count": len(subscriptions),
                "json_serializable": True,
                "sample_subscription": subscriptions[0] if subscriptions else None
            }
        except Exception as e:
            return {
                "status": "error",
                "error": str(e),
                "json_serializable": False
            }

    def _generate_overspent_rows(self, categories: List[Dict]) -> str:
        """Generate HTML table rows for overspent categories"""
        rows = []
        for category in categories:
            rows.append(f"""
                <tr>
                    <td>{category['name']}</td>
                    <td>€{category['budgeted']:,.2f}</td>
                    <td class="negative">€{category['spent']:,.2f}</td>
                    <td class="negative">{category['overspent_display']}</td>
                </tr>
            """)
        return ''.join(rows)

    def _generate_underfunded_rows(self, goals: List[Dict]) -> str:
        """Generate HTML table rows for underfunded goals"""
        rows = []
        for goal in goals:
            rows.append(f"""
                <tr>
                    <td>{goal['name']}</td>
                    <td>{goal['goal_target_display']}</td>
                    <td class="warning">{goal['under_funded_display']}</td>
                    <td>{goal['percentage_complete']:.1f}%</td>
                </tr>
            """)
        return ''.join(rows)

    def _generate_top_spending_rows(self, categories: List[Dict]) -> str:
        """Generate HTML table rows for top spending categories"""
        rows = []
        for category in categories:
            rows.append(f"""
                <tr>
                    <td>{category['name']}</td>
                    <td class="negative">{category['amount_display']}</td>
                </tr>
            """)
        return ''.join(rows)

    def _generate_payee_rows(self, payees: List[Dict]) -> str:
        """Generate HTML table rows for top payees"""
        rows = []
        for payee in payees:
            rows.append(f"""
                <tr>
                    <td>{payee['name']}</td>
                    <td class="negative">{payee['amount_display']}</td>
                </tr>
            """)
        return ''.join(rows)


def main():
    """Example usage of the budget health analyzer"""
    # You'll need to provide your budget ID
    budget_id = "d2f2e23f-f445-498d-9712-e356a90a4f64"  # Example from JSON

    try:
        analyzer = BudgetHealthAnalyzer(budget_id)

        # Generate the report
        html_report = analyzer.generate_html_report()

        # Save to file
        with open('budget_health_report.html', 'w', encoding='utf-8') as f:
            f.write(html_report)

        print("Budget health report generated successfully!")
        print("Open 'budget_health_report.html' in your browser to view the report.")

        # Also return the metrics for potential API use
        metrics = analyzer.analyze()
        print(f"\nQuick Summary:")
        print(f"Health Score: {metrics.health_score:.0f}/100")
        print(f"Total Budgeted: €{metrics.total_budgeted:,.2f}")
        print(f"Total Spent: €{metrics.total_spent:,.2f}")
        print(f"Overspent Categories: {len(metrics.overspent_categories)}")

        return html_report, metrics

    except Exception as e:
        logger.error(f"Error generating budget health report: {e}")
        raise


if __name__ == "__main__":
    main()
