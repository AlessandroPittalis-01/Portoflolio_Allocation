"""Hidden dollar exposure of ETFs quoted in EUR.

A EUR-quoted World ETF holds mostly US assets, so its EUR return moves with the dollar. We measure it
with a regression of the ETF's LOCAL (EUR) log return on the log change of the value of 1 USD in EUR:

    local_t = alpha + beta * usd_t + error_t        beta = "dollar beta", R2 = share of variance explained

The USD/EUR rate is computed from the two NBP rates we already have: (PLN per USD) / (PLN per EUR).
Caution: beta also captures the common reaction of stocks and the dollar to the same news, so it is a
statistical exposure, not an accounting one. It complements the fund factsheets, it does not replace them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from prm.fx.returns import align_fx


def usd_in_eur(usd_pln: pd.Series, eur_pln: pd.Series) -> pd.Series:
    """Value of 1 USD in EUR on the dates where both rates exist."""
    both = pd.concat([usd_pln, eur_pln], axis=1, join="inner").dropna()
    return both.iloc[:, 0] / both.iloc[:, 1]


def usd_beta(local_simple: pd.Series, usd_eur: pd.Series, min_obs: int = 60) -> tuple[float, float]:
    """Return ``(beta, r2)`` of the asset's local log return on the USD/EUR log change."""
    r = local_simple.dropna()
    if len(r) < min_obs:
        return float("nan"), float("nan")
    level = align_fx(usd_eur, r.index)
    # The rate change must cover the same interval as the asset return: use the asset's own dates.
    fx_ret = np.log(level).diff()
    y = np.log1p(r)
    d = pd.concat([y.rename("y"), fx_ret.rename("x")], axis=1).dropna()
    if len(d) < min_obs or d["x"].var() == 0:
        return float("nan"), float("nan")
    beta = d["y"].cov(d["x"]) / d["x"].var()
    r2 = d["y"].corr(d["x"]) ** 2
    return float(beta), float(r2)
