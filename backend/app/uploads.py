"""Chat-only PDF attachments. Not written to CMS. The binary stays on disk;
the model receives extracted text only."""

from __future__ import annotations

import json
import re
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pypdf import PdfReader

DATA_DIR = Path(__file__).resolve().parent.parent / "data" / "uploads"
INDEX_FILE = DATA_DIR / "index.json"

MAX_BYTES = 15 * 1024 * 1024
MAX_CHARS = 16000
MAX_PAGES = 40

_LOCK = threading.Lock()


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _read_index() -> dict[str, Any]:
    if not INDEX_FILE.exists():
        return {"files": []}
    try:
        with INDEX_FILE.open(encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {"files": []}
    if not isinstance(data, dict) or not isinstance(data.get("files"), list):
        return {"files": []}
    return data


def _write_index(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = INDEX_FILE.with_name(INDEX_FILE.name + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(INDEX_FILE)


def _safe_name(name: str) -> str:
    base = Path(name or "document.pdf").name
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip() or "document.pdf"
    if not base.lower().endswith(".pdf"):
        base += ".pdf"
    return base[:180]


def _extract_text(data: bytes) -> str:
    from io import BytesIO

    try:
        reader = PdfReader(BytesIO(data))
    except Exception as exc:
        raise UploadError("That file is not a readable PDF.") from exc
    pages = reader.pages[:MAX_PAGES]
    parts: list[str] = []
    for page in pages:
        try:
            parts.append(page.extract_text() or "")
        except Exception:
            continue
    text = re.sub(r"[ \t]+", " ", "\n".join(parts))
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise UploadError(
            "This PDF has no extractable text. It may be a scan — paste the terms you need."
        )
    if len(text) > MAX_CHARS:
        text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
    return text


def save_pdf(filename: str, data: bytes) -> dict[str, Any]:
    if not data:
        raise UploadError("The file was empty.")
    if len(data) > MAX_BYTES:
        raise UploadError("PDF is too large (15 MB limit).")
    if not data.startswith(b"%PDF"):
        raise UploadError("Only PDF files can be attached.")

    text = _extract_text(data)
    file_id = f"att-{uuid.uuid4().hex[:12]}"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    path = DATA_DIR / f"{file_id}.pdf"
    path.write_bytes(data)

    record = {
        "id": file_id,
        "filename": _safe_name(filename),
        "text": text,
        "bytes": len(data),
        "created_at": _now(),
    }
    with _LOCK:
        index = _read_index()
        index["files"].append({k: record[k] for k in ("id", "filename", "bytes", "created_at")})
        _write_index(index)
        (DATA_DIR / f"{file_id}.txt").write_text(text, encoding="utf-8")
    return {"id": record["id"], "filename": record["filename"], "chars": len(text)}


def get(file_id: str) -> dict[str, Any] | None:
    if not file_id or not str(file_id).startswith("att-"):
        return None
    text_path = DATA_DIR / f"{file_id}.txt"
    pdf_path = DATA_DIR / f"{file_id}.pdf"
    if not text_path.is_file():
        return None
    filename = f"{file_id}.pdf"
    with _LOCK:
        for row in _read_index().get("files") or []:
            if row.get("id") == file_id:
                filename = row.get("filename") or filename
                break
    return {
        "id": file_id,
        "filename": filename,
        "text": text_path.read_text(encoding="utf-8"),
        "path": pdf_path if pdf_path.is_file() else None,
    }


def public_meta(file_id: str | None) -> dict[str, str] | None:
    rec = get(file_id) if file_id else None
    if not rec:
        return None
    return {"id": rec["id"], "filename": rec["filename"]}
