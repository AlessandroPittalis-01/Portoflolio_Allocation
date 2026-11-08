# Methodology: the mathematics behind every stage

> Methodological and educational project. Not personalised financial advice.
> Rule (IPS decision 41): every stage that is built or changed updates this file, with the formulas that the code
> implements, the assumptions, and the limits. If code and this file disagree, it is a bug in one of them.
> The IPS (`docs/IPS.md`) says WHAT was decided and why; this file says HOW each number is computed.

**Contents**

0. Notation and conventions
1. Returns, currency and the FX decomposition (stage 03)
2. ETF selection by criteria (stage 02)
3. Covariance estimation and risk contributions (stages 04, 05)
4. Choice of ETFs inside each class (stage 05)
5. Allocation methods, risk budgets, volatility target, limits (stage 05)
6. Walk-forward backtest (stage 06)
7. Stationary block bootstrap (stage 07)
8. EUR/PLN hedge model (stage 08)
9. VaR and ES models (stage 09)
10. Backtesting of VaR and ES (stage 10)
11. Risk factors and variance attribution (stage 11)
12. Stress tests (stage 12)
13. Further risk metrics (stage 13)
14. Risk limits and monitoring report (stage 14)
15. Robustness variants (stage 15)
16. Where the methods are weak (summary)
17. References

---

## 0. Notation and conventions

* Time is in trading days $t=1,\dots,T$; a year has $252$ trading days. A daily return of asset $i$ is $r_{i,t}$ (simple
  return $P_{i,t}/P_{i,t-1}-1$ unless stated otherwise).
* Vectors are columns. $w$ is the weight vector (sum $1$, long-only, no leverage, so $w_i\ge 0$). $\Sigma$ is the
  covariance matrix of daily returns, $\Sigma_{\rm ann}=252\,\Sigma$, $\sigma_p=\sqrt{w^\top\Sigma_{\rm ann}w}$ the annual
  portfolio volatility.
