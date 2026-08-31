"""Pure diff of an incoming calendar feed against what is already stored.

This is the piece that decides whether the trader gets a message. It is kept
free of I/O so it can be tested against fixtures: given a list of incoming rows
and the rows currently in the database, it returns what is new, what changed,
and what to leave alone.

Two fields are watched, per the brief: the release time and the forecast. A
changed release time moves a blackout window; a changed forecast moves the
surprise the market is positioned for. Everything else (previous, impact) is
written through silently.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable, Sequence

# Fields whose change is worth waking the trader for.
WATCHED_FIELDS: tuple[str, ...] = ("ts_utc", "forecast")

# Forecasts are floats parsed from display strings; compare with a tolerance so
# 0.30000000000000004 never counts as a revision.
FLOAT_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Change:
    """One watched field that moved."""

    field: str
    old: Any
    new: Any

    def describe(self) -> str:
        return f"{self.field}: {_render(self.old)} -> {_render(self.new)}"


@dataclass
class DiffResult:
    """The outcome of one sync: what to insert, what to update, what to skip."""

    new: list[dict] = field(default_factory=list)
    changed: list[tuple[dict, list[Change]]] = field(default_factory=list)
    unchanged: list[dict] = field(default_factory=list)

    @property
    def counts(self) -> tuple[int, int, int]:
        return len(self.new), len(self.changed), len(self.unchanged)


def _render(value: Any) -> str:
    if value is None:
        return "none"
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def values_differ(old: Any, new: Any) -> bool:
    """True when a watched field moved.

    None on either side is significant: a skeleton row whose forecast was empty
    and now has one has genuinely changed, and that is worth reporting - it is
    the moment the consensus for that release becomes known.
    """
    if old is None and new is None:
        return False
    if old is None or new is None:
        return True
    if isinstance(old, datetime) and isinstance(new, datetime):
        return old != new
    if isinstance(old, (int, float)) and isinstance(new, (int, float)):
        return not math.isclose(float(old), float(new), rel_tol=0.0, abs_tol=FLOAT_TOLERANCE)
    return old != new


def diff_events(
    incoming: Sequence[dict],
    existing: dict[str, dict],
    *,
    watched: Iterable[str] = WATCHED_FIELDS,
) -> DiffResult:
    """Split incoming rows into new / changed / unchanged.

    ``incoming`` rows carry at least ``id`` and the watched fields, with
    datetimes already timezone-aware. ``existing`` is keyed by id, as
    db.repo.fetch_events_by_ids returns it. Later duplicates of an id inside one
    feed are dropped: ForexFactory occasionally lists the same release twice.
    """
    watched = tuple(watched)
    result = DiffResult()
    seen: set[str] = set()

    for row in incoming:
        event_id = row.get("id")
        if not event_id or event_id in seen:
            continue
        seen.add(event_id)

        stored = existing.get(event_id)
        if stored is None:
            result.new.append(row)
            continue

        changes = [
            Change(f, stored.get(f), row.get(f))
            for f in watched
            if values_differ(stored.get(f), row.get(f))
        ]
        if changes:
            result.changed.append((row, changes))
        else:
            result.unchanged.append(row)

    return result
