"""The tool logic, free of any MCP types, so it can be tested directly and through a client.

Nothing here reads DMs or sends invitations. The one outbound path to LinkedIn is
``profile_wrap.linkedin.post.publish`` (called from ``post_allowed``); there is no second posting path.
"""
from __future__ import annotations

import datetime as _dt
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from profile_wrap import config as config_mod
from profile_wrap import ledger, limits
from profile_wrap.atomic import atomic_write_json, atomic_write_text
from profile_wrap.board.security import SLUG_RE
from profile_wrap.board.store import BoardStore
from profile_wrap.facts import registers as reg
from profile_wrap.fsutil import is_inside
from profile_wrap.gate.claims import facts_path
from profile_wrap.linkedin import auth, post
from profile_wrap.plan import calendar as cal_mod
from profile_wrap.providers import ProviderError, get_provider
from profile_wrap.providers import settings as prov_settings

MAX_POSTS_PER_DAY = 1
MAX_TOPIC = 400
MAX_CAPTION = 3000

# Review-board state names shown to the model. "allowed" is the board's "queued" (set only by a
# person pressing Allow, after a gate PASS).
STATE_NAMES = {"queued": "allowed", "draft": "draft", "revising": "revising", "hold": "hold",
               "missed": "missed", "needs_check": "needs_check", "posted": "posted",
               "rejected": "rejected", "demo": "demo"}


@dataclass
class Context:
    ws: Path
    gate_fn: Optional[Callable[..., Dict[str, Any]]] = None      # default: the real gate
    client: Any = None                                           # default: a real LinkedIn client
    provider_factory: Callable[..., Any] = get_provider
    now: Optional[Callable[[], _dt.datetime]] = None
    extra: Dict[str, Any] = field(default_factory=dict)

    def cfg(self) -> Dict[str, Any]:
        return config_mod.load(self.ws)

    def gate(self, slug: str, write: bool = True) -> Dict[str, Any]:
        if self.gate_fn is not None:
            return self.gate_fn(slug, self.ws, write)
        return post.default_gate(slug, self.ws, write)


class ToolRefused(Exception):
    """A request was refused on purpose. The message is safe to show the model."""


def _slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise ToolRefused("slug must be lowercase letters, digits and hyphens (1-100 characters)")
    return slug


def _draft_dir(ctx: Context, slug: str) -> Path:
    d = ctx.ws / "drafts" / _slug(slug)
    if not is_inside(d, ctx.ws) or not (d / "meta.json").is_file():
        raise ToolRefused(f"no draft '{slug}'")
    return d


