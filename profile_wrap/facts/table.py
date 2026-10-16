"""A Markdown pipe table that round-trips: text around the table is kept byte for byte."""
from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

_SPLIT = re.compile(r"(?<!\\)\|")
_SEP_CELL = re.compile(r"^\s*:?-{1,}:?\s*$")

_ALIASES = {"number(s)": "numbers", "number": "numbers", "numbers(s)": "numbers", "claim_id": "id"}


def norm_header(name: str) -> str:
    key = re.sub(r"\s+", "_", name.strip().casefold())
    return _ALIASES.get(key, key)


def split_row(line: str) -> list[str]:
    body = line.strip()
    if body.startswith("|"):
        body = body[1:]
    if body.endswith("|") and not body.endswith("\\|"):
        body = body[:-1]
    return [c.strip().replace("\\|", "|") for c in _SPLIT.split(body)]


def join_row(cells: list[str]) -> str:
    return "| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |"


@dataclass
class Table:
    prelude: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    rows: list[dict[str, str]] = field(default_factory=list)
    postlude: list[str] = field(default_factory=list)
    has_table: bool = False
    bom: bool = False

    def ensure_columns(self, names: list[str]) -> None:
        for n in names:
            if n not in self.columns:
                self.columns.append(n)
                for r in self.rows:
                    r.setdefault(n, "")

    def render(self) -> str:
        lines = list(self.prelude)
        if self.columns:
            lines.append(join_row(self.columns))
            lines.append("|" + "|".join("---" for _ in self.columns) + "|")
            for r in self.rows:
                lines.append(join_row([r.get(c, "") for c in self.columns]))
        lines.extend(self.postlude)
        text = "\n".join(lines)
        return text + ("\n" if not text.endswith("\n") else "")


def parse_table(text: str) -> Table:
    """Parse the first pipe table of a Markdown document. No table gives has_table=False."""
    t = Table()
    if text.startswith("\ufeff"):
        t.bom = True
        text = text.lstrip("\ufeff")
    lines = text.splitlines()
    i = 0
    while i < len(lines) and not (lines[i].lstrip().startswith("|") and i + 1 < len(lines)
                                  and lines[i + 1].lstrip().startswith("|")
                                  and all(_SEP_CELL.match(c) for c in split_row(lines[i + 1]))):
        t.prelude.append(lines[i])
        i += 1
    if i >= len(lines):
        t.prelude = lines
        return t
    t.has_table = True
    t.columns = [norm_header(c) for c in split_row(lines[i])]
    i += 2
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        cells = split_row(lines[i])
        cells += [""] * (len(t.columns) - len(cells))
        t.rows.append(dict(zip(t.columns, cells[: len(t.columns)])))
        i += 1
    t.postlude = lines[i:]
    return t


def atomic_write_text(path: Path, text: str) -> None:
    """Write via a temp file in the same directory and os.replace; leaves no temp file on failure."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
