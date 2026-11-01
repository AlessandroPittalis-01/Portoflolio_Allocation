"""Exchange rates from the Polish central bank (NBP), table A.

Table A gives the average ("mid") rate: how many PLN buy ONE unit of a foreign
currency (for example EUR 4.30 means 1 EUR = 4.30 PLN). One rate per Polish
business day, published around midday.

The web API returns at most 367 days per request, so a long period is asked in
several windows. Rates are cached like prices (one CSV per currency).

Timing note: the NBP rate of day D is published before the European ETFs close,
so using it for the close of day D is a small approximation (hours, not days).
It never uses information from the future.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from prm.data.cache import is_fresh

NBP_URL = "https://api.nbp.pl/api/exchangerates/rates/a/{code}/{start}/{end}/?format=json"
WINDOW_DAYS = 360   # below the API limit of 367 days


def windows(start: date, end: date, days: int = WINDOW_DAYS) -> list[tuple[date, date]]:
    """Split ``[start, end]`` into consecutive windows of at most ``days`` days (no overlap, no gap)."""
    out = []
    current = start
    while current <= end:
        stop = min(current + timedelta(days=days - 1), end)
        out.append((current, stop))
        current = stop + timedelta(days=1)
    return out


def parse_rates(payload: dict) -> pd.Series:
    """Turn one API answer into a Series of PLN per 1 unit, indexed by date."""
    rows = payload.get("rates") or []
    if not rows:
        return pd.Series(dtype="float64", index=pd.DatetimeIndex([], name="date"))
    index = pd.to_datetime([r["effectiveDate"] for r in rows])
    return pd.Series([float(r["mid"]) for r in rows], index=pd.DatetimeIndex(index, name="date"), dtype="float64")


class NbpSource:
    """Downloads daily PLN rates. Replace this class in tests with a fake one."""

    name = "nbp"

    def fetch(self, code: str, start: date, end: date) -> pd.Series:
        parts = []
        for w_start, w_end in windows(start, end):
            url = NBP_URL.format(code=code.lower(), start=w_start.isoformat(), end=w_end.isoformat())
            try:
                with urllib.request.urlopen(url, timeout=30) as response:
                    parts.append(parse_rates(json.loads(response.read().decode("utf-8"))))
            except urllib.error.HTTPError as exc:
                if exc.code == 404:   # NBP answers 404 when a window has no data (for example only holidays)
                    continue
                raise
        if not parts:
            return pd.Series(dtype="float64", index=pd.DatetimeIndex([], name="date"))
        series = pd.concat(parts)
        return series[~series.index.duplicated(keep="first")].sort_index()


def cache_path(raw_dir: Path, code: str) -> Path:
    return Path(raw_dir) / "nbp" / f"{code.upper()}PLN.csv"


def load_rates(source, code: str, start: date, end: date, raw_dir: Path,
               max_age_days: float, refresh: bool = False) -> tuple[pd.Series, str]:
    """Return ``(rates, origin)`` with origin ``"cache"`` or ``"download"``. Empty downloads are not cached."""
    code = code.upper()
    if code == "PLN":
        raise ValueError("PLN needs no exchange rate")
    path = cache_path(raw_dir, code)
    if not refresh and is_fresh(path, max_age_days):
        cached = pd.read_csv(path, index_col="date", parse_dates=True)["mid"]
        return cached, "cache"
    series = source.fetch(code, start, end)
    if len(series) > 0:
        path.parent.mkdir(parents=True, exist_ok=True)
        series.rename("mid").to_csv(path, index_label="date")
    return series, "download"
