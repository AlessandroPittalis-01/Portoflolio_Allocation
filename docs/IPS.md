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
| `[SUPERSEDED]` / `[WITHDRAWN]` | replaced by a later decision / dropped by the owner |

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
| 10 | Vol target (owner profile) | 8-10% annual, measured in PLN (was 6-8%; raised by decision 24) | `[CALIBRATE]` |
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
| 22 | Selection rules | criteria-only ranking inside each category (stage 02; see section 9, 2026-11-01); performance never used | `[DECIDED]` |
| 23 | Safe part of the portfolio | ETFs in EUR only; no PLN assets (Polish bonds, PLN money funds) for now. EUR/PLN risk is accepted and measured, not removed | `[DECIDED]` |
| 24 | How risk is measured | in PLN, with EUR ETFs only; because EUR/PLN alone has 5-6% volatility, the owner target is raised from 7% to 9% (range 8-10%); the other profiles are shifted too (prudent 6.5%, balanced 9%, dynamic 12%) | `[DECIDED]` (owner chose option B, 2026-11-01) |
| 25 | Allocation universe (stage 05) | SUPERSEDED by 26: the 6 ETFs are no longer listed by hand | `[SUPERSEDED]` |
| 26 | Who chooses the ETFs | the code, by mathematical rules in `src/prm/allocation/choose.py`, never by performance. (1) eligible = `core` in the universe file, winner of its category in stage 02, EUR-quoted, usable data, history >= 5y; (2) cash = eligible cash-like ETF with the lowest PLN volatility; (3) inside each class (equity, bond, real) ETFs with correlation >= 0.90 (local-currency returns, average-linkage clusters) are the same exposure: only the medoid can enter; (4) groups are ordered: largest first, then maximin (lowest max correlation with the chosen ones); (5) max ETFs per class equity 2 / bond 3 / real 1, total <= 6; ties by id. Parameters in `config/portfolio.yaml`. Still to do in stage 06: repeat the choice inside the walk-forward with past data only, plus a stability rule | `[DECIDED]` (owner asked 2026-11-04: concentrated portfolio, ~6 ETFs, mathematical choice) |
| 27 | Proxies for short histories | WITHDRAWN by the owner on 2026-11-04: no proxies, only real data. Consequence: the common window starts 2021-07-19 and does NOT contain the COVID crash for gold and inflation-linked | `[WITHDRAWN]` |
| 28 | Risk budgets by class | equity 50% / bond 35% / real (gold) 15% of the portfolio RISK (not of the capital). Split equally among the ETFs of a class. Owner approved the numbers on 2026-11-04; reading as RISK shares to be confirmed by the owner. They are policy numbers, not tuned on results; the volatility target, the 40% cap and the equity cap 50% still apply on top | `[DECIDED]` (risk-share reading `[PROPOSED]`) |
| 29 | Benchmark 60/40 | fixed in `config/portfolio.yaml`: 60% allworld_vanguard + 40% eur_govt_bond, independent of the ETF choice, so the comparison does not move when the choice changes. Left untouched by volatility targeting and limits (the first version took the chosen ETFs and became 30% EM: not a fair benchmark) | `[DECIDED]` (owner 2026-11-04) |
| 30 | Second equity ETF: limited risk budget | the equity budget (50% of risk) is split 80% to the first ETF (global) and 20% to the second (emerging markets), i.e. 10% of total risk. Reason: the global ETF already holds about 10% emerging markets, so an equal split (25% of total risk each, as in the first run) is a large unjustified overweight. 20% is a policy number set before seeing results and not tuned; classes without `secondary_share` split equally | `[DECIDED]` (owner 2026-11-04; the 20% value is `[CALIBRATE]` in the backtest only as a robustness check, not to optimise) |
| 31 | Bonds: at most 2 ETFs, core 70% / second 30% | the core bond ETF (most representative, in practice broad euro government bonds) keeps 70% of the bond risk budget, the second (the most different one) 30%. Reason: in the 2026-11-04 run two of three bond slots were inflation-linked and carried twice the risk of the nominal bonds, while the bond class is meant to be the stable base. Structural reason, decided before any backtest | `[DECIDED]` (owner chose option A, 2026-11-04) |
| 32 | Backtest design (stage 06) | walk-forward at every month-end: choice of ETFs, covariance and weights redone with data up to that day; an ETF or class enters only after 504 days of history (so no proxies are needed and the test can include 2020); monthly contribution 2800 PLN (about 650 EUR); rebalancing by buying, sales only outside the band or when an ETF leaves; cost 10 bps per trade; no taxes. Parameters in `config/backtest.yaml`, declared before the first run. Success = staying inside the risk limits at reasonable cost, not beating the benchmark | `[PROPOSED]` (parameters `[CALIBRATE]`) |
| 33 | Bootstrap of the backtest | proposed by the owner 2026-11-04: stationary block bootstrap (resample whole dates in blocks, so correlations between ETFs and volatility clustering are kept) to get many alternative paths; use: distribution of max drawdown, probability of passing the review (-18%) and stop (-25%) thresholds, range of final wealth. It measures the sampling uncertainty of the SAME history, not regimes never seen. Planned in stage 07 after the first real run of stage 06; block length and number of paths declared in advance | `[PROPOSED]` |
| 34 | Stability rule and long benchmark | (a) an ETF already held keeps its place unless a challenger is better by more than 0.10 in correlation units; inside a group of the same exposure the held ETF represents the group; the previous core ETF stays core if its representativeness is within 0.10. Reason: the first real backtest changed the second bond ETF four times and swapped two ETFs with corr 0.99, and every sale is a taxable event in Poland; structural reason, the rule never looks at returns, margin declared before the re-run, not tuned. (b) a second benchmark `benchmark_60_40_long` (60% world_xtrackers + 40% eur_govt_bond) so the comparison covers the whole walk-forward including COVID. (c) new metrics: longest time below a previous peak, average class weights | `[DECIDED]` (owner approved 2026-11-05) |
| 35 | Core ETF of a class: broadest scope first | the first ETF of a class (core holding, keeps the larger risk budget) is the one with the broadest `scope` (broad = world / developed / all-country, regional = one region or country; field of the universe file), then the most representative. Reason: with two ETFs in a class representativeness is a tie decided by the id; in the first two real backtests this made emerging markets (em_equity) the core of the equity class from 2016 to 2021 (first run) and to 2023-10 (second run, kept by the stability rule), i.e. 80% of the equity risk in EM, including 2022. A flaw of the rule, found by reading the output, not a tuning on returns | `[DECIDED]` (flaw fix, 2026-11-05) |

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
   Reported as an FX risk contribution. Note (2026-11-01): with EUR ETFs only this limit may be too tight
   (see section 9). Until stage 05 shows the real FX shares it is REPORTED, not enforced.
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
| Annual vol target | `[CALIBRATE]` 8-10% in PLN (9% as the starting value) | see `config/profiles.yaml` for other profiles |
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
   Caveat (2026-11-01): the EUR overnight ETF has 6.3% volatility in PLN (all of it currency), so in PLN terms
   it lowers risk much less than a PLN cash position would. Vol scaling with it is weaker than it looks.
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
- Last 3 years held out, looked at once at the end. `[LIMIT 2026-11-04]` With about 5 years of common data plus the walk-forward warm-up, a separate hold-out is not possible: the whole walk-forward is run ONCE with declared parameters, and robustness is checked only with a few pre-declared variants (cost 5/10/25 bps, equity secondary share 10/20/30%), never to pick the best one.
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

