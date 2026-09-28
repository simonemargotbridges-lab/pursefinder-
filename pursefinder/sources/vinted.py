"""Vinted via the JSON endpoint its own website uses (unofficial; may change)."""

from __future__ import annotations

from ..models import Listing
from .base import Source, find_image_urls, to_float


class VintedSource(Source):
    name = "vinted"

    def __init__(self, options: dict | None = None):
        super().__init__(options)
        self.base = self.options.get("base_url", "https://www.vinted.com").rstrip("/")
        self._has_cookie = False

    def _ensure_cookie(self) -> None:
        # Vinted's API only answers once the homepage has handed out a session cookie.
        if not self._has_cookie:
            self.session.get(self.base + "/", timeout=20).raise_for_status()
            self._has_cookie = True

    def search(self, query: str, max_price: float, _retried: bool = False) -> list[Listing]:
        self._ensure_cookie()
        resp = self.session.get(
            f"{self.base}/api/v2/catalog/items",
            params={
                "search_text": query,
                "order": "newest_first",
                "price_to": int(max_price),
                "per_page": 96,
                "page": 1,
            },
            headers={"Accept": "application/json"},
            timeout=20,
        )
        if resp.status_code == 401 and not _retried:  # cookie expired; refresh once
            self._has_cookie = False
            return self.search(query, max_price, _retried=True)
        resp.raise_for_status()
        return parse_results(resp.json(), self.base)


def parse_results(body: dict, base: str = "https://www.vinted.com") -> list[Listing]:
    listings = []
    for item in body.get("items", []):
        photos = item.get("photos") or ([item["photo"]] if item.get("photo") else [])
        images = [p.get("full_size_url") or p.get("url") for p in photos if isinstance(p, dict)]
        images = [u for u in images if u] or find_image_urls(item)
        price = item.get("price")
        currency = "USD"
        if isinstance(price, dict):
            currency = price.get("currency_code", currency)
            price = price.get("amount")
        listings.append(
            Listing(
                source="vinted",
                id=str(item["id"]),
                title=item.get("title", ""),
                price=to_float(price),
                currency=item.get("currency", currency),
                url=item.get("url") or f"{base}/items/{item['id']}",
                image_urls=images,
            )
        )
    return listings
