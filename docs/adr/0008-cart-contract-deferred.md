# 0008 — Plan, verify, commit; only plan and verify ship

Date: 2026-10-28
Status: accepted (commit half not implemented)

## Context

Adding to the cart is the only irreversible action in scope and it mutates the
user's account. Deep links plus a verified price are nearly as useful.

## Decision

The protocol is fixed now:

- `plan` — produce the basket with links, prices and reasons.
- `verify` — re-fetch the chosen offers live, diff price/seller/delivery/stock
  against the plan; any deviation aborts.
- `commit` (future, `--commit` only) — add items one at a time, re-read the cart
  after each, never reach checkout, log before/after state.

v1 implements `plan` and the verification semantics (they are pure functions
over two observations). `commit` is blocked until it can be tested end to end
against the real cart page.

## Consequences

- The risky half plugs into a contract that is already exercised by tests.
- No checkout automation, ever: payment stays with the human.
