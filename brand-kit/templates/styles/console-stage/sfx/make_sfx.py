"""Writes the console-stage sound kit: short sounds computed in code (stdlib only, seeded, deterministic).

Every sample is computed here: no recording, no sample, no impulse response is inside, so the kit has no third-party licence
(the project's licence applies). Run `python make_sfx.py` in this folder to rewrite the WAVs byte for byte.
Format: 44.1 kHz, mono, 16-bit, peak -3 dBFS; the mixer places each one on its cue and sets its level.
"""
import math
import random
import struct
import wave
from pathlib import Path

SR = 44100
HERE = Path(__file__).resolve().parent


def lp(xs, fc):
    """One-pole low-pass (fc may be a number or a function of the sample index)."""
    y, out = 0.0, []
    for i, x in enumerate(xs):
        f = fc(i) if callable(fc) else fc
        a = 1.0 - math.exp(-2.0 * math.pi * f / SR)
        y += a * (x - y)
        out.append(y)
    return out


def hp(xs, fc):
    return [x - l for x, l in zip(xs, lp(xs, fc))]


def noise(n, rng):
    return [rng.uniform(-1.0, 1.0) for _ in range(n)]


def env_exp(n, tau_s):
    return [math.exp(-i / SR / tau_s) for i in range(n)]


def sine(n, f0, f1=None):
    ph, out = 0.0, []
    for i in range(n):
        f = f0 if f1 is None else f0 + (f1 - f0) * i / n
        ph += 2.0 * math.pi * f / SR
        out.append(math.sin(ph))
    return out


def mix(*tracks):
    n = max(len(t) for t in tracks)
    out = [0.0] * n
    for t in tracks:
        for i, v in enumerate(t):
            out[i] += v
    return out


def shift(xs, ms):
    return [0.0] * int(SR * ms / 1000.0) + list(xs)


def fade(xs, ms=4):
    n = len(xs)
    k = min(int(SR * ms / 1000.0), n // 2)
    out = list(xs)
    for i in range(k):
        out[i] *= i / k
        out[n - 1 - i] *= i / k
    return out


def norm(xs, peak_db=-3.0):
    p = max(abs(v) for v in xs) or 1.0
    g = (10 ** (peak_db / 20.0)) / p
    return [v * g for v in xs]


def make_click(rng):
    n = int(SR * 0.09)
    snap = [a * b for a, b in zip(hp(noise(n, rng), 1800), env_exp(n, 0.004))]
    body = [a * b for a, b in zip(sine(n, 520, 260), env_exp(n, 0.018))]
    return mix(snap, [0.5 * v for v in body])


def make_tick(rng):
    n = int(SR * 0.06)
    return [a * b for a, b in zip(sine(n, 2400), env_exp(n, 0.012))]


def make_key(rng):
    n = int(SR * 0.08)
    snap = [a * b for a, b in zip(lp(hp(noise(n, rng), 900), 5200), env_exp(n, 0.006))]
    thock = [a * b for a, b in zip(sine(n, 210, 150), env_exp(n, 0.02))]
    return mix(snap, [0.7 * v for v in thock])


def make_whoosh(rng):
    n = int(SR * 0.5)
    raw = noise(n, rng)
    sw = lp(raw, lambda i: 300 + 5200 * math.sin(math.pi * min(1.0, i / n)) ** 2)
    sw = hp(sw, 160)
    return [v * math.sin(math.pi * (i / n) ** 0.8) ** 2 for i, v in enumerate(sw)]


def make_thump(rng):
    n = int(SR * 0.5)
    body = [a * b for a, b in zip(sine(n, 95, 38), env_exp(n, 0.11))]
    tap = [a * b for a, b in zip(lp(noise(n, rng), 600), env_exp(n, 0.012))]
    return mix(body, [0.5 * v for v in tap])


def make_pop(rng):
    n = int(SR * 0.12)
    return [a * b for a, b in zip(sine(n, 380, 980), env_exp(n, 0.03))]


def make_splash(rng):
    n = int(SR * 0.45)
    wet = lp(hp(noise(n, rng), 700), lambda i: 6500 - 4500 * i / n)
    return [a * b for a, b in zip(wet, env_exp(n, 0.1))]


def make_sparkle(rng):
    parts = []
    for k, f in enumerate((2637, 3322, 4186)):
        n = int(SR * 0.22)
        parts.append(shift([a * b for a, b in zip(sine(n, f), env_exp(n, 0.05))], 38 * k))
    return mix(*parts)


KIT = {"click": make_click, "tick": make_tick, "key": make_key, "whoosh": make_whoosh, "thump": make_thump,
       "pop": make_pop, "splash": make_splash, "sparkle": make_sparkle}


def write(name, samples):
    with wave.open(str(HERE / f"{name}.wav"), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(b"".join(struct.pack("<h", int(max(-1.0, min(1.0, v)) * 32767)) for v in samples))


if __name__ == "__main__":
    for i, (name, fn) in enumerate(sorted(KIT.items())):
        write(name, norm(fade(fn(random.Random(1000 + i)))))
        print("wrote", name)
