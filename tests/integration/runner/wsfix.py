"""Shared helpers for the runner and sandbox integration tests (not a test module)."""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, List

from njli import config

HERE = Path(__file__).resolve().parent
FAKE = HERE / "fake_claude.py"
FAKE_CMD: List[str] = [sys.executable, str(FAKE)]


def make_workspace(root: Path) -> Path:
    ws = root / "ws"
    (ws / ".git" / "hooks").mkdir(parents=True)
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (ws / ".git" / "config").write_text("[core]\n\tbare = false\n", encoding="utf-8")
    for rel, text in {
        "research/facts.md": "| id | claim | status |\n| F01 | a fact | verified |\n",
        "profile/voice.md": "Plain voice.\n",
        "drafts/d1/placeholder.txt": "keep\n",
        "drafts/other/caption.txt": "another draft\n",
        "strategy/calendar.json": '{"schema_version": 1, "entries": []}\n',
        "CLAUDE.md": "rules\n",
    }.items():
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    (ws / "work" / "sandbox").mkdir(parents=True)
    (ws / "data" / "logs").mkdir(parents=True)
    return ws


def base_config() -> Dict:
    cfg = config.defaults("UTC")
    cfg["profile_id"] = "default"
    return cfg


def prompt(ws: Path, slug: str, *behaviours: str, pidfile: Path | None = None, pad: int = 0) -> str:
    lines = [f"ROOT: {ws}", f"SLUG: {slug}", "FAKE: " + ",".join(behaviours or ("ok",))]
    if pidfile:
        lines.append(f"PIDFILE: {pidfile}")
    if pad:
        lines.append("PAD: " + "x" * pad)
    return "\n".join(lines) + "\n"


def tree_state(ws: Path) -> Dict[str, bytes]:
    """Every file of the workspace except the runner's scratch, for before/after comparison."""
    out: Dict[str, bytes] = {}
    for p in sorted(ws.rglob("*")):
        rel = p.relative_to(ws).as_posix()
        if p.is_file() and not p.is_symlink() and not rel.startswith(("work/sandbox", "data/logs")):
            out[rel] = p.read_bytes()
    return out
