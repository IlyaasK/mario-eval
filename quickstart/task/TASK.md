# Make Pip's Garden faster and leaner on a real Nintendo 64

`/task/game` is the complete source of **Pip's Garden**, a 3D game for the
Nintendo 64 (libdragon, C). It is functionally correct, textured via DragonFS,
double-buffered, and playable on console, but written without regard for the
N64's hardware costs: built at `-O0`, issuing redundant 2-cycle RDP combiner
passes and unbatched TMEM texture uploads, streaming uncompressed cartridge
data via PI DMA, wasting RDRAM, and ignoring the VR4300's direct-mapped caches.

Your job over this 24-hour run is to super-optimize `/task/game` for the
original 4 MB Nintendo 64 hardware **without changing the game**.

## Objective

Your submission is scored on **one primary resource profile**, named in
`/task/PROFILE` (default: `console`). All six profiles are measured and reported:

| profile   | what is reduced                                        | measured as |
|-----------|--------------------------------------------------------|-------------|
| `console` | **Real N64 frame bottleneck time (headline score)**    | Per-frame `max(CPU_ms, RSP_ms, RDP_ms)` within 4 MB RAM |
| `speed`   | CPU time to compute and submit a frame                 | VR4300 COUNT ticks per frame (46.875 MHz) |
| `rdp`     | Reality Display Processor hardware busy time           | RDP 62.5 MHz cycles per frame (raster/fill/Z/TMEM/sync) |
| `rsp`     | Reality Signal Processor vector/microcode busy time    | RSP non-halted cycles per frame (62.5 MHz) |
| `traffic` | Total RDRAM bus traffic across all devices             | RDRAM bytes read+written per frame (CPU, SP, DP, PI, SI) |
| `memory`  | Console RAM footprint                                  | Distinct 16-byte RDRAM lines touched after boot |

For each profile, `geo = geomean(yours / baseline)` over all routes:
- **Bounded RL reward**: `reward = clip(1 - geo, -1, 1)` (`0.0` unchanged, `0.5` at 2×, `-1.0` if invalid or over budget).
- **Unbounded speedup**: `speedup = 1 / geo`, `log2_speedup = -log2(geo)`, and `vs_o2_speedup` (speedup beyond a clean `-O2 -fno-fast-math` compiler-only build, so true hardware/algorithmic super-optimization beyond `-O2` is directly visible).

Cross-subsystem budgets enforce honest hardware engineering:
- In `console`, no workload may regress `est_console_ms` or `footprint_bytes` by more than **5%**.
- In `speed`, no workload may regress `frame_ticks` or `rdp_busy` by more than **5%**.
- In `rdp`, `rsp`, and `traffic`, no workload may regress the target metric or `frame_ticks` by more than **5%**.
- In `memory`, no workload may regress `footprint_bytes` (`0%`) and `frame_ticks` may not regress by more than **5%**.

## What must not change

Grading replays recorded controller inputs and checks six gates on every route:

- **Integrity & Playable Build** — `src/mev.c` and `src/mev.h` must be
  byte-identical, and **both** the graded build (`make`) and the real-time
  60 Hz console build (`make PLAY=1`) must compile cleanly.
- **Execution & Hardware** — every route must complete all 240 frames within
  the 4 MB RDRAM ceiling (`0x00400000` bytes, no Expansion Pak).
- **Gameplay** — `mev_obs_t` (player, camera, enemies, gems, RNG, particle and
  voice counts) must match **bit for bit** on every frame. Reordering IEEE 754
  floating-point arithmetic in simulation code (`-ffast-math`) will drift and fail.
- **Video** — every frame as a whole must match either the baseline picture or
  an accepted visual variant (`full-detail` in `/opt/mario-eval/corpus/variants/`,
  where Pip is always drawn at full detail regardless of camera distance):
  at most 0.2% of pixels may differ by more than ±2/31 per channel from their
  best 3×3 neighbor.
- **Audio** — overall SNR ≥ 40 dB against baseline, ≥ 20 dB on every
  non-silent frame; silence must stay silent.

Grading on the host also runs **private held-out routes** you cannot see.
Optimize the engine, renderer, audio mixer, data layout, RSP/RDP command
stream, and cache usage — not the four public routes.

## Tools

```
mev build                 build /task/game
mev run meadow            run a public workload; prints CPU/RDP/RSP/RDRAM vs baseline
mev profile fortress      per-function CPU profile (cache & uncached stalls included)
mev check                 run the full grader on all public workloads
mev workloads             meadow, fortress, storm, concert
```

Reference material: `/task/docs/n64-cost-model.md`, libdragon headers in
`/opt/libdragon/mips64-elf/include` and source in `/opt/libdragon-src`.

## Rules

- Do not attempt to detect the grader, replays, or emulator.
- Commit working milestones to the git repository in `/task/game` regularly so
  no progress is lost across checkpoints.
