"""Narrated video styles: scaffold with --style, the MP4 lane, the probe rule, the gate and the CLI error."""
from __future__ import annotations

import json
import os
import re
import shutil
import struct
import wave
import zlib
import subprocess
import sys

import pytest

from conftest import REPO, load_cfg, need_gif_stack
from profile_wrap.visuals import VisualsError, assets, browser, gif, probe, proc, sfx, theme
from profile_wrap.visuals import render as render_mod

STYLES = ("console-stage",)


def _draft(ws, slug):
    d = ws / "drafts" / slug
    d.mkdir(parents=True, exist_ok=True)          # new-gif now writes drafts/<slug>/meta.json itself
    (d / "meta.json").write_text(json.dumps({
        "slug": slug, "lang": "en", "format": "video", "status": "draft", "claims": [],
        "video_project": f"videos/{slug}", "assets": [f"{slug}.mp4"]}), encoding="utf-8")
    return d


def _cli(*argv):
    env = dict(os.environ, PYTHONPATH=str(REPO), PYTHONUTF8="1")
    return subprocess.run([sys.executable, "-m", "profile_wrap", *argv], capture_output=True, text=True, env=env,
                          cwd=str(REPO), timeout=60)


def test_styles_are_discovered_from_the_kit():
    assert set(STYLES) <= set(gif.list_styles())


@pytest.mark.parametrize("style", STYLES)
def test_new_gif_scaffolds_a_style(ws, style):
    project = gif.new_gif("demo", ws, load_cfg(ws), style=style)
    assert gif.project_style(project) == style
    html = (project / "index.html").read_text(encoding="utf-8")
    assert "{{slug}}" not in html and 'data-composition-id="demo"' in html
    pkg = json.loads((project / "package.json").read_text(encoding="utf-8"))
    assert pkg["name"] == "demo" and "{{" not in json.dumps(pkg)          # same pins as gif-project, filled
    assert pkg["dependencies"]["hyperframes"] == assets.npm_pin("hyperframes")
    assert (project / "motion" / "brand.js").is_file()                    # the shared motion sync still ran


def test_console_stage_length_has_one_source_of_truth(ws):
    html = (gif.new_gif("len", ws, load_cfg(ws), style="console-stage") / "index.html").read_text(encoding="utf-8")
    assert 'data-duration="' in html and "D = Number(document.getElementById(\"stage\").getAttribute(\"data-duration\"))" in html
    assert "D = 12" not in html and ".tl.miss" in html and ".ic svg" in html     # the demo post needed all three


def test_plain_new_gif_has_no_style(ws):
    project = gif.new_gif("plain", ws, load_cfg(ws))
    assert gif.project_style(project) == ""
    assert not (project / gif.STYLE_MARKER).exists()


def test_default_style_comes_from_config_and_is_empty_by_default(ws):
    cfg = load_cfg(ws)
    assert cfg["visuals"]["default_style"] == ""
    cfg["visuals"]["default_style"] = "console-stage"
    assert gif.project_style(gif.new_gif("viacfg", ws, cfg)) == "console-stage"


def test_unknown_style_names_the_known_ones(ws):
    with pytest.raises(VisualsError) as e:
        gif.new_gif("x", ws, load_cfg(ws), style="nope")
    assert "unknown style 'nope'" in str(e.value) and "console-stage" in str(e.value)
    assert "caption-reel" not in str(e.value)
    assert not (ws / "videos" / "x").exists()


def test_cli_style_flag(ws):
    bad = _cli("new-gif", "x", "--style", "nope", "--workspace", str(ws))
    assert bad.returncode == 1 and "console-stage" in bad.stderr and "caption-reel" not in bad.stderr
    ok = _cli("new-gif", "y", "--style", "console-stage", "--workspace", str(ws))
    assert ok.returncode == 0 and (ws / "videos" / "y" / "index.html").is_file()


def test_style_probe_rule_needs_a_real_duration():
    assert probe.style_problems({"duration": 10.0, "chunks": 4}) == []          # known-true sample
    assert probe.style_problems({}) and probe.style_problems({"duration": 0})   # a probe that did not look fails
    assert probe.style_problems({"duration": 5, "problems": ["x"]}) == ["style probe: x"]
    assert probe.problems({"duration": 10.0})                                   # the GIF rule still needs plan/poster


