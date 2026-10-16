"""The facts register (research/facts.md) and the stats register (research/stats.md).

Facts are claims about the user. A fact is `verified` only by the user, in a terminal.
Stats are dated third-party figures; only a verified, unexpired grade-A stat may back a public number.
"""
from __future__ import annotations

import datetime as _dt
import getpass
import os
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

from .numspec import NumSpec, parse_number_cell, unitless_entries
from .table import Table, atomic_write_text, parse_table

FACT_COLUMNS = ["id", "claim", "numbers", "source", "status", "verified_by", "verified_at", "evidence",
                "usage", "supersedes", "demo", "added"]
STAT_COLUMNS = ["id", "stat", "numbers", "source", "retrieved", "sample", "grade", "expires", "kind",
                "status", "verified_by", "verified_at"]
FACT_STATUSES = ("draft", "verified", "do_not_use", "superseded")
STAT_STATUSES = ("draft", "verified", "expired", "retired")
GRADES = ("A", "B", "C", "X")
_ID = {"fact": re.compile(r"^F\d{2,4}$"), "stat": re.compile(r"^S\d{2,4}$")}
_TRUE = {"yes", "y", "true", "1", "demo"}
_FALSE = {"", "no", "n", "false", "0", "-"}


@dataclass
class Entry:
    kind: str  # "fact" | "stat"
    id: str
    text: str  # claim or stat sentence
    numbers_raw: str
    specs: list[NumSpec]
    source: str
    status: str
    row: dict[str, str] = field(default_factory=dict)

    @property
    def demo(self) -> bool:
        return self.row.get("demo", "").strip().casefold() in _TRUE

    @property
    def grade(self) -> str:
        return self.row.get("grade", "").strip().upper()

    @property
    def expires(self) -> _dt.date | None:
        return parse_date(self.row.get("expires", ""))


@dataclass
class Register:
    path: Path
    kind: str
    table: Table
    entries: list[Entry]
    problems: list[str]  # readable load problems (missing file, BOM, no table)
    exists: bool = True

    def get(self, ident: str) -> Entry | None:
        for e in self.entries:
            if e.id == ident:
                return e
        return None


def parse_date(value: str) -> _dt.date | None:
    try:
        return _dt.date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def today() -> _dt.date:
    return _dt.date.today()


def _build_entries(kind: str, table: Table) -> list[Entry]:
    textcol = "claim" if kind == "fact" else "stat"
    out = []
    for row in table.rows:
        ident = row.get("id", "").strip()
        if not ident:
            continue
        nums = row.get("numbers", "")
        out.append(Entry(kind, ident, row.get(textcol, ""), nums, parse_number_cell(nums),
                         row.get("source", ""), (row.get("status", "") or "draft").strip().casefold(), row))
    return out


def load_register(path: Path, kind: str) -> Register:
    """Load a register; a missing file, a BOM or a missing table become readable problems, never a traceback."""
    label = "facts" if kind == "fact" else "stats"
    problems: list[str] = []
    try:
        text = path.read_bytes().decode("utf-8-sig")
        raw_bom = path.read_bytes().startswith(b"\xef\xbb\xbf")
    except FileNotFoundError:
        return Register(path, kind, Table(), [], [f"{label} file not found: {path} (create it with `profile-wrap {label} add`)"], False)
    except (OSError, UnicodeDecodeError) as exc:
        return Register(path, kind, Table(), [], [f"{label} file unreadable: {path}: {exc}"], False)
    if raw_bom:
        problems.append(f"{label} file starts with a UTF-8 BOM: {path.name} (re-save as UTF-8 without BOM)")
    table = parse_table(text)
    if not table.has_table:
        problems.append(f"{label} file has no pipe table: {path.name}")
    return Register(path, kind, table, _build_entries(kind, table), problems, True)


