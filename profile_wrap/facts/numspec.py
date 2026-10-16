"""Number specs: the machine-readable form of the `numbers` column of facts and stats.

A spec is a value plus an optional unit. The gate matches the text's number and unit against these,
so "7 bugs" is only proven by a cited fact that lists 7 with the unit bugs (or no unit at all).
Self-contained and stdlib only: profile_wrap.gate imports from here, never the other way round.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_DIGIT_TABLE = {0x0660 + i: ord("0") + i for i in range(10)}
_DIGIT_TABLE.update({0x06F0 + i: ord("0") + i for i in range(10)})
_DIGIT_TABLE[0x066B] = ord(".")
_DIGIT_TABLE[0x066C] = ord(",")
_DIGIT_TABLE[0x066A] = ord("%")

CURRENCY = {"$": "usd", "€": "eur", "£": "gbp"}
_DATE_LIKE = re.compile(
    r"\b\d{1,2}/\d{4}\b|\b\d{4}-\d{2}(?:-\d{2})?\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b|\b\d{1,2}:\d{2}\b"
)
_NUM = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_PCT_WORDS = {"percent", "percentage", "pct", "٪"}
_SKIP_WORDS = {"per", "a", "an", "of", "the", "in", "and", "to", "or", "since", "from", "by"}


def normalise_digits(text: str) -> str:
    """Arabic-Indic and Persian digits (and their separators) to ASCII."""
    return text.translate(_DIGIT_TABLE)


def norm_unit(word: str) -> str:
    """Lowercase a unit word and drop a plural ending so 'hours' equals 'hour'."""
    w = word.casefold().strip()
    if w in {"percent", "percentage", "pct", "per cent"}:
        return "%"
    if len(w) > 3 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith(("sses", "xes", "ches", "shes")):
        return w[:-2]
    if len(w) > 2 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def to_float(token: str) -> float:
    return float(token.replace(",", ""))


@dataclass(frozen=True)
class NumSpec:
    value: float
    unit: str  # normalised unit word, "" when none; "%" for percent
    raw: str

    @property
    def pct(self) -> bool:
        return self.unit == "%"


def _blank_dates(entry: str) -> str:
    return _DATE_LIKE.sub(lambda m: " " * len(m.group(0)), entry)


def parse_entry(entry: str) -> list[NumSpec]:
    """Parse one entry such as '180+ hours', '8-16', '30%' or '$5 per month' into NumSpecs."""
    text = normalise_digits(entry).replace("\u2013", "-").replace("\u2014", "-")
    text = _blank_dates(text)
    out: list[NumSpec] = []
    matches = list(_NUM.finditer(text))
    if not matches:
        return out
    last_end = matches[-1].end()
    tail = text[last_end:]
    unit = ""
    tail_stripped = tail.lstrip(" +~")
    if tail_stripped.startswith("%"):
        unit = "%"
    else:
        for m in _WORD.finditer(tail_stripped):
            w = m.group(0)
            if w.casefold() in _SKIP_WORDS:
                continue
            unit = "%" if w.casefold() in _PCT_WORDS else norm_unit(w)
            break
    for m in matches:
        pre = text[max(0, m.start() - 1):m.start()]
        u = unit
        if pre in CURRENCY:
            u = CURRENCY[pre]
        out.append(NumSpec(to_float(m.group(0)), u, m.group(0)))
    return out


def parse_number_cell(cell: str) -> list[NumSpec]:
    """Parse a whole `numbers` cell: entries separated by ';', newlines or '<br>'."""
    if not cell or not cell.strip() or cell.strip() in {"-", "none", "n/a"}:
        return []
    parts = re.split(r";|؛|<br\s*/?>|\n", cell)
    specs: list[NumSpec] = []
    for part in parts:
        specs.extend(parse_entry(part))
    return specs


def unitless_entries(cell: str) -> list[str]:
    """Entries of the cell that carry a number but no unit (lint warns: a bare number proves little)."""
    bad = []
    for part in re.split(r";|؛|<br\s*/?>|\n", cell or ""):
        specs = parse_entry(part)
        if specs and not any(s.unit for s in specs):
            bad.append(part.strip())
    return bad
