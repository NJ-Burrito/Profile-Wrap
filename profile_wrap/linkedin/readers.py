"""Reading providers that find other people's recent posts, and the order they are used in.

Two free tools that complement each other, and the free public pages as the last resort:

    reading.providers = ["apify", "tavily", "public"]      (any subset, in this order; "public" always last)

  * Apify  first. Same-day posts. Its free monthly credit is paced: today's allowance is
    (credit left at the start of today - reserve) / days left in the Apify billing cycle, so the credit lasts
    the cycle. When the allowance is used up, or Apify says the credit is gone, Apify rests until tomorrow
    (or until the cycle ends) and the next reader takes over.
  * Tavily fills the targets and days Apify does not cover. A web search that finds posts a few days late.
    1,000 free credits a month, 100 held back, paced by the same rolling formula per calendar month.
    Full post text is fetched one URL per call (1 credit each); a search is cached for 3 days.
  * public: the guest pages, see ``public_reader`` (2 profile pages per run, spaced, 12 a day).

Every call goes through ``profile_wrap.http`` so the host policy applies: api.apify.com and api.tavily.com are
reachable only with their own typed acknowledgement. Keys are read from the environment variable NAMED in the
config and are never stored, logged or returned. Ledgers live in ``<workspace>/data/``. A ledger that cannot be
read fails closed (that reader is off); it is never reset to zero.

Nothing here posts, comments or likes.
"""
from __future__ import annotations

import calendar
import json
import math
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import quote

from .. import config as config_mod
from .. import http, policy
from ..atomic import atomic_write_json
from ..fsutil import read_json
from . import public_reader

ACTIVITY = re.compile(r"activity-(\d{19})")
MAX_AGE_H = 168
APIFY_BASE = "https://api.apify.com/v2"
TAVILY_BASE = "https://api.tavily.com"
Requester = Callable[..., http.Response]


class ReaderUnavailable(Exception):
    """This reader cannot answer now (no ack, no key, allowance used, ledger unreadable, service error).
    ``kind``: no_ack, no_key, allowance, exhausted, ledger, service, unusable."""

    def __init__(self, kind: str, message: str):
        super().__init__(message)
        self.kind = kind


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso_ts(value: Any) -> Optional[datetime]:
    try:
        d = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def post_ms(url: str) -> int:
    """LinkedIn activity ids carry the post time: (id >> 22) milliseconds."""
    m = ACTIVITY.search(url or "")
    return (int(m.group(1)) >> 22) if m else 0


def slug_of(profile_url: str) -> str:
    return (profile_url or "").rstrip("/").split("/in/")[-1].split("?")[0]


def _read_state(path: Path) -> Dict[str, Any]:
    try:
        st = read_json(path, default={})
    except ValueError:
        return {}
    return st if isinstance(st, dict) else {}


# ------------------------------------------------------------------------------------------------- Apify

