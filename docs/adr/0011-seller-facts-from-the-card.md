# 0011 — Seller trust comes from the listing card, not the profile page

Date: 2026-10-28
Status: accepted

## Context

Seller trust is 15 of the 100 score points. Fetching it costs a page per seller,
which on a four-offer run is four extra fetches — the largest avoidable cost in
the pipeline.

A captured profile page (`tests/fixtures/allegro/live-seller-kontratech.html`)
shows why the fetch is not worth it: the profile exposes Super Sprzedawca and a
list of offers with *product* ratings. The seller's own star rating lives behind
a second page (`/uzytkownik/<login>/oceny`) and measures the same thing the card
already publishes as a percentage.

## Decision

Every listing card carries `seller.login`, `seller.superSeller` and
`seller.positiveFeedbackPercent`. Those three facts are stored on the offer,
merged through the deep dive, and turned into the `Seller` used for scoring.

The scoring term uses star rating when one is already known (Bayesian-shrunk),
otherwise `positiveFeedbackPercent / 100`. Provenance is the card, so no extra
request is made.

`AllegroClient.seller` and `parse_seller` remain for explicit lookups, but the
pipeline does not call them.

## Consequences

- One fewer page per distinct seller per run.
- The seller signal is Allegro's own published metric, comparable across sellers.
- The `delivery` term stays unknown (5 points); delivery ETA is prose, not data.
