"""Text normalisation shared by every gate check (stdlib only)."""
from __future__ import annotations

import re
import unicodedata
from html.parser import HTMLParser

from njli.facts.numspec import normalise_digits  # noqa: F401  (single digit table for facts and gate)

INVISIBLE_ALWAYS = {
    0x00AD: "soft hyphen", 0x200B: "zero-width space", 0x2060: "word joiner",
    0xFEFF: "zero-width no-break space / BOM", 0x2061: "invisible function application",
    0x2062: "invisible times", 0x2063: "invisible separator", 0x2064: "invisible plus",
    0x180E: "mongolian vowel separator",
}
BIDI_CONTROLS = {
    0x200E: "left-to-right mark", 0x200F: "right-to-left mark", 0x061C: "arabic letter mark",
    0x202A: "LRE", 0x202B: "RLE", 0x202C: "PDF", 0x202D: "LRO", 0x202E: "RLO",
    0x2066: "LRI", 0x2067: "RLI", 0x2068: "FSI", 0x2069: "PDI",
}
ARABIC_RANGE = re.compile(r"[\u0600-ۿݐ-ݿࢠ-\u08ffﭐ-﷿ﹰ-\ufeff]")
_ALEF = {0x0622: 0x0627, 0x0623: 0x0627, 0x0625: 0x0627, 0x0671: 0x0627, 0x0649: 0x064A}
_DIACRITICS = re.compile(r"[\u064b-\u065f\u0670\u06d6-\u06ed]")


def strip_invisible(text: str) -> str:
    """Remove zero-width and bidi characters so term matching cannot be dodged with them."""
    return "".join(
        ch for ch in text
        if ord(ch) not in INVISIBLE_ALWAYS and ord(ch) not in BIDI_CONTROLS and ord(ch) not in (0x200C, 0x200D)
    )


def fold(text: str) -> str:
    """Case-fold and normalise for term matching (NFKC, no tatweel, diacritics or invisibles)."""
    t = unicodedata.normalize("NFKC", strip_invisible(text))
    t = t.replace("\u0640", "")
    t = _DIACRITICS.sub("", t).translate(_ALEF)  # alef and yeh variants match each other
    return t.casefold()


def find_invisible(text: str) -> list[tuple[int, str]]:
    """(code point, name) of always-suspicious invisible characters found in text."""
    seen = {ord(ch): INVISIBLE_ALWAYS[ord(ch)] for ch in text if ord(ch) in INVISIBLE_ALWAYS}
    return sorted(seen.items())


def find_bidi(text: str) -> list[tuple[int, str]]:
    seen = {ord(ch): BIDI_CONTROLS[ord(ch)] for ch in text if ord(ch) in BIDI_CONTROLS}
    return sorted(seen.items())


class _TextExtractor(HTMLParser):
    _SKIP = {"script", "style", "template", "noscript", "head"}
    _ATTRS = ("alt", "aria-label", "title")

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
            return
        if self._skip_depth:
            return
        for k, v in attrs:
            if k in self._ATTRS and v:
                self.parts.append(v)
                self.parts.append("\n")
        self.parts.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in self._SKIP:
            return
        self.handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self._SKIP:
            if self._skip_depth:
                self._skip_depth -= 1
        elif not self._skip_depth:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data)


def html_text(html: str) -> str:
    """Visible text plus alt, aria-label and title attributes of an HTML document."""
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed markup must not crash the gate
        pass
    return re.sub(r"\n\s*\n+", "\n", "".join(p.parts)).strip()


def first_line(text: str) -> str:
    for line in text.strip().splitlines():
        if line.strip():
            return line.strip()
    return ""


def is_arabic(text: str) -> bool:
    return bool(ARABIC_RANGE.search(text))
