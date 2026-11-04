"""Risk budgets by asset class.

The IPS fixes how much of the portfolio RISK each class may carry (for example equity 50%, bonds 35%, gold 15%).
Inside a class the budget is split equally among the ETFs of that class that are in the portfolio, so adding a
second equity ETF does not raise the equity risk: it only shares it.
"""

from __future__ import annotations

import pandas as pd


def asset_budgets(roles: dict[str, str], class_budgets: dict[str, float]) -> pd.Series:
    """Turn class budgets into one budget per ETF.

    ``roles`` maps ETF id -> class. Classes without budget (for example "cash") are not allowed here; classes
    in ``class_budgets`` that have no ETF are dropped and the rest is rescaled, so the budgets add up to 1.
    """
    if any(v <= 0 for v in class_budgets.values()):
        raise ValueError("class budgets must be positive")
    missing = sorted({r for r in roles.values()} - set(class_budgets))
    if missing:
        raise ValueError(f"no risk budget for the classes: {missing}")
    count = pd.Series(roles).value_counts()
    out = pd.Series({a: class_budgets[r] / count[r] for a, r in roles.items()}, dtype=float)
    return out / out.sum()
