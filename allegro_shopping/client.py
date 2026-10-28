"""Cache-aware Allegro client: the only place where "have we got it?" is decided.

Order of operations for every read:

1. ask the hoard;
2. if the row is fresh enough for its purpose, use it — no request;
3. otherwise fetch exactly that one page, parse it, append the observation.

A cache hit is never allowed to answer "what does it cost now" beyond the
offer TTL; the policy lives in `Cache.require_fresh` and is enforced here.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from .cache import Cache
from .config import Rules
from .errors import FetchFailure, UsageError
from .identity import canonical_url, listing_url, offer_id_from_url, seller_subject
from .models import Offer, Product, Seller, utc_now
from .parse import (
    SkippedCard,
    parse_listing,
    parse_offer_page,
    parse_product_page,
    parse_seller,
)
from .session import PageSource


class AllegroClient:
    def __init__(
        self,
        pages: PageSource,
        cache: Cache,
        rules: Rules,
        now: Callable[[], datetime] = utc_now,
    ) -> None:
        self.pages = pages
        self.cache = cache
        self.rules = rules
        self.now = now

    # -- search ---------------------------------------------------------------

    def search(
        self,
        query: str,
        *,
        order: str | None = None,
        page: int = 1,
        refresh: bool = False,
    ) -> tuple[list[Offer], int | None, tuple[SkippedCard, ...]]:
        if not refresh:
            cached_ids, fetched_at = self.cache.search_page(query, order, page)
            if cached_ids and self.cache.is_fresh("search", fetched_at, self.now()):
                offers = [self.cache.offer(oid) for oid in cached_ids]
                if all(offer is not None for offer in offers):
                    return [offer for offer in offers if offer is not None], None, ()

        url = listing_url(query, page=page, order=order)
        markup = self.pages.fetch(url, self.rules.site.listing_ready_selector)
        parsed = parse_listing(markup)
        for offer in parsed.offers:
            self.cache.add_offer(offer)
        self.cache.add_search_page(
            query=query,
            order=order,
            page=page,
            url=url,
            offer_ids=[offer.offer_id for offer in parsed.offers],
            last_page=parsed.last_page,
        )
        return list(parsed.offers), parsed.last_page, parsed.skipped

    # -- deep dive ------------------------------------------------------------

    def offer_detail(self, offer_id: str, *, refresh: bool = False) -> Offer:
        cached = self.cache.offer(offer_id)
        if (
            cached is not None
            and not refresh
            and cached.deep
            and self.cache.is_fresh("offer", cached.fetched_at, self.now())
        ):
            return cached
        url = cached.url if cached is not None else f"{self.rules.site.base_url}/oferta/{offer_id}"
        markup = self.pages.fetch(url, self.rules.site.offer_ready_selector)
        detail = parse_offer_page(markup, url)
        self.cache.add_offer(detail.offer)
        return detail.offer

    def product_detail(self, product_id: str, *, refresh: bool = False) -> Product:
        """The catalog page: the spec table shared by every offer of this product.

        Offer pages are seller claims; this is the identity of record, so it is
        cached separately and never overwritten by offer data.
        """
        cached = self.cache.product(product_id)
        if cached is not None and not refresh and self.cache.is_fresh(
            "detail", cached.fetched_at, self.now()
        ):
            return cached
        url = (
            cached.url
            if cached is not None
            else f"{self.rules.site.base_url}/produkt/{product_id}"
        )
        markup = self.pages.fetch(url, self.rules.site.offer_ready_selector)
        product = parse_product_page(markup, url)
        self.cache.add_product(product)
        return product

    def seller(self, login: str, *, refresh: bool = False) -> Seller | None:
        cached = self.cache.seller(login)
        if cached is not None and not refresh:
            rows = self.cache.store.latest("allegro", seller_subject(login).store_id)
            if rows and self.cache.is_fresh(
                "seller", datetime.fromisoformat(rows[0]["fetched_at"]), self.now()
            ):
                return cached
        url = f"{self.rules.site.base_url}/uzytkownik/{login}"
        try:
            markup = self.pages.fetch(url, "body")
        except FetchFailure:
            return None
        seller = parse_seller(markup, login, url)
        self.cache.add_seller(seller, url)
        return seller

    # -- capture --------------------------------------------------------------

    def capture(self, url: str) -> str:
        """Fetch a page exactly as the parser would receive it."""
        canon = canonical_url(url)
        if offer_id_from_url(canon) is not None:
            selector = self.rules.site.offer_ready_selector
        elif "/listing" in canon or "/kategoria/" in canon:
            selector = self.rules.site.listing_ready_selector
        else:
            raise UsageError(f"cannot tell listing from offer page: {url}")
        return self.pages.fetch(canon, selector)
