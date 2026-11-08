# Portfolio Risk Manager

A risk-first, multi-asset ETF portfolio allocation system in Python.
Allocation is driven mainly by risk; forecasts are limited and can only tilt, not drive, decisions.

> **Status: early development.** Done: investment policy, profile configuration, pipeline stage 01 (data sourcing with cache and quality checks), stage 02 (selection of one ETF per category), stage 03 (NBP exchange rates, PLN returns, FX decomposition) and stage 04 (risk analysis) stage 05 (allocation methods) and stage 06 (walk-forward backtest), all with tests.
> Not built yet: stages 06-08 (backtest, simulation, report). The rest of this README describes what is planned and is updated as each stage is built.
>
> Methodological and educational project. Not financial advice.

> The mathematics of every stage (formulas, assumptions, limits) is in `docs/METHODOLOGY.md`; the decisions and results are in `docs/IPS.md`.

## Goals

- Build and monitor ETF portfolios from an explicit **Investment Policy Statement** ([docs/IPS.md](docs/IPS.md)), written before the code and updated step by step as results are observed.
- Support several investor profiles through configuration ([config/profiles.yaml](config/profiles.yaml)): one engine, many parameter sets.
- Favour a robust process over in-sample performance: no results are claimed before they are validated out of sample.

## Design principles

- **Risk first.** Risk contributions, VaR/ES, drawdowns and stress tests are first-class outputs.
- **FX risk is explicit.** Results are measured in PLN. Returns are split into local-currency and currency components, the FX contribution to portfolio risk is reported and limited, and hedged and unhedged versions of an exposure are compared on risk criteria (see IPS section 3.1).
- **Frozen rules.** Parameters are fixed in the IPS before looking at backtest results; changes are versioned.
- **Honest evaluation.** Walk-forward backtests with transaction and FX costs, a held-out final period, small pre-defined parameter grids, and confidence intervals on performance differences.
- **Real-world constraints.** UCITS accumulating ETFs, monthly contributions in PLN, tax-aware rebalancing (contributions first, sales as the exception), no leverage.

## Planned methods

| Tier | Methods |
|------|---------|
| Baselines | equal weight, 60/40, inverse volatility |
| Core risk-based | ERC risk parity, Hierarchical Risk Parity, minimum variance, maximum diversification |
| Tail-risk aware | minimum CVaR |
| Overlays | volatility targeting (EWMA/GARCH), simple regime filter |
| Views | Black-Litterman with a few explicit, capped views |
| Robustness | Ledoit-Wolf and EWMA covariance, resampling, turnover penalty |

Each tier is implemented only after the previous one is tested, and a method is kept only if it improves on the simpler one out of sample under criteria fixed in advance. Details in the IPS.

## Pipeline stages

The project is a numbered pipeline. Each stage reads the files written by the previous one and writes its own, so any stage can be re-run alone. The scripts in `pipeline/` are thin runners: the logic lives in `src/prm/` and is covered by tests.

