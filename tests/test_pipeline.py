from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import make_item, make_offer, make_seller
from web_agent.store import Store

from allegro_shopping.cache import Cache
from allegro_shopping.client import AllegroClient
from allegro_shopping.config import Request, Rules
from allegro_shopping.errors import BudgetExceeded, FetchFailure, NoCandidates, StaleDataError
from allegro_shopping.money import Grosze
from allegro_shopping.parse import SkippedCard
from allegro_shopping.pipeline import Budget, run_request
from allegro_shopping.report import to_json, to_markdown, write_run
from allegro_shopping.session import PageSource

NOW = datetime(2026, 10, 28, 12, 0, tzinfo=UTC)


class FakePages(PageSource):
    def __init__(self, markup_by_url: dict[str, str]) -> None:
        self.markup_by_url = markup_by_url
        self.fetched: list[str] = []

    def fetch(self, url: str, ready_selector: str) -> str:
        del ready_selector
        self.fetched.append(url)
        try:
            return self.markup_by_url[url]
        except KeyError as e:
            raise FetchFailure(f"no fixture for {url}") from e


def build_request(*items) -> Request:
    return Request(name="wago restock", items=tuple(items))


def make_client(tmp_path: Path, rules: Rules, pages: FakePages, offers: list) -> AllegroClient:
    cache = Cache(Store(tmp_path / "hoard.db"), rules)
    for offer in offers:
        cache.add_offer(offer)
    cache.add_search_page(
        query="wago 221-413",
        order=None,
        page=1,
        url="https://allegro.pl/listing?string=wago+221-413",
        offer_ids=[offer.offer_id for offer in offers],
        last_page=None,
    )
    return AllegroClient(pages, cache, rules, now=lambda: NOW)


def test_run_produces_ranked_items_and_basket(tmp_path: Path, rules: Rules) -> None:
    offers = [
        make_offer("1000001", price=4500, seller="elektro-hurt"),
        make_offer("1000002", price=4200, seller="kabelmax", rating_count=4),
    ]
    client = make_client(tmp_path, rules, FakePages({}), offers)
    # Deep dives are already cached and fresh: no page fetch is needed.
    result = run_request(build_request(make_item(quantity=2)), client, rules, now=lambda: NOW)
    assert len(result.items) == 1
    assert result.plan is not None
    assert result.plan.grand_total > 0
    assert result.items[0].best is not None
    assert result.budget["offers"] == 2


def test_run_uses_cache_instead_of_refetching(tmp_path: Path, rules: Rules) -> None:
    offers = [make_offer("1000001", price=4500)]
    pages = FakePages({})
    client = make_client(tmp_path, rules, pages, offers)
    cache = client.cache
    cache.add_search_page(
        query="wago 221-413",
        order=None,
        page=1,
        url="https://allegro.pl/listing?string=wago+221-413",
        offer_ids=["1000001"],
        last_page=None,
    )
    run_request(build_request(make_item()), client, rules, now=lambda: NOW)
    assert not any("listing" in url or "/oferta/" in url for url in pages.fetched)


def test_offer_detail_refresh_fetches_and_parses(tmp_path: Path, rules: Rules) -> None:
    offer = make_offer("18330930177", price=4500)
    markup = (
        Path(__file__).parent / "fixtures" / "allegro" / "offer-wago-221.html"
    ).read_text(encoding="utf-8")
    pages = FakePages({offer.url: markup})
    client = make_client(tmp_path, rules, pages, [offer])
    refreshed = client.offer_detail("18330930177", refresh=True)
    assert pages.fetched == [offer.url]
    assert refreshed.price == 4599
    assert refreshed.deep is True


def test_stale_offer_is_refused_before_scoring(tmp_path: Path, rules: Rules) -> None:
    stale = makes_stale(make_offer("1000001", price=4500))
    client = make_client(tmp_path, rules, FakePages({}), [stale])
    with pytest.raises(StaleDataError, match="TTL is 2h"):
        client.cache.require_fresh("offer", stale.fetched_at, what="offer 1000001", now=NOW)


def makes_stale(offer):
    return replace(offer, fetched_at=datetime(2026, 10, 1, tzinfo=UTC))


def test_offer_budget_is_a_hard_error(tmp_path: Path, rules: Rules) -> None:
    offers = [make_offer(f"10000{i}", price=4000 + i) for i in range(1, 4)]
    client = make_client(tmp_path, rules, FakePages({}), offers)
    tight = Budget(replace(rules.budgets, max_offers=1))
    with pytest.raises(BudgetExceeded, match="offer budget"):
        run_request(build_request(make_item()), client, rules, budget=tight, now=lambda: NOW)


def test_no_eligible_offer_raises(tmp_path: Path, rules: Rules) -> None:
    offers = [make_offer("1000001", price=4000, condition="Używany")]
    client = make_client(tmp_path, rules, FakePages({}), offers)
    with pytest.raises(NoCandidates, match="no offer passed the gates"):
        run_request(build_request(make_item()), client, rules, now=lambda: NOW)