### 2026-11-01 — Stage 04 first run on real data `[OBSERVED]`

Window of the covariances: 2021-07-19 to 2026-10-30 (1321 days, 23 assets), set by gold (PPFB.DE starts 2021-07-16). It contains
ONE regime, including the 2022 rates shock, so correlations between bonds and equities estimated here are the "bad" ones of 2022.
Ledoit-Wolf shrinkage 0.010 (many days, few assets); condition number 7043 (sample) -> 972 (Ledoit-Wolf).
Main numbers in PLN: global equity ETF 16.3% volatility, maximum drawdown -29.0%; EUR government bonds 8.0-8.6% volatility and
-26/-27% drawdown (still -21% below the peak); EUR overnight ETF 6.3% volatility, -12.7% drawdown; inflation-linked EUR-hedged
-32.4% drawdown; gold 17.7% volatility. Expected shortfall 99% is about 1.6 times the Gaussian one for equities: Gaussian formulas
underestimate tail losses. Stress: in 2022 equities (-8.7%) and bonds (-9% to -17%) fell together; only gold (+14%), the EUR
overnight ETF (+5.5%) and USD short treasuries (+23%) held. In the COVID crash the EUR overnight ETF gained +6.5% in PLN and in the
2011 episode +10.7%, only because the zloty weakened: the currency cushions EUR assets in crises, which is a feature of this investor's position.
Redundant pairs (correlation above 0.95): EUR govt 7-10y vs EUR govt broad 0.984; World vs All-World 0.993; World vs Quality 0.977.
Dollar beta is close to zero for equities and gold: this is NOT absence of dollar exposure (the dollar tends to rise when stocks fall, so the
two effects cancel in a regression, and the NBP midday fixing is not synchronous with the ETF close). Only unhedged global bonds show a visible
beta (0.22, R2 8%). Use fund factsheets for the exposure map; keep this number as a cross-check.
Stress scenarios of 2011, 2013 and 2015 are mostly empty: few of our ETFs existed. Proxies would be needed (not done).

