"""Declared repairs of single bad prices (IPS decision 46).

A bad print is a row that is not a real trade: volume 0, open = high = low = close, a price far from the days around
it that returns to the old level the next trading day. Such rows are listed by hand per asset in the universe file
(``bad_prints``) after the raw rows were inspected. The raw file is never changed.

Repair: the price of the listed date is replaced by the last valid price BEFORE it, so the return of that day is 0
and the next day carries the whole true move (P[t+1] / P[t-1] - 1). Nothing is interpolated or invented.
"""

from __future__ import annotations

import pandas as pd


def repair_bad_prints(df: pd.DataFrame, dates: tuple[str, ...], columns: tuple[str, ...] = ("adj_close",)) -> tuple[pd.DataFrame, list[str]]:
    """Return a copy of ``df`` with the listed dates repaired, and one message per date.

    A listed date that is missing, or has no earlier valid price, is reported and left alone (never guessed).
    """
    out = df.copy()
    notes: list[str] = []
    for d in sorted(dates):
        ts = pd.Timestamp(d)
        if ts not in out.index:
            notes.append(f"{d}: not in the data, nothing repaired")
            continue
        before = out.loc[out.index < ts, list(columns)].dropna()
        if before.empty:
            notes.append(f"{d}: no earlier price, nothing repaired")
            continue
        old = out.loc[ts, list(columns)].astype(float).to_dict()
        out.loc[ts, list(columns)] = before.iloc[-1].to_numpy()
        notes.append(f"{d}: price {old['adj_close']:.4f} replaced by the previous valid price {before.iloc[-1]['adj_close']:.4f}"
                     if "adj_close" in old else f"{d}: repaired")
    return out, notes
