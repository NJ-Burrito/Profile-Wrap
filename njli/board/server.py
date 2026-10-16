"""The HTTP server: stdlib ``ThreadingHTTPServer`` on loopback only.

Every request: the Host header must be a loopback name on our port (421 otherwise). Every POST also
needs an Origin naming this server and the per-start token (403 otherwise). Files are served only by
explicit routes with strict names (see ``security``). Unexpected errors answer 500 JSON; the
connection is never dropped.
"""
from __future__ import annotations

import errno
import json
import re
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import urlsplit

from .. import __version__, config as config_mod, limits, policy
from ..notify import notify as desktop_notify
from . import security
from .actions import Decider
from .store import BoardStore
from .worker import Worker, recover_stuck

APP_DIR = Path(__file__).resolve().parent / "app"
I18N_DIR = Path(__file__).resolve().parent / "i18n"
STATIC = {"/app/board.js": ("board.js", "text/javascript; charset=utf-8"),
          "/app/board.css": ("board.css", "text/css; charset=utf-8")}
FAMILY_RE = re.compile(r"^[A-Za-z0-9 ._-]{1,60}$")
DOCTOR_TTL = 30.0
DRAIN_LIMIT = 1 << 20  # bodies up to this size are read before we answer, even when we refuse them


class PortInUse(OSError):
    """The port is taken; the message says what to do."""


class _V6Server(ThreadingHTTPServer):
    address_family = socket.AF_INET6


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class BoardApp:
    """Everything the handler needs, so tests can build one without a socket."""

    def __init__(self, ws: Path, *, token: Optional[str] = None, runner: Any = None,
                 gate_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
                 render_fn: Optional[Callable[[str], Tuple[int, str]]] = None,
                 notify_fn: Optional[Callable[[str, str], None]] = None, start_worker: bool = True):
        self.ws = Path(ws)
        self.store = BoardStore(self.ws)
        self.token = token or secrets.token_urlsafe(24)
        self.port = 0
        self.notify_fn = notify_fn or self._default_notify
        self.worker = Worker(self.store, runner=runner, gate_fn=gate_fn, render_fn=render_fn,
                             notify_fn=self.notify_fn)
        self.decider = Decider(self.store, gate_fn=gate_fn, worker=self.worker, notify_fn=self.notify_fn)
        self.worker.bind(self.decider)
        self.start_worker = start_worker
        self._doctor: Optional[Tuple[float, Dict[str, Any]]] = None
        self.started = time.time()

    def _default_notify(self, title: str, message: str) -> None:
        import os
        mode = "log" if os.environ.get(policy.TEST_ENV) == "1" else str(
            self.store.cfg.get("schedule", {}).get("notify", "auto"))
        desktop_notify(title, message, self.ws, mode="log" if mode in ("off", "log") else "auto")

    # ----------------------------------------------------------- payloads
    def health(self) -> Dict[str, Any]:
        return {"ok": True, "board": "nj-linkedin", "version": __version__, "api": 1,
                "uptime_s": int(time.time() - self.started), "busy": self.worker.busy,
                "worker": self.worker.available()[0], "paused": limits.pause_flags(self.ws)}

    def state_extra(self) -> Dict[str, Any]:
        return {"worker": self.worker.available()[0]}

    def settings(self) -> Dict[str, Any]:
        cfg = self.store.cfg
        try:
            modes = config_mod.effective_modes(cfg, self.ws)
        except Exception as exc:  # a broken ack file must not blank the tab
            modes = {"posting": cfg.get("posting", {}).get("mode"), "comments": "draft", "reading": "manual",
                     "likes": False, "notes": [f"modes unavailable: {exc}"]}
        try:
            acks = {k: {"status": v[0], "reason": v[1]} for k, v in config_mod.ack_statuses(cfg, self.ws).items()}
        except Exception as exc:
            acks = {"error": {"status": "unknown", "reason": str(exc)}}
        doctor = self.doctor()
        token = next((c for c in doctor.get("checks", []) if c.get("id") == "token"), None)
        return {"modes": modes, "acks": acks, "doctor": doctor, "token": token,
                "pause": limits.pause_flags(self.ws), "caps": policy.caps(),
                "board": {"host": cfg.get("board", {}).get("host"), "port": self.port,
                          "ui_language": cfg.get("board", {}).get("ui_language", "en")},
                "workspace": self.ws.name, "config_problem": self.store.config_problem,
                "notifications": self.store.notifications(10)}

    def doctor(self) -> Dict[str, Any]:
        now = time.time()
        if self._doctor and now - self._doctor[0] < DOCTOR_TTL:
            return self._doctor[1]
        try:
            from .. import doctor as doctor_mod
            result = doctor_mod.run(workspace=self.ws, online=False)
            slim = {"summary": result.get("summary"), "generated_at": result.get("generated_at"),
                    "checks": [{k: c.get(k) for k in ("id", "name", "status", "detail", "hint")}
                               for c in result.get("checks", [])]}
        except Exception as exc:
            slim = {"summary": {}, "checks": [], "error": str(exc)[:300]}
        self._doctor = (now, slim)
        return slim

    def index_html(self) -> bytes:
        html = (APP_DIR / "index.html").read_text(encoding="utf-8")
        return html.replace("__TOKEN__", self.token).encode("utf-8")

    def fonts_css(self) -> bytes:
        fonts = self.store.cfg.get("brand", {}).get("fonts", {})
        faces, vars_ = [], []
        for role in ("display", "text", "arabic"):
            spec = fonts.get(role) if isinstance(fonts.get(role), dict) else {}
            family = spec.get("family")
            files = [f for f in spec.get("files", []) if isinstance(f, str)]
            usable = []
            for name in files:
                base = Path(name).name
                if security.resolve_font(self.ws, base):
                    usable.append(base)
            if isinstance(family, str) and FAMILY_RE.match(family) and usable:
                for base in usable:
                    fmt = {"woff2": "woff2", "woff": "woff", "ttf": "truetype", "otf": "opentype"}[base.rsplit(".", 1)[-1].lower()]
                    faces.append(f'@font-face{{font-family:"{family}";src:url("/fonts/{base}") format("{fmt}");font-display:swap}}')
                vars_.append(f'--font-{role}:"{family}",system-ui,sans-serif;')
        css = "\n".join(faces) + ("\n:root{" + "".join(vars_) + "}\n" if vars_ else "\n")
        return css.encode("utf-8")


