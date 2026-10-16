"""Signature data for the opt-in identity card: ``none``, ``typed``, ``svg``, or a traced PNG.

- ``typed``: the outlines of the user's name in an OFL (or otherwise licensed) script font, via ``fontTools`` only
  (extra ``[sig]``: fonttools). No scikit-image, no numpy. Each glyph contour becomes one stroke that the motion
  library draws on.
- ``svg``: a user-supplied SVG; every ``<path>`` becomes a stroke in document order.
- ``trace``: a PNG of the user's own handwriting -> skeleton -> strokes -> simplified Bezier curves. Needs the extra
  ``[sig]`` (scikit-image, pillow, numpy) and optional waypoints JSON that fixes the writing order. Nothing is
  shipped: the photo and the signature stay the user's own files, in ``brand/identity/``.

The result is written to ``brand/identity/signature.data.js`` (never into the motion core).
"""
from __future__ import annotations

import json
import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from profile_wrap import atomic

from . import VisualsError

Point = Tuple[float, float]
SIG_REL = Path("brand") / "identity" / "signature.data.js"


# ------------------------------------------------------------------ path maths (stdlib)

_TOKEN = re.compile(r"([MmLlHhVvCcSsQqTtAaZz])|(-?\d*\.?\d+(?:[eE][-+]?\d+)?)")


def _cubic(p0: Point, p1: Point, p2: Point, p3: Point, n: int = 12) -> List[Point]:
    out = []
    for i in range(1, n + 1):
        t = i / n
        u = 1 - t
        out.append((u**3 * p0[0] + 3 * u * u * t * p1[0] + 3 * u * t * t * p2[0] + t**3 * p3[0],
                    u**3 * p0[1] + 3 * u * u * t * p1[1] + 3 * u * t * t * p2[1] + t**3 * p3[1]))
    return out


def flatten(d: str) -> List[Point]:
    """Sample an SVG path ``d`` into a polyline (absolute and relative M L H V C S Q T Z; arcs become lines)."""
    toks = _TOKEN.findall(d)
    items: List[object] = [t[0] if t[0] else float(t[1]) for t in toks]
    pts: List[Point] = []
    i, cur, start, cmd = 0, (0.0, 0.0), (0.0, 0.0), ""
    last_c: Optional[Point] = None
    last_q: Optional[Point] = None

    def num() -> float:
        nonlocal i
        v = items[i]
        i += 1
        if not isinstance(v, float):
            raise ValueError("bad path data")
        return v

    while i < len(items):
        if isinstance(items[i], str):
            cmd = str(items[i])
            i += 1
            if cmd in "Zz":
                cur = start
                pts.append(cur)
                last_c = last_q = None
                continue
        rel = cmd.islower()
        c = cmd.upper()
        ox, oy = cur if rel else (0.0, 0.0)
        if c == "M":
            cur = (num() + ox, num() + oy)
            start = cur
            pts.append(cur)
            cmd = "l" if rel else "L"
            last_c = last_q = None
        elif c == "L":
            cur = (num() + ox, num() + oy)
            pts.append(cur)
            last_c = last_q = None
        elif c == "H":
            cur = (num() + ox, cur[1])
            pts.append(cur)
            last_c = last_q = None
        elif c == "V":
            cur = (cur[0], num() + oy)
            pts.append(cur)
            last_c = last_q = None
        elif c == "C":
            p1 = (num() + ox, num() + oy)
            p2 = (num() + ox, num() + oy)
            p3 = (num() + ox, num() + oy)
            pts += _cubic(cur, p1, p2, p3)
            cur, last_c, last_q = p3, p2, None
        elif c == "S":
            p1 = (2 * cur[0] - last_c[0], 2 * cur[1] - last_c[1]) if last_c else cur
            p2 = (num() + ox, num() + oy)
            p3 = (num() + ox, num() + oy)
            pts += _cubic(cur, p1, p2, p3)
            cur, last_c, last_q = p3, p2, None
        elif c in "QT":
            if c == "Q":
                q = (num() + ox, num() + oy)
            else:
                q = (2 * cur[0] - last_q[0], 2 * cur[1] - last_q[1]) if last_q else cur
            p3 = (num() + ox, num() + oy)
            c1 = (cur[0] + 2 / 3 * (q[0] - cur[0]), cur[1] + 2 / 3 * (q[1] - cur[1]))
            c2 = (p3[0] + 2 / 3 * (q[0] - p3[0]), p3[1] + 2 / 3 * (q[1] - p3[1]))
            pts += _cubic(cur, c1, c2, p3)
            cur, last_q, last_c = p3, q, None
        elif c == "A":
            for _ in range(5):
                num()
            cur = (num() + ox, num() + oy)
            pts.append(cur)
            last_c = last_q = None
        else:
            raise ValueError(f"unsupported path command {cmd!r}")
    return pts


