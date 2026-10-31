"""Data-quality checks for daily price tables.

Principle: **flag, never silently fix.** Free data can contain duplicates, gaps,
stale prices or odd jumps. Each check reports what it found; the decision on what
to do (drop an ETF, use another source, accept a known event) stays with a human
and is recorded in docs/IPS.md.

Severity
--------
* ``error``   -> the series must not be used until the problem is understood
* ``warning`` -> worth a look; the series can still be used
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

# Fixed rules of the checks (the thresholds that you may want to tune live in settings.yaml).
MAX_ADJ_RATIO_JUMP = 0.05      # daily jump of adj_close/close that suggests a bad adjustment
MAX_ZERO_VOLUME_SHARE = 0.20   # share of zero-volume days above which we warn
MAX_DAYS_SINCE_LAST = 7        # last data point older than this many days -> stale download


@dataclass(frozen=True)
class Issue:
    severity: str   # "error" or "warning"
    code: str       # short machine-readable name, for example "duplicate_dates"
    message: str    # human-readable explanation


@dataclass
class QualityReport:
    symbol: str
    n_rows: int
    first_date: pd.Timestamp | None
    last_date: pd.Timestamp | None
    history_years: float
    issues: list[Issue] = field(default_factory=list)

    @property
    def status(self) -> str:
        """``error`` if any error, else ``warning`` if any issue, else ``ok``."""
        if any(i.severity == "error" for i in self.issues):
            return "error"
        return "warning" if self.issues else "ok"

    @property
    def codes(self) -> list[str]:
        return [i.code for i in self.issues]


def check_prices(
    df: pd.DataFrame,
    symbol: str,
    *,
    max_daily_move: float,
    max_gap_days: int,
    max_stale_days: int,
    min_history_years: float | None = None,
    today: pd.Timestamp | None = None,
) -> QualityReport:
    """Run all checks on a standard-format price table and return a report."""
    issues: list[Issue] = []

    def add(severity: str, code: str, message: str) -> None:
        issues.append(Issue(severity, code, message))

    # --- Basic structure: stop early if there is nothing meaningful to check ----------
    if df is None or len(df) == 0:
        add("error", "empty", "no data returned")
        return QualityReport(symbol, 0, None, None, 0.0, issues)
    if not isinstance(df.index, pd.DatetimeIndex):
        add("error", "bad_index", "the index is not a DatetimeIndex")
        return QualityReport(symbol, len(df), None, None, 0.0, issues)

    first, last = df.index.min(), df.index.max()
    years = (last - first).days / 365.25

    # --- Dates: duplicates and ordering ----------------------------------------------
    n_dup = int(df.index.duplicated().sum())
    if n_dup:
        add("error", "duplicate_dates", f"{n_dup} duplicated dates")
    if not df.index.is_monotonic_increasing:
        add("error", "unsorted_dates", "dates are not in increasing order")

    # The remaining checks run on a sorted, de-duplicated copy, so that one structural
    # problem does not hide the others.
    clean = df[~df.index.duplicated(keep="first")].sort_index()

    # --- Missing columns and missing values -------------------------------------------
    for col in ("close", "adj_close"):
        if col not in clean.columns:
            add("error", "missing_column", f"column '{col}' is missing")
            continue
        n_nan = int(clean[col].isna().sum())
        if n_nan == len(clean):
            add("error", "all_missing", f"'{col}' has no values")
        elif n_nan:
            add("warning", "missing_values", f"'{col}' has {n_nan} missing values")

    if "close" not in clean.columns or "adj_close" not in clean.columns:
        return QualityReport(symbol, len(df), first, last, years, issues)

    # --- Prices must be positive ------------------------------------------------------
    n_bad = int((clean["close"] <= 0).sum())
    if n_bad:
        add("error", "non_positive_price", f"{n_bad} days with close <= 0")

    # --- Large daily moves (on adjusted prices) ---------------------------------------
    price = clean["adj_close"].dropna()
    moves = price.pct_change().abs().dropna()
    big = moves[moves > max_daily_move]
    if len(big):
        worst_date = big.idxmax()
        add(
            "warning",
            "large_daily_move",
            f"{len(big)} daily moves above {max_daily_move:.0%}; "
            f"largest {big.max():.1%} on {worst_date.date()}",
        )

    # --- adj_close / close ratio: a sudden jump suggests a wrong adjustment ----------
    ratio = (clean["adj_close"] / clean["close"]).dropna()
    ratio_jumps = ratio.pct_change().abs().dropna()
    n_ratio = int((ratio_jumps > MAX_ADJ_RATIO_JUMP).sum())
    if n_ratio:
        add("warning", "adjustment_jump", f"{n_ratio} jumps of adj_close/close above {MAX_ADJ_RATIO_JUMP:.0%}")

    # --- Gaps: long stretches without data --------------------------------------------
    gaps = clean.index.to_series().diff().dt.days.dropna()
    long_gaps = gaps[gaps > max_gap_days]
    if len(long_gaps):
        add(
            "warning",
            "gaps",
            f"{len(long_gaps)} gaps longer than {max_gap_days} days; "
            f"longest {int(long_gaps.max())} days ending {long_gaps.idxmax().date()}",
        )

    # --- Stale prices: same close repeated many days in a row ------------------------
    close = clean["close"].dropna()
    run_id = (close != close.shift()).cumsum()           # a new id every time the price changes
    run_length = close.groupby(run_id).transform("size")  # length of the run each day belongs to
    is_stale = run_length >= max_stale_days
    if is_stale.any():
        n_stale_runs = int(run_id[is_stale].nunique())
        longest_day = run_length[is_stale].idxmax()               # a day inside the longest run
        longest_dates = close.index[run_id == run_id[longest_day]]  # all days of that run
        add(
            "warning",
            "stale_prices",
            f"{n_stale_runs} runs of {max_stale_days}+ identical closes; longest {len(longest_dates)} days "
            f"({longest_dates[0].date()} to {longest_dates[-1].date()})",
        )

    # --- Volume -----------------------------------------------------------------------
    if "volume" in clean.columns and clean["volume"].notna().any():
        zero_share = float((clean["volume"].fillna(0) == 0).mean())
        if zero_share > MAX_ZERO_VOLUME_SHARE:
            add("warning", "zero_volume", f"{zero_share:.0%} of days have zero volume")

    # --- History length and freshness -------------------------------------------------
    if min_history_years is not None and years < min_history_years:
        add("warning", "short_history", f"{years:.1f} years of history, below the {min_history_years:g} required")

    today = pd.Timestamp.today().normalize() if today is None else today
    days_old = (today - last).days
    if days_old > MAX_DAYS_SINCE_LAST:
        add("warning", "stale_last_date", f"last data point is {days_old} days old ({last.date()})")

    return QualityReport(symbol, len(df), first, last, years, issues)
