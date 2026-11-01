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
| 23 | Safe part of the portfolio | ETFs in EUR only; no PLN assets (Polish bonds, PLN money funds) for now. EUR/PLN risk is accepted and measured, not removed | `[DECIDED]` |
| 22 | Selection rules | criteria-only ranking inside each category (stage 02; see section 9, 2026-11-01); performance never used | `[DECIDED]` |

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

2026-11-01, first `--find` run (owner), 28 candidate ETFs in 24 categories. Result: for every ISIN checked, the
fund name shown by Yahoo matched the expected fund, so those ISINs are now verified. A search by ISIN returns
only one listing (usually London, in USD), while a search by name shows several exchanges; `--find` now does
both. EUR listings found and recorded: EUNU.DE (global aggregate USD Dist, XETRA), VWCG.DE (Vanguard Developed
Europe, XETRA), CW8.PA (Amundi MSCI World, Paris, swap-based), IBCI.AS (EUR inflation-linked, Amsterdam),
UIC2.DE (UBS China technology, XETRA). For 14 ETFs only a London line (USD) was shown: EUR listings still to be
found. IEAC and IHYG are distributing funds: acceptable for research with dividend-adjusted prices, but they
fail the accumulating preference for an implementable portfolio. No result at all for the "Europe RAFI" and
"EUR Govt Bond 7-10yr" searches (new search texts set). Listing currency must be recorded per symbol before
stage 03: Xetra, Paris and Amsterdam lines are in EUR, London lines can be in USD, GBP or pence.

2026-11-01, CORRECTION of an error of mine (assistant): the symbol EUNA.DE had been assigned to the asset
`eur_govt_bond` (iShares Core EUR Govt Bond) on the strength of a weak web source. The second `--find` showed that
Yahoo names EUNA.DE as the iShares Core Global Aggregate Bond UCITS ETF EUR Hedged (Acc), i.e. the asset
`global_bond_hedged`; its first date, 2017-11-21, also matches that fund. So the data downloaded under
`eur_govt_bond` so far were in fact the global aggregate hedged fund, and the stale-price flag of January 2018
belongs to it too. Fixed: EUNA.DE now belongs to `global_bond_hedged` (the AGGH.AS and AGGH.MI listings have a
shorter Yahoo history, from 2021-05-17 and 2019-06-12), `eur_govt_bond` is unconfirmed again, and the universe
loader now refuses the same symbol on two assets. Lesson recorded: a symbol is confirmed only when the fund name
Yahoo shows matches the intended fund, never from a ticker seen on a third-party page.

2026-11-01, second `--find` (owner): XETRA listings confirmed for 10 more ETFs (XDWD.DE, XMME.DE, IS3R.DE,
IS3Q.DE, IQQ0.DE, IS3S.DE, IUSN.DE, XDWH.DE, XDWS.DE, IBCM.DE). Still without a EUR listing: acwi_ishares,
allworld_vanguard, eur_corp_bonds, eur_high_yield, us_short_treasury (new guesses to test with `--probe`),
and no result for europe_rafi and eur_govt_bond. The quality report now has a `currency` column (quote
currency according to Yahoo), needed before stage 03.

2026-11-01, probe and `--find` run 3 (owner). Confirmed by fund name: EUNH.DE (iShares Core EUR Govt Bond, XETRA,
distributing; accumulating class IEGS.MI on Milan). Symbols that exist on Yahoo but whose fund NAME has not been
checked yet (the old probe printed only rows and dates, which is not enough): IUSQ.DE (data from 2011-10-21),
VWCE.DE (2019-07-29), VWCE.MI, IEAC.AS and IEAC.MI (2010), IHYG.MI (2010-12-15). Symbols that do not exist:
EUNF.DE, IHYG.AS, IB01.DE, IB01.MI, IB01.AS; for the USD short Treasury ETF only the London line IB01.L remains.
Probe now prints the fund name and the quote currency. `stale_prices` flags appeared again on IUSQ.DE, VWCE.MI,
IEAC.MI and IHYG.MI (details now printed by the probe). `europe_rafi` found nothing twice: probably not available
as a UCITS ETF.

