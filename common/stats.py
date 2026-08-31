"""Per-run counters. Every fetcher logs the same four numbers on the way out."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field


@dataclass
class Stats:
    """Rows fetched / inserted / updated / skipped, plus any errors survived."""

    name: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    skipped: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    def note(self, message: str) -> None:
        self.notes.append(message)

    def __str__(self) -> str:
        return (
            f"{self.name}: fetched={self.fetched} inserted={self.inserted} "
            f"updated={self.updated} skipped={self.skipped} errors={self.errors}"
        )

    def log(self, logger: logging.Logger | None = None) -> None:
        (logger or logging.getLogger(self.name)).info("%s", self)
        for note in self.notes:
            (logger or logging.getLogger(self.name)).info("  note: %s", note)
