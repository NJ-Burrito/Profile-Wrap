"""Render checks with injected tools (no real poppler or ffmpeg needed), plus real GIFs when Pillow exists."""
from __future__ import annotations

import json
import os
import time

import pytest
from gate_helpers import make_draft, write_config

from njli.gate import run_gate
from njli.gate.render import derived_fonts, run_tool

PDFFONTS_OK = """name                                 type              encoding         emb sub uni object ID
------------------------------------ ----------------- ---------------- --- --- --- ---------
ABCDEF+IBMPlexSans-Regular           CID TrueType      Identity-H       yes yes yes      5  0
"""
PDFFONTS_FALLBACK = PDFFONTS_OK + "XYZABC+ArialMT                       CID TrueType      Identity-H       yes yes yes      7  0\n"
PDFFONTS_T3 = PDFFONTS_OK.replace("CID TrueType     ", "Type 3           ")


def fake_which(tool):
    return f"/fake/{tool}"


def fake_runner(pdffonts=PDFFONTS_OK, pages="Pages:          2\n", frames="30\n", kept=30, probe_rc=0, probe_err=""):
    def run(cmd):
        tool = os.path.basename(cmd[0])
        if tool == "pdffonts":
            return 0, pdffonts, ""
        if tool == "pdfinfo":
            return 0, pages, ""
        if tool == "ffprobe":
            return probe_rc, frames, probe_err
        if tool == "ffmpeg":
            return 0, "", f"frame=  {kept} fps=0.0 q=-0.0 Lsize=N/A"
        return -1, "", "unknown"
    return run


def write_gif(path, lums, duration=40):
    from PIL import Image
    frames = [Image.new("L", (60, 75), int(v * 255)).convert("P") for v in lums]
    frames[0].save(path, save_all=True, append_images=frames[1:], duration=duration, loop=0, optimize=False)


def pdf_draft(ws, slides=2):
    d = make_draft(ws, "d1", "Plain.\n", fmt="slides", alt="alt\n", meta={"assets": ["deck.pdf"]},
                   slides="<html><body><p>hi</p></body></html>")
    (d / "out").mkdir(exist_ok=True)
    (d / "out" / "deck.pdf").write_bytes(b"%PDF fake")
    (d / "out" / "render.json").write_text(json.dumps({"slides": slides}), encoding="utf-8")
    return d


def gif_draft(ws, size=1000):
    d = make_draft(ws, "d1", "Plain.\n", fmt="gif", alt="alt\n", meta={"assets": ["d1.gif"]})
    (d / "out").mkdir(exist_ok=True)
    try:  # a valid, seamless GIF when Pillow exists, so the fake ffprobe/ffmpeg answers are the only variable
        import math
        write_gif(d / "out" / "d1.gif", [0.45 + 0.05 * math.sin(2 * math.pi * i / 30) for i in range(30)])
    except ImportError:
        (d / "out" / "d1.gif").write_bytes(b"GIF89a" + bytes(size))
    (d / "out" / "render.json").write_text("{}", encoding="utf-8")
    return d


def test_pdf_passes_with_brand_font_and_matching_pages(ws):
    write_config(ws, brand={"fonts": {"display": {"family": "IBM Plex Sans", "files": []}}})
    pdf_draft(ws)
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner())
    assert res["summary"] == "PASS", res["fails"]


def test_pdf_fallback_font_type3_and_page_mismatch_fail(ws):
    write_config(ws, gate={"required_font_substrings": ["IBMPlexSans"]})
    pdf_draft(ws)
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(pdffonts=PDFFONTS_FALLBACK))
    assert any("outside the brand fonts" in f and "ArialMT" in f for f in res["fails"])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(pdffonts=PDFFONTS_T3))
    assert any("Type 3" in f for f in res["fails"])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(pages="Pages:          5\n"))
    assert any("5 pages but 2 slides" in f for f in res["fails"])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(pages="garbage"))
    assert any("pdfinfo failed" in f for f in res["fails"])


def test_pdf_tool_failure_is_a_readable_fail(ws):
    pdf_draft(ws)

    def broken(cmd):
        return 1, "", "Syntax Error: bad xref"
    res = run_gate("d1", ws, which=fake_which, runner=broken)
    assert any("pdffonts failed" in f and "bad xref" in f for f in res["fails"])


def test_missing_asset_and_empty_assets_and_stale_render(ws):
    d = pdf_draft(ws)
    (d / "out" / "deck.pdf").unlink()
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner())
    assert any("missing asset out/deck.pdf" in f for f in res["fails"])
    make_draft(ws, "d2", "Plain.\n", fmt="slides", alt="alt\n", meta={"assets": []})
    assert any("meta.assets is empty" in f for f in run_gate("d2", ws, which=fake_which)["fails"])
    d = pdf_draft(ws)
    (d / "out" / "render.json").unlink()
    assert any("render.json is missing" in f for f in run_gate("d1", ws, which=fake_which, runner=fake_runner())["fails"])
    (d / "out" / "render.json").write_text("{bad", encoding="utf-8")
    assert any("render.json" in f for f in run_gate("d1", ws, which=fake_which, runner=fake_runner())["fails"])
    (d / "out" / "render.json").write_text(json.dumps({"slides": 2}), encoding="utf-8")
    old = time.time() - 1000
    os.utime(d / "out" / "render.json", (old, old))
    assert any("older than its source" in f for f in run_gate("d1", ws, which=fake_which, runner=fake_runner())["fails"])
    (d / "out" / "render.json").write_text(json.dumps({"slides": 0}), encoding="utf-8")
    os.utime(d / "out" / "render.json", None)
    assert any("0 slides" in f for f in run_gate("d1", ws, which=fake_which, runner=fake_runner())["fails"])


