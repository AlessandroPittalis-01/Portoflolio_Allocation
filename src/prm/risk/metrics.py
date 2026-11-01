"""Risk metrics of one return series (daily simple returns, in PLN).

All losses are reported as POSITIVE numbers (VaR 0.02 = a loss of 2%).

Important choices
-----------------
* Drawdown is computed on DAILY data. Monthly data hide the worst days and understate the drawdown
  (a weakness of simpler projects).
* VaR and ES are shown in two ways: historical (what really happened) and Gaussian (a formula that
  assumes a bell curve). The gap between the two says how fat the tails are.
* ``ann_return`` is DESCRIPTIVE. It is never used to choose or rank ETFs (that would be data snooping).
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def annual_return(r: pd.Series) -> float:
    """Geometric annual return from daily simple returns."""
    r = r.dropna()
    if len(r) == 0:
        return float("nan")
    growth = float((1 + r).prod())
    return growth ** (TRADING_DAYS / len(r)) - 1


def annual_vol(r: pd.Series) -> float:
    return float(r.dropna().std() * math.sqrt(TRADING_DAYS))


def _wealth(r: pd.Series) -> pd.Series:
    """Value of 1 invested before the first return. The starting point (value 1) is included, so a loss
    on the very first day counts as a drawdown."""
    r = r.dropna()
    start = pd.Series([1.0], index=[r.index[0] - pd.Timedelta(days=1)])
    return pd.concat([start, (1 + r).cumprod()])


def drawdown_series(r: pd.Series) -> pd.Series:
    """Drawdown on each day: value / highest value so far - 1 (always <= 0)."""
    wealth = _wealth(r)
    return (wealth / wealth.cummax() - 1).iloc[1:]


def max_drawdown(r: pd.Series) -> dict:
    """Worst drawdown with the date of the previous peak, the trough, and the recovery (None if not recovered)."""
    r = r.dropna()
    if len(r) == 0:
        return {"max_dd": float("nan"), "peak": None, "trough": None, "recovery": None}
    dd = drawdown_series(r)
    trough = dd.idxmin()
    wealth = _wealth(r)
    peak = wealth.loc[:trough].idxmax()
    after = wealth.loc[trough:]
    recovered = after[after >= wealth.loc[peak]]
    return {
        "max_dd": float(dd.min()),
        "peak": peak,
        "trough": trough,
        "recovery": recovered.index[0] if len(recovered) else None,
    }


def hist_var_es(r: pd.Series, level: float = 0.95) -> tuple[float, float]:
    """Historical 1-day VaR and Expected Shortfall (average loss beyond VaR), as positive losses."""
    r = r.dropna()
    if len(r) == 0:
        return float("nan"), float("nan")
    cutoff = r.quantile(1 - level)
    tail = r[r <= cutoff]
    return float(-cutoff), float(-tail.mean())


def gaussian_var_es(r: pd.Series, level: float = 0.95) -> tuple[float, float]:
    """1-day VaR and ES if returns were normal with the same mean and volatility."""
    r = r.dropna()
    if len(r) < 2:
        return float("nan"), float("nan")
    mu, sigma = float(r.mean()), float(r.std())
    z = NormalDist().inv_cdf(1 - level)               # negative number
    var = -(mu + sigma * z)
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    es = -(mu - sigma * pdf / (1 - level))
    return var, es


def summarise_returns(r: pd.Series) -> dict:
    """One row of the risk table for an asset."""
    r = r.dropna()
    dd = max_drawdown(r)
    var95, es95 = hist_var_es(r, 0.95)
    var99, es99 = hist_var_es(r, 0.99)
    g_var99, g_es99 = gaussian_var_es(r, 0.99)
    worst_day = r.idxmin() if len(r) else None
    return {
        "n_obs": len(r),
        "first_date": r.index.min() if len(r) else None,
        "ann_return": annual_return(r),
        "ann_vol": annual_vol(r),
        "max_dd": dd["max_dd"],
        "dd_peak": dd["peak"],
        "dd_trough": dd["trough"],
        "dd_recovery": dd["recovery"],
        "current_dd": float(drawdown_series(r).iloc[-1]) if len(r) else float("nan"),
        "var95_hist": var95,
        "es95_hist": es95,
        "var99_hist": var99,
        "es99_hist": es99,
        "var99_gauss": g_var99,
        "es99_gauss": g_es99,
        "skew": float(r.skew()) if len(r) > 2 else float("nan"),
        "excess_kurtosis": float(r.kurt()) if len(r) > 3 else float("nan"),
        "worst_day": float(r.min()) if len(r) else float("nan"),
        "worst_day_date": worst_day,
    }
