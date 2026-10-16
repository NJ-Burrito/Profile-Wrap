"""``profile-wrap gui --selftest``: server up headless, /health and every screen, no network.

Uses a throwaway demo workspace and a socket on 127.0.0.1 only. Exit 0 when every check passed.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import init_wizard, policy
from .server import SCREENS, GuiServer

API_GETS = ("/api/home", "/api/board", "/api/providers", "/api/calendar", "/api/settings")


def _get(url: str, headers: Optional[Dict[str, str]] = None) -> Tuple[int, bytes, Dict[str, str]]:
    # An opener with no proxy handler: the check must not leave this machine.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with opener.open(req, timeout=20) as r:
            return r.status, r.read(), dict(r.headers)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(), dict(exc.headers)


def run_selftest(json_out: bool = False) -> int:
    rows: List[Dict[str, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        rows.append({"check": name, "status": "PASS" if ok else "FAIL", "detail": detail})
        if not json_out:
            print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""), flush=True)

    tmp = Path(tempfile.mkdtemp(prefix="profile-wrap-gui-selftest-"))
    server = None
    try:
        summary = init_wizard.init_workspace(tmp / "ws", init_wizard.DEMO_ANSWERS, git=False)
        ws = Path(summary["workspace"])
        server = GuiServer(ws, doctor_fn=lambda _w: {"summary": {}, "checks": []}).start_background()
        base = f"http://127.0.0.1:{server.port}"
        check("binds 127.0.0.1 only", server.httpd.server_address[0] == "127.0.0.1", str(server.httpd.server_address))
        code, body, _ = _get(base + "/health")
        check("/health", code == 200 and json.loads(body).get("ok") is True, str(code))
        for path, screen in SCREENS.items():
            code, body, hdr = _get(f"{base}{path}?t={server.token}")
            ok = code == 200 and f'data-screen="{screen}"'.encode() in body
            check(f"screen {screen} ({path})", ok, str(code))
        code, _, _ = _get(base + "/")
        check("page refused without token", code == 403, str(code))
        code, _, _ = _get(base + "/?t=wrong")
        check("page refused with a wrong token", code == 403, str(code))
        api = {"X-PW-Token": server.token}
        for path in API_GETS:
            code, body, _ = _get(base + path, api)
            check(f"api {path}", code == 200 and isinstance(json.loads(body), dict), str(code))
        code, _, _ = _get(base + "/api/home")
        check("api refused without token", code == 403, str(code))
        code, _, _ = _get(base + "/health", {"Host": "evil.example"})
        check("foreign Host refused", code == 403, str(code))
        for name in ("gui.css", "gui.js"):
            code, _, _ = _get(f"{base}/assets/{name}")
            check(f"asset {name}", code == 200, str(code))
    except Exception as exc:  # noqa: BLE001 - the selftest reports, never crashes
        check("selftest ran", False, f"{type(exc).__name__}: {exc}")
    finally:
        if server is not None:
            server.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
    failed = [r for r in rows if r["status"] == "FAIL"]
    if json_out:
        print(json.dumps({"ok": not failed, "checks": rows}, indent=2))
    else:
        print(f"gui selftest: {len(rows) - len(failed)}/{len(rows)} passed", flush=True)
    return policy.EXIT_FAIL if failed else policy.EXIT_OK
