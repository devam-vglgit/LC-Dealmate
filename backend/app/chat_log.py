"""Append-only log of each chat turn: question asked and answer given.

Written to backend/data/chat.log.jsonl (gitignored) and echoed to the
server console so operators can see traffic without opening the file.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOG_FILE = Path(__file__).resolve().parent.parent / "data" / "chat.log.jsonl"
_LOCK = threading.Lock()
_log = logging.getLogger("dealmate.chat")
if not _log.handlers:
    _handler = logging.StreamHandler()
    _handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    _log.addHandler(_handler)
    _log.setLevel(logging.INFO)
    _log.propagate = False

CONSOLE_SNIP = 240


def enabled() -> bool:
    return os.getenv("LC_CHAT_LOG", "1").strip().lower() not in {"0", "false", "no", "off"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _snip(text: str | None, limit: int = CONSOLE_SNIP) -> str:
    value = (text or "").replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[: limit - 1].rstrip() + "…"


def record(entry: dict[str, Any]) -> None:
    """Persist one Q&A turn. Never raises — logging must not break chat."""
    if not enabled():
        return
    row = {"at": _now(), **entry}
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(row, ensure_ascii=False) + "\n"
        with _LOCK:
            with LOG_FILE.open("a", encoding="utf-8") as f:
                f.write(line)
        q = _snip(row.get("question"))
        a = _snip(row.get("answer"))
        err = row.get("error")
        user = row.get("user") or "unknown"
        conv = row.get("conversation_id") or "-"
        if err and not a:
            _log.info("chat user=%s conv=%s Q=%s ERROR=%s", user, conv, q, _snip(str(err)))
        else:
            _log.info("chat user=%s conv=%s Q=%s A=%s", user, conv, q, a)
    except Exception:
        _log.exception("failed to write chat log")