class FakeProbe:
    def __init__(self, ok=True):
        self.ok = ok

    def __call__(self, cmd, **kw):
        if not self.ok:
            return proc.Result(1, "", "Invalid data found")
        return proc.Result(0, json.dumps({"streams": [{"codec_name": "h264", "width": 1280, "height": 720,
                                                       "r_frame_rate": "30/1"}], "format": {"duration": "10.0"}}), "")


def test_deliver_video_swaps_atomically_and_leaves_nothing(tmp_path, monkeypatch):
    monkeypatch.setattr(gif.shutil, "which", lambda n: f"/bin/{n}")
    src, out = tmp_path / "v.mp4", tmp_path / "out" / "d.mp4"
    src.write_bytes(b"mp4data")
    info = gif.deliver_video(src, out, FakeProbe())
    assert out.read_bytes() == b"mp4data" and (info["w"], info["h"], info["duration_s"]) == (1280, 720, 10.0)
    out.write_bytes(b"old")
    with pytest.raises(VisualsError, match="does not decode"):
        gif.deliver_video(src, out, FakeProbe(ok=False))
    assert out.read_bytes() == b"old" and [p.name for p in out.parent.iterdir()] == ["d.mp4"]


def _fake_stack(ws, monkeypatch, probe_result):
    monkeypatch.setattr(gif.shutil, "which", lambda n: f"/bin/{n}")
    monkeypatch.setattr(assets, "require_node", lambda: None)
    monkeypatch.setattr(browser, "require", lambda *a, **k: browser.Browser(path=ws / "chrome", source="fake"))
    monkeypatch.setattr(gif, "prepare_project", lambda *a, **k: {"families": ["F"], "gsap": None, "motion_copied": []})
    monkeypatch.setattr(probe, "run_probe", lambda *a, **k: probe_result)
    monkeypatch.setattr(gif, "versions", lambda chrome=None: {"hyperframes": "x"})


def test_render_dispatch_delivers_mp4_and_records_the_style(ws, monkeypatch):
    """render.render -> render_gif with the slow parts faked: the MP4 lane runs, the GIF encoder never does."""
    cfg = load_cfg(ws)
    gif.new_gif("demo", ws, cfg, style="console-stage")
    _draft(ws, "demo")
    _fake_stack(ws, monkeypatch, {"duration": 10.0})
    monkeypatch.setattr(gif, "hyperframes_steps", lambda project, mp4, chrome, **kw: mp4.write_bytes(b"mp4data"))
    monkeypatch.setattr(gif, "encode_with_trim", lambda *a, **k: pytest.fail("a style video must not be GIF-encoded"))
    data = render_mod.render("demo", ws, cfg, runner=FakeProbe())
    assert data["format"] == "video" and data["style"] == "console-stage" and data["asset"] == "demo.mp4"
    assert data["canvas"] == {"w": 1280, "h": 720} and data["video"]["duration_s"] == 10.0
    out = ws / "drafts" / "demo" / "out"
    assert (out / "demo.mp4").read_bytes() == b"mp4data"
    assert json.loads((out / "render.json").read_text(encoding="utf-8"))["style"] == "console-stage"


def test_render_stops_when_the_style_probe_found_nothing(ws, monkeypatch):
    cfg = load_cfg(ws)
    gif.new_gif("demo", ws, cfg, style="console-stage")
    _draft(ws, "demo")
    _fake_stack(ws, monkeypatch, {})
    with pytest.raises(VisualsError, match="did not boot"):
        gif.render_gif("demo", ws, cfg)


def test_video_is_a_known_format_and_the_gate_decodes_the_mp4(tmp_path):
    from profile_wrap import policy
    from profile_wrap.gate import render as gate_render
    assert "video" in policy.FORMATS
    mp4 = tmp_path / "d.mp4"
    mp4.write_bytes(b"x")
    cfg = {"gate": {"tools_missing": "fail"}}
    good = gate_render.RenderChecker(tmp_path, tmp_path, {}, cfg, which=lambda n: n, runner=lambda c: (0, "10.0\n", ""))
    good._video(mp4)
    assert good.findings == []
    bad = gate_render.RenderChecker(tmp_path, tmp_path, {}, cfg, which=lambda n: n,
                                    runner=lambda c: (1, "", "Invalid data"))
    bad._video(mp4)
    assert bad.findings and "does not decode" in json.dumps(bad.findings)


