"""Small helpers shared by the tests (synthetic data, no network)."""

import numpy as np
import pandas as pd


def make_prices(start: str = "2015-01-01", end: str = "2026-10-28", seed: int = 0) -> pd.DataFrame:
    """A clean synthetic price table in the standard format (business days, random walk)."""
    index = pd.bdate_range(start, end, name="date")
    rng = np.random.default_rng(seed)
    close = 100 * np.exp(np.cumsum(rng.normal(0.0003, 0.01, len(index))))
    return pd.DataFrame(
        {
            "open": close,
            "high": close * 1.005,
            "low": close * 0.995,
            "close": close,
            "adj_close": close,
            "volume": 1000,
        },
        index=index,
    )
