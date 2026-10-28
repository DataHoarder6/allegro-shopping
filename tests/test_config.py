from __future__ import annotations

from pathlib import Path

import pytest

from allegro_shopping.config import load_request, load_rules
from allegro_shopping.errors import ConfigError
from allegro_shopping.money import Grosze
from allegro_shopping.rules import default_rules_path

REQUEST = """
[meta]
name = "Wago restock"
notes = "for the junction box rebuild"

[[items]]
label = "wago-3"
query = "wago 221-413"
quantity = 2
max_price_grosze = 6000
allow_used = false
required_specs = { Model = "221-413" }
min_rating = 4.0

[[items]]
label = "wago-5"
query = "wago 221-415"
quantity = 1
max_price_grosze = 9000
allow_used = true
"""


def test_shipped_rules_load() -> None:
    rules = load_rules(default_rules_path())
    assert rules.score.weights == {
        "price": 30,
        "landed": 25,
        "seller": 15,
        "rating": 15,
        "specs": 10,
        "delivery": 5,
    }
    assert sum(rules.score.weights.values()) == 100
    assert rules.basket.smart_minimum_grosze == 4990


def test_unknown_key_is_a_hard_error(tmp_path: Path) -> None:
    text = (
        default_rules_path()
        .read_text(encoding="utf-8")
        .replace("max_search_pages = 3", "max_search_pages = 3\nmax_spiders = 99")
    )
    path = tmp_path / "rules.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="unknown keys"):
        load_rules(path)


def test_missing_key_is_a_hard_error(tmp_path: Path) -> None:
    text = default_rules_path().read_text(encoding="utf-8")
    text = "\n".join(line for line in text.splitlines() if not line.startswith("seller_hours"))
    text += "\n"
    path = tmp_path / "rules.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="missing keys"):
        load_rules(path)


def test_weights_must_sum_to_100(tmp_path: Path) -> None:
    text = default_rules_path().read_text(encoding="utf-8").replace("price = 30", "price = 40")
    path = tmp_path / "rules.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(ConfigError, match="sum to 100"):
        load_rules(path)


def test_request_parses_strictly(tmp_path: Path) -> None:
    path = tmp_path / "request.toml"
    path.write_text(REQUEST, encoding="utf-8")
    request = load_request(path)
    assert request.name == "Wago restock"
    assert [item.label for item in request.items] == ["wago-3", "wago-5"]
    first = request.items[0]
    assert first.quantity == 2
    assert first.max_price_grosze == Grosze(6000)
    assert first.allow_used is False
    assert first.required_specs == {"Model": "221-413"}
    assert request.items[1].allow_used is True


def test_request_requires_allow_used(tmp_path: Path) -> None:
    path = tmp_path / "request.toml"
    path.write_text(REQUEST.replace("allow_used = true\n", ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="allow_used"):
        load_request(path)


def test_request_rejects_duplicate_labels(tmp_path: Path) -> None:
    path = tmp_path / "request.toml"
    path.write_text(REQUEST.replace('label = "wago-5"', 'label = "wago-3"'), encoding="utf-8")
    with pytest.raises(ConfigError, match="unique"):
        load_request(path)


def _mutated(tmp_path: Path, old: str, new: str) -> Path:
    text = default_rules_path().read_text(encoding="utf-8").replace(old, new)
    path = tmp_path / "rules.toml"
    path.write_text(text, encoding="utf-8")
    return path


@pytest.mark.parametrize(
    ("old", "new", "match"),
    [
        ("max_search_pages = 3", "max_search_pages = -1", ">= 1"),
        ("max_search_pages = 3", 'max_search_pages = "3"', "must be an integer"),
        ("max_search_pages = 3", "max_search_pages = true", "must be an integer"),
        ("smart_active = true", 'smart_active = "yes"', "must be a boolean"),
        ("price = 30", "price = -30", "non-negative"),
        ("delivery_baseline_hours = 24", "delivery_baseline_hours = 200", "must exceed"),
        ("rating_prior = 4.2", "rating_prior = 9.0", "within 1..5"),
        ("missing_term_value = 0.5", "missing_term_value = 2.0", "within 0..1"),
        ('base_url = "https://allegro.pl"', 'base_url = "https://allegro.cz"', "must be"),
        ("version = 1", 'version = "one"', "must be an integer"),
    ],
)
def test_rules_reject_bad_values(tmp_path: Path, old: str, new: str, match: str) -> None:
    with pytest.raises(ConfigError, match=match):
        load_rules(_mutated(tmp_path, old, new))


def test_rules_reject_invalid_toml(tmp_path: Path) -> None:
    path = tmp_path / "rules.toml"
    path.write_text("this is not toml", encoding="utf-8")
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_rules(path)


def test_rules_reject_missing_file(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        load_rules(tmp_path / "absent.toml")


def test_request_rejects_bad_notes_and_rating(tmp_path: Path) -> None:
    path = tmp_path / "request.toml"
    path.write_text(
        REQUEST.replace('notes = "for the junction box rebuild"', "notes = 5"), encoding="utf-8"
    )
    with pytest.raises(ConfigError, match="notes"):
        load_request(path)

    path.write_text(REQUEST.replace("min_rating = 4.0", "min_rating = 7.0"), encoding="utf-8")
    with pytest.raises(ConfigError, match="min_rating"):
        load_request(path)


def test_request_rejects_empty_items(tmp_path: Path) -> None:
    path = tmp_path / "request.toml"
    path.write_text('items = []\n\n[meta]\nname = "x"\n', encoding="utf-8")
    with pytest.raises(ConfigError, match="non-empty"):
        load_request(path)


def test_resolve_rules_prefers_explicit_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from allegro_shopping.rules import resolve_rules

    monkeypatch.setenv("ALLEGRO_SHOP_RULES", str(tmp_path / "env.toml"))
    rules = resolve_rules(str(default_rules_path()))
    assert rules.version == 1
