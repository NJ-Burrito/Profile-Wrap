"""LEARNINGS.md and the weekly read: the template, the heading check and the filled prompt.

The package never calls a model. ``read_prompt`` fills ``prompts/weekly-read.md`` so the user's own Claude
(plugin, desktop app or CLI) does the reading, and ``check_read`` refuses a read that lacks a required heading.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, List, Optional

from profile_wrap import atomic, claude_runner

KB_REL = Path("research") / "analysis-kb"
LEARNINGS_REL = KB_REL / "LEARNINGS.md"
LINE_CAP = 60
READ_HEADINGS = ("Summary", "Numbers", "What worked", "What did not", "Hypotheses",
                 "Experiments for next week", "Carry-over")
LEARNINGS_HEADINGS = ("Confirmed", "Open experiments", "Retired")
MAX_EXPERIMENTS = 3


def read_path(workspace: Path, label: str) -> Path:
    return Path(workspace) / KB_REL / f"{label}.md"


def init_learnings(workspace: Path) -> Optional[Path]:
    """Write LEARNINGS.md from the template when it does not exist. Returns the path, or None when it was there."""
    target = Path(workspace) / LEARNINGS_REL
    if target.exists():
        return None
    body = claude_runner.load_prompt(workspace, "learnings.template")
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic.atomic_write_text(target, body)
    return target


def _headings(text: str) -> List[str]:
    return [m.group(1).strip() for m in re.finditer(r"^##\s+(.+?)\s*$", text, flags=re.M)]


def _has(headings: List[str], wanted: str) -> bool:
    return any(h.lower().startswith(wanted.lower()) for h in headings)


def check_read(text: str) -> List[str]:
    """Problems with a weekly read: a missing heading, more than three experiments."""
    heads = _headings(text)
    problems = [f"missing heading '## {h}'" for h in READ_HEADINGS if not _has(heads, h)]
    m = re.search(r"^##\s+Experiments for next week\s*$(.*?)(?=^##\s|\Z)", text, flags=re.M | re.S)
    if m:
        items = re.findall(r"^\s*(?:[-*]|\d+\.)\s+\S", m.group(1), flags=re.M)
        if len(items) > MAX_EXPERIMENTS:
            problems.append(f"{len(items)} experiments listed; the limit is {MAX_EXPERIMENTS}")
    return problems


def check_learnings(text: str) -> List[str]:
    heads = _headings(text)
    problems = [f"missing heading '## {h}'" for h in LEARNINGS_HEADINGS if not _has(heads, h)]
    lines = len(text.splitlines())
    if lines > LINE_CAP:
        problems.append(f"{lines} lines; the cap is {LINE_CAP}. Retire or merge entries")
    return problems


def read_prompt(workspace: Path, label: str, report: Any) -> str:
    """``prompts/weekly-read.md`` filled for week ``label``; the weekly JSON goes in as untrusted data."""
    ws = Path(workspace)
    template = claude_runner.load_prompt(ws, "weekly-read")
    previous = sorted(p.name for p in (ws / KB_REL).glob("*-W??.md") if p.stem < label) if (ws / KB_REL).is_dir() else []
    values = {
        "week": label,
        "weekly_json": claude_runner.defang(json.dumps(report, indent=1, ensure_ascii=False)),
        "learnings_path": str(LEARNINGS_REL).replace("\\", "/"),
        "read_path": str(KB_REL / f"{label}.md").replace("\\", "/"),
        "previous_read": (str(KB_REL / previous[-1]).replace("\\", "/") if previous else "none"),
        "min_n": 5,
        "line_cap": LINE_CAP,
    }
    return claude_runner.render_prompt(claude_runner.prompt_body(template), values)
