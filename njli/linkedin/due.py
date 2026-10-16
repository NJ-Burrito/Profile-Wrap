"""``njli due``: post the one queued draft whose slot has come (the scheduled job).

* One post per run, drafts sorted by ``scheduled_at``, tolerant of one corrupt ``meta.json``.
* A slot later than ``posting.missed_after_hours`` becomes ``missed`` and notifies; a human
  reschedules. Late posts are never sent at a random hour.
* With ``copy`` or ``api_click`` (or an unacknowledged ``api_scheduled``) the run only notifies
  that a slot has arrived.
* A refused gap guard is a logged skip with exit 0, not log spam: a reason is logged once.
"""
from __future__ import annotations

import datetime as _dt
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .. import config as config_mod
from .. import ledger, limits
from ..atomic import atomic_write_json
from ..fsutil import append_jsonl, read_json, read_jsonl
from ..locks import FileLock, LockHeld
from ..notify import notify
from . import post

NOTIFIED_REL = Path("work") / "due-notified.json"
LOG_REL = Path("data") / "logs" / "post-due.jsonl"


def _log_once(ws: Path, slug: str, reason: str) -> bool:
    """Append a log line unless the last line for this slug already says the same thing."""
    rows, _bad = read_jsonl(Path(ws) / LOG_REL)
    for row in reversed(rows):
        if row.get("slug") == slug:
            if row.get("reason") == reason:
                return False
            break
    try:
        append_jsonl(Path(ws) / LOG_REL, {"at": ledger.now_iso(), "slug": slug, "reason": reason})
    except OSError:
        pass
    return True


def _parse(text: Any) -> Optional[_dt.datetime]:
    try:
        moment = _dt.datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return moment if moment.tzinfo else None


def queued(ws: Path) -> Tuple[List[Tuple[_dt.datetime, Dict[str, Any], Path]], List[str]]:
    """Queued drafts with a usable slot, sorted by slot, and the meta files that could not be read."""
    found: List[Tuple[_dt.datetime, Dict[str, Any], Path]] = []
    bad: List[str] = []
    for meta_file in sorted((Path(ws) / "drafts").glob("*/meta.json")):
        try:
            meta = read_json(meta_file)
            if not isinstance(meta, dict):
                raise ValueError("not an object")
        except (OSError, ValueError):
            bad.append(str(meta_file))
            continue
        if meta.get("status") != "queued":
            continue
        slot = _parse(meta.get("scheduled_at"))
        if slot is None:
            bad.append(f"{meta_file} (queued without a valid scheduled_at with an offset)")
            continue
        found.append((slot, meta, meta_file.parent))
    found.sort(key=lambda item: (item[0], str(item[2])))
    return found, bad


def _set_status(ws: Path, folder: Path, **changes: Any) -> bool:
    lock = FileLock(Path(ws) / post.LOCK_REL, stale_after=1800)
    try:
        lock.acquire()
    except LockHeld:
        return False
    try:
        meta = read_json(folder / "meta.json")
        meta.update(changes)
        atomic_write_json(folder / "meta.json", meta)
        return True
    finally:
        lock.release()


def _notify_once(ws: Path, slug: str, title: str, message: str) -> None:
    try:
        seen = read_json(Path(ws) / NOTIFIED_REL, default={})
    except ValueError:
        seen = {}
    if seen.get(slug) == title:
        return
    notify(title, message, ws)
    seen[slug] = title
    try:
        atomic_write_json(Path(ws) / NOTIFIED_REL, seen)
    except OSError:
        pass


def run_due(ws: Path, cfg: Dict[str, Any], *, now: Optional[_dt.datetime] = None,
            client: Any = None, gate_fn: Any = None) -> post.Outcome:
    ws = Path(ws)
    now = now or _dt.datetime.now(_dt.timezone.utc)
    if limits.is_paused(ws, "posting"):
        return post.Outcome("paused", "posting is paused", "", "guard")
    stopped = post.stop_active(ws)
    if stopped:
        _log_once(ws, "", stopped)
        return post.Outcome("skipped", stopped, "", "guard")
    mode = config_mod.effective_modes(cfg, ws)["posting"]
    missed_after = float(cfg["posting"].get("missed_after_hours", 6))
    items, bad = queued(ws)
    for note in bad:
        _log_once(ws, "", f"skipped unreadable draft metadata: {note}")
    done = {e.get("slug") for e in ledger.entries(ws) if e.get("state") in ledger.LIVE_STATES}
    for slot, meta, folder in items:
        slug = str(meta.get("slug") or folder.name)
        if slug in done:
            continue
        if (now - slot).total_seconds() > missed_after * 3600:
            if _set_status(ws, folder, status="missed"):
                notify("nj-linkedin: post missed",
                       f"'{slug}' was due {slot.isoformat()} and is more than {missed_after:g} h late. "
                       "Reschedule it on the board.", ws)
            continue
        if slot > now:
            continue
        if mode != "api_scheduled":
            _notify_once(ws, slug, "nj-linkedin: a post is due",
                         f"'{slug}' is due now. Open the board and press Post now.")
            return post.Outcome("skipped", f"'{slug}' is due; notified (posting.mode is {mode})",
                                slug, "guard")
        result = post.publish(ws, slug, cfg, by="due", client=client, gate_fn=gate_fn, now=now)
        if result.status == "refused":
            if result.kind == "gate":
                _set_status(ws, folder, status="hold", hold_reason=result.reason[:200])
                notify("nj-linkedin: post held",
                       f"'{slug}' no longer passes the gate: {result.reason[:140]}", ws)
            _log_once(ws, slug, result.reason)
        return result
    return post.Outcome("skipped", "nothing due", "", "guard")
