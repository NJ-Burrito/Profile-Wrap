#!/usr/bin/env python3
"""Check and render the agent templates (developer and CI tool).

    python tools/build_agents.py --check                 validate every template, exit 1 on a problem
    python tools/build_agents.py --out dist/agents       render with the default tier map into a folder
    python tools/build_agents.py --table                 print the tier / effort / tools table (for docs/MODEL-TIERS.md)
    python tools/build_agents.py --single --out dist/x   render with models.mode = single

It uses the same code as `njli agents render`, so what CI checks is what users get. The standard
library is enough; run it from the repository root.
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from njli import agents_render, config  # noqa: E402


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="validate the templates and a trial render")
    ap.add_argument("--out", help="render into this folder")
    ap.add_argument("--table", action="store_true", help="print a Markdown table of the agents")
    ap.add_argument("--single", action="store_true", help="render with models.mode = single")
    ap.add_argument("--templates", default=str(ROOT / "agents"))
    args = ap.parse_args(argv)

    templates, standing = agents_render.load_templates(Path(args.templates))
    problems = [p for t in templates for p in agents_render.validate_template(t)]
    cfg = copy.deepcopy(config.defaults("UTC"))
    if args.single:
        cfg["models"]["mode"] = "single"
    for t in templates:  # a trial render of every template must succeed
        try:
            agents_render.render_agent(t, cfg, standing)
        except Exception as exc:  # report, do not crash the check
            problems.append(f"{t.path.name}: render failed: {exc}")
    for p in problems:
        print(f"FAIL {p}")
    if args.table:
        print("| Agent | Tier | Effort | Tools |\n|---|---|---|---|")
        for t in templates:
            print(f"| {t.name} | {t.meta.get('tier')} | {t.meta.get('effort')} | {t.meta.get('tools')} |")
    if args.out and not problems:
        rep = agents_render.render_all(ROOT, cfg, templates_dir=Path(args.templates), out_dir=Path(args.out))
        for i in rep.items:
            print(f"{i.status:11} {i.name}")
        problems += rep.problems
    if args.check:
        print(("FAIL" if problems else "PASS") + f" {len(templates)} agent templates, {len(problems)} problems")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
