"""Every docs/references/*.md path cited by an agent, skill, prompt or template must exist."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CITING = ("agents", "skills", ".agents/skills", "prompts", "templates", "commands")
_REF = re.compile(r"docs/references/([A-Za-z0-9_.\-]+\.md)")


def _cited() -> list[tuple[Path, str]]:
    out = []
    for top in CITING:
        base = ROOT / top
        if not base.is_dir():
            continue
        for p in sorted(base.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in (".md", ".json", ".txt", ".toml", ".yaml", ".yml"):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            out.extend((p, m.group(1)) for m in _REF.finditer(text))
    return out


def test_cited_reference_files_exist():
    cited = _cited()
    assert cited, "the scan found no docs/references citation at all; the scan itself is broken"
    missing = sorted({f"{p.relative_to(ROOT).as_posix()} -> docs/references/{name}"
                      for p, name in cited if not (ROOT / "docs" / "references" / name).is_file()})
    assert not missing, "cited reference files do not exist:\n" + "\n".join(missing)


def test_evidence_files_state_what_is_unverified():
    for name in ("growth-evidence.md", "evidence-scale.md"):
        text = (ROOT / "docs" / "references" / name).read_text(encoding="utf-8")
        assert "\r" not in text
    growth = (ROOT / "docs" / "references" / "growth-evidence.md").read_text(encoding="utf-8")
    assert "Not covered by a verified source" in growth
    for row in re.findall(r"^\| (?:buffer|sprout|hootsuite)\S* \|.*$", growth, re.MULTILINE):
        assert re.search(r"\| [ABCX] \|", row), row
