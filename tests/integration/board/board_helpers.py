"""Shared by the board tests: a throwaway workspace, drafts, and a small real-socket HTTP client."""
from __future__ import annotations

import http.client
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from profile_wrap.board.worker import JobResult

REPO = Path(__file__).resolve().parents[3]
FIX = REPO / "tests" / "fixtures" / "captions"
GOOD_CAPTION = (FIX / "good_en_plain.txt").read_text(encoding="utf-8")
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\xcf\xc0\x00\x00\x03\x01\x01\x00\xc9\xfe\x92\xef\x00\x00\x00\x00IEND\xaeB`\x82")


def make_ws(root: Path, **cfg_sections: Any) -> Path:
    ws = root / "ws"
    (ws / "config").mkdir(parents=True)
    (ws / "research").mkdir()
    (ws / "notes").mkdir()
    (ws / "drafts").mkdir()
    shutil.copy(FIX / "config.json", ws / "config" / "profile-wrap.json")
    shutil.copy(FIX / "facts.md", ws / "research" / "facts.md")
    shutil.copy(FIX / "stats.md", ws / "research" / "stats.md")
    for n in ("review-time", "audit", "clinics", "pilot"):
        (ws / "notes" / f"{n}.md").write_text("evidence\n", encoding="utf-8")
    if cfg_sections:
        path = ws / "config" / "profile-wrap.json"
        cfg = json.loads(path.read_text(encoding="utf-8"))
        for key, val in cfg_sections.items():
            if isinstance(val, dict) and isinstance(cfg.get(key), dict):
                cfg[key].update(val)
            else:
                cfg[key] = val
        path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return ws


def make_draft(ws: Path, slug: str, status: str = "draft", *, base: str = "drafts", caption: str = GOOD_CAPTION,
               fmt: str = "text", lang: str = "en", scheduled_at: Optional[str] = None, extra: Optional[dict] = None,
               media: bool = False) -> Path:
    d = ws / base / slug
    d.mkdir(parents=True, exist_ok=True)
    meta: Dict[str, Any] = {"slug": slug, "title": f"Post {slug}", "lang": lang, "format": fmt, "pillar": "P1",
                            "status": status, "claims": []}
    if scheduled_at:
        meta["scheduled_at"] = scheduled_at
    meta.update(extra or {})
    (d / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (d / "caption.txt").write_text(caption, encoding="utf-8")
    if media:
        (d / "out").mkdir(exist_ok=True)
        (d / "out" / "card.png").write_bytes(PNG)
    return d


def meta_of(d: Path) -> dict:
    return json.loads((d / "meta.json").read_text(encoding="utf-8"))


class Client:
    """One request per connection, exactly the headers the test asks for."""

    def __init__(self, server, token: Optional[str] = None):
        self.port = server.port
        self.token = server.token if token is None else token

    def request(self, method: str, path: str, body: Any = None, *, headers: Optional[dict] = None,
                host: Optional[str] = None, origin: Optional[str] = "default", token: Optional[str] = "default",
                raw_body: Optional[bytes] = None, ctype: str = "application/json") -> Tuple[int, dict, bytes]:
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=20)
        conn.putrequest(method, path, skip_host=True, skip_accept_encoding=True)
        conn.putheader("Host", host if host is not None else f"127.0.0.1:{self.port}")
        if method == "POST":
            if origin == "default":
                origin = f"http://127.0.0.1:{self.port}"
            if origin:
                conn.putheader("Origin", origin)
            tok = self.token if token == "default" else token
            if tok:
                conn.putheader("X-Review-Token", tok)
            payload = raw_body if raw_body is not None else json.dumps(body or {}).encode("utf-8")
            conn.putheader("Content-Type", ctype)
            conn.putheader("Content-Length", str(len(payload)))
        else:
            payload = b""
        for k, v in (headers or {}).items():
            conn.putheader(k, v)
        conn.endheaders(payload if method == "POST" else None)
        resp = conn.getresponse()
        data = resp.read()
        out_headers = {k.lower(): v for k, v in resp.getheaders()}
        conn.close()
        return resp.status, out_headers, data

    def get(self, path: str, **kw) -> Tuple[int, dict, bytes]:
        return self.request("GET", path, **kw)

    def get_json(self, path: str, **kw) -> Tuple[int, Any]:
        code, _h, data = self.get(path, **kw)
        return code, (json.loads(data) if data else None)

    def post(self, path: str, body: Any = None, **kw) -> Tuple[int, Any]:
        code, _h, data = self.request("POST", path, body, **kw)
        try:
            return code, json.loads(data)
        except ValueError:
            return code, data

    def decide(self, slug: str, action: str, note: str = "", confirm: bool = False) -> Tuple[int, Any]:
        return self.post("/api/decision", {"slug": slug, "action": action, "note": note, "confirm": confirm})


class FakeRunner:
    """Stands in for the Claude worker. ``edit`` receives the JobSpec and does whatever the test wants."""

    def __init__(self, edit=None, rc=0):
        self.edit = edit
        self.rc = rc
        self.calls = []

    def __call__(self, spec):
        self.calls.append(spec)
        if self.edit:
            self.edit(spec)
        draft = spec.workspace / spec.allow[0]
        if self.rc == 0 and not (draft / "review-reply.txt").exists():
            (draft / "review-reply.txt").write_text("Shortened the caption.\n", encoding="utf-8")
        return JobResult(rc=self.rc, error="" if self.rc == 0 else "boom")


def read_decisions(ws):
    path = ws / "review" / "decisions.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def history(d: Path) -> list:
    doc = json.loads((d / "review.json").read_text(encoding="utf-8"))
    return doc["history"] if isinstance(doc, dict) else doc
