#!/usr/bin/env python3
"""Fold n64run PC samples into per-function totals.

usage: symbolize.py SAMPLES NM_OUTPUT [--top N]

SAMPLES is the file written by `n64run --profile`; NM_OUTPUT is
`mips64-elf-nm -n --defined-only build/<rom>.elf`. Prints functions by
share of sampled CPU time (stalls included).
"""
import argparse
import bisect
import collections


def load_symbols(path):
    starts, names = [], []
    for line in open(path):
        parts = line.split()
        if len(parts) != 3 or parts[1] not in "tTwW":
            continue
        starts.append(int(parts[0], 16) & 0xFFFFFFFF)
        names.append(parts[2])
    order = sorted(range(len(starts)), key=starts.__getitem__)
    return [starts[i] for i in order], [names[i] for i in order]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples")
    ap.add_argument("nm")
    ap.add_argument("--top", type=int, default=25)
    args = ap.parse_args()

    starts, names = load_symbols(args.nm)
    totals = collections.Counter()
    for line in open(args.samples):
        if line.startswith("#") or not line.strip():
            continue
        pc, n = line.split()
        pc = int(pc, 16)
        i = bisect.bisect_right(starts, pc) - 1
        totals[names[i] if i >= 0 else f"?{pc:08x}"] += int(n)
    total = sum(totals.values()) or 1
    for name, n in totals.most_common(args.top):
        print(f"{100.0 * n / total:6.2f}%  {n:9d}  {name}")


if __name__ == "__main__":
    main()