| Stage | Script | Purpose | Status |
|-------|--------|---------|--------|
| 01 | `pipeline/01_sourcing.py` | download prices of ALL candidate ETFs (Yahoo), local cache, data-quality checks; `--find` and `--probe` help to confirm symbols | built |
| 02 | `pipeline/02_selection.py` | pick the best candidate of each category, by criteria only (cost, size, history, data quality), never by performance | done |
| 03 | `pipeline/03_fx_returns.py` | NBP exchange rates, PLN returns, local vs FX decomposition | done |
| 04 | `pipeline/04_risk_analysis.py` | volatility, drawdown, VaR/ES, correlations, risk contributions, covariance estimators | done |
| 05 | `pipeline/05_allocation.py` | portfolio optimisation: chooses among the selected ETFs and sets the weights | done |
| 06 | `pipeline/06_backtest.py` | walk-forward backtest with monthly contributions, costs, TWR and IRR | built, not yet run on real data |
| 13 | `pipeline/13_risk_extras.py` | DaR/CDaR, Ulcer index, diversification ratio, effective risk bets, component ES, correlation in stress | built, not yet run on real data |
| 12 | `pipeline/12_stress.py` | stress tests: historical episodes (direct and replayed through factor betas), hypothetical scenarios, reverse stress test | built, not yet run on real data |
| 11 | `pipeline/11_risk_factors.py` | risk-factor sensitivities (the 'Greeks' of a linear portfolio): betas to equity, rates, credit, inflation, gold, EUR/PLN, variance attribution, rolling betas | built, not yet run on real data |
| 10 | `pipeline/10_var_backtest.py` | backtest of the VaR/ES models: Kupiec, Christoffersen, traffic light, ES checks, tick loss | built, not yet run on real data |
| 09 | `pipeline/09_market_risk.py` | VaR / ES of the allocated portfolio: historical, EWMA, GARCH, filtered historical simulation, Monte Carlo normal and Student-t | built, not yet run on real data |
| 08 | `pipeline/08_fx_hedge.py` | EUR/PLN hedge study: hedge ratio by class, assumed carry and cost, same allocation solved again; FX share, volatility, drawdown, ES | built, not yet run on real data |
| 07 | `pipeline/07_bootstrap.py` | stationary block bootstrap of the backtest returns: drawdown and under-water distribution, threshold probabilities, size of gaps between strategies | built, not yet run on real data |
| 14 | `pipeline/14_report.py` | monitoring report: numbers of the earlier stages against the risk limits (GREEN / AMBER / RED) | built, not yet run on real data |
| 15 | `pipeline/15_robustness.py` | the walk-forward re-run with one assumption changed at a time (cost, switch margin, secondary share), 7 pre-declared variants | built, not yet run on real data |

Selection funnel: many candidates per category (stage 01) -> one ETF per category (stage 02) -> a small subset with weights (stage 05).

## Structure

```
portfolio-risk-manager/
├── README.md
├── docs/IPS.md                      # policy, decisions, results log
├── docs/SETUP_it.md                 # step-by-step setup guide (Italian)
├── config/
│   ├── profiles.yaml                # investor profiles and parameters
│   ├── settings.yaml                # data-stage parameters and quality thresholds
│   └── universe_candidates.yaml     # candidate ETFs, chosen by criteria only
├── pipeline/                        # numbered stage runners
├── src/prm/
│   ├── config.py                    # loads and validates the configuration
│   └── data/                        # sources, cache, quality checks, universe
├── data/                            # raw cache and processed tables (not in git)
└── tests/
```

## Data and known limits

Free data (Yahoo Finance through `yfinance`) is used for ETF prices, and the Polish central bank (NBP) for PLN exchange rates (stage 03).
Yahoo has no official API: it can rate-limit or change without notice, and its adjusted prices can differ from other sources. For this reason every download is cached, every series is quality-checked, problems are flagged and never fixed silently, and a second source is planned for cross-checks.
Other limits: short ETF histories, different listing currencies, no quality guarantee. Any proxy used for older periods is declared explicitly. Do not use data from an employer's licensed terminals.

## Roadmap

- [x] M0 — IPS draft, profile configuration, validated config loader with tests
- [x] Stage 01 — sourcing: Yahoo source, cache, quality checks, tests (symbols of several assets still to be confirmed with `--probe`)
- [x] Stage 02 — selection of the best candidate per category (criteria only)
- [x] Stage 03 — FX and PLN returns (first live run of the NBP download still to confirm)
- [x] Stage 04 — risk analysis
- [x] Stage 05 — allocation methods (first tier: baselines, risk parity, minimum variance, HRP)
- [x] Stage 06 — backtest with contributions, costs, TWR and IRR (built; first real run pending)
- [ ] Stage 07 — Monte Carlo
- [ ] Stage 08 — reports and multi-profile comparison

## How to run

First time with GitHub and Codespaces? Follow the step-by-step guide in Italian: [docs/SETUP_it.md](docs/SETUP_it.md).

