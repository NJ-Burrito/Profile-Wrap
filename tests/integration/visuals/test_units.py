"""Fast tests: fonts, browser discovery, process tree kill, atomic GIF output, metrics maths, icons, rollback, leak scan."""
from __future__ import annotations

import io
import json
import os
import re
import subprocess
import sys
import tarfile
import textwrap
import time
from pathlib import Path

import pytest

from conftest import REPO, load_cfg, new_workspace
from profile_wrap.visuals import VisualsError, browser, fonts, gif, icons, metrics, motion_upgrade, proc, signature_trace


# ------------------------------------------------------------------ fonts

def _fake_tgz(path: Path, members: dict) -> Path:
    with tarfile.open(path, "w:gz") as tar:
        for name, data in members.items():
            info = tarfile.TarInfo("package/" + name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return path


def test_fetch_installs_ofl_files_and_licences(ws):
    cfg = load_cfg(ws)
    cat = fonts.catalog()["families"]

    def packer(spec, dest):
        name = spec.rsplit("@", 1)[0]
        entry = next(e for e in cat.values() if e["package"] == name)
        files = {f"files/{entry['slug']}-{entry['subset']}-{w}-normal.woff2": b"wOF2" + str(w).encode()
                 for w in entry["weights"]}
        files["LICENSE"] = b"OFL"
        return _fake_tgz(dest / "x.tgz", files)

    out = fonts.fetch(ws, cfg, packer=packer)
    assert len(out["files"]) == 8
    plan = fonts.resolve(cfg, ws)
    assert plan.ok and plan.family_names == ["IBM Plex Sans", "IBM Plex Sans Arabic"]
    css = fonts.fonts_css(plan)
    assert "@font-face" in css and "--brand-arabic" in css and "base64," in css


def test_user_files_are_used_in_place_never_copied(ws, tmp_path):
    f = tmp_path / "MyFont-Bold.ttf"
    f.write_bytes(b"\0\1\0\0")
    cfg = load_cfg(ws)
    cfg["brand"]["font_source"] = "user_files"
    for role in ("display", "text", "arabic"):
        cfg["brand"]["fonts"][role] = {"family": "My Family", "files": [str(f)]}
    plan = fonts.resolve(cfg, ws)
    assert plan.ok and plan.faces[0].weight == 700 and plan.faces[0].path == f
    assert not any((ws / "brand" / "fonts").iterdir())
    with pytest.raises(fonts.FontError, match="only installs OFL"):
        fonts.fetch(ws, cfg, packer=lambda *a: None)
    assert fonts.required_font_substrings(cfg) == ["MyFamily", "MyFamily", "MyFamily"]


def test_missing_user_file_is_reported(ws, tmp_path):
    cfg = load_cfg(ws)
    cfg["brand"]["font_source"] = "user_files"
    cfg["brand"]["fonts"]["display"] = {"family": "Gone", "files": [str(tmp_path / "gone.woff2")]}
    plan = fonts.resolve(cfg, ws)
    assert not plan.ok and any("gone.woff2" in p for p in plan.problems)


# ------------------------------------------------------------------ browser

def test_discovery_order(tmp_path):
    a, b, c = (tmp_path / n for n in ("a", "b", "c"))
    for p in (a, b, c):
        p.write_text("x")
    cfg = {"render": {"chrome_path": str(a)}}
    env = {"PROFILE_WRAP_BROWSER": str(b), "HYPERFRAMES_BROWSER_PATH": str(c)}
    assert browser.discover(cfg, env, use_npx=False).source == "config render.chrome_path"
    assert browser.discover({}, env, use_npx=False).source == "PROFILE_WRAP_BROWSER"
    del env["PROFILE_WRAP_BROWSER"]
    assert browser.discover({}, env, use_npx=False).source == "HYPERFRAMES_BROWSER_PATH"
    del env["HYPERFRAMES_BROWSER_PATH"]
    seen = []

    def runner(cmd):
        seen.append(cmd)
        return 0, str(a) + "\n"

    got = browser.discover({}, env, use_npx=True, which=lambda n: "npx" if n == "npx" else None, runner=runner)
    assert got.source == "hyperframes browser path" and seen[0][-3:] == ["hyperframes", "browser", "path"] or seen[0][-2:] == ["browser", "path"]


def test_system_candidates_are_per_os():
    assert any("msedge" in p for p in browser.system_candidates({"PROGRAMFILES": "C:/P"}, "win32"))
    assert any(p.startswith("/Applications") for p in browser.system_candidates({}, "darwin"))
    assert "/usr/bin/chromium" in browser.system_candidates({}, "linux")


# ------------------------------------------------------------------ processes

def test_timeout_kills_the_whole_tree(tmp_path):
    beat = tmp_path / "beat.txt"
    child = tmp_path / "child.py"
    child.write_text(textwrap.dedent(f"""
        import time, pathlib
        p = pathlib.Path({str(beat)!r})
        while True:
            p.write_text(str(time.time())); time.sleep(0.1)
    """), encoding="utf-8")
    parent = tmp_path / "parent.py"
    parent.write_text(textwrap.dedent(f"""
        import subprocess, sys, time
        subprocess.Popen([sys.executable, {str(child)!r}])
        time.sleep(60)
    """), encoding="utf-8")
    res = proc.run([sys.executable, str(parent)], timeout=3)
    assert res.timed_out
    time.sleep(0.6)
    t1 = beat.read_text()
    time.sleep(1.0)
    assert beat.read_text() == t1, "the grandchild is still writing: the tree was not killed"


# ------------------------------------------------------------------ atomic GIF output

class FakeFfmpeg:
    """A runner that writes files like ffmpeg would, so the atomic logic is tested without ffmpeg."""

    def __init__(self, frames=10, fail_at=None):
        self.frames, self.fail_at = frames, fail_at

    def __call__(self, cmd, **kw):
        if Path(cmd[0]).name.startswith("ffprobe"):
            return proc.Result(0, f"{self.frames}\n", "")
        last = cmd[-1]
        if self.fail_at == "paletteuse" and last.endswith(".tmp.gif"):
            Path(last).write_bytes(b"GIF89a-partial")
            return proc.Result(1, "", "boom")
        Path(last).write_bytes(b"GIF89a" + b"x" * 100)
        return proc.Result(0, "", "")


@pytest.fixture()
def fake_tools(monkeypatch):
    monkeypatch.setattr(gif.shutil, "which", lambda n: f"/bin/{n}")


def test_encode_swaps_atomically_and_leaves_nothing(tmp_path, fake_tools):
    out = tmp_path / "o" / "a.gif"
    info = gif.encode_gif(tmp_path / "v.mp4", out, runner=FakeFfmpeg(frames=250))
    assert info["frames"] == 250 and out.is_file()
    assert sorted(p.name for p in out.parent.iterdir()) == ["a.gif"]


def test_failed_encode_keeps_the_old_gif_and_cleans_temp(tmp_path, fake_tools):
    out = tmp_path / "a.gif"
    out.write_bytes(b"OLD")
    with pytest.raises(VisualsError, match="paletteuse"):
        gif.encode_gif(tmp_path / "v.mp4", out, runner=FakeFfmpeg(fail_at="paletteuse"))
    assert out.read_bytes() == b"OLD"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["a.gif"]


def test_too_many_frames_is_refused_and_clean(tmp_path, fake_tools):
    out = tmp_path / "a.gif"
    with pytest.raises(VisualsError, match="251 frames"):
        gif.encode_gif(tmp_path / "v.mp4", out, runner=FakeFfmpeg(frames=251))
    assert list(tmp_path.iterdir()) == []


def test_trim_pass_lowers_fps_then_colours(tmp_path, fake_tools, monkeypatch):
    sizes = iter([60, 50, 30])  # MiB per attempt
    real = gif.encode_gif
    calls = []

    def fake_encode(mp4, out, **kw):
        info = real(mp4, out, **kw)
        info["bytes"] = next(sizes) * 2 ** 20
        calls.append((kw["fps"], kw["colors"]))
        return info

    monkeypatch.setattr(gif, "encode_gif", fake_encode)
    cfg = load_cfg(new_workspace(tmp_path))
    info = gif.encode_with_trim(tmp_path / "v.mp4", tmp_path / "o.gif", cfg, runner=FakeFfmpeg(frames=200))
    assert calls == [(25, 256), (20, 256), (20, 192)]
    assert info["trimmed"] is True and info["fps"] == 20 and info["colors"] == 192


# ------------------------------------------------------------------ metrics

def _frames(rows):
    """rows: list of (r, g, b); each frame is an 8x8 flat colour."""
    return metrics.Frames(8, 8, [bytes(c) * 64 for c in rows], [0.04] * len(rows))


def test_wcag_ratio_is_computed_not_typed():
    assert metrics.wcag_ratio("#000000", "#ffffff") == pytest.approx(21.0)
    assert metrics.wcag_ratio("#777777", "#777777") == pytest.approx(1.0)
    rep = metrics.contrast_report({"contrast_pairs": [["#000", "#fff", 7], ["#777", "#888", 4.5]]})
    assert rep["failures"] == 1 and rep["pairs"][0]["ok"]


def test_still_share_excludes_logged_holds():
    rows = [(0, 0, 0)] * 6 + [(200, 200, 200), (0, 0, 0), (200, 200, 200), (0, 0, 0)]
    fr = _frames(rows)
    full = metrics.still_share(fr)
    held = metrics.still_share(fr, holds=[(1, 5)])
    assert full["still_pct"] > 50
    assert held["held_frames"] == 5 and held["still_pct"] < full["still_pct"]


def test_flash_counter_seam_and_poster():
    flashy = _frames([(0, 0, 0), (255, 255, 255)] * 4)
    assert metrics.flashes(flashy)["max_per_second"] >= 3
    calm = _frames([(10, 10, 10)] * 5)
    assert metrics.flashes(calm)["per_loop"] == 0 and metrics.seam_diff(calm) == 0
    assert metrics.flashes(_frames([(0, 0, 0), (255, 0, 0), (0, 0, 0)]))["red"] is True
    assert metrics.poster_share(_frames([(9, 9, 9)])) == 0.0
    assert metrics.seam_diff(_frames([(0, 0, 0), (255, 255, 255)])) == pytest.approx(255, abs=1)


# ------------------------------------------------------------------ icons

def test_icon_add_with_licence(ws):
    svg = b'<svg class="lucide" viewBox="0 0 24 24"><path d="M1 1"/></svg>'

    def packer(spec, dest):
        assert spec.startswith("lucide-static@")
        return _fake_tgz(dest / "l.tgz", {"icons/zap.svg": svg, "LICENSE": b"ISC License"})

    out = icons.add("zap", ws, packer=packer)
    assert Path(out["path"]).read_bytes() == svg
    assert (ws / "brand" / "icons" / "LICENSE-lucide.txt").read_text() == "ISC License"
    assert icons.find("zap", ws) and icons.find("target", ws)          # workspace first, shipped subset second
    with pytest.raises(VisualsError, match="no icon named"):
        icons.add("nope", ws, packer=packer)
    with pytest.raises(VisualsError):
        icons.add("../evil", ws, packer=packer)


# ------------------------------------------------------------------ motion upgrade

def _upgrade_ws(tmp_path):
    ws = new_workspace(tmp_path)
    proj = ws / "videos" / "p1"
    (proj / "motion").mkdir(parents=True)
    (proj / "index.html").write_text("<html></html>", encoding="utf-8")
    for n in gif.MOTION_FILES:
        (proj / "motion" / n).write_text("OLD " + n, encoding="utf-8")
    d = ws / "drafts" / "p1"
    (d / "out").mkdir(parents=True)
    (d / "out" / "p1.gif").write_bytes(b"OLDGIF")
    (d / "out" / "render.json").write_text('{"old": true}', encoding="utf-8")
    (d / "gates.json").write_text('{"old": true}', encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({
        "slug": "p1", "status": "queued", "video_project": "videos/p1", "assets": ["p1.gif"],
        "scheduled_at": "2099-01-01T10:00:00+00:00"}), encoding="utf-8")
    return ws


def _snapshot(ws):
    return {p.relative_to(ws): p.read_bytes() for p in ws.rglob("*")
            if p.is_file() and "work" not in p.parts and "data" not in p.parts}


def test_upgrade_rolls_back_on_forced_failure(tmp_path):
    ws = _upgrade_ws(tmp_path)
    before = _snapshot(ws)

    def render(slug):
        (ws / "drafts" / slug / "out" / "p1.gif").write_bytes(b"NEWGIF")
        (ws / "drafts" / slug / "out" / "render.json").write_text('{"new": true}', encoding="utf-8")
        (ws / "videos" / "p1" / "renders").mkdir(exist_ok=True)
        (ws / "videos" / "p1" / "renders" / "video.mp4").write_bytes(b"new mp4")
        raise RuntimeError("forced render failure")

    steps = motion_upgrade.Steps(render, lambda s: (True, "ok"), lambda s: None)
    res = motion_upgrade.upgrade(ws, load_cfg(ws), steps=steps)
    assert res["failed"] == 1 and res["results"][0]["status"] == "FAILED" and res["results"][0]["restored"]
    assert _snapshot(ws) == before, "files differ after rollback"
    assert "FAILED" in (ws / "data" / "logs" / "motion-upgrade.log").read_text(encoding="utf-8")


def test_upgrade_rolls_back_when_the_gate_fails(tmp_path):
    ws = _upgrade_ws(tmp_path)

    def render(slug):
        (ws / "drafts" / slug / "out" / "p1.gif").write_bytes(b"NEWGIF")
        return {}

    steps = motion_upgrade.Steps(render, lambda s: (False, "FAIL caption"), lambda s: None)
    res = motion_upgrade.upgrade(ws, load_cfg(ws), steps=steps)
    assert res["results"][0]["reason"].startswith("gate:")
    assert (ws / "drafts" / "p1" / "out" / "p1.gif").read_bytes() == b"OLDGIF"
    assert (ws / "videos" / "p1" / "motion" / "core.js").read_text() == "OLD core.js"


def test_upgrade_selection_status_and_dry_run(tmp_path):
    ws = _upgrade_ws(tmp_path)
    assert [r["project"] for r in motion_upgrade.status(ws) if r["stale"]] == ["p1"]
    res = motion_upgrade.upgrade(ws, load_cfg(ws), dry_run=True)
    assert res["results"] == [{"slug": "p1", "status": "WOULD", "scheduled_at": "2099-01-01T10:00:00+00:00"}]
    meta = ws / "drafts" / "p1" / "meta.json"
    m = json.loads(meta.read_text())
    m["scheduled_at"] = "2000-01-01T10:00:00+00:00"          # too soon: not selected when queued-only
    meta.write_text(json.dumps(m))
    assert motion_upgrade.upgrade(ws, load_cfg(ws), dry_run=True)["total"] == 0
    (ws / "published").mkdir()
    (ws / "published" / "ledger.jsonl").write_text(json.dumps({"slug": "p1"}) + "\n")
    assert motion_upgrade.upgrade(ws, load_cfg(ws), queued_only=False, dry_run=True)["total"] == 0   # posted: untouched


# ------------------------------------------------------------------ signature (no scikit-image)

def _make_font(path: Path):
    from fontTools.fontBuilder import FontBuilder
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    names = [".notdef", "A", "b"]
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder(names)
    fb.setupCharacterMap({65: "A", 98: "b"})

    def box(x0, y0, x1, y1):
        pen = TTGlyphPen(None)
        pen.moveTo((x0, y0))
        pen.lineTo((x0, y1))
        pen.lineTo((x1, y1))
        pen.lineTo((x1, y0))
        pen.closePath()
        return pen.glyph()

    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.qCurveTo((300, 900), (500, 0))
    pen.closePath()
    fb.setupGlyf({".notdef": box(0, 0, 400, 700), "A": pen.glyph(), "b": box(80, 0, 420, 600)})
    fb.setupHorizontalMetrics({n: (600, 0) for n in names})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": "Test", "styleName": "Regular"})
    fb.setupOS2()
    fb.setupPost()
    fb.save(str(path))


def test_typed_signature_works_without_scikit_image(ws, tmp_path, monkeypatch):
    pytest.importorskip("fontTools")
    font = tmp_path / "t.ttf"
    _make_font(font)
    for mod in ("skimage", "skimage.morphology", "skimage.graph", "scipy", "numpy", "PIL"):
        monkeypatch.setitem(sys.modules, mod, None)      # importing any of them now raises ImportError
    data = signature_trace.typed("Ab", font)
    assert data["mode"] == "typed" and len(data["strokes"]) >= 2
    assert data["strokes"][-1][0] == "swash-main"
    x, y, w, h = data["viewBox"]
    assert w > 0 and h > 0 and all(s[1] > 0 and s[3].startswith("M") for s in data["strokes"])
    target = signature_trace.write(ws, data)
    assert target == ws / "brand" / "identity" / "signature.data.js"
    assert "window.__brand.identity.signature" in target.read_text(encoding="utf-8")
    with pytest.raises(VisualsError, match="scikit-image"):          # the traced mode names its missing extra
        signature_trace.trace(tmp_path / "x.png")


def test_typed_signature_names_the_missing_extra(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "fontTools", None)
    monkeypatch.setitem(sys.modules, "fontTools.ttLib", None)
    monkeypatch.setitem(sys.modules, "fontTools.pens", None)
    monkeypatch.setitem(sys.modules, "fontTools.pens.svgPathPen", None)
    with pytest.raises(VisualsError, match="fonttools"):
        signature_trace.typed("Ab", tmp_path / "x.ttf")


def test_svg_signature_and_path_length():
    svg = ('<svg viewBox="0 0 100 50" xmlns="http://www.w3.org/2000/svg"><path id="a" d="M0 0 L30 40" '
           'stroke-width="3"/><path d="M0 0 h10 v10"/></svg>')
    data = signature_trace.from_svg(svg)
    assert data["viewBox"] == [0, 0, 100, 50] and data["strokes"][0][1] == 50 and data["strokes"][1][1] == 20
    with pytest.raises(VisualsError):
        signature_trace.from_svg("<svg/>")


def test_trace_png_with_the_sig_extra(tmp_path):
    pytest.importorskip("skimage")
    from PIL import Image, ImageDraw
    im = Image.new("RGBA", (200, 80), (0, 0, 0, 0))
    ImageDraw.Draw(im).line([(10, 60), (60, 20), (110, 60), (180, 30)], fill=(0, 0, 0, 255), width=5)
    png = tmp_path / "sig.png"
    im.save(png)
    data = signature_trace.trace(png)
    assert data["mode"] == "trace" and data["strokes"] and data["strokes"][0][3].startswith("M")


# ------------------------------------------------------------------ the library files and the leak scan

KIT = REPO / "brand-kit"
# Private names are checked by `profile-wrap leaks scan` with the owner's salted denylist, never listed here.
_PRIVATE = []
FONT_NAMES = ["thman" + "yah", "cai" + "ro"]
BS = chr(92)
DRIVES = ["c" + ":" + BS + "users", "o" + ":" + BS]
FORBIDDEN = _PRIVATE + FONT_NAMES + DRIVES + ["linkedin.com/in/", "@gmail"]
BINARY_EXT = {".woff", ".woff2", ".ttf", ".otf", ".eot", ".jpg", ".jpeg", ".png", ".heic", ".webp", ".gif", ".mp4", ".pdf"}


def test_brand_kit_has_no_font_photo_or_personal_string():
    files = [p for p in KIT.rglob("*") if p.is_file()]
    assert len(files) > 50
    assert [p for p in files if p.suffix.lower() in BINARY_EXT] == []
    hits = []
    for p in files:
        text = p.read_text(encoding="utf-8", errors="replace")
        low = text.lower()
        hits += [f"{p.relative_to(REPO)}: {w}" for w in FORBIDDEN if w in low]
        if p.name != "objects.data.js" and re.search(r"(?<![\d.#-])\+?\d{3}[ -]\d{3,4}[ -]\d{4}(?!\d)", text):
            hits.append(f"{p.relative_to(REPO)}: phone-like number")
    assert hits == []


def test_shipped_visual_sources_are_clean():
    roots = [REPO / "profile_wrap" / "visuals", REPO / "data" / "fonts-ofl.json", REPO / "docs" / "MOTION.md",
             REPO / "docs" / "FONTS.md", REPO / "skills" / "pw-visuals"]
    files = []
    for r in roots:
        if r.is_file():
            files.append(r)
        elif r.is_dir():
            files += [p for p in r.rglob("*") if p.is_file() and "__pycache__" not in p.parts]
    assert len(files) > 10
    hits = []
    for p in files:
        low = p.read_text(encoding="utf-8", errors="replace").lower()
        for w in FORBIDDEN:
            if w in low and not (w == FONT_NAMES[0] and p.name == "FONTS.md"):
                hits.append(f"{p.relative_to(REPO)}: {w}")
    assert hits == []


def test_core_has_no_default_identity_and_identity_reads_brand():
    ident = (KIT / "motion" / "identity.js").read_text(encoding="utf-8")
    assert "window.__brand" in ident and "names nobody by default" in ident
    assert "ID_COPY" not in (KIT / "motion" / "core.js").read_text(encoding="utf-8")


def test_objects_pack_is_rebuilt_from_the_svgs():
    import shutil
    node = shutil.which("node")
    if not node:
        pytest.skip("node not installed")
    data = KIT / "motion" / "objects.data.js"
    before = data.read_bytes().replace(b"\r\n", b"\n")
    r = subprocess.run([node, str(KIT / "objects" / "build.mjs")], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "49 objects" in r.stdout
    assert data.read_bytes().replace(b"\r\n", b"\n") == before                         # the committed pack equals the pack built from the .svg files


# ------------------------------------------------------------------ CLI wiring (the real entry point)

def _cli(*argv, cwd=REPO):
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-m", "profile_wrap", *argv], capture_output=True, text=True, env=env,
                          cwd=str(cwd), timeout=60)


def test_cli_registers_every_visual_command():
    for argv in (["render", "-h"], ["new-gif", "-h"], ["visuals", "metrics", "-h"], ["visuals", "banner", "-h"],
                 ["fonts", "check", "-h"], ["icons", "add", "-h"], ["assets", "fetch", "-h"], ["motion", "status", "-h"],
                 ["motion", "upgrade", "-h"], ["motion", "signature", "trace", "-h"]):
        r = _cli(*argv)
        assert r.returncode == 0, (argv, r.stderr[-200:])


def test_cli_fonts_check_fails_without_fonts(ws):
    r = _cli("fonts", "check", "--workspace", str(ws))
    assert r.returncode == 1 and "NOT ready" in r.stdout
