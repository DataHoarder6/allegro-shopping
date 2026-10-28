# CONTEXT — domain glossary

Terms are defined here once; every other doc points at this file.

**Hoard** — the append-only SQLite store owned by `web-agent`. Every fetch is an
immutable *observation*; "latest" is a query, never a write.

**Observation** — one fetch of one subject: URL, timestamp, data hash, JSON
payload. Re-observing identical content at a new timestamp still appends.

**Subject** — the key a hoard row is filed under: `offer:<id>`,
`product:<uuid>`, `seller:<login>`, `search:<hash>:p<n>`.

**Offer** — one purchasable listing: price, seller, condition, stock, delivery.
Identified by Allegro's numeric offer id.

**Product** — a catalog entry that several offers sell. Identified by Allegro's
product UUID, with EAN/GTIN when the page exposes it. Two offers are the same
product only by id, never by title similarity.

**Seller** — the account shipping the offer. Has a rating, a rating count and
(possibly) Super Sprzedawca status. Seller ratings measure logistics, product
ratings measure the item; they are never blended.

**Deep dive** — fetching an offer page to obtain facts a listing card lacks:
condition, stock, specs, description, rating. Budgeted, and the only expensive
per-offer step.

**Freshness / TTL** — per-kind age limit from `rules.toml`: search 6 h, offer
2 h, detail and seller 7 d. A fact past its TTL is still true-as-of-then; it may
not authorise a recommendation.

**Gate** — a hard filter (price cap, condition, stock, required spec, minimum
rating). A gated-out offer is excluded with a stated reason; it is not scored
low.

**Term** — a scored criterion: `price`, `landed`, `seller`, `rating`, `specs`,
`delivery`.

**Partial value** — a term's dimensionless 0..1 score after mapping its unit
(grosze, hours, stars) through an anchor function.

**Confidence** — share of weight backed by known inputs. Unknown input takes
`missing_term_value` and lowers confidence; it never becomes zero.

**Score version** — `score.version` from rules; every score carries the version
that produced it.

**Shortlist** — best `basket.shortlist` offers per item handed to the solver.

**Smart! threshold** — Allegro's per-seller free-delivery minimum, 49.90 zł
since 2026-03-02, and only for Smart! subscribers. Not a global basket total.

**Slice** — one seller's part of a basket: its lines, subtotal and delivery fee.

**ISOP** — Internet Shopping Optimization Problem: pick one offer per item,
pay per-seller delivery, minimise total. NP-hard; solved exactly here with
CP-SAT on small candidate sets.

**Budget** — hard cap on pages, deep dives, external lookups, LLM calls and wall
clock. Exceeding it fails the run.

**Capture** — saving a page's HTML as a test fixture, with personal data
redacted before commit.

**Specs of record** — the catalog product page's parameter table
(`/produkt/<uuid>`), merged over an offer's own seller-written specs for scoring
and gates. Both rows keep their own URL and timestamp.

**Spec source** — the URL and fetch time behind a spec fact. Shown in the
report; never inferred.

**LLM edge** — the two places a model is allowed: prose → request TOML
(`request-from-text`), and run → prose (`justify`). Neither can change a number.

**Bot-wall** — a challenge page (DataDome on Allegro). Stop, tell the human,
resume after they clear it in the visible browser.
