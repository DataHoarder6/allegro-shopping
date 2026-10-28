"""Cache policy over the shared hoard store.

The hoard (web_agent.store) is append-only facts. This module adds the only
thing a shopping assistant actually needs on top: *how old is this fact, and is
that old enough to matter*. Nothing here writes decisions; a stale offer is
still a fact, it just may not be used to recommend a purchase.

TTLs are per kind, never global: a listing page seeds candidates and can be
hours old, a price may not.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime

from web_agent.store import Store

from .config import Freshness, Rules
from .errors import StaleDataError
from .identity import (
    Subject,
    offer_subject,
    product_subject,
    search_subject,
    seller_subject,
)
from .models import Offer, Product, Seller, iso, parse_iso, utc_now

SITE = "allegro"


class Cache:
    """Read/write access to allegro rows in the shared hoard."""

    def __init__(self, store: Store, rules: Rules) -> None:
        self.store = store
        self.freshness: Freshness = rules.freshness

    # -- writes ---------------------------------------------------------------

    def add_offer(self, offer: Offer) -> int:
        return self.store.add(
            SITE,
            [{"url": offer.url, "fetched_at": iso(offer.fetched_at), "data": offer.to_record()}],
            source="allegro-shopping",
        )

    def add_product(self, product: Product) -> int:
        return self.store.add(
            SITE,
            [
                {
                    "url": product.url,
                    "fetched_at": iso(product.fetched_at),
                    "data": product.to_record(),
                }
            ],
            source="allegro-shopping",
        )

    def add_seller(self, seller: Seller, url: str) -> int:
        data = {
            "id": seller_subject(seller.login).store_id,
            "login": seller.login,
            "rating": seller.rating,
            "ratings_count": seller.ratings_count,
            "positive_feedback_percent": seller.positive_feedback_percent,
            "super_seller": seller.super_seller,
            "smart": seller.smart,
            "url": url,
        }
        return self.store.add(SITE, [{"url": url, "data": data}], source="allegro-shopping")

    def add_search_page(
        self,
        *,
        query: str,
        order: str | None,
        page: int,
        url: str,
        offer_ids: Iterable[str],
        last_page: int | None,
    ) -> int:
        subject = search_page_subject(query, order, page)
        data = {
            "id": subject.store_id,
            "query": query,
            "order": order,
            "page": page,
            "offer_ids": sorted(set(offer_ids)),
            "last_page": last_page,
        }
        return self.store.add(SITE, [{"url": url, "data": data}], source="allegro-shopping")

    # -- reads ----------------------------------------------------------------

    def offer(self, offer_id: str) -> Offer | None:
        rows = self.store.latest(SITE, offer_subject(offer_id).store_id)
        return Offer.from_record(rows[0]["data"]) if rows else None

    def offers(self) -> dict[str, Offer]:
        out: dict[str, Offer] = {}
        for row in self.store.latest(SITE):
            data = row["data"]
            if not isinstance(data.get("id", ""), str) or not data["id"].startswith("offer:"):
                continue
            offer = Offer.from_record(data)
            out[offer.offer_id] = offer
        return out

    def offers_for_product(self, product_id: str) -> list[Offer]:
        return [o for o in self.offers().values() if o.product_id == product_id.lower()]

    def product(self, product_id: str) -> Product | None:
        rows = self.store.latest(SITE, product_subject(product_id).store_id)
        return Product.from_record(rows[0]["data"]) if rows else None

    def seller(self, login: str) -> Seller | None:
        rows = self.store.latest(SITE, seller_subject(login).store_id)
        if not rows:
            return None
        data = rows[0]["data"]
        return Seller(
            login=str(data["login"]),
            rating=data.get("rating"),
            ratings_count=data.get("ratings_count"),
            positive_feedback_percent=data.get("positive_feedback_percent"),
            super_seller=bool(data.get("super_seller", False)),
            smart=bool(data.get("smart", False)),
            url=data.get("url"),
        )

    def search_page(self, query: str, order: str | None, page: int) -> tuple[list[str], datetime]:
        subject = search_page_subject(query, order, page)
        rows = self.store.latest(SITE, subject.store_id)
        if not rows:
            return [], datetime.min.replace(tzinfo=UTC)
        data = rows[0]["data"]
        ids = [str(i) for i in data.get("offer_ids", [])]
        return ids, parse_iso(rows[0]["fetched_at"])

    # -- freshness ------------------------------------------------------------

    def freshness_hours(self, kind: str) -> int:
        match kind:
            case "search":
                return self.freshness.search_hours
            case "offer":
                return self.freshness.offer_hours
            case "detail":
                return self.freshness.detail_hours
            case "seller":
                return self.freshness.seller_hours
            case _:
                raise ValueError(f"unknown freshness kind {kind!r}")

    def age_hours(self, moment: datetime, now: datetime | None = None) -> float:
        reference = now or utc_now()
        return (reference - moment).total_seconds() / 3600.0

    def is_fresh(self, kind: str, moment: datetime, now: datetime | None = None) -> bool:
        return self.age_hours(moment, now) <= self.freshness_hours(kind)

    def require_fresh(
        self, kind: str, moment: datetime, *, what: str, now: datetime | None = None
    ) -> None:
        """Raise StaleDataError when `moment` is older than the kind's TTL."""
        age = self.age_hours(moment, now)
        ttl = self.freshness_hours(kind)
        if age > ttl:
            raise StaleDataError(
                f"{what} is {age:.1f}h old, {kind} TTL is {ttl}h",
                detail="refresh it (allegro-shop refresh) or widen the TTL deliberately",
            )


def search_page_subject(query: str, order: str | None, page: int) -> Subject:
    base = search_subject(query, order)
    return Subject(base.kind, f"{base.key}:p{page}")