def lint_register(reg: Register) -> list[tuple[str, str]]:
    """Return [(level, message)] with level 'FAIL' or 'WARN'."""
    out: list[tuple[str, str]] = [("FAIL", p) for p in reg.problems if "BOM" not in p]
    out += [("WARN", p) for p in reg.problems if "BOM" in p]
    if not reg.exists:
        return out
    kind = reg.kind
    textcol = "claim" if kind == "fact" else "stat"
    need = ["id", textcol, "numbers", "source"] + (["status"] if kind == "fact" else ["grade", "expires", "retrieved"])
    for col in need:
        if reg.table.has_table and col not in reg.table.columns:
            out.append(("FAIL", f"missing column '{col}' in {reg.path.name}"))
    seen: set[str] = set()
    statuses = FACT_STATUSES if kind == "fact" else STAT_STATUSES
    for e in reg.entries:
        if e.id in seen:
            out.append(("FAIL", f"{e.id}: duplicate id"))
        seen.add(e.id)
        if not _ID[kind].match(e.id):
            out.append(("FAIL", f"{e.id}: id must look like {'F01' if kind == 'fact' else 'S01'}"))
        if not e.text.strip():
            out.append(("FAIL", f"{e.id}: empty {textcol}"))
        if not e.source.strip():
            out.append(("FAIL", f"{e.id}: source is required"))
        if e.status not in statuses:
            out.append(("FAIL", f"{e.id}: status '{e.status}' not one of {', '.join(statuses)}"))
        if e.numbers_raw.strip() and not e.specs:
            out.append(("WARN", f"{e.id}: numbers cell has no readable number: {e.numbers_raw!r}"))
        for bad in unitless_entries(e.numbers_raw):
            out.append(("WARN", f"{e.id}: '{bad}' has no unit; write '7 bugs', not '7' (a bare number proves little)"))
        if e.status == "verified" and not (e.row.get("verified_by", "").strip() and e.row.get("verified_at", "").strip()):
            out.append(("WARN", f"{e.id}: verified without verified_by / verified_at"))
        demo = e.row.get("demo", "").strip().casefold()
        if demo not in _TRUE and demo not in _FALSE:
            out.append(("WARN", f"{e.id}: demo column should be yes or no, got {demo!r}"))
        if kind == "stat":
            if e.grade not in GRADES:
                out.append(("FAIL", f"{e.id}: grade '{e.grade}' not one of {'/'.join(GRADES)}"))
            if e.row.get("kind", "").strip() not in ("", "third_party"):
                out.append(("WARN", f"{e.id}: kind should be third_party"))
            if not re.match(r"^https?://", e.source.strip()):
                out.append(("WARN", f"{e.id}: stat source should be a URL"))
            if e.expires is None:
                out.append(("FAIL", f"{e.id}: expires must be an ISO date (YYYY-MM-DD)"))
            if parse_date(e.row.get("retrieved", "")) is None:
                out.append(("FAIL", f"{e.id}: retrieved must be an ISO date (YYYY-MM-DD)"))
    if kind == "fact":
        ids = {e.id for e in reg.entries}
        for e in reg.entries:
            sup = e.row.get("supersedes", "").strip()
            if not sup:
                continue
            for target in re.split(r"[,\s]+", sup):
                if not target:
                    continue
                if target not in ids:
                    out.append(("FAIL", f"{e.id}: supersedes unknown id {target}"))
                elif target == e.id:
                    out.append(("FAIL", f"{e.id}: supersedes itself"))
                else:
                    t = reg.get(target)
                    if t is not None and t.status == "verified":
                        out.append(("WARN", f"{e.id}: supersedes {target} but {target} is still verified"))
        for e in reg.entries:  # cycle check along supersedes chains
            cur: Entry | None = e
            hops = 0
            while cur is not None and cur.row.get("supersedes", "").strip() and hops <= len(reg.entries):
                nxt = re.split(r"[,\s]+", cur.row["supersedes"].strip())[0]
                cur = reg.get(nxt)
                hops += 1
                if cur is not None and cur.id == e.id:
                    out.append(("FAIL", f"{e.id}: supersedes chain loops back to itself"))
                    break
    return out


def next_id(reg: Register) -> str:
    prefix = "F" if reg.kind == "fact" else "S"
    nums = [int(m.group(1)) for e in reg.entries if (m := re.match(rf"^{prefix}(\d+)$", e.id))]
    return f"{prefix}{(max(nums) + 1 if nums else 1):02d}"


def _save(reg: Register) -> None:
    atomic_write_text(reg.path, reg.table.render())


def _new_register(path: Path, kind: str) -> Register:
    cols = FACT_COLUMNS if kind == "fact" else STAT_COLUMNS
    title = "# Facts register\n" if kind == "fact" else "# Stats register\n"
    note = ("Every number in a post must come from a verified fact listed in the post's `claims`.\n"
            if kind == "fact" else "Dated third-party figures. Only a verified, unexpired grade-A stat may be quoted.\n")
    table = Table(prelude=[title.strip(), "", note.strip(), ""], columns=list(cols), has_table=True)
    return Register(path, kind, table, [], [], True)


