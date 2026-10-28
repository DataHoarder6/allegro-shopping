# 0010 — The LLM sits at the edges, under validation

Date: 2026-10-28
Status: accepted

## Context

The tool must stay fast and explainable. Every step that can be a function is
one. Two steps genuinely need judgement: turning a sentence into a structured
request, and explaining a computed plan in prose.

## Decision

1. `request-from-text` makes one `opencode run` call, extracts a JSON object,
   and feeds it through the *same* strict validator as a hand-written TOML file.
   Unknown keys, a missing budget or a malformed answer fail with `LLMError`
   (exit 10); nothing is repaired.
2. The generated request is written as TOML so a human can inspect and edit it
   before any page is fetched.
3. `justify` makes one call over the rendered run payload. Its output is
   printed, never merged into the report.
4. The core pipeline makes zero LLM calls. No number in the report ever comes
   from a model.

## Consequences

- Cost and latency are bounded per run (0–2 calls), and `budgets.max_llm_calls`
  remains the ceiling for any future in-pipeline use.
- A model outage degrades to "write the TOML yourself", not to a broken run.
