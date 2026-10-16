"""Text rules: slop lists, dashes, contrast patterns, links, hashtags, private terms, invisible characters.

All checks are deterministic string and regex work. Word lists live in data/banned-words/*.json.
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from .config import find_data_file
from .findings import FAIL, WARN, finding
from .textnorm import find_bidi, find_invisible, first_line, fold, is_arabic

_AR_CLITIC = "[وفبلك]?"
_EMAIL = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_SCHEME_URL = re.compile(r"(?:https?://|ftp://|www\.)[^\s<>\"')]+", re.I)
_PHONE = re.compile(r"(?<!\w)\+?\d[\d\s().-]{7,}\d(?!\w)")
_HASHTAG = re.compile(r"(?<![\w&])#(?!\d+\b)\w+", re.UNICODE)
# Two-letter and long TLDs that are also common file extensions are only links with a scheme, www. or a path.
_FILE_LIKE_TLDS = {"py", "md", "js", "ts", "rs", "sh", "pl", "rb", "cs", "cc", "hs", "ml", "ex", "sql", "txt", "json",
                   "yml", "yaml", "toml", "html", "css", "exe", "dll", "zip", "pdf", "png", "jpg", "gif", "svg",
                   "ini", "cfg", "log", "csv", "xml", "bat", "ps", "go", "kt", "so", "bin", "jar", "gz", "tar", "rar"}


@dataclass
class Banned:
    words: list[tuple[str, re.Pattern]] = field(default_factory=list)  # (display text, pattern)
    patterns: list[dict] = field(default_factory=list)  # {id, regex(compiled), message, severity}
    job_seeking: list[tuple[str, re.Pattern]] = field(default_factory=list)
    tlds: set[str] = field(default_factory=set)
    problems: list[str] = field(default_factory=list)


def _term_pattern(term: str, *, clitic: bool = True) -> re.Pattern:
    """Compile a word or phrase: boundary-checked, `stem*` means any ending, spaces match any whitespace."""
    t = fold(term.strip())
    star = t.endswith("*")
    t = t.rstrip("*")
    body = r"\s+".join(re.escape(part) for part in t.split())
    prefix = _AR_CLITIC if (clitic and is_arabic(t)) else ""
    if star:
        return re.compile(r"(?<![\w-])" + prefix + body + r"\w*")
    return re.compile(r"(?<![\w-])" + prefix + body + r"(?![\w-])")


def load_banned(banned_files: list[str], workspace: Path | None, extra: list[str] | None = None) -> Banned:
    b = Banned()
    for rel in banned_files:
        path = find_data_file(rel, workspace)
        if path is None:
            cand = Path(rel)
            path = cand if cand.is_absolute() and cand.is_file() else None
        if path is None:
            b.problems.append(f"banned-words file not found: {rel}")
            continue
        try:
            data = json.loads(path.read_bytes().decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            b.problems.append(f"banned-words file unreadable: {rel}: {exc}")
            continue
        for w in data.get("words", []):
            b.words.append((w, _term_pattern(w)))
        for w in data.get("job_seeking", []):
            b.job_seeking.append((w, _term_pattern(w)))
        for p in data.get("patterns", []):
            try:
                b.patterns.append({"id": p["id"], "regex": re.compile(p["regex"], re.I | re.UNICODE),
                                   "message": p.get("message", p["id"]), "severity": p.get("severity", FAIL)})
            except (re.error, KeyError) as exc:
                b.problems.append(f"banned-words pattern invalid in {rel}: {p!r}: {exc}")
        b.tlds.update(t.lower() for t in data.get("tlds", []))
    for w in extra or []:
        if w.strip():
            b.words.append((w, _term_pattern(w)))
    tld_path = find_data_file("data/banned-words/tlds.json", workspace)
    if tld_path is not None:
        try:
            b.tlds.update(t.lower() for t in json.loads(tld_path.read_bytes().decode("utf-8-sig")).get("tlds", []))
        except (OSError, ValueError):
            b.problems.append("banned-words/tlds.json unreadable")
    return b


@dataclass
class TextContext:
    banned: Banned
    private_terms: list[str]
    never_say: list[str]
    goal: str = "authority"
    em_dash: str = "fail"
    en_dash: str = "warn"
    links_in_body: str = "fail"
    hashtags_max: int = 3
    private_patterns: list[tuple[str, re.Pattern]] = field(default_factory=list)
    never_patterns: list[tuple[str, re.Pattern]] = field(default_factory=list)

    def __post_init__(self) -> None:
        self.private_patterns = [(t, _term_pattern(t)) for t in self.private_terms if t and t.strip()]
        self.never_patterns = [(t, _term_pattern(t)) for t in self.never_say if t and t.strip()]


def find_links(text: str, tlds: set[str]) -> list[str]:
    """URLs, www. hosts and bare domains with any known TLD. File names such as main.py are not links."""
    hits = [m.group(0).rstrip(".,;:!?") for m in _SCHEME_URL.finditer(text)]
    masked = _SCHEME_URL.sub(" ", text)
    masked = _EMAIL.sub(" ", masked)
    for m in re.finditer(r"(?<![\w@.-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+([a-z]{2,24}))(?![\w-])(/\S*)?", masked,
                         re.I):
        host, tld, path = m.group(1), m.group(2).lower(), m.group(3)
        if tld not in tlds:
            continue
        if path is None and tld in _FILE_LIKE_TLDS:
            continue
        # "Okay.It works" is a run-together sentence, not a domain: a TLD is written in lowercase or all caps
        raw_tld = m.group(2)
        if raw_tld[:1].isupper() and not raw_tld.isupper():
            continue
        hits.append((host + (path or "")).rstrip(".,;:!?"))
    return hits


def _is_emoji(ch: str) -> bool:
    return ord(ch) >= 0x1F000 or unicodedata.category(ch) == "So" or 0x2600 <= ord(ch) <= 0x27BF


def scan_text(surface: str, text: str, ctx: TextContext, *, is_caption: bool = False,
              is_first_comment: bool = False) -> list[dict]:
    """Every text rule against one surface. Returns findings (fail or warn)."""
    out: list[dict] = []
    if not text:
        return out
    folded = fold(text)

    for cp, name in find_invisible(text):
        out.append(finding("invisible", FAIL, f"invisible character U+{cp:04X} ({name}); remove it", surface=surface,
                           token=f"U+{cp:04X}"))
    if not is_arabic(text):
        for cp, name in find_bidi(text):
            out.append(finding("invisible", WARN, f"bidi control U+{cp:04X} ({name}) in non-Arabic text",
                               surface=surface, token=f"U+{cp:04X}"))

    for term, pat in ctx.private_patterns:
        if pat.search(folded):
            out.append(finding("private_terms", FAIL, f"private term '{term}' must not appear in public text",
                               surface=surface, token=term))
    for term, pat in ctx.never_patterns:
        if pat.search(folded):
            out.append(finding("never_say", FAIL, f"'{term}' is on the never-say list", surface=surface, token=term))
    for term, pat in ctx.banned.words:
        m = pat.search(folded)
        if m:
            shown = term if term == m.group(0) else f"{m.group(0)}' (banned: {term}"
            out.append(finding("slop", FAIL, f"banned word or phrase '{shown}'", surface=surface, token=term))
    for p in ctx.banned.patterns:
        m = p["regex"].search(folded)
        if m:
            out.append(finding("slop", p["severity"], f"{p['message']}: '{m.group(0)[:80]}'", surface=surface,
                               token=p["id"]))
    if ctx.goal != "job_seeking":
        for term, pat in ctx.banned.job_seeking:
            if pat.search(folded):
                out.append(finding("job_seeking", FAIL,
                                   f"job-seeking phrase '{term}' is blocked unless persona.goal is job_seeking",
                                   surface=surface, token=term))

    em = text.count("\u2014") + text.count("\u2015") + len(re.findall(r"(?<=\s)--(?=\s)", text))
    if em and ctx.em_dash != "off":
        out.append(finding("em_dash", FAIL if ctx.em_dash == "fail" else WARN,
                           f"{em} em dash(es); use a full stop, comma or colon", surface=surface, token="\u2014"))
    en = text.count("\u2013")
    if en and ctx.en_dash != "off":
        out.append(finding("en_dash", FAIL if ctx.en_dash == "fail" else WARN,
                           f"{en} en dash(es); write 'to' or a hyphen", surface=surface, token="\u2013"))

    for m in _EMAIL.finditer(text):
        out.append(finding("contact", FAIL, "email address in public text", surface=surface, token=m.group(0)))
    for m in _PHONE.finditer(text):
        digits = sum(c.isdigit() for c in m.group(0))
        if digits >= 9 and (m.group(0).lstrip().startswith("+") or re.search(r"[\s().-]", m.group(0))):
            out.append(finding("contact", WARN, "phone-number-like text; remove it unless it is meant to be public",
                               surface=surface, token=m.group(0).strip()))

    links = find_links(text, ctx.banned.tlds)
    if links and not is_first_comment:
        sev = FAIL if (is_caption and ctx.links_in_body == "fail") else WARN
        for link in dict.fromkeys(links):
            out.append(finding("links", sev, f"link in {'the caption body' if is_caption else surface}: {link} "
                               f"(put it in the first comment)", surface=surface, token=link))
    if (is_caption or is_first_comment):
        tags = _HASHTAG.findall(text)
        if len(tags) > ctx.hashtags_max:
            out.append(finding("hashtags", FAIL, f"{len(tags)} hashtags (max {ctx.hashtags_max}): {', '.join(tags)}",
                               surface=surface, token=tags[ctx.hashtags_max]))
    return out


def hook_findings(caption: str, hook_max: int, hook_target: int, style: str = "") -> list[dict]:
    out = []
    hook = first_line(caption)
    if not caption.strip():
        out.append(finding("caption", FAIL, "caption is empty", surface="caption"))
        return out
    if len(hook) > hook_max:
        out.append(finding("hook", FAIL, f"hook line is {len(hook)} characters (fold limit {hook_max})",
                           surface="caption", token=hook[:40]))
    elif len(hook) > hook_target:
        out.append(finding("hook", WARN, f"hook line is {len(hook)} characters (target {hook_target})",
                           surface="caption", token=hook[:40]))
    if style == "adhd_emoji" and hook and not _is_emoji(hook[0]):
        out.append(finding("hook", WARN, "adhd_emoji preset: the hook line should start with an emoji",
                           surface="caption", token=hook[:10]))
    return out