def _meta(d: Path) -> Dict[str, Any]:
    try:
        data = json.loads((d / "meta.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return {"status": "unreadable"}
    return data if isinstance(data, dict) else {"status": "unreadable"}


def _now(ctx: Context) -> Optional[_dt.datetime]:
    return ctx.now() if ctx.now else None


# ------------------------------------------------------------------ workspace_status

def workspace_status(ctx: Context) -> Dict[str, Any]:
    cfg = ctx.cfg()
    modes = config_mod.effective_modes(cfg, ctx.ws)
    counts: Dict[str, int] = {}
    for p in sorted((ctx.ws / "drafts").glob("*/meta.json")):
        st = STATE_NAMES.get(str(_meta(p.parent).get("status")), "unreadable")
        counts[st] = counts.get(st, 0) + 1
    last = ledger.last_activity(ctx.ws)
    tok = auth.token_status(auth.secrets_dir(cfg), int(cfg["linkedin"]["token_warn_days"]))
    return {"workspace": str(ctx.ws), "posting_mode": modes["posting"], "paused": limits.pause_flags(ctx.ws),
            "stop": post.stop_active(ctx.ws), "gap_problem": post.gap_problem(ctx.ws, cfg, _now(ctx)),
            "token": {"state": tok["state"], "days_left": tok["days_left"]},
            "drafts_by_state": counts, "ledger_rows": len(ledger.entries(ctx.ws)),
            "last_post_activity": last.isoformat() if last else None,
            "posts_today": ledger.posts_today(ctx.ws), "max_posts_per_day": MAX_POSTS_PER_DAY}


# ------------------------------------------------------------------ calendar

def calendar_list(ctx: Context, status: Optional[str] = None, limit: int = 60) -> Dict[str, Any]:
    try:
        entries = cal_mod.load(ctx.ws)["entries"]
    except cal_mod.CalendarError as exc:
        raise ToolRefused(str(exc)) from exc
    if status:
        entries = [e for e in entries if e.get("status") == status]
    limit = max(1, min(int(limit), 365))
    return {"count": len(entries), "entries": entries[:limit]}


# ------------------------------------------------------------------ facts

def facts_list(ctx: Context, status: Optional[str] = None) -> Dict[str, Any]:
    register = reg.load_register(facts_path(ctx.ws, ctx.cfg()), "fact")
    rows = [{"id": e.id, "claim": e.text, "numbers": e.numbers_raw, "source": e.source,
             "status": e.status} for e in register.entries if not status or e.status == status]
    return {"count": len(rows), "facts": rows, "problems": register.problems}


def facts_add(ctx: Context, claim: str, source: str, numbers: str = "") -> Dict[str, Any]:
    """Adds an UNVERIFIED fact (status draft). Verification is a human step in a terminal."""
    try:
        e = reg.add_entry(facts_path(ctx.ws, ctx.cfg()), "fact", text=claim, numbers=numbers, source=source)
    except ValueError as exc:
        raise ToolRefused(str(exc)) from exc
    return {"id": e.id, "status": e.status,
            "next": f"A person verifies it: profile-wrap facts verify {e.id} --evidence <path|url>. "
                    "Drafts cannot cite it until then."}


# ------------------------------------------------------------------ draft_create

def _slugify(text: str, today: _dt.date) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60].strip("-") or "draft"
    return f"{base}-{today.isoformat()}"


def draft_create(ctx: Context, topic: str, lang: str = "en", slug: Optional[str] = None) -> Dict[str, Any]:
    topic = (topic or "").strip()
    if not topic or len(topic) > MAX_TOPIC:
        raise ToolRefused(f"topic is required and must be at most {MAX_TOPIC} characters")
    cfg = ctx.cfg()
    today = (ctx.now() if ctx.now else _dt.datetime.now(_dt.timezone.utc)).date()
    slug = _slug(slug) if slug else _slugify(topic, today)
    if not SLUG_RE.match(slug):
        slug = f"draft-{today.isoformat()}"
    folder = ctx.ws / "drafts" / slug
    if folder.exists():
        raise ToolRefused(f"draft '{slug}' already exists; nothing was overwritten")
    chosen = prov_settings.load(ctx.ws)
    if not chosen.get("provider"):
        raise ToolRefused("no provider is chosen yet: run 'profile-wrap providers use <id>'")
    verified = [e for e in reg.load_register(facts_path(ctx.ws, cfg), "fact").entries
                if e.status == "verified"]
    facts_txt = "\n".join(f"- {e.id}: {e.text} ({e.numbers_raw})" for e in verified) or "(none)"
    persona = cfg.get("persona", {})
    system = ("You write one LinkedIn post caption. Plain text, short lines, no em dashes. "
              "Use ONLY the verified facts below for any claim or number about the author; never invent "
              "numbers, results or stories. Reply with the caption text only.\n"
              f"Language: {lang}. Author: {persona.get('name') or 'the author'}, {persona.get('role') or ''}.\n"
              f"Verified facts:\n{facts_txt}")
    try:
        provider = ctx.provider_factory(chosen["provider"], chosen.get("model"), chosen.get("base_url"))
        result = provider.complete(system, [{"role": "user", "content": f"Topic: {topic}"}], max_tokens=700)
    except ProviderError as exc:
        raise ToolRefused(f"provider failed ({exc.kind}): {exc}") from exc
    caption = (result.text or "").strip()
    if not caption:
        raise ToolRefused("the provider returned no text; nothing was written")
    caption = caption[:MAX_CAPTION]
    pillars = persona.get("pillars") or [{"id": "P1"}]
    meta = {"schema_version": 1, "slug": slug, "title": topic[:120], "lang": lang, "format": "text",
            "pillar": str(pillars[0].get("id", "P1")), "status": "draft", "claims": [],
            "created_by": "profile-wrap-mcp", "provider": result.provider, "model": result.model}
    folder.mkdir(parents=True)
    atomic_write_text(folder / "caption.txt", caption + "\n")
    atomic_write_json(folder / "meta.json", meta)
    gate = ctx.gate(slug, False)
    return {"slug": slug, "status": "draft", "provider": result.provider, "model": result.model,
            "caption": caption, "gate_preview": gate.get("summary"),
            "next": "A person reviews it and presses Allow on the board. Nothing was posted."}


# ------------------------------------------------------------------ gate_run

def gate_run(ctx: Context, slug: str) -> Dict[str, Any]:
    _draft_dir(ctx, slug)
    res = ctx.gate(slug, True)
    return {"slug": slug, "summary": res.get("summary"), "fails": res.get("fails", []),
            "warnings": res.get("warnings", [])}


# ------------------------------------------------------------------ review_state

def _allowed_by_board(ctx: Context, d: Path, meta: Dict[str, Any]) -> Optional[str]:
    """None when a person Allowed this draft on the board; otherwise the reason it did not happen."""
    if meta.get("status") != "queued":
        return f"state is '{STATE_NAMES.get(str(meta.get('status')), meta.get('status'))}', not 'allowed'"
    hist = BoardStore(ctx.ws).history(d)
    last = hist[-1] if hist else None
    if not last or last.get("action") != "allow" or last.get("to") != "queued":
        return "the review history has no board Allow as its latest decision"
    return None


def review_state(ctx: Context, slug: Optional[str] = None) -> Dict[str, Any]:
    dirs = [_draft_dir(ctx, slug)] if slug else sorted(
        p.parent for p in (ctx.ws / "drafts").glob("*/meta.json") if SLUG_RE.match(p.parent.name))
    out = []
    store = BoardStore(ctx.ws)
    for d in dirs:
        meta = _meta(d)
        hist = store.history(d)
        why = _allowed_by_board(ctx, d, meta)
        out.append({"slug": d.name, "state": STATE_NAMES.get(str(meta.get("status")), "unreadable"),
                    "allowed_on_board": why is None, "not_allowed_because": why,
                    "last_decision": hist[-1] if hist else None,
                    "scheduled_at": meta.get("scheduled_at")})
    return {"count": len(out), "drafts": out}


# ------------------------------------------------------------------ post_allowed

def post_allowed(ctx: Context, slug: str, confirm: bool = False) -> Dict[str, Any]:
    """Post one draft a person already Allowed. confirm=false returns the dry-run plan only."""
    d = _draft_dir(ctx, slug)
    why = _allowed_by_board(ctx, d, _meta(d))
    if why:
        return {"status": "refused", "kind": "not_allowed", "slug": slug,
                "reason": f"only drafts Allowed on the review board can be posted: {why}"}
    cfg = ctx.cfg()
    if ledger.posts_today(ctx.ws) >= MAX_POSTS_PER_DAY:
        return {"status": "refused", "kind": "daily_cap", "slug": slug,
                "reason": f"daily cap reached: at most {MAX_POSTS_PER_DAY} post a day"}
    if not confirm:
        plan = post.plan(ctx.ws, slug, cfg, gate_fn=ctx.gate_fn)
        return {"status": "dry", "slug": slug, "plan": plan,
                "reason": "nothing was sent. Call again with confirm=true to post."}
    out = post.publish(ctx.ws, slug, cfg, by="mcp", client=ctx.client, gate_fn=ctx.gate_fn,
                       now=_now(ctx), require_status="queued")
    return out.as_dict()


# ------------------------------------------------------------------ resources

def read_draft(ctx: Context, slug: str) -> Dict[str, Any]:
    d = _draft_dir(ctx, slug)
    cap = d / "caption.txt"
    return {"slug": slug, "meta": _meta(d),
            "caption": cap.read_text(encoding="utf-8-sig") if cap.is_file() else ""}


def list_drafts(ctx: Context) -> Dict[str, Any]:
    return review_state(ctx)
