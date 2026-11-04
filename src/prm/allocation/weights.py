"""Weight-finding methods. Each takes a covariance matrix of the RISKY ETFs and returns weights
that are long-only and add up to 1. Cash is NOT included here: it is added later by volatility targeting.

Methods (tiers 0-2 of IPS section 5)
------------------------------------
* ``equal_weight``  1/N. The baseline that is hard to beat out of sample.
* ``inverse_vol``   weight proportional to 1/volatility. Ignores correlations.
* ``risk_parity``   Equal Risk Contribution (ERC): every ETF carries the same share of portfolio risk.
* ``min_variance``  the lowest-variance mix, with a cap per ETF (without caps it concentrates in 1-2 assets).
* ``hrp``           Hierarchical Risk Parity (Lopez de Prado): clusters similar ETFs, then splits risk
                    top-down. No matrix inversion, so it is more stable when assets are very correlated.

None of these uses expected returns: they only need the covariance matrix.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import leaves_list, linkage
from scipy.optimize import minimize
from scipy.spatial.distance import squareform


def _check(cov: pd.DataFrame) -> None:
    if cov.shape[0] != cov.shape[1] or cov.shape[0] < 1:
        raise ValueError("covariance matrix must be square and not empty")
    if (np.diag(cov) <= 0).any():
        raise ValueError("every asset needs a positive variance")


def equal_weight(cov: pd.DataFrame) -> pd.Series:
    _check(cov)
    return pd.Series(1.0 / len(cov), index=cov.index)


def inverse_vol(cov: pd.DataFrame) -> pd.Series:
    _check(cov)
    inv = 1.0 / np.sqrt(np.diag(cov))
    return pd.Series(inv / inv.sum(), index=cov.index)


def risk_parity(cov: pd.DataFrame) -> pd.Series:
    """Equal risk contribution, long only.

    Solves the convex problem  min 0.5 w'Sw - (1/n) sum ln(w_i)  (Spinu, 2013). Its solution, once
    rescaled to sum to 1, makes every risk contribution equal. The log term keeps all weights positive.
    """
    _check(cov)
    s = cov.to_numpy()
    n = len(s)
    scale = 1.0 / np.mean(np.diag(s))                       # keeps the numbers near 1 for the optimiser
    s = s * scale

    def objective(w):
        return 0.5 * w @ s @ w - np.log(w).sum() / n

    def gradient(w):
        return s @ w - 1.0 / (n * w)

    x0 = 1.0 / np.sqrt(np.diag(s))
    x0 = x0 / x0.sum()
    res = minimize(objective, x0, jac=gradient, method="L-BFGS-B", bounds=[(1e-10, None)] * n,
                   options={"maxiter": 1000, "ftol": 1e-15, "gtol": 1e-12})
    if not res.success and not np.isfinite(res.fun):
        raise RuntimeError(f"risk parity did not converge: {res.message}")
    w = res.x / res.x.sum()
    return pd.Series(w, index=cov.index)


def risk_budget(cov: pd.DataFrame, budgets: pd.Series) -> pd.Series:
    """Risk budgeting: every ETF carries the share of risk written in ``budgets`` (long only).

    ``budgets`` are positive numbers (rescaled to add up to 1). With equal budgets this is exactly risk parity.
    Same convex problem as ``risk_parity`` with a weighted log term:  min 0.5 w'Sw - sum b_i ln(w_i).
    The budgets are a POLICY decision written in the IPS before looking at results (they are not tuned).
    """
    _check(cov)
    b = budgets.reindex(cov.index)
    if b.isna().any() or (b <= 0).any():
        raise ValueError("every ETF needs a positive risk budget")
    b = (b / b.sum()).to_numpy()
    s = cov.to_numpy()
    s = s / np.mean(np.diag(s))
    n = len(s)

    def objective(w):
        return 0.5 * w @ s @ w - (b * np.log(w)).sum()

    def gradient(w):
        return s @ w - b / w

    x0 = b / np.sqrt(np.diag(s))
    x0 = x0 / x0.sum()
    res = minimize(objective, x0, jac=gradient, method="L-BFGS-B", bounds=[(1e-10, None)] * n,
                   options={"maxiter": 1000, "ftol": 1e-15, "gtol": 1e-12})
    if not np.isfinite(res.fun):
        raise RuntimeError(f"risk budgeting did not converge: {res.message}")
    return pd.Series(res.x / res.x.sum(), index=cov.index)


def min_variance(cov: pd.DataFrame, max_weight: float = 1.0) -> pd.Series:
    """Lowest-variance long-only mix with weights between 0 and ``max_weight``."""
    _check(cov)
    n = len(cov)
    if max_weight * n < 1 - 1e-12:
        raise ValueError(f"max_weight {max_weight} is too small for {n} assets (they cannot add up to 1)")
    s = cov.to_numpy()
    scale = 1.0 / np.mean(np.diag(s))
    s = s * scale
    x0 = np.full(n, 1.0 / n)
    res = minimize(lambda w: w @ s @ w, x0, jac=lambda w: 2 * s @ w, method="SLSQP",
                   bounds=[(0.0, max_weight)] * n,
                   constraints=[{"type": "eq", "fun": lambda w: w.sum() - 1.0, "jac": lambda w: np.ones(n)}],
                   options={"maxiter": 500, "ftol": 1e-14})
    if not res.success:
        raise RuntimeError(f"minimum variance did not converge: {res.message}")
    w = np.clip(res.x, 0.0, max_weight)
    return pd.Series(w / w.sum(), index=cov.index)


def _cluster_variance(cov: pd.DataFrame, items: list) -> float:
    """Variance of a cluster using inverse-variance weights inside it."""
    sub = cov.loc[items, items].to_numpy()
    ivp = 1.0 / np.diag(sub)
    ivp = ivp / ivp.sum()
    return float(ivp @ sub @ ivp)


def hrp(cov: pd.DataFrame) -> pd.Series:
    """Hierarchical Risk Parity: cluster by correlation, then split weight between the two halves of each
    cluster in inverse proportion to their variance (recursive bisection)."""
    _check(cov)
    n = len(cov)
    if n == 1:
        return pd.Series(1.0, index=cov.index)
    sd = np.sqrt(np.diag(cov))
    corr = np.clip(cov.to_numpy() / np.outer(sd, sd), -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, None))
    np.fill_diagonal(dist, 0.0)
    order = leaves_list(linkage(squareform(dist, checks=False), method="single"))
    items = [cov.index[i] for i in order]                     # similar ETFs end up next to each other

    w = pd.Series(1.0, index=items)
    clusters = [items]
    while clusters:
        clusters = [c[i:j] for c in clusters for i, j in ((0, len(c) // 2), (len(c) // 2, len(c))) if len(c) > 1]
        for k in range(0, len(clusters), 2):
            left, right = clusters[k], clusters[k + 1]
            v_left, v_right = _cluster_variance(cov, left), _cluster_variance(cov, right)
            alpha = 1.0 - v_left / (v_left + v_right)          # the calmer half gets more weight
            w[left] *= alpha
            w[right] *= 1.0 - alpha
    return (w / w.sum()).reindex(cov.index)


def cap_weights(w: pd.Series, max_weight: float) -> pd.Series:
    """Limit every weight to ``max_weight`` and give the excess to the others, in proportion to their weights.
    Repeats until nobody is above the cap. Weights still add up to 1."""
    if max_weight * len(w) < 1 - 1e-12:
        raise ValueError(f"max_weight {max_weight} is too small for {len(w)} assets")
    out = w.astype(float).copy()
    for _ in range(len(w) + 1):
        over = out > max_weight + 1e-12
        if not over.any():
            return out
        excess = float((out[over] - max_weight).sum())
        out[over] = max_weight
        free = ~over & (out < max_weight - 1e-12)
        if not free.any():
            break
        out[free] += excess * out[free] / out[free].sum()
    return out
