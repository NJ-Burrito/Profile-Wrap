"""Fixtures for the visuals tests. The real-stack tests need Node, ffmpeg, a browser, Playwright (NJLI_NODE_DIR or a
workspace install) and network for the first fetch; each skips with its reason when something is missing."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    for name in ("NJLI_WORKSPACE", "NJLI_BROWSER", "NJLI_TEST", "NJLI_WORKER"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("NJLI_CONFIG_DIR", str(tmp_path / "cfgdir"))
    monkeypatch.setenv("NJLI_DATA_DIR", str(tmp_path / "datadir"))
    monkeypatch.setenv("NJLI_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PYTHONUTF8", "1")


def have(tool: str) -> bool:
    return shutil.which(tool) is not None


def new_workspace(root: Path) -> Path:
    ws = root / "ws"
    for d in ("config", "drafts", "videos", "work", "brand/fonts", "brand/vendor", "data/logs"):
        (ws / d).mkdir(parents=True, exist_ok=True)
    (ws / "config" / "njli.json").write_text("{}", encoding="utf-8")
    return ws


def load_cfg(ws: Path) -> dict:
    from njli import config
    return config.load(ws)


@pytest.fixture()
def ws(tmp_path) -> Path:
    return new_workspace(tmp_path)


@pytest.fixture(scope="session")
def toolcache(tmp_path_factory) -> Path:
    return tmp_path_factory.mktemp("toolcache")


@pytest.fixture(scope="session")
def ofl_dir(toolcache) -> Path:
    """The pinned OFL fonts, fetched once per session (skips without Node and network)."""
    if not have("npm"):
        pytest.skip("npm not installed: cannot fetch the OFL fonts")
    from njli.visuals import fonts
    ws = new_workspace(toolcache / "fontsws")
    try:
        fonts.fetch(ws, load_cfg(ws))
    except Exception as exc:  # network or registry problem
        pytest.skip(f"cannot fetch OFL fonts: {exc}")
    return ws / "brand" / "fonts"


@pytest.fixture(scope="session")
def gsap_js(toolcache) -> Path:
    if not have("npm"):
        pytest.skip("npm not installed: cannot fetch GSAP")
    from njli.visuals.assets import npm_pin
    dest = toolcache / "gsap"
    dest.mkdir(exist_ok=True)
    r = subprocess.run([shutil.which("npm"), "pack", f"gsap@{npm_pin('gsap')}", "--silent", "--pack-destination",
                        str(dest)], cwd=str(dest), capture_output=True, text=True, timeout=180)
    tgz = next(iter(sorted(dest.glob("*.tgz"))), None)
    if r.returncode != 0 or tgz is None:
        pytest.skip("cannot fetch GSAP from npm")
    with tarfile.open(tgz) as tar:
        member = tar.getmember("package/dist/gsap.min.js")
        out = dest / "gsap.min.js"
        out.write_bytes(tar.extractfile(member).read())
    return out


@pytest.fixture()
def stack_ws(ws, ofl_dir, gsap_js) -> Path:
    """A workspace with the OFL fonts and GSAP in place (what 'njli fonts fetch' and 'assets fetch' produce)."""
    for f in ofl_dir.iterdir():
        shutil.copyfile(f, ws / "brand" / "fonts" / f.name)
    from njli.visuals.assets import npm_pin
    vend = ws / "brand" / "vendor" / f"gsap@{npm_pin('gsap')}"
    vend.mkdir(parents=True)
    shutil.copyfile(gsap_js, vend / "gsap.min.js")
    return ws


def need_static_stack():
    from njli.visuals import assets, browser
    if not have("node"):
        pytest.skip("node not installed")
    if browser.discover(use_npx=False) is None and not have("npx"):
        pytest.skip("no browser found")
    return assets


def need_playwright(ws: Path):
    from njli.visuals import assets
    if assets.node_dir(ws) is None:
        pytest.skip("playwright not installed: run 'njli assets fetch' or set NJLI_NODE_DIR to a folder whose "
                    "node_modules has playwright")


def need_gif_stack():
    for tool in ("node", "npx", "ffmpeg", "ffprobe"):
        if not have(tool):
            pytest.skip(f"{tool} not installed")
