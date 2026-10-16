"""Probe a HyperFrames project without rendering it: load index.html in headless Chrome and read ``data-probe``.

The template's module writes ``window.__probe`` (story plan problems, poster check, hold frozen, palette contrast, identity
placement) into a ``data-probe`` attribute. This turns the library's own checks into a gate that runs before the slow render.
"""
from __future__ import annotations

import html
import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, List

from . import VisualsError, browser, proc


def run_probe(project: Path, chrome: browser.Browser, *, runner: Callable = proc.run, budget_ms: int = 8000) -> Dict:
    index = Path(project) / "index.html"
    if not index.is_file():
        raise VisualsError(f"{index} not found")
    profile = Path(tempfile.mkdtemp(prefix="profile-wrap-probe-"))   # a throwaway profile, removed below
    try:
        cmd = [str(chrome.path), "--headless", "--no-sandbox", "--disable-gpu", "--allow-file-access-from-files",
               f"--user-data-dir={profile}", f"--virtual-time-budget={budget_ms}", "--dump-dom", index.resolve().as_uri()]
        res = runner(cmd, timeout=120)
        if res.timed_out:
            raise VisualsError("the probe browser timed out and was stopped")
        m = re.search(r'data-probe="([^"]*)"', res.stdout)
        if not m:
            raise VisualsError("the composition wrote no data-probe attribute (does index.html set window.__probe?)")
        try:
            return json.loads(html.unescape(m.group(1)))
        except ValueError as exc:
            raise VisualsError(f"data-probe is not JSON: {exc}")
    finally:
        shutil.rmtree(profile, ignore_errors=True)


def problems(probe: Dict) -> List[str]:
    """Readable problems from one probe result. Absent keys are reported, never assumed fine (a probe must show it looked)."""
    out: List[str] = []
    for key in ("plan", "poster", "stopFrozen"):
        if key not in probe:
            out.append(f"probe is missing {key!r}: it did not look")
    plan = probe.get("plan") or {}
    out += [f"story plan: {p}" for p in plan.get("problems") or []]
    poster = probe.get("poster")
    if isinstance(poster, list):
        out += [f"poster frame 0: {p}" for p in poster]
    elif poster is not None:
        out.append(f"poster check raised: {poster}")
    if probe.get("stopFrozen") is False:
        out.append("something moves inside the logged dead stop (hold)")
    elif isinstance(probe.get("stopFrozen"), str):
        out.append(f"hold probe raised: {probe['stopFrozen']}")
    pal = probe.get("palette")
    if isinstance(pal, list) and pal:
        out.append(f"{len(pal)} palette contrast failure(s)")
    ident = probe.get("identity")
    if isinstance(ident, dict):
        out += [f"identity: {p}" for p in ident.get("problems") or []]
    return out
