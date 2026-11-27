# Super Mario 64 Hardware Optimization

`/task/game` contains the complete US Super Mario 64 source tree (`n64decomp/sm64`) targeting an unexpanded retail **4 MB Nintendo 64** (`4,194,304` bytes RDRAM, no Expansion Pak). Optimize it for the active profile in `/task/PROFILE` (default: `console`) without altering gameplay, audio, or visual fidelity beyond the accepted visual variants below.

This is an open-ended systems engineering benchmark with no score ceiling. Do not stop after initial speedups: keep profiling, testing concrete hypotheses, and committing verified improvements in `/task/game` until your time budget ends, always leaving a clean working tree that passes plain `mev check`.

## Evaluation & Scoring

Host grading builds `/task/game` from scratch in an isolated, network-disabled container with a scrubbed environment (`make VERSION=us COMPARE=0 NOEXTRACT=1` and `PLAY=1`) and evaluates the resulting ROM across **private held-out 240-frame scripted routes and seeded random-input trajectories** spanning Super Mario 64's courses, acts, and sub-areas. The 6 public workloads (`bob`, `wf`, `jrb`, `ddd`, `bitfs`, `rr`) are provided for local development and carry **0% weight** in the final score (`75%` held-out scripted routes, `25%` held-out random-input routes).

1. **Global & Route Gates**: Submission integrity, clean benchmark + `PLAY=1` compilation, `PLAY=1` cold-boot runtime smoke (video progress, controller response, 4 MB RDRAM limit, cache/DMA coherence, and active RSP audio), all 5 gates (`execution`, `gameplay`, `video`, `audio`, `hardware`) on every evaluated route, and the active profile's per-route regression cap must all pass, or the submission is `invalid` (`reward = -1.0`, `speedup = 0.0`).
2. **Aggregation**: On valid submissions, each route's cost ratio is $r_w = \text{cand}_w / \text{base}_w$, aggregated as `speedup = 1 / geomean_weighted(r_w)` (`75%` held-out scripted routes, `25%` held-out random-input routes), `cost_saved = 1 - 1 / speedup`, and `reward = log2(speedup) / 4.0`. (For diagnostic telemetry on invalid checkpoints, `fidelity.effective_speedups` also records per-route gated speedup with $r_w = 1.0$ on failed routes.)

| Profile | Metric (`frames 1..239`) | Route Regression Cap | Cross-Subsystem Cap |
|---------|--------------------------|----------------------|---------------------|
| `console` | `est_console_ms = max(cpu_ms, rsp_ms, rdp_ms, mem_ms)` | `<= 5%` | None (`<= 4.00 MB` RDRAM hardware gate applies) |
| `stutter` | `est_console_p99_ms` (99th-percentile frame cost) | `<= 5%` | None (`<= 4.00 MB` RDRAM hardware gate applies) |
| `speed` | `cpu_effective_cycles` | `<= 5%` | `rdp_busy <= 5%` |
| `rdp` | `rdp_busy` | `<= 5%` | `cpu_effective_cycles <= 5%` |
| `rsp` | `rsp_busy` | `<= 5%` | `cpu_effective_cycles <= 5%` |
| `traffic` | `rdram_bytes` | `<= 5%` | `cpu_effective_cycles <= 5%` |
| `memory` | `footprint_bytes` | `<= 0.2%` | `cpu_effective_cycles <= 5%` |

## Correctness Gates

