"""The non-post tabs: comments to post, Connect, Profile fixes, Metrics, Settings, and concurrent writers."""
from __future__ import annotations

import json
import threading

from board_helpers import make_draft, read_decisions

LI = "https://www.linkedin.com/"


def write(ws, rel, obj):
    p = ws / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj), encoding="utf-8")


# ----------------------------------------------------------------- profile

def test_profile_tab_empty_state_works_and_explains_how_to_start(board, ws):
    srv, c = board
    code, body = c.get_json("/api/profile")
    assert code == 200 and body["empty"] is True and body["steps"] == [] and body["total"] == 0
    assert body["steps_file"] == "profile/steps.json" and body["degraded"] is False
    # the UI side of the empty state: both languages carry its title and body
    en = json.loads(open(_i18n("en"), encoding="utf-8").read())
    ar = json.loads(open(_i18n("ar"), encoding="utf-8").read())
    for k in ("profile.empty.title", "profile.empty.body"):
        assert en[k] and ar[k]
    js = open(_js(), encoding="utf-8").read()
    assert "p.empty" in js and "profile.empty.title" in js


def _i18n(lang):
    import profile_wrap.board.server as s
    return str(s.I18N_DIR / f"{lang}.json")


def _js():
    import profile_wrap.board.server as s
    return str(s.APP_DIR / "board.js")


def test_profile_steps_done_state_lives_on_the_server_and_links_are_checked(board, ws):
    srv, c = board
    write(ws, "profile/steps.json", {"schema_version": 1, "steps": [
        {"id": "s1", "section": "Headline", "title": "Rewrite the headline", "text": "A new headline", "open": LI + "in/me/edit"},
        {"id": "s2", "section": "About", "title": "Trim the about", "open": "https://evil.example/phish"},
        {"id": "s3", "title": "Bad scheme", "open": "javascript:alert(1)"}]})
    code, body = c.get_json("/api/profile")
    assert code == 200 and body["total"] == 3 and body["done"] == 0
    by = {s["id"]: s for s in body["steps"]}
    assert by["s1"]["open"] == LI + "in/me/edit" and by["s1"]["open_refused"] is False
    assert by["s2"]["open"] is None and by["s2"]["open_refused"] is True
    assert by["s3"]["open"] is None
    assert c.post("/api/profile-done", {"id": "s1", "done": True})[0] == 200
    assert json.loads((ws / "profile" / "progress.json").read_text())["done"].keys() == {"s1"}
    assert c.get_json("/api/profile")[1]["done"] == 1
    assert c.post("/api/profile-done", {"id": "nope", "done": True})[0] == 404
    assert c.post("/api/profile-done", {"id": "s1", "done": False})[0] == 200
    assert c.get_json("/api/profile")[1]["done"] == 0


# ----------------------------------------------------------------- connect

def test_connect_shows_only_waiting_people_with_safe_links_and_closes_once(board, ws):
    srv, c = board
    write(ws, "engage/connect.json", {"schema_version": 1, "rows": [
        {"name": "Ana Demo", "profile_url": LI + "in/ana-demo", "status": "waiting", "note": "Hi Ana", "score": 9, "fictional": True},
        {"name": "Ben Demo", "profile_url": "https://evil.example/x", "status": "waiting", "action": "follow"},
        {"name": "Cy Demo", "profile_url": LI + "in/cy", "status": "sent"}]})
    code, body = c.get_json("/api/connect")
    assert code == 200 and [r["name"] for r in body["connect"]] == ["Ana Demo", "Ben Demo"]
    assert body["connect"][1]["profile_url"] is None and body["connect"][1]["action"] == "follow"
    ana = body["connect"][0]["id"]
    assert c.post("/api/connect-done", {"id": ana, "action": "done"})[0] == 200
    saved = json.loads((ws / "engage" / "connect.json").read_text())
    assert saved["rows"][0]["status"] == "sent" and saved["rows"][2]["status"] == "sent"
    assert c.post("/api/connect-done", {"id": ana, "action": "done"})[0] == 409
    assert c.post("/api/connect-done", {"id": "zzz", "action": "done"})[0] == 404
    assert c.post("/api/connect-done", {"id": ana, "action": "bogus"})[0] == 400
    assert len(c.get_json("/api/connect")[1]["connect"]) == 1


