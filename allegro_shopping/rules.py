"""Access to the shipped rules file.

The packaged default is the single source of truth. `--rules PATH` or
`ALLEGRO_SHOP_RULES` replaces it wholesale; there is no per-key merging, so a
custom file always states every value it uses.
"""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path

from .config import Rules, load_rules
from .errors import ConfigError

ENV_RULES = "ALLEGRO_SHOP_RULES"


def default_rules_path() -> Path:
    with resources.as_file(resources.files("allegro_shopping") / "data" / "rules.toml") as path:
        return Path(path)


def resolve_rules(explicit: str | None) -> Rules:
    if explicit:
        return load_rules(Path(explicit))
    env = os.environ.get(ENV_RULES)
    if env:
        return load_rules(Path(env))
    return load_rules(default_rules_path())


def resolve_rules_path(explicit: str | None) -> Path:
    if explicit:
        return Path(explicit)
    env = os.environ.get(ENV_RULES)
    if env:
        return Path(env)
    return default_rules_path()


__all__ = ["ENV_RULES", "ConfigError", "default_rules_path", "resolve_rules", "resolve_rules_path"]
