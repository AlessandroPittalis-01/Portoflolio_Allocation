"""Risk budgets by asset class.

The IPS fixes how much of the portfolio RISK each class may carry (for example equity 50%, bonds 35%, gold 15%).
Inside a class the budget is split among the ETFs of that class that are in the portfolio:
* by default equally, so adding a second ETF does not raise the class risk: it only shares it;
* if ``secondary_share[class]`` = s is given, the FIRST ETF of the class (the core holding, first in ``roles``)
  keeps 1 - s of the class budget and the other ETFs of the class share s equally. Used for equity, where the
  second ETF (emerging markets) is already partly inside the global ETF and must stay a small tilt.
"""

from __future__ import annotations

import pandas as pd


def asset_budgets(roles: dict[str, str], class_budgets: dict[str, float],
                  secondary_share: dict[str, float] | None = None) -> pd.Series:
    """Turn class budgets into one budget per ETF.

    ``roles`` maps ETF id -> class, in order of choice (the first ETF of each class is its core holding).
    Classes without budget (for example "cash") are not allowed here; classes in ``class_budgets`` that have
    no ETF are dropped and the rest is rescaled, so the budgets add up to 1.
    """
    secondary_share = secondary_share or {}
    if any(v <= 0 for v in class_budgets.values()):
        raise ValueError("class budgets must be positive")
    if any(not 0 < v < 1 for v in secondary_share.values()):
        raise ValueError("secondary_share must be strictly between 0 and 1")
    missing = sorted({r for r in roles.values()} - set(class_budgets))
    if missing:
        raise ValueError(f"no risk budget for the classes: {missing}")
    count = pd.Series(roles).value_counts()
    seen: dict[str, int] = {}
    out = {}
    for a, r in roles.items():
        k = seen.get(r, 0)
        seen[r] = k + 1
        s = secondary_share.get(r)
        if s is None or count[r] == 1:
            out[a] = class_budgets[r] / count[r]
        elif k == 0:
            out[a] = class_budgets[r] * (1 - s)
        else:
            out[a] = class_budgets[r] * s / (count[r] - 1)
    out = pd.Series(out, dtype=float)
    return out / out.sum()
