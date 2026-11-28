"""Render the review board off screen: ``uv run python tools/render_board.py <out-dir>``.

Starts the board on a throwaway demo workspace (fictional persona, sample posts, comments, connections, profile
steps and numbers) bound to 127.0.0.1 only, opens it in headless Chromium, and writes screenshots of every tab in
English and Arabic, on a wide and a narrow screen, plus one dark-scheme pair. Nothing leaves the machine: the
demo workspace is built by ``init --demo`` (no network), the board has no worker, and no LinkedIn address is ever
opened (external requests are blocked).

Needs Playwright (``uv pip install playwright``; the browser comes from PLAYWRIGHT_BROWSERS_PATH).
The fonts of the site (``site/fonts``) are copied into the demo workspace's brand folder, so the board shows
what an owner with those fonts sees; the files are never added to the repository.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LI = "https://www.linkedin.com/"
TABS = ["posts", "comments", "connect", "profile", "metrics", "settings"]
SIZES = {"wide": (1440, 900), "narrow": (390, 844)}


def build_workspace(root: Path) -> Path:
    """An isolated demo workspace with every tab holding something to look at."""
    env = dict(os.environ, PYTHONUTF8="1", PROFILE_WRAP_TEST="1", PYTHONPATH=str(REPO),
               PROFILE_WRAP_CONFIG_DIR=str(root / "cfg"), PROFILE_WRAP_DATA_DIR=str(root / "data"),
               PROFILE_WRAP_HOME=str(root / "home"))
    env.pop("PROFILE_WRAP_WORKSPACE", None)
    ws = root / "ws"
    subprocess.run([sys.executable, "-m", "profile_wrap", "init", "--demo", "--yes", str(ws)], env=env, check=True,
                   capture_output=True, text=True, encoding="utf-8")
    for k in ("PROFILE_WRAP_TEST", "PROFILE_WRAP_CONFIG_DIR", "PROFILE_WRAP_DATA_DIR", "PROFILE_WRAP_HOME"):
        os.environ[k] = env[k]

    # fonts: the site fonts, as the brand fonts of this throwaway workspace
    fonts = ws / "brand" / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    for name in ("display-bold.woff2", "sans-regular.woff2", "sans-bold.woff2"):
        shutil.copy(REPO / "site" / "fonts" / name, fonts / name)
    cfg_path = ws / "config" / "profile-wrap.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["brand"]["fonts"]["display"] = {"family": "PW Display", "files": ["display-bold.woff2"]}
    cfg["brand"]["fonts"]["text"] = {"family": "PW Sans", "files": ["sans-regular.woff2"]}
    cfg["brand"]["fonts"]["arabic"] = {"family": "PW Sans", "files": ["sans-regular.woff2"]}
    cfg_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")

    # run the offline gate on a few drafts so the gate card has something to show (no network, no model)
    for slug in ("weekly-review-in-30-minutes", "unopened-dashboard-ar", "a-chart-nobody-asked-for", "five-checks-before-sharing-a-chart"):
        subprocess.run([sys.executable, "-m", "profile_wrap", "gate", slug, "--workspace", str(ws), "--json"], env=env,
                       capture_output=True, text=True, encoding="utf-8", timeout=120)

    # a spread of statuses and times, so the list shows every badge
    now = dt.datetime.now().astimezone()
    plan = {"five-checks-before-sharing-a-chart": ("queued", 1), "seven-unused-dashboards": ("queued", 3),
            "donor-report-hot-take": ("revising", None), "spring-availability": ("rejected", None),
            "reminder-template-pilot": ("missed", -1), "volunteer-spreadsheet-day": ("hold", None),
            "weekly-review-in-30-minutes": ("draft", 2), "unopened-dashboard-ar": ("draft", 4)}
    for slug, (status, days) in plan.items():
        mp = ws / "drafts" / slug / "meta.json"
        if not mp.is_file():
            continue
        meta = json.loads(mp.read_text(encoding="utf-8"))
        meta["status"] = status
        if days is not None:
            meta["scheduled_at"] = (now + dt.timedelta(days=days)).replace(hour=9, minute=30, second=0, microsecond=0).isoformat(timespec="seconds")
        mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")

    seats = {"weekly-review-in-30-minutes": [("editor", "pass", []), ("language-voice", "pass", []), ("growth", "revise", []),
                                            ("devil", "pass", [])],
             "a-chart-nobody-asked-for": [("editor", "revise", []), ("devil", "blockers", [
                 {"where": "line 2", "quote": "More is better.", "fix": "Name the decision the extra chart changes."}])]}
    for slug, rows in seats.items():
        folder = ws / "drafts" / slug / "review"
        folder.mkdir(parents=True, exist_ok=True)
        for seat, verdict, blockers in rows:
            (folder / f"{seat}.json").write_text(json.dumps({"seat": seat, "verdict": verdict, "blockers": blockers}), encoding="utf-8")

    # one post with a picture (generated here, nothing downloaded)
    try:
        from PIL import Image, ImageDraw
        card = ws / "drafts" / "weekly-review-in-30-minutes" / "out"
        card.mkdir(parents=True, exist_ok=True)
        img = Image.new("RGB", (1080, 1350), (248, 243, 230))
        dr = ImageDraw.Draw(img)
        dr.rectangle((80, 80, 1000, 1270), outline=(27, 26, 46), width=6)
        dr.polygon([(80, 80), (360, 80), (220, 400)], fill=(180, 73, 31))
        dr.rectangle((140, 560, 940, 640), fill=(47, 127, 118))
        dr.rectangle((140, 700, 700, 780), fill=(217, 162, 46))
        dr.rectangle((140, 840, 860, 920), fill=(31, 43, 69))
        img.save(card / "card.png")
    except ImportError:
        pass

    def put(rel: str, obj: object) -> None:
        p = ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")

    put("engage/pending.json", {"schema_version": 1, "items": [
        {"kind": "comment", "author": "Sam Okafor (fictional)", "lang": "en", "status": "pending", "fictional": True,
         "text": "Short reports get read. Yours made me cut two charts from mine.", "at": now.isoformat(timespec="seconds"),
         "url": LI + "feed/update/1/", "gate": {"summary": "PASS"}},
        {"kind": "reply", "author": "Rana Haddad (fictional)", "lang": "ar", "status": "pending", "fictional": True,
         "text": "شكرًا على القراءة، والسؤال عن الأرقام في محله. سأضيف المصدر في التعليق الأول.",
         "at": now.isoformat(timespec="seconds"), "url": LI + "feed/update/2/", "gate": {"summary": "PASS"}},
        {"kind": "comment", "author": "Eli Brandt (fictional)", "lang": "en", "status": "pending", "fictional": True,
         "text": "We tried the thirty-minute review for a month. The hard part was saying no to the fourth chart.",
         "at": now.isoformat(timespec="seconds")}]})
    put("engage/connect.json", {"schema_version": 1, "rows": [
        {"name": "Lina Haddad (fictional)", "profile_url": LI + "in/lina-haddad-demo/", "post_url": LI + "feed/update/3/",
         "why": "Commented twice on short-report posts", "action": "connect", "score": 8, "status": "waiting", "fictional": True,
         "note": "Hi Lina, your point on short reports stuck with me. Would be glad to connect."},
        {"name": "Omar Saleh (fictional)", "profile_url": LI + "in/omar-saleh-demo/", "why": "Writes about dashboards",
         "action": "follow", "score": 6, "status": "waiting", "fictional": True}]})
    put("profile/steps.json", {"schema_version": 1, "steps": [
        {"id": "h1", "section": "Headline", "title": "Say who you help and how", "action": "Replace the job title with one plain line.",
         "text": "Data analyst. I turn weekly reports into one page people read.", "open": LI + "in/me/edit/"},
        {"id": "a1", "section": "About", "title": "Cut the about to five lines", "action": "Keep the first two sentences, drop the list of tools.",
         "text": "I help small teams read their numbers in thirty minutes a week.", "open": LI + "in/me/edit/"},
        {"id": "b1", "section": "About", "title": "Pin the best post", "action": "Feature the four-pages-to-one post.", "open": LI + "in/me/"},
        {"id": "p1", "section": "Photo", "title": "Use a plain, well lit photo", "action": "Head and shoulders, one colour behind you."}]})
    put("profile/progress.json", {"done": {"h1": True}})
    snap = {"at": now.isoformat(timespec="seconds"), "followers": 1284, "profile_views": 312, "impressions_7d": 9420, "engagement_rate": "4.1%"}
    snaps = ws / "metrics"
    snaps.mkdir(parents=True, exist_ok=True)
    (snaps / "track.jsonl").write_text(json.dumps(snap) + "\n", encoding="utf-8")
    return ws


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tools/render_board.py <out-dir>", file=sys.stderr)
        return 2
    out = Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    for old in out.glob("*.png"):
        old.unlink()
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("render_board: Playwright is missing (uv pip install playwright)", file=sys.stderr)
        return 2
    os.environ["PYTHONUTF8"] = "1"
    sys.path.insert(0, str(REPO))
    work = Path(tempfile.mkdtemp(prefix="board-render-", dir=str(out)))
    server = None
    shots: list[str] = []
    try:
        ws = build_workspace(work)
        from profile_wrap.board.server import BoardServer
        server = BoardServer(ws, port=0, notify_fn=lambda t, m: None, start_worker=False)
        server.prepare()
        server.start_background()
        base = f"http://127.0.0.1:{server.port}/"
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            try:
                for scheme in ("light", "dark"):
                    for lang in ("en", "ar"):
                        for size, (w, h) in SIZES.items():
                            if scheme == "dark" and size == "narrow":
                                continue
                            ctx = browser.new_context(viewport={"width": w, "height": h}, color_scheme=scheme, bypass_csp=True,
                                                      device_scale_factor=1, reduced_motion="reduce")
                            ctx.route("**/*", lambda route: route.continue_() if route.request.url.startswith(base) else route.abort())
                            ctx.add_init_script(f"localStorage.setItem('profile_wrapLang','{lang}')")
                            page = ctx.new_page()
                            errors: list[str] = []
                            page.on("pageerror", lambda e: errors.append(str(e)))
                            for tab in (TABS if scheme == "light" else ["posts", "settings"]):
                                page.goto(server.url + "#" + tab)
                                page.wait_for_selector("#tabs .tab")          # R15: the page booted
                                page.wait_for_function("document.documentElement.lang === '%s'" % lang)
                                if tab == "posts":
                                    page.wait_for_selector(".row")
                                    rows = page.locator(".row")
                                    pick = page.locator('.row[data-slug="weekly-review-in-30-minutes"]')
                                    (pick if pick.count() else rows.first).click()
                                    page.wait_for_selector("#detail .caption")
                                else:
                                    page.wait_for_function("document.querySelector('#view').children.length > 0 && !document.querySelector('#view .empty')")
                                page.wait_for_timeout(350)
                                name = f"{tab}-{lang}-{size}" + ("-dark" if scheme == "dark" else "") + ".png"
                                page.screenshot(path=str(out / name), full_page=True)
                                shots.append(name)
                            # armed reject + the update/stale states are not needed for the look
                            if errors:
                                print("page errors:", errors, file=sys.stderr)
                                return 1
                            ctx.close()
            finally:
                browser.close()
    finally:
        if server is not None:
            server.shutdown()
        shutil.rmtree(work, ignore_errors=True)
    sheets(out, shots)
    print(f"render_board: {len(shots)} screenshots in {out}")
    return 0


def sheets(out: Path, shots: list[str]) -> None:
    """One contact sheet per language and size, so a whole round is one look."""
    try:
        from PIL import Image
    except ImportError:
        return
    for lang in ("en", "ar"):
        for size in SIZES:
            names = [f"{t}-{lang}-{size}.png" for t in TABS if f"{t}-{lang}-{size}.png" in shots]
            if not names:
                continue
            width = 720 if size == "wide" else 300
            thumbs = []
            for n in names:
                im = Image.open(out / n).convert("RGB")
                r = width / im.width
                im = im.resize((width, int(im.height * r)))
                thumbs.append(im.crop((0, 0, width, min(im.height, 1100))))
            cols = 3 if size == "wide" else 6
            rows = [thumbs[i:i + cols] for i in range(0, len(thumbs), cols)]
            sheet = Image.new("RGB", (cols * width, sum(max(t.height for t in r) for r in rows)), (200, 200, 200))
            y = 0
            for r in rows:
                for i, t in enumerate(r):
                    sheet.paste(t, (i * width, y))
                y += max(t.height for t in r)
            sheet.save(out / f"sheet-{lang}-{size}.png")


if __name__ == "__main__":
    sys.exit(main(sys.argv))
