"""Pinned Node assets: Playwright, HyperFrames, lucide-static and GSAP, installed into the workspace (never the plugin).

``profile-wrap assets fetch`` runs ``npm install`` against the workspace ``package.json`` (pinned by ``data/pins.json`` when the
workspace was created) and copies GSAP with its licence into ``brand/vendor/gsap@<version>/`` so renders work offline.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Callable, Optional

from profile_wrap import atomic, paths

from . import VisualsError, proc


def pins() -> dict:
    try:
        return json.loads(paths.resource("data", "pins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VisualsError(f"data/pins.json unreadable: {exc}")


def npm_pin(name: str) -> str:
    version = (pins().get("npm") or {}).get(name)
    if not version:
        raise VisualsError(f"data/pins.json has no npm pin for {name}")
    return version


def node_dir(workspace: Path) -> Optional[Path]:
    """The folder whose node_modules holds playwright: the workspace, PROFILE_WRAP_NODE_DIR, or <data>/node."""
    candidates = [Path(workspace)]
    if os.environ.get("PROFILE_WRAP_NODE_DIR"):
        candidates.append(Path(os.environ["PROFILE_WRAP_NODE_DIR"]))
    candidates.append(paths.data_dir() / "node")
    for c in candidates:
        if (c / "node_modules" / "playwright").is_dir():
            return c
    return None


def gsap_dirs(workspace: Path) -> list:
    root = Path(workspace) / "brand" / "vendor"
    return sorted(p for p in root.glob("gsap@*") if (p / "gsap.min.js").is_file()) if root.is_dir() else []


def gsap_path(workspace: Path) -> Path:
    found = gsap_dirs(workspace)
    if not found:
        raise VisualsError("GSAP is not installed in brand/vendor/. Run 'profile-wrap assets fetch' once (needs Node and "
                           "network); renders work offline afterwards.")
    return found[-1] / "gsap.min.js"


def _vendor_gsap(workspace: Path) -> Optional[Path]:
    src = Path(workspace) / "node_modules" / "gsap"
    js = src / "dist" / "gsap.min.js"
    if not js.is_file():
        return None
    try:
        version = json.loads((src / "package.json").read_text(encoding="utf-8"))["version"]
    except (OSError, ValueError, KeyError):
        version = npm_pin("gsap")
    dest = Path(workspace) / "brand" / "vendor" / f"gsap@{version}"
    dest.mkdir(parents=True, exist_ok=True)
    atomic.atomic_write_bytes(dest / "gsap.min.js", js.read_bytes())
    lic = next((src / n for n in ("LICENSE", "LICENSE.md", "LICENSE.txt") if (src / n).is_file()), None)
    if lic is not None:
        atomic.atomic_write_bytes(dest / "LICENSE-gsap.txt", lic.read_bytes())
    else:
        try:
            text = json.loads((src / "package.json").read_text(encoding="utf-8")).get("license", "see https://gsap.com/standard-license")
        except (OSError, ValueError):
            text = "see https://gsap.com/standard-license"
        atomic.atomic_write_text(dest / "LICENSE-gsap.txt",
                                 f"GSAP {version} is fetched from npm by 'profile-wrap assets fetch'. It is not part of Profile-Wrap.\n"
                                 f"Licence declared in its package.json: {text}\n")
    return dest


def fetch(workspace: Path, runner: Callable[..., "proc.Result"] = proc.run, timeout: float = 900) -> dict:
    ws = Path(workspace)
    if not (ws / "package.json").is_file():
        raise VisualsError(f"{ws / 'package.json'} not found: run 'profile-wrap init' first (it writes the pinned package.json)")
    npm = shutil.which("npm")
    if not npm:
        raise VisualsError("npm not found: install Node >= %s from https://nodejs.org" % pins().get("node_min", 22))
    res = runner([npm, "install", "--no-audit", "--no-fund", "--loglevel=error"], cwd=ws, timeout=timeout)
    if not res.ok:
        raise VisualsError(f"npm install failed: {res.tail()}")
    vendored = _vendor_gsap(ws)
    if vendored is None:
        raise VisualsError("npm install finished but node_modules/gsap/dist/gsap.min.js is missing")
    return {"workspace": str(ws), "gsap": str(vendored), "playwright": (ws / "node_modules" / "playwright").is_dir(),
            "hyperframes": (ws / "node_modules" / "hyperframes").is_dir()}


def hyperframes_cmd(*args: str) -> list:
    """``npx --yes hyperframes@<pin> ...``. Never unpinned."""
    npx = shutil.which("npx")
    if not npx:
        raise VisualsError("npx not found: install Node >= %s from https://nodejs.org" % pins().get("node_min", 22))
    return [npx, "--yes", f"hyperframes@{npm_pin('hyperframes')}", *args]


def node_version() -> Optional[str]:
    node = shutil.which("node")
    if not node:
        return None
    res = proc.run([node, "--version"], timeout=30)
    m = re.match(r"v(\d+)\.(\d+)", res.stdout.strip()) if res.ok else None
    return res.stdout.strip() if m else None


def require_node() -> str:
    version = node_version()
    if not version:
        raise VisualsError("Node is not installed: slides and GIFs need Node >= %s (https://nodejs.org). Text posts "
                           "need nothing." % pins().get("node_min", 22))
    major = int(version.lstrip("v").split(".")[0])
    need = int(pins().get("node_min", 22))
    if major < need:
        raise VisualsError(f"Node {version} is too old: need >= {need}")
    return version
