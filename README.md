# Portfolio Risk Manager

A risk-first, multi-asset ETF portfolio allocation system in Python.
Allocation is driven mainly by risk; forecasts are limited and can only tilt, not drive, decisions.

> **Status: early development.** Done: investment policy, profile configuration, pipeline stage 01 (data sourcing with cache and quality checks), stage 02 (selection of one ETF per category), stage 03 (NBP exchange rates, PLN returns, FX decomposition) and stage 04 (risk analysis), all with tests.
> Not built yet: stages 05-08 (allocation, backtest, simulation, report). The rest of this README describes what is planned and is updated as each stage is built.
>
> Methodological and educational project. Not financial advice.

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
| 05 | `pipeline/05_allocation.py` | portfolio optimisation: chooses among the selected ETFs and sets the weights | planned |
| 06 | `pipeline/06_backtest.py` | walk-forward backtest with monthly contributions, costs, TWR and IRR | planned |
| 07 | `pipeline/07_simulation.py` | Monte Carlo with contributions | planned |
| 08 | `pipeline/08_report.py` | one report per investor profile | planned |

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
- [ ] Stage 05 — allocation methods
- [ ] Stage 06 — backtest with contributions, costs, TWR and IRR
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

Load the investor profiles from Python:

```python
from prm.config import load_profiles

profiles = load_profiles()       # reads config/profiles.yaml and validates it
print(profiles["owner"].target_vol)
```

The loader rejects unknown parameters (typos) and inconsistent values, for example a formal review threshold that is deeper than the drawdown at which the investor says they would stop contributing.

## Disclaimer

For educational and methodological purposes only. Past performance does not predict future results. Nothing here is a recommendation to buy or sell any security.
