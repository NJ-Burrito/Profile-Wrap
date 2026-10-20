"""The local server behind ``profile-wrap gui``.

Rules, all enforced here and tested:
* binds 127.0.0.1 only, on a port the OS picks;
* every request must name a loopback Host on this port (DNS-rebinding guard);
* a page needs the per-launch token in its URL (``?t=``), which the nav links carry;
* an API call needs the token in the ``X-PW-Token`` header, and a POST also needs this server's Origin;
* a strict CSP (no inline script or style, no external origin), and no key is ever sent to the page.
"""
from __future__ import annotations

import json
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

from .. import __version__
from .. import config as config_mod
from .. import paths, updates
from ..board.security import CSP, host_allowed, origin_allowed, token_ok
from . import logic
from .logic import GuiError

SCREENS: Dict[str, str] = {"/": "home", "/board": "board", "/providers": "providers", "/build": "build",
                           "/settings": "settings"}
TITLES = {"home": "Home", "board": "Board", "providers": "Providers", "build": "Build", "settings": "Settings"}
ASSET_TYPES = {"gui.css": "text/css; charset=utf-8", "gui.js": "text/javascript; charset=utf-8",
               "mark.svg": "image/svg+xml"}
MAX_BODY = 20000
DOCTOR_TTL = 60.0


def assets_dir() -> Path:
    return paths.resource("gui_assets")


