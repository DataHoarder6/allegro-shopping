"""Exact money. Grosze integers only; floats never touch a price.

Allegro quotes PLN with a comma decimal separator, space (or NBSP) thousands
separators, and suffixes ("/szt.", "zł/szt.", "od"). Parsing is strict: text
that does not describe exactly one amount raises MoneyError instead of being
coerced, because a silently misread price is a wrong purchase.
"""

from __future__ import annotations

import re
from typing import NewType

from .errors import MoneyError

Grosze = NewType("Grosze", int)

_NBSP = "\u00a0\u202f"
_AMOUNT_RE = re.compile(
    r"(?<![\d,.])(?P<whole>\d{1,3}(?:[\s\u00a0\u202f]\d{3})+|\d+)"
    r"(?:[,.](?P<frac>\d{1,2}))?\s*(?P<cur>zł|PLN)?",
)
_SPACE_RE = re.compile(r"[\s\u00a0\u202f]+")


def normalize_amount_text(text: str) -> str:
    """Collapse whitespace, drop currency suffixes and per-unit qualifiers."""
    cleaned = _SPACE_RE.sub(" ", text).strip()
    cleaned = cleaned.removeprefix("od ").strip()
    return cleaned


def parse_grosze(text: str) -> Grosze:
    """Parse a single PLN amount. Rejects text holding more than one amount."""
    cleaned = normalize_amount_text(text)
    matches = list(_AMOUNT_RE.finditer(cleaned))
    if not matches:
        raise MoneyError(f"no amount in {text!r}")
    if len(matches) > 1:
        raise MoneyError(f"ambiguous amount in {text!r}: {len(matches)} candidates")
    m = matches[0]
    remainder = cleaned[m.end() :]
    if re.search(r"\d", remainder):
        raise MoneyError(f"trailing digits after amount in {text!r}")
    whole = re.sub(r"\D", "", m.group("whole"))
    frac = (m.group("frac") or "0").ljust(2, "0")
    if m.group("cur") is None and m.group("frac") is None and len(whole) > 6:
        raise MoneyError(f"implausible bare integer amount in {text!r}")
    return Grosze(int(whole) * 100 + int(frac))


def format_grosze(amount: Grosze) -> str:
    """Render as Allegro does: '1 234,56 zł'."""
    sign = "-" if amount < 0 else ""
    value = abs(int(amount))
    whole, frac = divmod(value, 100)
    return f"{sign}{whole:,}".replace(",", " ") + f",{frac:02d} zł"


def percent_off(price: Grosze, reference: Grosze) -> int | None:
    """Whole-percent discount of `price` against `reference`, or None."""
    if reference <= 0 or price > reference:
        return None
    return round((reference - price) * 100 / reference)
