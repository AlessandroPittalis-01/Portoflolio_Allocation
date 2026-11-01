"""Covariance matrix estimators.

Why not only the sample covariance?  With many assets and a few years of data it is noisy, and an
optimiser loves noise: it puts big weights exactly where the estimate is wrong ("error maximiser").
Two standard remedies:

* **EWMA** (RiskMetrics): recent days count more, so the matrix follows the current volatility.
* **Ledoit-Wolf shrinkage**: mix the sample matrix with a simple, stable target (here: the identity
  scaled to the average variance). The mixing weight is estimated from the data (Ledoit & Wolf, 2004).

All functions take DAILY returns without missing values and return DAILY covariance matrices;
``annualise`` multiplies by 252.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def _clean(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.isna().any().any():
        raise ValueError("returns contain missing values: pass a common window (use dropna first)")
    if len(returns) < 2:
        raise ValueError("at least 2 observations are needed")
    return returns


def sample_cov(returns: pd.DataFrame) -> pd.DataFrame:
    """Ordinary sample covariance (divides by n-1)."""
    return _clean(returns).cov()


def ewma_cov(returns: pd.DataFrame, lam: float = 0.94) -> pd.DataFrame:
    """Exponentially weighted covariance, zero mean (RiskMetrics: lambda 0.94 for daily data).

    The last day has weight proportional to 1, the day before to lam, then lam^2, and so on.
    """
    if not 0 < lam <= 1:
        raise ValueError("lam must be in (0, 1]")
    x = _clean(returns).to_numpy()
    n = len(x)
    w = lam ** np.arange(n - 1, -1, -1)       # oldest day first -> smallest weight
    w = w / w.sum()
    cov = (x * w[:, None]).T @ x
    return pd.DataFrame(cov, index=returns.columns, columns=returns.columns)


def ledoit_wolf(returns: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Ledoit-Wolf shrinkage towards ``mu * I`` (mu = average variance). Returns ``(matrix, shrinkage)``.

    shrinkage is between 0 (pure sample covariance) and 1 (pure target).
    """
    x = _clean(returns).to_numpy()
    n, p = x.shape
    x = x - x.mean(axis=0)
    s = x.T @ x / n
    mu = np.trace(s) / p
    d2 = float(((s - mu * np.eye(p)) ** 2).sum())            # distance sample <-> target
    b2 = float(((x ** 2).sum(axis=1) ** 2).mean() - (s ** 2).sum()) / n   # estimation noise of the sample matrix
    b2 = min(max(b2, 0.0), d2)
    shrink = 0.0 if d2 == 0 else b2 / d2
    shrunk = (1 - shrink) * s + shrink * mu * np.eye(p)
    return pd.DataFrame(shrunk, index=returns.columns, columns=returns.columns), float(shrink)


def annualise(cov: pd.DataFrame) -> pd.DataFrame:
    return cov * TRADING_DAYS


def to_correlation(cov: pd.DataFrame) -> pd.DataFrame:
    sd = np.sqrt(np.diag(cov))
    corr = cov.to_numpy() / np.outer(sd, sd)
    return pd.DataFrame(corr, index=cov.index, columns=cov.columns)


def common_window(returns: pd.DataFrame) -> pd.DataFrame:
    """Rows where EVERY asset has a return (the window is set by the shortest history)."""
    return returns.dropna(how="any")
