"""Shared fakes for the app tests (not a test module)."""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from profile_wrap.gui.server import GuiServer
from profile_wrap.providers import Result

# Assembled at run time so this file holds no key-shaped literal.
FAKE_KEY = "sk-" + "ant-" + "api03-" + "Zq8Lm2" * 5


class FakeKeyring:
    def __init__(self):
        self.store = {}

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        self.store.pop((service, name), None)


class FakeProvider:
    """Stands in for an adapter: no network. ``reply`` is what the model 'said'."""

    def __init__(self, reply='{"caption": "Short hook\\nOne true line.", "alt": "A plain slide."}', fail=None):
        self.reply, self.fail, self.calls = reply, fail, []

    def __call__(self, pid, model=None, base_url=None, *a, **k):
        self.pid, self.model = pid, model or "fake-model"
        return self

    def api_key(self):
        return FAKE_KEY

    def complete(self, system, messages, **kw):
        self.calls.append((system, messages, kw))
        if self.fail:
            raise self.fail
        return Result(text=self.reply, provider=self.pid, model=self.model)


class Client:
    def __init__(self, server: GuiServer):
        self.s = server
        self.base = f"http://127.0.0.1:{server.port}"

    def call(self, method, path, body=None, headers=None, raw=None):
        h = {"X-PW-Token": self.s.token, "Origin": self.base}
        h.update(headers or {})
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        if data is not None:
            h.setdefault("Content-Type", "application/json")
        h = {k: v for k, v in h.items() if v is not None}
        req = urllib.request.Request(self.base + path, data=data, method=method, headers=h)
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        try:
            with opener.open(req, timeout=20) as r:
                return r.status, r.read(), dict(r.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(), dict(exc.headers)

    def get(self, path, **kw):
        status, body, hdr = self.call("GET", path, **kw)
        try:
            return status, json.loads(body)
        except ValueError:
            return status, body

    def post(self, path, body=None, **kw):
        status, raw, hdr = self.call("POST", path, body if body is not None else {}, **kw)
        try:
            return status, json.loads(raw)
        except ValueError:
            return status, raw
