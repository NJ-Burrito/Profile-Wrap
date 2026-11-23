"""The sound of a narrated video style: cue-synced effects, mixed from the project's ``sfx/`` kit.

The composition is the one source of truth for timing: it logs every sound as a cue ``{role, t, db}`` (``window.__probe.sfx``) on
the same timeline clock that drives the picture. ``build`` reads those cues, places each role's WAV from ``<project>/sfx/`` on its
cue time (onset on the cue), sums them and writes ``assets/sfx-mix.wav`` at a level that measures near the target loudness with
the peak under the ceiling. HyperFrames plays the file as one ``<audio>`` track and does the fades and the ducking.
No sound is generated here: the WAVs are the kit's (computed in code by ``sfx/make_sfx.py``) or the owner's own files.
"""
from __future__ import annotations

import array
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path
from typing import Callable, Dict, List, Optional

from . import VisualsError, proc

SR = 44100
TARGET_LUFS = -16.0
CEILING_DB = -1.5            # linear 0.841: leaves margin under -1 dBTP for the encoder
MAX_CUES = 400


def _ffmpeg() -> str:
    f = shutil.which("ffmpeg")
    if not f:
        raise VisualsError("ffmpeg not found: install ffmpeg (winget install Gyan.FFmpeg / brew install ffmpeg / apt install ffmpeg)")
    return f


def load_mono(path: Path) -> array.array:
    """Any ffmpeg-readable audio file as mono 44.1 kHz int16 samples."""
    res = subprocess.run([_ffmpeg(), "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"],
                         capture_output=True, timeout=120)
    if res.returncode != 0 or not res.stdout:
        raise VisualsError(f"{Path(path).name} does not decode: {res.stderr.decode('utf-8', 'replace').strip()[:160]}")
    a = array.array("h")
    a.frombytes(res.stdout[: len(res.stdout) // 2 * 2])
    return a


def generate_kit(kit: Path) -> List[str]:
    """Write the style's sound kit into ``kit``: run the project's own ``make_sfx.py`` (stdlib, seeded, computed in code), so no
    audio binary is stored in the template. Returns the roles written; nothing happens when the style ships no generator."""
    import contextlib
    import io
    import runpy
    gen = Path(kit) / "make_sfx.py"
    if not gen.is_file():
        return []
    with contextlib.redirect_stdout(io.StringIO()):
        runpy.run_path(str(gen), run_name="__main__")
    return sorted(p.stem for p in Path(kit).glob("*.wav"))


def clean_cues(raw) -> List[Dict]:
    out = []
    for c in raw or []:
        role = str(c.get("role", ""))
        t = c.get("t")
        if not re.match(r"^[a-z0-9_-]+$", role) or not isinstance(t, (int, float)) or isinstance(t, bool) or t < 0:
            raise VisualsError(f"bad sfx cue {c!r}: needs a role (a-z0-9_-) and t >= 0 seconds")
        out.append({"role": role, "t": float(t), "db": float(c.get("db", 0.0))})
    if len(out) > MAX_CUES:
        raise VisualsError(f"{len(out)} sfx cues (max {MAX_CUES})")
    return sorted(out, key=lambda c: c["t"])


def mix_cues(cues: List[Dict], duration: float, kit: Path) -> array.array:
    """Sum the cues into one float buffer, return it as int16 (clipped: the master step lowers it before it can clip)."""
    n = int(duration * SR) + SR
    buf = [0.0] * n
    cache: Dict[str, array.array] = {}
    for c in cues:
        if c["role"] not in cache:
            f = Path(kit) / f"{c['role']}.wav"
            if not f.is_file():
                raise VisualsError(f"sfx role {c['role']!r} has no file {f}")
            cache[c["role"]] = load_mono(f)
        s = cache[c["role"]]
        g = 10 ** (c["db"] / 20.0)
        o = int(round(c["t"] * SR))
        for i, v in enumerate(s):
            if o + i >= n:
                break
            buf[o + i] += v * g
    peak = max((abs(v) for v in buf), default=0.0)
    scale = 1.0 if peak <= 32767 else 32767 / peak
    return array.array("h", (int(v * scale) for v in buf))


def write_wav(path: Path, samples: array.array) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp.wav")
    try:
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(samples.tobytes())
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)


def loudness(path: Path, runner: Callable = proc.run) -> Dict[str, Optional[float]]:
    """Integrated loudness (LUFS) and true peak (dBTP) of a file's audio, measured by ffmpeg's loudnorm (BS.1770)."""
    res = runner([_ffmpeg(), "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
                  "-vn", "-f", "null", "-"], timeout=300)
    m = re.search(r"\{[^{}]*\"input_i\"[^{}]*\}", (res.stderr or "") + (res.stdout or ""), re.S)
    if not res.ok or not m:
        raise VisualsError(f"could not measure the loudness of {Path(path).name}: {(res.stderr or '')[-160:]}")
    d = json.loads(m.group(0))
    def num(k: str) -> Optional[float]:
        try:
            v = float(d[k])
            return None if v in (float("inf"), float("-inf")) else round(v, 1)
        except (KeyError, ValueError):
            return None
    return {"lufs": num("input_i"), "true_peak_dbtp": num("input_tp"), "lra": num("input_lra")}


def master(src: Path, dst: Path, lufs: float, runner: Callable = proc.run) -> Dict:
    """Gain the mix to the target loudness, then a peak limiter at the ceiling. Returns the gain and the final measure."""
    m = loudness(src, runner)
    if m["lufs"] is None:
        raise VisualsError("the sfx mix is silent")
    gain = round(lufs - m["lufs"], 2)
    tmp = dst.with_suffix(".tmp.wav")
    try:
        res = runner([_ffmpeg(), "-v", "error", "-y", "-i", str(src), "-af",
                      f"volume={gain}dB,alimiter=limit={10 ** (CEILING_DB / 20):.3f}:level=disabled", "-ar", str(SR), "-ac", "1", str(tmp)],
                     timeout=300)
        if not res.ok:
            raise VisualsError(f"sfx master failed: {res.tail()}")
        tmp.replace(dst)
    finally:
        tmp.unlink(missing_ok=True)
    final = loudness(dst, runner)
    return {"gain_db": gain, "premaster": m, "master": final}


def build(project: Path, probe_result: Dict, *, target_lufs: float = TARGET_LUFS, runner: Callable = proc.run) -> Optional[Dict]:
    """Read the cues the composition logged and write ``assets/sfx-mix.wav``. None when the composition has no sfx."""
    if "sfx" not in probe_result:
        return None
    cues = clean_cues(probe_result.get("sfx"))
    duration = float(probe_result.get("duration") or 0)
    if not cues or duration <= 0:
        return None
    project = Path(project)
    raw = project / "assets" / "sfx-premix.wav"
    out = project / "assets" / "sfx-mix.wav"
    try:
        write_wav(raw, mix_cues(cues, duration, project / "sfx"))
        info = master(raw, out, target_lufs, runner)
    finally:
        raw.unlink(missing_ok=True)
    info.update({"cues": len(cues), "roles": sorted({c["role"] for c in cues}), "file": "assets/sfx-mix.wav"})
    return info
