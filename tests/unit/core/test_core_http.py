from __future__ import annotations

import json
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from profile_wrap import http, policy


class Recorder(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *a):  # silence
        pass

    def _reply(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        Recorder.seen.append({"path": self.path, "headers": dict(self.headers), "body": body,
                              "method": self.command})
        path = self.path.split("?")[0]
        if path == "/rest/posts/429":
            self.send_response(429)
        elif path == "/rest/posts/500":
            self.send_response(503)
        elif path == "/rest/posts/403":
            self.send_response(403)
        elif path == "/rest/posts/404":
            self.send_response(404)
        elif path == "/rest/posts/redirect":
            self.send_response(302)
            self.send_header("Location", "https://evil.example/steal")
        elif path == "/rest/posts/slow":
            time.sleep(1.5)
            self.send_response(200)
        else:
            self.send_response(201)
        self.send_header("Content-Type", "application/json")
        payload = b'{"ok": true}'
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except OSError:   # the client gave up (timeout test)
            pass

    do_GET = do_POST = do_PUT = _reply


@pytest.fixture()
def server():
    Recorder.seen = []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Recorder)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


@pytest.fixture()
def test_mode(monkeypatch, server):
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", server)
    return server


API = "https://api.linkedin.com"


def test_allowlist_decisions():
    ok = lambda url, **kw: http.check_url(url, kw.pop("hp", None), **kw)  # noqa: E731
    assert ok(f"{API}/rest/posts") == "api.linkedin.com"
    assert ok(f"{API}/v2/userinfo") == "api.linkedin.com"
    assert ok(f"{API}/rest/images?action=initializeUpload")
    assert ok("https://www.linkedin.com/oauth/v2/accessToken") == "www.linkedin.com"
    for bad in (f"{API}/v2/me", f"{API}/rest/postsX", f"{API}/rest/messages",
                "https://www.linkedin.com/feed/", "http://api.linkedin.com/rest/posts",
                "https://evil.example/x", "ftp://api.linkedin.com/rest/posts", "https:///x",
                "https://127.0.0.1:9/x"):
        with pytest.raises(http.HttpError) as exc:
            ok(bad)
        assert exc.value.kind in ("blocked_host", "blocked_endpoint"), bad


def test_upload_hosts_are_limited_to_linkedin_domains():
    assert http.check_url("https://www.linkedin.com/dms-uploads/abc", upload=True)
    assert http.check_url("https://media.licdn.com/dms/image/abc", upload=True)
    for hostile in ("https://evil.example/upload", "https://linkedin.com.evil.example/u",
                    "https://notlinkedin.com/u"):
        with pytest.raises(http.HttpError):
            http.check_url(hostile, upload=True)
    with pytest.raises(http.HttpError):                       # not an upload: licdn is refused
        http.check_url("https://media.licdn.com/dms/image/abc")


def test_apify_and_extra_hosts_need_permission():
    with pytest.raises(http.HttpError, match="Apify"):
        http.check_url("https://api.apify.com/v2/acts")
    assert http.check_url("https://api.apify.com/v2/acts", http.HostPolicy(apify_ack=True))
    with pytest.raises(http.HttpError):
        http.check_url("https://news.example/feed.xml")
    assert http.check_url("https://news.example/feed.xml",
                          http.HostPolicy(extra_hosts=["News.Example"]))
    assert http.check_url(f"{API}/v2/me", http.HostPolicy(extra_endpoints=["/v2/me"]))


def test_loopback_only_in_test_or_demo(monkeypatch):
    with pytest.raises(http.HttpError, match="tests or demo"):
        http.check_url("http://127.0.0.1:9/x")
    assert http.check_url("http://127.0.0.1:9/x", http.HostPolicy(demo=True)) == "127.0.0.1"
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    assert http.check_url("http://localhost:9/x") == "localhost"
    with pytest.raises(http.HttpError, match="only 127.0.0.1"):
        http.check_url("https://news.example/x", http.HostPolicy(demo=True, extra_hosts=["news.example"]))


def test_override_is_ignored_outside_test_and_demo(monkeypatch, server):
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", server)
    assert http.override_base(http.HostPolicy()) is None
    assert http.override_base(http.HostPolicy(demo=True)) == server
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", "https://evil.example")
    assert http.override_base(http.HostPolicy(demo=True)) is None   # only loopback overrides
    # without test/demo the real host is the only target and the fake server never sees it
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", server)
    assert http._rewrite(f"{API}/rest/posts", http.HostPolicy()) == f"{API}/rest/posts"


