"""Model of an EUR/PLN hedge for a PLN investor holding EUR-quoted ETFs (IPS decision 38).

What this is: a SIMULATION of the hedge from returns already in the project, with assumed carry and cost.
What this is not: a real instrument. A Polish retail investor cannot easily buy PLN-hedged UCITS ETFs
(hedged share classes exist mainly for EUR/USD/GBP); the real routes (forwards, FX futures, CFDs, a
PLN-hedged fund) have margins, taxes and limits that are NOT modelled here. The study answers a prior
question: how much risk would the hedge remove, and what would it cost, if it were possible?
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import yaml

TRADING_DAYS = 252
DEFAULT_HEDGE_PATH = Path(__file__).resolve().parents[3] / "config" / "fx_hedge.yaml"
CLASSES = ("equity", "bond", "real")


class HedgeConfigError(ValueError):
    pass


def load_hedge_config(path: Path | str = DEFAULT_HEDGE_PATH) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    carry = cfg.get("carry_annual")
    cost = cfg.get("cost_annual")
    scen = cfg.get("scenarios")
    if not isinstance(carry, list) or not carry or not all(isinstance(c, (int, float)) for c in carry):
        raise HedgeConfigError("carry_annual must be a non-empty list of numbers")
    if not isinstance(cost, (int, float)) or cost < 0:
        raise HedgeConfigError("cost_annual must be a number >= 0")
    if not isinstance(scen, dict) or not scen:
        raise HedgeConfigError("scenarios must be a non-empty mapping")
    for name, ratios in scen.items():
        if not isinstance(ratios, dict) or set(ratios) != set(CLASSES):
            raise HedgeConfigError(f"scenario '{name}' needs exactly the classes {CLASSES}")
        for cls, h in ratios.items():
            if not isinstance(h, (int, float)) or not 0.0 <= h <= 1.0:
                raise HedgeConfigError(f"scenario '{name}', class {cls}: hedge ratio must be between 0 and 1")
    return {"carry_annual": [float(c) for c in carry], "cost_annual": float(cost), "scenarios": scen}


def fx_component(pln: pd.DataFrame, local: pd.DataFrame) -> pd.DataFrame:
    """Daily simple FX return of each asset: (1 + pln) / (1 + local) - 1."""
    cols = [c for c in pln.columns if c in local.columns]
    return (1 + pln[cols]) / (1 + local[cols]) - 1


def daily_net_carry(carry_annual: float, cost_annual: float) -> float:
    """Daily carry earned by the hedge after cost (simple, flat over the whole period)."""
    return (carry_annual - cost_annual) / TRADING_DAYS


def hedge_ratios(meta: pd.DataFrame, ratios_by_class: dict[str, float], columns) -> pd.Series:
    """Hedge ratio of each asset from its class; classes not listed (cash, unknown) are not hedged."""
    cls = meta["asset_class"].reindex(list(columns))
    return cls.map(ratios_by_class).fillna(0.0).astype(float)


def hedged_pln_returns(pln: pd.DataFrame, local: pd.DataFrame, ratios: pd.Series, net_carry_daily: float) -> pd.DataFrame:
    """PLN returns of every asset after hedging a share ``ratios`` of its EUR exposure.

    Simplification (stated): the hedge notional follows the position value every day, so there is no
    cross term between the hedge P&L and the local return. h = 0 gives back ``pln`` exactly.
    """
    fx = fx_component(pln, local)
    h = ratios.reindex(fx.columns).fillna(0.0)
    out = (1 + local[fx.columns]) * (1 + (1 - h) * fx + h * net_carry_daily) - 1
    return out.where(pln[fx.columns].notna())


def hedge_effect(weights: pd.Series, ratios: pd.Series, carry_annual: float, cost_annual: float) -> dict:
    """Size of the hedge for one portfolio: notional (share of the portfolio value hedged) and the yearly
    effect of carry minus cost on the portfolio return (an ASSUMPTION times the notional, not a forecast)."""
    h = ratios.reindex(weights.index).fillna(0.0)
    notional = float((weights * h).sum())
    return {"hedged_notional": notional, "carry_minus_cost_pa": notional * (carry_annual - cost_annual)}
