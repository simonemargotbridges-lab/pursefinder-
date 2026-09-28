from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from .models import Listing


class SeenStore:
    """Remembers every listing already checked so nothing is classified (or alerted) twice."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(
            """CREATE TABLE IF NOT EXISTS seen (
                key TEXT PRIMARY KEY,
                checked_at REAL,
                title TEXT,
                price REAL,
                url TEXT,
                verdict TEXT
            )"""
        )
        self.db.commit()

    def has(self, key: str) -> bool:
        return self.db.execute("SELECT 1 FROM seen WHERE key = ?", (key,)).fetchone() is not None

    def add(self, listing: Listing, verdict: dict | None) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO seen VALUES (?, ?, ?, ?, ?, ?)",
            (
                listing.key,
                time.time(),
                listing.title,
                listing.price,
                listing.url,
                json.dumps(verdict) if verdict is not None else None,
            ),
        )
        self.db.commit()
