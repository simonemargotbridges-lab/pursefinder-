from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    """One secondhand listing, normalized across marketplaces."""

    source: str
    id: str
    title: str
    price: float | None
    url: str
    image_urls: list[str] = field(default_factory=list)
    currency: str = "USD"
    listed_at: str | None = None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.id}"
