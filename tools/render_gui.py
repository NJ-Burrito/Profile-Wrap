"""Render every screen of the Profile-Wrap desktop GUI, English and Arabic, to PNG files.

    python tools/render_gui.py <out-dir>

Safe by construction: the GUI server is started in this process on 127.0.0.1 over a throwaway demo
workspace with ``PROFILE_WRAP_TEST=1``; the browser is headless and every request that is not to
127.0.0.1 is aborted; the screens that would touch the OS keychain, a provider or LinkedIn (providers,
connect, update, gate, copy, board start) are answered from fixtures inside the browser and never reach
the server's real handlers. Nothing is posted, and no credential file is read.

Needs Playwright (``uv pip install playwright``; the browsers live under PLAYWRIGHT_BROWSERS_PATH).
It is a render tool, not part of the shipped app, so Playwright is not a project dependency.
"""
from __future__ import annotations

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

SCREENS = ("home", "board", "providers", "build", "settings", "connect")
PATHS = {"home": "/", "board": "/board", "providers": "/providers", "build": "/build",
         "settings": "/settings", "connect": "/connect"}

DOCTOR = {"summary": {"pass": 11, "warn": 2, "fail": 0}, "checks": [
    {"id": "poppler", "name": "PDF tools", "status": "warn", "hint": "install poppler to check PDF posts"},
    {"id": "keychain", "name": "Key storage", "status": "warn", "hint": "no OS keychain found"},
    {"id": "config", "name": "Config file", "status": "pass"}]}

PROVIDERS = {"keychain": True, "chosen": "anthropic", "providers": [
    {"id": "anthropic", "label": "Anthropic", "needs_key": True, "note": "Your own key; it never leaves this machine except to this provider.",
     "in_use": True, "model": "claude-sonnet-4", "default_model": "claude-sonnet-4", "key": "sk-a...f3", "source": "keychain", "base_url": None},
    {"id": "openai", "label": "OpenAI", "needs_key": True, "note": "", "in_use": False, "model": "gpt-4.1",
     "default_model": "gpt-4.1", "key": "missing", "source": "-", "base_url": None},
    {"id": "ollama", "label": "Ollama (on this computer)", "needs_key": False, "note": "Runs locally; no key and no account.",
     "in_use": False, "model": "llama3.1", "default_model": "llama3.1", "key": "not needed", "source": "-", "base_url": None}]}

UPDATE = {"notify": True, "latest": "0.6.0", "current": "0.6.0", "url": "http://127.0.0.1/",
          "news": [{"tag": "v0.6.0", "body": "A calmer home screen.\nFaster gate checks."}],
          "method": {"id": "pip", "label": "pip", "command": "pip install -U profile-wrap", "note": ""}}

GATE_PASS = {"slug": "x", "summary": "PASS", "fails": [], "warnings": ["hashtag count is at the upper limit"],
             "checks": {"facts": {"ok": True, "detail": "6 of 6 claims match a source"},
                        "style": {"ok": True, "detail": "no banned phrases"},
                        "length": {"ok": True, "detail": "1,180 characters"}}}
GATE_FAIL = {"slug": "x", "summary": "FAIL", "fails": ["claim 3 has no source", "opening line is a staged hook"],
             "warnings": [], "checks": {"facts": {"ok": False, "detail": "1 of 6 claims has no source"},
                                        "style": {"ok": False, "detail": "1 banned pattern"},
                                        "length": {"ok": True, "detail": "1,180 characters"}}}
COPY = {"slug": "x", "caption": "Three small habits that made our monthly report easier to read.\n\n1. Lead with the answer.\n2. Show one chart, not six.\n3. Name the decision it supports.",
        "first_comment": "Template in the comments.", "alt": "A simple bar chart.", "assets": ["chart.png"],
        "asset_names": ["chart.png"], "open_url": "https://www.linkedin.com/feed/"}


