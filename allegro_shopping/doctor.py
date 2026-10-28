"""`doctor`: prove the environment can run before spending a single fetch.

Checks are local and fast. They exist because the expensive failure mode of
this tool is discovering at minute four that the Chrome profile is locked or
that the rules file has a typo.
"""

from __future__ import annotations

import contextlib
import importlib
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from web_agent.fetch import BrowserFetcher  # noqa: F401  (import proves the dependency)
from web_agent.store import Store

from .config import load_rules
from .errors import AllegroShoppingError
from .identity import canonical_url

OK = 0
WARN = 1
FAIL = 2


@dataclass(frozen=True)
class Check:
    name: str
    status: str
    detail: str
    severity: int


def _check_rules(path: Path) -> Check:
    try:
        rules = load_rules(path)
    except AllegroShoppingError as e:
        return Check("rules", "fail", f"{e.message} ({path})", FAIL)
    if canonical_url(rules.site.base_url) != "https://allegro.pl":
        return Check("rules", "fail", "site.base_url is not allegro.pl", FAIL)
    return Check("rules", "ok", f"v{rules.version} from {path}", OK)


def _check_store(path: Path) -> Check:
    try:
        with Store(path) as store:
            subjects = len(store.ids("allegro"))
    except Exception as e:
        return Check("hoard", "fail", f"cannot open {path}: {e}", FAIL)
    return Check("hoard", "ok", f"{subjects} allegro subjects in {path}", OK)


def _check_chrome() -> Check:
    found = shutil.which("google-chrome-stable") or shutil.which("google-chrome")
    if not found:
        candidate = Path("/etc/profiles/per-user/admin/bin/google-chrome-stable")
        found = str(candidate) if candidate.exists() else None
    if not found:
        return Check("chrome", "fail", "no google-chrome on PATH (real Chrome is required)", FAIL)
    return Check("chrome", "ok", found, OK)


def _check_playwright() -> Check:
    try:
        importlib.import_module("playwright.sync_api")
    except Exception as e:
        return Check(
            "playwright",
            "fail",
            f"cannot import playwright.sync_api: {e} "
            "(on NixOS set LD_LIBRARY_PATH to a gcc lib dir, or use the packaged wrapper)",
            FAIL,
        )
    return Check("playwright", "ok", "importable", OK)


def _check_profile(path: Path) -> Check:
    if not path.exists():
        return Check("profile", "fail", f"missing Chrome profile {path}", FAIL)
    lock = path.parent / (path.name + ".lock")
    try:
        import fcntl

        with lock.open("w") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return Check("profile", "warn", f"{path} is locked by another Chrome", WARN)
            finally:
                with contextlib.suppress(OSError):
                    fcntl.flock(handle, fcntl.LOCK_UN)
    except OSError as e:
        return Check("profile", "warn", f"cannot test lock on {path}: {e}", WARN)
    return Check("profile", "ok", str(path), OK)


def run_doctor(rules_path: Path, db_path: Path, profile: Path) -> list[Check]:
    return [
        Check("python", "ok", sys.version.split()[0], OK),
        _check_rules(rules_path),
        _check_store(db_path),
        _check_chrome(),
        _check_playwright(),
        _check_profile(profile),
    ]
