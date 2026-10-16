"""Render checks: assets exist, render.json is fresh, PDF fonts, GIF frames, size, stillness, seam, flashes.

External tools (pdffonts, pdfinfo, ffprobe, ffmpeg) and Pillow are optional. When one is missing the
check is skipped with a readable warning, or fails, depending on `gate.tools_missing`. Nothing here
raises: every tool call is wrapped and reports a readable line.
"""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .config import read_json
from .findings import FAIL, WARN, finding

HINTS = {
    "ffprobe": "install ffmpeg (Windows: winget install Gyan.FFmpeg; macOS: brew install ffmpeg; Linux: apt install ffmpeg)",
    "ffmpeg": "install ffmpeg (Windows: winget install Gyan.FFmpeg; macOS: brew install ffmpeg; Linux: apt install ffmpeg)",
    "pdffonts": "install poppler (Windows: winget install oschwartz10612.Poppler; macOS: brew install poppler; Linux: apt install poppler-utils)",
    "pdfinfo": "install poppler (Windows: winget install oschwartz10612.Poppler; macOS: brew install poppler; Linux: apt install poppler-utils)",
    "pillow": "install the media extra (profile-wrap doctor --fix, or uv pip install pillow)",
}
SEAM_FACTOR = 4.0   # seam step may be at most this many times the median frame step ...
SEAM_FLOOR = 0.02   # ... plus this floor (mean luminance difference, 0..1)
FLASH_STEP = 0.10   # a luminance swing of 10% between frames counts toward a flash

Runner = Callable[[list[str]], tuple[int, str, str]]


def run_tool(cmd: list[str], timeout: int = 180) -> tuple[int, str, str]:
    """Run a tool; (returncode, stdout, stderr). -1 on a launch failure or timeout, never an exception."""
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
        return p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired:
        return -1, "", f"{cmd[0]} timed out after {timeout}s"
    except OSError as exc:
        return -1, "", f"{cmd[0]} could not start: {exc}"


