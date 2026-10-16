"""The LinkedIn API client: member lookup, media upload, create post.

Every call goes through ``njli.http.request``, which enforces the host allowlist, the endpoint
allowlist, the neutral User-Agent and the rule that the Bearer token goes only to LinkedIn API and
OAuth hosts. Upload URLs come from LinkedIn's own ``initializeUpload`` answer and are still checked
here: https, a linkedin.com or licdn.com host, never the API or OAuth host, and the Bearer token is
never attached to an upload request.
"""
from __future__ import annotations

from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlsplit

from .. import policy
from ..http import HostPolicy, HttpError, Response, request
from . import versions

API = f"https://{policy.LINKEDIN_API_HOST}"
UPLOAD_KINDS = {"image": "/rest/images", "document": "/rest/documents"}


class ApiError(Exception):
    """A LinkedIn answer the caller cannot use (not a transport error)."""

    def __init__(self, message: str, status: Optional[int] = None, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def default_version(cfg: Dict[str, Any]) -> str:
    return versions.resolve(cfg)[0]


def host_policy(cfg: Dict[str, Any]) -> HostPolicy:
    return HostPolicy(demo=bool(cfg.get("persona", {}).get("demo")))


def check_upload_url(url: str) -> str:
    """Refuse an upload target that is not an https LinkedIn media host. Returns the host."""
    parts = urlsplit(url or "")
    host = (parts.hostname or "").lower()
    if parts.scheme != "https" or not host:
        raise HttpError("blocked_host", f"refusing upload URL that is not https: {url[:60]}")
    if host in (policy.LINKEDIN_API_HOST, policy.LINKEDIN_OAUTH_HOST):
        raise HttpError("blocked_host", f"refusing upload URL on {host}")
    if not host.endswith(policy.UPLOAD_HOST_SUFFIXES):
        raise HttpError("blocked_host", f"refusing upload host {host}: not a LinkedIn media host")
    return host


def _short(resp: Response) -> str:
    return resp.text()[:300].replace("\n", " ")


class Client:
    def __init__(self, token: str, version: str, hp: Optional[HostPolicy] = None,
                 timeout: float = 30.0, contact: Optional[str] = None):
        self._token = token
        self.version = version
        self.hp = hp or HostPolicy()
        self.timeout = timeout
        self.contact = contact

    def _call(self, method: str, path: str, **kw: Any) -> Response:
        return request(method, f"{API}{path}", token=self._token, hp=self.hp,
                       linkedin_version=self.version, timeout=self.timeout,
                       contact=self.contact, **kw)

    def call(self, method: str, path: str, *, extra_endpoints: Tuple[str, ...] = (),
             stop_on: Tuple[int, ...] = (429,), **kw: Any) -> Response:
        """A request to a path the caller names (used by the opt-in extra). The endpoint
        allowlist in ``njli.http`` still applies; ``extra_endpoints`` widens it for this call."""
        hp = HostPolicy(extra_hosts=self.hp.extra_hosts, apify_ack=self.hp.apify_ack,
                        demo=self.hp.demo, extra_endpoints=tuple(extra_endpoints))
        return request(method, f"{API}{path}", token=self._token, hp=hp,
                       linkedin_version=self.version, timeout=self.timeout,
                       contact=self.contact, stop_on=stop_on, **kw)

    def userinfo(self) -> Dict[str, Any]:
        resp = self._call("GET", "/v2/userinfo")
        if resp.status == 401:
            raise ApiError("LinkedIn rejected the access token (401): run 'njli auth'", 401)
        if not resp.ok:
            raise ApiError(f"member lookup answered {resp.status}: {_short(resp)}", resp.status)
        data = resp.json()
        if not data.get("sub"):
            raise ApiError("member lookup returned no subject id")
        return data

    def init_upload(self, kind: str, owner: str) -> Tuple[str, str]:
        """(upload_url, media_urn). The upload URL is checked before it is returned."""
        base = UPLOAD_KINDS[kind]
        resp = self._call("POST", f"{base}?action=initializeUpload",
                          json_body={"initializeUploadRequest": {"owner": owner}})
        if not resp.ok:
            raise ApiError(f"{kind} upload setup answered {resp.status}: {_short(resp)}", resp.status)
        value = resp.json().get("value", {})
        url, urn = value.get("uploadUrl"), value.get(kind)
        if not url or not urn:
            raise ApiError(f"{kind} upload setup returned no uploadUrl or id")
        check_upload_url(url)
        return url, urn

    def upload_bytes(self, upload_url: str, data: bytes) -> None:
        """PUT the file to LinkedIn's media host. No Bearer token is attached."""
        check_upload_url(upload_url)
        resp = request("PUT", upload_url, body=data, upload=True, hp=self.hp,
                       timeout=max(self.timeout * 4, 120.0),
                       headers={"Content-Type": "application/octet-stream"})
        if resp.status not in (200, 201):
            raise ApiError(f"media upload answered {resp.status}: {_short(resp)}", resp.status)

    def upload(self, kind: str, owner: str, data: bytes) -> str:
        url, urn = self.init_upload(kind, owner)
        self.upload_bytes(url, data)
        return urn

    def create_post(self, body: Dict[str, Any]) -> Tuple[Response, Optional[str]]:
        """POST /rest/posts once. Returns (response, urn from the x-restli-id header)."""
        resp = self._call("POST", "/rest/posts", json_body=body)
        return resp, resp.headers.get("x-restli-id")
