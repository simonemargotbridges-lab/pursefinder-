"""Depop via the JSON endpoint its own website uses (unofficial; may change)."""

from __future__ import annotations

from ..models import Listing
from .base import Source, find_image_urls, to_float

SEARCH_URL = "https://webapi.depop.com/api/v3/search/products/"


class DepopSource(Source):
    name = "depop"

    def search(self, query: str, max_price: float) -> list[Listing]:
        resp = self.session.get(
            SEARCH_URL,
            params={
                "what": query,
                "sort": "newlyListed",
                "priceMax": int(max_price),
                "country": self.options.get("country", "us"),
                "currency": "USD",
                "itemsPerPage": 48,
            },
            headers={"Accept": "application/json", "Referer": "https://www.depop.com/"},
            timeout=20,
        )
        resp.raise_for_status()
        return parse_results(resp.json())


def _best_rendition(picture: dict) -> str | None:
    """Depop gives each photo as {"150": url, "640": url, ...}; take the largest <= 1280."""
    sized = [(int(k), v) for k, v in picture.items() if str(k).isdigit() and isinstance(v, str)]
    if not sized:
        found = find_image_urls(picture, limit=1)
        return found[0] if found else None
    sized.sort()
    fitting = [s for s in sized if s[0] <= 1280] or sized[:1]
    return fitting[-1][1]


def parse_results(body: dict) -> list[Listing]:
    listings = []
    for product in body.get("products", []):
        pictures = product.get("pictures") or ([product["preview"]] if product.get("preview") else [])
        images = [u for u in (_best_rendition(p) for p in pictures if isinstance(p, dict)) if u]
        if not images:
            images = find_image_urls(product)
        price = product.get("price") or {}
        amount = price.get("discountedPriceAmount") or price.get("priceAmount") if isinstance(price, dict) else price
        slug = product.get("slug") or product.get("id")
        listings.append(
            Listing(
                source="depop",
                id=str(product.get("id") or slug),
                title=product.get("description") or product.get("title") or slug or "",
                price=to_float(amount),
                currency=price.get("currencyName", "USD") if isinstance(price, dict) else "USD",
                url=f"https://www.depop.com/products/{slug}/",
                image_urls=images,
                listed_at=product.get("dateCreated"),
            )
        )
    return listings
