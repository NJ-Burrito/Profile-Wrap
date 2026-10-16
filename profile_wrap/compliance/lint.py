"""`profile-wrap compliance lint`: scan profile_wrap/ and skills/ for code the package must never contain."""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

from . import rules as R


@dataclass(frozen=True)
class Violation:
    rule: str
    path: str
    line: int
    hint: str

    def render(self) -> str:
        return f"{self.rule}  {self.path}:{self.line}  {self.hint}"


def _pragma_ids(lines: list[str], i: int) -> set[str]:
    ids: set[str] = set()
    for j in (i, i - 1):
        if 0 <= j < len(lines):
            m = R.PRAGMA.search(lines[j])
            if m:
                ids |= {x.strip().lower() for x in m.group(1).split(",") if x.strip()}
    return ids


def lint_text(text: str, rel: str) -> list[Violation]:
    out: list[Violation] = []
    name = rel.rsplit("/", 1)[-1]
    lines = text.splitlines()

    def add(rule: str, i: int, hint: str) -> None:
        if rule not in _pragma_ids(lines, i):
            out.append(Violation(rule, rel, i + 1, hint))

    for i, line in enumerate(lines):
        for rule in R.RULES:
            if rule.only_in and not rel.startswith(rule.only_in):
                continue
            if any(rel.startswith(p) for p in rule.except_in) or name in rule.except_names:
                continue
            if rule.pattern.search(line):
                add(rule.id, i, rule.hint)
        if rel.startswith(R.LINKEDIN_PKG):
            for m in R.ENDPOINT.finditer(line):
                ok = m.group(0).startswith(R.ALLOWED_ENDPOINTS) or ("extra" in rel and m.group(0).startswith("/v2/socialActions"))
                if not ok:
                    add("api-endpoint", i, f"endpoint outside the allowlist {R.ALLOWED_ENDPOINTS}")
            if R.EXTRA_ONLY.search(line) and "extra" not in rel:
                add("api-endpoint", i, "socialActions exists only in the experimental extra")
    if R.LINKEDIN_DOMAIN.search(text):
        for i, line in enumerate(lines):
            if R.AUTOMATION_LIB.search(line):
                add("browser-linkedin", i, "browser automation in a file that names linkedin.com")
                break
    return out


def lint(root: str | Path, scan_dirs: tuple[str, ...] = R.SCAN_DIRS) -> list[Violation]:
    root = Path(root)
    out: list[Violation] = []
    for d in scan_dirs:
        base = root / d
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in R.TEXT_SUFFIXES:
                continue
            rel = p.relative_to(root).as_posix()
            if any(part in R.SKIP_DIRS for part in p.relative_to(root).parts) or rel.startswith(R.SKIP_PREFIXES):
                continue
            out.extend(lint_text(p.read_text(encoding="utf-8", errors="replace"), rel))
    return out


def run_lint(args: argparse.Namespace) -> int:
    root = Path(args.root)
    if not root.is_dir():
        print(f"compliance lint: not a directory: {root}", file=sys.stderr)
        return 2
    found = lint(root)
    for v in found:
        print(v.render())
    print(f"compliance lint: {'FAIL' if found else 'PASS'} ({len(found)} violations)")
    return 1 if found else 0


def _populate(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="compliance_cmd", required=True)
    s = sub.add_parser("lint", help="scan profile_wrap/ and skills/ for forbidden code and wording")
    s.add_argument("--root", default=".", help="repository root (default .)")
    s.set_defaults(func=run_lint)


def register(subparsers) -> None:
    """Add `compliance` to the profile-wrap subparsers. Handlers are set as args.func(args) -> exit code."""
    _populate(subparsers.add_parser("compliance", help="compliance by construction"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="profile-wrap compliance")
    _populate(ap)
    args = ap.parse_args(argv)
    return args.func(args)
