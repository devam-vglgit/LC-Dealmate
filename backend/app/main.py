"""LC DealMate API."""

from __future__ import annotations

import json
import os
from typing import Any, Literal

from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

# Anchored to backend/.env, not the working directory — otherwise the key is invisible
# when the server is launched from the project root via `--app-dir backend`.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from . import auth  # noqa: E402  (reads credentials at import — must follow load_dotenv)
from . import conversations as conv_mod  # noqa: E402
from . import inventory as inv_mod  # noqa: E402
from .agent import MODEL, credentials_configured, stream_reply  # noqa: E402

app = FastAPI(title="LC DealMate", version="0.1.0")

# Local dev origins are always allowed; a deployed frontend (e.g. Netlify) adds
# its own via LC_CORS_ORIGINS, comma-separated.
_DEV_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5174", "http://127.0.0.1:5174",
]
_EXTRA_ORIGINS = [o.strip() for o in os.getenv("LC_CORS_ORIGINS", "").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_DEV_ORIGINS + _EXTRA_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Reachable without a token: the login exchange itself, and health (so the UI can
# discover whether auth is even switched on before showing a form).
PUBLIC_PATHS = {"/api/login", "/api/health"}


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


class ChatRequest(BaseModel):
    # Only the new message — the server owns the history, so the model always
    # sees the full prior conversation and the client can't desync it.
    message: str = Field(min_length=1)
    conversation_id: str | None = None
    focus_id: str | None = None


class RenameRequest(BaseModel):
    title: str = Field(min_length=1)


class SoftwareIn(BaseModel):
    vendor: str = Field(min_length=1)
    product: str = Field(min_length=1)
    category: str | None = None
    plan: str | None = None
    seats: int | None = Field(default=None, ge=0)
    unit_price_annual: float | None = Field(default=None, ge=0)
    annual_cost: float | None = Field(default=None, ge=0)
    contract_start: str | None = None
    renewal_date: str | None = None
    auto_renew: bool | None = None
    notice_period_days: int | None = Field(default=None, ge=0)
    owner: str | None = None
    business_criticality: Literal["low", "medium", "high"] | None = None
    utilization_pct: float | None = Field(default=None, ge=0, le=100)
    notes: str | None = None


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "model": MODEL,
        "credentials": credentials_configured(),
        "auth_required": auth.enabled(),
    }


@app.post("/api/login")
def login(req: LoginRequest) -> dict[str, Any]:
    if not auth.enabled():
        raise HTTPException(status_code=400, detail="Login is not configured on this server")
    if not auth.check_credentials(req.username, req.password):
        raise HTTPException(status_code=401, detail="Incorrect username or password")
    return {"token": auth.issue_token(req.username), "expires_in": auth.SESSION_SECONDS}


@app.get("/api/inventory")
def get_inventory() -> dict[str, Any]:
    return inv_mod.enrich(inv_mod.load_inventory())


@app.post("/api/inventory", status_code=201)
def add_software(item: SoftwareIn) -> dict[str, Any]:
    # Only keep fields the caller actually supplied — no null clutter in the JSON file.
    payload = item.model_dump(exclude_none=True)
    inv_mod.add_item(payload)
    return inv_mod.enrich(inv_mod.load_inventory())


@app.delete("/api/inventory/{item_id}")
def remove_software(item_id: str) -> dict[str, Any]:
    if not inv_mod.delete_item(item_id):
        raise HTTPException(status_code=404, detail="No software entry with that id")
    return inv_mod.enrich(inv_mod.load_inventory())


@app.get("/api/conversations")
def list_conversations() -> dict[str, Any]:
    return {"conversations": conv_mod.list_summaries()}


@app.get("/api/conversations/{conversation_id}")
def get_conversation(conversation_id: str) -> dict[str, Any]:
    conv = conv_mod.get(conversation_id)
    if conv is None:
        raise HTTPException(status_code=404, detail="No conversation with that id")
    return conv


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


@app.post("/api/chat")
async def chat(req: ChatRequest) -> StreamingResponse:
    # Reloaded per request so edits to the inventory file take effect without a restart.
    enriched = inv_mod.enrich(inv_mod.load_inventory())
    block = inv_mod.as_context_block(enriched)

    conv = conv_mod.get(req.conversation_id) if req.conversation_id else None
    if conv is None:
        conv = conv_mod.create(conv_mod.title_from(req.message), focus_id=req.focus_id)
    conv_id = conv["id"]

    # An explicit focus wins; otherwise inherit whatever the conversation was started on.
    focus_id = req.focus_id or conv.get("focus_id")

    conv_mod.append_message(conv_id, {"role": "user", "content": req.message})
    history = conv_mod.history_for_model(conv_id)

    focus_block = None
    if focus_id:
        item = inv_mod.find_item(enriched, focus_id)
        if item:
            focus_block = inv_mod.as_focus_block(item)

    def frame(payload: dict[str, Any]) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    async def sse():
        yield frame({
            "type": "conversation",
            "id": conv_id,
            "title": conv.get("title"),
            "focus_id": focus_id,
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
