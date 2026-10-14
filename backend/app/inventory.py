"""Loads the company's contract inventory from CMS and shapes it for the UI/model."""

from __future__ import annotations

import os
from datetime import date
from typing import Any

from . import cms as cms_mod
from . import redact as redact_mod

SEND_FLAG = "LC_SEND_CONTRACTS_TO_MODEL"


def sends_contracts() -> bool:
    return os.getenv(SEND_FLAG, "0").strip().lower() in {"1", "true", "yes", "on"}


def load_inventory() -> dict[str, Any]:
    """CMS contracts only. Local JSON extras are not part of the CMS product."""
    portfolio = cms_mod.load_portfolio()
    if not portfolio:
        return {
            "organization": "Shop LC",
            "currency": "USD",
            "software": [],
            "cms": {"connected": False},
        }

    return {
        "organization": "Shop LC",
        "currency": "USD",
        "software": list(portfolio["software"]),
        "cms": portfolio["summary"],
    }


def _days_until(renewal: str | None) -> int | None:
    if not renewal:
        return None
    try:
        return (date.fromisoformat(renewal[:10]) - date.today()).days
    except ValueError:
        return None


def enrich(inv: dict[str, Any]) -> dict[str, Any]:
    """Adds derived fields the agent shouldn't have to compute itself."""
    items = []
    for item in inv.get("software", []):
        row = dict(item)
        row["days_until_renewal"] = _days_until(item.get("renewal_date"))
        notice = item.get("notice_period_days")
        days = row["days_until_renewal"]
        if notice is not None and days is not None:
            row["days_until_cancellation_deadline"] = days - notice
        items.append(row)

    total = sum(i.get("annual_cost") or 0 for i in items)
    out: dict[str, Any] = {
        "organization": inv.get("organization"),
        "currency": inv.get("currency", "USD"),
        "fiscal_year_end": inv.get("fiscal_year_end"),
        "total_annual_spend": round(total, 2),
        "line_item_count": len(items),
        "today": date.today().isoformat(),
        "software": items,
    }
    if inv.get("cms"):
        out["cms"] = inv["cms"]
        out["recorded_value"] = inv["cms"].get("recorded_value")
        out["active_recorded_value"] = inv["cms"].get("active_recorded_value")
    return out


def find_item(inv: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in inv.get("software", []):
        if item.get("id") == item_id:
            return item
    return None


WITHHELD_INVENTORY_BLOCK = (
    "<software_inventory>\n"
    "The company's live contracts are stored on this application server and are "
    "deliberately not sent to you. You have no titles, parties, values, owners, "
    "departments, dates, or documents from that database.\n\n"
    "Do not claim to know what they pay, what they have signed, or when anything "
    "renews. Answer from what the user types in this conversation and from public "
    "research. If a question needs their figures, ask them to type the specific "
    "fields they are willing to share.\n"
    "</software_inventory>"
)

WITHHELD_FOCUS_BLOCK = (
    "<focused_software>\n"
    "The user has a contract open in the local dashboard. Its title, parties, "
    "value and terms have not been given to you. Do not invent them. Work from "
    "what they type in this conversation.\n"
    "</focused_software>"
)


def as_context_block(inv: dict[str, Any] | None = None) -> str:
    """The portfolio as the model sees it, or a refusal block when switched off."""
    if not sends_contracts():
        return WITHHELD_INVENTORY_BLOCK
    if inv is None:
        inv = enrich(load_inventory())
    items = inv.get("software") or []
    if not items:
        return WITHHELD_INVENTORY_BLOCK
    return redact_mod.portfolio_block(items, inv.get("currency") or "USD")


def as_attachment_block(
    filename: str,
    text: str | None,
    inv: dict[str, Any] | None = None,
) -> str:
    """Extracted text from a PDF the user attached to this chat."""
    peers = (inv or {}).get("software") or []
    people = redact_mod.person_names(peers) if peers else set()
    scrubbed = redact_mod.scrub_excerpt(text, people, max_chars=16000)
    safe_name = (filename or "document.pdf").replace("<", "").replace(">", "")
    body = scrubbed or "No extractable text is available from this PDF."
    return (
        "<open_attachment>\n"
        "The user attached this PDF to this chat so they can ask about it. "
        "The file itself stays on their server; you only have this extracted text. "
        "Answer from it when they ask about the attachment or \"this PDF\". "
        "This is not a CMS contract and you cannot file it in CMS.\n\n"
        f"Filename: {safe_name}\n\n"
        f"{body}\n"
        "</open_attachment>"
    )


def as_focus_block(
    item: dict[str, Any] | None,
    excerpt: str | None = None,
    inv: dict[str, Any] | None = None,
) -> str:
    """The open contract in detail, or a refusal block when switched off."""
    if not sends_contracts() or not item:
        return WITHHELD_FOCUS_BLOCK
    # The individuals are collected across the whole portfolio, not just this
    # row: an excerpt for one contract routinely names a presenter who is the
    # counterparty on another, and only the portfolio-wide set catches that.
    peers = (inv or {}).get("software") or [item]
    return redact_mod.focus_block(
        item,
        excerpt,
        redact_mod.person_names(peers),
        (inv or {}).get("currency") or "USD",
    )
