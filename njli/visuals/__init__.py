"""Visuals: slides, GIFs, banners, fonts, icons, metrics, motion upgrade and the signature tools.

The pieces are imported where they are used (``njli.visuals.fonts``, ``njli.visuals.gif`` and so on); this
package file only holds the constants they share. Python stdlib only; Pillow, fontTools, numpy, scipy and
scikit-image are optional extras and every use of them names the extra to install when it is missing.
"""
from __future__ import annotations

from pathlib import Path

from njli import paths

#: Output size the static lane renders at, per slide (the canvas is the config's brand.canvas).
DEFAULT_CANVAS = {"w": 1080, "h": 1350}
#: GIF limits that are policy, not taste: LinkedIn documents <= 250 frames.
MAX_FRAMES = 250
EXIT_OK = 0
EXIT_FAIL = 1
EXIT_USAGE = 2


class VisualsError(RuntimeError):
    """A readable failure in the visual pipeline (the CLI prints it and exits 1)."""


def kit_dir() -> Path:
    """The shipped brand-kit (templates, motion library, objects, icons)."""
    return paths.resource("brand-kit")


def here() -> Path:
    return Path(__file__).resolve().parent
