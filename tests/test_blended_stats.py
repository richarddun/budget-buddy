from datetime import date, timedelta

import math

from forecast.blended_stats import (
    compute_daily_stats,
    compute_weekday_multipliers,
)


def _mk(d: date, amt_cents: int, **kw):
    rec = {"date": d.isoformat(), "amount_cents": amt_cents}
    rec.update(kw)
    return rec


def test_empty_data_returns_neutral():
    mu, sigma = compute_daily_stats([])
    assert mu == 0
    assert sigma == 0
    mults = compute_weekday_multipliers([])
    assert mults == [1.0] * 7


def test_daily_stats_mean_and_sigma_with_zeros():
    # 10-day window: 5 days of 100 cents spend, 5 days of 0
    start = date(2025, 1, 1)
    txns = []
    for i in range(10):
        d = start + timedelta(days=i)
        amt = -100 if (i % 2 == 1) else 0  # negatives are spend
        txns.append(_mk(d, amt))
    mu, sigma = compute_daily_stats(txns, window_days=10)
    assert mu == 50  # average of [0,100] across 10 days
    assert sigma == 50  # population stddev of the two-point distribution


def test_weekday_multipliers_normalize_and_shape():
    # 14 days starting on a Monday with patterned spends per weekday
    # Mon=100, Tue=200, Wed=300, Thu=0, Fri=0, Sat=0, Sun=0 (repeat)
    start = date(2025, 1, 6)  # Monday
    pattern = [100, 200, 300, 0, 0, 0, 0]
    txns = []
    for i in range(14):
        d = start + timedelta(days=i)
        amt = pattern[i % 7]
        if amt:
            txns.append(_mk(d, -amt))  # spend as negative
    mults = compute_weekday_multipliers(txns, window_days=14)
    assert len(mults) == 7
    # Average must be ~1.0
    avg = sum(mults) / 7.0
    assert abs(avg - 1.0) < 1e-9
    # Ordering should reflect spend intensity: Wed > Tue > Mon > others
    mon, tue, wed = mults[0], mults[1], mults[2]
    assert wed > tue > mon
    # Thu..Sun had zeros → should be the smallest (equal among themselves)
    low_block = mults[3:]
    assert max(low_block) - min(low_block) < 1e-9
    assert min(low_block) < mon


def test_exclusion_flags_and_income_filtered_out():
    start = date(2025, 2, 1)
    txns = [
        _mk(start + timedelta(days=0), 10000),  # income (positive) -> exclude
        _mk(start + timedelta(days=1), -500, is_commitment=True),  # exclude
        _mk(start + timedelta(days=2), -700, is_key_event=True),  # exclude
        _mk(start + timedelta(days=3), -900),  # include
        _mk(start + timedelta(days=4), -0),  # zero spend (ignored in input but contributes via window)
    ]
    mu, sigma = compute_daily_stats(txns, window_days=4)
    # Window covers days 1..4 ending at max date (day 4)
    # Included spend only on day 3 (-900) → daily series [0,0,900,0]
    assert mu == 225
    # Stddev of [0,0,900,0] around mean 225
    series = [0, 0, 900, 0]
    mean = sum(series) / 4
    var = sum((x - mean) ** 2 for x in series) / 4
    expected_sigma = int(round(math.sqrt(var)))
    assert sigma == expected_sigma

