"""Live ShopLC CMS data for DealMate.

The portfolio lives in CMS Postgres. This module pulls it so `/api/inventory`
and the chat agent see the same contracts as CMS.

How it connects, first match wins:

1. ``DATABASE_URL`` — direct Postgres (the path when DealMate is on the CMS network).
2. ``CMS_PG_DOCKER`` — ``docker exec`` into a running CMS Postgres container.
   Local Windows default only when ``DATABASE_URL`` is unset.
3. ``data/cms_snapshot.json`` — last successful fetch, so the API still serves
   data if Postgres is briefly down.

Embeddings' float vectors and encrypted columns stay in CMS. Excerpt text is
fetched per open contract and only then (redacted) offered to the model.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

from . import cms_db

log = logging.getLogger("lcdealmate.cms")

SNAPSHOT_FILE = Path(__file__).resolve().parent.parent / "data" / "cms_snapshot.json"

DEFAULT_DOCKER = cms_db.DEFAULT_DOCKER
DEFAULT_DOCKER_USER = cms_db.DEFAULT_DOCKER_USER
DEFAULT_DOCKER_DB = cms_db.DEFAULT_DOCKER_DB

CACHE_SECONDS = 120
try:
    CACHE_SECONDS = int(os.getenv("CMS_CACHE_SECONDS", "120"))
except ValueError:
    CACHE_SECONDS = 120

_CACHE: dict[str, Any] | None = None
_CACHE_AT: float = 0.0

# One round-trip: everything the agent and the API need, as a single JSON object.
_PORTFOLIO_SQL = """
SELECT json_build_object(
  'fetched_at', timezone('UTC', now()),
  'contracts', (
    SELECT coalesce(json_agg(row_to_json(x) ORDER BY x.end_date NULLS LAST, x.title), '[]'::json)
    FROM (
      SELECT
        c.id,
        c.title,
        c.parties,
        c.start_date,
        c.end_date,
        c.value,
        c.value_basis,
        c.currency,
        c.type,
        c.custom_type,
        c.owner,
        c.status,
        c.description,
        c.contract_structure,
        c.renewal_period_months,
        c.renewal_terms,
        c.pricing_structure,
        c.termination_notice_period,
        c.contracted_entity,
        c.sharing_basis,
        c.vendor_id,
        c.needs_review,
        c.workflow_state,
        c.is_shared_across_geos,
        c.document_name,
        (c.document_remote_path IS NOT NULL AND btrim(c.document_remote_path) <> '') AS has_document,
        c.is_deleted,
        v.name AS vendor_name,
        v.vendor_code,
        d.name AS department,
        le.name AS legal_entity,
        le.code AS legal_entity_code
      FROM contracts c
      LEFT JOIN mst_vendor v ON v.id = c.vendor_id
      LEFT JOIN departments d ON d.id = COALESCE(c.owning_department_id, c.department_id)
      LEFT JOIN legal_entities le ON le.id = c.owning_geo_id
    ) x
  ),
  'vendors', (
    SELECT coalesce(json_agg(row_to_json(v) ORDER BY v.name), '[]'::json)
    FROM (
      SELECT id, vendor_code, name, "group", status, created_at
      FROM mst_vendor
    ) v
  ),
  'departments', (
    SELECT coalesce(json_agg(row_to_json(d) ORDER BY d.name), '[]'::json)
    FROM (
      SELECT id, name, description, contact_emails
      FROM departments
    ) d
  ),
  'legal_entities', (
    SELECT coalesce(json_agg(row_to_json(e) ORDER BY e.sort_order, e.name), '[]'::json)
    FROM (
      SELECT id, name, code, country, is_active, sort_order
      FROM legal_entities
    ) e
  ),
  'users', (
    SELECT coalesce(json_agg(row_to_json(u) ORDER BY u.username), '[]'::json)
    FROM (
      SELECT id, username, name, email, is_admin, status, department_id, geo_id, last_login_at
      FROM users
    ) u
  ),
  'attachments', (
    SELECT coalesce(json_agg(row_to_json(a) ORDER BY a.created_at), '[]'::json)
    FROM (
      SELECT id, contract_id, file_name, file_size, file_type, created_at
      FROM contract_attachments
    ) a
  ),
  'embeddings', (
    SELECT coalesce(json_agg(row_to_json(e) ORDER BY e.created_at), '[]'::json)
    FROM (
      SELECT id, contract_id, model, content_hash,
             length(embedded_text) AS text_chars,
             left(embedded_text, 400) AS preview,
             created_at
      FROM contract_embeddings
    ) e
  ),
  'alerts', (
    SELECT json_build_object(
      'sent', count(*),
      'contracts', count(DISTINCT contract_id)
    )
    FROM alerts
  )
);
"""


def configured() -> bool:
    return cms_db.configured()


def _now() -> float:
    return datetime.now(timezone.utc).timestamp()


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value


def _as_date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value)
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        return None


def _num(value: Any) -> float:
    if value is None or value == "":
        return 0.0
    return float(value)


def annualize(
    value: Any,
    basis: str | None,
    start: date | None,
    end: date | None,
    renewal_months: int | None,
) -> float | None:
    """Turn a CMS recorded value into an annualised figure DealMate can total."""
    amount = _num(value)
    kind = (basis or "UNKNOWN").upper()
    if kind == "MONTHLY":
        return round(amount * 12, 2)
    if kind == "ANNUAL":
        return round(amount, 2)
    if kind in {"REVENUE_SHARE"}:
        return None
    months = renewal_months
    if not months and start and end:
        months = max(1, round((end - start).days / 30.44))
    if kind in {"TOTAL", "ONE_TIME", "NOT_TO_EXCEED", "UNKNOWN"} and months:
        return round(amount * 12 / months, 2)
    return round(amount, 2)


def contract_to_item(row: dict[str, Any]) -> dict[str, Any]:
    """Map one CMS contract onto the inventory shape the UI already renders."""
    start = _as_date(row.get("start_date"))
    end = _as_date(row.get("end_date"))
    vendor = (row.get("vendor_name") or row.get("parties") or "Unknown vendor").strip()
    title = (row.get("title") or "Untitled contract").strip()
    basis = row.get("value_basis") or "UNKNOWN"
    recorded = _num(row.get("value"))
    structure = row.get("contract_structure")
    return {
        "id": row["id"],
        "source": "cms",
        "vendor": vendor,
        "product": title,
        "category": row.get("type") or row.get("custom_type"),
        "plan": row.get("custom_type") or row.get("type"),
        "annual_cost": annualize(
            recorded, basis, start, end, row.get("renewal_period_months")
        ),
        "recorded_value": recorded,
        "value_basis": basis,
        "currency": row.get("currency") or "USD",
        "contract_start": start.isoformat() if start else None,
        "renewal_date": end.isoformat() if end else None,
        "auto_renew": structure == "auto-renewal",
        "contract_structure": structure,
        "notice_period_days": row.get("termination_notice_period"),
        "renewal_period_months": row.get("renewal_period_months"),
        "renewal_terms": row.get("renewal_terms"),
        "pricing_structure": row.get("pricing_structure"),
        "owner": row.get("owner"),
        "department": row.get("department"),
        "legal_entity": row.get("legal_entity") or row.get("contracted_entity"),
        "contracted_entity": row.get("contracted_entity"),
        "sharing_basis": row.get("sharing_basis"),
        "status": row.get("status"),
        "parties": row.get("parties"),
        "vendor_id": row.get("vendor_id"),
        "vendor_code": row.get("vendor_code"),
        "needs_review": row.get("needs_review"),
        "workflow_state": row.get("workflow_state"),
        "document_name": row.get("document_name"),
        "has_document": bool(row.get("has_document")),
        "notes": row.get("description"),
    }


def _database_name() -> str:
    """The database actually being read, whichever connection route won."""
    url = cms_db.database_url()
    if url:
        # Just the path segment; the rest of the URL carries the password.
        tail = url.rsplit("/", 1)[-1]
        return tail.split("?", 1)[0] or "unknown"
    return os.getenv("CMS_PG_DATABASE", "").strip() or "unknown"


def _environment() -> str:
    """'production', 'uat' or 'unknown', inferred from the database name.

    Inferred rather than configured so it cannot be set to one thing while the
    connection points at another — the label is derived from the same value the
    query uses.
    """
    name = _database_name().lower()
    if "prod" in name:
        return "production"
    if "uat" in name or "test" in name or "stag" in name:
        return "uat"
    return "unknown"


def _summarise(raw: dict[str, Any], origin: str) -> dict[str, Any]:
    contracts = list(raw.get("contracts") or [])
    live = [c for c in contracts if not c.get("is_deleted")]
    deleted = [c for c in contracts if c.get("is_deleted")]
    status_counts: dict[str, int] = {}
    for row in live:
        key = row.get("status") or "unknown"
        status_counts[key] = status_counts.get(key, 0) + 1

    recorded = sum(_num(c.get("value")) for c in live)
    active_recorded = sum(
        _num(c.get("value"))
        for c in live
        if (c.get("status") or "") in {"active", "expiring"}
    )
    alerts = raw.get("alerts") or {}
    return {
        "source": origin,
        # Which database these numbers came from. UAT and production do diverge
        # — they differ by two contracts today — so a figure quoted out of this
        # app needs its environment attached, or someone eventually negotiates
        # against test data believing it is the real book.
        "database": _database_name(),
        "environment": _environment(),
        "connected": True,
        "fetched_at": raw.get("fetched_at"),
        "live_contracts": len(live),
        "soft_deleted": len(deleted),
        "status_counts": status_counts,
        "recorded_value": round(recorded, 2),
        "active_recorded_value": round(active_recorded, 2),
        "vendors": len(raw.get("vendors") or []),
        "departments": len(raw.get("departments") or []),
        "legal_entities": len(raw.get("legal_entities") or []),
        "users": len(raw.get("users") or []),
        "attachments": len(raw.get("attachments") or []),
        "embeddings": len(raw.get("embeddings") or []),
        "expiry_alerts_sent": int(alerts.get("sent") or 0),
        "alert_contracts": int(alerts.get("contracts") or 0),
    }


def _public_users(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop anything that could be a credential. CMS stores bcrypt in `password`."""
    keep = ("id", "username", "name", "email", "is_admin", "status", "department_id", "geo_id", "last_login_at")
    return [{k: _jsonable(row.get(k)) for k in keep} for row in rows]


