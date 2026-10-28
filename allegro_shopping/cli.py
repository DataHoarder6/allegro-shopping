"""`allegro-shop` — the whole surface. Thin: argument parsing and wiring only.

Business logic lives in the modules; the CLI's only jobs are (a) resolving what
the user pointed at, (b) turning failures into the documented exit codes, and
(c) keeping the browser session scoped to one command.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from web_agent.store import Store

from . import __version__, llm
from .cache import Cache
from .client import AllegroClient
from .config import Rules, load_request
from .doctor import run_doctor
from .errors import AllegroShoppingError, ConfigError, PlanDrift, UsageError
from .pipeline import Budget, cache_summary, run_request, verify_plan
from .report import to_json, to_markdown, write_run
from .rules import resolve_rules, resolve_rules_path
from .score import ScoreInput, score_offer
from .session import BrowserSettings, PlaywrightPageSource


def default_db_path() -> Path:
    base = Path(os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share")))
    return base / "allegro-shopping" / "hoard.db"


def _store(args: argparse.Namespace) -> Store:
    return Store(args.db or default_db_path())


def _with_client(
    args: argparse.Namespace, rules: Rules, store: Store
) -> tuple[PlaywrightPageSource, AllegroClient]:
    pages = PlaywrightPageSource(
        rules, BrowserSettings(profile=args.profile, headless=args.headless), store
    )
    return pages, AllegroClient(pages, Cache(store, rules), rules)


def cmd_search(args: argparse.Namespace) -> int:
    rules = resolve_rules(args.rules)
    with _store(args) as store:
        pages, client = _with_client(args, rules, store)
        with pages.open():
            offers, _last, skipped = client.search(
                args.query, order=args.order, page=args.page, refresh=args.refresh
            )
    payload = {
        "offers": [offer.to_record() for offer in offers],
        "skipped": [{"index": s.index, "reason": s.reason} for s in skipped],
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    for offer in sorted(offers, key=lambda o: o.price):
        print(f"{offer.offer_id}  {offer.price:>8}  {offer.seller_login:<24} {offer.title[:80]}")
    if skipped:
        print(f"skipped {len(skipped)} cards (see --json)")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    rules = resolve_rules(args.rules)
    request = load_request(Path(args.request))
    with _store(args) as store:
        pages, client = _with_client(args, rules, store)
        with pages.open():
            result = run_request(
                request, client, rules, refresh=args.refresh, budget=Budget(rules.budgets)
            )
    markdown_path, json_path = write_run(result, Path(args.out))
    if args.json:
        print(json.dumps(to_json(result), ensure_ascii=False, indent=2))
    else:
        print(to_markdown(result))
        print(f"wrote {markdown_path} and {json_path}")
    return 0


def cmd_explain(args: argparse.Namespace) -> int:
    rules = resolve_rules(args.rules)
    request = load_request(Path(args.request))
    items = {item.label: item for item in request.items}
    if args.item not in items:
        raise UsageError(f"request has no item {args.item!r}; known: {sorted(items)}")
    item = items[args.item]
    with _store(args) as store:
        cache = Cache(store, rules)
        offer = cache.offer(args.offer_id)
        if offer is None:
            raise UsageError(f"offer {args.offer_id} is not in the cache; run a plan first")
        seller = cache.seller(offer.seller_login)
        result = score_offer(item, ScoreInput(offer, seller, None, item.quantity), rules.score)
    print(result.explain())
    return 0


def cmd_capture(args: argparse.Namespace) -> int:
    rules = resolve_rules(args.rules)
    with _store(args) as store:
        pages, client = _with_client(args, rules, store)
        with pages.open():
            markup = client.capture(args.url)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(markup, encoding="utf-8")
    print(f"wrote {out} ({len(markup)} bytes)")
    return 0


def cmd_verify(args: argparse.Namespace) -> int:
    rules = resolve_rules(args.rules)
    payload = json.loads(Path(args.run_file).read_text(encoding="utf-8"))
    with _store(args) as store:
        pages, client = _with_client(args, rules, store)
        with pages.open():
            deviations = verify_plan(payload, client)
    if args.json:
        print(
            json.dumps(
                [
                    {
                        "item": d.item_label,
                        "offer_id": d.offer_id,
                        "field": d.field,
                        "expected": d.expected,
                        "actual": d.actual,
                    }
                    for d in deviations
                ],
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        for deviation in deviations:
            print(
                f"DRIFT {deviation.item_label} {deviation.offer_id}: "
                f"{deviation.field} {deviation.expected} -> {deviation.actual}"
            )
    if deviations:
        print(
            f"error: {len(deviations)} deviation(s); re-plan before buying",
            file=sys.stderr,
        )
        return PlanDrift.exit_code
    return 0


def cmd_shop(args: argparse.Namespace) -> int:
    """One command: sentence in, plan out. The only LLM call is intent parsing."""
    rules = resolve_rules(args.rules)
    request = llm.request_from_text(args.text, runner=llm.run_opencode, model=args.model)
    print(llm.request_to_toml(request), file=sys.stderr, end="")
    if args.dry_run:
        return 0
    with _store(args) as store:
        pages, client = _with_client(args, rules, store)
        with pages.open():
            result = run_request(
                request, client, rules, refresh=args.refresh, budget=Budget(rules.budgets)
            )
    markdown_path, json_path = write_run(result, Path(args.out))
    print(to_markdown(result))
    print(f"wrote {markdown_path} and {json_path}")
    if args.justify:
        print(llm.justify(to_json(result), runner=llm.run_opencode, model=args.model))
    return 0


def cmd_request_from_text(args: argparse.Namespace) -> int:
    request = llm.request_from_text(args.text, runner=llm.run_opencode, model=args.model)
    document = llm.request_to_toml(request)
    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(document, encoding="utf-8")
        print(f"wrote {out}")
    else:
        print(document, end="")
    return 0


def cmd_justify(args: argparse.Namespace) -> int:
    payload = json.loads(Path(args.run_file).read_text(encoding="utf-8"))
    print(llm.justify(payload, runner=llm.run_opencode, model=args.model))
    return 0


def cmd_cache(args: argparse.Namespace) -> int:
    rules = resolve_rules(args.rules)
    with _store(args) as store:
        cache = Cache(store, rules)
        if args.action == "stats":
            print(json.dumps(cache_summary(cache), indent=2))
            return 0
        offers = sorted(cache.offers().values(), key=lambda o: -o.price)
        for offer in offers:
            print(
                f"{offer.offer_id}  {offer.price:>8}  {offer.seller_login:<24} "
                f"{offer.fetched_at.isoformat()}  {offer.title[:60]}"
            )
        return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    rules_path = resolve_rules_path(args.rules)
    checks = run_doctor(rules_path, Path(args.db or default_db_path()), Path(args.profile))
    worst = 0
    for check in checks:
        print(f"[{check.status.upper():<4}] {check.name}: {check.detail}")
        worst = max(worst, check.severity)
    return worst


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="allegro-shop", description=__doc__)
    parser.add_argument("--version", action="version", version=f"allegro-shopping {__version__}")
    parser.add_argument("--db", help=f"hoard sqlite path (default {default_db_path()})")
    parser.add_argument("--rules", help="rules TOML path (default: packaged rules)")
    parser.add_argument(
        "--profile", default=str(Path.home() / ".config" / "web-agent" / "chrome-profile")
    )
    parser.add_argument("--headless", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    search = sub.add_parser("search", help="search a listing page (cache-first)")
    search.add_argument("query")
    search.add_argument(
        "--order", default=None, help="Allegro sort code: p, pd, d, dd, qd, t, n, prd"
    )
    search.add_argument("--page", type=int, default=1)
    search.add_argument("--refresh", action="store_true")
    search.add_argument("--json", action="store_true")
    search.set_defaults(func=cmd_search)

    plan_cmd = sub.add_parser("plan", help="run a request file end to end")
    plan_cmd.add_argument("request")
    plan_cmd.add_argument("--out", default="runs")
    plan_cmd.add_argument("--refresh", action="store_true")
    plan_cmd.add_argument("--json", action="store_true")
    plan_cmd.set_defaults(func=cmd_plan)

    explain = sub.add_parser("explain", help="show a cached offer's score term by term")
    explain.add_argument("offer_id")
    explain.add_argument("--request", required=True)
    explain.add_argument("--item", required=True)
    explain.set_defaults(func=cmd_explain)

    verify = sub.add_parser("verify", help="re-fetch a run's chosen offers and diff them")
    verify.add_argument("run_file")
    verify.add_argument("--json", action="store_true")
    verify.set_defaults(func=cmd_verify)

    capture = sub.add_parser("capture", help="save a page's HTML for fixtures")
    capture.add_argument("url")
    capture.add_argument("--out", required=True)
    capture.set_defaults(func=cmd_capture)

    shop = sub.add_parser("shop", help="sentence in, plan out (one LLM call)")
    shop.add_argument("text")
    shop.add_argument("--out", default="runs")
    shop.add_argument("--model")
    shop.add_argument("--refresh", action="store_true")
    shop.add_argument("--justify", action="store_true", help="add one LLM-written summary")
    shop.add_argument(
        "--dry-run", action="store_true", help="show the parsed request, fetch nothing"
    )
    shop.set_defaults(func=cmd_shop)

    from_text = sub.add_parser("request-from-text", help="turn prose into a request file")
    from_text.add_argument("text")
    from_text.add_argument("--out")
    from_text.add_argument("--model")
    from_text.set_defaults(func=cmd_request_from_text)

    justify = sub.add_parser("justify", help="explain a run in prose (one LLM call)")
    justify.add_argument("run_file")
    justify.add_argument("--model")
    justify.set_defaults(func=cmd_justify)

    cache_cmd = sub.add_parser("cache", help="inspect the hoard")
    cache_cmd.add_argument("action", choices=("stats", "offers"))
    cache_cmd.set_defaults(func=cmd_cache)

    doctor = sub.add_parser("doctor", help="check environment, config and profile")
    doctor.set_defaults(func=cmd_doctor)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except AllegroShoppingError as e:
        print(f"error: {e.message}", file=sys.stderr)
        if e.detail:
            print(f"detail: {e.detail}", file=sys.stderr)
        return e.exit_code
    except FileNotFoundError as e:
        print(f"error: {e}", file=sys.stderr)
        return ConfigError.exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
