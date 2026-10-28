"""Allegro page parsers. Deterministic, fixture-tested, no LLM.

Allegro ships its data twice: as JSON inside `<script>` tags (stable across CSS
deploys) and as rendered DOM (rotating class names). We read the JSON first and
the DOM only for the few things that exist only there (the spec table).

Parsers are pure: `str -> records`. No fetching, no clock, no network. That is
what makes them fixture-testable and what keeps the slow path out of the loop.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

from lxml import html as lxml_html
from lxml.etree import ParserError

from .errors import ParseError
from .identity import canonical_url, offer_id_from_url, product_id_from_url
from .models import Offer, Product, Seller
from .money import Grosze

PARSER_REV = 2

_PROMOTED_CONTEXTS = frozenset({"PROMOTED", "SPONSORED", "ADS"})
_AVAILABILITY_IN_STOCK = frozenset(
    {"http://schema.org/InStock", "https://schema.org/InStock", "InStock"}
)
_ITEM_CONDITIONS = {
    "NewCondition": "new",
    "UsedCondition": "used",
    "RefurbishedCondition": "refurbished",
    "DamagedCondition": "damaged",
}


@dataclass(frozen=True)
class SkippedCard:
    index: int
    reason: str


@dataclass(frozen=True)
class ListingPage:
    offers: tuple[Offer, ...]
    last_page: int | None
    skipped: tuple[SkippedCard, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class OfferDetail:
    offer: Offer
    specs: dict[str, str]
    provenance: str


def _document(markup: str) -> Any:
    try:
        return lxml_html.fromstring(markup)
    except (ParserError, ValueError) as e:
        raise ParseError(f"page is not parseable HTML: {e}") from e


def _scripts(doc: Any) -> list[str]:
    out: list[str] = []
    for node in doc.xpath("//script"):
        text = node.text_content()
        if text and text.strip():
            out.append(text)
    return out


def _json_value(text: str) -> Any | None:
    """Decode the first JSON value in a script body, tolerating a JS prefix."""
    starts = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not starts:
        return None
    try:
        value, _ = json.JSONDecoder().raw_decode(text[min(starts) :])
    except json.JSONDecodeError:
        return None
    return value


def _listing_state(markup: str) -> dict[str, Any]:
    doc = _document(markup)
    for body in _scripts(doc):
        if "__listing_StoreState" not in body:
            continue
        value = _json_value(body)
        if isinstance(value, dict):
            state = value.get("__listing_StoreState")
            if isinstance(state, dict):
                return state
    raise ParseError("no __listing_StoreState JSON on the page (layout changed?)")


def _search_meta(markup: str) -> dict[str, Any]:
    doc = _document(markup)
    for body in _scripts(doc):
        if "searchMeta" not in body:
            continue
        value = _json_value(body)
        if not isinstance(value, dict):
            continue
        props = value.get("props")
        if isinstance(props, dict):
            nested = props.get("searchMeta")
            if isinstance(nested, dict):
                return nested
        direct = value.get("searchMeta")
        if isinstance(direct, dict):
            return direct
    return {}


def _amount_to_grosze(value: Any) -> Grosze:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ParseError(f"price amount is not a scalar: {value!r}")
    try:
        dec = Decimal(str(value).replace(" ", "").replace("\u00a0", "").replace(",", "."))
    except InvalidOperation as e:
        raise ParseError(f"price amount is not numeric: {value!r}") from e
    if dec < 0:
        raise ParseError(f"negative price: {value!r}")
    return Grosze(int((dec * 100).to_integral_value()))


def _card_price(element: dict[str, Any]) -> tuple[Grosze, str] | None:
    price = element.get("price")
    if not isinstance(price, dict):
        return None
    main = price.get("mainPrice") if isinstance(price.get("mainPrice"), dict) else price
    assert isinstance(main, dict)
    amount = main.get("amount")
    currency = main.get("currency", "PLN")
    if amount is None:
        return None
    if currency != "PLN":
        raise ParseError(f"unexpected currency {currency!r} on a PLN marketplace")
    return _amount_to_grosze(amount), str(currency)


def _card_title(element: dict[str, Any]) -> str:
    alt = element.get("alt")
    if isinstance(alt, str) and alt.strip():
        return alt.strip()
    title = element.get("title")
    if isinstance(title, dict):
        text = title.get("text")
        if isinstance(text, str) and text.strip():
            return text.strip()
    raise ValueError("card without a title")


def _card_shipping(element: dict[str, Any]) -> tuple[Grosze | None, str | None]:
    shipping = element.get("shipping")
    if not isinstance(shipping, dict):
        return None, None
    if shipping.get("freeDelivery") is True:
        return Grosze(0), "free delivery"
    lowest = shipping.get("lowest")
    if isinstance(lowest, dict) and lowest.get("amount") is not None:
        return _amount_to_grosze(lowest["amount"]), None
    return None, None


def _card_rating(element: dict[str, Any]) -> tuple[float | None, int | None]:
    block = element.get("productReview")
    source = block.get("rating") if isinstance(block, dict) else element.get("rating")
    if not isinstance(source, dict):
        return None, None
    raw_avg = source.get("average") or source.get("ratingValue")
    raw_count = source.get("count") or source.get("reviewCount")
    avg = float(raw_avg) if isinstance(raw_avg, (str, int, float)) else None
    count = _int_or_none(raw_count)
    return avg, count


def _card_seller(element: dict[str, Any]) -> tuple[str, bool, float | None]:
    seller = element.get("seller")
    if not isinstance(seller, dict):
        raise ValueError("card without a seller")
    login = seller.get("login")
    if not isinstance(login, str) or not login.strip():
        raise ValueError("card without a seller")
    percent = seller.get("positiveFeedbackPercent")
    percent_value = (
        float(percent) if isinstance(percent, (int, float, str)) and str(percent) else None
    )
    return login.strip(), bool(seller.get("superSeller", False)), percent_value


def _card_offer(element: dict[str, Any], position: int) -> Offer:
    del position
    title = _card_title(element)
    event = element.get("eventData") if isinstance(element.get("eventData"), dict) else {}
    offer_id = str(element.get("offerId") or "")
    if not offer_id and isinstance(event, dict):
        offer_id = str(event.get("offer_id") or "")
    raw_url = element.get("url") or (event.get("url") if isinstance(event, dict) else None)
    if not offer_id and isinstance(raw_url, str):
        offer_id = offer_id_from_url(raw_url) or ""
    if not offer_id.isdigit():
        raise ValueError("card without an offer id")
    url = canonical_url(raw_url) if isinstance(raw_url, str) else f"https://allegro.pl/oferta/{offer_id}"
    priced = _card_price(element)
    if priced is None:
        raise ValueError("card without a price")
    price, _currency = priced
    login, super_seller, positive_percent = _card_seller(element)
    rating_avg, rating_count = _card_rating(element)
    delivery, delivery_text = _card_shipping(element)
    delivery_info = element.get("deliveryInfo")
    if isinstance(delivery_info, dict) and isinstance(delivery_info.get("text"), str):
        delivery_text = delivery_info["text"].strip()
    context = str(element.get("context", "")).upper()
    sponsored = (
        context in _PROMOTED_CONTEXTS
        or bool(element.get("promoted"))
        or bool(element.get("isSponsored"))
    )
    cart_available = element.get("cartAvailable")
    in_stock = cart_available if isinstance(cart_available, bool) else None
    thumbnail = element.get("mainThumbnail") or element.get("thumbnail")
    return Offer(
        offer_id=offer_id,
        title=title,
        url=url,
        price=price,
        seller_login=login,
        product_id=product_id_from_url(url) or _uuid_or_none(element.get("id")),
        delivery_grosze=delivery,
        delivery_text=delivery_text,
        smart=bool(delivery == 0) if delivery is not None else None,
        sponsored=sponsored,
        in_stock=in_stock,
        thumbnail=str(thumbnail) if isinstance(thumbnail, str) else None,
        rating_avg=rating_avg,
        rating_count=rating_count,
        seller_super_seller=super_seller,
        seller_positive_percent=positive_percent,
        parser_rev=PARSER_REV,
    )


def _uuid_or_none(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    match = re.fullmatch(
        r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", value
    )
    return value.lower() if match else None


def parse_listing(markup: str) -> ListingPage:
    """Parse one search/listing page. Never returns an empty page silently."""
    state = _listing_state(markup)
    items = state.get("items")
    if not isinstance(items, dict):
        raise ParseError("listing state has no items object")
    elements = items.get("elements")
    if not isinstance(elements, list):
        raise ParseError("listing state has no items.elements array")
    offers: list[Offer] = []
    skipped: list[SkippedCard] = []
    for index, element in enumerate(elements):
        if not isinstance(element, dict):
            skipped.append(SkippedCard(index, "element is not an object"))
            continue
        try:
            offers.append(_card_offer(element, index))
        except ValueError as e:
            skipped.append(SkippedCard(index, str(e)))
    if not offers:
        raise ParseError(f"listing parsed to zero offers ({len(skipped)} cards skipped)")
    last_page_raw = _search_meta(markup).get("lastAvailablePage")
    last_page = (
        int(last_page_raw)
        if isinstance(last_page_raw, (int, str)) and str(last_page_raw).isdigit()
        else None
    )
    return ListingPage(offers=tuple(offers), last_page=last_page, skipped=tuple(skipped))


def _json_ld_products(markup: str) -> list[dict[str, Any]]:
    doc = _document(markup)
    found: list[dict[str, Any]] = []
    for node in doc.xpath("//script[@type='application/ld+json']"):
        body = node.text_content()
        if not body.strip():
            continue
        try:
            value = json.loads(body)
        except json.JSONDecodeError:
            continue
        for candidate in value if isinstance(value, list) else [value]:
            if not isinstance(candidate, dict):
                continue
            types = candidate.get("@type")
            types = types if isinstance(types, list) else [types]
            if any(str(t).lower() == "product" for t in types):
                found.append(candidate)
    return found


def _serialized_boxes(markup: str) -> dict[str, Any]:
    """Merge the `data-serialize-box-id` JSON blobs into one dict."""
    doc = _document(markup)
    merged: dict[str, Any] = {}
    for node in doc.xpath("//script[@data-serialize-box-id]"):
        value = _json_value(node.text_content())
        if isinstance(value, dict):
            merged.update(value)
    return merged


def _float_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        return float(str(value).replace(",", "."))
    except ValueError:
        return None


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        digits = re.sub(r"[^0-9]", "", value)
        if digits:
            return int(digits)
    return None


def _clean_text(text: str) -> str:
    """Collapse whitespace classes: Allegro mixes spaces, NBSP and narrow NBSP."""
    return " ".join(text.replace("\u00a0", " ").replace("\u202f", " ").split())


def parse_specs(markup: str) -> dict[str, str]:
    """Extract the parameter table: `<ul><li><b>Key:</b> value</li></ul>`."""
    doc = _document(markup)
    specs: dict[str, str] = {}
    for item in doc.xpath("//ul/li[b]"):
        key = _clean_text(item.xpath("string(./b)") or "").rstrip(":")
        value = _clean_text("".join(item.xpath("./text()")))
        if key and value and key not in specs:
            specs[key] = value
    return specs


def parse_offer_page(markup: str, url: str) -> OfferDetail:
    """Parse an offer/product page into a deep Offer plus its spec table."""
    canon = canonical_url(url)
    offer_id = offer_id_from_url(canon)
    if offer_id is None:
        raise ParseError(f"offer page URL has no offer id: {url}")

    boxed = _serialized_boxes(markup)
    products = _json_ld_products(markup)
    product = products[0] if products else {}

    title = product.get("name") if isinstance(product.get("name"), str) else None
    price_block = boxed.get("price")
    price_grosze: Grosze | None = None
    currency: str | None = None
    provenance: str | None = None
    if isinstance(price_block, dict):
        main = (
            price_block.get("mainPrice")
            if isinstance(price_block.get("mainPrice"), dict)
            else price_block
        )
        if isinstance(main, dict) and main.get("amount") is not None:
            price_grosze = _amount_to_grosze(main["amount"])
            currency = str(main.get("currency", "PLN"))
            provenance = "serialize-box"
    if price_grosze is None:
        offers = product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict) and offers.get("price") is not None:
            price_grosze = _amount_to_grosze(offers["price"])
            currency = str(offers.get("priceCurrency", "PLN"))
            provenance = "json-ld"
    if price_grosze is None:
        raise ParseError("offer page has no machine-readable price (both extractors failed)")
    if currency != "PLN":
        raise ParseError(f"unexpected currency {currency!r}")

    seller_block = boxed.get("sellerName")
    seller_login = None
    if isinstance(seller_block, str):
        seller_login = seller_block
    elif isinstance(seller_block, dict):
        raw_login = seller_block.get("login") or seller_block.get("name")
        seller_login = raw_login if isinstance(raw_login, str) else None
    if seller_login is None:
        offers = product.get("offers")
        if isinstance(offers, list):
            offers = offers[0] if offers else None
        if isinstance(offers, dict):
            seller = offers.get("seller")
            if isinstance(seller, dict) and isinstance(seller.get("name"), str):
                seller_login = seller["name"]
    if not seller_login:
        raise ParseError("offer page has no seller identity")

    rating = product.get("aggregateRating")
    rating_avg = rating_count = None
    if isinstance(rating, dict):
        rating_avg = _float_or_none(rating.get("ratingValue"))
        rating_count = _int_or_none(rating.get("reviewCount") or rating.get("ratingCount"))
    if rating_avg is None:
        box_rating = boxed.get("aggregateRating")
        if isinstance(box_rating, dict):
            rating_avg = _float_or_none(box_rating.get("ratingValue"))
            rating_count = _int_or_none(box_rating.get("reviewCount"))

    availability = None
    offers_block = product.get("offers")
    if isinstance(offers_block, list):
        offers_block = offers_block[0] if offers_block else None
    condition: str | None = None
    if isinstance(offers_block, dict):
        availability = offers_block.get("availability")
        raw_condition = offers_block.get("itemCondition")
        if isinstance(raw_condition, str):
            condition = _ITEM_CONDITIONS.get(raw_condition.rsplit("/", 1)[-1])
    in_stock = str(availability) in _AVAILABILITY_IN_STOCK if availability else None

    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    ean_raw = product.get("gtin13") or product.get("gtin") or product.get("ean")
    specs = parse_specs(markup)
    if isinstance(brand, str):
        specs.setdefault("Marka", brand)

    description = product.get("description")
    offer = Offer(
        offer_id=offer_id,
        title=title or f"offer {offer_id}",
        url=canon,
        price=price_grosze,
        seller_login=seller_login.strip(),
        product_id=product_id_from_url(canon),
        ean=str(ean_raw) if isinstance(ean_raw, (str, int)) else None,
        condition=condition or specs.get("Stan"),
        in_stock=in_stock,
        rating_avg=rating_avg,
        rating_count=rating_count,
        description=description if isinstance(description, str) else None,
        specs=specs,
        deep=True,
        parser_rev=PARSER_REV,
    )
    assert provenance is not None
    return OfferDetail(offer=offer, specs=specs, provenance=provenance)


def parse_product_page(markup: str, url: str) -> Product:
    """Parse the catalog product page: the spec table of record for all offers.

    Offer pages carry seller claims; the product page carries the shared
    parameter table. Both are kept, with their own URL and timestamp.
    """
    canon = canonical_url(url)
    product_id = product_id_from_url(canon)
    if product_id is None:
        raise ParseError(f"product page URL has no product uuid: {url}")
    products = _json_ld_products(markup)
    product = products[0] if products else {}
    name = product.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ParseError("product page has no name")
    brand = product.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    rating = product.get("aggregateRating")
    rating_avg = rating_count = None
    if isinstance(rating, dict):
        rating_avg = _float_or_none(rating.get("ratingValue"))
        rating_count = _int_or_none(rating.get("reviewCount") or rating.get("ratingCount"))
    ean = product.get("gtin13") or product.get("gtin") or product.get("ean")
    description = product.get("description")
    specs = parse_specs(markup)
    if isinstance(brand, str):
        specs.setdefault("Marka", brand)
    return Product(
        product_id=product_id,
        title=name.strip(),
        url=canon,
        ean=str(ean) if isinstance(ean, (str, int)) else None,
        brand=brand if isinstance(brand, str) else None,
        specs=specs,
        rating_avg=rating_avg,
        rating_count=rating_count,
        description=description if isinstance(description, str) else None,
        parser_rev=PARSER_REV,
    )


def parse_seller(markup: str, login: str, url: str) -> Seller:
    """Parse a seller profile page."""
    boxed = _serialized_boxes(markup)
    rating = _float_or_none(boxed.get("rating"))
    count = _int_or_none(boxed.get("ratingsCount"))
    if rating is None:
        doc = _document(markup)
        text = " ".join(doc.xpath("//body//text()"))
        match = re.search(r"(\d[,.]\d{1,2})\s*(?:na 5|/ ?5)", text)
        rating = _float_or_none(match.group(1)) if match else None
        tail = text.split("na 5")[-1] if "na 5" in text else text
        count_match = re.search(r"(\d{1,3}(?:[ \u00a0]\d{3})+|\d+)\s*ocen", tail)
        count = _int_or_none(count_match.group(1).replace(" ", "")) if count_match else None
    return Seller(
        login=login,
        rating=rating,
        ratings_count=count,
        super_seller="Super Sprzedawca" in markup,
        url=url,
    )


def is_gone_page(markup: str) -> bool:
    """True when the offer is finished/removed rather than merely blocked."""
    lowered = markup.lower()
    return any(
        marker in lowered
        for marker in (
            "oferta została zakończona",
            "oferta nie jest już dostępna",
            "ten przedmiot nie jest już dostępny",
            "nie znaleźliśmy tej strony",
        )
    )
