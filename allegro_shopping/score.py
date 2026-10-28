"""Ranking: hard gates first, then a gated SMART/MAVT score.

Why not a plain weighted sum: price (PLN), rating (0-5) and delivery (hours)
have no common unit. Each term is therefore mapped to a dimensionless 0..1
partial value before weighting; weights sum to 100 and live in versioned config.

Rules the implementation enforces:
- a gate is not a low score: a gated-out offer is excluded, with a reason;
- unknown input is not zero: it takes `missing_term_value` and lowers confidence;
- every score is explainable term by term, and carries the version that made it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from .config import Item, ScoreRules
from .models import Offer, Seller
from .money import Grosze, format_grosze


@dataclass(frozen=True)
class ScoreInput:
    offer: Offer
    seller: Seller | None
    delivery_hours: float | None
    quantity: int
    # Specs of record: offer claims overlaid with the catalog product page.
    # None means "use the offer's own specs".
    specs: dict[str, str] | None = None

    @property
    def effective_specs(self) -> dict[str, str]:
        return self.specs if self.specs is not None else self.offer.specs


@dataclass(frozen=True)
class ScoreResult:
    total: float
    terms: dict[str, float]
    values: dict[str, float | None]
    spec_evidence: dict[str, str]
    weights: dict[str, float]
    confidence: float
    confidence_badge: str
    worst_term: str
    score_version: int
    eligible: bool
    gate_failures: tuple[str, ...] = field(default_factory=tuple)

    def explain(self) -> str:
        lines = [
            f"score {self.total:.1f}/100 (v{self.score_version}, confidence {self.confidence:.0%})"
        ]
        if self.spec_evidence:
            evidence = ", ".join(f"{k}={v}" for k, v in sorted(self.spec_evidence.items()))
            lines.append(f"  spec evidence: {evidence}")
        for term, weight in sorted(self.weights.items(), key=lambda kv: -kv[1]):
            value = self.values[term]
            shown = "unknown" if value is None else f"{value:.3f}"
            points = self.terms[term]
            lines.append(
                f"  {term:<9} weight {weight:>5.1f}  value {shown:>8}  points {points:>6.2f}"
            )
        lines.append(f"  weakest term: {self.worst_term}")
        if self.gate_failures:
            lines.append("  gates: " + "; ".join(self.gate_failures))
        return "\n".join(lines)


def _clamp(value: float) -> float:
    return max(0.0, min(1.0, value))


def _linear_down(value: float, best: float, worst: float) -> float:
    """1.0 at `best`, 0.0 at `worst`, linear between, clamped outside."""
    if worst == best:
        raise ValueError("best and worst must differ")
    return _clamp((worst - value) / (worst - best))


def shrunk_rating(rating: float | None, count: int | None, rules: ScoreRules) -> float | None:
    """Bayesian shrinkage toward the prior: 1 review must not beat 500."""
    if rating is None:
        return None
    weight = rules.bounds.rating_prior_weight
    reviews = count if count is not None else 0
    prior = rules.bounds.rating_prior
    return (reviews * rating + weight * prior) / (reviews + weight)


def spec_match(
    specs: Mapping[str, str], required: Mapping[str, str], *, title: str = ""
) -> tuple[float | None, dict[str, str]]:
    """Fraction of required specs matched, with the evidence behind each one.

    Evidence is either the parameter table (`specs`) or the offer title. The
    title is a seller claim, not a datasheet, so it is recorded as such — but it
    is real evidence: model numbers live in titles far more reliably than in
    Allegro's parameter table, which is category-shaped, not model-shaped.
    """
    if not required:
        return 1.0, {}
    haystack_title = title.lower()
    matched = 0
    evidence: dict[str, str] = {}
    for key, expected in required.items():
        needle = expected.strip().lower()
        actual = next((v for k, v in specs.items() if k.lower() == key.lower()), None)
        if actual is not None and needle in actual.strip().lower():
            matched += 1
            evidence[key] = "specs"
        elif needle and needle in haystack_title:
            matched += 1
            evidence[key] = "title"
    if not specs and not evidence:
        return None, {}
    return matched / len(required), evidence


def gate_failures(
    item: Item, offer: Offer, seller: Seller | None, specs: Mapping[str, str] | None = None
) -> tuple[str, ...]:
    failures: list[str] = []
    if offer.price > item.max_price_grosze:
        failures.append(
            f"price {format_grosze(offer.price)} above cap {format_grosze(item.max_price_grosze)}"
        )
    if offer.in_stock is False:
        failures.append("out of stock")
    if not item.allow_used:
        if offer.condition_norm is None:
            failures.append("condition unknown (deep dive required)")
        elif offer.condition_norm != "new":
            failures.append(f"condition {offer.condition!r} not allowed")
    if item.min_rating is not None:
        if offer.rating_avg is None:
            failures.append("required minimum rating, rating unknown")
        elif offer.rating_avg < item.min_rating:
            failures.append(f"rating {offer.rating_avg:.2f} below minimum {item.min_rating:.2f}")
    if item.required_specs:
        known = specs if specs is not None else offer.specs
        if not known:
            if all(
                expected.strip().lower() not in offer.title.lower()
                for expected in item.required_specs.values()
            ):
                failures.append("required specs, no spec data on the offer")
        else:
            title = offer.title.lower()
            missing = [
                key
                for key, expected in item.required_specs.items()
                if not any(k.lower() == key.lower() for k in known)
                and expected.strip().lower() not in title
            ]
            if missing:
                failures.append(f"missing specs {missing}")
    if seller is not None and seller.rating is not None and seller.ratings_count == 0:
        failures.append("seller has zero ratings")
    return tuple(failures)


def score_offer(item: Item, candidate: ScoreInput, rules: ScoreRules) -> ScoreResult:
    """Score one offer for one item. Gates are evaluated first and are final."""
    offer = candidate.offer
    effective_specs = candidate.effective_specs
    failures = gate_failures(item, offer, candidate.seller, effective_specs)
    weights = dict(rules.weights)
    if failures:
        return ScoreResult(
            total=0.0,
            terms={term: 0.0 for term in weights},
            values={term: None for term in weights},
            spec_evidence={},
            weights=weights,
            confidence=0.0,
            confidence_badge="low",
            worst_term="gate",
            score_version=rules.version,
            eligible=False,
            gate_failures=failures,
        )

    bounds = rules.bounds
    quantity = candidate.quantity
    price_value = _linear_down(
        float(offer.price), bounds.price_floor_grosze, float(item.max_price_grosze)
    )

    landed_unknown = offer.delivery_grosze is None
    landed_per_unit = float(offer.price)
    if offer.delivery_grosze is not None:
        landed_per_unit += int(offer.delivery_grosze) / quantity
    landed_value = _linear_down(
        landed_per_unit, bounds.price_floor_grosze, float(item.max_price_grosze)
    )

    seller = candidate.seller
    if seller is not None and seller.rating is not None:
        seller_rating = shrunk_rating(seller.rating, seller.ratings_count, rules)
        seller_value = None if seller_rating is None else _clamp(seller_rating / 5.0)
    elif seller is not None and seller.positive_feedback_percent is not None:
        seller_value = _clamp(seller.positive_feedback_percent / 100.0)
    else:
        seller_value = None

    product_rating = shrunk_rating(offer.rating_avg, offer.rating_count, rules)
    rating_value = None if product_rating is None else _clamp(product_rating / 5.0)

    specs_value, spec_evidence = spec_match(
        effective_specs, item.required_specs, title=offer.title
    )

    delivery_value = None
    if candidate.delivery_hours is not None:
        delivery_value = _linear_down(
            candidate.delivery_hours,
            bounds.delivery_baseline_hours,
            bounds.delivery_slow_hours,
        )

    raw_values: dict[str, float | None] = {
        "price": price_value,
        "landed": None if landed_unknown else landed_value,
        "seller": seller_value,
        "rating": rating_value,
        "specs": specs_value,
        "delivery": delivery_value,
    }
    values: dict[str, float] = {
        term: (bounds.missing_term_value if raw_values[term] is None else raw_values[term])  # type: ignore[misc]
        for term in weights
    }
    terms = {term: weights[term] * values[term] for term in weights}
    total = sum(terms.values())

    known_weight = sum(weights[t] for t in weights if raw_values[t] is not None)
    confidence = known_weight / 100.0
    badge = "high" if confidence >= 0.9 else "medium" if confidence >= 0.6 else "low"
    worst_term = min(terms, key=lambda t: terms[t])
    return ScoreResult(
        total=total,
        terms=terms,
        values=raw_values,
        spec_evidence=spec_evidence,
        weights=weights,
        confidence=confidence,
        confidence_badge=badge,
        worst_term=worst_term,
        score_version=rules.version,
        eligible=True,
    )


def rank(
    item: Item, candidates: list[ScoreInput], rules: ScoreRules
) -> list[tuple[ScoreInput, ScoreResult]]:
    """Eligible candidates, best first.

    Ineligible ones are dropped; their gate reasons stay on the ScoreResult.
    """
    scored = [(c, score_offer(item, c, rules)) for c in candidates]
    eligible = [(c, s) for c, s in scored if s.eligible]
    eligible.sort(key=lambda pair: (-pair[1].total, pair[0].offer.price, pair[0].offer.offer_id))
    return eligible


__all__ = [
    "Grosze",
    "ScoreInput",
    "ScoreResult",
    "gate_failures",
    "rank",
    "score_offer",
    "shrunk_rating",
    "spec_match",
]
