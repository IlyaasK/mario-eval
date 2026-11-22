#!/usr/bin/env python3
"""Generate deterministic 240-frame controller replays for Super Mario 64.

Frame 0 selects the target course via mev_select_boot_level():
  '.' -> Bob-omb Battlefield    (LEVEL_BOB)
  'L' -> Whomp's Fortress       (LEVEL_WF)
  'R' -> Jolly Roger Bay        (LEVEL_JRB)
  'Z' -> Rainbow Ride           (LEVEL_RR)
  'u' -> Dire, Dire Docks       (LEVEL_DDD)
  'd' -> Bowser in the Fire Sea (LEVEL_BITFS)
  'l' -> Cool, Cool Mountain    (LEVEL_CCM)
  'r' -> Shifting Sand Land     (LEVEL_SSL)
  '8' -> Lethal Lava Land       (LEVEL_LLL)
  '2' -> Hazy Maze Cave         (LEVEL_HMC)
  '4' -> Wet-Dry World          (LEVEL_WDW)

With --heldout DIR --mash-seed S, DIR also gets seeded random button mashing
(mash-<course>.txt) on every public and held-out course. Mashing has no route
to overfit, so builds that special-case the scripted replays, or crash or
diverge on unusual input, fail. Keep S private; it is the only state.
"""
import argparse
import glob
import math
import os
import random


def clamp80(v):
    return max(-80, min(80, int(round(v))))


