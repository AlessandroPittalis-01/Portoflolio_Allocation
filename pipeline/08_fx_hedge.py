"""Stage 08 - what would an EUR/PLN hedge do to the portfolio? (IPS decision 38)

Reads  : data/processed/returns_pln.csv, returns_local.csv (stage 03), selection.csv (stage 02),
         config/fx_hedge.yaml (scenarios and ASSUMED carry / cost), portfolio.yaml, profiles.yaml
Writes : data/processed/fx_hedge_summary.csv   one row per scenario x assumed carry
         data/processed/fx_hedge_assets.csv    per ETF: FX volatility and correlation local vs FX

For each hedge scenario (hedge ratio by class) the PLN returns of every ETF are rebuilt (model in prm/fx/hedge.py),
then the SAME allocation (risk_budget, same rules, same target volatility, same limits) is solved again on them.
So the table shows both the risk the hedge removes and how the target-volatility rule reuses that room.

HOW TO READ THE RESULT
* It is a model, not an instrument: carry and cost are assumptions (config/fx_hedge.yaml); margins, taxes, rolling
  and the availability of real PLN-hedged products are NOT modelled. Return effects shown are 'assumed carry x notional'.
* In crises the PLN often weakens (EUR/PLN up), which cushions EUR assets for a PLN investor. If local returns and
  FX are negatively correlated, hedging can make the worst drawdowns DEEPER. Check corr_local_fx and max_dd.
* One in-sample window (common window of the chosen ETFs).

Run:  python pipeline/08_fx_hedge.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.allocation.build import AllocationError, allocate, build_meta  # noqa: E402
from prm.allocation.spec import DEFAULT_PORTFOLIO_PATH, load_portfolio  # noqa: E402
from prm.allocation.targeting import portfolio_vol  # noqa: E402
from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402
from prm.data.universe import DEFAULT_UNIVERSE_PATH, load_universe  # noqa: E402
from prm.fx.hedge import (  # noqa: E402
    DEFAULT_HEDGE_PATH, daily_net_carry, fx_component, hedge_effect, hedge_ratios, hedged_pln_returns, load_hedge_config,
)
from prm.risk.metrics import hist_var_es, max_drawdown  # noqa: E402

METHOD = "risk_budget"


def _fx_share(port_pln: pd.Series, port_local: pd.Series) -> float:
    var = port_pln.var()
    return float(port_pln.cov(port_pln - port_local) / var) if var > 0 else float("nan")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 08: EUR/PLN hedge study.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--portfolio", default=str(DEFAULT_PORTFOLIO_PATH))
    parser.add_argument("--universe", default=str(DEFAULT_UNIVERSE_PATH))
    parser.add_argument("--hedge", default=str(DEFAULT_HEDGE_PATH))
    parser.add_argument("--profile", default="owner")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    needed = ("returns_pln.csv", "returns_local.csv", "selection.csv")
    if any(not (processed / f).exists() for f in needed):
        print("Missing stage-02/03 output. Run first:  python pipeline/02_selection.py  and  python pipeline/03_fx_returns.py")
        return 1
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Available: {sorted(profiles)}")
        return 1
    profile, spec, cfg = profiles[args.profile], load_portfolio(args.portfolio), load_hedge_config(args.hedge)

    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    _, assets = load_universe(args.universe)
    meta = build_meta(pd.read_csv(processed / "selection.csv"), assets)

    rows = []
    for name, ratios_by_class in cfg["scenarios"].items():
        ratios = hedge_ratios(meta, ratios_by_class, pln.columns)
        carries = cfg["carry_annual"] if ratios.max() > 0 else [0.0]      # no hedge: carry is irrelevant
        for carry in carries:
            pln_h = hedged_pln_returns(pln, local, ratios, daily_net_carry(carry, cfg["cost_annual"]))
            try:
                alloc = allocate(pln_h, local, meta, spec, profile, spec.covariance, methods=(METHOD,), min_window=500)
            except AllocationError as exc:
                print(f"[{name}, carry {carry:.0%}] allocation not possible: {exc}")
                continue
            w = alloc.weights[METHOD]
            port, port_loc = alloc.pln @ w, alloc.local @ w
            dd = max_drawdown(port)
            var95, es95 = hist_var_es(port, 0.95)
            _, es99 = hist_var_es(port, 0.99)
            cls = meta["asset_class"].reindex(w.index)
            eff = hedge_effect(w, ratios, carry, cfg["cost_annual"])
            rows.append({
                "scenario": name, "carry_assumed": carry, "chosen": " ".join(a for a in alloc.risky_ids),
                "vol_model": portfolio_vol(w, alloc.cov), "vol_realised": float(port.std() * np.sqrt(252)),
                "risky_share_k": alloc.status[METHOD][0], "status": alloc.status[METHOD][1],
                "equity_w": float(w[cls == "equity"].sum()), "bond_w": float(w[cls == "bond"].sum()),
                "real_w": float(w[cls == "real"].sum()), "cash_w": float(w[alloc.cash_id]),
                "fx_share": _fx_share(port, port_loc), "max_dd": dd["max_dd"], "es95_daily": es95, "es99_daily": es99,
                "hedged_notional": eff["hedged_notional"], "carry_minus_cost_pa": eff["carry_minus_cost_pa"],
            })
    if not rows:
        print("No scenario could be computed.")
        return 1
    summary = pd.DataFrame(rows)
    summary.to_csv(processed / "fx_hedge_summary.csv", index=False)

    fx = fx_component(pln, local)
    asset_rows = [{"asset_id": a, "asset_class": meta["asset_class"].get(a),
                   "vol_fx_ann": float(fx[a].std() * np.sqrt(252)),
                   "corr_local_fx": float(local[a].corr(fx[a]))} for a in fx.columns if a in meta.index]
    assets_tbl = pd.DataFrame(asset_rows)
    assets_tbl.to_csv(processed / "fx_hedge_assets.csv", index=False)

    pct = lambda s: (s * 100).round(1)  # noqa: E731
    show = summary.drop(columns=["chosen"]).copy()
    for c in ("carry_assumed", "vol_model", "vol_realised", "risky_share_k", "equity_w", "bond_w", "real_w", "cash_w",
              "fx_share", "max_dd", "es95_daily", "es99_daily", "hedged_notional"):
        show[c] = pct(show[c])
    show["carry_minus_cost_pa"] = (show["carry_minus_cost_pa"] * 100).round(2)
    print(f"\nFX HEDGE STUDY, profile '{args.profile}', method {METHOD}, target {profile.target_vol:.1%}; cost assumed "
          f"{cfg['cost_annual']:.2%} a year. Window {pln.index.min().date()} -> {pln.index.max().date()}\n")
    print("ETFs chosen per scenario:", "; ".join(sorted({f"{r.scenario}: {r.chosen}" for r in summary.itertuples()})))
    print("\nRESULT (%, in-sample; carry_assumed = ASSUMED PLN-EUR interest differential; carry_minus_cost_pa = assumed effect on the "
          "yearly return, NOT a forecast)\n")
    print(show.to_string(index=False))
    show_a = assets_tbl.copy()
    show_a["vol_fx_ann"] = pct(show_a["vol_fx_ann"])
    show_a["corr_local_fx"] = show_a["corr_local_fx"].round(2)
    print("\nPER ETF: FX volatility (%) and correlation of the local return with EUR/PLN. Negative = the currency cushions "
          "the ETF in bad times, so hedging removes a natural offset\n")
    print(show_a.to_string(index=False))
    print("\nREAD WITH CARE\n * A model with ASSUMED carry and cost; real instruments, margin calls, taxes and rolling are not modelled."
          "\n * Judge risk (volatility, drawdown, ES, FX share), not the carry line."
          "\n * Gold: hedging EUR/PLN leaves the USD risk of the gold price in place."
          "\n * In-sample, one window; the allocation is solved again for each scenario (same rules and target)."
          "\n\nWrote fx_hedge_summary.csv, fx_hedge_assets.csv in", processed)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
