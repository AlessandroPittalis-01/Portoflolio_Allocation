"""Stage 10 - backtest of the VaR / ES models (IPS decision 39, step 2).

Reads  : data/processed/backtest_returns_full.csv (stage 06)  or  allocation_weights.csv + returns_pln.csv (stages 03, 05)
Writes : data/processed/var_backtest.csv   one row per model x level

Every day the VaR is forecast with the data of the PREVIOUS days only (rolling window, GARCH refitted every 63 days)
and compared with the loss that really happened. Tests: Kupiec (number of exceptions), Christoffersen (are they
clustered?), conditional coverage, Basel traffic light, ES checks, and a tick loss to rank models.

--source backtest  the realised walk-forward return of the strategy (about 10 years: more exceptions, more power)
--source weights   the stage-05 weights held fixed on the common window (about 5 years)

HOW TO READ THE RESULT
* 'ok' = not rejected at 5% by Kupiec and independence; it is NOT proof that the model is right.
* Too many exceptions = risk understated; too few = too cautious (capital that could work). Clusters = slow model.
* At 99% a 10-year sample has only about 20 expected exceptions: low power, read the zone and the rate, not one p-value.
* Several models are tested: with many tests some pass or fail by chance.

Run:  python pipeline/10_var_backtest.py
      python pipeline/10_var_backtest.py --source weights --window 400
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from prm.config import DEFAULT_SETTINGS_PATH, load_data_settings  # noqa: E402
from prm.risk.var_backtest import MODELS, backtest_model  # noqa: E402

LEVELS = (0.95, 0.99)


def load_series(processed: Path, source: str, method: str) -> tuple[pd.Series | None, str]:
    if source == "backtest":
        path = processed / "backtest_returns_full.csv"
        if not path.exists():
            return None, "Missing stage-06 output. Run first:  python pipeline/06_backtest.py"
        data = pd.read_csv(path, index_col="date", parse_dates=True)
        if method not in data.columns:
            return None, f"Unknown strategy '{method}'. Available: {list(data.columns)}"
        return data[method].dropna(), ""
    if source == "weights":
        if not (processed / "allocation_weights.csv").exists() or not (processed / "returns_pln.csv").exists():
            return None, "Missing stage-03/05 output. Run first:  python pipeline/03_fx_returns.py  and  python pipeline/05_allocation.py"
        weights = pd.read_csv(processed / "allocation_weights.csv", index_col="method")
        if method not in weights.index:
            return None, f"Unknown method '{method}'. Available: {list(weights.index)}"
        w = weights.loc[method]
        w = w[w > 1e-12]
        pln = pd.read_csv(processed / "returns_pln.csv", index_col="date", parse_dates=True)
        if any(a not in pln.columns for a in w.index):
            return None, "Some weighted ETFs have no PLN returns."
        return (pln[list(w.index)].dropna() @ w), ""
    return None, f"Unknown source '{source}' (backtest or weights)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Stage 10: backtest of VaR / ES models.")
    parser.add_argument("--settings", default=str(DEFAULT_SETTINGS_PATH))
    parser.add_argument("--source", default="backtest", choices=["backtest", "weights"])
    parser.add_argument("--method", default="risk_budget")
    parser.add_argument("--window", type=int, default=500, help="days of history for each forecast")
    parser.add_argument("--refit-every", type=int, default=63, help="days between GARCH refits")
    args = parser.parse_args(argv)

    processed = Path(load_data_settings(args.settings).processed_dir)
    series, error = load_series(processed, args.source, args.method)
    if series is None:
        print(error)
        return 1
    if len(series) < args.window + 250:
        print(f"Series too short ({len(series)} days) for a window of {args.window} days (needs at least window + 250).")
        return 1

    rows = [backtest_model(series, m, lvl, args.window, args.refit_every) for lvl in LEVELS for m in MODELS]
    out = pd.DataFrame(rows)
    out["ok"] = (out["kupiec_p"] >= 0.05) & ~(out["independence_p"] < 0.05)
    out.to_csv(processed / "var_backtest.csv", index=False)

    print(f"\nVaR BACKTEST of '{args.method}' ({args.source}); {len(series)} days {series.index.min().date()} -> "
          f"{series.index.max().date()}; forecasts from day {args.window + 1} on (window {args.window}, GARCH refit every "
          f"{args.refit_every} days)\n")
    for lvl in LEVELS:
        sub = out[out["level"] == lvl].set_index("model")
        show = pd.DataFrame({
            "days": sub["n_obs"], "exceptions": sub["exceptions"], "expected": sub["expected"].round(1),
            "rate_%": (sub["rate"] * 100).round(2), "kupiec_p": sub["kupiec_p"].round(3),
            "indep_p": sub["independence_p"].round(3), "cc_p": sub["cc_p"].round(3), "zone": sub["zone"],
            "ES_ratio": sub["es_ratio"].round(2), "ES_p": sub["es_p_value"].round(3),
            "tick_loss_x1e4": (sub["tick_loss"] * 1e4).round(3), "ok": sub["ok"]})
        print(f"{lvl:.0%} level (expected exception rate {(1 - lvl) * 100:.0f}%):\n{show.to_string()}\n")
    print("READ WITH CARE\n * 'ok' = not rejected at 5%; with 99% and about 10 years the power is low."
          "\n * ES_ratio above 1 = the realised loss on exception days is larger than the forecast ES (tail understated); NaN = fewer than 3 exceptions."
          "\n * tick_loss: lower is better, compare models only among those that are not rejected."
          "\n * The series is one history; models were not tuned on it (fixed 0.94 EWMA, window 500), but they are compared on it."
          f"\n\nWrote var_backtest.csv in {processed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
