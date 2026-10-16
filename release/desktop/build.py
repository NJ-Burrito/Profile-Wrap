"""Build and package the desktop app for the current OS.

    python release/desktop/build.py --version 0.2.0 [--out dist-release] [--skip-selftest]

Produces profile-wrap-<version>-<os>-<arch>.zip (Windows, macOS) or .tar.gz (Linux). The built
app runs ``--selftest`` before it is packed; a failing selftest fails the build.
"""
from __future__ import annotations

import argparse
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPEC = ROOT / "release" / "desktop" / "profile-wrap.spec"


def target() -> tuple[str, str]:
    osname = {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}[platform.system()]
    arch = {"AMD64": "x64", "x86_64": "x64", "arm64": "arm64", "aarch64": "arm64"}.get(platform.machine(), platform.machine())
    return osname, arch


def exe_path(app: Path) -> Path:
    return app / ("Profile-Wrap.exe" if platform.system() == "Windows" else "Profile-Wrap")


def pack(app: Path, out: Path, stem: str) -> Path:
    if platform.system() == "Linux":
        archive = out / f"{stem}.tar.gz"
        with tarfile.open(archive, "w:gz") as tf:
            tf.add(app, arcname="Profile-Wrap")
    else:
        archive = out / f"{stem}.zip"
        if platform.system() == "Darwin":  # zip keeps the exec bit and symlinks only via the system tool
            subprocess.run(["zip", "-qry", str(archive), "Profile-Wrap"], cwd=app.parent, check=True)
        else:
            with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                for p in sorted(app.rglob("*")):
                    zf.write(p, Path("Profile-Wrap") / p.relative_to(app))
    return archive


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", required=True)
    ap.add_argument("--out", default=str(ROOT / "dist-release"))
    ap.add_argument("--skip-selftest", action="store_true")
    args = ap.parse_args()
    out = Path(args.out).resolve()
    work = ROOT / "build" / "pyinstaller"
    out.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(work / "dist"), "--workpath", str(work / "work"), str(SPEC)],
                   cwd=ROOT, check=True)
    app = work / "dist" / "Profile-Wrap"
    exe = exe_path(app)
    if not exe.is_file():
        print(f"build: {exe} missing", file=sys.stderr)
        return 1
    if not args.skip_selftest:
        r = subprocess.run([str(exe), "--selftest"], timeout=300)
        if r.returncode != 0:
            print(f"build: --selftest exited {r.returncode}", file=sys.stderr)
            return 1
    osname, arch = target()
    archive = pack(app, out, f"profile-wrap-{args.version}-{osname}-{arch}")
    size = sum(p.stat().st_size for p in app.rglob("*") if p.is_file())
    print(f"built {archive} (folder {size / 1048576:.1f} MiB, archive {archive.stat().st_size / 1048576:.1f} MiB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
