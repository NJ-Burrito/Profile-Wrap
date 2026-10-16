"""/api/state: a 500-draft fixture stays inside its budget, is cached by mtime, and answers 304 on its ETag."""
from __future__ import annotations

import json
import os
import time

from board_helpers import make_draft, meta_of

N = 500
COLD_BUDGET_S = 6.0  # the first build opens ~1000 files; real-time scanners make each open slow on some machines
INCREMENTAL_BUDGET_S = 1.5
WARM_BUDGET_S = 0.25
MAX_BYTES = 600_000


def build(ws, n=N):
    for i in range(n):
        d = make_draft(ws, f"post-{i:04d}", ["draft", "queued", "hold", "rejected", "missed"][i % 5],
                       caption=f"UNIQUE-CAPTION-MARKER {i}\n" * 20, scheduled_at=f"2030-01-{(i % 28) + 1:02d}T10:00:00+00:00")
        (d / "gates.json").write_text(json.dumps({"summary": "PASS" if i % 2 else "FAIL", "fails": ["a"] * (i % 3),
                                                 "warnings": ["w"], "checks": {}, "findings": []}), encoding="utf-8")
    for i in range(20):
        make_draft(ws, f"live-{i:03d}", "posted", base="published")


def test_500_drafts_stay_under_budget_and_carry_no_captions(board, ws):
    srv, c = board
    build(ws)
    t0 = time.perf_counter()
    code, h, data = c.get("/api/state")
    cold = time.perf_counter() - t0
    assert code == 200 and cold < COLD_BUDGET_S, f"cold /api/state took {cold:.2f}s"
    assert len(data) < MAX_BYTES, f"/api/state was {len(data)} bytes"
    state = json.loads(data)
    assert state["total"] == N + 20 and len(state["posts"]) == N + 20
    assert b"UNIQUE-CAPTION-MARKER" not in data, "captions are loaded on demand"
    etag = h["etag"]
    t0 = time.perf_counter()
    code, h2, body = c.get("/api/state", headers={"If-None-Match": etag})
    warm = time.perf_counter() - t0
    assert code == 304 and body == b"" and h2["etag"] == etag and warm < WARM_BUDGET_S, f"warm took {warm:.2f}s"
    # one change: only that draft is re-read, so the rebuild is far cheaper than the cold one
    d = ws / "drafts" / "post-0007"
    meta = meta_of(d)
    meta["title"] = "Edited"
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    srv.app.store.invalidate()
    t0 = time.perf_counter()
    code, h3, data = c.get("/api/state")
    incremental = time.perf_counter() - t0
    assert code == 200 and h3["etag"] != etag and b"Edited" in data and incremental < INCREMENTAL_BUDGET_S, incremental


def test_the_state_is_built_once_until_a_file_changes(board, ws, monkeypatch):
    srv, c = board
    build(ws, 40)
    store = srv.app.store
    calls = []
    real = store.state
    monkeypatch.setattr(store, "state", lambda: (calls.append(1), real())[1])
    etags = set()
    for _ in range(12):
        code, h, _b = c.get("/api/state")
        assert code == 200
        etags.add(h["etag"])
    assert len(calls) == 1 and len(etags) == 1
    d = ws / "drafts" / "post-0003"
    meta = meta_of(d)
    meta["title"] = "Changed title"
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    os.utime(d / "meta.json", None)
    time.sleep(store.STAMP_TTL + 0.1)  # an edit made outside the board is noticed after the stamp TTL
    code, h, data = c.get("/api/state")
    assert len(calls) == 2 and h["etag"] not in etags and b"Changed title" in data
    # a gate result changing also moves the ETag
    (d / "gates.json").write_text(json.dumps({"summary": "FAIL", "fails": ["x"], "warnings": []}), encoding="utf-8")
    store.invalidate()
    code, h3, _b = c.get("/api/state")
    assert h3["etag"] != h["etag"]


def test_an_empty_workspace_has_a_clean_state(board):
    srv, c = board
    code, state = c.get_json("/api/state")
    assert code == 200 and state["total"] == 0 and state["posts"] == [] and state["degraded"] is False
    assert state["pause"] == [] and state["api"] == 1


def test_posts_are_ordered_by_what_needs_attention(board, ws):
    srv, c = board
    for slug, st in (("z-posted", "posted"), ("a-queued", "queued"), ("m-draft", "draft"), ("k-revising", "revising")):
        make_draft(ws, slug, st, base="published" if st == "posted" else "drafts")
    order = [p["status"] for p in c.get_json("/api/state")[1]["posts"]]
    assert order == ["draft", "revising", "queued", "posted"]


def test_ids_that_are_not_valid_slugs_are_ignored(board, ws):
    srv, c = board
    make_draft(ws, "good-one")
    for bad in (".hidden", "Has Space", "UPPER", "-lead"):
        d = ws / "drafts" / bad
        d.mkdir()
        (d / "meta.json").write_text("{}", encoding="utf-8")
    assert [p["slug"] for p in c.get_json("/api/state")[1]["posts"]] == ["good-one"]