Decision (owner, option B, 2026-11-01) `[DECIDED]`: the risk target is kept in PLN and raised to 9% for the owner (range 8-10%), see decision 24.
To verify in stages 05-06: that the drawdown rules (alert -10%, review -18%) are consistent with a 9% volatility; the "safe" EUR bond
ETFs alone already had drawdowns of -21% to -27% in PLN.

### 2026-11-01 — Factor ETFs: bad early data removed with `use_from` `[PROVISIONAL]`

Listing the daily moves above 12% (local currency): IS3R/IS3Q/IS3S show alternating moves of +-19% to +-31% from October to December 2014
(an up of +24% followed by a down of -21% is not a market, it is bad data), IQQ0 shows the same in February-April 2013. Rows before
2015-06-01 (momentum, last bad day 2015-05-08), 2015-01-02 (quality, value) and 2013-05-01 (low volatility) are now ignored through `use_from`.
Raw files are untouched. STILL OPEN: all four show +12.5% to +12.8% on 2017-06-05 (identical across four funds: a data or fund event, not a market
move) and IQQ0 shows +16.1% on 2025-10-24 followed by -13.8% on 2025-10-27 (a spike that reverses: a bad print). They are research-only
ETFs, so they do not block stage 05. To inspect the raw rows around those dates before any of these four enters a final portfolio.

### 2026-11-04 — Stage 04 re-run after the factor-ETF cleanup `[OBSERVED]`

With `use_from` the factor ETFs drop from 24-29% to 14.7-18.8% annual volatility and the excess kurtosis falls from 100-220 to 10-17
(low volatility stays at 60: the bad print of 2025-10-24 and the +12.5-12.8% move of 2017-06-05 on all four funds are still in the data, still OPEN).
All other numbers of the previous entry are unchanged (data now run to 2026-11-02). Redundant pairs: World vs All-World 0.993, World vs Quality 0.982,
EUR govt 7-10y vs broad 0.984.

### 2026-11-04 — Stage 05 (allocation) built `[DECIDED]`

Five methods on the 6 risky ETFs (equal weight, inverse volatility, risk parity/ERC, minimum variance with a cap, HRP), then SAME treatment for all:
cap per ETF inside the risky mix, mix with the cash-like ETF to reach the profile's volatility target in PLN (largest share of risky ETFs with
volatility <= target, no leverage, exact covariance because the cash ETF has 6% PLN volatility), then profile limits (max 40% per ETF, cash-like exempt;
equity cap 50% for the owner; any excess goes to cash). The 60/40 benchmark (All-World + EUR government bonds) is shown untouched, as a reference.
Covariance: Ledoit-Wolf, declared in advance (sample and EWMA available with `--cov`). No expected returns are used anywhere.
The stage shows NO returns on purpose: only weights, volatility, risk shares, FX share, in-sample drawdown and ES. It is a snapshot over the common
window of the 7 ETFs (limited by gold, about 5 years, one regime), so it describes the shape of each portfolio and proves nothing about performance.
Cases not covered yet: minimum CVaR (needs scenarios, tier 2), Black-Litterman views, covariance re-estimated through time (that is the backtest, stage 06).
If a method cannot reach the target without leverage the stage says so (status `below_target`), because comparing methods at different risk levels would break principle 1 of section 5.

