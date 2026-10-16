"""Helpers shared by the gate tests (kept out of conftest.py so the name cannot clash with other suites)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
FIX = ROOT / "tests" / "fixtures" / "captions"


def write_config(ws: Path, **sections) -> None:
    path = ws / "config" / "profile-wrap.json"
    cfg = json.loads(path.read_text(encoding="utf-8"))
    for key, val in sections.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def make_draft(ws: Path, slug: str = "d1", caption: str = "A plain sentence.\n", *, meta: dict | None = None,
               first_comment: str | None = None, alt: str | None = None, slides: str | None = None,
               fmt: str = "text", lang: str = "en", claims: list | None = None) -> Path:
    d = ws / "drafts" / slug
    d.mkdir(parents=True, exist_ok=True)
    m = {"slug": slug, "lang": lang, "format": fmt, "pillar": "P1", "status": "draft",
         "claims": [] if claims is None else claims}
    m.update(meta or {})
    (d / "meta.json").write_text(json.dumps(m, indent=2), encoding="utf-8")
    (d / "caption.txt").write_text(caption, encoding="utf-8")
    if first_comment is not None:
        (d / "first_comment.txt").write_text(first_comment, encoding="utf-8")
    if alt is not None:
        (d / "alt.txt").write_text(alt, encoding="utf-8")
    if slides is not None:
        (d / "slides.html").write_text(slides, encoding="utf-8")
    return d
