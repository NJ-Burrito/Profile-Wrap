"""Section 14 board security: token, Host, Origin, file allowlist, traversal, headers, degraded reads."""
from __future__ import annotations

import json
import os
import socket

import pytest
from board_helpers import PNG, make_draft

from njli.board import security
from njli.board.server import BoardServer, PortInUse


def test_health_works_without_a_token_and_names_the_board(board):
    srv, c = board
    code, body = c.get_json("/api/health")
    assert code == 200 and body["ok"] is True and body["board"] == "nj-linkedin"
    assert body["api"] == 1 and "paused" in body


def test_bad_token_is_403_and_changes_nothing(board, ws):
    srv, c = board
    d = make_draft(ws, "a1")
    for tok in ("wrong", "", None):
        code, body = c.post("/api/decision", {"slug": "a1", "action": "allow"}, token=tok)
        assert code == 403 and body["reload"] is True
    assert json.loads((d / "meta.json").read_text())["status"] == "draft"


def test_foreign_host_is_421_on_get_and_post(board):
    srv, c = board
    for host in ("evil.example", "evil.example:%d" % srv.port, "127.0.0.1.evil.example:%d" % srv.port,
                 "127.0.0.1:1", "localhost:9"):
        code, _h, _b = c.get("/api/health", host=host)
        assert code == 421, host
        code, _body = c.post("/api/decision", {"slug": "x", "action": "allow"}, host=host)
        assert code == 421, host


def test_missing_host_header_is_refused(board):
    srv, _c = board
    with socket.create_connection(("127.0.0.1", srv.port), timeout=10) as s:
        s.sendall(b"GET /api/health HTTP/1.0\r\n\r\n")
        data = b""
        while chunk := s.recv(4096):
            data += chunk
    assert data.split(b" ", 2)[1] == b"421"


def test_loopback_names_are_accepted(board):
    srv, c = board
    for host in (f"localhost:{srv.port}", f"127.0.0.1:{srv.port}"):
        assert c.get("/api/health", host=host)[0] == 200


def test_post_without_origin_or_with_foreign_origin_is_403(board, ws):
    srv, c = board
    make_draft(ws, "a1")
    assert c.post("/api/decision", {"slug": "a1", "action": "allow"}, origin=None)[0] == 403
    assert c.post("/api/decision", {"slug": "a1", "action": "allow"}, origin="https://evil.example")[0] == 403
    assert c.post("/api/decision", {"slug": "a1", "action": "allow"}, origin="http://127.0.0.1:1")[0] == 403
    assert c.post("/api/decision", {"slug": "a1", "action": "allow"}, origin="null")[0] == 403


def test_post_needs_json_and_a_bounded_body(board):
    srv, c = board
    assert c.post("/api/decision", raw_body=b"slug=a", ctype="application/x-www-form-urlencoded")[0] == 415
    assert c.post("/api/decision", raw_body=b"{not json")[0] == 400
    assert c.post("/api/decision", raw_body=b"[1,2]")[0] == 400
    big = json.dumps({"slug": "a1", "action": "improve", "note": "x" * (security.MAX_BODY + 10)}).encode()
    assert c.post("/api/decision", raw_body=big)[0] == 413


TRAVERSAL = [
    "/media/drafts/s1/..%2fmeta.json",
    "/media/drafts/s1/%252e%252e",
    "/media/drafts/s1/meta.json",
    "/media/drafts/..%2fdrafts%2fs1/card.png",
    "/media/drafts/s1/%2e%2e",
    "/media/drafts/s1/../../config/njli.json",
    "/media/drafts/%2e%2e/%2e%2e/config/njli.json",
    "/media/drafts/s1/%2e%2e%2f%2e%2e%2fmeta.json",
    "/media/drafts/s1/..%5c..%5cmeta.json",
    "/media/drafts/s1/%252e%252e/meta.json",
    "/media/drafts/.git/card.png",
    "/media/drafts/s1/.hidden.png",
    "/media/drafts/s1/card.png/../../meta.json",
    "/media/research/s1/card.png",
    "/media/drafts/s1/card.txt",
    "/fonts/..%2fconfig%2fnjli.json",
    "/fonts/../config/njli.json",
    "/fonts/%2e%2e/config/njli.json",
    "/research/facts.md",
    "/config/njli.json",
    "/profile/steps.json",
    "/.git/config",
    "/review/decisions.jsonl",
    "/engage/pending.json",
    "/app/../config/njli.json",
    "/i18n/../../config/njli.json",
    "/media/drafts/s1/c:%5cwindows%5cwin.ini",
    "/media/drafts/s1/card.png%00.txt",
]


