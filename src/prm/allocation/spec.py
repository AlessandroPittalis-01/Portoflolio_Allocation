"""Read ``config/portfolio.yaml``: class risk budgets, how many ETFs per class, the choice rules, the estimator."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from prm.allocation.choose import RISKY_CLASSES, ChoiceRules
from prm.config import REPO_ROOT

DEFAULT_PORTFOLIO_PATH = REPO_ROOT / "config" / "portfolio.yaml"
COVARIANCES = ("sample", "ewma", "ledoit_wolf")
MAX_RISKY_ETFS = 6                                       # IPS decision 9


@dataclass(frozen=True)
class PortfolioSpec:
    class_budgets: dict[str, float]    # share of portfolio RISK per class (sums to 1)
    rules: ChoiceRules                 # how the ETFs of each class are chosen
    secondary_share: dict[str, float]  # share of a class budget given to its non-core ETFs (absent = equal split)
    benchmark_equity: str              # fixed 60/40 benchmark legs (IPS decision 29), independent of the choice
    benchmark_bond: str
    covariance: str                    # sample | ewma | ledoit_wolf
    ewma_lambda: float


def load_portfolio(path: Path | str = DEFAULT_PORTFOLIO_PATH) -> PortfolioSpec:
    with open(path, "r", encoding="utf-8") as f:
        raw = (yaml.safe_load(f) or {}).get("allocation") or {}
    budgets = {str(k): float(v) for k, v in (raw.get("class_budgets") or {}).items()}
    if not budgets or set(budgets) - set(RISKY_CLASSES):
        raise ValueError(f"class_budgets needs classes from {RISKY_CLASSES}, got {sorted(budgets)}")
    if any(v <= 0 for v in budgets.values()):
        raise ValueError("class budgets must be positive")
    if abs(sum(budgets.values()) - 1.0) > 1e-6:
        raise ValueError(f"class budgets must add up to 1, got {sum(budgets.values()):.4f}")
    if "equity" not in budgets or "bond" not in budgets:
        raise ValueError("class_budgets needs at least 'equity' and 'bond' (the 60/40 benchmark uses them)")
    max_etfs = {str(k): v for k, v in (raw.get("max_etfs") or {}).items()}
    for cls in budgets:
        n = max_etfs.get(cls)
        if not isinstance(n, int) or isinstance(n, bool) or n < 1:
            raise ValueError(f"max_etfs['{cls}'] must be an integer >= 1")
    if sum(max_etfs[c] for c in budgets) > MAX_RISKY_ETFS:
        raise ValueError(f"at most {MAX_RISKY_ETFS} risky ETFs in total (IPS decision 9)")
    secondary = {str(k): float(v) for k, v in (raw.get("secondary_share") or {}).items()}
    for cls, s in secondary.items():
        if cls not in budgets or not 0 < s < 1:
            raise ValueError(f"secondary_share['{cls}'] needs a class in class_budgets and a value strictly between 0 and 1")
    bench = raw.get("benchmark_60_40") or {}
    b_eq, b_bd = bench.get("equity"), bench.get("bond")
    if not isinstance(b_eq, str) or not isinstance(b_bd, str) or b_eq == b_bd:
        raise ValueError("benchmark_60_40 needs two different ETF ids: 'equity' and 'bond'")
    sel = raw.get("selection") or {}
    rho = float(sel.get("rho_max", 0.90))
    if not 0 < rho < 1:
        raise ValueError("selection.rho_max must be in (0, 1)")
    overlap = int(sel.get("min_overlap_days", 500))
    hist = float(sel.get("min_history_years", 5))
    if overlap < 100 or hist <= 0:
        raise ValueError("selection.min_overlap_days must be >= 100 and min_history_years > 0")
    cov = raw.get("covariance", "ledoit_wolf")
    if cov not in COVARIANCES:
        raise ValueError(f"covariance must be one of {COVARIANCES}, got '{cov}'")
    lam = float(raw.get("ewma_lambda", 0.94))
    if not 0 < lam <= 1:
        raise ValueError("ewma_lambda must be in (0, 1]")
    rules = ChoiceRules(rho_max=rho, max_etfs={c: max_etfs[c] for c in budgets}, min_overlap_days=overlap,
                        min_history_years=hist, currency=str(sel.get("currency", "EUR")))
    return PortfolioSpec(budgets, rules, secondary, b_eq, b_bd, cov, lam)