def write_replay(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("# buttons stick_x stick_y\n")
        for btn, x, y in lines:
            f.write(f"{btn or '.'} {clamp80(x)} {clamp80(y)}\n")


def gen_bob(frames=240, heldout=False):
    out = [(".", 0, 0)]
    for i in range(1, frames):
        btn = ""
        if not heldout:
            ang = 0.18 * math.sin(i * 0.045)
            x, y = 78 * math.sin(ang), 78 * math.cos(ang)
            if i in (24, 25, 26, 56, 57, 58, 92, 93, 94, 95, 165, 166):
                btn += "A"
            if i in (106, 107, 195, 196):
                btn += "B"
            if i == 30:
                btn += "2"
            if i in (80, 140):
                btn += "6"
        else:
            ang = -0.32 + 0.25 * math.cos(i * 0.05)
            x, y = 76 * math.sin(ang), 76 * math.cos(ang)
            if 38 <= i <= 44 or 130 <= i <= 136:
                btn += "Z"
            if i in (24, 25, 40, 41, 78, 79, 80, 132, 133, 182, 183, 184):
                btn += "A"
            if i in (210, 211):
                btn += "B"
            if i in (25, 115):
                btn += "4"
        out.append((btn, x, y))
    return out


def gen_wf(frames=240, heldout=False):
    out = [("L", 0, 0)]
    for i in range(1, frames):
        btn = ""
        if not heldout:
            ang = -0.22 + 0.20 * math.sin(i * 0.04)
            x, y = 78 * math.sin(ang), 78 * math.cos(ang)
            if 44 <= i <= 50:
                btn += "Z"
            if i in (22, 23, 46, 47, 88, 89, 90, 128, 129, 174, 175):
                btn += "A"
            if i in (138, 139):
                btn += "B"
            if i == 20:
                btn += "2"
            if i in (70, 150):
                btn += "4"
        else:
            ang = 0.28 * math.sin(i * 0.055 + 0.6)
            x, y = 75 * math.sin(ang), 75 * math.cos(ang)
            if i in (28, 29, 62, 63, 64, 102, 103, 148, 149, 150, 198, 199):
                btn += "A"
            if 100 <= i <= 105:
                btn += "Z"
            if i in (160, 161):
                btn += "B"
            if i in (35, 120):
                btn += "6"
        out.append((btn, x, y))
    return out


def gen_jrb(frames=240, heldout=False):
    out = [("R", 0, 0)]
    for i in range(1, frames):
        btn = ""
        if not heldout:
            x = 18 * math.sin(i * 0.05)
            y = 78 if i < 90 else (55 * math.cos((i - 90) * 0.03))
            if i in (30, 31):
                btn += "A"
            if i in (36, 37):
                btn += "B"
            if i >= 75 and i % 12 in (0, 1):
                btn += "A"
            if i == 25:
                btn += "2"
            if i == 110:
                btn += "6"
        else:
            x = -24 * math.cos(i * 0.045)
            y = 76 if i < 70 else (60 * math.sin((i - 70) * 0.035 + 0.8))
            if 24 <= i <= 29:
                btn += "Z"
            if i in (26, 27):
                btn += "A"
            if i >= 65 and i % 9 in (0, 1, 2):
                btn += "A"
            if i in (40, 145):
                btn += "4"
        out.append((btn, x, y))
    return out


def gen_ddd(frames=240, heldout=False):
    """Dire, Dire Docks: underwater lagoon with fish-school spawners, Sushi sharks & whirlpool."""
    out = [("u", 0, 0)]
    for i in range(1, frames):
        btn = ""
        if not heldout:
            x = 34 * math.sin(i * 0.045)
            y = -55 if i < 80 else (48 * math.cos((i - 80) * 0.04))
            if i >= 35 and i % 10 in (0, 1, 2):
                btn += "A"
            if i == 24:
                btn += "2"
            if i in (75, 145, 205):
                btn += "6"
        else:
            x = -38 * math.cos(i * 0.05)
            y = -62 if i < 95 else (50 * math.sin((i - 95) * 0.035))
            if i >= 30 and i % 8 in (0, 1):
                btn += "A"
            if i in (55, 125, 190):
                btn += "4"
        out.append((btn, x, y))
    return out


def gen_bitfs(frames=240):
    """Bowser in the Fire Sea: 19 dynamic collision platforms, lava sea & flamethrowers."""
    out = [("d", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = i * 0.08
        x, y = 38 * math.cos(ang), 38 * math.sin(ang)
        if i in (26, 27, 68, 69, 70, 122, 123, 180, 181):
            btn += "A"
        if i == 22:
            btn += "2"
        if i in (55, 105, 155, 205):
            btn += "6"
        out.append((btn, x, y))
    return out


def gen_rr(frames=240):
    """Rainbow Ride: sky platforms, carpets & camera sweeps."""
    out = [("Z", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = i * 0.07
        x, y = 42 * math.cos(ang), 42 * math.sin(ang)
        if i in (25, 26, 65, 66, 67, 115, 116, 175, 176):
            btn += "A"
        if i == 22:
            btn += "2"
        if i in (50, 95, 140, 190):
            btn += "6"
        out.append((btn, x, y))
    return out


def gen_ccm(frames=240):
    """Held-out Cool, Cool Mountain: snow particle envfx, slopes & cabin."""
    out = [("l", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = 0.35 * math.sin(i * 0.05)
        x, y = 55 * math.sin(ang), 55 * math.cos(ang)
        if i in (24, 25, 26, 58, 59, 98, 99, 100, 152, 153, 204, 205):
            btn += "A"
        if i in (120, 121):
            btn += "B"
        if i == 20:
            btn += "2"
        if i in (65, 140):
            btn += "6"
        out.append((btn, x, y))
    return out


def gen_ssl(frames=240):
    """Held-out Shifting Sand Land: desert haze, pyramid, Klepto & Pokeys."""
    out = [("r", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = i * 0.06
        x, y = 52 * math.cos(ang), 52 * math.sin(ang)
        if i in (24, 25, 60, 61, 62, 112, 113, 168, 169, 212, 213):
            btn += "A"
        if i == 22:
            btn += "2"
        if i in (70, 145):
            btn += "4"
        out.append((btn, x, y))
    return out


def gen_lll(frames=240):
    """Held-out Lethal Lava Land: static-object terrain, Bullies & fireballs."""
    out = [("8", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = i * 0.085
        x, y = 36 * math.cos(ang), 36 * math.sin(ang)
        if i in (24, 25, 26, 48, 49, 92, 93, 144, 145, 196, 197):
            btn += "A"
        if i == 20:
            btn += "2"
        if i in (60, 115, 175):
            btn += "6"
        out.append((btn, x, y))
    return out


def gen_hmc(frames=240):
    """Held-out Hazy Maze Cave: cavern fog, heavy overdraw, rolling rocks & swoops."""
    out = [("2", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = -0.25 + 0.30 * math.sin(i * 0.05)
        x, y = 72 * math.sin(ang), 72 * math.cos(ang)
        if i in (24, 25, 26, 60, 61, 104, 105, 106, 158, 159, 208, 209):
            btn += "A"
        if i in (82, 83, 172, 173):
            btn += "B"
        if i == 20:
            btn += "2"
        if i in (70, 145):
            btn += "6"
        out.append((btn, x, y))
    return out


def gen_wdw(frames=240):
    """Held-out Wet-Dry World: dynamic water plane, crystal switches, elevators & Chuckya."""
    out = [("4", 0, 0)]
    for i in range(1, frames):
        btn = ""
        ang = 0.20 + 0.28 * math.cos(i * 0.055)
        x, y = 68 * math.sin(ang), 68 * math.cos(ang)
        if i in (22, 23, 56, 57, 58, 96, 97, 142, 143, 192, 193):
            btn += "A"
        if i in (118, 119):
            btn += "B"
        if i == 22:
            btn += "2"
        if i in (65, 150):
            btn += "4"
        out.append((btn, x, y))
    return out


COURSE_KEY = {"bob": ".", "wf": "L", "jrb": "R", "rr": "Z", "ddd": "u",
              "bitfs": "d", "ccm": "l", "ssl": "r", "lll": "8",
              "hmc": "2", "wdw": "4"}


def gen_mash(rng, course, frames=240):
    """Random stick held 3-20 frames, released 15% of the time; A/B pressed
    on 25% of frames, Z and each C button on 6%."""
    out = [(COURSE_KEY[course], 0, 0)]
    x = y = 0
    hold = 0
    for _ in range(1, frames):
        if hold == 0:
            if rng.random() < 0.15:
                x = y = 0
            else:
                ang = rng.uniform(0, 2 * math.pi)
                mag = rng.choice((30, 60, 80))
                x, y = mag * math.sin(ang), mag * math.cos(ang)
            hold = rng.randint(3, 20)
        hold -= 1
        btn = "".join(b for b in "ABZ2468" if rng.random() < (0.25 if b in "AB" else 0.06))
        out.append((btn, x, y))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=240)
    ap.add_argument("--public", default=os.path.join(os.path.dirname(__file__), "replays", "public"))
    ap.add_argument("--heldout", default=None)
    ap.add_argument("--mash-seed", type=int, default=None,
                    help="also write seeded button-mash replays into --heldout")
    args = ap.parse_args()

    pub_gens = [
        ("bob", lambda n: gen_bob(n, heldout=False)),
        ("wf", lambda n: gen_wf(n, heldout=False)),
        ("jrb", lambda n: gen_jrb(n, heldout=False)),
        ("ddd", lambda n: gen_ddd(n, heldout=False)),
        ("bitfs", gen_bitfs),
        ("rr", gen_rr),
    ]
    for name, fn in pub_gens:
        write_replay(os.path.join(args.public, f"{name}.txt"), fn(args.frames))

    if args.heldout:
        for old in glob.glob(os.path.join(args.heldout, "*.txt")):
            os.remove(old)
        held_gens = [
            ("ccm", gen_ccm),
            ("lll", gen_lll),
            ("ssl", gen_ssl),
            ("hmc", gen_hmc),
            ("wdw", gen_wdw),
            ("bob2", lambda n: gen_bob(n, heldout=True)),
            ("jrb2", lambda n: gen_jrb(n, heldout=True)),
            ("ddd2", lambda n: gen_ddd(n, heldout=True)),
        ]
        for name, fn in held_gens:
            write_replay(os.path.join(args.heldout, f"{name}.txt"), fn(args.frames))
        if args.mash_seed is not None:
            for course in COURSE_KEY:
                rng = random.Random(f"{args.mash_seed}:{course}")
                write_replay(os.path.join(args.heldout, f"mash-{course}.txt"), gen_mash(rng, course, args.frames))
    elif args.mash_seed is not None:
        ap.error("--mash-seed needs --heldout")


if __name__ == "__main__":
    main()
