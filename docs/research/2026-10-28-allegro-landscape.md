# Allegro shopping — landscape and constraints

Researched 2026-10-28. Every claim below was read from the linked source on that
date unless marked otherwise. Volatile facts carry their as-of date.

## What already exists

| Project | What it is | Why we do not depend on it |
|---|---|---|
| [agentic-shopping-autopilot](https://github.com/AndriiShramko/agentic-shopping-autopilot) | Apache-2.0; Allegro-first purchase autopilot; live autonomous purchase 2026-09-05; context-first notes, signed mandate, Smart!-aware basket | Its decision layer *is* an LLM operator session; it targets checkout and payment, which we exclude. Useful as prior art for the purchase handoff and cart flow. |
| [allegro-open-mcp-server](https://github.com/piotrlinski/allegro-open-mcp-server) | MIT; 268 MCP tools over Allegro REST; strict typing; extractable `allegro_client` | Search endpoint is inaccessible (below). Usable only for non-search resources. |
| [web-agent](https://github.com/anomalyco/opencode) (local `~/git/web-agent`) | Hoard store, real-Chrome fetcher, parser protocol, run reports | Direct dependency. |
| `car-hunt` (local) | Pipeline blueprint: delta-before-write, parser revs, gated SMART scoring | Domain-hardwired; we reuse the shape, not the code. |

## Hard facts

1. **No buyer API.** `GET /offers/listing` is "access for verified applications
   only" and new applications have been refused since ~August 2024 — Allegro's
   own collaborator in [allegro-api#12257](https://github.com/allegro/allegro-api/issues/12257)
   (2025-09-22) states access is suspended for business reasons. There is no
   public endpoint for buyer-side search.
2. **DataDome.** Plain HTTP gets 403; a fresh automated context receives a
   ~1.5 kB interstitial ("DataDome Device Check"). Observed on this machine
   2026-10-28; fixture committed. Only a real, logged-in, persistent profile
   passes, and not always on the first request.
3. **Structured data, not CSS.** Listing pages embed `__listing_StoreState`
   (`items.elements[]`: `alt`, `price.mainPrice`, `eventData.offer_id`,
   `seller.login`, `context`); product/offer pages embed
   `data-serialize-box-id` blobs and JSON-LD.
   ([Scrapfly, 2026](https://scrapfly.io/blog/posts/how-to-scrape-allegro))
4. **Smart! is per seller.** Since 2026-03-02, free delivery applies to orders
   from a single seller of ≥ 49.90 zł (previously 45 zł lockers / 65 zł courier
   for existing subscriptions).
   ([Allegro, 2026-03-02](https://help.allegro.com/en/sell/a/we-changed-the-allegro-smart-terms-conditions-for-buyers-wwkzRYxRdio))
5. **Terms.** Regulamin art. 10.10 (extracting data for reuse) and 10.11 (bots
   and software tools while using Allegro), art. 2.8 (automation at the user's
   risk), art. 8 (blocking mechanisms). Read via the summary in
   `agentic-shopping-autopilot/docs/architecture.md` (2026-09-03) — verify the
   primary text before relying on it.
6. **The basket problem has a name.** ISOP — Internet Shopping Optimization
   Problem — models one-offer-per-item with per-shop delivery; it is NP-hard in
   general and small instances are solved exactly.
   ([Musiał & Błażewicz, Poznań](https://www.cs.put.poznan.pl/jmusial/files/51126.pdf))
7. **Workflows beat agents for fixed pipelines.** Anthropic's guidance matches
   the shape chosen here: deterministic tools, LLM only where judgement is
   genuinely required.
   ([Building effective agents](https://www.anthropic.com/research/building-effective-agents))

## Consequences baked into the design

- Search is browser-only, cache-first, personal-scale.
- Parsing is deterministic and fixture-tested; `PARSER_REV` invalidates old rows.
- Prices are grosze integers; floats never touch a comparison.
- The basket is solved exactly with CP-SAT, not greedily.
- The LLM is outside the hot path (intent parsing, prose justification).
- Cart mutation is deferred behind the plan → verify → commit contract.
