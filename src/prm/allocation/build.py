"""One allocation, from data to weights: choose the ETFs, budget the risk, run every method.

Used by stage 05 (a snapshot on all the data) and by stage 06 (repeated at every rebalance date on the data
available up to that date, which is what makes the backtest walk-forward).
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

from prm.allocation.budgets import asset_budgets
from prm.allocation.choose import ChoiceRules, choose_etfs
from prm.allocation.spec import PortfolioSpec
from prm.allocation.targeting import enforce_limits, portfolio_vol, scale_to_target_vol
from prm.allocation.weights import (
    cap_weights, equal_weight, hrp, inverse_vol, min_variance, risk_budget, risk_parity,
)
from prm.config import Profile
from prm.risk.covariance import annualise, common_window, ewma_cov, ledoit_wolf, sample_cov

METHODS = ("equal_weight", "inverse_vol", "risk_parity", "risk_budget", "min_variance", "hrp")


class AllocationError(Exception):
    """The data or the rules do not allow an allocation (reported, never hidden)."""


@dataclass
class Allocation:
    choice: pd.DataFrame                   # one row per candidate: decision and reason
    roles: dict[str, str]                  # chosen ETF (and cash) -> asset class
    cash_id: str
    ids: list[str]                         # chosen risky ETFs + cash
    all_ids: list[str]                     # ids + extra ETFs (for example the benchmark ones)
    risky_ids: list[str]
    budgets: pd.Series                     # risk budget per risky ETF
    cov: pd.DataFrame                      # annual covariance over all_ids
    weights: dict[str, pd.Series]          # method -> weights over all_ids (zero outside the chosen ETFs)
    status: dict[str, tuple[float, str]]   # method -> (risky share k, on_target / below_target / above_floor)
    pln: pd.DataFrame                      # PLN returns of the common window (all_ids)
    local: pd.DataFrame                    # local-currency returns of the same window
    missing_classes: list[str]


def estimate_cov(window: pd.DataFrame, kind: str, lam: float) -> pd.DataFrame:
    if kind == "sample":
        return sample_cov(window)
    if kind == "ewma":
        return ewma_cov(window, lam)
    return ledoit_wolf(window)[0]


def raw_weights(method: str, sleeve_cov: pd.DataFrame, max_weight: float, budgets: pd.Series) -> pd.Series:
    if method == "equal_weight":
        return equal_weight(sleeve_cov)
    if method == "inverse_vol":
        return inverse_vol(sleeve_cov)
    if method == "risk_parity":
        return risk_parity(sleeve_cov)
    if method == "risk_budget":
        return risk_budget(sleeve_cov, budgets)
    if method == "min_variance":
        return min_variance(sleeve_cov, max_weight)
    return hrp(sleeve_cov)


def allocate(pln: pd.DataFrame, local: pd.DataFrame, meta: pd.DataFrame, spec: PortfolioSpec, profile: Profile,
             cov_kind: str, extra_ids: tuple[str, ...] = (), min_window: int = 500, rules: ChoiceRules | None = None,
             lookback_days: int | None = None, methods: tuple[str, ...] = METHODS,
             incumbents: list[str] | None = None) -> Allocation:
    """Choose the ETFs with the rules, then compute the weights of every method. Raises AllocationError."""
    choice = choose_etfs(local, pln, meta, rules or spec.rules, incumbents)
    risky = choice[choice["decision"] == "chosen"].sort_values(["asset_class", "order"])
    cash_rows = choice[choice["decision"] == "cash"]
    if cash_rows.empty or not {"equity", "bond"} <= set(risky["asset_class"]):
        raise AllocationError("the choice rules left no cash-like ETF, or no equity / bond ETF")
    cash_id = str(cash_rows["asset_id"].iloc[0])
    roles = dict(zip(risky["asset_id"], risky["asset_class"]))
    roles[cash_id] = "cash"
    ids = list(roles)
    risky_ids = [a for a in ids if a != cash_id]
    budgets = asset_budgets({a: roles[a] for a in risky_ids}, spec.class_budgets, spec.secondary_share)

    all_ids = ids + [b for b in extra_ids if b not in ids]
    bad = [b for b in all_ids if b not in pln.columns or b not in local.columns]
    if bad:
        raise AllocationError(f"no returns for: {bad}")
    window = common_window(pln[all_ids])
    if lookback_days:
        window = window.tail(lookback_days)
    if len(window) < min_window:
        raise AllocationError(f"common window has only {len(window)} days (< {min_window})")
    cov = annualise(estimate_cov(window, cov_kind, spec.ewma_lambda))
    cov_ids = cov.loc[ids, ids]
    sleeve_cov = cov.loc[risky_ids, risky_ids]

    weights: dict[str, pd.Series] = {}
    status: dict[str, tuple[float, str]] = {}
    for method in methods:
        capped = cap_weights(raw_weights(method, sleeve_cov, profile.max_weight_per_etf, budgets), profile.max_weight_per_etf)
        scaled, k, st = scale_to_target_vol(capped, cov_ids, cash_id, profile.target_vol)
        final = enforce_limits(scaled, roles, profile.max_weight_per_etf, profile.equity_cap, cash_id)
        weights[method] = final.reindex(all_ids).fillna(0.0)
        status[method] = (k, st)
    missing = [c for c in spec.class_budgets if c not in set(risky["asset_class"])]
    return Allocation(choice, roles, cash_id, ids, all_ids, risky_ids, budgets, cov, weights, status,
                      window, local[all_ids].reindex(window.index), missing)


def build_meta(selection: pd.DataFrame, assets) -> pd.DataFrame:
    """Join stage-02 ``selection.csv`` with the asset class and ``core`` flag of the universe file."""
    meta = selection.set_index("asset_id").copy()
    meta["asset_class"] = {a.id: a.asset_class for a in assets}
    meta["core"] = {a.id: a.core for a in assets}
    meta["scope"] = {a.id: a.scope for a in assets}
    meta = meta[meta["asset_class"].notna()].copy()
    meta["core"] = meta["core"].astype(bool)
    meta["selected"] = meta["selected"].astype(bool)
    meta["excluded_because"] = meta["excluded_because"].fillna("")
    return meta


def equity_budget_curve(pln: pd.DataFrame, local: pd.DataFrame, meta: pd.DataFrame, spec: PortfolioSpec, profile: Profile,
                        cov_kind: str, grid: tuple[float, ...] = tuple(round(0.30 + 0.025 * i, 3) for i in range(21)),
                        min_window: int = 500, tol: float = 0.0005) -> pd.DataFrame:
    """Ex-ante rule for the equity risk budget (IPS decision 36): what does each equity risk budget give?

    For every equity budget ``e`` in ``grid`` the other classes keep their mutual proportions (bond : real = 35 : 15)
    and share ``1 - e``; the ``risk_budget`` method is run with the usual targeting and limits. The result tells which
    is the SMALLEST ``e`` whose final volatility reaches the profile target. Only the covariance is used: no returns.
    """
    others = {c: v for c, v in spec.class_budgets.items() if c != "equity"}
    total_others = sum(others.values())
    rows = []
    for e in grid:
        budgets = {"equity": e, **{c: v / total_others * (1.0 - e) for c, v in others.items()}}
        alloc = allocate(pln, local, meta, replace(spec, class_budgets=budgets), profile, cov_kind,
                         min_window=min_window, methods=("risk_budget",))
        w = alloc.weights["risk_budget"]
        k, status = alloc.status["risk_budget"]
        cls = pd.Series(alloc.roles)
        by_class = {c: float(w[[a for a in cls.index if cls[a] == c]].sum()) for c in ("equity", "bond", "real", "cash")}
        vol = portfolio_vol(w, alloc.cov)
        rows.append({"equity_risk_budget": e, "vol_model": vol, "status": status, "risky_share_k": k,
                     "equity_w": by_class["equity"], "bond_w": by_class["bond"], "real_w": by_class["real"],
                     "cash_w": by_class["cash"], "reaches_target": bool(vol >= profile.target_vol - tol)})
    return pd.DataFrame(rows)


def smallest_budget_reaching_target(curve: pd.DataFrame) -> float | None:
    """Smallest equity budget whose final volatility reaches the target, or ``None`` if none does."""
    ok = curve[curve["reaches_target"]]
    return float(ok["equity_risk_budget"].min()) if len(ok) else None
