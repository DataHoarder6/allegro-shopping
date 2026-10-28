# 0004 — Freshness is per observation kind

Date: 2026-10-28
Status: accepted

## Context

A cached price is a fact about the past. Serving it as current is the single
most expensive failure this tool can have.

## Decision

TTLs live in `[freshness]`: search 6 h (it only seeds candidates), offer 2 h
(the price may authorise a recommendation), detail and seller 168 h (specs and
reputation change slowly).

`Cache.require_fresh` is called before scoring every offer, so a stale row can
never reach a recommendation. The report prints each price's age.

Hitting a search TTL triggers one refetch of that page; hitting an offer TTL
triggers one refetch of that offer.

## Consequences

- A run may be a mix of fresh and cached data; the age column makes it visible.
- Changing a parser requires a `PARSER_REV` bump, not a cache flush.