def test_connect_accepts_a_bare_list_from_an_older_export(board, ws):
    srv, c = board
    write(ws, "engage/connect.json", [{"name": "Old Demo", "profile_url": LI + "in/old", "status": "waiting"}])
    item = c.get_json("/api/connect")[1]["connect"][0]["id"]
    assert c.post("/api/connect-done", {"id": item, "action": "skip"})[0] == 200
    assert json.loads((ws / "engage" / "connect.json").read_text())[0]["status"] == "skipped"


# ----------------------------------------------------------------- comments

def test_comments_to_post_done_appends_to_the_shared_log_once(board, ws):
    srv, c = board
    write(ws, "engage/pending.json", {"schema_version": 1, "items": [
        {"urn": "urn:li:share:1", "kind": "comment", "author": "Dana Demo", "text": "Good point about reports.", "status": "pending", "url": LI + "feed/update/1"},
        {"urn": "urn:li:share:2", "kind": "reply", "author": "Eli Demo", "text": "Thanks for reading.", "status": "pending", "url": "javascript:x"},
        {"urn": "urn:li:share:3", "kind": "comment", "text": "Already done", "status": "posted"}]})
    code, body = c.get_json("/api/pending")
    assert code == 200 and len(body["pending"]) == 2 and body["pending"][1]["url"] is None
    first, second = (p["id"] for p in body["pending"])
    assert c.post("/api/pending-done", {"id": first, "action": "done"})[0] == 200
    assert c.post("/api/pending-done", {"id": first, "action": "done"})[0] == 409
    assert c.post("/api/pending-done", {"id": second, "action": "skip"})[0] == 200
    log = [json.loads(x) for x in (ws / "published" / "comments.jsonl").read_text().splitlines()]
    assert len(log) == 1 and log[0]["mode"] == "hand" and log[0]["text"].startswith("Good point")
    assert [r["status"] for r in json.loads((ws / "engage" / "pending.json").read_text())["items"]] == ["posted", "skipped", "posted"]
    assert any(r["action"] == "comment-posted" for r in read_decisions(ws))


def test_concurrent_writers_lose_no_update(board, ws):
    srv, c = board
    n = 16
    write(ws, "engage/pending.json", {"schema_version": 1, "items": [
        {"urn": f"urn:li:share:{i}", "kind": "comment", "text": f"comment number {i}", "status": "pending"} for i in range(n)]})
    ids = [p["id"] for p in c.get_json("/api/pending")[1]["pending"]]
    codes = []
    barrier = threading.Barrier(n)

    def go(item):
        barrier.wait()
        codes.append(c.post("/api/pending-done", {"id": item, "action": "done"})[0])

    ts = [threading.Thread(target=go, args=(i,)) for i in ids]
    [t.start() for t in ts]
    [t.join(120) for t in ts]
    assert codes.count(200) == n, codes
    rows = json.loads((ws / "engage" / "pending.json").read_text())["items"]
    assert all(r["status"] == "posted" for r in rows)
    assert len((ws / "published" / "comments.jsonl").read_text().splitlines()) == n


def test_concurrent_writers_on_different_files_and_drafts(board, ws):
    srv, c = board
    for i in range(6):
        make_draft(ws, f"d{i}")
    write(ws, "profile/steps.json", {"schema_version": 1, "steps": [{"id": f"s{i}", "title": "t", "open": LI} for i in range(6)]})
    results = []

    def decide(i):
        results.append(c.decide(f"d{i}", "reject", confirm=True)[0])

    def step(i):
        results.append(c.post("/api/profile-done", {"id": f"s{i}", "done": True})[0])

    ts = [threading.Thread(target=f, args=(i,)) for i in range(6) for f in (decide, step)]
    [t.start() for t in ts]
    [t.join(120) for t in ts]
    assert results.count(200) == 12
    assert len(json.loads((ws / "profile" / "progress.json").read_text())["done"]) == 6
    assert len([r for r in read_decisions(ws) if r["action"] == "reject"]) == 6


