from __future__ import annotations

import argparse
import logging

from .agent import BagFinder, build_sources
from .config import load_config
from .notify import Notifier
from .store import SeenStore
from .vision import BagClassifier


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="pursefinder",
        description="Watch secondhand marketplaces for Balenciaga City and Chloé Paddington bags, judged by their photos.",
    )
    parser.add_argument("-c", "--config", default="config.yaml", help="path to config file (default: config.yaml)")
    parser.add_argument("--once", action="store_true", help="check once and exit instead of watching forever")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in ("httpx", "httpx2", "urllib3", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    cfg = load_config(args.config)
    cfg.data_dir.mkdir(parents=True, exist_ok=True)
    finder = BagFinder(
        cfg,
        classifier=BagClassifier(cfg.model, cfg.effort, cfg.images_per_listing),
        sources=build_sources(cfg),
        store=SeenStore(cfg.data_dir / "seen.sqlite3"),
        notifier=Notifier(cfg.data_dir, cfg.ntfy_topic, cfg.discord_webhook_url),
    )
    try:
        finder.run_once() if args.once else finder.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for source in finder.sources:
            source.close()


if __name__ == "__main__":
    main()
