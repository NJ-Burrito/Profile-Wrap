"""The ledger-first, idempotent post flow (design section 10).

    1. re-run the gate            5. write a ``pending`` ledger row (idempotency key)
    2. refuse a slug in the ledger 6. POST once (upload media first); the token goes only to
    3. check the minimum gap         allowlisted hosts
    4. take the lock              7. on 201 complete the row, then the optional first comment,
                                     then ``meta.status = posted``; nothing is moved on disk
    8. an error or timeout after send, or a crash after step 5, leaves ``pending``; the next run
       sets ``needs_check`` and never reposts. There is no blind retry.

All checks run inside the lock, so two concurrent runs cannot both pass them.
"""
from __future__ import annotations

import datetime as _dt
import re
import socket
import time
import urllib.error
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .. import config as config_mod
from .. import ledger, limits, policy
from ..atomic import atomic_write_json
from ..fsutil import read_json
from ..http import HttpError
from ..locks import FileLock, LockHeld
from ..notify import notify
from . import api, auth, social_extra, versions

LOCK_REL = Path("work") / "posting.lock"
STOP_REL = Path("work") / "linkedin-stop.json"
RECOVERY_REL = Path("work") / "posting-recovery.json"
RESERVED = "\\|{}@[]()<>#*_~"
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif")
MAX_COMMENTARY = 3000
MAX_IMAGES = 20
GateFn = Callable[[str, Path, bool], Dict[str, Any]]


# ------------------------------------------------------------------ text

def _esc(text: str) -> str:
    return "".join("\\" + c if c in RESERVED else c for c in text)


def little_text(text: str) -> str:
    """LinkedIn "little text" commentary: reserved characters escaped, hashtags as entities.

    Reserved characters are escaped inside a hashtag too: an unescaped underscore in an Arabic
    tag makes the whole commentary invalid and LinkedIn shows it raw.
    """
    out: List[str] = []
    i = 0
    for m in re.finditer(r"(?<!\w)#(\w+)", text):
        out.append(_esc(text[i:m.start()]))
        out.append("{hashtag|\\#|" + _esc(m.group(1)) + "}")
        i = m.end()
    out.append(_esc(text[i:]))
    return "".join(out)


# ------------------------------------------------------------------ outcome

@dataclass
class Outcome:
    status: str          # posted, dry, refused, needs_check, failed, stopped, paused, skipped
    reason: str = ""
    slug: str = ""
    kind: str = ""       # guard (benign skip), gate, error
    urn: Optional[str] = None
    url: Optional[str] = None
    details: Dict[str, Any] = field(default_factory=dict)

    @property
    def exit_code(self) -> int:
        if self.status == "paused":
            return policy.EXIT_PAUSED
        if self.status in ("posted", "dry", "skipped"):
            return policy.EXIT_OK
        if self.status == "refused" and self.kind == "guard":
            return policy.EXIT_OK  # a guard refusal is a logged skip, not a failure
        return policy.EXIT_FAIL

    def as_dict(self) -> Dict[str, Any]:
        return {"status": self.status, "reason": self.reason, "slug": self.slug, "kind": self.kind,
                "urn": self.urn, "url": self.url, "exit_code": self.exit_code, **self.details}


def _refuse(slug: str, reason: str, kind: str = "guard", **details: Any) -> Outcome:
    return Outcome("refused", reason, slug, kind, details=details)


# ------------------------------------------------------------------ draft

@dataclass
class Draft:
    dir: Path
    meta: Dict[str, Any]
    caption: str
    first_comment: str
    alt: str
    assets: List[Path]
    kind: str            # text, image, multi_image, document


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def media_kind(fmt: str, assets: List[Path]) -> str:
    """How the draft is sent: text, image (single image or GIF), multi_image or document."""
    if fmt == "text" and not assets:
        return "text"
    if fmt == "document" or (assets and all(a.suffix.lower() == ".pdf" for a in assets)):
        return "document"
    if len(assets) > 1:
        return "multi_image"
    return "image" if assets else "text"


