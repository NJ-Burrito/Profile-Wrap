"""Per-post themes for the narrated video styles: the palette, glows and canvas come from the post's subject.

A theme is ``theme.json`` in the video project (written at scaffold) plus ``theme.css``, the CSS variables the template reads.
The template holds no colour of its own. ``derive(image)`` reads a logo or screenshot (stdlib only: ffmpeg downsamples it to a
small RGBA grid), takes the dominant hue as the accent and the next distinct hue as the second accent, builds a dark
field and glows from them, and lifts every text colour until each text pair passes WCAG AA (4.5) and each UI pair 3.
"""
from __future__ import annotations

import colorsys
import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from . import VisualsError

RGB = Tuple[int, int, int]
TEXT_MIN = 4.5
UI_MIN = 3.0
GRID = 48
#: seed colour of the neutral default theme (a plain slate blue); a real post passes ``--theme-from <logo or screenshot>``.
DEFAULT_SEED = (59, 130, 246)

COLOUR_KEYS = ("bg", "glow_a", "glow_b", "ink", "muted", "faint", "accent", "ok", "panel", "line", "mark")


# ------------------------------------------------------------------ colour maths

def hex_to_rgb(value: str) -> RGB:
    v = value.strip().lstrip("#")
    if len(v) != 6:
        raise VisualsError(f"not a #rrggbb colour: {value!r}")
    return int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16)


def rgb_to_hex(rgb: RGB) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, int(round(c)))) for c in rgb)


def hsv_hex(h: float, s: float, v: float) -> str:
    r, g, b = colorsys.hsv_to_rgb(h % 1.0, max(0.0, min(1.0, s)), max(0.0, min(1.0, v)))
    return rgb_to_hex((r * 255, g * 255, b * 255))


def luminance(rgb: RGB) -> float:
    def lin(c: int) -> float:
        x = c / 255.0
        return x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4
    r, g, b = rgb
    return 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b)


def contrast(a: str, b: str) -> float:
    la, lb = luminance(hex_to_rgb(a)), luminance(hex_to_rgb(b))
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def rgba(value: str, alpha: float) -> str:
    r, g, b = hex_to_rgb(value)
    return f"rgba({r},{g},{b},{alpha:g})"


# ------------------------------------------------------------------ reading the subject's image

