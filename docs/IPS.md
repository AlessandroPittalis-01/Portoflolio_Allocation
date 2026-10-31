# Investment Policy Statement (IPS) — v0.1 DRAFT

> Methodological and educational project. Not personalised financial advice.
> Rule: every parameter used by the code must appear here (or in `config/profiles.yaml`)
> with its rationale. Parameters are frozen BEFORE looking at backtest results.
> Any change = new IPS version + entry in the changelog at the bottom.

## 1. Status legend

| Tag | Meaning |
|-----|---------|
| `[DECIDED]` | stated by the project owner |
| `[PROPOSED]` | suggested during design, not yet confirmed |
| `[CALIBRATE]` | numeric hypothesis, to be checked against historical data |

## 2. Decision log

| # | Topic | Value | Status |
|---|-------|-------|--------|
| 1 | Purpose | long-term investing, no liability to fund | `[DECIDED]` |
| 2 | Horizon | 10 years | `[DECIDED]` |
| 3 | Contributions | monthly, 500-800 EUR-equivalent, paid in PLN | `[DECIDED]` |
| 4 | Tax residence / base currency | Poland / PLN | `[DECIDED]` |
| 5 | Instruments | multi-asset UCITS ETFs | `[DECIDED]` |
| 6 | Behavioural limit | would NOT keep contributing at -25% drawdown | `[DECIDED]` |
| 7 | Rebalancing style | prefers buying (contributions) over selling | `[DECIDED]` |
| 8 | Share class | accumulating (Belka tax deferred to sale) | `[PROPOSED]` |
| 9 | Max number of ETFs | 6 risk ETFs + 1 cash-like ETF for vol scaling | `[PROPOSED]` |
| 10 | Vol target (owner profile) | 6-8% annual | `[CALIBRATE]` — lowered after #6 |
| 11 | IPS maintenance | updated step by step as code results are observed | `[DECIDED]` |
| 12 | Allocation methods | tiered plan in section 5 | `[PROPOSED]` |
| 13 | Drawdown at which owner feels discomfort / stops contributing | below -25% | OPEN — to be refined by looking at historical drawdowns of candidate portfolios |
| 14 | Equity blocks | developed and emerging as separate ETFs | `[DECIDED]` |
| 15 | Research universe (8-12 ETFs) vs implementable universe (max 6 + 1) | see section 3 | `[PROPOSED]` |
| 16 | Bond block | global bonds | `[DECIDED]` |
| 17 | FX risk | explicit, structured component of the portfolio | `[DECIDED]` |
| 18 | Hedging policy and FX risk limit | see section 3.1 | `[PROPOSED]` / `[CALIBRATE]` |
| 19 | Project layout | numbered pipeline stages 01-07 (see README), logic in `src/prm`, thin runners in `pipeline/` | `[DECIDED]` |
| 20 | Selection workflow | stage 01 downloads all candidates; a separate stage picks the best per category by criteria; optimisation then chooses among the selected | `[DECIDED]` |
| 21 | Candidate categories | those of the reference project plus ours (about 20 categories, see `universe_candidates.yaml`) | `[DECIDED]` |

Why #6 matters: a risk level whose plausible drawdowns exceed what the owner will
actually tolerate is not implementable. The vol target must be consistent with the
behavioural limit, not the other way round.

## 3. Universe

Two layers `[PROPOSED]`:

- **Research universe**: about 8-12 UCITS ETFs, used to study risk contributions,
  correlations, clustering (HRP) and method behaviour. More assets make these analyses
  more informative: HRP on 5 assets is almost trivial.
- **Implementable universe**: max 6 risk ETFs + 1 cash-like ETF, a subset of the research
  universe. This is what the owner would actually buy with 500-800 EUR per month.

Selection funnel `[DECIDED]`: (1) stage 01 downloads ALL candidates, several per category where useful;
(2) a separate stage chooses the best candidate of each category using only criteria fixed in advance
(cost, fund size, history length, data-quality flags, replication method), never performance;
(3) portfolio optimisation (stage 05) then chooses among the selected ETFs. With about 20 categories the
covariance matrix has about 200 free numbers: robust estimators (Ledoit-Wolf, EWMA) and methods that tolerate
many assets (HRP, risk parity) become essential, and highly overlapping ETFs (factor and sector ETFs versus
MSCI World) will be checked for redundancy before optimisation.

Subset rule: the implementable set is chosen by constraints fixed in advance (one ETF per
risk driver, history length, cost, size, listing currency), NOT by backtest performance.
Choosing it by performance would be data snooping on the universe.

All ETFs: UCITS, accumulating, listed in one currency (to batch FX conversions).
No leverage, derivatives, single stocks.

Risk drivers (implementable core): developed equities, emerging equities (separate ETF
`[DECIDED]`), global bonds (`[DECIDED]`; hedged and unhedged versions both enter the
research universe), inflation-linked bonds, gold. Concrete tickers are chosen
in the data module, checking history length, TER, domicile, listing currency.

## 3.1 Currency (FX) risk policy `[PROPOSED]`