def path_length(d: str) -> float:
    pts = flatten(d)
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


def bounds(strokes: Sequence[Sequence[Point]]) -> Tuple[float, float, float, float]:
    xs = [p[0] for s in strokes for p in s]
    ys = [p[1] for s in strokes for p in s]
    if not xs:
        raise VisualsError("the signature has no points")
    return min(xs), min(ys), max(xs), max(ys)


def _pack(strokes: List[Tuple[str, str, float]], pad: float = 8.0) -> dict:
    """[(id, d, width)] -> the SIGNATURE object the motion library reads."""
    polys = [flatten(d) for _, d, _ in strokes]
    x0, y0, x1, y1 = bounds(polys)
    vb = [math.floor(x0 - pad), math.floor(y0 - pad), math.ceil(x1 - x0 + 2 * pad), math.ceil(y1 - y0 + 2 * pad)]
    out = []
    for (sid, d, w), poly in zip(strokes, polys):
        length = sum(math.dist(a, b) for a, b in zip(poly, poly[1:]))
        out.append([sid, max(1, round(length)), round(w, 1), d])
    return {"viewBox": vb, "strokes": out}


def _num(v: float) -> str:
    return f"{v:.1f}".rstrip("0").rstrip(".") if abs(v) >= 0.05 else "0"


# ------------------------------------------------------------------ typed

def typed(text: str, font_path: Path, *, height: float = 300.0, stroke: Optional[float] = None,
          swash: bool = True) -> dict:
    """Outline strokes of ``text`` in the font at ``font_path``. Needs fontTools only."""
    try:
        from fontTools.pens.svgPathPen import SVGPathPen  # type: ignore
        from fontTools.pens.transformPen import TransformPen  # type: ignore
        from fontTools.ttLib import TTFont  # type: ignore
    except ImportError:
        raise VisualsError("typed signatures need fonttools: uv pip install fonttools (extra: profile-wrap[sig])")
    text = text.strip()
    if not text:
        raise VisualsError("typed signature: the name is empty")
    path = Path(font_path)
    if not path.is_file():
        raise VisualsError(f"typed signature: font file not found: {path}")
    try:
        font = TTFont(str(path), lazy=True)
        gs = font.getGlyphSet()
        cmap = font.getBestCmap() or {}
        upm = float(font["head"].unitsPerEm)
        hmtx = font["hmtx"]
    except Exception as exc:
        raise VisualsError(f"typed signature: cannot read {path.name}: {exc}")
    s = height / upm
    x = 0.0
    strokes: List[Tuple[str, str, float]] = []
    skipped = []
    for ch in text:
        gname = cmap.get(ord(ch))
        if gname is None:
            skipped.append(ch)
            x += 0.3 * upm
            continue
        pen = SVGPathPen(gs, ntos=_num)
        gs[gname].draw(TransformPen(pen, (s, 0, 0, -s, x * s, 0)))
        d = pen.getCommands()
        for sub in re.findall(r"M[^M]*", d):
            if len(flatten(sub)) > 2:
                strokes.append((f"t{len(strokes) + 1}", sub.strip(), 0.0))
        x += float(hmtx[gname][0])
    if not strokes:
        raise VisualsError(f"typed signature: {path.name} has no outlines for {text!r}"
                           + (f" (missing glyphs: {''.join(skipped)})" if skipped else ""))
    w = stroke if stroke else max(2.0, height * 0.02)
    strokes = [(sid, d, w) for sid, d, _ in strokes]
    if swash:
        x0, y0, x1, y1 = bounds([flatten(d) for _, d, _ in strokes])
        yb = y1 + height * 0.12
        c = (x1 - x0) * 0.33
        strokes.append(("swash-main", f"M{_num(x0)} {_num(yb)}C{_num(x0 + c)} {_num(yb + height * 0.06)} "
                        f"{_num(x1 - c)} {_num(yb - height * 0.06)} {_num(x1 + height * 0.1)} {_num(yb - height * 0.02)}", w * 1.2))
    data = _pack(strokes)
    data["mode"] = "typed"
    if skipped:
        data["skipped"] = skipped
    return data


