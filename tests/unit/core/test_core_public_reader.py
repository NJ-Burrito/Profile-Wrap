"""The free public reading provider: parsing, acknowledgement, limits, headers. No real network."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from profile_wrap import config, http, policy
from profile_wrap.linkedin import public_reader as pr

FIX = Path(__file__).resolve().parents[2] / "fixtures" / "public"
PROFILE = (FIX / "profile.html").read_text(encoding="utf-8")
POST = (FIX / "post.html").read_text(encoding="utf-8")
POST_URL = "https://www.linkedin.com/posts/alex-example_one-activity-1-AAAA"


class Handler(BaseHTTPRequestHandler):
    seen: list = []
    status = 200

    def log_message(self, *a):
        pass

    def do_GET(self):
        Handler.seen.append({"path": self.path, "headers": dict(self.headers), "method": "GET"})
        body = (PROFILE if self.path.startswith("/in/") else POST).encode()
        self.send_response(Handler.status)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


@pytest.fixture()
def server(monkeypatch):
    Handler.seen, Handler.status = [], 200
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", f"http://127.0.0.1:{srv.server_address[1]}")
    yield srv
    srv.shutdown()
    srv.server_close()
    t.join(timeout=5)


def reader(tmp_path, ack=True, pages=30, gap=3, sleeps=None, now=None):
    cfg = config.defaults("Europe/Lisbon")
    cfg["engagement"]["reading"]["public"] = {"max_pages_per_day": pages, "gap_seconds": gap}
    log = sleeps if sleeps is not None else []
    return pr.PublicReader(cfg, tmp_path, ack_valid=ack, sleep=log.append, clock=lambda: 0.0,
                           today=lambda: "2026-10-19", **({"now": now} if now else {}))


def test_profile_json_ld_parse_from_fixture():
    posts = pr.posts_from_page(PROFILE)
    assert [p["author"] for p in posts] == ["Alex Example", "Alex Example"]
    first = posts[0]
    assert first["url"].endswith("AAAA") and first["published"].startswith("2026-10-15")
    assert first["text"] == "First public post text"
    assert (first["reactions"], first["comments"]) == (12, 3)
    assert posts[1]["comments"] == 0 and posts[1]["source"] == "public"


def test_post_page_parse_from_fixture():
    assert pr.stats_from_page(POST) == {"reactions": 40, "comments": 2}
    comments = pr.comments_from_page(POST)
    assert [c["text"] for c in comments] == ["Great point", "Agreed"]
    assert comments[0]["author"]["profile_url"].endswith("/in/sam-example")
    assert all(c["source"] == "public" and c["urn_known"] is False for c in comments)
    assert "error" in pr.stats_from_page("<html>nothing</html>")


def test_refused_without_ack(tmp_path, server):
    r = reader(tmp_path, ack=False)
    with pytest.raises(pr.PublicReadError) as e:
        r.profile_posts("alex-example")
    assert e.value.kind == "no_ack"
    assert r.post_stats(POST_URL)["kind"] == "no_ack"
    assert Handler.seen == []
    with pytest.raises(http.HttpError):     # the host policy itself refuses without the ack
        http.check_url(POST_URL)
    assert http.check_url(POST_URL, http.HostPolicy(public_ack=True)) == "www.linkedin.com"


def test_config_needs_ack_and_validates_limits():
    c = config.defaults("Europe/Lisbon")
    c["engagement"]["reading"]["provider"] = "public"
    assert any("config ack public" in e for e in config.validate(c).errors)
    assert "public" in policy.ACK_ACTIONS
    c["engagement"]["reading"]["public"]["gap_seconds"] = 1
    c["engagement"]["reading"]["public"]["max_pages_per_day"] = 0
    errs = config.validate(c).errors
    assert any("gap_seconds" in e for e in errs) and any("max_pages_per_day" in e for e in errs)
    ok = config.defaults("Europe/Lisbon")
    assert config.validate(ok).ok and ok["engagement"]["reading"]["public"]["max_pages_per_day"] == 30


def test_ack_roundtrip_and_stale(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    config.ack(ws, "public", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    cfg = config.load(ws)
    assert config.ack_statuses(cfg, ws, cdir, plugin_root)["public"][0] == "valid"
    cfg["engagement"]["reading"]["provider"] = "public"
    assert config.effective_modes(cfg, ws, cdir, plugin_root)["reading"] == "public"
    (plugin_root / "docs" / "TERMS-AND-RISK.md").write_text("changed", encoding="utf-8")
    modes = config.effective_modes(cfg, ws, cdir, plugin_root)
    assert modes["reading"] == "manual" and any("reading downgraded" in n for n in modes["notes"])


def test_limits_enforced(tmp_path, server):
    sleeps: list = []
    r = reader(tmp_path, pages=2, gap=1, sleeps=sleeps)        # a gap below the floor is raised to 3 s
    assert r.gap == policy.PUBLIC_READ_GAP_SECONDS_FLOOR
    r.profile_posts("alex-example")
    r.post_comments(POST_URL)
    assert sleeps and sleeps[0] == pytest.approx(3.0)
    with pytest.raises(pr.PublicReadError) as e:
        r.profile_posts("alex-example")
    assert e.value.kind == "limit" and len(Handler.seen) == 2
    assert reader(tmp_path, pages=2).pages_left() == 0         # the count survives a new reader, same day


def test_999_on_a_post_page_stops_for_the_day(tmp_path, server):
    Handler.status = 999
    r = reader(tmp_path)
    with pytest.raises(pr.PublicReadError) as e:
        r.fetch(POST_URL)
    assert e.value.kind == "blocked" and "999" in str(e.value)
    Handler.status = 200
    with pytest.raises(pr.PublicReadError):                    # no retry, even from a fresh reader
        reader(tmp_path).fetch(POST_URL)
    assert len(Handler.seen) == 1
    assert json.loads((tmp_path / "data" / "public_reader.json").read_text())["stopped"]


def test_profile_999_pauses_profiles_for_six_hours(tmp_path, server):
    clock = [1_000_000.0]
    Handler.status = 999
    with pytest.raises(pr.PublicReadError) as e:
        reader(tmp_path, now=lambda: clock[0]).profile_posts("alex-example")
    assert e.value.kind == "paused" and "6 hours" in str(e.value)
    Handler.status = 200
    clock[0] += 5 * 3600                                       # five hours later, new reader: still paused
    again = reader(tmp_path, now=lambda: clock[0])
    assert again.profile_wait_seconds() == pytest.approx(3600)
    with pytest.raises(pr.PublicReadError) as e:
        again.profile_posts("alex-example")
    assert e.value.kind == "paused" and len(Handler.seen) == 1
    assert again.post_comments(POST_URL)                       # post pages have their own limits
    clock[0] += 3601                                           # past six hours
    assert reader(tmp_path, now=lambda: clock[0]).profile_posts("alex-example")


def test_profile_spacing_per_run_and_per_day(tmp_path, server):
    clock = [1_000_000.0]
    r = reader(tmp_path, now=lambda: clock[0])
    assert r.profile_posts("a") and len(Handler.seen) == 1
    with pytest.raises(pr.PublicReadError) as e:               # 20 minutes not yet passed
        r.profile_posts("b")
    assert e.value.kind == "spacing" and len(Handler.seen) == 1
    clock[0] += 19 * 60
    with pytest.raises(pr.PublicReadError):
        reader(tmp_path, now=lambda: clock[0]).profile_posts("b")   # spacing persists across runs
    clock[0] += 61
    r2 = reader(tmp_path, now=lambda: clock[0])
    assert r2.profile_posts("b")
    clock[0] += 21 * 60
    assert r2.profile_posts("c")                               # second page of this run
    clock[0] += 21 * 60
    with pytest.raises(pr.PublicReadError) as e:               # third page in the same run
        r2.profile_posts("c2")
    assert e.value.kind == "limit" and "per run" in str(e.value)
    # daily cap 12: a fresh reader every 21 minutes, two per run
    for _ in range(40):
        clock[0] += 21 * 60
        try:
            reader(tmp_path, now=lambda: clock[0]).profile_posts("d")
        except pr.PublicReadError as exc:
            assert exc.kind == "limit" and "daily profile" in str(exc)
            break
    assert json.loads((tmp_path / "data" / "public_reader.json").read_text())["profile_pages"] == 12


def test_profile_defaults_and_validation():
    c = config.defaults("Europe/Lisbon")
    pub = c["engagement"]["reading"]["public"]
    assert (pub["profile_max_per_run"], pub["profile_max_per_day"], pub["profile_gap_minutes"]) == (2, 12, 20)
    pub["profile_gap_minutes"] = 5
    pub["profile_max_per_run"] = 0
    errs = config.validate(c).errors
    assert any("profile_gap_minutes" in e for e in errs) and any("profile_max_per_run" in e for e in errs)


def test_request_headers_no_referer_no_login(tmp_path, server):
    reader(tmp_path).post_comments(POST_URL)
    h = {k.lower(): v for k, v in Handler.seen[0]["headers"].items()}
    assert "referer" not in h and "cookie" not in h and "authorization" not in h
    assert h["user-agent"] == http.user_agent() and h["user-agent"].startswith("profile-wrap/")
    assert "mozilla" not in h["user-agent"].lower() and "text/html" in h["accept"]
    assert Handler.seen[0]["method"] == "GET"


def test_only_public_paths_and_get(tmp_path):
    r = reader(tmp_path)
    for bad in ("https://www.linkedin.com/messaging/", "https://evil.example/in/x/",
                "http://www.linkedin.com/in/x-example/"):
        with pytest.raises(pr.PublicReadError) as e:
            r.fetch(bad)
        assert e.value.kind == "bad_url"
    with pytest.raises(http.HttpError, match="GET only"):
        http.request("POST", POST_URL, hp=http.HostPolicy(public_ack=True))
    with pytest.raises(pr.PublicReadError):
        r.profile_posts("../x")


def test_a_caller_cannot_replace_the_neutral_user_agent(tmp_path, server):
    http.request("GET", POST_URL, headers={"User-Agent": "Mozilla/5.0 Chrome"},
                 hp=http.HostPolicy(public_ack=True))
    ua = {k.lower(): v for k, v in Handler.seen[0]["headers"].items()}["user-agent"]
    assert ua == http.user_agent() and "chrome" not in ua.lower()


@pytest.mark.parametrize("path", ["/in/../messaging/", "/in/%2e%2e/messaging/", "/in//x/", "/posts/%2E%2e/x",
                                  "/in/a/../../messaging", "/in/a%2fb", "/messaging/"])
def test_public_path_rejects_traversal(path):
    assert not http.is_public_read_path(path)


def test_public_path_accepts_normal_paths():
    assert http.is_public_read_path("/in/alex-example/") and http.is_public_read_path("/posts/alex_one-activity-1-AAAA")


@pytest.mark.parametrize("page", [
    '<script type="application/ld+json">{"@type":"SocialMediaPosting","interactionStatistic":"oops"}</script>',
    '<script type="application/ld+json">{"@type":"SocialMediaPosting","interactionStatistic":["x"]}</script>',
    '<script type="application/ld+json">{"@type":"SocialMediaPosting","comment":["x"]}</script>',
    '<script type="application/ld+json">{"@type":"SocialMediaPosting","comment":[{"author":"x"}]}</script>',
    '<script type="application/ld+json">{"@type":"DiscussionForumPosting","author":["x"]}</script>',
])
def test_malformed_json_ld_is_unreadable_not_a_crash(page):
    for fn in (pr.comments_from_page, pr.posts_from_page, pr.stats_from_page):
        try:
            fn(page)
        except pr.PublicReadError as exc:
            assert exc.kind == "unreadable"
