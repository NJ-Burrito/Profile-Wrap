"""The real entry points (python -m profile_wrap board / review), the UI strings, and the doc."""
from __future__ import annotations

import json
import re
import socket
import subprocess
import sys
import time

from board_helpers import REPO, make_draft, meta_of

BOARD = REPO / "profile_wrap" / "board"


def run(*argv, ws, env_extra=None, timeout=120):
    import os
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO), **(env_extra or {})}
    return subprocess.run([sys.executable, "-m", "profile_wrap", *argv, "--workspace", str(ws)], capture_output=True, text=True,
                          env=env, timeout=timeout, cwd=str(REPO))


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_review_list_allow_reject_through_the_real_cli(ws):
    make_draft(ws, "c1")
    make_draft(ws, "c2")
    r = run("review", "list", ws=ws)
    assert r.returncode == 0 and "c1" in r.stdout and "c2" in r.stdout, r.stderr
    r = run("review", "allow", "c1", ws=ws)  # no terminal and no --yes: refuses
    assert r.returncode == 1 and meta_of(ws / "drafts" / "c1")["status"] == "draft"
    r = run("review", "allow", "c1", "--yes", ws=ws)
    assert r.returncode == 0, r.stderr
    assert meta_of(ws / "drafts" / "c1")["status"] == "queued"
    r = run("review", "allow", "c1", "--yes", ws=ws)
    assert r.returncode == 3  # conflict: already queued
    r = run("review", "reject", "c2", "--yes", ws=ws)
    assert r.returncode == 0 and meta_of(ws / "drafts" / "c2")["status"] == "rejected"
    r = run("review", "list", "--status", "queued", "--json", ws=ws)
    assert [p["slug"] for p in json.loads(r.stdout)] == ["c1"]


def test_the_cli_refuses_allow_for_a_worker_and_improve_without_a_worker(ws):
    make_draft(ws, "w1")
    r = run("review", "allow", "w1", "--yes", ws=ws, env_extra={"PROFILE_WRAP_WORKER": "1"})
    assert r.returncode == 1 and "worker" in r.stderr.lower() and meta_of(ws / "drafts" / "w1")["status"] == "draft"
    r = run("review", "improve", "w1", "--note", "shorter", ws=ws)
    assert r.returncode == 1 and meta_of(ws / "drafts" / "w1")["status"] == "draft"


