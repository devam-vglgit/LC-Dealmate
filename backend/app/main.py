"""LC DealMate API."""

from __future__ import annotations

import json
import os
from typing import Any

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

# Anchored to backend/.env, not the working directory — otherwise the key is invisible
# when the server is launched from the project root via `--app-dir backend`.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import auth  # noqa: E402  (reads credentials at import — must follow load_dotenv)
from . import cms as cms_mod  # noqa: E402
from . import cms_files as cms_files_mod  # noqa: E402
from . import conversations as conv_mod  # noqa: E402
from . import inventory as inv_mod  # noqa: E402
from . import uploads as uploads_mod  # noqa: E402
from .agent import (  # noqa: E402
    MODEL,
    credentials_configured,
    stream_reply,
)

app = FastAPI(title="LC DealMate", version="0.1.0")

# Local Vite plus CMS origins. Extra hosts via LC_CORS_ORIGINS, comma-separated.
_DEV_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5174", "http://127.0.0.1:5174",
    "http://localhost:38090", "http://127.0.0.1:38090",
    "https://contractsuat.shoplc.com",
    "https://contracts.shoplc.com",
]
_EXTRA_ORIGINS = [o.strip() for o in os.getenv("LC_CORS_ORIGINS", "").split(",") if o.strip()]
_FRAME_ANCESTORS = os.getenv(
    "LC_FRAME_ANCESTORS",
    "https://contractsuat.shoplc.com https://contracts.shoplc.com "
    "http://localhost:38090 http://127.0.0.1:38090",
).strip()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS + _EXTRA_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    # CMS loads DealMate in an iframe. X-Frame-Options: DENY would block that.
    response.headers["Content-Security-Policy"] = f"frame-ancestors 'self' {_FRAME_ANCESTORS}"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    return response


# Reachable without a token: the login exchange itself, and health (so the UI can
# discover whether auth is even switched on before showing a form).
PUBLIC_PATHS = {"/api/login", "/api/health", "/api/auth/cms"}


@app.middleware("http")
async def require_auth(request: Request, call_next):
    path = request.url.path
    if (
        not auth.enabled()
        or request.method == "OPTIONS"  # never block the CORS preflight
        or not path.startswith("/api")
        or path in PUBLIC_PATHS
    ):
        return await call_next(request)

    token = auth.token_from_header(request.headers.get("authorization"))
    if not auth.verify_token(token):
        return JSONResponse({"detail": "Not authenticated"}, status_code=401)
    return await call_next(request)


class LoginRequest(BaseModel):
    username: str
    password: str


class CmsHandoff(BaseModel):
    token: str = Field(min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    focus_id: str | None = None
    attachment_id: str | None = None


class RenameRequest(BaseModel):
    title: str = Field(min_length=1)


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL,
        "credentials": credentials_configured(),
        "auth_required": auth.enabled(),
        "password_login": auth.password_login_enabled(),
        "cms_handoff": auth.cms_handoff_enabled(),
        "cms": cms_mod.status(),
        "sends_contracts_to_model": inv_mod.sends_contracts(),
        "sends_documents_to_model": False,
    }


@app.post("/api/login")
def login(req: LoginRequest) -> dict[str, Any]:
    if not auth.password_login_enabled():
        raise HTTPException(status_code=400, detail="Password login is not configured on this server")
    if not auth.check_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"token": auth.issue_token(req.username), "expires_in": auth.SESSION_SECONDS}


@app.post("/api/auth/cms")
def cms_handoff(req: CmsHandoff) -> dict[str, Any]:
    """CMS opens DealMate with a short-lived JWT; this exchanges it for a session."""
    if not auth.cms_handoff_enabled():
        raise HTTPException(status_code=400, detail="CMS handoff is not configured (set CMS_EMBED_SECRET)")
    token = auth.exchange_cms_token(req.token)
    if not token:
        raise HTTPException(status_code=401, detail="Invalid or expired CMS token")
    return {"token": token, "expires_in": auth.SESSION_SECONDS}


@app.get("/api/inventory")
def get_inventory() -> dict[str, Any]:
    return inv_mod.enrich(inv_mod.load_inventory())


@app.get("/api/cms")
def cms_summary() -> dict[str, Any]:
    portfolio = cms_mod.load_portfolio()
    if not portfolio:
        raise HTTPException(status_code=503, detail="CMS database is not reachable")
    return portfolio["summary"]


@app.post("/api/cms/refresh")
def cms_refresh() -> dict[str, Any]:
    portfolio = cms_mod.refresh()
    if not portfolio:
        raise HTTPException(status_code=503, detail="CMS database is not reachable")
    return portfolio["summary"]


