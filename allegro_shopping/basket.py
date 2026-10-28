"""Basket planning: buy every item once, minimise money actually paid.

The problem is ISOP (Internet Shopping Optimization Problem): one offer per
item, delivery charged per used seller, free above a per-seller threshold. It
is NP-hard in general, so the model is solved exactly with CP-SAT on the small
candidate sets this tool produces (< 10 items x < 40 offers). No greedy
heuristics: with that size, exactness is cheaper than being wrong.

Money is grosze integers throughout. The objective is the true total, so the
"cheaper item beats the shipping saving" rule is not special-cased — it falls
out of minimising the sum.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ortools.sat.python import cp_model

from .config import BasketRules
from .errors import NoCandidates
from .models import Offer
from .money import Grosze


@dataclass(frozen=True)
class Candidate:
    """One offer that may fulfil one item, with its ranking score."""

    item_label: str
    offer: Offer
    score: float
    quantity: int

    @property
    def line_goods(self) -> Grosze:
        return Grosze(int(self.offer.price) * self.quantity)


@dataclass(frozen=True)
class BasketLine:
    item_label: str
    offer: Offer
    quantity: int
    score: float
    goods: Grosze


@dataclass(frozen=True)
class SellerSlice:
    seller: str
    lines: tuple[BasketLine, ...]
    subtotal: Grosze
    delivery: Grosze
    free_delivery: bool


@dataclass(frozen=True)
class BasketPlan:
    slices: tuple[SellerSlice, ...]
    items_total: Grosze
    delivery_total: Grosze
    grand_total: Grosze
    baseline_total: Grosze
    savings: Grosze
    sellers_used: int
    solver: str

    @property
    def lines(self) -> tuple[BasketLine, ...]:
        return tuple(line for s in self.slices for line in s.lines)


def seller_delivery_fee(offers: Sequence[Offer], rules: BasketRules) -> Grosze:
    """Known per-offer delivery wins; otherwise the category default applies."""
    known = [int(o.delivery_grosze) for o in offers if o.delivery_grosze is not None]
    if known:
        return Grosze(min(known))
    return Grosze(
        rules.locker_delivery_grosze if rules.prefer_locker else rules.courier_delivery_grosze
    )


def is_smart_eligible(lines: Sequence[BasketLine]) -> bool:
    """Smart! covers only offers flagged Smart! — a plain seller offer pays its fee."""
    return all(line.offer.smart is True for line in lines)


def delivery_for(subtotal: int, fee: int, rules: BasketRules, *, smart_eligible: bool) -> int:
    if rules.smart_active and smart_eligible and subtotal >= rules.smart_minimum_grosze:
        return 0
    return fee


def _group_by_seller(candidates: Sequence[Candidate]) -> dict[str, list[Candidate]]:
    grouped: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        grouped.setdefault(candidate.offer.seller_login, []).append(candidate)
    return grouped


def _fee_table(candidates: Sequence[Candidate], rules: BasketRules) -> dict[str, int]:
    grouped = _group_by_seller(candidates)
    return {
        seller: int(seller_delivery_fee([c.offer for c in items], rules))
        for seller, items in grouped.items()
    }


def evaluate(
    selection: Mapping[str, Candidate],
    fee: Mapping[str, int],
    rules: BasketRules,
    *,
    include_penalty: bool = True,
) -> int:
    """Total grosze for one assignment, under the same rules the solver uses."""
    subtotal: dict[str, int] = {}
    smart: dict[str, bool] = {}
    total = 0
    for candidate in selection.values():
        total += int(candidate.line_goods)
        seller = candidate.offer.seller_login
        subtotal[seller] = subtotal.get(seller, 0) + int(candidate.line_goods)
        smart[seller] = smart.get(seller, True) and candidate.offer.smart is True
    for seller, subtotal_grosze in subtotal.items():
        total += delivery_for(subtotal_grosze, fee[seller], rules, smart_eligible=smart[seller])
        if include_penalty:
            total += rules.seller_penalty_grosze
    return total


def brute_force(candidates: Sequence[Candidate], rules: BasketRules) -> int:
    """Exact minimum by enumeration. Test oracle only; exponential by design."""
    items: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        items.setdefault(candidate.item_label, []).append(candidate)
    fee = _fee_table(candidates, rules)
    best: int | None = None
    for combo in itertools.product(*(items[label] for label in sorted(items))):
        selection = {candidate.item_label: candidate for candidate in combo}
        if len({c.offer.seller_login for c in combo}) > rules.sellers_max:
            continue
        total = evaluate(selection, fee, rules)
        best = total if best is None else min(best, total)
    if best is None:
        raise NoCandidates("no assignment respects sellers_max")
    return best


def plan(candidates: Sequence[Candidate], rules: BasketRules) -> BasketPlan:
    """Solve the basket exactly. Raises NoCandidates when the constraints are infeasible."""
    if not candidates:
        raise NoCandidates("no candidates to plan from")
    items: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        items.setdefault(candidate.item_label, []).append(candidate)
    for label, offers in items.items():
        if not offers:
            raise NoCandidates(f"item {label!r} has no candidate offers")

    fee = _fee_table(candidates, rules)
    sellers = sorted({c.offer.seller_login for c in candidates})
    max_subtotal = sum(int(c.line_goods) for c in candidates) + 1

    model = cp_model.CpModel()
    x: dict[tuple[str, str], cp_model.IntVar] = {}
    for label in sorted(items):
        for candidate in items[label]:
            x[(label, candidate.offer.offer_id)] = model.NewBoolVar(
                f"x_{label}_{candidate.offer.offer_id}"
            )
    y = {seller: model.NewBoolVar(f"y_{seller}") for seller in sellers}
    z = {seller: model.NewBoolVar(f"z_{seller}") for seller in sellers}

    for label in sorted(items):
        model.Add(sum(x[(label, c.offer.offer_id)] for c in items[label]) == 1)

    for candidate in candidates:
        pair = (candidate.item_label, candidate.offer.offer_id)
        model.Add(x[pair] <= y[candidate.offer.seller_login])

    subtotals: dict[str, Any] = {}
    for seller in sellers:
        terms = [
            int(c.line_goods) * x[(c.item_label, c.offer.offer_id)]
            for c in candidates
            if c.offer.seller_login == seller
        ]
        subtotals[seller] = sum(terms)
        model.Add(subtotals[seller] <= max_subtotal * y[seller])
        if rules.smart_active:
            model.Add(subtotals[seller] >= rules.smart_minimum_grosze * z[seller])
            model.Add(z[seller] <= y[seller])
            # Free delivery needs every chosen line from this seller to be Smart!.
            for c in candidates:
                if c.offer.seller_login == seller and c.offer.smart is not True:
                    model.Add(z[seller] + x[(c.item_label, c.offer.offer_id)] <= 1)
        else:
            model.Add(z[seller] == 0)
        # A seller with a zero subtotal may not be marked used.
        model.Add(subtotals[seller] >= y[seller])

    model.Add(sum(y.values()) <= rules.sellers_max)

    objective = []
    for candidate in candidates:
        objective.append(
            int(candidate.line_goods) * x[(candidate.item_label, candidate.offer.offer_id)]
        )
    for seller in sellers:
        objective.append(fee[seller] * (y[seller] - z[seller]))
        objective.append(rules.seller_penalty_grosze * y[seller])
    model.Minimize(sum(objective))

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.random_seed = 7
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise NoCandidates(
            "basket constraints are infeasible",
            detail=f"status={solver.StatusName(status)} sellers_max={rules.sellers_max}",
        )

    best_cost = round(solver.ObjectiveValue())

    # Second pass: among all minimum-cost baskets, prefer the higher-scoring one.
    model.Add(sum(objective) <= best_cost)
    # Among equal-cost baskets prefer higher scores, then the earlier candidate
    # (candidates arrive price-ordered), so the output is reproducible.
    score_terms = [
        (int(candidate.score * 1000) + len(candidates) - index)
        * x[(candidate.item_label, candidate.offer.offer_id)]
        for index, candidate in enumerate(candidates)
    ]
    model.Maximize(sum(score_terms))
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        raise NoCandidates("basket cost is fixed but no assignment reproduces it")

    chosen: list[BasketLine] = []
    for label in sorted(items):
        for candidate in items[label]:
            if solver.BooleanValue(x[(label, candidate.offer.offer_id)]):
                chosen.append(
                    BasketLine(
                        item_label=label,
                        offer=candidate.offer,
                        quantity=candidate.quantity,
                        score=candidate.score,
                        goods=candidate.line_goods,
                    )
                )
                break
        else:
            raise NoCandidates(f"solver returned no offer for item {label!r}")

    slices = _slices(chosen, fee, rules)
    items_total = Grosze(sum(int(line.goods) for line in chosen))
    delivery_total = Grosze(sum(int(s.delivery) for s in slices))
    grand_total = Grosze(items_total + delivery_total)
    baseline = _baseline(candidates, fee, rules)
    return BasketPlan(
        slices=tuple(slices),
        items_total=items_total,
        delivery_total=delivery_total,
        grand_total=grand_total,
        baseline_total=Grosze(baseline),
        savings=Grosze(max(0, baseline - int(grand_total))),
        sellers_used=len(slices),
        solver=solver.StatusName(status),
    )


def _slices(
    chosen: Sequence[BasketLine], fee: Mapping[str, int], rules: BasketRules
) -> list[SellerSlice]:
    grouped: dict[str, list[BasketLine]] = {}
    for line in chosen:
        grouped.setdefault(line.offer.seller_login, []).append(line)
    slices: list[SellerSlice] = []
    for seller in sorted(grouped):
        lines = tuple(sorted(grouped[seller], key=lambda line: line.item_label))
        subtotal = sum(int(line.goods) for line in lines)
        eligible = is_smart_eligible(lines)
        delivery = delivery_for(subtotal, fee[seller], rules, smart_eligible=eligible)
        slices.append(
            SellerSlice(
                seller=seller,
                lines=lines,
                subtotal=Grosze(subtotal),
                delivery=Grosze(delivery),
                free_delivery=delivery == 0
                and rules.smart_active
                and eligible
                and subtotal >= rules.smart_minimum_grosze,
            )
        )
    return slices


def _baseline(candidates: Sequence[Candidate], fee: Mapping[str, int], rules: BasketRules) -> int:
    """Naive baseline: cheapest offer per item ignoring seller consolidation."""
    items: dict[str, list[Candidate]] = {}
    for candidate in candidates:
        items.setdefault(candidate.item_label, []).append(candidate)
    selection: dict[str, Candidate] = {}
    for label, offers in items.items():
        selection[label] = min(offers, key=lambda c: (int(c.offer.price), c.offer.offer_id))
    return evaluate(selection, fee, rules, include_penalty=False)
