"""Which FRED series carries the actual for each calendar event, and how to read it.

A forecast from ForexFactory and an observation from FRED have to end up in the
same units before the surprise calculation means anything. Three things differ:

* **Shape.** ForexFactory quotes CPI as a month-on-month percentage; FRED
  publishes the index level. The change has to be computed.
* **Scale.** ForexFactory quotes non-farm payrolls as "165K", which parsing
  turns into 165000. FRED's PAYEMS is in thousands, so its 165.0 needs x1000.
* **Timing.** For a monthly release the right observation is the newest one
  dated before the release. For a Fed decision it is the value *on* the day -
  the point of the event is that the rate changes that afternoon.

Anything not listed here is skipped by fred_actuals with a log line, which is
the honest outcome: ISM's PMIs, for example, were withdrawn from FRED over
licensing and there is no free replacement series.
"""

from __future__ import annotations

from dataclasses import dataclass

# How to turn raw observations into the number the feed quotes.
TRANSFORMS = ("level", "diff", "pct_change_mom", "pct_change_yoy", "level_at_or_after")


@dataclass(frozen=True)
class SeriesSpec:
    """One event title's route to an actual."""

    series_id: str
    transform: str = "level"
    scale: float = 1.0
    note: str = ""

    def __post_init__(self) -> None:
        if self.transform not in TRANSFORMS:
            raise ValueError(f"unknown transform {self.transform!r} for {self.series_id}")


# Keyed by the canonical (ForexFactory) title, matched case-insensitively.
SERIES_MAP: dict[str, SeriesSpec] = {
    # --- Inflation -------------------------------------------------------
    "cpi m/m": SeriesSpec("CPIAUCSL", "pct_change_mom", note="CPI, all items, SA"),
    "cpi y/y": SeriesSpec("CPIAUCNS", "pct_change_yoy", note="NSA, as the feed quotes it"),
    "core cpi m/m": SeriesSpec("CPILFESL", "pct_change_mom", note="less food and energy, SA"),
    "core pce price index m/m": SeriesSpec("PCEPILFE", "pct_change_mom"),
    "ppi m/m": SeriesSpec("PPIFIS", "pct_change_mom", note="final demand, SA"),

    # --- Labour ----------------------------------------------------------
    # PAYEMS is a level in thousands; the release quotes the monthly change.
    "non-farm employment change": SeriesSpec("PAYEMS", "diff", scale=1_000.0),
    "unemployment rate": SeriesSpec("UNRATE", "level"),
    "average hourly earnings m/m": SeriesSpec("CES0500000003", "pct_change_mom"),
    "unemployment claims": SeriesSpec("ICSA", "level", note="initial claims, SA"),

    # --- Demand ----------------------------------------------------------
    "retail sales m/m": SeriesSpec("RSAFS", "pct_change_mom"),
    "core retail sales m/m": SeriesSpec("RSFSXMV", "pct_change_mom", note="ex motor vehicles"),

    # --- Rates -----------------------------------------------------------
    # The decision itself: read the target range's upper bound on the day.
    "fomc statement": SeriesSpec("DFEDTARU", "level_at_or_after", note="target range, upper"),
    "federal funds rate": SeriesSpec("DFEDTARU", "level_at_or_after"),

    # --- Housing ---------------------------------------------------------
    # Published in thousands of units; the feed quotes e.g. "1.42M".
    "building permits": SeriesSpec("PERMIT", "level", scale=1_000.0),
    "housing starts": SeriesSpec("HOUST", "level", scale=1_000.0),
    "new home sales": SeriesSpec("HSN1F", "level", scale=1_000.0),
    "existing home sales": SeriesSpec("EXHOSLUSM495S", "level"),
}

# Titles deliberately left unmapped, with the reason, so the log can say why
# rather than just "unknown".
UNMAPPED_REASONS: dict[str, str] = {
    "ism manufacturing pmi": "ISM withdrew its PMIs from FRED; no free replacement",
    "ism services pmi": "ISM withdrew its PMIs from FRED; no free replacement",
    "fomc press conference": "no numeric release",
    "fomc economic projections": "projections are a table, not a single figure",
    "fomc meeting minutes": "no numeric release",
    "fed chair testifies": "no numeric release",
    "fed chair speaks": "no numeric release",
    "jackson hole symposium": "no numeric release",
    "fomc member speaks": "no numeric release",
}


def spec_for(title: str) -> SeriesSpec | None:
    """The series spec for a title, or None if there is not one."""
    return SERIES_MAP.get(title.strip().lower())


def reason_unmapped(title: str) -> str:
    """Why a title has no series. Falls back to a generic message."""
    return UNMAPPED_REASONS.get(
        title.strip().lower(), "no FRED series mapped for this title"
    )