- **Integrity & `PLAY=1` Parity**: `src/game/mev.c` and `src/game/mev.h` are read-only contract files and must not be modified. Do not touch ISViewer MMIO (`0xB3FF....`) or emit `@mev ` outside the harness, redefine/wrap `mev_*` or `thread1_idle`, use `-include`/`-imacros`/`--wrap`/`--defsym` build overrides, exceed the retail `8 MB` (`8,388,608` bytes) ROM cartridge size, shrink `gGfxSPTaskYieldBuffer` (`>= 2304` bytes) or `sMevAudioStorage` (`>= 4096` bytes), or add `#ifdef PLAY` / `#ifndef PLAY` conditionals (or edit protected `PLAY` blocks beyond framebuffer count / D-cache writebacks) that make the benchmark ROM diverge from the `PLAY=1` console ROM. Edit `/task/game/Makefile` directly for compiler/microcode flags (CLI Make environment overrides are stripped during grading).
- **Execution & Hardware**: Every route must complete `240` logical frames with `0` synchronous CPU fault or trap exceptions (`cpu_fault_exceptions == 0`, `cpu_trap_exceptions == 0`), Frame-0 cold-boot setup within `+500 ms` (`46,875,000` VR4300 cycles) of baseline, `highest_byte <= 4,194,304`, `oob_rdram_accesses == 0` (including zero cached `KSEG0` accesses outside `4 MB` RDRAM), `cache_uncached_ops == 0`, `cache_cde_unaligned_ops == 0`, `cache_kseg1_dirty_synonyms == 0`, `rdram_dma_coherence_errors == 0`, `sp_dmem_coherence_errors <= 2.1 * frames`, and active RSP audio synthesis (`rsp_aud_cycles > 0`).
- **Gameplay**: On every frame, `frame`, `level_area`, `mario_stats` (health, coins, stars, lives), `mario_action`, and `actor_count` must match exact baseline values; `mario_pos`, `mario_vel`, and `mario_floor_height` must stay within `+-0.01` units (`L_inf`); `cam_pos` and `cam_focus` within `+-0.02` units; and every reference actor within `2000` units of Mario must match a candidate actor (unordered) with identical action/state and position within `+-0.1` units.
- **Video**: Every frame of a route must match either the baseline video or **one consistent accepted visual rendering mode** across all frames of that route, with `<= 0.35%` of pixels exceeding `+-2/31` channel difference in a `3x3` neighborhood **and** 16x16 block-SSIM `>= 0.98` (worst frame `>= 0.85`). Equal-or-higher-detail rendering changes accepted by the reference set (individually or combined) are: always drawing Mario's near high-polygon model, disabling distance LOD model switching across scene geometry, switching to libultra's `F3DEX2` graphics microcode, using SGI's reduced-aliasing opaque surface render modes (`RA_ZB_OPA_SURF` / `RA_OPA_SURF`), and drawing Rainbow Ride's static zero-yaw decorative platform pieces as static level geometry rather than spawned objects.
- **Audio**: Stereo 32 kHz output must achieve overall SNR `>= 40 dB` and worst-frame SNR `>= 20 dB` (or 40-band log-mel spectral similarity `>= 0.95`, worst frame `>= 0.75`, and channel RMS loudness within `+-15%`), and frames silent in the baseline must remain silent.

## Local Tooling & Documentation

- `mev build [--clean]` — build `/task/game` with a scrubbed Make environment.
- `mev run (<course> | --all) [--frames N] [--json]` — run one or all 6 public dev courses (`N = 240` default) and print CPU/RSP/RDP/RDRAM cost breakdowns.
- `mev profile <course> [--top N] [--frames N]` — run with clock-weighted PC, D-cache miss, write-back, and 16 KB I-cache conflict symbolization.
- `mev check [<course> ...] [--fast]` — run the exact public grader and gates (`--fast` reuses incremental builds and skips `PLAY=1` for rapid iteration; run plain `mev check` before committing milestones).
- `mev stress [--frames N] [--seed S] [--all-courses]` — run seeded random-input differential checks against the unmodified baseline ROM across the 6 public courses (or across 18 SM64 courses with `--all-courses`).
- `mev diff <replay.txt> [--frames N]` — run any custom replay file against both `/task/game` and the unmodified baseline ROM and verify all execution, hardware, gameplay, video, and audio gates. (On frame 0 of a replay, holding `S` + level bits `{6:1, 4:2, 2:4, 8:8, B:16, A:32}` + `(act - 1)` bits `{Z:1, L:2, u:4}` boots any valid SM64 `level` `4..36` and `act` `1..6`; without `S`, single-button shortcuts `.`=`bob`, `L`=`wf`, `R`=`jrb`, `u`=`ddd`, `d`=`bitfs`, `Z`=`rr` boot Act 1.)
- `mev workloads` / `mev restore-assets` — list public dev courses or restore extracted US assets offline if deleted.
- Read-only specifications in `/task/spec/`:
  - `/task/spec/MEASUREMENT.md` — `n64run` counter and `est_console_ms` definitions.
  - `/task/spec/n64brew/` — N64brew Wiki hardware documentation (VR4300 CPU/FPU/MMU, RSP, RDP, RDRAM, and RCP DMA interfaces; start at `/task/spec/n64brew/INDEX.md`).
