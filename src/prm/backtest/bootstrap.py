"""Stationary block bootstrap of the realised strategy returns (stage 07, IPS decision 33).

WHAT IT DOES
It takes the daily time-weighted returns (after costs) that the walk-forward backtest really produced for several
strategies, and builds many alternative histories by resampling BLOCKS of dates. The same dates are drawn for every
strategy (paired), so correlations between strategies, volatility clustering and short runs of bad days are kept.
Block lengths are random (geometric, mean ``mean_block`` days: Politis-Romano stationary bootstrap).

WHAT IT CAN SAY
* how much the risk outcomes (maximum drawdown, time under water, probability of crossing -10%, -18%, -25%) depend on
  the ORDER of the days, given the days we have seen;
* whether a difference between two strategies (for example 2.7 points a year) is large compared with that noise.

WHAT IT CANNOT SAY
* It only reshuffles what already happened: no regime that is not in the sample (one 2022, one COVID) can appear.
* The resampled paths keep the realised mean return, so they are NOT a forecast of future returns.
* It resamples the OUTPUT of the walk-forward (the choice of ETFs is not re-run on each path).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from prm.config import REPO_ROOT

DEFAULT_BOOTSTRAP_PATH = REPO_ROOT / "config" / "bootstrap.yaml"
TRADING_DAYS = 252
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


@dataclass(frozen=True)
class BootstrapSettings:
    n_paths: int
    mean_block_days: int
    sensitivity_blocks: tuple[int, ...]
    horizon_years: float
    contribution_every_days: int
    seed: int
    strategies: tuple[str, ...]
    reference: str


def load_bootstrap(path: Path | str = DEFAULT_BOOTSTRAP_PATH) -> BootstrapSettings:
    with open(path, "r", encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("bootstrap") or {}
    n_paths = int(raw.get("n_paths", 2000))
    block = int(raw.get("mean_block_days", 21))
    sens = tuple(int(b) for b in (raw.get("sensitivity_blocks") or ()))
    horizon = float(raw.get("horizon_years", 10))
    every = int(raw.get("contribution_every_days", 21))
    strategies = tuple(raw.get("strategies") or ())
    reference = str(raw.get("reference", ""))
    if n_paths < 100 or block < 1 or any(b < 1 for b in sens) or horizon <= 0 or every < 1:
        raise ValueError("bootstrap: n_paths >= 100, block lengths >= 1, horizon_years > 0, contribution_every_days >= 1")
    if len(strategies) < 2 or reference not in strategies:
        raise ValueError("bootstrap: 'strategies' needs at least two names and must contain 'reference'")
    return BootstrapSettings(n_paths, block, sens, horizon, every, int(raw.get("seed", 42)), strategies, reference)


def stationary_indices(n: int, horizon: int, mean_block: float, n_paths: int, rng: np.random.Generator) -> np.ndarray:
    """Indices (n_paths, horizon) into ``range(n)``: blocks of consecutive days, random start, geometric length."""
    if n < 2 or horizon < 1:
        raise ValueError("need at least 2 observations and a positive horizon")
    p = 1.0 / mean_block
    new = rng.random((n_paths, horizon)) < p
    new[:, 0] = True
    start_pos = rng.integers(0, n, size=(n_paths, horizon))
    step = np.arange(horizon)
    first_step = np.maximum.accumulate(np.where(new, step, 0), axis=1)
    start = np.take_along_axis(start_pos, first_step, axis=1)
    return (start + step - first_step) % n


def path_metrics(r: np.ndarray, contribution_every: int, alert: float, review: float, stop: float) -> dict[str, np.ndarray]:
    """Metrics of resampled paths. ``r`` has shape (paths, days, strategies); every output is (paths, strategies)."""
    paths, days, _ = r.shape
    wealth = np.cumprod(1.0 + r, axis=1)
    peak = np.maximum(1.0, np.maximum.accumulate(wealth, axis=1))
    dd = wealth / peak - 1.0
    max_dd = dd.min(axis=1)
    below = dd < -1e-12
    idx = np.arange(days)[None, :, None]
    last_ok = np.maximum.accumulate(np.where(~below, idx, -1), axis=1)
    underwater_days = np.where(below, idx - last_ok, 0).max(axis=1)
    value = np.zeros((paths, r.shape[2]))
    n_contrib = 0
    for t in range(days):
        value = value * (1.0 + r[:, t, :])
        if t % contribution_every == 0:                  # a unit contribution at the close of the rebalance day
            value += 1.0
            n_contrib += 1
    return {
        "twr_ann": wealth[:, -1, :] ** (TRADING_DAYS / days) - 1.0,
        "vol_ann": r.std(axis=1, ddof=1) * np.sqrt(TRADING_DAYS),
        "max_dd": max_dd,
        "underwater_years": underwater_days / TRADING_DAYS,
        "money_multiple": value / n_contrib,
        "hit_alert": (max_dd <= alert).astype(float),
        "hit_review": (max_dd <= review).astype(float),
        "hit_stop": (max_dd <= stop).astype(float),
        "loss_of_capital": (value / n_contrib < 1.0).astype(float),
    }


def run_bootstrap(returns: pd.DataFrame, horizon_days: int, mean_block: int, n_paths: int, contribution_every: int,
                  alert: float, review: float, stop: float, seed: int, chunk: int = 250) -> dict[str, np.ndarray]:
    """Resample the rows of ``returns`` (no missing values) and compute the metrics of every path."""
    if returns.isna().any().any():
        raise ValueError("returns must have no missing values: use the dates where every strategy exists")
    rng = np.random.default_rng(seed)
    data = returns.to_numpy(dtype=float)
    out: dict[str, list[np.ndarray]] = {}
    done = 0
    while done < n_paths:
        m = min(chunk, n_paths - done)
        idx = stationary_indices(len(data), horizon_days, mean_block, m, rng)
        res = path_metrics(data[idx], contribution_every, alert, review, stop)
        for k, v in res.items():
            out.setdefault(k, []).append(v)
        done += m
    return {k: np.concatenate(v, axis=0) for k, v in out.items()}


def summarise_paths(metrics: dict[str, np.ndarray], names: list[str]) -> pd.DataFrame:
    """One row per strategy: quantiles of the continuous metrics and probabilities of the threshold events."""
    rows = []
    for j, name in enumerate(names):
        row: dict[str, float | str] = {"strategy": name}
        for key in ("twr_ann", "max_dd", "underwater_years", "money_multiple"):
            q = np.quantile(metrics[key][:, j], QUANTILES)
            for qq, v in zip(QUANTILES, q):
                row[f"{key}_p{int(qq * 100):02d}"] = float(v)
        row["vol_ann_median"] = float(np.median(metrics["vol_ann"][:, j]))
        for key in ("hit_alert", "hit_review", "hit_stop", "loss_of_capital"):
            row[key] = float(metrics[key][:, j].mean())
        rows.append(row)
    return pd.DataFrame(rows).set_index("strategy")


def paired_difference(metrics: dict[str, np.ndarray], names: list[str], reference: str) -> pd.DataFrame:
    """Strategy minus reference on the SAME resampled paths: median, 5%-95% range and share of paths with a positive gap."""
    ref = names.index(reference)
    rows = []
    for j, name in enumerate(names):
        if j == ref:
            continue
        row: dict[str, float | str] = {"strategy": name}
        for key in ("twr_ann", "max_dd", "underwater_years"):
            d = metrics[key][:, j] - metrics[key][:, ref]
            row[f"{key}_diff_median"] = float(np.median(d))
            row[f"{key}_diff_p05"] = float(np.quantile(d, 0.05))
            row[f"{key}_diff_p95"] = float(np.quantile(d, 0.95))
            row[f"{key}_share_positive"] = float((d > 0).mean())
        rows.append(row)
    return pd.DataFrame(rows).set_index("strategy")


GRID_LEVELS = (-0.10, -0.125, -0.15, -0.175, -0.20, -0.225, -0.25, -0.30)


def threshold_grid(metrics: dict[str, np.ndarray], names: list[str], levels: tuple[float, ...] = GRID_LEVELS) -> pd.DataFrame:
    """Probability that the maximum drawdown of a 10-year path reaches AT LEAST each level (rows = levels).

    Used to calibrate alert / review / stop thresholds: a threshold that almost every path crosses is a routine event,
    not an alert.
    """
    dd = metrics["max_dd"]
    return pd.DataFrame({name: [float((dd[:, j] <= lvl).mean()) for lvl in levels] for j, name in enumerate(names)},
                        index=pd.Index(levels, name="drawdown_level"))
