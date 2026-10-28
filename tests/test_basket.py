from __future__ import annotations

from dataclasses import replace

import pytest
from conftest import make_offer
from hypothesis import given, settings
from hypothesis import strategies as st

from allegro_shopping.basket import Candidate, brute_force, plan
from allegro_shopping.config import BasketRules, Rules, load_rules
from allegro_shopping.errors import NoCandidates
from allegro_shopping.rules import default_rules_path


def candidate(
    item: str,
    offer_id: str,
    price: int,
    seller: str,
    *,
    quantity: int = 1,
    score: float = 50.0,
    delivery_grosze: int | None = None,
) -> Candidate:
    return Candidate(
        item_label=item,
        offer=make_offer(
            offer_id,
            price=price,
            seller=seller,
            delivery_grosze=delivery_grosze,
            specs={"Model": "x"},
            rating_avg=4.5,
            rating_count=50,
        ),
        score=score,
        quantity=quantity,
    )


def rules_with(rules: Rules, **overrides: object) -> BasketRules:
    return replace(rules.basket, **overrides)


def test_free_delivery_at_threshold(rules: Rules) -> None:
    basket_rules = rules_with(rules, sellers_max=1)
    under = plan([candidate("a", "1000001", 4000, "s1")], basket_rules)
    assert under.delivery_total == basket_rules.locker_delivery_grosze

    over = plan([candidate("a", "1000001", 5000, "s1")], basket_rules)
    assert over.delivery_total == 0
    assert over.slices[0].free_delivery is True


def test_smart_disabled_always_charges(rules: Rules) -> None:
    basket_rules = rules_with(rules, smart_active=False, sellers_max=1)
    basket = plan([candidate("a", "1000001", 9000, "s1")], basket_rules)
    assert basket.delivery_total == basket_rules.locker_delivery_grosze


def test_known_offer_delivery_overrides_default(rules: Rules) -> None:
    basket_rules = rules_with(rules, sellers_max=1)
    basket = plan([candidate("a", "1000001", 2000, "s1", delivery_grosze=2499)], basket_rules)
    assert basket.delivery_total == 2499


def test_quantity_multiplies_goods(rules: Rules) -> None:
    basket = plan(
        [candidate("a", "1000001", 1500, "s1", quantity=3)], rules_with(rules, sellers_max=1)
    )
    assert basket.items_total == 4500


def test_consolidation_beats_two_sellers(rules: Rules) -> None:
    basket_rules = rules_with(rules, sellers_max=3)
    candidates = [
        candidate("a", "1000001", 3000, "s1"),
        candidate("b", "1000002", 3000, "s2"),
        candidate("a", "1000003", 3400, "s2"),
    ]
    basket = plan(candidates, basket_rules)
    assert basket.sellers_used == 1
    assert basket.slices[0].seller == "s2"
    assert basket.grand_total == 3400 + 3000  # one seller, above threshold, free delivery


def test_cheaper_split_beats_forced_consolidation(rules: Rules) -> None:
    basket_rules = rules_with(rules, sellers_max=2)
    candidates = [
        candidate("a", "1000001", 1500, "s1"),
        candidate("b", "1000002", 1000, "s1"),
        candidate("a", "1000003", 100, "s2"),
    ]
    # Consolidating on s1: 2500 + one fee. Splitting: 1100 + two fees, which is
    # 101 grosze cheaper — the item saving beats the extra parcel.
    basket = plan(candidates, basket_rules)
    assert basket.items_total == 1100
    assert basket.sellers_used == 2
    assert basket.grand_total == 1100 + 2 * basket_rules.locker_delivery_grosze


def test_sellers_max_infeasible_is_an_error(rules: Rules) -> None:
    with pytest.raises(NoCandidates, match="infeasible"):
        plan(
            [candidate("a", "1000001", 1000, "s1"), candidate("b", "1000002", 1000, "s2")],
            rules_with(rules, sellers_max=1),
        )


def test_empty_candidates_is_an_error(rules: Rules) -> None:
    with pytest.raises(NoCandidates):
        plan([], rules.basket)


def test_baseline_is_never_better_than_the_plan(rules: Rules) -> None:
    candidates = [
        candidate("a", "1000001", 3000, "s1"),
        candidate("b", "1000002", 3000, "s2"),
        candidate("a", "1000003", 3400, "s2"),
    ]
    basket = plan(candidates, rules_with(rules, sellers_max=3))
    assert basket.baseline_total >= basket.grand_total


@settings(max_examples=60, deadline=None)
@given(
    st.lists(
        st.tuples(
            st.sampled_from(["a", "b", "c"]),
            st.integers(min_value=100, max_value=9000),
            st.sampled_from(["s1", "s2", "s3"]),
            st.integers(min_value=1, max_value=2),
        ),
        min_size=1,
        max_size=7,
        unique_by=lambda t: (t[0], t[2], t[1]),
    )
)
def test_solver_matches_brute_force(rows: list) -> None:
    rules = load_rules(default_rules_path())
    seen: set[str] = set()
    candidates: list[Candidate] = []
    for index, (item, price, seller, quantity) in enumerate(rows):
        offer_id = f"{2000000 + index}"
        if (item, offer_id) in seen:
            continue
        seen.add((item, offer_id))
        candidates.append(candidate(item, offer_id, price, seller, quantity=quantity))
    labels = {c.item_label for c in candidates}
    if len(labels) < 1:
        return
    basket_rules = rules_with(rules, sellers_max=3)
    try:
        expected = brute_force(candidates, basket_rules)
    except NoCandidates:
        with pytest.raises(NoCandidates):
            plan(candidates, basket_rules)
        return
    basket = plan(candidates, basket_rules)
    actual = int(basket.grand_total) + basket_rules.seller_penalty_grosze * basket.sellers_used
    assert actual == expected
