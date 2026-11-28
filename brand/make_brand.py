#!/usr/bin/env python3
"""Build the Profile-Wrap logo and icon set from code.

    uv run --with pillow python brand/make_brand.py [--sheet PATH]

Writes (relative to the repo root):
  brand/svg/  mark-{light,dark}.svg, lockup-{light,dark}.svg, lockup-rtl-{light,dark}.svg, favicon.svg
  brand/png/  icon-32.png, icon-180.png, icon-192.png, icon-512.png
  gui_assets/mark.svg, site/favicon.svg, site/favicon.ico, site/apple-touch-icon.png, site/icon-512.png

The wordmark is drawn from outlines of the site's own display face
(site/fonts/display-bold-latin.woff2), so no font file is shipped or needed to view it.
Offline only: no network, no model. Needs pillow, cairosvg and fonttools; when one is
missing the script re-runs itself under `uv run --with ...` (nothing is installed globally).
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import struct
import subprocess
import sys
import tempfile
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NEEDED = {"PIL": "pillow", "cairosvg": "cairosvg", "fontTools": "fonttools", "brotli": "brotli"}


def _bootstrap() -> None:
    missing = [p for m, p in NEEDED.items() if importlib.util.find_spec(m) is None]
    if not missing or os.environ.get("PW_BRAND_BOOT"):
        return
    cmd = ["uv", "run"]
    for pkg in NEEDED.values():
        cmd += ["--with", pkg]
    cmd += ["python", str(Path(__file__).resolve()), *sys.argv[1:]]
    env = dict(os.environ, PW_BRAND_BOOT="1", PYTHONUTF8="1")
    sys.exit(subprocess.call(cmd, env=env))


_bootstrap()

import cairosvg  # noqa: E402
from fontTools.pens.svgPathPen import SVGPathPen  # noqa: E402
from fontTools.pens.transformPen import TransformPen  # noqa: E402
from fontTools.ttLib import TTFont  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

# ---- palette (site/index.html :root) -------------------------------------------------
PAPER, INK = "#F8F3E6", "#1B1A2E"
RUST, RUST2 = "#B4491F", "#8E3414"
TEAL, MUSTARD = "#2F7F76", "#D9A22E"
NAVY, NAVY2 = "#1F2B45", "#141C31"
ON_DARK = "#FBF6E8"
FONT = ROOT / "site" / "fonts" / "display-bold-latin.woff2"

NS = 'xmlns="http://www.w3.org/2000/svg"'


# ---- the tile, large version (>= 96 px): depth, highlights, contact shadows -----------
def _defs(uid: str) -> str:
    return f"""<defs>
<linearGradient id="{uid}t" x1="0.1" y1="0" x2="0.9" y2="1"><stop offset="0" stop-color="#34466F"/><stop offset="0.55" stop-color="{NAVY}"/><stop offset="1" stop-color="{NAVY2}"/></linearGradient>
<radialGradient id="{uid}g" cx="0.22" cy="0.12" r="0.8"><stop offset="0" stop-color="#8FA3D6" stop-opacity="0.34"/><stop offset="1" stop-color="#8FA3D6" stop-opacity="0"/></radialGradient>
<linearGradient id="{uid}e" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#9FB0DD" stop-opacity="0.75"/><stop offset="0.55" stop-color="#9FB0DD" stop-opacity="0.08"/><stop offset="1" stop-color="{MUSTARD}" stop-opacity="0.85"/></linearGradient>
<linearGradient id="{uid}c" x1="0" y1="0" x2="0.35" y2="1"><stop offset="0" stop-color="#FFFFFB"/><stop offset="1" stop-color="#E4D8BD"/></linearGradient>
<linearGradient id="{uid}b" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#CF5F2E"/><stop offset="0.55" stop-color="{RUST}"/><stop offset="1" stop-color="{RUST2}"/></linearGradient>
<linearGradient id="{uid}f" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#6E2810"/><stop offset="1" stop-color="#4E1A09"/></linearGradient>
<linearGradient id="{uid}a" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#34466F"/><stop offset="1" stop-color="{NAVY2}"/></linearGradient>
</defs>"""


def _glyph_large(uid: str) -> str:
    """Profile card wrapped by a rust band, on a 512 grid."""
    shadow = "".join(
        f'<rect x="{146 - i * 3}" y="{98 - i * 2 + 14}" width="{220 + i * 6}" height="{336 + i * 4}" rx="{34 + i * 3}" fill="#05091A" opacity="0.075"/>'
        for i in range(8)
    )
    return f"""{shadow}
