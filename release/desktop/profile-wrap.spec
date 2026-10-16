# PyInstaller spec: one-folder app "Profile-Wrap" that starts `profile-wrap gui`.
# Build: uv run --with pyinstaller --with pywebview --with keyring pyinstaller release/desktop/profile-wrap.spec
# (run from the repository root). No fonts are bundled (project rule).
import os
import sys

from PyInstaller.utils.hooks import collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))

# profile_wrap/paths.py finds these next to the package (plugin_root), so they go to the bundle root.
DATA_DIRS = ["data", "schema", "templates", "brand-kit", "examples", "prompts", "agents", "gui_assets"]
datas = [(os.path.join(ROOT, d), d) for d in DATA_DIRS if os.path.isdir(os.path.join(ROOT, d))]

hiddenimports = collect_submodules("profile_wrap") + ["keyring.backends"]
if sys.platform == "win32":
    hiddenimports += ["keyring.backends.Windows", "tzdata"]
elif sys.platform == "darwin":
    hiddenimports += ["keyring.backends.macOS"]
else:
    hiddenimports += ["keyring.backends.SecretService", "keyring.backends.kwallet"]

a = Analysis(
    [os.path.join(SPECPATH, "launcher.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter", "matplotlib", "IPython", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Profile-Wrap",
    console=True,   # keeps --selftest output visible; the GUI window is separate
    upx=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Profile-Wrap", upx=False)
