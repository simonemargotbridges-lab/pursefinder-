from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

DEFAULT_QUERIES = [
    # Brand-level searches catch listings with vague titles ("Chloe purse",
    # "Balenciaga leather bag") -- the photos decide whether it's the right bag.
    "balenciaga bag",
    "balenciaga purse",
    "chloe bag",
    "chloe purse",
    "chloe leather bag",
    # Brand-less searches catch listings that don't name the brand at all.
    "padlock bag",
    "motorcycle bag leather",
    "vintage leather bag studs",
]


@dataclass
class Config:
    max_price: float = 500.0
    min_price: float = 0.0
    queries: list[str] = field(default_factory=lambda: list(DEFAULT_QUERIES))
    sources: dict[str, dict] = field(default_factory=dict)
    interval_minutes: float = 10.0
    min_confidence: int = 60
    include_other_balenciaga: bool = False
    images_per_listing: int = 3
    max_classifications_per_cycle: int = 150
    classify_workers: int = 4
    model: str = "claude-opus-5"
    effort: str = "low"
    data_dir: Path = Path("data")
    ntfy_topic: str | None = None
    discord_webhook_url: str | None = None


def load_config(path: str | os.PathLike | None) -> Config:
    raw: dict = {}
    if path and Path(path).exists():
        raw = yaml.safe_load(Path(path).read_text()) or {}

    cfg = Config()
    for key, value in raw.items():
        if not hasattr(cfg, key):
            raise ValueError(f"Unknown config option: {key!r}")
        setattr(cfg, key, value)
    cfg.data_dir = Path(cfg.data_dir)

    if not cfg.sources:
        cfg.sources = {name: {} for name in ("ebay", "poshmark", "depop", "vinted", "mercari")}

    # Secrets come from the environment so config.yaml can be shared safely.
    cfg.ntfy_topic = os.environ.get("NTFY_TOPIC") or cfg.ntfy_topic
    cfg.discord_webhook_url = os.environ.get("DISCORD_WEBHOOK_URL") or cfg.discord_webhook_url
    return cfg