FX risk is a first-class risk of this portfolio, not a detail: everything is measured in
PLN and almost every ETF holds non-PLN assets.

1. **Measurement.** PLN return = (1 + local return) x (1 + FX return) - 1. Risk is
   decomposed into asset risk, FX risk and their covariance. Reports show PLN and local-currency
   results side by side.
2. **Exposure map.** Exposure is by the currency of the UNDERLYING assets, not the listing
   currency (a EUR-listed ETF on US stocks is mostly USD exposure). Source: fund factsheets stored
   in config with a date, cross-checked with a regression of ETF returns on FX returns
   ("currency betas").
3. **Hedging policy** (hedged share classes only, no derivatives). Global bonds: both hedged and
   unhedged versions are studied. Starting hypothesis: hedged, because unhedged global bonds have
   FX volatility comparable to or larger than their own volatility, so they stop acting as a
   stabiliser. Equities: unhedged as a starting point, because foreign-currency exposure may
   reduce losses in global stress for a PLN investor. BOTH statements are hypotheses to test on
   data, not facts.
4. **Limit.** Share of total portfolio variance coming from FX: max `[CALIBRATE]` 30%.
   Reported as an FX risk contribution.
5. **Stress tests.** PLN depreciation and appreciation scenarios, plus historical episodes
   (2008, 2020, 2022).
6. **No FX forecasting and no active currency views.** Hedging decisions use risk criteria
   (drawdown in PLN, FX risk contribution), not past returns.
7. **Costs.** A hedged ETF embeds the interest-rate differential (a cost or a gain) in its price.
   Backtests on real hedged ETFs include it; proxy histories must reproduce it explicitly.
8. **Data.** Exchange rates from the Polish central bank (NBP), free; to be verified when the
   data module is built.

## 4. Risk policy

| Parameter | Owner profile | Notes |
|-----------|---------------|-------|
| Annual vol target | `[CALIBRATE]` 6-8% | see `config/profiles.yaml` for other profiles |
| Drawdown ALERT | `[CALIBRATE]` -10% | triggers a review, never an automatic sale |
| Drawdown REVIEW | `[CALIBRATE]` -18% | formal re-check of the IPS assumptions |
| Max weight per ETF | `[CALIBRATE]` 40% | |
| Long only, no leverage | fixed | |
| Consistency rule | review threshold not deeper than the drawdown where the investor stops contributing | enforced in `prm.config` |

## 5. Allocation methods

Principles `[PROPOSED]`:

1. All methods are compared under the SAME constraints and the SAME volatility target.
   Otherwise a low-risk method looks "better" only because it takes less risk.
2. Without leverage, hitting a vol target means shifting weight to a cash-like ETF
   (money market / short-term bonds). This ETF is used only for vol scaling.
3. Methods are added in tiers. A tier is implemented only after the previous one is tested.
4. A method becomes a final candidate only if, out of sample and net of costs, it improves
   on the simpler method below it on criteria fixed in advance (risk-adjusted return AND
   drawdown), in a majority of sub-periods and not only overall.
5. With 10-15 years of data, many differences will not be statistically significant.
   We report block-bootstrap confidence intervals for performance differences, and say so
   when a difference is inside the noise.

| Tier | Methods | Role |
|------|---------|------|
| 0 Baselines | equal weight, 60/40, inverse volatility | yardsticks, never "beaten" in-sample for its own sake |
| 1 Core risk-based | ERC risk parity, HRP, min variance (with weight caps), max diversification | main candidates |
| 2 Tail-risk aware | min-CVaR (scenario LP), optionally min-CDaR | tests whether tail focus helps; CVaR is noisy on short samples |
| 3 Overlays | vol targeting (EWMA/GARCH forecast), regime filter (e.g. VIX level), drawdown control | rules written before testing, no tuning on results |
| 4 Views | Black-Litterman with few explicit, documented views | tilt capped at `[CALIBRATE]` +-5 pp from risk-based weights; never drives the core |
| Robustness layer | Ledoit-Wolf / EWMA covariance, resampled weights, blends of methods, turnover penalty | applied to tiers 1-2 |

Forecasts: volatility forecasts only in the core. Return forecasts appear only in tier 4,
as explicit views, and are capped.

## 6. Rebalancing

Monthly check. New contributions go first to the most underweight ETF. Sell only
if a weight breaches the band (`[CALIBRATE]` +-5 pp absolute). Each sale in profit
is a taxable event (19% Belka in Poland): sales are the exception.
Note: as the portfolio grows, a monthly contribution moves weights less, so the
band rule becomes more likely to trigger.

## 7. Evaluation protocol (anti-overfitting)

- Walk-forward, transaction costs and FX costs included `[CALIBRATE]`.
- Last 3 years held out, looked at once at the end.
- Small parameter grid defined in advance. Pick a stable plateau, not the best point.
- Cash flows simulated (monthly contributions): report time-weighted return AND IRR.
- Metrics: vol, max drawdown, ES 95%, risk contributions, turnover, costs.
- Success = staying inside the risk limits at reasonable cost. NOT beating benchmarks in-sample.