def connect_fixture(kind: str) -> Dict[str, Any]:
    def step(i: str, state: str, code: str, **params: Any) -> Dict[str, Any]:
        return {"id": i, "state": state, "code": code, "params": params}
    if kind == "fresh":
        steps = [step("app", "todo", "res.app.todo"), step("products", "wait", "res.products.unverified"),
                 step("redirect", "done", "res.redirect.done", port=8765, uri="http://localhost:8765/callback"),
                 step("credentials", "todo", "res.creds.todo"), step("signin", "todo", "res.signin.blocked")]
        reauth, mode = None, "copy"
    else:
        steps = [step("app", "done", "res.app.done"), step("products", "done", "res.products.done"),
                 step("redirect", "done", "res.redirect.done", port=8765, uri="http://localhost:8765/callback"),
                 step("credentials", "done", "res.creds.done"),
                 step("signin", "done", "res.signin.done", name="Maya Rivera", days=54)]
        reauth, mode = {"expires_on": "2026-12-20", "warn_from": "2026-12-06"}, "api_click"
    return {"steps": steps, "ready": kind != "fresh", "redirect_uri": "http://localhost:8765/callback",
            "scopes": ["openid", "profile", "w_member_social"],
            "products": ["Share on LinkedIn", "Sign In with LinkedIn using OpenID Connect"],
            "portal_url": "https://www.linkedin.com/developers/", "reauth": reauth, "posting_mode": mode,
            "ui_language": "en", "signin": {"state": "idle", "code": "", "params": {}, "url": ""}}


