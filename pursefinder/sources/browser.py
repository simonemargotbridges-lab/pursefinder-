"""Sites without a usable JSON API, read by rendering the search page in headless Chromium.

It doesn't depend on any site's exact HTML: it looks for links to item pages that contain
a photo, and pulls the first "$123" price out of each card. Needs:

    pip install playwright && playwright install chromium
"""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus, urljoin

from ..models import Listing
from .base import BROWSER_UA, Source, to_float

log = logging.getLogger(__name__)

# name -> (search URL template, regex that identifies an item-page link)
PRESETS: dict[str, tuple[str, str]] = {
    "mercari": ("https://www.mercari.com/search/?keyword={q}&sortBy=2&itemStatuses=1", r"/(?:us/)?item/(m\d+)"),
    "thredup": ("https://www.thredup.com/search?search_text={q}&sort=newest_first", r"/product/[^?#]*?(\d{6,})"),
    "vestiaire": ("https://us.vestiairecollective.com/search/?q={q}&sortBy=newIn", r"-(\d{6,})\.shtml"),
    "therealreal": ("https://www.therealreal.com/shop?keywords={q}&sort=newest", r"/products/[^?#]*?([\w-]+)$"),
}

# Runs in the page: every <a> that contains an <img>, with the card text around it.
EXTRACT_JS = """
() => Array.from(document.querySelectorAll('a[href]')).map(a => {
  const imgs = Array.from(a.querySelectorAll('img'));
  if (!imgs.length) return null;
  let card = a;
  for (let i = 0; i < 3 && card.parentElement && !/\\$\\s?\\d/.test(card.innerText || ''); i++) {
    card = card.parentElement;
  }
  const pick = img => {
    const set = img.getAttribute('srcset') || img.getAttribute('data-srcset');
    if (set) {
      const parts = set.split(',').map(s => s.trim().split(/\\s+/)[0]).filter(Boolean);
      if (parts.length) return parts[parts.length - 1];
    }
    return img.currentSrc || img.getAttribute('src') || img.getAttribute('data-src');
  };
  return {
    href: a.href,
    images: imgs.map(pick).filter(u => u && !u.startsWith('data:')),
    alt: imgs.map(i => i.alt || '').join(' ').trim(),
    text: (card.innerText || '').trim().slice(0, 400),
  };
}).filter(Boolean)
"""

_PRICE_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d{2})?")


def parse_cards(cards: list[dict], site: str, item_pattern: str, base_url: str) -> list[Listing]:
    item_re = re.compile(item_pattern)
    listings: dict[str, Listing] = {}
    for card in cards:
        href = urljoin(base_url, card.get("href", "")).split("#")[0]
        match = item_re.search(href.split("?")[0])
        if not match:
            continue
        item_id = match.group(1)
        prices = _PRICE_RE.findall(card.get("text", ""))
        # With a sale, cards show "$80 $200" -- the lowest number is what you'd pay.
        price = min((to_float(p) for p in prices), default=None)
        images = [urljoin(base_url, u) for u in card.get("images", [])]
        if item_id in listings:
            existing = listings[item_id]
            existing.image_urls += [u for u in images if u not in existing.image_urls]
            existing.price = existing.price if existing.price is not None else price
            continue
        title = card.get("alt") or card.get("text", "").split("\n")[0]
        listings[item_id] = Listing(
            source=site, id=item_id, title=title, price=price, url=href.split("?")[0], image_urls=images
        )
    return list(listings.values())


class BrowserSource(Source):
    def __init__(self, name: str, options: dict | None = None):
        super().__init__(options)
        self.name = name
        template, pattern = PRESETS.get(name, (None, None))
        self.url_template = self.options.get("search_url", template)
        self.item_pattern = self.options.get("item_link_pattern", pattern)
        if not (self.url_template and self.item_pattern):
            raise ValueError(f"{name}: needs search_url and item_link_pattern options")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RuntimeError("install Playwright to search this site: pip install playwright") from exc
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=True)
        self._context = self._browser.new_context(user_agent=BROWSER_UA, viewport={"width": 1400, "height": 2000})

    def search(self, query: str, max_price: float) -> list[Listing]:
        url = self.url_template.format(q=quote_plus(query), max_price=int(max_price))
        page = self._context.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(4_000)  # let client-side rendering fill in the results
            for _ in range(3):  # scroll to trigger lazy-loaded photos
                page.mouse.wheel(0, 2500)
                page.wait_for_timeout(800)
            cards = page.evaluate(EXTRACT_JS)
        finally:
            page.close()
        listings = parse_cards(cards, self.name, self.item_pattern, url)
        if not listings:
            log.warning("%s: no listings found on %s (blocked, or page layout changed?)", self.name, url)
        return listings

    def close(self) -> None:
        super().close()
        self._context.close()
        self._browser.close()
        self._pw.stop()