def test_real_style_render_to_mp4(stack_ws):
    """The real stack: scaffold console-stage, render once, an MP4 appears and decodes. Skips without the stack."""
    need_gif_stack()
    ws, cfg = stack_ws, load_cfg(stack_ws)
    draft = _draft(ws, "real")
    gif.new_gif("real", ws, cfg, style="console-stage")
    data = gif.render_gif("real", ws, cfg)
    assert data["format"] == "video" and (draft / "out" / "real.mp4").stat().st_size > 0
    assert data["video"]["w"] == 1280 and data["video"]["h"] == 720 and data["video"]["duration_s"] > 5


# ------------------------------------------------------------------ theme from the subject, meta.json, VFX and SFX slots

def _png(path, rows):
    """A tiny RGB PNG from rows of (r, g, b) triples, written with the standard library."""
    h, w = len(rows), len(rows[0])
    raw = b"".join(b"\x00" + b"".join(bytes(px) for px in row) for row in rows)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


def _logo(path, colour, base=(235, 235, 235)):
    rows = [[colour if 8 <= x < 24 and 8 <= y < 24 else base for x in range(32)] for y in range(32)]
    _png(path, rows)


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
KIT = REPO / "brand-kit" / "templates" / "styles" / "console-stage"


def test_template_holds_no_colour_of_its_own():
    """The old fixed navy/ember/orange palette is gone: every colour in the template is a theme variable."""
    html = (KIT / "index.html").read_text(encoding="utf-8")
    assert not re.findall(r"#[0-9a-fA-F]{6}\b", html) and "ff6200" not in html.lower() and "navy" not in html.lower()
    assert "./theme.css" in html and "{{canvas.w}}" in html and 'id="motif"' in html and "PWFX(" in html


def test_default_theme_is_the_shipped_theme_json_and_passes_contrast():
    shipped = json.loads((KIT / "theme.json").read_text(encoding="utf-8"))
    assert shipped == theme.default_theme()
    assert theme.check(shipped)["failures"] == [] and theme.check(shipped)["pairs"] >= 20


def test_contrast_maths_matches_wcag():
    assert round(theme.contrast("#000000", "#ffffff"), 2) == 21.0
    assert theme.contrast("#777777", "#777777") == 1.0


@needs_ffmpeg
@pytest.mark.parametrize("colour", [(220, 30, 40), (30, 200, 60), (40, 90, 230), (230, 190, 20)])
def test_theme_follows_the_subjects_colour_and_passes_contrast(tmp_path, colour):
    import colorsys
    img = tmp_path / "logo.png"
    _logo(img, colour)
    t = theme.derive(img)
    assert theme.check(t)["failures"] == []
    want = colorsys.rgb_to_hsv(*(c / 255 for c in colour))[0]
    got = colorsys.rgb_to_hsv(*(c / 255 for c in theme.hex_to_rgb(t["palette"]["accent"])))[0]
    assert min(abs(want - got), 1 - abs(want - got)) < 0.06          # the accent keeps the subject's hue
    other = tmp_path / "other.png"
    _logo(other, (30, 200, 60) if colour != (30, 200, 60) else (220, 30, 40))
    assert theme.derive(other)["palette"]["accent"] != t["palette"]["accent"]      # a different subject gives a different look


@needs_ffmpeg
def test_theme_refuses_an_image_with_no_colour(tmp_path):
    img = tmp_path / "grey.png"
    _png(img, [[(128, 128, 128)] * 8 for _ in range(8)])
    with pytest.raises(VisualsError, match="no colour"):
        theme.derive(img)
    with pytest.raises(VisualsError, match="not found"):
        theme.derive(tmp_path / "missing.png")


@needs_ffmpeg
def test_new_gif_scaffolds_theme_canvas_and_meta_json(ws, tmp_path):
    img = tmp_path / "logo.png"
    _logo(img, (230, 120, 20))
    project = gif.new_gif("themed", ws, load_cfg(ws), style="console-stage", theme_from=img, canvas="1080x1350",
                          subject="a thing", motif="orbit")
    t = json.loads((project / "theme.json").read_text(encoding="utf-8"))
    assert t["canvas"] == {"w": 1080, "h": 1350} and t["subject"] == "a thing" and t["motif"] == "orbit"
    css = (project / "theme.css").read_text(encoding="utf-8")
    assert "--w: 1080px; --h: 1350px;" in css and f"--c-accent: {t['palette']['accent']};" in css
    html = (project / "index.html").read_text(encoding="utf-8")
    assert 'data-width="1080" data-height="1350"' in html and "{{canvas" not in html
    meta = json.loads((ws / "drafts" / "themed" / "meta.json").read_text(encoding="utf-8"))
    assert meta["video_project"] == "videos/themed" and meta["format"] == "video" and meta["assets"] == ["themed.mp4"]
    assert (project / "sfx" / "click.wav").is_file() and (project / "fx.js").is_file()


