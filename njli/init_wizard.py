"""``njli init``: build a workspace from answers (demo, express, full or replayed).

The interview itself is run by the setup skill through AskUserQuestion, in batches of at most
four questions. Each batch becomes a section of an answers file that this module applies, so a
stop resumes where it left off (``.njl/onboarding.json``). ``--answers a.json --yes`` replays the
whole file without questions (CI); ``--section <name>`` re-enters one step.
"""
from __future__ import annotations

import datetime as _dt
import importlib
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from . import __version__, config, doctor, paths, policy, scaffold, schemalite
from .atomic import atomic_write_json, atomic_write_text
from .fsutil import read_json

SECTIONS = ("preflight", "where", "who", "privacy", "facts", "voice", "brand", "cadence",
            "models", "linkedin", "consent", "scheduler", "profile", "first_week", "wrapup")
# Steps another command performs; init only records the pointer.
EXTERNAL = {
    "linkedin": "njli auth (see docs/linkedin-app-setup.md); skippable, copy mode needs no app",
    "scheduler": "njli schedule install --dry-run, then install",
    "profile": "njli profile ingest (optional)",
    "first_week": "njli calendar fill --weeks 1, then njli build-week --dry-run",
}
DEFAULT_WEEKDAYS = {
    1: ["wed"], 2: ["tue", "thu"], 3: ["mon", "wed", "thu"], 4: ["mon", "tue", "thu", "fri"],
    5: ["mon", "tue", "wed", "thu", "fri"], 6: ["mon", "tue", "wed", "thu", "fri", "sat"],
    7: ["mon", "tue", "wed", "thu", "fri", "sat", "sun"],
}

DEMO_ANSWERS: Dict[str, Any] = {
    "schema_version": 1,
    "where": {"profile_id": "demo"},
    "who": {
        "name": "Maya Rivera",
        "handle": "maya-rivera-demo",
        "role": "Independent data analyst for small non-profits (fictional)",
        "niche": "Data analysis for small non-profits",
        "audience": "Non-profit directors and programme managers",
        "audience_regions": ["Europe"],
        "languages": ["en", "ar"],
        "primary_language": "en",
        "timezone": "Europe/Lisbon",
        "goal": "authority",
        "pillars": [{"id": "P1", "name": "Teach", "share": 0.4},
                    {"id": "P2", "name": "Proof of work", "share": 0.4},
                    {"id": "P3", "name": "Availability", "share": 0.2}],
    },
    "privacy": {"private_terms": ["Fernhill Cycles"], "never_say": [], "sensitive_rules": []},
    "voice": {"style_preset": "plain",
              "answers": {"voice": "Warm, concrete, short sentences.",
                          "note": "Maya Rivera is fictional. Every demo file says so."}},
    "brand": {"font_source": "google_ofl", "palette_mode": "per_post",
              "identity": {"enabled": True, "name": "Maya Rivera", "role": "Data analyst",
                           "photo": None, "signature": "typed"}},
    "cadence": {"per_week": 3},
    "models": {"mode": "tiered", "auth": "login"},
    "options": {"demo": True, "git_commit": False},
}


class WizardError(Exception):
    """The answers cannot be applied."""


# -------------------------------------------------------------------- answers

def load_answers(path: Path) -> Dict[str, Any]:
    try:
        data = read_json(path)
    except (OSError, ValueError) as exc:
        raise WizardError(f"cannot read answers file {path}: {exc}") from exc
    return check_answers(data)


def check_answers(data: Dict[str, Any]) -> Dict[str, Any]:
    problems = schemalite.validate(data, schemalite.load_schema(
        paths.resource("schema", "answers.schema.json")))
    if problems:
        raise WizardError("answers do not match schema/answers.schema.json:\n  "
                          + "\n  ".join(problems))
    return data


