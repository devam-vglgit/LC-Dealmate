"""The negotiation agent: Claude + server-side web search, streamed."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncIterator

from anthropic import AsyncAnthropic, APIStatusError, APIConnectionError

from .prompts import SYSTEM_PROMPT

MODEL = os.getenv("LC_MODEL", "claude-opus-5")
EFFORT = os.getenv("LC_EFFORT", "high")
MAX_TOKENS = int(os.getenv("LC_MAX_TOKENS", "16000"))

# Server-side fallback: if a safety classifier declines a request, the API retries it
# on Anthropic's recommended fallback model instead of returning the refusal.
ENABLE_FALLBACK = os.getenv("LC_ENABLE_FALLBACK", "1") != "0"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

# A server-tool turn can stop with `pause_turn` before it is finished; re-send to resume.
MAX_CONTINUATIONS = 4

# `overloaded_error` arrives inside an already-open stream, so the SDK's own retry logic
# never sees it — we retry here instead.
OVERLOAD_RETRIES = 3

# Markdown that only renders correctly at the start of a line.
_BLOCK_MARKDOWN = re.compile(r"^\s*(#{1,6}\s|\||>\s?|[-*+]\s|\d+\.\s)")

WEB_SEARCH_TOOL = {
    "type": "web_search_20260209",
    "name": "web_search",
    "max_uses": 10,
}

client = AsyncAnthropic()

NO_CREDENTIALS = (
    "No Anthropic API key found. Put ANTHROPIC_API_KEY=sk-ant-... in backend/.env "
    "and restart the server."
)


def credentials_configured() -> bool:
    return bool(client.api_key or client.auth_token)


def _build_system(inventory_block: str, focus_block: str | None) -> list[dict[str, Any]]:
    # Stable prompt first, inventory second — both cached, so only the conversation
    # tail is re-processed on each turn. The focus block (which software the user has
    # open in the UI) varies per request and goes after the cache breakpoint, so it
    # doesn't invalidate the cached prefix above it.
    system = [
        {"type": "text", "text": SYSTEM_PROMPT},
        {"type": "text", "text": inventory_block, "cache_control": {"type": "ephemeral"}},
    ]
    if focus_block:
        system.append({"type": "text", "text": focus_block})
    return system


def _is_overloaded(e: APIStatusError) -> bool:
    """An in-stream overload surfaces as APIStatusError with status_code 200."""
    if e.status_code == 529:
        return True
    body = getattr(e, "body", None)
    if isinstance(body, dict):
        return (body.get("error") or {}).get("type") == "overloaded_error"
    return "overloaded" in str(e).lower()


def _usage_event(totals: dict[str, int], pending_output: int = 0, final: bool = False):
    """Token counts so far. `final` marks the exact end-of-turn numbers; before that
    the output count is whatever the API has reported, which it only sends once per
    message — the UI estimates between those points."""
    return {
        "type": "usage",
        "final": final,
        "input_tokens": totals["input_tokens"],
        "output_tokens": totals["output_tokens"] + pending_output,
        "cache_read_input_tokens": totals["cache_read_input_tokens"],
        "cache_creation_input_tokens": totals["cache_creation_input_tokens"],
    }


def _queries_from(content: list[Any]) -> list[str]:
    """The actual search queries. Server tools don't stream their input as deltas, so
    this is only available once the turn's final message is assembled."""
    out: list[str] = []
    for block in content:
        if getattr(block, "type", None) != "server_tool_use":
            continue
        params = getattr(block, "input", None)
        query = params.get("query") if isinstance(params, dict) else None
        if query:
            out.append(query)
    return out


def _sources_from(content: list[Any]) -> list[dict[str, str]]:
    """Pulls deduped {title, url} out of any web_search_tool_result blocks."""
    seen: set[str] = set()
    out: list[dict[str, str]] = []
    for block in content:
        if getattr(block, "type", None) != "web_search_tool_result":
            continue
        results = block.content
        # On error `content` is a single object, not a list of results.
        if not isinstance(results, list):
            continue
        for r in results:
            url = getattr(r, "url", None)
            if not url or url in seen:
                continue
            seen.add(url)
            out.append({"url": url, "title": getattr(r, "title", None) or url})
    return out


