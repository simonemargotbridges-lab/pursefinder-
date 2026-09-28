from __future__ import annotations

from pathlib import Path

import pytest

from pursefinder.agent import BagFinder
from pursefinder.config import Config, load_config
from pursefinder.models import Listing
from pursefinder.notify import Notifier
from pursefinder.sources import base, depop, ebay, poshmark, vinted
from pursefinder.sources.browser import EXTRACT_JS, PRESETS, parse_cards
from pursefinder.store import SeenStore
from pursefinder.vision import Verdict


# --- marketplace response parsing -------------------------------------------------


def test_ebay_parse():
    body = {
        "itemSummaries": [
            {
                "itemId": "v1|123|0",
                "title": "Womens black leather purse",
                "price": {"value": "249.99", "currency": "USD"},
                "image": {"imageUrl": "https://i.ebayimg.com/a.jpg"},
                "additionalImages": [{"imageUrl": "https://i.ebayimg.com/b.jpg"}],
                "itemWebUrl": "https://www.ebay.com/itm/123",
                "itemCreationDate": "2026-09-28T10:00:00.000Z",
            }
        ]
    }
    [item] = ebay.parse_results(body)
    assert item.key == "ebay:v1|123|0"
    assert item.price == 249.99
    assert item.image_urls == ["https://i.ebayimg.com/a.jpg", "https://i.ebayimg.com/b.jpg"]


def test_poshmark_parse():
    body = {
        "data": [
            {
                "id": "abc",
                "title": "Chloe purse",
                "price_amount": {"val": "320"},
                "cover_shot": {"url": "https://di2ponv0v5otw.cloudfront.net/posts/1.jpg"},
                "pictures": [{"url": "https://di2ponv0v5otw.cloudfront.net/posts/2.jpg"}],
            }
        ]
    }
    [item] = poshmark.parse_results(body)
    assert item.price == 320
    assert item.url == "https://poshmark.com/listing/abc"
    assert len(item.image_urls) == 2


def test_depop_parse_picks_one_rendition_per_photo():
    body = {
        "products": [
            {
                "id": 99,
                "slug": "seller-chloe-bag",
                "price": {"priceAmount": "150.00", "currencyName": "USD"},
                "pictures": [
                    {"150": "https://media-photos.depop.com/p1/150.jpg", "640": "https://media-photos.depop.com/p1/640.jpg"},
                    {"150": "https://media-photos.depop.com/p2/150.jpg", "1280": "https://media-photos.depop.com/p2/1280.jpg"},
                ],
            }
        ]
    }
    [item] = depop.parse_results(body)
    assert item.image_urls == ["https://media-photos.depop.com/p1/640.jpg", "https://media-photos.depop.com/p2/1280.jpg"]
    assert item.price == 150
    assert item.url == "https://www.depop.com/products/seller-chloe-bag/"


def test_vinted_parse():
    body = {
        "items": [
            {
                "id": 7,
                "title": "Sac cuir",
                "price": {"amount": "120.0", "currency_code": "USD"},
                "photo": {"url": "https://images1.vinted.net/t/x.jpeg?s=1"},
                "url": "https://www.vinted.com/items/7-sac",
            }
        ]
    }
    [item] = vinted.parse_results(body)
    assert item.price == 120
    assert item.image_urls == ["https://images1.vinted.net/t/x.jpeg?s=1"]


def test_helpers():
    assert base.to_float("$1,250.00") == 1250
    assert base.to_float("US $89") == 89
    assert base.to_float(None) is None
    blob = {"a": [{"deep": {"u": "https://x.com/1.webp"}}, "not an image", "https://x.com/2.JPG?w=3"]}
    assert base.find_image_urls(blob) == ["https://x.com/1.webp", "https://x.com/2.JPG?w=3"]


# --- browser extraction ----------------------------------------------------------

CARD_PAGE = """<html><body>
<div class="tile"><a href="/us/item/m123456/"><img src="https://u-mercari-images.mercdn.net/photos/m123456_1.jpg" alt="Leather bag"></a>
  <p>Leather bag</p><span>$450</span> <s>$900</s></div>
<div class="tile"><a href="/us/item/m999/"><img srcset="https://img/s.jpg 200w, https://img/l.jpg 800w" alt="Chloe purse"></a>
  <span>$95</span></div>
<a href="/about"><img src="https://x/logo.png"></a>
</body></html>"""


def test_parse_cards_without_browser():
    cards = [
        {"href": "https://www.mercari.com/us/item/m1/?ref=x", "images": ["https://a/1.jpg"], "alt": "", "text": "Bag\n$80\n$200"},
        {"href": "https://www.mercari.com/us/item/m1/", "images": ["https://a/2.jpg"], "alt": "", "text": ""},
        {"href": "https://www.mercari.com/help", "images": ["https://a/3.jpg"], "alt": "", "text": "$5"},
    ]
    [item] = parse_cards(cards, "mercari", PRESETS["mercari"][1], "https://www.mercari.com/search/")
    assert item.id == "m1" and item.price == 80
    assert item.image_urls == ["https://a/1.jpg", "https://a/2.jpg"]


