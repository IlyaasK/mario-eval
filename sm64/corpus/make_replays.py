#!/usr/bin/env python3
"""Generate deterministic 240-frame controller replays for Super Mario 64.

Frame 0 selects the target (level, act) via mev_select_boot_level():
  - Public single-button shortcuts (Act 1):
      '.' -> Bob-omb Battlefield    (LEVEL_BOB = 9)
      'L' -> Whomp's Fortress       (LEVEL_WF = 24)
      'R' -> Jolly Roger Bay        (LEVEL_JRB = 12)
      'Z' -> Rainbow Ride           (LEVEL_RR = 15)
      'u' -> Dire, Dire Docks       (LEVEL_DDD = 23)
      'd' -> Bowser in the Fire Sea (LEVEL_BITFS = 19)
  - Generic digital selector (any valid SM64 level 4..36, act 1..6):
      Hold 'S' (START_BUTTON) on Frame 0 + 6-bit level in ('6'=1,'4'=2,'2'=4,'8'=8,'B'=16,'A'=32)
      + 3-bit (act - 1) in ('Z'=1,'L'=2,'u'=4).

Private held-out routes (both scripted multi-course/multi-act trajectories and
random-input mash trajectories) are synthesized strictly from --heldout-seed S;
keep S private outside git.
"""
import argparse
import glob
import math
import os
import random

LEVEL_IDS = {
    "bbh": 4,
    "ccm": 5,
    "castle": 6,
    "hmc": 7,
    "ssl": 8,
    "bob": 9,
    "sl": 10,
    "wdw": 11,
    "jrb": 12,
    "thi": 13,
    "ttc": 14,
    "rr": 15,
    "castle_grounds": 16,
    "bitdw": 17,
    "vcutm": 18,
    "bitfs": 19,
    "sa": 20,
    "bits": 21,
    "lll": 22,
    "ddd": 23,
    "wf": 24,
    "castle_courtyard": 26,
    "pss": 27,
    "cotmc": 28,
    "totwc": 29,
    "bowser_1": 30,
    "wmotr": 31,
    "bowser_2": 33,
    "bowser_3": 34,
    "ttm": 36,
}

HELDOUT_SCRIPTED_TARGETS = [
    ("bbh", 4, "land"),
    ("ccm", 5, "land"),
    ("hmc", 7, "land"),
    ("ssl", 8, "land"),
    ("sl", 10, "land"),
    ("wdw", 11, "mixed"),
    ("thi", 13, "land"),
    ("ttc", 14, "platform"),
    ("lll", 22, "platform"),
    ("ttm", 36, "land"),
    ("bitdw", 17, "platform"),
    ("bits", 21, "platform"),
    ("jrb-act2", 12, "swim"),
    ("wf-act2", 24, "platform"),
]

ALL_MASH_POOL = [
    ("bbh", 4), ("ccm", 5), ("hmc", 7), ("ssl", 8), ("bob", 9),
    ("sl", 10), ("wdw", 11), ("jrb", 12), ("thi", 13), ("ttc", 14),
    ("rr", 15), ("bitdw", 17), ("bitfs", 19), ("bits", 21),
    ("lll", 22), ("ddd", 23), ("wf", 24), ("ttm", 36),
]


def clamp80(v):
    return max(-80, min(80, int(round(v))))


def encode_boot_buttons(level_id, act=1):
    assert 4 <= level_id <= 36 and level_id not in (25, 32, 35), f"invalid SM64 level_id {level_id}"
    assert 1 <= act <= 6, f"invalid act {act}"
    btn = ["S"]
    for bit, ch in ((1, "6"), (2, "4"), (4, "2"), (8, "8"), (16, "B"), (32, "A")):
        if level_id & bit:
            btn.append(ch)
    act_bits = act - 1
    for bit, ch in ((1, "Z"), (2, "L"), (4, "u")):
        if act_bits & bit:
            btn.append(ch)
    return "".join(btn)


def write_replay(path, lines):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("# buttons stick_x stick_y\n")
        for btn, x, y in lines:
            f.write(f"{btn or '.'} {clamp80(x)} {clamp80(y)}\n")


