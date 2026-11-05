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
4. The first ETF of a class (its core holding) is the one with the BROADEST scope (``broad`` before ``regional``,
   an equity-only field of the universe file), then the most REPRESENTATIVE one: the medoid with the highest average
   correlation with all the other eligible ETFs of the class. Scope comes first because with only two ETFs in a
   class representativeness is symmetric (a tie) and would be decided by the id: in the first real backtest this made
   an emerging-markets ETF the core of the equity class for years. Then, one by one, the group whose medoid has the LOWEST maximum
   correlation with the ETFs already chosen (maximin diversification). A class keeps at most ``max_etfs`` ETFs.
   The order matters: the first ETF is the class's core holding (it keeps the larger share of the class budget,
   see ``secondary_share`` in config/portfolio.yaml).
5. Stability (only when the choice is repeated in time, stage 06): an ETF already held ("incumbent") keeps its place
   unless a challenger is better by more than ``switch_margin`` (in correlation units, 0.10). Inside a group of the
   same exposure the incumbent always represents the group. This avoids selling and re-buying (and paying tax) for
   differences that are noise. The rule never looks at returns.
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
    switch_margin: float = 0.10              # 0 switches the stability rule off

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


def _core_reason(a: str, rep: dict[str, float], scope_rank: dict[str, int] | None, ids: list[str]) -> str:
    broad = [x for x in ids if (scope_rank or {}).get(x, 1) == 0]
    base = f"average corr with the others {rep[a]:.2f}"
    if scope_rank and a in broad and len(broad) < len(ids):
        return f"core: broadest scope of the class, then most representative ({base})"
    return f"most representative of the class ({base})"


def _pick_class(corr: pd.DataFrame, rules: ChoiceRules, limit: int, incumbents: list[str] | None = None,
                scope_rank: dict[str, int] | None = None):
    """Cluster, take medoids, order them. Returns (chosen ids in order, {id: reason})."""
    ids = list(corr.index)
    reasons: dict[str, str] = {}
    if len(ids) == 1:
        return ids, {ids[0]: "only eligible ETF of its class"}
    margin = rules.switch_margin
    inc = [a for a in (incumbents or []) if a in ids] if margin > 0 else []
    dist = (1.0 - corr.values).clip(min=0)
    dist = (dist + dist.T) / 2
    np.fill_diagonal(dist, 0.0)
    labels = fcluster(linkage(squareform(dist, checks=False), "average"), t=1.0 - rules.rho_max, criterion="distance")
    groups: dict[int, list[str]] = {}
    for a, g in zip(ids, labels):
        groups.setdefault(int(g), []).append(a)

    def centrality(a: str, members: list[str]) -> float:
        return float(corr.loc[a, members].drop(a).mean()) if len(members) > 1 else 1.0

    medoid: dict[int, str] = {}
    for g, members in groups.items():
        held = [a for a in members if a in inc]
        pool = held or members                          # an incumbent always represents its group
        medoid[g] = sorted(pool, key=lambda a: (-centrality(a, members), a))[0]
        for a in members:
            if a != medoid[g]:
                how = "incumbent kept" if held else "less central"
                reasons[a] = f"same exposure as {medoid[g]} (corr {corr.loc[a, medoid[g]]:.2f} >= {rules.rho_max:.2f}), {how}"

    rep = {a: float(corr.loc[a].drop(a).mean()) for a in ids}          # average correlation with the whole class
    remaining = dict(groups)
    chosen: list[str] = []
    sr = lambda a: (scope_rank or {}).get(a, 1)         # noqa: E731  broad 0, unknown 1, regional 2
    ranked = sorted(remaining, key=lambda g: (sr(medoid[g]), -rep[medoid[g]], medoid[g]))
    first = ranked[0]
    core = inc[0] if inc else None                      # the previous core ETF of the class
    if core is not None:
        g_core = next((g for g, members in groups.items() if core in members), None)
        if (g_core is not None and sr(medoid[g_core]) <= sr(medoid[first])
                and rep[medoid[g_core]] >= rep[medoid[first]] - margin):
            first = g_core
    chosen.append(medoid[first])
    kept = medoid[first] in inc and medoid[first] != medoid[ranked[0]]
    reasons[medoid[first]] = (f"incumbent core kept: {medoid[ranked[0]]} is better by less than {margin:.2f}" if kept
                              else _core_reason(medoid[first], rep, scope_rank, ids))
    del remaining[first]
    while remaining and len(chosen) < limit:
        score = {g: float(corr.loc[medoid[g], chosen].abs().max()) for g in remaining}
        best = sorted(remaining, key=lambda g: (score[g], medoid[g]))[0]
        keep = sorted((g for g in remaining if medoid[g] in inc and score[g] <= score[best] + margin),
                      key=lambda g: (score[g], medoid[g]))
        pick = keep[0] if keep else best
        m = medoid[pick]
        if pick != best:
            reasons[m] = (f"incumbent kept: {medoid[best]} is more different by less than {margin:.2f} "
                          f"(max corr {score[pick]:.2f} vs {score[best]:.2f})")
        else:
            reasons[m] = f"most different from {', '.join(chosen)} (max corr {corr.loc[m, chosen].max():.2f})"
        chosen.append(m)
        del remaining[pick]
    for g in remaining:
        m = medoid[g]
        reasons[m] = f"class already has {limit} ETF(s); closest to chosen ones (max corr {corr.loc[m, chosen].max():.2f})"
    return chosen, reasons


def choose_etfs(returns: pd.DataFrame, pln_returns: pd.DataFrame, meta: pd.DataFrame, rules: ChoiceRules,
                incumbents: list[str] | None = None) -> pd.DataFrame:
    """Return one row per asset in ``meta``: asset_class, decision (chosen / cash / rejected), reason.

    ``returns`` = daily returns used for similarity (local currency, so that EUR/PLN does not make every
    euro asset look alike); ``pln_returns`` = used only to find the cash-like ETF with the lowest PLN volatility.
    ``incumbents`` = ETFs held now, core first (stability rule); ``None`` for a one-off choice.
    """
    meta = meta.copy()
    why = eligibility(meta, rules)
    decision = pd.Series("rejected", index=meta.index, dtype=object)
    reason = why.copy()
    order = pd.Series(0, index=meta.index)

    scope_rank = {a: {"broad": 0, "regional": 2}.get(str(meta.loc[a].get("scope")), 1) for a in meta.index} \
        if "scope" in meta.columns else None
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
        chosen, reasons = _pick_class(corr, rules, rules.limit(cls), incumbents, scope_rank)
        for a, text in reasons.items():
            reason[a] = text
        for i, a in enumerate(chosen, start=1):
            decision[a] = "chosen"
            order[a] = i
    out = pd.DataFrame({"asset_class": meta["asset_class"], "decision": decision, "order": order, "reason": reason})
    return out.reset_index(names="asset_id")
