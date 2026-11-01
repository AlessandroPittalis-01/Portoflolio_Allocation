"""Risk contributions: how much of the portfolio risk each asset is responsible for.

Portfolio volatility  sigma_p = sqrt(w' S w).  The contribution of asset i is

    RC_i = w_i * (S w)_i / sigma_p        and      sum_i RC_i = sigma_p      (Euler's theorem)

The percentage contribution is RC_i / sigma_p; they add up to 100%. An asset with 10% of the money
can easily carry 40% of the risk: this is the core idea of risk-based allocation.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def portfolio_vol(weights: pd.Series, cov: pd.DataFrame) -> float:
    w = weights.reindex(cov.index).to_numpy(dtype=float)
    return float(np.sqrt(w @ cov.to_numpy() @ w))


def risk_contributions(weights: pd.Series, cov: pd.DataFrame) -> pd.DataFrame:
    """Table with weight, absolute contribution (same unit as the volatility) and percentage contribution."""
    w = weights.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)
    sigma = float(np.sqrt(w @ cov.to_numpy() @ w))
    if sigma == 0:
        raise ValueError("portfolio volatility is zero")
    marginal = cov.to_numpy() @ w / sigma
    rc = w * marginal
    return pd.DataFrame({"weight": w, "risk_contribution": rc, "risk_share": rc / sigma}, index=cov.index)
