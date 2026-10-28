# 0003 — Three entities: product, offer, seller

Date: 2026-10-28
Status: accepted

## Context

A "product" on Allegro is a catalog entry sold by many sellers under different
offers, at different prices, conditions and delivery costs. Flattening these
loses the comparison the tool exists for.

## Decision

Model `Product` (UUID, EAN/GTIN), `Offer` (offer id, seller, price, delivery,
condition, stock) and `Seller` (rating, count, Super Sprzedawca) separately.
Hoard subjects are namespaced: `offer:<id>`, `product:<uuid>`, `seller:<login>`.

Identity comes from ids only. Titles are never fuzzy-matched.

## Consequences

- Same-product aggregation is a query, not a heuristic.
- An offer may exist without a product row (listing cards often lack it); the
  deep dive fills it in.