def sample_pixels(image: Path, *, grid: int = GRID) -> List[Tuple[int, int, int, int]]:
    """The image downsampled to ``grid`` x ``grid`` RGBA pixels, through ffmpeg (a build dependency already)."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise VisualsError("ffmpeg not found: install ffmpeg (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg)")
    image = Path(image)
    if not image.is_file():
        raise VisualsError(f"theme source not found: {image}")
    res = subprocess.run([ffmpeg, "-v", "error", "-i", str(image), "-frames:v", "1", "-vf", f"scale={grid}:{grid}:flags=area",
                          "-f", "rawvideo", "-pix_fmt", "rgba", "-"], capture_output=True, timeout=120)
    if res.returncode != 0 or len(res.stdout) != grid * grid * 4:
        raise VisualsError(f"{image.name} could not be read as an image: {res.stderr.decode('utf-8', 'replace').strip()[:160]}")
    d = res.stdout
    return [(d[i], d[i + 1], d[i + 2], d[i + 3]) for i in range(0, len(d), 4)]


def dominant_hues(pixels: List[Tuple[int, int, int, int]]) -> List[Tuple[float, float, float]]:
    """Hue clusters (hue, mean saturation, mean value), strongest first. Greys, near-black, near-white and transparent
    pixels carry no hue and are skipped; weight is saturation x value so a vivid small shape beats a pale large one."""
    bins = 24
    weight = [0.0] * bins
    sat = [0.0] * bins
    val = [0.0] * bins
    for r, g, b, a in pixels:
        if a < 128:
            continue
        h, s, v = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s < 0.25 or v < 0.25:
            continue
        w = s * v
        i = int(h * bins) % bins
        weight[i] += w
        sat[i] += s * w
        val[i] += v * w
    # merge each bin with its neighbours so one colour split across a bin edge counts once
    smooth = [weight[i] + 0.5 * (weight[(i - 1) % bins] + weight[(i + 1) % bins]) for i in range(bins)]
    order = sorted(range(bins), key=lambda i: -smooth[i])
    out: List[Tuple[float, float, float]] = []
    for i in order:
        if weight[i] <= 0:
            continue
        h = (i + 0.5) / bins
        if any(min(abs(h - o[0]), 1 - abs(h - o[0])) < 0.09 for o in out):
            continue
        out.append((h, sat[i] / weight[i], val[i] / weight[i]))
    return out


# ------------------------------------------------------------------ building a theme

def _lift(fg: str, backgrounds: List[str], need: float, h: float, s: float) -> str:
    """Raise the value (and ease the saturation) of ``fg`` until it clears ``need`` against every background."""
    cur = fg
    for _ in range(60):
        if all(contrast(cur, bg) >= need for bg in backgrounds):
            return cur
        r, g, b = hex_to_rgb(cur)
        _, cs, cv = colorsys.rgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        cur = hsv_hex(h, max(0.0, cs - 0.012), min(1.0, cv + 0.015))
    return cur


def build(accent_hue: float, accent_sat: float, accent_val: float, second_hue: Optional[float] = None, *,
          name: str = "", subject: str = "", motif: str = "", canvas: Optional[Dict[str, int]] = None,
          source: str = "") -> Dict:
    """A complete theme from one or two hues. Every text and UI pair is contrast-checked and lifted."""
    if second_hue is None:
        second_hue = (accent_hue - 0.14) % 1.0          # no second colour in the subject: a near neighbour toward green, so "result" still reads as one family
    bg = hsv_hex(accent_hue, 0.50, 0.075)
    glow_a = hsv_hex(accent_hue, 0.62, 0.30)
    glow_b = hsv_hex(second_hue, 0.55, 0.26)
    panel = hsv_hex(accent_hue, 0.40, 0.115)
    line = hsv_hex(accent_hue, 0.30, 0.26)
    surfaces = [bg, glow_a, glow_b, panel]
    ink = _lift(hsv_hex(accent_hue, 0.05, 0.97), surfaces, 7.0, accent_hue, 0.05)
    muted = _lift(hsv_hex(accent_hue, 0.14, 0.74), surfaces, TEXT_MIN, accent_hue, 0.14)
    faint = _lift(hsv_hex(accent_hue, 0.12, 0.70), surfaces, TEXT_MIN, accent_hue, 0.12)
    mark = _lift(hsv_hex(accent_hue, 0.20, 0.72), surfaces, TEXT_MIN, accent_hue, 0.20)
    accent = _lift(hsv_hex(accent_hue, max(0.55, min(1.0, accent_sat)), max(0.75, min(1.0, accent_val))), surfaces,
                   TEXT_MIN, accent_hue, accent_sat)
    ok = _lift(hsv_hex(second_hue, 0.62, 0.92), surfaces, TEXT_MIN, second_hue, 0.62)
    return {"name": name or "theme", "subject": subject, "source": source, "motif": motif,
            "canvas": dict(canvas or {"w": 1280, "h": 720}),
            "palette": {"bg": bg, "glow_a": glow_a, "glow_b": glow_b, "ink": ink, "muted": muted, "faint": faint,
                        "accent": accent, "ok": ok, "panel": panel, "line": line, "mark": mark}}


def default_theme() -> Dict:
    h, s, v = colorsys.rgb_to_hsv(*(c / 255.0 for c in DEFAULT_SEED))
    return build(h, s, v, name="neutral", subject="", motif="rings", source="default seed colour: replace per post")


def derive(image: Path, *, name: str = "", subject: str = "", motif: str = "",
           canvas: Optional[Dict[str, int]] = None) -> Dict:
    """A theme from a logo or screenshot of the post's subject."""
    hues = dominant_hues(sample_pixels(image))
    if not hues:
        raise VisualsError(f"{Path(image).name} has no colour to take a theme from (all grey, black, white or transparent); "
                           "pass a logo or screenshot that carries the subject's colour")
    h1, s1, v1 = hues[0]
    second = hues[1][0] if len(hues) > 1 else None
    return build(h1, s1, v1, second, name=name or Path(image).stem, subject=subject, motif=motif, canvas=canvas,
                 source=Path(image).name)


# ------------------------------------------------------------------ checks and output

