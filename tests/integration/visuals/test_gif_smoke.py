"""Smoke render of the shipped GIF template: 250 frames, size, still share, seam, poster, fonts, no temp files."""
from __future__ import annotations

import json

import pytest

from conftest import load_cfg, need_gif_stack



def _draft(ws, slug):
    d = ws / "drafts" / slug
    d.mkdir(parents=True)
    (d / "meta.json").write_text(json.dumps({
        "slug": slug, "lang": "en", "format": "gif", "pillar": "demo", "status": "draft", "claims": [],
        "video_project": f"videos/{slug}", "assets": [f"{slug}.gif"]}), encoding="utf-8")
    return d


def test_template_renders_to_a_gate_clean_gif(stack_ws):
    need_gif_stack()
    from profile_wrap.visuals import gif, metrics
    ws, cfg = stack_ws, load_cfg(stack_ws)
    draft = _draft(ws, "smoke")
    gif.new_gif("smoke", ws, cfg, title="Smoke")
    data = gif.render_gif("smoke", ws, cfg)

    out = draft / "out"
    assert data["gif"]["frames"] == 250
    assert data["canvas"] == {"w": 1080, "h": 1350}
    assert data["fonts"] == ["IBM Plex Sans", "IBM Plex Sans Arabic"]
    assert data["versions"]["hyperframes"]
    assert (out / "smoke.gif").stat().st_size <= cfg["gate"]["gif"]["max_mb"] * 1024 * 1024
    leftovers = [p.name for p in out.iterdir() if p.name.startswith("pal") or p.name.endswith(".tmp.gif")]
    assert leftovers == []

    rep = metrics.run_for_slug("smoke", ws, cfg)
    assert rep.frames == 250
    assert rep.still["still_pct"] <= cfg["gate"]["gif"]["max_still_pct"]
    assert rep.seam <= metrics.SEAM_LIMIT
    assert rep.poster >= metrics.POSTER_MIN          # poster frame 0 is not blank or masked
    assert rep.flash["per_loop"] <= 1 and not rep.flash["red"]
    assert rep.contrast["failures"] == 0
    assert rep.ok, rep.problems
    assert json.loads((out / "metrics.json").read_text(encoding="utf-8"))["ok"] is True


def test_missing_font_fails_before_any_render(ws):
    """Negative test: no fonts installed means the render stops with a clear error, never a fallback face."""
    from profile_wrap.visuals import fonts, gif
    cfg = load_cfg(ws)
    plan = fonts.resolve(cfg, ws)
    assert not plan.ok
    with pytest.raises(fonts.FontError, match="profile-wrap fonts fetch"):
        fonts.require(plan)
    _draft(ws, "nofont")
    gif.new_gif("nofont", ws, cfg)
    with pytest.raises(fonts.FontError):
        gif.prepare_project(ws / "videos" / "nofont", ws, cfg, need_gsap=False)
