"""Serves the single-file UI under a Content-Security-Policy built from its own contents."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

from fastapi.responses import HTMLResponse

_INDEX = Path(__file__).parent / "static" / "index.html"


def _source_hash(html: bytes, tag: bytes) -> str:
    match = re.search(b"<" + tag + b">(.*?)</" + tag + b">", html, re.DOTALL)
    if match is None:
        raise ValueError(f"index.html has no <{tag.decode()}> element")
    digest = hashlib.sha256(match.group(1)).digest()
    return f"'sha256-{base64.b64encode(digest).decode()}'"


def load_index_page() -> HTMLResponse:
    """Build the response once. Hashes let exactly this page's code run, so even an injection
    that slipped past textContent couldn't execute a script or exfiltrate anything."""
    html = _INDEX.read_bytes()
    policy = "; ".join(
        (
            "default-src 'none'",
            f"script-src {_source_hash(html, b'script')}",
            f"style-src {_source_hash(html, b'style')}",
            "connect-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        )
    )
    return HTMLResponse(
        html,
        headers={
            "Content-Security-Policy": policy,
            "X-Content-Type-Options": "nosniff",
            "Referrer-Policy": "no-referrer",
        },
    )
