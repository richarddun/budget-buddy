from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Iterable, List, Mapping, Optional, Sequence, Tuple, Union


DateLike = Union[date, datetime, str]


def _to_date(d: DateLike) -> date:
    if isinstance(d, date) and not isinstance(d, datetime):
        return d
    if isinstance(d, datetime):
        return d.date()
    # Assume ISO-8601 string
    return date.fromisoformat(str(d)[:10])


def _is_truthy(val: object) -> bool:
    return bool(val) and str(val).lower() not in {"0", "false", "no", "none"}


def _should_exclude(txn: Mapping[str, object]) -> bool:
    """Heuristic exclusion for non-variable spend.

    Excludes transactions that are:
    - Marked explicitly: is_commitment, is_key_event, exclude
    - Non-outflows (amount >= 0)
    - Category hints that imply non-variable spend (Transfers/Income/Savings)
    """
    amt = int(txn.get("amount_cents", 0) or 0)
    if amt >= 0:
        return True

    # Explicit flags
    for k in ("is_commitment", "is_key_event", "exclude"):
        if _is_truthy(txn.get(k)):
            return True

    # Category-based hints (best-effort; optional fields)
    names = []
    for k in ("category", "category_name", "category_group", "group", "type"):
        v = txn.get(k)
        if isinstance(v, str):
            names.append(v.lower())
    hints = " ".join(names)
    blocked = ("transfer" in hints) or ("income" in hints) or ("savings" in hints)
    return blocked


def _daily_series(
    transactions: Iterable[Mapping[str, object]],
    *,
    window_days: int,
) -> Tuple[List[date], List[int]]:
    """Aggregate negative outflows into a contiguous daily series over window_days.

    Returns (days, amounts_cents_positive) where amounts are positive magnitudes
    for spending (e.g., amount_cents=-1234 becomes 1234 for that day).
    Missing days are filled with zero.
    """
    # Collect eligible transactions by date
    daily: dict[date, int] = {}
    max_d: Optional[date] = None

    for txn in transactions:
        if _should_exclude(txn):
            continue
        d = _to_date(txn.get("date") or txn.get("posted_at") or txn.get("when") or txn.get("ts"))
        amt = -abs(int(txn.get("amount_cents", 0) or 0))  # ensure negative
        # Convert to positive magnitude for spend
        spend = -amt
        daily[d] = daily.get(d, 0) + spend
        if max_d is None or d > max_d:
            max_d = d

    if max_d is None:
        # No data
        return [], []

    # Build contiguous window ending at max_d
    start_d = max_d - timedelta(days=max(0, int(window_days) - 1))
    days: List[date] = []
    vals: List[int] = []
    d = start_d
    while d <= max_d:
        days.append(d)
        vals.append(daily.get(d, 0))
        d = d + timedelta(days=1)
    return days, vals


def compute_daily_stats(
    transactions: Iterable[Mapping[str, object]],
    window_days: int = 180,
) -> Tuple[int, int]:
    """Compute (mu_cents, sigma_cents) of daily variable spend over a window.

    - Includes zero-spend days within the window for stability.
    - Returns integer cents for both mean and population-stddev (ddof=0), rounded.
    - Falls back to (0, 0) with sparse/no data.
    """
    _, vals = _daily_series(transactions, window_days=window_days)
    n = len(vals)
    if n == 0:
        return 0, 0
    # Mean
    s = sum(vals)
    mu = s / n
    # Population stddev
    var = 0.0
    if n > 0:
        m = mu
        var = sum((v - m) ** 2 for v in vals) / n
    sigma = var ** 0.5
    return int(round(mu)), int(round(sigma))


def compute_weekday_multipliers(
    transactions: Iterable[Mapping[str, object]],
    window_days: int = 180,
) -> List[float]:
    """Compute 7 weekday multipliers normalized to average 1.0.

    - Builds a contiguous daily series (including zeros), then computes the
      average spend for each weekday and divides by overall mean to form
      initial multipliers.
    - Normalizes the 7 multipliers so their simple average is exactly 1.0.
    - Sparse/empty data → return [1.0] * 7.
    """
    days, vals = _daily_series(transactions, window_days=window_days)
    n = len(vals)
    if n == 0:
        return [1.0] * 7

    overall_mean = (sum(vals) / n) if n else 0.0
    if overall_mean <= 0:
        return [1.0] * 7

    sums = [0.0] * 7
    counts = [0] * 7
    for d, v in zip(days, vals):
        w = d.weekday()  # 0=Mon..6=Sun
        sums[w] += v
        counts[w] += 1

    mults: List[float] = []
    for w in range(7):
        if counts[w] == 0:
            mults.append(1.0)
        else:
            avg_w = sums[w] / counts[w]
            mults.append(avg_w / overall_mean if overall_mean > 0 else 1.0)

    # Normalize to unweighted average of 1.0
    avg_mult = sum(mults) / 7.0
    if avg_mult <= 0:
        return [1.0] * 7
    normalized = [m / avg_mult for m in mults]
    return normalized


__all__ = [
    "compute_daily_stats",
    "compute_weekday_multipliers",
]

