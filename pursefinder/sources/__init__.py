from __future__ import annotations

from .base import Source
from .browser import PRESETS, BrowserSource
from .depop import DepopSource
from .ebay import EbaySource
from .poshmark import PoshmarkSource
from .vinted import VintedSource

API_SOURCES: dict[str, type[Source]] = {
    "ebay": EbaySource,
    "poshmark": PoshmarkSource,
    "depop": DepopSource,
    "vinted": VintedSource,
}


def build_source(name: str, options: dict | None) -> Source:
    """Create a source by name. Anything that isn't an API source is rendered in a browser."""
    options = options or {}
    if name in API_SOURCES:
        return API_SOURCES[name](options)
    if name in PRESETS or "search_url" in options:
        return BrowserSource(name, options)
    raise ValueError(f"Unknown source {name!r}. Known: {sorted(API_SOURCES) + sorted(PRESETS)}")
