"""The run: intent -> candidates -> deep dives -> scores -> basket plan.

Every expensive step is counted against a hard budget. Hitting a budget is an
error, not a truncation: a recommendation computed from a partial candidate set
is worse than no recommendation.

The LLM never enters this module. Its jobs (prose -> request TOML, spec
normalisation, written justification) happen before or after the run.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from .basket import BasketPlan, Candidate, plan
from .cache import Cache
from .client import AllegroClient
from .config import Budgets, Item, Request, Rules
from .errors import BudgetExceeded, FetchFailure, NoCandidates
from .models import Offer, Product, Seller, utc_now
from .parse import PARSER_REV
from .score import ScoreInput, ScoreResult, score_offer


class Budget:
    """Counters with a wall-clock ceiling. Spend before doing the work."""

    def __init__(self, budgets: Budgets, clock: Callable[[], float] = time.monotonic) -> None:
        self.budgets = budgets
        self.clock = clock
        self.started = clock()
        self.pages = 0
        self.offers = 0
        self.external = 0
        self.llm = 0

    def _wall(self) -> float:
        return self.clock() - self.started

    def spend_page(self) -> None:
        if self._wall() > self.budgets.max_wall_seconds:
            raise BudgetExceeded(f"wall-clock budget of {self.budgets.max_wall_seconds}s exhausted")
        if self.pages >= self.budgets.max_search_pages * 10:
            raise BudgetExceeded(f"hard page budget exhausted ({self.pages} pages)")
        self.pages += 1

    def spend_offer(self) -> None:
        if self._wall() > self.budgets.max_wall_seconds:
            raise BudgetExceeded(f"wall-clock budget of {self.budgets.max_wall_seconds}s exhausted")
        if self.offers >= self.budgets.max_offers:
            raise BudgetExceeded(
                f"offer budget of {self.budgets.max_offers} deep dives exhausted",
                detail="raise budgets.max_offers deliberately or narrow the request",
            )
        self.offers += 1

    def spend_external(self) -> None:
        if self.external >= self.budgets.max_external_lookups:
            raise BudgetExceeded(
                f"external lookup budget of {self.budgets.max_external_lookups} exhausted"
            )
        self.external += 1

    def spend_llm(self) -> None:
        if self.llm >= self.budgets.max_llm_calls:
            raise BudgetExceeded(f"LLM budget of {self.budgets.max_llm_calls} calls exhausted")
        self.llm += 1

    def as_dict(self) -> dict[str, int]:
        return {
            "pages": self.pages,
            "offers": self.offers,
            "external": self.external,
            "llm": self.llm,
        }


@dataclass(frozen=True)
class ItemOutcome:
    item: Item
    ranked: tuple[tuple[Offer, ScoreResult], ...]
    rejected: tuple[tuple[Offer, ScoreResult], ...]
    warnings: tuple[str, ...] = ()
    # (offer_id, product page url) for every offer whose specs came from the
    # catalog page rather than the seller's own text.
    spec_sources: tuple[tuple[str, str], ...] = ()

    @property
    def best(self) -> tuple[Offer, ScoreResult] | None:
        return self.ranked[0] if self.ranked else None


@dataclass(frozen=True)
class RunResult:
    request_name: str
    generated_at: datetime
    items: tuple[ItemOutcome, ...]
    plan: BasketPlan | None
    warnings: tuple[str, ...]
    rules_version: int
    parser_rev: int
    budget: dict[str, int] = field(default_factory=dict)


def _dedupe(offers: Sequence[Offer]) -> list[Offer]:
    seen: dict[str, Offer] = {}
    for offer in offers:
        seen.setdefault(offer.offer_id, offer)
    return list(seen.values())


def run_request(
    request: Request,
    client: AllegroClient,
    rules: Rules,
    *,
    refresh: bool = False,
    budget: Budget | None = None,
    now: Callable[[], datetime] = utc_now,
) -> RunResult:
    run_budget = budget or Budget(rules.budgets)
    warnings: list[str] = []
    outcomes: list[ItemOutcome] = []
    remaining_offers = rules.budgets.max_offers

    for item in request.items:
        offers, _last_page, skipped = client.search(item.query, refresh=refresh)
        run_budget.spend_page()
        for skip in skipped:
            warnings.append(f"{item.label}: card {skip.index} skipped: {skip.reason}")
        if not offers:
            raise NoCandidates(f"{item.label}: search returned no offers for {item.query!r}")

        shortlist = _select_candidates(offers, remaining_offers)
        remaining_offers -= len(shortlist)
        sellers: dict[str, Seller | None] = {}
        products: dict[str, Product | None] = {}
        spec_sources: list[tuple[str, str]] = []
        scored: list[tuple[Offer, ScoreResult]] = []
        rejected: list[tuple[Offer, ScoreResult]] = []

        for offer in shortlist:
            run_budget.spend_offer()
            try:
                deep = client.offer_detail(offer.offer_id, refresh=refresh)
            except FetchFailure as e:
                warnings.append(
                    f"{item.label}: offer {offer.offer_id} deep dive failed: {e.message}"
                )
                continue
            client.cache.require_fresh(
                "offer", deep.fetched_at, what=f"offer {deep.offer_id}", now=now()
            )
            if deep.seller_login not in sellers:
                run_budget.spend_page()
                sellers[deep.seller_login] = client.seller(deep.seller_login, refresh=refresh)
            specs = deep.specs
            if deep.product_id is not None:
                if deep.product_id not in products:
                    run_budget.spend_page()
                    try:
                        products[deep.product_id] = client.product_detail(
                            deep.product_id, refresh=refresh
                        )
                    except FetchFailure as e:
                        warnings.append(
                            f"{item.label}: product page {deep.product_id} failed: {e.message}"
                        )
                        products[deep.product_id] = None
                product = products[deep.product_id]
                if product is not None:
                    specs = {**deep.specs, **product.specs}
                    spec_sources.append((deep.offer_id, product.url))
            result = score_offer(
                item,
                ScoreInput(
                    offer=deep,
                    seller=sellers[deep.seller_login],
                    delivery_hours=None,
                    quantity=item.quantity,
                    specs=specs if specs is not deep.specs else None,
                ),
                rules.score,
            )
            if result.eligible:
                scored.append((deep, result))
            else:
                rejected.append((deep, result))

        scored.sort(key=lambda pair: (-pair[1].total, pair[0].price, pair[0].offer_id))
        if not scored:
            reasons = "; ".join(
                f"{offer.offer_id}: {', '.join(result.gate_failures)}"
                for offer, result in rejected[:5]
            )
            raise NoCandidates(f"{item.label}: no offer passed the gates ({reasons})")
        outcomes.append(
            ItemOutcome(
                item=item,
                ranked=tuple(scored),
                rejected=tuple(rejected),
                warnings=(),
                spec_sources=tuple(spec_sources),
            )
        )

    shortlisted: list[Candidate] = []
    for outcome in outcomes:
        for offer, result in outcome.ranked[: rules.basket.shortlist]:
            shortlisted.append(
                Candidate(
                    item_label=outcome.item.label,
                    offer=offer,
                    score=result.total,
                    quantity=outcome.item.quantity,
                )
            )

    basket = plan(shortlisted, rules.basket)
    return RunResult(
        request_name=request.name,
        generated_at=now(),
        items=tuple(outcomes),
        plan=basket,
        warnings=tuple(warnings),
        rules_version=rules.version,
        parser_rev=PARSER_REV,
        budget=run_budget.as_dict(),
    )


def _select_candidates(offers: Sequence[Offer], limit: int) -> list[Offer]:
    """Cheapest first, then by rating volume. Cheap offers are the ones worth a deep dive."""
    unique = _dedupe(offers)
    unique.sort(key=lambda o: (o.price, -(o.rating_count or 0), o.offer_id))
    return unique[: max(0, limit)]


def cache_summary(cache: Cache) -> dict[str, object]:
    offers = cache.offers()
    return {
        "offers": len(offers),
        "sellers": sum(
            1 for subject in cache.store.ids("allegro") if subject.startswith("seller:")
        ),
        "products": sum(
            1 for subject in cache.store.ids("allegro") if subject.startswith("product:")
        ),
        "searches": sum(
            1 for subject in cache.store.ids("allegro") if subject.startswith("search:")
        ),
    }


@dataclass(frozen=True)
class Deviation:
    item_label: str
    offer_id: str
    field: str
    expected: str
    actual: str


def verify_plan(payload: dict[str, object], client: AllegroClient) -> list[Deviation]:
    """Re-fetch every chosen offer and diff it against the recorded plan.

    This is the safety half of the plan -> verify -> commit contract: it touches
    no account state, only reads. Any difference is a reason to re-plan.
    """
    basket = payload.get("basket")
    if not isinstance(basket, dict):
        raise NoCandidates("run file has no basket to verify")
    sellers = basket.get("sellers")
    if not isinstance(sellers, list):
        raise NoCandidates("run file basket has no sellers list")
    deviations: list[Deviation] = []
    for seller in sellers:
        if not isinstance(seller, dict):
            continue
        lines = seller.get("lines")
        if not isinstance(lines, list):
            continue
        for line in lines:
            if not isinstance(line, dict):
                continue
            offer_id = str(line.get("offer_id", ""))
            item_label = str(line.get("item", ""))
            expected_price = line.get("price_grosze")
            expected_seller = str(seller.get("seller", ""))
            live = client.offer_detail(offer_id, refresh=True)
            if expected_price is not None and int(live.price) != int(str(expected_price)):
                deviations.append(
                    Deviation(
                        item_label,
                        offer_id,
                        "price",
                        f"{expected_price} grosze",
                        f"{int(live.price)} grosze",
                    )
                )
            if live.seller_login != expected_seller:
                deviations.append(
                    Deviation(item_label, offer_id, "seller", expected_seller, live.seller_login)
                )
            if live.in_stock is False:
                deviations.append(
                    Deviation(item_label, offer_id, "stock", "in stock", "out of stock")
                )
    return deviations
