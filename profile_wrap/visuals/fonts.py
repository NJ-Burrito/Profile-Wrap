"""Brand fonts: resolve the configured families to files, build the base64 @font-face CSS, fetch OFL fonts.

Rules (design-spec section 9):
- ``google_ofl`` (default): IBM Plex Sans and IBM Plex Sans Arabic come from fontsource npm packages into
  ``<workspace>/brand/fonts/`` (git-ignored). ``user_files``: the user's own licensed files, referenced in place and
  never copied, bundled or redistributed. ``system``: installed families, no files.
- The render **fails** when a configured family did not load. There is no silent fallback face.
- This module never ships, copies out or names a proprietary family; family names are just strings from the config.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from profile_wrap import atomic, paths

from . import VisualsError

ROLES = ("display", "text", "arabic")
_FORMATS = {".woff2": "woff2", ".woff": "woff", ".ttf": "truetype", ".otf": "opentype"}
_MIME = {".woff2": "font/woff2", ".woff": "font/woff", ".ttf": "font/ttf", ".otf": "font/otf"}
_WEIGHT_WORDS = (("thin", 100), ("extralight", 200), ("ultralight", 200), ("light", 300), ("regular", 400),
                 ("normal", 400), ("medium", 500), ("semibold", 600), ("demibold", 600), ("extrabold", 800),
                 ("bold", 700), ("black", 900), ("heavy", 900))


class FontError(VisualsError):
    """A configured font is missing or did not load."""


@dataclass
class Face:
    family: str
    role: str
    weight: int
    path: Optional[Path]
    style: str = "normal"

    @property
    def fmt(self) -> str:
        return _FORMATS.get((self.path.suffix.lower() if self.path else ""), "woff2")


@dataclass
class FontPlan:
    source: str
    faces: List[Face] = field(default_factory=list)
    families: Dict[str, str] = field(default_factory=dict)  # role -> family
    licence_note: str = ""
    problems: List[str] = field(default_factory=list)

    @property
    def family_names(self) -> List[str]:
        seen: List[str] = []
        for role in ROLES:
            fam = self.families.get(role)
            if fam and fam not in seen:
                seen.append(fam)
        return seen

    @property
    def ok(self) -> bool:
        return not self.problems


# ------------------------------------------------------------------ catalog

def catalog() -> dict:
    path = paths.resource("data", "fonts-ofl.json")
    return json.loads(path.read_text(encoding="utf-8"))


def _pins() -> dict:
    try:
        return json.loads(paths.resource("data", "pins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guess_weight(name: str) -> int:
    low = re.sub(r"[^a-z0-9]", "", name.lower())
    m = re.search(r"(?<![0-9])([1-9]00)(?![0-9])", name)
    if m:
        return int(m.group(1))
    for word, weight in _WEIGHT_WORDS:
        if word in low:
            return weight
    return 400


def _brand(cfg: dict) -> dict:
    return (cfg or {}).get("brand") or {}


def fonts_dir(workspace: Path) -> Path:
    return Path(workspace) / "brand" / "fonts"


def _ofl_faces(workspace: Path, family: str, role: str, cat: dict) -> List[Face]:
    entry = (cat.get("families") or {}).get(family)
    if not entry:
        return []
    out: List[Face] = []
    for weight in entry["weights"]:
        name = f"{entry['slug']}-{entry['subset']}-{weight}-{entry.get('style', 'normal')}.woff2"
        out.append(Face(family, role, int(weight), fonts_dir(workspace) / name))
    return out


def resolve(cfg: dict, workspace: Path) -> FontPlan:
    """Turn ``brand.font_source`` and ``brand.fonts`` into a plan. Missing files are listed in ``plan.problems``."""
    workspace = Path(workspace)
    brand = _brand(cfg)
    source = brand.get("font_source", "google_ofl")
    fonts = brand.get("fonts") or {}
    plan = FontPlan(source=source, licence_note=str(fonts.get("licence_note") or ""))
    cat = catalog()
    for role in ROLES:
        spec = fonts.get(role) or {}
        family = spec.get("family") or (cat.get("defaults") or {}).get(role)
        if not family:
            plan.problems.append(f"brand.fonts.{role}.family is empty")
            continue
        plan.families[role] = family
        if source == "system":
            continue
        files = spec.get("files") or []
        if source == "user_files":
            if not files:
                plan.problems.append(f"brand.fonts.{role}.files is empty (font_source=user_files)")
            for item in files:
                weight = None
                if isinstance(item, dict):
                    raw, weight = item.get("path"), item.get("weight")
                else:
                    raw = item
                p = Path(str(raw)).expanduser()
                if not p.is_absolute():
                    p = workspace / p
                if p.suffix.lower() not in _FORMATS:
                    plan.problems.append(f"{role}: {p.name} is not a font file ({', '.join(_FORMATS)})")
                    continue
                plan.faces.append(Face(family, role, int(weight or _guess_weight(p.stem)), p))
        else:  # google_ofl
            faces = _ofl_faces(workspace, family, role, cat)
            if not faces:
                plan.problems.append(
                    f"{family!r} is not in data/fonts-ofl.json: add it there, or set brand.font_source "
                    "to user_files or system")
            plan.faces.extend(faces)
    seen = set()
    for face in plan.faces:
        key = str(face.path)
        if key in seen:
            continue
        seen.add(key)
        if face.path is not None and not face.path.is_file():
            hint = "run 'profile-wrap fonts fetch'" if source == "google_ofl" else "check the path in brand.fonts"
            plan.problems.append(f"font file missing for {face.family} {face.weight}: {face.path.name} ({hint})")
    return plan


def require(plan: FontPlan) -> FontPlan:
    """Raise one FontError listing everything wrong; the render never starts with a fallback face."""
    if plan.problems:
        raise FontError("fonts not ready: " + "; ".join(plan.problems))
    return plan


# ------------------------------------------------------------------ CSS

def font_stack(plan: FontPlan, role: str) -> str:
    fam = plan.families.get(role)
    if not fam:
        return "system-ui, sans-serif"
    stack = [f'"{fam}"']
    if role == "arabic":
        latin = plan.families.get("text") or plan.families.get("display")
        if latin and latin != fam:
            stack.append(f'"{latin}"')
    return ", ".join(stack) + ", sans-serif"


def fonts_css(plan: FontPlan) -> str:
    """Base64 @font-face rules plus the --brand-* variables the motion library and templates read."""
    require(plan)
    parts: List[str] = []
    done = set()
    for face in plan.faces:
        if face.path is None or str(face.path) in done:
            continue
        done.add(str(face.path))
        data = base64.b64encode(face.path.read_bytes()).decode("ascii")
        suffix = face.path.suffix.lower()
        parts.append(
            f'@font-face{{font-family:"{face.family}";font-style:{face.style};font-weight:{face.weight};'
            f'font-display:block;src:url(data:{_MIME.get(suffix, "font/woff2")};base64,{data}) '
            f'format("{face.fmt}");}}')
    parts.append(
        ":root{--brand-display:%s;--brand-text:%s;--brand-sans:%s;--brand-arabic:%s;}" % (
            font_stack(plan, "display"), font_stack(plan, "text"), font_stack(plan, "text"),
            font_stack(plan, "arabic")))
    return "\n".join(parts) + "\n"


def write_fonts_css(plan: FontPlan, target: Path) -> Path:
    return atomic.atomic_write_text(target, fonts_css(plan))


def required_font_substrings(cfg: dict) -> List[str]:
    """Substrings a PDF's embedded font names must contain: the gate's override, else the families (no spaces)."""
    explicit = ((cfg or {}).get("gate") or {}).get("required_font_substrings") or []
    if explicit:
        return list(explicit)
    fonts = _brand(cfg).get("fonts") or {}
    cat = catalog()
    subs: List[str] = []
    for role in ROLES:
        spec = fonts.get(role) or {}
        fam = spec.get("family") or (cat.get("defaults") or {}).get(role)
        if fam:
            subs.append(fam.replace(" ", ""))
    return subs


# ------------------------------------------------------------------ fetch (OFL only)

Packer = Callable[[str, Path], Path]


def npm_pack(spec: str, dest: Path, timeout: int = 180) -> Path:
    """``npm pack <spec>`` into ``dest``; returns the tarball path."""
    import shutil
    npm = shutil.which("npm")
    if not npm:
        raise FontError("npm not found: install Node >= 22 (https://nodejs.org) or put the font files in "
                        "brand/fonts/ yourself")
    r = subprocess.run([npm, "pack", spec, "--silent", "--pack-destination", str(dest)], cwd=str(dest),
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout)
    if r.returncode != 0:
        raise FontError(f"npm pack {spec} failed: {(r.stderr or r.stdout).strip()[-200:]}")
    name = (r.stdout.strip().splitlines() or [""])[-1].strip()
    tgz = dest / name
    if not tgz.is_file():
        found = sorted(dest.glob("*.tgz"))
        if not found:
            raise FontError(f"npm pack {spec} produced no tarball")
        tgz = found[-1]
    return tgz


def _extract(tgz: Path, wanted: Dict[str, str]) -> Dict[str, bytes]:
    """Read only the named members out of a tarball (never extracts to disk, so no path tricks)."""
    out: Dict[str, bytes] = {}
    with tarfile.open(tgz, "r:gz") as tar:
        for member in tar.getmembers():
            rel = member.name.split("/", 1)[-1]
            if rel in wanted and member.isfile():
                handle = tar.extractfile(member)
                if handle is not None:
                    out[wanted[rel]] = handle.read()
    return out


def fetch(workspace: Path, cfg: dict, packer: Optional[Packer] = None) -> dict:
    """Install the configured OFL families into ``brand/fonts/`` with their licence files. Idempotent."""
    workspace = Path(workspace)
    if _brand(cfg).get("font_source", "google_ofl") != "google_ofl":
        raise FontError("brand.font_source is not google_ofl: 'profile-wrap fonts fetch' only installs OFL fonts. "
                        "Your own fonts are used in place and never copied.")
    cat, pins = catalog(), (_pins().get("npm") or {})
    plan = resolve(cfg, workspace)
    pack = packer or npm_pack
    target = fonts_dir(workspace)
    target.mkdir(parents=True, exist_ok=True)
    written: List[str] = []
    for family in plan.family_names:
        entry = (cat.get("families") or {}).get(family)
        if not entry:
            raise FontError(f"{family!r} is not in data/fonts-ofl.json; add it there or use another font_source")
        version = pins.get(entry["package"]) or entry.get("version")
        if not version:
            raise FontError(f"no pinned version for {entry['package']} (data/pins.json)")
        wanted = {}
        for weight in entry["weights"]:
            name = f"{entry['slug']}-{entry['subset']}-{weight}-{entry.get('style', 'normal')}.woff2"
            wanted[f"files/{name}"] = name
        wanted[entry.get("license_file", "LICENSE")] = f"{entry['slug']}-LICENSE.txt"
        with tempfile.TemporaryDirectory(prefix="profile-wrap-fonts-") as tmp:
            tgz = pack(f"{entry['package']}@{version}", Path(tmp))
            got = _extract(tgz, wanted)
        missing = [n for n in wanted.values() if n not in got]
        if missing:
            raise FontError(f"{entry['package']}@{version} lacks {', '.join(missing)}")
        for name, data in got.items():
            atomic.atomic_write_bytes(target / name, data)
            written.append(name)
    return {"dir": str(target), "files": sorted(set(written)), "licence": "SIL Open Font License 1.1"}


def check(cfg: dict, workspace: Path) -> dict:
    plan = resolve(cfg, workspace)
    return {"source": plan.source, "families": plan.family_names, "ok": plan.ok, "problems": plan.problems,
            "faces": [{"family": f.family, "weight": f.weight, "file": f.path.name if f.path else None}
                      for f in plan.faces]}
