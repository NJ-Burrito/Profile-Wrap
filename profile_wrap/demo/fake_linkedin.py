"""A fake LinkedIn server for tests and the demo workspace. It makes no real call, ever.

It binds 127.0.0.1 only. Point the client at it with ``PROFILE_WRAP_TEST=1`` (or a demo workspace) and
``PROFILE_WRAP_LINKEDIN_BASE=<base_url>``; ``profile_wrap.http`` then rewrites LinkedIn API, OAuth and media hosts
to this server while still judging every request by the host the caller asked for.

Behaviour is scripted per route; a script entry is consumed once:

    fake.script("posts", {"status": 429})            # answer 429 once
    fake.script("posts", {"delay": 3})               # read the request, answer after 3 s
    fake.script("posts", {"drop": True})             # read the request, close without an answer
    fake.script("init_image", {"upload_host": "evil.example.invalid"})   # hostile upload URL

Every request is recorded in ``fake.requests`` (method, path, query, headers, parsed body).
Persona data is fictional.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

DEMO_SUB = "DEMO000000"
DEMO_NAME = "Maya Rivera"
REQUIRED_POST_FIELDS = ("author", "commentary", "visibility", "distribution", "lifecycleState")


class FakeLinkedIn:
    def __init__(self, host: str = "127.0.0.1", port: int = 0, sub: str = DEMO_SUB,
                 name: str = DEMO_NAME, social_actions: str = "closed",
                 inactive_versions: Optional[List[str]] = None, upload_host: str = "upload.licdn.com"):
        self.host, self.port = host, port
        self.sub, self.name = sub, name
        self.social_actions = social_actions          # "closed" (403) or "open"
        self.inactive_versions = set(inactive_versions or [])
        self.upload_host = upload_host
        self.requests: List[Dict[str, Any]] = []
        self.posts: List[Dict[str, Any]] = []
        self.comments: List[Dict[str, Any]] = []
        self.uploads: List[Dict[str, Any]] = []
        self._scripts: Dict[str, List[Dict[str, Any]]] = {}
        self._lock = threading.Lock()
        self._counter = 0
        self._server: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # -------------------------------------------------------------- control
    def script(self, route: str, behaviour: Dict[str, Any]) -> None:
        with self._lock:
            self._scripts.setdefault(route, []).append(dict(behaviour))

    def _next(self, route: str) -> Dict[str, Any]:
        with self._lock:
            queue = self._scripts.get(route) or []
            return queue.pop(0) if queue else {}

    def _id(self) -> str:
        with self._lock:
            self._counter += 1
            return f"DEMO{self._counter:010d}"

    def calls(self, method: Optional[str] = None, path_prefix: str = "") -> List[Dict[str, Any]]:
        return [r for r in self.requests
                if (method is None or r["method"] == method) and r["path"].startswith(path_prefix)]

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def start(self) -> "FakeLinkedIn":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *args: Any) -> None:
                return

            def _go(self) -> None:
                fake._handle(self)

            do_GET = do_POST = do_PUT = do_DELETE = _go  # noqa: N815

        class Server(ThreadingHTTPServer):
            daemon_threads = True
            allow_reuse_address = True

        self._server = Server((self.host, self.port), Handler)
        self.port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "FakeLinkedIn":
        return self.start()

    def __exit__(self, *exc: Any) -> None:
        self.stop()

    # -------------------------------------------------------------- handling
    def _reply(self, h: BaseHTTPRequestHandler, status: int, body: Any = None,
               headers: Optional[Dict[str, str]] = None) -> None:
        data = b"" if body is None else (body if isinstance(body, bytes)
                                         else json.dumps(body).encode("utf-8"))
        try:
            h.send_response(status)
            h.send_header("Content-Type", "application/json")
            h.send_header("Content-Length", str(len(data)))
            for k, v in (headers or {}).items():
                h.send_header(k, v)
            h.end_headers()
            h.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def _handle(self, h: BaseHTTPRequestHandler) -> None:
        url = urlsplit(h.path)
        length = int(h.headers.get("Content-Length") or 0)
        raw = h.rfile.read(length) if length else b""
        try:
            parsed: Any = json.loads(raw.decode("utf-8")) if raw[:1] in (b"{", b"[") else None
        except ValueError:
            parsed = None
        headers = {k.lower(): v for k, v in h.headers.items()}
        rec = {"method": h.command, "path": url.path, "query": parse_qs(url.query), "headers": headers,
               "body": parsed, "raw_len": len(raw), "token": headers.get("authorization", "")}
        with self._lock:
            self.requests.append(rec)
        route = self._route(h.command, url.path)
        beh = self._next(route)
        if beh.get("drop"):
            h.close_connection = True
            try:
                h.connection.close()
            except OSError:
                pass
            return
        if beh.get("delay"):
            time.sleep(float(beh["delay"]))
        if "status" in beh:
            self._reply(h, int(beh["status"]), beh.get("body", {"message": "scripted"}),
                        beh.get("headers"))
            return
        self._serve(h, route, url.path, headers, parsed, beh)

    @staticmethod
    def _route(method: str, path: str) -> str:
        if path.endswith("/accessToken"):
            return "token"
        if path == "/v2/userinfo":
            return "userinfo"
        if path == "/rest/images":
            return "init_image"
        if path == "/rest/documents":
            return "init_document"
        if path == "/rest/posts":
            return "posts"
        if path.startswith("/v2/socialActions/"):
            return "comments"
        if method == "PUT":
            return "upload"
        return "other"

    def _serve(self, h: BaseHTTPRequestHandler, route: str, path: str, headers: Dict[str, str],
               body: Any, beh: Dict[str, Any]) -> None:
        if route == "token":
            self._reply(h, 200, {"access_token": "fake-access-token", "expires_in": 5184000,
                                 "scope": "openid,profile,w_member_social"})
            return
        if route == "upload":
            self.uploads.append({"path": path, "token": headers.get("authorization", "")})
            self._reply(h, 201)
            return
        if route == "other":
            self._reply(h, 404, {"message": "unknown route"})
            return
        if not headers.get("authorization", "").startswith("Bearer "):
            self._reply(h, 401, {"message": "missing token"})
            return
        version = headers.get("linkedin-version", "")
        if not version or version in self.inactive_versions:
            self._reply(h, 426 if version else 400,
                        {"code": "NONEXISTENT_VERSION", "message": f"version {version or '(none)'} is not active"})
            return
        if route == "userinfo":
            self._reply(h, 200, {"sub": self.sub, "name": self.name})
        elif route in ("init_image", "init_document"):
            kind = "image" if route == "init_image" else "document"
            media_id = self._id()
            host = beh.get("upload_host", self.upload_host)
            self._reply(h, 200, {"value": {"uploadUrl": f"https://{host}/mp/{media_id}",
                                           kind: f"urn:li:{kind}:{media_id}",
                                           "uploadUrlExpiresAt": int(time.time() * 1000) + 3600000}})
        elif route == "posts":
            missing = [k for k in REQUIRED_POST_FIELDS if not isinstance(body, dict) or k not in body]
            if missing:
                self._reply(h, 400, {"message": "missing " + ", ".join(missing)})
                return
            urn = f"urn:li:share:{self._id()}"
            self.posts.append({"urn": urn, "body": body})
            self._reply(h, 201, None, {"x-restli-id": urn})
        elif route == "comments":
            if self.social_actions != "open":
                self._reply(h, 403, {"code": "ACCESS_DENIED", "message": "partner only"})
                return
            if not isinstance(body, dict) or "message" not in body:
                self._reply(h, 400, {"message": "invalid body"})
                return
            cid = f"urn:li:comment:(urn:li:activity:1,{self._id()})"
            self.comments.append({"path": unquote(path), "body": body})
            self._reply(h, 201, None, {"x-restli-id": cid})


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="fake_linkedin", description="fake LinkedIn server (no real calls)")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--social-actions", choices=["closed", "open"], default="closed")
    args = ap.parse_args(argv)
    fake = FakeLinkedIn(port=args.port, social_actions=args.social_actions).start()
    print(f"fake LinkedIn on {fake.base_url}")
    print("set PROFILE_WRAP_TEST=1 and PROFILE_WRAP_LINKEDIN_BASE=" + fake.base_url)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        fake.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
