"""Pure parsing of the forecast/previous/actual strings a calendar feed emits.

ForexFactory publishes these as display strings: ``"0.3%"``, ``"165K"``,
``"-1.2%"``, ``"1.25M"``, ``"<0.1%"``, ``""``. They are turned into plain floats
so the surprise calculation and the UI both have numbers to work with.

Units are expanded rather than kept as a suffix: ``"165K"`` becomes ``165000.0``.
The surprise formula is a ratio, so any consistent scale cancels out - but only
if both sides use the same one, and the FRED actuals arrive as full numbers.
Percent signs are dropped without dividing by 100: ``"0.3%"`` is ``0.3``, and the
matching FRED figure is also 0.3, so they compare directly.
"""

from __future__ import annotations

import re

# Suffix -> multiplier. Case-insensitive; matched after the numeric part.
SUFFIX_MULTIPLIERS: dict[str, float] = {
    "K": 1_000.0,
    "M": 1_000_000.0,
    "B": 1_000_000_000.0,
    "T": 1_000_000_000_000.0,
}

# Placeholders the feed uses for "no value". Compared lowercased.
BLANKS = {"", "-", "--", "n/a", "na", "none", "null", "tentative", "tbd"}

_NUMERIC = re.compile(
    r"""^
    (?P<sign>[+-])?
    (?P<number>\d{1,3}(?:,\d{3})*(?:\.\d+)?|\d*\.?\d+)
    \s*
    (?P<suffix>[KMBT])?
    \s*
    %?
    $""",
    re.VERBOSE | re.IGNORECASE,
)


def parse_numeric(value: str | float | int | None) -> float | None:
    """Parse a feed value to a float, or None when there is no usable number.

    Returns None rather than raising: one unparseable cell must never stop a
    batch, and "no forecast published" is a normal, meaningful state.
    """
    if value is None:
        return None
    if isinstance(value, bool):  # bool is an int subclass; never a market figure
        return None
    if isinstance(value, (int, float)):
        return float(value)

    text = str(value).strip()
    if text.lower() in BLANKS:
        return None

    # "<0.1%" / ">2.5%" - the feed's way of saying "just under/over". The bound
    # is the only number available, so use it.
    text = text.lstrip("<>~≈").strip()
    # Some rows carry a trailing currency or unit marker.
    text = text.replace("$", "").strip()

    match = _NUMERIC.match(text)
    if not match:
        return None

    number = float(match.group("number").replace(",", ""))
    if match.group("suffix"):
        number *= SUFFIX_MULTIPLIERS[match.group("suffix").upper()]
    if match.group("sign") == "-":
        number = -number
    return number


def parse_impact(value: str | None) -> str | None:
    """Normalise the feed's impact flag to High / Medium / Low, else None."""
    if not value:
        return None
    text = str(value).strip().lower()
    for level in ("high", "medium", "low"):
        if text.startswith(level):
            return level.capitalize()
    if text.startswith("holiday"):
        return "Holiday"
    return None