def answers_to_config(answers: Dict[str, Any]) -> Dict[str, Any]:
    """Map answers onto a full config dict (defaults for everything not answered)."""
    who = answers.get("who", {})
    cfg = config.defaults(who.get("timezone"))
    cfg["profile_id"] = answers.get("where", {}).get("profile_id", "default")
    persona = cfg["persona"]
    for key in ("name", "handle", "role", "niche", "audience", "goal"):
        if key in who:
            persona[key] = who[key]
    if "languages" in who:
        persona["languages"] = list(who["languages"])
        persona["primary_language"] = who.get("primary_language", who["languages"][0])
    elif "primary_language" in who:
        persona["primary_language"] = who["primary_language"]
    persona["pillars"] = who.get("pillars") or [
        {"id": "P1", "name": who.get("niche") or "Main topic", "share": 1.0}]
    cfg["locale"]["audience_regions"] = list(who.get("audience_regions", []))
    privacy = answers.get("privacy", {})
    for key in ("private_terms", "never_say", "sensitive_rules"):
        if key in privacy:
            persona[key] = list(privacy[key])
    voice = answers.get("voice", {})
    if "style_preset" in voice:
        persona["style_preset"] = voice["style_preset"]
    persona["demo"] = bool(answers.get("options", {}).get("demo", False))
    brand_in = answers.get("brand", {})
    brand = cfg["brand"]
    if "font_source" in brand_in:
        brand["font_source"] = brand_in["font_source"]
    for role, spec in brand_in.get("fonts", {}).items():
        if role == "licence_note":
            brand["fonts"]["licence_note"] = spec
        else:
            brand["fonts"][role] = {"family": spec["family"], "files": list(spec.get("files", []))}
    if "palette_mode" in brand_in:
        brand["palette"]["mode"] = brand_in["palette_mode"]
    if "identity" in brand_in:
        brand["identity"].update(brand_in["identity"])
    cad = answers.get("cadence", {})
    posting = cfg["posting"]
    if "per_week" in cad:
        posting["per_week"] = cad["per_week"]
        if "weekdays" not in cad:
            posting["weekdays"] = list(DEFAULT_WEEKDAYS[cad["per_week"]])
    if "weekdays" in cad:
        posting["weekdays"] = list(cad["weekdays"])
    if "window" in cad:
        posting["window"] = dict(cad["window"])
    if "min_gap_hours" in cad:
        posting["min_gap_hours"] = cad["min_gap_hours"]
    if "comment_daily_cap" in cad:
        cfg["engagement"]["comments"]["daily_cap"] = cad["comment_daily_cap"]
        cfg["engagement"]["comments"]["reply_reserve"] = min(
            cfg["engagement"]["comments"]["reply_reserve"], cad["comment_daily_cap"])
    if "connect_weekly_slots" in cad:
        cfg["engagement"]["connect"]["weekly_slots"] = cad["connect_weekly_slots"]
    models = answers.get("models", {})
    runner = cfg["models"]["runner"]
    if "mode" in models:
        cfg["models"]["mode"] = models["mode"]
    if "auth" in models:
        runner["auth"] = models["auth"]
    if models.get("api_key_env"):
        runner["api_key_env"] = models["api_key_env"]
    return cfg


# ----------------------------------------------------------------- artifacts

def _persona_json(cfg: Dict[str, Any], fictional: bool) -> Dict[str, Any]:
    p = cfg["persona"]
    doc = {k: p[k] for k in ("name", "handle", "role", "niche", "audience", "goal", "languages",
                            "primary_language", "pillars")}
    doc["schema_version"] = 1
    doc["audience_regions"] = cfg["locale"]["audience_regions"]
    doc["timezone"] = cfg["locale"]["timezone"]
    if fictional:
        doc["fictional"] = True
    return doc


def _voice_md(cfg: Dict[str, Any], voice: Dict[str, Any]) -> str:
    lines = [f"# Voice notes: {cfg['persona']['name']}", ""]
    if cfg["persona"]["demo"]:
        lines += ["> Fictional demo persona. Not a real person.", ""]
    lines += [f"Style preset: `{cfg['persona']['style_preset']}`", ""]
    answers = voice.get("answers", {})
    if answers:
        lines += ["## Style answers", ""]
        lines += [f"- **{k}:** {v}" for k, v in answers.items()]
        lines.append("")
    samples = voice.get("samples", [])
    if samples:
        lines += ["## Past posts that sound like you", ""]
        for i, text in enumerate(samples, start=1):
            lines += [f"### Sample {i}", "", text.strip(), ""]
    if not answers and not samples:
        lines += ["Add 3 to 5 past posts, or answer six style questions with the setup skill.", ""]
    return "\n".join(lines)


