"""``profile-wrap track``: the weekly learnings loop.

Offline and deterministic. It reads only files Profile-Wrap already holds (``published/ledger.jsonl`` and, when
present, ``metrics/track.jsonl``), writes ``metrics/weekly/<YYYY-Www>.json`` and never calls LinkedIn or a model.
A metric that was not measured is ``null``; it is never turned into 0 and never guessed.
"""
from __future__ import annotations

from .week import build_report, parse_week, write_report  # noqa: F401
