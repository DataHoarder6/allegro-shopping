# Operations runbook

Last verified: 2026-10-28.

## First run

```sh
uv sync
uv run allegro-shop doctor     # every line must be ok or an explained warn
```

`doctor` checks Python, the rules file, the hoard, Chrome, Playwright import and
the profile lock. A locked profile means another Chrome owns it.

## The bot-wall

Allegro uses DataDome. A cold request may return a 1546-byte interstitial; the
fetcher reloads once, then stops with exit code 3 and a message naming the URL.

Do this, once:

```sh
google-chrome --user-data-dir="$HOME/.config/web-agent/chrome-profile" \
  "https://allegro.pl/"
```

Sign in if needed, browse normally, close it. Then re-run. Never retry in a
loop, never reach for a proxy or a stealth browser: the profile is the identity.

Captured evidence of the interstitial lives at
`tests/fixtures/allegro/blocked-datadome.html`.

### Live check (manual)

```sh
ALLEGRO_SHOP_LIVE=1 uv run pytest -m live -q
```

One listing page, read-only. It fails on a wall instead of skipping: a silent
skip would hide exactly the condition it exists to catch.

## Cache

```sh
uv run allegro-shop cache stats        # subjects by kind
uv run allegro-shop cache offers       # cached offers, newest prices first
```

TTLs come from `allegro_shopping/data/rules.toml` (`[freshness]`). To use a
custom file: `--rules path` or `ALLEGRO_SHOP_RULES=path`. The file replaces the
packaged one wholesale — there is no per-key merge.

Hoard location: `$XDG_DATA_HOME/allegro-shopping/hoard.db` (override `--db`).
Point `--db` at `~/git/web-agent/cache/web-agent.db` to share the hoard with
other consumers.

## Prose in, prose out

```sh
uv run allegro-shop request-from-text "dwa wago 221-413 do 60 zl, tylko nowe" --out /tmp/req.toml
$EDITOR /tmp/req.toml        # inspect before anything is fetched
uv run allegro-shop plan /tmp/req.toml
uv run allegro-shop justify runs/<stamp>.json
```

Both commands make exactly one `opencode run` call. A malformed answer exits 10
and is never repaired; a missing budget is refused, not invented.

## Tuning

- `basket.smart_active`: set `false` if you do not subscribe to Smart!; then
  every seller charges its delivery fee and the threshold is ignored.
- `basket.smart_minimum_grosze`: 4990 as of 2026-03-02. Verify before changing.
- `basket.sellers_max`: parcel pragmatics, not money. Default 3.
- `score.weights`: must sum to 100; change `score.version` when you change them.
- `budgets.max_offers`: the main lever on run time.

## After a layout change

Symptoms: `ParseError` (exit 5) or a run that finds fewer offers than before.

```sh
uv run allegro-shop capture "<url>" --out tests/fixtures/allegro/<name>.html
```

Then update the parser, bump `PARSER_REV` in `parse.py`, and add a fixture test.
Records carry their parser revision, so a bump makes old observations visibly
stale rather than silently trusted.

## NixOS

Playwright's `greenlet` needs `libstdc++.so.6`:

```sh
nix develop          # provides python, uv, chrome, libstdc++
```

Without the devshell, export `LD_LIBRARY_PATH` to a gcc lib directory; otherwise
`doctor` reports a Playwright import failure with that hint.