def test_video_project_source_makes_a_render_stale(ws):
    d = gif_draft(ws)
    vp = ws / "videos" / "d1"
    vp.mkdir(parents=True)
    (vp / "index.html").write_text("<html><body>hi</body></html>", encoding="utf-8")
    meta = json.loads((d / "meta.json").read_text(encoding="utf-8"))
    meta["video_project"] = "videos/d1"
    (d / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    old = time.time() - 1000
    os.utime(d / "out" / "render.json", (old, old))
    res = run_gate("d1", ws, which=lambda _t: None)
    assert any("older than its source" in f for f in res["fails"])


def test_gif_frame_count_size_and_decode(ws):
    gif_draft(ws)
    assert run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="250\n", kept=250))["summary"] == "PASS"
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="300\n"))
    assert any("300 frames (max 250)" in f for f in res["fails"])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="1\n"))
    assert any("1 frame(s)" in f for f in res["fails"])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(probe_rc=1, probe_err="Invalid data"))
    assert any("does not decode cleanly" in f for f in res["fails"])
    write_config(ws, gate={"gif": {"max_mb": 0.0001}})
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner())
    assert any("MB (max" in f for f in res["fails"])


def test_gif_still_frame_share(ws):
    gif_draft(ws)
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="100\n", kept=50))
    assert any("50.0% of frames are still" in f for f in res["fails"])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="100\n", kept=96))
    assert not any("still" in f for f in res["fails"])

    def no_ffmpeg_output(cmd):
        if os.path.basename(cmd[0]) == "ffmpeg":
            return 1, "", "Error opening input"
        return fake_runner(frames="100\n")(cmd)
    res = run_gate("d1", ws, which=fake_which, runner=no_ffmpeg_output)
    assert any("still-frame check could not run" in w for w in res["warnings"])


def test_gif_without_ffprobe_skips_or_fails_by_config(ws):
    gif_draft(ws)
    res = run_gate("d1", ws, which=lambda _t: None)
    assert res["summary"] == "PASS" and any("ffprobe not found" in w and "ffmpeg" in w for w in res["warnings"])
    write_config(ws, gate={"tools_missing": "fail"})
    assert run_gate("d1", ws, which=lambda _t: None)["summary"] == "FAIL"


def test_run_tool_never_raises(tmp_path):
    rc, out, err = run_tool(["definitely-not-a-real-tool-xyz"])
    assert rc == -1 and "could not start" in err
    import sys
    rc, out, err = run_tool([sys.executable, "-c", "import time; time.sleep(5)"], timeout=1)
    assert rc == -1 and "timed out" in err
    rc, out, err = run_tool([sys.executable, "-c", "print('hi')"])
    assert rc == 0 and out.strip() == "hi"


def test_derived_fonts():
    cfg = {"gate": {"required_font_substrings": []},
           "brand": {"fonts": {"display": {"family": "IBM Plex Sans"}, "arabic": {"family": "IBM Plex Sans Arabic"},
                               "text": "oops"}}}
    assert derived_fonts(cfg) == ["IBMPlexSans", "IBMPlexSansArabic"]
    assert derived_fonts({"gate": {"required_font_substrings": ["X"]}}) == ["X"]
    assert derived_fonts({"gate": {}}) == []


# ---- real GIF decoding with Pillow (seam and flashes)
PIL = pytest.importorskip("PIL.Image", reason="Pillow (media extra) not installed")


def real_gif_draft(ws, lums, duration=40):
    d = gif_draft(ws)
    write_gif(d / "out" / "d1.gif", lums, duration)
    return d


def test_loop_seam_passes_for_a_cycle_and_fails_for_a_ramp(ws):
    import math
    real_gif_draft(ws, [0.45 + 0.05 * math.sin(2 * math.pi * i / 30) for i in range(30)])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="30\n"))
    assert not any("seam" in f for f in res["fails"]), res["fails"]
    real_gif_draft(ws, [i / 29 for i in range(30)])
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="30\n"))
    assert any("loop seam jump" in f for f in res["fails"])


def test_flashing_gif_fails(ws):
    real_gif_draft(ws, [0.1, 0.9] * 15)
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="30\n"))
    assert any("flashes per second" in f for f in res["fails"])
    real_gif_draft(ws, [0.1] * 10 + [0.9] * 10 + [0.1] * 10)
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="30\n"))
    assert not any("flashes per second" in f for f in res["fails"])


def test_corrupt_gif_with_pillow(ws):
    d = gif_draft(ws)
    (d / "out" / "d1.gif").write_bytes(b"GIF89a-not-really")
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="30\n"))
    assert any("cannot read frames" in f for f in res["fails"])


def test_missing_pillow_is_a_skip_with_a_hint(ws, monkeypatch):
    import sys
    gif_draft(ws)
    monkeypatch.setitem(sys.modules, "PIL", None)
    res = run_gate("d1", ws, which=fake_which, runner=fake_runner(frames="30\n"))
    assert any("pillow" in w.lower() for w in res["warnings"])