### 2026-11-04 — Stage 05 first run on real data (window 2021-07-19 to 2026-11-02, 1349 days, Ledoit-Wolf) `[OBSERVED]`

Weights are long-only and add up to 100% in every row (smallest weight 1.6%, no leverage).
**Owner profile (target 9% in PLN): NO method reaches the target.** All five end with the risky mix at 100% and volatility 6.9% (min variance) to 7.8% (equal weight)
(status `below_target`). Reason: with ONE equity ETF out of six, risk-based methods hold only 10-17% in equity; the mix is mostly bonds and gold.
The 60/40 benchmark has 10.0% volatility, 80% of its risk is equity. This is a property of the universe plus equal-risk logic, not a bug:
risk parity depends on how many ETFs sit in each risk driver.
**In-sample drawdown:** risk-based mixes -19.0% to -21.3%, the 60/40 -17.1% despite its higher volatility (10.0% against 7.4%). The window contains 2022, when
EUR bonds lost 13-17% in PLN while global equities lost only 8.7%. One regime: not a conclusion about the methods, but it breaks the idea that "more bonds = smaller drawdown".
Every mix, including the 60/40, is at or beyond the owner's review threshold (-18%): the drawdown rules need recalibration in stage 06.
**FX share of the variance:** 48-62% for the owner mixes, 70-71% for the prudent ones, 26% for the 60/40. The FX limit of 30% (section 3.1) is not met by any risk-based
mix: with EUR bonds the currency is the main source of risk. The limit stays a reported number, it is not enforceable with this universe.
**Prudent profile (6.5%):** all methods reach the target with 16-37% in the cash-like ETF, which carries 11-27% of the portfolio risk (cash is not risk-free in PLN).
Drawdowns -15.5% to -17.8% against a prudent review level of -12%: that level is not reachable either.
**Method notes:** risk parity gives exactly 16.7% of risk to each ETF (check passed). Minimum variance concentrates: 40% corporate bonds + 40% hedged global bonds,
effective number of positions 3.0. HRP holds most in hedged global bonds (31%) and inflation-linked (22%).
Open decisions: how to handle a target that equal-risk methods cannot reach (risk budgets by class, a lower target, or more equity ETFs); proxy history to extend
the backtest before 2021 (gold, inflation-linked, All-World start in 2019-2021); what to do with the FX limit and the drawdown thresholds.

### 2026-11-04 — Direction chosen after the first stage-05 run `[PROPOSED]`

Owner decisions: keep the real series for the latest snapshot, add proxies only for the backtest, cover at least the COVID crash, adapt the universe because return matters,
and let the allocator choose the ETFs mathematically. Critical notes recorded here: (1) the common window of the 7 current ETFs starts 2021-07-19, so it does NOT contain the COVID crash
(Feb-Mar 2020) and holds a single regime (the 2022 rates shock); (2) choosing among ~20 candidates on 5 years of data invites selection bias, so the choice must be done inside the walk-forward
with past data only; (3) nearly identical ETFs (correlation 0.97-0.99) swap on noise, hence clustering first; (4) return is pursued through the equity risk budget, not by picking ETFs that did well;
(5) any change of the universe made AFTER seeing the first result is a post-hoc choice and is declared as such.
Built so far: risk budgeting (`risk_budget`, class budgets split inside the class) and the `proxy_for` field in the universe file; proxy candidates for gold (London USD line of the same fund) and
inflation-linked (Dist class of the same fund) are in the file, symbols still to confirm with `--probe` / `--find`. Not built yet: proxy splicing with overlap validation, the selection engine, the walk-forward backtest.

No backtest results yet.

### 2026-11-04 — ETF choice by rule and class risk budgets built `[DECIDED]`
Proxies removed from code and universe (decision 27 withdrawn). Every candidate now has `asset_class` and `core` (13 non-core, each with its reason in the YAML). `choose.py` picks the ETFs of each class by correlation groups, medoid and maximin (decision 26); stage 05 writes `etf_choice.csv` with the reason for every candidate and adds the `risk_budget` method (equity 50 / bond 35 / real 15, decision 28). The 60/40 benchmark is now 60% equity ETFs + 40% bond ETFs chosen by the same rules. Not yet run on real data: the first real result will be logged here. Limit to remember: with one window of about 5 years (one regime, 2022) the choice can change if the window changes; stage 06 must repeat it with past data only.

