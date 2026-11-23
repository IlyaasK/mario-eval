#!/usr/bin/env python3
"""Fold n64run address-keyed samples into per-function or per-data-symbol totals.

usage: symbolize.py SAMPLES SYMBOLS [--top N] [--frames N]
                    [--exclude-range LO:HI ...] [--by-data-symbol]
                    [--with-sizes] [--icache-conflicts]

SAMPLES is any file written by `n64run --profile`: the PC sample histogram
(`pc count`), or one of the cache profiles written beside it — `.dmiss`
(`faulting_pc count`), `.imiss` (`line_address count`), `.wb`
(`physical_line last_writer_pc count`), and `.dmissaddr`
(`virtual_line faulting_pc count`).

By default a two-column file is keyed by column 0 and a three-column file by
column 1 (the code PC). With `--by-data-symbol`, a three-column file is keyed
by column 0 (the missed/written-back data line address, mapping physical
`0x00xxxxxx` addresses to KSEG0 `0x80xxxxxx`) against data/bss/rodata symbols.
SYMBOLS is `mips64-elf-nm -n -S --defined-only ELF` (preferred: includes sizes)
or `mips64-elf-objdump -t ELF`.
"""
import argparse
import bisect
import collections


def load_symbols(path, data_only=False):
    out = []
    for line in open(path):
        parts = line.split()
        if not parts:
            continue
        # objdump -t: "802f2b70 g     F .main  00000120 func"
        if len(parts) >= 5 and len(parts[0]) == 8 and parts[-2].isalnum() and len(parts[-2]) == 8:
            section = parts[-3]
            if section in ("*ABS*", "*UND*") or section.startswith((".debug", ".comment")):
                continue
            is_data = section in (".data", ".bss", ".rodata", ".sdata", ".sbss") or "O" in parts[1:-3]
            if data_only != is_data:
                continue
            out.append((int(parts[0], 16) & 0xFFFFFFFF, int(parts[-2], 16), parts[-1]))
        # nm -n -S --defined-only: "802f2b70 00000120 T name"
        elif len(parts) == 4 and len(parts[2]) == 1:
            sym_type = parts[2]
            if data_only and sym_type in "dDbBrRgGsS":
                out.append((int(parts[0], 16) & 0xFFFFFFFF, int(parts[1], 16), parts[3]))
            elif not data_only and sym_type in "tTwW":
                out.append((int(parts[0], 16) & 0xFFFFFFFF, int(parts[1], 16), parts[3]))
        # nm -n --defined-only (no size): "802f2b70 T name"
        elif len(parts) == 3 and len(parts[1]) == 1:
            sym_type = parts[1]
            if data_only and sym_type in "dDbBrRgGsS":
                out.append((int(parts[0], 16) & 0xFFFFFFFF, 0, parts[2]))
            elif not data_only and sym_type in "tTwW":
                out.append((int(parts[0], 16) & 0xFFFFFFFF, 0, parts[2]))
    out.sort()
    # Infer missing sizes from the distance to the next symbol (capped at 64 KB).
    starts = [a for a, _, _ in out]
    sizes = []
    names = [n for _, _, n in out]
    for i, (addr, sz, _name) in enumerate(out):
        if sz == 0 and i + 1 < len(out):
            gap = out[i + 1][0] - addr
            if 0 < gap <= 65536:
                sz = gap
        sizes.append(sz)
    return starts, sizes, names


def parse_ranges(raw_ranges):
    ranges = []
    for item in raw_ranges or ():
        lo_s, hi_s = item.split(":", 1)
        ranges.append((int(lo_s, 16) & 0xFFFFFFFF, int(hi_s, 16) & 0xFFFFFFFF))
    return ranges


def in_ranges(addr, ranges):
    for lo, hi in ranges:
        if lo <= addr < hi:
            return True
    return False


def totals(samples, starts, sizes, names, exclude_ranges=(), by_data_symbol=False):
    out = collections.Counter()
    sym_size = {}
    excluded = 0
    for line in open(samples):
        if line.startswith("#") or not line.strip():
            continue
        parts = line.split()
        if by_data_symbol:
            addr = int(parts[0], 16) & 0xFFFFFFFF
            if addr < 0x80000000:
                addr |= 0x80000000
        else:
            addr = (int(parts[0], 16) if len(parts) == 2 else int(parts[1], 16)) & 0xFFFFFFFF
        n = int(parts[-1])
        if exclude_ranges and in_ranges(addr, exclude_ranges):
            excluded += n
            continue
        i = bisect.bisect_right(starts, addr) - 1
        if i >= 0:
            # For data symbols, guard against attributing far-away heap/stack addresses
            # to the last static symbol when size is known.
            if by_data_symbol and sizes[i] > 0 and addr >= starts[i] + max(sizes[i], 64):
                label = f"?{addr & ~0xFFF:08x}..{(addr & ~0xFFF) + 0xFFF:08x}"
            else:
                label = names[i]
                sym_size[label] = sizes[i]
        else:
            label = f"?{addr & ~0xFFF:08x}" if by_data_symbol else f"?{addr:08x}"
        out[label] += n
    return out, sym_size, excluded


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
    ap.add_argument("--frames", type=int, default=0, help="if >0, also print per-frame rate")
    ap.add_argument("--exclude-range", action="append", default=[], help="hex LO:HI PC range excluded from denominator")
    ap.add_argument("--by-data-symbol", action="store_true", help="key 3-col files by col 0 against data/bss/rodata symbols")
    ap.add_argument("--with-sizes", action="store_true", help="show symbol byte size and 32B I-cache lines")
    ap.add_argument("--icache-conflicts", action="store_true")
    args = ap.parse_args()

    starts, sizes, names = load_symbols(args.symbols, data_only=args.by_data_symbol)
    if args.icache_conflicts:
        icache_conflicts(args.samples, starts, names, args.top)
        return
    ranges = parse_ranges(args.exclude_range)
    counted, sym_size, excluded = totals(
        args.samples, starts, sizes, names,
        exclude_ranges=ranges, by_data_symbol=args.by_data_symbol,
    )
    busy_total = sum(counted.values())
    grand_total = busy_total + excluded
    if excluded > 0 and grand_total > 0:
        print(f"  [busy samples: {busy_total} ({100.0 * busy_total / grand_total:.1f}%); "
              f"excluded idle: {excluded} ({100.0 * excluded / grand_total:.1f}%)]")
    denom = busy_total or 1
    for name, n in counted.most_common(args.top):
        rate = f"  {n / args.frames:8.1f}/f" if args.frames > 0 else ""
        sz_col = ""
        if args.with_sizes:
            sz = sym_size.get(name, 0)
            if sz > 0:
                lines_str = f" ({(sz + 31) // 32:3d} I$)" if not args.by_data_symbol else f" ({(sz + 15) // 16:4d} D$)"
                sz_col = f"  {sz:6d}B{lines_str}"
            else:
                sz_col = "  " + (" " * 16 if not args.by_data_symbol else " " * 17)
        print(f"{100.0 * n / denom:6.2f}%  {n:9d}{rate}{sz_col}  {name}")


if __name__ == "__main__":
    main()