def _add_facts(ws: Path, facts: List[Dict[str, Any]]) -> str:
    """Write interview rows as draft facts through the facts package when it is installed."""
    if not facts:
        return "facts: none given (add them with 'njli facts add')"
    try:
        reg = importlib.import_module("njli.facts.registers")
    except ImportError:
        return "facts: njli.facts is not installed; answers kept in .njl/onboarding.json"
    count = 0
    for row in facts:
        reg.add_entry(ws / "research" / "facts.md", "fact", text=row["claim"],
                      numbers=row.get("number", ""), source=row["source"])
        count += 1
    return (f"facts: {count} rows written as draft; verify each yourself in a terminal "
            "('njli facts verify <ID> --evidence <path|url>')")


def _git(ws: Path, *args: str) -> subprocess.CompletedProcess:
    git = shutil.which("git")
    if not git:
        raise FileNotFoundError("git")
    env = dict(os.environ)
    for key, value in (("GIT_AUTHOR_NAME", "nj-linkedin"), ("GIT_COMMITTER_NAME", "nj-linkedin"),
                       ("GIT_AUTHOR_EMAIL", "njli@example.invalid"),
                       ("GIT_COMMITTER_EMAIL", "njli@example.invalid")):
        existing = subprocess.run([git, "config", "--get",
                                   "user.name" if "NAME" in key else "user.email"],
                                  cwd=str(ws), capture_output=True, text=True).stdout.strip()
        if not existing:
            env[key] = value
    return subprocess.run([git, *args], cwd=str(ws), capture_output=True, text=True,
                          timeout=120, env=env)


def _commit(ws: Path) -> str:
    try:
        add = _git(ws, "add", "-A")
        if add.returncode != 0:
            return f"git add failed: {add.stderr.strip()[:100]}"
        done = _git(ws, "commit", "-m", f"nj-linkedin {__version__}: initial workspace")
    except FileNotFoundError:
        return "git not found: skipped the first commit"
    return "first commit made" if done.returncode == 0 else \
        f"git commit failed: {(done.stderr or done.stdout).strip()[:100]}"


def _leak_note(ws: Path) -> str:
    try:
        leak = importlib.import_module("njli.leakcheck")
        findings = leak.scan_tree(ws)
    except Exception as exc:  # a missing or failing scanner must not block setup
        return f"leaks scan: not run ({exc.__class__.__name__})"
    return f"leaks scan --workspace: {len(findings)} findings" + \
        ("" if not findings else " (review before you push the workspace)")


def _onboarding_path(ws: Path) -> Path:
    return ws / ".njl" / "onboarding.json"


def _record(ws: Path, steps: Dict[str, Dict[str, str]], extra: Optional[Dict[str, Any]] = None
            ) -> None:
    path = _onboarding_path(ws)
    doc = read_json(path, default={"schema_version": 1, "steps": {}})
    doc["steps"].update(steps)
    doc.update(extra or {})
    atomic_write_json(path, doc)