def main(argv: List[str]) -> int:
    if len(argv) != 2:
        print(__doc__)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("render_gui: Playwright is not installed (uv pip install playwright)", file=sys.stderr)
        return 2
    from profile_wrap import init_wizard
    from profile_wrap.gui import logic
    from profile_wrap.gui.server import GuiServer

    work = Path(tempfile.mkdtemp(prefix="pw-gui-render-", dir=str(out)))
    server = None
    shots: List[str] = []
    problems: List[str] = []
    try:
        summary = init_wizard.init_demo(work / "ws")
        ws = Path(summary["workspace"])
        logic.set_posting_mode(ws, "copy")  # what a new user sees
        server = GuiServer(ws, doctor_fn=lambda _w: DOCTOR).start_background()
        base = f"http://127.0.0.1:{server.port}"
        mock: Dict[str, Any] = {"connect": "fresh", "gate": GATE_PASS, "board": False, "update": False}

        def handle(route: Any) -> None:
            url = urlsplit(route.request.url)
            if url.hostname != "127.0.0.1":
                problems.append("blocked non-local request: " + url.hostname)
                return route.abort()
            p, m = url.path, route.request.method
            def ok(body: Any, status: int = 200) -> None:
                route.fulfill(status=status, content_type="application/json", body=json.dumps(body))
            if p == "/api/providers" and m == "GET":
                return ok(PROVIDERS)
            if p == "/api/providers/test":
                return ok({"ok": True, "message": "the model answered", "status": 200})
            if p.startswith("/api/providers/") or p.startswith("/api/connect/") and p != "/api/connect/signin":
                return ok({"ok": True})
            if p == "/api/connect/signin":
                return ok({"state": "idle", "code": "", "params": {}, "url": ""})
            if p == "/api/connect":
                return ok(connect_fixture(mock["connect"]))
            if p == "/api/update":
                return ok(UPDATE if mock["update"] else {"notify": False})
            if p == "/api/board/start":
                return ok({"running": True, "url": "http://127.0.0.1:8899/"})
            if p == "/api/board":
                return ok({"running": mock["board"], "url": "http://127.0.0.1:8899/" if mock["board"] else None})
            if p == "/api/build/gate":
                return ok(mock["gate"])
            if p == "/api/build/copy":
                return ok(COPY) if mock["gate"]["summary"] == "PASS" else ok(
                    {"error": "gate failed", "code": "copy.refused.gate", "params": {"count": 2, "first": "claim 3 has no source"}}, 422)
            if p in ("/api/build/draft", "/api/doctor") and m == "POST":
                return ok({"ok": True})
            route.continue_()

        def shoot(page: Any, name: str, full: bool = True) -> None:
            page.wait_for_timeout(450)  # let the entrance transition settle
            f = out / (name + ".png")
            page.screenshot(path=str(f), full_page=full)
            shots.append(f.name)

        def goto(page: Any, screen: str) -> None:
            page.goto(f"{base}{PATHS[screen]}?t={server.token}")
            page.wait_for_selector('#view[aria-busy="false"]', timeout=15000)  # R15: the ready state, not a timer
            page.wait_for_selector("#view > *", timeout=5000)

        with sync_playwright() as pw:
            browser = pw.chromium.launch()  # headless; closed in the finally below
            try:
                for lang in ("en", "ar"):
                    logic.set_language(ws, lang)
                    for theme in ("light", "dark"):
                        ctx = browser.new_context(viewport={"width": 1280, "height": 860}, color_scheme=theme,
                                                  locale="ar" if lang == "ar" else "en-US",
                                                  permissions=[])
                        ctx.route("**/*", handle)
                        page = ctx.new_page()
                        tag = f"{lang}-{theme}"
                        mock.update(connect="fresh", gate=GATE_PASS, board=False, update=False)
                        # the page remembers the theme in localStorage; set it before first paint
                        page.add_init_script(f"try{{localStorage.setItem('pw-theme','{theme}')}}catch(e){{}}")
                        for screen in SCREENS:
                            goto(page, screen)
                            if page.locator("body").get_attribute("data-screen") != screen:
                                problems.append(f"{tag} {screen}: wrong screen")
                            shoot(page, f"{tag}-{screen}")
                        if theme == "light":
                            mock["board"] = True
                            goto(page, "board"); shoot(page, f"{tag}-board-running")
                            mock["board"] = False
                            mock["connect"] = "done"
                            goto(page, "connect"); shoot(page, f"{tag}-connect-done")
                            mock["connect"] = "fresh"
                            mock["update"] = True
                            goto(page, "home")
                            page.wait_for_selector("#update:not([hidden])", timeout=5000)
                            shoot(page, f"{tag}-home-update")
                            page.click("#upd-how")
                            shoot(page, f"{tag}-home-update-open")
                            mock["update"] = False
                            # providers: type into a key field and test
                            goto(page, "providers")
                            page.click("#view .card button.ghost >> nth=0")
                            shoot(page, f"{tag}-providers-tested")
                            # build: gate pass, then gate fail
                            goto(page, "build")
                            page.click("#gate-btn")
                            page.wait_for_selector("#view .copybox", timeout=8000)
                            shoot(page, f"{tag}-build-pass")
                            mock["gate"] = GATE_FAIL
                            page.click("#gate-btn")
                            page.wait_for_selector("#view .gate-fail", timeout=8000)
                            shoot(page, f"{tag}-build-fail")
                            mock["gate"] = GATE_PASS
                            # narrow window
                            page.set_viewport_size({"width": 400, "height": 820})
                            goto(page, "home"); shoot(page, f"{tag}-home-narrow")
                        ctx.close()
            finally:
                browser.close()
    finally:
        if server is not None:
            server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    try:
        from PIL import Image
        for lang in ("en", "ar"):
            names = [f"{lang}-light-{s}.png" for s in SCREENS]
            ims = [Image.open(out / n) for n in names if (out / n).is_file()]
            if ims:
                w, hh = 640, 430
                sheet = Image.new("RGB", (w * 3, hh * 2), "white")
                for i, im in enumerate(ims):
                    sheet.paste(im.convert("RGB").resize((w, int(im.height * w / im.width))).crop((0, 0, w, hh)), ((i % 3) * w, (i // 3) * hh))
                sheet.save(out / f"sheet-{lang}.png")
    except ImportError:
        pass
    print(f"render_gui: {len(shots)} screenshots in {out}")
    for p in problems:
        print("PROBLEM", p)
    return 1 if problems or len(shots) < 24 else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
