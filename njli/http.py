"""The only network module. Every outgoing request goes through ``request()``.

Rules enforced here:
  * a host allowlist: LinkedIn API and OAuth hosts, upload hosts (https, linkedin.com or
    licdn.com), hosts the caller names (configured public trend feeds), and api.apify.com only
    when the caller says the Apify acknowledgement is valid;
  * the Bearer token is sent only to LinkedIn hosts (or the loopback fake server in tests/demo);
  * the LinkedIn API host is limited to the endpoint allowlist in policy.py;
  * a neutral User-Agent, never rotated; ``Linkedin-Version`` always sent to the API host;
  * timeouts and network errors are classified, 429 and 5xx stop the run;
  * redirects are never followed (a redirect could carry the token to another host);
  * a fake-server base-URL override works only when ``NJLI_TEST=1`` or the workspace is a demo.
"""
from __future__ import annotations

import json as _json
import os
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any, Dict, Iterable, Optional
from urllib.parse import urlsplit, urlunsplit

from . import __version__, policy

OAUTH_PATH_PREFIX = "/oauth/"
OVERRIDE_ENV = "NJLI_LINKEDIN_BASE"


class HttpError(Exception):
    """A classified network failure.

    kind: blocked_host, blocked_endpoint, no_version, timeout, network, stop, client_error
    ``maybe_sent`` is True when the request may have reached the server (a timeout, or a
    non-2xx answer), so a caller that posts must not retry blindly.
    """

    def __init__(self, kind: str, message: str, status: Optional[int] = None,
                 response: Optional["Response"] = None, maybe_sent: bool = False):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.response = response
        self.maybe_sent = maybe_sent


@dataclass
class Response:
    status: int
    headers: Dict[str, str]
    body: bytes
    url: str = ""

    @property
    def ok(self) -> bool:
        return 200 <= self.status < 300

    def text(self) -> str:
        return self.body.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return _json.loads(self.body.decode("utf-8-sig"))


@dataclass
class HostPolicy:
    extra_hosts: Iterable[str] = field(default_factory=tuple)
    apify_ack: bool = False
    demo: bool = False
    extra_endpoints: Iterable[str] = field(default_factory=tuple)

    @property
    def test(self) -> bool:
        return os.environ.get(policy.TEST_ENV) == "1"

    @property
    def loopback_ok(self) -> bool:
        return self.demo or self.test


def _is_loopback(host: str) -> bool:
    return host in policy.LOOPBACK_HOSTS


def override_base(hp: HostPolicy) -> Optional[str]:
    """The fake-server base URL, honoured only in tests or a demo workspace."""
    base = os.environ.get(OVERRIDE_ENV)
    if not base or not hp.loopback_ok:
        return None
    host = urlsplit(base).hostname or ""
    return base.rstrip("/") if _is_loopback(host) else None


def _rewrite(url: str, hp: HostPolicy) -> str:
    base = override_base(hp)
    if not base:
        return url
    parts = urlsplit(url)
    if (parts.hostname or "") in policy.LINKEDIN_TOKEN_HOSTS or (parts.hostname or "").endswith(
            policy.UPLOAD_HOST_SUFFIXES):
        target = urlsplit(base)
        return urlunsplit((target.scheme, target.netloc, parts.path, parts.query, ""))
    return url


def check_endpoint(host: str, path: str, hp: Optional[HostPolicy] = None) -> None:
    """The API host is limited to the endpoint allowlist (also enforced before a rewrite)."""
    hp = hp or HostPolicy()
    if host != policy.LINKEDIN_API_HOST:
        return
    allowed = tuple(policy.LINKEDIN_ENDPOINT_ALLOWLIST) + tuple(hp.extra_endpoints)
    if not any(path == p or path.startswith(p.rstrip("/") + "/") for p in allowed):
        raise HttpError("blocked_endpoint", f"{path} is not on the LinkedIn endpoint allowlist")


def check_url(url: str, hp: Optional[HostPolicy] = None, upload: bool = False) -> str:
    """Return the host if the URL may be requested, else raise ``HttpError``."""
    hp = hp or HostPolicy()
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    if not host or parts.scheme not in ("https", "http"):
        raise HttpError("blocked_host", f"refusing URL without a web host: {url[:80]}")
    if _is_loopback(host):
        if hp.loopback_ok:
            return host
        raise HttpError("blocked_host", "loopback requests are allowed only in tests or demo")
    if hp.demo:
        raise HttpError("blocked_host",
                        f"demo workspace: only 127.0.0.1 is reachable, not {host}")
    if parts.scheme != "https":
        raise HttpError("blocked_host", f"refusing non-https URL to {host}")
    if host == policy.LINKEDIN_API_HOST:
        check_endpoint(host, parts.path, hp)
        return host
    if host == policy.LINKEDIN_OAUTH_HOST:
        if upload or parts.path.startswith(OAUTH_PATH_PREFIX):
            return host
        raise HttpError("blocked_endpoint", "www.linkedin.com is reachable for OAuth only")
    if upload and host.endswith(policy.UPLOAD_HOST_SUFFIXES):
        return host
    if host == policy.APIFY_HOST:
        if hp.apify_ack:
            return host
        raise HttpError("blocked_host", "api.apify.com needs a valid Apify acknowledgement")
    if host in {h.lower() for h in hp.extra_hosts}:
        return host
    raise HttpError("blocked_host", f"host {host} is not on the allowlist")


