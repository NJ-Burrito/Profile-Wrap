"""``profile-wrap read posts`` with a fake chain, and the copies of the risk text. No network."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from profile_wrap import cli
from profile_wrap.linkedin import readers

REPO = Path(__file__).resolve().parents[3]
URL = "https://www.linkedin.com/in/alex-example/"


class FakeChain:
    def __init__(self, order, result):
        self.order, self.result, self.seen, self.filled = order, result, [], 0

    def profile_posts(self, target):
        self.seen.append(target)
        return self.result

    def fill_text(self, posts):
        self.filled += 1
        return 0


def run(monkeypatch, capsys, ws, chain, *extra):
    monkeypatch.setattr(readers, "build_chain", lambda cfg, workspace, **kw: chain)
    code = cli.main(["read", "posts", URL, "--workspace", str(ws), *extra])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_read_posts_json_uses_the_chain(monkeypatch, capsys, make_workspace):
    ws = make_workspace()
    res = readers.ReadResult(posts=[{"url": "https://www.linkedin.com/posts/alex-example_x-activity-1-AAAA",
                                     "source": "apify"}], source="apify", notes=[], clean_empty=False)
    chain = FakeChain(["apify"], res)
    code, out, _ = run(monkeypatch, capsys, ws, chain, "--json")
    assert code == 0 and chain.seen[0]["profile_url"] == URL
    data = json.loads(out)
    assert data["source"] == "apify" and data["posts"][0]["source"] == "apify" and chain.filled == 0


def test_read_posts_text_flag_fills_text(monkeypatch, capsys, make_workspace):
    ws = make_workspace()
    res = readers.ReadResult(posts=[{"url": "u", "source": "tavily"}], source="tavily", notes=[], clean_empty=False)
    chain = FakeChain(["tavily"], res)
    code, out, _ = run(monkeypatch, capsys, ws, chain, "--text")
    assert code == 0 and chain.filled == 1 and "1 post(s) via tavily" in out


def test_read_posts_with_no_reader_on_fails_with_a_plain_message(monkeypatch, capsys, make_workspace):
    ws = make_workspace()
    chain = FakeChain([], readers.ReadResult(posts=[], source=None, notes=[], clean_empty=False))
    code, _, err = run(monkeypatch, capsys, ws, chain)
    assert code == 1 and "off by default" in err and chain.seen == []


def test_read_posts_refuses_a_bad_address(monkeypatch, capsys, make_workspace):
    ws = make_workspace()
    monkeypatch.setattr(readers, "build_chain", lambda *a, **k: pytest.fail("must not be built"))
    code = cli.main(["read", "posts", "https://www.linkedin.com/messaging/", "--workspace", str(ws)])
    assert code == 2


def test_default_config_builds_an_empty_chain(make_workspace):
    from profile_wrap import config
    ws = make_workspace()
    assert readers.build_chain(config.load(ws), ws).order == []


def test_every_copy_of_the_compliance_text_is_identical():
    master = (REPO / "docs" / "references" / "compliance.md").read_bytes()
    copies = [p for p in REPO.glob("**/references/compliance.md")
              if "node_modules" not in p.parts and ".git" not in p.parts and "work" not in p.relative_to(REPO).parts]
    assert len(copies) >= 10
    stale = [str(p.relative_to(REPO)) for p in copies if p.read_bytes() != master]
    assert not stale, f"copy docs/references/compliance.md over: {stale}"


def test_name_from_slug():
    from profile_wrap.linkedin.cli_ext import name_from_slug
    assert name_from_slug("alex-example") == "Alex Example"
    assert name_from_slug("alex-example-1a2b3c4d") == "Alex Example"
    assert name_from_slug("alex-example-123456") == "Alex Example"
    assert name_from_slug("12345678") == ""


def test_read_passes_the_name(monkeypatch, capsys, make_workspace):
    ws = make_workspace()
    chain = FakeChain(["apify"], readers.ReadResult(posts=[], source="apify", notes=[], clean_empty=True))
    run(monkeypatch, capsys, ws, chain)
    assert chain.seen[0]["name"] == "Alex Example"
    run(monkeypatch, capsys, ws, chain, "--name", "Alexandra Example")
    assert chain.seen[1]["name"] == "Alexandra Example"
