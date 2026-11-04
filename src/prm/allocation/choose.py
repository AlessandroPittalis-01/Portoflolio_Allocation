"""Rule-based choice of the ETFs inside each asset class (IPS decision 26).

The owner fixes the CLASSES and their risk budgets; this module decides WHICH ETFs represent each class, with
rules written before looking at any result. No performance (mean return, Sharpe, drawdown) is ever used.

Rules, in order
1. Eligibility (hard). An ETF is a candidate only if it is: ``core`` in the universe file, the winner of its
   category in stage 02, quoted in the portfolio currency (EUR), with usable data and enough history.
2. Cash. The cash-like ETF is the eligible one with the LOWEST volatility in PLN (it is used only to scale risk).
3. Inside each risky class, similarity is measured by correlation of the daily returns on the class's common
   window. ETFs with correlation >= ``rho_max`` are the SAME exposure: they are grouped (average-linkage
   clustering) and only the most central one (medoid: highest average correlation with its group) can enter.
4. The groups are ranked: the largest group first (the most representative exposure of the class), then, one by
   one, the group whose medoid has the LOWEST maximum correlation with the ETFs already chosen (maximin
   diversification). A class keeps at most ``max_etfs`` ETFs.
Ties are broken by the ETF id, so the result is deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy.cluster.hierarchy import fcluster, linkage
from scipy.spatial.distance import squareform

RISKY_CLASSES = ("equity", "bond", "real")


@dataclass(frozen=True)
class ChoiceRules:
    rho_max: float = 0.90
    max_etfs: dict[str, int] = None          # type: ignore[assignment]
    min_overlap_days: int = 500
    min_history_years: float = 5.0
    currency: str = "EUR"

    def limit(self, asset_class: str) -> int:
        return int((self.max_etfs or {}).get(asset_class, 1))


def eligibility(meta: pd.DataFrame, rules: ChoiceRules) -> pd.Series:
    """Reason why each asset cannot be chosen ('' = eligible). ``meta`` is indexed by asset id."""
    out = {}
    for a, r in meta.iterrows():
        if not bool(r.get("core", False)):
            out[a] = "not core (policy: broad, EUR-based index only)"
        elif not bool(r.get("selected", False)):
            out[a] = "lost its category in stage 02"
        elif str(r.get("currency", "")).upper() != rules.currency.upper():
            out[a] = f"quoted in {r.get('currency') or '?'}, not {rules.currency}"
        elif str(r.get("excluded_because", "") or "") not in ("", "nan"):
            out[a] = str(r["excluded_because"])
        elif float(r.get("history_years", 0) or 0) < rules.min_history_years:
            out[a] = f"history {float(r.get('history_years', 0)):.1f}y < {rules.min_history_years:g}y"
        elif r.get("asset_class") not in ("equity", "bond", "real", "cash"):
            out[a] = "no asset class"
        else:
            out[a] = ""
    return pd.Series(out, dtype=object)


def _trim_to_overlap(returns: pd.DataFrame, ids: list[str], meta: pd.DataFrame, min_days: int):
    """Drop the shortest-history ETF until the common window has ``min_days`` rows. Returns (window, ids, dropped)."""
    ids = list(ids)
    dropped: list[str] = []
    while True:
        window = returns[ids].dropna()
        if len(window) >= min_days or len(ids) <= 1:
            return window, ids, dropped
        worst = min(ids, key=lambda a: (float(meta.loc[a, "history_years"]), a))
        ids.remove(worst)
        dropped.append(worst)


def _pick_class(corr: pd.DataFrame, rules: ChoiceRules, limit: int):
    """Cluster, take medoids, order them. Returns (chosen ids in order, {id: reason})."""
    ids = list(corr.index)
    reasons: dict[str, str] = {}
    if len(ids) == 1:
        return ids, {ids[0]: "only eligible ETF of its class"}
    dist = (1.0 - corr.values).clip(min=0)
    dist = (dist + dist.T) / 2
    np.fill_diagonal(dist, 0.0)
    labels = fcluster(linkage(squareform(dist, checks=False), "average"), t=1.0 - rules.rho_max, criterion="distance")
    groups: dict[int, list[str]] = {}
    for a, g in zip(ids, labels):
        groups.setdefault(int(g), []).append(a)

    medoid: dict[int, str] = {}
    for g, members in groups.items():
        score = {a: (corr.loc[a, members].drop(a).mean() if len(members) > 1 else 1.0, ) for a in members}
        medoid[g] = sorted(members, key=lambda a: (-score[a][0], a))[0]
        for a in members:
            if a != medoid[g]:
                reasons[a] = f"same exposure as {medoid[g]} (corr {corr.loc[a, medoid[g]]:.2f} >= {rules.rho_max:.2f}), less central"

    remaining = dict(groups)
    chosen: list[str] = []
    first = sorted(remaining, key=lambda g: (-len(remaining[g]), medoid[g]))[0]
    chosen.append(medoid[first])
    reasons[medoid[first]] = (f"most representative exposure of the class (group of {len(groups[first])})"
                              if len(groups[first]) > 1 else "first choice: only group of its size, lowest id")
    del remaining[first]
    while remaining and len(chosen) < limit:
        best = sorted(remaining, key=lambda g: (corr.loc[medoid[g], chosen].abs().max(), medoid[g]))[0]
        m = medoid[best]
        reasons[m] = f"most different from {', '.join(chosen)} (max corr {corr.loc[m, chosen].max():.2f})"
        chosen.append(m)
        del remaining[best]
    for g in remaining:
        m = medoid[g]
        reasons[m] = f"class already has {limit} ETF(s); closest to chosen ones (max corr {corr.loc[m, chosen].max():.2f})"
    return chosen, reasons


def choose_etfs(returns: pd.DataFrame, pln_returns: pd.DataFrame, meta: pd.DataFrame, rules: ChoiceRules) -> pd.DataFrame:
    """Return one row per asset in ``meta``: asset_class, decision (chosen / cash / rejected), reason.

    ``returns`` = daily returns used for similarity (local currency, so that EUR/PLN does not make every
    euro asset look alike); ``pln_returns`` = used only to find the cash-like ETF with the lowest PLN volatility.
    """
    meta = meta.copy()
    why = eligibility(meta, rules)
    decision = pd.Series("rejected", index=meta.index, dtype=object)
    reason = why.copy()
    order = pd.Series(0, index=meta.index)

    avail = {a for a in meta.index if a in returns.columns}
    for a in meta.index:
        if why[a] == "" and a not in avail:
            reason[a] = "no returns in the stage-03 file"
    eligible = [a for a in meta.index if why[a] == "" and a in avail]

    # ---- cash: lowest PLN volatility ------------------------------------------------------------
    cash = [a for a in eligible if meta.loc[a, "asset_class"] == "cash" and a in pln_returns.columns]
    if cash:
        vol = {a: float(pln_returns[a].dropna().std()) for a in cash}
        best = sorted(cash, key=lambda a: (vol[a], a))[0]
        decision[best], reason[best] = "cash", f"lowest PLN volatility among cash-like ETFs ({vol[best] * np.sqrt(252):.1%})"
        for a in cash:
            if a != best:
                reason[a] = f"cash-like ETF with higher PLN volatility ({vol[a] * np.sqrt(252):.1%})"

    # ---- risky classes ------------------------------------------------------------------------------
    for cls in RISKY_CLASSES:
        ids = [a for a in eligible if meta.loc[a, "asset_class"] == cls]
        if not ids:
            continue
        window, kept, dropped = _trim_to_overlap(returns, ids, meta, rules.min_overlap_days)
        for a in dropped:
            reason[a] = f"common window with the class would be < {rules.min_overlap_days} days"
        if len(window) < rules.min_overlap_days:
            for a in kept:
                reason[a] = f"common window of the class has only {len(window)} days"
            continue
        corr = window.corr()
        chosen, reasons = _pick_class(corr, rules, rules.limit(cls))
        for a, text in reasons.items():
            reason[a] = text
        for i, a in enumerate(chosen, start=1):
            decision[a] = "chosen"
            order[a] = i
    out = pd.DataFrame({"asset_class": meta["asset_class"], "decision": decision, "order": order, "reason": reason})
    return out.reset_index(names="asset_id")
