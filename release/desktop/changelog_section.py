"""Print the CHANGELOG.md section for a version (``0.2.0`` or ``v0.2.0``); exit 1 if it is missing."""
from __future__ import annotations

import re
import sys
from pathlib import Path


def section(text: str, version: str) -> str | None:
    version = version.lstrip("v")
    pat = re.compile(rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|\Z)", re.S | re.M)
    m = pat.search(text)
    return m.group(1).strip() if m else None


def main(argv: list[str]) -> int:
    version = argv[0]
    path = Path(argv[1]) if len(argv) > 1 else Path("CHANGELOG.md")
    body = section(path.read_text(encoding="utf-8"), version)
    if not body:
        print(f"no CHANGELOG section for {version}", file=sys.stderr)
        return 1
    print(body)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
