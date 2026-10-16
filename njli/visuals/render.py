"""``njli render <slug>``: the static lane (slides -> 2x PNG + tagged PDF) and the dispatch to the GIF lane."""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Callable, Optional

from njli import atomic

from . import VisualsError, here, kit_dir
from . import assets, browser, fonts, icons, proc


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")


def _canvas(cfg: dict) -> tuple:
    c = ((cfg.get("brand") or {}).get("canvas")) or {"w": 1080, "h": 1350}
    return int(c.get("w", 1080)), int(c.get("h", 1350))


def draft_dir(workspace: Path, slug: str) -> Path:
    d = Path(workspace) / "drafts" / slug
    if not d.is_dir():
        raise VisualsError(f"no draft at {d}")
    return d


def read_meta(draft: Path) -> dict:
    try:
        return json.loads((draft / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VisualsError(f"{draft / 'meta.json'} unreadable: {exc}")


def run_static(html: Path, out_dir: Path, workspace: Path, cfg: dict, *, selector: str = ".slide",
               prefix: str = "slide", scales: str = "2", numbered: bool = True, canvas: Optional[tuple] = None,
               pdf: Optional[str] = None, safe_zone: Optional[str] = None, min_font: Optional[int] = None,
               png_only: bool = False, runner: Callable = proc.run, chrome: Optional[browser.Browser] = None) -> dict:
    """Render ``html`` through render_slides.mjs into ``out_dir`` atomically (a temp folder, then replace)."""
    assets.require_node()
    plan = fonts.require(fonts.resolve(cfg, workspace))
    chrome = chrome or browser.require(cfg, pin=assets.npm_pin("hyperframes"))
    cw, ch = canvas or _canvas(cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".render-", dir=str(out_dir)))
    css = tmp / "fonts.css"
    try:
        fonts.write_fonts_css(plan, css)
        cmd = [shutil.which("node") or "node", str(here() / "render_slides.mjs"), "--html", str(html),
               "--out", str(tmp / "files"), "--fonts-css", str(css), "--families", ",".join(plan.family_names),
               "--scales", scales, "--selector", selector, "--prefix", prefix, "--canvas", f"{cw}x{ch}",
               "--chrome", str(chrome.path)]
        for d in icons.icon_dirs(workspace):
            cmd += ["--icons", str(d)]
        nd = assets.node_dir(workspace)
        if nd:
            cmd += ["--node-dir", str(nd)]
        if numbered:
            cmd.append("--numbered")
        if pdf:
            cmd += ["--pdf", pdf]
        if safe_zone:
            cmd += ["--safe-zone", safe_zone]
        if min_font:
            cmd += ["--min-font", str(min_font)]
        if png_only:
            cmd.append("--png-only")
        res = runner(cmd, cwd=workspace, timeout=float((cfg.get("render") or {}).get("timeout_s", 1800)))
        if res.timed_out:
            raise VisualsError("the slide render timed out; its browser was stopped")
        if not res.ok:
            raise VisualsError((res.stderr.strip() or res.stdout.strip() or "render failed")[-1500:])
        last = [ln for ln in res.stdout.strip().splitlines() if ln.strip().startswith("{")]
        if not last:
            raise VisualsError("the renderer printed no result line")
        info = json.loads(last[-1])
        produced = sorted(Path(p) for p in info["files"])
        for p in produced:
            if not p.is_file() or p.stat().st_size == 0:
                raise VisualsError(f"renderer reported {p.name} but it is missing or empty")
        names = []
        for p in produced:
            os.replace(p, out_dir / p.name)
            names.append(p.name)
        info["files"] = names
        info["browser"] = chrome.to_dict()
        return info
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_slides(slug: str, workspace: Path, cfg: dict, *, runner: Callable = proc.run) -> dict:
    draft = draft_dir(workspace, slug)
    html = draft / "slides.html"
    out = draft / "out"
    scale = str(((cfg.get("render") or {}).get("static") or {}).get("scale", 2))
    info = run_static(html, out, workspace, cfg, scales=scale, pdf=f"{slug}.pdf", runner=runner)
    keep = set(info["files"])
    for stale in list(out.glob("slide-*.png")) + list(out.glob("*.pdf")):
        if stale.name not in keep:
            stale.unlink()
    cw, ch = _canvas(cfg)
    data = {"slug": slug, "format": "slides", "slides": info["slides"], "rendered": now_iso(),
            "scale": float(scale), "canvas": {"w": cw, "h": ch}, "fonts": info["families"],
            "files": info["files"], "browser": info["browser"]["source"]}
    atomic.atomic_write_json(out / "render.json", data)
    return data


def render(slug: str, workspace: Path, cfg: dict, *, runner: Callable = proc.run) -> dict:
    """Render a draft by what it contains: slides.html -> static lane, meta.video_project -> GIF lane."""
    draft = draft_dir(workspace, slug)
    meta = read_meta(draft)
    if (draft / "slides.html").is_file():
        return render_slides(slug, workspace, cfg, runner=runner)
    if meta.get("video_project"):
        from . import gif
        return gif.render_gif(slug, workspace, cfg, runner=runner)
    raise VisualsError(f"drafts/{slug} has no slides.html and no meta.video_project: nothing to render "
                       "(a text post needs no render)")
