"""``njli motion status`` and ``njli motion upgrade [--queued-only]``: re-render posts with the current motion library.

For each selected post: back up the project's motion files and the draft's outputs, install the library (data files only
when the project has none or an identical copy), render, gate, measure, and compare the loop seam with a **non-ratcheting**
limit (the previous GIF's own seam difference plus a tolerance, never lower than the base limit). On ANY failure the
backed-up files are restored byte for byte and the post is logged FAILED; the run goes on with the next post. meta.json,
caption.txt and review.json are never touched.
"""
from __future__ import annotations

import datetime as _dt
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from njli import atomic

from . import VisualsError, kit_dir, metrics
from .gif import DATA_FILES, LEGACY_FILE, MOTION_FILES, file_hash, motion_source, sync_motion

STATUSES_QUEUED = ("queued",)
STATUSES_OPEN = ("queued", "draft", "revising", "hold", "needs_check", "missed")
OUTPUTS = ("render.json", "gates.json", "metrics.json")


class Fail(VisualsError):
    pass


@dataclass
class Steps:
    """The three machine steps, injectable so tests can force a failure."""
    render: Callable[[str], dict]
    gate: Callable[[str], Tuple[bool, str]]
    measure: Callable[[str], "metrics.Report"]


def default_steps(workspace: Path, cfg: dict) -> Steps:
    from . import render as render_mod

    def _render(slug: str) -> dict:
        return render_mod.render(slug, workspace, cfg)

    def _gate(slug: str) -> Tuple[bool, str]:
        p = subprocess.run([sys.executable, "-m", "njli", "gate", slug, "--workspace", str(workspace)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        lines = [ln for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
        return p.returncode == 0, (lines[-1] if lines else "no output")[:240]

    def _measure(slug: str) -> "metrics.Report":
        return metrics.run_for_slug(slug, workspace, cfg)

    return Steps(_render, _gate, _measure)


# ------------------------------------------------------------------ discovery

def _ledger_slugs(workspace: Path) -> set:
    out = set()
    p = Path(workspace) / "published" / "ledger.jsonl"
    if p.is_file():
        for line in p.read_text(encoding="utf-8").splitlines():
            try:
                out.add(json.loads(line).get("slug"))
            except ValueError:
                pass
    return out


def posts(workspace: Path, *, queued_only: bool = True, min_hours: float = 3.0,
          now: Optional[_dt.datetime] = None) -> List[Tuple[Path, dict]]:
    """Drafts with a video project that are not posted. Queued posts need ``scheduled_at`` at least ``min_hours`` away."""
    now = now or _dt.datetime.now(_dt.timezone.utc)
    ledger = _ledger_slugs(workspace)
    out: List[Tuple[Path, dict]] = []
    for mp in sorted((Path(workspace) / "drafts").glob("*/meta.json")):
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        slug = mp.parent.name
        if not meta.get("video_project") or slug in ledger or meta.get("slug") in ledger:
            continue
        status = meta.get("status")
        if status in ("posted", "rejected", "demo"):
            continue
        if queued_only:
            if status not in STATUSES_QUEUED:
                continue
            try:
                when = _dt.datetime.fromisoformat(str(meta["scheduled_at"]).replace("Z", "+00:00"))
            except (KeyError, ValueError):
                continue
            if when.tzinfo is None:
                when = when.astimezone()
            if when - now < _dt.timedelta(hours=min_hours):
                continue
        elif status not in STATUSES_OPEN:
            continue
        out.append((mp.parent, meta))
    return out


def _version(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def status(workspace: Path) -> List[dict]:
    """Every video project with its motion version and whether it differs from the current library."""
    src = motion_source(workspace)
    cur_core, cur_ver = file_hash(src / "core.js"), _version(src / "VERSION")
    out = []
    for proj in sorted((Path(workspace) / "videos").glob("*/")):
        if not (proj / "index.html").is_file():
            continue
        m = proj / "motion"
        have = file_hash(m / "core.js")
        out.append({"project": proj.name, "version": _version(m / "VERSION") or None, "current": cur_ver,
                    "has_library": have is not None, "stale": have is not None and have != cur_core,
                    "legacy_only": have is None and (m / "motion.js").is_file()})
    return out


# ------------------------------------------------------------------ backup / restore

@dataclass
class Backup:
    root: Path
    entries: List[Tuple[str, bool]] = field(default_factory=list)   # (path relative to workspace, existed)


def backup(workspace: Path, slug: str, meta: dict, asset: str) -> Backup:
    ws = Path(workspace)
    root = ws / "work" / "motion-backup" / slug
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    proj = Path(meta["video_project"])
    rels = [str(proj / "motion" / n) for n in list(MOTION_FILES) + [LEGACY_FILE, "brand.js"]]
    rels += [str(proj / "assets" / "fonts.css"), str(proj / "renders" / "video.mp4")]
    rels += [f"drafts/{slug}/out/{asset}"] + [f"drafts/{slug}/out/{n}" for n in OUTPUTS[:1]] + \
        [f"drafts/{slug}/{OUTPUTS[1]}", f"drafts/{slug}/out/{OUTPUTS[2]}"]
    b = Backup(root)
    for rel in rels:
        rel = rel.replace("\\", "/")
        src = ws / rel
        existed = src.is_file()
        b.entries.append((rel, existed))
        if existed:
            dst = root / "files" / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
    atomic.atomic_write_json(root / "manifest.json", {"entries": b.entries})
    return b


def restore(workspace: Path, b: Backup) -> None:
    ws = Path(workspace)
    for rel, existed in b.entries:
        target = ws / rel
        if existed:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(b.root / "files" / rel, target)
        elif target.is_file():
            target.unlink()


# ------------------------------------------------------------------ one post

def seam_of(gif: Path, identity: bool) -> Optional[float]:
    if not gif.is_file():
        return None
    try:
        return metrics.seam_diff(metrics.decode_frames(gif), identity)
    except Exception:   # an unreadable old GIF just means there is no previous seam to compare with
        return None


def process(workspace: Path, cfg: dict, draft: Path, meta: dict, steps: Steps, *, force: bool = False) -> dict:
    ws = Path(workspace)
    slug = draft.name
    proj = ws / meta["video_project"]
    asset = next((a for a in meta.get("assets", []) if str(a).endswith(".gif")), f"{slug}.gif")
    gif = draft / "out" / asset
    src = motion_source(ws)
    same_lib = all(file_hash(src / n) == file_hash(proj / "motion" / n) for n in MOTION_FILES if n not in DATA_FILES)
    if same_lib and not force and gif.is_file() and (draft / "out" / "render.json").is_file() and \
            gif.stat().st_mtime >= (proj / "motion" / "core.js").stat().st_mtime:
        return {"slug": slug, "status": "SKIP-current"}
    identity = bool((((cfg.get("brand") or {}).get("identity")) or {}).get("enabled"))
    old_seam = seam_of(gif, identity)
    bk = backup(ws, slug, meta, asset)
    try:
        sync_motion(proj, ws, cfg)
        steps.render(slug)
        ok, line = steps.gate(slug)
        if not ok:
            raise Fail("gate: " + line)
        rep = steps.measure(slug)
        if not rep.ok:
            raise Fail("metrics: " + "; ".join(rep.problems))
        limit = max(metrics.SEAM_LIMIT, (old_seam if old_seam is not None else 0.0) + metrics.SEAM_RATCHET)
        if rep.seam > limit:
            raise Fail(f"seam: first and last frame differ by {rep.seam:.2f} (limit {limit:.2f}, non-ratcheting)")
        return {"slug": slug, "status": "PASS", "frames": rep.frames, "still_pct": rep.still["still_pct"],
                "mib": round(rep.bytes / 2**20, 2), "seam": rep.seam}
    except BaseException as exc:
        restore(ws, bk)
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        msg = str(exc).splitlines()[0][:240] if str(exc) else type(exc).__name__
        return {"slug": slug, "status": "FAILED", "reason": msg, "restored": True}


def upgrade(workspace: Path, cfg: dict, *, queued_only: bool = True, only: Optional[str] = None, min_hours: float = 3.0,
            dry_run: bool = False, steps: Optional[Steps] = None, force: bool = False,
            now: Optional[_dt.datetime] = None) -> dict:
    ws = Path(workspace)
    todo = [(d, m) for d, m in posts(ws, queued_only=queued_only, min_hours=min_hours, now=now)
            if not only or d.name == only]
    results: List[dict] = []
    log = ws / "data" / "logs" / "motion-upgrade.log"

    def note(line: str) -> None:
        log.parent.mkdir(parents=True, exist_ok=True)
        stamp = _dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")

    note(f"START {len(todo)} post(s) queued_only={queued_only} dry_run={dry_run}")
    if dry_run:
        results = [{"slug": d.name, "status": "WOULD", "scheduled_at": m.get("scheduled_at")} for d, m in todo]
    else:
        steps = steps or default_steps(ws, cfg)
        for draft, meta in todo:
            res = process(ws, cfg, draft, meta, steps, force=force)
            results.append(res)
            note(" ".join(f"{k}={v}" for k, v in res.items()))
    failed = sum(1 for r in results if r["status"] == "FAILED")
    note(f"END failed={failed} of {len(todo)}")
    return {"results": results, "failed": failed, "total": len(todo), "log": str(log)}
