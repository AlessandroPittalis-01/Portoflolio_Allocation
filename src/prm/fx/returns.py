"""Convert prices to PLN and split the PLN return into a local part and a currency part.

Idea
----
You buy an ETF quoted in EUR, but your money is in PLN. What you earn in PLN is

    (1 + PLN return) = (1 + local return) x (1 + FX return)

* local return = return of the ETF in its quote currency
* FX return    = change of the PLN price of that currency (EUR/PLN, USD/PLN)

With LOG returns the product becomes a sum, so the variance can be split exactly:

    FX share = cov(PLN, FX) / var(PLN)      local share = cov(PLN, local) / var(PLN)

The two shares add up to 1. A negative FX share means the currency moves HEDGED
the local risk in that period (the ETF falls when the currency rises). IPS section 3.1
sets a limit for the FX share of the portfolio (about 30%, to calibrate).

Honest limit: this separates only the quote currency. A EUR-quoted World ETF still holds
USD assets inside, and that hidden dollar risk is part of its "local" return. Stage 04 studies it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def align_fx(fx: pd.Series, dates: pd.DatetimeIndex) -> pd.Series:
    """FX level on each price date = the last published rate on or before that date (never a future one)."""
    fx = fx.sort_index()
    return fx.reindex(fx.index.union(dates)).ffill().reindex(dates)


def decompose(price_local: pd.Series, fx: pd.Series | None) -> pd.DataFrame:
    """Log returns ``local``, ``fx`` and ``pln`` of one asset, on the asset's own trading days.

    ``fx`` is PLN per 1 unit of the quote currency, or ``None`` if the asset is already quoted in PLN.
    Returns are computed between consecutive days on which the ASSET has a price, so a holiday of
    another exchange never creates a fake zero or a missing value.
    """
    price = price_local.dropna()
    price = price[price > 0]
    local = np.log(price).diff()
    if fx is None:
        fx_log = pd.Series(0.0, index=price.index)
    else:
        level = align_fx(fx, price.index)
        fx_log = np.log(level).diff()
    out = pd.DataFrame({"local": local, "fx": fx_log})
    out["pln"] = out["local"] + out["fx"]
    return out.dropna()


def fx_variance_share(d: pd.DataFrame) -> float:
    """Share of the PLN variance coming from the currency: cov(pln, fx) / var(pln). NaN if there is no variance."""
    var = d["pln"].var()
    if len(d) < 3 or not var or np.isnan(var):
        return float("nan")
    return float(d["pln"].cov(d["fx"]) / var)


def summarise(d: pd.DataFrame, last_years: float = 3.0) -> dict:
    """Key numbers of one decomposition: annual volatilities, correlation and FX variance share."""
    recent = d[d.index >= d.index.max() - pd.DateOffset(years=int(last_years))]
    ann = np.sqrt(TRADING_DAYS)
    return {
        "n_obs": len(d),
        "vol_local_ann": float(d["local"].std() * ann),
        "vol_fx_ann": float(d["fx"].std() * ann),
        "vol_pln_ann": float(d["pln"].std() * ann),
        "corr_local_fx": float(d["local"].corr(d["fx"])) if d["fx"].std() > 0 else float("nan"),
        "fx_share_full": fx_variance_share(d),
        "fx_share_last3y": fx_variance_share(recent),
    }


def simple_from_log(log_returns: pd.DataFrame | pd.Series):
    """Simple return = exp(log return) - 1 (what a portfolio adds up across assets)."""
    return np.expm1(log_returns)