### 2026-11-04 — First real run of the ETF choice (window 2021-07-19 to 2026-11-02) `[OBSERVED]`
Chosen: equity allworld_vanguard + em_equity; bonds eur_corp_bonds, inflation_linked, eur_inflation_linked; gold; cash xeon (cash_like, PLN vol 6.3%). xtrackers World was dropped as the same exposure (corr 0.99). With `risk_budget` the risk shares came out exactly 25/25 equity, 11.7 x3 bonds, 15 gold; capital: equity 36.5%, bonds 51%, gold 12.6% (the earlier guess of 25-30% equity was wrong). Owner profile: nothing reaches exactly 9% (no leverage); `risk_budget` 8.5% and `equal_weight` 8.6% are inside the 8-10% range, the others 7.4-7.9%. FX share of variance 36.8% (limit 30%); in-sample max drawdown -17.6%. Prudent: 6.5% reached with about 44% cash-like, drawdown -14% vs -12% goal.
Two flaws found by reading the output, both fixed the same day: (1) first bond pick was alphabetical, which dropped eur_govt_bond and global_bond_hedged (fix: decision 26 point 4); (2) equal split of the equity budget made EM 25% of total risk (fix: decision 30). The benchmark became 30% EM (fix: decision 29). All numbers are in-sample, one regime (2022).

### 2026-11-04 — Stage 06 (walk-forward backtest) built `[DECIDED]`
`src/prm/backtest/` (simulate, engine, settings, report), `config/backtest.yaml`, `pipeline/06_backtest.py`; allocation logic moved into `prm.allocation.build.allocate`, used by stages 05 and 06. Month-end walk-forward without look-ahead in the allocation (tested: changing future data does not change past weights). Outputs: two summary tables (each strategy from its own start; common period from the benchmark start), choices over time, weights, daily TWR. Metrics: TWR, IRR, volatility, max drawdown, ES95, days below the alert/review drawdown, costs, turnover (sales only), months with sales, stability of the chosen set. Remaining look-ahead: stage-02 category winners (TER and flags of today) and the `core` list. Not yet run on real data.

### 2026-11-04 — Stage 06 first real run: owner profile, 2016-06-30 to 2026-11-04, 10 bps, Ledoit-Wolf `[OBSERVED]`
Walk-forward 126 month-ends (77 skipped before 2016-06: no equity ETF with 2 years of history). The walk-forward includes COVID (2020) and 2022 without proxies. The risky set changed 6 times: young ETFs entering (world_xtrackers 2016-08, allworld_vanguard 2021-07, gold 2023-07) and the second bond ETF changing four times (eur_corp_bonds, global_bond_hedged, eur_corp_bonds, inflation_linked). Gold class absent until 2023-07 (7 of 10.5 years untested).
Full period (after costs): risk_budget TWR 4.2%, IRR 5.4%, vol 8.0%, max drawdown -17.2%, 20% of days below -10%, never below -18%, costs 1,020 PLN on 352,800 contributed; equal_weight TWR 5.3%, vol 8.9%, drawdown -17.1%; inverse_vol, risk_parity, hrp, min_variance had drawdowns of -19% to -21% and 2.5-8% of days below the -18% review line (they load on euro bonds, which fell with equities in 2022). Worst drawdown of any strategy -21.4%: the -25% stop-contributing level was never reached.
Common period from 2021-08 (60/40 benchmark available): benchmark TWR 4.8%, vol 9.9%, drawdown -17.6%, 32% of days below -10%; risk_budget TWR 3.6%, vol 8.2%, drawdown -16.6%, 37% of days below -10%; equal_weight TWR 4.6%, drawdown -14.6%, 24% of days below -10%. IRR (7.6-8.5%) is far above TWR (2.4-4.6%) because the contributions bought after the 2022 fall: IRR flatters the timing of contributions, TWR measures the strategy.
Reading (not a performance test, one history): (1) volatility-based weighting (min variance, HRP, inverse vol, risk parity) did WORSE on drawdown than equal weight, because low volatility means long-duration bonds and 2022 was a rates shock; (2) risk_budget cut volatility and depth a little versus 60/40 but spent MORE days below -10%; (3) the -10% alert is breached 20-37% of days, so it is too tight for this universe: a calibration question, to be answered with the bootstrap distribution (decision 33) and not by tuning on this run; (4) costs are small (about 0.3% of contributions in 10 years) but 6 set changes and sales are taxable events not modelled here; (5) 1/N is hard to beat in a short sample, differences between risk_budget and equal_weight are not significant.
Open: incumbent (stability) rule for the choice, a long benchmark leg (world_xtrackers) to compare over the full period, drawdown duration and class weights over time in the report, bootstrap (stage 07).