def test_new_gif_writes_meta_json_and_keeps_an_existing_one(ws):
    gif.new_gif("m1", ws, load_cfg(ws), style="console-stage")
    meta_path = ws / "drafts" / "m1" / "meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    assert meta["slug"] == "m1" and meta["video_project"] == "videos/m1" and meta["status"] == "draft"
    meta_path.write_text(json.dumps({**meta, "status": "queued"}), encoding="utf-8")
    assert gif.write_meta(ws, "m1", "en", "video", "m1.mp4") is None                  # without force a draft is never touched
    assert json.loads(meta_path.read_text(encoding="utf-8"))["status"] == "queued"
    gif.new_gif("m1", ws, load_cfg(ws), style="console-stage", force=True)
    assert json.loads(meta_path.read_text(encoding="utf-8"))["status"] == "draft"      # force rewrites it
    gif.new_gif("m2", ws, load_cfg(ws))
    assert json.loads((ws / "drafts" / "m2" / "meta.json").read_text(encoding="utf-8"))["format"] == "gif"


def test_theme_flags_need_a_style_and_exclude_each_other(ws, tmp_path):
    with pytest.raises(VisualsError, match="apply to a video style"):
        gif.new_gif("p", ws, load_cfg(ws), canvas="1080x1350")
    with pytest.raises(VisualsError, match="not both"):
        gif.new_gif("p", ws, load_cfg(ws), style="console-stage", theme_from=tmp_path / "a.png", theme_file=tmp_path / "b.json")
    with pytest.raises(VisualsError, match="WxH"):
        theme.parse_canvas("wide")


def test_theme_that_fails_contrast_is_refused(ws, tmp_path):
    t = theme.default_theme()
    t["palette"]["muted"] = t["palette"]["bg"]
    f = tmp_path / "bad.json"
    f.write_text(json.dumps(t), encoding="utf-8")
    with pytest.raises(VisualsError, match="fails contrast"):
        gif.new_gif("bad", ws, load_cfg(ws), style="console-stage", theme_file=f)


def test_cli_theme_command_and_new_gif_flags(ws, tmp_path):
    if shutil.which("ffmpeg") is None:
        pytest.skip("ffmpeg not installed")
    img, out = tmp_path / "logo.png", tmp_path / "t" / "theme.json"
    _logo(img, (30, 160, 220))
    r = _cli("visuals", "theme", "--from", str(img), "--out", str(out), "--workspace", str(ws))
    assert r.returncode == 0 and "0 failure(s)" in r.stdout and json.loads(out.read_text(encoding="utf-8"))["palette"]["accent"]
    ok = _cli("new-gif", "viacli", "--style", "console-stage", "--theme", str(out), "--canvas", "1080x1350", "--workspace", str(ws))
    assert ok.returncode == 0 and (ws / "videos" / "viacli" / "theme.css").is_file() and (ws / "drafts" / "viacli" / "meta.json").is_file()


def test_fx_kit_is_deterministic_and_clean():
    js = (KIT / "fx.js").read_text(encoding="utf-8")
    code = re.sub(r"/\*.*?\*/", "", js, flags=re.S)
    assert "Math.random" not in code and "Date.now" not in code and "performance.now" not in code and "repeat: -1" not in code
    for name in ("ripple", "burst", "bubbles", "pulse", "shine", "shake", "count", "sparkles", "drain", "cue"):
        assert f"fx.{name} =" in js


def test_cues_are_validated():
    assert sfx.clean_cues([{"role": "click", "t": 1}, {"role": "tick", "t": 0.5, "db": -3}])[0]["role"] == "tick"
    for bad in ({"role": "Click", "t": 1}, {"role": "click", "t": -1}, {"role": "click"}, {"role": "x y", "t": 1}):
        with pytest.raises(VisualsError):
            sfx.clean_cues([bad])


def _tone(path, hz=440, secs=0.1):
    import math
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(44100)
        w.writeframes(b"".join(struct.pack("<h", int(12000 * math.sin(2 * math.pi * hz * i / 44100))) for i in range(int(44100 * secs))))


