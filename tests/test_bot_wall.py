from __future__ import annotations

from pathlib import Path

from web_agent.fetch import detect_bot_wall

FIXTURES = Path(__file__).parent / "fixtures" / "allegro"


def test_datadome_interstitial_is_detected() -> None:
    markup = (FIXTURES / "blocked-datadome.html").read_text(encoding="utf-8")
    assert detect_bot_wall(markup, "allegro.pl") is True


def test_normal_listing_is_not_a_wall() -> None:
    markup = (FIXTURES / "listing-wago.html").read_text(encoding="utf-8")
    assert detect_bot_wall(markup, "wago 221 - allegro.pl") is False