class GuiApp:
    """State the handler needs. Tests build one without a socket."""

    def __init__(self, ws: Path, *, token: Optional[str] = None,
                 provider_factory: Optional[Callable[..., Any]] = None,
                 doctor_fn: Optional[Callable[[Path], Dict[str, Any]]] = None):
        self.ws = Path(ws)
        self.token = token or secrets.token_urlsafe(24)
        self.port = 0
        self.provider_factory = provider_factory
        self.doctor_fn = doctor_fn or self._doctor
        self._doctor_cache: Optional[Tuple[float, Path, Dict[str, Any]]] = None
        self.board: Any = None
        self.update_enabled = False   # set by window.run: only a real app window asks GitHub
        self.quit = threading.Event()
        self.lock = threading.Lock()

    # ----------------------------------------------------------- helpers
    def cfg(self) -> Dict[str, Any]:
        try:
            return config_mod.load(self.ws)
        except Exception as exc:  # a broken config must not blank the screen
            raise GuiError(f"the workspace config is unreadable: {str(exc)[:200]}", 409) from None

    @staticmethod
    def _doctor(ws: Path) -> Dict[str, Any]:
        try:
            from .. import doctor as doctor_mod
            result = doctor_mod.run(workspace=ws, online=False)
            return {"summary": result.get("summary"), "generated_at": result.get("generated_at"),
                    "checks": [{k: c.get(k) for k in ("id", "name", "status", "detail", "hint")}
                               for c in result.get("checks", [])]}
        except Exception as exc:
            return {"summary": {}, "checks": [], "error": str(exc)[:300]}

    def doctor(self, fresh: bool = False) -> Dict[str, Any]:
        now = time.time()
        c = self._doctor_cache
        if c and not fresh and c[1] == self.ws and now - c[0] < DOCTOR_TTL:
            return c[2]
        result = self.doctor_fn(self.ws)
        self._doctor_cache = (now, self.ws, result)
        return result

    def health(self) -> Dict[str, Any]:
        return {"ok": True, "app": "profile-wrap-gui", "version": __version__, "api": 1}

    def page(self, screen: str) -> bytes:
        html = (assets_dir() / "index.html").read_text(encoding="utf-8")
        return (html.replace("__TOKEN__", self.token).replace("__SCREEN__", screen)
                .replace("__TITLE__", TITLES[screen]).replace("__VERSION__", __version__)).encode("utf-8")

    def start_board(self) -> Dict[str, Any]:
        from ..board.server import BoardServer
        with self.lock:
            if self.board is None:
                if not config_mod.config_path(self.ws).is_file():
                    raise GuiError("this folder has no workspace config; run `profile-wrap init` first", 409)
                try:
                    self.board = BoardServer(self.ws, port=0)
                    self.board.app.update_enabled = self.update_enabled
                    self.board.start_background()
                except ValueError as exc:
                    raise GuiError(str(exc), 409) from None
            return {"running": True, "url": self.board.url}

    def board_state(self) -> Dict[str, Any]:
        b = self.board
        return {"running": b is not None, "url": b.url if b else None}

    def stop_board(self) -> None:
        with self.lock:
            b, self.board = self.board, None
        if b is not None:
            b.shutdown()

    # ----------------------------------------------------------- routes
    def api_get(self, path: str) -> Any:
        if path == "/api/home":
            return logic.home(self.ws, self.cfg(), self.doctor(), __version__)
        if path == "/api/board":
            return self.board_state()
        if path == "/api/providers":
            return logic.provider_rows(self.ws)
        if path == "/api/calendar":
            return {"entries": logic.calendar_rows(self.ws)}
        if path == "/api/settings":
            return logic.settings_view(self.ws, self.cfg())
        if path == "/api/update":
            return updates.web_status(self.ws, self.update_enabled)
        raise GuiError("not found", 404)

    def api_post(self, path: str, body: Dict[str, Any]) -> Any:
        ws = self.ws
        if path == "/api/doctor":
            return self.doctor(fresh=True)
        if path == "/api/board/start":
            return self.start_board()
        if path == "/api/providers/key":
            return logic.set_key(body.get("provider"), body.get("key"))
        if path == "/api/providers/key/delete":
            return logic.delete_key(body.get("provider"))
        if path == "/api/providers/use":
            return logic.use_provider(ws, body.get("provider"), body.get("model"), body.get("base_url"))
        if path == "/api/providers/test":
            if self.provider_factory:
                return logic.test_provider(ws, body.get("provider"), self.provider_factory)
            return logic.test_provider(ws, body.get("provider"))
        if path == "/api/build/draft":
            kw = {"factory": self.provider_factory} if self.provider_factory else {}
            return logic.generate_draft(ws, body.get("slug"), bool(body.get("overwrite")), **kw)
        if path == "/api/build/gate":
            return logic.run_gate_for(ws, body.get("slug"))
        if path == "/api/build/text":
            return logic.draft_text(ws, body.get("slug"))
        if path == "/api/settings/posting-mode":
            logic.set_posting_mode(ws, body.get("mode"))
            return logic.settings_view(ws, self.cfg())
        if path == "/api/settings/job":
            logic.set_job(ws, body.get("name"), body.get("enabled"))
            return logic.settings_view(ws, self.cfg())
        if path == "/api/settings/workspace":
            new = logic.check_workspace(body.get("path"))
            self.stop_board()
            self.ws = new
            self._doctor_cache = None
            return logic.settings_view(self.ws, self.cfg())
        if path in ("/api/update/skip", "/api/update/later"):
            return updates.web_action(path.rsplit("/", 1)[1], ws)
        if path == "/api/quit":
            self.quit.set()
            return {"ok": True}
        raise GuiError("not found", 404)


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = False


class GuiServer:
    def __init__(self, ws: Path, *, host: str = "127.0.0.1", **kwargs: Any):
        if host != "127.0.0.1":
            raise ValueError("the app server binds 127.0.0.1 only")
        self.app = GuiApp(ws, **kwargs)
        self.httpd = _Server((host, 0), _make_handler(self.app))
        self.port = self.httpd.server_address[1]
        self.app.port = self.port
        self._thread: Optional[threading.Thread] = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    @property
    def token(self) -> str:
        return self.app.token

    @property
    def launch_url(self) -> str:
        return f"{self.url}?t={self.token}"

    def start_background(self) -> "GuiServer":
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.1},
                                        name="gui-http", daemon=True)
        self._thread.start()
        return self

    def shutdown(self) -> None:
        try:
            self.app.stop_board()
        finally:
            try:
                self.httpd.shutdown()
            finally:
                self.httpd.server_close()
                if self._thread is not None:
                    self._thread.join(5)


