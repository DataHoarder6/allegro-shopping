# 0006 — Exact CP-SAT basket, not a greedy heuristic

Date: 2026-10-28
Status: accepted

## Context

The requirement "prefer one seller, but not at the cost of a cheaper item" is
ISOP: one offer per item, per-seller delivery, free above a per-seller
threshold. Greedy consolidation gets it wrong whenever the item saving exceeds
the extra delivery fee.

## Decision

Model with OR-tools CP-SAT: boolean per (item, offer), per-seller used flag,
per-seller threshold flag. Objective = goods + delivery + a 1-grosze per-seller
penalty. A second pass maximises score subject to the optimal cost.

Cap the number of sellers (`sellers_max`) and the shortlist per item; both are
policy, not correctness.

## Consequences

- Optimum is proven on the shortlist, not on the whole market.
- The solver is property-tested against a brute-force oracle.
- Infeasible constraints raise `NoCandidates`, never a partial basket.
