from __future__ import annotations

import logging
import random
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Protocol

from .config import Config
from .models import Listing
from .notify import Notifier
from .sources import Source, build_source
from .store import SeenStore
from .vision import Verdict

log = logging.getLogger(__name__)


class Classifier(Protocol):
    def classify(self, listing: Listing) -> Verdict | None: ...


class BagFinder:
    def __init__(self, cfg: Config, classifier: Classifier, sources: list[Source], store: SeenStore, notifier: Notifier):
        self.cfg = cfg
        self.classifier = classifier
        self.sources = sources
        self.store = store
        self.notifier = notifier

    def _wanted(self, verdict: Verdict) -> bool:
        if verdict.confidence < self.cfg.min_confidence:
            return False
        if verdict.bag in ("balenciaga_city", "chloe_paddington"):
            return True
        return verdict.bag == "balenciaga_other_motorcycle" and self.cfg.include_other_balenciaga

    def collect_new(self) -> list[Listing]:
        """Newest listings from every source and query that we haven't looked at yet and fit the budget."""
        fresh: dict[str, Listing] = {}
        for source in self.sources:
            for query in self.cfg.queries:
                try:
                    results = source.search(query, self.cfg.max_price)
                except Exception as exc:  # noqa: BLE001 - one broken site shouldn't stop the rest
                    log.warning("%s search for %r failed: %s", source.name, query, exc)
                    continue
                for listing in results:
                    if listing.key in fresh or self.store.has(listing.key):
                        continue
                    if listing.price is None or not (self.cfg.min_price <= listing.price <= self.cfg.max_price):
                        continue
                    if not listing.image_urls:
                        continue
                    fresh[listing.key] = listing
                time.sleep(random.uniform(1.0, 3.0))  # be polite to each site
        return list(fresh.values())

    def _check(self, listing: Listing) -> tuple[Listing, Verdict | None, bool]:
        try:
            return listing, self.classifier.classify(listing), True
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not classify %s: %s", listing.url, exc)
            return listing, None, False

    def run_once(self) -> int:
        listings = self.collect_new()
        if len(listings) > self.cfg.max_classifications_per_cycle:
            log.info("Found %d new listings; checking the first %d this round", len(listings), self.cfg.max_classifications_per_cycle)
            listings = listings[: self.cfg.max_classifications_per_cycle]
        log.info("Checking photos of %d new listings", len(listings))

        matches = 0
        with ThreadPoolExecutor(max_workers=self.cfg.classify_workers) as pool:
            for listing, verdict, ok in pool.map(self._check, listings):
                if not ok:
                    continue  # leave it unseen so the next round retries it
                self.store.add(listing, verdict.model_dump() if verdict else None)
                if verdict and self._wanted(verdict):
                    matches += 1
                    self.notifier.send(listing, verdict)
        log.info("Round done: %d match(es)", matches)
        return matches

    def run_forever(self) -> None:
        while True:
            started = time.time()
            try:
                self.run_once()
            except Exception:  # noqa: BLE001
                log.exception("Round failed; will try again next round")
            wait = self.cfg.interval_minutes * 60 * random.uniform(0.85, 1.15) - (time.time() - started)
            if wait > 0:
                log.info("Next check in %.0f min", wait / 60)
                time.sleep(wait)


def build_sources(cfg: Config) -> list[Source]:
    sources = []
    for name, options in cfg.sources.items():
        if options and options.get("enabled") is False:
            continue
        try:
            sources.append(build_source(name, options))
        except Exception as exc:  # noqa: BLE001
            log.warning("Skipping %s: %s", name, exc)
    if not sources:
        raise SystemExit("No marketplaces could be set up -- see the warnings above.")
    log.info("Searching: %s", ", ".join(s.name for s in sources))
    return sources