def test_report_markdown_and_json_are_consistent(tmp_path: Path, rules: Rules) -> None:
    offers = [
        make_offer("1000001", price=4500),
        make_offer("1000002", price=4600, seller="kabelmax"),
    ]
    client = make_client(tmp_path, rules, FakePages({}), offers)
    result = run_request(build_request(make_item()), client, rules, now=lambda: NOW)
    markdown = to_markdown(result)
    assert "# wago restock" in markdown
    assert "## Basket" in markdown
    assert "WAGO 221 offer 1000001" in markdown
    payload = to_json(result)
    assert payload["request"] == "wago restock"
    assert payload["basket"]["sellers_used"] == 1
    md_path, json_path = write_run(result, tmp_path / "runs")
    assert md_path.exists() and json_path.exists()


def test_skipped_cards_become_warnings(tmp_path: Path, rules: Rules) -> None:
    offers = [make_offer("1000001", price=4500)]

    class SkippingClient(AllegroClient):
        def search(self, query, *, order=None, page=1, refresh=False):  # type: ignore[override]
            return offers, None, (SkippedCard(3, "card without a seller"),)

    cache = Cache(Store(tmp_path / "hoard.db"), rules)
    for offer in offers:
        cache.add_offer(offer)
    client = SkippingClient(FakePages({}), cache, rules, now=lambda: NOW)
    result = run_request(build_request(make_item()), client, rules, now=lambda: NOW)
    assert any("skipped" in warning for warning in result.warnings)


def test_seller_is_looked_up_once_per_run(tmp_path: Path, rules: Rules) -> None:
    offers = [
        make_offer("1000001", price=4500, seller="same"),
        make_offer("1000002", price=4600, seller="same"),
    ]
    client = make_client(tmp_path, rules, FakePages({}), offers)
    calls: list[str] = []
    original = client.seller

    def counted(login: str, *, refresh: bool = False):
        calls.append(login)
        return make_seller(login)

    client.seller = counted  # type: ignore[method-assign]
    run_request(build_request(make_item()), client, rules, now=lambda: NOW)
    assert calls == ["same"]
    assert original is not None


def _plan_payload(result) -> dict:
    import json

    return json.loads(json.dumps(to_json(result)))


def test_verify_reports_no_drift_when_offers_are_unchanged(tmp_path: Path, rules: Rules) -> None:
    from allegro_shopping.pipeline import verify_plan

    offer = make_offer("1000001", price=4500)
    client = make_client(tmp_path, rules, FakePages({}), [offer])
    result = run_request(build_request(make_item()), client, rules, now=lambda: NOW)
    client.offer_detail = lambda offer_id, refresh=False: offer  # type: ignore[method-assign]
    assert verify_plan(_plan_payload(result), client) == []


def test_verify_reports_price_seller_and_stock_drift(tmp_path: Path, rules: Rules) -> None:
    from allegro_shopping.pipeline import verify_plan

    offer = make_offer("1000001", price=4500)
    client = make_client(tmp_path, rules, FakePages({}), [offer])
    result = run_request(build_request(make_item()), client, rules, now=lambda: NOW)
    changed = replace(offer, price=Grosze(9999), seller_login="other", in_stock=False)
    client.offer_detail = lambda offer_id, refresh=False: changed  # type: ignore[method-assign]
    fields = {d.field for d in verify_plan(_plan_payload(result), client)}
    assert fields == {"price", "seller", "stock"}


def test_verify_requires_a_basket() -> None:
    from allegro_shopping.pipeline import verify_plan

    class Unused:
        pass

    with pytest.raises(NoCandidates, match="no basket"):
        verify_plan({"items": []}, Unused())  # type: ignore[arg-type]


def test_catalog_specs_hydrate_a_required_spec(tmp_path: Path, rules: Rules) -> None:
    from allegro_shopping.models import Product

    product_id = "b4c19645-7c11-48a5-bfbe-c2ea5fbe9bc3"
    offer = replace(
        make_offer("1000001", price=4500, specs={}), product_id=product_id
    )
    client = make_client(tmp_path, rules, FakePages({}), [offer])
    client.cache.add_product(
        Product(
            product_id=product_id,
            title="WAGO 221-413",
            url=f"https://allegro.pl/produkt/{product_id}",
            specs={"Model": "221-413"},
            fetched_at=NOW,
        )
    )
    result = run_request(
        build_request(make_item(required_specs={"Model": "221-413"})),
        client,
        rules,
        now=lambda: NOW,
    )
    assert result.items[0].ranked
    assert result.items[0].spec_sources == (
        ("1000001", f"https://allegro.pl/produkt/{product_id}"),
    )
    markdown = to_markdown(result)
    assert "specs of record" in markdown
