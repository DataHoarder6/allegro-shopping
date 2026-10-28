"""Domain records. Frozen, JSON-round-trippable, no behaviour beyond validation.

Prices are `Grosze`. Missing facts are `None`, never a made-up default: the
scorer treats `None` as unknown, and unknown is visible in the output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any, Self

from .money import Grosze

_CONDITION_ALIASES = {
    "nowy": "new",
    "nowe": "new",
    "nowa": "new",
    "new": "new",
    "używany": "used",
    "używane": "used",
    "uzywana": "used",
    "used": "used",
    "powystawowy": "open-box",
    "po zwrocie": "returned",
    "uszkodzony": "damaged",
}


def normalize_condition(raw: str | None) -> str | None:
    """Allegro states condition in Polish prose; ranking needs a closed set."""
    if raw is None:
        return None
    return _CONDITION_ALIASES.get(raw.strip().lower())


def utc_now() -> datetime:
    return datetime.now(UTC)


def iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    return moment.astimezone(UTC).isoformat(timespec="seconds")


def parse_iso(text: str) -> datetime:
    moment = datetime.fromisoformat(text)
    if moment.tzinfo is None:
        raise ValueError(f"naive timestamp: {text!r}")
    return moment


@dataclass(frozen=True)
class Seller:
    login: str
    rating: float | None = None
    ratings_count: int | None = None
    # Allegro's own seller metric, present on every listing card: the share of
    # positive buyer feedback. Cheaper and more reliable than the /oceny page.
    positive_feedback_percent: float | None = None
    super_seller: bool = False
    smart: bool = False
    url: str | None = None


@dataclass(frozen=True)
class Offer:
    """One purchasable offer, as seen on a listing card or an offer page."""

    offer_id: str
    title: str
    url: str
    price: Grosze
    seller_login: str
    product_id: str | None = None
    ean: str | None = None
    price_before_30d: Grosze | None = None
    unit_price: Grosze | None = None
    delivery_grosze: Grosze | None = None
    delivery_text: str | None = None
    smart: bool | None = None
    sponsored: bool = False
    in_stock: bool | None = None
    condition: str | None = None
    rating_avg: float | None = None
    rating_count: int | None = None
    seller_super_seller: bool | None = None
    seller_positive_percent: float | None = None
    thumbnail: str | None = None
    description: str | None = None
    specs: dict[str, str] = field(default_factory=dict)
    deep: bool = False
    fetched_at: datetime = field(default_factory=utc_now)
    parser_rev: int = 1

    @property
    def condition_norm(self) -> str | None:
        return normalize_condition(self.condition)

    def __post_init__(self) -> None:
        if self.price < 0:
            raise ValueError("price must be non-negative")
        if not self.offer_id.isdigit():
            raise ValueError(f"offer_id must be numeric, got {self.offer_id!r}")

    def to_record(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["id"] = f"offer:{self.offer_id}"
        raw["price"] = int(self.price)
        raw["price_before_30d"] = (
            None if self.price_before_30d is None else int(self.price_before_30d)
        )
        raw["unit_price"] = None if self.unit_price is None else int(self.unit_price)
        raw["delivery_grosze"] = None if self.delivery_grosze is None else int(self.delivery_grosze)
        raw["fetched_at"] = iso(self.fetched_at)
        return raw

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> Self:
        data = {k: v for k, v in raw.items() if k != "id"}
        data["price"] = Grosze(int(data["price"]))
        for key in ("price_before_30d", "unit_price", "delivery_grosze"):
            if data.get(key) is not None:
                data[key] = Grosze(int(data[key]))
        data["fetched_at"] = parse_iso(data["fetched_at"])
        return cls(**data)


@dataclass(frozen=True)
class Product:
    """A catalog product: the thing several offers sell."""

    product_id: str
    title: str
    url: str
    ean: str | None = None
    brand: str | None = None
    specs: dict[str, str] = field(default_factory=dict)
    rating_avg: float | None = None
    rating_count: int | None = None
    description: str | None = None
    fetched_at: datetime = field(default_factory=utc_now)
    parser_rev: int = 1

    def to_record(self) -> dict[str, Any]:
        raw = asdict(self)
        raw["id"] = f"product:{self.product_id}"
        raw["fetched_at"] = iso(self.fetched_at)
        return raw

    @classmethod
    def from_record(cls, raw: dict[str, Any]) -> Self:
        data = {k: v for k, v in raw.items() if k != "id"}
        data["fetched_at"] = parse_iso(data["fetched_at"])
        return cls(**data)


@dataclass(frozen=True)
class SearchHit:
    """One card on a listing page. Cheap, incomplete; the offer page is the truth."""

    offer: Offer
    position: int