def load_draft(ws: Path, slug: str) -> Draft:
    folder = Path(ws) / "drafts" / slug
    meta_file = folder / "meta.json"
    if not meta_file.is_file():
        raise FileNotFoundError(f"draft not found: {meta_file}")
    meta = read_json(meta_file)
    if not isinstance(meta, dict) or meta.get("slug") != slug:
        raise ValueError(f"{meta_file}: slug in meta.json must be '{slug}'")
    assets: List[Path] = []
    for name in meta.get("assets", []) or []:
        for candidate in (folder / name, folder / "out" / name):
            if candidate.is_file():
                assets.append(candidate)
                break
        else:
            raise FileNotFoundError(f"asset '{name}' not found in {folder} or {folder / 'out'}")
    fc = _read_text(folder / "first_comment.txt") or str(meta.get("first_comment") or "").strip()
    alt = _read_text(folder / "alt.txt") or str(meta.get("alt") or "").strip() or str(meta.get("title") or "")
    return Draft(folder, meta, _read_text(folder / "caption.txt"), fc, alt, assets,
                 media_kind(str(meta.get("format", "text")), assets))


def check_draft(d: Draft, cfg: Dict[str, Any]) -> List[str]:
    """Problems that make a send impossible (not gate findings)."""
    problems: List[str] = []
    if not d.caption:
        problems.append("caption.txt is empty or missing")
    limit = min(MAX_COMMENTARY, int(cfg.get("gate", {}).get("caption_max", MAX_COMMENTARY)))
    if len(d.caption) > limit:
        problems.append(f"caption is {len(d.caption)} characters; the limit is {limit}")
    if d.kind == "document" and (len(d.assets) != 1 or d.assets[0].suffix.lower() != ".pdf"):
        problems.append("a document post needs exactly one PDF in assets")
    if d.kind == "image" and d.assets[0].suffix.lower() not in IMAGE_EXT:
        problems.append(f"image post: {d.assets[0].suffix} is not png, jpg or gif")
    if d.kind == "multi_image":
        if len(d.assets) > MAX_IMAGES:
            problems.append(f"a multi-image post holds at most {MAX_IMAGES} images")
        bad = [a.name for a in d.assets if a.suffix.lower() not in IMAGE_EXT]
        if bad:
            problems.append("multi-image posts take png, jpg or gif only: " + ", ".join(bad))
    return problems


def build_body(d: Draft, author: str, cfg: Dict[str, Any],
               media_ids: Optional[List[str]] = None) -> Dict[str, Any]:
    body: Dict[str, Any] = {
        "author": author, "commentary": little_text(d.caption),
        "visibility": cfg["posting"].get("visibility", "PUBLIC"),
        "distribution": {"feedDistribution": "MAIN_FEED", "targetEntities": [],
                         "thirdPartyDistributionChannels": []},
        "lifecycleState": "PUBLISHED", "isReshareDisabledByAuthor": False}
    ids = media_ids or []
    if d.kind == "image" and ids:
        body["content"] = {"media": {"altText": d.alt, "id": ids[0]}}
    elif d.kind == "document" and ids:
        title = str(d.meta.get("document_title") or d.meta.get("title") or d.dir.name)
        body["content"] = {"media": {"title": title, "id": ids[0]}}
    elif d.kind == "multi_image" and ids:
        lines = [x.strip() for x in d.alt.splitlines() if x.strip()]
        alts = lines if len(lines) == len(ids) else [d.alt] * len(ids)
        body["content"] = {"multiImage": {"images": [
            {"id": i, "altText": a} for i, a in zip(ids, alts)]}}
    return body


# ------------------------------------------------------------------ helpers

def _utcnow() -> _dt.datetime:
    return _dt.datetime.now(_dt.timezone.utc)


