"""Summary numbers of one simulated strategy."""

from __future__ import annotations

import numpy as np
import pandas as pd

from prm.backtest.simulate import SimResult, irr
from prm.config import Profile
from prm.risk.metrics import TRADING_DAYS, drawdown_series, hist_var_es, max_drawdown


def summarise(sim: SimResult, profile: Profile) -> dict:
    r = sim.twr.iloc[1:] if len(sim.twr) > 1 else sim.twr
    r = r[sim.value.reindex(r.index) > 0]
    n = len(r)
    years = n / TRADING_DAYS if n else float("nan")
    wealth = float((1 + r).prod()) if n else float("nan")
    dd = drawdown_series(r) if n else pd.Series(dtype=float)
    _, es95 = hist_var_es(r, 0.95) if n > 20 else (float("nan"), float("nan"))
    sold = float(sim.trades["sold"].sum()) if len(sim.trades) else 0.0          # turnover = money SOLD (contributions are not turnover)
    avg_value = float(sim.value[sim.value > 0].mean()) if (sim.value > 0).any() else float("nan")
    final = float(sim.value.iloc[-1])
    return {
        "start": r.index.min().date() if n else None,
        "years": years,
        "twr_ann": wealth ** (1 / years) - 1 if n else float("nan"),
        "irr_ann": irr(sim.contributions, final, sim.value.index[-1]),
        "vol_ann": float(r.std() * np.sqrt(TRADING_DAYS)) if n > 1 else float("nan"),
        "max_dd": max_drawdown(r)["max_dd"] if n else float("nan"),
        "es95_daily": es95,
        "days_below_alert_pct": float((dd <= profile.dd_alert).mean()) if n else float("nan"),
        "days_below_review_pct": float((dd <= profile.dd_review).mean()) if n else float("nan"),
        "contributed_pln": float(sim.contributions.sum()),
        "final_value_pln": final,
        "costs_pln": float(sim.trades["cost"].sum()) if len(sim.trades) else 0.0,
        "turnover_ann": sold / avg_value / years if n and avg_value > 0 else float("nan"),
        "months_with_sales": int((sim.trades["n_sold"] > 0).sum()) if len(sim.trades) else 0,
    }
