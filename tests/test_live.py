"""Tier 3: the real site, the real profile. Never in CI, never scheduled.

Run manually after clearing any DataDome challenge in the visible window:

    ALLEGRO_SHOP_LIVE=1 uv run pytest -m live -q

Read-only: one listing page. It asserts the parser still finds offers. A wall is
a failure, not a skip — a silent skip would hide the exact condition the test
exists to detect.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from web_agent.store import Store

from allegro_shopping.cache import Cache
from allegro_shopping.client import AllegroClient
from allegro_shopping.rules import resolve_rules
from allegro_shopping.session import BrowserSettings, PlaywrightPageSource

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("ALLEGRO_SHOP_LIVE") != "1",
        reason="set ALLEGRO_SHOP_LIVE=1 to touch allegro.pl",
    ),
]


def test_live_listing_parses(tmp_path: Path) -> None:
    rules = resolve_rules(None)
    store = Store(tmp_path / "live.db")
    settings = BrowserSettings(profile=Path.home() / ".config" / "web-agent" / "chrome-profile")
    pages = PlaywrightPageSource(rules, settings, store)
    client = AllegroClient(pages, Cache(store, rules), rules)
    with pages.open():
        offers, _last_page, _skipped = client.search("wago 221", refresh=True)
    assert offers, "listing parsed to zero offers"
    assert all(offer.price > 0 for offer in offers)