def _step(status: str, note: str = "") -> Dict[str, str]:
    return {"status": status, "note": note,
            "at": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds")}


def onboarding_status(ws: Path) -> Dict[str, Any]:
    return read_json(_onboarding_path(ws), default={"schema_version": 1, "steps": {}})


# ------------------------------------------------------------------- operations

def preflight(allow_no_claude: bool, plugin_root: Optional[Path] = None) -> Dict[str, Any]:
    """Step 0. Stops only when Python is too old or (unless allowed) the claude CLI is missing."""
    result = doctor.run(plugin_root=plugin_root)
    blockers = []
    for check in result["checks"]:
        if check["id"] == "python" and check["status"] == "fail":
            blockers.append(check)
        if check["id"] == "claude" and check["status"] != "pass" and not allow_no_claude:
            blockers.append(check)
    result["blockers"] = blockers
    return result


def init_workspace(target: Path, answers: Dict[str, Any], plugin_root: Optional[Path] = None,
                   git: bool = True, require_claude: bool = False) -> Dict[str, Any]:
    """Create a workspace from answers. Returns a summary dict (also used by --json)."""
    check_answers(answers)
    pre = preflight(allow_no_claude=not require_claude, plugin_root=plugin_root)
    if pre["blockers"]:
        raise WizardError("preflight failed: " + "; ".join(
            f"{b['name']}: {b['detail']} -> {b['hint']}" for b in pre["blockers"]))
    cfg = answers_to_config(answers)
    report = config.validate(cfg)
    if report.errors:
        raise WizardError("these answers give an invalid config:\n  " + "\n  ".join(report.errors))
    ws = paths.workspace_path(cfg["profile_id"], str(target)) if target else \
        paths.workspace_path(cfg["profile_id"])
    created = scaffold.create_workspace(ws, cfg, plugin_root, git=git)
    notes = list(created["notes"])
    voice = answers.get("voice", {})
    fictional = bool(cfg["persona"]["demo"])
    atomic_write_json(ws / "profile" / "persona.json", _persona_json(cfg, fictional))
    atomic_write_text(ws / "profile" / "voice.md", _voice_md(cfg, voice))
    notes.append(_add_facts(ws, answers.get("facts", [])))

    consent_notes = []
    for action, phrase in answers.get("consent", {}).items():
        try:
            config.ack(ws, action, phrase, root=plugin_root)
            consent_notes.append(f"{action}: acknowledged")
        except ValueError as exc:
            raise WizardError(f"consent for '{action}' was not recorded: {exc}") from exc
    steps = {name: _step("done") for name in
             ("where", "who", "privacy", "voice", "brand", "cadence", "models")}
    steps["preflight"] = _step("done", f"{pre['summary']['fail']} fail, {pre['summary']['warn']} warn")
    steps["facts"] = _step("done" if answers.get("facts") else "skipped", notes[-1])
    steps["consent"] = _step("done" if consent_notes else "skipped",
                             "; ".join(consent_notes) or "safe defaults kept")
    for name, pointer in EXTERNAL.items():
        steps[name] = _step("external", pointer)
    steps["wrapup"] = _step("done")
    _record(ws, steps, {"answers_keys": sorted(answers)})
    if git and answers.get("options", {}).get("git_commit", True):
        notes.append(_commit(ws))
        notes.append(_leak_note(ws))
    return {"workspace": str(ws), "profile_id": cfg["profile_id"], "demo": fictional,
            "preflight": pre["summary"], "notes": notes,
            "next": ["njli doctor --workspace " + str(ws),
                     "add and verify facts: njli facts add / njli facts verify",
                     "plan a week: njli calendar fill --weeks 1"]}


def init_demo(target: Optional[Path] = None, plugin_root: Optional[Path] = None) -> Dict[str, Any]:
    """Seed the fictional demo persona into a temp (or given) workspace."""
    root = Path(plugin_root) if plugin_root else paths.plugin_root()
    folder = Path(target) if target else Path(tempfile.mkdtemp(prefix="njli-demo-")) / "demo"
    summary = init_workspace(folder, DEMO_ANSWERS, root, git=True)
    examples = root / "examples" / "demo-persona"
    if examples.is_dir():
        summary["notes"].append(f"demo data copied: {scaffold.copy_examples(examples, Path(summary['workspace']))} files")
    else:
        summary["notes"].append("examples/demo-persona is not installed yet; empty demo workspace")
    return summary


# Per-section answer application for an existing workspace (--section).
_SECTION_KEYS = {
    "who": "who", "privacy": "privacy", "voice": "voice", "brand": "brand",
    "cadence": "cadence", "models": "models",
}


def apply_section(ws: Path, section: str, answers: Dict[str, Any],
                  plugin_root: Optional[Path] = None) -> Dict[str, Any]:
    """Re-enter one step on an existing workspace and update config plus its files."""
    if section not in SECTIONS:
        raise WizardError(f"unknown section '{section}'; choose from {', '.join(SECTIONS)}")
    check_answers(answers)
    ws = Path(ws)
    if section in EXTERNAL:
        _record(ws, {section: _step("external", EXTERNAL[section])})
        return {"workspace": str(ws), "section": section, "notes": [EXTERNAL[section]]}
    if section in ("preflight", "wrapup", "where"):
        raise WizardError(f"'{section}' cannot be re-entered on an existing workspace")
    notes: List[str] = []
    if section == "facts":
        notes.append(_add_facts(ws, answers.get("facts", [])))
    elif section == "consent":
        for action, phrase in answers.get("consent", {}).items():
            config.ack(ws, action, phrase, root=plugin_root)
            notes.append(f"{action}: acknowledged")
    else:
        stored = config.load(ws)
        stored_answers = {"where": {"profile_id": stored["profile_id"]},
                          _SECTION_KEYS[section]: answers.get(_SECTION_KEYS[section], {})}
        if section != "who":
            stored_answers["who"] = {"name": stored["persona"]["name"] or "x",
                                     "languages": stored["persona"]["languages"],
                                     "goal": stored["persona"]["goal"]}
        fresh = answers_to_config(stored_answers)
        updated = _merge_section(stored, fresh, section,
                                 answers.get("who", {}).get("timezone"))
        report = config.validate(updated, ws)
        if report.errors:
            raise WizardError("these answers give an invalid config:\n  " + "\n  ".join(report.errors))
        atomic_write_json(config.config_path(ws), updated)
        if section == "voice":
            atomic_write_text(ws / "profile" / "voice.md", _voice_md(updated, answers.get("voice", {})))
        if section == "who":
            atomic_write_json(ws / "profile" / "persona.json",
                              _persona_json(updated, updated["persona"]["demo"]))
        notes.append(f"{section}: config/njli.json updated")
    _record(ws, {section: _step("done", "; ".join(notes))})
    return {"workspace": str(ws), "section": section, "notes": notes}


def _merge_section(stored: Dict[str, Any], fresh: Dict[str, Any], section: str,
                   timezone: Optional[str] = None) -> Dict[str, Any]:
    out = json.loads(json.dumps(stored))
    if section == "who":
        for key in ("name", "handle", "role", "niche", "audience", "goal", "languages",
                    "primary_language", "pillars"):
            out["persona"][key] = fresh["persona"][key]
        out["locale"]["audience_regions"] = fresh["locale"]["audience_regions"]
        if timezone:
            out["locale"]["timezone"] = fresh["locale"]["timezone"]
    elif section == "privacy":
        for key in ("private_terms", "never_say", "sensitive_rules"):
            out["persona"][key] = fresh["persona"][key]
    elif section == "voice":
        out["persona"]["style_preset"] = fresh["persona"]["style_preset"]
    elif section == "brand":
        out["brand"] = fresh["brand"]
    elif section == "cadence":
        out["posting"].update({k: fresh["posting"][k] for k in
                               ("per_week", "weekdays", "window", "min_gap_hours")})
        out["engagement"]["comments"]["daily_cap"] = fresh["engagement"]["comments"]["daily_cap"]
        out["engagement"]["comments"]["reply_reserve"] = \
            fresh["engagement"]["comments"]["reply_reserve"]
        out["engagement"]["connect"]["weekly_slots"] = \
            fresh["engagement"]["connect"]["weekly_slots"]
    elif section == "models":
        out["models"]["mode"] = fresh["models"]["mode"]
        out["models"]["runner"]["auth"] = fresh["models"]["runner"]["auth"]
        out["models"]["runner"]["api_key_env"] = fresh["models"]["runner"]["api_key_env"]
    return out


# ------------------------------------------------------------ terminal fallback

EXPRESS_QUESTIONS = (
    ("name", "Your name"), ("handle", "Your LinkedIn handle (without the URL)"),
    ("role", "Your role or headline"), ("niche", "Your niche or topic"),
    ("audience", "Who you write for"), ("languages", "Languages you post in (comma separated, e.g. en,ar)"),
    ("goal", "Goal: authority, clients, job_seeking, hiring or network"),
)


def express_answers(ask: Callable[[str], str]) -> Dict[str, Any]:
    """Seven questions in a terminal, defaults for everything else."""
    who: Dict[str, Any] = {}
    for key, prompt in EXPRESS_QUESTIONS:
        reply = ask(prompt + ": ").strip()
        if key == "languages":
            who["languages"] = [p.strip() for p in reply.split(",") if p.strip()] or ["en"]
        elif key == "goal":
            who["goal"] = reply if reply in policy.GOALS else "authority"
        else:
            who[key] = reply
    if not who.get("name"):
        raise WizardError("a name is required")
    who["timezone"] = ask(f"Time zone [{config.defaults()['locale']['timezone']}]: ").strip() or \
        config.defaults()["locale"]["timezone"]
    return {"schema_version": 1, "who": who}
