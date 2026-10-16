"""Arabic hygiene checks. They run only when the draft language is Arabic (meta.lang)."""
from __future__ import annotations

import re

from .findings import FAIL, WARN, finding
from .textnorm import BIDI_CONTROLS, is_arabic

# Persian letters that do not belong in Arabic text: peh, tcheh, jeh, gaf, keheh (Persian kaf), farsi yeh.
PERSIAN_LETTERS = "پچژگکی"
_AR = r"[\u0600-ۿ]"
_LATIN_COMMA = re.compile(rf"{_AR}\s*,")
_LATIN_Q = re.compile(rf"{_AR}[\s\u200f]*\?")
_LATIN_SEMI = re.compile(rf"{_AR}\s*;")
_ARABIC_INDIC = re.compile(r"[٠-٩]")
_PERSIAN_DIGITS = re.compile(r"[۰-۹]")
_ASCII_DIGITS = re.compile(r"[0-9]")


def is_arabic_lang(lang: str) -> bool:
    """True for 'ar', 'ar-JO', 'ar+en', 'ar_en' and similar."""
    parts = re.split(r"[^a-z]+", (lang or "").casefold())
    return "ar" in parts


def check_arabic(surface: str, text: str) -> list[dict]:
    """Persian letters, tatweel, bidi controls, Latin punctuation next to Arabic, mixed numerals."""
    out: list[dict] = []
    if not text or not is_arabic(text):
        return out
    persian = sorted({c for c in text if c in PERSIAN_LETTERS})
    if persian:
        out.append(finding("arabic", FAIL,
                           "Persian letter(s) in Arabic text: " + " ".join(f"{c} (U+{ord(c):04X})" for c in persian)
                           + "; use the Arabic form (ك for kaf, ي for yeh)", surface=surface,
                           token=persian[0]))
    if "\u0640" in text:
        out.append(finding("arabic", FAIL, f"tatweel (kashida) U+0640 x{text.count(chr(0x0640))}; remove it",
                           surface=surface, token="U+0640"))
    bidi = sorted({ord(c) for c in text if ord(c) in BIDI_CONTROLS})
    if bidi:
        out.append(finding("arabic", FAIL, "invisible bidi control(s): " + ", ".join(
            f"U+{cp:04X} ({BIDI_CONTROLS[cp]})" for cp in bidi), surface=surface, token=f"U+{bidi[0]:04X}"))
    if _LATIN_COMMA.search(text):
        out.append(finding("arabic", FAIL, "Latin comma next to Arabic text; use ،", surface=surface, token=","))
    if _LATIN_Q.search(text):
        out.append(finding("arabic", FAIL, "Latin question mark after Arabic text; use ؟", surface=surface,
                           token="?"))
    if _LATIN_SEMI.search(text):
        out.append(finding("arabic", WARN, "Latin semicolon after Arabic text; use ؛", surface=surface,
                           token=";"))
    kinds = sum(bool(p.search(text)) for p in (_ARABIC_INDIC, _PERSIAN_DIGITS, _ASCII_DIGITS))
    if kinds > 1:
        out.append(finding("arabic", WARN, "mixed numeral systems in one text; pick one", surface=surface,
                           token="digits"))
    return out
