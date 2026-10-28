from __future__ import annotations

from pathlib import Path

import pytest

from allegro_shopping.config import Rules
from allegro_shopping.errors import BotWallError, FetchFailure
from allegro_shopping.session import CONSENT_SELECTORS, PlaywrightPageSource

FIXTURES = Path(__file__).parent / "fixtures" / "allegro"

BLOCKED = (FIXTURES / "blocked-datadome.html").read_text(encoding="utf-8")
LISTING = (FIXTURES / "listing-wago.html").read_text(encoding="utf-8")


class FakeElement:
    def __init__(self, page: FakePage, selector: str) -> None:
        self.page = page
        self.selector = selector

    def click(self) -> None:
        self.page.clicks.append(self.selector)
        self.page.consent_visible = False


class FakePage:
    def __init__(
        self, pages: list[str], *, title: str = "allegro.pl", consent: bool = False
    ) -> None:
        self.pages = pages
        self.current = ""
        self.title_value = title
        self.consent_visible = consent
        self.clicks: list[str] = []
        self.navigations: list[str] = []
        self.waits: list[int] = []
        self.ready_ok = True

    def goto(self, url: str, timeout: int, wait_until: str) -> None:
        del timeout, wait_until
        self.navigations.append(url)
        self.current = self.pages.pop(0) if self.pages else self.current

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)

    def content(self) -> str:
        return self.current

    def title(self) -> str:
        return self.title_value

    def query_selector(self, selector: str) -> FakeElement | None:
        if self.consent_visible and selector in CONSENT_SELECTORS:
            return FakeElement(self, selector)
        return None

    def wait_for_selector(self, selector: str, timeout: int) -> None:
        del selector, timeout
        if not self.ready_ok:
            raise RuntimeError("timeout")


def source(rules: Rules, tmp_path: Path) -> PlaywrightPageSource:
    from allegro_shopping.session import BrowserSettings

    class Store:
        def __getattr__(self, name: str):
            raise AssertionError(f"store should not be touched in session unit tests: {name}")

    return PlaywrightPageSource(rules, BrowserSettings(profile=tmp_path / "profile"), Store())  # type: ignore[arg-type]


def test_fetch_returns_markup_after_ready_selector(rules: Rules, tmp_path: Path) -> None:
    instance = source(rules, tmp_path)
    page = FakePage([LISTING])
    instance._pages = page
    assert instance.fetch("https://allegro.pl/listing?string=x", "article") == LISTING
    assert page.navigations == ["https://allegro.pl/listing?string=x"]


def test_consent_is_dismissed_once(rules: Rules, tmp_path: Path) -> None:
    instance = source(rules, tmp_path)
    page = FakePage([LISTING], consent=True)
    instance._pages = page
    instance.fetch("https://allegro.pl/listing?string=x", "article")
    assert page.clicks == [CONSENT_SELECTORS[0]]


def test_wall_is_reloaded_then_gives_up(rules: Rules, tmp_path: Path) -> None:
    instance = source(rules, tmp_path)
    page = FakePage([BLOCKED, BLOCKED], title="allegro.pl")
    instance._pages = page
    with pytest.raises(BotWallError, match="bot-wall"):
        instance.fetch("https://allegro.pl/listing?string=x", "article")
    assert len(page.navigations) == 2


def test_wall_reload_that_clears_returns_markup(rules: Rules, tmp_path: Path) -> None:
    instance = source(rules, tmp_path)
    page = FakePage([BLOCKED, LISTING], title="allegro.pl")
    instance._pages = page
    assert instance.fetch("https://allegro.pl/listing?string=x", "article") == LISTING


def test_missing_ready_selector_is_a_fetch_failure(rules: Rules, tmp_path: Path) -> None:
    instance = source(rules, tmp_path)
    page = FakePage([LISTING])
    page.ready_ok = False
    instance._pages = page
    with pytest.raises(FetchFailure, match="ready selector"):
        instance.fetch("https://allegro.pl/listing?string=x", "article")


def test_fetch_outside_session_is_a_programming_error(rules: Rules, tmp_path: Path) -> None:
    with pytest.raises(RuntimeError, match="outside"):
        source(rules, tmp_path).fetch("https://allegro.pl/", "body")
