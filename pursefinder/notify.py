from __future__ import annotations

import html
import json
import logging
from pathlib import Path

import requests

from .models import Listing
from .vision import Verdict

log = logging.getLogger(__name__)

BAG_NAMES = {
    "balenciaga_city": "Balenciaga City",
    "balenciaga_other_motorcycle": "Balenciaga Motorcycle bag (not City)",
    "chloe_paddington": "Chloé Paddington",
}


class Notifier:
    """Sends each match to the terminal, a log file, a browsable HTML page, and optionally your phone."""

    def __init__(self, data_dir: Path, ntfy_topic: str | None = None, discord_webhook_url: str | None = None):
        self.matches_path = data_dir / "matches.jsonl"
        self.html_path = data_dir / "matches.html"
        self.ntfy_topic = ntfy_topic
        self.discord_webhook_url = discord_webhook_url

    def send(self, listing: Listing, verdict: Verdict) -> None:
        bag = BAG_NAMES.get(verdict.bag, verdict.bag)
        price = f"${listing.price:,.0f}" if listing.price is not None else "price?"
        headline = f"{bag} for {price} on {listing.source} ({verdict.confidence}% sure)"
        flags = "; ".join(verdict.authenticity_red_flags)
        details = f"{verdict.reasoning}\nSeller title: {listing.title}" + (f"\n⚠️ Check authenticity: {flags}" if flags else "")

        print(f"\n🎯 {headline}\n   {listing.url}\n   {details.replace(chr(10), chr(10) + '   ')}\n", flush=True)

        record = {"listing": listing.__dict__, "verdict": verdict.model_dump()}
        with self.matches_path.open("a") as f:
            f.write(json.dumps(record) + "\n")
        self._write_html()

        if self.ntfy_topic:
            message = {
                "topic": self.ntfy_topic,
                "title": headline,
                "message": f"{details}\n{listing.url}",
                "click": listing.url,
                "tags": ["handbag"],
            }
            if listing.image_urls:
                message["attach"] = listing.image_urls[0]
            self._safe(requests.post, "https://ntfy.sh/", json=message, timeout=15)
        if self.discord_webhook_url:
            embed = {"title": headline, "url": listing.url, "description": details[:4000]}
            if listing.image_urls:
                embed["image"] = {"url": listing.image_urls[0]}
            self._safe(requests.post, self.discord_webhook_url, json={"embeds": [embed]}, timeout=15)

    @staticmethod
    def _safe(fn, *args, **kwargs) -> None:
        try:
            fn(*args, **kwargs).raise_for_status()
        except Exception as exc:  # noqa: BLE001 - a failed push shouldn't stop the search
            log.warning("Notification failed: %s", exc)

    def _write_html(self) -> None:
        rows = [json.loads(line) for line in self.matches_path.read_text().splitlines() if line.strip()]
        cards = []
        for row in reversed(rows):  # newest first
            l, v = row["listing"], row["verdict"]
            img = html.escape(l["image_urls"][0]) if l["image_urls"] else ""
            price = f"${l['price']:,.0f}" if l["price"] is not None else "?"
            flags = "".join(f"<li>{html.escape(f)}</li>" for f in v["authenticity_red_flags"])
            cards.append(
                f"""<a class="card" href="{html.escape(l['url'])}" target="_blank" rel="noopener">
  <img src="{img}" loading="lazy" alt="">
  <div class="info"><b>{html.escape(BAG_NAMES.get(v['bag'], v['bag']))}</b> · {price} · {html.escape(l['source'])}
  <small>{v['confidence']}% sure — {html.escape(v['reasoning'])}</small>
  <small class="title">“{html.escape(l['title'])}”</small>
  {f'<ul class="flags">{flags}</ul>' if flags else ''}</div></a>"""
            )
        self.html_path.write_text(
            """<!doctype html><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bag Finder Matches</title>
<style>
body{font-family:system-ui,sans-serif;margin:0;padding:16px;background:#faf8f5;color:#222}
h1{font-size:1.4rem}.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:16px}
.card{display:block;background:#fff;border-radius:10px;overflow:hidden;text-decoration:none;color:inherit;box-shadow:0 1px 4px #0002}
.card img{width:100%;aspect-ratio:1;object-fit:cover;background:#eee}.info{padding:10px}
small{display:block;color:#555;margin-top:4px}.title{font-style:italic}.flags{color:#a33;font-size:.8rem;padding-left:18px}
</style><h1>Bag Finder Matches</h1><div class="grid">"""
            + "\n".join(cards)
            + "</div>"
        )
