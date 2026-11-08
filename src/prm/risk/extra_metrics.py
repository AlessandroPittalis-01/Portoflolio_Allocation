"""Further risk metrics (IPS decision 39, step 5). Losses and drawdown depths are POSITIVE numbers.

* DaR / CDaR      drawdown-at-risk and conditional drawdown-at-risk: the drawdown depth that is exceeded 5% of the time,
                  and the AVERAGE depth in that worst 5% of the time (the drawdown analogue of VaR and ES)
* Ulcer index     root-mean-square drawdown: it punishes deep AND long drawdowns
* Diversification ratio and effective number of risk bets (entropy of the risk shares)
* Component ES    Euler split of the historical ES among the assets: it adds up EXACTLY to the portfolio ES
* Stress correlation  correlation of each asset with the equity market on the worst days of the market, corrected for
                  the selection effect (Forbes-Rigobon): does the diversification really weaken when it is needed?

Honest limits: all are historical and in-sample; the tail contributions rest on few days (5% of the sample); the
corrected correlation assumes that the slope and the noise of the relation do not change in stress, so a value above the
normal-time correlation is evidence of a change, not a measurement of how large it will be.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from prm.risk.metrics import drawdown_series


def drawdown_depths(r: pd.Series) -> pd.Series:
    """Drawdown depth on each day as a positive number (0 at a new high)."""
    return -drawdown_series(r.dropna())


def dar_cdar(r: pd.Series, level: float = 0.95) -> tuple[float, float]:
    """(DaR, CDaR): the ``level`` quantile of the drawdown depth and the mean depth of the days at or beyond it."""
    d = drawdown_depths(r)
    if len(d) < 20:
        return float("nan"), float("nan")
    q = float(d.quantile(level))
    tail = d[d >= q]
    return q, float(tail.mean())


def ulcer_index(r: pd.Series) -> float:
    d = drawdown_depths(r)
    return float(math.sqrt(float((d ** 2).mean()))) if len(d) else float("nan")


def diversification_ratio(weights: pd.Series, cov: pd.DataFrame) -> float:
    """sum_i w_i sigma_i / sigma_p  (>= 1 for long-only; 1 = no diversification)."""
    w = weights.reindex(cov.index).fillna(0.0).to_numpy(float)
    sd = np.sqrt(np.diag(cov))
    sigma_p = float(np.sqrt(w @ cov.to_numpy() @ w))
    if sigma_p <= 0:
        raise ValueError("portfolio volatility is zero")
    return float((w * sd).sum() / sigma_p)


def effective_risk_bets(risk_shares: pd.Series) -> float:
    """exp of the entropy of the risk shares: N equal shares give N; one asset carrying everything gives 1."""
    p = risk_shares.clip(lower=0.0)
    p = p / p.sum()
    p = p[p > 0]
    return float(math.exp(-float((p * np.log(p)).sum())))


def component_es(returns: pd.DataFrame, weights: pd.Series, level: float = 0.95) -> pd.DataFrame:
    """Euler split of the historical ES. Tail days = days with portfolio return at or below its (1-level) quantile.
    component_i = - w_i * mean(r_i on tail days); the components add up to the portfolio ES exactly."""
    w = weights.reindex(returns.columns).fillna(0.0)
    port = returns @ w
    cut = port.quantile(1 - level)
    tail = returns[port <= cut]
    comp = -(w * tail.mean())
    es = float(-port[port <= cut].mean())
    return pd.DataFrame({"weight": w, "component_es": comp, "share_of_es": comp / es}).assign(es_total=es)


def stress_correlation(returns: pd.DataFrame, market: pd.Series, tail: float = 0.10) -> pd.DataFrame:
    """Correlation of each column of ``returns`` with ``market`` on all days and on the worst ``tail`` of market days.

    Selecting days on the market return mechanically lowers the measured correlation. The corrected value undoes only
    that effect (Forbes-Rigobon, delta = var_stress(x)/var_all(x) - 1; rho* = rho_s / sqrt(1 + delta (1 - rho_s^2))).
    adjusted > all  means the relation really strengthened in stress."""
    df = pd.concat([returns, market.rename("_mkt")], axis=1, sort=True).dropna()
    m = df["_mkt"]
    stress = df[m <= m.quantile(tail)]
    if len(stress) < 20:
        raise ValueError("too few stress days")
    delta = float(stress["_mkt"].var() / m.var() - 1.0)
    rows = {}
    for c in returns.columns:
        r_all = float(df[c].corr(m))
        r_s = float(stress[c].corr(stress["_mkt"]))
        adj = r_s / math.sqrt(1.0 + delta * (1.0 - r_s ** 2)) if 1.0 + delta * (1.0 - r_s ** 2) > 0 else float("nan")
        rows[c] = {"corr_all": r_all, "corr_stress_raw": r_s, "corr_stress_adjusted": adj, "change": adj - r_all}
    out = pd.DataFrame(rows).T
    out.attrs["delta"], out.attrs["n_stress_days"] = delta, len(stress)
    return out
