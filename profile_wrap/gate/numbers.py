"""Claim-bound number check.

Every number in a public text must be proven by a cited fact or stat: same value, same unit.
A bare "7" somewhere else in the register proves nothing. Dates, ids, versions, list markers,
ordinals, ages and the post's own list counts ("5 tips") are not claims; see EXEMPT_REASONS.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

from profile_wrap.facts.numspec import CURRENCY, NumSpec, norm_unit, normalise_digits

from .findings import FAIL, WARN, finding

EXEMPT_REASONS = ("url", "date", "time", "version", "phone/id", "list marker", "ordinal", "identifier",
                  "year", "label", "age", "list count", "idiom")

_TOKEN = re.compile(r"(?<![\w.,])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?!\d)")
_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_URL = re.compile(r"(?:https?://|www\.)\S+|\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b", re.I)
_DATE = re.compile(
    r"\b\d{4}-\d{1,2}-\d{1,2}\b|\b\d{1,2}[/.]\d{1,2}[/.]\d{2,4}\b|\b\d{1,2}/\d{4}\b|\b\d{4}/\d{1,2}\b|\bQ[1-4]\b",
    re.I)
_TIME = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\s*(?:am|pm)?\b|\b\d{1,2}\s?(?:am|pm)\b", re.I)
_SEMVER = re.compile(r"\b\d+\.\d+\.\d+(?:\.\d+)?\b")
_PHONE = re.compile(r"\+?\d[\d\s().-]{6,}\d")
_IDIOM = re.compile(r"\b24/7\b|\b365/24/7\b|\b9[- ]?(?:to|-)[- ]?5\b|\b1:1\b|\b1[- ]on[- ]1\b|\b100/100\b", re.I)
_AGE_AFTER = re.compile(r"^\s*-?\s*(?:years?|yrs?|y/?o)\b[\s-]*(?:old)?", re.I)
_PCT_WORD = re.compile(r"^\s*(?:percent|percentage|per\s?cent|pct)\b", re.I)

_MONTHS = {m.casefold() for m in (
    "jan january feb february mar march apr april may jun june jul july aug august sep sept september oct october "
    "nov november dec december").split()} | {
    "يناير", "فبراير", "مارس",
    "أبريل", "مايو", "يونيو",
    "يوليو", "أغسطس", "سبتمبر",
    "أكتوبر", "نوفمبر", "ديسمبر"}
_YEAR_PREV = {"in", "since", "by", "from", "until", "till", "during", "of", "year", "fy", "class", "est",
              "سنة", "عام", "منذ", "في"}
_LABEL_PREV = {
    "day", "week", "month", "part", "step", "chapter", "episode", "ep", "slide", "page", "post", "level", "phase",
    "tip", "rule", "lesson", "number", "no", "item", "question", "figure", "fig", "table", "section", "version",
    "v", "release", "python", "node", "ios", "android", "windows", "macos", "chrome", "gpt", "top", "issue",
    "ticket", "pr", "line", "row", "column", "option", "plan", "tier", "round", "stage", "module",
    "الخطوة", "الجزء", "الحلقة",
    "اليوم", "الفصل", "الدرس",
    "الصفحة", "رقم", "نصيحة"}
STRUCT_UNITS = {
    "tip", "step", "lesson", "way", "thing", "reason", "mistake", "rule", "question", "point", "slide", "idea",
    "habit", "takeaway", "example", "part", "tool", "pillar", "principle", "framework", "template", "prompt",
    "trick", "hack", "myth", "sign", "checklist", "check", "word", "paragraph",
    "خطوة", "خطوات", "نصيحة",
    "نصائح", "درس", "دروس", "سبب",
    "أسباب", "خطأ", "أخطاء", "فكرة",
    "أفكار", "قاعدة", "قواعد",
    "نقطة", "نقاط", "طريقة", "طرق",
    "أداة", "أدوات"}
_STOP = {"a", "an", "the", "of", "in", "on", "at", "to", "and", "or", "for", "with", "is", "are", "was", "were", "i",
         "we", "it", "that", "this", "my", "our", "by", "as", "from", "than", "per", "so", "but", "them", "they", "you",
         "us", "him", "her", "me", "your", "their", "these", "those", "each", "all", "some", "who", "which",
         "في", "من", "على", "إلى", "و", "عن",
         "مع"}
_ATTACH_UNITS = {"x": "x", "min": "minute", "mins": "minute", "h": "hour", "hr": "hour", "hrs": "hour", "s": "second",
                 "sec": "second", "secs": "second", "ms": "ms", "kb": "kb", "mb": "mb", "gb": "gb", "tb": "tb",
                 "px": "px", "kg": "kg", "km": "km", "cm": "cm", "mm": "mm", "fps": "fps", "hz": "hz",
                 "khz": "khz", "ghz": "ghz", "m": "m"}
_MULT = {"k": 1e3, "m": 1e6, "b": 1e9}
_ORD = {"st", "nd", "rd", "th"}
NUMBER_WORDS = {
    "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve", "thirteen",
    "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "thirty", "forty", "fifty",
    "sixty", "seventy", "eighty", "ninety", "hundred", "thousand", "million", "billion", "dozen", "dozens",
    "hundreds", "thousands", "millions"}
_NUMBER_WORD = re.compile(r"\b(" + "|".join(sorted(NUMBER_WORDS, key=len, reverse=True)) + r")\b\s+([^\W\d_]+)",
                          re.I)


@dataclass
class NumToken:
    value: float
    raw: str
    display: str
    pct: bool = False
    units: list[str] = field(default_factory=list)
    reason: str | None = None  # exempt reason, or None when the number is a claim
    bare: bool = False
    start: int = 0

    def key(self) -> str:
        return self.display


def prepare(text: str) -> str:
    return unicodedata.normalize("NFKC", normalise_digits(text))


def _spans(pattern: re.Pattern, text: str) -> list[tuple[int, int]]:
    return [m.span() for m in pattern.finditer(text)]


def _inside(pos: int, spans: list[tuple[int, int]]) -> bool:
    return any(a <= pos < b for a, b in spans)


def _words_after(text: str, pos: int) -> list[str]:
    window = text[pos:pos + 60]
    cut = re.search(r"[.!?\n;:()\[\]؟؛]|\d", window)
    if cut:
        window = window[: cut.start()]
    words = []
    for m in _WORD.finditer(window):
        w = m.group(0)
        if w.casefold() in _STOP:
            continue
        words.append(norm_unit(w))
        if len(words) == 3:
            break
    return words


def _prev_word(text: str, pos: int) -> str:
    m = re.search(r"([^\W\d_]+)\W{0,2}$", text[max(0, pos - 30):pos], re.UNICODE)
    return m.group(1).casefold() if m else ""


def _next_raw_word(text: str, pos: int) -> str:
    m = re.match(r"\s*([^\W\d_]+)", text[pos:pos + 40], re.UNICODE)
    return m.group(1) if m else ""


def extract(text: str, min_bare: int = 10) -> list[NumToken]:
    """All numeric tokens of a text with their exemption reason (None = the number is a claim)."""
    t = prepare(text)
    url_s = _spans(_URL, t)
    date_s = _spans(_DATE, t)
    time_s = _spans(_TIME, t)
    ver_s = _spans(_SEMVER, t)
    ph_s = [s for s in _spans(_PHONE, t) if sum(c.isdigit() for c in t[s[0]:s[1]]) >= 8]
    idiom_s = _spans(_IDIOM, t)
    out: list[NumToken] = []
    for m in _TOKEN.finditer(t):
        raw, start, end = m.group(1), m.start(1), m.end(1)
        value = float(raw.replace(",", ""))
        tok = NumToken(value, raw, raw, start=start)
        line_start = t.rfind("\n", 0, start) + 1
        before_line = t[line_start:start]
        attached = re.match(r"[A-Za-z]+", t[end:end + 6])
        att = attached.group(0).casefold() if attached else ""
        after = end
        reason = None
        if _inside(start, url_s):
            reason = "url"
        elif _inside(start, ver_s):
            reason = "version"
        elif _inside(start, date_s):
            reason = "date"
        elif _inside(start, time_s):
            reason = "time"
        elif _inside(start, ph_s) or (len(raw) >= 7 and raw.isdigit()):
            reason = "phone/id"
        elif _inside(start, idiom_s):
            reason = "idiom"
        elif t[end:end + 2] == "\ufe0f\u20e3":
            reason = "list marker"
        elif re.fullmatch(r"[^\w\s]{0,4}\s*", before_line) is not None and t[end:end + 1] in ".)" and value < 100 \
                and raw.isdigit():
            reason = "list marker"
        elif before_line.endswith("#"):
            reason = "identifier"
        if reason is None and att:
            if att in _ORD:
                reason = "ordinal"
            elif att in _MULT and not re.match(r"[A-Za-z]", t[end + 1:end + 2] or " "):
                tok.value = value * _MULT[att]
                after = end + 1
                tok.display = raw + att
            elif att in _ATTACH_UNITS:
                tok.units.append(_ATTACH_UNITS[att])
                after = end + len(att)
                tok.display = raw + att
            else:
                reason = "identifier"
        if reason is None:
            if t[after:after + 1] == "%" or _PCT_WORD.match(t[after:after + 20]):
                tok.pct = True
                tok.units.append("%")
                tok.display = raw + "%"
                after = after + 1 if t[after:after + 1] == "%" else after
            if t[after:after + 1] == "+":
                after += 1
            prev = t[start - 1:start]
            if prev in CURRENCY:
                tok.units.append(CURRENCY[prev])
            tok.units.extend(_words_after(t, after))
            pw = _prev_word(t, start)
            nxt = tok.units[0] if tok.units and not tok.pct else ""
            first_raw = _next_raw_word(t, after)
            if first_raw and not tok.pct and first_raw.casefold() not in _STOP:
                tok.display = f"{tok.display} {first_raw}"
            if _AGE_AFTER.match(t[after:after + 20]) or pw in ("age", "aged"):
                reason = "age"
            elif 1900 <= value <= 2100 and raw.isdigit() and len(raw) == 4 and (
                    pw in _YEAR_PREV or pw in _MONTHS or not tok.units or _next_raw_word(t, after).casefold() in _MONTHS):
                reason = "year"
            elif pw in _MONTHS or _next_raw_word(t, after).casefold() in _MONTHS:
                reason = "date"
            elif pw in _LABEL_PREV:
                reason = "label"
            elif nxt in STRUCT_UNITS:
                reason = "list count"
            elif (not tok.pct and not tok.units and raw.isdigit() and value < min_bare):
                tok.bare = True
        tok.reason = reason
        out.append(tok)
    return out


def _close(a: float, b: float) -> bool:
    return abs(a - b) <= 1e-9 * max(1.0, abs(a), abs(b))


def token_matches(tok: NumToken, spec: NumSpec) -> bool:
    """Same value, same percent-ness, and the spec's unit among the token's unit words."""
    if not _close(tok.value, spec.value):
        return False
    if tok.pct != spec.pct:
        return False
    if tok.pct or not spec.unit:
        return True
    cand = set(tok.units)
    return not cand or spec.unit in cand


def number_word_hits(text: str) -> list[str]:
    hits = []
    for m in _NUMBER_WORD.finditer(text):
        nxt = norm_unit(m.group(2))
        if nxt in STRUCT_UNITS or m.group(2).casefold() in _STOP:
            continue
        hits.append(f"{m.group(1)} {m.group(2)}")
    return hits


def check_numbers(surfaces: dict[str, str], specs: list[NumSpec], *, min_bare: int = 10,
                  number_words: str = "warn") -> list[dict]:
    """Findings for every surface: FAIL for an unproven claim number, WARN for bare digits and number words."""
    out: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    for name, text in surfaces.items():
        if not text:
            continue
        for tok in extract(text, min_bare):
            if tok.reason is not None:
                continue
            if tok.bare:
                key = (name, "bare", tok.display)
                if key not in seen:
                    seen.add(key)
                    out.append(finding("numbers", WARN,
                                       f"bare digit '{tok.raw}' is not proof; add a unit and a cited claim if it is a figure",
                                       surface=name, token=tok.display))
                continue
            if any(token_matches(tok, s) for s in specs):
                continue
            key = (name, "claim", tok.display)
            if key in seen:
                continue
            seen.add(key)
            cited = ", ".join(sorted({f"{s.raw}{s.unit and ' ' + s.unit}" for s in specs})) or "none"
            out.append(finding("numbers", FAIL,
                               f"'{tok.display}' has no cited claim with that number and unit (cited numbers: {cited}); "
                               f"add the fact id to meta.claims, fix the figure, or cut it",
                               surface=name, token=tok.display))
        if number_words != "off":
            for hit in number_word_hits(text):
                key = (name, "word", hit.casefold())
                if key not in seen:
                    seen.add(key)
                    out.append(finding("numbers", FAIL if number_words == "fail" else WARN,
                                       f"number word '{hit}' is not checked against claims; use a cited figure or rephrase",
                                       surface=name, token=hit))
    return out
