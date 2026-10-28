from __future__ import annotations

from datetime import UTC, datetime

import pytest

from allegro_shopping.config import Item, Rules, load_rules
from allegro_shopping.models import Offer, Seller
from allegro_shopping.money import Grosze
from allegro_shopping.rules import default_rules_path


@pytest.fixture(scope="session")
def rules() -> Rules:
    return load_rules(default_rules_path())


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


def make_offer(
    offer_id: str = "18330930177",
    *,
    price: int = 4500,
    seller: str = "elektro-hurt",
    condition: str | None = "Nowy",
    in_stock: bool | None = True,
    rating_avg: float | None = 4.8,
    rating_count: int | None = 112,
    specs: dict[str, str] | None = None,
    delivery_grosze: int | None = None,
    smart: bool | None = None,
    fetched_at: datetime | None = None,
    deep: bool = True,
) -> Offer:
    return Offer(
        offer_id=offer_id,
        title=f"WAGO 221 offer {offer_id}",
        url=f"https://allegro.pl/oferta/wago-221-{offer_id}",
        price=Grosze(price),
        seller_login=seller,
        condition=condition,
        in_stock=in_stock,
        rating_avg=rating_avg,
        rating_count=rating_count,
        specs={"Model": "221-413"} if specs is None else specs,
        delivery_grosze=None if delivery_grosze is None else Grosze(delivery_grosze),
        smart=smart,
        fetched_at=fetched_at or datetime(2026, 10, 28, 12, 0, tzinfo=UTC),
        deep=deep,
    )


def make_seller(
    login: str = "elektro-hurt", *, rating: float | None = 4.9, count: int | None = 812
) -> Seller:
    return Seller(login=login, rating=rating, ratings_count=count)


def make_item(
    *,
    label: str = "wago",
    quantity: int = 1,
    max_price_grosze: int = 10000,
    required_specs: dict[str, str] | None = None,
    allow_used: bool = False,
    min_rating: float | None = None,
) -> Item:
    return Item(
        label=label,
        query="wago 221-413",
        quantity=quantity,
        max_price_grosze=Grosze(max_price_grosze),
        allow_used=allow_used,
        required_specs=required_specs or {},
        min_rating=min_rating,
    )
