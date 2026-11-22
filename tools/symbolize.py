#!/usr/bin/env python3
"""Fold n64run address-keyed samples into per-function totals.

usage: symbolize.py SAMPLES SYMBOLS [--top N]

SAMPLES is any file written by `n64run --profile`: the PC sample histogram
(`pc count`), or one of the cache profiles it writes beside it — `.dmiss`
(`faulting_pc count`), `.imiss` (`line_address count`), `.wb` and
`.dmissaddr` (`line_address pc count`, keyed by the PC). A two-column file is
keyed by its first (hex) column, a three-column file by the second (hex) PC
column; the last column is always the count. SYMBOLS is either
`mips64-elf-objdump -t ELF` (preferred: includes assembly labels such as
osWritebackDCacheAll and the exception handler) or `mips64-elf-nm -n
--defined-only ELF`. Prints functions by share of the total (for the CPU
profile: sampled CPU time, stalls included).
"""
import argparse
import bisect
import collections


def load_symbols(path):
    out = []
    for line in open(path):
        parts = line.split()
        if not parts:
            continue
        # objdump -t: "802f2b70 g       .main  00000000 osWritebackDCacheAll"
        if len(parts) >= 5 and len(parts[0]) == 8 and parts[-2].isalnum() and len(parts[-2]) == 8:
            section = parts[-3]
            if section in (".data", ".bss", ".rodata", "*ABS*", "*UND*") or section.startswith((".debug", ".comment")):
                continue
            if "O" in parts[1:-3]:
                continue
            out.append((int(parts[0], 16) & 0xFFFFFFFF, parts[-1]))
        # nm: "802f2b70 T name"
        elif len(parts) == 3 and parts[1] in "tTwW":
            out.append((int(parts[0], 16) & 0xFFFFFFFF, parts[2]))
    out.sort()
    return [a for a, _ in out], [n for _, n in out]


def totals(samples, starts, names):
    out = collections.Counter()
    for line in open(samples):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        addr = int(parts[0], 16) if len(parts) == 2 else int(parts[1], 16)
        n = int(parts[-1])
        i = bisect.bisect_right(starts, addr) - 1
        out[names[i] if i >= 0 else f"?{addr:08x}"] += n
    return out


def icache_conflicts(samples, starts, names, top):
    """Group .imiss line misses by 16 KB direct-mapped VR4300 I-cache set
    (512 sets of 32 bytes: set = (addr & 0x3fff) >> 5) and report the top
    colliding function pairs that evict each other from the same sets."""
    per_set = collections.defaultdict(collections.Counter)
    for line in open(samples):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        addr = int(parts[0], 16)
        n = int(parts[-1])
        cset = (addr & 0x3FFF) >> 5
        i = bisect.bisect_right(starts, addr) - 1
        fn = names[i] if i >= 0 else f"?{addr:08x}"
        per_set[cset][fn] += n
    pair_score = collections.Counter()
    pair_sets = collections.defaultdict(int)
    for cset, counts in per_set.items():
        if len(counts) < 2:
            continue
        items = counts.most_common(4)
        for idx_a in range(len(items)):
            fa, ca = items[idx_a]
            for idx_b in range(idx_a + 1, len(items)):
                fb, cb = items[idx_b]
                if fa == fb:
                    continue
                key = (fa, fb) if fa < fb else (fb, fa)
                # Conflict intensity in this set is bounded by the smaller sharer's misses
                pair_score[key] += min(ca, cb)
                pair_sets[key] += 1
    total_conflicts = sum(pair_score.values()) or 1
    for (fa, fb), score in pair_score.most_common(top):
        print(f"{100.0 * score / total_conflicts:6.2f}%  {score:9d}  ({pair_sets[(fa, fb)]:3d} sets)  {fa}  <->  {fb}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("samples")
    ap.add_argument("symbols")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--icache-conflicts", action="store_true")
    args = ap.parse_args()

    starts, names = load_symbols(args.symbols)
    if args.icache_conflicts:
        icache_conflicts(args.samples, starts, names, args.top)
        return
    counted = totals(args.samples, starts, names)
    total = sum(counted.values()) or 1
    for name, n in counted.most_common(args.top):
        print(f"{100.0 * n / total:6.2f}%  {n:9d}  {name}")


if __name__ == "__main__":
    main()