2026-11-01, probe with fund names (owner). Confirmed (name and currency match): IUSQ.DE, VWCE.DE, IEAC.AS,
IHYG.MI, IB01.L (USD, London). Findings: (1) IUSQ.DE has one frozen price for its first 116 days (2011-10-21
to 2012-04-02): not a real price series; (2) IB01.L has a +1883.8% daily move on 2019-02-22, two days after its first
date: the first rows are wrong; (3) the two Milan listings VWCE.MI and IEAC.MI (different funds, same exchange) show
the SAME stale run, 2022-09-12 to 2022-09-20, so it is probably an exchange or data-provider problem and not a
fund problem; (4) IHYG.MI has 15 identical closes in 2012-06-22 to 2012-07-12, not explained. Decision `[PROVISIONAL]`:
a new optional field `use_from` in `universe_candidates.yaml` tells stage 01 to ignore earlier rows of one asset.
It is set for IUSQ.DE (2012-04-03) and IB01.L (2019-02-22) and must be confirmed by looking at the first rows of the raw
files. The raw cache is never modified, and the field is shown in `quality_report.csv`. Rule: bad data are never
corrected silently; ignoring early rows is allowed only as a documented decision of this kind.

### 2026-11-01 — Stage 01 closed: findings of the full run (27 series downloaded) `[OBSERVED]`

Stage 01 is considered **finished**. The flags below are recorded, not fixed: nothing was corrected silently.
- `stale_prices` (runs of identical closes): XEON.DE, EUNA.DE, EUNU.DE, VWCG.DE, IHYG.MI, IB01.L. For XEON.DE (overnight
  rate) and the short-bond funds a flat price over a few days is plausible; for the others the cause is not known.
  Decision `[PROVISIONAL]`: keep the series, flag stays visible; revisit in stage 04 if returns look wrong.
- `large_daily_move`: the factor ETFs (IS3R, IS3Q, IQQ0, IS3S) in 2013-2014 look like early-history artefacts;
  XMME.DE +16.1% on 2025-10-24, UIC2.DE 24.2% on 2022-03-16 (China tech, a real market event is plausible),
  VWCG.DE 12.1% on 2020-03-12 (COVID crash, plausible). Not removed. Check against a second source if they matter.
- `zero_volume`: CW8.PA has 49% zero-volume days (swap-based fund on Paris): a liquidity signal, counted as a warning in stage 02.
- `short_history`: gold 5.3 years and China tech 5.7 years: usable but near the 5-year minimum.
- Distributing funds (EUNU, EUNH, IEAC, IBCM, IHYG): adjusted prices include dividends, but they fail the accumulating
  preference. Stage 02 ranks accumulating funds first; these stay research-only unless they are the only candidate.
- `europe_rafi`: no UCITS ETF found twice. `[OPEN]`: check justETF once, otherwise remove from the list.
- TER figures differ between aggregators (for example 0.12% against 0.19% for the same fund). Values in the YAML
  are provisional until checked on the KID. Stage 02 treats TER gaps below 0.05 percentage points as a tie.

### 2026-11-01 — Stage 02 (selection) built `[DECIDED]`

One ETF per category, by fixed rules in this order: eligible (usable data, history >= 5 years); accumulating first;
EUR listing; fewer data warnings; lower TER (ties below 0.05 pp); longer history; id. **Performance is never used.**
Fund size is not used because there are no verified figures. After the choice, a redundancy check lists winners whose
daily-return correlation is above 0.95 (almost the same exposure: the optimiser should not treat them as separate bets).
The winner is a starting point: the owner may override it with a written reason in this log.

### 2026-11-01 — First run of stage 02 on real data `[OBSERVED]`

23 winners out of 28 candidates in 24 categories. Where there was a real choice: `world_developed` -> XDWD.DE
(TER 0.12 against 0.20 of EUNL.DE; but the 0.12 figure is disputed, see above), `all_country` -> VWCE.DE (lower TER),
`emerging_markets` -> IS3N.DE (fewer data warnings). `europe_rafi` has no winner (no symbol).
Redundancy check: VWCE.DE vs XDWD.DE correlation 0.993 and VWCE.DE vs IS3Q.DE (quality factor) 0.974.
Meaning: the global ETF and the developed-world ETF are almost the same bet, and the factor ETFs add little diversification
inside equities. Rule `[PROVISIONAL]`: the optimiser may use EITHER the all-country ETF OR the developed + emerging pair, never both,
and factor/sector ETFs are research-only until stage 04 shows they add something.
Open: the factor ETFs show daily moves of 29-31% in 2013-2014 (first months after launch): probably early-history artefacts,
to inspect in the raw files before they enter any covariance estimate.

