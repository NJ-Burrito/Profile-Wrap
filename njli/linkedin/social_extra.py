"""The experimental extra: comments through LinkedIn's legacy social-actions route.

NOT part of the core promise. The route is undocumented and may be closed at any time (the
versioned replacement needs partner approval). Everything here is off unless ALL of these hold:

  * the extra is installed (``njli extras install comments-api`` writes the marker file);
  * ``engagement.comments.mode`` is ``api`` and the typed ``comments_api`` acknowledgement is valid
    (``config.effective_modes`` downgrades it to ``draft`` otherwise);
  * a ``selftest comments`` pass younger than 30 days says the route is reachable;
  * the comments kill switch is not set and today's count is under the cap (at most 10).

A 403 turns the mode back to draft by invalidating the selftest record. Likes are never sent from
here. The README never claims this works.
"""
from __future__ import annotations

import datetime as _dt
import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from .. import config as config_mod
from .. import limits, paths, policy
from ..atomic import atomic_write_json
from ..fsutil import append_jsonl, read_json, read_jsonl
from ..http import HttpError
from . import api

ROUTE = "/v2/socialActions"
RECORD_REL = Path("work") / "selftest-comments.json"
LOG_REL = Path("published") / "comments.jsonl"
MARKER = ("extras", "comments-api", "installed.json")
RECORD_MAX_AGE_DAYS = 30
PROBE_TARGET = "urn:li:activity:0"   # an id that cannot exist: the probe can never reach a real post


def marker_path() -> Path:
    return paths.data_dir().joinpath(*MARKER)


def installed() -> bool:
    return marker_path().is_file()


def read_record(ws: Path) -> Dict[str, Any]:
    try:
        rec = read_json(Path(ws) / RECORD_REL, default={})
    except ValueError:
        return {}
    return rec if isinstance(rec, dict) else {}


def write_record(ws: Path, result: str, status: Optional[int], note: str) -> Dict[str, Any]:
    rec = {"at": time.time(), "at_iso": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
           "result": result, "status": status, "note": note}
    atomic_write_json(Path(ws) / RECORD_REL, rec)
    return rec


def record_fresh(ws: Path, now: Optional[float] = None) -> bool:
    rec = read_record(ws)
    if rec.get("result") != "reachable":
        return False
    return ((now if now is not None else time.time()) - float(rec.get("at", 0))) < RECORD_MAX_AGE_DAYS * 86400


def comments_today(ws: Path) -> int:
    rows, _bad = read_jsonl(Path(ws) / LOG_REL)
    today = _dt.date.today().isoformat()
    return sum(1 for r in rows if str(r.get("at", ""))[:10] == today)


def enabled(ws: Path, cfg: Dict[str, Any]) -> Tuple[bool, str]:
    """(on, reason). Reads configuration and local files only; makes no request."""
    if not installed():
        return False, "the comments-api extra is not installed"
    if config_mod.effective_modes(cfg, ws)["comments"] != "api":
        return False, "engagement.comments.mode is not 'api' with a valid acknowledgement"
    if limits.is_paused(Path(ws), "comments"):
        return False, "comments are paused"
    if not record_fresh(ws):
        return False, "no recent 'njli selftest comments' pass (needed every 30 days)"
    cap = min(int(cfg["engagement"]["comments"]["daily_cap"]), policy.COMMENTS_REPLIES_PER_DAY_MAX)
    if comments_today(ws) >= cap:
        return False, f"today's comment cap of {cap} is used"
    return True, "enabled"


def create_comment(client: api.Client, target: str, actor: str, text: str,
                   parent: Optional[str] = None) -> Optional[str]:
    """One comment (or a reply when ``parent`` is given). Returns the comment id.

    Raises ``ApiError`` with status 403 when the route is closed to this app.
    """
    body: Dict[str, Any] = {"actor": actor, "object": target, "message": {"text": text}}
    if parent:
        body["parentComment"] = parent
    where = parent or target
    try:
        resp = client.call("POST", f"{ROUTE}/{urllib.parse.quote(where, safe='')}/comments",
                           extra_endpoints=(ROUTE,), json_body=body, stop_on=(429, 403))
    except HttpError as exc:
        raise api.ApiError(str(exc), exc.status) from exc
    if not resp.ok:
        raise api.ApiError(f"comment answered {resp.status}", resp.status, resp.text()[:200])
    return resp.headers.get("x-restli-id")


def maybe_first_comment(ws: Path, cfg: Dict[str, Any], client: api.Client, urn: str,
                        text: str, actor: str) -> Tuple[str, str]:
    """(first_comment_state, note) for the ledger. Never undoes the post, never raises."""
    if not text:
        return "none", ""
    on, why = enabled(ws, cfg)
    if not on:
        return "none", f"first comment left for you to post by hand ({why})"
    try:
        cid = create_comment(client, urn, actor, text)
    except api.ApiError as exc:
        if exc.status == 403:
            write_record(ws, "disabled", 403, "closed to this app; comments are back to draft")
        return "failed", f"first comment failed: {exc}"
    except Exception as exc:  # the post is live: any failure here is logged, not raised
        return "failed", f"first comment failed: {exc}"
    try:
        append_jsonl(Path(ws) / LOG_REL, {"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                                          "post": urn, "comment": cid, "kind": "first_comment"})
    except OSError:
        pass
    return "posted", ""


def probe(client: api.Client, ws: Path) -> Dict[str, Any]:
    """A non-posting probe: an invalid body aimed at an id that cannot exist.

    403 means the route is closed to this app (disabled). 400 or 422 means the route is reachable,
    which is NOT proof that comments are permitted. Anything else is reported as unknown.
    No comment is ever created by this call.
    """
    path = f"{ROUTE}/{urllib.parse.quote(PROBE_TARGET, safe='')}/comments"
    resp = client.call("POST", path, extra_endpoints=(ROUTE,), stop_on=(429,),
                       body=json.dumps({}).encode("utf-8"),
                       headers={"Content-Type": "application/json"})
    if resp.status == 403:
        return write_record(ws, "disabled", 403, "partner-only or closed; comments stay in draft mode")
    if resp.status in (400, 422):
        return write_record(ws, "reachable", resp.status,
                            "reachable, not proven permitted: the first real comment may still be refused")
    if resp.status in (404,):
        return write_record(ws, "reachable", resp.status, "route answered for an unknown object")
    return write_record(ws, "unknown", resp.status, f"unexpected answer {resp.status}")