# ------------------------------------------------------------------ svg

def from_svg(svg_text: str) -> dict:
    """A user-supplied SVG: each <path> is one stroke, in document order."""
    try:
        root = ET.fromstring(svg_text)
    except ET.ParseError as exc:
        raise VisualsError(f"the signature SVG is not valid XML: {exc}")
    paths = [e for e in root.iter() if e.tag.split("}")[-1] == "path" and e.get("d")]
    if not paths:
        raise VisualsError("the signature SVG has no <path d=...> elements")
    strokes = []
    for i, e in enumerate(paths, 1):
        w = e.get("stroke-width") or root.get("stroke-width") or "4"
        try:
            width = float(re.sub(r"[^0-9.]", "", w) or 4)
        except ValueError:
            width = 4.0
        try:
            flatten(e.get("d", ""))
        except (ValueError, IndexError) as exc:
            raise VisualsError(f"path {i} of the signature SVG cannot be read: {exc}")
        strokes.append((e.get("id") or f"s{i}", e.get("d", ""), width))
    data = _pack(strokes)
    vb = root.get("viewBox")
    if vb:
        try:
            nums = [float(v) for v in re.split(r"[ ,]+", vb.strip())]
            if len(nums) == 4:
                data["viewBox"] = [round(v) for v in nums]
        except ValueError:
            pass
    data["mode"] = "svg"
    return data


# ------------------------------------------------------------------ trace (extra: scikit-image)

