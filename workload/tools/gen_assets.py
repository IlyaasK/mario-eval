#!/usr/bin/env python3
"""Generate deterministic 16x16 RGBA5551 textures for Pip's Garden (DragonFS)."""
import math
import pathlib
import struct
import sys


def rgba16(r, g, b, a=1):
    r5 = max(0, min(31, int(round(r * 31.0))))
    g5 = max(0, min(31, int(round(g * 31.0))))
    b5 = max(0, min(31, int(round(b * 31.0))))
    return (r5 << 11) | (g5 << 6) | (b5 << 1) | (1 if a else 0)


def write_tex(out_dir, name, fn):
    buf = bytearray()
    for y in range(16):
        for x in range(16):
            buf += struct.pack(">H", fn(x, y))
    (out_dir / name).write_bytes(buf)


def main():
    out = pathlib.Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)

    # Neutral bright modulation textures (0.82..1.0) so vertex shading & colors read cleanly.
    write_tex(out, "grass.tex", lambda x, y: rgba16(
        0.86 + 0.12 * (((x * 7 + y * 13) & 7) / 7.0),
        0.90 + 0.10 * (((x * 3 + y * 11) & 7) / 7.0),
        0.84 + 0.10 * (((x * 5 + y * 9) & 7) / 7.0),
    ))

    def stone(x, y):
        mortar = (y % 8 == 0) or ((x + (4 if (y // 8) else 0)) % 8 == 0)
        v = 0.78 if mortar else (0.92 + 0.07 * (((x * 11 + y * 5) & 3) / 3.0))
        return rgba16(v, v * 0.98, v * 0.95)

    write_tex(out, "stone.tex", stone)

    def enemy(x, y):
        stripe = 0.84 if ((x + y) & 4) else 0.98
        return rgba16(stripe, stripe * 0.92, stripe * 0.94)

    write_tex(out, "enemy.tex", enemy)

    def pip(x, y):
        border = (x in (0, 15)) or (y in (0, 15))
        v = 0.88 if border else 0.99
        return rgba16(v, v, v)

    write_tex(out, "pip.tex", pip)

    for frame in range(4):
        phase = frame * (math.pi * 0.5)

        def gem(x, y, p=phase):
            dx, dy = (x - 7.5) / 8.0, (y - 7.5) / 8.0
            glint = 0.90 + 0.10 * math.cos((dx + dy) * 4.0 + p)
            return rgba16(glint * 0.95, glint, 1.0)

        write_tex(out, f"gem{frame}.tex", gem)

    def particle(x, y):
        dx, dy = (x - 7.5) / 7.5, (y - 7.5) / 7.5
        r2 = dx * dx + dy * dy
        if r2 > 1.15:
            return rgba16(0.0, 0.0, 0.0, 0)
        v = max(0.55, 1.0 - 0.35 * r2)
        return rgba16(v, v, v, 1)

    write_tex(out, "particle.tex", particle)


if __name__ == "__main__":
    main()
