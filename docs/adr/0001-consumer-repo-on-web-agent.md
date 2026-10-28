# 0001 — A new consumer repo on web-agent

Date: 2026-10-28
Status: accepted

## Context

`web-agent` already provides the hoard store, the real-Chrome fetcher and the
parser protocol. `car-hunt` is the first consumer, but its modules are hardwired
to cars (site maps, judge prompt, scoring terms, notification strings).

`web-agent/docs/adr/0011` says to promote delta/judge/score shapes into the
library when a *second* real consumer exists. Allegro is that consumer.

## Decision

Create `allegro-shopping` as a separate repo consuming `web-agent` as an
editable path dependency, exactly as `car-hunt` does. Do not extend `car-hunt`.
Do not rebuild fetch/store/parse.

Promote into `web-agent` only what both consumers genuinely share, when this
repo needs it. So far: configurable browser posture, DataDome wall detection,
`py.typed`.

## Consequences

- Two repos to keep in step; `uv sync` resolves the path dependency.
- `car-hunt` stays untouched and keeps its own regression suite.
- Library changes require library tests, not just consumer tests.