class BoardServer:
    def __init__(self, ws: Path, *, host: Optional[str] = None, port: Optional[int] = None, **kwargs: Any):
        self.app = BoardApp(ws, **kwargs)
        cfg_board = self.app.store.cfg.get("board", {})
        self.host = host or cfg_board.get("host") or "127.0.0.1"
        want = cfg_board.get("port", 8770) if port is None else port
        if self.host not in ("127.0.0.1", "localhost", "::1"):
            raise ValueError(f"board.host must be a loopback address (127.0.0.1, localhost or ::1), not {self.host!r}")
        handler = _make_handler(self.app)
        cls = _V6Server if self.host == "::1" else _Server
        try:
            self.httpd = cls((self.host, int(want)), handler)
        except OSError as exc:
            if exc.errno in (errno.EADDRINUSE, 10048, 10013, 98, 48):
                raise PortInUse(exc.errno, f"port {want} is already in use. If the board is already running, open "
                                           f"http://127.0.0.1:{want}/ . Otherwise pick another port with "
                                           f"`njli board --port N`.") from exc
            raise
        self.port = self.httpd.server_address[1]
        self.app.port = self.port
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/" if self.host != "::1" else f"http://[::1]:{self.port}/"

    @property
    def token(self) -> str:
        return self.app.token

    def prepare(self) -> list:
        fixed = recover_stuck(self.app.store, self.app.decider)
        if self.app.start_worker:
            self.app.worker.start()
        return fixed

    def serve_forever(self) -> None:
        self.prepare()
        self.httpd.serve_forever(poll_interval=0.2)

    def start_background(self) -> "BoardServer":
        self.prepare()
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1},
                                        name="board-http", daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        try:
            self.httpd.shutdown()
        finally:
            self.httpd.server_close()
            self.app.worker.stop()
            if self._thread is not None:
                self._thread.join(5)


