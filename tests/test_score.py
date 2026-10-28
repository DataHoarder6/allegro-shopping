from __future__ import annotations

import pytest
from conftest import make_item, make_offer, make_seller

from allegro_shopping.config import Rules
from allegro_shopping.score import ScoreInput, ScoreResult, score_offer, shrunk_rating, spec_match


def _score(rules: Rules, item, offer, seller=None, delivery_hours=None) -> ScoreResult:
    return score_offer(
        item,
        ScoreInput(
            offer=offer,
            seller=seller or make_seller(),
            delivery_hours=delivery_hours,
            quantity=item.quantity,
        ),
        rules.score,
    )


def test_eligible_offer_scores_within_range(rules: Rules) -> None:
    result = _score(rules, make_item(), make_offer())
    assert result.eligible
    assert 0 <= result.total <= 100
    assert result.score_version == rules.score.version
    assert result.gate_failures == ()


def test_cheaper_offer_scores_higher_all_else_equal(rules: Rules) -> None:
    cheap = _score(rules, make_item(), make_offer(price=4000))
    dear = _score(rules, make_item(), make_offer(price=9000))
    assert cheap.total > dear.total


def test_price_above_cap_is_gated_not_penalised(rules: Rules) -> None:
    result = _score(rules, make_item(max_price_grosze=5000), make_offer(price=5001))
    assert result.eligible is False
    assert any("above cap" in failure for failure in result.gate_failures)


def test_unknown_condition_is_gated(rules: Rules) -> None:
    result = _score(rules, make_item(), make_offer(condition=None))
    assert result.eligible is False
    assert any("condition unknown" in failure for failure in result.gate_failures)


def test_used_offer_rejected_unless_allowed(rules: Rules) -> None:
    used = make_offer(condition="Używany")
    assert _score(rules, make_item(), used).eligible is False
    assert _score(rules, make_item(allow_used=True), used).eligible is True


def test_missing_rating_lowers_confidence_not_score_to_zero(rules: Rules) -> None:
    known = _score(rules, make_item(), make_offer(rating_avg=4.8, rating_count=112))
    unknown = _score(rules, make_item(), make_offer(rating_avg=None, rating_count=None))
    assert unknown.eligible
    assert unknown.confidence < known.confidence
    assert unknown.values["rating"] is None
    assert unknown.terms["rating"] == pytest.approx(
        rules.score.weights["rating"] * rules.score.bounds.missing_term_value
    )


def test_missing_specs_fail_a_required_spec(rules: Rules) -> None:
    item = make_item(required_specs={"Model": "221-413"})
    result = _score(rules, item, make_offer(specs={}))
    assert result.eligible is False
    assert any("spec" in failure for failure in result.gate_failures)


def test_spec_match_is_substring_and_case_insensitive() -> None:
    offer = make_offer(specs={"Model": "WAGO 221-413 100szt"})
    assert spec_match(offer, {"model": "221-413"})[0] == 1.0
    assert spec_match(offer, {"Model": "221-415"})[0] == 0.0
    assert spec_match(make_offer(specs={}), {"Model": "x"})[0] is None


def test_rating_shrinkage_prefers_evidence(rules: Rules) -> None:
    one_review = shrunk_rating(5.0, 1, rules.score)
    many_reviews = shrunk_rating(4.8, 500, rules.score)
    assert one_review is not None and many_reviews is not None
    assert one_review < many_reviews


def test_delivery_unknown_is_not_zero(rules: Rules) -> None:
    result = _score(rules, make_item(), make_offer(), delivery_hours=None)
    assert result.values["delivery"] is None
    assert result.terms["delivery"] > 0


def test_delivery_speed_is_monotonic(rules: Rules) -> None:
    fast = _score(rules, make_item(), make_offer(), delivery_hours=24)
    slow = _score(rules, make_item(), make_offer(), delivery_hours=160)
    assert fast.terms["delivery"] > slow.terms["delivery"]


def test_explain_names_terms_and_version(rules: Rules) -> None:
    text = _score(rules, make_item(), make_offer()).explain()
    assert "price" in text
    assert f"v{rules.score.version}" in text
    assert "weakest term" in text
