"""Write side of the board: decisions (Allow, Reject, Improve) and the human bookkeeping clicks.

Every write is atomic (temp + replace) and runs under the lock the posting code also uses, so a click
and a scheduled post cannot interleave. A decision re-reads the meta inside the lock and checks the
status again, so two clicks racing for the same draft produce one winner and one 409.
"""
from __future__ import annotations

import contextlib
import datetime as _dt
import os
import threading
import time
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Tuple

from .. import limits, policy, tzutil
from ..atomic import atomic_write_json
from ..fsutil import append_jsonl
from ..locks import FileLock, LockHeld
from .security import MAX_NOTE, SLUG_RE
from .store import ALLOW_FROM, IMPROVE_FROM, REJECT_FROM, SHARED_LOCK_REL, BoardStore, now_iso, read_json_safe, rows_of

Result = Tuple[int, Dict[str, Any]]


class Busy(Exception):
    """The shared lock could not be taken in time."""


def _err(code: int, error: str, message: str, **extra: Any) -> Result:
    return code, {"error": error, "message": message, **extra}


class Decider:
    def __init__(self, store: BoardStore, *, gate_fn: Optional[Callable[[str], Dict[str, Any]]] = None,
                 worker: Any = None, notify_fn: Optional[Callable[[str, str], None]] = None,
                 lock_wait: float = 10.0):
        self.store = store
        self.ws = store.ws
        self._gate_fn = gate_fn
        self.worker = worker
        self.notify_fn = notify_fn or (lambda title, msg: None)
        self.lock_wait = lock_wait
        self._mx = threading.Lock()
        self.touched: set = set()  # workspace-relative files the board itself wrote (the Improve guard skips them)

    def _touch(self, path: Path) -> None:
        try:
            self.touched.add(Path(path).relative_to(self.ws).as_posix())
        except ValueError:
            pass

    def _write(self, path: Path, data: Any) -> None:
        self._touch(path)
        atomic_write_json(path, data)

    # ------------------------------------------------------------------ plumbing
    def gate(self, slug: str) -> Dict[str, Any]:
        if self._gate_fn is not None:
            return self._gate_fn(slug)
        from ..gate.runner import run_gate
        return run_gate(slug, self.ws)

    @contextlib.contextmanager
    def locked(self, key: str) -> Iterator[None]:
        """One writer at a time inside this process (a mutex), then the shared file lock across processes.

        Threads of this process never contend on the file lock, and a release whose unlink was refused by a
        concurrent reader (Windows) is retried, so a click can never leave ``work/posting.lock`` behind.
        """
        with self._mx:
            lock = FileLock(self.ws / SHARED_LOCK_REL, stale_after=1800, wait=self.lock_wait)
            try:
                lock.acquire()
            except LockHeld as exc:
                raise Busy(str(exc)) from exc
            try:
                yield
            finally:
                lock.release()
                for _ in range(40):
                    owner = lock.owner()
                    if owner is None or owner.get("token") != lock.token:
                        break
                    try:
                        lock.path.unlink()
                    except OSError:
                        time.sleep(0.05)

    def log(self, row: Dict[str, Any]) -> None:
        append_jsonl(self.ws / "review" / "decisions.jsonl", row)

    def remember(self, d: Path, entry: Dict[str, Any]) -> None:
        doc = self.store.review_doc(d)
        doc["schema_version"] = policy.SCHEMA_VERSION
        hist = self.store.history(d)
        hist.append(entry)
        doc["history"] = hist
        self._write(d / "review.json", doc)
        self.log({"slug": d.name, **entry})

    def merge_council(self, d: Path) -> Optional[str]:
        """Fold the seat files (review/<seat>.json) into review.json's ``verdict``, which the gate reads."""
        seats = self.store.seats(d)
        verdict = self.store.aggregate(seats)
        if verdict is None:
            return None
        doc = self.store.review_doc(d)
        doc.update({"schema_version": policy.SCHEMA_VERSION, "verdict": verdict,
                    "seats": [{"seat": s["seat"], "verdict": s["verdict"]} for s in seats], "merged_at": now_iso()})
        doc.setdefault("history", [])
        self._write(d / "review.json", doc)
        return verdict

    def set_status(self, d: Path, status: str, **extra: Any) -> None:
        meta, _ = self.store.read_meta(d)
        meta["status"] = status
        for key, value in extra.items():
            if value is None:
                meta.pop(key, None)
            else:
                meta[key] = value
        self._write(d / "meta.json", meta)

    # ----------------------------------------------------------------- decisions
    def decide(self, slug: str, action: str, note: str = "", confirm: bool = False) -> Result:
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            return _err(400, "bad_slug", "That is not a valid draft name.")
        if action not in ("allow", "reject", "improve"):
            return _err(400, "bad_action", "Unknown action.")
        note = (note or "")[:MAX_NOTE]
        try:
            with self.locked(slug):
                return self._decide_locked(slug, action, note, confirm)
        except Busy:
            return _err(423, "busy", "Another write holds the lock. Try again in a moment.")

    def _decide_locked(self, slug: str, action: str, note: str, confirm: bool) -> Result:
        base, d = self.store.find(slug)
        if d is None or base is None:
            return _err(404, "unknown_post", "No such draft.")
        meta, _problem = self.store.read_meta(d)
        status = self.store.status_of(meta, base)
        if base == "published" or status in policy.READ_ONLY_STATUSES:
            return _err(409, "read_only", f"A {status} post is read-only.", status=status)
        if action == "allow":
            return self._allow(d, meta, status)
        if action == "reject":
            return self._reject(d, status, note, confirm)
        return self._improve(d, meta, status, note)

    def _allow(self, d: Path, meta: Dict[str, Any], status: str) -> Result:
        if os.environ.get(policy.WORKER_ENV) == "1":
            return _err(403, "worker_forbidden", "A worker can never allow a post. Only a person can.")
        if status not in ALLOW_FROM:
            reasons = {"revising": "It is being revised. Wait for the revision to come back.",
                       "queued": "It is already queued.",
                       "needs_check": "A post attempt left it unconfirmed. Confirm whether it went out first.",
                       "rejected": "It was rejected. Edit it back to a draft first."}
            return _err(409, "not_allowed_from_status", reasons.get(status, f"Cannot allow a {status} post."),
                        status=status)
        if self.store.cfg.get("gate", {}).get("require_council_pass"):
            verdict = self.merge_council(d)
            if verdict is None:
                return _err(422, "council_missing", "The council has not reviewed this draft yet.")
            if verdict != "pass":
                bad = [s["seat"] for s in self.store.seats(d) if s["verdict"] != "pass"]
                return _err(422, "council_not_passed", "The council has not passed it.", seats=bad)
        result = self.gate(d.name)
        if result.get("summary") != "PASS":
            return _err(422, "gate_failed", "The gate did not pass, so it was not queued.",
                        fails=[str(x)[:300] for x in (result.get("fails") or [])][:12])
        warnings = self._schedule_warnings(meta)
        now = now_iso()
        self.set_status(d, "queued")
        self.remember(d, {"at": now, "action": "allow", "from": status, "to": "queued",
                          "warnings": [w["code"] for w in warnings]})
        self.notify_fn("Allowed", f"{meta.get('title') or d.name}: queued.")
        return 200, {"ok": True, "status": "queued", "warnings": warnings}

    def _schedule_warnings(self, meta: Dict[str, Any]) -> List[Dict[str, str]]:
        sched = meta.get("scheduled_at")
        if not isinstance(sched, str) or not sched:
            return [{"code": "no_schedule", "message": "No scheduled_at is set, so nothing will post until you set one."}]
        try:
            when = tzutil.parse_aware(sched)
        except (ValueError, TypeError):
            return [{"code": "bad_schedule", "message": "scheduled_at is not a valid date and time."}]
        hours = float(self.store.cfg.get("posting", {}).get("missed_after_hours", 6))
        if _dt.datetime.now(_dt.timezone.utc) - when.astimezone(_dt.timezone.utc) > _dt.timedelta(hours=hours):
            return [{"code": "past_missed_window", "message": "The scheduled time is past the missed window, so it will be marked missed."}]
        return []

    def _reject(self, d: Path, status: str, note: str, confirm: bool) -> Result:
        if status not in REJECT_FROM:
            reasons = {"revising": "It is being revised. Wait for the revision to come back.",
                       "needs_check": "A post attempt left it unconfirmed. Confirm whether it went out first.",
                       "rejected": "It is already rejected."}
            return _err(409, "not_allowed_from_status", reasons.get(status, f"Cannot reject a {status} post."),
                        status=status)
        if confirm is not True:
            return _err(400, "confirm_required", "Rejecting needs confirmation.", confirm=True)
        self.set_status(d, "rejected")
        self.remember(d, {"at": now_iso(), "action": "reject", "from": status, "to": "rejected", "note": note})
        self.notify_fn("Rejected", f"{d.name}: it will not be posted.")
        return 200, {"ok": True, "status": "rejected"}

    def _improve(self, d: Path, meta: Dict[str, Any], status: str, note: str) -> Result:
        if status not in IMPROVE_FROM:
            reasons = {"revising": "It is already being revised.", "needs_check": "Confirm whether it went out first.",
                       "rejected": "It was rejected."}
            return _err(409, "not_allowed_from_status", reasons.get(status, f"Cannot improve a {status} post."),
                        status=status)
        if not note.strip():
            return _err(400, "note_required", "Write what to change.")
        if limits.is_paused(self.ws):
            return _err(409, "paused", "Everything is paused, so no worker will start.")
        if self.worker is None:
            return _err(503, "no_worker", "No worker is configured.")
        ok, why = self.worker.available()
        if not ok:
            return _err(503, "worker_unavailable", why)
        self.set_status(d, "revising")
        self.remember(d, {"at": now_iso(), "action": "improve", "from": status, "to": "revising", "note": note})
        try:
            self.worker.submit(d.name, note, status)
        except Exception as exc:  # the post must never be left in "revising" with nobody working on it
            self.set_status(d, status)
            return _err(500, "submit_failed", f"Could not start the worker: {exc}")
        self.notify_fn("Improve note received", f"{meta.get('title') or d.name}: a worker is on it.")
        return 200, {"ok": True, "status": "revising"}

    # ------------------------------------------------------------ human bookkeeping
    def _update_rows(self, rel: str, key: str, wanted: str, from_status: str, to_status: str,
                     id_of: Callable[[Dict[str, Any]], str]) -> Tuple[int, Optional[Dict[str, Any]]]:
        path = self.ws / rel
        data, problem = read_json_safe(path, None)
        if data is None or problem:
            return 404, None
        rows = data.get(key) if isinstance(data, dict) else data
        if not isinstance(rows, list):
            return 404, None
        hit = next((r for r in rows if isinstance(r, dict) and id_of(r) == wanted), None)
        if hit is None:
            return 404, None
        if hit.get("status") != from_status:
            return 409, hit
        hit["status"] = to_status
        hit["closed_at"] = now_iso()
        self._write(path, data)
        return 200, hit

    def connect_done(self, row_id: str, action: str) -> Result:
        from .store import item_id
        if action not in ("done", "skip"):
            return _err(400, "bad_action", "Use done or skip.")
        try:
            with self.locked("connect"):
                code, hit = self._update_rows("engage/connect.json", "rows", row_id, "waiting",
                                              "sent" if action == "done" else "skipped", item_id)
                if code == 200 and hit is not None:
                    self.log({"slug": f"connect:{row_id}", "at": now_iso(), "action": f"connect-{hit['status']}"})
        except Busy:
            return _err(423, "busy", "Another write holds the lock. Try again in a moment.")
        if code == 404:
            return _err(404, "not_waiting", "That person is not waiting any more.")
        if code == 409:
            return _err(409, "already_closed", "That row was already closed.")
        return 200, {"ok": True}

    def pending_done(self, item: str, action: str) -> Result:
        from .store import item_id
        if action not in ("done", "skip"):
            return _err(400, "bad_action", "Use done or skip.")
        try:
            with self.locked("pending"):
                code, hit = self._update_rows("engage/pending.json", "items", item, "pending",
                                              "posted" if action == "done" else "skipped", item_id)
                if code == 200 and hit is not None:
                    if hit["status"] == "posted":
                        self._touch(self.ws / "published" / "comments.jsonl")
                        append_jsonl(self.ws / "published" / "comments.jsonl", {
                            "at": hit["closed_at"], "kind": hit.get("kind"), "urn": hit.get("urn"),
                            "url": hit.get("url"), "author": hit.get("author"), "text": hit.get("text"),
                            "mode": "hand", "by": "human"})
                    self.log({"slug": f"comment:{item}", "at": now_iso(), "action": f"comment-{hit['status']}"})
        except Busy:
            return _err(423, "busy", "Another write holds the lock. Try again in a moment.")
        if code == 404:
            return _err(404, "not_pending", "That comment is not waiting any more.")
        if code == 409:
            return _err(409, "already_closed", "That comment was already closed.")
        return 200, {"ok": True}

    def profile_done(self, step_id: str, done: bool) -> Result:
        view = self.store.profile_view()
        if step_id not in {s["id"] for s in view["steps"]}:
            return _err(404, "unknown_step", "No such step.")
        path = self.ws / "profile" / "progress.json"
        try:
            with self.locked("profile"):
                data, _ = read_json_safe(path, {})
                if not isinstance(data, dict):
                    data = {}
                marks: Dict[str, Any] = dict(data["done"]) if isinstance(data.get("done"), dict) else {}
                if done:
                    marks[step_id] = now_iso()
                else:
                    marks.pop(step_id, None)
                data = {"schema_version": policy.SCHEMA_VERSION, "done": marks}
                self._write(path, data)
        except Busy:
            return _err(423, "busy", "Another write holds the lock. Try again in a moment.")
        return 200, {"ok": True, "done": bool(done)}

    def set_pause(self, kind: str, paused: bool) -> Result:
        if kind not in ("all",) + policy.PAUSE_KINDS:
            return _err(400, "bad_kind", "Use all, posting or comments.")
        if paused:
            limits.pause(self.ws, kind, reason="paused from the review board")
        else:
            limits.resume(self.ws, kind)
        self.log({"slug": f"pause:{kind}", "at": now_iso(), "action": "pause" if paused else "resume"})
        return 200, {"ok": True, "pause": limits.pause_flags(self.ws)}


def rows_for_cli(store: BoardStore) -> List[Dict[str, Any]]:
    return store.state()["posts"]


__all__ = ["Decider", "Busy", "rows_of"]
