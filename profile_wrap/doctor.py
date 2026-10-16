"""``profile-wrap doctor``: PASS/WARN/FAIL checks with one install hint per failure for this OS.

The result is a dict that validates against ``schema/doctor.schema.json``. Tool lookups use
``shutil.which`` with an optional ``path`` so tests (and the e2e job) can hide tools from PATH.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __version__, config, http, limits, paths, policy, tzutil
from .bootstrap import runtime as runtime_mod
from .fsutil import read_json, read_jsonl, secret_file_is_private

OS_LABELS = ("windows", "macos", "linux")

HINTS: Dict[str, Dict[str, str]] = {
    "python": {
        "windows": "winget install Python.Python.3.12   (or: scoop install python)",
        "macos": "brew install python@3.12",
        "linux": "sudo apt install python3.12   (or: sudo dnf install python3.12)",
    },
    "tzdata": {
        "windows": "uv pip install tzdata   (Windows has no IANA time zone database)",
        "macos": "uv pip install tzdata",
        "linux": "uv pip install tzdata   (or: sudo apt install tzdata)",
    },
    "git": {
        "windows": "winget install Git.Git   (or: scoop install git)",
        "macos": "brew install git   (or: xcode-select --install)",
        "linux": "sudo apt install git   (or: sudo dnf install git)",
    },
    "claude": {
        "windows": "npm install -g @anthropic-ai/claude-code   (needs Node; see "
                   "https://docs.claude.com/en/docs/claude-code)",
        "macos": "npm install -g @anthropic-ai/claude-code   (or: brew install node first)",
        "linux": "npm install -g @anthropic-ai/claude-code   (needs Node; see "
                 "https://docs.claude.com/en/docs/claude-code)",
    },
    "node": {
        "windows": "winget install OpenJS.NodeJS.LTS   (or: scoop install nodejs-lts)",
        "macos": "brew install node@22   (or: nvm install 22)",
        "linux": "nvm install 22   (https://github.com/nvm-sh/nvm), or: sudo apt install nodejs "
                 "/ sudo dnf install nodejs",
    },
    "npx": {
        "windows": "npx ships with Node: winget install OpenJS.NodeJS.LTS",
        "macos": "npx ships with Node: brew install node@22",
        "linux": "npx ships with Node: nvm install 22, or sudo apt install npm",
    },
    "uv": {
        "windows": "winget install astral-sh.uv   (or: scoop install uv)",
        "macos": "brew install uv",
        "linux": "curl -LsSf https://astral.sh/uv/install.sh | sh",
    },
    "ffmpeg": {
        "windows": "winget install Gyan.FFmpeg   (or: scoop install ffmpeg)",
        "macos": "brew install ffmpeg",
        "linux": "sudo apt install ffmpeg   (or: sudo dnf install ffmpeg)",
    },
    "ffprobe": {
        "windows": "ffprobe ships with FFmpeg: winget install Gyan.FFmpeg   (or: scoop install ffmpeg)",
        "macos": "ffprobe ships with FFmpeg: brew install ffmpeg",
        "linux": "ffprobe ships with FFmpeg: sudo apt install ffmpeg   (or: sudo dnf install ffmpeg)",
    },
    "chrome": {
        "windows": "winget install Google.Chrome   (or: npx hyperframes browser ensure)",
        "macos": "brew install --cask google-chrome   (if macOS blocks a downloaded browser, run: "
                 "xattr -dr com.apple.quarantine <path-to-browser>; Apple Silicon needs the arm64 build)",
        "linux": "sudo apt install chromium   (or: sudo dnf install chromium; or: npx playwright "
                 "install chromium)",
    },
    "playwright": {
        "windows": "npx playwright install chromium   (run inside the workspace)",
        "macos": "npx playwright install chromium   (run inside the workspace)",
        "linux": "npx playwright install --with-deps chromium   (run inside the workspace)",
    },
    "poppler": {
        "windows": "scoop install poppler   (or: winget install oschwartz10612.Poppler)",
        "macos": "brew install poppler",
        "linux": "sudo apt install poppler-utils   (or: sudo dnf install poppler-utils)",
    },
}

CHROME_NAMES = ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                "chrome", "msedge", "microsoft-edge")


def os_label() -> str:
    return paths.os_name()


def _chrome_locations(label: str) -> List[str]:
    if label == "windows":
        bases = [os.environ.get("PROGRAMFILES"), os.environ.get("PROGRAMFILES(X86)"),
                 os.environ.get("LOCALAPPDATA")]
        rel = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
               r"Chromium\Application\chrome.exe"]
        return [str(Path(b) / r) for b in bases if b for r in rel]
    if label == "macos":
        return ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
                "/Applications/Chromium.app/Contents/MacOS/Chromium",
                "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"]
    return ["/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
            "/snap/bin/chromium"]


class Doctor:
    def __init__(self, workspace: Optional[Path] = None, label: Optional[str] = None,
                 path: Optional[str] = None, online: bool = False, launchd_dryrun: bool = False,
                 plugin_root: Optional[Path] = None, data: Optional[Path] = None,
                 cfg: Optional[Dict[str, Any]] = None):
        self.workspace = Path(workspace) if workspace else None
        self.label = label or os_label()
        if self.label not in OS_LABELS:
            raise ValueError(f"unknown os label {self.label}")
        self.path = path
        self.online = online
        self.launchd_dryrun = launchd_dryrun
        self.root = Path(plugin_root) if plugin_root else paths.plugin_root()
        self.data = Path(data) if data else paths.data_dir()
        self.cfg = cfg
        self.checks: List[Dict[str, Any]] = []

    # -- helpers ----------------------------------------------------------
    def add(self, cid: str, name: str, status: str, detail: str = "", hint_key: Optional[str] = None,
            hint: str = "") -> None:
        if status in ("warn", "fail") and not hint and hint_key:
            hint = HINTS[hint_key][self.label]
        self.checks.append({"id": cid, "name": name, "status": status, "detail": detail,
                            "hint": hint if status in ("warn", "fail") else ""})

    def which(self, name: str) -> Optional[str]:
        return shutil.which(name, path=self.path)

    def tool(self, cid: str, exe: str, label: str, level: str, why: str) -> Optional[str]:
        found = self.which(exe)
        if found:
            self.add(cid, label, "pass", found)
        else:
            self.add(cid, label, level, f"{exe} not found on PATH ({why})", cid)
        return found

    # -- checks -----------------------------------------------------------
    def check_python(self) -> None:
        ver = ".".join(str(p) for p in sys.version_info[:3])
        if sys.version_info[:2] >= policy.MIN_PYTHON:
            self.add("python", "Python >= 3.10", "pass", f"Python {ver} at {sys.executable}")
        else:
            self.add("python", "Python >= 3.10", "fail", f"Python {ver} is too old", "python")

    def check_tzdata(self) -> None:
        if tzutil.tzdata_available():
            self.add("tzdata", "Time zone database", "pass", "IANA zones load")
        else:
            self.add("tzdata", "Time zone database", "fail" if self.label == "windows" else "warn",
                     "zoneinfo cannot load IANA zones", "tzdata")

    def check_tools(self) -> None:
        self.tool("git", "git", "git", "warn", "needed to keep the workspace under version control")
        claude = self.which("claude") or os.environ.get("PROFILE_WRAP_CLAUDE_BIN")
        if claude and Path(claude).exists():
            self.add("claude", "Claude CLI", "pass", str(claude))
        else:
            self.add("claude", "Claude CLI", "warn",
                     "claude not found; AI drafting needs it (demo and copy mode do not)",
                     "claude")
        node = self.which("node")
        if node:
            self.add("node", "Node >= 22", "pass", node)
        else:
            self.add("node", "Node >= 22", "warn",
                     "node not found (the GIF lane and slide rendering need it)", "node")
        self.tool("npx", "npx", "npx", "warn", "installs the pinned renderers")
        uv = self.which("uv")
        self.add("uv", "uv (optional)", "pass" if uv else "skip",
                 uv or "uv not found; optional, pip works too",
                 hint="" if uv else HINTS["uv"][self.label])
        self.tool("ffmpeg", "ffmpeg", "ffmpeg", "warn", "needed to build GIFs")
        self.tool("ffprobe", "ffprobe", "ffprobe", "warn", "needed to verify GIFs")

    def _chrome(self) -> Optional[str]:
        cfg_path = (self.cfg or {}).get("render", {}).get("chrome_path")
        for cand in (cfg_path, os.environ.get("PROFILE_WRAP_BROWSER"),
                     os.environ.get("HYPERFRAMES_BROWSER_PATH")):
            if cand and Path(cand).exists():
                return cand
        for name in CHROME_NAMES:
            found = self.which(name)
            if found:
                return found
        for loc in _chrome_locations(self.label):
            if Path(loc).exists():
                return loc
        return None

    def check_render(self) -> None:
        chrome = self._chrome()
        if chrome:
            self.add("chrome", "Chrome / Chromium", "pass", chrome)
        else:
            self.add("chrome", "Chrome / Chromium", "warn",
                     "no browser found (slides and GIFs need one)", "chrome")
        pins = read_json(self.root / "data" / "pins.json", default={}) if \
            (self.root / "data" / "pins.json").is_file() else {}
        hf = pins.get("npm", {}).get("hyperframes")
        if hf:
            self.add("hyperframes_pin", "HyperFrames pin", "pass", f"hyperframes@{hf} (data/pins.json)")
        else:
            self.add("hyperframes_pin", "HyperFrames pin", "warn", "data/pins.json has no hyperframes pin",
                     hint="Reinstall the plugin; npx is never run unpinned")
        pw = False
        if self.workspace and (self.workspace / "node_modules" / "playwright").is_dir():
            pw = True
        cache = {"windows": Path(os.environ.get("LOCALAPPDATA", "")) / "ms-playwright",
                 "macos": Path.home() / "Library" / "Caches" / "ms-playwright",
                 "linux": Path.home() / ".cache" / "ms-playwright"}[self.label]
        if cache.is_dir() and any(cache.iterdir()):
            pw = True
        self.add("playwright", "Playwright (optional)", "pass" if pw else "skip",
                 "found" if pw else "not installed; a system Chrome works instead",
                 hint="" if pw else HINTS["playwright"][self.label])
        needs_pdf = bool(self.cfg and "document" in self.cfg.get("posting", {}).get(
            "formats_enabled", []))
        pdftotext = self.which("pdftotext")
        if pdftotext:
            self.add("poppler", "poppler (PDF checks)", "pass", pdftotext)
        elif needs_pdf:
            self.add("poppler", "poppler (PDF checks)", "warn",
                     "PDF posts are enabled but pdftotext/pdffonts were not found", "poppler")
        else:
            self.add("poppler", "poppler (PDF checks)", "skip",
                     "only needed when document posts are enabled",
                     hint=HINTS["poppler"][self.label])

    def check_network(self) -> None:
        if not self.online:
            self.add("network", "Network reach (LinkedIn API host)", "skip",
                     "not checked; run 'profile-wrap doctor --online'")
            return
        ok, msg = http.reachable(policy.LINKEDIN_API_HOST)
        self.add("network", "Network reach (LinkedIn API host)", "pass" if ok else "warn", msg,
                 hint="" if ok else "Check your connection; behind a proxy set HTTPS_PROXY. "
                                    "Everything except posting works offline.")

    def check_secrets(self) -> None:
        profile = (self.cfg or {}).get("profile_id", "default")
        try:
            cdir = paths.config_dir(profile)
        except paths.PathError as exc:
            self.add("secrets", "Secrets directory", "fail", str(exc))
            return
        if not cdir.is_dir():
            self.add("secrets", "Secrets directory", "skip",
                     f"{cdir} does not exist yet (created by 'profile-wrap auth')")
            return
        loose = []
        for name in ("linkedin.env", "token.json", "apify.env", "ack.json"):
            f = cdir / name
            if f.is_file() and secret_file_is_private(f) is False:
                loose.append(name)
        if loose:
            self.add("secrets", "Secrets directory", "fail",
                     f"{', '.join(loose)} readable by other users",
                     hint=f"chmod 600 {cdir}/*   (Windows: icacls <file> /inheritance:r "
                          "/grant:r %USERNAME%:(R,W))")
        else:
            note = "ACLs are not inspected on Windows" if self.label == "windows" else \
                "files are private to this user"
            self.add("secrets", "Secrets directory", "pass", f"{cdir} ({note})")

    def check_token(self) -> None:
        profile = (self.cfg or {}).get("profile_id", "default")
        warn_days = (self.cfg or {}).get("linkedin", {}).get("token_warn_days", 10)
        try:
            token_file = paths.config_dir(profile) / "token.json"
        except paths.PathError:
            return
        if not token_file.is_file():
            self.add("token", "LinkedIn token", "skip",
                     "no token yet; copy mode needs none, 'profile-wrap auth' creates one")
            return
        try:
            tok = read_json(token_file)
            expires = tok.get("expires_at")
            if isinstance(expires, (int, float)):
                when = _dt.datetime.fromtimestamp(expires, _dt.timezone.utc)
            elif isinstance(expires, str):
                when = tzutil.parse_aware(expires)
            else:
                born = tok.get("obtained_at") or tok.get("created_at")
                when = tzutil.parse_aware(born) + _dt.timedelta(seconds=int(tok["expires_in"]))
        except (ValueError, KeyError, TypeError, OSError, AttributeError):
            self.add("token", "LinkedIn token", "warn", "token.json has no readable expiry",
                     hint="Run 'profile-wrap auth' again")
            return
        left = (when - _dt.datetime.now(_dt.timezone.utc)).total_seconds() / 86400
        if left <= 0:
            self.add("token", "LinkedIn token", "fail", "token expired",
                     hint="There is no refresh token: run 'profile-wrap auth' again")
        elif left < warn_days:
            self.add("token", "LinkedIn token", "warn", f"{left:.0f} days left",
                     hint="Run 'profile-wrap auth' before it expires")
        else:
            self.add("token", "LinkedIn token", "pass", f"{left:.0f} days left")

    def check_api_version(self) -> None:
        table = self.root / "data" / "linkedin-versions.json"
        if not table.is_file():
            self.add("api_version", "Linkedin-Version table", "skip", "data/linkedin-versions.json "
                     "is not shipped yet")
            return
        try:
            data = read_json(table)
            stamp = data.get("updated") or data.get("retrieved") if isinstance(data, dict) else None
            age = (_dt.date.today() - _dt.date.fromisoformat(str(stamp)[:10])).days
        except (ValueError, TypeError, OSError):
            self.add("api_version", "Linkedin-Version table", "warn", "table has no readable date",
                     hint="Run 'profile-wrap api-versions --refresh'")
            return
        if age > 90:
            self.add("api_version", "Linkedin-Version table", "warn", f"table is {age} days old",
                     hint="Run 'profile-wrap api-versions --refresh'")
        else:
            self.add("api_version", "Linkedin-Version table", "pass", f"table is {age} days old")

    def check_runtime(self) -> None:
        st = runtime_mod.status(self.root, self.data)
        if st["current"] is None:
            self.add("runtime", "Stable runtime", "warn", st["reason"],
                     hint="Run 'profile-wrap runtime install' (schedulers call this copy)")
        elif st["drift"]:
            self.add("runtime", "Stable runtime", "warn", st["reason"],
                     hint="Run 'profile-wrap runtime sync' (jobs keep working meanwhile)")
        else:
            self.add("runtime", "Stable runtime", "pass",
                     f"runtime/current is {st['current']} ({st['mode']})")

    def check_workspace(self) -> None:
        if not self.workspace:
            self.add("workspace", "Workspace", "skip", "no workspace selected (use --workspace)")
            return
        ws = self.workspace
        if not (ws / ".njl" / "workspace.json").is_file():
            self.add("workspace", "Workspace", "fail", f"{ws} is not a workspace",
                     hint="Run 'profile-wrap init' (or 'profile-wrap init --demo' to try it first)")
            return
        report = config.validate_workspace(ws)
        if report.errors:
            self.add("config", "Config", "fail", "; ".join(report.errors[:3]),
                     hint="Run 'profile-wrap config validate' for the full list")
        elif report.warnings:
            self.add("config", "Config", "warn", "; ".join(report.warnings[:3]),
                     hint="Run 'profile-wrap config validate' for the full list")
        else:
            self.add("config", "Config", "pass", "valid")
        flags = limits.pause_flags(ws)
        if flags:
            self.add("pause", "Pause flag", "warn", f"paused: {', '.join(flags)}",
                     hint="Run 'profile-wrap resume' when you want jobs to run again")
        else:
            self.add("pause", "Pause flag", "pass", "not paused")
        meta = read_json(ws / ".njl" / "workspace.json", default={})
        entries = meta.get("created_schedule", [])
        self.add("schedule", "Scheduler entries",
                 "pass" if entries else "warn",
                 f"{len(entries)} entries recorded" if entries else "no scheduler entries installed",
                 hint="" if entries else "Run 'profile-wrap schedule install --dry-run' to preview")
        rows, _bad = read_jsonl(ws / "data" / "logs" / "runs.jsonl")
        failed = [r for r in rows[-20:] if r.get("exit") not in (None, 0) or r.get("ok") is False]
        if failed:
            last = failed[-1]
            self.add("job_logs", "Last job runs", "warn",
                     f"{len(failed)} of the last {len(rows[-20:])} runs failed "
                     f"(latest: {last.get('job', '?')})", hint="See data/logs/<job>.log")
        else:
            self.add("job_logs", "Last job runs", "pass" if rows else "skip",
                     f"{len(rows[-20:])} recent runs ok" if rows else "no job has run yet")
        gates = sorted((ws / "hooks").glob("gate_*.py")) if (ws / "hooks").is_dir() else []
        if gates:
            self.add("user_gates", "Custom gates", "warn",
                     f"{len(gates)} user-owned gate scripts run code on every gate: "
                     + ", ".join(g.name for g in gates),
                     hint="Review them; they are your code, not the plugin's")

    def check_compliance(self) -> None:
        try:
            lint = importlib.import_module("profile_wrap.compliance.lint")
        except ImportError:
            self.add("compliance", "Compliance lint", "skip", "lint module not installed")
            return
        try:
            found = lint.lint(self.root)
        except Exception as exc:  # a broken lint must not hide the other results
            self.add("compliance", "Compliance lint", "warn", f"lint could not run: {exc}")
            return
        if found:
            self.add("compliance", "Compliance lint", "fail", f"{len(found)} violations",
                     hint="Run 'profile-wrap compliance lint' for the list; do not run modified code")
        else:
            self.add("compliance", "Compliance lint", "pass", "no forbidden code or wording")

    def check_launchd(self) -> None:
        if not self.launchd_dryrun:
            return
        if self.label != "macos":
            self.add("launchd", "launchd PATH capture", "skip", "macOS only")
            return
        missing = [t for t in ("node", "npx", "ffmpeg", "ffprobe", "claude") if not self.which(t)]
        if missing:
            self.add("launchd", "launchd PATH capture", "warn",
                     f"launchd runs with a minimal PATH; these would be missing: {', '.join(missing)}",
                     hint="Install them with brew, then re-run 'profile-wrap schedule install' so the "
                          "absolute paths are captured into the plist")
        else:
            self.add("launchd", "launchd PATH capture", "pass",
                     "all tools resolve; install captures their absolute paths into the plist")

    # -- run --------------------------------------------------------------
    def run(self) -> Dict[str, Any]:
        if self.cfg is None and self.workspace and (self.workspace / config.CONFIG_REL).is_file():
            try:
                self.cfg = config.load(self.workspace)
            except config.ConfigError:
                self.cfg = None
        steps: List[Callable[[], None]] = [
            self.check_python, self.check_tzdata, self.check_tools, self.check_render,
            self.check_network, self.check_secrets, self.check_token, self.check_api_version,
            self.check_runtime, self.check_workspace, self.check_compliance, self.check_launchd,
        ]
        for step in steps:
            step()
        counts = {s: sum(1 for c in self.checks if c["status"] == s)
                  for s in ("pass", "warn", "fail", "skip")}
        return {
            "schema_version": 1,
            "plugin_version": __version__,
            "os": self.label,
            "python": ".".join(str(p) for p in sys.version_info[:3]),
            "workspace": str(self.workspace) if self.workspace else None,
            "generated_at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
            "summary": counts,
            "checks": self.checks,
        }


def run(**kwargs: Any) -> Dict[str, Any]:
    return Doctor(**kwargs).run()


def exit_code(result: Dict[str, Any]) -> int:
    return policy.EXIT_FAIL if result["summary"]["fail"] else policy.EXIT_OK


def render_table(result: Dict[str, Any]) -> str:
    marks = {"pass": "PASS", "warn": "WARN", "fail": "FAIL", "skip": "skip"}
    lines = [f"profile-wrap doctor  ({result['os']}, Python {result['python']}, profile-wrap {result['plugin_version']})"]
    for c in result["checks"]:
        lines.append(f"  [{marks[c['status']]}] {c['name']}: {c['detail']}")
        if c["hint"]:
            lines.append(f"         -> {c['hint']}")
    s = result["summary"]
    lines.append(f"{s['pass']} pass, {s['warn']} warn, {s['fail']} fail, {s['skip']} skipped")
    return "\n".join(lines)


def dumps(result: Dict[str, Any]) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)
