"""Stress tests of a portfolio through its risk factors (IPS decision 39, step 4).

Three tools, all LINEAR in the factors of stage 11 (loss = sum of beta_i x factor move_i):

1. Historical episodes. (a) DIRECT: the weighted PLN return of the ETFs in the window, only where the ETFs existed
   (coverage = share of the portfolio weight with data; never filled with a guess). (b) REPLAYED: the realised moves of
   the FACTORS in the window (they have a longer history than the new ETFs) multiplied by today's betas; a factor with
   no data in the window counts as 0 and is listed.
2. Hypothetical scenarios: factor moves written in config/stress_hypothetical.yaml before looking at results.
3. Reverse stress test: the SMALLEST (most plausible) combination of factor moves that produces a given loss L. With
   factor covariance S_h for the horizon, the shock d minimises d' S_h^-1 d subject to beta' d = -L:

       d* = -L * S_h beta / (beta' S_h beta),      distance = L / sqrt(beta' S_h beta)

   The distance is how many standard deviations of the portfolio's factor-driven return the loss is; under normality
   the probability of a loss at least that big is Phi(-distance). d* tells which factors would typically drive it.

Honest limits: linear (no convexity), betas are those of one window, the part not explained by factors is ignored,
normality is assumed in the reverse stress probability (fat tails make it optimistic), and hypothetical sizes are
assumptions, not forecasts.
"""

from __future__ import annotations

import math
from pathlib import Path
from statistics import NormalDist

import numpy as np
import pandas as pd
import yaml

from prm.config import REPO_ROOT
from prm.risk.stress import scenario_return

DEFAULT_HYPOTHETICAL_PATH = REPO_ROOT / "config" / "stress_hypothetical.yaml"


class StressConfigError(ValueError):
    pass


def load_hypothetical(path: Path | str = DEFAULT_HYPOTHETICAL_PATH, factor_names: list[str] | None = None) -> dict[str, dict]:
    """Read the hypothetical scenarios: {id: {"description": str, "shocks": {factor: move}}}."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    scen = raw.get("scenarios")
    if not isinstance(scen, dict) or not scen:
        raise StressConfigError("scenarios must be a non-empty mapping")
    out = {}
    for sid, body in scen.items():
        if not isinstance(body, dict):
            raise StressConfigError(f"scenario '{sid}' must be a mapping")
        shocks = {k: v for k, v in body.items() if k != "description"}
        if not shocks:
            raise StressConfigError(f"scenario '{sid}' has no factor shock")
        for k, v in shocks.items():
            if not isinstance(v, (int, float)) or isinstance(v, bool) or not -1.0 < v < 10.0:
                raise StressConfigError(f"scenario '{sid}', factor '{k}': the move must be a number between -1 and 10")
            if factor_names is not None and k not in factor_names:
                raise StressConfigError(f"scenario '{sid}': unknown factor '{k}' (known: {factor_names})")
        out[str(sid)] = {"description": str(body.get("description", "")), "shocks": {k: float(v) for k, v in shocks.items()}}
    return out


def direct_historical(pln: pd.DataFrame, weights: pd.Series, scenarios: list[dict]) -> pd.DataFrame:
    """Per scenario: weighted PLN return of the ETFs that existed, rescaled to their weight (``covered_return``), the
    coverage (share of the weight with data) and the number of ETFs missing."""
    rows = []
    for s in scenarios:
        rets = pd.Series({a: scenario_return(pln[a], s["start"], s["end"]) for a in weights.index})
        have = rets.notna()
        cov = float(weights[have].sum())
        rows.append({"scenario": s["id"], "coverage": cov, "n_missing": int((~have).sum()),
                     "covered_return": float((weights[have] * rets[have]).sum() / cov) if cov > 0 else float("nan")})
    return pd.DataFrame(rows).set_index("scenario")


def factor_moves(factors: pd.DataFrame, scenarios: list[dict]) -> pd.DataFrame:
    """Compound factor return in each historical window (rows = scenarios, columns = factors); NaN = no data."""
    data = {s["id"]: {f: scenario_return(factors[f], s["start"], s["end"]) for f in factors.columns} for s in scenarios}
    return pd.DataFrame(data).T


def apply_shocks(beta: pd.Series, shocks: pd.Series) -> dict:
    """Linear loss/gain: sum beta_i x move_i. Factors without a shock (or NaN) count as 0 and are listed as missing."""
    s = shocks.reindex(beta.index)
    missing = [f for f in beta.index if pd.isna(s[f])]
    contrib = (beta * s.fillna(0.0))
    return {"pnl": float(contrib.sum()), "contrib": contrib, "missing": missing}


def reverse_stress(beta: pd.Series, cov_daily: pd.DataFrame, loss: float, horizon_days: int) -> dict:
    """Most plausible factor shock that brings the portfolio to -``loss`` over ``horizon_days`` (see module doc)."""
    if loss <= 0 or horizon_days < 1:
        raise ValueError("loss must be positive and horizon at least 1 day")
    b = beta.to_numpy(dtype=float)
    S = cov_daily.reindex(index=beta.index, columns=beta.index).to_numpy(dtype=float) * horizon_days
    var = float(b @ S @ b)
    if var <= 0:
        raise ValueError("the factor-driven variance of the portfolio is zero")
    shock = -loss * (S @ b) / var
    dist = loss / math.sqrt(var)
    sd = np.sqrt(np.diag(S))
    return {"shock": pd.Series(shock, index=beta.index), "shock_in_sigmas": pd.Series(shock / sd, index=beta.index),
            "distance": dist, "normal_prob": float(NormalDist().cdf(-dist)), "sigma_portfolio": math.sqrt(var)}