def _simplify(pts: List[Point], eps: float) -> List[Point]:
    """Ramer-Douglas-Peucker."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    stack = [(0, len(pts) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        (ax, ay), (bx, by) = pts[i], pts[j]
        dx, dy = bx - ax, by - ay
        norm = math.hypot(dx, dy)
        best, bi = -1.0, i
        for k in range(i + 1, j):
            px, py = pts[k]
            dist = abs(dx * (py - ay) - dy * (px - ax)) / norm if norm else math.hypot(px - ax, py - ay)
            if dist > best:
                best, bi = dist, k
        if best > eps:
            keep[bi] = True
            stack += [(i, bi), (bi, j)]
    return [p for p, k in zip(pts, keep) if k]


def _smooth(pts: List[Point], radius: int) -> List[Point]:
    if radius <= 0 or len(pts) < 3:
        return list(pts)
    out = []
    for i, _ in enumerate(pts):
        lo, hi = max(0, i - radius), min(len(pts), i + radius + 1)
        seg = pts[lo:hi]
        out.append((sum(p[0] for p in seg) / len(seg), sum(p[1] for p in seg) / len(seg)))
    out[0], out[-1] = pts[0], pts[-1]
    return out


def _unit(a: Point, b: Point) -> Point:
    n = math.hypot(b[0] - a[0], b[1] - a[1])
    return ((b[0] - a[0]) / n, (b[1] - a[1]) / n) if n > 1e-9 else (0.0, 0.0)


def bezier_path(pts: List[Point], corner_deg: float = 62.0) -> str:
    """Cubic Bezier through simplified vertices; sharp corners keep separate in/out tangents."""
    n = len(pts)
    if n < 2:
        raise VisualsError("a stroke needs at least two points")
    tin: List[Point] = [(0.0, 0.0)] * n
    tout: List[Point] = [(0.0, 0.0)] * n
    for i in range(n):
        if i == 0:
            tin[i] = tout[i] = _unit(pts[0], pts[1])
        elif i == n - 1:
            tin[i] = tout[i] = _unit(pts[i - 1], pts[i])
        else:
            a, b = _unit(pts[i - 1], pts[i]), _unit(pts[i], pts[i + 1])
            ang = math.degrees(math.acos(max(-1.0, min(1.0, a[0] * b[0] + a[1] * b[1]))))
            if ang > corner_deg:
                tin[i], tout[i] = a, b
            else:
                m = _unit((0.0, 0.0), (a[0] + b[0], a[1] + b[1]))
                tin[i] = tout[i] = m
    segs = [f"M{_num(pts[0][0])} {_num(pts[0][1])}"]
    for i in range(n - 1):
        L = math.dist(pts[i], pts[i + 1])
        c1 = (pts[i][0] + tout[i][0] * L / 3, pts[i][1] + tout[i][1] * L / 3)
        c2 = (pts[i + 1][0] - tin[i + 1][0] * L / 3, pts[i + 1][1] - tin[i + 1][1] * L / 3)
        segs.append(f"C{_num(c1[0])} {_num(c1[1])} {_num(c2[0])} {_num(c2[1])} {_num(pts[i + 1][0])} {_num(pts[i + 1][1])}")
    return "".join(segs)


def _walk_skeleton(skel) -> List[List[Point]]:
    """Trace a boolean skeleton array into pixel paths between endpoints/junctions (stdlib walk over numpy output)."""
    import numpy as np  # type: ignore
    ys, xs = np.nonzero(skel)
    pixels = set(zip(xs.tolist(), ys.tolist()))
    nbrs = {p: [(p[0] + dx, p[1] + dy) for dx in (-1, 0, 1) for dy in (-1, 0, 1)
                if (dx or dy) and (p[0] + dx, p[1] + dy) in pixels] for p in pixels}
    nodes = {p for p, n in nbrs.items() if len(n) != 2}
    seen_edges = set()
    paths: List[List[Point]] = []

    def walk(start: Tuple[int, int], first: Tuple[int, int]) -> List[Tuple[int, int]]:
        path = [start, first]
        prev, cur = start, first
        while cur not in nodes:
            nxt = [q for q in nbrs[cur] if q != prev and q not in path[-3:]]
            if not nxt:
                break
            prev, cur = cur, min(nxt, key=lambda q: abs(q[0] - cur[0]) + abs(q[1] - cur[1]))
            path.append(cur)
            if len(path) > len(pixels) + 2:
                break
        return path

    for n in sorted(nodes):
        for first in nbrs[n]:
            key = (n, first)
            if key in seen_edges:
                continue
            path = walk(n, first)
            seen_edges.add((path[0], path[1]))
            seen_edges.add((path[-1], path[-2]))
            if len(path) >= 4:
                paths.append([(float(x), float(y)) for x, y in path])
    if not paths and pixels:  # a closed loop with no endpoint
        start = min(pixels)
        paths.append([(float(x), float(y)) for x, y in walk(start, nbrs[start][0])])
    return paths


def trace(png: Path, *, waypoints: Optional[Path] = None, threshold: int = 140, epsilon: float = 0.55,
          smooth: int = 2) -> dict:
    """Skeletonise a handwriting PNG (alpha or dark ink) into strokes. Extra ``[sig]`` required."""
    try:
        import numpy as np  # type: ignore
        from PIL import Image  # type: ignore
        from skimage.morphology import skeletonize  # type: ignore
    except ImportError as exc:
        raise VisualsError(f"tracing a PNG needs the [sig] extra (pillow, numpy, scikit-image): uv pip install "
                           f"pillow numpy scikit-image ({exc}). A typed signature needs only fonttools.")
    src = Path(png)
    if not src.is_file():
        raise VisualsError(f"signature image not found: {src}")
    im = Image.open(src)
    arr = np.array(im.convert("RGBA"))
    alpha = arr[..., 3]
    mask = alpha > threshold if alpha.min() < 250 else np.array(im.convert("L")) < 128
    if mask.sum() < 20:
        raise VisualsError("no ink found in the signature image (expects ink as alpha or dark strokes on light)")
    skel = skeletonize(mask)
    width = float(mask.sum()) / max(1.0, float(skel.sum()))
    if waypoints:
        strokes_px = _waypoint_strokes(mask, Path(waypoints))
    else:
        raw = _walk_skeleton(skel)
        raw.sort(key=lambda p: (min(q[0] for q in p), min(q[1] for q in p)))  # left to right: the writing order
        strokes_px = [(f"s{i + 1}", p) for i, p in enumerate(raw)]
    out: List[Tuple[str, str, float]] = []
    for sid, pts in strokes_px:
        pts = _simplify(_smooth(pts, smooth), epsilon)
        if len(pts) >= 2:
            out.append((sid, bezier_path(pts), max(2.0, width)))
    if not out:
        raise VisualsError("tracing produced no strokes")
    data = _pack(out)
    data["mode"] = "trace"
    return data


def _waypoint_strokes(mask, path: Path) -> List[Tuple[str, List[Point]]]:
    """Snap hand-picked waypoints per stroke onto the ink centre-line (distance-transform shortest path)."""
    try:
        import numpy as np  # type: ignore
        from scipy import ndimage as ndi  # type: ignore
        from skimage.graph import route_through_array  # type: ignore
    except ImportError as exc:
        raise VisualsError(f"waypoints need scipy and scikit-image: uv pip install scipy scikit-image ({exc})")
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise VisualsError(f"waypoints file unreadable: {exc}")
    dt = ndi.distance_transform_edt(mask)
    cost = np.where(mask, 1.0 / (dt + 0.3) ** 3, 1e6)
    h, w = mask.shape
    out = []
    for item in spec:
        sid = item["id"] if isinstance(item, dict) else item[0]
        wps = item["points"] if isinstance(item, dict) else item[1]
        snapped = []
        for x, y in wps:
            best = None
            for yy in range(max(0, int(y) - 10), min(h, int(y) + 11)):
                for xx in range(max(0, int(x) - 10), min(w, int(x) + 11)):
                    if mask[yy, xx]:
                        d = (xx - x) ** 2 + (yy - y) ** 2 - 25 * dt[yy, xx]
                        if best is None or d < best[0]:
                            best = (d, xx, yy)
            if best is None:
                raise VisualsError(f"waypoint ({x}, {y}) of stroke {sid} is not near any ink")
            snapped.append((best[1], best[2]))
        pts: List[Point] = []
        for (x0, y0), (x1, y1) in zip(snapped, snapped[1:]):
            seg, _ = route_through_array(cost, (y0, x0), (y1, x1), fully_connected=True, geometric=True)
            xy = [(float(px), float(py)) for py, px in seg]
            pts += xy if not pts else xy[1:]
        out.append((sid, pts))
    return out


# ------------------------------------------------------------------ output

def to_js(data: dict) -> str:
    sig = {k: data[k] for k in ("viewBox", "strokes")}
    return ("/* GENERATED by profile-wrap (motion signature). Your own signature data; never commit it to a public repo. */\n"
            "window.__brand = window.__brand || {};\nwindow.__brand.identity = window.__brand.identity || {};\n"
            "window.__brand.identity.signature = " + json.dumps(sig, separators=(",", ":")) + ";\n")


def write(workspace: Path, data: dict) -> Path:
    return atomic.atomic_write_text(Path(workspace) / SIG_REL, to_js(data))
