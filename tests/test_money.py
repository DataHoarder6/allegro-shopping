from __future__ import annotations

import pytest

from allegro_shopping.errors import MoneyError
from allegro_shopping.money import Grosze, format_grosze, parse_grosze, percent_off


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("45,00 zł", 4500),
        ("45.00", 4500),
        ("1 234,56 zł", 123456),
        ("1\u00a0234,56 zł", 123456),
        ("12,73 zł/szt.", 1273),
        ("od 45,00 zł", 4500),
        ("0,99 zł", 99),
        ("139,99 zł", 13999),
        ("2700", 270000),
    ],
)
def test_parse_grosze_accepts_allegro_shapes(text: str, expected: int) -> None:
    assert parse_grosze(text) == Grosze(expected)


@pytest.mark.parametrize("text", ["", "abc", "zł", "45,00 zł 39,00 zł", "12,3,4"])
def test_parse_grosze_rejects_ambiguity_and_noise(text: str) -> None:
    with pytest.raises(MoneyError):
        parse_grosze(text)


def test_parse_grosze_rejects_implausible_bare_integer() -> None:
    with pytest.raises(MoneyError):
        parse_grosze("999999999")


def test_format_grosze_is_allegro_shaped() -> None:
    assert format_grosze(Grosze(123456)) == "1 234,56 zł"
    assert format_grosze(Grosze(99)) == "0,99 zł"
    assert format_grosze(Grosze(0)) == "0,00 zł"
    assert format_grosze(Grosze(-150)) == "-1,50 zł"


def test_percent_off() -> None:
    assert percent_off(Grosze(8499), Grosze(9999)) == 15
    assert percent_off(Grosze(10000), Grosze(10000)) == 0
    assert percent_off(Grosze(11000), Grosze(10000)) is None
    assert percent_off(Grosze(100), Grosze(0)) is None