def pairs(theme: Dict) -> List[Tuple[str, str, str, float]]:
    """(foreground key, background key, kind, minimum) for every pair the template draws, computed from the palette."""
    p = theme["palette"]
    surf = ("bg", "glow_a", "glow_b", "panel")
    out: List[Tuple[str, str, str, float]] = []
    for fg in ("ink", "muted", "faint", "mark", "accent", "ok"):
        for bg in surf:
            out.append((fg, bg, "text", TEXT_MIN))
    out.append(("bg", "accent", "text", TEXT_MIN))     # dark text on an accent fill (chips, stamps)
    out.append(("bg", "ok", "text", TEXT_MIN))
    out.append(("line", "panel", "ui", 1.0))          # a hairline border: decorative, no minimum
    out.append(("accent", "line", "ui", UI_MIN))      # accent on its own panel border
    assert all(a in p and b in p for a, b, _, _ in out)
    return out


def check(theme: Dict) -> Dict:
    """Contrast report computed from the palette: ``failures`` is empty when the theme is usable."""
    p = theme["palette"]
    rows, failures = [], []
    for fg, bg, kind, need in pairs(theme):
        ratio = round(contrast(p[fg], p[bg]), 2)
        row = {"fg": fg, "bg": bg, "kind": kind, "ratio": ratio, "min": need}
        rows.append(row)
        if ratio < need:
            failures.append(f"{fg} on {bg}: {ratio} < {need}")
    return {"pairs": len(rows), "failures": failures, "rows": rows}


def validate(theme: Dict) -> Dict:
    """A theme read from disk: the keys must all be there and be #rrggbb. Returns the theme."""
    p = theme.get("palette") if isinstance(theme, dict) else None
    if not isinstance(p, dict):
        raise VisualsError("theme has no palette")
    missing = [k for k in COLOUR_KEYS if k not in p]
    if missing:
        raise VisualsError(f"theme palette is missing: {', '.join(missing)}")
    for k in COLOUR_KEYS:
        hex_to_rgb(str(p[k]))
    cv = theme.get("canvas") or {}
    if not (isinstance(cv.get("w"), int) and isinstance(cv.get("h"), int) and cv["w"] > 0 and cv["h"] > 0):
        raise VisualsError("theme canvas needs integer w and h")
    return theme


def css(theme: Dict) -> str:
    """The ``:root`` variables the template reads (theme.css)."""
    p = validate(theme)["palette"]
    cv = theme["canvas"]
    lines = [
        "/* GENERATED by profile-wrap from theme.json. Do not edit; change theme.json and re-scaffold, or edit both. */",
        ":root {",
        f"  --w: {cv['w']}px; --h: {cv['h']}px;",
        f"  --c-bg: {p['bg']};",
        f"  --c-glow-a: {p['glow_a']}; --c-glow-a-0: {rgba(p['glow_a'], 0)};",
        f"  --c-glow-b: {p['glow_b']}; --c-glow-b-0: {rgba(p['glow_b'], 0)};",
        f"  --c-ink: {p['ink']}; --c-muted: {p['muted']}; --c-faint: {p['faint']}; --c-mark: {p['mark']};",
        f"  --c-accent: {p['accent']}; --c-ok: {p['ok']};",
        f"  --c-panel: {p['panel']}; --c-line: {p['line']};",
        f"  --c-on-accent: {p['bg']};",
        f"  --glow-hot: {rgba(p['accent'], 0.45)}; --glow-ok: {rgba(p['ok'], 0.5)};",
        "}",
        "",
    ]
    return "\n".join(lines)


def write(project: Path, theme: Dict) -> Dict:
    """Write theme.json and theme.css into a video project."""
    from profile_wrap import atomic
    validate(theme)
    atomic.atomic_write_json(Path(project) / "theme.json", theme)
    atomic.atomic_write_text(Path(project) / "theme.css", css(theme))
    return theme


def load(path: Path) -> Dict:
    try:
        return validate(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError) as exc:
        raise VisualsError(f"{path} unreadable: {exc}")


def parse_canvas(text: str) -> Dict[str, int]:
    try:
        w, h = text.lower().split("x")
        out = {"w": int(w), "h": int(h)}
    except ValueError:
        raise VisualsError(f"canvas is WxH, for example 1080x1350 (got {text!r})")
    if out["w"] < 320 or out["h"] < 320 or out["w"] > 4096 or out["h"] > 4096:
        raise VisualsError(f"canvas {text} is outside 320 to 4096 px")
    return out
