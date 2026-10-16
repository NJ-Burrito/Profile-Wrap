"""The gate: deterministic checks of one draft, no model. Writes drafts/<slug>/gates.json."""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import shutil
from pathlib import Path
from typing import Callable

from profile_wrap.facts.table import atomic_write_text

from . import numbers as nums
from .arabic import check_arabic, is_arabic_lang
from .claims import load_registers, resolve_claims
from .config import load_config, read_json, resolve_workspace
from .findings import FAIL, OVERRIDDEN, WARN, finding
from .overrides import apply_overrides
from .render import RenderChecker, derived_fonts, run_tool
from .rules import TextContext, hook_findings, load_banned, scan_text
from .textnorm import html_text
from .usergates import run_user_gates

REQUIRED_META = ("slug", "lang", "format", "pillar", "status", "claims")
try:  # the enumeration lives in WP1's policy.py
    from profile_wrap.policy import FORMATS  # type: ignore
except Exception:  # pragma: no cover - policy.py absent while WP2 is built alone
    FORMATS = ("text", "slides", "gif", "image", "document", "multi_image")
STANDARD_CHECKS = ("meta", "facts", "claims", "caption", "hook", "slop", "private_terms", "numbers", "links",
                   "hashtags", "arabic", "alt", "render")
SCHEMA_VERSION = 1


def _check_group(name: str) -> str:
    """Which reported check a finding belongs to (em_dash, never_say and friends roll up into slop)."""
    return {"em_dash": "slop", "en_dash": "slop", "never_say": "slop", "job_seeking": "slop", "invisible": "slop",
            "contact": "slop", "tools": "render", "overrides": "meta", "config": "meta"}.get(name, name)


def _read_text(path: Path) -> tuple[str | None, str | None]:
    """Text of a file or (None, problem). A BOM stays in the text so the invisible-character check sees it."""
    try:
        return path.read_bytes().decode("utf-8"), None
    except FileNotFoundError:
        return None, None
    except (OSError, UnicodeDecodeError) as exc:
        return None, f"{path.name} unreadable: {exc}"


def _video_text(ws: Path, meta: dict, draft: Path) -> tuple[str, list[str]]:
    """Visible text of the video project (index.html and sub-compositions) plus narration and caption files."""
    vp = meta.get("video_project")
    roots = [ws / str(vp)] if vp else []
    if (draft / "video").is_dir():
        roots.append(draft / "video")
    parts: list[str] = []
    problems: list[str] = []
    for root in roots:
        if not root.is_dir():
            problems.append(f"video_project not found: {root}")
            continue
        for p in sorted(root.rglob("*")):
            if any(seg in ("node_modules", "out", ".git", "renders") for seg in p.parts):
                continue
            if p.suffix.lower() in (".html", ".htm"):
                txt, prob = _read_text(p)
                if prob:
                    problems.append(prob)
                elif txt:
                    parts.append(html_text(txt))
            elif p.suffix.lower() in (".txt", ".srt", ".vtt") and p.stat().st_size < 200_000:
                txt, prob = _read_text(p)
                if txt:
                    parts.append(txt)
    return "\n".join(x for x in parts if x), problems


def inputs_hash(ws: Path, draft: Path, cfg: dict) -> str:
    """sha256 over everything the gate read, so a later step can tell the PASS is stale."""
    h = hashlib.sha256()
    names = ["meta.json", "caption.txt", "first_comment.txt", "alt.txt", "slides.html", "review.json"]
    files = [draft / n for n in names]
    files += [ws / cfg["persona"].get("facts_file", "research/facts.md"),
              (ws / cfg["persona"].get("facts_file", "research/facts.md")).parent / "stats.md"]
    for f in files:
        h.update(f.name.encode())
        if f.is_file():
            h.update(f.read_bytes())
    h.update(json.dumps([cfg["persona"].get("private_terms"), cfg["persona"].get("never_say"), cfg["gate"]],
                        sort_keys=True).encode())
    return h.hexdigest()


def _bad_config(problems: list[str]) -> list[dict]:
    out = []
    for p in problems:
        sev = WARN if "not found" in p else FAIL
        out.append(finding("config", sev, p))
    return out