@needs_ffmpeg
def test_sfx_mix_places_each_cue_on_its_time_and_masters_the_level(tmp_path):
    """Sync: the sound starts on the cue sample. Level: the master lands near the target loudness under the ceiling."""
    kit = tmp_path / "project" / "sfx"
    kit.mkdir(parents=True)
    _tone(kit / "click.wav")
    cues = [{"role": "click", "t": 1.0}, {"role": "click", "t": 2.5, "db": -6}]
    buf = sfx.mix_cues(sfx.clean_cues(cues), 4.0, kit)
    first = next(i for i, v in enumerate(buf) if abs(v) > 100)
    assert abs(first / sfx.SR - 1.0) < 0.005                                        # onset on the cue
    second = next(i for i, v in enumerate(buf) if i > 1.5 * sfx.SR and abs(v) > 100)
    assert abs(second / sfx.SR - 2.5) < 0.005
    assert max(abs(v) for v in buf[int(2.5 * sfx.SR):int(2.6 * sfx.SR)]) < 0.6 * max(abs(v) for v in buf[:int(1.2 * sfx.SR)])
    info = sfx.build(tmp_path / "project", {"duration": 4.0, "sfx": cues})
    assert info["cues"] == 2 and info["roles"] == ["click"] and abs(info["master"]["lufs"] - sfx.TARGET_LUFS) < 1.5
    assert info["master"]["true_peak_dbtp"] <= 0.0
    assert (tmp_path / "project" / "assets" / "sfx-mix.wav").is_file() and not (tmp_path / "project" / "assets" / "sfx-premix.wav").exists()


def test_sfx_build_is_skipped_without_cues_and_a_missing_role_is_named(tmp_path):
    assert sfx.build(tmp_path, {"duration": 3.0}) is None and sfx.build(tmp_path, {"duration": 3.0, "sfx": []}) is None
    (tmp_path / "sfx").mkdir()
    with pytest.raises(VisualsError, match="role 'whoosh' has no file"):
        sfx.mix_cues(sfx.clean_cues([{"role": "whoosh", "t": 0.1}]), 1.0, tmp_path / "sfx")


@needs_ffmpeg
def test_shipped_kit_covers_the_roles_the_template_cues(ws):
    project = gif.new_gif("kit", ws, load_cfg(ws), style="console-stage")
    code = (project / "index.html").read_text(encoding="utf-8") + (project / "fx.js").read_text(encoding="utf-8")
    used = set(re.findall(r'cue\("([a-z]+)"', code)) | set(re.findall(r'p\.sound \|\| "([a-z]+)"', code))
    assert {"whoosh", "key", "click", "tick", "thump", "splash", "sparkle", "pop"} <= used
    for role in used:
        f = project / "sfx" / f"{role}.wav"
        assert f.is_file() and len(sfx.load_mono(f)) > 500, role


def test_render_runs_the_sfx_build_from_the_probe(ws, monkeypatch):
    cfg = load_cfg(ws)
    gif.new_gif("snd", ws, cfg, style="console-stage")
    _draft(ws, "snd")
    cues = [{"role": "click", "t": 0.5, "db": 0}]
    _fake_stack(ws, monkeypatch, {"duration": 10.0, "sfx": cues})
    seen = {}
    monkeypatch.setattr(sfx, "build", lambda project, result, **kw: seen.update(result=result) or {"cues": 1, "roles": ["click"]})
    monkeypatch.setattr(sfx, "loudness", lambda p, runner=None: {"lufs": -16.0, "true_peak_dbtp": -2.0, "lra": 1.0})
    monkeypatch.setattr(gif, "hyperframes_steps", lambda project, mp4, chrome, **kw: mp4.write_bytes(b"mp4data"))
    data = render_mod.render("snd", ws, cfg, runner=FakeProbe())
    assert seen["result"]["sfx"] == cues and data["sfx"]["cues"] == 1 and data["audio"]["lufs"] == -16.0


def test_sound_kit_is_generated_at_scaffold_and_is_deterministic(ws):
    """No audio binary lives in the template (the leak scan allows none): new-gif computes the kit from make_sfx.py, byte for byte the same each time."""
    assert not list((KIT / "sfx").glob("*.wav"))
    a = gif.new_gif("k1", ws, load_cfg(ws), style="console-stage")
    b = gif.new_gif("k2", ws, load_cfg(ws), style="console-stage")
    roles = sorted(p.stem for p in (a / "sfx").glob("*.wav"))
    assert roles == ["click", "key", "pop", "sparkle", "splash", "thump", "tick", "whoosh"]
    assert all((a / "sfx" / f"{r}.wav").read_bytes() == (b / "sfx" / f"{r}.wav").read_bytes() for r in roles)
