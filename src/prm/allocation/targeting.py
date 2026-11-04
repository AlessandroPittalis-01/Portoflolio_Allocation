"""Volatility targeting and portfolio limits.

Volatility targeting (no leverage)
----------------------------------
A method gives weights for the risky ETFs (sum 1). To hit the volatility target we keep a share ``k`` of
that mix and put ``1 - k`` in the cash-like ETF:  final = k * risky + (1 - k) * cash.
The mix is searched on a grid of k between 0 and 1 and the LARGEST k with volatility <= target is used.
We do not just multiply the risky volatility by k: in PLN the cash-like ETF has 6% volatility of its own
(the EUR/PLN rate) and it is correlated with the other EUR assets, so the exact covariance is used.
If even k = 1 is below the target we stop at k = 1: no leverage.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

GRID = 1001


def portfolio_vol(weights: pd.Series, cov: pd.DataFrame) -> float:
    w = weights.reindex(cov.index).fillna(0.0).to_numpy(dtype=float)
    return float(np.sqrt(w @ cov.to_numpy() @ w))


def scale_to_target_vol(risky: pd.Series, cov: pd.DataFrame, cash_id: str, target_vol: float) -> tuple[pd.Series, float, str]:
    """Return ``(final weights incl. cash, k, status)``. ``cov`` must be ANNUAL and include the cash ETF.

    status: "on_target", "below_target" (k = 1, cannot take more risk without leverage) or
    "above_floor" (even the lowest-risk mix is above the target: the minimum-volatility mix is used).
    """
    if cash_id not in cov.index:
        raise ValueError(f"cash ETF '{cash_id}' is not in the covariance matrix")
    ids = list(cov.index)
    risky_full = risky.reindex(ids).fillna(0.0).to_numpy(dtype=float)
    cash = np.zeros(len(ids))
    cash[ids.index(cash_id)] = 1.0
    ks = np.linspace(0.0, 1.0, GRID)
    mixes = ks[:, None] * risky_full[None, :] + (1 - ks)[:, None] * cash[None, :]
    vols = np.sqrt(np.einsum("ij,jk,ik->i", mixes, cov.to_numpy(), mixes))
    ok = np.where(vols <= target_vol + 1e-12)[0]
    if len(ok) == 0:
        idx, status = int(np.argmin(vols)), "above_floor"
    else:
        idx = int(ok.max())
        status = "below_target" if idx == GRID - 1 and vols[idx] < target_vol - 1e-4 else "on_target"
    return pd.Series(mixes[idx], index=ids), float(ks[idx]), status


def enforce_limits(weights: pd.Series, roles: dict[str, str], max_weight: float, equity_cap: float,
                   cash_id: str) -> pd.Series:
    """Apply the profile limits to FINAL weights: max weight per ETF (cash-like exempt) and equity cap.
    Any excess goes to the cash-like ETF, so weights still add up to 1 (and risk can only go down)."""
    w = weights.astype(float).copy()
    excess = 0.0
    for asset in w.index:
        if asset != cash_id and w[asset] > max_weight:
            excess += w[asset] - max_weight
            w[asset] = max_weight
    equity = [a for a in w.index if roles.get(a) == "equity"]
    equity_total = float(w[equity].sum()) if equity else 0.0
    if equity and equity_total > equity_cap:
        w[equity] *= equity_cap / equity_total
        excess += equity_total - equity_cap
    w[cash_id] += excess
    return w
