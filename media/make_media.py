#!/usr/bin/env python3
"""Rebuild the Profile-Wrap README and site pictures for 0.6.0, off screen.

    uv run --with pillow --with playwright python media/make_media.py [--sheet PATH] [--out DIR]

Writes (relative to the repo root):
  docs/assets/  hero.gif (README hero, <= 4 MB), board.png, gui.png, gui-ar.png
  site/         board.webp, og.png (1200x630), hero-still.png (1280x640)
  media/        banner.png (1280x640, the GitHub social preview; upload it by hand in the repo settings)

How: the real GUI and the real review board are started in this process on 127.0.0.1 over a throwaway demo
workspace (PROFILE_WRAP_TEST=1, fictional persona, no network, no key, no LinkedIn), photographed in headless
Chromium with every non-local request aborted, then composed into the pictures with the site's own fonts
(site/fonts) and the 0.6.0 logo (brand/svg). It reuses tools/render_gui.py and tools/render_board.py
for the fixtures and the demo workspace. Nothing is posted and no credential file is read.

Playwright and Pillow are render tools only: run them with `uv run --with`, never install them in the repo .venv.
Raw shots and the contact sheet go to pw-renders/media in the system temp folder (or --out); nothing else leaves the repo.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlsplit

os.environ["PROFILE_WRAP_TEST"] = "1"
os.environ["PYTHONUTF8"] = "1"
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

VERSION = "0.6.0"                       # shown in the sidebar of the shots
DEMO_PATH = "~/Profile-Wrap/demo"       # replaces the throwaway workspace path in the shots
FONTS = ROOT / "site" / "fonts"
LOCKUP_DARK = ROOT / "brand" / "svg" / "lockup-dark.svg"
LOCKUP_LIGHT = ROOT / "brand" / "svg" / "lockup-light.svg"
MARK_DARK = ROOT / "brand" / "svg" / "mark-dark.svg"

PAPER, INK, RUST, RUST2 = "#F8F3E6", "#1B1A2E", "#B4491F", "#8E3414"
TEAL, MUSTARD, NAVY, NAVY2, ON_DARK = "#2F7F76", "#D9A22E", "#1F2B45", "#141C31", "#FBF6E8"

HERO_W, HERO_H = 1280, 640
SHOT_W, SHOT_H, DPR = 1100, 760, 1.5     # the window pictures used inside the compositions

# the hero loop: (key, label, label is Arabic)
SCENES = [("home", "Home", False), ("build", "Build and gate", False), ("board", "Review board", False),
          ("dark", "Dark mode", False), ("ar", "بالعربية", True)]


def uri(p: Path) -> str:
    return p.resolve().as_uri()


def font_css() -> str:
    lat = ("U+0000-00FF,U+0131,U+0152-0153,U+02BB-02BC,U+02C6,U+02DA,U+02DC,U+2000-206F,U+20AC,U+2122,U+2190-2193,U+2212")
    ar = "U+0600-06FF,U+0750-077F,U+08A0-08FF,U+FB50-FDFF,U+FE70-FEFF"
    faces = [("PW Display", 700, "display-bold-latin", lat), ("PW Display", 700, "display-bold", ar),
             ("PW Sans", 400, "sans-regular-latin", lat), ("PW Sans", 400, "sans-regular", ar),
             ("PW Sans", 700, "sans-bold-latin", lat), ("PW Sans", 700, "sans-bold", ar)]
    return "".join(f'@font-face{{font-family:"{f}";src:url("{uri(FONTS / (n + ".woff2"))}") format("woff2");'
                   f'font-weight:{w};unicode-range:{u}}}' for f, w, n, u in faces)


# --------------------------------------------------------------------------- shots (the real app, off screen)

def shoot_gui(raw: Path, work: Path, pw: Any) -> None:
    import render_gui as rg
    from profile_wrap import init_wizard
    from profile_wrap.gui import logic
    from profile_wrap.gui.server import GuiServer

    summary = init_wizard.init_demo(work / "gui-ws")
    ws = Path(summary["workspace"])
    logic.set_posting_mode(ws, "copy")
    server = GuiServer(ws, doctor_fn=lambda _w: rg.DOCTOR).start_background()
    base = f"http://127.0.0.1:{server.port}"
    mock = {"connect": "fresh"}
    problems: List[str] = []

    def handle(route: Any) -> None:
        url = urlsplit(route.request.url)
        if url.hostname != "127.0.0.1":
            problems.append("blocked: " + str(url.hostname))
            return route.abort()
        p, m = url.path, route.request.method

        def ok(body: Any, status: int = 200) -> None:
            route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
        if p == "/api/providers" and m == "GET":
            return ok(rg.PROVIDERS)
        if p.startswith("/api/providers/") or (p.startswith("/api/connect/") and p != "/api/connect/signin"):
            return ok({"ok": True})
        if p == "/api/connect/signin":
            return ok({"state": "idle", "code": "", "params": {}, "url": ""})
        if p == "/api/connect":
            return ok(rg.connect_fixture(mock["connect"]))
        if p == "/api/update":
            return ok({"notify": False})
        if p in ("/api/board", "/api/board/start"):
            return ok({"running": False, "url": None})
        if p == "/api/build/gate":
            return ok(rg.GATE_PASS)
        if p == "/api/build/copy":
            return ok(rg.COPY)
        if p in ("/api/build/draft", "/api/doctor") and m == "POST":
            return ok({"ok": True})
        route.continue_()

    patch_js = ("(args) => {const w=document.createTreeWalker(document.body,NodeFilter.SHOW_TEXT);let n;"
                "while((n=w.nextNode())){let t=n.nodeValue;"
                "t=t.replace(/[A-Za-z]:[\\\\\\/]\\S*/g,args.path).replace(/\\b0\\.5\\.0\\b/g,args.ver);"
                "if(/^\\s*[\\w-]*ws\\s*$/.test(t))t='demo';if(t!==n.nodeValue)n.nodeValue=t;}}")

    def goto(page: Any, screen: str) -> None:
        page.goto(f"{base}{rg.PATHS[screen]}?t={server.token}")
        page.wait_for_selector('#view[aria-busy="false"]', timeout=15000)
        page.wait_for_selector("#view > *", timeout=5000)

    def shoot(page: Any, name: str, screen: str, w: int, h: int) -> None:
        page.set_viewport_size({"width": w, "height": h})
        page.wait_for_timeout(200)
        page.evaluate(patch_js, {"path": DEMO_PATH, "ver": VERSION})
        page.wait_for_timeout(450)
        page.screenshot(path=str(raw / f"{name}.png"))

    browser = pw.chromium.launch()
    try:
        for lang, theme in (("en", "light"), ("ar", "light"), ("en", "dark")):
            logic.set_language(ws, lang)
            ctx = browser.new_context(viewport={"width": 1280, "height": 900}, device_scale_factor=DPR, color_scheme=theme,
                                      locale="ar" if lang == "ar" else "en-US", permissions=[])
            ctx.route("**/*", handle)
            page = ctx.new_page()
            page.add_init_script(f"try{{localStorage.setItem('pw-theme','{theme}')}}catch(e){{}}")
            goto(page, "home")
            if page.locator("body").get_attribute("data-screen") != "home":   # R15: it is the Home screen
                problems.append(f"{lang}-{theme}: not on home")
            if theme == "light":
                shoot(page, f"gui-{lang}", "home", 1280, 900)
            shoot(page, f"hero-home-{lang}-{theme}", "home", SHOT_W, SHOT_H)
            if lang == "en" and theme == "light":
                goto(page, "build")
                page.click("#gate-btn")
                page.wait_for_selector("#view .copybox", timeout=8000)
                page.evaluate("document.querySelector('#view .copybox').scrollIntoView({block:'end'})")
                shoot(page, "hero-build-en-light", "build", SHOT_W, SHOT_H)
            ctx.close()
    finally:
        browser.close()
        server.shutdown()
    if problems:
        raise SystemExit("PROBLEM " + "; ".join(problems))


def shoot_board(raw: Path, work: Path, pw: Any) -> None:
    import render_board as rb
    ws = rb.build_workspace(work / "board")
    from profile_wrap.board.server import BoardServer
    server = BoardServer(ws, port=0, notify_fn=lambda t, m: None, start_worker=False)
    server.prepare()
    server.start_background()
    base = f"http://127.0.0.1:{server.port}/"
    browser = pw.chromium.launch()
    try:
        for name, (w, h, dpr, extra) in {
                "board-full": (1600, 1611, 1.8, ".media img{max-height:400px!important}"),
                "hero-board": (SHOT_W, SHOT_H, DPR, "")}.items():
            ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=dpr, color_scheme="light",
                                      bypass_csp=True, reduced_motion="reduce")
            ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
            ctx.add_init_script("localStorage.setItem('profile_wrapLang','en')")
            page = ctx.new_page()
            errors: List[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(server.url + "#posts")
            page.wait_for_selector("#tabs .tab")
            page.wait_for_function("document.documentElement.lang === 'en'")
            page.wait_for_selector(".row")
            pick = page.locator('.row[data-slug="weekly-review-in-30-minutes"]')
            (pick if pick.count() else page.locator(".row").first).click()
            page.wait_for_selector("#detail .caption")
            if extra:
                page.add_style_tag(content=extra)
            page.wait_for_timeout(500)
            page.screenshot(path=str(raw / f"{name}.png"))
            if errors:
                raise SystemExit("board page errors: " + "; ".join(errors))
            ctx.close()
    finally:
        browser.close()
        server.shutdown()


# --------------------------------------------------------------------------- compositions (HTML, photographed)

def window(src: Path, x: int, y: int, w: int, *, rot: float = 0, shadow: str = "dark", z: int = 1) -> str:
    sh = ("0 40px 70px -28px rgba(0,0,0,.75),0 0 0 1px rgba(255,255,255,.10)" if shadow == "dark"
          else "0 34px 60px -26px rgba(27,26,46,.55),0 0 0 1px rgba(27,26,46,.10)")
    return (f'<img class="win" src="{uri(src)}" style="left:{x}px;top:{y}px;width:{w}px;z-index:{z};'
            f'transform:rotate({rot}deg);box-shadow:{sh}">')


def page_html(w: int, h: int, body: str, *, dark: bool) -> str:
    bg = (f"radial-gradient(900px 520px at 88% -10%,rgba(180,73,31,.34),transparent 60%),"
          f"radial-gradient(700px 500px at 0% 110%,rgba(47,127,118,.18),transparent 60%),"
          f"linear-gradient(160deg,{NAVY} 0%,{NAVY2} 100%)") if dark else (
          f"radial-gradient(800px 500px at 90% -10%,rgba(217,162,46,.22),transparent 60%),"
          f"radial-gradient(700px 500px at 0% 110%,rgba(47,127,118,.12),transparent 60%),{PAPER}")
    return f"""<!doctype html><meta charset=utf-8><style>{font_css()}
