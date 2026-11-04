"""Portfolio simulation with monthly contributions, a rebalancing band and transaction costs.

Rules (IPS section 6)
* On every rebalance date the new contribution is spent first on the ETFs below their target ("rebalancing by buying").
* An ETF is SOLD only if (a) its target is now zero (it left the portfolio) or (b) its weight is above its target
  by more than the band. Sales are the exception because in Poland every sale in profit is taxed (Belka 19%).
  Taxes are NOT modelled here: accumulating ETFs defer them until the final sale.
* Every purchase and sale pays ``cost_bps`` of the traded amount (spread + commission, an assumption).
* A missing return of a held ETF means its exchange was closed that day (returns are computed between the ETF's own
  trading days, so the next return already contains the gap): the ETF is left unchanged that day. A held ETF with no
  return at all before that day (not listed yet) is an error.
* Weights drift with the market between rebalance dates. Trades happen at the close of the rebalance date, and the
  target weights are computed with data up to that same close, so the next day's return is the first one earned.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.optimize import brentq


@dataclass
class SimResult:
    twr: pd.Series                 # daily time-weighted return, after costs, from the first investment
    value: pd.Series               # portfolio value at the close of each day (after trades)
    contributions: pd.Series       # money added on each rebalance date
    trades: pd.DataFrame           # per rebalance date: bought, sold, cost, number of sold ETFs
    holdings: pd.DataFrame         # weights after trading on each rebalance date


def _rebalance(v: np.ndarray, target: np.ndarray, contribution: float, band: float, cost: float):
    """Return (new values, bought, sold, cost paid). ``v`` are current values, ``target`` weights summing to 1."""
    n = len(v)
    sold = np.zeros(n)
    total = v.sum() + contribution
    if total <= 0:
        return v.copy(), np.zeros(n), sold, 0.0
    # forced sales: ETF that left the portfolio, or overweight beyond the band
    w_after = v / total
    over = (target <= 0) & (v > 0)
    over |= (w_after - target) > band
    new = v.copy()
    pool = contribution
    for i in np.where(over)[0]:
        goal = target[i] * total
        sold[i] = max(new[i] - goal, 0.0)
        new[i] -= sold[i]
        pool += sold[i] * (1 - cost)
    # buys: fill the gaps of the underweight ETFs, pro rata to the gap, with what the pool can pay (price + cost)
    gap = np.clip(target * total - new, 0.0, None)
    gap[target <= 0] = 0.0
    if gap.sum() > 0 and pool > 0:
        affordable = pool / (1 + cost)
        buy = gap * min(1.0, affordable / gap.sum())
    else:
        buy = np.zeros(n)
    spent = buy.sum() * (1 + cost)
    leftover = pool - spent
    if leftover > 1e-9:                                  # pool bigger than the gaps: spread the rest by target weight
        extra = leftover / (1 + cost)
        buy = buy + extra * target / target.sum()
    new = new + buy
    paid = cost * (buy.sum() + sold.sum())
    return new, buy, sold, paid


def simulate(returns: pd.DataFrame, schedule: dict[pd.Timestamp, pd.Series], contribution: float,
             cost_bps: float, band: float) -> SimResult:
    """Simulate day by day. ``schedule`` maps a rebalance date to the target weights (index = ETF ids)."""
    if not schedule:
        raise ValueError("empty schedule")
    cost = cost_bps / 1e4
    dates = sorted(schedule)
    cols = list(returns.columns)
    start = dates[0]
    r = returns.loc[start:]
    R = r.to_numpy(dtype=float)
    idx = r.index
    first_valid = np.array([returns[c].first_valid_index() or pd.Timestamp.max for c in cols], dtype="datetime64[ns]")
    v = np.zeros(len(cols))
    reb = {d: schedule[d].reindex(cols).fillna(0.0).to_numpy(dtype=float) for d in dates}
    twr, value, contr, trade_rows, hold_rows = [], [], {}, [], {}
    for k, day in enumerate(idx):
        mkt_value = v.sum()
        ret = 0.0
        if k > 0 and mkt_value > 0:
            held = v > 0
            not_listed = held & (first_valid > np.datetime64(day))
            if not_listed.any():
                bad = [cols[i] for i in np.where(not_listed)[0]]
                raise ValueError(f"held ETF without any return before {day.date()}: {bad}")
            v = v * (1 + np.nan_to_num(R[k]))
            ret = v.sum() / mkt_value - 1
        paid = 0.0
        if day in reb:
            tw = reb[day]
            if tw.sum() <= 0:
                raise ValueError(f"target weights sum to zero on {day.date()}")
            tw = tw / tw.sum()
            before = v.sum()
            v, buy, sold, paid = _rebalance(v, tw, contribution, band, cost)
            contr[day] = contribution
            trade_rows.append({"date": day, "bought": buy.sum(), "sold": sold.sum(), "cost": paid,
                               "n_sold": int((sold > 0).sum()), "value_before": before})
            hold_rows[day] = pd.Series(v / v.sum() if v.sum() > 0 else v, index=cols)
            if before > 0:
                ret = (1 + ret) * (1 - paid / before) - 1       # the cost reduces the time-weighted return
        twr.append(ret)
        value.append(v.sum())
    out_twr = pd.Series(twr, index=idx)
    return SimResult(out_twr, pd.Series(value, index=idx), pd.Series(contr, dtype=float),
                     pd.DataFrame(trade_rows).set_index("date"), pd.DataFrame(hold_rows).T)


def irr(contributions: pd.Series, final_value: float, final_date: pd.Timestamp) -> float:
    """Annual money-weighted return of the contributions (daily timing). NaN if it cannot be solved."""
    if contributions.empty or final_value <= 0:
        return float("nan")
    t0 = contributions.index[0]
    years = np.array([(d - t0).days / 365.25 for d in contributions.index])
    cf = contributions.to_numpy(dtype=float)
    t_end = (final_date - t0).days / 365.25

    def npv(rate: float) -> float:
        return float((cf * (1 + rate) ** (t_end - years)).sum() - final_value)

    try:
        return float(brentq(npv, -0.9, 5.0))
    except ValueError:
        return float("nan")
