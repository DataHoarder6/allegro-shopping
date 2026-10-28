# How a run works

One `plan` invocation, in order. Every step is deterministic except where marked.

1. **Load.** `config.load_request` parses the request TOML strictly: every label
   unique, every cap explicit, `allow_used` stated. Unknown keys fail.
2. **Search.** For each item, `AllegroClient.search` asks the hoard for that
   search page. Fresh (`freshness.search_hours`) and complete → no request.
   Otherwise one page is fetched, parsed by `parse_listing` from
   `__listing_StoreState`, and appended to the hoard.
3. **Select.** Candidates are ordered by price, then rating volume; at most
   `budgets.max_offers` across the run get a deep dive. Cheap offers are the
   ones worth spending a page on.
4. **Deep dive.** `AllegroClient.offer_detail` serves a fresh *deep* offer from
   cache or fetches the offer page, parsing JSON-LD and the serialized boxes.
   It records specs, condition, stock, EAN and rating, and `merge_offer` keeps
   the card-only facts (delivery price, thumbnail, sponsorship, seller feedback
   percentage) that the offer page does not repeat. Seller trust therefore costs
   no extra page (ADR-0011).
5. **Catalog specs.** When an offer has a product id, its catalog page is
   fetched once per product (detail TTL) and merged *over* the offer's specs.
   This is the spec table of record (ADR-0009); the report names its URL.
6. **Gate.** `score_offer` applies hard filters first: cap, condition, stock,
   required specs, minimum rating. A required spec counts as matched when the
   parameter table or the offer title carries the value; the evidence is
   recorded per key. Failures are kept with reasons and shown in the report.

7. **Score.** Each surviving offer gets partial values per term, weighted to a
   0..100 total, with confidence and its weakest term. Unknown inputs take the
   configured neutral value.
8. **Shortlist.** The best `basket.shortlist` offers per item go to the solver.
9. **Solve.** `basket.plan` builds a CP-SAT model: one offer per item,
   per-seller subtotal, delivery free above the Smart! threshold when active,
   at most `sellers_max` sellers. It minimises the true total, then breaks ties
   on score. Infeasible constraints raise `NoCandidates`.
10. **Render.** `report.to_markdown` and `to_json` write the deliverable: per-item
   ranking with the age of each price, the basket sliced by seller, the
   cheapest-per-item baseline and the saving.

## Where the LLM sits

Outside the loop. It may turn prose into a request TOML before step 1 and
explain the result after step 9. It never produces a number that reaches the
report.

## Failure contract

| Failure | Exit | Meaning |
|---|---|---|
| `ConfigError` / `UsageError` | 1 | fix the file or the command |
| `StaleDataError` | 2 | observation too old for its purpose |
| `BotWallError` | 3 | human must clear a challenge |
| `BudgetExceeded` | 4 | raise the budget deliberately, or narrow the request |
| `ParseError` | 5 | page layout changed; capture a fixture and bump `PARSER_REV` |
| `NoCandidates` | 6 | nothing passed the gates or the constraints are infeasible |
| `MoneyError` | 7 | a price string could not be read exactly |
| `FetchFailure` | 8 | network/profile/selector failure that is not a wall |