## 8. Known data limitations

Free data (yfinance/Stooq): short ETF histories, listing-currency differences, possible
bad ticks, no quality guarantee. Proxies for older periods must be declared explicitly.

## 9. Results and observations log

Updated step by step as each module is built and tested. Each entry: date, module,
what was observed, which IPS parameter (if any) it affects, and whether the change was
decided BEFORE or AFTER seeing out-of-sample results (the latter must be flagged).

| Date | Module | Observation | IPS parameter affected | Decided before/after seeing OOS results |
|------|--------|-------------|------------------------|------------------------------------------|
| 2026-10-26 | `prm.config` | Profile loader implemented with validation. Rules enforced in code: drawdowns negative; `dd_review` no less severe than `dd_alert`; `dd_review` not deeper than `stop_contributing_dd` (so the review comes before the investor would stop contributing). The 9 unit tests pass. | none (rules only) | before (no market data used) |

2026-10-28, candidate universe v0 (`config/universe_candidates.yaml`): chosen by criteria only,
no performance data looked at. Observation: public aggregator pages disagree on basic figures
(for example the fund size of the EUR-hedged global aggregate ETF is reported between about
2.5 and 12 billion EUR), so every value is marked `verify` until checked against official
factsheets/KIDs. Also: the usual gold vehicle is an ETC, not a UCITS fund, and no accumulating
unhedged global aggregate ETF was found, so the hedged/unhedged comparison uses a distributing
class with total-return prices. Status: awaiting approval of the criteria.

2026-10-29, data check by the owner: `yfinance` returned 1738 daily rows for EUNL.DE (iShares Core
MSCI World, Xetra, EUR) from 2020-01-01 to 2026-10-29, with Close equal to Adj Close, as expected
for an accumulating ETF. The symbol EUNL.DE is therefore confirmed. The other symbols in
`universe_candidates.yaml` are guesses until tested with `python pipeline/01_sourcing.py --probe`.

2026-10-29, stage 01 (`pipeline/01_sourcing.py`) built: Yahoo source behind a replaceable interface,
CSV cache, quality checks that flag problems and never fix them silently (duplicates, gaps,
stale prices, large moves, adjustment jumps, short history). Checked with 44 offline unit tests using
synthetic data. Not yet run against real data for all assets. Data-quality decisions (drop an
ETF, accept a flagged event) must be written here when made.

2026-10-30, first real probe of stage 01 (run by the owner): 5 of 6 guessed Yahoo symbols exist
(IS3N.DE, IS3V.DE, PPFB.DE, XEON.DE, EUNA.DE) and are now confirmed in `universe_candidates.yaml`; EIMI.MI
also exists. AGGH.DE does not exist on Yahoo ("possibly delisted"), so the EUR-hedged global aggregate
ETF still needs a symbol (next guesses: AGGH.AS, AGGH.MI). Observations to follow up, none decided yet:
(1) the gold ETC on Xetra (PPFB.DE) has data only from 2021-07-16, about 5.3 years, close to the 5-year
minimum; a longer history would need another listing of the same fund and a declared proxy;
(2) the `stale_prices` flag appeared on XEON.DE, EUNA.DE and EIMI.MI: it may be genuine (an overnight-rate
ETF barely moves when rates are near zero) or a data problem, so the quality check now reports the longest
run and its dates; (3) the inflation-linked ETF starts on 2020-04-27 (about 6.5 years), which will limit the
common history of the implementable universe.

2026-10-31, first full run of stage 01 (owner): 6 of 9 universe assets downloaded and checked
(EUNL.DE, IS3N.DE, IS3V.DE, PPFB.DE, XEON.DE, EUNA.DE); status ok for 4, `stale_prices` warning for 2.
Details of the warnings (not decided yet, no correction applied): XEON.DE has 13 runs of 5+ identical
closes, longest 8 days in October 2013, a period of near-zero overnight rates, so rounding of a very
slowly moving price is a plausible explanation; EUNA.DE has 3 runs, longest 8 days in January 2018, two
months after the fund launch, so thin early trading or a Yahoo artefact are both possible. Both are far in
the past and do not affect recent data. To be settled by comparing with a second source (issuer NAV file).
Still without a Yahoo symbol: global_bond_hedged (AGGH.AS / AGGH.MI to test), global_bond_unhedged,
europe_equity.

No backtest results yet.

## 10. Changelog

- v0.1 — first draft from design conversation.
- v0.2 — tiered allocation methods (section 5), cash-like ETF for vol scaling,
  results log, open item on drawdown tolerance.
- v0.3 — separate developed/emerging equity ETFs; research vs implementable universe,
  with a subset rule that does not use backtest performance.
- v0.4 — global bonds; explicit FX risk policy (section 3.1).
- v0.5 — numbered pipeline layout; stage 01 (sourcing) built; first confirmed Yahoo symbol.
- v0.6 — selection funnel (all candidates -> best per category -> optimisation); about 20 candidate categories; `--find` to confirm symbols.