def default_gate(slug: str, ws: Path, write: bool = True) -> Dict[str, Any]:
    from ..gate.runner import run_gate

    return run_gate(slug, ws, write=write)


def min_gap_hours(cfg: Dict[str, Any]) -> float:
    return max(float(policy.POST_GAP_HOURS_FLOOR),
               float(cfg["posting"].get("min_gap_hours", policy.POST_GAP_HOURS_DEFAULT)))


def gap_problem(ws: Path, cfg: Dict[str, Any], now: Optional[_dt.datetime] = None) -> Optional[str]:
    last = ledger.last_activity(ws)
    if last is None:
        return None
    gap = min_gap_hours(cfg)
    age = ((now or _utcnow()) - last).total_seconds() / 3600
    if age < gap:
        return (f"gap guard: the last post was {age:.1f} h ago (minimum {gap:g} h); "
                f"next slot opens in {gap - age:.1f} h")
    return None


def stop_active(ws: Path, now: Optional[float] = None) -> Optional[str]:
    """A 429/403 hard stop written by an earlier run, honoured until it lapses."""
    file = Path(ws) / STOP_REL
    if not file.is_file():
        return None
    try:
        info = read_json(file)
    except ValueError:
        return None
    until = float(info.get("until", 0))
    if (now if now is not None else time.time()) < until:
        wait = (until - (now if now is not None else time.time())) / 60
        return f"LinkedIn stopped the last request ({info.get('why')}); no posting for {wait:.0f} more minutes"
    return None


def write_stop(ws: Path, why: str, seconds: float) -> None:
    atomic_write_json(Path(ws) / STOP_REL, {"why": why, "until": time.time() + seconds,
                                             "at": ledger.now_iso()})


def _meta_set(draft_dir: Path, **changes: Any) -> None:
    meta = read_json(draft_dir / "meta.json")
    meta.update(changes)
    atomic_write_json(draft_dir / "meta.json", meta)


def _not_sent(exc: HttpError) -> bool:
    """True when the failure proves the request never left (name lookup or refused connection)."""
    if exc.kind in ("blocked_host", "blocked_endpoint", "no_version"):
        return True
    cause: Any = exc.__cause__
    if isinstance(cause, urllib.error.URLError):
        cause = cause.reason
    return isinstance(cause, (socket.gaierror, ConnectionRefusedError))


def recover(ws: Path, cfg: Optional[Dict[str, Any]] = None, quiet: bool = False) -> List[Dict[str, Any]]:
    """Turn every orphan ``pending`` row into ``needs_check``. Call it only while holding the lock."""
    done: List[Dict[str, Any]] = []
    for row in ledger.pending_rows(ws):
        ledger.update(ws, row["idempotency_key"], state="needs_check",
                      error="the run ended before the post was confirmed; check LinkedIn",
                      checked_at=ledger.now_iso())
        meta_dir = Path(ws) / "drafts" / str(row.get("slug"))
        if (meta_dir / "meta.json").is_file():
            try:
                _meta_set(meta_dir, status="needs_check")
            except (OSError, ValueError):
                pass
        if not quiet:
            notify("nj-linkedin: check a post",
                   f"'{row.get('slug')}' may or may not be live. Open LinkedIn, then confirm on the board.",
                   ws)
        done.append(row)
    return done


def _report_row(ws: Path, when: str, title: str, url: str) -> None:
    report = Path(ws) / "published" / "REPORT.md"
    report.parent.mkdir(parents=True, exist_ok=True)
    if not report.exists():
        report.write_text("# Posted by the account manager\n\n| when | title | link |\n|---|---|---|\n",
                          encoding="utf-8")
    safe = title.replace("|", "\\|").replace("\n", " ")
    with report.open("a", encoding="utf-8") as fh:
        fh.write(f"| {when} | {safe} | {url} |\n")


