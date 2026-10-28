# allegro-shopping

Deterministic Allegro research, comparison and basket planning, with an LLM only
at the edges.

You describe what you need. The tool searches Allegro once, caches everything it
sees, deep-dives only the offers worth checking, scores them on price, true
landed cost, seller trust, product rating, spec match and delivery, then solves
the basket that costs you the least **including delivery** — respecting
Allegro Smart!'s per-seller 49.90 zł threshold.

It does not buy. Payment and checkout are out of scope by design; the
deliverable is a Markdown plan with verified prices and links.

## Quickstart

```sh
uv sync
uv run allegro-shop doctor
uv run allegro-shop shop "dwa wago 221-413, tylko nowe, do 60 zł"
```

That is the intended path: a sentence in, a plan out. It writes
`runs/<timestamp>-<name>.md` and `.json`, then you run `verify <file>` before
buying. `--dry-run` shows the parsed request without fetching anything;
`--justify` adds a written summary.

Prefer files? `request-from-text` writes the same request as an editable TOML,
and `plan config/request.example.toml` has the same behaviour.

## What it will not do

- No login automation, no proxy, no CAPTCHA solving, no anti-detect tricks.
  It drives your own logged-in Chrome profile at human pace. A challenge stops
  the run and asks you to clear it.
- No buyer API exists: `GET /offers/listing` has been closed to new
  applications since 2024, so search is browser-only
  ([allegro-api#12257](https://github.com/allegro/allegro-api/issues/12257)).
- No cart mutation yet. The plan → verify → commit contract is defined in
  [ADR-0008](docs/adr/0008-cart-contract-deferred.md); only `plan` and `verify`
  logic ships.

Allegro's Regulamin (art. 10.10 and 10.11) restricts data extraction and
software tools. This tool is built for personal-scale use with a cache and a
human handoff; using it is your decision and your account's risk.

## Layout

- `allegro_shopping/` — the library and CLI
- `tests/fixtures/allegro/` — parser fixtures (provenance in their README)
- `docs/` — research, pipeline explanation, operations, ADRs
- `config/request.example.toml` — request format
- `skills/allegro-shopping/SKILL.md` — agent skill that drives the CLI from prose
