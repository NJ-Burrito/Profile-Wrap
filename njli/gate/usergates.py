"""User-owned gates: hooks/gate_*.py in the workspace.

Each file defines  check(draft_dir, meta, surfaces, cfg)  and returns a list of findings. A finding is
a string (a failure) or a dict with `severity` ("fail" or "warn") and `message`. The code is the
user's own and runs with the user's rights; `njli doctor` flags that such files exist. An exception
or a bad return value becomes a FAIL line, never a traceback.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from .findings import FAIL, WARN, finding


def list_user_gates(ws: Path) -> list[Path]:
    hooks = ws / "hooks"
    return sorted(hooks.glob("gate_*.py")) if hooks.is_dir() else []


def run_user_gates(ws: Path, draft: Path, meta: dict, surfaces: dict, cfg: dict) -> tuple[list[dict], list[str]]:
    """Run every hooks/gate_*.py. Returns (findings, names of the gates that ran)."""
    out: list[dict] = []
    names: list[str] = []
    for path in list_user_gates(ws):
        name = path.stem
        names.append(name)
        try:
            spec = importlib.util.spec_from_file_location(f"njli_user_{name}", path)
            if spec is None or spec.loader is None:
                raise ImportError("cannot load module")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            check = getattr(mod, "check", None)
            if not callable(check):
                out.append(finding(f"custom:{name}", FAIL, f"{path.name} defines no check(draft_dir, meta, surfaces, cfg)"))
                continue
            result = check(draft, dict(meta), dict(surfaces), cfg)
        except Exception as exc:  # user code: report, never crash the gate
            out.append(finding(f"custom:{name}", FAIL, f"{path.name} raised {type(exc).__name__}: {exc}"))
            continue
        if result is None:
            continue
        if not isinstance(result, (list, tuple)):
            out.append(finding(f"custom:{name}", FAIL, f"{path.name} must return a list of findings"))
            continue
        for item in result:
            if isinstance(item, str):
                out.append(finding(f"custom:{name}", FAIL, item, token=item[:40]))
            elif isinstance(item, dict) and item.get("message"):
                sev = WARN if str(item.get("severity", "fail")).casefold() == "warn" else FAIL
                out.append(finding(f"custom:{name}", sev, str(item["message"]), surface=str(item.get("surface", "")),
                                   token=str(item.get("token", ""))))
            else:
                out.append(finding(f"custom:{name}", FAIL, f"{path.name} returned an unreadable finding: {item!r}"))
    return out, names
