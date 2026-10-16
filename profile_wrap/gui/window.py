"""Open the app: a pywebview window when pywebview and a web view are present, else the browser."""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from .. import policy
from .server import GuiServer


def have_webview() -> bool:
    try:
        import webview  # noqa: F401  (optional dependency)
    except Exception:
        return False
    return True


def run(ws: Path, *, force_browser: bool = False) -> int:
    try:
        server = GuiServer(ws).start_background()
    except (OSError, ValueError) as exc:
        print(f"profile-wrap gui: could not start the local server: {exc}", file=sys.stderr)
        return policy.EXIT_FAIL
    try:
        if not force_browser and have_webview():
            import webview
            print(f"Profile-Wrap app on {server.url} (close the window to stop it)", flush=True)
            try:
                webview.create_window("Profile-Wrap", server.launch_url, width=1180, height=800,
                                      min_size=(760, 560))
                webview.start()
                return policy.EXIT_OK
            except Exception as exc:  # no WebView2 / WebKitGTK: fall back to the browser
                print(f"profile-wrap gui: no native window here ({type(exc).__name__}); using your browser.",
                      file=sys.stderr)
        elif not force_browser:
            print("profile-wrap gui: pywebview is not installed; using your browser. "
                  "For a native window: uv pip install pywebview", file=sys.stderr)
        print(f"Profile-Wrap app on {server.url}\nOpening your browser. Stop with Ctrl+C or the Quit button.",
              flush=True)
        webbrowser.open(server.launch_url)
        try:
            while not server.app.quit.wait(0.5):
                pass
        except KeyboardInterrupt:
            pass
        return policy.EXIT_OK
    finally:
        server.shutdown()