### 2026-11-01 — Stage 03 (FX and PLN returns) built `[DECIDED]`

PLN return = (1 + local return) x (1 + FX return), FX = NBP table A mid rate (PLN per 1 unit of the quote currency),
forward-filled so that no future rate is used. Variance split with log returns: FX share = cov(PLN, FX) / var(PLN);
local and FX shares add to 1; a negative FX share means the currency hedged the local risk. This is the measurement
required by section 3.1. Limit: only the QUOTE currency is separated; the USD risk inside a EUR-quoted World ETF stays
in the local part (to study in stage 04). Not tested against the live NBP API when written (no access from the build
environment): the first real run is the test, and any difference must be logged here.

### 2026-11-01 — Stage 03 first live run: FX risk is large for the "safe" assets `[OBSERVED]`

The NBP download works (4249 daily rates for EUR/PLN and USD/PLN, 2010-01-04 to 2026-10-30), so the open point of the
previous entry is closed. Annual volatility of the currency alone: EUR/PLN about 5.3-6.3%, USD/PLN about 10%.
Share of the PLN variance due to the currency (full sample): equities 1-8% (the currency is small next to 16% equity
volatility, and its correlation with equity returns is slightly negative, about -0.1: PLN tends to weaken when stocks fall,
which cushions EUR assets for a PLN investor); EUR bonds 37-73% (EUR corporate bonds: 4.0% local volatility becomes 7.1% in PLN);
the EUR overnight ETF 100% (0.3% local volatility, 6.3% in PLN); USD short treasuries 99%; gold 10%.
Consequence: for a PLN investor the EUR "safe" assets are mostly an EUR/PLN position. With an owner volatility target of
about 7%, a portfolio fully in EUR assets carries roughly 5-6% of currency volatility, so the FX variance limit of section 3.1
(30%, `[CALIBRATE]`) is likely to bind or to be too tight. Order of magnitude only, to confirm in stages 04-05.
Decision (owner, 2026-11-01) `[DECIDED]`: continue with EUR-quoted ETFs only; the currency risk is accepted and
reported as a risk contribution. PLN assets (Polish government bonds, PLN money funds) are NOT added for now; they remain
a possible later extension.

### 2026-11-01 — Stage 04 (risk analysis) built `[DECIDED]`

Measures only, no choices. Per asset in PLN: annual volatility, maximum drawdown on DAILY data (with peak, trough, recovery),
historical and Gaussian VaR/ES (95% and 99%, 1 day), skewness, excess kurtosis, worst day, dollar beta (regression of the EUR
return on the USD/EUR rate derived from the two NBP rates). Covariances on the common window of the chosen assets: sample,
EWMA (lambda 0.94) and Ledoit-Wolf shrinkage towards the average variance; the shrinkage and the condition numbers are printed.
Historical stress windows in `config/scenarios.yaml` (taper tantrum 2013, euro crisis 2011, China 2015, Q4 2018, COVID 2020,
rates shock 2022), chosen from known events and not from the data. The covariance window is set by the shortest history among
the chosen assets (gold 5.3 years, China tech 5.7 years): choose the assets with `--assets` to keep a longer window.
A bug found by the tests while writing it: a loss on the very first day was not counted in the drawdown; fixed.
Returns shown are descriptive: they never decide the selection.

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
- v0.7 — stage 01 closed (findings logged); stage 02 selection rules fixed; `accumulating` and `ter_pct` fields in the universe file.
- v0.8 — first real run of stage 02 logged; stage 03 (NBP rates, PLN returns, FX variance share) built.
- v0.9 — EUR-only decision; stage 03 live results (FX share); stage 04 risk analysis built.
