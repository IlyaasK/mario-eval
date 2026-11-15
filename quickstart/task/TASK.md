# Make Pip's Garden cheaper to run on a Nintendo 64

`/task/game` is the complete source of **Pip's Garden**, a small 3D game for
the Nintendo 64 (libdragon, C). It is correct but was written without regard
for the N64's costs: built at `-O0`, with redundant math, wasteful memory use
and no attention to the CPU caches. Your job is to make it cheaper to run on
the original hardware **without changing the game**.

## Objective

Your submission is scored on **one resource profile**, named in
`/task/PROFILE` (default: `speed`). The available profiles are:

| profile   | what is reduced                                        | measured as |
|-----------|--------------------------------------------------------|-------------|
| `speed`   | time to compute and render a frame                     | CPU COUNT ticks per frame (unthrottled) |
| `rsp`     | RSP (vector coprocessor) busy time                     | RSP non-halted cycles per frame |
| `traffic` | memory bus traffic                                     | RDRAM bytes moved per frame, all devices |
| `memory`  | RAM the game needs                                     | distinct RDRAM bytes touched after boot |

Reward = 1 − (geometric mean over workloads of yours / baseline), clipped to
[−1, 1]. Halving the cost scores 0.5; no change scores 0; a broken submission
scores −1 regardless of how fast it is. Other profiles have budgets: for
`rsp`, `traffic` and `memory`, frame time may not get more than 5% worse on any
workload, and no workload may regress more than 5% on the scored metric
(0% for `memory`).

All costs are measured by the emulator on the target hardware model: the
original 4 MB Nintendo 64 (no Expansion Pak) as modelled by ares, CPU
interpreter with the VR4300 instruction and data caches. Nothing the ROM
reports about itself is used.

## What must not change

Grading replays recorded controller inputs and compares your build to the
original, frame by frame:

- **Gameplay** — the observation record (`mev_obs_t`: player, camera,
  enemies, gems, RNG, particle and voice counts) must match **bit for bit**
  on every frame. Floating-point results that feed gameplay must therefore be
  identical: reordering arithmetic, `-ffast-math`, or approximate math in
  simulation code will fail.
- **Video** — every frame must match the original picture. A pixel passes if
  some pixel within one pixel of it in the original is within 2/31 per
  channel; a frame fails if more than 0.2% of pixels fail. Sub-pixel edge
  differences pass; missing or added objects do not.
- **Audio** — overall SNR ≥ 40 dB against the original, ≥ 20 dB on every
  non-silent frame; silence must stay silent.
- **The harness** — `src/mev.c` and `src/mev.h` must be byte-identical. Call
  `mev_read_pad()` once per frame before simulating it and `mev_end_frame()`
  once the frame is complete (see `mev.h`).
- **The hardware** — the ROM must run on a 4 MB console.

Everything else in `/task/game` is yours to change: C code, data layout,
the Makefile and compiler flags, assembly, RSP microcode, use of the cache
instructions. The libdragon in the toolchain is fixed.

Grading also uses **held-out routes** you cannot see (same scenes, different
inputs). Optimize the game, not the four public routes.

## Tools

```
mev build                 build /task/game
mev run meadow            run a public workload; prints cost vs baseline
mev profile fortress      per-function CPU profile (cache stalls included)
mev check                 the full grader on the public workloads
mev workloads             meadow, fortress, storm, concert
```

`mev check` is the same grader used for scoring, minus the held-out routes;
its `summary.json` names the first divergent field, frame and workload on any
gate failure. Raw run output (per-frame counters, framebuffers, audio,
observations) is kept under `/tmp/mev-*`.

Reference material: `/task/docs/` (N64 hardware notes, the cost model,
measurement definitions), libdragon headers and source in
`/opt/libdragon/mips64-elf/include` and `/opt/libdragon-src`. There is no
internet access.

## Rules

- Do not try to detect the grader, the replays or the emulator; the score is
  for the game running on the console.
- Commit your work to the git repository in `/task/game` as you go.
- You have a fixed time budget. A correct, modest improvement beats a broken
  ambitious one.