@app.get("/api/cms/contracts/{contract_id}/document")
def cms_contract_document(contract_id: str) -> Response:
    """Stream the CMS PDF to this browser only. It is not sent to the model."""
    try:
        data, filename, content_type = cms_files_mod.load_document(contract_id)
    except cms_files_mod.DocumentError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc

    ascii_name = "".join(ch if 32 <= ord(ch) < 127 and ch not in '\\"' else "_" for ch in filename)
    return Response(
        content=data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{ascii_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/conversations")
def list_conversations() -> dict[str, Any]:
    return {"conversations": conv_mod.list_summaries()}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    conv = conv_mod.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="No conversation with that id")
    out = dict(conv)
    out["attachment"] = uploads_mod.public_meta(conv.get("attachment_id"))
    return out


@app.post("/api/conversations/{conversation_id}/rename")
def rename_conversation(conversation_id: str, req: RenameRequest) -> dict[str, Any]:
    conv = conv_mod.rename(conversation_id, req.title)
    if conv is None:
        raise HTTPException(status_code=404, detail="No conversation with that id")
    return {"conversations": conv_mod.list_summaries()}


@app.delete("/api/conversations/{conversation_id}")
def delete_conversation(conversation_id: str) -> dict[str, Any]:
    if not conv_mod.delete(conversation_id):
        raise HTTPException(status_code=404, detail="No conversation with that id")
    return {"conversations": conv_mod.list_summaries()}


@app.post("/api/attachments")
async def upload_attachment(file: UploadFile = File(...)) -> dict[str, Any]:
    """Store a PDF for this chat and extract text for the model. Not written to CMS."""
    data = await file.read()
    try:
        return uploads_mod.save_pdf(file.filename or "document.pdf", data)
    except uploads_mod.UploadError as exc:
        raise HTTPException(status_code=exc.status, detail=str(exc)) from exc


@app.get("/api/attachments/{attachment_id}")
def get_attachment_file(attachment_id: str) -> Response:
    rec = uploads_mod.get(attachment_id)
    if not rec or not rec.get("path"):
        raise HTTPException(status_code=404, detail="Attachment not found")
    data = Path(rec["path"]).read_bytes()
    ascii_name = "".join(
        ch if 32 <= ord(ch) < 127 and ch not in '\\"' else "_"
        for ch in rec["filename"]
    )
    return Response(
        content=data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{ascii_name}"',
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    # What the model receives is decided entirely by LC_SEND_CONTRACTS_TO_MODEL.
    # Off: both blocks say the data is withheld and no CMS row is read at all.
    # On: de-identified rows via redact.py — never documents, which stay behind
    # /api/cms/.../document and reach the browser only.
    sending = inv_mod.sends_contracts()
    inv = inv_mod.enrich(inv_mod.load_inventory()) if sending else None
    block = inv_mod.as_context_block(inv)

    conv = conv_mod.get(req.conversation_id) if req.conversation_id else None
    if conv is None:
        conv = conv_mod.create(conv_mod.title_from(req.message), focus_id=req.focus_id)
    conv_id = conv["id"]

    focus_id = req.focus_id or conv.get("focus_id")
    focus_parts: list[str] = []
    if sending and focus_id and inv is not None:
        item = inv_mod.find_item(inv, focus_id)
        if item is not None:
            excerpt = None
            if item.get("source") == "cms":
                record = cms_mod.embedding_text(focus_id)
                excerpt = (record or {}).get("embedded_text")
            focus_parts.append(inv_mod.as_focus_block(item, excerpt, inv))

    attachment_id = req.attachment_id or conv.get("attachment_id")
    attachment = uploads_mod.get(attachment_id) if attachment_id else None
    if req.attachment_id and attachment is None:
        raise HTTPException(status_code=400, detail="That attachment is not available.")
    if attachment:
        conv_mod.set_attachment(conv_id, attachment["id"], attachment["filename"])
        focus_parts.append(
            inv_mod.as_attachment_block(attachment["filename"], attachment["text"], inv)
        )
    focus_block = "\n\n".join(focus_parts) or None

    user_message: dict[str, Any] = {"role": "user", "content": req.message}
    if attachment:
        user_message["attachment"] = attachment["filename"]
    conv_mod.append_message(conv_id, user_message)
    history = conv_mod.history_for_model(conv_id)

    def frame(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    async def sse():
        yield frame({
            "type": "conversation",
            "id": conv_id,
            "title": conv.get("title"),
            "focus_id": focus_id,
            "attachment": uploads_mod.public_meta(attachment["id"]) if attachment else None,
        })

        reply: dict[str, Any] = {"role": "assistant", "content": "", "searches": [], "sources": []}
        try:
            async for event in stream_reply(history, block, focus_block):
                kind = event["type"]
                if kind == "text":
                    reply["content"] += event["text"]
                elif kind == "searches":
                    reply["searches"] = event["queries"]
                elif kind == "sources":
                    reply["sources"] = event["items"]
                elif kind == "usage" and event.get("final"):
                    reply["usage"] = {k: v for k, v in event.items() if k.endswith("_tokens")}
                yield frame(event)
            yield frame({"type": "done"})
        finally:
            # Runs on normal completion *and* on client disconnect, so an
            # interrupted answer is still saved rather than silently lost.
            if reply["content"]:
                conv_mod.append_message(conv_id, reply)

    return StreamingResponse(
        sse(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# Production: CMS (or Docker) serves the built SPA from this same origin so the
# iframe does not need a second host or a Vite proxy.
_DIST = Path(__file__).resolve().parents[2] / "frontend" / "dist"


def _spa_file(name: str) -> FileResponse:
    target = (_DIST / name).resolve()
    if _DIST.resolve() not in target.parents and target != _DIST.resolve():
        raise HTTPException(status_code=404)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Frontend build is missing (npm run build in frontend/)")
    headers = {}
    if name == "index.html":
        headers["Cache-Control"] = "no-cache"
    return FileResponse(target, headers=headers)


if _DIST.is_dir():
    assets = _DIST / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/")
    def spa_root() -> FileResponse:
        return _spa_file("index.html")

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        if full_path == "api" or full_path.startswith("api/") or full_path in {"docs", "redoc", "openapi.json"}:
            raise HTTPException(status_code=404)
        candidate = _DIST / full_path
        if candidate.is_file():
            return _spa_file(full_path)
        return _spa_file("index.html")