def plan(ws: Path, slug: str, cfg: Dict[str, Any],
         gate_fn: Optional[GateFn] = None) -> Dict[str, Any]:
    """What a post would send. No network, no ledger row, no gates.json write."""
    d = load_draft(ws, slug)
    gate = (gate_fn or default_gate)(slug, ws, False)
    ids = [f"urn:li:{d.kind}:EXAMPLE"] * len(d.assets)
    body = build_body(d, "urn:li:person:DEMO000000", cfg, ids or None)
    return {"slug": slug, "format": d.kind, "assets": [str(a) for a in d.assets], "body": body,
            "first_comment": d.first_comment, "alt": d.alt, "problems": check_draft(d, cfg),
            "gate": gate.get("summary"), "gap": gap_problem(ws, cfg),
            "status": d.meta.get("status")}


# ------------------------------------------------------------------ publish

def publish(ws: Path, slug: str, cfg: Dict[str, Any], *, by: str = "human",
            client: Optional[api.Client] = None, gate_fn: Optional[GateFn] = None,
            now: Optional[_dt.datetime] = None, require_status: Optional[str] = "queued",
            lock_wait: float = 0.0) -> Outcome:
    """Post one draft. Never raises for an expected failure; returns an ``Outcome``."""
    ws = Path(ws)
    if limits.is_paused(ws, "posting"):
        return Outcome("paused", "posting is paused (njli resume to continue)", slug, "guard")
    modes = config_mod.effective_modes(cfg, ws)
    mode = modes["posting"]
    if mode == "copy":
        return _refuse(slug, "posting.mode is 'copy': no API is used. Run 'njli post "
                             f"{slug} --dry' for the copy-ready block.", "error")
    if by == "due" and mode != "api_scheduled":
        return _refuse(slug, "unattended posting needs posting.mode=api_scheduled and a valid "
                             "acknowledgement; this run only notifies", "guard")
    lock = FileLock(ws / LOCK_REL, stale_after=1800, wait=lock_wait)
    try:
        lock.acquire()
    except LockHeld as exc:
        return _refuse(slug, f"another post run is in progress ({exc})", "guard")
    try:
        return _publish_locked(ws, slug, cfg, by, mode, client, gate_fn, now, require_status)
    finally:
        lock.release()


