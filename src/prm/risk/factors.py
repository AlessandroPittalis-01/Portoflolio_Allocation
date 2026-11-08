"""Risk-factor sensitivities of a portfolio (IPS decision 39, step 3): the 'Greeks' of a linear portfolio.

ETFs are linear instruments, so there is no gamma, vega or theta. The equivalent of delta is the sensitivity of the
portfolio return to a few risk factors: equity market (beta), interest rates (duration proxy), credit spread,
inflation, gold and EUR/PLN. They are estimated by OLS of the portfolio PLN return on factor returns built from ETFs.

The variance splits exactly: Var(p) = sum_i beta_i * Cov(f_i, p) + Var(residual). Each term over Var(p) is the share
of the risk explained by that factor (it can be negative = the factor diversifies); the residual is what the factors
do not explain.

Honest limits: factors are ETF proxies (collinear, with their own mix of exposures), betas change over time (see the
rolling check), OLS standard errors ignore autocorrelation and fat tails, and a beta is a sensitivity to SMALL moves,
not a stress test. Read it as a map of where the risk comes from.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

DEFAULT_FACTORS_PATH = Path(__file__).resolve().parents[3] / "config" / "risk_factors.yaml"
FX_NAME = "EURPLN"


class FactorConfigError(ValueError):
    pass


def load_factor_config(path: Path | str = DEFAULT_FACTORS_PATH) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    factors = cfg.get("factors")
    if not isinstance(factors, dict) or len(factors) < 2:
        raise FactorConfigError("factors must be a mapping with at least 2 factors")
    for name, expr in factors.items():
        if not isinstance(expr, str) or not expr.strip():
            raise FactorConfigError(f"factor '{name}' needs an expression like 'a' or 'a - b'")
        parts = [p.strip() for p in expr.split(" - ")]
        if len(parts) > 2 or not all(parts):
            raise FactorConfigError(f"factor '{name}': use 'a' or 'a - b'")
    ref = cfg.get("fx_reference_asset")
    if any(e.strip() == FX_NAME for e in factors.values()) and not isinstance(ref, str):
        raise FactorConfigError("fx_reference_asset is needed when a factor is EURPLN")
    return {"factors": {k: v.strip() for k, v in factors.items()}, "fx_reference_asset": ref}


def build_factors(local: pd.DataFrame, pln: pd.DataFrame, factors: dict[str, str], fx_reference_asset: str | None) -> pd.DataFrame:
    """Daily factor returns. Raises FactorConfigError if an ETF is missing."""
    out = {}
    for name, expr in factors.items():
        if expr == FX_NAME:
            if fx_reference_asset not in local.columns or fx_reference_asset not in pln.columns:
                raise FactorConfigError(f"fx reference asset '{fx_reference_asset}' has no returns")
            out[name] = (1 + pln[fx_reference_asset]) / (1 + local[fx_reference_asset]) - 1
            continue
        legs = [p.strip() for p in expr.split(" - ")]
        missing = [a for a in legs if a not in local.columns]
        if missing:
            raise FactorConfigError(f"factor '{name}': no returns for {missing}")
        out[name] = local[legs[0]] - (local[legs[1]] if len(legs) == 2 else 0.0)
    return pd.DataFrame(out)


def ols(y: pd.Series, x: pd.DataFrame) -> dict:
    """OLS with intercept. Returns betas (Series), t-stats (classic), r2 and the residual series."""
    df = pd.concat([y.rename("y"), x], axis=1, sort=True).dropna()
    if len(df) < 5 * (x.shape[1] + 1):
        raise ValueError("too few observations for this number of factors")
    X = np.column_stack([np.ones(len(df)), df[x.columns].to_numpy()])
    yy = df["y"].to_numpy()
    coef, *_ = np.linalg.lstsq(X, yy, rcond=None)
    resid = yy - X @ coef
    dof = len(df) - X.shape[1]
    sigma2 = float(resid @ resid / dof)
    se = np.sqrt(np.diag(sigma2 * np.linalg.pinv(X.T @ X)))
    r2 = 1 - float(resid @ resid) / float(((yy - yy.mean()) ** 2).sum())
    names = list(x.columns)
    return {"alpha": float(coef[0]), "beta": pd.Series(coef[1:], index=names), "t": pd.Series(coef[1:] / se[1:], index=names),
            "r2": r2, "resid": pd.Series(resid, index=df.index), "data": df}


def variance_attribution(y: pd.Series, x: pd.DataFrame, fit: dict | None = None) -> pd.DataFrame:
    """Share of Var(y) per factor: beta_i * Cov(f_i, y) / Var(y); the last row is the residual. Shares add up to 1."""
    fit = fit or ols(y, x)
    df = fit["data"]
    var = float(df["y"].var())
    rows = {f: float(fit["beta"][f] * df[f].cov(df["y"]) / var) for f in x.columns}
    rows["residual"] = float(fit["resid"].var() / var)
    return pd.DataFrame({"share_of_variance": pd.Series(rows)})


def sensitivities(y: pd.Series, x: pd.DataFrame) -> pd.DataFrame:
    """One table: beta (portfolio % move for a 1% move of the factor), t-stat, factor volatility (annual), and the
    portfolio move for a 1-sigma monthly factor shock (beta x monthly sigma)."""
    fit = ols(y, x)
    attr = variance_attribution(y, x, fit)
    vol_ann = fit["data"][x.columns].std() * np.sqrt(252)
    shock = fit["beta"] * fit["data"][x.columns].std() * np.sqrt(21)
    out = pd.DataFrame({"beta": fit["beta"], "t_stat": fit["t"], "factor_vol_ann": vol_ann,
                        "one_sigma_month_move": shock, "share_of_variance": attr["share_of_variance"].reindex(x.columns)})
    out.attrs["r2"], out.attrs["residual_share"] = fit["r2"], float(attr.loc["residual", "share_of_variance"])
    return out


def rolling_beta(y: pd.Series, x: pd.DataFrame, window: int = 504, step: int = 63) -> pd.DataFrame:
    """Betas re-estimated on windows of ``window`` days every ``step`` days (a stability check: do they move?)."""
    df = pd.concat([y.rename("y"), x], axis=1, sort=True).dropna()
    rows = {}
    for end in range(window, len(df) + 1, step):
        w = df.iloc[end - window:end]
        rows[w.index[-1]] = ols(w["y"], w[x.columns])["beta"]
    return pd.DataFrame(rows).T
