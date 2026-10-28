# Fixtures

Two kinds live here, and the difference matters.

## Genuine captures (2026-10-28)

Raw pages saved with `allegro-shop capture`, unmodified except that nothing
personal was ever in them: the session was logged out ("Witaj w Allegro!").

| File | URL | Why it is here |
|---|---|---|
| `live-listing.html` | `allegro.pl/listing?string=wago 221` | 72 offers, page 1 of 9. Proves card parsing, sponsored flags, delivery, ratings, `cartAvailable`, and that `allegrolokalnie.pl` links are rejected. |
| `live-offer-18657388077.html` | `allegro.pl/oferta/18657388077` | Proves offer parsing: price, seller, EAN, rating, `itemCondition`, 36-row spec table. |
| `live-product-6041c31c.html` | `allegro.pl/produkt/6041c31c-a5bc-40d8-b46b-f5fe30f1fd99` | The catalog page: the spec table of record (ADR-0009). |
| `live-seller-kontratech.html` | `allegro.pl/uzytkownik/KONTRATECH` | Evidence for ADR-0011: the profile page exposes no seller star rating, only product ratings. |
| `blocked-datadome.html` | first cold request | The interstitial itself, ~1.5 kB, title `allegro.pl`. Proves wall detection. |

`PARSER_REV` is 2: it changed when these pages were first parsed (card JSON keys,
`itemCondition`, whitespace normalisation in spec values).

## Reconstructed containers

`listing-wago.html`, `offer-wago-221.html`, `offer-wago-221-jsonld-only.html`
and `product-wago-221.html` are small, hand-built pages that embed the documented
JSON shapes. Their field values come from real snapshots in
`~/git/web-agent/.playwright-mcp/allegro-*.md` (2026-08-09). They exist to pin
edge cases the live corpus does not contain: a card with no seller, a promoted
card, a page with only JSON-LD.

Do not "fix" a live fixture by hand. If a parser change needs a new case, capture
a real page; if that is impossible, add a reconstructed container and say so here.