def _make_handler(app: GuiApp):
    class Handler(BaseHTTPRequestHandler):
        server_version = "profile-wrap-gui"
        sys_version = ""
        protocol_version = "HTTP/1.1"

        def log_message(self, *args: Any) -> None:
            pass

        # ------------------------------------------------ output
        def send_bytes(self, code: int, body: bytes, ctype: str, extra: Optional[Dict[str, str]] = None) -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Connection", "close")
            self.close_connection = True
            self.send_header("Content-Security-Policy", CSP)
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Cross-Origin-Resource-Policy", "same-origin")
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def send_json(self, code: int, obj: Any) -> None:
            self.send_bytes(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"),
                            "application/json; charset=utf-8")

        def fail(self, code: int, message: str) -> None:
            self.send_json(code, {"error": message})

        # ------------------------------------------------ checks
        def _host_ok(self) -> bool:
            return host_allowed(self.headers.get("Host"), app.port)

        def _api_authorized(self) -> bool:
            return token_ok(self.headers.get("X-PW-Token"), app.token)

        # ------------------------------------------------ verbs
        def do_HEAD(self) -> None:
            self.do_GET()

        def do_GET(self) -> None:
            if not self._host_ok():
                return self.fail(403, "host not allowed")
            url = urlsplit(self.path)
            path = url.path
            if path == "/health":
                return self.send_json(200, app.health())
            if path.startswith("/assets/"):
                name = path[len("/assets/"):]
                ctype = ASSET_TYPES.get(name)
                f = assets_dir() / name
                if ctype is None or not f.is_file():
                    return self.fail(404, "not found")
                return self.send_bytes(200, f.read_bytes(), ctype)
            if path.startswith("/api/"):
                if not self._api_authorized():
                    return self.fail(403, "missing or wrong token")
                try:
                    return self.send_json(200, app.api_get(path))
                except GuiError as exc:
                    return self.fail(exc.status, str(exc))
                except Exception as exc:
                    return self.fail(500, f"internal error ({type(exc).__name__})")
            screen = SCREENS.get(path)
            if screen is None:
                return self.fail(404, "not found")
            supplied = parse_qs(url.query).get("t", [None])[0]
            if not token_ok(supplied, app.token):
                return self.send_bytes(403, b"Open Profile-Wrap from the app: this page needs its launch token.",
                                       "text/plain; charset=utf-8")
            self.send_bytes(200, app.page(screen), "text/html; charset=utf-8")

        def do_POST(self) -> None:
            if not self._host_ok():
                return self.fail(403, "host not allowed")
            if not origin_allowed(self.headers.get("Origin"), app.port):
                return self.fail(403, "origin not allowed")
            if not self._api_authorized():
                return self.fail(403, "missing or wrong token")
            try:
                length = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return self.fail(400, "bad length")
            if length > MAX_BODY:
                return self.fail(413, "request too large")
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw.decode("utf-8")) if raw else {}
            except (ValueError, UnicodeDecodeError):
                return self.fail(400, "the body must be JSON")
            if not isinstance(body, dict):
                return self.fail(400, "the body must be a JSON object")
            secret = body.get("key") if isinstance(body.get("key"), str) else ""
            try:
                return self.send_json(200, app.api_post(self.path.split("?")[0], body))
            except GuiError as exc:
                return self.fail(exc.status, logic.redact(str(exc), secret))
            except Exception as exc:
                return self.fail(500, f"internal error ({type(exc).__name__})")

        def _unsupported(self) -> None:
            self.fail(405, "method not allowed")

        do_PUT = do_DELETE = do_PATCH = _unsupported

    return Handler
