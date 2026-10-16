"""Fixtures: a throwaway workspace, a token, the fake LinkedIn server, a fake provider. No real call is made."""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
MCP_ROOT = ROOT / "mcp"
for p in (ROOT, MCP_ROOT):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

from mcp.client import Client  # noqa: E402

from profile_wrap import config as config_mod  # noqa: E402
from profile_wrap.demo.fake_linkedin import FakeLinkedIn  # noqa: E402
from profile_wrap.linkedin import auth  # noqa: E402
from profile_wrap.providers import settings as prov_settings  # noqa: E402
from profile_wrap.providers.base import Result  # noqa: E402
from profile_wrap_mcp.core import Context  # noqa: E402
from profile_wrap_mcp.server import build_server  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "captions"


def gate_pass(slug, ws, write=True):
    return {"summary": "PASS", "fails": []}


def gate_fail(slug, ws, write=True):
    return {"summary": "FAIL", "fails": ["numbers: 7 bugs has no cited claim"]}


class FakeProvider:
    def __init__(self, text="Testing is a habit.\nWrite the failing test first.\n"):
        self.text = text
        self.calls = []

    def complete(self, system, messages, **kw):
        self.calls.append((system, messages))
        return Result(self.text, {}, "r1", "fake", "fake-1")


@dataclass
class Env:
    ws: Path
    fake: FakeLinkedIn
    ctx: Context
    provider: FakeProvider

    def draft(self, slug="d1", status="queued", allow_history=True, caption="A plain sentence about testing.\n"):
        folder = self.ws / "drafts" / slug
        folder.mkdir(parents=True, exist_ok=True)
        slot = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=1)
        meta = {"slug": slug, "title": slug, "lang": "en", "format": "text", "pillar": "P1",
                "status": status, "claims": [], "scheduled_at": slot.isoformat(timespec="seconds")}
        (folder / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
        (folder / "caption.txt").write_text(caption, encoding="utf-8")
        if allow_history:
            (folder / "review.json").write_text(json.dumps({"history": [
                {"at": "2026-10-16T10:00:00Z", "action": "allow", "from": "draft", "to": "queued"}]}),
                encoding="utf-8")
        return folder

    def ledger_rows(self):
        path = self.ws / "published" / "ledger.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def set_config(self, **sections):
        path = self.ws / "config" / "profile-wrap.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        for k, v in sections.items():
            raw[k].update(v) if isinstance(v, dict) and isinstance(raw.get(k), dict) else raw.__setitem__(k, v)
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for name in ("PROFILE_WRAP_WORKER", "PROFILE_WRAP_WORKSPACE", "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    cfg_dir = tmp_path / "cfg"
    monkeypatch.setenv("PROFILE_WRAP_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("PROFILE_WRAP_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PROFILE_WRAP_TEST", "1")
    monkeypatch.setenv("PYTHONUTF8", "1")
    fake = FakeLinkedIn().start()
    monkeypatch.setenv("PROFILE_WRAP_LINKEDIN_BASE", fake.base_url)
    ws = tmp_path / "ws"
    for sub in ("config", "research", "drafts", "strategy"):
        (ws / sub).mkdir(parents=True)
    shutil.copy(FIX / "facts.md", ws / "research" / "facts.md")
    shutil.copy(FIX / "stats.md", ws / "research" / "stats.md")
    raw = json.loads((FIX / "config.json").read_text(encoding="utf-8"))
    raw["profile_id"] = "it"
    raw["linkedin"] = {"timeout_s": 2}
    (ws / "config" / "profile-wrap.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    auth.save_token(cfg_dir / "it", {"access_token": "tok-secret-1", "expires_at": time.time() + 30 * 86400,
                                     "author": "urn:li:person:DEMO000000", "name": "Maya Rivera"})
    prov_settings.save(ws, "ollama", "llama3.2")
    provider = FakeProvider()
    ctx = Context(ws=ws, gate_fn=gate_pass, provider_factory=lambda *a, **k: provider)
    e = Env(ws, fake, ctx, provider)
    yield e
    fake.stop()


def call(ctx, name, args=None):
    """Run one tool through a real in-process MCP client; returns (is_error, parsed json or text)."""
    async def go():
        async with Client(build_server(ctx)) as c:
            r = await c.call_tool(name, args or {})
            text = r.content[0].text if r.content else ""
            try:
                return r.is_error, json.loads(text)
            except ValueError:
                return r.is_error, text
    return asyncio.run(go())


def with_client(ctx, fn):
    async def go():
        async with Client(build_server(ctx)) as c:
            return await fn(c)
    return asyncio.run(go())