def _publish_locked(ws: Path, slug: str, cfg: Dict[str, Any], by: str, mode: str,
                    client: Optional[api.Client], gate_fn: Optional[GateFn],
                    now: Optional[_dt.datetime], require_status: Optional[str]) -> Outcome:
    recover(ws, cfg)
    try:
        d = load_draft(ws, slug)
    except (OSError, ValueError) as exc:
        return _refuse(slug, str(exc), "error")
    status = d.meta.get("status")
    if status in policy.READ_ONLY_STATUSES or status == "needs_check":
        return _refuse(slug, f"draft status is '{status}': it is not sent again", "guard")
    if require_status and status != require_status:
        return _refuse(slug, f"draft status is '{status}', not '{require_status}': press Allow on "
                             "the board first (a gate PASS is required)", "guard")
    row = ledger.find_slug(ws, slug)
    if row is not None and row.get("state") != "failed":
        return _refuse(slug, f"'{slug}' is already in the ledger ({row.get('state')}); one draft, "
                             "one post", "guard")
    problem = gap_problem(ws, cfg, now)
    if problem:
        return _refuse(slug, problem, "guard")
    problem = stop_active(ws)
    if problem:
        return _refuse(slug, problem, "guard")
    # token and version before any model of the post is built
    cfg_dir = auth.secrets_dir(cfg)
    try:
        tok = auth.require_token(cfg_dir) if client is None else {"author": "urn:li:person:DEMO000000"}
        version, warns = versions.resolve(cfg, now.date() if now else None) if client is None else (client.version, [])
    except auth.AuthError as exc:
        return _refuse(slug, str(exc), "error")
    except versions.VersionError as exc:
        return _refuse(slug, str(exc), "error")
    gate = (gate_fn or default_gate)(slug, ws, True)
    if gate.get("summary") != "PASS":
        fails = gate.get("fails") or []
        return _refuse(slug, "the gate does not pass: " + "; ".join(str(f) for f in fails[:3]),
                       "gate", gate_fails=fails)
    problems = check_draft(d, cfg)
    if problems:
        return _refuse(slug, "; ".join(problems), "error")
    if client is None:
        client = api.Client(tok["access_token"], version, hp=api.host_policy(cfg),
                            timeout=float(cfg["linkedin"].get("timeout_s", 30)))
    author = tok["author"] if tok else "urn:li:person:DEMO000000"

    key = ledger.new_key(slug)
    base_row = {"slug": slug, "state": "pending", "idempotency_key": key,
                "started_at": ledger.now_iso(), "format": d.kind, "lang": d.meta.get("lang", "en"),
                "pillar": str(d.meta.get("pillar", "")), "title": str(d.meta.get("title", slug)),
                "automation": {"mode": "api_scheduled" if by == "due" else mode, "by": by,
                               "api_version": client.version}}
    if d.first_comment:
        base_row["first_comment"] = d.first_comment
        base_row["first_comment_state"] = "none"
    try:
        ledger.append(ws, base_row)           # step 5: nothing is sent unless this succeeds
    except ledger.LedgerError as exc:
        return _refuse(slug, f"ledger is not writable, nothing was sent: {exc}", "error")

    # media upload (a failure here is safe: the post itself was never sent)
    media: List[str] = []
    try:
        kind = "document" if d.kind == "document" else "image"
        for asset in d.assets:
            media.append(client.upload(kind, author, asset.read_bytes()))
    except (HttpError, api.ApiError) as exc:
        if getattr(exc, "status", None) == 429:
            write_stop(ws, "429", 3600)
        return _fail(ws, key, slug, f"upload failed before posting: {exc}", exc, hold=False)
    body = build_body(d, author, cfg, media)

    try:
        resp, urn = client.create_post(body)
    except HttpError as exc:
        if exc.status == 429:
            retry = _retry_after(exc)
            write_stop(ws, "429", retry)
            return _fail(ws, key, slug, "LinkedIn answered 429; the run stops", exc, hold=False,
                         status="stopped")
        if _not_sent(exc):
            return _fail(ws, key, slug, f"the request never left: {exc}", exc, hold=False)
        return _needs_check(ws, key, slug, d, f"no answer was read after sending ({exc})")
    if resp.status in (401, 403):
        write_stop(ws, str(resp.status), 24 * 3600 if resp.status == 403 else 3600)
        return _fail(ws, key, slug, f"LinkedIn refused the post ({resp.status}): "
                                    f"{resp.text()[:200]}", None, hold=True)
    if resp.status >= 400:
        return _fail(ws, key, slug, f"LinkedIn rejected the post ({resp.status}): "
                                    f"{resp.text()[:200]}", None, hold=True)
    if not urn:
        return _needs_check(ws, key, slug, d, f"LinkedIn answered {resp.status} without a post id")

    # step 7: complete the row first, everything else after it
    posted_at = ledger.now_iso()
    url = f"https://www.linkedin.com/feed/update/{urn}/"
    done = {"state": "posted", "urn": urn, "url": url, "posted_at": posted_at}
    last_exc: Optional[Exception] = None
    for attempt in range(3):
        try:
            ledger.update(ws, key, **done)
            last_exc = None
            break
        except ledger.LedgerError as exc:
            last_exc = exc
            time.sleep(0.2 * (attempt + 1))
    if last_exc is not None:
        atomic_write_json(ws / RECOVERY_REL, {"slug": slug, "key": key, **done})
        notify("nj-linkedin: post is live but not recorded",
               f"'{slug}' is live at {url}; the ledger could not be written. See {RECOVERY_REL}.", ws)
        return Outcome("needs_check", f"the post is live ({url}) but the ledger write failed: {last_exc}",
                       slug, "error", urn, url)
    first_state, first_note = social_extra.maybe_first_comment(ws, cfg, client, urn, d.first_comment,
                                                               author)
    if first_state != "none":
        try:
            ledger.update(ws, key, first_comment_state=first_state,
                          **({"first_comment_note": first_note} if first_note else {}))
        except ledger.LedgerError:
            pass
    try:
        _meta_set(d.dir, status="posted", posted_at=posted_at, urn=urn, url=url)
    except (OSError, ValueError):
        pass
    try:
        _report_row(ws, posted_at, str(d.meta.get("title", slug)), url)
    except OSError:
        pass
    return Outcome("posted", "posted", slug, "", urn, url,
                   {"first_comment_state": first_state, "first_comment_note": first_note,
                    "first_comment_manual": bool(d.first_comment and first_state != "posted")})


