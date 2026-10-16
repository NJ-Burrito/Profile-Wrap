"""``njli visuals metrics <slug>``: still-frame share, loop-seam difference, flash counter, WCAG contrast pairs.

Frames come from Pillow when it is installed; without it ffmpeg decodes a small raw RGB thumbnail stream, so the
numbers are the same and no extra is needed. Nothing is typed in: every figure is computed from the GIF and the
shot plan as they are now.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from njli import atomic

from . import VisualsError, proc

THUMB_W = 108
CHANGE_LEVEL = 12          # luminance levels (0..255) that count as a changed pixel
STILL_FRACTION = 0.0005    # a frame is "still" when fewer than this share of pixels changed
FLASH_STEP = 0.10          # a mean-luminance swing of 10 % between frames is a flash edge
SEAM_LIMIT = 3.0           # mean absolute luminance difference (0..255) inside the seam band
SEAM_RATCHET = 2.0         # a non-ratcheting upgrade may be this much worse than the previous GIF's own seam
POSTER_MIN = 0.04          # frame 0 is a finished poster: at least this share of pixels is not background
IDENTITY_BAND = 170 / 1350  # bottom share of the canvas the identity card and signature own


@dataclass
class Frames:
    width: int
    height: int
    rgb: List[bytes]                 # thumbnail RGB bytes per frame
    durations: List[float]           # seconds per frame
    source_w: int = 0
    source_h: int = 0
    _luma: Optional[List[List[float]]] = None

    @property
    def n(self) -> int:
        return len(self.rgb)

    def luma_all(self) -> List[List[float]]:
        if self._luma is None:
            self._luma = [_luma(f) for f in self.rgb]
        return self._luma


# ------------------------------------------------------------------ decoding

def _pillow():
    try:
        from PIL import Image, ImageSequence  # type: ignore
        return Image, ImageSequence
    except ImportError:
        return None


def decode_frames(gif: Path, thumb_w: int = THUMB_W) -> Frames:
    pil = _pillow()
    if pil:
        Image, ImageSequence = pil
        rgb: List[bytes] = []
        durs: List[float] = []
        with Image.open(gif) as im:
            sw, sh = im.size
            tw = min(thumb_w, sw)
            th = max(1, round(sh * tw / sw))
            for fr in ImageSequence.Iterator(im):
                durs.append((float(fr.info.get("duration", 40)) or 40.0) / 1000.0)
                rgb.append(fr.convert("RGB").resize((tw, th)).tobytes())
        return Frames(tw, th, rgb, durs, sw, sh)
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not (ffmpeg and ffprobe):
        raise VisualsError("cannot read frames: install Pillow (uv pip install pillow) or ffmpeg")
    probe = proc.run([ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                      "stream=width,height,avg_frame_rate", "-of", "json", str(gif)], timeout=120)
    try:
        st = json.loads(probe.stdout)["streams"][0]
        sw, sh = int(st["width"]), int(st["height"])
        num, den = (st.get("avg_frame_rate") or "25/1").split("/")
        fps = float(num) / float(den) if float(den) else 25.0
    except (ValueError, KeyError, IndexError):
        raise VisualsError(f"ffprobe cannot read {gif.name}: {probe.tail(200)}")
    tw = min(thumb_w, sw)
    th = max(2, round(sh * tw / sw))
    res = _run_bytes([ffmpeg, "-v", "error", "-i", str(gif), "-vf", f"scale={tw}:{th}", "-f", "rawvideo",
                      "-pix_fmt", "rgb24", "-"])
    size = tw * th * 3
    if not res or len(res) < size:
        raise VisualsError(f"ffmpeg decoded no frames from {gif.name}")
    frames = [res[i:i + size] for i in range(0, len(res) - size + 1, size)]
    return Frames(tw, th, frames, [1.0 / (fps or 25.0)] * len(frames), sw, sh)


def _run_bytes(cmd: Sequence[str]) -> Optional[bytes]:
    import subprocess
    try:
        p = subprocess.run(list(cmd), capture_output=True, timeout=600,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout if p.returncode == 0 else None


# ------------------------------------------------------------------ measures

def _luma(frame: bytes) -> List[float]:
    # Rec. 601 integer approximation, one value per pixel
    return [(299 * frame[i] + 587 * frame[i + 1] + 114 * frame[i + 2]) / 1000.0 for i in range(0, len(frame), 3)]


def hold_frames(plan: Optional[dict]) -> List[Tuple[int, int]]:
    """The logged dead stops of shot-plan.json as (first, last) frame indices."""
    out: List[Tuple[int, int]] = []
    for h in (plan or {}).get("hold") or []:
        fr = h.get("frames")
        if isinstance(fr, (list, tuple)) and len(fr) == 2:
            out.append((int(fr[0]), int(fr[1])))
    return out


def still_share(frames: Frames, holds: Sequence[Tuple[int, int]] = ()) -> Dict[str, float]:
    """Share of frame transitions with (almost) no change. Transitions inside a logged hold are excluded."""
    luma = frames.luma_all()
    npx = len(luma[0]) if luma else 1
    counted = still = held = 0
    for i in range(1, len(luma)):
        in_hold = any(a <= i <= b for a, b in holds)
        changed = sum(1 for x, y in zip(luma[i - 1], luma[i]) if abs(x - y) > CHANGE_LEVEL)
        is_still = changed / npx < STILL_FRACTION
        if in_hold:
            held += 1
            continue
        counted += 1
        still += 1 if is_still else 0
    return {"still_pct": round(100.0 * still / counted, 2) if counted else 0.0, "still_frames": still,
            "counted_frames": counted, "held_frames": held}


def seam_band(frames: Frames, identity: bool, canvas_h: Optional[int] = None) -> Tuple[int, int]:
    """Rows (in thumbnail pixels) the seam check compares: the identity band when the card is on, else the frame."""
    h = frames.height
    if identity:
        return max(0, int(h * (1 - IDENTITY_BAND))), h
    return 0, h


def seam_diff(frames: Frames, identity: bool = False) -> float:
    """Mean absolute luminance difference between the first and last frame inside the seam band (0..255)."""
    if frames.n < 2:
        return 0.0
    la = frames.luma_all()
    a, b = la[0], la[-1]
    y0, y1 = seam_band(frames, identity)
    w = frames.width
    seg = range(y0 * w, y1 * w)
    return round(sum(abs(a[i] - b[i]) for i in seg) / max(1, len(seg)), 3)


def poster_share(frames: Frames) -> float:
    """Share of frame-0 pixels that differ from its dominant colour. A masked or blank poster scores ~0."""
    if not frames.rgb:
        return 0.0
    f = frames.rgb[0]
    px = [(f[i] >> 3, f[i + 1] >> 3, f[i + 2] >> 3) for i in range(0, len(f), 3)]
    counts: Dict[Tuple[int, int, int], int] = {}
    for c in px:
        counts[c] = counts.get(c, 0) + 1
    return round(1.0 - max(counts.values()) / len(px), 4)


def flashes(frames: Frames) -> Dict[str, float]:
    """Luminance flashes: opposing swings of >= FLASH_STEP of mean luminance. Also whether a flash is red."""
    lum, red = [], []
    for f, lf in zip(frames.rgb, frames.luma_all()):
        px = len(f) // 3
        lum.append(sum(lf) / (px * 255.0))
        reds = sum(1 for i in range(0, len(f), 3) if f[i] > 150 and f[i + 1] < 80 and f[i + 2] < 80)
        red.append(reds / px)
    t, times = 0.0, []
    for d in frames.durations:
        times.append(t)
        t += d
    swings = [(times[i + 1], 1 if lum[i + 1] > lum[i] else -1, i + 1) for i in range(len(lum) - 1)
              if abs(lum[i + 1] - lum[i]) >= FLASH_STEP]
    worst = 0
    for i, (t0, _, _) in enumerate(swings):
        window = [s for s in swings[i:] if s[0] - t0 <= 1.0]
        pairs = sum(1 for a, b in zip(window, window[1:]) if a[1] != b[1])
        worst = max(worst, (pairs + 1) // 2 if pairs else 0)
    pairs_total = sum(1 for a, b in zip(swings, swings[1:]) if a[1] != b[1])
    flash_count = (pairs_total + 1) // 2 if pairs_total else 0
    red_flash = any(red[idx] > 0.25 for _, _, idx in swings)
    return {"max_per_second": worst, "per_loop": flash_count, "red": bool(red_flash), "duration_s": round(t, 3)}


# ------------------------------------------------------------------ contrast

def _channel(c: int) -> float:
    v = c / 255.0
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def rel_luminance(hex_colour: str) -> float:
    h = hex_colour.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise ValueError(f"not a hex colour: {hex_colour!r}")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def wcag_ratio(fg: str, bg: str) -> float:
    a, b = rel_luminance(fg), rel_luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


def contrast_report(plan: Optional[dict]) -> Dict[str, object]:
    """Each ``contrast_pairs`` entry [fg, bg, minimum] of shot-plan.json is computed from the colours now written."""
    rows, failures = [], 0
    for pair in (plan or {}).get("contrast_pairs") or []:
        try:
            fg, bg, need = pair[0], pair[1], float(pair[2])
            ratio = wcag_ratio(fg, bg)
        except (ValueError, IndexError, TypeError) as exc:
            rows.append({"pair": pair, "error": str(exc), "ok": False})
            failures += 1
            continue
        ok = ratio + 1e-9 >= need
        failures += 0 if ok else 1
        rows.append({"fg": fg, "bg": bg, "min": need, "ratio": round(ratio, 2), "ok": ok})
    return {"pairs": rows, "failures": failures}


# ------------------------------------------------------------------ the report

@dataclass
class Report:
    gif: str
    frames: int
    bytes: int
    still: Dict[str, float]
    seam: float
    poster: float
    flash: Dict[str, float]
    contrast: Dict[str, object]
    problems: List[str] = field(default_factory=list)
    limits: Dict[str, float] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict:
        return {"gif": self.gif, "frames": self.frames, "bytes": self.bytes, "mib": round(self.bytes / 2**20, 2),
                "still": self.still, "seam_band_diff": self.seam, "poster_ink": self.poster, "flash": self.flash, "contrast": self.contrast,
                "limits": self.limits, "problems": self.problems, "ok": self.ok}


def analyze(gif: Path, plan: Optional[dict] = None, cfg: Optional[dict] = None, *, identity: Optional[bool] = None,
            seam_limit: Optional[float] = None) -> Report:
    gif = Path(gif)
    if not gif.is_file():
        raise VisualsError(f"{gif} not found")
    g = (((cfg or {}).get("gate") or {}).get("gif")) or {}
    max_frames = int(g.get("max_frames", 250))
    max_mb = float(g.get("max_mb", 40))
    max_still = float(g.get("max_still_pct", 8))
    max_flash = float(g.get("flash_max_per_s", 3))
    if identity is None:
        identity = bool((((cfg or {}).get("brand") or {}).get("identity") or {}).get("enabled"))
    frames = decode_frames(gif)
    holds = hold_frames(plan)
    still = still_share(frames, holds)
    sd = seam_diff(frames, bool(identity))
    fl = flashes(frames)
    ps = poster_share(frames)
    con = contrast_report(plan)
    limit = SEAM_LIMIT if seam_limit is None else seam_limit
    rep = Report(str(gif), frames.n, gif.stat().st_size, still, sd, ps, fl, con,
                 limits={"max_frames": max_frames, "max_mb": max_mb, "max_still_pct": max_still,
                         "seam_limit": limit, "flash_max_per_s": max_flash, "poster_min_ink": POSTER_MIN})
    if frames.n > max_frames:
        rep.problems.append(f"{frames.n} frames (max {max_frames})")
    if rep.bytes > max_mb * 1024 * 1024:
        rep.problems.append(f"{rep.bytes / 2**20:.1f} MiB (max {max_mb:g})")
    if still["still_pct"] > max_still:
        rep.problems.append(f"{still['still_pct']}% of frames are still (max {max_still:g}%, logged holds excluded)")
    if sd > limit:
        rep.problems.append(f"loop seam differs by {sd} in the {'identity band' if identity else 'frame'} (limit {limit:g})")
    if ps < POSTER_MIN:
        rep.problems.append(f"frame 0 looks blank or masked ({ps:.1%} of pixels differ from its background; poster needs {POSTER_MIN:.0%})")
    if fl["max_per_second"] > max_flash:
        rep.problems.append(f"{fl['max_per_second']} flashes in one second (max {max_flash:g})")
    if fl["per_loop"] > 1:
        rep.problems.append(f"{fl['per_loop']} flashes per loop (at most 1)")
    if fl["red"]:
        rep.problems.append("a red flash (never red)")
    if con["failures"]:
        rep.problems.append(f"{con['failures']} contrast pair(s) below their minimum")
    return rep


def find_gif(draft: Path, meta: dict) -> Path:
    for a in meta.get("assets") or []:
        if str(a).endswith(".gif") and (draft / "out" / a).is_file():
            return draft / "out" / a
    found = sorted((draft / "out").glob("*.gif")) if (draft / "out").is_dir() else []
    if not found:
        raise VisualsError(f"no GIF in {draft / 'out'}: run 'njli render {draft.name}' first")
    return found[0]


def run_for_slug(slug: str, workspace: Path, cfg: dict, write: bool = True) -> Report:
    draft = Path(workspace) / "drafts" / slug
    if not draft.is_dir():
        raise VisualsError(f"no draft at {draft}")
    try:
        meta = json.loads((draft / "meta.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VisualsError(f"{draft / 'meta.json'} unreadable: {exc}")
    plan = None
    vp = meta.get("video_project")
    if vp and (Path(workspace) / vp / "shot-plan.json").is_file():
        plan = json.loads((Path(workspace) / vp / "shot-plan.json").read_text(encoding="utf-8"))
    rep = analyze(find_gif(draft, meta), plan, cfg)
    if write:
        atomic.atomic_write_json(draft / "out" / "metrics.json", rep.to_dict())
    return rep


def format_lines(rep: Report) -> List[str]:
    lines = [f"{Path(rep.gif).name}: frames={rep.frames} size={rep.bytes / 2**20:.2f} MiB",
             f"  still={rep.still['still_pct']}% (limit {rep.limits['max_still_pct']:g}%, "
             f"{rep.still['held_frames']} held frame(s) excluded)",
             f"  seam_band_diff={rep.seam} (limit {rep.limits['seam_limit']:g}); poster_ink={rep.poster:.1%}",
             f"  flashes: {rep.flash['max_per_second']}/s max, {rep.flash['per_loop']} per loop, red={rep.flash['red']}",
             f"  contrast: {len(rep.contrast['pairs'])} pair(s), {rep.contrast['failures']} failing"]
    lines += [f"FAIL {p}" for p in rep.problems]
    lines.append("metrics: " + ("PASS" if rep.ok else "FAIL"))
    return lines
