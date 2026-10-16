"""Read side of the board: one workspace, every file read tolerantly (a corrupt file degrades, never raises).

The state payload is cached by file mtimes and served with an ETag. It carries no captions; those are
loaded on demand per draft (``draft_detail``).
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

from .. import config as config_mod
from .. import fsutil, limits, policy
from .security import SLUG_RE, safe_linkedin_url

STATUS_ORDER = {"draft": 0, "revising": 1, "hold": 2, "needs_check": 3, "queued": 4, "missed": 5,
                "rejected": 6, "posted": 7, "demo": 8}
ALLOW_FROM = ("draft", "hold", "missed")
REJECT_FROM = ("draft", "hold", "queued", "missed")
IMPROVE_FROM = ("draft", "hold", "queued", "missed")
RTL_LANGS = ("ar", "fa", "he", "ur")
SHARED_LOCK_REL = Path("work") / "posting.lock"  # the lock profile_wrap.linkedin.post holds while it posts; the board writes under it too
MEDIA_LIMIT = 12
RTL = RTL_LANGS


def item_id(row: Dict[str, Any]) -> str:
    """A stable id for a pending/connect row (rows have no required id field)."""
    basis = "|".join(str(row.get(k, "")) for k in ("kind", "urn", "parent", "profile_url", "text", "name"))
    return hashlib.sha1(basis.encode("utf-8")).hexdigest()[:12]


def read_json_safe(path: Path, default: Any = None) -> Tuple[Any, Optional[str]]:
    """(value, problem). A missing file is (default, None); a corrupt file is (default, message)."""
    try:
        if not Path(path).exists():
            return default, None
        return fsutil.read_json(path), None
    except (ValueError, OSError, UnicodeDecodeError) as exc:
        return default, f"{Path(path).name}: {exc}"


def rows_of(data: Any, key: str) -> List[Dict[str, Any]]:
    """Rows from ``{"schema_version": 1, key: [...]}`` or a bare list (older exports)."""
    if isinstance(data, dict):
        data = data.get(key, [])
    return [r for r in data if isinstance(r, dict)] if isinstance(data, list) else []


def _mtime(path: Path) -> int:
    try:
        return os.stat(path).st_mtime_ns
    except OSError:
        return 0


class BoardStore:
    def __init__(self, workspace: Path):
        self.ws = Path(workspace)
        self._cfg: Optional[Dict[str, Any]] = None
        self._cfg_stamp = -1
        self._cfg_problem: Optional[str] = None
        self._state: Optional[Tuple[str, bytes]] = None
        self._rows: Dict[Tuple[str, str], Tuple[Tuple[int, ...], Dict[str, Any]]] = {}
        self._guard = threading.Lock()
        self._stamp_cache: Optional[Tuple[float, str]] = None

    # ----------------------------------------------------------------- config
    @property
    def cfg(self) -> Dict[str, Any]:
        stamp = _mtime(config_mod.config_path(self.ws))
        if self._cfg is None or stamp != self._cfg_stamp:
            try:
                self._cfg = config_mod.load(self.ws)
                self._cfg_problem = None
            except (config_mod.ConfigError, ValueError, OSError) as exc:
                self._cfg = config_mod.defaults("UTC")
                self._cfg_problem = str(exc)
            self._cfg_stamp = stamp
        return self._cfg

    @property
    def config_problem(self) -> Optional[str]:
        _ = self.cfg
        return self._cfg_problem

    # ------------------------------------------------------------------ drafts
    def post_dirs(self) -> Iterator[Tuple[str, Path]]:
        for base in ("drafts", "published"):
            root = self.ws / base
            try:
                names = sorted(e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False))
            except OSError:
                continue
            for name in names:
                if SLUG_RE.match(name) and (root / name / "meta.json").is_file():
                    yield base, root / name

    def find(self, slug: str) -> Tuple[Optional[str], Optional[Path]]:
        """published wins over drafts: a posted copy is read-only whatever the draft folder says."""
        if not SLUG_RE.match(slug or ""):
            return None, None
        for base in ("published", "drafts"):
            d = self.ws / base / slug
            if (d / "meta.json").is_file():
                return base, d
        return None, None

    def read_meta(self, d: Path) -> Tuple[Dict[str, Any], Optional[str]]:
        data, problem = read_json_safe(d / "meta.json", {})
        if not isinstance(data, dict):
            return {}, problem or "meta.json is not an object"
        return data, problem

    @staticmethod
    def status_of(meta: Dict[str, Any], base: str) -> str:
        status = meta.get("status")
        if status not in policy.POST_STATUSES:
            status = "posted" if base == "published" else "draft"
        return status

    @staticmethod
    def can(status: str, base: str) -> Dict[str, bool]:
        ro = base == "published" or status in policy.READ_ONLY_STATUSES
        return {"allow": not ro and status in ALLOW_FROM,
                "reject": not ro and status in REJECT_FROM,
                "improve": not ro and status in IMPROVE_FROM}

    def gates_of(self, d: Path) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        data, problem = read_json_safe(d / "gates.json", None)
        return (data if isinstance(data, dict) else None), problem

    def seats(self, d: Path) -> List[Dict[str, Any]]:
        seats: List[Dict[str, Any]] = []
        folder = d / "review"
        try:
            files = sorted(p for p in folder.glob("*.json") if p.is_file())
        except OSError:
            return seats
        for path in files:
            data, problem = read_json_safe(path, None)
            if isinstance(data, dict):
                verdict = data.get("verdict") if data.get("verdict") in ("pass", "revise", "blockers") else "invalid"
                blockers: List[Any] = list(data["blockers"]) if isinstance(data.get("blockers"), list) else []
                notes: List[Any] = list(data["notes"]) if isinstance(data.get("notes"), list) else []
                seats.append({"seat": str(data.get("seat") or path.stem)[:60], "verdict": verdict,
                              "blockers": [b for b in blockers if isinstance(b, dict)][:20],
                              "notes": [str(n)[:300] for n in notes[:10]]})
            else:
                seats.append({"seat": path.stem[:60], "verdict": "invalid", "blockers": [], "notes": [problem or ""]})
        return seats

    def review_doc(self, d: Path) -> Dict[str, Any]:
        """review.json is ``{"verdict": ..., "seats": [...], "history": [...]}``. A bare list (older exports) is the history."""
        data, _ = read_json_safe(d / "review.json", {})
        if isinstance(data, list):
            return {"history": [h for h in data if isinstance(h, dict)]}
        return data if isinstance(data, dict) else {}

    def history(self, d: Path) -> List[Dict[str, Any]]:
        hist = self.review_doc(d).get("history")
        return [h for h in hist if isinstance(h, dict)] if isinstance(hist, list) else []

    @staticmethod
    def aggregate(seats: List[Dict[str, Any]]) -> Optional[str]:
        """One council verdict from the seat files: pass only when every seat passes."""
        if not seats:
            return None
        verdicts = {s["verdict"] for s in seats}
        if "blockers" in verdicts:
            return "blockers"
        return "pass" if verdicts == {"pass"} else "revise"

    # --------------------------------------------------------------- state view
    STAMP_TTL = 1.0  # seconds a computed stamp is reused; a write made through the board invalidates it at once

    def invalidate(self) -> None:
        self._stamp_cache = None

    def _stamp(self) -> str:
        cached = self._stamp_cache
        now = time.monotonic()
        if cached and now - cached[0] < self.STAMP_TTL:
            return cached[1]
        value = self._compute_stamp()
        self._stamp_cache = (now, value)
        return value

    def _compute_stamp(self) -> str:
        """Fingerprint of everything the list depends on: the two roots' mtimes, each draft's name, and the size
        and mtime of its meta.json and gates.json (two stats per draft; captions and media are not in the list)."""
        parts: List[str] = []
        for base in ("drafts", "published"):
            root = self.ws / base
            parts.append(f"{base}:{_mtime(root)}")
            try:
                names = sorted(e.name for e in os.scandir(root) if e.is_dir(follow_symlinks=False))
            except OSError:
                continue
            for name in names:
                if SLUG_RE.match(name):
                    parts.append(f"{name}:{self._file_key(root / name)}")
        for rel in ("config/profile-wrap.json", "review/decisions.jsonl", "work/PAUSE", "work/PAUSE.posting",
                    "work/PAUSE.comments", "data/logs/notifications.jsonl"):
            parts.append(f"{rel}:{_mtime(self.ws / rel)}")
        return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()

    def state_bytes(self, extra: Dict[str, Any]) -> Tuple[str, bytes]:
        """(etag, body) of /api/state. Rebuilt only when a watched mtime moved."""
        stamp = self._stamp()
        with self._guard:
            if self._state and self._state[0] == stamp:
                return self._state
        body = json.dumps({**self.state(), **extra}, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        result = (stamp, body)
        with self._guard:
            self._state = result
            self._stamp_cache = (time.monotonic(), stamp)  # the build took time; the stamp is as fresh as the data
        return result

    def _summary(self, base: str, d: Path) -> Dict[str, Any]:
        """One post's row for the list, plus the read problems it hit. Pure function of two small files."""
        meta, problem = self.read_meta(d)
        status = self.status_of(meta, base)
        gates, gproblem = self.gates_of(d)
        scheduled = meta.get("scheduled_at")
        return {
            "slug": d.name, "where": base, "title": str(meta.get("title") or d.name)[:200],
            "lang": str(meta.get("lang") or "en"), "format": meta.get("format"),
            "status": status, "scheduled_at": scheduled if isinstance(scheduled, str) else None,
            "pillar": meta.get("pillar") if isinstance(meta.get("pillar"), str) else None,
            "hold_reason": meta.get("hold_reason") if isinstance(meta.get("hold_reason"), str) else None,
            "url": safe_linkedin_url(meta.get("url")),
            "gate": (gates or {}).get("summary") if gates else None,
            "gate_fails": len((gates or {}).get("fails") or []) if gates else 0,
            "gate_warns": len((gates or {}).get("warnings") or []) if gates else 0,
            "read_only": base == "published" or status in policy.READ_ONLY_STATUSES,
            "can": self.can(status, base),
            "degraded": bool(problem or gproblem),
            "_problems": [f"{d.name}/{x}" for x in (problem, gproblem) if x],
        }

    def state(self) -> Dict[str, Any]:
        """The list payload. Each post row is cached by the size and mtime of meta.json and gates.json, and a
        cold build reads the files on a few threads (the cost is file opens, which scanners slow down)."""
        todo: List[Tuple[str, Path, Tuple[int, ...]]] = []
        rows: Dict[Tuple[str, str], Dict[str, Any]] = {}
        live = set()
        for base, d in self.post_dirs():
            key = self._file_key(d)
            live.add((base, d.name))
            cached = self._rows.get((base, d.name))
            if cached and cached[0] == key:
                rows[(base, d.name)] = cached[1]
            else:
                todo.append((base, d, key))
        if todo:
            with ThreadPoolExecutor(max_workers=8) as pool:
                for (base, d, key), row in zip(todo, pool.map(lambda t: self._summary(t[0], t[1]), todo)):
                    self._rows[(base, d.name)] = (key, row)
                    rows[(base, d.name)] = row
        for gone in [k for k in self._rows if k not in live]:
            del self._rows[gone]
        posts = [{k: v for k, v in r.items() if k != "_problems"} for r in rows.values()]
        problems = [p for r in rows.values() for p in r["_problems"]]
        counts: Dict[str, int] = {}
        for p in posts:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        posts.sort(key=lambda p: (STATUS_ORDER.get(p["status"], 9), p["scheduled_at"] or "", p["slug"]))
        persona = self.cfg.get("persona", {})
        return {
            "api": 1,
            "posts": posts, "counts": counts, "total": len(posts),
            "degraded": bool(problems), "problems": problems[:20],
            "config_problem": self.config_problem,
            "persona": {"name": persona.get("name") or "", "role": persona.get("role") or "",
                        "demo": bool(persona.get("demo"))},
            "ui_language": self.cfg.get("board", {}).get("ui_language", "en"),
            "pause": limits.pause_flags(self.ws),
            "notifications": self.notifications(),
            "require_council_pass": bool(self.cfg.get("gate", {}).get("require_council_pass")),
        }

    @staticmethod
    def _file_key(d: Path) -> Tuple[int, ...]:
        key: List[int] = []
        for name in ("meta.json", "gates.json"):
            try:
                st = os.stat(d / name)
                key += [st.st_mtime_ns, st.st_size]
            except OSError:
                key += [0, 0]
        return tuple(key)

    def notifications(self, limit: int = 5) -> List[Dict[str, Any]]:
        rows, _ = fsutil.read_jsonl(self.ws / "data" / "logs" / "notifications.jsonl")
        return [{"at": r.get("at"), "title": str(r.get("title", ""))[:120], "message": str(r.get("message", ""))[:300]}
                for r in rows[-limit:]][::-1]

    # ------------------------------------------------------------ draft detail
    def draft_detail(self, slug: str) -> Optional[Dict[str, Any]]:
        base, d = self.find(slug)
        if d is None or base is None:
            return None
        meta, problem = self.read_meta(d)
        status = self.status_of(meta, base)

        def text(name: str, cap: int = 20000) -> str:
            try:
                return (d / name).read_text(encoding="utf-8-sig")[:cap]
            except (OSError, UnicodeDecodeError):
                return ""

        out = d / "out"
        media: List[str] = []
        try:
            names = sorted(e.name for e in os.scandir(out) if e.is_file())
        except OSError:
            names = []
        for n in names:
            if Path(n).suffix.lower() in (".png", ".gif", ".jpg", ".jpeg", ".webp") and not n.startswith("."):
                media.append(f"/media/{base}/{d.name}/{n}")
        gates, gproblem = self.gates_of(d)
        reply = d / "review-reply.txt"
        replies_file = self.ws / "engage" / f"replies-{d.name}.md"
        return {
            "slug": d.name, "where": base, "status": status, "can": self.can(status, base),
            "read_only": base == "published" or status in policy.READ_ONLY_STATUSES,
            "title": str(meta.get("title") or d.name)[:200], "lang": str(meta.get("lang") or "en"),
            "rtl": str(meta.get("lang") or "en").split("-")[0].lower() in RTL_LANGS,
            "format": meta.get("format"), "pillar": meta.get("pillar"),
            "scheduled_at": meta.get("scheduled_at") if isinstance(meta.get("scheduled_at"), str) else None,
            "hold_reason": meta.get("hold_reason"), "url": safe_linkedin_url(meta.get("url")),
            "claims": [str(c) for c in meta.get("claims", [])][:50] if isinstance(meta.get("claims"), list) else [],
            "last_revision": meta.get("last_revision"), "last_revision_gates": meta.get("last_revision_gates"),
            "caption": text("caption.txt"), "first_comment": text("first_comment.txt", 4000),
            "alt": meta.get("alt") if isinstance(meta.get("alt"), str) else text("alt.txt", 2000),
            "media": media[:MEDIA_LIMIT],
            "gates": None if gates is None else {
                "summary": gates.get("summary"), "fails": [str(x)[:400] for x in (gates.get("fails") or [])][:30],
                "warnings": [str(x)[:400] for x in (gates.get("warnings") or [])][:30],
                "overrides": [o for o in (gates.get("overrides") or []) if isinstance(o, dict)][:10],
                "skipped": [str(x)[:200] for x in (gates.get("skipped") or [])][:10],
                "checked_at": gates.get("checked_at")},
            "seats": self.seats(d), "history": self.history(d)[-30:],
            "revision_note": reply.read_text("utf-8", errors="replace").strip()[:600] if reply.is_file() else "",
            "replies": replies_file.read_text("utf-8", errors="replace")[:6000] if replies_file.is_file() else "",
            "degraded": bool(problem or gproblem),
            "problems": [p for p in (problem, gproblem) if p],
        }

    # ------------------------------------------------------------------ the rest
    def connect_rows(self) -> Dict[str, Any]:
        data, problem = read_json_safe(self.ws / "engage" / "connect.json", [])
        rows = []
        for r in rows_of(data, "rows"):
            if r.get("status") != "waiting":
                continue
            rows.append({"id": item_id(r), "name": str(r.get("name", ""))[:120], "why": str(r.get("why", ""))[:400],
                         "action": r.get("action") if r.get("action") in ("connect", "follow") else "connect",
                         "score": r.get("score"), "note": str(r.get("note", ""))[:policy.CONNECT_NOTE_MAX],
                         "profile_url": safe_linkedin_url(r.get("profile_url")),
                         "post_url": safe_linkedin_url(r.get("post_url")), "fictional": bool(r.get("fictional"))})
        return {"connect": rows, "degraded": bool(problem), "problem": problem,
                "slots_max": policy.CONNECT_SLOTS_MAX}

    def pending_rows(self) -> Dict[str, Any]:
        data, problem = read_json_safe(self.ws / "engage" / "pending.json", [])
        rows = []
        for r in rows_of(data, "items"):
            if r.get("status") != "pending":
                continue
            rows.append({"id": item_id(r), "kind": r.get("kind"), "author": str(r.get("author", ""))[:120],
                         "text": str(r.get("text", ""))[:3000], "lang": str(r.get("lang") or "en"),
                         "url": safe_linkedin_url(r.get("url")), "at": r.get("at"),
                         "gate": r.get("gate") if isinstance(r.get("gate"), dict) else None,
                         "fictional": bool(r.get("fictional"))})
        return {"pending": rows, "degraded": bool(problem), "problem": problem}

    def profile_view(self) -> Dict[str, Any]:
        steps_path = self.ws / "profile" / "steps.json"
        data, problem = read_json_safe(steps_path, None)
        steps_raw = rows_of(data, "steps") if data is not None else []
        progress, pproblem = read_json_safe(self.ws / "profile" / "progress.json", {})
        done: Dict[str, Any] = progress["done"] if isinstance(progress, dict) and isinstance(progress.get("done"), dict) else {}
        steps = []
        for s in steps_raw:
            sid = str(s.get("id", ""))
            if not sid:
                continue
            link = safe_linkedin_url(s.get("open"))
            steps.append({"id": sid, "section": str(s.get("section", ""))[:80], "title": str(s.get("title", ""))[:200],
                          "action": str(s.get("action", ""))[:600], "text": str(s.get("text", ""))[:3000],
                          "open": link, "open_refused": bool(s.get("open")) and link is None,
                          "done": sid in done or bool(s.get("done"))})
        return {"empty": not steps, "steps": steps, "done": sum(1 for s in steps if s["done"]), "total": len(steps),
                "degraded": bool(problem or pproblem), "problem": problem or pproblem,
                "steps_file": "profile/steps.json"}

    def metrics(self) -> Dict[str, Any]:
        ledger, bad = fsutil.read_jsonl(self.ws / "published" / "ledger.jsonl")
        snaps, _ = fsutil.read_jsonl(self.ws / "metrics" / "track.jsonl")
        comments, _ = fsutil.read_jsonl(self.ws / "published" / "comments.jsonl")
        keep = ("slug", "state", "posted_at", "url", "format", "lang", "pillar", "title", "first_comment_state")
        posts = [{k: r.get(k) for k in keep} for r in ledger[-200:]]
        for p in posts:
            p["url"] = safe_linkedin_url(p.get("url"))
        queued = [{"slug": p["slug"], "title": p["title"], "scheduled_at": p["scheduled_at"], "format": p["format"],
                   "lang": p["lang"], "pillar": p["pillar"]} for p in self.state_light() if p["status"] == "queued"]
        return {"posts": posts, "snapshots": snaps[-60:], "queued": sorted(queued, key=lambda q: q["scheduled_at"] or ""),
                "comments_total": len(comments), "bad_ledger_lines": len(bad)}

    def state_light(self) -> List[Dict[str, Any]]:
        out = []
        for base, d in self.post_dirs():
            meta, _ = self.read_meta(d)
            out.append({"slug": d.name, "title": meta.get("title") or d.name, "scheduled_at": meta.get("scheduled_at"),
                        "format": meta.get("format"), "lang": meta.get("lang"), "pillar": meta.get("pillar"),
                        "status": self.status_of(meta, base)})
        return out


def now_iso() -> str:
    return _dt.datetime.now().astimezone().isoformat(timespec="seconds")