### 2026-11-05 — Stability rule, long benchmark and extra metrics built `[DECIDED]`
After the first real run of stage 06 (see above) three structural changes, decided by the owner, written down before the re-run: decision 34 (a), (b), (c). The first-run numbers stay in this log as the "before" picture; the re-run is compared with them, but the stability margin is NOT to be tuned on the re-run (one value, 0.10; sensitivity 0.05 / 0.15 only as a robustness check). New files: `backtest_class_weights.csv`; new columns: `max_underwater_years`.

### 2026-11-05 — Stage 06 second real run (stability rule, long benchmark): worse result, and why `[OBSERVED]`
Risky set changes 5 (was 6). Full period: risk_budget TWR 3.5% (was 4.2%), vol 8.0%, max drawdown -20.7% (was -17.2%), 6.2% of days below -18% (was 0%), longest time under water 4.2 years; equal_weight TWR 5.2%, drawdown -17.1%; min_variance/inverse_vol/risk_parity/hrp -19.7% to -20.8%. Average class weights: risk_budget bonds 58%, equity 34%, gold 4.5% (gold only from 2023-07), cash 3%. New long benchmark (60% world_xtrackers + 40% eur_govt_bond), 2016-09 to 2026-11: TWR 7.2%, vol 10.2%, drawdown -18.3%, 16% of days below -10%, no sales, 347 PLN of costs; it beat every risk-based strategy by 2-4 points a year with a similar drawdown.
Cause of the worse result (found by reading the order of the chosen ETFs): em_equity was the CORE of the equity class (80% of the equity budget) from 2016 until 2023-10. With only two equity ETFs available (em_equity from 2014, world_xtrackers from 2016-08) the representativeness criterion is a tie, decided by the alphabetical id; the first run had the same flaw until allworld_vanguard entered in 2021-07, the second run kept em_equity as core through the stability rule. Fix: decision 35 (scope). The two earlier runs are therefore both affected and their comparison with the benchmark is not reliable; the next run is the first with a valid core.
Lesson for the method: tie-breaks by id hide arbitrary choices; read the choice table of every run, not only the performance table.

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
- v0.10 — stage 04 first run logged; decision 24 (risk in PLN, owner target 9%); `use_from` for four factor ETFs.
- v0.11 — stage 04 re-run logged; stage 05 allocation built (5 methods, same target and limits, no returns shown); decision 25.
- v0.12 — stage 05 first real run logged: target not reached by risk-based methods, FX limit and drawdown thresholds in conflict with the universe.
- v0.13 — decisions 26-28 proposed (allocator chooses ETFs, proxies, class risk budgets); risk budgeting and `proxy_for` built.
- v0.14 — decision 26 decided (rule-based choice per class), 27 withdrawn (no proxies), 28 decided (risk budgets 50/35/15); `choose.py`, `asset_class`/`core` labels, `risk_budget` method in stage 05; proxy code removed.
- v0.15 — first real run read; decision 26 (first ETF = most representative), 29 (fixed 60/40 benchmark), 30 (second equity ETF at 20% of the equity risk budget).
- v0.16 — decision 31 (bonds max 2, core 70% / second 30%), 32 (backtest design); stage 06 built; hold-out limit noted.
- v0.17 — decision 33 proposed (bootstrap); stage 06 fix: a closed-exchange day (NaN return) leaves the held ETF unchanged instead of raising an error.
- v0.18 — decision 34 (stability rule, long benchmark, extra metrics); stage 06 first real run logged.
- v0.19 — decision 35 (core ETF = broadest scope, then most representative; `scope` field); second real run of stage 06 logged.
