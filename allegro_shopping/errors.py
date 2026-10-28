"""Typed failures and their process exit codes.

Every failure the CLI can produce maps to exactly one code, so scripts and the
agent above can branch without parsing prose. Codes are part of the contract:
never renumber, only add.
"""

from __future__ import annotations


class AllegroShoppingError(Exception):
    """Base class. `exit_code` is the process status this failure must produce."""

    exit_code: int = 1

    def __init__(self, message: str, *, detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ConfigError(AllegroShoppingError):
    """Config or request file is wrong. Never recovered from; fix the file."""

    exit_code = 1


class UsageError(AllegroShoppingError):
    """The invocation itself is invalid."""

    exit_code = 1


class StaleDataError(AllegroShoppingError):
    """A cached row is past its TTL and the caller forbade a refetch."""

    exit_code = 2


class BotWallError(AllegroShoppingError):
    """A challenge page. A human must clear it; never retried mechanically."""

    exit_code = 3


class BudgetExceeded(AllegroShoppingError):
    """A hard run budget was hit. The result would be incomplete, so we fail."""

    exit_code = 4


class ParseError(AllegroShoppingError):
    """The page did not contain the structure the parser needs."""

    exit_code = 5


class NoCandidates(AllegroShoppingError):
    """Search returned nothing usable after filtering."""

    exit_code = 6


class FetchFailure(AllegroShoppingError):
    """A page could not be fetched for a reason that is not a bot-wall."""

    exit_code = 8


class MoneyError(AllegroShoppingError):
    """A price string could not be interpreted exactly."""

    exit_code = 7


class PlanDrift(AllegroShoppingError):
    """A verified plan no longer matches the live offers."""

    exit_code = 9