Requires Python 3.10 or newer.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[dev]"          # installs the package and pytest
pytest                           # runs the tests (no network needed)
```

Stage 01 (needs internet the first time; later runs use the cache). It downloads every ETF of `config/universe_candidates.yaml` that has a confirmed symbol:

```bash
python pipeline/01_sourcing.py                  # download, check, write data/processed/
python pipeline/01_sourcing.py --find           # list the Yahoo listings (symbol, exchange, name) of each unconfirmed ETF
python pipeline/01_sourcing.py --probe          # test unconfirmed symbol guesses (yahoo_symbol_try)
python pipeline/01_sourcing.py --refresh        # ignore the cache
python pipeline/01_sourcing.py --assets dev_equity,gold
```

It writes `data/processed/prices_adj_close.csv` (one column per asset) and `data/processed/quality_report.csv` (symbol, quote currency, status and issues per asset). Series with structural errors are excluded from the price table.

Stage 02 (offline, uses the files written by stage 01). It picks one ETF per category by criteria only (accumulating, EUR listing, data quality, cost, history), never by performance:

```bash
python pipeline/02_selection.py
```

It writes `data/processed/selection.csv` (every candidate with its rank and the reason it was excluded, if any), `selected_assets.csv` (the winners) and `prices_selected.csv`, and prints a redundancy check on the winners.

Stage 03 (needs internet the first time, for the NBP exchange rates):

```bash
python pipeline/03_fx_returns.py
```

It writes `data/processed/returns_pln.csv` (daily returns in PLN, input of the risk stages), `returns_local.csv`, `fx_rates.csv` and `fx_decomposition.csv` (volatility in local currency and in PLN, and the share of the PLN variance due to the currency).

Stage 04 (offline). Measures risk in PLN: volatility, daily drawdown, VaR/ES, tails, hidden dollar exposure, three covariance estimators and historical stress scenarios:

```bash
python pipeline/04_risk_analysis.py
python pipeline/04_risk_analysis.py --assets allworld_vanguard,global_bond_hedged,gold,cash_like   # longer common window
```

Stage 05 (offline). Chooses the ETFs of each class by mathematical rules (`src/prm/allocation/choose.py`: eligibility, correlation groups, medoid, maximin) and computes the weights of six allocation methods (including `risk_budget`: equity 50 / bond 35 / gold 15 as shares of risk) under the same volatility target and limits (in PLN), for a chosen profile:

```bash
python pipeline/05_allocation.py                            # owner profile
python pipeline/05_allocation.py --profile prudent --cov ewma
python pipeline/05_allocation.py --solve-equity-budget     # volatility reached by each equity risk budget (covariance only)
```

It prints weights, volatility, risk shares, FX share and in-sample drawdown, and writes `etf_choice.csv` (why each candidate was chosen or not), `allocation_weights.csv`, `allocation_summary.csv`, `allocation_risk_shares.csv`. It shows no returns on purpose: it is a snapshot, not a performance test. Class budgets and choice rules are in `config/portfolio.yaml`; it needs the output of stage 02 (`selection.csv`).

Load the investor profiles from Python:

```python
from prm.config import load_profiles

