"""Poshmark via the JSON endpoint its own website uses (unofficial; may change)."""

from __future__ import annotations

import json

from ..models import Listing
from .base import Source, find_image_urls, to_float

SEARCH_URL = "https://poshmark.com/vm-rest/posts"


class PoshmarkSource(Source):
    name = "poshmark"

    def search(self, query: str, max_price: float) -> list[Listing]:
        request = {
            "filters": {"department": "Women", "inventory_status": ["available"]},
            "query": query,
            "sort_by": "added_desc",
            "count": 48,
        }
        resp = self.session.get(
            SEARCH_URL,
            params={"request": json.dumps(request), "summarize": "true", "app_version": "2.55"},
            headers={"Accept": "application/json"},
            timeout=20,
        )
        resp.raise_for_status()
        return parse_results(resp.json())


def parse_results(body: dict) -> list[Listing]:
    listings = []
    for post in body.get("data", []):
        images = []
        cover = (post.get("cover_shot") or {}).get("url")
        if cover:
            images.append(cover)
        for pic in post.get("pictures", []):
            if pic.get("url") and pic["url"] not in images:
                images.append(pic["url"])
        if not images:
            images = find_image_urls(post)
        price = post.get("price_amount", {}).get("val") if isinstance(post.get("price_amount"), dict) else post.get("price")
        listings.append(
            Listing(
                source="poshmark",
                id=str(post["id"]),
                title=post.get("title", ""),
                price=to_float(price),
                url=f"https://poshmark.com/listing/{post['id']}",
                image_urls=images,
                listed_at=post.get("created_at"),
            )
        )
    return listings
