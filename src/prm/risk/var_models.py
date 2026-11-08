"""1-day VaR and Expected Shortfall with models that look at TODAY's volatility (IPS decision 39, step 1).

Losses are POSITIVE numbers (VaR 0.02 = a loss of 2%). Every model answers the same question:
"what is the loss that is exceeded with probability 1 - level tomorrow?" but with different assumptions:

* historical      all past days weighted equally (metrics.hist_var_es): slow to react to a calm or stormy market
* gaussian        bell curve with the full-sample volatility: ignores fat tails
* ewma / garch    bell curve with the CURRENT volatility estimate (conditional volatility)
* fhs             Filtered Historical Simulation (Barone-Adesi et al.): divide each past return by its volatility of
                  that day, keep the shape of the tails, rescale with tomorrow's volatility. Reacts to the regime and
                  keeps the real tail shape
* monte carlo     simulate many days of all assets together with a covariance matrix, Gaussian or Student-t
                  (fat tails, same covariance), and read the portfolio loss distribution

Honest limits: they all use the past; fixed weights (no rebalancing within the day); the Student-t shares one
degrees-of-freedom value among all assets (no tail dependence beyond what a multivariate t gives); GARCH is fitted
by Gaussian quasi-maximum likelihood with variance targeting. Quality is judged by BACKTESTING (next step), not by
how good the formulas look.
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import minimize

MIN_OBS = 100


def _clean(r: pd.Series) -> pd.Series:
    r = r.dropna()
    if len(r) < MIN_OBS:
        raise ValueError(f"at least {MIN_OBS} observations are needed (got {len(r)})")
    return r


# ---- conditional volatility ---------------------------------------------------------------------------
def ewma_sigma(r: pd.Series, lam: float = 0.94) -> tuple[pd.Series, float]:
    """RiskMetrics volatility. ``sigma[t]`` is the forecast for day t made with returns up to t-1 only
    (no look-ahead); the second value is the forecast for the day after the last observation."""
    if not 0 < lam < 1:
        raise ValueError("lam must be between 0 and 1")
    r = _clean(r)
    x = r.to_numpy()
    var = np.empty(len(x) + 1)
    var[0] = float(np.var(x[:30])) if len(x) >= 30 else float(np.var(x))
    for t in range(len(x)):
        var[t + 1] = lam * var[t] + (1 - lam) * x[t] ** 2
    return pd.Series(np.sqrt(var[:-1]), index=r.index), float(math.sqrt(var[-1]))


def _garch_path(x: np.ndarray, omega: float, alpha: float, beta: float, var0: float) -> np.ndarray:
    var = np.empty(len(x) + 1)
    var[0] = var0
    for t in range(len(x)):
        var[t + 1] = omega + alpha * x[t] ** 2 + beta * var[t]
    return var


def garch11_fit(r: pd.Series) -> dict:
    """GARCH(1,1) by Gaussian quasi-maximum likelihood, variance targeting (omega = var * (1 - alpha - beta)).

    Returns alpha, beta, persistence, long-run annual volatility, the sigma series (forecast for day t from
    returns up to t-1) and ``sigma_next``. Zero mean is assumed (daily returns are tiny against their volatility).
    """
    r = _clean(r)
    x = r.to_numpy()
    uncond = float(np.mean(x ** 2))

    def nll(p):
        alpha, beta = p
        if alpha < 0 or beta < 0 or alpha + beta >= 0.9999:
            return 1e10
        var = _garch_path(x, uncond * (1 - alpha - beta), alpha, beta, uncond)[:-1]
        return 0.5 * float(np.sum(np.log(var) + x ** 2 / var))

    best = None
    for start in ((0.05, 0.90), (0.10, 0.80), (0.03, 0.95)):
        res = minimize(nll, start, method="Nelder-Mead", options={"xatol": 1e-5, "fatol": 1e-8, "maxiter": 600})
        if best is None or res.fun < best.fun:
            best = res
    alpha, beta = (float(v) for v in best.x)
    if alpha + beta >= 0.9999 or alpha < 0 or beta < 0:
        raise ValueError("GARCH fit failed: parameters outside the stationary region")
    omega = uncond * (1 - alpha - beta)
    var = _garch_path(x, omega, alpha, beta, uncond)
    return {"alpha": alpha, "beta": beta, "persistence": alpha + beta, "omega": omega,
            "long_run_vol_ann": float(math.sqrt(uncond * 252)),
            "sigma": pd.Series(np.sqrt(var[:-1]), index=r.index), "sigma_next": float(math.sqrt(var[-1]))}


# ---- closed forms used as references and by the simple models -------------------------------------------
def normal_var_es(sigma: float, level: float = 0.95, mu: float = 0.0) -> tuple[float, float]:
    z = NormalDist().inv_cdf(1 - level)
    pdf = math.exp(-0.5 * z * z) / math.sqrt(2 * math.pi)
    return -(mu + sigma * z), -(mu - sigma * pdf / (1 - level))


def student_var_es(sigma: float, df: float, level: float = 0.95, mu: float = 0.0) -> tuple[float, float]:
    """VaR and ES of a Student-t scaled to standard deviation ``sigma`` (needs df > 2)."""
    if df <= 2:
        raise ValueError("df must be above 2 for a finite variance")
    scale = sigma * math.sqrt((df - 2) / df)
    tq = float(stats.t.ppf(1 - level, df))
    es_std = float(stats.t.pdf(tq, df)) * (df + tq ** 2) / ((df - 1) * (1 - level))
    return -(mu + scale * tq), -mu + scale * es_std


def fit_student_df(z: pd.Series | np.ndarray, lo: float = 2.5, hi: float = 100.0) -> float:
    """Degrees of freedom of a zero-centred Student-t fitted to STANDARDISED returns (unit variance).
    Low = fat tails (about 4-6 is typical for daily returns); 100 is almost a bell curve."""
    z = np.asarray(pd.Series(z).dropna(), dtype=float)
    if len(z) < MIN_OBS:
        raise ValueError(f"at least {MIN_OBS} observations are needed")
    z = z / z.std()

    def nll(df):
        scale = math.sqrt((df - 2) / df)
        return -float(np.sum(stats.t.logpdf(z / scale, df) - math.log(scale)))

    res = minimize(lambda p: nll(p[0]), [8.0], bounds=[(lo, hi)], method="L-BFGS-B")
    return float(res.x[0])


# ---- Filtered Historical Simulation ---------------------------------------------------------------------
def fhs_var_es(r: pd.Series, level: float = 0.95, vol: str = "ewma", lam: float = 0.94) -> dict:
    """Filtered historical simulation: standardise by the daily conditional volatility, take the empirical
    quantile / tail mean of the standardised returns, rescale with tomorrow's volatility.
    ``vol`` is 'ewma' or 'garch'. Returns var, es, sigma_next (daily) and the standardised residuals."""
    r = _clean(r)
    if vol == "ewma":
        sigma, sigma_next = ewma_sigma(r, lam)
    elif vol == "garch":
        fit = garch11_fit(r)
        sigma, sigma_next = fit["sigma"], fit["sigma_next"]
    else:
        raise ValueError("vol must be 'ewma' or 'garch'")
    z = (r / sigma).dropna()
    q = float(z.quantile(1 - level))
    tail = z[z <= q]
    return {"var": float(-q * sigma_next), "es": float(-tail.mean() * sigma_next), "sigma_next": sigma_next, "z": z}


# ---- Monte Carlo -----------------------------------------------------------------------------------------
def simulate_returns(cov_daily: pd.DataFrame, n_paths: int = 200_000, df: float | None = None,
                     mean: pd.Series | None = None, seed: int = 42) -> pd.DataFrame:
    """One-day returns of all assets, jointly. ``df=None`` gives a multivariate normal; a number gives a multivariate
    Student-t with that many degrees of freedom, scaled so that the covariance is exactly ``cov_daily``."""
    if df is not None and df <= 2:
        raise ValueError("df must be above 2")
    rng = np.random.default_rng(seed)
    cov = cov_daily.to_numpy()
    chol = np.linalg.cholesky(cov + 1e-14 * np.eye(len(cov)))
    z = rng.standard_normal((n_paths, len(cov))) @ chol.T
    if df is not None:
        w = rng.chisquare(df, n_paths) / df
        z = z / np.sqrt(w)[:, None] * math.sqrt((df - 2) / df)
    mu = np.zeros(len(cov)) if mean is None else mean.reindex(cov_daily.index).to_numpy()
    return pd.DataFrame(z + mu, columns=cov_daily.columns)


def mc_var_es(weights: pd.Series, cov_daily: pd.DataFrame, level: float = 0.95, n_paths: int = 200_000,
              df: float | None = None, mean: pd.Series | None = None, seed: int = 42) -> tuple[float, float]:
    sims = simulate_returns(cov_daily, n_paths, df, mean, seed)
    pnl = sims @ weights.reindex(cov_daily.index).fillna(0.0)
    cut = pnl.quantile(1 - level)
    return float(-cut), float(-pnl[pnl <= cut].mean())
