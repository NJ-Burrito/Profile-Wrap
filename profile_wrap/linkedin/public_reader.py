"""Free "public" reading provider: read LinkedIn pages that anyone can open without signing in.

Opt-in (``engagement.reading.provider = "public"``, typed acknowledgement ``profile-wrap config ack public``).
It reads three things, always with a plain GET:

    post_stats(url)      -> {"reactions": n, "comments": n} or {"error": ...}
    post_comments(url)   -> [{"comment_id", "text", "author", "source": "public", ...}]
    profile_posts(slug)  -> [{"url", "author", "published", "text", "reactions", "comments", "source": "public"}]

Polite by construction: a gap of at least 3 s between pages, a daily page cap (default 30, kept in
``data/public_reader.json``), the same neutral profile-wrap User-Agent as every other call (never disguised, never rotated), no Referer, no login state, no
login, no proxy, no redirects. HTTP 999, 429 or 403 on a post page stops the reader for the rest of the day:
nothing is retried or pushed. Guest PROFILE pages are rate-limited per IP by LinkedIn, so they have their own,
stricter limits (2 per run, 20 minutes apart, 12 a day, kept across runs) and a 999 on one pauses profile
reads for 6 hours. Every request goes through ``profile_wrap.http`` so the host policy still applies.
This is reading the public page, which the LinkedIn User Agreement restricts; see docs/TERMS-AND-RISK.md.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.parse import quote, urlsplit

from .. import http, policy
from ..atomic import atomic_write_json
from ..fsutil import read_json

HEADERS = {"Accept": "text/html,application/xhtml+xml",
           "Accept-Language": "en-US,en;q=0.9"}
BASE = "https://www.linkedin.com"
LD = re.compile(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>', re.S)
SLUG = re.compile(r"^[\w%.\-]{1,100}$")


class PublicReadError(Exception):
    """A refusal or a stop; ``kind`` is one of: no_ack, limit, blocked, bad_url, unreadable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def _ld_objects(page: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for raw in LD.findall(page or ""):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        for x in (data if isinstance(data, list) else [data]):
            if isinstance(x, dict):
                out.append(x)
                graph = x.get("@graph")
                if isinstance(graph, list):
                    out.extend(g for g in graph if isinstance(g, dict))
    return out


def _counts(ld: Dict[str, Any]) -> Dict[str, int]:
    likes = comments = None
    stats = ld.get("interactionStatistic") or []
    if isinstance(stats, dict):
        stats = [stats]
    if not isinstance(stats, list):
        raise PublicReadError("unreadable", "page data has an unexpected shape")
    for s in stats:
        if not isinstance(s, dict):
            raise PublicReadError("unreadable", "page data has an unexpected shape")
        kind = str(s.get("interactionType", "")).rsplit("/", 1)[-1]
        n = s.get("userInteractionCount")
        if kind == "LikeAction":
            likes = n
        elif kind == "CommentAction":
            comments = n
    if comments is None:
        comments = ld.get("commentCount")
    try:
        return {"reactions": int(likes or 0), "comments": int(comments or 0)}
    except (TypeError, ValueError):
        return {"reactions": 0, "comments": 0}


def stats_from_page(page: str) -> Dict[str, Any]:
    for ld in _ld_objects(page):
        if ld.get("@type") == "SocialMediaPosting":
            return _counts(ld)
    return {"error": "post page not readable (public)"}


def comments_from_page(page: str) -> List[Dict[str, Any]]:
    for ld in _ld_objects(page):
        if ld.get("@type") != "SocialMediaPosting":
            continue
        out = []
        raw = ld.get("comment") or []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            raise PublicReadError("unreadable", "page data has an unexpected shape")
        for i, c in enumerate(raw):
            if not isinstance(c, dict):
                raise PublicReadError("unreadable", "page data has an unexpected shape")
            author = c.get("author") or {}
            if not isinstance(author, dict):
                raise PublicReadError("unreadable", "page data has an unexpected shape")
            item = {"comment_id": f"pub-{i}", "text": str(c.get("text") or "").strip(),
                    "author": {"name": author.get("name") or "", "profile_url": author.get("url") or ""},
                    "source": "public", "urn_known": False}
            if c.get("datePublished"):
                item["posted_at"] = c["datePublished"]
            out.append(item)
        return out
    return []


def posts_from_page(page: str) -> List[Dict[str, Any]]:
    """Recent posts of a public profile page (DiscussionForumPosting items in the JSON-LD @graph)."""
    out = []
    for ld in _ld_objects(page):
        if ld.get("@type") not in ("DiscussionForumPosting", "SocialMediaPosting"):
            continue
        author = ld.get("author") or {}
        if not isinstance(author, dict):
            raise PublicReadError("unreadable", "page data has an unexpected shape")
        item = {"url": ld.get("url") or "", "author": author.get("name") or "",
                "published": ld.get("datePublished") or "", "text": str(ld.get("text") or "").strip(),
                "source": "public"}
        item.update(_counts(ld))
        out.append(item)
    return out


class PublicReader:
    """Rate-limited reader. ``cfg`` is the profile-wrap config; ``workspace`` holds the daily counter."""

    def __init__(self, cfg: Dict[str, Any], workspace: Path, *, ack_valid: bool,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic,
                 today: Optional[Callable[[], str]] = None,
                 now: Callable[[], float] = time.time) -> None:
        pub = cfg["engagement"]["reading"].get("public") or {}
        self.ack_valid = bool(ack_valid)
        self.max_pages = int(pub.get("max_pages_per_day", policy.PUBLIC_READ_PAGES_PER_DAY_DEFAULT))
        self.gap = max(float(pub.get("gap_seconds", 0)), float(policy.PUBLIC_READ_GAP_SECONDS_FLOOR))
        self.profile_per_run = int(pub.get("profile_max_per_run", policy.PUBLIC_PROFILE_PER_RUN_DEFAULT))
        self.profile_per_day = int(pub.get("profile_max_per_day", policy.PUBLIC_PROFILE_PER_DAY_DEFAULT))
        self.profile_gap_s = 60.0 * max(float(pub.get("profile_gap_minutes", 0)),
                                        float(policy.PUBLIC_PROFILE_GAP_MINUTES_FLOOR))
        self._now = now
        self._profile_run = 0
        self.state_path = Path(workspace) / "data" / "public_reader.json"
        self._sleep, self._clock = sleep, clock
        self._today = today or (lambda: time.strftime("%Y-%m-%d"))
        self._last: Optional[float] = None
        self.hp = http.HostPolicy(public_ack=self.ack_valid)

    def _state(self) -> Dict[str, Any]:
        try:
            st = read_json(self.state_path, default={})
        except ValueError:
            st = {}
        if not isinstance(st, dict):
            st = {}
        if st.get("date") != self._today():   # daily counters reset; the profile spacing and pause persist
            st = {"date": self._today(), "pages": 0, "stopped": None, "profile_pages": 0,
                  "last_profile_at": st.get("last_profile_at"),
                  "profile_pause_until": st.get("profile_pause_until")}
        st.setdefault("profile_pages", 0)
        return st

    def profile_wait_seconds(self) -> float:
        """Seconds until the next profile page may be read (0 when allowed now)."""
        st, now = self._state(), self._now()
        waits = [0.0]
        if st.get("profile_pause_until"):
            waits.append(float(st["profile_pause_until"]) - now)
        if st.get("last_profile_at"):
            waits.append(float(st["last_profile_at"]) + self.profile_gap_s - now)
        return max(waits)

    def pages_left(self) -> int:
        return max(0, self.max_pages - int(self._state()["pages"]))

    def stopped(self) -> Optional[str]:
        return self._state().get("stopped")

    def fetch(self, url: str, profile: bool = False) -> str:
        if not self.ack_valid:
            raise PublicReadError("no_ack", "public reading needs a valid 'profile-wrap config ack public'")
        parts = urlsplit(url)
        if parts.scheme != "https" or (parts.hostname or "").lower() != "www.linkedin.com" \
                or not http.is_public_read_path(parts.path):
            raise PublicReadError("bad_url", "only public LinkedIn profile, post and feed pages over https")
        st = self._state()
        if st.get("stopped"):
            raise PublicReadError("blocked", f"stopped for today: {st['stopped']}")
        if st["pages"] >= self.max_pages:
            raise PublicReadError("limit", f"daily page limit reached ({self.max_pages})")
        if profile:
            if st.get("profile_pause_until") and float(st["profile_pause_until"]) > self._now():
                raise PublicReadError("paused", "profile reads are paused for a few hours after LinkedIn answered 999")
            if self._profile_run >= self.profile_per_run:
                raise PublicReadError("limit", f"at most {self.profile_per_run} profile pages per run")
            if st["profile_pages"] >= self.profile_per_day:
                raise PublicReadError("limit", f"daily profile page limit reached ({self.profile_per_day})")
            if st.get("last_profile_at") and float(st["last_profile_at"]) + self.profile_gap_s > self._now():
                raise PublicReadError("spacing", "profile pages are read at least "
                                      f"{int(self.profile_gap_s // 60)} minutes apart; try again later")
        if self._last is not None:
            wait = self.gap - (self._clock() - self._last)
            if wait > 0:
                self._sleep(wait)
        st["pages"] += 1                      # counted before the request: a failed page still costs
        if profile:
            st["profile_pages"] += 1
            st["last_profile_at"] = self._now()
            self._profile_run += 1
        atomic_write_json(self.state_path, st)
        self._last = self._clock()
        try:
            resp = http.request("GET", url, headers=dict(HEADERS), hp=self.hp,
                                stop_on=policy.PUBLIC_READ_STOP_STATUSES)
        except http.HttpError as exc:
            if exc.kind == "stop" and profile and exc.status == 999:
                st["profile_pause_until"] = self._now() + 3600.0 * policy.PUBLIC_PROFILE_PAUSE_HOURS
                atomic_write_json(self.state_path, st)
                raise PublicReadError("paused", "LinkedIn answered 999 for a profile page; profile reads "
                                      f"paused for {policy.PUBLIC_PROFILE_PAUSE_HOURS} hours") from exc
            if exc.kind == "stop":
                st["stopped"] = f"LinkedIn answered {exc.status}"
                atomic_write_json(self.state_path, st)
                raise PublicReadError("blocked", f"{st['stopped']}; reading stopped for today") from exc
            raise PublicReadError("unreadable", str(exc)) from exc
        if not resp.ok:
            raise PublicReadError("unreadable", f"page answered {resp.status}")
        return resp.text()

    def post_stats(self, url: str) -> Dict[str, Any]:
        try:
            return stats_from_page(self.fetch(url))
        except PublicReadError as exc:
            return {"error": str(exc), "kind": exc.kind}

    def post_comments(self, url: str) -> List[Dict[str, Any]]:
        return comments_from_page(self.fetch(url))

    def profile_posts(self, slug: str) -> List[Dict[str, Any]]:
        if not SLUG.match(slug or ""):
            raise PublicReadError("bad_url", "not a profile slug")
        return posts_from_page(self.fetch(f"{BASE}/in/{quote(slug, safe='%')}/", profile=True))


def for_config(cfg: Dict[str, Any], workspace: Path, **kw: Any) -> PublicReader:
    """Reader bound to the config, valid only while the acknowledgement matches the current risk text."""
    from .. import config
    valid = config.effective_modes(cfg, Path(workspace))["reading"] == "public"
    return PublicReader(cfg, Path(workspace), ack_valid=valid, **kw)
