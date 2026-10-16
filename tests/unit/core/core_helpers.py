"""Helpers shared by the core tests (a unique module name, safe next to other packages' tests)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Optional

import pytest

from profile_wrap import tzutil

REPO = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"

#: Skip, with a reason, the tests that need the IANA database (absent on bare Windows).
needs_tzdata = pytest.mark.skipif(
    not tzutil.tzdata_available(),
    reason="IANA time zone data not installed (Windows: uv pip install tzdata)",
)


def load_answers_fixture(name: str) -> dict:
    return json.loads((FIXTURES / "answers" / name).read_text(encoding="utf-8"))


def run_cli(*argv: str, cwd: Optional[Path] = None, env: Optional[dict] = None):
    """Run ``python -m profile_wrap`` for real and return the CompletedProcess."""
    full_env = dict(os.environ)
    full_env.update(env or {})
    full_env["PYTHONPATH"] = str(REPO) + os.pathsep + full_env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, "-m", "profile_wrap", *argv], capture_output=True, text=True,
                          cwd=str(cwd or REPO), env=full_env, timeout=120)
