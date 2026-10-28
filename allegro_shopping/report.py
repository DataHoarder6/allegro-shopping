"""Rendering: Markdown for humans, JSON for the agent above.

The Markdown file *is* the deliverable: it names the offer, the seller, the
price, the age of that price, and why it won. Nothing in it is inferred at
render time — every number comes from the run result.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

from .basket import BasketPlan
from .models import Offer, iso
from .money import format_grosze
from .pipeline import ItemOutcome, RunResult
from .score import ScoreResult


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower()).strip("-")
    return cleaned or "run"


def _offer_row(index: int, offer: Offer, result: ScoreResult, generated_at: datetime) -> str:
    age_hours = (generated_at - offer.fetched_at).total_seconds() / 3600
    rating = (
        "—" if offer.rating_avg is None else f"{offer.rating_avg:.2f} ({offer.rating_count or 0})"
    )
    return (
        f"| {index} | {offer.title[:70]} | {offer.seller_login} | "
        f"{format_grosze(offer.price)} | {rating} | {result.total:.1f} | "
        f"{result.confidence:.0%} | {age_hours:.1f}h | {offer.url} |"
    )


def _item_section(outcome: ItemOutcome, generated_at: datetime) -> list[str]:
    item = outcome.item
    lines = [
        f"### {item.label} — {item.quantity} pcs, cap {format_grosze(item.max_price_grosze)}",
        "",
        f"query: `{item.query}`",
        "",
        "| # | offer | seller | price | rating (n) | score | conf | age | link |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for index, (offer, result) in enumerate(outcome.ranked[:5], 1):
        lines.append(_offer_row(index, offer, result, generated_at))
    if len(outcome.ranked) > 5:
        lines.append("")
        lines.append(f"_{len(outcome.ranked) - 5} further eligible offers in the JSON._")
    for offer_id, url in outcome.spec_sources[:1]:
        lines += ["", f"specs of record: {url} (catalog page for offer {offer_id})"]
    if outcome.rejected:
        lines += ["", "Excluded:"]
        for offer, result in outcome.rejected[:5]:
            lines.append(f"- {offer.offer_id} — {'; '.join(result.gate_failures)}")
    lines.append("")
    return lines


def _basket_section(plan_result: BasketPlan) -> list[str]:
    lines = ["## Basket", ""]
    for seller_slice in plan_result.slices:
        delivery = (
            "free (Smart!)" if seller_slice.free_delivery else format_grosze(seller_slice.delivery)
        )
        goods = format_grosze(seller_slice.subtotal)
        lines.append(f"### {seller_slice.seller} — goods {goods}, delivery {delivery}")
        for line in seller_slice.lines:
            lines.append(
                f"- {line.item_label}: {line.quantity} x {format_grosze(line.offer.price)} — "
                f"{line.offer.title} — {line.offer.url}"
            )
        lines.append("")
    goods = format_grosze(plan_result.items_total)
    delivery = format_grosze(plan_result.delivery_total)
    total = format_grosze(plan_result.grand_total)
    lines += [
        f"Goods {goods} + delivery {delivery} = **{total}**",
        "",
        f"Cheapest-per-item baseline (no seller consolidation): "
        f"{format_grosze(plan_result.baseline_total)} — this plan saves "
        f"{format_grosze(plan_result.savings)}.",
        "",
    ]
    return lines


def to_markdown(result: RunResult) -> str:
    lines = [
        f"# {result.request_name}",
        "",
        f"- generated: {iso(result.generated_at)}",
        f"- rules version: {result.rules_version}, parser rev: {result.parser_rev}",
        "- budget used: " + ", ".join(f"{k}={v}" for k, v in sorted(result.budget.items())),
        "",
        "Prices are observations, not offers: the age column says how old the "
        "observation is at render time.",
        "",
    ]
    for outcome in result.items:
        lines += _item_section(outcome, result.generated_at)
    if result.plan is not None:
        lines += _basket_section(result.plan)
    if result.warnings:
        lines += ["## Warnings", ""]
        lines += [f"- {warning}" for warning in result.warnings]
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def to_json(result: RunResult) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for outcome in result.items:
        items.append(
            {
                "label": outcome.item.label,
                "query": outcome.item.query,
                "quantity": outcome.item.quantity,
                "max_price_grosze": int(outcome.item.max_price_grosze),
                "ranked": [
                    {
                        "offer": offer.to_record(),
                        "score": {
                            "total": res.total,
                            "terms": res.terms,
                            "values": res.values,
                            "weights": res.weights,
                            "confidence": res.confidence,
                            "confidence_badge": res.confidence_badge,
                            "worst_term": res.worst_term,
                            "score_version": res.score_version,
                        },
                    }
                    for offer, res in outcome.ranked
                ],
                "spec_sources": [
                    {"offer_id": offer_id, "url": url} for offer_id, url in outcome.spec_sources
                ],
                "rejected": [
                    {"offer_id": offer.offer_id, "gates": list(res.gate_failures)}
                    for offer, res in outcome.rejected
                ],
            }
        )
    plan_payload: dict[str, Any] | None = None
    if result.plan is not None:
        plan_payload = {
            "sellers": [
                {
                    "seller": s.seller,
                    "subtotal_grosze": int(s.subtotal),
                    "delivery_grosze": int(s.delivery),
                    "free_delivery": s.free_delivery,
                    "lines": [
                        {
                            "item": line.item_label,
                            "offer_id": line.offer.offer_id,
                            "quantity": line.quantity,
                            "price_grosze": int(line.offer.price),
                            "url": line.offer.url,
                        }
                        for line in s.lines
                    ],
                }
                for s in result.plan.slices
            ],
            "items_total_grosze": int(result.plan.items_total),
            "delivery_total_grosze": int(result.plan.delivery_total),
            "grand_total_grosze": int(result.plan.grand_total),
            "baseline_total_grosze": int(result.plan.baseline_total),
            "savings_grosze": int(result.plan.savings),
            "sellers_used": result.plan.sellers_used,
            "solver": result.plan.solver,
        }
    return {
        "request": result.request_name,
        "generated_at": iso(result.generated_at),
        "rules_version": result.rules_version,
        "parser_rev": result.parser_rev,
        "budget": result.budget,
        "items": items,
        "basket": plan_payload,
        "warnings": list(result.warnings),
    }


def write_run(result: RunResult, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = result.generated_at.strftime("%Y%m%dT%H%M%S")
    stem = f"{stamp}-{_slug(result.request_name)}"
    markdown_path = out_dir / f"{stem}.md"
    json_path = out_dir / f"{stem}.json"
    markdown_path.write_text(to_markdown(result), encoding="utf-8")
    json_path.write_text(
        json.dumps(to_json(result), ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return markdown_path, json_path
