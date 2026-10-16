"""Write examples/demo-persona/drafts/dashboard-three-numbers-too-many/out/sample.gif.

A 2 second, 540 px wide sample loop made with the standard library only, so the demo works without
Node, Chrome, ffmpeg or Pillow. Run it again to regenerate the file; the output is deterministic.

    python examples/make_demo_gif.py
"""
from __future__ import annotations

import struct
from pathlib import Path

W, H, FRAMES, DELAY_CS = 540, 675, 10, 20
PALETTE = [(250, 247, 240), (30, 41, 59), (226, 232, 240), (13, 148, 136), (234, 88, 12), (100, 116, 139),
           (255, 255, 255), (15, 23, 42)]
BG, INK, GRID, TEAL, ORANGE, MUTED, WHITE, DARK = range(8)


def lzw(indices: bytes, min_bits: int = 3) -> bytes:
    clear, end = 1 << min_bits, (1 << min_bits) + 1
    table = {bytes([i]): i for i in range(clear)}
    code_size, nxt = min_bits + 1, end + 1
    out, acc, nbits = bytearray(), 0, 0

    def emit(code: int) -> None:
        nonlocal acc, nbits
        acc |= code << nbits
        nbits += code_size
        while nbits >= 8:
            out.append(acc & 255)
            acc >>= 8
            nbits -= 8

    emit(clear)
    cur = b""
    for byte in indices:
        probe = cur + bytes([byte])
        if probe in table:
            cur = probe
            continue
        emit(table[cur])
        table[probe] = nxt
        nxt += 1
        if nxt > (1 << code_size) and code_size < 12:
            code_size += 1
        if nxt >= 4095:
            emit(clear)
            table = {bytes([i]): i for i in range(clear)}
            code_size, nxt = min_bits + 1, end + 1
        cur = bytes([byte])
    emit(table[cur])
    emit(end)
    if nbits:
        out.append(acc & 255)
    return bytes(out)


def blocks(data: bytes) -> bytes:
    return b"".join(bytes([len(data[i:i + 255])]) + data[i:i + 255] for i in range(0, len(data), 255)) + b"\x00"


def frame(step: int) -> bytes:
    px = bytearray([BG]) * (W * H)

    def rect(x0: int, y0: int, x1: int, y1: int, colour: int) -> None:
        for y in range(max(0, y0), min(H, y1)):
            px[y * W + max(0, x0):y * W + min(W, x1)] = bytes([colour]) * (min(W, x1) - max(0, x0))

    rect(0, 0, W, 90, DARK)
    rect(40, 28, 300, 44, WHITE)
    for row in range(5):                                     # grid lines
        rect(40, 160 + row * 90, W - 40, 162 + row * 90, GRID)
    keep = 3                                                 # three numbers stay, the rest fade out
    for i in range(6):
        x = 60 + i * 75
        top = 520 - (80 + (i * 53) % 220)
        grow = min(1.0, (step + 1) / 5)
        h = int((520 - top) * grow)
        colour = TEAL if i < keep else (MUTED if step < 6 else GRID)
        rect(x, 520 - h, x + 46, 520, colour)
    rect(40, 520, W - 40, 524, INK)
    rect(40, 570, 40 + 40 * (step + 1), 590, ORANGE)       # progress bar under the chart
    rect(40, 610, 300, 624, MUTED)
    return bytes(px)


def build() -> bytes:
    out = bytearray(b"GIF89a" + struct.pack("<HHBBB", W, H, 0xF0 | 2, 0, 0))
    out += b"".join(bytes(c) for c in PALETTE)
    out += b"\x21\xff\x0bNETSCAPE2.0\x03\x01\x00\x00\x00"
    for step in range(FRAMES):
        out += b"\x21\xf9\x04" + bytes([0]) + struct.pack("<H", DELAY_CS) + b"\x00\x00"
        out += b"\x2c" + struct.pack("<HHHHB", 0, 0, W, H, 0) + bytes([3]) + blocks(lzw(frame(step)))
    out += b"\x3b"
    return bytes(out)


if __name__ == "__main__":
    target = (Path(__file__).parent / "demo-persona" / "drafts" / "dashboard-three-numbers-too-many"
              / "out" / "sample.gif")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(build())
    print(f"wrote {target} ({target.stat().st_size} bytes)")
