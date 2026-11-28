"""The app serves the workspace's brand fonts the way the board does: fonts.css built from cfg, files confined."""
from __future__ import annotations

import json

from profile_wrap import config as config_mod


def _configure(ws, family="Dummy Family", files=("dummy.woff2",)):
    raw = config_mod.load_raw(ws)
    raw.setdefault("brand", {})["fonts"] = {"text": {"family": family, "files": list(files)}}
    config_mod.config_path(ws).write_text(json.dumps(raw), encoding="utf-8")


def test_fonts_css_empty_without_config_and_page_links_it(client, live, ws):
    status, body, hdr = client.call("GET", "/assets/fonts.css")
    assert status == 200 and b"@font-face" not in body and b"--font-" not in body
    _, page, _ = client.call("GET", f"/?t={live.token}")
    assert b"/assets/fonts.css" in page


def test_fonts_css_and_file_served_from_workspace(client, ws):
    fonts = ws / "brand" / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    (fonts / "dummy.woff2").write_bytes(b"wOF2-dummy-bytes")
    _configure(ws)
    status, body, hdr = client.call("GET", "/assets/fonts.css")
    text = body.decode()
    assert status == 200 and 'font-family:"Dummy Family"' in text and "/fonts/dummy.woff2" in text
    assert '--font-text:"Dummy Family"' in text
    status, data, hdr = client.call("GET", "/fonts/dummy.woff2")
    assert status == 200 and data == b"wOF2-dummy-bytes"
    assert "font-src 'self'" in hdr.get("Content-Security-Policy", "")


def test_unlisted_or_missing_file_is_dropped_and_traversal_refused(client, ws):
    fonts = ws / "brand" / "fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    (ws / "secret.woff2").write_bytes(b"secret")
    _configure(ws, files=("absent.woff2", "../secret.woff2"))
    _, body, _ = client.call("GET", "/assets/fonts.css")
    assert b"@font-face" not in body
    for bad in ("/fonts/absent.woff2", "/fonts/../secret.woff2", "/fonts/%2e%2e/secret.woff2",
                "/fonts/..%2fsecret.woff2", "/fonts/a/b.woff2", "/fonts/x.txt"):
        assert client.call("GET", bad)[0] == 404, bad
    assert client.call("GET", "/fonts/dummy.woff2", headers={"Host": "evil.example"})[0] == 403
