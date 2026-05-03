#!/usr/bin/env python3
"""
Budget Health Analyzer

A standalone script that analyzes local budget data from SQLite and generates
an HTML health report.  This can be integrated into FastAPI routes or run
independently.  Reads from localdb/budget.db instead of the YNAB API.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEFAULT_DB_PATH = Path("localdb/budget.db")


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
    recurring_transactions: List[Dict[str, Any]]
    calendar_heat_map: Dict[str, Any]
    health_score: float  # 0-100


class BudgetHealthAnalyzer:
    """Analyzes budget health from a local SQLite database.

    Parameters
    ----------
    db_path : str or Path, optional
        Path to the budget SQLite database.  Defaults to ``localdb/budget.db``.
    """

    def __init__(self, db_path: str | Path = DEFAULT_DB_PATH) -> None:
        self.db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._account_cache: list[dict] | None = None
        self._category_cache: list[dict] | None = None
        self._transaction_cache: list[dict] | None = None

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self.db_path)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def _close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    # ------------------------------------------------------------------
    # Data-loading helpers (replaces YNAB SDK calls)
    # ------------------------------------------------------------------

    def _cents_to_euros(self, cents: int | None) -> float:
        """Convert integer cents to euro float."""
        if cents is None:
            return 0.0
        return cents / 100.0

    def _load_accounts(self) -> list[dict]:
        if self._account_cache is not None:
            return self._account_cache
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, name, type, currency, is_active FROM accounts ORDER BY name"
        ).fetchall()
        self._account_cache = [dict(r) for r in rows]
        return self._account_cache

    def _load_categories(self) -> list[dict]:
        if self._category_cache is not None:
            return self._category_cache
        conn = self._connect()
        rows = conn.execute(
            "SELECT id, name, parent_id, is_archived FROM categories ORDER BY name"
        ).fetchall()
        self._category_cache = [dict(r) for r in rows]
        return self._category_cache

    def _load_transactions(self) -> list[dict]:
        if self._transaction_cache is not None:
            return self._transaction_cache
        conn = self._connect()
        rows = conn.execute(
            "SELECT idempotency_key, account_id, posted_at, amount_cents, "
            "payee, memo, category_id, is_cleared "
            "FROM transactions ORDER BY posted_at"
        ).fetchall()
        self._transaction_cache = [dict(r) for r in rows]
        return self._transaction_cache

    def _category_name(self, category_id: int | None) -> str:
        if category_id is None:
            return "Uncategorized"
        for c in self._load_categories():
            if c["id"] == category_id:
                return c["name"]
        return "Unknown"

    def _account_name(self, account_id: int | None) -> str:
        if account_id is None:
            return "Unknown"
        for a in self._load_accounts():
            if a["id"] == account_id:
                return a["name"]
        return "Unknown"

    # ------------------------------------------------------------------
    # Analysis – budget totals
    # ------------------------------------------------------------------

    def _calculate_budget_totals(self) -> Tuple[float, float, float]:
        """Return (total_budgeted, total_spent, total_remaining).

        Since the local DB doesn't store budget targets, we use net
        inflow/outflow from transactions as a proxy for the current period.
        The 'budgeted' value is derived from income transactions and
        'spent' from expense transactions within the current month.
        """
        now = datetime.now()
        month_start = now.replace(day=1).date().isoformat()

        total_income = 0.0
        total_expense = 0.0

        for tx in self._load_transactions():
            posted = tx.get("posted_at", "")
            if posted and posted[:10] < month_start:
                continue  # only current month
            cents = tx.get("amount_cents", 0) or 0
            if cents > 0:
                total_income += self._cents_to_euros(cents)
            else:
                total_expense += abs(self._cents_to_euros(cents))

        total_budgeted = total_income
        total_spent = total_expense
        total_remaining = total_income - total_expense
        return total_budgeted, total_spent, total_remaining

    # ------------------------------------------------------------------
    # Analysis – overspent & underfunded
    # ------------------------------------------------------------------

    def _find_overspent_categories(self) -> List[Dict[str, Any]]:
        """Find categories where spending exceeds a simple estimate.

        Without explicit budget targets, we compare each category's
        spending against its proportional share of income.
        """
        txns = self._load_transactions()
        now = datetime.now()
        month_start = now.replace(day=1).date().isoformat()

        cat_spend: dict[int, float] = defaultdict(float)
        for tx in txns:
            posted = tx.get("posted_at", "")
            if posted[:10] < month_start:
                continue
            cents = tx.get("amount_cents", 0) or 0
            if cents < 0:
                cat_spend[tx["category_id"]] += self._cents_to_euros(abs(cents))

        overspent: list[dict] = []
        for cat_id, spent in sorted(cat_spend.items(), key=lambda x: -x[1]):
            name = self._category_name(cat_id)
            # Simple heuristic: if a single category accounts for >30% of
            # total spending, flag it.
            total_spent = sum(v for v in cat_spend.values())
            if total_spent > 0 and spent / total_spent > 0.30 and spent > 100:
                overspent.append(
                    {
                        "name": name,
                        "budgeted": 0.0,
                        "spent": spent,
                        "overspent_amount": spent,
                        "overspent_display": f"€{spent:,.2f}",
                    }
                )
        return overspent

    def _find_underfunded_goals(self) -> List[Dict[str, Any]]:
        """Placeholder – no explicit goal data in local DB yet.

        Returns an empty list until goal tracking is added to the schema.
        """
        return []

    # ------------------------------------------------------------------
    # Analysis – spending trends
    # ------------------------------------------------------------------

    def _analyze_spending_trends(self) -> Dict[str, float]:
        now = datetime.now().date()
        trends: Dict[str, float] = {
            "last_7_days": 0.0,
            "last_14_days": 0.0,
            "last_30_days": 0.0,
        }
        for tx in self._load_transactions():
            amt = tx.get("amount_cents", 0) or 0
            if amt >= 0:  # income, skip
                continue
            posted = tx.get("posted_at", "")
            try:
                tx_date = datetime.fromisoformat(posted).date()
            except (ValueError, TypeError):
                continue
            days_ago = (now - tx_date).days
            amount = self._cents_to_euros(abs(amt))
            if days_ago <= 7:
                trends["last_7_days"] += amount
            if days_ago <= 14:
                trends["last_14_days"] += amount
            if days_ago <= 30:
                trends["last_30_days"] += amount
        return trends

    # ------------------------------------------------------------------
    # Analysis – account summary
    # ------------------------------------------------------------------

    def _summarize_accounts(self) -> List[Dict[str, Any]]:
        conn = self._connect()
        rows = conn.execute(
            "SELECT a.id, a.name, a.type, "
            "COALESCE(SUM(t.amount_cents), 0) AS balance_cents "
            "FROM accounts a "
            "LEFT JOIN transactions t ON t.account_id = a.id "
            "WHERE a.is_active = 1 "
            "GROUP BY a.id ORDER BY a.name"
        ).fetchall()
        result = []
        for r in rows:
            bal = self._cents_to_euros(r["balance_cents"])
            result.append(
                {
                    "name": r["name"],
                    "type": r["type"],
                    "balance": bal,
                    "balance_display": f"€{bal:,.2f}",
                    "cleared_balance": bal,
                    "cleared_balance_display": f"€{bal:,.2f}",
                }
            )
        return result

    # ------------------------------------------------------------------
    # Analysis – category analysis
    # ------------------------------------------------------------------

    def _analyze_categories(self) -> List[Dict[str, Any]]:
        txns = self._load_transactions()
        cat_spend: dict[int, float] = defaultdict(float)
        for tx in txns:
            cents = tx.get("amount_cents", 0) or 0
            if cents < 0:
                cat_spend[tx["category_id"]] += self._cents_to_euros(abs(cents))

        result = []
        for cat_id, spent in sorted(cat_spend.items(), key=lambda x: -x[1]):
            name = self._category_name(cat_id)
            result.append(
                {
                    "name": name,
                    "budgeted": 0.0,
                    "budgeted_display": "€0.00",
                    "activity": -spent,
                    "activity_display": f"-€{spent:,.2f}",
                    "balance": -spent,
                    "balance_display": f"-€{spent:,.2f}",
                    "utilization": 100.0 if spent > 0 else 0.0,
                }
            )
        return result

    # ------------------------------------------------------------------
    # Analysis – top spending categories & payees
    # ------------------------------------------------------------------

    def _get_top_spending_categories(self) -> List[Dict[str, Any]]:
        txns = self._load_transactions()
        cat_spend: dict[int, float] = defaultdict(float)
        for tx in txns:
            cents = tx.get("amount_cents", 0) or 0
            if cents < 0:
                cat_spend[tx["category_id"]] += self._cents_to_euros(abs(cents))

        result = []
        for cat_id, amount in sorted(cat_spend.items(), key=lambda x: -x[1])[:10]:
            result.append(
                {
                    "name": self._category_name(cat_id),
                    "amount": amount,
                    "amount_display": f"€{amount:,.2f}",
                }
            )
        return result

    def _analyze_spending_by_payee(self) -> List[Dict[str, Any]]:
        txns = self._load_transactions()
        payee_spend: dict[str, float] = defaultdict(float)
        for tx in txns:
            cents = tx.get("amount_cents", 0) or 0
            if cents < 0:
                payee = tx.get("payee") or "Unknown"
                payee_spend[payee] += self._cents_to_euros(abs(cents))

        result = []
        for payee, amount in sorted(payee_spend.items(), key=lambda x: -x[1])[:10]:
            result.append(
                {
                    "name": payee,
                    "amount": amount,
                    "amount_display": f"€{amount:,.2f}",
                }
            )
        return result

    # ------------------------------------------------------------------
    # Analysis – health score
    # ------------------------------------------------------------------

    def _calculate_health_score(
        self,
        budgeted: float,
        spent: float,
        overspent_categories: list,
        underfunded_goals: list,
    ) -> float:
        score = 100.0
        if budgeted > 0:
            overspend_ratio = spent / budgeted
            if overspend_ratio > 1:
                score -= (overspend_ratio - 1) * 50
        score -= min(30, len(overspent_categories) * 5)
        score -= min(20, len(underfunded_goals) * 3)
        return max(0.0, score)

    # ------------------------------------------------------------------
    # Analysis – recurring transactions
    # ------------------------------------------------------------------

    def _detect_recurring_transactions(self) -> List[Dict[str, Any]]:
        """Detect recurring transactions from local transaction data."""
        txns = self._load_transactions()
        recurring: list[dict] = []

        payee_patterns: dict[str, dict[float, list[dict]]] = defaultdict(
            lambda: defaultdict(list)
        )

        for tx in txns:
            cents = tx.get("amount_cents", 0) or 0
            if cents >= 0:
                continue
            payee = tx.get("payee") or "Unknown"
            amount = abs(self._cents_to_euros(cents))
            rounded = round(amount, 0)
            date_str = tx.get("posted_at", "")
            if date_str and payee != "Unknown":
                try:
                    tx_date = datetime.fromisoformat(date_str).date()
                except (ValueError, TypeError):
                    continue
                payee_patterns[payee][rounded].append(
                    {"date": tx_date, "amount": amount, "day_of_month": tx_date.day}
                )

        for payee_name, amount_groups in payee_patterns.items():
            for base_amount, transactions in amount_groups.items():
                if len(transactions) < 3:
                    continue
                dates = sorted(tx["date"] for tx in transactions)
                intervals = [
                    (dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)
                ]
                avg_interval = sum(intervals) / len(intervals) if intervals else 0

                is_monthly = 25 <= avg_interval <= 35
                is_weekly = 6 <= avg_interval <= 8
                is_quarterly = 85 <= avg_interval <= 95

                if not (is_monthly or is_weekly or is_quarterly):
                    continue

                days_of_month = [tx["day_of_month"] for tx in transactions]
                most_common_day = max(set(days_of_month), key=days_of_month.count)

                if is_monthly:
                    freq_type = "Monthly"
                elif is_weekly:
                    freq_type = "Weekly"
                else:
                    freq_type = "Quarterly"

                recurring.append(
                    {
                        "payee_name": payee_name,
                        "amount": base_amount,
                        "amount_display": f"€{base_amount:,.2f}",
                        "frequency_count": len(transactions),
                        "avg_interval_days": round(avg_interval, 1),
                        "most_common_day": most_common_day,
                        "frequency_type": freq_type,
                        "last_transaction_date": max(dates).isoformat(),
                        "transactions": transactions[-3:],
                    }
                )

        return sorted(recurring, key=lambda x: x.get("amount", 0) or 0, reverse=True)

    # ------------------------------------------------------------------
    # Analysis – calendar heat map
    # ------------------------------------------------------------------

    def _generate_calendar_heat_map(self) -> Dict[str, Any]:
        txns = self._load_transactions()
        day_counts: dict[int, int] = defaultdict(int)
        day_amounts: dict[int, float] = defaultdict(float)

        for tx in txns:
            cents = tx.get("amount_cents", 0) or 0
            if cents >= 0:
                continue
            date_str = tx.get("posted_at", "")
            if not date_str:
                continue
            try:
                tx_date = datetime.fromisoformat(date_str).date()
            except (ValueError, TypeError):
                continue
            day = tx_date.day
            day_counts[day] += 1
            day_amounts[day] += self._cents_to_euros(abs(cents))

        max_freq = max(day_counts.values()) if day_counts else 0
        heat_days: dict[str, dict] = {}
        for d in range(1, 32):
            freq = day_counts.get(d, 0)
            total_amt = day_amounts.get(d, 0.0)
            intensity = freq / max_freq if max_freq > 0 else 0
            heat_days[str(d)] = {
                "day": d,
                "frequency": freq,
                "total_amount": total_amt,
                "total_amount_display": f"€{total_amt:,.2f}",
                "intensity": intensity,
                "color_opacity": min(0.1 + (intensity * 0.8), 0.9),
            }

        return {
            "days": heat_days,
            "max_frequency": max_freq,
            "total_transaction_days": len(day_counts),
        }

    # ------------------------------------------------------------------
    # Subscription detection (uses local data only)
    # ------------------------------------------------------------------

    def detect_subscriptions_and_scheduled_payments(self) -> List[Dict[str, Any]]:
        """Detect potential subscriptions from transaction patterns."""
        txns = self._load_transactions()
        subscriptions: list[dict] = []

        payee_groups: dict[str, list[dict]] = defaultdict(list)
        for tx in txns:
            cents = tx.get("amount_cents", 0) or 0
            if cents >= 0:
                continue
            payee = tx.get("payee") or "Unknown"
            if payee == "Unknown":
                continue
            amount = self._cents_to_euros(abs(cents))
            date_str = tx.get("posted_at", "")
            if date_str:
                try:
                    parts = date_str.split("T")[0].split("-")
                    month_year = f"{parts[0]}-{parts[1]}"
                    payee_groups[payee].append(
                        {
                            "date": date_str,
                            "amount": amount,
                            "month_year": month_year,
                            "year": int(parts[0]),
                            "month": int(parts[1]),
                            "day": int(parts[2]),
                        }
                    )
                except (IndexError, ValueError):
                    continue

        for payee_name, transactions in payee_groups.items():
            if len(transactions) < 2:
                continue
            transactions.sort(key=lambda x: x["date"])

            amount_groups: dict[float, list[dict]] = defaultdict(list)
            for tx in transactions:
                amt = tx["amount"]
                found = False
                for existing in list(amount_groups.keys()):
                    if abs(amt - existing) <= 3.0:
                        amount_groups[existing].append(tx)
                        found = True
                        break
                if not found:
                    amount_groups[amt].append(tx)

            for base_amount, similar in amount_groups.items():
                if len(similar) < 2:
                    continue
                unique_months = set(tx["month_year"] for tx in similar)
                if len(unique_months) < 2:
                    continue

                amounts = [tx["amount"] for tx in similar]
                avg_amt = sum(amounts) / len(amounts)
                min_amt = min(amounts)
                max_amt = max(amounts)
                dates = sorted(tx["date"] for tx in similar)

                intervals: list[int] = []
                for i in range(len(dates) - 1):
                    try:
                        d1 = datetime.fromisoformat(dates[i]).date()
                        d2 = datetime.fromisoformat(dates[i + 1]).date()
                        intervals.append((d2 - d1).days)
                    except (ValueError, TypeError):
                        continue
                avg_interval = sum(intervals) / len(intervals) if intervals else 0

                confidence = 50 + min(30, len(similar) * 5)
                if max_amt > 0 and (max_amt - min_amt) / max_amt <= 0.05:
                    confidence += 15
                elif max_amt > 0 and (max_amt - min_amt) / max_amt <= 0.10:
                    confidence += 10
                if 25 <= avg_interval <= 35:
                    confidence += 10
                    sub_type = "Monthly Subscription"
                elif 6 <= avg_interval <= 10:
                    confidence += 8
                    sub_type = "Weekly Service"
                elif 85 <= avg_interval <= 95:
                    sub_type = "Quarterly Payment"
                else:
                    sub_type = "Scheduled Payment"
                confidence = min(100, max(0, confidence))

                subscriptions.append(
                    {
                        "payee_name": payee_name,
                        "avg_amount": avg_amt,
                        "avg_amount_display": f"€{avg_amt:,.2f}",
                        "min_amount": min_amt,
                        "max_amount": max_amt,
                        "amount_range_display": (
                            f"€{min_amt:,.2f} – €{max_amt:,.2f}"
                            if min_amt != max_amt
                            else f"€{avg_amt:,.2f}"
                        ),
                        "occurrence_count": len(similar),
                        "month_span": len(unique_months),
                        "months_covered": sorted(unique_months),
                        "avg_interval_days": round(avg_interval, 1),
                        "subscription_type": sub_type,
                        "confidence_score": confidence,
                        "first_seen": min(dates),
                        "last_seen": max(dates),
                        "sample_transactions": similar[-3:],
                    }
                )

        return sorted(
            subscriptions,
            key=lambda x: (x.get("confidence_score", 0) or 0, x.get("avg_amount", 0) or 0),
            reverse=True,
        )

    # ------------------------------------------------------------------
    # Cashflow helper
    # ------------------------------------------------------------------

    def _calculate_cashflow_totals(self) -> Dict[str, float]:
        inflows_all = 0.0
        outflows_all = 0.0
        inflows_mtd = 0.0
        outflows_mtd = 0.0

        now = datetime.now()
        month_start = now.replace(day=1).date().isoformat()

        for tx in self._load_transactions():
            cents = tx.get("amount_cents", 0) or 0
            amt = self._cents_to_euros(cents)
            posted = tx.get("posted_at", "")[:10]

            if amt > 0:
                inflows_all += amt
                if posted >= month_start:
                    inflows_mtd += amt
            elif amt < 0:
                outflows_all += abs(amt)
                if posted >= month_start:
                    outflows_mtd += abs(amt)

        return {
            "inflows_all": inflows_all,
            "outflows_all": outflows_all,
            "net_all": inflows_all - outflows_all,
            "inflows_mtd": inflows_mtd,
            "outflows_mtd": outflows_mtd,
            "net_mtd": inflows_mtd - outflows_mtd,
        }

    def _render_cashflow_section(self) -> str:
        cf = self._calculate_cashflow_totals()
        return f"""
            <div class="metric">
                <span>All-time Inflows:</span>
                <span class="metric-value">€{cf['inflows_all']:,.2f}</span>
            </div>
            <div class="metric">
                <span>All-time Outflows:</span>
                <span class="metric-value negative">€{cf['outflows_all']:,.2f}</span>
            </div>
            <div class="metric">
                <span>All-time Net:</span>
                <span class="metric-value {'positive' if cf['net_all'] >= 0 else 'negative'}">€{cf['net_all']:,.2f}</span>
            </div>
            <div class="metric" style="margin-top:12px; color:#666">
                <span>Month-to-date Inflows:</span>
                <span class="metric-value">€{cf['inflows_mtd']:,.2f}</span>
            </div>
            <div class="metric">
                <span>Month-to-date Outflows:</span>
                <span class="metric-value negative">€{cf['outflows_mtd']:,.2f}</span>
            </div>
            <div class="metric">
                <span>Month-to-date Net:</span>
                <span class="metric-value {'positive' if cf['net_mtd'] >= 0 else 'negative'}">€{cf['net_mtd']:,.2f}</span>
            </div>
        """

    # ------------------------------------------------------------------
    # Main analysis entry point
    # ------------------------------------------------------------------

    def analyze(self) -> BudgetHealthMetrics:
        logger.info("Analyzing budget health from local DB ...")
        total_budgeted, total_spent, total_remaining = self._calculate_budget_totals()
        overspent = self._find_overspent_categories()
        underfunded = self._find_underfunded_goals()
        trends = self._analyze_spending_trends()
        accounts = self._summarize_accounts()
        categories = self._analyze_categories()
        top_cats = self._get_top_spending_categories()
        top_payees = self._analyze_spending_by_payee()
        recurring = self._detect_recurring_transactions()
        heatmap = self._generate_calendar_heat_map()
        score = self._calculate_health_score(total_budgeted, total_spent, overspent, underfunded)

        return BudgetHealthMetrics(
            total_budgeted=total_budgeted,
            total_spent=total_spent,
            total_remaining=total_remaining,
            overspent_categories=overspent,
            underfunded_goals=underfunded,
            recent_spending_trend=trends,
            account_summary=accounts,
            category_analysis=categories,
            top_spending_categories=top_cats,
            spending_by_payee=top_payees,
            recurring_transactions=recurring,
            calendar_heat_map=heatmap,
            health_score=score,
        )

    # ------------------------------------------------------------------
    # HTML report generation
    # ------------------------------------------------------------------

    def generate_html_report(self, metrics: BudgetHealthMetrics | None = None) -> str:
        if metrics is None:
            metrics = self.analyze()

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
                .card {{ background: white; border: 1px solid #ddd; border-radius: 8px; padding: 20px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); width: fit-content; }}
                .card h3 {{ margin-top: 0; color: #333; border-bottom: 2px solid #667eea; padding-bottom: 10px; }}
                .metric {{ display: flex; justify-content: space-between; margin: 10px 0; }}
                .metric-value {{ font-weight: bold; }}
                .positive {{ color: #4CAF50; }}
                .negative {{ color: #F44336; }}
                .warning {{ color: #FF9800; }}
                .table {{ width: 100%; border-collapse: collapse; margin-top: 10px; }}
                .table th, .table td {{ text-align: left; padding: 8px; border-bottom: 1px solid #ddd; }}
                .table th {{ background-color: #f8f9fa; }}
                .alert {{ padding: 15px; margin: 10px 0; border-radius: 4px; }}
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
                    <div class="card">
                        <h3>📊 Budget Overview</h3>
                        <div class="metric">
                            <span>Total Spent:</span>
                            <span class="metric-value negative">€{metrics.total_spent:,.2f}</span>
                        </div>
                        <div class="metric">
                            <span>Remaining:</span>
                            <span class="metric-value {'positive' if metrics.total_remaining >= 0 else 'negative'}">€{metrics.total_remaining:,.2f}</span>
                        </div>
                    </div>

                    <div class="card">
                        <h3>💵 Cashflow Overview (Transactions)</h3>
                        {self._render_cashflow_section()}
                    </div>

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
                            <span class="metric-value">€{metrics.recent_spending_trend['last_30_days'] / 30:,.2f}</span>
                        </div>
                    </div>

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

        if metrics.top_spending_categories:
            html += f"""
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

        if metrics.spending_by_payee:
            html += f"""
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

        if metrics.recurring_transactions:
            html += f"""
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

        html += f"""
                    <div class="card" style="grid-column: 1 / -1;">
                        <h3>📅 Transaction Calendar Heat Map</h3>
                        <p style="margin-bottom: 20px; color: #666;">Days with more frequent transactions are highlighted in red.</p>
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

        if metrics.health_score >= 80:
            html += """
                    <div class="card">
                        <div class="alert alert-success">
                            <strong>Great job!</strong> Your budget is in excellent health. Keep up the good work!
                        </div>
                    </div>
            """

        html += f"""
                </div>
                <div class="timestamp">
                    Report generated on {datetime.now().strftime('%Y-%m-%d at %H:%M:%S')}
                </div>
            </div>
        </body>
        </html>
        """
        return html

    # ------------------------------------------------------------------
    # HTML helper methods
    # ------------------------------------------------------------------

    def _generate_account_rows(self, accounts: list[dict]) -> str:
        rows = []
        for acct in accounts[:10]:
            cls = "positive" if acct["balance"] >= 0 else "negative"
            rows.append(
                f'<tr><td>{acct["name"]}</td>'
                f'<td class="{cls}">{acct["balance_display"]}</td>'
                f'<td>{acct["cleared_balance_display"]}</td></tr>'
            )
        return "\n".join(rows)

    def _generate_recurring_rows(self, recurring: list[dict]) -> str:
        rows = []
        for t in recurring:
            badge = (
                f'<span style="background:#17a2b8;color:white;padding:2px 8px;'
                f'border-radius:12px;font-size:11px;">{t["frequency_type"]}</span>'
            )
            rows.append(
                f'<tr><td>{t["payee_name"]}</td>'
                f'<td class="negative">{t["amount_display"]}</td>'
                f'<td>{badge} ({t["frequency_count"]}x)</td>'
                f'<td style="text-align:center;">{t["most_common_day"]}</td></tr>'
            )
        return "\n".join(rows)

    def _generate_calendar_html(self, calendar_data: dict) -> str:
        if not calendar_data or not calendar_data.get("days"):
            return "<p>No transaction data available for calendar visualization.</p>"

        days = calendar_data["days"]
        max_freq = calendar_data.get("max_frequency", 0)

        html = '<div class="calendar-grid">'
        for day in range(1, 32):
            d = days.get(str(day), {})
            freq = d.get("frequency", 0)
            intensity = d.get("intensity", 0)
            total_amt = d.get("total_amount_display", "€0.00")

            if intensity >= 0.7:
                css_class = "active"
                opacity = d.get("color_opacity", 0.8)
            elif intensity >= 0.3:
                css_class = "medium"
                opacity = d.get("color_opacity", 0.5)
            else:
                css_class = "low"
                opacity = 0.1

            html += (
                f'<div class="calendar-day {css_class}" style="--opacity: {opacity};">'
                f"{day}"
                f'<div class="calendar-tooltip">Day {day}: {freq} transactions, {total_amt}</div>'
                f"</div>"
            )
        html += "</div>"
        return html

    def _generate_top_spending_rows(self, categories: list[dict]) -> str:
        rows = []
        for cat in categories:
            rows.append(
                f'<tr><td>{cat["name"]}</td>'
                f'<td class="negative">{cat["amount_display"]}</td></tr>'
            )
        return "\n".join(rows)

    def _generate_payee_rows(self, payees: list[dict]) -> str:
        rows = []
        for p in payees:
            rows.append(
                f'<tr><td>{p["name"]}</td>'
                f'<td class="negative">{p["amount_display"]}</td></tr>'
            )
        return "\n".join(rows)

    # ------------------------------------------------------------------
    # Subscription detection test
    # ------------------------------------------------------------------

    def test_subscription_detection(self) -> dict:
        try:
            subscriptions = self.detect_subscriptions_and_scheduled_payments()
            json.dumps(
                {
                    "count": len(subscriptions),
                    "first": subscriptions[0] if subscriptions else None,
                }
            )
            return {
                "status": "success",
                "subscription_count": len(subscriptions),
                "json_serializable": True,
                "sample": subscriptions[0] if subscriptions else None,
            }
        except Exception as e:
            return {"status": "error", "error": str(e), "json_serializable": False}


def main() -> None:
    """Generate a budget health report from the local database."""
    import sys

    db_arg = sys.argv[1] if len(sys.argv) > 1 else "localdb/budget.db"
    analyzer = BudgetHealthAnalyzer(db_arg)
    html = analyzer.generate_html_report()
    out = Path("budget_health_report.html")
    out.write_text(html, encoding="utf-8")
    metrics = analyzer.analyze()
    print(f"✅ Budget health report → {out}")
    print(f"   Health Score: {metrics.health_score:.0f}/100")
    print(f"   Total Spent:  €{metrics.total_spent:,.2f}")
    print(f"   Remaining:    €{metrics.total_remaining:,.2f}")
    print(f"   Transactions: {len(analyzer._load_transactions())}")
    analyzer._close()


if __name__ == "__main__":
    main()
