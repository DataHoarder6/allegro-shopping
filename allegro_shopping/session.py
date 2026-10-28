"""Browser session: the only code that touches Network.

Everything Allegro-specific about *driving* the site lives here: the pl-PL
posture, the cookie-consent click, the DataDome interstitial (one reload, then
hand off to a human). Everything about *reading* lives in `parse.py`.

No stealth, no proxies, no fingerprint games: the session is the user's own
logged-in Chrome profile at human pace. A challenge is a stop, not an obstacle.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from web_agent.fetch import (
    BotWallError as WebBotWallError,
)
from web_agent.fetch import (
    BrowserFetcher,
    BrowserPosture,
    ProfileBusyError,
    detect_bot_wall,
)
from web_agent.store import Store

from .config import Rules
from .errors import BotWallError, FetchFailure

CONSENT_SELECTORS = (
    '[data-testid="accept_home_view_action"]',
    'button:has-text("Zgadzam się")',
)
WALL_RELOAD_PAUSE_SECONDS = 6.0


class PageSource(Protocol):
    """The one method the client needs from a browser. Faked in tests."""

    def fetch(self, url: str, ready_selector: str) -> str: ...


@dataclass(frozen=True)
class BrowserSettings:
    profile: Path
    headless: bool = False
    wall_reloads: int = 1

    def __post_init__(self) -> None:
        object.__setattr__(self, "profile", Path(self.profile))

    @classmethod
    def for_rules(cls, rules: Rules, profile: Path | None = None) -> BrowserSettings:
        del rules  # posture comes from rules.site, not from settings
        return cls(profile=profile or default_profile())


def default_profile() -> Path:
    """The same persistent profile web-agent uses: one human, one Chrome."""
    return Path.home() / ".config" / "web-agent" / "chrome-profile"


class PlaywrightPageSource:
    """PageSource over web-agent's BrowserFetcher.

    Owns one session for the whole run: launching Chrome per page would be both
    slower and more suspicious than a single human-paced tab.
    """

    def __init__(self, rules: Rules, settings: BrowserSettings, store: Store) -> None:
        self.rules = rules
        self.settings = settings
        posture = BrowserPosture(locale=rules.site.locale, timezone_id=rules.site.timezone)
        self.fetcher = BrowserFetcher(
            store,
            profile=settings.profile,
            posture=posture,
            headless=settings.headless,
        )
        self._session: object | None = None
        self._pages: object | None = None

    @contextmanager
    def open(self) -> Iterator[PlaywrightPageSource]:
        try:
            with self.fetcher.session() as page_session:
                self._session = page_session
                self._pages = page_session.page
                yield self
        except ProfileBusyError as e:
            raise FetchFailure(
                f"Chrome profile is busy: {self.settings.profile}",
                detail="close the interactive Chrome window using this profile, then retry",
            ) from e
        finally:
            self._session = None
            self._pages = None

    def fetch(self, url: str, ready_selector: str) -> str:
        if self._pages is None:
            raise RuntimeError("fetch() outside an open() session")
        page = self._pages
        attempts = 1 + self.settings.wall_reloads
        last_markup = ""
        for attempt in range(attempts):
            try:
                page.goto(url, timeout=60000, wait_until="domcontentloaded")  # type: ignore[attr-defined]
            except Exception as e:
                raise FetchFailure(f"navigation failed: {url}: {e}") from e
            page.wait_for_timeout(2500)  # type: ignore[attr-defined]
            self._dismiss_consent()
            last_markup = page.content()  # type: ignore[attr-defined]
            title = page.title()  # type: ignore[attr-defined]
            if not detect_bot_wall(last_markup, title):
                break
            if attempt + 1 == attempts:
                raise BotWallError(
                    f"bot-wall on {url}",
                    detail="clear the challenge in the visible Chrome window, then re-run",
                )
            time.sleep(WALL_RELOAD_PAUSE_SECONDS)
        try:
            page.wait_for_selector(ready_selector, timeout=30000)  # type: ignore[attr-defined]
        except Exception as e:
            if detect_bot_wall(last_markup, page.title()):  # type: ignore[attr-defined]
                raise BotWallError(f"bot-wall on {url}") from e
            raise FetchFailure(f"ready selector {ready_selector!r} never appeared on {url}") from e
        return str(page.content())  # type: ignore[attr-defined]

    def _dismiss_consent(self) -> None:
        if self._pages is None:
            return
        for selector in CONSENT_SELECTORS:
            try:
                element = self._pages.query_selector(selector)  # type: ignore[attr-defined]
            except Exception:
                continue
            if element is not None:
                element.click()
                self._pages.wait_for_timeout(1500)  # type: ignore[attr-defined]
                return


class StaticPageSource:
    """PageSource over a directory of saved pages. Used by capture replay tests."""

    def __init__(self, mapping: dict[str, str]) -> None:
        self.mapping = mapping

    def fetch(self, url: str, ready_selector: str) -> str:
        del ready_selector
        try:
            return self.mapping[url]
        except KeyError as e:
            raise FetchFailure(f"no fixture for {url}") from e


def wrap_web_bot_wall(error: WebBotWallError) -> BotWallError:
    return BotWallError(str(error))


def clock() -> Callable[[], float]:
    return time.monotonic