def token_allowed(host: str, hp: Optional[HostPolicy] = None) -> bool:
    """The Bearer token goes to LinkedIn hosts only (judged on the host the caller asked for,
    so a rewrite to the fake server never widens the rule), or to a loopback fake in tests."""
    hp = hp or HostPolicy()
    if host in policy.LINKEDIN_TOKEN_HOSTS:
        return True
    return _is_loopback(host) and hp.loopback_ok


def user_agent(contact: Optional[str] = None) -> str:
    base = f"nj-linkedin/{__version__}"
    return f"{base} (+{contact})" if contact else base


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any):  # noqa: D401
        return None


def _opener() -> urllib.request.OpenerDirector:
    return urllib.request.build_opener(_NoRedirect, urllib.request.ProxyHandler())


def _timeout_like(exc: BaseException) -> bool:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (socket.timeout, TimeoutError))


def request(method: str, url: str, *, headers: Optional[Dict[str, str]] = None,
            body: Optional[bytes] = None, json_body: Any = None, token: Optional[str] = None,
            timeout: float = 30.0, hp: Optional[HostPolicy] = None,
            linkedin_version: Optional[str] = None, upload: bool = False,
            contact: Optional[str] = None, stop_on: Iterable[int] = (429,)) -> Response:
    """Perform one request. Returns a Response for any HTTP status except stop statuses.

    429 and every 5xx raise ``HttpError(kind="stop")`` (the run must stop). Add 403 through
    ``stop_on`` for the social-actions extra. Other 4xx are returned for the caller to read.
    """
    hp = hp or HostPolicy()
    orig = urlsplit(url)
    orig_host = (orig.hostname or "").lower()
    check_endpoint(orig_host, orig.path, hp)
    # The URL the caller asked for must be allowed on its own merits (a demo workspace only
    # restricts where the request finally goes, not what the code believes it is calling).
    check_url(url, replace(hp, demo=False), upload=upload)
    url = _rewrite(url, hp)
    host = check_url(url, hp, upload=upload)
    hdrs: Dict[str, str] = {"User-Agent": user_agent(contact), "Accept": "application/json"}
    hdrs.update(headers or {})
    if token is not None:
        if not token_allowed(orig_host, hp):
            raise HttpError("blocked_host", f"the access token is never sent to {host}")
        hdrs["Authorization"] = f"Bearer {token}"
    if orig_host == policy.LINKEDIN_API_HOST:
        if not linkedin_version:
            raise HttpError("no_version", "Linkedin-Version is required for the LinkedIn API")
        hdrs["Linkedin-Version"] = linkedin_version
        hdrs["X-Restli-Protocol-Version"] = "2.0.0"
    data = body
    if json_body is not None:
        data = _json.dumps(json_body).encode("utf-8")
        hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=data, method=method.upper(), headers=hdrs)
    stop = set(stop_on)
    try:
        with _opener().open(req, timeout=timeout) as resp:
            result = Response(resp.status, {k.lower(): v for k, v in resp.headers.items()},
                              resp.read(), url)
    except urllib.error.HTTPError as err:
        payload = err.read() if err.fp else b""
        result = Response(err.code, {k.lower(): v for k, v in err.headers.items()}, payload, url)
    except (socket.timeout, TimeoutError) as exc:
        raise HttpError("timeout", f"timed out after {timeout:g}s calling {host}",
                        maybe_sent=True) from exc
    except urllib.error.URLError as exc:
        if _timeout_like(exc):
            raise HttpError("timeout", f"timed out after {timeout:g}s calling {host}",
                            maybe_sent=True) from exc
        raise HttpError("network", f"cannot reach {host}: {exc.reason}") from exc
    except OSError as exc:
        raise HttpError("network", f"network error calling {host}: {exc}") from exc
    if result.status in stop or result.status >= 500:
        raise HttpError("stop", f"{host} answered {result.status}; the run must stop",
                        status=result.status, response=result, maybe_sent=True)
    return result


def reachable(host: str, port: int = 443, timeout: float = 5.0) -> "tuple[bool, str]":
    """TCP reachability probe for ``doctor`` (no request is sent). Returns (ok, message)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, f"{host}:{port} reachable"
    except socket.gaierror:
        return False, f"cannot resolve {host}: offline, or a DNS problem"
    except (socket.timeout, TimeoutError):
        return False, f"timed out reaching {host}:{port}: a proxy or firewall may block it"
    except OSError as exc:
        return False, f"cannot reach {host}:{port}: {exc}"
