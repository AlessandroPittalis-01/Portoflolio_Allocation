"""Load the ETF universe from ``config/universe_candidates.yaml``.

The YAML marks every value that is not yet confirmed with the word ``verify``.
Here ``verify`` becomes ``None``: an unknown value stays unknown, it is never guessed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from prm.config import REPO_ROOT

DEFAULT_UNIVERSE_PATH = REPO_ROOT / "config" / "universe_candidates.yaml"

# The two groups of assets defined in the YAML file.
TIERS = ("implementable", "research_only")


@dataclass(frozen=True)
class Asset:
    """One ETF (or ETC) of the universe."""

    id: str                          # short name used everywhere in the code, e.g. "dev_equity"
    name: str
    tier: str                        # "implementable" (first shortlist) or "research_only"
    risk_driver: str
    category: str                    # what the ETF represents; several candidates can share one category
    yahoo_symbol: str | None         # confirmed Yahoo symbol, or None if still to be found
    symbols_to_try: tuple[str, ...]  # unconfirmed guesses, tested by the --probe option
    isin: str | None
    base_currency: str | None
    search_text: str | None          # text used by --find when the ISIN is not known


def _known(value) -> str | None:
    """Return the value as text, or ``None`` if it is empty or marked ``verify``."""
    if value is None:
        return None
    text = str(value).strip()
    return None if text.lower() in ("", "verify", "n/a") else text


def load_universe(path: Path | str = DEFAULT_UNIVERSE_PATH) -> tuple[dict, list[Asset]]:
    """Return ``(criteria, assets)`` read from the YAML file.

    Raises
    ------
    ValueError
        If an asset has no id, name or risk driver, or two assets share an id.
    """
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    assets: list[Asset] = []
    seen: set[str] = set()

    for tier in TIERS:
        for item in raw.get(tier) or []:
            for key in ("id", "name", "risk_driver"):
                if key not in item:
                    raise ValueError(f"[{tier}] an asset is missing the field '{key}': {item}")
            if item["id"] in seen:
                raise ValueError(f"duplicate asset id: {item['id']}")
            seen.add(item["id"])

            assets.append(
                Asset(
                    id=item["id"],
                    name=item["name"],
                    tier=tier,
                    risk_driver=item["risk_driver"],
                    category=str(item.get("category") or item["risk_driver"]),
                    yahoo_symbol=_known(item.get("yahoo_symbol")),
                    symbols_to_try=tuple(str(s) for s in (item.get("yahoo_symbol_try") or [])),
                    isin=_known(item.get("isin")),
                    base_currency=_known(item.get("base_currency")),
                    search_text=_known(item.get("search")),
                )
            )

    return raw.get("criteria") or {}, assets
