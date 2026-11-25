"""Interface strings in English and Arabic, one JSON file per language in ``gui_assets/i18n/``.

The desktop app (``gui.js``) and the terminal flows (``auth connect``, ``copy``, the ``init`` hint) read
the same two files, so a string is written once per language and a missing pair is caught by a test.
Placeholders look like ``{name}``. A key missing in the chosen language falls back to English, and a
key missing everywhere comes back as the key itself (never an exception in a user's face).
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict

from . import paths

LANGS = ("en", "ar")
DEFAULT_LANG = "en"
_CACHE: Dict[str, Dict[str, str]] = {}
_PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def normalize(lang: Any) -> str:
    return "ar" if isinstance(lang, str) and lang.lower().startswith("ar") else DEFAULT_LANG


def strings(lang: str) -> Dict[str, str]:
    lang = normalize(lang)
    if lang not in _CACHE:
        path = paths.resource("gui_assets", "i18n", f"{lang}.json")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        _CACHE[lang] = {k: v for k, v in data.items() if isinstance(k, str) and isinstance(v, str)}
    return _CACHE[lang]


def t(key: str, lang: str = DEFAULT_LANG, **params: Any) -> str:
    text = strings(lang).get(key)
    if text is None:
        text = strings(DEFAULT_LANG).get(key, key)
    return _PLACEHOLDER.sub(lambda m: str(params.get(m.group(1), m.group(0))), text)


def dir_of(lang: str) -> str:
    return "rtl" if normalize(lang) == "ar" else "ltr"
