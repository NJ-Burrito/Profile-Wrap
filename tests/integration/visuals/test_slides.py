"""Static lane: Arabic RTL slides pass the overflow gates; a deliberate overflow, a tiny font and a missing family fail."""
from __future__ import annotations

import json

import pytest

from conftest import load_cfg, need_playwright, need_static_stack

AR = """<!doctype html><html lang="ar" dir="rtl"><head><meta charset="utf-8"><style>
@page{size:1080px 1350px;margin:0} *{margin:0;padding:0;box-sizing:border-box}
.slide{width:1080px;height:1350px;position:relative;overflow:hidden;padding:84px;display:flex;flex-direction:column;
 font-family:var(--brand-arabic);background:#f4f1ea;color:#17202b;page-break-after:always}
h1{font-size:120px;line-height:1.4;letter-spacing:0} p{font-size:44px;line-height:1.6} .grow{flex:1;display:flex;flex-direction:column;justify-content:center}
</style></head><body>
<section class="slide"><div class="grow"><h1>فكرة واحدة تقال مرة واحدة</h1><p>جملة قصيرة تستحق التمرير إلى الشريحة التالية.</p></div></section>
<section class="slide"><div class="grow"><h1>نقطة واحدة في كل شريحة</h1><p><i data-icon="target"></i> ثلاثة أسطر قصيرة بكلمات بسيطة.</p></div></section>
</body></html>"""


def _setup(stack_ws, slug, html, fmt="document"):
    d = stack_ws / "drafts" / slug
    d.mkdir(parents=True)
    (d / "slides.html").write_text(html, encoding="utf-8")
    (d / "meta.json").write_text(json.dumps({"slug": slug, "lang": "ar", "format": fmt, "pillar": "x",
                                             "status": "draft", "claims": [], "assets": [f"{slug}.pdf"]}),
                                 encoding="utf-8")
    return d


def test_arabic_rtl_slides_pass_overflow_gates(stack_ws):
    need_static_stack()
    need_playwright(stack_ws)
    from njli.visuals import render
    d = _setup(stack_ws, "ar", AR)
    data = render.render("ar", stack_ws, load_cfg(stack_ws))
    assert data["slides"] == 2 and data["scale"] == 2.0
    assert sorted(p.name for p in (d / "out").iterdir() if p.suffix == ".png") == ["slide-01.png", "slide-02.png"]
    assert (d / "out" / "ar.pdf").stat().st_size > 1000
    assert not [p for p in (d / "out").iterdir() if p.name.startswith(".render-")]
    png = (d / "out" / "slide-01.png").read_bytes()
    assert int.from_bytes(png[16:20], "big") == 2160 and int.from_bytes(png[20:24], "big") == 2700   # 2x


def test_overflow_and_small_text_fail(stack_ws):
    need_static_stack()
    need_playwright(stack_ws)
    from njli.visuals import VisualsError, render
    bad = AR.replace("<p>جملة قصيرة", '<p style="position:absolute;left:-200px;top:10px">جملة قصيرة')
    _setup(stack_ws, "ovf", bad)
    with pytest.raises(VisualsError, match="overflows"):
        render.render("ovf", stack_ws, load_cfg(stack_ws))
    small = AR.replace("p{font-size:44px", "p{font-size:20px")
    _setup(stack_ws, "small", small)
    with pytest.raises(VisualsError, match="below 28px"):
        render.render("small", stack_ws, load_cfg(stack_ws))
    leftovers = [p.name for p in (stack_ws / "drafts" / "ovf" / "out").iterdir()]
    assert leftovers == []                      # a failed render leaves no temp folder behind


def test_unloadable_system_family_fails(stack_ws):
    """font_source=system with a family nobody installed must fail in the browser, not fall back."""
    need_static_stack()
    need_playwright(stack_ws)
    from njli.visuals import VisualsError, render
    cfg = load_cfg(stack_ws)
    cfg["brand"]["font_source"] = "system"
    cfg["brand"]["fonts"]["display"]["family"] = "Njli Test Family That Does Not Exist"
    _setup(stack_ws, "sysfont", AR)
    with pytest.raises(VisualsError, match="fonts fell back"):
        render.render("sysfont", stack_ws, cfg)
