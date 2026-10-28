# 0009 — The catalog product page is the spec source of record

Date: 2026-10-28
Status: accepted; external providers deferred

## Context

"Compare specs beyond the offer text" needs a trustworthy parameter table.
Allegro's offer page carries seller claims; the catalog product page
(`/produkt/<uuid>`) carries one shared table across every seller of that
product.

External candidates were checked on 2026-10-28:

- **Icecat** — requires an account; the anonymous `UserName=open` call now
  returns "open the Icecat user is unknown". Best coverage for electronics, but
  needs credentials.
- **Open Products Facts** — keyless and verified, but catalogued for food-like
  products; a WAGO connector returns `product not found` / `different product
  type: food`.
- **UPCitemdb trial** — rejects EAN-13 (`INVALID_UPC`), so it cannot key on the
  ids Allegro exposes.

## Decision

The catalog product page is the spec source of record. `parse_product_page`
extracts it, `AllegroClient.product_detail` caches it under `product:<uuid>`
with the detail TTL, and scoring merges it *over* the offer's own specs while
keeping both rows (each with its URL and timestamp).

No external provider ships until one satisfies two conditions: it accepts
EAN/GTIN and its response shape is verified. The `Product`/`specs` model is the
seam where such a provider will land.

## Consequences

- Spec provenance is a URL plus a timestamp, visible in the report
  ("specs of record: …").
- Sellers' claims never overwrite the catalog row.
- Coverage beyond Allegro's catalog requires an Icecat account; that is a
  configuration decision, not a code change.