class RenderChecker:
    def __init__(self, draft: Path, workspace: Path, meta: dict, cfg: dict, *,
                 which: Callable[[str], str | None] = shutil.which, runner: Runner = run_tool) -> None:
        self.draft, self.ws, self.meta, self.cfg = draft, workspace, meta, cfg
        self.g = cfg["gate"]
        self.which, self.run = which, runner
        self.findings: list[dict] = []
        self.skipped: list[str] = []

    # -- helpers
    def _missing(self, tool: str, what: str) -> None:
        sev = FAIL if self.g["tools_missing"] == "fail" else WARN
        verb = "cannot check" if sev == FAIL else "skipped"
        self.findings.append(finding("tools", sev, f"{verb} {what}: {tool} not found; {HINTS.get(tool, 'install it')}",
                                     surface="render", token=tool))
        if sev == WARN:
            self.skipped.append(what)

    def _tool(self, name: str, what: str) -> str | None:
        path = self.which(name)
        if not path:
            self._missing(name, what)
        return path

    def _add(self, sev: str, check: str, msg: str, token: str = "") -> None:
        self.findings.append(finding(check, sev, msg, surface="render", token=token))

    # -- main
    def run_all(self) -> list[dict]:
        fmt = self.meta.get("format", "")
        assets = self.meta.get("assets") or []
        if fmt == "text" and not assets:
            return self.findings
        if not isinstance(assets, list) or not assets:
            self._add(FAIL, "render", f"meta.assets is empty for a '{fmt}' post: name the files in out/")
            return self.findings
        out_dir = self.draft / "out"
        present: list[Path] = []
        for a in assets:
            p = out_dir / str(a)
            if p.exists():
                present.append(p)
            else:
                self._add(FAIL, "render", f"missing asset out/{a}", token=str(a))
        self._freshness(out_dir)
        for p in present:
            suf = p.suffix.lower()
            if suf == ".pdf":
                self._pdf(p)
            elif suf == ".gif":
                self._gif(p)
        return self.findings

    def _freshness(self, out_dir: Path) -> None:
        rj = out_dir / "render.json"
        if not rj.exists():
            self._add(FAIL, "render", "out/render.json is missing; render the draft first (profile-wrap render <slug>)")
            return
        data, note = read_json(rj)
        if data is None:
            self._add(FAIL, "render", f"out/render.json: {note}")
            return
        sources = [self.draft / "slides.html"]
        vp = self.meta.get("video_project")
        if vp:
            sources.append(self.ws / str(vp) / "index.html")
        newest = max((s.stat().st_mtime for s in sources if s.exists()), default=0)
        if newest and rj.stat().st_mtime < newest:
            self._add(FAIL, "render", "render is older than its source (slides.html / index.html); re-render")
        if (self.draft / "slides.html").exists() and not (isinstance(data, dict) and data.get("slides")):
            self._add(FAIL, "render", "render.json reports 0 slides for a draft with slides.html")
        self._render_json = data if isinstance(data, dict) else {}

    def _pdf(self, p: Path) -> None:
        fonts_tool = self._tool("pdffonts", f"fonts of {p.name}")
        if fonts_tool:
            rc, out, err = self.run([fonts_tool, str(p)])
            if rc != 0:
                self._add(FAIL, "render", f"pdffonts failed on {p.name}: {(err or out).strip()[:120]}")
            else:
                rows = [ln for ln in out.splitlines()[2:] if ln.strip()]
                names = [ln.split()[0] for ln in rows]
                if any(re.search(r"\bType 3\b", ln) for ln in rows):
                    self._add(FAIL, "render", f"{p.name}: Type 3 font embedded (text will not be searchable)")
                need = [s.casefold() for s in self.g.get("required_font_substrings", []) if s]
                if need:
                    bad = [n for n in names if not any(s in n.casefold() for s in need)]
                    if bad:
                        self._add(FAIL, "render", f"{p.name}: font(s) outside the brand fonts (fallback glyphs): "
                                  f"{', '.join(bad)}", token=bad[0])
        info_tool = self._tool("pdfinfo", f"page count of {p.name}")
        n_slides = getattr(self, "_render_json", {}).get("slides")
        if info_tool and n_slides:
            rc, out, err = self.run([info_tool, str(p)])
            pages = next((ln.split()[-1] for ln in out.splitlines() if ln.startswith("Pages:")), "")
            if rc != 0 or not pages.isdigit():
                self._add(FAIL, "render", f"pdfinfo failed on {p.name}: {(err or out).strip()[:120]}")
            elif int(pages) != int(n_slides):
                self._add(FAIL, "render", f"{p.name} has {pages} pages but {n_slides} slides were rendered")

    def _gif(self, p: Path) -> None:
        gif = self.g["gif"]
        size_mb = p.stat().st_size / (1024 * 1024)
        if size_mb > gif["max_mb"]:
            self._add(FAIL, "render", f"{p.name} is {size_mb:.1f} MB (max {gif['max_mb']} MB)")
        probe = self._tool("ffprobe", f"frame count of {p.name}")
        frames = 0
        if probe:
            rc, out, err = self.run([probe, "-v", "error", "-count_frames", "-select_streams", "v:0", "-show_entries",
                                     "stream=nb_read_frames", "-of", "csv=p=0", str(p)])
            n = out.strip().splitlines()[0].strip() if out.strip() else ""
            if rc != 0 or err.strip() or not n.isdigit():
                self._add(FAIL, "render", f"{p.name} does not decode cleanly ({(err or n or 'no frame count').strip()[:100]})")
            else:
                frames = int(n)
                if frames <= 1:
                    self._add(FAIL, "render", f"{p.name} has {frames} frame(s); an animated GIF needs more")
                elif frames > gif["max_frames"]:
                    self._add(FAIL, "render", f"{p.name} has {frames} frames (max {gif['max_frames']})")
        ffmpeg = self._tool("ffmpeg", f"still-frame share of {p.name}") if frames > 1 else None
        if ffmpeg:
            rc, out, err = self.run([ffmpeg, "-hide_banner", "-nostdin", "-i", str(p), "-vf", "mpdecimate", "-f",
                                     "null", "-"])
            kept = re.findall(r"frame=\s*(\d+)", err)
            if rc == 0 and kept:
                dropped = max(0, frames - int(kept[-1]))
                pct = 100.0 * dropped / frames
                if pct > gif["max_still_pct"]:
                    self._add(FAIL, "render", f"{p.name}: {pct:.1f}% of frames are still (max {gif['max_still_pct']}%)")
            else:
                self._add(WARN, "render", f"still-frame check could not run on {p.name}: {err.strip()[-100:]}")
        if frames > 1:
            self._seam_and_flash(p, gif)

    def _seam_and_flash(self, p: Path, gif: dict) -> None:
        try:
            from PIL import Image, ImageSequence  # type: ignore
        except ImportError:
            self._missing("pillow", f"loop seam and flash check of {p.name}")
            return
        try:
            lum: list[float] = []
            dur: list[float] = []
            with Image.open(p) as im:
                for fr in ImageSequence.Iterator(im):
                    g = fr.convert("L")
                    g.thumbnail((48, 60))
                    px = g.tobytes()
                    lum.append(sum(px) / (len(px) * 255.0))
                    dur.append(float(fr.info.get("duration", 40)) or 40.0)
        except Exception as exc:  # corrupt or truncated file
            self._add(FAIL, "render", f"{p.name}: cannot read frames ({exc})")
            return
        if len(lum) < 3:
            return
        steps = sorted(abs(lum[i + 1] - lum[i]) for i in range(len(lum) - 1))
        median = steps[len(steps) // 2]
        seam = abs(lum[0] - lum[-1])
        if seam > SEAM_FACTOR * median + SEAM_FLOOR:
            self._add(FAIL, "render", f"{p.name}: loop seam jump {seam:.3f} (frame step median {median:.3f}); "
                      f"the last frame must flow into the first")
        # flashes: opposing luminance swings of >= FLASH_STEP inside any 1 s window
        t, times = 0.0, []
        for d in dur:
            times.append(t)
            t += d / 1000.0
        swings = [(times[i + 1], 1 if lum[i + 1] > lum[i] else -1) for i in range(len(lum) - 1)
                  if abs(lum[i + 1] - lum[i]) >= FLASH_STEP]
        worst = 0
        for i, (t0, _) in enumerate(swings):
            window = [s for s in swings[i:] if s[0] - t0 <= 1.0]
            pairs = sum(1 for a, b in zip(window, window[1:]) if a[1] != b[1])
            worst = max(worst, (pairs + 1) // 2 if pairs else 0)
        if worst > gif["flash_max_per_s"]:
            self._add(FAIL, "render", f"{p.name}: about {worst} flashes per second (max {gif['flash_max_per_s']})")


def derived_fonts(cfg: dict) -> list[str]:
    """Font substrings to require: gate.required_font_substrings, else the brand font families (spaces removed)."""
    explicit = cfg.get("gate", {}).get("required_font_substrings") or []
    if explicit:
        return list(explicit)
    fonts = (cfg.get("brand") or {}).get("fonts") or {}
    subs = []
    for key in ("display", "text", "arabic"):
        fam = (fonts.get(key) or {}).get("family") if isinstance(fonts.get(key), dict) else None
        if fam:
            subs.append(fam.replace(" ", ""))
    return subs