class ApifyReader:
    """Apify, paced so the free monthly credit lasts the whole billing cycle."""

    def __init__(self, cfg: Dict[str, Any], workspace: Path, *, ack_valid: bool,
                 now: Callable[[], datetime] = utcnow, request: Requester = http.request,
                 env: Optional[Dict[str, str]] = None) -> None:
        a = cfg["engagement"]["reading"]["apify"]
        self.ack_valid = bool(ack_valid)
        self.token_env = a["token_env"]
        self.actor = a.get("actor") or ""
        self.max_calls = int(a["max_calls_per_day"])
        self.cost = float(a.get("cost_per_call_usd", 0.01))
        self.reserve = float(a.get("reserve_usd", policy.APIFY_RESERVE_USD))
        self.path = Path(workspace) / "data" / "apify_budget.json"
        self._now, self._request = now, request
        self._env = os.environ if env is None else env
        self.hp = http.HostPolicy(apify_ack=self.ack_valid)

    # -- credit and pacing
    def _token(self) -> str:
        tok = self._env.get(self.token_env, "")
        if not tok:
            raise ReaderUnavailable("no_key", f"environment variable {self.token_env} is not set")
        return tok

    def _auth(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self._token()}"}

    def fetch_limits(self) -> Tuple[float, Optional[str]]:
        """(credit left in USD, billing cycle end). A free call. Raises ReaderUnavailable."""
        try:
            resp = self._request("GET", f"{APIFY_BASE}/users/me/limits", headers=self._auth(),
                                 hp=self.hp, timeout=30)
            data = resp.json().get("data", {})
            cap = float(data["limits"]["maxMonthlyUsageUsd"])
            used = float(data["current"]["monthlyUsageUsd"])
            return max(cap - used, 0.0), (data.get("monthlyUsageCycle") or {}).get("endAt")
        except http.HttpError as exc:
            raise ReaderUnavailable("service", f"Apify credit not readable: {exc.kind}") from exc
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise ReaderUnavailable("service", "Apify credit answer not readable") from exc

    def _days_left(self, now: datetime, cycle_end: Optional[str]) -> int:
        end = _iso_ts(cycle_end) if cycle_end else None
        if end is not None and end > now:
            return max(1, math.ceil((end - now).total_seconds() / 86400))
        return calendar.monthrange(now.year, now.month)[1] - now.day + 1

    def _day_state(self) -> Dict[str, Any]:
        """Today's state. A new day (or a new billing cycle) reads the credit once, free of charge."""
        now = self._now()
        today, st = f"{now:%Y-%m-%d}", _read_state(self.path)
        end = _iso_ts(st.get("cycle_end")) if st.get("cycle_end") else None
        new_cycle = end is not None and now >= end
        if st.get("day") == today and not new_cycle:
            return st
        carried = st.get("exhausted_until") if not new_cycle else None
        try:
            left, cycle_end = self.fetch_limits()
        except ReaderUnavailable:
            if st.get("day_start") is None or new_cycle:
                raise
            # not readable: assume what yesterday's allowance left (calls counted at the estimated price)
            left = max(0.0, float(st["day_start"]) - int(st.get("calls", 0)) * self.cost)
            cycle_end = st.get("cycle_end")
        st = {"day": today, "day_start": left, "calls": 0, "cycle_end": cycle_end,
              "exhausted_until": carried}
        if left < self.reserve + self.cost:
            st["exhausted_until"] = cycle_end or (now + timedelta(hours=24)).isoformat()
        atomic_write_json(self.path, st)
        return st

    def calls_left(self) -> int:
        """Apify calls still allowed today (0 when resting)."""
        now = self._now()
        st = self._day_state()
        rest = _iso_ts(st.get("exhausted_until")) if st.get("exhausted_until") else None
        if rest is not None and rest > now:
            return 0
        daily_usd = max(0.0, (float(st["day_start"]) - self.reserve) / self._days_left(now, st.get("cycle_end")))
        allowed = min(self.max_calls, int(daily_usd / self.cost + 1e-9))
        return max(0, allowed - int(st.get("calls", 0)))

    def status_local(self) -> str:
        """What the ledger on disk says, without any network call (used by doctor)."""
        st = _read_state(self.path)
        if st.get("day") != f"{self._now():%Y-%m-%d}" or st.get("day_start") is None:
            return "credit is read once on the first use each day (a free call)"
        return (f"{max(0, int(self.max_calls) - int(st.get('calls', 0)))} call(s) at most left today, "
                f"credit at the start of today ${float(st['day_start']):.2f}")

    def status(self) -> str:
        try:
            n = self.calls_left()
        except ReaderUnavailable as exc:
            return f"credit unknown ({exc})"
        st = _read_state(self.path)
        return f"{n} call(s) left today, credit at the start of today ${float(st.get('day_start', 0)):.2f}"

    # -- the read
    def profile_posts(self, target: Dict[str, Any]) -> List[Dict[str, Any]]:
        if not self.ack_valid:
            raise ReaderUnavailable("no_ack", "Apify reading needs a valid 'profile-wrap config ack apify'")
        if not self.actor:
            raise ReaderUnavailable("unusable", "engagement.reading.apify.actor is not set")
        headers = self._auth()
        if self.calls_left() < 1:
            raise ReaderUnavailable("allowance", "today's Apify allowance is used")
        st = _read_state(self.path)
        st["calls"] = int(st.get("calls", 0)) + 1          # counted before the call: a failed call may still cost
        atomic_write_json(self.path, st)
        slug = slug_of(target["profile_url"])
        try:
            resp = self._request("POST", f"{APIFY_BASE}/acts/{quote(self.actor, safe='~')}/run-sync-get-dataset-items",
                                 headers=headers, hp=self.hp, timeout=300,
                                 json_body={"username": slug, "limit": 2, "total_posts": 2})
        except http.HttpError as exc:
            raise ReaderUnavailable("service", f"Apify call failed: {exc.kind}") from exc
        if resp.status in (402, 403) and (resp.status == 402 or any(
                w in resp.text().lower() for w in ("limit", "usage", "credit", "exceed"))):
            st["exhausted_until"] = st.get("cycle_end") or (self._now() + timedelta(hours=24)).isoformat()
            atomic_write_json(self.path, st)
            raise ReaderUnavailable("exhausted", "Apify says the monthly credit is used up")
        if not resp.ok:
            raise ReaderUnavailable("service", f"Apify answered {resp.status}")
        try:
            items = resp.json()
            if not isinstance(items, list):
                raise ValueError("not a list")
        except ValueError as exc:
            raise ReaderUnavailable("unusable", "Apify answer not readable") from exc
        return [_from_apify(p) for p in items if isinstance(p, dict)]


