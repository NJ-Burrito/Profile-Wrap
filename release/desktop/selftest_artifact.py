"""Unpack a release archive in a fresh folder and run its --selftest (used by CI after the build)."""
from __future__ import annotations

import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def main(archive: str) -> int:
    a = Path(archive).resolve()
    with tempfile.TemporaryDirectory(prefix="pw-artifact-") as tmp:
        if a.suffix == ".zip":
            if sys.platform == "darwin":
                subprocess.run(["ditto", "-x", "-k", str(a), tmp], check=True)
            else:
                zipfile.ZipFile(a).extractall(tmp)
        else:
            with tarfile.open(a) as tf:
                tf.extractall(tmp)
        app = Path(tmp) / "Profile-Wrap"
        exe = app / ("Profile-Wrap.exe" if sys.platform == "win32" else "Profile-Wrap")
        r = subprocess.run([str(exe), "--selftest"], timeout=300)
        return r.returncode


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
