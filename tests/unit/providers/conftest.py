"""Mock provider server (127.0.0.1, no network) and a fake keychain."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from prov_helpers import FakeKeyring

class Mock:
    def __init__(self):
        self.requests = []
        self.responses = {}   # path -> (status, body dict or str, extra headers)
        self.server = None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server.server_address[1]}"

    def reply(self, path: str, body, status: int = 200, headers=None):
        self.responses[path] = (status, body, headers or {})

    def last(self):
        return self.requests[-1]


@pytest.fixture()
def mock():
    m = Mock()

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep test output quiet
            pass

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n)
            m.requests.append({"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()},
                               "json": json.loads(raw or b"{}")})
            status, body, extra = m.responses.get(self.path, (404, {"error": "no route"}, {}))
            data = body if isinstance(body, str) else json.dumps(body)
            self.send_response(status)
            for k, v in extra.items():
                self.send_header(k, v)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data.encode())))
            self.end_headers()
            self.wfile.write(data.encode())

    m.server = ThreadingHTTPServer(("127.0.0.1", 0), H)
    t = threading.Thread(target=m.server.serve_forever, daemon=True)
    t.start()
    yield m
    m.server.shutdown()
    m.server.server_close()
    t.join(timeout=5)


@pytest.fixture()
def keychain(monkeypatch):
    from profile_wrap.providers import keystore
    fake = FakeKeyring()
    monkeypatch.setattr(keystore, "_keyring", lambda: fake)
    return fake


@pytest.fixture()
def nokeychain(monkeypatch):
    from profile_wrap.providers import keystore
    monkeypatch.setattr(keystore, "_keyring", lambda: None)


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path):
    import os
    for name in list(os.environ):
        if name.startswith("PROFILE_WRAP_") and name.endswith("_API_KEY"):
            monkeypatch.delenv(name)
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("PROFILE_WRAP_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")