def _from_apify(p: Dict[str, Any]) -> Dict[str, Any]:
    a = p.get("author") or {}
    ts = (p.get("posted_at") or {}).get("timestamp")
    url = p.get("url") or ""
    return {"url": url, "urn": p.get("full_urn") or "", "ts": int(ts) if isinstance(ts, (int, float)) else post_ms(url),
            "text": p.get("text") or "", "author": f"{a.get('first_name', '')} {a.get('last_name', '')}".strip(),
            "source": "apify"}


# ------------------------------------------------------------------------------------------------- Tavily

class TavilyReader:
    """Tavily search + one-URL extract, paced so the free credits last the calendar month."""

    def __init__(self, cfg: Dict[str, Any], workspace: Path, *, ack_valid: bool,
                 now: Callable[[], datetime] = utcnow, request: Requester = http.request,
                 env: Optional[Dict[str, str]] = None) -> None:
        t = cfg["engagement"]["reading"]["tavily"]
        self.ack_valid = bool(ack_valid)
        self.key_env, self.topic = t["key_env"], t.get("topic") or ""
        self.month_credits, self.reserve = int(t["month_credits"]), int(t["reserve_credits"])
        self.cache_days = int(t["cache_days"])
        data = Path(workspace) / "data"
        self.ledger_path, self.cache_path = data / "tavily_usage.json", data / "tavily_cache.json"
        self._now, self._request = now, request
        self._env = os.environ if env is None else env
        self.hp = http.HostPolicy(tavily_ack=self.ack_valid)

    # -- ledger and pacing
    def _ledger(self) -> Dict[str, Any]:
        """The ledger. Missing = empty; unreadable = fail closed (never reset to zero)."""
        if not self.ledger_path.exists():
            return {"calls": []}
        try:
            led = json.loads(self.ledger_path.read_text(encoding="utf-8"))
            rows = led["calls"]
            if not isinstance(rows, list) or not all(
                    isinstance(r, dict) and isinstance(r.get("credits"), int) for r in rows):
                raise ValueError("bad rows")
            return led
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise ReaderUnavailable("ledger", f"Tavily ledger unreadable ({type(exc).__name__}): "
                                    f"{self.ledger_path.name}") from exc

    def _log(self, kind: str, credits: int, target: str) -> None:
        led = self._ledger()
        led["calls"].append({"date": f"{self._now():%Y-%m-%d}", "kind": kind, "credits": credits, "target": target})
        atomic_write_json(self.ledger_path, led)

    def used(self) -> Tuple[int, int]:
        """(credits used this calendar month, used today). Only this month's rows count, so it resets itself."""
        now = self._now()
        month, day = f"{now:%Y-%m}", f"{now:%Y-%m-%d}"
        rows = self._ledger()["calls"]
        return (sum(r["credits"] for r in rows if str(r.get("date", "")).startswith(month)),
                sum(r["credits"] for r in rows if r.get("date") == day))

    def allowance(self) -> float:
        """(month credits - reserve - used before today) / days left in the month, today included."""
        now = self._now()
        m, d = self.used()
        left = calendar.monthrange(now.year, now.month)[1] - now.day + 1
        return (self.month_credits - self.reserve - (m - d)) / left

    def remaining_today(self) -> int:
        """Credits still spendable today: never past today's allowance, never into the reserve."""
        m, d = self.used()
        return max(0, min(int(self.allowance() - d + 1e-9), self.month_credits - self.reserve - m))

    def status(self) -> str:
        try:
            m, d = self.used()
        except ReaderUnavailable as exc:
            return f"credits unknown ({exc})"
        return (f"credits used today {d}, allowance {self.allowance():.1f}, "
                f"month {m}/{self.month_credits - self.reserve}")

    # -- the two spending calls
    def _call(self, path: str, body: Dict[str, Any], kind: str, label: str) -> Dict[str, Any]:
        if not self.ack_valid:
            raise ReaderUnavailable("no_ack", "Tavily reading needs a valid 'profile-wrap config ack tavily'")
        key = self._env.get(self.key_env, "")
        if not key:
            raise ReaderUnavailable("no_key", f"environment variable {self.key_env} is not set")
        if self.remaining_today() < 1:
            raise ReaderUnavailable("allowance", "today's Tavily allowance is used")
        try:
            resp = self._request("POST", f"{TAVILY_BASE}{path}", headers={"Authorization": f"Bearer {key}"},
                                 hp=self.hp, timeout=90, json_body=body)
        except http.HttpError as exc:
            if exc.maybe_sent:
                self._log(kind, 1, label)       # the call started, so it may have been billed
            raise ReaderUnavailable("service", f"Tavily call failed: {exc.kind}") from exc
        if resp.status in (401, 403):
            raise ReaderUnavailable("no_key", f"Tavily refused the key ({resp.status})")
        self._log(kind, 1, label)
        if not resp.ok:
            raise ReaderUnavailable("service", f"Tavily answered {resp.status}")
        try:
            data = resp.json()
        except ValueError as exc:
            raise ReaderUnavailable("unusable", "Tavily answer not readable") from exc
        if not isinstance(data, dict):
            raise ReaderUnavailable("unusable", "Tavily answer is not an object")
        return data

    def _cache(self) -> Dict[str, Any]:
        return _read_state(self.cache_path)

    def cached(self, slug: str) -> Optional[List[Dict[str, Any]]]:
        e, now = self._cache().get(slug), self._now()
        when = _iso_ts(e.get("last_searched")) if isinstance(e, dict) else None
        if when is None or now - when >= timedelta(days=self.cache_days):
            return None
        return [p for p in e.get("posts", []) if isinstance(p, dict) and isinstance(p.get("ts"), (int, float))
                and now.timestamp() * 1000 - p["ts"] <= MAX_AGE_H * 3600 * 1000]

    def search_posts(self, target: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], int]:
        """(posts newest first, credits spent). A target searched within ``cache_days`` costs nothing.
        An empty list is only 'nothing found by this search', never a sign the person is inactive."""
        slug = slug_of(target["profile_url"])
        hit = self.cached(slug)
        if hit is not None:
            return hit, 0
        if not target.get("name"):
            raise ReaderUnavailable("unusable", "no person name to search for (give one with --name)")
        query = " ".join(x for x in (target.get("name", ""), target.get("topic") or self.topic, "linkedin") if x)
        data = self._call("/search", {"query": query, "topic": "news", "time_range": "week", "max_results": 10},
                          "search", target.get("name", slug))
        results = data.get("results")
        posts = self.own_posts(results if isinstance(results, list) else [], slug)
        cache = self._cache()
        cache[slug] = {"last_searched": self._now().isoformat(), "posts": posts}
        atomic_write_json(self.cache_path, cache)
        return posts, 1

    def own_posts(self, results: List[Any], slug: str) -> List[Dict[str, Any]]:
        """Keep /posts/<slug>_ results younger than a week, newest first. Time comes from the activity id."""
        now, out, seen = self._now(), [], set()
        for r in results:
            url = (r.get("url") or "") if isinstance(r, dict) else ""
            ts = post_ms(url)
            if f"/posts/{slug}_".lower() not in url.lower() or not ts or url in seen \
                    or now.timestamp() * 1000 - ts > MAX_AGE_H * 3600 * 1000:
                continue
            seen.add(url)
            out.append({"url": url, "urn": "urn:li:activity:" + ACTIVITY.search(url).group(1), "ts": ts,
                        "snippet": r.get("content", ""), "text": "", "author": "", "source": "tavily"})
        return sorted(out, key=lambda p: -p["ts"])

    def extract_texts(self, posts: List[Dict[str, Any]]) -> int:
        """Fill ``text`` for posts that have none: ONE url per call, 1 credit each (several urls in one call fail
        on the current CLI and are never sent). Stops at the daily allowance. Returns credits spent."""
        spent = 0
        for p in posts:
            if not isinstance(p, dict) or p.get("text") or p.get("no_text"):
                continue
            if self.remaining_today() < 1:
                break
            try:
                data = self._call("/extract", {"urls": p["url"]}, "extract", p["url"].split("/posts/")[-1][:60])
            except ReaderUnavailable as exc:
                p["extract_failed"] = str(exc)[:80]
                if exc.kind in ("ledger", "no_ack", "no_key"):
                    break
                continue
            spent += 1
            results = data.get("results")
            raw = next((r.get("raw_content", "") for r in (results if isinstance(results, list) else [])
                        if isinstance(r, dict) and r.get("url") == p["url"]), "")
            p["text"] = strip_guest_header(raw if isinstance(raw, str) else "")
            p["no_text"] = not p["text"]
            self._remember_text(p)
        return spent

    def _remember_text(self, post: Dict[str, Any]) -> None:
        """Keep a bought text in the search cache, so the same post is never extracted (and paid for) twice."""
        cache = self._cache()
        changed = False
        for entry in cache.values():
            for q in (entry.get("posts", []) if isinstance(entry, dict) else []):
                if isinstance(q, dict) and q.get("url") == post.get("url"):
                    q["text"], q["no_text"] = post.get("text", ""), bool(post.get("no_text"))
                    changed = True
        if changed:
            atomic_write_json(self.cache_path, cache)


