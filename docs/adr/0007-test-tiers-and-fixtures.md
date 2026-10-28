# 0007 — Three test tiers; fixtures are the contract

Date: 2026-10-28
Status: accepted

## Context

Allegro cannot be exercised in CI (DataDome, terms), yet parser correctness is
the whole product.

## Decision

1. **Unit** — pure functions: money, identity, scoring, solver, cache policy.
2. **Fixture replay** — parsers run against saved HTML; a page that parses to
   zero records without a pinned expectation is a failure.
3. **Live** — opt-in (`pytest -m live`), manual, read-only, never in CI.

Fixtures are captured with `allegro-shop capture`, redacted, and shipped with
their provenance in `tests/fixtures/allegro/README.md`.

## Consequences

- A layout change surfaces as a failing fixture test before it corrupts a run.
- The solver is additionally checked by a property test against brute force.
- Coverage gate: 85% on `allegro_shopping/`.
