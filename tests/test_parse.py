from __future__ import annotations

import json
from pathlib import Path

import pytest

from allegro_shopping.errors import ParseError
from allegro_shopping.parse import (
    PARSER_REV,
    is_gone_page,
    parse_listing,
    parse_offer_page,
    parse_specs,
)

FIXTURES = Path(__file__).parent / "fixtures" / "allegro"


def read(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_parse_listing_reads_cards_and_pagination() -> None:
    page = parse_listing(read("listing-wago.html"))
    assert len(page.offers) == 3
    assert page.last_page == 3
    assert len(page.skipped) == 1
    assert "seller" in page.skipped[0].reason

    first = page.offers[0]
    assert first.offer_id == "18330930177"
    assert first.price == 4500
    assert first.seller_login == "elektro-hurt"
    assert first.title.startswith("WAGO 221-413")
    assert first.product_id == "b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3"
    assert first.rating_avg == pytest.approx(4.67)
    assert first.rating_count == 9
    assert first.sponsored is False
    assert first.parser_rev == PARSER_REV
    assert first.deep is False


def test_parse_listing_marks_promoted_cards() -> None:
    page = parse_listing(read("listing-wago.html"))
    promoted = [o for o in page.offers if o.sponsored]
    assert [o.offer_id for o in promoted] == ["18529923195"]


def test_parse_listing_never_returns_zero_silently() -> None:
    empty = (
        '<html><body><script type="application/json">'
        '{"__listing_StoreState": {"items": {"elements": []}}}'
        "</script></body></html>"
    )
    with pytest.raises(ParseError, match="zero offers"):
        parse_listing(empty)


def test_parse_listing_requires_state_blob() -> None:
    with pytest.raises(ParseError, match="__listing_StoreState"):
        parse_listing("<html><body><article>nothing</article></body></html>")


def test_parse_listing_rejects_foreign_currency() -> None:
    markup = (
        '<html><body><script type="application/json">{"__listing_StoreState": {"items": '
        '{"elements": [{"alt": "x", "eventData": {"offer_id": "123456"}, "url": '
        '"https://allegro.pl/oferta/x-123456", "seller": {"login": "s"}, "price": '
        '{"mainPrice": {"amount": "10.00", "currency": "EUR"}}}]}}}</script></body></html>'
    )
    with pytest.raises(ParseError):
        parse_listing(markup)


def test_parse_offer_prefers_serialized_price_box() -> None:
    detail = parse_offer_page(
        read("offer-wago-221.html"), "https://allegro.pl/oferta/wago-221-413-18330930177"
    )
    assert detail.provenance == "serialize-box"
    offer = detail.offer
    assert offer.price == 4599
    assert offer.offer_id == "18330930177"
    assert offer.seller_login == "elektro-hurt"
    assert offer.ean == "4044918645118"
    assert offer.rating_avg == pytest.approx(4.8)
    assert offer.rating_count == 112
    assert offer.in_stock is True
    assert offer.deep is True
    assert offer.specs["Model"] == "221-413"
    assert offer.specs["Prąd znamionowy"] == "32 A"


def test_parse_offer_falls_back_to_json_ld_price() -> None:
    detail = parse_offer_page(
        read("offer-wago-221-jsonld-only.html"), "https://allegro.pl/oferta/wago-221-413-18330930178"
    )
    assert detail.provenance == "json-ld"
    assert detail.offer.price == 3900
    assert detail.offer.rating_avg is None


def test_parse_offer_without_price_is_an_error() -> None:
    with pytest.raises(ParseError, match="no machine-readable price"):
        parse_offer_page("<html><body><h1>x</h1></body></html>", "https://allegro.pl/oferta/x-123456")


def test_parse_specs_reads_parameter_list() -> None:
    specs = parse_specs(read("offer-wago-221.html"))
    assert specs["Marka"] == "WAGO"
    assert specs["Liczba przewodów"] == "3"


def test_is_gone_page() -> None:
    assert is_gone_page("<html>Oferta została zakończona</html>")
    assert not is_gone_page("<html>WAGO 221</html>")


def test_card_without_event_url_derives_url_from_offer_id() -> None:
    markup = (
        '<html><body><script type="application/json">{"__listing_StoreState": {"items": '
        '{"elements": [{"alt": "x", "eventData": {"offer_id": "123456"}, "seller": '
        '{"login": "s"}, "price": {"mainPrice": {"amount": "10.00"}}}]}}}</script></body></html>'
    )
    page = parse_listing(markup)
    assert page.offers[0].url == "https://allegro.pl/oferta/123456"
    assert page.last_page is None


def test_non_object_elements_are_skipped_with_a_reason() -> None:
    markup = (
        '<html><body><script type="application/json">{"__listing_StoreState": {"items": '
        '{"elements": [42, {"alt": "x", "eventData": {"offer_id": "123456"}, "seller": '
        '{"login": "s"}, "price": {"mainPrice": {"amount": "10.00"}}}]}}}</script></body></html>'
    )
    page = parse_listing(markup)
    assert page.skipped[0].reason == "element is not an object"
    assert len(page.offers) == 1


def test_card_without_price_or_title_is_skipped() -> None:
    base = {"eventData": {"offer_id": "123456"}, "seller": {"login": "s"}}
    elements = [
        {**base, "price": {"mainPrice": {"amount": "10.00"}}},
        {**base, "alt": "x", "price": {"mainPrice": {"amount": "10.00"}}},
        {"alt": "x", **base},
    ]
    markup = (
        "<html><body><script type=\"application/json\">"
        + json.dumps({"__listing_StoreState": {"items": {"elements": elements}}})
        + "</script></body></html>"
    )
    page = parse_listing(markup)
    reasons = [skip.reason for skip in page.skipped]
    assert "card without a title" in reasons
    assert "card without a price" in reasons


def test_malformed_json_script_is_ignored_not_fatal() -> None:
    markup = (
        '<html><body><script type="application/json">{not json}</script>'
        '<script type="application/json">{"__listing_StoreState": {"items": {"elements": '
        '[{"alt": "x", "eventData": {"offer_id": "123456"}, "seller": {"login": "s"}, '
        '"price": {"mainPrice": {"amount": "10.00"}}}]}}}</script></body></html>'
    )
    assert len(parse_listing(markup).offers) == 1


def test_json_ld_list_is_understood() -> None:
    markup = (
        '<html><head><script type="application/ld+json">[{"@type": "BreadcrumbList"}, '
        '{"@type": "Product", "name": "x", "offers": {"price": "12.50", "priceCurrency": '
        '"PLN", "seller": {"name": "s"}}}]</script></head><body></body></html>'
    )
    detail = parse_offer_page(markup, "https://allegro.pl/oferta/x-123456")
    assert detail.offer.price == 1250


def test_parse_seller_from_boxes_and_text() -> None:
    from allegro_shopping.parse import parse_seller

    markup = (
        '<html><body><script data-serialize-box-id="r" type="application/json">'
        '{"rating": "4,91", "ratingsCount": "1 234"}</script>Super Sprzedawca</body></html>'
    )
    seller = parse_seller(markup, "kabelmax", "https://allegro.pl/uzytkownik/kabelmax")
    assert seller.rating == pytest.approx(4.91)
    assert seller.ratings_count == 1234
    assert seller.super_seller is True


def test_parse_product_page_keeps_specs_and_provenance_fields() -> None:
    from allegro_shopping.parse import parse_product_page

    product = parse_product_page(
        (FIXTURES / "product-wago-221.html").read_text(encoding="utf-8"),
        "https://allegro.pl/produkt/wago-221-413-b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3",
    )
    assert product.product_id == "b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3"
    assert product.ean == "4044918645118"
    assert product.brand == "WAGO"
    assert product.rating_count == 241
    assert product.specs["Napięcie znamionowe"] == "450 V"


def test_product_page_without_uuid_is_an_error() -> None:
    from allegro_shopping.parse import parse_product_page

    with pytest.raises(ParseError, match="uuid"):
        parse_product_page("<html></html>", "https://allegro.pl/oferta/x-123456")