@pytest.mark.parametrize("path", TRAVERSAL)
def test_traversal_and_dot_dirs_are_404(board, ws, path):
    srv, c = board
    d = make_draft(ws, "s1", media=True)
    (d / "out" / "card.txt").write_text("secret", encoding="utf-8")
    (ws / "brand" / "fonts").mkdir(parents=True)
    (d.parent / ".git").mkdir(exist_ok=True)
    (d.parent / ".git" / "out").mkdir(exist_ok=True)
    (d.parent / ".git" / "out" / "card.png").write_bytes(PNG)
    code, _h, data = c.get(path)
    assert code == 404, (path, code)
    assert b"secret" not in data and b"schema_version" not in data and b"persona" not in data


def test_allowed_files_are_served_with_the_security_headers(board, ws):
    srv, c = board
    make_draft(ws, "s1", media=True)
    (ws / "brand" / "fonts").mkdir(parents=True)
    (ws / "brand" / "fonts" / "Plex.woff2").write_bytes(b"wOF2")
    code, h, data = c.get("/media/drafts/s1/card.png")
    assert code == 200 and data == PNG and h["content-type"] == "image/png"
    assert h["x-content-type-options"] == "nosniff"
    assert "default-src 'none'" in h["content-security-policy"] and "frame-ancestors 'none'" in h["content-security-policy"]
    code, h, data = c.get("/fonts/Plex.woff2")
    assert code == 200 and data == b"wOF2" and h["content-type"] == "font/woff2"


def test_published_media_is_served_and_a_symlink_out_of_the_folder_is_refused(board, ws):
    srv, c = board
    d = make_draft(ws, "p1", "posted", base="published", media=True)
    assert c.get("/media/published/p1/card.png")[0] == 200
    secret = ws / "config" / "secret.png"
    secret.write_bytes(PNG)
    try:
        os.symlink(secret, d / "out" / "link.png")
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not available here")
    assert c.get("/media/published/p1/link.png")[0] == 404


def test_avatar_only_from_inside_the_workspace(start, ws):
    (ws / "brand" / "identity").mkdir(parents=True)
    (ws / "brand" / "identity" / "me.png").write_bytes(PNG)
    cfg = json.loads((ws / "config" / "njli.json").read_text())
    cfg["brand"] = {"identity": {"enabled": True, "name": "x", "role": "y", "photo": "brand/identity/me.png", "signature": "none"}}
    (ws / "config" / "njli.json").write_text(json.dumps(cfg))
    srv, c = start()
    assert c.get("/avatar")[0] == 200
    cfg["brand"]["identity"]["photo"] = "../outside.png"
    (ws / "config" / "njli.json").write_text(json.dumps(cfg))
    (ws.parent / "outside.png").write_bytes(PNG)
    assert c.get("/avatar")[0] == 404
    cfg["brand"]["identity"]["photo"] = "config/njli.json"
    (ws / "config" / "njli.json").write_text(json.dumps(cfg))
    assert c.get("/avatar")[0] == 404


def test_every_response_carries_the_hardening_headers(board, ws):
    srv, c = board
    make_draft(ws, "s1")
    for path in ("/", "/app/board.js", "/app/board.css", "/api/state", "/api/health", "/api/draft/s1", "/nothing"):
        code, h, _b = c.get(path)
        assert h["x-content-type-options"] == "nosniff", path
        assert "content-security-policy" in h and h["cache-control"] == "no-store", path
        assert h["x-frame-options"] == "DENY" and h["referrer-policy"] == "no-referrer", path


def test_the_token_appears_only_in_the_page_never_in_an_api_answer(board, ws):
    srv, c = board
    make_draft(ws, "s1", media=True)
    code, _h, page = c.get("/")
    assert code == 200 and srv.token.encode() in page
    for path in ("/api/state", "/api/health", "/api/draft/s1", "/api/pending", "/api/connect", "/api/profile",
                 "/api/metrics", "/api/settings", "/app/board.js", "/app/board.css", "/i18n/en.json", "/app/fonts.css"):
        code, _h, data = c.get(path)
        assert srv.token.encode() not in data, path


