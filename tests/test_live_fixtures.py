"""Regression on genuinely captured Allegro pages (2026-10-28).

These are the only tests that prove the parsers against real markup. The
synthetic fixtures stay for edge cases the live corpus does not contain.
"""

from __future__ import annotations

from pathlib import Path

from allegro_shopping.parse import parse_listing, parse_offer_page, parse_product_page

FIXTURES = Path(__file__).parent / "fixtures" / "allegro"
LISTING = (FIXTURES / "live-listing.html").read_text(encoding="utf-8")
OFFER_URL = "https://allegro.pl/oferta/18657388077"
OFFER = (FIXTURES / "live-offer-18657388077.html").read_text(encoding="utf-8")
PRODUCT_URL = "https://allegro.pl/produkt/6041c31c-a5bc-40d8-b46b-f5fe30f1fd99"
PRODUCT = (FIXTURES / "live-product-6041c31c.html").read_text(encoding="utf-8")


def test_live_listing_parses_the_whole_page() -> None:
    page = parse_listing(LISTING)
    assert len(page.offers) >= 60
    assert page.last_page == 9
    assert len(page.skipped) <= 3

    first = page.offers[0]
    assert first.offer_id.isdigit()
    assert first.price > 0
    assert first.seller_login
    assert first.url.startswith("https://allegro.pl/")
    assert first.product_id is not None
    assert first.parser_rev == 2


def test_live_listing_carries_delivery_stock_and_ratings() -> None:
    page = parse_listing(LISTING)
    assert any(o.delivery_grosze is not None for o in page.offers)
    assert any(o.rating_avg is not None for o in page.offers)
    assert any(o.in_stock is True for o in page.offers)
    assert any(o.sponsored for o in page.offers)
    assert any(not o.sponsored for o in page.offers)


def test_live_listing_rejects_foreign_domains_with_a_reason() -> None:
    page = parse_listing(LISTING)
    reasons = " ".join(skip.reason for skip in page.skipped)
    assert "allegrolokalnie.pl" in reasons


def test_live_offer_page_parses_price_specs_and_condition() -> None:
    detail = parse_offer_page(OFFER, OFFER_URL)
    offer = detail.offer
    assert offer.price == 7600
    assert offer.seller_login == "spacja_net_pl"
    assert offer.ean == "4055143644907"
    assert offer.rating_avg == 4.98
    assert offer.rating_count == 939
    assert offer.in_stock is True
    assert offer.condition_norm == "new"
    assert offer.deep is True
    assert detail.specs["Prąd znamionowy"] == "32 A"
    assert detail.specs["Liczba zacisków"] == "3"


def test_live_product_page_is_the_spec_table_of_record() -> None:
    product = parse_product_page(PRODUCT, PRODUCT_URL)
    assert product.product_id == "6041c31c-a5bc-40d8-b46b-f5fe30f1fd99"
    assert product.ean == "4055143644907"
    assert product.rating_count == 939
    assert len(product.specs) >= 30
    assert product.specs["Kolor dźwigni"]
