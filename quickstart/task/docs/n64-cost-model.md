# N64 cost model used by mario-eval

These notes describe what the grader measures and how the emulator it uses
(ares, pinned commit, CPU interpreter) models the machine. Where the model is
known to differ from a real console, that is stated.

## The machine

- **CPU** — NEC VR4300 (MIPS III), 93.75 MHz. One instruction per cycle when
  nothing stalls. 64-bit registers; the FPU is used in 32-bit-float mode by
  this game. No fused multiply-add.
- **Caches** — 16 KB instruction cache (32-byte lines) and 8 KB data cache
  (16-byte lines), both **direct-mapped**: two addresses 16 KB (I) or 8 KB (D)
  apart compete for the same line. Data cache is write-back. A miss stalls
  the CPU while the line is transferred from RDRAM.
- **RDRAM** — 4 MB, shared by the CPU (cache fills, write-backs, uncached
  accesses), the RSP (DMA), the RDP (command fetch, framebuffer and Z-buffer
  access), the video interface and audio interface DMA, and cartridge DMA.
- **RSP** — vector coprocessor running microcode from its own 4 KB IMEM / 4 KB
  DMEM. In this game it runs libdragon's `rspq` command queue, which feeds the
  RDP.
- **RDP** — rasterizer. Draws the triangles the CPU sends through `rdpq`.

## The `CACHE` instruction

The VR4300 lets software manage the caches directly (`cache op, offset(base)`).
Useful operations on the data cache:

| op     | effect |
|--------|--------|
| `0x0d` | **Create Dirty Exclusive**: mark the line for this address valid and dirty *without* reading RDRAM. Only safe if every byte of the line is written before it is read or written back. |
| `0x11` | Hit Invalidate: drop the line without writing it back. |
| `0x15` | Hit Write Back Invalidate. |
| `0x19` | Hit Write Back. |

libdragon wraps several of these (`data_cache_hit_writeback`, etc.). Create
Dirty Exclusive has no wrapper; use inline assembly.

## What the emulator models, and what it does not

| aspect | modelled by ares | notes |
|--------|------------------|-------|
| CPU instruction timing | yes | 1 cycle per instruction plus stalls |
| I-cache / D-cache contents and misses | yes | fixed per-miss stall cost |
| `CACHE` operations, incl. Create Dirty Exclusive | yes | CDE does not fetch the line |
| RSP instruction timing | yes | |
| RDRAM traffic per bus device | yes (counted) | |
| RDP rasterization time | **no** | the RDP completes instantly |
| Bus contention between CPU and RCP | **no** | a cache miss costs the same whatever else is running |

Consequences: making RDP work cheaper (fewer pixels, different fill modes)
does not change `speed` in this model, although it would on a console. Memory
traffic you remove is counted in `traffic` even where it would not have
stalled anything. Optimizations that only pay off through reduced bus
contention are not rewarded by `speed`.

## Measurement definitions

Each workload runs 240 logical frames **unthrottled**: the game never waits
for vertical blank, so frame cost is pure work. Frame 0 (boot and scene setup)
is excluded from per-frame averages.

- **COUNT ticks** — the CP0 Count register, which advances at half the CPU
  clock (46.875 MHz). One NTSC video field (1/60 s) is 781,250 ticks.
  `speed` = mean ticks between consecutive `mev_end_frame()` calls.
- **RSP busy** — RSP cycles not spent halted.
- **RDRAM bytes** — bytes read plus written by all hardware bus devices
  (CPU I-cache fills, D-cache fills and write-backs, uncached CPU accesses,
  SP/DP/PI/SI/VI/AI DMA).
- **Footprint** — distinct 16-byte RDRAM lines read or written by any device
  from the moment the game's entry point first executes (so the boot loader's
  RAM clear is excluded) to the end of the run; the maximum over workloads.
  Memory that is reserved but never touched is not counted; memory that is
  cleared once at startup is.

## Determinism

The emulator is deterministic: running the same ROM twice gives identical
counters. A change of a few percent is real, even if its cause is surprising
— code moving to a different cache index is a common one.