# ----------------------------------------------------------- metrics, settings

def test_metrics_tab_reads_the_ledger_and_the_queue(board, ws):
    srv, c = board
    make_draft(ws, "q1", "queued", scheduled_at="2030-01-01T10:00:00+00:00")
    (ws / "published").mkdir()
    (ws / "published" / "ledger.jsonl").write_text(
        json.dumps({"slug": "p1", "state": "posted", "title": "Posted one", "url": LI + "feed/update/1", "posted_at": "2026-01-01T10:00:00+00:00"}) + "\n"
        + json.dumps({"slug": "p2", "state": "posted", "title": "Bad link", "url": "http://evil.example"}) + "\n", encoding="utf-8")
    (ws / "metrics").mkdir()
    (ws / "metrics" / "track.jsonl").write_text(json.dumps({"date": "2026-01-02", "followers": 120}) + "\n", encoding="utf-8")
    code, m = c.get_json("/api/metrics")
    assert code == 200 and [q["slug"] for q in m["queued"]] == ["q1"]
    assert [p["url"] for p in m["posts"]] == [LI + "feed/update/1", None]
    assert m["snapshots"][0]["followers"] == 120


def test_settings_tab_reports_modes_acks_doctor_pause_and_the_token(board, ws):
    srv, c = board
    code, s = c.get_json("/api/settings")
    assert code == 200
    assert s["modes"]["posting"] in ("copy", "api_click", "api_scheduled") and s["modes"]["likes"] is False
    assert set(s["acks"]) >= {"terms_read", "api_scheduled", "comments_api", "apify", "likes"}
    assert s["doctor"]["checks"] and any(ch["id"] == "token" for ch in s["doctor"]["checks"])
    assert s["pause"] == [] and s["caps"]["comments_replies_per_day_max"] == 10
    assert s["board"]["port"] == srv.port and "/" not in s["workspace"] and "\\" not in s["workspace"]


def test_settings_shows_an_expired_token_banner_source(start, ws, tmp_path):
    from profile_wrap import paths
    cfg_dir = paths.config_dir("default")
    cfg_dir.mkdir(parents=True)
    (cfg_dir / "token.json").write_text(json.dumps({"access_token": "SECRET-TOKEN-VALUE", "expires_at": 1000}), encoding="utf-8")
    srv, c = start()
    code, s = c.get_json("/api/settings")
    assert s["token"]["status"] == "fail" and "expired" in s["token"]["detail"]
    assert "SECRET-TOKEN-VALUE" not in json.dumps(s)


def test_the_draft_detail_loads_the_caption_on_demand_and_shows_the_seats(board, ws):
    srv, c = board
    d = make_draft(ws, "dd1", media=True, caption="Hello detail caption.\n")
    (d / "review").mkdir()
    (d / "review" / "council-editor.json").write_text(json.dumps(
        {"seat": "council-editor", "verdict": "blockers", "blockers": [{"where": "line 1", "quote": "x", "fix": "y"}]}), encoding="utf-8")
    (d / "first_comment.txt").write_text("First!\n", encoding="utf-8")
    state = c.get_json("/api/state")[1]
    assert "caption" not in state["posts"][0]
    code, det = c.get_json("/api/draft/dd1")
    assert code == 200 and det["caption"].startswith("Hello detail") and det["first_comment"].startswith("First")
    assert det["media"] == ["/media/drafts/dd1/card.png"] and det["seats"][0]["verdict"] == "blockers"
    assert det["can"] == {"allow": True, "reject": True, "improve": True}
    assert c.get_json("/api/draft/missing")[0] == 404
    assert c.get_json("/api/draft/..%2f..")[0] == 404


def test_arabic_posts_preview_right_to_left(board, ws):
    srv, c = board
    make_draft(ws, "ar1", lang="ar", caption="مرحباً بكم\n")
    det = c.get_json("/api/draft/ar1")[1]
    assert det["rtl"] is True and det["caption"].startswith("مرحباً")
