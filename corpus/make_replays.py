#!/usr/bin/env python3
"""Generate deterministic controller routes for Pip's Garden.

A route is a sequence of segments (hold a stick direction for some frames,
optionally jumping, dashing or turning the camera). Frame 0 always holds the
scene-select button. One line per logical frame: "<buttons> <x> <y>", where
buttons uses A B Z S(tart) L R u d l r (d-pad) 8 2 4 6 (C up/down/left/right)
and '.' means none; x/y are stick values in -80..80.

usage:
  make_replays.py OUT_DIR --seeds public          # committed public routes
  make_replays.py OUT_DIR --seed-file FILE        # held-out routes (private)
"""
import argparse
import json
import math
import pathlib
import random

SCENES = {"meadow": ".", "fortress": "L", "storm": "R", "concert": "Z"}
FRAMES = 240
PUBLIC_SEEDS = {"meadow": 101, "fortress": 202, "storm": 303, "concert": 404}


def route(scene, seed, frames=FRAMES):
    rng = random.Random(seed)
    lines = [f"{SCENES[scene]} 0 0"]
    while len(lines) < frames:
        angle = rng.uniform(0, 2 * math.pi)
        mag = rng.choice([40, 60, 80, 80])
        x = int(round(math.cos(angle) * mag))
        y = int(round(math.sin(angle) * mag))
        length = rng.randint(10, 40)
        jump_at = rng.randint(0, length - 1) if rng.random() < 0.6 else -1
        dash_at = rng.randint(0, length - 1) if rng.random() < 0.3 else -1
        cam = rng.choice(["", "", "4", "6", "2"])
        for i in range(length):
            if len(lines) >= frames:
                break
            buttons = cam
            if jump_at <= i < jump_at + 6:
                buttons += "A"
            if i == dash_at:
                buttons += "B"
            lines.append(f"{buttons or '.'} {x} {y}")
        # Occasionally stand still so idle paths are exercised.
        if rng.random() < 0.2:
            for _ in range(rng.randint(5, 15)):
                if len(lines) < frames:
                    lines.append(". 0 0")
    return lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--seeds", choices=["public"])
    group.add_argument("--seed-file", help='JSON: {"meadow": 1234, ...}')
    args = ap.parse_args()

    seeds = PUBLIC_SEEDS if args.seeds else json.load(open(args.seed_file))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for scene, seed in seeds.items():
        (out / f"{scene}.txt").write_text("\n".join(route(scene, seed)) + "\n")
        print(f"{out / scene}.txt  seed={seed}")


if __name__ == "__main__":
    main()
