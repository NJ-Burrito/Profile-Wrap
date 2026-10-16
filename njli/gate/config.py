"""Gate configuration: defaults mirror design-spec section 6 and sit under the workspace config."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any

DEFAULTS: dict[str, Any] = {
    "persona": {
        "name": "", "handle": "", "goal": "authority", "languages": ["en"], "primary_language": "en",
        "pillars": [], "voice_file": "profile/voice.md", "facts_file": "research/facts.md",
        "never_say": [], "private_terms": [], "demo": False,
    },
    "posting": {"formats_enabled": ["text", "slides", "gif"]},
    "engagement": {"comments": {"max_chars": 1250}, "connect": {"note_max": 200}},
    "research": {"stats_expiry_days": 90},
    "gate": {
        "caption_max": 3000, "hook_max": 210, "hook_target": 40,
        "hashtags_max": 3, "links_in_body": "fail", "em_dash": "fail", "en_dash": "warn",
        "banned_files": ["data/banned-words/en.json", "data/banned-words/ar.json"], "extra_banned": [],
        "numbers": {"mode": "claim_bound", "require_claims": True, "min_bare_digit": 10,
                    "scan": ["caption", "first_comment", "slides", "video", "alt"], "number_words": "warn"},
        "overrides": {"allow": True, "require_reason": True, "max_per_post": 2},
        "first_comment_gated": True, "require_alt_text": True, "require_council_pass": False,
        "gif": {"max_frames": 250, "max_mb": 40, "max_still_pct": 8, "flash_max_per_s": 3},
        "tools_missing": "skip_with_warning", "required_font_substrings": [],
    },
}


def deep_merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def resolve_workspace(workspace: str | os.PathLike | None = None, profile: str | None = None) -> Path:
    """The workspace folder: the argument, else the core resolver, else NJLI_WORKSPACE or the cwd.

    The core resolver (njli.paths) honours NJLI_WORKSPACE, then a folder holding .njl/workspace.json
    above the cwd, then ~/nj-linkedin/<profile>.
    """
    if workspace:
        return Path(workspace).expanduser().resolve()
    try:
        from njli import paths as core_paths  # type: ignore
        found = core_paths.find_workspace()
        return (found if found else core_paths.workspace_path(profile or "default")).resolve()
    except Exception:  # core module absent or a refused path: fall back to the plain rule
        return Path(os.environ.get("NJLI_WORKSPACE") or os.getcwd()).expanduser().resolve()


def read_json(path: Path) -> tuple[Any, str | None]:
    """Read JSON tolerating a BOM. Returns (data, note); data is None with a readable note on failure.

    On success the note is "BOM" when the file started with a UTF-8 byte order mark, else None.
    """
    try:
        raw = path.read_bytes()
    except FileNotFoundError:
        return None, f"{path.name} not found at {path}"
    except OSError as exc:
        return None, f"cannot read {path}: {exc}"
    bom = raw.startswith(b"\xef\xbb\xbf")
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return None, f"{path.name} is not valid UTF-8 JSON: {exc}"
    return data, ("BOM" if bom else None)


def load_config(workspace: Path) -> tuple[dict, list[str]]:
    """Merged config and a list of readable problems (never raises)."""
    problems: list[str] = []
    try:  # WP1's loader adds the full defaults and the split config files
        from njli import config as core_config  # type: ignore
        return deep_merge(DEFAULTS, core_config.load(workspace)), problems
    except ImportError:
        pass
    except Exception as exc:  # ConfigError and anything else: fall back, keep the reason readable
        if "not found" not in str(exc):
            problems.append(f"config: {exc}")
    data, note = read_json(workspace / "config" / "njli.json")
    if data is None and problems:
        return deep_merge(DEFAULTS, {}), problems
    if data is None:
        problems.append(f"config: {note}; gate defaults are used (run njli init)")
        data = {}
    elif not isinstance(data, dict):
        problems.append("config: config/njli.json must hold a JSON object; gate defaults are used")
        data = {}
    return deep_merge(DEFAULTS, data), problems


def package_root() -> Path:
    """Repo or install root that holds data/ (njli/gate/config.py is two levels below it)."""
    return Path(__file__).resolve().parents[2]


def find_data_file(rel: str, workspace: Path | None = None) -> Path | None:
    """Locate a shipped data file: NJLI_DATA_ROOT, the workspace copy, then the package root."""
    candidates: list[Path] = []
    env = os.environ.get("NJLI_DATA_ROOT")
    if env:
        candidates.append(Path(env) / rel)
    if workspace is not None:
        candidates.append(workspace / rel)
    candidates.append(package_root() / rel)
    candidates.append(Path(__file__).resolve().parents[1] / "_data" / rel)  # wheel layout (pyproject force-include)
    for c in candidates:
        if c.is_file():
            return c
    return None
