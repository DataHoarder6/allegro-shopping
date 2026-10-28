# Fixtures

`blocked-datadome.html` is a **genuine** capture of the DataDome interstitial
allegro.pl served on 2026-10-28 (first request from a fresh automated context).

`listing-wago.html`, `offer-wago-221.html` and `offer-wago-221-jsonld-only.html`
are **reconstructed containers**: the JSON shapes follow Allegro's documented
`__listing_StoreState` and `data-serialize-box-id` payloads, and the field
values (titles, prices, sellers, ratings) are copied from real snapshots in
`~/git/web-agent/.playwright-mcp/allegro-*.md` (2026-08-09). Replace them with
genuine captures via `allegro-shop capture <url> --out <file>` as soon as the
bot-wall is cleared; keep `PARSER_REV` in step with any change.
