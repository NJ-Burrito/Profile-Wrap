"""The providers' one HTTP helper: JSON in, JSON out, keys never in an error.

https is required except for a loopback host (a local Ollama or a test server). Redirects are not
followed, so a key header can never travel to another host.
"""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.request
from typing import Any, Dict, Mapping, Sequence
from urllib.parse import urlsplit

from .base import ProviderError
from .keypatterns import redact

LOOPBACK = {"127.0.0.1", "localhost", "::1"}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **kw):
        return None


def _check_url(url: str) -> None:
    parts = urlsplit(url)
    if parts.scheme == "https" and parts.hostname:
        return
    if parts.scheme == "http" and parts.hostname in LOOPBACK:
        return
    raise ProviderError("config", "provider URLs must be https (http only for localhost): "
                        + redact(f"{parts.scheme}://{parts.hostname or '?'}"))


def _kind(status: int) -> str:
    if status in (401, 403):
        return "auth"
    if status == 429:
        return "rate_limit"
    if status >= 500:
        return "server"
    return "bad_response"


def post_json(url: str, headers: Mapping[str, str], payload: Mapping[str, Any], timeout: float,
              secrets: Sequence[str] = ()) -> Dict[str, Any]:
    """POST ``payload``; return the parsed JSON object. Raises ``ProviderError`` otherwise."""
    _check_url(url)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    hdrs = {"Content-Type": "application/json", "Accept": "application/json",
            "User-Agent": "profile-wrap-providers"}
    hdrs.update(headers)
    req = urllib.request.Request(url, data=data, headers=hdrs, method="POST")
    secrets = tuple(secrets)
    try:
        with urllib.request.build_opener(_NoRedirect).open(req, timeout=timeout) as resp:
            body = resp.read(8_000_000)
            status = resp.status
    except urllib.error.HTTPError as exc:
        detail = redact(exc.read(600).decode("utf-8", errors="replace"), secrets)
        raise ProviderError(_kind(exc.code), f"HTTP {exc.code}: {detail}".strip(), exc.code) from None
    except (socket.timeout, TimeoutError):
        raise ProviderError("timeout", f"no answer within {timeout:g}s") from None
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)):
            raise ProviderError("timeout", f"no answer within {timeout:g}s") from None
        raise ProviderError("network", redact(f"could not reach the provider: {exc.reason}", secrets)) from None
    except OSError as exc:
        raise ProviderError("network", redact(f"network error: {exc}", secrets)) from None
    try:
        obj = json.loads(body.decode("utf-8-sig"))
    except ValueError:
        raise ProviderError("bad_response", f"HTTP {status}: the answer was not JSON", status) from None
    if not isinstance(obj, dict):
        raise ProviderError("bad_response", f"HTTP {status}: unexpected JSON shape", status)
    return obj
