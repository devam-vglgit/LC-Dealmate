"""Loads the company's software inventory and renders it for the model."""

from __future__ import annotations

import json
import uuid
from datetime import date
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "software_inventory.json"


def load_inventory() -> dict[str, Any]:
    with DATA_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def save_inventory(inv: dict[str, Any]) -> None:
    DATA_FILE.write_text(json.dumps(inv, indent=2) + "\n", encoding="utf-8")


def add_item(item: dict[str, Any]) -> dict[str, Any]:
    """Appends one software entry to the inventory file and returns it (with its id)."""
    inv = load_inventory()
    item = {**item, "id": item.get("id") or f"sw-{uuid.uuid4().hex[:8]}"}
    inv.setdefault("software", []).append(item)
    save_inventory(inv)
    return item


def delete_item(item_id: str) -> bool:
    """Removes one entry by id. Returns False if no entry matched."""
    inv = load_inventory()
    items = inv.get("software", [])
    kept = [i for i in items if i.get("id") != item_id]
    if len(kept) == len(items):
        return False
    inv["software"] = kept
    save_inventory(inv)
    return True


def _days_until(renewal: str | None) -> int | None:
    if not renewal:
        return None
    try:
        return (date.fromisoformat(renewal) - date.today()).days
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
    return {
        "organization": inv.get("organization"),
        "currency": inv.get("currency", "USD"),
        "fiscal_year_end": inv.get("fiscal_year_end"),
        "total_annual_spend": round(total, 2),
        "line_item_count": len(items),
        "today": date.today().isoformat(),
        "software": items,
    }


def find_item(inv: dict[str, Any], item_id: str) -> dict[str, Any] | None:
    for item in inv.get("software", []):
        if item.get("id") == item_id:
            return item
    return None


def as_focus_block(item: dict[str, Any]) -> str:
    """Tells the model which line item the user currently has open in the UI, so a
    bare 'should we renew?' resolves to the right vendor without the user repeating
    it. Deliberately small — the full row already sits in <software_inventory>."""
    return (
        "<focused_software>\n"
        f"The user is currently looking at this line item in the dashboard: "
        f"{item.get('vendor', 'Unknown vendor')} — {item.get('product', 'Unknown product')} "
        f"(id: {item.get('id')}). Unless they clearly ask about something else, treat "
        "this as the subject of the conversation.\n"
        "</focused_software>"
    )


def as_context_block(inv: dict[str, Any]) -> str:
    """The inventory as it is injected into the system prompt."""
    if not inv.get("software"):
        return (
            "<software_inventory>\n"
            "The stored inventory is empty — no contracts have been loaded into the app "
            "yet. This is not a blocker and is not worth remarking on. Answer the user's "
            "question directly from what they tell you in the conversation plus your own "
            "research. Only mention the empty inventory if a question genuinely cannot be "
            "answered without knowing their whole stack, and even then ask only for the "
            "specific figures you need.\n"
            "</software_inventory>"
        )
    return (
        "<software_inventory>\n"
        "The organization's current software stack and contract terms, as JSON. "
        "Treat this as the single source of truth for what the company already pays for.\n\n"
        f"{json.dumps(inv, indent=2)}\n"
        "</software_inventory>"
    )
