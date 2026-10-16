"""Visual commands, registered through register(subparsers):

    profile-wrap render <slug>                      slides -> 2x PNG + PDF, or HyperFrames -> GIF
    profile-wrap new-gif <slug> [--title T]         copy the GIF project template into videos/<slug>
    profile-wrap visuals metrics <slug>             still-frame %, loop seam, flashes, contrast pairs
    profile-wrap visuals banner --headline H ...    render the profile banner at 1x and 2x
    profile-wrap fonts fetch | check                OFL fonts into brand/fonts, or verify the configured fonts
    profile-wrap icons add <name>                   fetch one Lucide icon (ISC) into brand/icons
    profile-wrap assets fetch                       npm install the pinned renderers and vendor GSAP
    profile-wrap motion status                      projects whose motion library is stale
    profile-wrap motion upgrade [--queued-only]     re-render with the current library, restore on any failure
    profile-wrap motion signature typed|svg|trace   write brand/identity/signature.data.js
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from profile_wrap import config as core_config
from profile_wrap import paths

from . import EXIT_FAIL, EXIT_OK, EXIT_USAGE, VisualsError


def _workspace(args: argparse.Namespace) -> Path:
    explicit = getattr(args, "workspace", None)
    if explicit:
        return Path(explicit).expanduser().resolve()
    found = paths.find_workspace()
    return (found if found else paths.workspace_path(getattr(args, "profile", None) or "default")).resolve()


def _config(ws: Path) -> Dict[str, Any]:
    try:
        return core_config.load(ws)
    except core_config.ConfigError as exc:
        if "not found" in str(exc):
            print(f"profile-wrap: no config in {ws}; using defaults ({exc})", file=sys.stderr)
            return core_config.defaults()
        raise VisualsError(str(exc))


def _emit(args: argparse.Namespace, obj: Any, text: Callable[[], None]) -> None:
    if getattr(args, "json", False):
        print(json.dumps(obj, indent=2, ensure_ascii=False))
    else:
        text()


def _guard(fn: Callable[[argparse.Namespace], int]) -> Callable[[argparse.Namespace], int]:
    def wrapper(args: argparse.Namespace) -> int:
        try:
            return fn(args)
        except VisualsError as exc:
            print(f"profile-wrap: {exc}", file=sys.stderr)
            return EXIT_FAIL
    return wrapper


# ------------------------------------------------------------------ handlers

@_guard
def _render(args: argparse.Namespace) -> int:
    from . import render
    ws = _workspace(args)
    data = render.render(args.slug, ws, _config(ws))
    _emit(args, data, lambda: print(f"OK {args.slug}: {data['format']} rendered ({data.get('slides') or data.get('gif', {}).get('frames')})"))
    return EXIT_OK


@_guard
def _new_gif(args: argparse.Namespace) -> int:
    from . import gif
    ws = _workspace(args)
    project = gif.new_gif(args.slug, ws, _config(ws), title=args.title or "", lang=args.lang, force=args.force)
    _emit(args, {"project": str(project)}, lambda: print(f"created {project}\nnext: profile-wrap assets fetch (once), edit index.html, then profile-wrap render {args.slug}"))
    return EXIT_OK


@_guard
def _metrics(args: argparse.Namespace) -> int:
    from . import metrics
    ws = _workspace(args)
    rep = metrics.run_for_slug(args.slug, ws, _config(ws))
    _emit(args, rep.to_dict(), lambda: print("\n".join(metrics.format_lines(rep))))
    return EXIT_OK if rep.ok else EXIT_FAIL


@_guard
def _banner(args: argparse.Namespace) -> int:
    from . import banner
    ws = _workspace(args)
    values = {"headline": args.headline, "subline": args.subline or "", "dir": args.dir}
    for key in ("c_bg", "c_ink", "c_accent"):
        if getattr(args, key):
            values[key] = getattr(args, key)
    data = banner.render_banner(ws, _config(ws), values, overlay=not args.no_overlay)
    _emit(args, data, lambda: print(f"banner written to {data['out']}: {', '.join(data['files'])}"))
    return EXIT_OK


@_guard
def _fonts(args: argparse.Namespace) -> int:
    from . import fonts
    ws = _workspace(args)
    cfg = _config(ws)
    if args.fonts_cmd == "fetch":
        data = fonts.fetch(ws, cfg)
        _emit(args, data, lambda: print(f"installed {len(data['files'])} file(s) into {data['dir']} ({data['licence']})"))
        return EXIT_OK
    data = fonts.check(cfg, ws)
    def show() -> None:
        print(f"font source: {data['source']}; families: {', '.join(data['families']) or 'none'}")
        for p in data["problems"]:
            print(f"FAIL {p}")
        print("fonts: " + ("ready" if data["ok"] else "NOT ready"))
    _emit(args, data, show)
    return EXIT_OK if data["ok"] else EXIT_FAIL


@_guard
def _icons(args: argparse.Namespace) -> int:
    from . import icons
    ws = _workspace(args)
    data = icons.add(args.name, ws)
    _emit(args, data, lambda: print(f"added {data['icon']} -> {data['path']} ({data['licence']})"))
    return EXIT_OK


@_guard
def _assets(args: argparse.Namespace) -> int:
    from . import assets
    ws = _workspace(args)
    data = assets.fetch(ws)
    _emit(args, data, lambda: print(f"installed pinned renderers in {ws}; GSAP vendored at {data['gsap']}"))
    return EXIT_OK


@_guard
def _motion(args: argparse.Namespace) -> int:
    from . import motion_upgrade, signature_trace
    ws = _workspace(args)
    if args.motion_cmd == "status":
        rows = motion_upgrade.status(ws)
        def show() -> None:
            for r in rows:
                flag = "STALE" if r["stale"] else ("legacy" if r["legacy_only"] else "current")
                print(f"{flag:8} {r['project']} (library {r['version'] or 'none'}, kit {r['current'] or 'none'})")
            if not rows:
                print("no video projects")
        _emit(args, rows, show)
        return EXIT_OK
    if args.motion_cmd == "upgrade":
        cfg = _config(ws)
        res = motion_upgrade.upgrade(ws, cfg, queued_only=args.queued_only, only=args.only, min_hours=args.min_hours,
                                     dry_run=args.dry_run, force=args.force)
        def show2() -> None:
            for r in res["results"]:
                print(" ".join(f"{k}={v}" for k, v in r.items()))
            print(f"motion upgrade: {res['failed']} failed of {res['total']} (log {res['log']})")
        _emit(args, res, show2)
        return EXIT_FAIL if res["failed"] else EXIT_OK
    if args.motion_cmd == "signature":
        mode = args.sig_cmd
        if mode == "typed":
            data = signature_trace.typed(args.text, Path(args.font), swash=not args.no_swash)
        elif mode == "svg":
            data = signature_trace.from_svg(Path(args.file).read_text(encoding="utf-8"))
        else:
            data = signature_trace.trace(Path(args.png), waypoints=Path(args.waypoints) if args.waypoints else None)
        target = signature_trace.write(ws, data)
        _emit(args, {"mode": data["mode"], "strokes": len(data["strokes"]), "path": str(target)},
              lambda: print(f"signature ({data['mode']}, {len(data['strokes'])} strokes) written to {target}"))
        return EXIT_OK
    return EXIT_USAGE


# ------------------------------------------------------------------ registration

def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--workspace", default=argparse.SUPPRESS, help="workspace path (default: PROFILE_WRAP_WORKSPACE or cwd)")
    p.add_argument("--profile", default=argparse.SUPPRESS, help="profile id (default: default)")
    p.add_argument("--json", action="store_true", default=argparse.SUPPRESS, help="machine-readable output")


def register(subparsers) -> None:
    p = subparsers.add_parser("render", help="render drafts/<slug>: slides to 2x PNG + PDF, or a GIF")
    p.add_argument("slug")
    _common(p)
    p.set_defaults(func=_render)

    p = subparsers.add_parser("new-gif", help="create videos/<slug> from the GIF project template")
    p.add_argument("slug")
    p.add_argument("--title", help="page title (default: the slug)")
    p.add_argument("--lang", choices=("en", "ar"), default="en")
    p.add_argument("--force", action="store_true", help="overwrite template files in an existing project")
    _common(p)
    p.set_defaults(func=_new_gif)

    v = subparsers.add_parser("visuals", help="visual checks and the banner")
    vs = v.add_subparsers(dest="visuals_cmd", required=True)
    m = vs.add_parser("metrics", help="still-frame share, loop seam, flashes and contrast of a GIF draft")
    m.add_argument("slug")
    _common(m)
    m.set_defaults(func=_metrics)
    b = vs.add_parser("banner", help="render the 1584x396 profile banner at 1x and 2x")
    b.add_argument("--headline", required=True)
    b.add_argument("--subline")
    b.add_argument("--dir", choices=("ltr", "rtl"), default="ltr")
    b.add_argument("--c-bg", dest="c_bg")
    b.add_argument("--c-ink", dest="c_ink")
    b.add_argument("--c-accent", dest="c_accent")
    b.add_argument("--no-overlay", action="store_true", help="skip the safe-zone preview image")
    _common(b)
    b.set_defaults(func=_banner)

    f = subparsers.add_parser("fonts", help="install OFL fonts or verify the configured fonts")
    fs = f.add_subparsers(dest="fonts_cmd", required=True)
    for name, text in (("fetch", "install the configured OFL fonts into brand/fonts"),
                       ("check", "verify every configured family resolves to files")):
        x = fs.add_parser(name, help=text)
        _common(x)
        x.set_defaults(func=_fonts)

    i = subparsers.add_parser("icons", help="manage Lucide icons")
    is_ = i.add_subparsers(dest="icons_cmd", required=True)
    a = is_.add_parser("add", help="fetch one Lucide icon (ISC) into brand/icons")
    a.add_argument("name")
    _common(a)
    a.set_defaults(func=_icons)

    s = subparsers.add_parser("assets", help="pinned Node renderers")
    ss = s.add_subparsers(dest="assets_cmd", required=True)
    fa = ss.add_parser("fetch", help="npm install the pinned renderers into the workspace and vendor GSAP")
    _common(fa)
    fa.set_defaults(func=_assets)

    mo = subparsers.add_parser("motion", help="motion library status, upgrade and signature tools")
    ms = mo.add_subparsers(dest="motion_cmd", required=True)
    st = ms.add_parser("status", help="list video projects whose library is stale")
    _common(st)
    st.set_defaults(func=_motion)
    up = ms.add_parser("upgrade", help="re-render posts with the current library; restores on any failure")
    up.add_argument("--queued-only", action="store_true", help="only queued posts at least --min-hours away")
    up.add_argument("--only", help="one draft slug")
    up.add_argument("--min-hours", type=float, default=3.0)
    up.add_argument("--dry-run", action="store_true")
    up.add_argument("--force", action="store_true", help="re-render even if the library is current")
    _common(up)
    up.set_defaults(func=_motion)
    sg = ms.add_parser("signature", help="write brand/identity/signature.data.js")
    sgs = sg.add_subparsers(dest="sig_cmd", required=True)
    t = sgs.add_parser("typed", help="outline of a name in a script font (needs fonttools only)")
    t.add_argument("--text", required=True)
    t.add_argument("--font", required=True, help="path to your font file (OFL or licensed to you)")
    t.add_argument("--no-swash", action="store_true")
    _common(t)
    t.set_defaults(func=_motion)
    sv = sgs.add_parser("svg", help="a signature SVG you drew")
    sv.add_argument("file")
    _common(sv)
    sv.set_defaults(func=_motion)
    tr = sgs.add_parser("trace", help="trace your handwriting PNG (needs the [sig] extra)")
    tr.add_argument("png")
    tr.add_argument("--waypoints", help="JSON with hand-picked waypoints per stroke (fixes the writing order)")
    _common(tr)
    tr.set_defaults(func=_motion)
