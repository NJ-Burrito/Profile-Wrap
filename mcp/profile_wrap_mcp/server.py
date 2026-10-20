"""The MCP server: tool and resource wiring over ``core``. stdio transport only."""
from __future__ import annotations

import argparse
import functools
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

from mcp.server.mcpserver import MCPServer
from mcp_types import ToolAnnotations

from . import __version__, core
from .core import Context

INSTRUCTIONS = (
    "Profile-Wrap workspace tools. Independent open-source tool, not affiliated with LinkedIn. "
    "Everything is read-only or draft-only except post_allowed, which posts a draft ONLY when a person "
    "has already pressed Allow on the review board. No tool reads direct messages or sends "
    "connection invitations. Facts you add are unverified until a person verifies them."
)

READ = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITE_LOCAL = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
POSTS = ToolAnnotations(readOnlyHint=False, destructiveHint=False, idempotentHint=False, openWorldHint=True)


def _explained(fn):
    """A deliberate refusal becomes a readable result; the SDK would otherwise mask it as a bare error."""
    @functools.wraps(fn)
    def run(*a, **k):
        try:
            return fn(*a, **k)
        except core.ToolRefused as exc:
            return {"status": "refused", "reason": str(exc)}
    return run


def build_server(ctx: Context) -> MCPServer:
    notice = core.update_notice(ctx.ws)
    text = INSTRUCTIONS + ("\n\n" + notice if notice else "")
    app = MCPServer("profile-wrap", instructions=text, version=__version__)
    tool = app.tool

    @tool(annotations=READ)
    @_explained
    def workspace_status() -> Dict[str, Any]:
        """Summarise the Profile-Wrap workspace: posting mode, pauses and stops, the 20 h gap guard,
        token state (never the token), draft counts by review state, and how many posts went out today.
        Read-only; makes no network call."""
        return core.workspace_status(ctx)

    @tool(annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=True))
    @_explained
    def update_status() -> Dict[str, Any]:
        """Check whether a newer Profile-Wrap release exists on GitHub and what is new in it. Updating is
        optional and never done by this tool; tell the user, and install nothing unless they ask. One anonymous
        GET, cached for an hour; off with updates.check=false or PROFILE_WRAP_NO_UPDATE_CHECK=1."""
        return core.update_status(ctx)

    @tool(annotations=READ)
    @_explained
    def calendar_list(status: Optional[str] = None, limit: int = 60) -> Dict[str, Any]:
        """List content-calendar entries (planned, built, posted, skipped, blocked), optionally
        filtered by status. Read-only."""
        return core.calendar_list(ctx, status, limit)

    @tool(annotations=WRITE_LOCAL)
    @_explained
    def draft_create(topic: str, lang: str = "en", slug: Optional[str] = None) -> Dict[str, Any]:
        """Create a new text draft from a topic using the provider chosen with 'profile-wrap providers use'.
        The model sees only VERIFIED facts and is told not to invent numbers. The draft starts in state
        'draft'; it never overwrites an existing draft, is never queued, and nothing is posted. The topic
        is sent to the chosen provider (your own key, or your local claude CLI)."""
        return core.draft_create(ctx, topic, lang, slug)

    @tool(annotations=WRITE_LOCAL)
    @_explained
    def gate_run(slug: str) -> Dict[str, Any]:
        """Run the deterministic gate (numbers, claims, language, banned patterns) on drafts/<slug> and
        record gates.json. Returns PASS or FAIL with the failing lines. Local only; no model, no network."""
        return core.gate_run(ctx, slug)

    @tool(annotations=READ)
    @_explained
    def facts_list(status: Optional[str] = None) -> Dict[str, Any]:
        """List the fact register (id, claim, numbers, source, status: draft or verified). Only
        verified facts may back a number in a post. Read-only."""
        return core.facts_list(ctx, status)

    @tool(annotations=WRITE_LOCAL)
    @_explained
    def facts_add(claim: str, source: str, numbers: str = "") -> Dict[str, Any]:
        """Add one fact as UNVERIFIED (status draft). It cannot back a post until a person verifies it
        in a terminal ('profile-wrap facts verify'). This server has no verify tool, by design."""
        return core.facts_add(ctx, claim, source, numbers)

    @tool(annotations=READ)
    @_explained
    def review_state(slug: Optional[str] = None) -> Dict[str, Any]:
        """Show the review-board state of one draft (or all): draft, revising, hold, allowed, rejected,
        needs_check, missed, posted, demo; whether a person Allowed it on the board; the last board
        decision. 'allowed' is the only state post_allowed accepts. Read-only."""
        return core.review_state(ctx, slug)

    @tool(annotations=POSTS)
    @_explained
    def post_allowed(slug: str, confirm: bool = False) -> Dict[str, Any]:
        """Post ONE draft to LinkedIn through the official API, but only if a person already pressed Allow
        on the review board. Refuses draft, revising, hold, rejected, needs_check, missed, posted and demo
        drafts, and refuses an 'allowed' status that lacks a board Allow in its review history. Also
        enforces the gate PASS, the 20 hour gap between posts, the 1 post a day cap, the posting lock, a
        429/403 stop, pauses, and writes the ledger row before anything is sent. With confirm=false (the
        default) it returns the dry-run plan and sends nothing. This is the only tool that can reach LinkedIn."""
        return core.post_allowed(ctx, slug, confirm)

    @app.resource("pw://calendar", mime_type="application/json")
    def calendar_resource() -> str:
        """The content calendar (strategy/calendar.json)."""
        return json.dumps(core.calendar_list(ctx, None, 365), ensure_ascii=False, indent=2)

    @app.resource("pw://drafts", mime_type="application/json")
    def drafts_resource() -> str:
        """Every draft with its review-board state."""
        return json.dumps(core.list_drafts(ctx), ensure_ascii=False, indent=2)

    @app.resource("pw://drafts/{slug}", mime_type="application/json")
    def draft_resource(slug: str) -> str:
        """One draft: meta.json and caption.txt."""
        return json.dumps(core.read_draft(ctx, slug), ensure_ascii=False, indent=2)

    return app


def resolve_workspace(arg: Optional[str]) -> Path:
    if arg:
        return Path(arg).expanduser().resolve()
    from profile_wrap.gate.config import resolve_workspace as _resolve
    return _resolve(None)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(prog="profile-wrap-mcp",
                                description="stdio MCP server over a Profile-Wrap workspace (not affiliated with LinkedIn)")
    p.add_argument("--workspace", help="workspace folder (default: PROFILE_WRAP_WORKSPACE, else the usual lookup)")
    p.add_argument("--version", action="store_true")
    args = p.parse_args(argv)
    if args.version:
        print(__version__)
        return 0
    ws = resolve_workspace(args.workspace)
    if not ws.is_dir():
        print(f"profile-wrap-mcp: workspace not found: {ws}", file=sys.stderr)
        return 2
    os.environ.setdefault("PYTHONUTF8", "1")
    build_server(Context(ws=ws)).run("stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
