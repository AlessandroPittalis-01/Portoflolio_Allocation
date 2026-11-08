"""Monitoring report: put the numbers of the earlier stages next to the limits (IPS decision 42).

Pure functions (no file access) so that they can be tested with small synthetic tables. The pipeline script
``pipeline/14_report.py`` reads the CSV files and calls ``build_checks`` and ``render_markdown``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from prm.config import Profile
from prm.risk.limits import AMBER, GREEN, NA, RED, Limit, drawdown_status, evaluate, worst_status, zone_status

REFERENCE_MODEL = "fhs_ewma"        # IPS decision 40
REFERENCE_LEVEL = 0.99


def current_drawdown(twr: pd.Series) -> tuple[float, float]:
    """(current drawdown, maximum drawdown) of a daily time-weighted return series; both <= 0."""
    r = twr.dropna()
    if r.empty:
        return float("nan"), float("nan")
    wealth = (1 + r).cumprod()
    dd = wealth / wealth.cummax() - 1
    return float(dd.iloc[-1]), float(dd.min())


def class_risk_gap(risk_shares: pd.Series, classes: dict[str, str], budgets: dict[str, float]) -> pd.Series:
    """Absolute gap between the realised risk share of each class and its budget, both on the risky part only.

    ``risk_shares`` is indexed by ETF id, ``classes`` maps ETF id -> asset class; ``cash`` is excluded and the
    remaining shares are rescaled to 1. A class with budget but no ETF counts as share 0.
    """
    s = risk_shares.copy()
    cls = pd.Series({a: classes.get(a) for a in s.index})
    s = s[cls != "cash"]
    cls = cls[s.index]
    by_class = s.groupby(cls).sum()
    total = by_class.sum()
    if total <= 0:
        return pd.Series(dtype=float)
    by_class = by_class / total
    b = pd.Series(budgets, dtype=float)
    b = b / b.sum()
    return (by_class.reindex(b.index).fillna(0.0) - b).abs()


def build_checks(limits: dict[str, Limit], profile: Profile, *, summary_row: pd.Series | None, weights: pd.Series | None,
                 class_gap: pd.Series | None, var_table: pd.DataFrame | None, var_backtest: pd.DataFrame | None,
                 hypothetical: pd.DataFrame | None, twr: pd.Series | None) -> pd.DataFrame:
    """One row per check: id, label, value, limit text, status, origin (decided / proposed / profile)."""
    rows = []

    def add(cid, label, value, text, status, origin):
        rows.append({"id": cid, "label": label, "value": value, "limit": text, "status": status, "origin": origin})

    L = limits
    vol = None if summary_row is None else float(summary_row["vol_model"])
    lim = L["portfolio_vol"]
    add(lim.id, lim.label, vol, f"{lim.lower:.0%} - {lim.upper:.0%}", evaluate(vol, lim.lower, lim.upper, lim.amber_margin), lim.status)

    fx = None if summary_row is None else float(summary_row["fx_share"])
    lim = L["fx_share"]
    add(lim.id, lim.label, fx, f"<= {lim.upper:.0%}", evaluate(fx, None, lim.upper, lim.amber_margin), lim.status)

    eq = None if summary_row is None else float(summary_row["equity_w"])
    add("equity_cap", "Equity weight", eq, f"<= {profile.equity_cap:.0%}", evaluate(eq, None, profile.equity_cap, 0.03), "profile")

    mw = None if summary_row is None else float(summary_row["max_weight"])    # stage 05 excludes the cash-like ETF
    add("max_weight", "Largest weight of a risky ETF", mw, f"<= {profile.max_weight_per_etf:.0%}",
        evaluate(mw, None, profile.max_weight_per_etf, 0.03), "profile")

    gap = None if class_gap is None or class_gap.empty else float(class_gap.max())
    lim = L["class_risk_share"]
    add(lim.id, lim.label, gap, f"<= {lim.upper:.0%} points", evaluate(gap, None, lim.upper, lim.amber_margin), lim.status)

    var = None
    if var_table is not None and len(var_table):
        sel = var_table[(var_table["model"] == REFERENCE_MODEL) & (np.isclose(var_table["level"], REFERENCE_LEVEL))]
        var = float(sel["var"].iloc[0]) if len(sel) else None
    lim = L["var99_1d"]
    add(lim.id, lim.label, var, f"<= {lim.upper:.2%}", evaluate(var, None, lim.upper, lim.amber_margin), lim.status)

    zone = None
    if var_backtest is not None and len(var_backtest):
        sel = var_backtest[(var_backtest["model"] == REFERENCE_MODEL) & (np.isclose(var_backtest["level"], REFERENCE_LEVEL))]
        zone = str(sel["zone"].iloc[0]) if len(sel) else None
    lim = L["var_model_zone"]
    add(lim.id, lim.label, zone, "green", zone_status(zone), lim.status)

    worst = None
    if hypothetical is not None and len(hypothetical):
        worst = float(hypothetical["portfolio_move"].min())
    lim = L["worst_hypothetical"]
    add(lim.id, lim.label, worst, f">= {profile.stop_contributing_dd:.0%}",
        evaluate(worst, profile.stop_contributing_dd, None, lim.amber_margin), lim.status)

    cur = mx = None
    if twr is not None and len(twr):
        cur, mx = current_drawdown(twr)
    add("drawdown_now", "Current drawdown (backtest series, time-weighted)", cur,
        f"alert {profile.dd_alert:.0%} / review {profile.dd_review:.0%} / stop {profile.stop_contributing_dd:.0%}",
        drawdown_status(cur, profile.dd_alert, profile.dd_review, profile.stop_contributing_dd), "profile")
    add("drawdown_max", "Maximum drawdown so far (information)", mx, f"review {profile.dd_review:.0%}",
        drawdown_status(mx, profile.dd_alert, profile.dd_review, profile.stop_contributing_dd), "profile")
    return pd.DataFrame(rows)


def _fmt(cid: str, v) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "n/a"
    if isinstance(v, str):
        return v
    return f"{v:.2%}" if cid in ("var99_1d",) else f"{v:.1%}"


def render_markdown(checks: pd.DataFrame, profile: Profile, method: str, as_of: str) -> str:
    overall = worst_status(list(checks["status"]))
    lines = [f"# Risk monitoring report - profile `{profile.name}`, portfolio `{method}`", "",
             f"Data up to {as_of}. Overall status: **{overall}**.", "",
             "| Check | Value | Limit | Status | Origin |", "|---|---|---|---|---|"]
    for r in checks.itertuples():
        lines.append(f"| {r.label} | {_fmt(r.id, r.value)} | {r.limit} | {r.status} | {r.origin} |")
    lines += ["", "How to read it: GREEN = inside the limit; AMBER = inside but close (look at it, no trade);",
              "RED = outside (formal review of the IPS). No limit triggers an automatic trade.",
              "Origin `proposed` = limit suggested by the code and not yet confirmed by the owner (IPS decision 42).",
              "The drawdown rows use the backtest series, because the real account is not in the data: with real",
              "contributions the same check must be run on the real time-weighted return.", ""]
    flagged = checks[checks["status"].isin([AMBER, RED])]
    if len(flagged):
        lines.append("## To look at")
        for r in flagged.itertuples():
            lines.append(f"- {r.status}: {r.label} = {_fmt(r.id, r.value)} (limit {r.limit})")
    else:
        lines.append("Nothing to look at: every check is GREEN or N/A.")
    return "\n".join(lines) + "\n"
