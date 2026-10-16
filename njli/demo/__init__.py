"""The demo: a fictional workspace, a fake LinkedIn and a fake ``claude``. No network, no model."""
from __future__ import annotations

from typing import Any


def register(subparsers: Any) -> None:
    from . import run
    run.register(subparsers)