def run_gate(slug: str | None, workspace: str | Path | None = None, *, write: bool = True,
             which: Callable[[str], str | None] = shutil.which, runner=run_tool,
             today: _dt.date | None = None, profile: str | None = None) -> dict:
    """Run every gate on drafts/<slug>. Returns the gates.json dict; summary is 'PASS' or 'FAIL'.

    Never raises for a bad draft: a missing slug, folder, meta, facts file or tool becomes a FAIL (or a
    warning) line. `which` and `runner` are injectable so tests can hide tools.
    """
    ws = resolve_workspace(workspace, profile)
    result: dict = {"schema_version": SCHEMA_VERSION, "slug": slug or "", "summary": "FAIL", "checks": {},
                    "findings": [], "fails": [], "warnings": [], "overrides": [], "skipped": [], "surfaces": []}
    if not slug or not str(slug).strip():
        return _finish(result, [finding("meta", FAIL, "no draft given. Usage: profile-wrap gate <slug> (a folder under drafts/)")],
                       None, write=False)
    slug = str(slug).strip()
    draft = Path(slug) if Path(slug).is_dir() and Path(slug).name != "" and (Path(slug) / "meta.json").exists() \
        else ws / "drafts" / slug
    if not draft.is_dir():
        return _finish(result, [finding("meta", FAIL, f"draft folder not found: {draft}")], None, write=False)
    result["slug"] = draft.name

    cfg, cfg_problems = load_config(ws)
    found: list[dict] = _bad_config(cfg_problems)
    g = cfg["gate"]
    persona = cfg["persona"]

    # ---- meta
    meta: dict = {}
    mp = draft / "meta.json"
    raw = mp.read_bytes() if mp.exists() else None
    if raw is None:
        found.append(finding("meta", FAIL, f"meta.json is missing in {draft.name}"))
    else:
        if raw.startswith(b"\xef\xbb\xbf"):
            found.append(finding("meta", FAIL, "meta.json starts with a UTF-8 BOM; re-save it as UTF-8 without BOM",
                                 token="BOM"))
        try:
            parsed = json.loads(raw.decode("utf-8-sig"))
            if isinstance(parsed, dict):
                meta = parsed
            else:
                found.append(finding("meta", FAIL, "meta.json must hold a JSON object"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            found.append(finding("meta", FAIL, f"meta.json is not valid UTF-8 JSON: {exc}"))
    required = [k for k in REQUIRED_META if k != "claims" or g["numbers"].get("require_claims", True)]
    missing = [k for k in required if k not in meta]
    if meta and missing:
        found.append(finding("meta", FAIL, f"meta.json lacks required field(s): {', '.join(missing)}",
                             token=missing[0]))
    if meta.get("slug") and meta["slug"] != draft.name:
        found.append(finding("meta", FAIL, f"meta.slug '{meta['slug']}' differs from the folder name '{draft.name}'"))
    fmt = meta.get("format", "")
    if fmt and fmt not in FORMATS:
        found.append(finding("meta", FAIL, f"meta.format '{fmt}' is not one of {', '.join(FORMATS)}", token=str(fmt)))
    elif fmt and fmt not in cfg["posting"].get("formats_enabled", FORMATS):
        found.append(finding("meta", FAIL, f"format '{fmt}' is not enabled in posting.formats_enabled", token=fmt))
    lang = str(meta.get("lang", ""))
    allowed_langs = {str(x).casefold() for x in persona.get("languages", ["en"])}
    if lang:
        parts = [p for p in lang.replace("+", ",").replace("/", ",").split(",") if p]
        base = {p.split("-")[0].casefold() for p in parts}
        if base - allowed_langs - {"bilingual"}:
            found.append(finding("meta", FAIL, f"meta.lang '{lang}' is not in persona.languages {sorted(allowed_langs)}",
                                 token=lang))
    pillar_ids = {p.get("id") for p in persona.get("pillars", []) if isinstance(p, dict)}
    if meta.get("pillar") and pillar_ids and meta["pillar"] not in pillar_ids:
        found.append(finding("meta", WARN, f"meta.pillar '{meta['pillar']}' is not a configured pillar", token=str(meta["pillar"])))
    if (meta.get("fictional") or meta.get("demo")) and not persona.get("demo"):
        found.append(finding("meta", FAIL, "this is a demo (fictional) draft and cannot pass in a live workspace"))

    # ---- surfaces
    surfaces: dict[str, str] = {}
    for name, fname in (("caption", "caption.txt"), ("first_comment", "first_comment.txt"), ("alt", "alt.txt")):
        txt, prob = _read_text(draft / fname)
        if prob:
            found.append(finding("caption" if name == "caption" else name, FAIL, prob))
        if txt is not None:
            surfaces[name] = txt
    cap = surfaces.get("caption")
    if cap is None and not any(f["check"] == "caption" for f in found):
        found.append(finding("caption", FAIL, f"caption.txt is missing in {draft.name}", surface="caption"))
    sh, prob = _read_text(draft / "slides.html")
    if prob:
        found.append(finding("slides", FAIL, prob))
    if sh:
        surfaces["slides"] = html_text(sh)
    vt, vprobs = _video_text(ws, meta, draft)
    for p in vprobs:
        found.append(finding("render", FAIL, p))
    if vt:
        surfaces["video"] = vt
    result["surfaces"] = sorted(surfaces)

    # ---- facts and claims
    facts, stats, reg_problems = load_registers(ws, cfg)
    found.extend(reg_problems)
    claims = meta.get("claims")
    specs, claim_findings = resolve_claims(claims, facts, stats, cfg, today)
    found.extend(claim_findings)
    result["claims"] = claims if isinstance(claims, list) else []

    # ---- text rules
    banned = load_banned(g.get("banned_files", []), ws, g.get("extra_banned", []))
    for p in banned.problems:
        found.append(finding("slop", FAIL, p))
    ctx = TextContext(banned, list(persona.get("private_terms", [])), list(persona.get("never_say", [])),
                      goal=persona.get("goal", "authority"), em_dash=g["em_dash"], en_dash=g["en_dash"],
                      links_in_body=g["links_in_body"], hashtags_max=g["hashtags_max"])
    is_ar = is_arabic_lang(lang)
    for name, text in surfaces.items():
        if name == "first_comment" and not g.get("first_comment_gated", True):
            continue
        found.extend(scan_text(name, text, ctx, is_caption=(name == "caption"), is_first_comment=(name == "first_comment")))
        if is_ar:
            found.extend(check_arabic(name, text))
    if cap is not None:
        if len(cap.strip()) > g["caption_max"]:
            found.append(finding("caption", FAIL, f"caption is {len(cap.strip())} characters (max {g['caption_max']})",
                                 surface="caption", token="length"))
        found.extend(hook_findings(cap, g["hook_max"], g["hook_target"], str(meta.get("style", ""))))

    # ---- numbers
    n_cfg = g["numbers"]
    if n_cfg.get("mode", "claim_bound") != "off":
        scanned = {k: v for k, v in surfaces.items() if k in n_cfg.get("scan", [])}
        found.extend(nums.check_numbers(scanned, specs, min_bare=int(n_cfg.get("min_bare_digit", 10)),
                                        number_words=n_cfg.get("number_words", "warn")))

    # ---- alt text
    if g.get("require_alt_text", True) and fmt in ("slides", "gif") and not surfaces.get("alt", "").strip():
        found.append(finding("alt", FAIL, f"alt text is required for a {fmt} post: write alt.txt", surface="alt"))

    # ---- render
    if fmt in ("slides", "gif") or meta.get("assets"):
        cfg_r = dict(cfg)
        cfg_r["gate"] = dict(g)
        if not g.get("required_font_substrings"):
            cfg_r["gate"]["required_font_substrings"] = derived_fonts(cfg)
        rc = RenderChecker(draft, ws, meta, cfg_r, which=which, runner=runner)
        found.extend(rc.run_all())
        result["skipped"] = rc.skipped

    # ---- user-owned gates (hooks/gate_*.py)
    user_found, user_names = run_user_gates(ws, draft, meta, surfaces, cfg)
    found.extend(user_found)
    result["user_gates"] = user_names

    # ---- council
    if g.get("require_council_pass"):
        rj, note = read_json(draft / "review.json")
        verdict = str(rj.get("verdict", "")).casefold() if isinstance(rj, dict) else ""
        if rj is None:
            found.append(finding("review", FAIL, f"council pass required but review.json: {note}"))
        elif verdict not in ("pass", "ready", "approved"):
            found.append(finding("review", FAIL, f"council verdict is '{verdict or 'missing'}'; a pass is required"))

    # ---- overrides
    found, log, extra = apply_overrides(found, meta.get("overrides"), cfg)
    found.extend(extra)
    result["overrides"] = log
    try:
        result["input_sha256"] = inputs_hash(ws, draft, cfg)
    except OSError:
        result["input_sha256"] = ""
    result["lang"] = lang
    return _finish(result, found, draft, write=write)


def _finish(result: dict, found: list[dict], draft: Path | None, *, write: bool) -> dict:
    groups: dict[str, list[dict]] = {}
    for f in found:
        groups.setdefault(_check_group(f["check"]), []).append(f)
    names = list(STANDARD_CHECKS) + sorted(set(groups) - set(STANDARD_CHECKS))
    checks = {}
    for n in names:
        fs = groups.get(n, [])
        bad = [f for f in fs if f["severity"] == FAIL]
        warn = [f for f in fs if f["severity"] == WARN]
        over = [f for f in fs if f["severity"] == OVERRIDDEN]
        if bad:
            detail = "; ".join(f["message"] for f in bad[:3]) + (f" (+{len(bad) - 3} more)" if len(bad) > 3 else "")
        elif over:
            detail = "overridden: " + "; ".join(f["message"] for f in over[:3])
        elif warn:
            detail = "warn: " + "; ".join(f["message"] for f in warn[:3])
        else:
            detail = "ok"
        checks[n] = {"ok": not bad, "detail": detail}
    result["checks"] = checks
    result["findings"] = found
    result["fails"] = [f"{f['check']}[{f['surface']}]: {f['message']}" if f["surface"] else f"{f['check']}: {f['message']}"
                       for f in found if f["severity"] == FAIL]
    result["warnings"] = [f"{f['check']}[{f['surface']}]: {f['message']}" if f["surface"] else f"{f['check']}: {f['message']}"
                          for f in found if f["severity"] == WARN]
    result["summary"] = "FAIL" if result["fails"] else "PASS"
    result["checked_at"] = _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()
    if write and draft is not None:
        atomic_write_text(draft / "gates.json", json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    return result


def format_lines(result: dict) -> list[str]:
    """Human output: one summary line, then one FAIL or WARN line per finding."""
    lines = [f"{result['summary']} {result.get('slug', '')}".strip()]
    lines += [f"  FAIL {x}" for x in result["fails"]]
    lines += [f"  WARN {x}" for x in result["warnings"]]
    for o in result.get("overrides", []):
        if o.get("applied"):
            lines.append(f"  OVERRIDE {o['check']}/{o['token']}: {o['reason']}")
    return lines
