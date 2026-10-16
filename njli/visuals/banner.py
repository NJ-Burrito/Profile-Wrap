"""The profile banner: a variables-driven 1584x396 template with a safe-zone gate and a minimum-font gate.

Rendered at 1x and 2x into ``<workspace>/brand/banner/out/`` (never into the plugin). Only text the user supplies appears.
``profile banner render`` (WP7) calls :func:`render_banner`.
"""
from __future__ import annotations

import html
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Dict, Optional

from . import VisualsError, kit_dir, proc
from .render import run_static

BANNER_W, BANNER_H = 1584, 396
SAFE_ZONE_LTR = (0, 120, 420, 276)     # x, y, w, h: where the profile photo overlaps on desktop
MIN_FONT = 28
DEFAULTS = {"headline": "", "subline": "", "c_bg": "#f4f1ea", "c_ink": "#17202b", "c_accent": "#0e7c66", "dir": "ltr"}
_HEX = re.compile(r"^#[0-9a-fA-F]{3,8}$")


def template_path(workspace: Path) -> Path:
    mine = Path(workspace) / "brand" / "banner" / "banner.html"
    return mine if mine.is_file() else kit_dir() / "templates" / "banner.html"


def fill(template: str, values: Dict[str, str], overlay: bool = False) -> str:
    vals = dict(DEFAULTS)
    vals.update({k: v for k, v in values.items() if v is not None})
    for key in ("c_bg", "c_ink", "c_accent"):
        if not _HEX.match(str(vals[key])):
            raise VisualsError(f"banner colour {key}={vals[key]!r} is not a hex colour")
    if vals["dir"] not in ("ltr", "rtl"):
        raise VisualsError("banner dir must be ltr or rtl")
    vals["body_class"] = "show-zone" if overlay else ""
    for key in ("headline", "subline"):
        vals[key] = html.escape(str(vals[key]))
    out = template
    for key, value in vals.items():
        out = out.replace("{{" + key + "}}", str(value))
    left = re.findall(r"\{\{[a-z_]+\}\}", out)
    if left:
        raise VisualsError(f"banner template has unfilled variables: {', '.join(sorted(set(left)))}")
    return out


def safe_zone(direction: str) -> str:
    x, y, w, h = SAFE_ZONE_LTR
    if direction == "rtl":
        x = BANNER_W - w
    return f"{x},{y},{w},{h}"


def render_banner(workspace: Path, cfg: dict, values: Dict[str, str], *, out_dir: Optional[Path] = None,
                  overlay: bool = True, runner: Callable = proc.run) -> dict:
    """Render ``banner@1x.png`` and ``banner@2x.png`` (and ``banner-safezone.png`` when ``overlay``)."""
    workspace = Path(workspace)
    out = Path(out_dir) if out_dir else workspace / "brand" / "banner" / "out"
    template = template_path(workspace).read_text(encoding="utf-8")
    direction = values.get("dir", "ltr")
    zone = safe_zone(direction)
    work = Path(tempfile.mkdtemp(prefix=".banner-", dir=str(workspace / "work") if (workspace / "work").is_dir() else None))
    try:
        page = work / "banner.html"
        page.write_text(fill(template, values), encoding="utf-8")
        info = run_static(page, out, workspace, cfg, selector=".banner", prefix="banner", scales="1,2", numbered=False,
                          canvas=(BANNER_W, BANNER_H), safe_zone=zone, min_font=MIN_FONT, runner=runner)
        files = list(info["files"])
        if overlay:
            prev = work / "preview.html"
            prev.write_text(fill(template, values, overlay=True), encoding="utf-8")
            pinfo = run_static(prev, work / "preview", workspace, cfg, selector=".banner", prefix="banner-safezone",
                               scales="1", numbered=False, canvas=(BANNER_W, BANNER_H), runner=runner)
            for name in pinfo["files"]:
                shutil.move(str(work / "preview" / name), str(out / name))
                files.append(name)
        return {"out": str(out), "files": sorted(files), "safe_zone": zone, "canvas": {"w": BANNER_W, "h": BANNER_H}}
    finally:
        shutil.rmtree(work, ignore_errors=True)
