"""Persisted chat conversations.

The server is the source of truth for history: the client sends only the new
message, and the full prior conversation is replayed to the model from here. That
is what makes the agent remember, and what makes a conversation survive a browser
refresh or a server restart.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent.parent / "data" / "conversations.json"

# Every read-modify-write goes through this. Single-process app, so a plain lock
# is enough to stop two concurrent turns clobbering each other's appends.
_LOCK = threading.Lock()

MAX_TITLE_CHARS = 60


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read() -> dict[str, Any]:
    if not DATA_FILE.exists():
        return {"conversations": []}
    try:
        with DATA_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        # A corrupt file shouldn't take the whole app down — start clean rather
        # than 500 on every request.
        return {"conversations": []}
    if not isinstance(data, dict) or not isinstance(data.get("conversations"), list):
        return {"conversations": []}
    return data


def _write(data: dict[str, Any]) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    # Write-then-replace so an interrupted write can't leave a truncated file.
    tmp = DATA_FILE.with_name(DATA_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(DATA_FILE)


def title_from(text: str) -> str:
    """A conversation's title is the opening line of its first question."""
    line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    if not line:
        return "New chat"
    return line if len(line) <= MAX_TITLE_CHARS else line[: MAX_TITLE_CHARS - 1].rstrip() + "…"


def _summary(conv: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": conv["id"],
        "title": conv.get("title") or "New chat",
        "focus_id": conv.get("focus_id"),
        "attachment": (
            {"id": conv["attachment_id"], "filename": conv.get("attachment_filename")}
            if conv.get("attachment_id")
            else None
        ),
        "created_at": conv.get("created_at"),
        "updated_at": conv.get("updated_at"),
        "message_count": len(conv.get("messages", [])),
    }


def list_summaries() -> list[dict[str, Any]]:
    """Newest activity first — that's the order the sidebar shows."""
    with _LOCK:
        convs = _read()["conversations"]
    convs.sort(key=lambda c: c.get("updated_at") or "", reverse=True)
    return [_summary(c) for c in convs]


def get(conversation_id: str) -> dict[str, Any] | None:
    with _LOCK:
        for conv in _read()["conversations"]:
            if conv.get("id") == conversation_id:
                return conv
    return None


def create(title: str, focus_id: str | None = None) -> dict[str, Any]:
    conv = {
        "id": f"conv-{uuid.uuid4().hex[:10]}",
        "title": title or "New chat",
        "focus_id": focus_id,
        "attachment_id": None,
        "attachment_filename": None,
        "created_at": _now(),
        "updated_at": _now(),
        "messages": [],
    }
    with _LOCK:
        data = _read()
        data["conversations"].append(conv)
        _write(data)
    return conv


def set_attachment(conversation_id: str, attachment_id: str, filename: str) -> None:
    with _LOCK:
        data = _read()
        for conv in data["conversations"]:
            if conv.get("id") == conversation_id:
                conv["attachment_id"] = attachment_id
                conv["attachment_filename"] = filename
                conv["updated_at"] = _now()
                _write(data)
                return


def append_message(conversation_id: str, message: dict[str, Any]) -> None:
    with _LOCK:
        data = _read()
        for conv in data["conversations"]:
            if conv.get("id") == conversation_id:
                conv.setdefault("messages", []).append(message)
                conv["updated_at"] = _now()
                _write(data)
                return


def rename(conversation_id: str, title: str) -> dict[str, Any] | None:
    with _LOCK:
        data = _read()
        for conv in data["conversations"]:
            if conv.get("id") == conversation_id:
                conv["title"] = title.strip()[:MAX_TITLE_CHARS] or "New chat"
                conv["updated_at"] = _now()
                _write(data)
                return conv
    return None


def delete(conversation_id: str) -> bool:
    with _LOCK:
        data = _read()
        kept = [c for c in data["conversations"] if c.get("id") != conversation_id]
        if len(kept) == len(data["conversations"]):
            return False
        data["conversations"] = kept
        _write(data)
    return True


def history_for_model(conversation_id: str) -> list[dict[str, Any]]:
    """Role/content pairs only. UI fields (searches, sources) are stripped."""
    conv = get(conversation_id)
    if not conv:
        return []
    out: list[dict[str, Any]] = []
    for m in conv.get("messages", []):
        role, content = m.get("role"), m.get("content")
        if role not in ("user", "assistant") or not content:
            continue
        out.append({"role": role, "content": content})
    return out