profiles = load_profiles()       # reads config/profiles.yaml and validates it
print(profiles["owner"].target_vol)
```

The loader rejects unknown parameters (typos) and inconsistent values, for example a formal review threshold that is deeper than the drawdown at which the investor says they would stop contributing.

## Disclaimer

For educational and methodological purposes only. Past performance does not predict future results. Nothing here is a recommendation to buy or sell any security.

### Stage 06 - walk-forward backtest

```bash
python pipeline/06_backtest.py                       # owner profile
python pipeline/06_backtest.py --profile prudent --cost-bps 25
```

At every month-end the choice of the ETFs, the covariance and the weights are recomputed with the data available up to that day; an ETF enters only after 504 days of history (no proxies). Monthly contributions buy the underweight ETFs; sales happen only outside the band or when an ETF leaves the portfolio; every trade pays `cost_bps` (`config/backtest.yaml`). The core ETF of a class is the broadest one (`scope` in the universe file); a held ETF keeps its place unless a challenger is clearly better (stability rule). It compares the allocation methods with two fixed 60/40 benchmarks (one with the all-world ETF, one with an older world ETF to cover the whole period) and writes `backtest_summary_full.csv`, `backtest_summary_common.csv`, `backtest_returns.csv`, `backtest_choices.csv`, `backtest_weights.csv`, `backtest_class_weights.csv`. It is a check of risk limits, costs and stability, not a promise of returns: no taxes, one history, no separate hold-out.

### Stage 07 - block bootstrap of the backtest

```bash
python pipeline/06_backtest.py       # writes backtest_returns_full.csv
python pipeline/07_bootstrap.py      # 2000 paths of 10 years, paired dates
```

Resamples blocks of days from the daily returns of stage 06 (same dates for every strategy) and reports the distribution of maximum drawdown, time under water and final money multiple, the probability of crossing the alert / review / stop drawdowns, and each strategy minus the reference on the same paths. It measures how much the outcome depends on the order of the days we have seen. It cannot create regimes that are not in the sample and it is not a forecast. Parameters: `config/bootstrap.yaml`.

### Stage 08 - EUR/PLN hedge study

```bash
python pipeline/08_fx_hedge.py       # scenarios and assumed carry/cost in config/fx_hedge.yaml
```

A model with ASSUMED carry and cost, not a real instrument. It answers: how much risk would a hedge remove, and can it deepen drawdowns?

### Stage 09 - VaR and ES with several models

```bash
python pipeline/09_market_risk.py     # portfolio = risk_budget weights of stage 05
```

Same portfolio, same day, different assumptions: the spread is model risk. Backtesting (Kupiec, Christoffersen, traffic light) is the next step.

### Stage 10 - backtest of VaR and ES

```bash
python pipeline/10_var_backtest.py                   # realised walk-forward returns of risk_budget (stage 06), about 10 years
python pipeline/10_var_backtest.py --source weights  # fixed stage-05 weights on the common window
```

Forecasts use only past data. 'ok' = not rejected at 5%, never proof. At 99% the power is low.

### Stage 11 - risk-factor sensitivities

```bash
python pipeline/11_risk_factors.py     # factors in config/risk_factors.yaml
```

ETFs are linear: no gamma or vega. The equivalent of delta is the beta of the portfolio to a few factors built from ETFs. Shares of variance add up to 100% with a residual.

### Stage 12 - stress tests

```bash
python pipeline/12_stress.py     # scenarios in config/scenarios.yaml and config/stress_hypothetical.yaml
```

Linear in the factors of stage 11. A stress is a what-if, not a forecast. Reverse stress: the most plausible factor shock that reaches -15%, -20% and -25%.

### Stage 13 - further risk metrics

```bash
python pipeline/13_risk_extras.py
```

Drawdown-based measures, diversification, who carries the tail loss, and whether correlations rise in stress (corrected for selection).

### Stage 14 - monitoring report
```bash
python pipeline/14_report.py
```
Writes `data/processed/report_owner.md`: model volatility, FX share, weights, VaR 99%, VaR model zone, worst stress scenario,
drawdown, each against its limit (`config/limits.yaml` and `config/profiles.yaml`). Limits marked *proposed* wait for the owner.

### Stage 15 - robustness of the backtest
```bash
python pipeline/15_robustness.py
```
Seven pre-declared variants, one change at a time. Slow (about 7 times stage 06). Do not pick the best variant.

### Whole pipeline in order
```bash
bash run_all.sh              # everything, in order
bash run_all.sh --skip-slow  # without stage 15
```
Instruments for hedging EUR/PLN: see `docs/FX_HEDGE_INSTRUMENTS.md` (research note, mostly unverified).
