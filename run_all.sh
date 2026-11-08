#!/usr/bin/env bash
# Run the whole pipeline in order with the final configuration. Stops at the first error.
# Usage:  bash run_all.sh            (all stages)
#         bash run_all.sh --skip-slow   (skips stage 15, the robustness runs, which take about 7 times stage 06)
# Each stage prints its own result; outputs go to data/processed/.
set -euo pipefail
cd "$(dirname "$0")"
SKIP_SLOW=0
[ "${1:-}" = "--skip-slow" ] && SKIP_SLOW=1

run() { echo; echo "================ $* ================"; python "$@"; }

run pipeline/01_sourcing.py
run pipeline/02_selection.py
run pipeline/03_fx_returns.py
run pipeline/04_risk_analysis.py
run pipeline/05_allocation.py
run pipeline/06_backtest.py
run pipeline/07_bootstrap.py
run pipeline/08_fx_hedge.py
run pipeline/09_market_risk.py
run pipeline/10_var_backtest.py
run pipeline/11_risk_factors.py
run pipeline/12_stress.py
run pipeline/13_risk_extras.py
[ "$SKIP_SLOW" = "1" ] || run pipeline/15_robustness.py
run pipeline/14_report.py
echo; echo "Done. Report: data/processed/report_owner.md"