<rect x="146" y="88" width="220" height="336" rx="34" fill="url(#{uid}c)"/>
<rect x="147.5" y="89.5" width="217" height="333" rx="32.5" fill="none" stroke="#FFFFFF" stroke-opacity="0.9" stroke-width="3"/>
<circle cx="256" cy="190" r="50" fill="url(#{uid}a)"/>
<ellipse cx="240" cy="172" rx="17" ry="11" fill="#FFFFFF" opacity="0.2" transform="rotate(-28 240 172)"/>
<path d="M172 304 C172 262 208 242 256 242 C304 242 340 262 340 304 Z" fill="url(#{uid}a)"/>
<path d="M126 306 L146 296 L146 360 L126 352 Z" fill="url(#{uid}f)"/>
<path d="M386 306 L366 296 L366 360 L386 352 Z" fill="url(#{uid}f)"/>
<rect x="146" y="298" width="220" height="64" fill="#2A0F05" opacity="0.28" transform="translate(0 6)"/>
<rect x="136" y="292" width="240" height="64" rx="6" fill="url(#{uid}b)"/>
<rect x="136" y="292" width="240" height="4" rx="2" fill="#FFFFFF" opacity="0.3"/>
<line x1="152" y1="324" x2="360" y2="324" stroke="{MUSTARD}" stroke-width="5" stroke-linecap="round" stroke-dasharray="14 12"/>
<rect x="190" y="382" width="132" height="14" rx="7" fill="{NAVY}" opacity="0.82"/>
<rect x="190" y="403" width="84" height="12" rx="6" fill="{TEAL}" opacity="0.9"/>"""


def tile_large(uid: str = "L", size: int | None = None, full_bleed: bool = False) -> str:
    wh = f' width="{size}" height="{size}"' if size else ""
    if full_bleed:  # apple-touch: opaque square, the OS rounds it
        base = f'<rect width="512" height="512" fill="url(#{uid}t)"/><rect width="512" height="512" fill="url(#{uid}g)"/>'
    else:
        base = (
            f'<rect x="16" y="16" width="480" height="480" rx="112" fill="url(#{uid}t)"/>'
            f'<rect x="16" y="16" width="480" height="480" rx="112" fill="url(#{uid}g)"/>'
            f'<rect x="17.5" y="17.5" width="477" height="477" rx="110.5" fill="none" stroke="url(#{uid}e)" stroke-width="3"/>'
        )
    k = 1.0 if full_bleed else 1.17  # full bleed keeps room for the OS corner mask
    glyph = f'<g transform="translate(256 256) scale({k}) translate(-256 -256)">{_glyph_large(uid)}</g>'
    return (
        f'<svg {NS} viewBox="0 0 512 512"{wh} role="img" aria-label="Profile-Wrap">'
        f"{_defs(uid)}{base}{glyph}</svg>"
    )


# ---- the tile, small version (favicon, GUI header): bold shapes, 64 grid ---------------
def tile_small(size: int | None = None) -> str:
    wh = f' width="{size}" height="{size}"' if size else ""
    return (
        f'<svg {NS} viewBox="0 0 64 64"{wh} role="img" aria-label="Profile-Wrap">'
        f'<defs><linearGradient id="st" x1="0.1" y1="0" x2="0.9" y2="1"><stop offset="0" stop-color="#2E3F66"/><stop offset="1" stop-color="{NAVY2}"/></linearGradient>'
        f'<linearGradient id="sb" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#CF5F2E"/><stop offset="1" stop-color="{RUST2}"/></linearGradient></defs>'
        f'<rect width="64" height="64" rx="15" fill="url(#st)"/>'
        f'<g transform="translate(32 32) scale(1.1) translate(-32 -32)"><rect x="17" y="8" width="30" height="48" rx="6.5" fill="{PAPER}"/>'
        f'<circle cx="32" cy="21.5" r="6.6" fill="{NAVY}"/>'
        f'<path d="M22.5 38 C22.5 30.5 27 29.5 32 29.5 C37 29.5 41.5 30.5 41.5 38 Z" fill="{NAVY}"/>'
        f'<rect x="11" y="35" width="42" height="11.5" rx="2" fill="url(#sb)"/>'
        f'<line x1="14.5" y1="40.75" x2="49.5" y2="40.75" stroke="{MUSTARD}" stroke-width="1.8" stroke-linecap="round" stroke-dasharray="3.4 3"/>'
        f'<rect x="23" y="50" width="18" height="2.6" rx="1.3" fill="{NAVY}"/></g>'
        f"</svg>"
    )


# ---- wordmark from the display-face outlines ------------------------------------------------
def wordmark_paths(text: str, size: float, x0: float, baseline: float):
    """Return ([(char, d)], advance) laid out left to right with advance widths only."""
    font = TTFont(str(FONT))
    gs, cmap = font.getGlyphSet(), font.getBestCmap()
    upm = font["head"].unitsPerEm
    k = size / upm
    x, out = x0, []
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[name].draw(TransformPen(pen, (k, 0, 0, -k, x, baseline)))
        out.append((ch, pen.getCommands()))
        x += gs[name].width * k
    return out, x - x0


def lockup(dark: bool, rtl: bool) -> str:
    """Tile plus wordmark. 'Profile-' in ink, 'Wrap' in rust (mustard on dark)."""
    H, gap, size = 160, 36, 92
    ink = ON_DARK if dark else INK
    accent = MUSTARD if dark else RUST
    paths, adv = wordmark_paths("Profile-Wrap", size, 0, 0)
    width = H + gap + adv
    base = 102  # baseline inside the 160 box: cap height ~ 0.7 * size, centred on the tile
    text_x = 0 if rtl else H + gap
    tile_x = width - H if rtl else 0
    tile_inner = tile_large("K").split(">", 1)[1].rsplit("</svg>", 1)[0]
    tx = text_x
    glyphs = []
    for i, (ch, d) in enumerate(paths):
        fill = accent if i >= len("Profile-") else ink
        if ch == "-":
            fill = accent
        glyphs.append(f'<path d="{d}" fill="{fill}"/>')
    return (
        f'<svg {NS} viewBox="0 0 {width:.1f} {H}" width="{width:.0f}" height="{H}" role="img" aria-label="Profile-Wrap">'
        f'<g transform="translate({tile_x:.1f} 0) scale({H / 512:.5f})">{tile_inner}</g>'
        f'<g transform="translate({tx:.1f} {base})">{"".join(glyphs)}</g></svg>'
    )


# ---- output ----------------------------------------------------------------------------
def png(svg: str, px: int) -> bytes:
    return cairosvg.svg2png(bytestring=svg.encode("utf-8"), output_width=px, output_height=px)


def ico(entries: list[tuple[int, bytes]]) -> bytes:
    head = struct.pack("<HHH", 0, 1, len(entries))
    off = 6 + 16 * len(entries)
    table, body = b"", b""
    for px, data in entries:
        table += struct.pack("<BBBBHHII", px % 256, px % 256, 0, 0, 1, 32, len(data), off + len(body))
        body += data
    return head + table + body


def write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, str):
        path.write_text(data, encoding="utf-8", newline="\n")
    else:
        path.write_bytes(data)


def build() -> dict[str, str | bytes]:
    out: dict[str, str | bytes] = {}
    out["brand/svg/mark-light.svg"] = tile_large("A")
    out["brand/svg/mark-dark.svg"] = tile_large("A")
    out["brand/svg/favicon.svg"] = tile_small()
    for dark in (False, True):
        tag = "dark" if dark else "light"
        out[f"brand/svg/lockup-{tag}.svg"] = lockup(dark, False)
        out[f"brand/svg/lockup-rtl-{tag}.svg"] = lockup(dark, True)
    out["gui_assets/mark.svg"] = tile_small()
    out["site/favicon.svg"] = tile_small()
    big = tile_large("P")
    out["brand/png/icon-32.png"] = png(tile_small(), 32)
    out["brand/png/icon-180.png"] = png(tile_large("Q", full_bleed=True), 180)
    out["brand/png/icon-192.png"] = png(big, 192)
    out["brand/png/icon-512.png"] = png(big, 512)
    out["site/apple-touch-icon.png"] = out["brand/png/icon-180.png"]
    out["site/icon-512.png"] = out["brand/png/icon-512.png"]
    small = tile_small()
    out["site/favicon.ico"] = ico([(16, png(small, 16)), (32, png(small, 32)), (48, png(small, 48))])
    return out


def load_font(px: int) -> ImageFont.FreeTypeFont:
    tmp = Path(tempfile.gettempdir()) / "pw-brand-font.ttf"
    if not tmp.exists():
        f = TTFont(str(FONT))
        f.flavor = None
        f.save(str(tmp))
    return ImageFont.truetype(str(tmp), px)


def sheet(path: Path) -> None:
    W, H = 1800, 1300
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([0, 650, W, H], fill=NAVY2)
    lab, labd = load_font(22), load_font(22)

    def paste(svg: str, w: int, h: int, xy):
        im = Image.open(BytesIO(cairosvg.svg2png(bytestring=svg.encode(), output_width=w, output_height=h))).convert("RGBA")
        img.paste(im, xy, im)

    for row, dark in ((0, False), (1, True)):
        y0 = 650 * row
        ink = ON_DARK if dark else INK
        tag = "dark" if dark else "light"
        d.text((40, y0 + 24), f"lockup {tag}  LTR / RTL", font=lab, fill=ink)
        l1 = lockup(dark, False)
        w1 = float(l1.split('viewBox="0 0 ')[1].split(" ")[0])
        paste(l1, 700, int(700 * 160 / w1), (40, y0 + 70))
        l2 = lockup(dark, True)
        wv = float(l2.split('viewBox="0 0 ')[1].split(" ")[0])
        paste(l2, 700, int(700 * 160 / wv), (860, y0 + 70))
        x = 40
        for px in (512, 192, 180, 96, 48, 32, 16):
            show = px if px <= 192 else 280
            svg = tile_large("S") if px >= 96 else tile_small()
            if px == 180:
                svg = tile_large("S", full_bleed=True)
            paste(svg, show, show, (x, y0 + 270 if px > 96 else y0 + 270 + 200))
            d.text((x, y0 + 270 + 290 if px > 96 else y0 + 270 + 200 + show + 6), str(px), font=labd, fill=ink)
            x += show + 36
        # browser tab mock
        tab_bg = "#2B2A3C" if dark else "#E9E3D2"
        d.rounded_rectangle([1120, y0 + 440, 1480, y0 + 484], 10, fill=tab_bg)
        paste(tile_small(), 20, 20, (1136, y0 + 452))
        d.text((1166, y0 + 449), "Profile-Wrap", font=load_font(20), fill=ink)
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", help="also write a contact sheet PNG here")
    ap.add_argument("--check", action="store_true", help="build in memory and fail if files on disk differ")
    a = ap.parse_args()
    files = build()
    if a.check:
        bad = [r for r, data in files.items() if not (ROOT / r).exists() or (ROOT / r).read_bytes() != (data if isinstance(data, bytes) else data.encode("utf-8"))]
        print("brand check:", "OK" if not bad else f"stale: {bad}")
        return 1 if bad else 0
    for rel, data in files.items():
        write(ROOT / rel, data)
    print(f"wrote {len(files)} files")
    if a.sheet:
        sheet(Path(a.sheet))
        print("sheet", a.sheet)
    return 0


if __name__ == "__main__":
    sys.exit(main())
