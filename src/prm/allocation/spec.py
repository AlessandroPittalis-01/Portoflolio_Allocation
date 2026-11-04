"""Read ``config/portfolio.yaml``: which ETFs the allocation uses, their role, and the benchmark."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from prm.config import REPO_ROOT

DEFAULT_PORTFOLIO_PATH = REPO_ROOT / "config" / "portfolio.yaml"
ROLES = ("equity", "bond", "real", "cash")
COVARIANCES = ("sample", "ewma", "ledoit_wolf")


@dataclass(frozen=True)
class PortfolioSpec:
    roles: dict[str, str]          # asset id -> role (equity, bond, real, cash)
    cash_id: str                   # the single cash-like ETF, used only for volatility scaling
    benchmark_equity: str          # 60/40 benchmark legs
    benchmark_bond: str
    covariance: str                # sample | ewma | ledoit_wolf
    ewma_lambda: float

    @property
    def risky_ids(self) -> list[str]:
        return [a for a, r in self.roles.items() if r != "cash"]


def load_portfolio(path: Path | str = DEFAULT_PORTFOLIO_PATH) -> PortfolioSpec:
    with open(path, "r", encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("allocation") or {}
    roles: dict[str, str] = {}
    for item in raw.get("universe") or []:
        if "id" not in item or "role" not in item:
            raise ValueError(f"every universe entry needs 'id' and 'role': {item}")
        if item["role"] not in ROLES:
            raise ValueError(f"role of {item['id']} must be one of {ROLES}, got '{item['role']}'")
        if item["id"] in roles:
            raise ValueError(f"duplicate asset id in the allocation universe: {item['id']}")
        roles[item["id"]] = item["role"]
    cash = [a for a, r in roles.items() if r == "cash"]
    if len(cash) != 1:
        raise ValueError(f"exactly one cash-like ETF is needed, found {len(cash)}")
    if len(roles) - 1 < 3:
        raise ValueError("at least 3 risky ETFs are needed")
    bench = raw.get("benchmark_60_40") or {}
    eq, bd = bench.get("equity"), bench.get("bond")
    if roles.get(eq) != "equity" or roles.get(bd) != "bond":
        raise ValueError("benchmark_60_40 needs an 'equity' ETF and a 'bond' ETF from the universe")
    cov = raw.get("covariance", "ledoit_wolf")
    if cov not in COVARIANCES:
        raise ValueError(f"covariance must be one of {COVARIANCES}, got '{cov}'")
    lam = float(raw.get("ewma_lambda", 0.94))
    if not 0 < lam <= 1:
        raise ValueError("ewma_lambda must be in (0, 1]")
    return PortfolioSpec(roles, cash[0], eq, bd, cov, lam)
