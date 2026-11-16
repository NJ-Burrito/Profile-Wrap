"""A caption that promises a link or details "in the first comment" needs a first comment that holds a URL."""
from __future__ import annotations

import re

from .findings import FAIL, WARN, finding
from .rules import find_links

_EN_THING = r"(?:links?|urls?|details|sources?|repo|code|template|demo|download|full\s+(?:post|guide|write-?up)|more)"
_EN_FIRST = r"(?:first|1st)\s+comment"
_EN_PLACE = rf"(?:the\s+|my\s+|a\s+)?(?:{_EN_FIRST}|comments?(?:\s+(?:below|section))?)"
_EN = [
    re.compile(rf"\b{_EN_THING}\b[^.!?\n]{{0,45}}\b(?:in|on|under|at)\s+{_EN_PLACE}\b", re.IGNORECASE),
    re.compile(rf"\b(?:in|on|under)\s+(?:the\s+|my\s+)?{_EN_FIRST}\b[^.!?\n]{{0,25}}\b{_EN_THING}\b", re.IGNORECASE),
    re.compile(rf"\b{_EN_FIRST}\b[^.!?\n]{{0,30}}\b{_EN_THING}\b", re.IGNORECASE),
    re.compile(rf"\b{_EN_THING}\b[^.!?\n]{{0,20}}\b{_EN_FIRST}\b", re.IGNORECASE),
]
_AL = "[أاإآ]"  # alef with or without hamza
_AR_THING = r"(?:ال)?(?:رابط|روابط|تفاصيل|مصدر|مصادر|كود)"
_AR_PLACE = (rf"(?:في|فى|ب|بـ|تحت)\s*(?:{_AL}ول\s+تعليق|(?:ال)?تعليق(?:\s+(?:ال){_AL}ول)?|(?:ال)?تعليقات)")
_AR = [
    re.compile(rf"{_AR_THING}[^.!?\n؟]{{0,40}}{_AR_PLACE}"),
    re.compile(rf"{_AR_PLACE}[^.!?\n؟]{{0,25}}{_AR_THING}"),
]


def promise_phrases(text: str) -> list[str]:
    """The matched promise phrases in a caption (English and Arabic)."""
    found: list[str] = []
    for rx in _EN + _AR:
        for m in rx.finditer(text):
            found.append(" ".join(m.group(0).split()))
    return list(dict.fromkeys(found))


def check_first_comment_promise(caption: str | None, first_comment: str | None, tlds: set[str],
                                mode: str = "fail") -> list[dict]:
    """FAIL (or WARN, or off) when the caption promises a link in the first comment that is missing or has no URL."""
    if mode == "off" or not caption:
        return []
    phrases = promise_phrases(caption)
    if not phrases:
        return []
    if first_comment is None:
        why = "first_comment.txt is missing"
    elif not first_comment.strip():
        why = "first_comment.txt is empty"
    elif not find_links(first_comment, tlds):
        why = "first_comment.txt has no link"
    else:
        return []
    sev = FAIL if mode == "fail" else WARN
    return [finding("first_comment_promise", sev,
                    f"the caption promises something in the first comment ('{phrases[0]}') but {why}; write the first "
                    f"comment with the link, or remove the promise", surface="caption", token=phrases[0])]