*{{box-sizing:border-box;margin:0}}
html,body{{width:{w}px;height:{h}px;overflow:hidden}}
body{{position:relative;background:{bg};font-family:"PW Sans",sans-serif;color:{ON_DARK if dark else INK}}}
.win{{position:absolute;border-radius:14px;display:block}}
.logo{{position:absolute;display:block}}
.sub{{position:absolute;font-family:"PW Display",serif;font-weight:700;line-height:1.18;letter-spacing:-.01em}}
.cta{{position:absolute;background:{RUST};color:{ON_DARK};font-weight:700;border-radius:12px;
  box-shadow:0 10px 18px -10px rgba(0,0,0,.55),inset 0 -3px 0 {RUST2};white-space:nowrap}}
.chips{{position:absolute;display:flex;flex-wrap:wrap;gap:8px}}
.chip{{font-weight:700;font-size:15px;padding:7px 14px;border-radius:999px;border:1.5px solid rgba(251,246,232,.28);
  color:rgba(251,246,232,.55)}}
.chip.on{{background:{MUSTARD};border-color:{MUSTARD};color:{NAVY2}}}
.tag{{position:absolute;font-weight:700;font-size:13px;letter-spacing:.14em;text-transform:uppercase}}
</style>{body}"""


def chips(active: str, left: int, top: int, width: int) -> str:
    items = "".join(f'<span class="chip{" on" if k == active else ""}"{" dir=rtl" if rtl else ""}>{lab}</span>'
                    for k, lab, rtl in SCENES)
    return f'<div class="chips" style="left:{left}px;top:{top}px;width:{width}px">{items}</div>'


def hero_body(raw: Path, scene: str) -> str:
    img = raw / ({"home": "hero-home-en-light", "build": "hero-build-en-light", "board": "hero-board",
                 "dark": "hero-home-en-dark", "ar": "hero-home-ar-light"}[scene] + ".png")
    return (f'<img class="logo" src="{uri(LOCKUP_DARK)}" style="left:62px;top:54px;width:330px">'
            f'<div class="sub" style="left:62px;top:150px;width:340px;font-size:31px">From idea to posted, with a review board in the middle.</div>'
            f'<div class="cta" style="left:62px;top:372px;font-size:18px;padding:13px 20px">Nothing posts until you tap Allow</div>'
            + chips(scene, 62, 470, 340)
            + window(img, 426, 38, 826))


def banner_body(raw: Path) -> str:
    return (f'<img class="logo" src="{uri(LOCKUP_DARK)}" style="left:64px;top:66px;width:520px">'
            f'<div class="sub" style="left:64px;top:210px;width:500px;font-size:42px">Free, open-source LinkedIn post manager.</div>'
            f'<div class="cta" style="left:64px;top:418px;font-size:22px;padding:15px 24px">Nothing posts until you tap Allow</div>'
            + window(raw / "hero-board.png", 690, 64, 600, rot=2.2, z=1)
            + window(raw / "hero-home-en-light.png", 600, 250, 560, rot=-1.6, z=2))


def og_body(raw: Path) -> str:
    return (f'<img class="logo" src="{uri(LOCKUP_LIGHT)}" style="left:60px;top:58px;width:430px">'
            f'<div class="sub" style="left:60px;top:176px;width:440px;font-size:36px;color:{INK}">Free, open-source LinkedIn post manager.</div>'
            f'<div class="cta" style="left:60px;top:392px;font-size:21px;padding:14px 22px">Nothing posts until you tap Allow</div>'
            f'<div class="tag" style="left:62px;top:498px;color:{TEAL}">Review board &middot; Gate &middot; Council &middot; Allow</div>'
            + window(raw / "hero-board.png", 600, 52, 560, rot=2, shadow="light", z=1)
            + window(raw / "hero-home-en-light.png", 560, 260, 520, rot=-1.6, shadow="light", z=2))


def compose(pw: Any, work: Path, name: str, w: int, h: int, body: str, dark: bool):
    from PIL import Image
    f = work / f"compose-{name}.html"
    f.write_text(page_html(w, h, body, dark=dark), encoding="utf-8")
    browser = pw.chromium.launch()
    try:
        ctx = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
        page = ctx.new_page()
        page.goto(uri(f))
        page.evaluate("document.fonts.ready.then(()=>1)")
        page.wait_for_function("[...document.images].every(i=>i.complete&&i.naturalWidth>0)")
        page.wait_for_timeout(300)
        out = work / f"compose-{name}.png"
        page.screenshot(path=str(out))
        ctx.close()
    finally:
        browser.close()
    return Image.open(out).convert("RGB")


# --------------------------------------------------------------------------- assemble

def save_gif(scenes: List[Any], path: Path) -> int:
    from PIL import Image
    frames, durs = [], []
    hold, steps, step_ms = 1400, 4, 55
    n = len(scenes)
    for i in range(n):
        a, b = scenes[i], scenes[(i + 1) % n]
        frames.append(a); durs.append(hold)
        for s in range(1, steps + 1):
            frames.append(Image.blend(a, b, s / (steps + 1))); durs.append(step_ms)
    q = [f.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE) for f in frames]
    q[0].save(path, save_all=True, append_images=q[1:], duration=durs, loop=0, optimize=True, disposal=1)
    return len(frames)


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default="")
    ap.add_argument("--out", default=str(Path(tempfile.gettempdir()) / "pw-renders" / "media"))
    ap.add_argument("--reuse-raw", action="store_true", help="skip photographing the apps; compose from the raw shots")
    a = ap.parse_args()
    out = Path(a.out)
    raw = out / "raw"
    work = out / "work"
    raw.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    os.environ["TMPDIR"] = os.environ["TEMP"] = os.environ["TMP"] = str(work)
    from PIL import Image
    from playwright.sync_api import sync_playwright

    tmp = Path(tempfile.mkdtemp(prefix="pw-media-", dir=str(work)))
    try:
        with sync_playwright() as pw:
            if not a.reuse_raw:
                shoot_gui(raw, tmp, pw)
                shoot_board(raw, tmp, pw)

            # docs/assets/gui.png, gui-ar.png, board.png and site/board.webp
            for k, dst in (("gui-en", "docs/assets/gui.png"), ("gui-ar", "docs/assets/gui-ar.png")):
                Image.open(raw / f"{k}.png").convert("RGB").save(ROOT / dst, optimize=True)
            board = Image.open(raw / "board-full.png").convert("RGB")
            assert board.size == (2880, 2900), board.size
            board.save(ROOT / "docs/assets/board.png", optimize=True)
            board.resize((1600, 1611), Image.LANCZOS).save(ROOT / "site/board.webp", quality=84, method=6)

            # the five scenes: hero.gif, and the first one is the hero still
            scenes = [compose(pw, work, f"hero-{k}", HERO_W, HERO_H, hero_body(raw, k), True) for k, _l, _r in SCENES]
            frames = save_gif(scenes, ROOT / "docs/assets/hero.gif")
            scenes[0].save(ROOT / "site/hero-still.png", optimize=True)
            compose(pw, work, "banner", 1280, 640, banner_body(raw), True).save(ROOT / "media/banner.png", optimize=True)
            compose(pw, work, "og", 1200, 630, og_body(raw), False).save(ROOT / "site/og.png", optimize=True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    files = ["docs/assets/hero.gif", "docs/assets/board.png", "docs/assets/gui.png", "docs/assets/gui-ar.png",
             "site/board.webp", "site/og.png", "site/hero-still.png", "media/banner.png"]
    for f in files:
        im = Image.open(ROOT / f)
        print(f"{f}: {im.size[0]}x{im.size[1]} {(ROOT / f).stat().st_size} bytes")
    gif = (ROOT / "docs/assets/hero.gif").stat().st_size
    assert gif <= 4 * 1024 * 1024, f"hero.gif is {gif} bytes, over 4 MB"
    assert Image.open(ROOT / "site/og.png").size == (1200, 630)
    assert Image.open(ROOT / "site/hero-still.png").size == (1280, 640)
    assert Image.open(ROOT / "media/banner.png").size == (1280, 640)
    assert Image.open(ROOT / "site/board.webp").size == (1600, 1611)
    (out / "allow-hashes.txt").write_text("".join(f"{sha(ROOT / f)}  {f}\n" for f in files), encoding="utf-8")

    if a.sheet:
        sheet = Image.new("RGB", (1920, 1560), "#777")
        x = y = 0
        thumbs = [Image.open(ROOT / f).convert("RGB") for f in files[1:]] + scenes
        slots = [(0, 0, 620, 620), (640, 0, 620, 620), (1280, 0, 620, 620)]
        for im, (sx, sy, sw, sh) in zip(thumbs[:3], slots):
            t = im.copy(); t.thumbnail((sw, sh)); sheet.paste(t, (sx, sy))
        rest = thumbs[3:]
        for i, im in enumerate(rest):
            t = im.copy(); t.thumbnail((620, 330))
            sheet.paste(t, ((i % 3) * 640, 640 + (i // 3) * 350))
        Path(a.sheet).parent.mkdir(parents=True, exist_ok=True)
        sheet.save(a.sheet)
        print("sheet:", a.sheet)
    print(f"hero.gif frames: {frames}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
