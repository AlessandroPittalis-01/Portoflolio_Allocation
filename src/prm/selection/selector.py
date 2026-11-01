"""Pick the best candidate of each category, using CRITERIA ONLY.

Golden rule (IPS section 3): **performance is never used.** No returns, no Sharpe, no
backtest. Only facts that can be checked on a factsheet or in the data-quality report:
can we use the data, does it pay out income, what does it cost, how long is the history.

Why: choosing the ETF that "did best" in the past is data snooping. It would make the
later backtest look better than it really is.

Ranking inside a category (first rule that differs decides; the order is fixed in advance)
-------------------------------------------------------------------------------------------
0. Eligibility (hard): data downloaded, status not "error", history >= min_history_years.
1. Accumulating share class first (Belka tax is deferred, see IPS). Unknown ranks last.
2. Quote currency equal to the preferred listing currency (EUR).
3. Fewer data-quality warnings.
4. Lower TER. Differences smaller than TER_TIE_PP count as a tie (sources disagree by that much).
5. Longer history.
6. Asset id (alphabetical), only to make the result reproducible.

Fund size is NOT used yet: we have no verified figures (aggregators disagree by a factor 4).
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from prm.data.universe import Asset

TER_TIE_PP = 0.05      # TER differences below this (in percentage points) are treated as equal
CORR_WARNING = 0.95    # selected pairs more correlated than this are almost the same exposure
USABLE_STATUSES = ("ok", "warning")


@dataclass(frozen=True)
class Candidate:
    asset: Asset
    status: str
    currency: str | None
    history_years: float
    n_warnings: int


def _n_warnings(issues) -> int:
    """Number of flags in the 'issues' text of the quality report ('a; b' -> 2)."""
    if not isinstance(issues, str) or not issues.strip():
        return 0
    return len([part for part in issues.split(";") if part.strip()])


def build_candidates(assets: list[Asset], report: pd.DataFrame) -> list[Candidate]:
    """Join the universe with the stage-01 quality report (one row per asset)."""
    rows = report.set_index("asset_id")
    out = []
    for asset in assets:
        if asset.id in rows.index:
            r = rows.loc[asset.id]
            history = r.get("history_years")
            out.append(
                Candidate(
                    asset=asset,
                    status=str(r["status"]),
                    currency=r.get("currency") if isinstance(r.get("currency"), str) else None,
                    history_years=0.0 if pd.isna(history) else float(history),
                    n_warnings=_n_warnings(r.get("issues")),
                )
            )
        else:
            out.append(Candidate(asset, "not_downloaded", None, 0.0, 0))
    return out


def exclusion_reason(c: Candidate, min_history_years: float) -> str | None:
    """Why a candidate cannot be chosen at all, or ``None`` if it is eligible."""
    if c.status not in USABLE_STATUSES:
        return f"no usable data ({c.status})"
    if c.history_years < min_history_years:
        return f"history {c.history_years:.1f}y < {min_history_years:g}y"
    return None


def _ter_bucket(ter: float | None) -> float:
    """Group TERs that differ by less than TER_TIE_PP; unknown TER ranks after every known one."""
    return float("inf") if ter is None else round(ter / TER_TIE_PP)


def rank_key(c: Candidate, preferred_currency: str):
    """Sort key: smaller is better. Mirrors the ranking rules in the module docstring."""
    acc_rank = {True: 0, None: 1, False: 2}[c.asset.accumulating]
    currency_rank = 0 if (c.currency or "").upper() == preferred_currency.upper() else 1
    return (acc_rank, currency_rank, c.n_warnings, _ter_bucket(c.asset.ter_pct), -c.history_years, c.asset.id)


def select_per_category(candidates: list[Candidate], criteria: dict) -> pd.DataFrame:
    """Return one row per candidate with its rank in the category and a ``selected`` flag."""
    min_history = float(criteria.get("min_history_years", 0))
    currency = str(criteria.get("listing_currency", "EUR"))

    rows = []
    for category in sorted({c.asset.category for c in candidates}):
        group = [c for c in candidates if c.asset.category == category]
        eligible = sorted((c for c in group if exclusion_reason(c, min_history) is None),
                          key=lambda c: rank_key(c, currency))
        rank_of = {c.asset.id: i + 1 for i, c in enumerate(eligible)}
        for c in group:
            reason = exclusion_reason(c, min_history)
            rows.append({
                "category": category,
                "asset_id": c.asset.id,
                "symbol": c.asset.yahoo_symbol or "",
                "tier": c.asset.tier,
                "rank": rank_of.get(c.asset.id),
                "selected": rank_of.get(c.asset.id) == 1,
                "accumulating": c.asset.accumulating,
                "currency": c.currency or "",
                "n_warnings": c.n_warnings,
                "ter_pct": c.asset.ter_pct,
                "history_years": c.history_years,
                "n_candidates": len(group),
                "excluded_because": reason or "",
            })
    return pd.DataFrame(rows)


def explain_choice(table: pd.DataFrame, category: str) -> str:
    """One plain sentence on why the winner of a category won (or why there is no winner)."""
    group = table[table["category"] == category].sort_values("rank")
    winner = group[group["selected"]]
    if winner.empty:
        return "no eligible candidate"
    w = winner.iloc[0]
    if len(group) == 1:
        return "only candidate"
    others = group[(group["rank"].notna()) & (~group["selected"])]
    if others.empty:
        return "the others are excluded (see excluded_because)"
    r = others.iloc[0]
    if w["accumulating"] == True and r["accumulating"] != True:  # noqa: E712 (pandas may hold numpy bools)
        return "accumulating share class"
    if w["currency"] == "EUR" and r["currency"] != "EUR":
        return "EUR listing"
    if w["n_warnings"] < r["n_warnings"]:
        return "fewer data-quality warnings"
    if _ter_bucket(w["ter_pct"] if pd.notna(w["ter_pct"]) else None) < _ter_bucket(r["ter_pct"] if pd.notna(r["ter_pct"]) else None):
        return "lower TER"
    if w["history_years"] > r["history_years"]:
        return "longer history (TER is a tie)"
    return "tie on all criteria: alphabetical order (look at it by hand)"


def high_correlation_pairs(returns: pd.DataFrame, threshold: float = CORR_WARNING) -> list[tuple[str, str, float]]:
    """Pairs of columns whose daily-return correlation exceeds ``threshold`` (almost the same exposure)."""
    corr = returns.corr()
    pairs = []
    cols = list(corr.columns)
    for i, a in enumerate(cols):
        for b in cols[i + 1:]:
            value = corr.loc[a, b]
            if pd.notna(value) and value > threshold:
                pairs.append((a, b, float(value)))
    return sorted(pairs, key=lambda t: -t[2])
