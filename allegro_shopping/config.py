"""Strict config: every key declared, every value validated, nothing coalesced.

Two documents exist:

- *rules* (algorithm and policy): freshness, budgets, scoring, basket, site.
- *request* (what the user wants bought): a list of items with hard limits.

Both are TOML. Unknown keys, missing keys, wrong types and out-of-range values
raise ConfigError. A default is a value written in the shipped rules file, not
an implicit one in code.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .errors import ConfigError
from .money import Grosze


def _table(doc: dict[str, Any], name: str, *, required: bool = True) -> dict[str, Any]:
    value = doc.get(name)
    if value is None:
        if required:
            raise ConfigError(f"missing table [{name}]")
        return {}
    if not isinstance(value, dict):
        raise ConfigError(f"[{name}] must be a table")
    return value


def _expect(
    table: dict[str, Any], where: str, required: tuple[str, ...], optional: tuple[str, ...] = ()
) -> None:
    missing = [k for k in required if k not in table]
    if missing:
        raise ConfigError(f"{where}: missing keys {missing}")
    unknown = [k for k in table if k not in required and k not in optional]
    if unknown:
        raise ConfigError(f"{where}: unknown keys {unknown}")


def _int(table: dict[str, Any], key: str, where: str, *, minimum: int = 0) -> int:
    value = table[key]
    if not isinstance(value, int) or isinstance(value, bool):
        raise ConfigError(f"{where}.{key} must be an integer")
    if value < minimum:
        raise ConfigError(f"{where}.{key} must be >= {minimum}")
    return value


def _number(table: dict[str, Any], key: str, where: str) -> float:
    value = table[key]
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ConfigError(f"{where}.{key} must be a number")
    return float(value)


def _bool(table: dict[str, Any], key: str, where: str) -> bool:
    value = table[key]
    if not isinstance(value, bool):
        raise ConfigError(f"{where}.{key} must be a boolean")
    return value


def _str(table: dict[str, Any], key: str, where: str) -> str:
    value = table[key]
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.{key} must be a non-empty string")
    return value


@dataclass(frozen=True)
class Freshness:
    """TTL per kind of observation, in hours."""

    search_hours: int
    offer_hours: int
    detail_hours: int
    seller_hours: int

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> Freshness:
        where = "freshness"
        _expect(doc, where, ("search_hours", "offer_hours", "detail_hours", "seller_hours"))
        return cls(
            search_hours=_int(doc, "search_hours", where, minimum=1),
            offer_hours=_int(doc, "offer_hours", where, minimum=1),
            detail_hours=_int(doc, "detail_hours", where, minimum=1),
            seller_hours=_int(doc, "seller_hours", where, minimum=1),
        )


@dataclass(frozen=True)
class Budgets:
    max_search_pages: int
    max_offers: int
    max_external_lookups: int
    max_llm_calls: int
    max_wall_seconds: int

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> Budgets:
        where = "budgets"
        keys = (
            "max_search_pages",
            "max_offers",
            "max_external_lookups",
            "max_llm_calls",
            "max_wall_seconds",
        )
        _expect(doc, where, keys)
        return cls(
            max_search_pages=_int(doc, "max_search_pages", where, minimum=1),
            max_offers=_int(doc, "max_offers", where, minimum=1),
            max_external_lookups=_int(doc, "max_external_lookups", where, minimum=0),
            max_llm_calls=_int(doc, "max_llm_calls", where, minimum=0),
            max_wall_seconds=_int(doc, "max_wall_seconds", where, minimum=1),
        )


SCORE_TERMS = ("price", "landed", "seller", "rating", "specs", "delivery")


@dataclass(frozen=True)
class ScoreBounds:
    price_floor_grosze: int
    delivery_slow_hours: int
    delivery_baseline_hours: int
    rating_prior: float
    rating_prior_weight: int
    missing_term_value: float

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> ScoreBounds:
        where = "score.bounds"
        keys = (
            "price_floor_grosze",
            "delivery_slow_hours",
            "delivery_baseline_hours",
            "rating_prior",
            "rating_prior_weight",
            "missing_term_value",
        )
        _expect(doc, where, keys)
        bounds = cls(
            price_floor_grosze=_int(doc, "price_floor_grosze", where, minimum=0),
            delivery_slow_hours=_int(doc, "delivery_slow_hours", where, minimum=1),
            delivery_baseline_hours=_int(doc, "delivery_baseline_hours", where, minimum=1),
            rating_prior=_number(doc, "rating_prior", where),
            rating_prior_weight=_int(doc, "rating_prior_weight", where, minimum=0),
            missing_term_value=_number(doc, "missing_term_value", where),
        )
        if bounds.delivery_slow_hours <= bounds.delivery_baseline_hours:
            raise ConfigError(f"{where}: delivery_slow_hours must exceed delivery_baseline_hours")
        if not 1.0 <= bounds.rating_prior <= 5.0:
            raise ConfigError(f"{where}: rating_prior must be within 1..5")
        if not 0.0 <= bounds.missing_term_value <= 1.0:
            raise ConfigError(f"{where}: missing_term_value must be within 0..1")
        return bounds


@dataclass(frozen=True)
class ScoreRules:
    weights: dict[str, float]
    bounds: ScoreBounds
    version: int

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> ScoreRules:
        where = "score"
        _expect(doc, where, ("version", "weights", "bounds"))
        weights_doc = _table(doc, "weights")
        _expect(weights_doc, f"{where}.weights", SCORE_TERMS)
        weights = {term: _number(weights_doc, term, f"{where}.weights") for term in SCORE_TERMS}
        if any(w < 0 for w in weights.values()):
            raise ConfigError(f"{where}.weights must be non-negative")
        total = sum(weights.values())
        if abs(total - 100.0) > 0.001:
            raise ConfigError(f"{where}.weights must sum to 100, got {total}")
        return cls(
            weights=weights,
            bounds=ScoreBounds.from_toml(_table(doc, "bounds")),
            version=_int(doc, "version", where, minimum=1),
        )


@dataclass(frozen=True)
class BasketRules:
    sellers_max: int
    shortlist: int
    smart_active: bool
    smart_minimum_grosze: int
    locker_delivery_grosze: int
    courier_delivery_grosze: int
    prefer_locker: bool
    seller_penalty_grosze: int

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> BasketRules:
        where = "basket"
        keys = (
            "sellers_max",
            "shortlist",
            "smart_active",
            "smart_minimum_grosze",
            "locker_delivery_grosze",
            "courier_delivery_grosze",
            "prefer_locker",
            "seller_penalty_grosze",
        )
        _expect(doc, where, keys)
        rules = cls(
            sellers_max=_int(doc, "sellers_max", where, minimum=1),
            shortlist=_int(doc, "shortlist", where, minimum=1),
            smart_active=_bool(doc, "smart_active", where),
            smart_minimum_grosze=_int(doc, "smart_minimum_grosze", where, minimum=0),
            locker_delivery_grosze=_int(doc, "locker_delivery_grosze", where, minimum=0),
            courier_delivery_grosze=_int(doc, "courier_delivery_grosze", where, minimum=0),
            prefer_locker=_bool(doc, "prefer_locker", where),
            seller_penalty_grosze=_int(doc, "seller_penalty_grosze", where, minimum=0),
        )
        if rules.smart_active and rules.smart_minimum_grosze <= 0:
            raise ConfigError(f"{where}: smart_minimum_grosze must be positive when smart_active")
        return rules


@dataclass(frozen=True)
class SiteRules:
    base_url: str
    listing_ready_selector: str
    offer_ready_selector: str
    locale: str
    timezone: str
    max_price_grosze: int

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> SiteRules:
        where = "site"
        keys = (
            "base_url",
            "listing_ready_selector",
            "offer_ready_selector",
            "locale",
            "timezone",
            "max_price_grosze",
        )
        _expect(doc, where, keys)
        base_url = _str(doc, "base_url", where)
        if base_url != "https://allegro.pl":
            raise ConfigError(f"{where}.base_url must be https://allegro.pl, got {base_url}")
        return cls(
            base_url=base_url,
            listing_ready_selector=_str(doc, "listing_ready_selector", where),
            offer_ready_selector=_str(doc, "offer_ready_selector", where),
            locale=_str(doc, "locale", where),
            timezone=_str(doc, "timezone", where),
            max_price_grosze=_int(doc, "max_price_grosze", where, minimum=1),
        )


@dataclass(frozen=True)
class Rules:
    version: int
    freshness: Freshness
    budgets: Budgets
    score: ScoreRules
    basket: BasketRules
    site: SiteRules

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> Rules:
        _expect(doc, "rules", ("meta", "freshness", "budgets", "score", "basket", "site"))
        meta = _table(doc, "meta")
        _expect(meta, "meta", ("version", "updated"))
        return cls(
            version=_int(meta, "version", "meta", minimum=1),
            freshness=Freshness.from_toml(_table(doc, "freshness")),
            budgets=Budgets.from_toml(_table(doc, "budgets")),
            score=ScoreRules.from_toml(_table(doc, "score")),
            basket=BasketRules.from_toml(_table(doc, "basket")),
            site=SiteRules.from_toml(_table(doc, "site")),
        )


def load_rules(path: Path) -> Rules:
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"rules file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"rules file is not valid TOML: {path}: {e}") from e
    return Rules.from_toml(doc)


@dataclass(frozen=True)
class Item:
    """One thing to buy. Limits are hard gates, not preferences."""

    label: str
    query: str
    quantity: int
    max_price_grosze: Grosze
    allow_used: bool
    required_specs: dict[str, str] = field(default_factory=dict)
    min_rating: float | None = None

    @classmethod
    def from_toml(cls, doc: dict[str, Any], where: str) -> Item:
        _expect(
            doc,
            where,
            ("label", "query", "quantity", "max_price_grosze", "allow_used"),
            ("required_specs", "min_rating"),
        )
        required_specs = doc.get("required_specs", {})
        if not isinstance(required_specs, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in required_specs.items()
        ):
            raise ConfigError(f"{where}.required_specs must be a table of strings")
        min_rating_raw = doc.get("min_rating")
        min_rating: float | None
        if min_rating_raw is None:
            min_rating = None
        else:
            min_rating = _number(doc, "min_rating", where)
            if not 1.0 <= min_rating <= 5.0:
                raise ConfigError(f"{where}.min_rating must be within 1..5")
        quantity = _int(doc, "quantity", where, minimum=1)
        allow_used = _bool(doc, "allow_used", where)
        return cls(
            label=_str(doc, "label", where),
            query=_str(doc, "query", where),
            quantity=quantity,
            max_price_grosze=Grosze(_int(doc, "max_price_grosze", where, minimum=1)),
            allow_used=allow_used,
            required_specs=dict(required_specs),
            min_rating=min_rating,
        )


@dataclass(frozen=True)
class Request:
    name: str
    items: tuple[Item, ...]
    notes: str | None = None

    @classmethod
    def from_toml(cls, doc: dict[str, Any]) -> Request:
        _expect(doc, "request", ("meta", "items"))
        meta = _table(doc, "meta")
        _expect(meta, "meta", ("name",), ("notes",))
        raw_items = doc["items"]
        if not isinstance(raw_items, list) or not raw_items:
            raise ConfigError("request.items must be a non-empty array of tables")
        items = tuple(Item.from_toml(item, f"items[{i}]") for i, item in enumerate(raw_items))
        labels = [item.label for item in items]
        if len(set(labels)) != len(labels):
            raise ConfigError(f"request item labels must be unique, got {labels}")
        notes = meta.get("notes")
        if notes is not None and not isinstance(notes, str):
            raise ConfigError("meta.notes must be a string")
        return cls(name=_str(meta, "name", "meta"), items=items, notes=notes)


def load_request(path: Path) -> Request:
    try:
        doc = tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise ConfigError(f"request file not found: {path}") from e
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"request file is not valid TOML: {path}: {e}") from e
    return Request.from_toml(doc)
