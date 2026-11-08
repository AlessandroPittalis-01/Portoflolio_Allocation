"""Backtesting of 1-day VaR / ES forecasts (IPS decision 39, step 2).

A VaR model is a claim: "with probability 1 - level the loss tomorrow exceeds VaR". Backtesting checks the claim
on the past, day by day, with forecasts made ONLY with data available the day before (no look-ahead):

* Kupiec (1995) POF      are there as many exceptions as promised? (too many = risk understated, too few = too cautious)
* Christoffersen (1998)  are the exceptions independent, or do they come in clusters (a model that is slow to react)?
* conditional coverage   the two together
* traffic light          Basel rule on the number of exceptions, from the binomial law (green / yellow / red)
* ES checks              ratio realised loss / forecast ES on exception days, and a McNeil-Frey style test
* tick (pinball) loss    one number per model to rank models that all pass the tests

Honest limits: with a 99% level and about 2500 days only about 25 exceptions are expected, so power is low and a
'pass' means 'not rejected', not 'correct'. The portfolio is the one return series given (fixed weights or the
realised walk-forward series); parameters of GARCH are re-estimated every ``refit_every`` days.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import stats

from prm.risk.var_models import MIN_OBS, ewma_sigma, garch11_fit, normal_var_es

MODELS = ("historical", "gaussian", "gaussian_ewma", "gaussian_garch", "fhs_ewma", "fhs_garch")


# ---- forecasts -------------------------------------------------------------------------------------------
def _tail(z: np.ndarray, level: float) -> tuple[float, float]:
    q = float(np.quantile(z, 1 - level))
    tail = z[z <= q]
    return q, float(tail.mean())


def _garch_blocks(x: np.ndarray, window: int, refit_every: int):
    """Yield (t, sigma_t, z_window) for t >= window. Every ``refit_every`` days GARCH is fitted on the ``window`` days
    before t; those parameters filter the volatility forward AND standardise the last ``window`` returns, so every
    quantity uses only returns before day t (the parameters are re-estimated, never taken from the future)."""
    n = len(x)
    t0 = window
    while t0 < n:
        fit = garch11_fit(pd.Series(x[t0 - window:t0]))
        omega, alpha, beta = fit["omega"], fit["alpha"], fit["beta"]
        end = min(t0 + refit_every, n)
        span = x[t0 - window:end]
        var = np.empty(len(span) + 1)
        var[0] = float(np.mean(span[:window] ** 2))
        for i in range(len(span)):
            var[i + 1] = omega + alpha * span[i] ** 2 + beta * var[i]
        sig = np.sqrt(var[:-1])                               # sig[i] = forecast for day t0 - window + i
        z = span / sig
        for u in range(t0, end):
            i = u - (t0 - window)
            yield u, float(math.sqrt(var[i])), z[i - window:i]
        t0 = end


def rolling_forecasts(r: pd.Series, model: str, level: float = 0.99, window: int = 500,
                      refit_every: int = 63, lam: float = 0.94) -> pd.DataFrame:
    """VaR and ES forecast (positive losses) for every day from ``window`` on, with returns up to the day before.

    Columns: var, es, sigma (the volatility used, 0 for historical), loss (the realised loss of that day).
    """
    if model not in MODELS:
        raise ValueError(f"model must be one of {MODELS}")
    r = r.dropna()
    if window < MIN_OBS or len(r) <= window + 20:
        raise ValueError("series too short for this window")
    x = r.to_numpy(dtype=float)
    n = len(x)
    var, es, sig = np.full(n, np.nan), np.full(n, np.nan), np.zeros(n)

    if model in ("fhs_garch", "gaussian_garch"):
        for u, s, zw in _garch_blocks(x, window, refit_every):
            sig[u] = s
            if model == "gaussian_garch":
                var[u], es[u] = normal_var_es(s, level)
            else:
                q, tl = _tail(zw, level)
                var[u], es[u] = -q * s, -tl * s
    else:
        if model in ("fhs_ewma", "gaussian_ewma"):
            s_all = ewma_sigma(r, lam)[0].to_numpy()           # s_all[t] uses returns up to t-1
            z_all = x / s_all
        for t in range(window, n):
            past = x[t - window:t]
            if model == "historical":
                q, tl = _tail(past, level)
                var[t], es[t] = -q, -tl
            elif model == "gaussian":
                sig[t] = past.std(ddof=1)
                var[t], es[t] = normal_var_es(float(sig[t]), level, float(past.mean()))
            elif model == "gaussian_ewma":
                sig[t] = s_all[t]
                var[t], es[t] = normal_var_es(float(s_all[t]), level)
            else:                                               # fhs_ewma
                q, tl = _tail(z_all[t - window:t], level)
                var[t], es[t], sig[t] = -q * s_all[t], -tl * s_all[t], s_all[t]
    out = pd.DataFrame({"var": var, "es": es, "sigma": sig, "loss": -x}, index=r.index).iloc[window:]
    return out.dropna()


# ---- tests ------------------------------------------------------------------------------------------------
def _xlogy(a: float, b: float) -> float:
    return 0.0 if a == 0 else a * math.log(b)


def kupiec_pof(n_exceptions: int, n_obs: int, p: float) -> dict:
    """Kupiec proportion-of-failures test; ``p`` = 1 - level. LR ~ chi2(1) under correct coverage."""
    x, n = n_exceptions, n_obs
    if n <= 0 or not 0 < p < 1 or not 0 <= x <= n:
        raise ValueError("invalid inputs")
    ph = x / n
    ll0 = _xlogy(n - x, 1 - p) + _xlogy(x, p)
    ll1 = _xlogy(n - x, 1 - ph) + _xlogy(x, ph)
    lr = max(-2 * (ll0 - ll1), 0.0)
    return {"lr": lr, "p_value": float(stats.chi2.sf(lr, 1))}


def christoffersen_independence(hits: np.ndarray) -> dict:
    """First-order Markov independence test of the exception series (1 = exception). NaN p-value if untestable."""
    h = np.asarray(hits, dtype=int)
    a, b = h[:-1], h[1:]
    n00, n01 = int(((a == 0) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    n10, n11 = int(((a == 1) & (b == 0)).sum()), int(((a == 1) & (b == 1)).sum())
    if n01 + n11 == 0 or n00 + n01 == 0 or n10 + n11 == 0:
        return {"lr": float("nan"), "p_value": float("nan")}           # no exceptions, or none followed by anything
    p01, p11 = n01 / (n00 + n01), n11 / (n10 + n11)
    p = (n01 + n11) / (n00 + n01 + n10 + n11)
    ll0 = _xlogy(n00 + n10, 1 - p) + _xlogy(n01 + n11, p)
    ll1 = _xlogy(n00, 1 - p01) + _xlogy(n01, p01) + _xlogy(n10, 1 - p11) + _xlogy(n11, p11)
    lr = max(-2 * (ll0 - ll1), 0.0)
    return {"lr": lr, "p_value": float(stats.chi2.sf(lr, 1))}


def conditional_coverage(kupiec: dict, indep: dict) -> dict:
    if math.isnan(indep["lr"]):
        return {"lr": float("nan"), "p_value": float("nan")}
    lr = kupiec["lr"] + indep["lr"]
    return {"lr": lr, "p_value": float(stats.chi2.sf(lr, 2))}


def traffic_light(n_exceptions: int, n_obs: int, p: float) -> str:
    """Basel-style zone from the binomial law: green while P(X <= exceptions) < 95%, yellow below 99.99%, else red.
    For 250 days at 99% this reproduces the Basel zones (green up to 4, yellow 5-9, red 10+)."""
    cdf = float(stats.binom.cdf(n_exceptions, n_obs, p))            # P(X <= x)
    if cdf < 0.95:
        return "green"
    return "yellow" if cdf < 0.9999 else "red"


def es_checks(fc: pd.DataFrame) -> dict:
    """ES on exception days: ratio of realised to forecast ES (about 1 is right, above 1 = tail understated) and a
    McNeil-Frey style one-sided t-test that (loss - ES) / VaR has zero mean on exception days."""
    ex = fc[fc["loss"] > fc["var"]]
    if len(ex) < 3:
        return {"es_ratio": float("nan"), "es_p_value": float("nan")}
    ratio = float(ex["loss"].mean() / ex["es"].mean())
    resid = (ex["loss"] - ex["es"]) / ex["var"]
    p = float(stats.ttest_1samp(resid, 0.0, alternative="greater").pvalue)
    return {"es_ratio": ratio, "es_p_value": p}


def tick_loss(fc: pd.DataFrame, level: float) -> float:
    """Average pinball loss of the VaR forecasts (lower is better); proper score for a quantile."""
    q = -fc["var"].to_numpy()                              # forecast quantile of the return
    ret = -fc["loss"].to_numpy()
    a = 1 - level
    d = ret - q
    return float(np.mean(np.where(d >= 0, a * d, (a - 1) * d)))


def backtest_model(r: pd.Series, model: str, level: float, window: int = 500, refit_every: int = 63) -> dict:
    fc = rolling_forecasts(r, model, level, window, refit_every)
    hits = (fc["loss"] > fc["var"]).to_numpy()
    n, x, p = len(fc), int(hits.sum()), 1 - level
    ku = kupiec_pof(x, n, p)
    ind = christoffersen_independence(hits)
    cc = conditional_coverage(ku, ind)
    return {"model": model, "level": level, "n_obs": n, "exceptions": x, "expected": n * p, "rate": x / n,
            "kupiec_p": ku["p_value"], "independence_p": ind["p_value"], "cc_p": cc["p_value"],
            "zone": traffic_light(x, n, p), "tick_loss": tick_loss(fc, level), **es_checks(fc)}