* **Losses are positive numbers** in every risk measure: $\mathrm{VaR}=0.02$ means a loss of $2\%$.
* All returns that the risk stages use are **in PLN** (the investor's currency), unless the text says "local".
* No expected return is ever used to choose ETFs or weights (IPS golden rule). Returns appear only in descriptive
  tables and in the backtest as an outcome.

---

## 1. Returns, currency and the FX decomposition (stage 03)

An ETF quoted in EUR has local return $r^{\rm loc}_t$. The EUR/PLN rate $S_t$ (PLN per 1 EUR, NBP table A) gives the
currency return $s_t=S_t/S_{t-1}-1$, where $S_t$ is the last published rate on or before day $t$ (never a future
one). The PLN return is

$$1+r^{\rm pln}_t=(1+r^{\rm loc}_t)(1+s_t)\quad\Longrightarrow\quad r^{\rm pln}_t=r^{\rm loc}_t+s_t+r^{\rm loc}_ts_t .$$

In **log returns** the product becomes a sum, $\ell^{\rm pln}=\ell^{\rm loc}+\ell^{\rm fx}$, so the variance splits exactly:

$$\mathrm{Var}(\ell^{\rm pln})=\mathrm{Cov}(\ell^{\rm pln},\ell^{\rm loc})+\mathrm{Cov}(\ell^{\rm pln},\ell^{\rm fx}),\qquad
\text{FX share}=\frac{\mathrm{Cov}(\ell^{\rm pln},\ell^{\rm fx})}{\mathrm{Var}(\ell^{\rm pln})},$$

and the local share is $1-$ FX share. A negative FX share means the currency moved against the local return in that
period (it cushioned the PLN investor). For a portfolio with fixed weights the same ratio is computed on the
portfolio series, with $r^{\rm fx}_p=r^{\rm pln}_p-r^{\rm loc}_p$.

Returns are computed **between the ETF's own consecutive trading days**: a holiday of another exchange never creates
a fake zero or a missing value. Stage 03 writes `returns_local.csv` and `returns_pln.csv` as simple returns
($e^{\ell}-1$).

**Limit.** Only the *quote* currency is separated. A EUR-quoted World ETF still holds USD assets inside, and that
hidden dollar risk is part of its "local" return (stage 04 estimates a USD beta).

---

## 2. ETF selection by criteria (stage 02)

Inside each category the best candidate is picked with a **lexicographic ranking**: the first rule on which two
candidates differ decides. The order is fixed in advance: (0) hard eligibility (data usable, history $\ge 5$ years);
(1) accumulating share class (Belka tax is deferred); (2) quote currency equal to the preferred one (EUR); (3) fewer
data-quality warnings; (4) lower TER, where differences below $0.05$ pp count as a tie; (5) longer history; (6)
alphabetical id (only to be reproducible).

**No performance is used** (no return, Sharpe, drawdown): choosing the ETF that "did best" is data snooping and would
make the later backtest look better than it is. Known remaining look-ahead: TER and flags are today's values.

---

## 3. Covariance estimation and risk contributions (stages 04, 05)

Let $X$ be the $T\times p$ matrix of daily returns on a **common window** (all assets have a value on every row).

**Sample covariance.** $S=\frac{1}{T-1}\sum_t (x_t-\bar x)(x_t-\bar x)^\top$.

**EWMA (RiskMetrics).** Zero mean, weights decreasing geometrically into the past, $\lambda=0.94$:

$$\Sigma^{\rm EWMA}=\sum_{t=1}^{T}\omega_t\,x_tx_t^\top,\qquad \omega_t=\frac{\lambda^{T-t}}{\sum_{u}\lambda^{T-u}} .$$

**Ledoit–Wolf shrinkage towards $\mu I$** (the default in `config/portfolio.yaml`). With $x_t$ demeaned,
$S=\frac1T\sum_tx_tx_t^\top$, $\mu=\mathrm{tr}(S)/p$:

$$\hat\Sigma=(1-\delta)\,S+\delta\,\mu I,\qquad
\delta=\frac{\min(b^2,d^2)}{d^2},\quad d^2=\|S-\mu I\|_F^2,\quad
b^2=\frac1{T^2}\sum_{t}\|x_tx_t^\top-S\|_F^2 .$$

$d^2$ is the distance between the sample matrix and the target; $b^2$ estimates the noise of the sample matrix.
$\delta\in[0,1]$: with little data or many assets the estimate is pulled towards a diagonal matrix, which makes
optimisers more stable. The matrix is positive definite.

**Risk contributions (Euler).** $\sigma_p=\sqrt{w^\top\Sigma w}$ is homogeneous of degree $1$ in $w$, so

$$\sigma_p=\sum_i w_i\frac{\partial\sigma_p}{\partial w_i}=\sum_i\underbrace{\frac{w_i(\Sigma w)_i}{\sigma_p}}_{RC_i},\qquad
\text{risk share}_i=\frac{RC_i}{\sigma_p}=\frac{w_i(\Sigma w)_i}{w^\top\Sigma w},\ \ \sum_i\text{risk share}_i=1 .$$

An asset with $10\%$ of the money can carry $40\%$ of the risk: this is the idea behind risk-based allocation.

---

## 4. Choice of ETFs inside each class (stage 05, `choose.py`)

The owner fixes the **classes** (equity, bond, real = gold) and their risk budgets. A rule picks *which* ETFs represent
each class, with rules written before any result (IPS decisions 26, 31, 34, 35).

1. **Eligibility.** `core` flag in the universe file, winner of its category (stage 02), quoted in EUR, usable data,
   enough history (the as-of version is used in the backtest: $\ge504$ days).
2. **Cash-like ETF** = the eligible cash-like ETF with the lowest volatility in PLN. It is used only to scale risk.
3. **Same exposure.** Inside a class, similarity is the correlation $\rho_{ij}$ of the daily **local** returns on the
   class's common window. With distance $d_{ij}=1-\rho_{ij}$, average-linkage clustering is cut at
   $d\le1-\rho_{\max}$ ($\rho_{\max}=0.90$): ETFs with $\rho\ge0.90$ are the same exposure; only the **medoid**
   (highest average correlation with its group) can enter.
4. **First ETF (core holding).** For equity, `scope` first (`broad` before `regional`), then the most
   **representative**: the highest average correlation with all other eligible ETFs of the class. Scope comes first
   because with two ETFs the representativeness is symmetric (a tie) and the id would decide.
5. **Next ETFs** by **maximin diversification**: choose the group whose medoid has the lowest maximum correlation
   with the ETFs already chosen. At most `max_etfs` per class (equity 2, bond 2, real 1).
6. **Stability** (only when the choice is repeated in time). An incumbent keeps its place unless the challenger is
   better by more than `switch_margin` $=0.10$ in correlation units; inside a group the incumbent represents the group.
   This avoids selling and re-buying (and paying tax) for differences that are noise.

Ties are broken by id, so the result is deterministic. **Limit:** any tie-break by id hides an arbitrary choice; the
rules were extended (scope, stability) whenever a real run showed one.

---

## 5. Allocation methods, risk budgets, volatility target, limits (stage 05)

All methods need only $\Sigma$ of the risky ETFs; weights are long-only and sum to $1$.

**Equal weight.** $w_i=1/n$.

**Inverse volatility.** $w_i\propto 1/\sigma_i$. Ignores correlations.

**Risk budgeting.** Given budgets $b_i>0$, $\sum b_i=1$, find $w>0$ with risk shares $=b_i$. Solve the convex problem
(Spinu, 2013)

$$\min_{w>0}\ \tfrac12\,w^\top\Sigma w-\sum_i b_i\ln w_i .$$

The first-order condition $\Sigma w-b/w=0$ gives $w_i(\Sigma w)_i=b_i$. Summing over $i$: $w^\top\Sigma w=\sum b_i=1$.
After rescaling $w\leftarrow w/\sum w$ the risk shares are $w_i(\Sigma w)_i/(w^\top\Sigma w)=b_i$, as wanted. The log term
keeps all weights strictly positive (long-only, no leverage). With $b_i=1/n$ this is **risk parity** (equal risk
contribution). The problem is solved by L-BFGS-B with the analytic gradient.

**Minimum variance with cap.** $\min_w w^\top\Sigma w$ s.t. $\sum w=1$, $0\le w_i\le 0.40$ (SLSQP). Without the cap it
concentrates in one or two assets.

**Hierarchical Risk Parity** (López de Prado, 2016). (i) Correlation distance
$d_{ij}=\sqrt{\tfrac12(1-\rho_{ij})}$; (ii) single-linkage clustering orders the assets so similar ones are adjacent
(quasi-diagonalisation); (iii) recursive bisection: for a cluster split into halves $L,R$ with inverse-variance
weights inside each half, $V_L=\tilde w_L^\top\Sigma_{LL}\tilde w_L$, $\tilde w_L\propto 1/\mathrm{diag}\,\Sigma_{LL}$, the
weights of $L$ are multiplied by $\alpha=1-\frac{V_L}{V_L+V_R}$ and those of $R$ by $1-\alpha$. No matrix inversion.

**Class risk budgets and the second ETF.** The class budgets $B_{\rm class}$ (decision 36: equity $0.60$, bond $0.28$,
real $0.12$, *as shares of risk*) are split inside the class: with $s$ the `secondary_share`, the first ETF gets
$(1-s)B_{\rm class}$ and the other ETFs share $sB_{\rm class}$ equally (equity $s=0.20$, bond $s=0.30$). A class with no
eligible ETF is dropped and the budgets are rescaled to sum to $1$.

**Equity risk budget by an ex-ante rule (decision 36).** For a grid of equity budgets $e$ the other classes keep their
proportions ($0.35:0.15$ of $1-e$); the final volatility $\sigma(e)$ after targeting is computed with $\hat\Sigma$ only.
The chosen $e$ is the **smallest** with $\sigma(e)\ge$ target (within $5\times10^{-4}$), rounded up to a multiple of
$5\%$, found **once** and written in the IPS before the backtest is run.

**Volatility target without leverage.** The risky mix $w^{\rm risky}$ is blended with the cash-like ETF $c$:

$$w(k)=k\,w^{\rm risky}+(1-k)\,e_c,\qquad k^\*=\max\{k\in[0,1]:\sigma_p(w(k))\le\sigma^\*\}$$

on a grid of $1001$ values of $k$, with the **exact covariance** (the cash-like ETF has $6\%$ volatility in PLN of its own,
the EUR/PLN rate, and is correlated with the other EUR assets). If $\sigma_p(w(1))<\sigma^\*$ the status is
`below_target`: with no leverage the target cannot be reached.

**Limits** (applied to the final weights): $w_i\le0.40$ for every ETF except the cash-like one, total equity weight
$\le0.50$; any excess goes to the cash-like ETF, so risk can only go down.

**Limits of the method.** The covariance is estimated in-sample; risk-based weights inherit its errors; the
volatility target is in PLN and cannot go below about $5.5$–$6\%$ because of the EUR/PLN risk of every EUR asset.

---

## 6. Walk-forward backtest (stage 06)

**No look-ahead.** On each month-end date $d$ the whole procedure (eligibility, ETF choice, covariance, weights,
targeting, limits) is redone with data **up to $d$ only** (at least $504$ days of history); a test checks it.

**Portfolio simulation.** Values $v_i$ per ETF drift with the market between rebalance dates. At a rebalance date, with
contribution $C$, total $V=\sum v_i+C$ and target weights $\tau_i$:

* an ETF is **sold** only if $\tau_i=0$ (left the portfolio) or $v_i/V-\tau_i>0.05$ (band); it is sold down to $\tau_iV$;
* the pool $C+\sum\text{sales}\cdot(1-c)$ buys the underweight ETFs pro rata to their gaps
  $g_i=\max(\tau_iV-v_i,0)$, paying $c=10$ bps on every traded amount: purchased amount
  $=g\cdot\min\!\big(1,\ \tfrac{\text{pool}/(1+c)}{\sum g}\big)$.
* The trades happen at the close of the date, and the next day's return is the first one earned.
* A missing return of a held ETF (closed exchange) leaves its value unchanged that day. No taxes (accumulating ETFs
  defer them) and no PLN→EUR conversion cost on the contributions: both are optimistic.

**Time-weighted return (TWR).** On day $t$ the market return of the portfolio is
$R^{\rm mkt}_t=\frac{\sum_iv_{i,t}}{\sum_iv_{i,t-1}}-1$ (values after the previous day's trades). On a rebalance day the
trading cost $c_t$ (money paid) lowers it: $R_t=(1+R^{\rm mkt}_t)\big(1-c_t/V^{\rm before}_t\big)-1$. Contributions never
enter the return (they are cash flows), so they do not hide a drawdown. Annual TWR $=\prod_t(1+R_t)^{252/N}-1$.

**IRR.** The rate $\rho$ that solves $\sum_k C_k(1+\rho)^{\tau_{\rm end}-\tau_k}=V_{\rm final}$ (years from the first
contribution, found with Brent's method). It is *money-weighted*: it flatters or penalises the timing of contributions.

**Risk outcomes** (on the TWR series):
volatility $\sigma=\mathrm{std}(R_t)\sqrt{252}$;
drawdown $D_t=W_t/\max_{u\le t}W_u-1$ with $W_t=\prod_{u\le t}(1+R_u)$ (daily data; monthly data hide the worst days);
maximum drawdown $\min_tD_t$; ES$_{95}$ of the daily return; share of days with $D_t\le$ alert and $\le$ review;
**longest time under water** (longest run with $D_t<0$); **turnover** $=\frac{\text{money sold}}{\overline V\cdot\text{years}}$
(contributions are not turnover).

**Benchmarks.** Fixed $60/40$ (all-world ETF + euro government bonds) and a longer $60/40$ with an older World ETF.
Target weights $0.6/0.4$ on every month-end, run through the **same simulation** (same contributions, $\pm5$ pp band,
rebalancing by buying, same costs), so the comparison is like for like. The benchmark is not volatility-targeted.

**Limits.** One history, one regime sequence; no hold-out period; the look-ahead left is the stage-02 winners (today's
TER) and the `core` list; the result is a sample outcome, not a test of skill.

---

## 7. Stationary block bootstrap (stage 07)

Aim: how much do the risk outcomes depend on the **order** of the days, given the days we have seen? (Politis and
Romano, 1994.) It resamples the daily TWR series of the strategies produced by stage 06.

**Resampling.** For a path of $H$ days: the first block starts at a uniformly random date; at each next day, with
probability $p=1/m$ a **new block** starts at a new uniformly random date, otherwise the path takes the day after the
previous one (circular indexing). Block lengths are geometric with mean $m$ ($m=21$ days; sensitivity $10$ and $63$).
The **same dates** are drawn for all strategies (paired), so their correlations and the clusters of bad days are kept.

**Metrics per path.** Wealth $W_t=\prod_{u\le t}(1+R_u)$, peak including the starting value $1$, drawdown, maximum
drawdown, longest under-water run, annual TWR $W_H^{252/H}-1$, annual volatility, money multiple (final value / money
paid, with a unit contribution every $21$ days), and indicators $\mathbb 1\{\max DD\le x\}$ for the alert, review and
stop thresholds. Over $B=2000$ paths one gets quantiles and probabilities
$\hat P=\frac1B\sum_b\mathbb 1\{\cdot\}$ (a threshold crossed by almost every path is routine, not an alert).
Differences between two strategies are computed **on the same path**, then summarised (median, $5$–$95\%$ band,
share of paths where the gap is positive).

**Threshold grid.** $P(\max DD\le x)$ for $x\in\{-10,-12.5,\dots,-30\}\%$; it is used to calibrate the alert/review
thresholds (decision 37).

**Limits.** It reshuffles one history: a regime that is not in the sample cannot appear. The resampled paths keep the
historical mean return, so they measure sampling noise, **not** a forecast. The choice of ETFs is not repeated on each
path. It probably understates the drawdown of bond-heavy portfolios in a trending-rate regime.

---

## 8. EUR/PLN hedge model (stage 08)

Per EUR-quoted asset with hedge ratio $h\in[0,1]$ (by class), daily:

$$1+r^{\rm hedged}=(1+r^{\rm loc})\Big(1+(1-h)\,s+h\,c\Big),\qquad c=\frac{\Delta_{\rm rate}-\kappa}{252},$$

where $s=\frac{1+r^{\rm pln}}{1+r^{\rm loc}}-1$ is the EUR/PLN return, $\Delta_{\rm rate}$ the **assumed** PLN−EUR interest
differential (grid $0,2,4\%$ a year) and $\kappa$ the **assumed** all-in hedge cost ($0.3\%$ a year). The idea: a PLN
investor who sells EUR forward earns the forward points, about the rate differential ($F=S\frac{1+i_{\rm PLN}}{1+i_{\rm EUR}}$).
Simplification: the hedge notional follows the position value every day, so there is no cross term between hedge P&L and
local return; $h=0$ returns $r^{\rm pln}$ exactly. The cash-like ETF is not hedged; gold keeps its USD risk.

For each scenario the **same allocation is solved again** on the hedged returns (same rules, target, limits), so the
result shows both the risk removed and how the volatility target reuses that room. Reported: model volatility, FX share
of variance, maximum drawdown, ES, hedged notional $\sum_iw_ih_i$, and the assumed effect
$\sum_iw_ih_i(\Delta_{\rm rate}-\kappa)$ on the yearly return.

**Limits.** A model, not an instrument: margins, taxes, rolling, and the real availability of PLN-hedged products are not
modelled; carry and cost are assumptions; a drawdown improvement of the same size as the volatility reduction is *not* a
free lunch.

---

## 9. VaR and ES models (stage 09, `var_models.py`)

For a daily return $R$ and level $\alpha$ (95%, 99%): $\mathrm{VaR}_\alpha=-q_{1-\alpha}(R)$, and
$\mathrm{ES}_\alpha=-\mathbb E[R\mid R\le q_{1-\alpha}(R)]\ \ge\ \mathrm{VaR}_\alpha$.
Horizon: one day; weights fixed; PLN returns.

**Historical.** Empirical quantile and tail mean of the window.

**Gaussian.** $R\sim N(\mu,\sigma^2)$, $z=\Phi^{-1}(1-\alpha)<0$:
$\mathrm{VaR}=-(\mu+\sigma z)$, $\ \mathrm{ES}=-\mu+\sigma\,\frac{\varphi(z)}{1-\alpha}$.

**EWMA volatility.** $\sigma_t^2=\lambda\sigma_{t-1}^2+(1-\lambda)R_{t-1}^2$, $\lambda=0.94$, initialised with the variance of
the first 30 days. $\sigma_t$ uses returns **up to $t-1$** only; the forecast for tomorrow is
$\sigma_{T+1}^2=\lambda\sigma_T^2+(1-\lambda)R_T^2$.

**GARCH(1,1).** $R_t=\sigma_t\varepsilon_t$, $\ \sigma_t^2=\omega+\alpha R_{t-1}^2+\beta\sigma_{t-1}^2$, zero mean, **variance
targeting** $\omega=\bar\sigma^2(1-\alpha-\beta)$ with $\bar\sigma^2=\frac1T\sum R_t^2$ (so only $\alpha,\beta$ are free).
Gaussian quasi-maximum likelihood, minimised over $\alpha,\beta\ge0$, $\alpha+\beta<1$:

$$-\ell(\alpha,\beta)=\tfrac12\sum_t\Big(\ln\sigma_t^2+\frac{R_t^2}{\sigma_t^2}\Big).$$

Persistence $\alpha+\beta$ (near $0.97$ for a diversified portfolio) says how slowly volatility shocks fade; the
long-run annual volatility is $\sqrt{252\,\bar\sigma^2}$.

**Filtered Historical Simulation** (Barone-Adesi et al., 1999). Standardise each past return by that day's conditional
volatility, $z_t=R_t/\sigma_t$; take the empirical quantile $q_z$ and tail mean $\bar z_{\rm tail}$ of $\{z_t\}$; rescale
with tomorrow's volatility:

$$\mathrm{VaR}=-q_z\,\sigma_{T+1},\qquad \mathrm{ES}=-\bar z_{\rm tail}\,\sigma_{T+1}.$$

It keeps the **real tail shape** and reacts to the **current regime**. `fhs_ewma` and `fhs_garch` use the two volatility
filters.

**Student-$t$.** A Student-$t$ with $\nu>2$ degrees of freedom has variance $\nu/(\nu-2)$. To have standard deviation
$\sigma$ its scale is $\sigma\sqrt{(\nu-2)/\nu}$. With $t_q=t_\nu^{-1}(1-\alpha)$:

$$\mathrm{VaR}=-\sigma\sqrt{\tfrac{\nu-2}{\nu}}\;t_q,\qquad
\mathrm{ES}=\sigma\sqrt{\tfrac{\nu-2}{\nu}}\;\frac{f_\nu(t_q)}{1-\alpha}\,\frac{\nu+t_q^2}{\nu-1}$$

($f_\nu$ = density). $\nu$ is fitted by maximum likelihood on the standardised portfolio returns
($\nu\in[2.5,100]$): $\nu\approx4$–$6$ is typical for single assets; a diversified portfolio gave about $10$.

**Monte Carlo.** One-day returns of all assets jointly, with covariance $\hat\Sigma=LL^\top$ (Ledoit–Wolf, daily):

* Gaussian: $X=LZ$, $Z\sim N(0,I)$.
* Student-$t$: $X=\dfrac{LZ}{\sqrt{W/\nu}}\sqrt{\dfrac{\nu-2}{\nu}}$, $W\sim\chi^2_\nu$ independent of $Z$.
  Since $\mathrm{Var}(Z/\sqrt{W/\nu})=\nu/(\nu-2)$, the covariance is exactly $\hat\Sigma$; the fat tails and the
  tail dependence of a multivariate $t$ come for free, with **one $\nu$ for all assets**.

The portfolio loss is $-w^\top X$ over $200{,}000$ paths (seed $42$); VaR and ES are read from the simulated
distribution. Tests compare the simulation with the closed forms above.

**Limits.** All models are in-sample estimates of the past; the $99\%$ quantile on 1349 days rests on about 13 points;
the spread among models is **model risk**: never pick the smallest number. Adequacy is decided by backtesting (§10).

---

## 10. Backtesting of VaR and ES (stage 10, `var_backtest.py`)

**Forecasts without look-ahead.** For each day $t\ge500$ the VaR/ES of day $t$ is computed with returns up to $t-1$
(rolling window $500$; GARCH re-fitted every $63$ days on the previous $500$ days; the same parameters filter the
volatility forward **and** standardise the window). Six models: `historical`, `gaussian`, `gaussian_ewma`,
`gaussian_garch`, `fhs_ewma`, `fhs_garch`. Tests check that changing the return of one day never changes that day's
forecast.

**Exceptions.** $I_t=\mathbb 1\{L_t>\mathrm{VaR}_t\}$ with $L_t=-R_t$. If the model is right, $I_t$ are i.i.d.
Bernoulli with $p=1-\alpha$. Let $x=\sum I_t$, $n$ = number of forecast days, $\hat p=x/n$.

**Kupiec (1995) proportion-of-failures test.**

$$LR_{\rm POF}=-2\Big[(n-x)\ln(1-p)+x\ln p-(n-x)\ln(1-\hat p)-x\ln\hat p\Big]\ \sim\ \chi^2_1 .$$

Too many exceptions: risk understated; too few: capital kept idle.

**Christoffersen (1998) independence test.** Count transitions $n_{ab}$ of $I_t$ ($a,b\in\{0,1\}$); $\pi_{01}=\frac{n_{01}}{n_{00}+n_{01}}$,
$\pi_{11}=\frac{n_{11}}{n_{10}+n_{11}}$, $\pi=\frac{n_{01}+n_{11}}{n}$:

$$LR_{\rm ind}=-2\Big[\ln L(\pi)-\ln L(\pi_{01},\pi_{11})\Big]\sim\chi^2_1,\quad
\ln L(\pi)=(n_{00}+n_{10})\ln(1-\pi)+(n_{01}+n_{11})\ln\pi .$$

It detects **clusters** of exceptions (a model that reacts slowly). **Conditional coverage:**
$LR_{\rm CC}=LR_{\rm POF}+LR_{\rm ind}\sim\chi^2_2$. If there are no transitions to test, the p-value is NaN.

**Traffic light (Basel).** With $X\sim\mathrm{Bin}(n,p)$: green if $P(X\le x)<95\%$, yellow if $<99.99\%$, red otherwise.
For $250$ days at $99\%$ this gives the Basel zones (green $0$–$4$, yellow $5$–$9$, red $\ge10$).

**ES checks.** On exception days: $\text{ES ratio}=\frac{\overline{L}}{\overline{\mathrm{ES}}}$ (about $1$ is right, above $1$:
tail understated), and a McNeil–Frey-style one-sided $t$-test that $\frac{L_t-\mathrm{ES}_t}{\mathrm{VaR}_t}$ has zero mean
(fewer than 3 exceptions: NaN).

**Tick (pinball) loss.** With forecast quantile $q_t=-\mathrm{VaR}_t$ and $a=1-\alpha$:
$\frac1n\sum_t\big[a\,(R_t-q_t)^+ + (1-a)\,(q_t-R_t)^+\big]$, a proper scoring rule: lower is better; it ranks the
models that are not rejected.

**Reference model (decision 40).** `fhs_ewma`; challenger `fhs_garch`. Chosen from the first real run
(2154 days, about 21 expected exceptions at 99%): fixed-volatility models fail on clusters and on the tail, and the
conditional models with an empirical tail pass.

**Limits.** Low power at $99\%$; six models tested on one history (some pass or fail by chance); the choice of
reference model is made on the same data it is compared on, so it is declared now and not changed after seeing new
results.

---

## 11. Risk factors and variance attribution (stage 11, `factors.py`)

ETFs are **linear**: there is no gamma, vega or theta. The analogue of the Greeks is the sensitivity of the portfolio
return to a few risk factors.

**Factor returns** (`config/risk_factors.yaml`), built from ETFs already in the project, in **local (EUR)** returns, so
the currency enters only through the FX factor:

| factor | definition $f_t$ |
|---|---|
| market | $r^{\rm loc}_{\text{world\_xtrackers}}$ (global equity beta) |
| rates | $r^{\rm loc}_{\text{eur\_govt\_bond}}$ (duration proxy: interest-rate level) |
| credit | $r^{\rm loc}_{\text{eur\_corp\_bonds}}-r^{\rm loc}_{\text{eur\_govt\_bond}}$ (credit spread) |
| inflation | $r^{\rm loc}_{\text{eur\_inflation\_linked}}-r^{\rm loc}_{\text{eur\_govt\_bond}}$ (breakeven inflation) |
| gold | $r^{\rm loc}_{\text{gold}}$ |
| fx | EUR/PLN return $\frac{1+r^{\rm pln}}{1+r^{\rm loc}}-1$ of a EUR-quoted ETF |

**Regression.** The portfolio PLN return $y_t$ (fixed weights) on the factors, by OLS with intercept:
$y_t=a+\sum_i\beta_if_{i,t}+\varepsilon_t$, $\ \hat\beta=(F^\top F)^{-1}F^\top y$ on the demeaned data. $\beta_i$ is the
portfolio move (in %) for a $+1\%$ move of factor $i$, others fixed. The classic $t$-statistic is
$\hat\beta_i/\widehat{\mathrm{se}}_i$ with $\widehat{\mathrm{se}}_i^2=\hat\sigma^2_\varepsilon[(F^\top F)^{-1}]_{ii}$.

**Exact variance split.** Because the OLS residual is orthogonal to the factors, $\mathrm{Cov}(\varepsilon,f_i)=0$ and so

$$\mathrm{Var}(y)=\sum_i\beta_i\,\mathrm{Cov}(f_i,y)+\mathrm{Var}(\varepsilon)
\ \Longrightarrow\ 1=\sum_i\underbrace{\frac{\beta_i\,\mathrm{Cov}(f_i,y)}{\mathrm{Var}(y)}}_{\text{share}_i}+(1-R^2).$$

A **negative share** means the factor diversifies the portfolio; the residual share $1-R^2$ is the risk the factors do
not explain.

**One-sigma monthly move.** $\beta_i\cdot\sigma_{f_i}\sqrt{21}$: the portfolio move for a one-standard-deviation monthly shock to
factor $i$. **Factor volatility** $\sigma_{f_i}\sqrt{252}$.

**Rolling betas.** $\beta$ re-estimated on windows of $504$ days every $63$ days: a stability check (if the range is wide,
a beta is not a constant of the portfolio).

**Limits.** Factors are ETF proxies, **correlated** and with their own mix of exposures (so individual betas are less
reliable than the total picture); betas change over time; OLS standard errors ignore autocorrelation and fat tails; a
beta describes small moves and is **not** a stress test.

---

## 12. Stress tests (stage 12, `stress_tests.py`)

A stress test is a "what if", not a forecast and not a probability. All three tools below are **linear in the risk
factors** of section 11: with $\beta$ the vector of betas and $\Delta f$ a vector of factor returns over an episode,

$$\Delta P\approx\sum_i\beta_i\,\Delta f_i ,$$

and the contribution of factor $i$ is $\beta_i\Delta f_i$. The part of the return not explained by the factors
(residual, $1-R^2$) is ignored; convexity is ignored.

**1. Historical episodes** (`config/scenarios.yaml`, windows chosen from well-known market events, not from our data).

* *Direct:* the compound PLN return of each ETF from the close of the start date to the close of the end date,
  $r_i=\prod_{t}(1+r_{i,t})-1$. An ETF with no return on or before the start (it did not exist) is **missing**, never
  filled with a guess. The weighted return of the ETFs that existed is rescaled by their weight,
  $\frac{\sum_{i\in\mathcal C}w_ir_i}{\sum_{i\in\mathcal C}w_i}$, and the **coverage** $\sum_{i\in\mathcal C}w_i$ is reported.
* *Replayed:* the compound moves of the **factors** in the window (factors have a longer history than recent ETFs),
  multiplied by today's betas. A factor with no data in the window counts as $0$ and is listed.

**2. Hypothetical scenarios** (`config/stress_hypothetical.yaml`). Factor moves written **before** looking at results,
with the order of magnitude of known episodes (2008, 2020, 2022); not calibrated, not probabilities. Sign of the FX
factor: EUR/PLN return, so a **negative** move (the zloty strengthens) is a loss for a PLN investor holding EUR assets.

**3. Reverse stress test.** Question: what is the most plausible combination of factor moves that brings the portfolio
to a loss $L$ (the thresholds $-15\%$, $-20\%$, $-25\%$) over a horizon of $h$ days? Let $S_h=h\,\Sigma_f$ be the factor
covariance for the horizon (daily covariance times $h$). Choose the shock $d$ that minimises its Mahalanobis length
subject to hitting the loss:

$$\min_d\ \tfrac12\,d^\top S_h^{-1}d\quad\text{s.t.}\quad\beta^\top d=-L .$$

Lagrangian $\tfrac12d^\top S_h^{-1}d+\lambda(\beta^\top d+L)$: first-order condition $S_h^{-1}d+\lambda\beta=0$, so
$d=-\lambda S_h\beta$; the constraint gives $\lambda=L/(\beta^\top S_h\beta)$. Hence

$$d^\*=-L\,\frac{S_h\beta}{\beta^\top S_h\beta},\qquad
\text{distance}=\sqrt{d^{\*\top}S_h^{-1}d^\*}=\frac{L}{\sqrt{\beta^\top S_h\beta}} .$$

$\sqrt{\beta^\top S_h\beta}$ is the standard deviation of the factor-driven portfolio return over the horizon, so the
distance is the loss measured in standard deviations. If $\Delta f\sim N(0,S_h)$, then $\beta^\top\Delta f\sim
N(0,\beta^\top S_h\beta)$ and $P(\text{loss}\ge L)=\Phi(-\text{distance})$. The vector $d^\*$ shows which factors would
typically drive such a loss (factors with large $\beta_i$ and large variance or correlated with them). Horizons: 21, 63
and 252 days; the distance falls as $1/\sqrt h$.

**Limits.** Linear (no convexity: e.g. bond convexity, option-like behaviour of credit); betas from one window; the
residual is ignored; the probability assumes normality, so it is **optimistic** (fat tails); hypothetical sizes are
assumptions. Replayed episodes assume today's betas held in the past.

---

## 13. Further risk metrics (stage 13, `extra_metrics.py`)

Let $W_t$ be the wealth index of the fixed-weight portfolio and $d_t=1-W_t/\max_{u\le t}W_u\ge0$ the **drawdown depth**
(positive number, $0$ at a new high).

**DaR and CDaR** (Chekhlov, Uryasev, Zabarankin, 2005). The drawdown analogue of VaR and ES:

$$\mathrm{DaR}_\alpha=q_\alpha(d),\qquad \mathrm{CDaR}_\alpha=\mathbb E\big[d_t\mid d_t\ge\mathrm{DaR}_\alpha\big],\quad\alpha=95\%,$$

estimated as the quantile of the daily depths and the mean of the days at or beyond it. $\mathrm{DaR}$ is the depth exceeded
$5\%$ of the time; $\mathrm{CDaR}$ the average depth in that worst $5\%$ of the time. Unlike VaR it looks at the path:
how deep and for how long.

**Ulcer index** (Martin and McCann, 1989). $\mathrm{UI}=\sqrt{\frac1T\sum_td_t^2}$: root-mean-square drawdown; squaring
punishes deep drawdowns, averaging over time punishes long ones.

**Diversification ratio** (Choueifaty and Coignard, 2008).

$$\mathrm{DR}=\frac{\sum_iw_i\sigma_i}{\sigma_p}\ \ge 1\ \text{(long-only)},$$

because $\sigma_p\le\sum_iw_i\sigma_i$ (the triangle inequality for the norm $\sqrt{w^\top\Sigma w}$); $\mathrm{DR}=1$ if and only
if all assets are perfectly correlated. It is the ratio between the volatility the portfolio would have with no
diversification and the one it has.

**Effective number of risk bets.** With the Euler risk shares $p_i$ of §3 ($\sum p_i=1$):
$\mathrm{ENB}=\exp\!\big(-\sum_ip_i\ln p_i\big)$. Equal shares over $N$ assets give $N$; one asset carrying all the risk gives
$1$. It is an asset-level (entropy) version of Meucci's effective number of bets, which uses principal components.

**Component ES (Euler allocation of the tail loss).** Let $\mathcal T=\{t:R_{p,t}\le q_{1-\alpha}(R_p)\}$ be the tail days of the
portfolio. Since $R_{p,t}=\sum_iw_ir_{i,t}$ is linear,

$$\mathrm{ES}=-\frac1{|\mathcal T|}\sum_{t\in\mathcal T}R_{p,t}=\sum_i\underbrace{\Big(-w_i\,\frac1{|\mathcal T|}\sum_{t\in\mathcal T}r_{i,t}\Big)}_{\mathrm{CES}_i},$$

so the components add up **exactly** to the ES (Tasche, 2000: the contribution is $w_i\,\partial\mathrm{ES}/\partial w_i=-w_i\mathbb E[r_i\mid\text{tail}]$).
Comparing $\mathrm{CES}_i/\mathrm{ES}$ with the volatility share $p_i$ shows who is riskier **in bad times** than its volatility says;
a hedge has a negative component.

**Correlation in stress, corrected for selection** (Forbes and Rigobon, 2002). Take the worst $10\%$ days of the equity
market $x$ (the `market` factor) and an asset return $y$. Selecting days on $x$ truncates its variance and mechanically
lowers the measured correlation, even if the relation has not changed. Assume $y=a+bx+e$ with constant slope $b$ and
noise variance $\sigma_e^2$. Let $\rho_s$ be the correlation on the selected days, $k=\sigma_x^2/\sigma_{x,s}^2$ the ratio of
the full-sample to the selected-sample variance of $x$. Then the full-sample correlation implied by the selected sample is

$$\rho^\*=\frac{\rho_s}{\sqrt{1+\delta\,(1-\rho_s^2)}},\qquad\delta=\frac{\sigma_{x,s}^2}{\sigma_x^2}-1 .$$

(Derivation: $\rho_s^2=\frac{b^2\sigma_{x,s}^2}{b^2\sigma_{x,s}^2+\sigma_e^2}$ and the same with $\sigma_x^2$ for the full sample; eliminating
$b^2/\sigma_e^2$ gives $\rho^{\*2}=\frac{k\rho_s^2}{1-\rho_s^2+k\rho_s^2}$, which is the formula above.) If $\rho^\*$ is clearly **above** the
all-days correlation $\rho$, the relation really strengthened in stress; if it is close to $\rho$, the lower raw value was only
the selection effect.

**Limits.** All historical and in-sample; the tail quantities rest on about $5\%$ of the days (few observations); the
corrected correlation assumes that slope and noise do not change in stress, so it shows **whether** the relation changes,
not how large it will be in the next crisis; the market factor is an ETF proxy.

---

## 14. Risk limits and monitoring report (stage 14, `limits.py`, `monitor.py`)

A **limit** is a rule on a number that an earlier stage already computes. The report only compares; it never trades.

**Status of a value $x$** against an optional lower bound $L$, upper bound $U$ and margin $m \ge 0$:

$$
\text{status}(x)=\begin{cases}
\text{RED} & x<L \ \text{ or } \ x>U\\
\text{AMBER} & L\le x\le U \ \text{ and } \ (x-L<m \ \text{ or } \ U-x<m)\\
\text{GREEN} & \text{otherwise}
\end{cases}
$$

A missing value gives N/A (the stage that produces it has not been run). The overall status is the worst of the rows
(RED > AMBER > GREEN; N/A ignored).

**Drawdown** uses the three profile levels $a>r>s$ (alert, review, stop, all negative). With $D_t = W_t/\max_{u\le t}W_u-1$
and $W_t=\prod_{u\le t}(1+r_u)$ the time-weighted wealth: GREEN if $D_t>a$; AMBER if $r<D_t\le a$; RED if $D_t\le r$.
Below $s$ the text of the IPS applies (stop contributions and review).

**Checks computed** (values come from the stage in brackets):

| Check | Value | Limit | Origin |
|---|---|---|---|
| Model volatility (05) | $\sqrt{w'\Sigma w}$ | 8% to 10% | decided |
| FX share of variance (05) | $\mathrm{Cov}(r_{pln},fx)/\mathrm{Var}(r_{pln})$ | $\le 30\%$ | decided |
| Equity weight, largest weight (05) | sum / max of weights | profile caps | profile |
| 1-day VaR 99%, `fhs_ewma` (09) | historical quantile of standardised residuals $\times$ current $\sigma$ | $\le 1.5\%$ | proposed |
| Basel zone of `fhs_ewma` at 99% (10) | traffic light | green | proposed |
| Worst hypothetical scenario (12) | $\min_s \beta'\,\text{shock}_s$ | $\ge$ stop level | proposed |
| Class risk-share gap (05) | $\max_c \lvert \hat s_c - b_c\rvert$, shares on the risky part, cash excluded and rescaled | $\le 10$ points | proposed |
| Current drawdown (06) | $D_T$ of the backtest series | alert / review / stop | profile |

The 1.5% VaR limit is the Gaussian 99% VaR of a portfolio at the upper volatility bound, $2.33\times 10\%/\sqrt{252}=1.47\%$,
rounded. It is a proposal, not an owner decision (IPS decision 42).

**Limits of the report.** The drawdown rows use the backtest series, not the real account, whose returns are not in the data.
Values are point estimates, with no confidence interval; AMBER margins are conventions, not statistics.

## 15. Robustness variants (stage 15, `robustness.py`)

The walk-forward of stage 06 is repeated with **one** assumption changed at a time. The seven variants are fixed
in advance (IPS decision 43): base; cost 5 and 25 bps (base 10); switch margin 0.05 and 0.15 (base 0.10); equity
secondary share 0.10 and 0.30 (base 0.20). Everything else is identical, including the data.

For each variant $v$ and strategy $i$ the same summary as stage 06 is computed (annual TWR, volatility, maximum drawdown,
longest time under water, turnover, costs, final value). Two quantities describe the sensitivity:

$$
\text{spread}_i(m)=\max_v m_{i,v}-\min_v m_{i,v},
\qquad
\text{gap}_v = \mathrm{MaxDD}_{\text{risk\_budget},v}-\mathrm{MaxDD}_{\text{benchmark},v}.
$$

How to read it: if the spread of volatility and drawdown is small and $\text{gap}_v$ keeps its sign in all variants, the
conclusion does not depend on the assumption. A large spread means the base result was fragile. **The best variant is
never selected**: that would be data snooping. With one history the checks test the assumptions, not the future.

## 16. Where the methods are weak (summary)

* **One history.** Backtest, bootstrap and VaR backtest all use the same sample; no hold-out; one 2022, one COVID.
* **Data.** Free data (yfinance), short histories for newer ETFs, known anomalies on some days.
* **Look-ahead left.** Stage-02 category winners (today's TER and flags) and the `core` list.
* **Estimation error.** Covariance in-sample; GARCH and EWMA are fitted, not known; $\nu$ is one number for all assets.
* **Simplifications.** No taxes, no PLN→EUR cost on contributions, hedge modelled with assumed carry and cost.
* **Multiple testing.** Several models and several strategies are compared on the same data.
* **Meaning of results.** Differences are judged by their size against bootstrap noise, never as a forecast of returns.

## 17. References

* Politis, D., Romano, J. (1994). The stationary bootstrap. *JASA* 89.
* Ledoit, O., Wolf, M. (2004). A well-conditioned estimator for large-dimensional covariance matrices. *JMVA* 88.
* Spinu, F. (2013). An algorithm for computing risk parity weights. SSRN.
* López de Prado, M. (2016). Building diversified portfolios that outperform out of sample. *JPM* 42.
* Barone-Adesi, G., Giannopoulos, K., Vosper, L. (1999). VaR without correlations for nonlinear portfolios. *J. Futures Markets* 19.
* Bollerslev, T. (1986). Generalized autoregressive conditional heteroskedasticity. *J. Econometrics* 31.
* J.P. Morgan/Reuters (1996). *RiskMetrics Technical Document*, 4th ed.
* Kupiec, P. (1995). Techniques for verifying the accuracy of risk measurement models. *J. Derivatives* 3.
* Christoffersen, P. (1998). Evaluating interval forecasts. *International Economic Review* 39.
* McNeil, A., Frey, R. (2000). Estimation of tail-related risk measures for heteroscedastic financial time series. *J. Empirical Finance* 7.
* Chekhlov, A., Uryasev, S., Zabarankin, M. (2005). Drawdown measure in portfolio optimization. *Int. J. Theoretical and Applied Finance* 8.
* Martin, P., McCann, B. (1989). *The Investor's Guide to Fidelity Funds*. Wiley (Ulcer index).
* Choueifaty, Y., Coignard, Y. (2008). Toward maximum diversification. *J. Portfolio Management* 35.
* Meucci, A. (2009). Managing diversification. *Risk* 22.
* Tasche, D. (2000). Risk contributions and performance measurement. Working paper.
* Forbes, K., Rigobon, R. (2002). No contagion, only interdependence. *Journal of Finance* 57.
* Basel Committee (1996). *Supervisory framework for the use of backtesting in conjunction with the internal models approach*.
