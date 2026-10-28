# 0002 — Browser-only access, human-in-the-loop on walls

Date: 2026-10-28
Status: accepted

## Context

Allegro offers no buyer API. `GET /offers/listing` has been closed to new
applications since ~2024 (allegro-api#12257). Plain HTTP is refused by DataDome;
a fresh automated context receives the interstitial too.

## Decision

All reads go through the user's real, logged-in, persistent Chrome profile,
one session per run, human pace. One reload is allowed on a challenge; a second
challenge raises `BotWallError` (exit 3) and the run stops for a human.

No proxies, no fingerprint spoofing, no CAPTCHA solving, no scheduled crawls.

## Consequences

- Runs are slow by construction; the cache is what makes them tolerable.
- CI never touches allegro.pl; live verification is manual (`pytest -m live`
  once implemented).
- Account risk under Regulamin art. 10.10/10.11 is accepted per user, stated in
  the README.
