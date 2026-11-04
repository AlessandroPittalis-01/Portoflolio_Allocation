"""Stage 05 - allocation methods under the SAME volatility target and the SAME limits.

Reads  : data/processed/returns_pln.csv, returns_local.csv (stage 03), selection.csv (stage 02),
         config/universe_candidates.yaml, config/portfolio.yaml, config/profiles.yaml
Writes : data/processed/etf_choice.csv            which ETFs were chosen in each class, and why (rules: choose.py)
         data/processed/allocation_weights.csv    final weights of each method (cash included)
         data/processed/allocation_summary.csv    one row per method: risk, limits, FX share, drawdown
         data/processed/allocation_risk_shares.csv  share of risk carried by each ETF, per method

ETF choice: the owner fixes the classes and their risk budgets (equity 50 / bond 35 / real 15, as shares of RISK);
the ETFs of each class are chosen by a mathematical rule (correlation groups, medoid, maximin), see choose.py.

Methods: equal weight, inverse volatility, risk parity (ERC), risk budget (50/35/15), minimum variance (capped), HRP.
Each gives weights for the risky ETFs; then the mix with the cash-like ETF is scaled to the profile's volatility
target (no leverage) and the profile limits are applied. The 60/40 benchmark (two fixed ETFs from config/portfolio.yaml) is shown as it is, with no targeting.

HOW TO READ THE RESULT (important)
* It is a SNAPSHOT with all the data of the common window (about 5 years, including 2022). It is in-sample.
* Volatility, drawdown and risk shares describe the shape of the portfolio. They are NOT a performance test.
  No returns are shown on purpose. The honest test is the walk-forward backtest of stage 06.

Run:  python pipeline/05_allocation.py                       (profile owner)
      python pipeline/05_allocation.py --profile prudent --cov ewma
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.allocation.budgets import asset_budgets  # noqa: E402
from prm.allocation.choose import choose_etfs  # noqa: E402
from prm.allocation.spec import DEFAULT_PORTFOLIO_PATH, load_portfolio  # noqa: E402
from prm.allocation.targeting import enforce_limits, portfolio_vol, scale_to_target_vol  # noqa: E402
from prm.allocation.weights import (  # noqa: E402
    cap_weights, equal_weight, hrp, inverse_vol, min_variance, risk_budget, risk_parity,
)
from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe  # noqa: E402
from prm.risk.contributions import risk_contributions  # noqa: E402
from prm.risk.covariance import annualise, common_window, ewma_cov, ledoit_wolf, sample_cov  # noqa: E402
from prm.risk.metrics import hist_var_es, max_drawdown  # noqa: E402

METHODS = ("equal_weight", "inverse_vol", "risk_parity", "risk_budget", "min_variance", "hrp")


def _estimate_cov(window: pd.DataFrame, kind: str, lam: float) -> pd.DataFrame:
    if kind == "sample":
        return sample_cov(window)
    if kind == "ewma":
        return ewma_cov(window, lam)
    return ledoit_wolf(window)[0]


def _raw_weights(method: str, sleeve_cov: pd.DataFrame, max_weight: float, budgets: pd.Series) -> pd.Series:
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


def _fx_share(w: pd.Series, pln: pd.DataFrame, local: pd.DataFrame) -> float:
    """Share of the portfolio's PLN variance due to the currency (fixed weights, rebalanced daily)."""
    ids = list(w.index)
    pln_p = pln[ids] @ w
    fx_p = pln_p - local[ids] @ w
    var = pln_p.var()
    return float(pln_p.cov(fx_p) / var) if var > 0 else float("nan")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 05: allocation methods.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO_PATH))
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--profile", default="owner", help="prudent, balanced, dynamic or owner")
    parser.add_argument("--cov", default="", help="sample, ewma or ledoit_wolf (default: the one in portfolio.yaml)")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    if not (processed / "returns_pln.csv").exists() or not (processed / "returns_local.csv").exists():
        print("Missing stage-03 output. Run first:  python pipeline/03_fx_returns.py")
        return 1
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Available: {sorted(profiles)}")
        return 1
    profile = profiles[args.profile]
    spec = load_portfolio(args.portfolio)
    cov_kind = args.cov or spec.covariance

    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    if not (processed / "selection.csv").exists():
        print("Missing stage-02 output. Run first:  python pipeline/02_selection.py")
        return 1
    _, assets = load_universe(args.universe)
    meta = pd.read_csv(processed / "selection.csv").set_index("asset_id")
    meta["asset_class"] = {a.id: a.asset_class for a in assets}
    meta["core"] = {a.id: a.core for a in assets}
    meta = meta[meta["asset_class"].notna()]
    meta["core"] = meta["core"].astype(bool)
    meta["selected"] = meta["selected"].astype(bool)
    meta["excluded_because"] = meta["excluded_because"].fillna("")

    # ---- which ETFs? (rules in choose.py, no performance used) ---------------------------------------
    choice = choose_etfs(local, pln, meta, spec.rules)
    choice.to_csv(processed / "etf_choice.csv", index=False)
    risky = choice[choice["decision"] == "chosen"].sort_values(["asset_class", "order"])
    cash_rows = choice[choice["decision"] == "cash"]
    missing_cls = [c for c in spec.class_budgets if c not in set(risky["asset_class"])]
    if cash_rows.empty or not {"equity", "bond"} <= set(risky["asset_class"]):
        print("The choice rules left no cash-like ETF, or no equity / bond ETF. See etf_choice.csv.")
        print(choice[choice["decision"] != "chosen"].to_string(index=False))
        return 1
    cash_id = str(cash_rows["asset_id"].iloc[0])
    roles = dict(zip(risky["asset_id"], risky["asset_class"]))
    roles[cash_id] = "cash"
    ids = list(roles)
    risky_ids = [a for a in ids if a != cash_id]
    budgets = asset_budgets({a: roles[a] for a in risky_ids}, spec.class_budgets, spec.secondary_share)

    bench_ids = [spec.benchmark_equity, spec.benchmark_bond]
    bad = [b for b in bench_ids if b not in pln.columns or b not in local.columns]
    if bad:
        print(f"Benchmark ETFs of config/portfolio.yaml not found in the stage-03 files: {bad}")
        return 1
    all_ids = ids + [b for b in bench_ids if b not in ids]          # the benchmark ETFs only enter the 60/40 line
    window = common_window(pln[all_ids])
    if len(window) < 500:
        print(f"Common window has only {len(window)} days: too short.")
        return 1
    local = local[all_ids].reindex(window.index)
    pln = window

    cov_daily = _estimate_cov(pln, cov_kind, spec.ewma_lambda)
    cov = annualise(cov_daily)
    sleeve_cov = cov.loc[risky_ids, risky_ids]
    cov_ids = cov.loc[ids, ids]

    weights: dict[str, pd.Series] = {}
    status: dict[str, tuple[float, str]] = {}
    for method in METHODS:
        raw = _raw_weights(method, sleeve_cov, profile.max_weight_per_etf, budgets)
        capped = cap_weights(raw, profile.max_weight_per_etf)
        scaled, k, st = scale_to_target_vol(capped, cov_ids, cash_id, profile.target_vol)
        weights[method] = enforce_limits(scaled, roles, profile.max_weight_per_etf, profile.equity_cap, cash_id)
        status[method] = (k, st)
    weights = {m: w.reindex(all_ids).fillna(0.0) for m, w in weights.items()}
    bench = pd.Series(0.0, index=all_ids)
    bench[spec.benchmark_equity], bench[spec.benchmark_bond] = 0.6, 0.4
    weights["benchmark_60_40"] = bench
    status["benchmark_60_40"] = (1.0, "no_targeting")

    # ---- table of results ------------------------------------------------------------------------
    w_table = pd.DataFrame(weights).T[all_ids]
    rows, rc_rows = [], {}
    for method, w in weights.items():
        rc = risk_contributions(w, cov)
        rc_rows[method] = rc["risk_share"]
        port = pln @ w
        dd = max_drawdown(port)
        _, es99 = hist_var_es(port, 0.99)
        equity_w = float(sum(w[a] for a in all_ids if meta.loc[a, "asset_class"] == "equity"))
        rows.append({
            "method": method,
            "risky_share_k": status[method][0],
            "status": status[method][1],
            "vol_model": portfolio_vol(w, cov),
            "vol_realised": float(port.std() * np.sqrt(252)),
            "equity_w": equity_w,
            "cash_w": float(w[cash_id]),
            "max_weight": float(w.drop(cash_id).max()),
            "effective_n": float(1.0 / (w ** 2).sum()),
            "max_risk_share": float(rc["risk_share"].max()),
            "fx_share": _fx_share(w, pln, local),
            "max_dd_insample": dd["max_dd"],
            "es99_insample": es99,
        })
    summary = pd.DataFrame(rows)
    risk_shares = pd.DataFrame(rc_rows).T[all_ids]

    w_table.to_csv(processed / "allocation_weights.csv", index_label="method")
    summary.to_csv(processed / "allocation_summary.csv", index=False)
    risk_shares.to_csv(processed / "allocation_risk_shares.csv", index_label="method")

    # ---- console ---------------------------------------------------------------------------------------
    pct = lambda df, d=1: (df * 100).round(d)  # noqa: E731
    print(f"\nProfile '{args.profile}': target volatility {profile.target_vol:.1%} (PLN), max {profile.max_weight_per_etf:.0%} per ETF, "
          f"equity cap {profile.equity_cap:.0%}")
    print(f"Window: {pln.index.min().date()} to {pln.index.max().date()} ({len(pln)} days). Covariance: {cov_kind}. "
          f"Cash-like ETF: {cash_id} (volatility scaling only)")
    print(f"\nWHY THESE ETFs (rules: eligible -> correlation >= {spec.rules.rho_max:.2f} = same exposure -> most central "
          f"-> most different; class risk budgets {spec.class_budgets})\n")
    print(choice[["asset_class", "asset_id", "decision", "reason"]].sort_values(["asset_class", "decision", "asset_id"]).to_string(index=False))
    for cls in missing_cls:
        print(f"\nNOTE: no ETF could be chosen for the class '{cls}': its risk budget is split among the other classes.")
    print("\nFINAL WEIGHTS (%)\n")
    print(pct(w_table).to_string())
    show = summary.copy()
    for col in ("risky_share_k", "vol_model", "vol_realised", "equity_w", "cash_w", "max_weight",
                "max_risk_share", "fx_share", "max_dd_insample", "es99_insample"):
        show[col] = (show[col] * 100).round(1)
    show["effective_n"] = show["effective_n"].round(1)
    print("\nSUMMARY (%, in-sample snapshot, NOT a performance test). k = share kept in the risky mix; "
          "effective_n = 1/sum(w^2); fx_share = part of the variance due to EUR/PLN\n")
    print(show.to_string(index=False))
    print("\nSHARE OF RISK CARRIED BY EACH ETF (%), from the covariance matrix\n")
    print(pct(risk_shares).to_string())
    off = summary[(summary["status"] != "on_target") & (summary["method"] != "benchmark_60_40")]
    for r in off.itertuples():
        print(f"\nNOTE {r.method}: {r.status} -> "
              + ("cannot add risk without leverage, volatility stays under the target." if r.status == "below_target"
                 else "even the lowest-risk mix is above the target."))
    print("\nWrote etf_choice.csv, allocation_weights.csv, allocation_summary.csv, allocation_risk_shares.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
