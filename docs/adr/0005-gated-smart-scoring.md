# 0005 — Gates first, then gated SMART/MAVT

Date: 2026-10-28
Status: accepted

## Context

Price (PLN), delivery (hours), ratings (0–5) and spec completeness have no
common unit. A plain weighted sum on raw values is indefensible; a single
"score" that hides a missing fact is worse.

## Decision

1. Hard gates: price cap, condition, stock, required specs, minimum rating.
   A gated-out offer is excluded with a stated reason, never scored low.
2. Surviving offers get partial values in 0..1 per term, then weights summing
   to 100.
3. Unknown input takes `missing_term_value` and lowers confidence; it is never
   zero and never invented.
4. Ratings are shrunk toward a prior by review count.
5. Every score carries `score_version` and can be printed term by term
   (`explain`).

## Consequences

- Weights are versioned data; changing them is a config + version change.
- The output always says why, which is what makes it usable for a purchase.
