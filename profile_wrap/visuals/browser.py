"""Browser discovery for the static lane and HyperFrames. No hard-coded versions or paths.

Order (design-spec section 9): ``render.chrome_path`` config, ``PROFILE_WRAP_BROWSER``, ``HYPERFRAMES_BROWSER_PATH``,
``npx hyperframes browser path``, a Playwright chromium, then system Chrome/Chromium/Edge at known per-OS places.
"""
from __future__ import annotations

import glob
import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional

Runner = Callable[[List[str]], "tuple[int, str]"]


@dataclass(frozen=True)
class Browser:
    path: Path
    source: str

    def to_dict(self) -> dict:
        return {"path": str(self.path), "source": self.source}


def _is_file(value: Optional[str]) -> Optional[Path]:
    if not value:
        return None
    p = Path(os.path.expandvars(os.path.expanduser(str(value))))
    return p if p.is_file() else None


def default_runner(cmd: List[str]) -> "tuple[int, str]":
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
        return p.returncode, p.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def _playwright_dirs(env: Dict[str, str]) -> List[Path]:
    roots: List[Path] = []
    if env.get("PLAYWRIGHT_BROWSERS_PATH") and env["PLAYWRIGHT_BROWSERS_PATH"] != "0":
        roots.append(Path(env["PLAYWRIGHT_BROWSERS_PATH"]))
    home = Path(env.get("HOME") or env.get("USERPROFILE") or Path.home())
    if sys.platform == "win32":
        base = env.get("LOCALAPPDATA")
        if base:
            roots.append(Path(base) / "ms-playwright")
    elif sys.platform == "darwin":
        roots.append(home / "Library" / "Caches" / "ms-playwright")
    else:
        roots.append(home / ".cache" / "ms-playwright")
    return roots


def _playwright_chromium(env: Dict[str, str]) -> Optional[Path]:
    patterns = ["chromium-*/chrome-win*/chrome.exe", "chromium_headless_shell-*/chrome-win*/headless_shell.exe",
                "chromium-*/chrome-linux*/chrome", "chromium_headless_shell-*/chrome-linux*/headless_shell",
                "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium"]
    for root in _playwright_dirs(env):
        for pat in patterns:
            hits = sorted(glob.glob(str(root / pat)))
            if hits:
                return Path(hits[-1])
    return None


def system_candidates(env: Optional[Dict[str, str]] = None, platform: Optional[str] = None) -> List[str]:
    """Known install locations per OS (also used by tests with a fake platform)."""
    env = dict(os.environ if env is None else env)
    platform = platform or sys.platform
    if platform == "win32":
        out = []
        for var in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            base = env.get(var)
            if base:
                out += [str(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"),
                        str(Path(base) / "Microsoft" / "Edge" / "Application" / "msedge.exe"),
                        str(Path(base) / "Chromium" / "Application" / "chrome.exe")]
        return out
    if platform == "darwin":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    return ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium",
            "/usr/bin/chromium-browser", "/snap/bin/chromium", "/usr/bin/microsoft-edge"]


def discover(cfg: Optional[dict] = None, env: Optional[Dict[str, str]] = None, *, use_npx: bool = True,
             pin: Optional[str] = None, runner: Runner = default_runner,
             which: Callable[[str], Optional[str]] = shutil.which, platform: Optional[str] = None) -> Optional[Browser]:
    """The first usable browser in the documented order, or None."""
    env = dict(os.environ if env is None else env)
    hit = _is_file(((cfg or {}).get("render") or {}).get("chrome_path"))
    if hit:
        return Browser(hit, "config render.chrome_path")
    for var in ("PROFILE_WRAP_BROWSER", "HYPERFRAMES_BROWSER_PATH"):
        hit = _is_file(env.get(var))
        if hit:
            return Browser(hit, var)
    npx = which("npx") if use_npx else None
    if npx:
        spec = f"hyperframes@{pin}" if pin else "hyperframes"
        rc, out = runner([npx, "--yes", spec, "browser", "path"])
        line = (out.strip().splitlines() or [""])[-1].strip() if rc == 0 else ""
        hit = _is_file(line)
        if hit:
            return Browser(hit, "hyperframes browser path")
    hit = _playwright_chromium(env)
    if hit:
        return Browser(hit, "playwright chromium")
    for cand in system_candidates(env, platform):
        hit = _is_file(cand)
        if hit:
            return Browser(hit, "system browser")
    for name in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "chrome", "msedge"):
        found = which(name)
        if found:
            return Browser(Path(found), "PATH")
    return None


def require(cfg: Optional[dict] = None, **kw) -> Browser:
    from . import VisualsError
    b = discover(cfg, **kw)
    if b is None:
        raise VisualsError(
            "no browser found. Install Google Chrome or Chromium, or set render.chrome_path in the config, "
            "or PROFILE_WRAP_BROWSER to the executable (see docs/PLATFORMS.md).")
    return b