def test_request_sends_neutral_ua_version_and_token(test_mode):
    resp = http.request("POST", f"{API}/rest/posts", json_body={"a": 1}, token="TOKEN-123",
                        linkedin_version="202601", contact="me@example.invalid")
    assert resp.status == 201 and resp.ok and resp.json() == {"ok": True}
    seen = Recorder.seen[-1]
    h = {k.lower(): v for k, v in seen["headers"].items()}
    assert h["authorization"] == "Bearer TOKEN-123"
    assert h["linkedin-version"] == "202601"
    assert h["x-restli-protocol-version"] == "2.0.0"
    assert h["user-agent"].startswith("profile-wrap/") and "me@example.invalid" in h["user-agent"]
    assert json.loads(seen["body"]) == {"a": 1}
    assert h["content-type"] == "application/json"
    assert seen["path"] == "/rest/posts"


def test_api_host_requires_a_version(test_mode):
    with pytest.raises(http.HttpError) as exc:
        http.request("GET", f"{API}/v2/userinfo", token="t")
    assert exc.value.kind == "no_version"
    assert Recorder.seen == []


def test_token_never_goes_to_other_hosts(test_mode, monkeypatch):
    # a configured public feed host: allowed to be fetched, never with the token
    with pytest.raises(http.HttpError, match="never sent"):
        http.request("GET", "https://news.example/feed", token="TOKEN-123",
                     hp=http.HostPolicy(extra_hosts=["news.example"]))
    with pytest.raises(http.HttpError, match="never sent"):
        http.request("PUT", "https://media.licdn.com/up", token="TOKEN-123", upload=True)
    assert Recorder.seen == []
    assert http.token_allowed("api.linkedin.com") and http.token_allowed("www.linkedin.com")
    assert not http.token_allowed("media.licdn.com") and not http.token_allowed("evil.example")
    assert http.token_allowed("127.0.0.1")                        # PROFILE_WRAP_TEST=1 is set here
    monkeypatch.delenv("PROFILE_WRAP_TEST")
    assert not http.token_allowed("127.0.0.1")                    # loopback only in test or demo
    assert http.token_allowed("127.0.0.1", http.HostPolicy(demo=True))


def test_endpoint_allowlist_holds_even_with_the_override(test_mode):
    with pytest.raises(http.HttpError) as exc:
        http.request("GET", f"{API}/v2/messages", token="t", linkedin_version="202601")
    assert exc.value.kind == "blocked_endpoint"
    assert Recorder.seen == []


def test_429_and_5xx_stop_the_run_and_403_is_opt_in(test_mode):
    for path, status in (("429", 429), ("500", 503)):
        with pytest.raises(http.HttpError) as exc:
            http.request("POST", f"{API}/rest/posts/{path}", linkedin_version="202601")
        assert exc.value.kind == "stop" and exc.value.status == status
        assert exc.value.response.status == status and exc.value.maybe_sent
    assert http.request("GET", f"{API}/rest/posts/403", linkedin_version="202601").status == 403
    with pytest.raises(http.HttpError) as exc:
        http.request("GET", f"{API}/rest/posts/403", linkedin_version="202601", stop_on=(403, 429))
    assert exc.value.kind == "stop"
    resp = http.request("GET", f"{API}/rest/posts/404", linkedin_version="202601")
    assert resp.status == 404 and not resp.ok


def test_redirects_are_not_followed(test_mode):
    resp = http.request("GET", f"{API}/rest/posts/redirect", token="TOKEN-123",
                        linkedin_version="202601")
    assert resp.status == 302
    assert resp.headers["location"] == "https://evil.example/steal"
    assert len(Recorder.seen) == 1


def test_timeout_is_classified_as_maybe_sent(test_mode):
    with pytest.raises(http.HttpError) as exc:
        http.request("POST", f"{API}/rest/posts/slow", linkedin_version="202601", timeout=0.3)
    assert exc.value.kind == "timeout" and exc.value.maybe_sent


def test_connection_refused_is_a_network_error_not_maybe_sent(monkeypatch):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", f"http://127.0.0.1:{port}")
    with pytest.raises(http.HttpError) as exc:
        http.request("GET", f"{API}/v2/userinfo", linkedin_version="202601", timeout=10)
    assert exc.value.kind == "network" and not exc.value.maybe_sent


def test_reachable(server):
    port = int(server.rsplit(":", 1)[1])
    ok, msg = http.reachable("127.0.0.1", port, timeout=2)
    assert ok and "reachable" in msg
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead = sock.getsockname()[1]
    sock.close()
    ok, msg = http.reachable("127.0.0.1", dead, timeout=8)
    assert not ok and ("cannot reach" in msg or "timed out" in msg)
    ok, msg = http.reachable("no-such-host.invalid", 443, timeout=3)
    assert not ok


def test_response_helpers():
    r = http.Response(200, {}, b'\xef\xbb\xbf{"a": 1}')
    assert r.json() == {"a": 1} and r.text().endswith("}")
    assert http.user_agent() == f"profile-wrap/{http.__version__}"
    assert policy.LINKEDIN_API_HOST in http.policy.LINKEDIN_TOKEN_HOSTS
