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
| `console` | **Real N64 frame bottleneck time (headline score)**    | Per-frame `est_console_ms` = `max(cpu_ms, rsp_ms, rdp_ms, mem_ms)` within 4 MB RAM |
| `speed`   | CPU time to compute and submit a frame                 | `cpu_effective_cycles` per frame (VR4300 cycles incl. cache/bus stalls) |
| `rdp`     | Reality Display Processor hardware busy time           | `rdp_busy` (RDP 62.5 MHz cycles: raster/fill/Z/TMEM/sync) |
| `rsp`     | Reality Signal Processor vector/microcode busy time    | `rsp_busy` (RSP non-halted cycles per frame) |
| `traffic` | Total RDRAM bus traffic across all devices             | `rdram_bytes` read+written per frame (CPU, SP, DP, PI, SI) |
| `memory`  | Console RAM footprint                                  | `footprint_bytes` (distinct 16-byte RDRAM lines touched after boot) |

For each profile, `geo = geomean(yours / baseline)` over all routes:
- **Reward (log-scaled, unbounded above)**: `reward = max(-1, log2(1 / geo) / 4)` — 2× scores 0.25, 4× 0.5, 16× 1.0 (`0.0` unchanged); any failed gate, or an over-budget profile, scores `-1.0`.
- **Unbounded speedup**: `speedup = 1 / geo`, `log2_speedup = -log2(geo)`, and `vs_o2_speedup` (speedup beyond a clean `-O2 -fno-fast-math` compiler-only build, so true hardware/algorithmic super-optimization beyond `-O2` is directly visible).

Course budgets enforce honest hardware engineering. Each profile has a **profile budget** on its own metric and a **cross-subsystem budget** on the other metric:
- In `console`, no workload may regress `est_console_ms` or `footprint_bytes` by more than **5%**.
- In `speed`, no workload may regress `cpu_effective_cycles` or `rdp_busy` by more than **5%**.
- In `rdp`, `rsp`, and `traffic`, no workload may regress the target metric or `cpu_effective_cycles` by more than **5%**.
- In `memory`, no workload may regress `footprint_bytes` (`0%`) and `cpu_effective_cycles` may not regress by more than **5%**.

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
