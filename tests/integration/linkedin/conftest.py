"""Fixtures: a throwaway workspace, a token, and the fake LinkedIn server. No real call is made."""
from __future__ import annotations

import datetime as dt
import json
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from njli import config as config_mod  # noqa: E402
from njli import policy  # noqa: E402
from njli.demo.fake_linkedin import FakeLinkedIn  # noqa: E402
from njli.linkedin import auth  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "captions"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
GIF = b"GIF89a" + b"\x00" * 32
PDF = b"%PDF-1.4\n%%EOF\n"


def gate_pass(slug, ws, write=True):
    return {"summary": "PASS", "fails": []}


def gate_fail(slug, ws, write=True):
    return {"summary": "FAIL", "fails": ["numbers: 7 bugs has no cited claim"]}


@dataclass
class Env:
    ws: Path
    fake: FakeLinkedIn
    cfg_dir: Path
    data_dir: Path
    profile: str = "it"

    def cfg(self) -> dict:
        return config_mod.load(self.ws)

    def set_config(self, **sections) -> None:
        path = self.ws / "config" / "njli.json"
        raw = json.loads(path.read_text(encoding="utf-8"))
        for key, val in sections.items():
            if isinstance(val, dict) and isinstance(raw.get(key), dict):
                raw[key].update(val)
            else:
                raw[key] = val
        path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    def scheduled(self) -> None:
        """posting.mode = api_scheduled with a valid typed acknowledgement."""
        self.set_config(posting={"mode": "api_scheduled"})
        config_mod.ack(self.ws, "api_scheduled", policy.ACK_PHRASE, config_dir=self.cfg_dir)

    def draft(self, slug="d1", *, fmt="text", caption="A plain sentence about testing.\n",
              assets=(), status="queued", slot_hours_ago=1.0, first_comment=None, alt="A picture.",
              title=None, extra=None) -> Path:
        folder = self.ws / "drafts" / slug
        (folder / "out").mkdir(parents=True, exist_ok=True)
        slot = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=slot_hours_ago)
        meta = {"slug": slug, "title": title or slug, "lang": "en", "format": fmt, "pillar": "P1",
                "status": status, "claims": [], "scheduled_at": slot.isoformat(timespec="seconds")}
        names = []
        for name, data in assets:
            (folder / "out" / name).write_bytes(data)
            names.append(name)
        if names:
            meta["assets"] = names
        meta.update(extra or {})
        (folder / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        (folder / "caption.txt").write_text(caption, encoding="utf-8")
        if first_comment is not None:
            (folder / "first_comment.txt").write_text(first_comment, encoding="utf-8")
        if alt is not None:
            (folder / "alt.txt").write_text(alt, encoding="utf-8")
        return folder

    def ledger_rows(self) -> list:
        path = self.ws / "published" / "ledger.jsonl"
        if not path.exists():
            return []
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]

    def meta(self, slug="d1") -> dict:
        return json.loads((self.ws / "drafts" / slug / "meta.json").read_text(encoding="utf-8"))


@pytest.fixture()
def env(tmp_path, monkeypatch):
    for name in ("NJLI_WORKER", "NJLI_WORKSPACE", "LINKEDIN_CLIENT_ID", "LINKEDIN_CLIENT_SECRET"):
        monkeypatch.delenv(name, raising=False)
    cfg_dir = tmp_path / "cfg"
    data_dir = tmp_path / "data"
    monkeypatch.setenv("NJLI_CONFIG_DIR", str(cfg_dir))
    monkeypatch.setenv("NJLI_DATA_DIR", str(data_dir))
    monkeypatch.setenv("NJLI_TEST", "1")
    monkeypatch.setenv("PYTHONUTF8", "1")
    fake = FakeLinkedIn().start()
    monkeypatch.setenv("NJLI_LINKEDIN_BASE", fake.base_url)
    ws = tmp_path / "ws"
    (ws / "config").mkdir(parents=True)
    (ws / "research").mkdir()
    (ws / "drafts").mkdir()
    shutil.copy(FIX / "facts.md", ws / "research" / "facts.md")
    shutil.copy(FIX / "stats.md", ws / "research" / "stats.md")
    raw = json.loads((FIX / "config.json").read_text(encoding="utf-8"))
    raw["profile_id"] = "it"
    raw["linkedin"] = {"timeout_s": 2}
    (ws / "config" / "njli.json").write_text(json.dumps(raw, indent=2), encoding="utf-8")
    profile_dir = cfg_dir / "it"
    auth.save_token(profile_dir, {"access_token": "tok-secret-1", "expires_at": time.time() + 30 * 86400,
                                  "author": "urn:li:person:DEMO000000", "name": "Maya Rivera"})
    e = Env(ws, fake, profile_dir, data_dir)
    yield e
    fake.stop()
