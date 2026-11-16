"""``profile-wrap build-week``: turn the next planned calendar entries into drafts, and never queue one.

For every ``planned`` entry 8 to 14 days ahead (``--days``), and, as catch-up, every briefed ``planned``
entry 1 to 7 days out that still has no draft (a missed or failed week leaves no hole), the orchestrator:

1. picks a stable per-slug posting time (:func:`profile_wrap.plan.spread.spread_time`) and records it;
2. scaffolds the visual project when the format needs one (``profile-wrap new-gif``);
3. runs a build worker (no Bash) that writes ``meta.json``, ``caption.txt`` and the rest;
4. renders and runs ``profile-wrap gate`` itself, outside the worker, with one bounded fix pass;
5. runs one council-editor review pass and appends it to ``review.json``;
6. marks the calendar entry ``built`` (atomically).

``--dry-run`` lists what would be built and writes the plan to ``work/dryrun/``. It starts no worker,
makes no model call and changes no draft or calendar entry. A build never sets ``queued`` and never
posts: only a human Allow does.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from profile_wrap import claude_runner as cr
from profile_wrap import policy, tzutil
from profile_wrap.atomic import atomic_write_json
from profile_wrap.fsutil import read_jsonl
from profile_wrap.locks import LockHeld, named_lock
from profile_wrap.notify import notify
from profile_wrap.plan import calendar as calmod
from profile_wrap.plan import holidays as hol
from profile_wrap.plan import spread
from profile_wrap.schedule.jobs import profile_wrap_argv, profile_wrap_env

NEEDS_PROJECT = ("gif",)
NEEDS_RENDER = ("slides", "gif", "image", "document", "multi_image")
SEAT = "council-editor"
DEFAULT_MAX_ATTEMPTS = 3          # a failed entry is retried on the next runs, then left for a human
CATCHUP_MIN_DAYS = 1              # catch-up looks at entries CATCHUP_MIN_DAYS .. (window start - 1) days out


class BuildError(RuntimeError):
    pass


@dataclass
class Item:
    slug: str
    date: str
    time: str = ""
    scheduled_at: str = ""
    lang: str = ""
    format: str = ""
    status: str = "planned"   # planned | built | failed | skipped
    detail: str = ""
    relaxed: List[str] = field(default_factory=list)
    verdict: str = ""


@dataclass
class Report:
    dry_run: bool
    items: List[Item] = field(default_factory=list)
    skipped: List[Item] = field(default_factory=list)
    model_calls: int = 0

    @property
    def built(self) -> List[Item]:
        return [i for i in self.items if i.status == "built"]

    @property
    def failed(self) -> List[Item]:
        return [i for i in self.items if i.status == "failed"]

    def as_dict(self) -> Dict[str, Any]:
        def row(i: Item) -> Dict[str, Any]:
            return {k: getattr(i, k) for k in ("slug", "date", "time", "scheduled_at", "lang", "format",
                                               "status", "detail", "relaxed", "verdict")}
        return {"dry_run": self.dry_run, "model_calls": self.model_calls,
                "items": [row(i) for i in self.items], "skipped": [row(i) for i in self.skipped]}


@dataclass
class Steps:
    """The commands the orchestrator runs itself. Tests replace them; the defaults call ``profile-wrap``."""
    scaffold: Callable[[str, str], Tuple[int, str]]
    render: Callable[[str], Tuple[int, str]]
    gate: Callable[[str], Tuple[int, str]]


def default_steps(workspace: Path, timeout_s: int = 3600) -> Steps:
    def run(args: Sequence[str]) -> Tuple[int, str]:
        try:
            r = subprocess.run(profile_wrap_argv(*args, "--workspace", str(workspace)), cwd=str(workspace),
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               env=profile_wrap_env(), timeout=timeout_s,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except (OSError, subprocess.SubprocessError) as exc:
            return 1, f"{args[0]} could not run: {exc}"
        return r.returncode, (r.stdout + r.stderr)[-3000:]

    return Steps(scaffold=lambda slug, fmt: run(["new-gif", slug]),
                 render=lambda slug: run(["render", slug]),
                 gate=lambda slug: run(["gate", slug]))


# ----------------------------------------------------------------------------- selection

def ledger_slugs(workspace: Path) -> set:
    rows, _bad = read_jsonl(Path(workspace) / "published" / "ledger.jsonl")
    return {r["slug"] for r in rows if isinstance(r, dict) and r.get("slug")}


def _draft_status(workspace: Path, slug: str) -> str:
    try:
        meta = json.loads((Path(workspace) / "drafts" / slug / "meta.json").read_text(encoding="utf-8-sig"))
        return str(meta.get("status", "")) if isinstance(meta, dict) else ""
    except (OSError, ValueError):
        return ""


def select(cal: Mapping[str, Any], workspace: Path, *, today: _dt.date, lo: int, hi: int,
           only: Optional[str] = None, catchup_lo: Optional[int] = None,
           max_attempts: int = DEFAULT_MAX_ATTEMPTS) -> Tuple[List[Dict[str, Any]], List[Item]]:
    """Planned, briefed entries inside the window whose folders and ledger rows do not exist.

    ``catchup_lo`` also picks entries ``catchup_lo`` to ``lo - 1`` days out. An entry whose last build
    failed (``build_failed_at``) is retried even though the failed run left a draft folder, until it has
    failed ``max_attempts`` times.
    """
    done = ledger_slugs(workspace)
    chosen: List[Dict[str, Any]] = []
    skipped: List[Item] = []
    for e in sorted(cal.get("entries", []), key=lambda x: (x.get("date", ""), x.get("slug", ""))):
        slug = e.get("slug", "")
        if only and slug != only:
            continue
        if e.get("status") != "planned":
            if only:
                skipped.append(Item(slug, e.get("date", ""), status="skipped",
                                    detail=f"status is {e.get('status')}, not planned"))
            continue
        if calmod.is_open(e):
            skipped.append(Item(slug, e.get("date", ""), status="skipped",
                                detail="open slot: brief it first (replace the title, remove open)"))
            continue
        try:
            ahead = (_dt.date.fromisoformat(e["date"]) - today).days
        except (KeyError, ValueError):
            skipped.append(Item(slug, e.get("date", ""), status="skipped", detail="bad date"))
            continue
        in_window = lo <= ahead <= hi
        in_catchup = catchup_lo is not None and catchup_lo <= ahead < lo
        if not only and not (in_window or in_catchup):
            continue
        try:
            attempts = int(e.get("build_attempts") or 0)
        except (TypeError, ValueError):
            attempts = 0
        retry = bool(e.get("build_failed_at"))
        if retry and attempts >= max_attempts and not only:
            skipped.append(Item(slug, e["date"], status="skipped",
                                detail=f"the build failed {attempts} times; fix the cause, then "
                                       f"`profile-wrap build-week --slug {slug}`"))
            continue
        exists = (Path(workspace) / "drafts" / slug).exists() or (Path(workspace) / "videos" / slug).exists()
        retryable = retry and slug not in done and _draft_status(workspace, slug) not in (
            "queued", "posted", "needs_check")
        if (exists and not retryable) or slug in done:
            skipped.append(Item(slug, e["date"], status="skipped",
                                detail="a draft folder, video project or ledger row already exists"))
            continue
        chosen.append(dict(e, _catchup=True) if (in_catchup and not in_window) else e)
    return chosen, skipped


def collect_taken(workspace: Path, cfg: Mapping[str, Any], cal: Mapping[str, Any],
                  exclude: str = "") -> Dict[str, List[str]]:
    """``{date: [HH:MM, ...]}`` of posting times already used: ledger, drafts and calendar."""
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    taken: Dict[str, List[str]] = {}

    def put(day: str, hhmm: str) -> None:
        taken.setdefault(day, []).append(hhmm)

    rows, _ = read_jsonl(Path(workspace) / "published" / "ledger.jsonl")
    for r in rows:
        stamp = r.get("posted_at") if isinstance(r, dict) else None
        if stamp:
            try:
                local = tzutil.to_zone(tzutil.parse_aware(stamp), tz)
                put(local.date().isoformat(), f"{local.hour:02d}:{local.minute:02d}")
            except (ValueError, tzutil.TimezoneUnavailable):
                pass
    drafts = Path(workspace) / "drafts"
    if drafts.is_dir():
        for meta in drafts.glob("*/meta.json"):
            if meta.parent.name == exclude:
                continue
            try:
                m = json.loads(meta.read_text(encoding="utf-8-sig"))
                local = tzutil.to_zone(tzutil.parse_aware(m["scheduled_at"]), tz)
                put(local.date().isoformat(), f"{local.hour:02d}:{local.minute:02d}")
            except (OSError, ValueError, KeyError, tzutil.TimezoneUnavailable):
                continue
    for e in cal.get("entries", []):
        if e.get("slug") != exclude and e.get("time") and e.get("status") != "skipped":
            put(e["date"], e["time"])
    return taken


def assign_time(entry: Mapping[str, Any], workspace: Path, cfg: Mapping[str, Any],
                cal: Mapping[str, Any], holidays: hol.Holidays) -> Tuple[str, List[str], str]:
    """(HH:MM, relaxations, note). A calendar ``time`` wins; otherwise a stable per-slug minute."""
    if entry.get("time"):
        return entry["time"], [], "from the calendar"
    kw = spread.kwargs_from_config(cfg)
    day = _dt.date.fromisoformat(entry["date"])
    win, shift = holidays.shifted_window(day, kw["window"])
    kw["window"] = win
    if not cfg.get("posting", {}).get("time_spread", True):
        return win[0], [], "time_spread is off: the start of the window"
    det = spread.spread_detail(entry["slug"], day, taken=collect_taken(workspace, cfg, cal, entry["slug"]), **kw)
    note = f"window shifted by {shift}" if shift else ""
    return det.time, det.relaxed, note


def scheduled_at(day: str, hhmm: str, tz: str) -> str:
    naive = _dt.datetime.combine(_dt.date.fromisoformat(day), _dt.time(*[int(x) for x in hhmm.split(":")]))
    return tzutil.localize(naive, tz).isoformat(timespec="seconds")


# ----------------------------------------------------------------------------- prompt values

def prompt_values(workspace: Path, cfg: Mapping[str, Any], entry: Mapping[str, Any], sched: str) -> Dict[str, Any]:
    persona = cfg.get("persona", {})
    slug = entry["slug"]
    fmt = entry.get("format", "text")
    return {
        "slug": slug, "format": fmt, "lang": entry.get("lang", persona.get("primary_language", "en")),
        "entry": json.dumps(entry, ensure_ascii=False, indent=1),
        "scheduled_at": sched,
        "voice_file": persona.get("voice_file", "profile/voice.md"),
        "facts_file": persona.get("facts_file", "research/facts.md"),
        "story_bank": persona.get("story_bank", "profile/story-bank.md"),
        "style_preset": persona.get("style_preset", "plain"),
        "hook_target": cfg.get("gate", {}).get("hook_target", 40),
        "hook_max": cfg.get("gate", {}).get("hook_max", 210),
        "hashtags_max": cfg.get("gate", {}).get("hashtags_max", 3),
        "canvas_w": cfg.get("brand", {}).get("canvas", {}).get("w", 1080),
        "canvas_h": cfg.get("brand", {}).get("canvas", {}).get("h", 1350),
        "project_dir": f"videos/{slug}" if fmt in NEEDS_PROJECT else "none",
        "draft_dir": f"drafts/{slug}",
        "persona_name": persona.get("name") or "the author",
        "claims": ", ".join(entry.get("claims") or []) or "none",
        "ai_disclosure": persona.get("ai_disclosure", {}).get("text", "") or "none",
    }


def _allow_for(entry: Mapping[str, Any]) -> List[str]:
    slug = entry["slug"]
    allow = [f"drafts/{slug}/**"]
    if entry.get("format") in NEEDS_PROJECT:
        allow.append(f"videos/{slug}/**")
    return allow


def _expect_for(entry: Mapping[str, Any]) -> List[str]:
    slug = entry["slug"]
    out = [f"drafts/{slug}/meta.json", f"drafts/{slug}/caption.txt"]
    if entry.get("format") in NEEDS_PROJECT:
        out.append(f"videos/{slug}/index.html")
    return out


# ----------------------------------------------------------------------------- one entry

def _log(workspace: Path, msg: str) -> None:
    """Best effort: a log that cannot be written (lock, full disk, permissions) never stops a build."""
    line = f"{_dt.datetime.now().astimezone():%Y-%m-%d %H:%M:%S} {msg}"
    try:
        p = Path(workspace) / "work" / "build.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return
    except OSError:
        pass
    try:
        stamp = f"{_dt.datetime.now():%Y%m%dT%H%M%S}-{os.getpid()}"
        with (Path(workspace) / "work" / f"build-fallback-{stamp}.log").open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return
    except OSError:
        pass
    try:
        sys.stderr.write(line + "\n")
    except (OSError, ValueError, AttributeError):
        pass


def _mark_build(ws: Path, slug: str, *, failed: bool, reason: str = "") -> int:
    """Set or clear the retry marker on a calendar entry. Returns the attempt count. Never raises."""
    box = {"n": 0}

    def change(cal: Dict[str, Any]) -> None:
        for e in cal["entries"]:
            if e.get("slug") == slug:
                if failed:
                    box["n"] = int(e.get("build_attempts") or 0) + 1
                    e["build_attempts"] = box["n"]
                    e["build_failed_at"] = _dt.datetime.now().astimezone().isoformat(timespec="seconds")
                    e["build_error"] = reason[:300]
                else:
                    for k in ("build_attempts", "build_failed_at", "build_error"):
                        e.pop(k, None)
                return

    try:
        calmod.update(ws, change)
    except Exception as exc:  # the marker is a convenience; the build result stands without it
        _log(ws, f"could not update the retry marker for {slug}: {exc}")
    return box["n"]


def _fail_marker(ws: Path, slug: str, item: Item, cap: int) -> None:
    n = _mark_build(ws, slug, failed=True, reason=item.detail)
    if n >= cap:
        item.detail += f" (attempt {n}: giving up until you run build-week --slug {slug})"
        _log(ws, f"{slug}: giving up after {n} failed builds")
    elif n:
        item.detail += f" (attempt {n} of {cap}; the next run retries)"


# ----------------------------------------------------------------------------- browser preflight

def _launch_smoke(path: Path, ws: Path, timeout: float = 45.0) -> Tuple[bool, str]:
    """Launch the browser headless on about:blank with a throwaway profile. (ok, reason)."""
    from profile_wrap.visuals import proc
    work = Path(ws) / "work"
    work.mkdir(parents=True, exist_ok=True)
    prof = Path(tempfile.mkdtemp(prefix=".preflight-", dir=str(work)))
    try:
        res = proc.run([str(path), "--headless=new", "--disable-gpu", "--no-first-run",
                        f"--user-data-dir={prof}", "--dump-dom", "about:blank"], timeout=timeout)
        if res.ok:
            return True, ""
        return False, res.tail(300) or f"exit {res.returncode}"
    finally:
        shutil.rmtree(prof, ignore_errors=True)


def browser_preflight(ws: Path, cfg: Mapping[str, Any], *, require: Optional[Callable[..., Any]] = None,
                      smoke: Callable[[Path, Path], Tuple[bool, str]] = _launch_smoke) -> str:
    """Prove the render browser exists and starts, before any model call. Raises BuildError with the fix."""
    from profile_wrap import doctor
    from profile_wrap.visuals import VisualsError, assets
    from profile_wrap.visuals import browser as browser_mod
    fix = doctor.HINTS["chrome"][doctor.os_label()]
    try:
        if require is not None:
            found = require(cfg)
        else:
            found = browser_mod.require(dict(cfg), pin=assets.npm_pin("hyperframes"))
    except VisualsError as exc:
        raise BuildError(f"cannot render: {exc} Fix: {fix}") from exc
    ok, reason = smoke(Path(found.path), Path(ws))
    if not ok:
        raise BuildError(f"cannot render: the browser {found.path} ({found.source}) did not start: {reason}. "
                         f"Fix: {fix}")
    return str(found.path)


def _render_and_gate(steps: Steps, entry: Mapping[str, Any]) -> Tuple[bool, str]:
    slug = entry["slug"]
    if entry.get("format") in NEEDS_RENDER:
        rc, tail = steps.render(slug)
        if rc != 0:
            return False, "render failed: " + tail[-1200:]
    rc, tail = steps.gate(slug)
    return rc == 0, tail[-1200:]


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return default


def build_one(workspace: Path, cfg: Mapping[str, Any], entry: Dict[str, Any], hhmm: str, sched: str,
              steps: Steps, report: Report, *, exe: Optional[Sequence[str]] = None,
              runner: Callable[..., cr.WorkerResult] = cr.run_worker) -> str:
    """Build one draft. Raises BuildError with the reason when it fails; returns the council verdict."""
    ws = Path(workspace)
    slug = entry["slug"]
    d = ws / "drafts" / slug
    d.mkdir(parents=True, exist_ok=True)
    if entry.get("format") in NEEDS_PROJECT and not (ws / "videos" / slug).exists():
        rc, tail = steps.scaffold(slug, entry["format"])
        if rc != 0:
            raise BuildError("scaffold failed: " + tail[-300:])
    values = prompt_values(ws, cfg, entry, sched)
    template = cr.prompt_body(cr.load_prompt(ws, "build"))
    prompt = cr.render_prompt(template, {**values, "entry": cr.defang(values["entry"])})
    report.model_calls += 1
    res = runner(ws, cfg, job=f"build-{slug}", kind="build", prompt=prompt, allow=_allow_for(entry),
                 expect=_expect_for(entry), exe=exe)
    if not res.ok:
        raise BuildError(f"build worker {res.status}: " + res.tail(300).replace("\n", " "))
    meta_path = d / "meta.json"
    meta = _read_json(meta_path, None)
    if not isinstance(meta, dict):
        raise BuildError("the worker wrote no valid meta.json")
    # The contract fields belong to the orchestrator, not the worker.
    meta.update({"slug": slug, "status": "draft", "scheduled_at": sched, "lang": entry.get("lang"),
                 "format": entry.get("format"), "title": meta.get("title") or entry.get("title", slug)})
    if entry.get("claims"):
        meta["claims"] = list(entry["claims"])
    meta.setdefault("claims", [])
    if entry.get("format") in NEEDS_PROJECT:
        meta["video_project"] = f"videos/{slug}"
    meta.setdefault("schema_version", policy.SCHEMA_VERSION)
    atomic_write_json(meta_path, meta)

    ok, tail = _render_and_gate(steps, entry)
    if not ok:  # one fix pass, then a deterministic re-check
        fix = cr.prompt_body(cr.load_prompt(ws, "fix"))
        report.model_calls += 1
        fres = runner(ws, cfg, job=f"fix-{slug}", kind="fix", exe=exe, allow=_allow_for(entry),
                      prompt=cr.render_prompt(fix, {**values, "failure": cr.defang(tail)}))
        if not fres.ok:
            raise BuildError(f"gate failed and the fix pass {fres.status}: " + tail[-300:])
        # The fix pass may not change the contract fields either.
        meta2 = _read_json(meta_path, meta)
        meta2.update({"slug": slug, "status": "draft", "scheduled_at": sched})
        atomic_write_json(meta_path, meta2)
        ok, tail = _render_and_gate(steps, entry)
    if not ok:
        raise BuildError("gate failed: " + (tail.strip().splitlines() or ["no output"])[-1][:200])
    return review_one(ws, cfg, entry, values, report, exe=exe, runner=runner)


def _draft_text(ws: Path, slug: str) -> str:
    parts = []
    for name in ("caption.txt", "first_comment.txt", "alt.txt"):
        p = ws / "drafts" / slug / name
        if p.is_file():
            parts.append(f"--- {name}\n" + p.read_text(encoding="utf-8-sig"))
    return "\n".join(parts)


def review_one(ws: Path, cfg: Mapping[str, Any], entry: Mapping[str, Any], values: Mapping[str, Any],
               report: Report, *, exe: Optional[Sequence[str]] = None,
               runner: Callable[..., cr.WorkerResult] = cr.run_worker) -> str:
    """One council-editor pass (``prompts/review.md``); the verdict is appended to ``review.json``."""
    slug = entry["slug"]
    out_rel = f"drafts/{slug}/review/{SEAT}.json"
    (ws / out_rel).unlink(missing_ok=True)
    template = cr.prompt_body(cr.load_prompt(ws, "review"))
    regions = ", ".join(cfg.get("locale", {}).get("audience_regions") or []) or "not set"
    prompt = cr.render_prompt(template, {
        "slug": slug, "seat": SEAT, "seat_brief": _seat_brief(ws), "voice_file": values["voice_file"],
        "facts_file": values["facts_file"], "audience_regions": regions,
        "draft_text": cr.defang(_draft_text(ws, slug))})
    report.model_calls += 1
    res = runner(ws, cfg, job=f"review-{slug}", kind="review", prompt=prompt, allow=[out_rel],
                 expect=[out_rel], exe=exe)
    verdict, note = "unreviewed", "the review pass produced no file"
    if res.ok:
        data = _read_json(ws / out_rel, {})
        if isinstance(data, dict) and data.get("verdict") in ("pass", "revise", "blockers"):
            verdict = data["verdict"]
            blockers = [b for b in data.get("blockers", [])[:5] if isinstance(b, dict)]
            note = ("; ".join(f"{b.get('quote', '')} -> {b.get('fix', '')}" for b in blockers)
                    or "; ".join(str(n) for n in data.get("notes", [])[:3]) or "checked")
        else:
            note = "the review file had no valid verdict"
    hist_path = ws / "drafts" / slug / "review.json"
    hist = _read_json(hist_path, [])
    if not isinstance(hist, list):
        hist = []
    hist.append({"at": _dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                 "action": SEAT, "verdict": verdict, "note": note[:800]})
    atomic_write_json(hist_path, hist)
    return verdict


def _seat_brief(ws: Path) -> str:
    agent = ws / ".claude" / "agents" / f"{SEAT}.md"
    return ("Your role is described in `.claude/agents/" + SEAT + ".md`. Check truth against the facts "
            "register, run the slop detect pass, and compare with the voice file.") if agent.exists() else \
        "Check truth against the facts register, run the slop detect pass, and compare with the voice file."


# ----------------------------------------------------------------------------- the command

def parse_days(text: str) -> Tuple[int, int]:
    try:
        lo, hi = (int(x) for x in str(text).split("-"))
    except ValueError as exc:
        raise BuildError(f"--days must look like 8-14, not {text!r}") from exc
    if lo < 0 or hi < lo:
        raise BuildError("--days: the first number must not be above the second")
    return lo, hi


def build_week(workspace: Path, cfg: Mapping[str, Any], *, days: Tuple[int, int] = (8, 14),
               slug: Optional[str] = None, dry_run: bool = False, today: Optional[_dt.date] = None,
               steps: Optional[Steps] = None, exe: Optional[Sequence[str]] = None,
               runner: Callable[..., cr.WorkerResult] = cr.run_worker, notify_user: bool = True,
               catchup: bool = False, max_attempts: Optional[int] = None,
               preflight: Optional[Callable[[Path, Mapping[str, Any]], Any]] = None) -> Report:
    """``catchup`` also builds briefed entries 1 to ``days[0] - 1`` days out. ``preflight`` defaults to the real
    browser check, used only when the real render steps are in play (``steps`` is None)."""
    ws = Path(workspace)
    tz = cfg.get("locale", {}).get("timezone") or "UTC"
    today = today or tzutil.now(tz).date()
    report = Report(dry_run=dry_run)
    cal = calmod.load(ws)
    holidays = hol.load(ws, dict(cfg))
    cap = max_attempts if max_attempts is not None else int(
        (cfg.get("schedule") or {}).get("build_max_attempts", DEFAULT_MAX_ATTEMPTS))
    todo, report.skipped = select(cal, ws, today=today, lo=days[0], hi=days[1], only=slug,
                                  catchup_lo=CATCHUP_MIN_DAYS if catchup else None, max_attempts=cap)
    plan: List[Tuple[Dict[str, Any], str, str, List[str], str]] = []
    for e in todo:
        catch = bool(e.pop("_catchup", False))
        hhmm, relaxed, note = assign_time(e, ws, cfg, cal, holidays)
        if catch:
            note = (note + "; " if note else "") + "catch-up (closer than the usual window)"
        plan.append((e, hhmm, scheduled_at(e["date"], hhmm, tz), relaxed, note))
        # later entries in this run must see this one's minute
        e = dict(e, time=hhmm)
        cal["entries"] = [x if x.get("slug") != e["slug"] else {**x, "time": hhmm} for x in cal["entries"]]
    for e, hhmm, sched, relaxed, note in plan:
        report.items.append(Item(e["slug"], e["date"], hhmm, sched, e.get("lang", ""), e.get("format", ""),
                                 relaxed=relaxed, detail=note))
    if dry_run:
        out = ws / "work" / "dryrun" / "build-week.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(out, report.as_dict())
        return report
    if not plan:
        _log(ws, "nothing to build")
        return report
    check = preflight if preflight is not None else (browser_preflight if steps is None else None)
    if check is not None and any(e.get("format") in NEEDS_RENDER for e, *_ in plan):
        try:
            check(ws, cfg)
        except BuildError as exc:
            _log(ws, f"preflight failed, no model call made: {exc}")
            if notify_user:
                notify("Weekly build cannot render", str(exc)[:300], workspace=ws,
                       mode=cfg.get("schedule", {}).get("notify", "auto"))
            raise
    lock = named_lock(ws, "build-week", stale_after=4 * 3600, wait=0)
    try:
        lock.acquire()
    except LockHeld as exc:
        raise BuildError(f"another build is running ({exc})") from exc
    steps = steps or default_steps(ws)
    try:
        for (e, hhmm, sched, relaxed, note), item in zip(plan, report.items):
            _log(ws, f"build {e['slug']} at {hhmm}")
            try:
                if not e.get("time"):  # record the stable time so the next run sees it
                    calmod.set_status(ws, e["slug"], "planned", time=hhmm, time_auto=True)
                item.verdict = build_one(ws, cfg, dict(e, time=hhmm), hhmm, sched, steps, report, exe=exe,
                                         runner=runner)
                calmod.set_status(ws, e["slug"], "built")
                _mark_build(ws, e["slug"], failed=False)
                item.status = "built"
                _log(ws, f"built {e['slug']} (review: {item.verdict})")
            except BuildError as exc:
                item.status, item.detail = "failed", str(exc)
                _log(ws, f"FAILED {e['slug']}: {exc}")
                _fail_marker(ws, e["slug"], item, cap)
            except Exception as exc:  # one bad entry never stops the next
                item.status, item.detail = "failed", f"{type(exc).__name__}: {exc}"
                _log(ws, f"FAILED {e['slug']}: {item.detail}")
                _fail_marker(ws, e["slug"], item, cap)
    finally:
        lock.release()
    if notify_user:
        if report.built:
            notify("Posts ready to review", f"{len(report.built)} drafts ready on the board"
                   + (f" ({len(report.failed)} failed, see work/build.log)" if report.failed else ""),
                   workspace=ws, mode=cfg.get("schedule", {}).get("notify", "auto"))
        elif report.failed:
            notify("Weekly build failed", f"{len(report.failed)} drafts failed, see work/build.log",
                   workspace=ws, mode=cfg.get("schedule", {}).get("notify", "auto"))
    return report


def cleanup(workspace: Path, slug: str) -> List[str]:
    """Move a failed build's folders to ``work/trash/`` and set the entry back to planned."""
    ws = Path(workspace)
    if slug in ledger_slugs(ws):
        raise BuildError(f"{slug} is in the ledger: it was posted, so it is not cleaned up")
    meta = _read_json(ws / "drafts" / slug / "meta.json", {})
    if isinstance(meta, dict) and meta.get("status") in ("queued", "posted", "needs_check"):
        raise BuildError(f"{slug} is {meta.get('status')}: reject it on the board first")
    stamp = _dt.datetime.now().strftime("%Y%m%dT%H%M%S")
    moved: List[str] = []
    for base in ("drafts", "videos"):
        src = ws / base / slug
        if src.exists():
            dst = ws / "work" / "trash" / stamp / base / slug
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved.append(f"{base}/{slug} -> work/trash/{stamp}/{base}/{slug}")
    calmod.set_status(ws, slug, "planned")
    _mark_build(ws, slug, failed=False)
    return moved
