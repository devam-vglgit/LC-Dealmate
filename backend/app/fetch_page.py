"""Fetch a live official vendor page so facts are read from the page, not memory."""

from __future__ import annotations

import html
import ipaddress
import re
import socket
import ssl
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

MAX_BYTES = 400_000
MAX_CHARS = 12_000
TIMEOUT = 12
MAX_REDIRECTS = 5

_BLOCKED_HOST_SUFFIXES = (
    "wikipedia.org",
    "fandom.com",
    "g2.com",
    "g2crowd.com",
    "capterra.com",
    "trustradius.com",
    "softwareadvice.com",
    "aitools.fyi",
    "producthunt.com",
    "reddit.com",
    "medium.com",
    "quora.com",
    "youtube.com",
    "facebook.com",
    "x.com",
    "twitter.com",
    "linkedin.com",
)

_SKIP_TAGS = frozenset({"script", "style", "noscript", "svg", "nav", "footer", "header"})


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in {"p", "div", "tr", "li", "h1", "h2", "h3", "br", "table"}:
            self.parts.append("\n")
        elif tag == "td" or tag == "th":
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP_TAGS and self._skip:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        text = data.strip()
        if text:
            self.parts.append(text)


def _host_blocked(host: str) -> bool:
    h = host.lower().rstrip(".")
    if h.startswith("www."):
        h = h[4:]
    for suffix in _BLOCKED_HOST_SUFFIXES:
        if h == suffix or h.endswith("." + suffix):
            return True
    return False


def _resolve_public(host: str) -> None:
    if not host or host.lower() in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("That host is not allowed")
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve {host}") from exc
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            raise ValueError("That host is not allowed")


def _html_to_text(raw: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(raw)
        parser.close()
    except Exception:
        stripped = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", raw)
        stripped = re.sub(r"(?is)<[^>]+>", " ", stripped)
        return html.unescape(re.sub(r"\s+", " ", stripped)).strip()
    text = " ".join(parser.parts)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def fetch_official_page(url: str) -> str:
    """Return visible text from an official HTTPS page, or an error the model can use."""
    try:
        return _fetch_official_page(url)
    except Exception as exc:
        return f"ERROR: Could not read that page ({type(exc).__name__})."


def _fetch_official_page(url: str) -> str:
    """Return visible text from an official HTTPS page, or an error the model can use."""
    current = (url or "").strip()
    if not current:
        return "ERROR: No URL was provided."

    seen: set[str] = set()
    for _ in range(MAX_REDIRECTS):
        parsed = urlparse(current)
        if parsed.scheme != "https" or not parsed.netloc:
            return "ERROR: Only https URLs on a public host are allowed."
        host = parsed.hostname or ""
        if _host_blocked(host):
            return (
                "ERROR: Review and directory sites are not allowed. "
                "Use the vendor's own pricing or product page."
            )
        try:
            _resolve_public(host)
        except ValueError as exc:
            return f"ERROR: {exc}"

        if current in seen:
            return "ERROR: Redirect loop."
        seen.add(current)

        req = Request(
            current,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.8",
            },
            method="GET",
        )
        ctx = ssl.create_default_context()
        try:
            with urlopen(req, timeout=TIMEOUT, context=ctx) as resp:
                final_url = resp.geturl() or current
                content_type = (resp.headers.get("Content-Type") or "").lower()
                data = resp.read(MAX_BYTES + 1)
        except HTTPError as exc:
            if exc.code in {301, 302, 303, 307, 308}:
                loc = exc.headers.get("Location")
                if not loc:
                    return f"ERROR: HTTP {exc.code} with no redirect."
                current = urljoin(current, loc)
                continue
            return f"ERROR: HTTP {exc.code} fetching {current}"
        except (URLError, TimeoutError, ssl.SSLError) as exc:
            return f"ERROR: Could not fetch {current}: {exc}"

        if len(data) > MAX_BYTES:
            data = data[:MAX_BYTES]
        if "html" not in content_type and "text" not in content_type and content_type:
            return f"ERROR: Unsupported content type {content_type} at {final_url}"

        raw = data.decode("utf-8", errors="replace")
        text = _html_to_text(raw)
        if not text:
            return f"ERROR: Page had no readable text: {final_url}"
        if len(text) > MAX_CHARS:
            text = text[:MAX_CHARS].rsplit(" ", 1)[0] + "…"
        return f"URL: {final_url}\n\n{text}"

    return "ERROR: Too many redirects."


# Older prompt/tool name.
fetch_pricing_page = fetch_official_page
