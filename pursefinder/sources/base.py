from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

import requests

from ..models import Listing

BROWSER_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0 Safari/537.36"
)

_IMAGE_RE = re.compile(r"^https?://\S+\.(?:jpe?g|png|webp)(?:\?\S*)?$", re.IGNORECASE)
_PRICE_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?)")


class Source(ABC):
    """A marketplace we can ask for its newest listings matching a search."""

    name: str

    def __init__(self, options: dict | None = None):
        self.options = options or {}
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "en-US,en;q=0.9"})

    @abstractmethod
    def search(self, query: str, max_price: float) -> list[Listing]:
        """Return the newest listings for `query`, newest first."""

    def close(self) -> None:
        self.session.close()


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value)
    match = _PRICE_RE.search(text) or re.search(r"(\d+(?:\.\d+)?)", text.replace(",", ""))
    return float(match.group(1).replace(",", "")) if match else None


def find_image_urls(obj: Any, limit: int = 8) -> list[str]:
    """Collect image URLs anywhere inside a JSON blob.

    Unofficial marketplace APIs change field names often; walking the whole object keeps
    working when e.g. `pictures[0].url` becomes `photos[0].formats.large`.
    """
    found: list[str] = []

    def walk(node: Any) -> None:
        if len(found) >= limit:
            return
        if isinstance(node, str):
            if _IMAGE_RE.match(node) and node not in found:
                found.append(node)
        elif isinstance(node, dict):
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(obj)
    return found