def _make_handler(app: BoardApp):
    store = app.store

    class Handler(BaseHTTPRequestHandler):
        server_version = "njli-board"
        sys_version = ""
        protocol_version = "HTTP/1.0"  # one request per connection: an unread POST body can never desync

        def log_message(self, *args: Any) -> None:
            pass

        # ------------------------------------------------------ responses
        def send_bytes(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in security.response_headers():
                self.send_header(k, v)
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_json(self, code: int, obj: Any, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_bytes(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8", extra)

        def send_file(self, found: Optional[Tuple[Path, str]]) -> None:
            if not found:
                return self.send_json(404, {"error": "not_found"})
            try:
                data = found[0].read_bytes()
            except OSError:
                return self.send_json(404, {"error": "not_found"})
            self.send_bytes(200, data, found[1])

        # ------------------------------------------------------- entry
        def _common_checks(self) -> bool:
            if not security.host_allowed(self.headers.get("Host"), app.port):
                self.send_json(421, {"error": "bad_host", "message": "This board answers only on its own loopback address."})
                return False
            return True

        def _read_raw(self) -> Optional[bytes]:
            """Read the whole request body before any answer, so closing never resets a half-sent upload."""
            try:
                length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                length = -1
            if length < 0:
                return None
            if length > DRAIN_LIMIT:
                return None
            return self.rfile.read(length) if length else b""

        def do_GET(self) -> None:
            if not self._common_checks():
                return
            try:
                self.route_get()
            except Exception as exc:  # never drop the connection
                self.send_json(500, {"error": "internal", "degraded": True, "message": str(exc)[:200]})

        do_HEAD = do_GET

        def do_POST(self) -> None:
            self._raw = self._read_raw()
            if not self._common_checks():
                return
            if not security.origin_allowed(self.headers.get("Origin"), app.port) or                     not security.token_ok(self.headers.get("X-Review-Token"), app.token):
                return self.send_json(403, {"error": "forbidden", "reload": True,
                                            "message": "This page is out of date or not from this board. Reload it."})
            try:
                self.route_post()
            except Exception as exc:
                self.send_json(500, {"error": "internal", "message": str(exc)[:200]})

        def _unsupported(self) -> None:
            self.send_json(405, {"error": "method_not_allowed"})

        do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _unsupported

        # --------------------------------------------------------- GET
        def route_get(self) -> None:
            raw = urlsplit(self.path).path
            if raw in ("/", "/index.html"):
                return self.send_bytes(200, app.index_html(), "text/html; charset=utf-8")
            if raw in STATIC:
                name, ctype = STATIC[raw]
                return self.send_bytes(200, (APP_DIR / name).read_bytes(), ctype)
            if raw == "/app/fonts.css":
                return self.send_bytes(200, app.fonts_css(), "text/css; charset=utf-8")
            if raw == "/api/health":
                return self.send_json(200, app.health())
            segs = raw.split("/")[1:]
            clean = [security.clean_segment(s) for s in segs]
            if raw == "/api/state":
                etag, body = store.state_bytes(app.state_extra())
                quoted = f'"{etag}"'
                if self.headers.get("If-None-Match") == quoted:
                    return self.send_bytes(304, b"", "application/json", {"ETag": quoted})
                return self.send_bytes(200, body, "application/json; charset=utf-8", {"ETag": quoted})
            if raw == "/api/pending":
                return self.send_json(200, store.pending_rows())
            if raw == "/api/connect":
                return self.send_json(200, store.connect_rows())
            if raw == "/api/profile":
                return self.send_json(200, store.profile_view())
            if raw == "/api/metrics":
                return self.send_json(200, store.metrics())
            if raw == "/api/settings":
                return self.send_json(200, app.settings())
            if len(segs) == 3 and segs[:2] == ["api", "draft"] and clean[2]:
                detail = store.draft_detail(clean[2])
                return self.send_json(200, detail) if detail else self.send_json(404, {"error": "unknown_post"})
            if len(segs) == 2 and segs[0] == "i18n" and segs[1] in ("en.json", "ar.json"):
                return self.send_bytes(200, (I18N_DIR / segs[1]).read_bytes(), "application/json; charset=utf-8")
            if len(segs) == 4 and segs[0] == "media" and all(clean[1:]):
                return self.send_file(security.resolve_media(store.ws, clean[1] or "", clean[2] or "", clean[3] or ""))
            if len(segs) == 2 and segs[0] == "fonts" and clean[1]:
                return self.send_file(security.resolve_font(store.ws, clean[1]))
            if raw == "/avatar":
                photo = store.cfg.get("brand", {}).get("identity", {}).get("photo")
                return self.send_file(security.resolve_avatar(store.ws, photo))
            self.send_json(404, {"error": "not_found"})

        # -------------------------------------------------------- POST
        def read_body(self) -> Optional[Dict[str, Any]]:
            ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
            if ctype != "application/json":
                self.send_json(415, {"error": "json_required"})
                return None
            raw = self._raw
            if raw is None:
                self.send_json(411 if self.headers.get("Content-Length") is None else 413, {"error": "too_large"})
                return None
            if len(raw) > security.MAX_BODY:
                self.send_json(413, {"error": "too_large"})
                return None
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self.send_json(400, {"error": "bad_json"})
                return None
            if not isinstance(body, dict):
                self.send_json(400, {"error": "bad_json"})
                return None
            return body

        def route_post(self) -> None:
            path = urlsplit(self.path).path
            body = self.read_body()
            if body is None:
                return
            def text(key: str) -> str:
                value = body.get(key)
                return value if isinstance(value, str) else ""

            if path == "/api/decision":
                code, resp = app.decider.decide(text("slug"), text("action"), text("note"), body.get("confirm") is True)
            elif path == "/api/connect-done":
                code, resp = app.decider.connect_done(text("id"), text("action"))
            elif path == "/api/pending-done":
                code, resp = app.decider.pending_done(text("id"), text("action"))
            elif path == "/api/profile-done":
                code, resp = app.decider.profile_done(text("id"), body.get("done") is True)
            elif path == "/api/pause":
                code, resp = app.decider.set_pause(text("kind"), body.get("paused") is True)
            else:
                code, resp = 404, {"error": "not_found"}
            store.invalidate()
            self.send_json(code, resp)

    return Handler


def probe_health(port: int, timeout: float = 1.5) -> Optional[Dict[str, Any]]:
    """If something answers /api/health like a board on 127.0.0.1:port, return its payload."""
    import http.client
    try:
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
        conn.request("GET", "/api/health")
        resp = conn.getresponse()
        data = json.loads(resp.read().decode("utf-8"))
        conn.close()
        return data if isinstance(data, dict) and data.get("board") == "nj-linkedin" else None
    except (OSError, ValueError):
        return None
