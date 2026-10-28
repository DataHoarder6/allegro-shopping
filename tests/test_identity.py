from __future__ import annotations

import pytest

from allegro_shopping.identity import (
    canonical_url,
    listing_url,
    offer_id_from_url,
    offer_subject,
    product_id_from_url,
    search_subject,
    seller_subject,
    unwrap_redirect,
)

SPONSORED = (
    "https://allegro.pl/events/clicks?emission_unit_id=abc&type=OFFER&ts=1786284832771"
    "&redirect=https%3A%2F%2Fallegro.pl%2Foferta%2Fwago-221-413-18330930177"
    "%3Fbi_s%3Dads%26bi_m%3Dproductlisting&placement=productlisting&sig=deadbeef"
)


def test_unwrap_redirect_returns_inner_url() -> None:
    assert unwrap_redirect(SPONSORED).startswith(
        "https://allegro.pl/oferta/wago-221-413-18330930177"
    )


def test_canonical_url_strips_tracking_and_keeps_identity() -> None:
    assert canonical_url(SPONSORED) == "https://allegro.pl/oferta/wago-221-413-18330930177"
    assert (
        canonical_url("https://allegro.pl/oferta/x-123456789?bi_s=ads&utm_source=mail&slist=abc")
        == "https://allegro.pl/oferta/x-123456789"
    )


def test_canonical_url_keeps_offer_id_on_product_pages() -> None:
    url = "https://allegro.pl/produkt/wago-221-413-b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3?offerId=18330930177&utm_medium=x"
    assert canonical_url(url) == (
        "https://allegro.pl/produkt/wago-221-413-b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3?offerId=18330930177"
    )


def test_canonical_url_rejects_foreign_hosts() -> None:
    with pytest.raises(ValueError):
        canonical_url("https://example.com/oferta/x-123456789")


def test_offer_id_from_offer_and_product_urls() -> None:
    assert offer_id_from_url("https://allegro.pl/oferta/wago-221-413-18330930177") == "18330930177"
    assert (
        offer_id_from_url(
            "https://allegro.pl/produkt/wago-b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3?offerId=18529923195"
        )
        == "18529923195"
    )
    assert offer_id_from_url("https://allegro.pl/listing?string=wago") is None


def test_product_id_from_url() -> None:
    url = "https://allegro.pl/produkt/wago-221-413-B4C19645-7C11-48A5-BFBE-C2EA5FBE9BC3"
    assert product_id_from_url(url) == "b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3"


def test_subjects_namespace_kinds() -> None:
    assert offer_subject("18330930177").store_id == "offer:18330930177"
    assert offer_subject("https://allegro.pl/oferta/x-18330930177").store_id == "offer:18330930177"
    assert seller_subject(" Elektro-Hurt ").store_id == "seller:elektro-hurt"
    assert search_subject("WAGO 221").store_id == search_subject("wago 221").store_id
    assert search_subject("wago", "p").store_id != search_subject("wago", "qd").store_id


def test_listing_url_is_stable_and_ordered() -> None:
    assert listing_url("wago 221") == "https://allegro.pl/listing?string=wago+221"
    assert (
        listing_url("wago 221", page=2, order="p")
        == "https://allegro.pl/listing?string=wago+221&order=p&p=2"
    )
