"""eBay via the official Browse API (free keys from developer.ebay.com)."""

from __future__ import annotations

import os
import time

from ..models import Listing
from .base import Source, to_float

TOKEN_URL = "https://api.ebay.com/identity/v1/oauth2/token"
SEARCH_URL = "https://api.ebay.com/buy/browse/v1/item_summary/search"
WOMENS_BAGS_CATEGORY = "169291"


class EbaySource(Source):
    name = "ebay"

    def __init__(self, options: dict | None = None):
        super().__init__(options)
        self.client_id = os.environ.get("EBAY_CLIENT_ID")
        self.client_secret = os.environ.get("EBAY_CLIENT_SECRET")
        if not (self.client_id and self.client_secret):
            raise RuntimeError("set EBAY_CLIENT_ID and EBAY_CLIENT_SECRET to search eBay")
        self.marketplace = self.options.get("marketplace", "EBAY_US")
        self.category = str(self.options.get("category_id", WOMENS_BAGS_CATEGORY))
        self._token: str | None = None
        self._token_expires = 0.0

    def _get_token(self) -> str:
        if self._token and time.time() < self._token_expires - 60:
            return self._token
        resp = self.session.post(
            TOKEN_URL,
            auth=(self.client_id, self.client_secret),
            data={"grant_type": "client_credentials", "scope": "https://api.ebay.com/oauth/api_scope"},
            timeout=20,
        )
        resp.raise_for_status()
        body = resp.json()
        self._token = body["access_token"]
        self._token_expires = time.time() + int(body.get("expires_in", 7200))
        return self._token

    def search(self, query: str, max_price: float) -> list[Listing]:
        resp = self.session.get(
            SEARCH_URL,
            headers={
                "Authorization": f"Bearer {self._get_token()}",
                "X-EBAY-C-MARKETPLACE-ID": self.marketplace,
            },
            params={
                "q": query,
                "category_ids": self.category,
                "sort": "newlyListed",
                "limit": 50,
                "filter": f"price:[..{max_price:g}],priceCurrency:USD",
            },
            timeout=20,
        )
        resp.raise_for_status()
        return parse_results(resp.json())


def parse_results(body: dict) -> list[Listing]:
    listings = []
    for item in body.get("itemSummaries", []):
        images = []
        if item.get("image", {}).get("imageUrl"):
            images.append(item["image"]["imageUrl"])
        images += [i["imageUrl"] for i in item.get("additionalImages", []) if i.get("imageUrl")]
        price = item.get("price") or item.get("currentBidPrice") or {}
        listings.append(
            Listing(
                source="ebay",
                id=item["itemId"],
                title=item.get("title", ""),
                price=to_float(price.get("value")),
                currency=price.get("currency", "USD"),
                url=item.get("itemWebUrl", ""),
                image_urls=images,
                listed_at=item.get("itemCreationDate"),
            )
        )
    return listings
