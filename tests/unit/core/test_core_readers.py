"""Apify + Tavily + public as a chain: order, pacing, ledger, one-url extract, acks. No network: every request is faked."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from profile_wrap import config, doctor, http, policy
from profile_wrap.linkedin import api, public_reader, readers, social_extra

KEY = "tvly-xxxxxxxx"            # placeholder, not a key
TOKEN = "apify_token_placeholder"
ENV = {"TAVILY_API_KEY": KEY, "APIFY_TOKEN": TOKEN}
SLUG = "alex-example"
TARGET = {"name": "Alex Example", "profile_url": f"https://www.linkedin.com/in/{SLUG}/"}


def utc(y, m, d, h=12):
    return datetime(y, m, d, h, tzinfo=timezone.utc)


def activity_url(slug, when: datetime, tail="AAAA"):
    ident = (int(when.timestamp() * 1000)) << 22
    return f"https://www.linkedin.com/posts/{slug}_topic-activity-{ident}-{tail}"


class Clock:
    def __init__(self, t):
        self.t = t

    def __call__(self):
        return self.t


class FakeNet:
    """Stands in for http.request. Routes by URL; records every call."""

    def __init__(self):
        self.calls, self.limits_left, self.cycle_end = [], 5.0, "2026-11-01T00:00:00Z"
        self.search_results, self.extract_raw, self.fail_limits = [], "# t\n\nBody of the post\n\nTo view or add a comment", False
        self.apify_status, self.apify_items = 200, []

    def __call__(self, method, url, *, headers=None, json_body=None, hp=None, timeout=30, **kw):
        self.calls.append({"method": method, "url": url, "headers": dict(headers or {}), "json": json_body,
                           "hp": hp})
        host = url.split("/")[2]
        http.check_url(url, hp)           # the real host policy still decides
        if url.endswith("/users/me/limits"):
            if self.fail_limits:
                raise http.HttpError("network", "down")
            body = {"data": {"limits": {"maxMonthlyUsageUsd": 5.0},
                             "current": {"monthlyUsageUsd": 5.0 - self.limits_left},
                             "monthlyUsageCycle": {"endAt": self.cycle_end}}}
            return http.Response(200, {}, json.dumps(body).encode(), url)
        if host == "api.apify.com":
            return http.Response(self.apify_status, {}, json.dumps(self.apify_items).encode(), url)
        if url.endswith("/search"):
            return http.Response(200, {}, json.dumps({"results": self.search_results}).encode(), url)
        if url.endswith("/extract"):
            urls = json_body["urls"]
            if not isinstance(urls, str):
                return http.Response(400, {}, b"one url per call", url)
            return http.Response(200, {}, json.dumps({"results": [{"url": urls, "raw_content": self.extract_raw}]}).encode(), url)
        raise AssertionError(url)

    def of(self, suffix):
        return [c for c in self.calls if c["url"].endswith(suffix)]


def cfg_with(providers, **over):
    c = config.defaults("Europe/Lisbon")
    rd = c["engagement"]["reading"]
    rd["providers"] = providers
    rd.update(over)
    return c


def apify(tmp_path, net, now, cfg=None, ack=True, env=ENV):
    return readers.ApifyReader(cfg or cfg_with([]), tmp_path, ack_valid=ack, now=Clock(now), request=net, env=env)


def tavily(tmp_path, net, now, cfg=None, ack=True, env=ENV):
    return readers.TavilyReader(cfg or cfg_with([]), tmp_path, ack_valid=ack, now=Clock(now), request=net, env=env)


# ------------------------------------------------------------------------------------------------ config and order

def test_provider_order_is_validated():
    ok = cfg_with(["apify", "tavily", "public"], apify_ack={"date": "2026-10-19T10:00:00+00:00", "sha256": "a" * 64},
                  tavily_ack={"date": "2026-10-19T10:00:00+00:00", "sha256": "a" * 64}, public_ack={"date": "2026-10-19T10:00:00+00:00", "sha256": "a" * 64})
    assert config.validate(ok).ok
    bad = cfg_with(["public", "apify"], apify_ack=ok["engagement"]["reading"]["apify_ack"],
                   public_ack=ok["engagement"]["reading"]["public_ack"])
    assert any("'public' must come last" in e for e in config.validate(bad).errors)
    assert any("providers" in e for e in config.validate(cfg_with(["apify", "apify"])).errors)
    assert any("providers" in e for e in config.validate(cfg_with(["nope"])).errors)
    missing = config.validate(cfg_with(["tavily"])).errors
    assert any("config ack tavily" in e for e in missing)
    leak = cfg_with([])
    leak["engagement"]["reading"]["tavily"]["key_env"] = "tvly-" + "x" * 8
    assert any("NAME of an environment" in e for e in config.validate(leak).errors)


def test_ack_refusal_and_effective_chain(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    assert "tavily" in policy.ACK_ACTIONS
    with pytest.raises(ValueError):
        config.ack(ws, "tavily", "not the phrase", config_dir=cdir, root=plugin_root)
    config.ack(ws, "tavily", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    config.ack(ws, "apify", policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    cfg = config.load(ws)
    cfg["engagement"]["reading"]["providers"] = ["apify", "tavily", "public"]
    modes = config.effective_modes(cfg, ws, cdir, plugin_root)
    assert modes["reading_chain"] == ["apify", "tavily"] and modes["reading"] == "apify"
    assert any("public skipped" in n for n in modes["notes"])
    (plugin_root / "docs" / "TERMS-AND-RISK.md").write_text("changed", encoding="utf-8")   # risk text moved: all stale
    modes = config.effective_modes(cfg, ws, cdir, plugin_root)
    assert modes["reading_chain"] == [] and modes["reading"] == "manual"


def test_hosts_need_their_own_ack():
    for url, flag in (("https://api.tavily.com/search", "tavily_ack"), ("https://api.apify.com/v2/x", "apify_ack")):
        with pytest.raises(http.HttpError):
            http.check_url(url)
        assert http.check_url(url, http.HostPolicy(**{flag: True})) == url.split("/")[2]
    with pytest.raises(http.HttpError):                 # the Apify ack does not open Tavily
        http.check_url("https://api.tavily.com/search", http.HostPolicy(apify_ack=True))


def test_readers_refuse_without_ack_and_make_no_call(tmp_path):
    net = FakeNet()
    with pytest.raises(readers.ReaderUnavailable) as e:
        tavily(tmp_path, net, utc(2026, 10, 10), ack=False).search_posts(TARGET)
    assert e.value.kind == "no_ack"
    with pytest.raises(readers.ReaderUnavailable) as e:
        apify(tmp_path, net, utc(2026, 10, 10), ack=False).profile_posts(TARGET)
    assert e.value.kind == "no_ack"
    with pytest.raises(readers.ReaderUnavailable) as e:
        tavily(tmp_path, net, utc(2026, 10, 10), env={}).search_posts(TARGET)
    assert e.value.kind == "no_key"
    assert net.calls == []


# ------------------------------------------------------------------------------------------------ Apify pacing

def test_apify_pacing_spreads_the_credit_over_the_cycle(tmp_path):
    net = FakeNet()
    net.limits_left, net.cycle_end = 5.0, "2026-11-01T00:00:00Z"
    now = utc(2026, 10, 19)                       # 13 days to the cycle end, today included
    ap = apify(tmp_path, net, now)
    # (5.00 - 0.05 reserve) / 13 days = 0.38 USD a day = 38 calls at 0.01, capped by max_calls_per_day (20)
    assert ap.calls_left() == 20
    cfg = cfg_with([])
    cfg["engagement"]["reading"]["apify"]["max_calls_per_day"] = 100
    ap2 = apify(tmp_path / "b", FakeNet(), now, cfg=cfg)
    assert ap2.calls_left() == 38


def test_apify_allowance_used_then_rests_until_tomorrow(tmp_path):
    net = FakeNet()
    net.limits_left, net.cycle_end = 0.40, "2026-10-21T00:00:00Z"
    net.apify_items = [{"url": activity_url(SLUG, utc(2026, 10, 18)), "text": "hi", "author": {"first_name": "Alex"},
                        "posted_at": {"timestamp": 1760000000000}}]
    clock = Clock(utc(2026, 10, 19))
    ap = readers.ApifyReader(cfg_with([]), tmp_path, ack_valid=True, now=clock, request=net, env=ENV)
    # (0.40 - 0.05) / 2 days = 0.175 a day = 17 calls
    assert ap.calls_left() == 17
    for _ in range(17):
        assert ap.profile_posts(TARGET)[0]["source"] == "apify"
    with pytest.raises(readers.ReaderUnavailable) as e:
        ap.profile_posts(TARGET)
    assert e.value.kind == "allowance" and len(net.of("run-sync-get-dataset-items")) == 17
    assert TOKEN not in json.dumps(json.loads((tmp_path / "data" / "apify_budget.json").read_text()))
    clock.t = utc(2026, 10, 20)                   # next day: the unspent share rolls forward; the credit is re-read
    net.limits_left = 0.40 - 17 * 0.01
    assert ap.calls_left() == 18                  # (0.23 - 0.05) / 1 day = 18


def test_apify_pacing_across_the_cycle_end(tmp_path):
    net = FakeNet()
    net.limits_left, net.cycle_end = 0.05, "2026-10-20T00:00:00Z"
    clock = Clock(utc(2026, 10, 19))
    ap = readers.ApifyReader(cfg_with([]), tmp_path, ack_valid=True, now=clock, request=net, env=ENV)
    assert ap.calls_left() == 0                   # 0.05 left is below reserve + one call: rests to the cycle end
    state = json.loads((tmp_path / "data" / "apify_budget.json").read_text())
    assert state["exhausted_until"] == "2026-10-20T00:00:00Z"
    clock.t = utc(2026, 10, 20, 1)                # the new cycle: full credit again, rest is dropped
    net.limits_left, net.cycle_end = 5.0, "2026-11-20T00:00:00Z"
    assert ap.calls_left() == 15                  # (5.00 - 0.05) / 31 days = 0.159 a day
    assert json.loads((tmp_path / "data" / "apify_budget.json").read_text())["cycle_end"] == "2026-11-20T00:00:00Z"


def test_apify_402_marks_exhausted(tmp_path):
    net = FakeNet()
    net.apify_status = 402
    ap = apify(tmp_path, net, utc(2026, 10, 19))
    with pytest.raises(readers.ReaderUnavailable) as e:
        ap.profile_posts(TARGET)
    assert e.value.kind == "exhausted" and ap.calls_left() == 0


# ------------------------------------------------------------------------------------------------ Tavily ledger

def test_tavily_allowance_formula_and_reserve(tmp_path):
    net = FakeNet()
    tv = tavily(tmp_path, net, utc(2026, 10, 1))
    assert tv.allowance() == pytest.approx(900 / 31) and tv.remaining_today() == 29
    ledger = tmp_path / "data" / "tavily_usage.json"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(json.dumps({"calls": [{"date": "2026-10-05", "kind": "search", "credits": 880, "target": "x"}]}))
    tv = tavily(tmp_path, net, utc(2026, 10, 31))
    assert tv.remaining_today() == 20             # last day: the 20 credits left of the 900 are today's share
    assert tavily(tmp_path, net, utc(2026, 10, 20)).remaining_today() == 1   # 20 left over 12 days
    ledger.write_text(json.dumps({"calls": [{"date": "2026-10-05", "kind": "search", "credits": 900, "target": "x"}]}))
    with pytest.raises(readers.ReaderUnavailable) as e:
        tv.search_posts({"name": "Someone", "profile_url": "https://www.linkedin.com/in/someone-example/"})
    assert e.value.kind == "allowance" and net.calls == []     # the 100 reserve is never touched
    ledger.write_text(json.dumps({"calls": [{"date": "2026-09-30", "kind": "search", "credits": 900, "target": "x"}]}))
    assert tavily(tmp_path, net, utc(2026, 10, 1)).remaining_today() == 29      # a new month starts clean


def test_tavily_corrupt_ledger_fails_closed(tmp_path):
    net = FakeNet()
    ledger = tmp_path / "data" / "tavily_usage.json"
    ledger.parent.mkdir(parents=True)
    ledger.write_text("{not json")
    with pytest.raises(readers.ReaderUnavailable) as e:
        tavily(tmp_path, net, utc(2026, 10, 10)).search_posts(TARGET)
    assert e.value.kind == "ledger" and net.calls == [] and ledger.read_text() == "{not json"


def test_tavily_search_cache_and_ledger_rows(tmp_path):
    net = FakeNet()
    now = utc(2026, 10, 19)
    net.search_results = [
        {"url": activity_url(SLUG, now - timedelta(days=2)), "content": "snippet"},
        {"url": activity_url("someone-else", now - timedelta(days=1)), "content": "not theirs"},
        {"url": activity_url(SLUG, now - timedelta(days=30), "OLD"), "content": "too old"},
    ]
    tv = tavily(tmp_path, net, now)
    posts, spent = tv.search_posts(TARGET)
    assert spent == 1 and len(posts) == 1 and posts[0]["source"] == "tavily"
    assert net.of("/search")[0]["json"]["query"] == "Alex Example linkedin"
    assert net.of("/search")[0]["headers"]["Authorization"] == f"Bearer {KEY}"
    again, spent2 = tv.search_posts(TARGET)               # inside the 3-day cache: free
    assert spent2 == 0 and again == posts and len(net.of("/search")) == 1
    rows = json.loads((tmp_path / "data" / "tavily_usage.json").read_text())["calls"]
    assert [r["kind"] for r in rows] == ["search"] and KEY not in json.dumps(rows)
    later = tavily(tmp_path, net, now + timedelta(days=4))
    later.search_posts(TARGET)
    assert len(net.of("/search")) == 2


def test_tavily_extract_is_one_url_per_call(tmp_path):
    net = FakeNet()
    now = utc(2026, 10, 19)
    posts = [{"url": activity_url(SLUG, now - timedelta(days=i), t), "text": "", "source": "tavily"}
             for i, t in enumerate(("AAAA", "BBBB", "CCCC"))]
    tv = tavily(tmp_path, net, now)
    assert tv.extract_texts(posts) == 3
    calls = net.of("/extract")
    assert len(calls) == 3 and all(isinstance(c["json"]["urls"], str) for c in calls)
    assert [p["text"] for p in posts] == ["Body of the post"] * 3
    assert tv.extract_texts(posts) == 0                   # text already there: nothing bought twice
    # stops at the daily allowance
    led = tmp_path / "data" / "tavily_usage.json"
    led.write_text(json.dumps({"calls": [{"date": "2026-10-19", "kind": "x", "credits": 70, "target": "t"}]}))
    fresh = [{"url": activity_url(SLUG, now, "ZZZZ"), "text": "", "source": "tavily"}]
    assert tv.extract_texts(fresh) == 0 and len(net.of("/extract")) == 3


def test_tavily_failed_started_call_is_booked(tmp_path):
    def boom(method, url, **kw):
        raise http.HttpError("timeout", "slow", maybe_sent=True)
    tv = readers.TavilyReader(cfg_with([]), tmp_path, ack_valid=True, now=Clock(utc(2026, 10, 19)), request=boom, env=ENV)
    with pytest.raises(readers.ReaderUnavailable):
        tv.search_posts(TARGET)
    assert tv.used() == (1, 1)


# ------------------------------------------------------------------------------------------------ the chain

def make_chain(tmp_path, net, now, order, public=None):
    cfg = cfg_with(order)
    rd = {}
    if "apify" in order:
        rd["apify"] = apify(tmp_path, net, now, cfg)
    if "tavily" in order:
        rd["tavily"] = tavily(tmp_path, net, now, cfg)
    if "public" in order:
        rd["public"] = public
    return readers.ReadingChain(order, rd)


class FakePublic:
    def __init__(self, posts=None, error=None):
        self.posts, self.error, self.asked = posts or [], error, []

    def profile_posts(self, slug):
        self.asked.append(slug)
        if self.error:
            raise public_reader.PublicReadError(self.error, "stopped")
        return self.posts


def test_chain_uses_apify_first_and_stops(tmp_path):
    net, now = FakeNet(), utc(2026, 10, 19)
    net.apify_items = [{"url": activity_url(SLUG, now), "text": "fresh", "author": {}, "posted_at": {}}]
    pub = FakePublic()
    res = make_chain(tmp_path, net, now, ["apify", "tavily", "public"], pub).profile_posts(TARGET)
    assert res["source"] == "apify" and res["posts"][0]["text"] == "fresh"
    assert net.of("/search") == [] and pub.asked == []


def test_chain_tavily_fills_when_apify_allowance_is_gone(tmp_path):
    net, now = FakeNet(), utc(2026, 10, 19)
    net.limits_left = 0.0                                 # Apify credit gone
    net.search_results = [{"url": activity_url(SLUG, now - timedelta(days=1)), "content": "s"}]
    chain = make_chain(tmp_path, net, now, ["apify", "tavily", "public"], FakePublic())
    res = chain.profile_posts(TARGET)
    assert res["source"] == "tavily" and any(n.startswith("apify:") for n in res["notes"])
    assert net.of("run-sync-get-dataset-items") == []
    assert chain.fill_text(res["posts"]) == 1 and res["posts"][0]["text"] == "Body of the post"


def test_chain_clean_empty_answer_does_not_spend_more(tmp_path):
    net, now = FakeNet(), utc(2026, 10, 19)
    net.apify_items = []
    pub = FakePublic()
    res = make_chain(tmp_path, net, now, ["apify", "tavily", "public"], pub).profile_posts(TARGET)
    assert res["clean_empty"] and res["source"] == "apify" and net.of("/search") == [] and pub.asked == []


def test_chain_falls_to_public_last_and_reports_all_notes(tmp_path):
    net, now = FakeNet(), utc(2026, 10, 19)
    net.limits_left = 0.0
    net.search_results = []
    pub = FakePublic(posts=[{"url": activity_url(SLUG, now), "published": now.isoformat(), "text": "t",
                             "author": "Alex Example", "source": "public"}])
    # Tavily answers with nothing: clean empty ends the search, public is not tried for a quiet person
    res = make_chain(tmp_path, net, now, ["apify", "tavily", "public"], pub).profile_posts(TARGET)
    assert res["clean_empty"] and pub.asked == []
    # Tavily out of key: public is the last resort
    chain = readers.ReadingChain(["apify", "tavily", "public"], {
        "apify": apify(tmp_path, net, now), "tavily": tavily(tmp_path / "two", net, now, env={}), "public": pub})
    res = chain.profile_posts(TARGET)
    assert res["source"] == "public" and pub.asked == [SLUG] and len(res["notes"]) == 2
    blocked = readers.ReadingChain(["public"], {"public": FakePublic(error="blocked")}).profile_posts(TARGET)
    assert blocked["source"] is None and blocked["posts"] == []


def test_build_chain_follows_acks(make_workspace, plugin_root, tmp_path):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    for a in ("apify", "tavily"):
        config.ack(ws, a, policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    cfg = config.load(ws)
    cfg["engagement"]["reading"]["providers"] = ["apify", "tavily", "public"]
    chain = readers.build_chain(cfg, ws, config_dir=cdir, root=plugin_root, request=FakeNet(), env=ENV)
    assert chain.order == ["apify", "tavily"] and set(chain.readers) == {"apify", "tavily"}


# ------------------------------------------------------------------------------------------------ doctor

def test_doctor_lists_both_readers_without_a_call(make_workspace, plugin_root, tmp_path, monkeypatch):
    ws = make_workspace()
    cdir = tmp_path / "ackcfg"
    for a in ("apify", "tavily"):
        config.ack(ws, a, policy.ACK_PHRASE, config_dir=cdir, root=plugin_root)
    cfg = config.load(ws)
    cfg["engagement"]["reading"]["providers"] = ["apify", "tavily"]
    monkeypatch.setenv("TAVILY_API_KEY", KEY)
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setattr(http, "request", lambda *a, **k: (_ for _ in ()).throw(AssertionError("doctor made a call")))
    result = doctor.run(workspace=ws, cfg=cfg, plugin_root=plugin_root, path=str(tmp_path))
    by = {c["id"]: c for c in result["checks"]}
    assert by["reading"]["detail"] == "apify then tavily"
    assert by["reading_apify"]["status"] == "warn" and "APIFY_TOKEN is not set" in by["reading_apify"]["detail"]
    assert by["reading_tavily"]["status"] == "pass" and "month 0/900" in by["reading_tavily"]["detail"]
    assert KEY not in json.dumps(result)


# ------------------------------------------------------------------------------------------------ threadUrn retry

class ScriptedClient:
    def __init__(self, answers):
        self.answers, self.sent = list(answers), []

    def call(self, method, path, **kw):
        self.sent.append({"path": path, "body": kw["json_body"]})
        status, text, hdr = self.answers.pop(0)
        return http.Response(status, hdr, text.encode(), path)


def test_comment_retries_once_with_the_real_thread_urn():
    act, real = "urn:li:activity:10", "urn:li:ugcPost:20"
    msg = f'{{"message":"actual threadUrn: {real}"}}'
    client = ScriptedClient([(400, msg, {}), (201, "", {"x-restli-id": "c1"})])
    assert social_extra.create_comment(client, act, "urn:li:person:DEMO0000", "hello") == "c1"
    assert len(client.sent) == 2
    assert client.sent[1]["body"]["object"] == real and "ugcPost" in client.sent[1]["path"]
    # a second failure is reported, never looped
    client = ScriptedClient([(400, msg, {}), (400, msg, {})])
    with pytest.raises(api.ApiError):
        social_extra.create_comment(client, act, "urn:li:person:DEMO0000", "hello")
    assert len(client.sent) == 2
    # a 400 without the hint is not retried
    client = ScriptedClient([(400, "bad", {})])
    with pytest.raises(api.ApiError):
        social_extra.create_comment(client, act, "urn:li:person:DEMO0000", "hello")
    assert len(client.sent) == 1


# ------------------------------------------------------------------------------------------------ review fixes

def test_bought_extract_text_is_cached_and_not_bought_twice(tmp_path):
    net = FakeNet()
    now = utc(2026, 10, 19)
    net.search_results = [{"url": activity_url(SLUG, now - timedelta(days=1)), "content": "s"}]
    tv = tavily(tmp_path, net, now)
    posts, _ = tv.search_posts(TARGET)
    assert tv.extract_texts(posts) == 1 and len(net.of("/extract")) == 1
    again, spent = tv.search_posts(TARGET)                 # served from the cache, text included
    assert spent == 0 and again[0]["text"] == "Body of the post"
    assert tv.extract_texts(again) == 0 and len(net.of("/extract")) == 1


def test_empty_extract_is_cached_as_no_text(tmp_path):
    net = FakeNet()
    net.extract_raw = ""
    now = utc(2026, 10, 19)
    net.search_results = [{"url": activity_url(SLUG, now - timedelta(days=1)), "content": "s"}]
    tv = tavily(tmp_path, net, now)
    posts, _ = tv.search_posts(TARGET)
    tv.extract_texts(posts)
    again, _ = tv.search_posts(TARGET)
    assert again[0]["no_text"] is True
    assert tv.extract_texts(again) == 0 and len(net.of("/extract")) == 1


def test_tavily_topic_default_is_empty():
    assert config.defaults("Europe/Lisbon")["engagement"]["reading"]["tavily"]["topic"] == ""


def test_apify_token_env_must_be_a_name():
    c = cfg_with([])
    c["engagement"]["reading"]["apify"]["token_env"] = "apify" + "_api_" + "x" * 10
    assert any("NAME of an environment" in e and "apify" in e for e in config.validate(c).errors)


def _scan(text):
    from profile_wrap import leakcheck
    return [f.rule for f in leakcheck.scan_blob(text.encode(), "docs/x.md", leakcheck._Ctx([], None))]


def test_leak_scan_and_sandbox_catch_tavily_keys_not_the_placeholder():
    from profile_wrap import sandbox
    real = "tvly" + "-" + "dev-" + "a1B2c3D4e5F6g7H8i9J0"
    assert "token-tavily" in _scan(f"key {real}")
    assert "token-tavily" not in _scan("TAVILY_API_KEY=tvly-xxxxxxxx")
    assert sandbox.scan_secrets(real)
    assert not sandbox.scan_secrets("TAVILY_API_KEY=tvly-xxxxxxxx")


def test_child_env_passes_the_tavily_key_name():
    from profile_wrap.schedule import runner
    c = config.defaults("Europe/Lisbon")
    env = runner.child_env(c, {"TAVILY_API_KEY": "v", "APIFY_TOKEN": "w", "OTHER_SECRET": "z"})
    assert env.get("TAVILY_API_KEY") == "v" and env.get("APIFY_TOKEN") == "w" and "OTHER_SECRET" not in env


def test_malformed_cache_entries_do_not_crash(tmp_path):
    now = utc(2026, 10, 19)
    tv = tavily(tmp_path, FakeNet(), now)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data" / "tavily_cache.json").write_text(json.dumps(
        {SLUG: {"last_searched": now.isoformat(), "posts": ["x", {"url": "u"}, {"ts": "bad"}]}}))
    assert tv.cached(SLUG) == []


def test_doctor_reading_details_make_no_network_call(tmp_path, monkeypatch):
    def boom(*a, **k):
        raise AssertionError("doctor must not call the network")
    monkeypatch.setattr(http, "request", boom)
    ap = readers.ApifyReader(cfg_with([]), tmp_path, ack_valid=True, now=Clock(utc(2026, 10, 19)))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "apify_budget.json").write_text(json.dumps(
        {"day": "2026-10-18", "day_start": 3.0, "calls": 1, "cycle_end": "2026-10-19T00:00:00Z"}))
    assert "once on the first use" in ap.status_local()