def test_the_page_has_no_inline_script_or_style_and_the_app_never_uses_innerhtml(board):
    srv, c = board
    page = c.get("/")[2].decode()
    assert "<script>" not in page and "<style" not in page and "onclick=" not in page and ' style="' not in page
    js = c.get("/app/board.js")[2].decode()
    assert "innerHTML" not in js and "document.write" not in js and "eval(" not in js


def test_other_methods_are_refused(board):
    srv, c = board
    for method in ("PUT", "DELETE", "PATCH"):
        code, _h, _b = c.request(method, "/api/state")
        assert code == 405


def test_corrupt_json_gives_a_degraded_200_not_a_dropped_connection(board, ws):
    srv, c = board
    d = make_draft(ws, "ok1")
    bad = make_draft(ws, "bad1")
    (bad / "meta.json").write_text("{not json", encoding="utf-8")
    (d / "gates.json").write_text("\x00\x01", encoding="utf-8")
    (d / "review.json").write_text("{", encoding="utf-8")
    (ws / "engage").mkdir()
    (ws / "engage" / "pending.json").write_text("[[[", encoding="utf-8")
    (ws / "engage" / "connect.json").write_text("nope", encoding="utf-8")
    (ws / "profile").mkdir()
    (ws / "profile" / "steps.json").write_text("}", encoding="utf-8")
    (ws / "published").mkdir()
    (ws / "published" / "ledger.jsonl").write_text('{"slug": "x"}\nnot json\n', encoding="utf-8")
    (ws / "config" / "njli.json").write_text("{", encoding="utf-8")
    code, state = c.get_json("/api/state")
    assert code == 200 and state["degraded"] is True and state["total"] == 2
    assert {p["slug"]: p["degraded"] for p in state["posts"]} == {"ok1": True, "bad1": True}
    assert state["config_problem"]
    assert c.get_json("/api/draft/bad1")[0] == 200
    assert c.get_json("/api/draft/ok1")[1]["degraded"] is True
    for path in ("/api/pending", "/api/connect", "/api/profile", "/api/metrics", "/api/settings"):
        code, body = c.get_json(path)
        assert code == 200, path
    assert c.get_json("/api/metrics")[1]["bad_ledger_lines"] == 1


def test_stale_token_after_a_restart_is_403_with_a_reload_hint(start, ws):
    srv1, c1 = start()
    make_draft(ws, "a1")
    old = srv1.token
    srv1.shutdown()
    srv2, c2 = start()
    assert srv2.token != old
    code, body = c2.post("/api/decision", {"slug": "a1", "action": "allow"}, token=old)
    assert code == 403 and body["reload"] is True
    js = (os.path.dirname(security.__file__) + "/app/board.js")
    text = open(js, encoding="utf-8").read()
    assert "res.status === 403" in text and "banner.stale" in text
    en = json.load(open(os.path.dirname(security.__file__) + "/i18n/en.json", encoding="utf-8"))
    assert "Reload" in en["banner.reload"] and "out of date" in en["banner.stale"]


def test_port_in_use_gives_a_plain_message(start, ws):
    srv, _c = start()
    with pytest.raises(PortInUse) as exc:
        BoardServer(ws, port=srv.port)
    assert "already in use" in str(exc.value) and "--port" in str(exc.value)


def test_a_non_loopback_bind_is_refused(ws):
    with pytest.raises(ValueError):
        BoardServer(ws, host="0.0.0.0", port=0)


def test_security_helpers_directly():
    assert security.host_allowed("127.0.0.1:8770", 8770) and security.host_allowed("LOCALHOST:8770", 8770)
    assert security.host_allowed("[::1]:8770", 8770)
    assert not security.host_allowed("127.0.0.1:8771", 8770) and not security.host_allowed(None, 8770)
    assert not security.host_allowed("127.0.0.1@evil.example:8770", 8770)
    good = security.LINKEDIN_PREFIX + "in/example"
    assert security.safe_linkedin_url(good)
    for bad in (good.replace("https", "http"), "https://linkedin.com.evil.example/", "javascript:alert(1)",
                good + " x", None, 5):
        assert security.safe_linkedin_url(bad) is None
