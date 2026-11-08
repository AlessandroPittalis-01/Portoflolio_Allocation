# EUR/PLN hedging instruments for a Polish retail investor (research note)

Status: **research, not advice, mostly NOT verified against primary sources.** Written for IPS decision 38 (FX hedge
study). The owner said that if bonds are ever hedged he accepts a lower volatility (~7%). Nothing here changes the
IPS: it only says whether a hedge could be *implemented* and what it would cost. Date of the search: 2026-11-08.

## What has to be hedged
The ETFs are quoted in EUR, the investor measures results in PLN. The exposure is **long EUR / short PLN**. To hedge,
the investor must **sell EUR forward** (or hold the equivalent). Stage 08 models this with a hedge ratio `h` and a
carry `c = (carry - cost)/252`. With Polish rates above euro rates, interest-rate parity says the forward EUR/PLN
is above spot, so *selling EUR forward earns* the rate gap (before costs). This sign is from theory, not from a quote:
check the forward points on the day.

## Candidate instruments

| Instrument | Can a retail resident use it? | Cost / margin found | Main problem |
|---|---|---|---|
| **Bank FX forward** (OTC) | Usually only business clients with a credit line; one example (BOS bank KID) says the product is meant for hedging business EUR obligations | Entry cost up to **4% of notional** built into the rate (that example is a *buy EUR* forward, the opposite direction); extra collateral may be requested; risk class 7/7 | Not designed for a small portfolio; fixed maturity (3M example), cannot be closed early; high margin |
| **Futures / CFD on EUR/PLN** (broker) | Yes, offered by retail brokers | Leverage for retail FX CFDs is capped by ESMA-style rules (30:1 for major pairs; EUR/PLN may be treated as non-major, check) - found only in a 2019 article about ESMA/KNF | CFDs are leveraged, with daily financing, spread and margin calls; a short-EUR position needs margin and can be closed out. Complex to keep aligned with a portfolio that changes monthly |
| **EUR-hedged ETF share classes** | Yes | Only hedge back to EUR, not to PLN | Do not remove EUR/PLN risk, only the ETF's own currency risk (e.g. USD). Irrelevant for our EUR-quoted unhedged ETFs |
| **PLN-hedged ETF share classes** | A secondary source says PLN-hedged UCITS are rare and the main ones on the Warsaw exchange are BETA Securities S&P 500 / Nasdaq-100 classes | Cost "typically higher than unhedged", no numbers found | No PLN-hedged version of the multi-asset ETFs in our universe was found; not a general solution |
| **Hold PLN assets** (e.g. Polish government bonds) | Yes | Not a hedge of EUR assets; changes the strategy | Out of scope of the UCITS multi-asset universe |
| **Natural hedge**: spend in EUR | n/a | None | Applies only if future liabilities are in EUR; here they are in PLN |

## Taxes (Poland)
Not verified: the interpretation pages I tried were not readable. What I could find says that income from CFD /
derivative contracts of a private person is a capital income reported in **PIT-38** at **19%**, and that
derivative losses and gains are netted in the same capital-income basket. The owner's ETFs are accumulating UCITS
whose tax is on sale (19%). Open question for a tax adviser: whether hedge losses can be netted against the
ETF gains in the same year (this decides if hedging creates a tax drag in years when PLN strengthens).

## Practical conclusion (to be confirmed)
1. A **simple, cheap, retail-proof way to hedge a multi-asset EUR ETF portfolio into PLN was not found**. The two
   workable routes (EUR/PLN CFD or future short; bank forward) both add leverage-type risk, margin management and
   monthly maintenance, and the costs I found are either unquantified (CFD spread/financing) or very high (bank margin).
2. Stage 08 assumes a cost; the real cost for a CFD is spread + overnight financing, which can be **larger than the carry
   it earns**. Treat the stage-08 numbers as an upper bound on benefit.
3. This supports the owner's choice to *not hedge by default* and to accept the 30% FX-variance limit as an AMBER/RED
   monitor (stage 14), reviewing the choice once a year.

## What is still unverified (to do before any implementation)
- Current retail leverage rules for EUR/PLN CFD at the broker the owner would use (KNF / ESMA status in 2026).
- Spread, financing and margin for a short EUR/PLN position at that broker (ask for the KID / cost table).
- Tax netting of derivative losses in the Polish PIT-38 (tax adviser).
- Existence and TER of PLN-hedged share classes for the exact ETFs chosen (check the issuer's KID).
- All figures above come from secondary sources (blogs, a 2019 news article, one bank KID); none comes from a regulator
  or a tax authority.

## Sources
- [BOS bank - KID FX Forward EUR/PLN 3M (buy EUR), Apr 2024](https://www.bosbank.pl/__data/assets/pdf_file/0028/58753/KID_FX_FORWARD_EUR_PLN_ZAKUP-PRZEZ-KLIENTA_3M_IV_2024.pdf)
- [Comparic - ESMA leverage limits ending and KNF position, 2019](https://comparic.pl/forex-w-polsce-z-dzwignia-1001-co-najmniej-do-6-sierpnia-esma-wygasa-knf-bez-nowych-przepisow/)
- [Freenance - Currency-hedged ETFs: when to hedge and when to skip](https://freenance.io/etf/etf-z-zabezpieczeniem-walutowym/) (secondary source; its PLN cost figure looks inconsistent with interest-rate parity)
- Search results consulted but not readable or not used: comparic.pl tax articles on CFD/futures, an individual tax interpretation (arslege.pl, ITPB1/415-7a/11/AD), Interactive Brokers forex commission PDF (binary, not readable).