# ----------------------------------------------------------------- public dev (6)

def gen_bob(frames=240):
    out = [(".", 0, 0)]
    for i in range(1, frames):
        btn = ""
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
        out.append((btn, x, y))
    return out


def gen_wf(frames=240):
    out = [("L", 0, 0)]
    for i in range(1, frames):
        btn = ""
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
        out.append((btn, x, y))
    return out


def gen_jrb(frames=240):
    out = [("R", 0, 0)]
    for i in range(1, frames):
        btn = ""
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
        out.append((btn, x, y))
    return out


def gen_ddd(frames=240):
    out = [("u", 0, 0)]
    for i in range(1, frames):
        btn = ""
        x = 34 * math.sin(i * 0.045)
        y = -55 if i < 80 else (48 * math.cos((i - 80) * 0.04))
        if i >= 35 and i % 10 in (0, 1, 2):
            btn += "A"
        if i == 24:
            btn += "2"
        if i in (75, 145, 205):
            btn += "6"
        out.append((btn, x, y))
    return out


def gen_bitfs(frames=240):
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


# ------------------------------------------------------ seeded private held-out

def gen_seeded_scripted(rng, level_id, act, style, frames=240):
    """Synthesize a smooth, deterministic 240-frame route from the private seed."""
    out = [(encode_boot_buttons(level_id, act), 0, 0)]
    if level_id == 24:
        # Whomp's Fortress spawns near a right-hand sky dropoff; steer left-forward up the main ramp.
        base_ang = rng.uniform(-0.42, -0.16)
        amp1 = rng.uniform(0.14, 0.24)
    else:
        base_ang = rng.uniform(-0.55, 0.55)
        amp1 = rng.uniform(0.22, 0.50)
    freq1 = rng.uniform(0.035, 0.070)
    phase1 = rng.uniform(0.0, 2.0 * math.pi)
    amp2 = rng.uniform(0.10, 0.25)
    freq2 = rng.uniform(0.065, 0.12)
    phase2 = rng.uniform(0.0, 2.0 * math.pi)
    if style == "platform":
        mag = rng.uniform(28.0, 40.0)
        stride = rng.randint(16, 22)
    else:
        mag = rng.uniform(58.0, 76.0)
        stride = 0

    jump_starts = sorted(rng.sample(range(24, max(26, frames - 16), 10), k=min(5, max(1, (frames - 30) // 42))))
    jump_frames = set()
    z_frames = set()
    b_frames = set()
    for js in jump_starts:
        hold = rng.randint(2, 3 if style == "platform" else 5)
        for d in range(hold):
            jump_frames.add(js + d)
        if style == "land" and rng.random() < 0.35:
            for d in range(-2, 4):
                z_frames.add(max(18, js + d))
        elif style != "platform" and rng.random() < 0.28:
            b_frames.add(js + hold + rng.randint(6, 14))
            b_frames.add(js + hold + rng.randint(7, 15))
        elif style == "platform" and rng.random() < 0.40:
            z_frames.add(max(18, js + hold + 4))

    cam_taps = {
        rng.randint(18, 32): "2",
        rng.randint(60, 115): rng.choice(("4", "6")),
        rng.randint(135, max(140, frames - 20)): rng.choice(("4", "6")),
    }
    swim_period = rng.randint(9, 14)

    for i in range(1, frames):
        btn = ""
        if style == "swim":
            x = rng.uniform(18.0, 32.0) * math.sin(i * freq1 + phase1)
            y = mag if i < 75 else (0.75 * mag * math.cos((i - 75) * 0.035 + phase2))
            if i >= 28 and (i % swim_period) in (0, 1):
                btn += "A"
        elif style == "platform":
            # Oscillate forward/backward across the starting island/platform so Mario
            # traverses geometry, jumps, and rotates the camera without walking into lava/void.
            leg = ((i - 1) // stride) % 2
            dir_off = 0.0 if leg == 0 else math.pi
            ang = base_ang + dir_off + 0.30 * math.sin(i * freq2 + phase2)
            x, y = mag * math.sin(ang), mag * math.cos(ang)
        else:
            ang = base_ang + amp1 * math.sin(i * freq1 + phase1) + amp2 * math.cos(i * freq2 + phase2)
            x, y = mag * math.sin(ang), mag * math.cos(ang)

        if i in z_frames:
            btn += "Z"
        if i in jump_frames and "A" not in btn:
            btn += "A"
        if i in b_frames:
            btn += "B"
        if i in cam_taps:
            btn += cam_taps[i]
        out.append((btn, x, y))
    return out


def gen_mash(rng, level_id, act, frames=240):
    """Seeded high-entropy controller input (never presses Start so pause menu never opens)."""
    out = [(encode_boot_buttons(level_id, act), 0, 0)]
    narrow = level_id in (14, 15, 17, 19, 21, 22, 36)
    x = y = 0.0
    ang = rng.uniform(0.0, 2.0 * math.pi)
    hold = 0
    for _ in range(1, frames):
        if hold == 0:
            if rng.random() < 0.18:
                x = y = 0.0
            elif narrow:
                ang = (ang + math.pi + rng.uniform(-0.45, 0.45)) % (2.0 * math.pi)
                mag = rng.choice((24, 34, 44))
                x, y = mag * math.sin(ang), mag * math.cos(ang)
            else:
                ang = rng.uniform(0.0, 2.0 * math.pi)
                mag = rng.choice((32, 58, 80))
                x, y = mag * math.sin(ang), mag * math.cos(ang)
            hold = rng.randint(3, 6) if narrow else rng.randint(3, 14)
        hold -= 1
        if narrow:
            btn = "".join(b for b in "AZ2468" if rng.random() < (0.16 if b == "A" else 0.06))
        else:
            btn = "".join(b for b in "ABZ2468" if rng.random() < (0.22 if b in "AB" else 0.06))
        out.append((btn, x, y))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", type=int, default=240)
    ap.add_argument("--public", default=os.path.join(os.path.dirname(__file__), "replays", "public"))
    ap.add_argument("--heldout", default=None)
    ap.add_argument("--heldout-seed", "--mash-seed", dest="heldout_seed", type=str, default=None,
                    help="private seed used to synthesize all held-out scripted and mash replays")
    args = ap.parse_args()

    pub_gens = [
        ("bob", gen_bob),
        ("wf", gen_wf),
        ("jrb", gen_jrb),
        ("ddd", gen_ddd),
        ("bitfs", gen_bitfs),
        ("rr", gen_rr),
    ]
    for name, fn in pub_gens:
        write_replay(os.path.join(args.public, f"{name}.txt"), fn(args.frames))

    if args.heldout:
        if not args.heldout_seed:
            ap.error("--heldout requires --heldout-seed <SECRET_SEED>")
        os.makedirs(args.heldout, exist_ok=True)
        for old in glob.glob(os.path.join(args.heldout, "*.txt")):
            os.remove(old)

        for name, level_id, style in HELDOUT_SCRIPTED_TARGETS:
            rng = random.Random(f"v4-scripted:{args.heldout_seed}:{name}")
            if name.endswith("-act2"):
                act = 2
            elif level_id in (17, 19, 21):
                act = 1
            else:
                act = rng.randint(1, 6)
            write_replay(
                os.path.join(args.heldout, f"{name}.txt"),
                gen_seeded_scripted(rng, level_id, act, style, args.frames),
            )

        mash_master = random.Random(f"v4-mash-pool:{args.heldout_seed}")
        chosen_mash = mash_master.sample(ALL_MASH_POOL, k=6)
        for idx, (cname, level_id) in enumerate(chosen_mash, 1):
            rng = random.Random(f"v4-mash:{args.heldout_seed}:{idx}:{cname}")
            act = 1 if level_id in (17, 19, 21) else rng.randint(1, 6)
            write_replay(
                os.path.join(args.heldout, f"mash-{idx:02d}-{cname}.txt"),
                gen_mash(rng, level_id, act, args.frames),
            )
    elif args.heldout_seed is not None:
        ap.error("--heldout-seed requires --heldout DIR")


if __name__ == "__main__":
    main()
