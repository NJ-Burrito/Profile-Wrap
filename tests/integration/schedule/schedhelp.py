"""Helpers shared by the schedule and planning tests (a module with a unique name, so it can be imported
alongside the other test folders' conftest files)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from profile_wrap import config

PYTHON = sys.executable


def make_ws(root: Path, profile: str = "demo", tz: str = "UTC", **patch) -> Path:
    ws = root / "ws"
    for d in ("config", "strategy", "research", "profile", "drafts", "videos", "published", "work", "data/logs",
              "data/locks", ".njl", ".claude/agents", "prompts"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    cfg = config.defaults(tz)
    cfg["profile_id"] = profile
    for dotted, value in patch.items():
        node = cfg
        parts = dotted.split("__")
        for part in parts[:-1]:
            node = node[part]
        node[parts[-1]] = value
    (ws / "config" / "profile-wrap.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    (ws / ".njl" / "workspace.json").write_text(json.dumps({
        "schema_version": 1, "template_version": "1", "plugin_version": "0.1.0", "profile_id": profile,
        "files": {}, "created_schedule": []}), encoding="utf-8")
    (ws / "research" / "facts.md").write_text(
        "| id | claim | numbers | source | status |\n|---|---|---|---|---|\n"
        "| F01 | The suite has 120 tests | 120 tests | repo | verified |\n"
        "| F02 | A draft claim | 5 | repo | draft |\n", encoding="utf-8")
    (ws / "profile" / "voice.md").write_text("Plain.\n", encoding="utf-8")
    # the shipped prompt templates are the plugin's own; copy none, load_prompt falls back to them
    return ws


def cfg_of(ws: Path) -> dict:
    return config.load(ws)
