"""Historical stress scenarios: what each asset did, in PLN, during a known market episode.

The windows are listed in ``config/scenarios.yaml`` and were chosen from well-known market events,
NOT from the data of our ETFs. An asset that did not exist at the start of a window gets no value
(NaN): we never fill it with a guess.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import yaml

from prm.config import REPO_ROOT

DEFAULT_SCENARIOS_PATH = REPO_ROOT / "config" / "scenarios.yaml"


def load_scenarios(path: Path | str = DEFAULT_SCENARIOS_PATH) -> list[dict]:
    """Read and validate the scenario list: each needs id, start, end (ISO dates, start before end)."""
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    out = []
    seen = set()
    for item in raw.get("scenarios") or []:
        for key in ("id", "start", "end"):
            if key not in item:
                raise ValueError(f"scenario missing '{key}': {item}")
        start = date.fromisoformat(str(item["start"]))
        end = date.fromisoformat(str(item["end"]))
        if start >= end:
            raise ValueError(f"scenario {item['id']}: start must be before end")
        if item["id"] in seen:
            raise ValueError(f"duplicate scenario id: {item['id']}")
        seen.add(item["id"])
        out.append({"id": item["id"], "start": pd.Timestamp(start), "end": pd.Timestamp(end),
                    "description": str(item.get("description", ""))})
    return out


def scenario_return(r: pd.Series, start: pd.Timestamp, end: pd.Timestamp) -> float:
    """Compound return from the close of ``start`` to the close of ``end``.

    Uses the returns dated after ``start`` up to ``end``. NaN if the asset has no return on or before
    ``start`` (it did not exist yet) or none up to ``end`` (it was gone).
    """
    r = r.dropna()
    if len(r) == 0 or r.index.min() > start or r.index.max() < end:
        return float("nan")
    window = r[(r.index > start) & (r.index <= end)]
    return float((1 + window).prod() - 1) if len(window) else float("nan")


def stress_table(returns: pd.DataFrame, scenarios: list[dict]) -> pd.DataFrame:
    """Rows = assets, columns = scenario ids, values = compound return in the window."""
    data = {s["id"]: {a: scenario_return(returns[a], s["start"], s["end"]) for a in returns.columns} for s in scenarios}
    return pd.DataFrame(data)