async def stream_reply(
    messages: list[dict[str, Any]],
    inventory_block: str,
    focus_block: str | None = None,
) -> AsyncIterator[dict[str, Any]]:
    """Yields UI events for one user turn, retrying transient API overloads.

    A retry only happens before any text has reached the client — once the answer has
    started streaming, restarting it would duplicate output, so a late failure is
    reported instead.
    """
    if not credentials_configured():
        yield {"type": "error", "message": NO_CREDENTIALS}
        return

    for attempt in range(1, OVERLOAD_RETRIES + 2):
        produced = False
        try:
            async for event in _run_turn(messages, inventory_block, focus_block):
                if event["type"] == "text":
                    produced = True
                yield event
            return

        except APIStatusError as e:
            retriable = _is_overloaded(e) or e.status_code in (429, 500, 502, 503, 529)
            if retriable and not produced and attempt <= OVERLOAD_RETRIES:
                yield {
                    "type": "status",
                    "message": f"Anthropic's API is busy — retrying ({attempt}/{OVERLOAD_RETRIES})…",
                }
                await asyncio.sleep(1.5 * attempt)
                continue
            if _is_overloaded(e):
                yield {
                    "type": "error",
                    "message": "Anthropic's API is overloaded right now. Wait a few seconds "
                    "and ask again.",
                }
            else:
                yield {"type": "error", "message": f"API error {e.status_code}: {e.message}"}
            return

        except APIConnectionError:
            yield {
                "type": "error",
                "message": "Could not reach the Claude API. Check your connection.",
            }
            return
        except Exception as e:  # never let the SSE stream die without telling the client
            logging.exception("agent stream failed")
            yield {"type": "error", "message": f"{type(e).__name__}: {e}"}
            return


async def _run_turn(
    messages: list[dict[str, Any]],
    inventory_block: str,
    focus_block: str | None,
) -> AsyncIterator[dict[str, Any]]:
    """One full turn, including any pause_turn continuations. Lets errors propagate."""
    system = _build_system(inventory_block, focus_block)
    convo: list[dict[str, Any]] = list(messages)

    request: dict[str, Any] = {
        "model": MODEL,
        "max_tokens": MAX_TOKENS,
        "system": system,
        "tools": [WEB_SEARCH_TOOL],
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": EFFORT},
    }
    if ENABLE_FALLBACK:
        request["betas"] = [FALLBACK_BETA]
        request["fallbacks"] = "default"

    stream_fn = client.beta.messages.stream if ENABLE_FALLBACK else client.messages.stream

    # A turn emits several text blocks — one before each search, one after — and they
    # carry no separator. Usually the model resumes mid-sentence (or mid-table-row) and
    # the blocks must be joined with nothing. But when the previous block ended on a
    # heading, or the next opens block-level markdown, a missing break corrupts the
    # rendering. Track just enough state to tell those cases apart.
    open_line = ""  # current line so far; "" means we're at a fresh line
    prev_was_heading = False
    had_text = False
    awaiting_block_start = False

    # Accumulated across pause_turn continuations, so a multi-round research turn
    # reports one running total rather than restarting the count each round.
    totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
    }

    for _ in range(MAX_CONTINUATIONS):
        turn_output = 0
        async with stream_fn(messages=convo, **request) as stream:
            async for event in stream:
                if event.type == "message_start":
                    u = getattr(event.message, "usage", None)
                    if u is not None:
                        totals["input_tokens"] += getattr(u, "input_tokens", 0) or 0
                        totals["cache_read_input_tokens"] += (
                            getattr(u, "cache_read_input_tokens", 0) or 0
                        )
                        totals["cache_creation_input_tokens"] += (
                            getattr(u, "cache_creation_input_tokens", 0) or 0
                        )
                        yield _usage_event(totals)

                elif event.type == "message_delta":
                    u = getattr(event, "usage", None)
                    out = getattr(u, "output_tokens", None) if u is not None else None
                    if out is not None:
                        turn_output = out
                        yield _usage_event(totals, pending_output=out)

                elif event.type == "content_block_start":
                    kind = event.content_block.type
                    if kind == "server_tool_use":
                        # Placeholder — the query itself is only known after the turn.
                        yield {"type": "search_start"}
                    elif kind == "thinking":
                        yield {"type": "thinking_start"}
                    elif kind == "text":
                        awaiting_block_start = had_text and bool(open_line)

                elif event.type == "content_block_delta":
                    delta = event.delta
                    if delta.type == "text_delta":
                        chunk = delta.text
                        if not chunk:
                            continue
                        if awaiting_block_start:
                            awaiting_block_start = False
                            if prev_was_heading or _BLOCK_MARKDOWN.match(chunk):
                                yield {"type": "text", "text": "\n\n"}
                                open_line = ""
                        open_line = (open_line + chunk).rsplit("\n", 1)[-1]
                        had_text = True
                        yield {"type": "text", "text": chunk}
                    elif delta.type == "thinking_delta":
                        yield {"type": "thinking", "text": delta.thinking}

                elif event.type == "content_block_stop":
                    if had_text:
                        prev_was_heading = open_line.lstrip().startswith("#")

            final = await stream.get_final_message()

        totals["output_tokens"] += turn_output

        queries = _queries_from(final.content)
        if queries:
            yield {"type": "searches", "queries": queries}

        sources = _sources_from(final.content)
        if sources:
            yield {"type": "sources", "items": sources}

        if final.stop_reason == "refusal":
            yield {
                "type": "error",
                "message": "That request was declined by the model's safety systems. "
                "Try rephrasing it.",
            }
            return

        if final.stop_reason != "pause_turn":
            yield _usage_event(totals, final=True)
            return

        # Paused mid-turn: append the partial assistant turn and resume it.
        convo.append({"role": "assistant", "content": final.content})

    yield {"type": "error", "message": "The research loop did not finish — ask a narrower question."}
