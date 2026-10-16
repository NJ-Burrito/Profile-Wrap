# Third-party notices

Regenerated at each release by `tools/export_public.py` (maintainer step). Nothing below is copied into this repository unless its row says "bundled".

## Runtime

| Component | Use | Licence | How it arrives |
|---|---|---|---|
| Python standard library | the whole core (stdlib only, Python 3.10+) | PSF-2.0 | the user's Python |

## Optional extras (installed on demand, never bundled)

| Component | Extra | Licence | Note |
|---|---|---|---|
| openpyxl | `[xlsx]` | MIT | analytics workbook import |
| tzdata | `[tz]` | Apache-2.0 | time zone data on Windows |
| Pillow | `[media]` | HPND | GIF checks |
| HyperFrames | `profile-wrap assets fetch` | per upstream | pinned in the workspace `package.json` |
| Playwright | `profile-wrap assets fetch` | Apache-2.0 | renders local `file://` pages only |
| lucide-static | `profile-wrap assets fetch` | ISC | vector icons |
| gsap | `profile-wrap assets fetch` | per upstream (standard licence) | read the upstream licence before commercial use |

## System tools (never bundled)

ffmpeg (LGPL/GPL, depending on build), Node.js (MIT), poppler (GPL-2.0-or-later, optional). `profile-wrap doctor` prints install lines.

## Optional upstream skills (`profile-wrap deps`)

Cloned at pinned commits into the user's `~/.claude/skills`, never into this repository. The installer copies each upstream LICENSE next to the skill.

| Skill set | Source | Licence |
|---|---|---|
| linkedin-agent-skill | Jakeschincariol/linkedin-agent-skill | see upstream LICENSE |
| linkedin-skills (12 skills) | sergebulaev/linkedin-skills @ 261240a | see upstream LICENSE |
| humanizer | blader/humanizer | see upstream LICENSE |

## Bundled assets

| Asset | Licence | Where |
|---|---|---|
| Lucide icons (subset) | ISC | `assets/icons/` (added with the visuals package) |
| Open-licence demo fonts (OFL) | SIL OFL 1.1 | `assets/fonts-ofl/` (added with the visuals package, each pinned by hash in `release/leak-allow.json`) |

The OFL font files and their licence texts are added by the visuals package; until then this table lists the intent, not shipped files.