def _retry_after(exc: HttpError) -> float:
    try:
        value = float((exc.response.headers if exc.response else {}).get("retry-after", ""))
    except (TypeError, ValueError):
        value = 3600.0
    return max(900.0, min(value, 24 * 3600.0))


def _fail(ws: Path, key: str, slug: str, reason: str, exc: Optional[BaseException], *,
          hold: bool, status: str = "failed") -> Outcome:
    try:
        ledger.update(ws, key, state="failed", error=reason[:400])
    except ledger.LedgerError:
        pass
    if hold:
        try:
            _meta_set(Path(ws) / "drafts" / slug, status="hold", hold_reason=reason[:200])
        except (OSError, ValueError):
            pass
        notify("nj-linkedin: post refused", f"'{slug}' was not posted: {reason[:160]}", ws)
    return Outcome(status, reason, slug, "error")


def _needs_check(ws: Path, key: str, slug: str, d: Draft, reason: str) -> Outcome:
    try:
        ledger.update(ws, key, state="needs_check", error=reason[:400], checked_at=ledger.now_iso())
    except ledger.LedgerError:
        pass
    try:
        _meta_set(d.dir, status="needs_check")
    except (OSError, ValueError):
        pass
    notify("nj-linkedin: check a post",
           f"'{slug}' may be live ({reason[:120]}). Look at LinkedIn, then confirm on the board.", ws)
    return Outcome("needs_check", reason + "; it will not be reposted. Confirm on the board "
                   "or with 'njli post --resolve'.", slug, "error")


# ------------------------------------------------------------------ human confirmation

def resolve_needs_check(ws: Path, slug: str, posted: bool, url: Optional[str] = None,
                        urn: Optional[str] = None) -> Dict[str, Any]:
    """The human says whether a ``needs_check`` post went out. No network call is made."""
    ws = Path(ws)
    lock = FileLock(ws / LOCK_REL, stale_after=1800)
    with lock:
        row = ledger.find_slug(ws, slug)
        if row is None or row.get("state") != "needs_check":
            raise ValueError(f"'{slug}' is not waiting for a check")
        folder = ws / "drafts" / slug
        if posted:
            changes: Dict[str, Any] = {"state": "confirmed", "confirmed_at": ledger.now_iso()}
            if urn:
                changes["urn"] = urn
            if url:
                changes["url"] = url
            if "posted_at" not in row:
                changes["posted_at"] = row.get("started_at", ledger.now_iso())
            ledger.update(ws, row["idempotency_key"], **changes)
            if folder.is_dir():
                _meta_set(folder, status="posted", **({"url": url} if url else {}))
        else:
            ledger.update(ws, row["idempotency_key"], state="failed",
                          error="the human confirmed it was not posted")
            if folder.is_dir():
                _meta_set(folder, status="draft")
    return ledger.find_slug(ws, slug) or {}
