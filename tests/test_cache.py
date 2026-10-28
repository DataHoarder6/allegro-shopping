from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from conftest import make_offer
from web_agent.store import Store

from allegro_shopping.cache import Cache
from allegro_shopping.config import Rules
from allegro_shopping.errors import StaleDataError
from allegro_shopping.models import Product


@pytest.fixture
def cache(tmp_path: Path, rules: Rules) -> Cache:
    return Cache(Store(tmp_path / "hoard.db"), rules)


def test_round_trip_offer(cache: Cache) -> None:
    offer = make_offer()
    assert cache.add_offer(offer) == 1
    loaded = cache.offer("18330930177")
    assert loaded is not None
    assert loaded.price == offer.price
    assert loaded.seller_login == offer.seller_login
    assert loaded.specs == offer.specs
    assert loaded.deep is True


def test_append_only_history(cache: Cache) -> None:
    cache.add_offer(make_offer(price=4500))
    cache.add_offer(make_offer(price=4300, fetched_at=datetime(2026, 10, 28, 13, 0, tzinfo=UTC)))
    assert cache.offer("18330930177").price == 4300  # type: ignore[union-attr]
    history = cache.store.history("allegro", "offer:18330930177")
    assert len(history) == 2


def test_offers_filter_by_product(cache: Cache) -> None:
    cache.add_offer(make_offer("18330930177"))
    cache.add_offer(make_offer("18330930178"))
    assert len(cache.offers()) == 2


def test_product_round_trip(cache: Cache) -> None:
    product = Product(
        product_id="b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3",
        title="WAGO 221-413",
        url="https://allegro.pl/produkt/wago-b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3",
        specs={"Model": "221-413"},
    )
    cache.add_product(product)
    loaded = cache.product(product.product_id)
    assert loaded is not None
    assert loaded.specs == {"Model": "221-413"}


def test_freshness_uses_per_kind_ttl(cache: Cache) -> None:
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    moment = now - timedelta(hours=3)
    assert cache.is_fresh("search", moment, now) is True
    assert cache.is_fresh("offer", moment, now) is False


def test_require_fresh_raises_with_age_and_ttl(cache: Cache) -> None:
    now = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)
    stale = now - timedelta(hours=5)
    with pytest.raises(StaleDataError, match="TTL is 2h"):
        cache.require_fresh("offer", stale, what="offer 18330930177", now=now)


def test_search_page_ids_round_trip(cache: Cache) -> None:
    cache.add_search_page(
        query="wago 221",
        order="p",
        page=1,
        url="https://allegro.pl/listing?string=wago+221&order=p",
        offer_ids=["18330930177", "18330930178"],
        last_page=3,
    )
    ids, fetched_at = cache.search_page("wago 221", "p", 1)
    assert ids == ["18330930177", "18330930178"]
    assert fetched_at.tzinfo is not None


def test_search_page_miss_returns_min_datetime(cache: Cache) -> None:
    ids, fetched_at = cache.search_page("nothing", None, 1)
    assert ids == []
    assert fetched_at.year == 1
