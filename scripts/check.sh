#!/usr/bin/env bash
# The exact gate CI runs, runnable without GitHub Actions.
set -euo pipefail
cd "$(dirname "$0")/.."

# ortools -> numpy loads libstdc++; on NixOS that is not on the default loader
# path. Re-enter through the devshell once instead of documenting a magic path.
if ! uv run python -c "import numpy" >/dev/null 2>&1; then
  if command -v nix >/dev/null 2>&1; then
    echo "libstdc++ not on the loader path; re-entering nix develop" >&2
    exec nix develop --command bash "$0" "$@"
  fi
  echo "libstdc++ missing and nix is unavailable; install a C++ runtime" >&2
  exit 1
fi

uv sync --quiet
uv run ruff check .
uv run mypy
uv run pytest --cov
