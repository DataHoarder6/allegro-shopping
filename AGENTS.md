# AGENTS.md

Product research for Allegro: cache-first, deterministic ranking, exact basket
optimisation. The LLM translates intent and writes prose; it never touches
prices, sums or the winner.

## Hard rules

1. Never invent a price, rating or spec. Missing facts stay `None` and lower
   confidence; they are never filled with a default.
2. A recommendation may only be rendered from offers whose observation is
   inside `freshness.offer_hours`. `Cache.require_fresh` enforces it.
3. A budget breach fails the run (`BudgetExceeded`). Never return a truncated
   candidate set as a complete answer.
4. A bot-wall means stop and hand off to the human. No retries beyond the one
   documented reload, no stealth, no proxies.
5. Parsers are pure functions over HTML with fixture tests. Never parse inside
   the agent loop, never scrape with the LLM.
6. Every failure is an `AllegroShoppingError` subclass with a stable exit code
   (`errors.py`). Never let an untyped exception reach the CLI.
7. Mutation of the user's Allegro account (cart, orders) is out of scope until
   ADR-0008's commit half is implemented.

## Commands

| Task | Command |
|---|---|
| environment check | `uv run allegro-shop doctor` |
| tests (offline) | `uv run pytest` |
| coverage gate (85%) | `uv run pytest --cov` |
| lint / types | `uv run ruff check .` · `uv run mypy` |
| search (cache-first) | `uv run allegro-shop search "<query>" [--order p] [--json]` |
| full plan | `uv run allegro-shop plan <request.toml>` |
| score breakdown | `uv run allegro-shop explain <offer_id> --request R --item L` |
| new fixture | `uv run allegro-shop capture <url> --out tests/fixtures/allegro/<name>.html` |
| hoard stats | `uv run allegro-shop cache stats` |

`LD_LIBRARY_PATH` must point at a gcc lib dir on NixOS when Playwright is
imported (`nix develop` sets it).

## Docs

- `CONTEXT.md` — domain glossary (read before changing names)
- `docs/pipeline.md` — what a run does, step by step
- `docs/operations.md` — runbook: walls, profiles, cache, tuning
- `docs/research/2026-10-28-allegro-landscape.md` — facts this design rests on
- `docs/adr/` — decisions, one per file
- `tests/fixtures/allegro/README.md` — fixture provenance

## Gotchas

- Allegro embeds JSON in `<script>` tags (`__listing_StoreState`,
  `data-serialize-box-id`). Parse that, never CSS classes.
- Product pages and offer pages are different subjects with different URLs.
  `/produkt/<uuid>?offerId=<id>` names both.
- Smart! is per **seller**, not per basket: 49.90 zł each, since 2026-03-02.
- `web-agent` owns the hoard store and the browser fetcher; do not fork them.
  Library changes go there with their tests.
