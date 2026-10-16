"""Request and path rules for the board. Pure functions, so tests can hit them without a socket."""
from __future__ import annotations

import hmac
import os
import re
from pathlib import Path
from typing import Iterable, Optional, Tuple
from urllib.parse import unquote

from ..fsutil import is_inside

LOOPBACK_NAMES = ("127.0.0.1", "localhost", "[::1]")
MAX_BODY = 20000
MAX_NOTE = 4000

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
FILE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,119}$")
MEDIA_TYPES = {".png": "image/png", ".gif": "image/gif", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
               ".webp": "image/webp"}
FONT_TYPES = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf"}
LINKEDIN_PREFIX = "https://www.linkedin.com/"

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
       "font-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'none'; "
       "frame-ancestors 'none'")


def safe_linkedin_url(value: object) -> Optional[str]:
    """A URL the UI may open: it must start with https://www.linkedin.com/ (no other scheme or host)."""
    if isinstance(value, str) and value.startswith(LINKEDIN_PREFIX) and not re.search(r"[\s\x00-\x1f]", value):
        return value
    return None


def host_allowed(host_header: Optional[str], port: int) -> bool:
    """The Host header must name a loopback host on the port we listen on (DNS-rebinding guard)."""
    if not host_header:
        return False
    host = host_header.strip().lower()
    name, sep, port_text = host.rpartition(":")
    if host.startswith("["):
        # [::1] or [::1]:8770
        end = host.find("]")
        if end == -1:
            return False
        name = host[: end + 1]
        rest = host[end + 1:]
        if rest == "":
            return port == 80
        if not rest.startswith(":"):
            return False
        port_text = rest[1:]
    elif not sep:
        name, port_text = host, "80"
    if name not in LOOPBACK_NAMES:
        return False
    return port_text.isdigit() and int(port_text) == port


def origin_allowed(origin: Optional[str], port: int) -> bool:
    """POST must carry an Origin header naming this very server. A missing Origin is refused."""
    if not origin:
        return False
    allowed = {f"http://{name}:{port}" for name in LOOPBACK_NAMES}
    return origin.strip().lower() in allowed


def token_ok(supplied: Optional[str], token: str) -> bool:
    return bool(supplied) and hmac.compare_digest(str(supplied).encode("utf-8"), token.encode("utf-8"))


def clean_segment(raw: str) -> Optional[str]:
    """Decode one path segment once; refuse dots-first, separators, NUL, and anything still encoded."""
    seg = unquote(raw)
    if not seg or seg.startswith(".") or "/" in seg or "\\" in seg or "\x00" in seg or "%" in seg:
        return None
    if ":" in seg:  # drive letters and NTFS streams
        return None
    return seg


def resolve_media(ws: Path, base: str, slug: str, name: str) -> Optional[Tuple[Path, str]]:
    """``drafts|published/<slug>/out/<file>`` only. Returns (path, content-type) or None."""
    if base not in ("drafts", "published") or not SLUG_RE.match(slug) or not FILE_RE.match(name):
        return None
    ext = Path(name).suffix.lower()
    ctype = MEDIA_TYPES.get(ext)
    if ctype is None:
        return None
    out_dir = ws / base / slug / "out"
    return _confined(out_dir, name, ctype)


def resolve_font(ws: Path, name: str) -> Optional[Tuple[Path, str]]:
    if not FILE_RE.match(name):
        return None
    ctype = FONT_TYPES.get(Path(name).suffix.lower())
    if ctype is None:
        return None
    return _confined(ws / "brand" / "fonts", name, ctype)


def resolve_avatar(ws: Path, configured: object) -> Optional[Tuple[Path, str]]:
    """The configured identity photo, only if it sits inside the workspace and is an image."""
    if not isinstance(configured, str) or not configured.strip():
        return None
    candidate = Path(configured)
    path = candidate if candidate.is_absolute() else ws / candidate
    ctype = MEDIA_TYPES.get(path.suffix.lower())
    if ctype is None or not path.is_file() or not is_inside(path, ws):
        return None
    real = Path(os.path.realpath(str(path)))
    parts = {p.lower() for p in real.relative_to(Path(os.path.realpath(str(ws)))).parts}
    if parts & {".git", "config", "profile", "research", "data", "work"}:
        return None
    return real, ctype


def _confined(directory: Path, name: str, ctype: str) -> Optional[Tuple[Path, str]]:
    path = directory / name
    if not path.is_file() or not is_inside(path, directory):
        return None
    return Path(os.path.realpath(str(path))), ctype


def response_headers() -> Iterable[Tuple[str, str]]:
    return (
        ("X-Content-Type-Options", "nosniff"),
        ("Content-Security-Policy", CSP),
        ("Referrer-Policy", "no-referrer"),
        ("X-Frame-Options", "DENY"),
        ("Cross-Origin-Resource-Policy", "same-origin"),
        ("Cache-Control", "no-store"),
    )