def _shape(raw: dict[str, Any], origin: str) -> dict[str, Any]:
    live = [c for c in (raw.get("contracts") or []) if not c.get("is_deleted")]
    software = [contract_to_item(c) for c in live]
    summary = _summarise(raw, origin)
    return {
        "summary": summary,
        "software": software,
        "contracts": live,
        "vendors": raw.get("vendors") or [],
        "departments": raw.get("departments") or [],
        "legal_entities": raw.get("legal_entities") or [],
        "users": _public_users(raw.get("users") or []),
        "attachments": raw.get("attachments") or [],
        "embeddings": raw.get("embeddings") or [],
        "alerts": raw.get("alerts") or {"sent": 0, "contracts": 0},
    }


def _save_snapshot(raw: dict[str, Any], origin: str) -> None:
    SNAPSHOT_FILE.parent.mkdir(parents=True, exist_ok=True)
    payload = {"origin": origin, "raw": raw}
    SNAPSHOT_FILE.write_text(json.dumps(payload, default=_jsonable) + "\n", encoding="utf-8")


def _load_snapshot() -> dict[str, Any] | None:
    if not SNAPSHOT_FILE.is_file():
        return None
    try:
        payload = json.loads(SNAPSHOT_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("CMS snapshot unreadable: %s", exc)
        return None
    raw = payload.get("raw") if isinstance(payload, dict) else None
    if not isinstance(raw, dict):
        return None
    origin = payload.get("origin") or "snapshot"
    shaped = _shape(raw, f"snapshot:{origin}")
    return shaped


def _fetch_raw() -> tuple[dict[str, Any], str]:
    raw, origin = cms_db.fetch_json(_PORTFOLIO_SQL)
    if not isinstance(raw, dict):
        raise RuntimeError("CMS query did not return a JSON object")
    return raw, origin


def load_portfolio(*, force: bool = False) -> dict[str, Any] | None:
    """Return the shaped CMS portfolio, or None if nothing could be loaded."""
    global _CACHE, _CACHE_AT
    if not force and _CACHE is not None and (_now() - _CACHE_AT) < CACHE_SECONDS:
        return _CACHE

    try:
        raw, origin = _fetch_raw()
        shaped = _shape(raw, origin)
        try:
            _save_snapshot(raw, origin)
        except OSError as exc:
            log.warning("Could not write CMS snapshot: %s", exc)
        _CACHE = shaped
        _CACHE_AT = _now()
        return shaped
    except Exception as exc:
        log.warning("Live CMS fetch failed: %s", exc)
        snapshot = _load_snapshot()
        if snapshot:
            _CACHE = snapshot
            _CACHE_AT = _now()
            return snapshot
        return None


def refresh() -> dict[str, Any] | None:
    return load_portfolio(force=True)


def status() -> dict[str, Any]:
    portfolio = load_portfolio()
    if not portfolio:
        return {
            "connected": False,
            "source": None,
            "detail": "CMS database is not reachable and no snapshot is cached.",
        }
    summary = portfolio["summary"]
    return {"connected": True, **summary}


_EXCERPT_CACHE: dict[str, dict[str, Any] | None] = {}


def embedding_text(contract_id: str) -> dict[str, Any] | None:
    """Fetch the extracted excerpt for one contract.

    Cached for the process lifetime. Without it, a chat turn with a contract
    open pays a fresh `docker exec` — a second or more — on every single
    message, and the excerpt only changes when the document is re-processed.
    """
    if contract_id in _EXCERPT_CACHE:
        return _EXCERPT_CACHE[contract_id]
    result = _fetch_embedding_text(contract_id)
    _EXCERPT_CACHE[contract_id] = result
    return result


def _fetch_embedding_text(contract_id: str) -> dict[str, Any] | None:
    try:
        safe_id = cms_db.require_uuid(contract_id)
    except ValueError:
        return None
    sql = """
    SELECT json_build_object(
      'contract_id', contract_id,
      'model', model,
      'content_hash', content_hash,
      'embedded_text', left(embedded_text, 1300),
      'created_at', created_at
    )
    FROM contract_embeddings
    WHERE contract_id = %s
    ORDER BY created_at DESC
    LIMIT 1
    """
    try:
        raw, _origin = cms_db.fetch_json(sql, (safe_id,))
    except Exception as exc:
        log.warning("embedding_text failed: %s", exc)
        return None
    return raw if isinstance(raw, dict) else None