def test_profile_wrap_board_starts_answers_health_and_stops(ws):
    import http.client
    import os
    port = free_port()
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": str(REPO), "PROFILE_WRAP_TEST": "1"}
    proc = subprocess.Popen([sys.executable, "-m", "profile_wrap", "board", "--port", str(port), "--workspace", str(ws)],
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env, cwd=str(REPO))
    try:
        body = None
        end = time.time() + 60
        while time.time() < end and body is None:
            try:
                conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                body = json.loads(resp.read())
                assert resp.status == 200
            except (OSError, ValueError):
                time.sleep(0.3)
        assert body and body["ok"] is True, "the board never answered /api/health"
        # a second board on the same port gives the plain message and a non-zero exit
        r = run("board", "--port", str(port), ws=ws)
        assert r.returncode != 0 and "already in use" in r.stderr
    finally:
        proc.terminate()
        try:
            proc.wait(15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(10)
    assert proc.poll() is not None


# ----------------------------------------------------------------- i18n

def _keys_used_by_the_app():
    js = (BOARD / "app" / "board.js").read_text(encoding="utf-8")
    static = set(re.findall(r"\bt\(\"([a-z0-9_.]+[a-z0-9_])\"", js))
    msg = set(re.findall(r'"(msg\.[a-z]+)"', js))
    return static | msg, js


def test_en_and_ar_have_the_same_keys_and_no_empty_values():
    en = json.loads((BOARD / "i18n" / "en.json").read_text(encoding="utf-8"))
    ar = json.loads((BOARD / "i18n" / "ar.json").read_text(encoding="utf-8"))
    assert set(en) == set(ar)
    assert all(isinstance(v, str) and v.strip() for v in list(en.values()) + list(ar.values()))
    for key, value in en.items():  # placeholders must match across languages
        assert sorted(re.findall(r"\{[a-z]+\}", value)) == sorted(re.findall(r"\{[a-z]+\}", ar[key])), key
    assert any(re.search(r"[\u0600-\u06FF]", v) for v in ar.values())
    for key, value in ar.items():  # Arabic hygiene: no Persian letters, no tatweel, no Latin comma/question mark
        assert not re.search(r"[\u06CC\u06A9\u0640]", value), key
        assert "," not in value and "?" not in value, key


def test_every_string_the_app_asks_for_exists_in_both_languages():
    from profile_wrap import policy
    en = json.loads((BOARD / "i18n" / "en.json").read_text(encoding="utf-8"))
    used, js = _keys_used_by_the_app()
    missing = sorted(k for k in used if k not in en)
    assert not missing, missing
    # keys built at run time
    dynamic = [f"status.{s}" for s in policy.POST_STATUSES] + [f"tab.{t}" for t in ("posts", "comments", "connect", "profile", "metrics", "settings")]
    dynamic += [f"gate.{g}" for g in ("pass", "fail")] + [f"verdict.{v}" for v in ("pass", "revise", "blockers", "invalid")]
    dynamic += [f"kind.{k}" for k in ("comment", "reply", "posting", "comments", "all")]
    dynamic += [f"connect.action.{a}" for a in ("connect", "follow")] + [f"ack.{a}" for a in ("valid", "stale", "missing", "unknown")]
    dynamic += [f"settings.mode.{m}" for m in ("posting", "comments", "reading", "likes")]
    dynamic += [f"warn.{w}" for w in ("no_schedule", "past_missed_window", "bad_schedule")]
    dynamic += ["msg.allow", "msg.reject", "msg.improve", "msg.done", "msg.skipped", "msg.sent", "msg.pause"]
    assert not [k for k in dynamic if k not in en], [k for k in dynamic if k not in en]


def test_every_error_code_the_server_can_return_has_a_message():
    en = json.loads((BOARD / "i18n" / "en.json").read_text(encoding="utf-8"))
    src = "".join((BOARD / f).read_text(encoding="utf-8") for f in ("actions.py", "server.py"))
    codes = set(re.findall(r'_err\(\d+, "([a-z_]+)"', src)) | set(re.findall(r'"error": "([a-z_]+)"', src))
    codes -= {"internal", "bad_host", "bad_json", "length_required"}
    missing = sorted(c for c in codes if f"err.{c}" not in en)
    assert not missing, missing


def test_the_page_switches_to_rtl_for_arabic():
    js = (BOARD / "app" / "board.js").read_text(encoding="utf-8")
    assert 'document.documentElement.dir = lang === "ar" ? "rtl" : "ltr"' in js
    css = (BOARD / "app" / "board.css").read_text(encoding="utf-8")
    assert "margin-inline-start" in css and "inset-inline-start" in css


def test_the_feed_has_no_aria_live_region_only_the_toast():
    html = (BOARD / "app" / "index.html").read_text(encoding="utf-8")
    js = (BOARD / "app" / "board.js").read_text(encoding="utf-8")
    assert html.count("aria-live") == 1 and 'id="toast"' in html and "aria-live" not in js


def test_no_machine_specific_or_secret_shaped_text_in_the_board_files():
    patterns = [re.compile(r"[A-Za-z]:[\\]"), re.compile(r"/(Users|home)/[a-z]"), re.compile(r"[\w.+-]+@[\w-]+\.[a-z]{2,}"),
                re.compile(r"(?:sk|apify_api|xox[bp])[-_][A-Za-z0-9]{12,}"), re.compile(r"li_at|JSESSIONID")]
    scanned = 0
    for path in list(BOARD.rglob("*")) + [REPO / "docs" / "references" / "review-board.md"]:
        if path.is_file() and path.suffix in (".py", ".js", ".css", ".html", ".json", ".md"):
            scanned += 1
            text = path.read_text(encoding="utf-8")
            for pat in patterns:
                assert not pat.search(text), (path.name, pat.pattern)
    assert scanned >= 10
