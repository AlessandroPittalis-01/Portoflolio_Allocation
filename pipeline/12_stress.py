"""Stage 12 - stress tests of the allocated portfolio (IPS decision 39, step 4).

Reads  : data/processed/allocation_weights.csv (stage 05), returns_pln.csv, returns_local.csv (stage 03),
         config/risk_factors.yaml, config/scenarios.yaml (historical episodes), config/stress_hypothetical.yaml
Writes : data/processed/stress_historical.csv    each episode: direct ETF return (with coverage) and replay through factor betas
         data/processed/stress_hypothetical.csv  each hypothetical scenario: portfolio move and contribution of each factor
         data/processed/stress_reverse.csv       smallest factor shock that reaches each drawdown threshold, per horizon

Three views, all linear in the risk factors of stage 11 (see prm/risk/stress_tests.py and docs/METHODOLOGY.md, section 12):
* historical episodes: direct (ETFs that existed) and replayed (realised factor moves x today's betas)
* hypothetical scenarios with sizes written in a config file BEFORE looking at the results
* reverse stress: which factor combination is the most plausible way to lose 15%, 20%, 25% (the profile's thresholds)

HOW TO READ THE RESULT
* A stress is not a forecast and not a probability. It asks "what if", with today's betas.
* Linear: no convexity. The part of the return not explained by the factors is ignored.
* Reverse stress: 'distance' = how many standard deviations of the factor-driven return the loss is; the normal
  probability is optimistic because real returns have fatter tails.

Run:  python pipeline/12_stress.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_PROFILES_PATH, DEFAULT_SETTINGS_PATH, load_data_settings, load_profiles  # noqa: E402
from prm.risk.factors import (  # noqa: E402
    DEFAULT_FACTORS_PATH, FactorConfigError, build_factors, load_factor_config, sensitivities,
)
from prm.risk.stress import DEFAULT_SCENARIOS_PATH, load_scenarios  # noqa: E402
from prm.risk.stress_tests import (  # noqa: E402
    DEFAULT_HYPOTHETICAL_PATH, StressConfigError, apply_shocks, direct_historical, factor_moves, load_hypothetical,
    reverse_stress,
)

HORIZONS = (21, 63, 252)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 12: stress tests.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--profiles", default=str(DEFAULT_PROFILES_PATH))
    parser.add_argument("--factors", default=str(DEFAULT_FACTORS_PATH))
    parser.add_argument("--scenarios", default=str(DEFAULT_SCENARIOS_PATH))
    parser.add_argument("--hypothetical", default=str(DEFAULT_HYPOTHETICAL_PATH))
    parser.add_argument("--method", default="risk_budget", help="row of allocation_weights.csv")
    parser.add_argument("--profile", default="owner")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    needed = ("allocation_weights.csv", "returns_pln.csv", "returns_local.csv")
    if any(not (processed / f).exists() for f in needed):
        print("Missing stage-03/05 output. Run first:  python pipeline/03_fx_returns.py  and  python pipeline/05_allocation.py")
        return 1
    weights = pd.read_csv(processed / "allocation_weights.csv", index_col="method")
    if args.method not in weights.index:
        print(f"Unknown method '{args.method}'. Available: {list(weights.index)}")
        return 1
    profiles = load_profiles(args.profiles)
    if args.profile not in profiles:
        print(f"Unknown profile '{args.profile}'. Available: {sorted(profiles)}")
        return 1
    profile = profiles[args.profile]
    w = weights.loc[args.method]
    w = w[w > 1e-12]
    pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
    local = pd.read_csv(processed / "returns_local.csv", index_col="date", parse_dates=True)
    if any(a not in pln.columns for a in w.index):
        print("Some weighted ETFs have no PLN returns.")
        return 1
    try:
        cfg = load_factor_config(args.factors)
        factors = build_factors(local, pln, cfg["factors"], cfg["fx_reference_asset"])
        hypo = load_hypothetical(args.hypothetical, list(factors.columns))
    except (FactorConfigError, StressConfigError) as exc:
        print(f"Setup problem: {exc}")
        return 1
    scenarios = load_scenarios(args.scenarios)

    port = pln[list(w.index)].dropna() @ w
    data = pd.concat([port.rename("port"), factors], axis=1, sort=True).dropna()
    if len(data) < 600:
        print(f"Common window too short ({len(data)} days).")
        return 1
    sens = sensitivities(data["port"], data[factors.columns])
    beta = sens["beta"]
    cov_daily = data[factors.columns].cov()

    # ---- historical: direct and replayed -------------------------------------------------------------
    direct = direct_historical(pln, w, scenarios)
    moves = factor_moves(factors, scenarios)
    rows = []
    for s in scenarios:
        res = apply_shocks(beta, moves.loc[s["id"]])
        rows.append({"scenario": s["id"], "coverage": direct.loc[s["id"], "coverage"], "direct_return": direct.loc[s["id"], "covered_return"],
                     "replayed_move": res["pnl"], "factors_without_data": " ".join(res["missing"])})
    hist = pd.DataFrame(rows).set_index("scenario")
    hist.to_csv(processed / "stress_historical.csv", index_label="scenario")

    # ---- hypothetical ---------------------------------------------------------------------------------
    rows = []
    for sid, body in hypo.items():
        res = apply_shocks(beta, pd.Series(body["shocks"]))
        rows.append({"scenario": sid, "portfolio_move": res["pnl"], **{f"c_{f}": res["contrib"][f] for f in beta.index},
                     "description": body["description"]})
    hyp = pd.DataFrame(rows).set_index("scenario")
    hyp.to_csv(processed / "stress_hypothetical.csv", index_label="scenario")

    # ---- reverse --------------------------------------------------------------------------------------
    levels = [profile.dd_alert, profile.dd_review, profile.stop_contributing_dd]
    rows = []
    for lvl in levels:
        for h in HORIZONS:
            r = reverse_stress(beta, cov_daily, abs(lvl), h)
            rows.append({"loss": lvl, "horizon_days": h, "distance": r["distance"], "normal_prob": r["normal_prob"],
                         **{f"shock_{f}": r["shock"][f] for f in beta.index}})
    rev = pd.DataFrame(rows)
    rev.to_csv(processed / "stress_reverse.csv", index=False)

    # ---- console ---------------------------------------------------------------------------------------
    pct = lambda s, d=1: (s * 100).round(d)  # noqa: E731
    print(f"\nSTRESS TESTS of '{args.method}' ({len(w)} ETFs, fixed weights, PLN), profile '{args.profile}'. Betas from "
          f"{data.index.min().date()} -> {data.index.max().date()} ({len(data)} days), R-squared {sens.attrs['r2']:.2f}")
    print("\nBetas (portfolio % move for +1% of the factor): " + ", ".join(f"{f} {beta[f]:.2f}" for f in beta.index))
    show = hist.copy()
    for c in ("coverage", "direct_return", "replayed_move"):
        show[c] = pct(show[c])
    print("\n1) HISTORICAL EPISODES (%): direct = ETFs that existed (coverage = share of the weight with data); "
          "replayed = realised factor moves x today's betas\n")
    print(show.to_string())
    show = hyp.drop(columns="description").copy()
    for c in show.columns:
        show[c] = pct(show[c])
    print("\n2) HYPOTHETICAL SCENARIOS (%): portfolio move and contribution of each factor (sizes in config/stress_hypothetical.yaml)\n")
    print(show.to_string())
    for sid, body in hypo.items():
        print(f"   {sid}: {body['description']}")
    print("\n3) REVERSE STRESS: the most plausible factor shock (in %) that brings the portfolio to each threshold\n"
          "   distance = loss / std of the factor-driven return over the horizon; prob = normal probability of a loss at least this big\n")
    show = rev.copy()
    show["loss"] = pct(show["loss"], 0)
    show["distance"] = show["distance"].round(2)
    show["normal_prob"] = pct(show["normal_prob"], 2)
    for c in [c for c in show.columns if c.startswith("shock_")]:
        show[c] = pct(show[c])
    print(show.to_string(index=False))
    print("\nREAD WITH CARE\n * Linear in the factors of stage 11: no convexity; the unexplained part of the return is ignored."
          "\n * Hypothetical sizes are assumptions fixed before looking at results; they are not probabilities."
          "\n * Reverse stress probability assumes normality: real tails are fatter, so it is optimistic."
          "\n * Replayed episodes use today's betas on the realised factor moves; factors without data in a window count as 0."
          f"\n\nWrote stress_historical.csv, stress_hypothetical.csv, stress_reverse.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