def test_extract_js_in_real_browser(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    page_file = tmp_path / "search.html"
    page_file.write_text(CARD_PAGE)
    with sync_api.sync_playwright() as pw:
        try:
            browser = pw.chromium.launch()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"no chromium available: {exc}")
        page = browser.new_page()
        page.goto(page_file.as_uri())
        cards = page.evaluate(EXTRACT_JS)
        browser.close()
    listings = parse_cards(cards, "mercari", PRESETS["mercari"][1], "https://www.mercari.com/search/")
    by_id = {l.id: l for l in listings}
    assert set(by_id) == {"m123456", "m999"}
    assert by_id["m123456"].price == 450
    assert by_id["m999"].price == 95
    assert by_id["m999"].image_urls == ["https://img/l.jpg"]


# --- the watch loop --------------------------------------------------------------


class FakeSource:
    name = "fake"

    def __init__(self, listings):
        self.listings = listings

    def search(self, query, max_price):
        return self.listings

    def close(self):
        pass


class FakeClassifier:
    def __init__(self, verdicts):
        self.verdicts = verdicts
        self.calls = []

    def classify(self, listing):
        self.calls.append(listing.id)
        return self.verdicts[listing.id]


def make_listing(id, price, images=("https://x/1.jpg",)):
    return Listing(source="fake", id=id, title="purse", price=price, url=f"https://x/{id}", image_urls=list(images))


def test_run_once_filters_classifies_and_alerts(tmp_path, monkeypatch):
    monkeypatch.setattr("pursefinder.agent.time.sleep", lambda s: None)
    cfg = Config(queries=["q1", "q2"], data_dir=tmp_path)
    listings = [
        make_listing("city", 300),
        make_listing("padd", 499),
        make_listing("other", 200),
        make_listing("pricey", 650),
        make_listing("noimg", 100, images=()),
        make_listing("unsure", 100),
        make_listing("moto", 100),
    ]
    verdicts = {
        "city": Verdict(bag="balenciaga_city", confidence=90, reasoning="tassels, studs", authenticity_red_flags=[]),
        "padd": Verdict(bag="chloe_paddington", confidence=85, reasoning="padlock", authenticity_red_flags=["shiny hardware"]),
        "other": Verdict(bag="none", confidence=95, reasoning="tote", authenticity_red_flags=[]),
        "unsure": Verdict(bag="chloe_paddington", confidence=30, reasoning="blurry", authenticity_red_flags=[]),
        "moto": Verdict(bag="balenciaga_other_motorcycle", confidence=90, reasoning="First", authenticity_red_flags=[]),
    }
    classifier = FakeClassifier(verdicts)
    store = SeenStore(tmp_path / "seen.db")
    finder = BagFinder(cfg, classifier, [FakeSource(listings)], store, Notifier(tmp_path))

    assert finder.run_once() == 2
    # Same listing from two queries is only checked once; over-budget and photo-less ones never.
    assert sorted(classifier.calls) == ["city", "moto", "other", "padd", "unsure"]
    assert (tmp_path / "matches.jsonl").read_text().count("\n") == 2
    assert "Chloé Paddington" in (tmp_path / "matches.html").read_text()

    # Second round: everything already seen, nothing re-checked.
    classifier.calls.clear()
    assert finder.run_once() == 0
    assert classifier.calls == []


def test_failed_classification_is_retried_next_round(tmp_path, monkeypatch):
    monkeypatch.setattr("pursefinder.agent.time.sleep", lambda s: None)

    class Flaky:
        attempts = 0

        def classify(self, listing):
            Flaky.attempts += 1
            if Flaky.attempts == 1:
                raise RuntimeError("API down")
            return Verdict(bag="balenciaga_city", confidence=80, reasoning="", authenticity_red_flags=[])

    cfg = Config(queries=["q"], data_dir=tmp_path)
    finder = BagFinder(cfg, Flaky(), [FakeSource([make_listing("a", 100)])], SeenStore(tmp_path / "s.db"), Notifier(tmp_path))
    assert finder.run_once() == 0
    assert finder.run_once() == 1


def test_include_other_balenciaga(tmp_path):
    cfg = Config(include_other_balenciaga=True)
    finder = BagFinder(cfg, None, [], None, None)
    assert finder._wanted(Verdict(bag="balenciaga_other_motorcycle", confidence=70, reasoning="", authenticity_red_flags=[]))


def test_example_config_loads():
    cfg = load_config(Path(__file__).parent.parent / "config.example.yaml")
    assert cfg.max_price == 500
    assert "ebay" in cfg.sources