def add_entry(path: Path, kind: str, *, text: str, numbers: str, source: str, ident: str | None = None,
              extra: dict[str, str] | None = None) -> Entry:
    """Append a row with status draft. Refuses a duplicate id or an empty text or source."""
    if not text.strip() or not source.strip():
        raise ValueError("a claim and a source are both required")
    reg = load_register(path, kind) if path.exists() else _new_register(path, kind)
    if not reg.table.has_table:
        reg = _new_register(path, kind)
    cols = FACT_COLUMNS if kind == "fact" else STAT_COLUMNS
    reg.table.ensure_columns(cols)
    new_id = ident or next_id(reg)
    if reg.get(new_id):
        raise ValueError(f"id {new_id} already exists")
    if not _ID[kind].match(new_id):
        raise ValueError(f"id {new_id} must look like {'F01' if kind == 'fact' else 'S01'}")
    textcol = "claim" if kind == "fact" else "stat"
    row = {c: "" for c in reg.table.columns}
    row.update({"id": new_id, textcol: text.strip(), "numbers": numbers.strip(), "source": source.strip(),
                "status": "draft"})
    if kind == "fact":
        row["added"] = today().isoformat()
        row["demo"] = "no"
    else:
        row["kind"] = "third_party"
    row.update(extra or {})
    reg.table.rows.append(row)
    _save(reg)
    return _build_entries(kind, Table(columns=reg.table.columns, rows=[row]))[0]


def is_tty() -> bool:
    try:
        return bool(sys.stdin.isatty() and sys.stdout.isatty())
    except (AttributeError, ValueError):
        return False


class VerifyRefused(Exception):
    """The verification gate said no; the message is the readable reason."""


def check_verify_allowed(env: Mapping[str, str] | None = None, tty: Callable[[], bool] = is_tty) -> None:
    env_map: Mapping[str, str] = os.environ if env is None else env
    if env_map.get("PROFILE_WRAP_WORKER", "") == "1":
        raise VerifyRefused("refused: PROFILE_WRAP_WORKER=1. An agent cannot mark a fact verified; only the user can, in a terminal.")
    if not tty():
        raise VerifyRefused("refused: no interactive terminal. Run `profile-wrap facts verify` yourself in a terminal; scripts and agents cannot verify.")


def _check_evidence(workspace: Path, evidence: str) -> str:
    ev = evidence.strip()
    if not ev:
        raise VerifyRefused("refused: --evidence is required (a file path or an http(s) URL)")
    if re.match(r"^https?://\S+$", ev):
        return ev
    p = Path(ev)
    if not p.is_absolute():
        p = workspace / p
    if not p.exists():
        raise VerifyRefused(f"refused: evidence file not found: {ev}")
    return ev


def verify_entry(path: Path, kind: str, ident: str, evidence: str, *, workspace: Path, verifier: str = "",
                 env: Mapping[str, str] | None = None, tty: Callable[[], bool] = is_tty,
                 ask: Callable[[str], str] = input, on_date: _dt.date | None = None) -> Entry:
    """Mark one entry verified after the checks: not a worker, a real terminal, evidence, typed confirmation."""
    check_verify_allowed(env, tty)
    reg = load_register(path, kind)
    entry = reg.get(ident)
    if entry is None:
        raise VerifyRefused(f"refused: {ident} not found in {path.name}")
    ev = _check_evidence(workspace, evidence)
    if kind == "stat" and entry.grade not in GRADES:
        raise VerifyRefused(f"refused: {ident} has no grade A/B/C/X")
    answer = ask(f"{ident}: {entry.text}\n  numbers: {entry.numbers_raw}\n  evidence: {ev}\n"
                 f"Type {ident} to confirm you checked the evidence yourself: ").strip()
    if answer != ident:
        raise VerifyRefused("cancelled: confirmation did not match")
    row = next(r for r in reg.table.rows if r.get("id", "").strip() == ident)
    reg.table.ensure_columns(["status", "verified_by", "verified_at"] + (["evidence"] if kind == "fact" else []))
    row["status"] = "verified"
    row["verified_by"] = verifier or _default_verifier()
    row["verified_at"] = (on_date or today()).isoformat()
    if kind == "fact":
        row["evidence"] = ev
    _save(reg)
    return load_register(path, kind).get(ident)  # type: ignore[return-value]


def _default_verifier() -> str:
    try:
        return getpass.getuser()
    except Exception:  # no user database in some containers
        return "user"


def expire_stats(path: Path, *, on_date: _dt.date | None = None, dry_run: bool = False) -> list[str]:
    """Mark verified stats past their `expires` date as expired. Returns the ids changed."""
    reg = load_register(path, "stat")
    when = on_date or today()
    changed = []
    for e in reg.entries:
        if e.status in ("verified", "draft") and e.expires is not None and e.expires < when:
            changed.append(e.id)
            if not dry_run:
                next(r for r in reg.table.rows if r.get("id", "").strip() == e.id)["status"] = "expired"
    if changed and not dry_run:
        _save(reg)
    return changed


def default_expiry(retrieved: _dt.date, days: int) -> _dt.date:
    return retrieved + _dt.timedelta(days=days)


def export_entries(reg: Register, verified_only: bool = False) -> list[dict]:
    out = []
    for e in reg.entries:
        if verified_only and e.status != "verified":
            continue
        d: dict[str, Any] = dict(e.row)
        d["numbers_parsed"] = [{"value": s.value, "unit": s.unit} for s in e.specs]
        out.append(d)
    return out