def strip_guest_header(raw: str) -> str:
    """LinkedIn's guest page: banner, '# title', author line, the post, 'To view or add a comment', other people's posts."""
    m = re.search(r"^# .*$", raw or "", re.M)
    body = (raw or "")[m.end():] if m else (raw or "")
    body = re.sub(r"^\s*!\[View profile for[^\n]*\n", "", body.lstrip("\n"))
    for stop in ("To view or add a comment", "## More Relevant Posts"):
        i = body.find(stop)
        if i != -1:
            body = body[:i]
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body)
    body = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", body)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# ------------------------------------------------------------------------------------------------- the chain

class ReadResult(dict):
    """posts, source (which reader answered), notes (why earlier readers were skipped), clean_empty."""


class ReadingChain:
    """Apify, then Tavily, then the public pages, whichever the user switched on, in that order.

    A reader that cannot answer (allowance used, no key, error) hands over to the next one. A reader that answers
    with an empty list ends the search for that person: a quiet person is never paid for twice.
    """

    def __init__(self, order: List[str], readers: Dict[str, Any]) -> None:
        self.order, self.readers = order, readers

    def profile_posts(self, target: Dict[str, Any]) -> ReadResult:
        notes: List[str] = []
        for name in self.order:
            reader = self.readers[name]
            try:
                if name == "tavily":
                    posts, _ = reader.search_posts(target)
                elif name == "public":
                    posts = [_from_public(p) for p in reader.profile_posts(slug_of(target["profile_url"]))]
                else:
                    posts = reader.profile_posts(target)
            except (ReaderUnavailable, public_reader.PublicReadError) as exc:
                notes.append(f"{name}: {exc}")
                continue
            if posts:
                return ReadResult(posts=posts, source=name, notes=notes, clean_empty=False)
            if name != "public":
                return ReadResult(posts=[], source=name, notes=notes, clean_empty=True)
            notes.append("public: page had no readable posts")
        return ReadResult(posts=[], source=None, notes=notes, clean_empty=False)

    def fill_text(self, posts: List[Dict[str, Any]]) -> int:
        """Full text for Tavily-found posts (one url per call). Other sources already carry their text."""
        tav = self.readers.get("tavily")
        todo = [p for p in posts if p.get("source") == "tavily"]
        return tav.extract_texts(todo) if tav is not None and todo else 0


def _from_public(p: Dict[str, Any]) -> Dict[str, Any]:
    when = _iso_ts(p.get("published"))
    url = p.get("url", "")
    return {"url": url, "urn": "", "ts": int(when.timestamp() * 1000) if when else post_ms(url),
            "text": p.get("text", ""), "author": p.get("author", ""), "source": "public"}


def build_chain(cfg: Dict[str, Any], workspace: Path, *, config_dir: Optional[Path] = None,
                root: Optional[Path] = None, **kw: Any) -> ReadingChain:
    """The chain for this workspace: only providers whose acknowledgement matches the current risk text."""
    modes = config_mod.effective_modes(cfg, Path(workspace), config_dir, root)
    order = list(modes["reading_chain"])
    readers: Dict[str, Any] = {}
    if "apify" in order:
        readers["apify"] = ApifyReader(cfg, workspace, ack_valid=True, **kw)
    if "tavily" in order:
        readers["tavily"] = TavilyReader(cfg, workspace, ack_valid=True, **kw)
    if "public" in order:
        readers["public"] = public_reader.PublicReader(cfg, Path(workspace), ack_valid=True)
    return ReadingChain(order, readers)
