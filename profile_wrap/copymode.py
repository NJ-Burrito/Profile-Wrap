"""Copy mode: draft, gate, copy to the clipboard, paste on LinkedIn by hand.

This is the first-run path. It needs no LinkedIn developer app and no token, and it never touches a
LinkedIn account. ``prepare`` refuses unless the draft passes the gate, so nothing that failed a rule is
offered for pasting. ``profile-wrap copy <slug>`` is the terminal door; the desktop app's Build screen
calls ``prepare`` too.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import config as config_mod
from . import i18n, ledger, policy

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,99}$")
LINKEDIN_FEED_URL = "https://www.linkedin.com/feed/"
POST_URL_RE = re.compile(r"^https://www\.linkedin\.com/\S+$")
URN_IN_URL_RE = re.compile(r"(share|ugcPost|activity)[-:](\d+)")
GateFn = Callable[[str, Path, bool], Dict[str, Any]]


class CopyRefused(Exception):
    """The draft cannot be offered for pasting. ``code`` is an i18n key, ``message`` the English text."""

    def __init__(self, code: str, **params: Any):
        self.code = code
        self.params = params
        super().__init__(i18n.t(code, "en", **params))


def prepare(ws: Path, slug: Any, cfg: Optional[Dict[str, Any]] = None,
            gate_fn: Optional[GateFn] = None) -> Dict[str, Any]:
    """The pieces to paste, or ``CopyRefused``. Reads the draft, runs the gate without writing gates.json."""
    from .linkedin import post

    ws = Path(ws)
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise CopyRefused("copy.refused.slug")
    cfg = cfg or config_mod.load(ws)
    try:
        draft = post.load_draft(ws, slug)
    except FileNotFoundError:
        raise CopyRefused("copy.refused.nodraft", slug=slug) from None
    except (OSError, ValueError) as exc:
        raise CopyRefused("copy.refused.unreadable", detail=str(exc)[:160]) from None
    status = draft.meta.get("status")
    if status in policy.READ_ONLY_STATUSES:
        raise CopyRefused("copy.refused.status", status=status)
    if not draft.caption:
        raise CopyRefused("copy.refused.empty")
    problems = post.check_draft(draft, cfg)
    if problems:
        raise CopyRefused("copy.refused.problem", detail="; ".join(problems))
    gate = (gate_fn or post.default_gate)(slug, ws, False)
    if gate.get("summary") != "PASS":
        fails = [str(f) for f in gate.get("fails", [])][:3]
        raise CopyRefused("copy.refused.gate", count=len(gate.get("fails", [])), first="; ".join(fails))
    return {"slug": slug, "caption": draft.caption, "first_comment": draft.first_comment,
            "alt": draft.alt, "assets": [str(a) for a in draft.assets],
            "asset_names": [a.name for a in draft.assets], "open_url": LINKEDIN_FEED_URL}


class PostedRefused(ValueError):
    """``mark_posted`` refused; nothing was written. The message says why in plain words."""


def _default_workspace() -> Path:
    from . import paths

    return paths.find_workspace() or paths.workspace_path("default")


def mark_posted(slug: str, url: Optional[str] = None, ws: Optional[Path] = None) -> Dict[str, Any]:
    """Record that the user pasted this draft on LinkedIn by hand. Returns the ledger row.

    Writes the same kind of row API posting writes (``state: posted``, ``automation.mode: copy``,
    ``by: user``), sets the draft's ``meta.status`` to ``posted`` and the calendar entry to ``posted``.
    No network call, no LinkedIn login. Raises ``PostedRefused`` (nothing written) when the slug is not a
    draft, is already in the ledger, or ``url`` is not a linkedin.com address. The desktop board's
    "I posted it" button calls this.
    """
    from .linkedin import post
    from .locks import FileLock
    from .plan import calendar as calmod

    ws = Path(ws) if ws is not None else _default_workspace()
    if not isinstance(slug, str) or not SLUG_RE.match(slug):
        raise PostedRefused(i18n.t("copy.refused.slug", "en"))
    url = (url or "").strip() or None
    if url is not None and not POST_URL_RE.match(url):
        raise PostedRefused(f"the address must start with https://www.linkedin.com/ (got {url[:60]!r})")
    folder = ws / "drafts" / slug
    try:
        draft = post.load_draft(ws, slug)
        fmt, first_comment = draft.kind, draft.first_comment
        meta = draft.meta
    except FileNotFoundError:
        if not (folder / "meta.json").is_file():
            raise PostedRefused(i18n.t("copy.refused.nodraft", "en", slug=slug)) from None
        meta = post.read_json(folder / "meta.json")  # a missing asset must not stop "I posted it"
        fmt, first_comment = str(meta.get("format", "text")), str(meta.get("first_comment") or "")
    except (OSError, ValueError) as exc:
        raise PostedRefused(i18n.t("copy.refused.unreadable", "en", detail=str(exc)[:160])) from None
    with FileLock(ws / post.LOCK_REL, stale_after=1800):
        have = ledger.find_slug(ws, slug)
        if have is not None and have.get("state") in ledger.LIVE_STATES:
            hint = (" Confirm it with 'profile-wrap post %s --resolve --posted'." % slug
                    if have.get("state") == "needs_check" else "")
            raise PostedRefused(f"'{slug}' is already in the ledger ({have.get('state')}); "
                                f"one draft, one post.{hint}")
        now = ledger.now_iso()
        row: Dict[str, Any] = {
            "slug": slug, "state": "posted", "idempotency_key": ledger.new_key(slug),
            "started_at": now, "posted_at": now, "format": fmt, "lang": meta.get("lang", "en"),
            "pillar": str(meta.get("pillar", "")), "title": str(meta.get("title", slug)),
            "automation": {"mode": "copy", "by": "user"}}
        if url:
            row["url"] = url
            found = URN_IN_URL_RE.search(url)
            if found:
                row["urn"] = f"urn:li:{found.group(1)}:{found.group(2)}"
        if first_comment:
            row["first_comment"] = first_comment
            row["first_comment_state"] = "none"
        try:
            row = ledger.append(ws, row)
        except ledger.LedgerError as exc:
            raise PostedRefused(str(exc)) from exc
        post._meta_set(folder, status="posted", **({"url": url} if url else {}))
        if calmod.calendar_path(ws).is_file():
            calmod.set_status(ws, slug, "posted", posted_at=now, **({"url": url} if url else {}))
    return row


def clipboard_command(platform: Optional[str] = None,
                      which: Callable[[str], Optional[str]] = shutil.which) -> Optional[List[str]]:
    """The command that reads UTF-8 text on stdin and sets the clipboard, or None when there is none."""
    platform = platform or sys.platform
    if platform == "win32":
        exe = which("powershell") or which("pwsh")
        if not exe:
            return None
        script = ("[Console]::InputEncoding = [System.Text.Encoding]::UTF8; "
                  "Set-Clipboard -Value ([Console]::In.ReadToEnd())")
        return [exe, "-NoProfile", "-NonInteractive", "-Command", script]
    if platform == "darwin":
        return ["pbcopy"] if which("pbcopy") else None
    for name, args in (("wl-copy", []), ("xclip", ["-selection", "clipboard"]), ("xsel", ["--clipboard", "--input"])):
        if which(name):
            return [name] + args
    return None


def to_clipboard(text: str, *, platform: Optional[str] = None,
                 which: Callable[[str], Optional[str]] = shutil.which,
                 run: Callable[..., Any] = subprocess.run) -> bool:
    """Put ``text`` on the clipboard. False when this machine has no way to (the caller prints it)."""
    cmd = clipboard_command(platform, which)
    if cmd is None:
        return False
    try:
        done = run(cmd, input=text.encode("utf-8"), capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return False
    return getattr(done, "returncode", 1) == 0


def _lang(cfg: Dict[str, Any]) -> str:
    return i18n.normalize(cfg.get("board", {}).get("ui_language", "en"))


def cmd_copy(args: argparse.Namespace, *, copier: Callable[[str], bool] = to_clipboard,
             gate_fn: Optional[GateFn] = None) -> int:
    from .cli import resolve_workspace

    ws = resolve_workspace(args)
    if getattr(args, "posted", False):
        try:
            row = mark_posted(args.slug, getattr(args, "url", None), ws)
        except (PostedRefused, ValueError) as exc:
            print("profile-wrap copy: " + str(exc), file=sys.stderr)
            return policy.EXIT_FAIL
        print(f"recorded {row['slug']} as posted by hand (ledger row {row['idempotency_key']})")
        return policy.EXIT_OK
    if getattr(args, "url", None):
        print("profile-wrap copy: --url goes with --posted", file=sys.stderr)
        return policy.EXIT_USAGE
    cfg = config_mod.load(ws)
    lang = i18n.normalize(getattr(args, "lang", None) or _lang(cfg))
    try:
        piece = prepare(ws, args.slug, cfg, gate_fn)
    except CopyRefused as exc:
        print("profile-wrap copy: " + i18n.t(exc.code, lang, **exc.params), file=sys.stderr)
        return policy.EXIT_FAIL
    what = getattr(args, "part", "caption")
    text = {"caption": piece["caption"], "first-comment": piece["first_comment"], "alt": piece["alt"]}[what]
    if not text:
        print("profile-wrap copy: " + i18n.t("copy.refused.nopart", lang), file=sys.stderr)
        return policy.EXIT_FAIL
    if getattr(args, "print_only", False) or not copier(text):
        if not getattr(args, "print_only", False):
            print(i18n.t("copy.cli.noclip", lang))
        print(text)
    else:
        print(i18n.t("copy.cli.copied", lang))
    if piece["asset_names"]:
        print(i18n.t("copy.media", lang, files=", ".join(piece["assets"])))
    print(i18n.t("copy.after", lang))
    print(piece["open_url"])
    return policy.EXIT_OK


def register(subparsers: Any) -> None:
    p = subparsers.add_parser("copy", help="copy mode: gate a draft, then copy it to the clipboard to paste on LinkedIn")
    p.add_argument("slug", help="draft folder name under drafts/")
    p.add_argument("--part", choices=["caption", "first-comment", "alt"], default="caption",
                   help="what to copy (default: the post text)")
    p.add_argument("--print", dest="print_only", action="store_true", help="print the text instead of copying it")
    p.add_argument("--posted", action="store_true",
                   help="record that you pasted this draft on LinkedIn (ledger row, draft and calendar become posted)")
    p.add_argument("--url", help="with --posted: the address of your post (https://www.linkedin.com/...)")
    p.add_argument("--lang", choices=list(i18n.LANGS), help="message language (default: board.ui_language)")
    p.add_argument("--workspace", default=argparse.SUPPRESS, help="workspace folder")
    p.add_argument("--profile", default=argparse.SUPPRESS, help="profile id")
    p.set_defaults(func=cmd_copy)
