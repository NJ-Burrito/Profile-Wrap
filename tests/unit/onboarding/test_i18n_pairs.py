"""Arabic and English are both first-class: a string with one language only is a failure."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from profile_wrap import i18n

ROOT = Path(__file__).resolve().parents[3]
I18N = ROOT / "gui_assets" / "i18n"
ARABIC = re.compile(r"[؀-ۿ]")
PLACEHOLDER = re.compile(r"\{([A-Za-z_][A-Za-z0-9_]*)\}")


def load(lang):
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def used_keys():
    keys = set()
    js = (ROOT / "gui_assets" / "gui.js").read_text(encoding="utf-8")
    keys |= set(re.findall(r'\bt\("([a-z0-9_.]+)"', js))
    html = (ROOT / "gui_assets" / "index.html").read_text(encoding="utf-8")
    keys |= set(re.findall(r'data-i18n(?:-label)?="([a-z0-9_.]+)"', html))
    for f in (ROOT / "profile_wrap").rglob("*.py"):
        text = f.read_text(encoding="utf-8")
        keys |= set(re.findall(r'(?:i18n\.t|\bsay|\bt)\(\s*"([a-z0-9_.]+)"', text))
        keys |= set(re.findall(r'"((?:res|step|connect|cli|copy|init|reauth|state|home|lang|nav|fail)\.[a-z0-9_.]*[a-z0-9])"', text))
        keys |= set(re.findall(r'(?:ConnectError|CopyRefused)\(\s*"([a-z0-9_.]+)"', text))
    for n in ("app", "products", "redirect", "credentials", "signin"):
        keys |= {f"step.{n}.title", f"step.{n}.how"}
    keys |= {f"state.{s}" for s in ("done", "todo", "fix", "wait")}
    # "state." and "step." are prefixes built at run time (covered above); "connect.json" is a file name
    return {k for k in keys if not k.endswith((".", ".json"))}


def test_both_languages_have_exactly_the_same_keys():
    en, ar = load("en"), load("ar")
    assert sorted(set(en) - set(ar)) == [], "missing in Arabic"
    assert sorted(set(ar) - set(en)) == [], "missing in English"
    assert list(en) == list(ar), "keep the same order so the pair reads side by side"


def test_no_string_is_empty_and_each_arabic_string_is_really_arabic():
    en, ar = load("en"), load("ar")
    for key in en:
        assert en[key].strip() and ar[key].strip(), key
        if key == "lang.switch":   # the button names the other language: Arabic text on the English page and back
            assert ARABIC.search(en[key]) and ar[key] == "English"
            continue
        assert ARABIC.search(ar[key]), f"{key} has no Arabic letters"
        assert not ARABIC.search(en[key]), f"{key} (English) holds Arabic"
        assert en[key] != ar[key], key


def test_placeholders_match_in_the_pair():
    en, ar = load("en"), load("ar")
    for key in en:
        assert set(PLACEHOLDER.findall(en[key])) == set(PLACEHOLDER.findall(ar[key])), key


def test_every_key_the_code_uses_exists_in_both_languages():
    en, ar = load("en"), load("ar")
    used = used_keys()
    assert used, "the scan found nothing; the pattern is broken"
    assert sorted(k for k in used if k not in en) == []
    assert sorted(k for k in used if k not in ar) == []


def test_the_arabic_text_has_no_latin_punctuation_or_tashkeel_or_tatweel():
    for key, text in load("ar").items():
        assert not re.search(r"[ً-ْـ]", text), f"{key}: tashkeel or tatweel"
        assert not re.search(r"[؀-ۿ][,;?]|[,;?]\s*[؀-ۿ]", text), f"{key}: Latin punctuation next to Arabic"


def test_a_login_password_is_only_ever_mentioned_to_say_it_is_never_asked_for():
    en = load("en")
    mentions = sorted(k for k, v in en.items() if "password" in v.lower())
    assert mentions == ["connect.nopassword", "res.creds.password_refused"]
    for key in mentions:
        assert "never" in en[key].lower()


def test_the_lookup_falls_back_to_english_then_to_the_key():
    assert i18n.t("nav.connect", "ar") != i18n.t("nav.connect", "en")
    assert i18n.t("nav.connect", "fr") == i18n.t("nav.connect", "en")
    assert i18n.t("no.such.key", "ar") == "no.such.key"
    assert i18n.t("connect.step_n", "en", n=2, total=5) == "Step 2 of 5"
    assert i18n.t("connect.step_n", "ar", n=2, total=5) == "الخطوة 2 من 5"
    assert i18n.dir_of("ar") == "rtl" and i18n.dir_of("en") == "ltr"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_the_app_script_parses():
    done = subprocess.run(["node", "--check", str(ROOT / "gui_assets" / "gui.js")], capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stderr
