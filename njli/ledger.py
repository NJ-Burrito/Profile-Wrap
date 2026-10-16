"""The post ledger: ``published/ledger.jsonl``, append-only.

One post is one idempotency key. Each state change appends a complete new row with the same key
(pending, then posted / needs_check / failed / confirmed); readers collapse rows by key and the
latest wins. A crash can therefore never lose a row, and a half-written line is skipped, not fatal.

Counters (posts per day, the gap guard) read this file only, so API-posted and hand-posted items
share one source of truth.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from . import paths, schemalite
from .fsutil import append_jsonl, read_jsonl

LEDGER_REL = Path("published") / "ledger.jsonl"
SCHEMA_VERSION = 1
STATES = ("pending", "posted", "needs_check", "confirmed", "failed")
# States that mean "this slug may have reached LinkedIn" (never post it again).
LIVE_STATES = ("pending", "posted", "needs_check", "confirmed")
TERMINAL_STATES = ("posted", "needs_check", "confirmed", "failed")


class LedgerError(Exception):
    """The ledger cannot be written; the caller must not send anything."""


def ledger_path(workspace: Any) -> Path:
    return Path(workspace) / LEDGER_REL


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).astimezone().isoformat(timespec="seconds")


def new_key(slug: str) -> str:
    return f"{slug}-{uuid.uuid4().hex[:12]}"


def read_rows(workspace: Any) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Raw rows in file order, plus the numbers of lines that could not be read."""
    return read_jsonl(ledger_path(workspace))


def collapse(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """One merged row per idempotency key (later rows update earlier ones), in first-seen order."""
    merged: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        key = row.get("idempotency_key") or f"legacy:{row.get('slug')}:{row.get('posted_at')}"
        if key in merged:
            merged[key] = {**merged[key], **row}
        else:
            merged[key] = dict(row)
            merged[key].setdefault("idempotency_key", key)
            merged[key].setdefault("state", "posted")  # rows from before states existed
    return list(merged.values())


def entries(workspace: Any) -> List[Dict[str, Any]]:
    rows, _bad = read_rows(workspace)
    return collapse(rows)


def find_slug(workspace: Any, slug: str) -> Optional[Dict[str, Any]]:
    """The newest merged row for a slug, or None."""
    found = [e for e in entries(workspace) if e.get("slug") == slug]
    return found[-1] if found else None


def find_key(workspace: Any, key: str) -> Optional[Dict[str, Any]]:
    for e in entries(workspace):
        if e.get("idempotency_key") == key:
            return e
    return None


def _when(row: Dict[str, Any]) -> Optional[_dt.datetime]:
    for field in ("posted_at", "started_at"):
        text = row.get(field)
        if not text:
            continue
        try:
            moment = _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
        except ValueError:
            continue
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=_dt.timezone.utc)
        return moment
    return None


def last_activity(workspace: Any) -> Optional[_dt.datetime]:
    """Time of the newest row that may have reached LinkedIn (the gap guard reads this)."""
    times = [t for t in (_when(e) for e in entries(workspace) if e.get("state") in LIVE_STATES)
             if t is not None]
    return max(times) if times else None


def pending_rows(workspace: Any) -> List[Dict[str, Any]]:
    return [e for e in entries(workspace) if e.get("state") == "pending"]


def posts_today(workspace: Any, tz_name: Optional[str] = None) -> int:
    """Rows posted on today's date (local, or in ``tz_name``)."""
    today = _dt.datetime.now(_dt.timezone.utc).astimezone().date()
    count = 0
    for e in entries(workspace):
        if e.get("state") not in ("posted", "confirmed"):
            continue
        moment = _when(e)
        if moment is not None and moment.astimezone().date() == today:
            count += 1
    return count


def validate_row(row: Dict[str, Any]) -> List[str]:
    schema = schemalite.load_schema(paths.resource("schema", "ledger.schema.json"))
    return schemalite.validate(row, schema)


def append(workspace: Any, row: Dict[str, Any]) -> Dict[str, Any]:
    """Validate and append one row. Raises ``LedgerError`` (nothing written) when it cannot."""
    row = {"schema_version": SCHEMA_VERSION, **row}
    problems = validate_row(row)
    if problems:
        raise LedgerError("ledger row rejected: " + "; ".join(problems[:3]))
    try:
        append_jsonl(ledger_path(workspace), row)
    except OSError as exc:
        raise LedgerError(f"cannot write {ledger_path(workspace)}: {exc}") from exc
    return row


def update(workspace: Any, key: str, **changes: Any) -> Dict[str, Any]:
    """Append a full row for ``key`` with ``changes`` applied on top of its current state."""
    current = find_key(workspace, key)
    if current is None:
        raise LedgerError(f"no ledger row for key {key}")
    return append(workspace, {**current, **changes})
