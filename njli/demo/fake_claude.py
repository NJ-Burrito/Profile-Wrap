"""A stand-in for the ``claude`` CLI, used by ``njli demo run``. It calls no model and no network.

The runner pipes a prompt to stdin. The fake reads three lines from it and writes canned, fictional
text into the workspace folder it is allowed to change:

    ROOT: <workspace>      where the workspace is
    TASK: draft|comment|shortlist
    SLUG: <slug>           for ``draft``: the folder drafts/<slug>/

``--help`` lists the flags the real CLI has, so ``njli claude probe`` accepts it. Persona data is
fictional (Maya Rivera).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HELP = """Usage: claude [options] [prompt]

Options:
  -p, --print                 Print response and exit
  --model <model>             Model alias
  --effort <level>            Effort level
  --max-turns <n>             Maximum turns
  --max-budget-usd <usd>      Budget cap
  --allowedTools <tools>      Allowed tools
  --disallowedTools <tools>   Disallowed tools
  --permission-mode <mode>    Permission mode
  --output-format <fmt>       Output format
  --no-session-persistence    Do not save the session
  --add-dir <dirs...>         Extra directories
  --settings <file>           Settings file
"""

CAPTION = """Handoffs got faster when we wrote one line.

Each handoff now ends with the same sentence: what does the next person need first?

That is the whole template.

What is the first thing your next person needs?
"""

COMMENT = ("Short reports get read. Yours made me cut two charts from mine, "
           "and the decision got clearer.\n")


def _fields(prompt: str) -> dict:
    out = {}
    for line in prompt.splitlines():
        for key in ("ROOT", "TASK", "SLUG"):
            if line.startswith(key + ": "):
                out[key] = line[len(key) + 2:].strip()
    return out


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def shortlist(root: Path) -> str:
    """Score the fictional targets by a fixed rule (no model): people we have a reason to meet."""
    lines = ["# Connect shortlist (fake claude, fictional people)", ""]
    try:
        data = json.loads((root / "engage" / "targets.example.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {"targets": []}
    for t in data.get("targets", [])[:3]:
        lines.append(f"- {t.get('name')}: score 8, {t.get('why', '')}. You click Connect yourself.")
    return "\n".join(lines) + "\n"


def main() -> int:
    argv = sys.argv[1:]
    if "--version" in argv:
        print("9.9.9 (demo fake)")
        return 0
    if "--help" in argv or "-h" in argv:
        print(HELP)
        return 0
    fields = _fields(sys.stdin.buffer.read().decode("utf-8", errors="replace"))
    root = Path(fields.get("ROOT", "."))
    task = fields.get("TASK", "draft")
    if task == "draft":
        slug = fields.get("SLUG", "faster-handoffs")
        folder = root / "drafts" / slug
        _write(folder / "caption.txt", CAPTION)
        meta = {"schema_version": 1, "slug": slug, "title": "Faster handoffs, one line", "lang": "en",
                "format": "text", "pillar": "P1", "status": "draft", "claims": [], "fictional": True}
        _write(folder / "meta.json", json.dumps(meta, indent=2) + "\n")
    elif task == "comment":
        _write(root / "engage" / "reports" / "demo-comment.md", COMMENT)
    elif task == "shortlist":
        _write(root / "engage" / "reports" / "demo-connect-shortlist.md", shortlist(root))
    print(json.dumps({"result": f"demo fake finished {task}", "total_cost_usd": 0, "is_error": False}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
