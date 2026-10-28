from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import make_offer
from web_agent.store import Store

from allegro_shopping.cache import Cache
from allegro_shopping.client import AllegroClient
from allegro_shopping.config import Rules
from allegro_shopping.errors import FetchFailure, UsageError
from allegro_shopping.session import PageSource

FIXTURES = Path(__file__).parent / "fixtures" / "allegro"
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class Pages(PageSource):
    def __init__(self, markup: dict[str, str]) -> None:
        self.markup = markup
        self.fetched: list[str] = []

    def fetch(self, url: str, ready_selector: str) -> str:
        del ready_selector
        self.fetched.append(url)
        try:
            return self.markup[url]
        except KeyError as e:
            raise FetchFailure(f"no fixture for {url}") from e


def client(tmp_path: Path, rules: Rules, pages: Pages) -> AllegroClient:
    return AllegroClient(pages, Cache(Store(tmp_path / "hoard.db"), rules), rules, now=lambda: NOW)


def test_search_fetches_parses_and_caches(tmp_path: Path, rules: Rules) -> None:
    url = "https://allegro.pl/listing?string=wago+221"
    pages = Pages({url: (FIXTURES / "listing-wago.html").read_text(encoding="utf-8")})
    instance = client(tmp_path, rules, pages)
    offers, last_page, skipped = instance.search("wago 221")
    assert len(offers) == 3
    assert last_page == 3
    assert len(skipped) == 1
    assert pages.fetched == [url]
    assert len(instance.cache.offers()) == 3

    # Second call is a cache hit: no further fetch.
    again, _, _ = instance.search("wago 221")
    assert len(again) == 3
    assert pages.fetched == [url]


def test_search_refresh_forces_a_fetch(tmp_path: Path, rules: Rules) -> None:
    url = "https://allegro.pl/listing?string=wago+221"
    pages = Pages({url: (FIXTURES / "listing-wago.html").read_text(encoding="utf-8")})
    instance = client(tmp_path, rules, pages)
    instance.search("wago 221")
    instance.search("wago 221", refresh=True)
    assert pages.fetched == [url, url]


def test_offer_detail_parses_and_records_product(tmp_path: Path, rules: Rules) -> None:
    product_id = "b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3"
    url = f"https://allegro.pl/produkt/wago-221-413-{product_id}?offerId=1000001"
    offer = replace(make_offer("1000001", price=4500), url=url)
    markup = (FIXTURES / "offer-wago-221.html").read_text(encoding="utf-8")
    pages = Pages({url: markup})
    instance = client(tmp_path, rules, pages)
    instance.cache.add_offer(offer)
    detail = instance.offer_detail("1000001", refresh=True)
    assert detail.price == 4599
    assert detail.deep is True
    assert detail.product_id == product_id
    # The offer page does not create the catalog row; only the product page does.
    assert instance.cache.product(product_id) is None

    product_url = f"https://allegro.pl/produkt/{product_id}"
    pages.markup[product_url] = (FIXTURES / "product-wago-221.html").read_text(encoding="utf-8")
    product = instance.product_detail(product_id)
    assert product.ean == "4044918645118"
    assert product.specs["Napięcie znamionowe"] == "450 V"
    assert instance.cache.product(product_id) is not None
    # Second call is served from cache.
    count = len(pages.fetched)
    instance.product_detail(product_id)
    assert len(pages.fetched) == count


def test_offer_detail_without_cache_uses_canonical_url(tmp_path: Path, rules: Rules) -> None:
    pages = Pages({})
    instance = client(tmp_path, rules, pages)
    with pytest.raises(FetchFailure):
        instance.offer_detail("1000001")
    assert pages.fetched == ["https://allegro.pl/oferta/1000001"]


def test_seller_is_parsed_and_cached(tmp_path: Path, rules: Rules) -> None:
    markup = (
        "<html><body><span>4,93 na 5</span><span>1 234 ocen</span> Super Sprzedawca</body></html>"
    )
    pages = Pages({"https://allegro.pl/uzytkownik/kabelmax": markup})
    instance = client(tmp_path, rules, pages)
    seller = instance.seller("kabelmax")
    assert seller is not None
    assert seller.rating == pytest.approx(4.93)
    assert seller.ratings_count == 1234
    assert seller.super_seller is True
    assert instance.cache.seller("kabelmax") is not None


def test_seller_failure_is_none_not_an_exception(tmp_path: Path, rules: Rules) -> None:
    instance = client(tmp_path, rules, Pages({}))
    assert instance.seller("ghost") is None


def test_capture_routes_by_page_kind(tmp_path: Path, rules: Rules) -> None:
    listing = "https://allegro.pl/listing?string=wago"
    pages = Pages({listing: "markup"})
    instance = client(tmp_path, rules, pages)
    assert instance.capture(listing) == "markup"
    with pytest.raises(UsageError):
        instance.capture("https://allegro.pl/koszyk")


def test_deep_offer_without_specs_is_not_refetched(tmp_path: Path, rules: Rules) -> None:
    offer = replace(make_offer("1000001", price=4500, specs={}), deep=True)
    pages = Pages({})
    instance = client(tmp_path, rules, pages)
    instance.cache.add_offer(offer)
    assert instance.offer_detail("1000001").price == 4500
    assert pages.fetched == []


def test_deep_dive_keeps_card_delivery_and_sponsorship(tmp_path: Path, rules: Rules) -> None:
    card = replace(
        make_offer("1000001", price=4500, delivery_grosze=1049),
        sponsored=True,
        thumbnail="https://img/x.jpg",
        seller_positive_percent=99.5,
        seller_super_seller=True,
    )
    pages = Pages({card.url: (FIXTURES / "offer-wago-221.html").read_text(encoding="utf-8")})
    instance = client(tmp_path, rules, pages)
    instance.cache.add_offer(card)
    deep = instance.offer_detail("1000001", refresh=True)
    assert deep.delivery_grosze == 1049
    assert deep.sponsored is True
    assert deep.thumbnail == "https://img/x.jpg"
    assert deep.price == 4599
    assert deep.seller_positive_percent == 99.5
    assert deep.seller_super_seller is True
