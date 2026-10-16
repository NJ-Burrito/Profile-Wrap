"""``profile-wrap handoff check``: handoff.md must carry exactly six headings, in this order."""
from __future__ import annotations

import re
from pathlib import Path
from typing import List, Tuple

HEADINGS = (
    "# goals",
    "## current state",
    "## files in flight",
    "## changed",
    "## failed attempts",
    "## next step",
)

_HEADING = re.compile(r"^(#{1,2})\s+(.*?)\s*$")


def _headings(text: str) -> List[Tuple[int, str, int]]:
    """(line number, normalised heading, body line count) for level 1-2 headings."""
    out: List[Tuple[int, str, int]] = []
    in_fence = False
    lines = text.lstrip("﻿").splitlines()
    for number, line in enumerate(lines, start=1):
        if line.strip().startswith("```") or line.strip().startswith("~~~"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = _HEADING.match(line)
        if match:
            out.append((number, f"{match.group(1)} {match.group(2)}", 0))
    # body sizes
    sized: List[Tuple[int, str, int]] = []
    for i, (number, name, _zero) in enumerate(out):
        end = out[i + 1][0] - 1 if i + 1 < len(out) else len(lines)
        body = [ln for ln in lines[number:end] if ln.strip()]
        sized.append((number, name, len(body)))
    return sized


def check_text(text: str) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings)."""
    errors: List[str] = []
    warnings: List[str] = []
    found = _headings(text)
    names = [name for _n, name, _b in found]
    for expected in HEADINGS:
        count = names.count(expected)
        if count == 0:
            near = [n for n in names if n.lower() == expected.lower()]
            if near:
                errors.append(f"heading '{near[0]}' must be written exactly '{expected}'")
            else:
                errors.append(f"missing heading '{expected}'")
        elif count > 1:
            errors.append(f"heading '{expected}' appears {count} times")
    for number, name, _body in found:
        if name not in HEADINGS and name.lower() not in [h.lower() for h in HEADINGS]:
            errors.append(f"line {number}: extra heading '{name}' (use ### for sub-headings)")
    if not errors and names != list(HEADINGS):
        errors.append("headings are out of order; expected: " + ", ".join(HEADINGS))
    if not errors:
        for number, name, body in found:
            if body == 0:
                warnings.append(f"line {number}: section '{name}' is empty (write 'none')")
    return errors, warnings


def check_file(path: Path) -> Tuple[List[str], List[str]]:
    p = Path(path)
    if not p.is_file():
        return [f"{p} not found"], []
    return check_text(p.read_text(encoding="utf-8-sig"))
