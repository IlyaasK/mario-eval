# N64 hardware cost model used by mario-eval

These notes describe what the grader measures and how the instrumented emulator
(`ares`, pinned commit, VR4300 interpreter + RSP + instrumented RDP command &
rasterizer cost model) models the Nintendo 64.

## The machine

- **CPU** — NEC VR4300 (MIPS III), 93.75 MHz. One instruction per cycle when
  nothing stalls. 64-bit registers; 32-bit IEEE 754 FPU (no fused multiply-add).
- **Caches** — 16 KB instruction cache (32-byte lines) and 8 KB data cache
  (16-byte lines), both **direct-mapped**: two addresses 16 KB (I) or 8 KB (D)
  apart alias to the same line. Data cache is write-back and **allocate-on-write**
  by default (writing a cold line stalls to fetch all 16 bytes from RDRAM
  unless `Create Dirty Exclusive` is used).
- **RDRAM** — 4 MB (`0x00000000..0x003FFFFF`), shared across CPU I/D-cache
  fills and write-backs, uncached CPU accesses, SP DMA, DP DMA (display lists &
  TMEM uploads), DP Draw (framebuffer & Z-buffer reads/writes), PI DMA
  (cartridge ROM reads), and SI/VI/AI DMA.
- **RSP** — 62.5 MHz vector coprocessor (scalar SU + 8×16-bit SIMD VU) running
  microcode out of 4 KB IMEM / 4 KB DMEM (`rspq` in Pip's Garden; `gspFast3D`
  and `rspAspMain` in Super Mario 64).
- **RDP** — 62.5 MHz (`gclk`) fixed-function rasterizer, 4 KB on-chip TMEM,
  color combiner, Z-buffer, and blender.

## The `CACHE` instruction

The VR4300 allows user/kernel software in KSEG0 (`0x80xxxxxx`) to manage caches
directly (`cache op, offset(base)`):

| op     | effect |
|--------|--------|
| `0x0d` | **Create Dirty Exclusive**: mark the 16-byte D-cache line valid and dirty *without* reading RDRAM. Safe ONLY when every byte of that 16-byte line will be overwritten before any read or eviction, and never on boundary lines shared with live data. |
| `0x11` | Hit Invalidate: discard D-cache line without writing back (use before CPU reads of DMA targets). |
| `0x15` | Hit Write Back Invalidate. |
| `0x19` | Hit Write Back. |

## What the instrumented emulator models

| aspect | modelled | notes |
|--------|----------|-------|
| VR4300 instruction timing & pipeline | yes | 1 cycle/insn + FPU/mul/div + cache/bus stalls |
| 16 KB I-cache & 8 KB D-cache (direct-mapped) | yes | exact line tags; I-cache fill 48 cycles, D-cache fill or write-back 40 cycles |
| `CACHE` ops incl. `Create Dirty Exclusive` (`0x0d`) | yes | eliminates RDRAM read-for-ownership on cold writes |
| Uncached CPU access to RDRAM (KSEG1, `0xA0xxxxxx`) | yes | read 40 cycles, write 10 cycles (write buffer); each also counts as a bus transaction |
| RSP scalar + VU vector instruction cycles | yes | exact non-halted 62.5 MHz RSP cycles |
| **RDP 62.5 MHz hardware cost (`rdp_busy`)** | **yes** | exact scissor-clipped 4-subpixel scanline rasterizer + **4-bank × 2 KB RDRAM page-miss model (24 gclk/miss)** + TMEM + sync cost model |
| **RDRAM traffic per bus device (`rdram_bytes`)** | **yes** | CPU I/D/Uncached + SP DMA + PI DMA + SI DMA + **DP DMA** + **DP Draw** (+ continuous 60 Hz VI scanout in `mem_ms`) |
| **4 MB RDRAM footprint (`footprint_bytes`)** | **yes** | distinct 16-byte lines touched by CPU, DMA, or RDP |
| RDRAM bus contention | bus-coupled | the units run deterministically one after another; each CPU bus transaction pays `4 + 6 × (RCP_MB)` extra contention cycles so reducing `DP Draw`, `DP DMA`, or `SP DMA` lowers CPU bus stalls too |

### RDP cycle & RDRAM cost breakdown (`rdp_busy`, `DP DMA`, `DP Draw`)

Every RDP command emitted to the command buffer is profiled deterministically:
- **Fill / Copy mode (`G_CYC_FILL`, `G_CYC_COPY`)**: 4 pixels per cycle at 16bpp
  (2 pixels/cycle at 32bpp), color write only (`DP Draw` write).
- **1-Cycle vs 2-Cycle mode (`G_CYC_1CYCLE`, `G_CYC_2CYCLE`)**: 1 cycle/pixel in
  1-cycle mode, **2 cycles/pixel** in 2-cycle mode (`rdp_fill_cycles`), plus:
  - `+1 cycle/pixel` + `DP Draw` framebuffer read when `IM_RD` is enabled in `other_modes` (e.g. alpha blending or `AA_OPA_SURF` read-modify-write);
  - `+1 cycle/pixel` + `DP Draw` Z-buffer read (2 B/px) when `Z_CMP` is enabled;
  - `+0.5 cycle/pixel` + `DP Draw` Z-buffer write (2 B/px) when `Z_UPD` is enabled.
  - **Early-Z rejection**: when `Z_CMP` rejects a pixel against the shadow Z-buffer (`rdp_z_rejected_pixels`), color framebuffer writes, Z-buffer writes, and occluded-span color-write RDRAM page misses are skipped (rewarding front-to-back opaque ordering and overdraw reduction).
- **TMEM uploads (`LoadBlock`, `LoadTile`, `LoadTLUT`)**: `24 + ceil(bytes / 8)`
  cycles (`rdp_tmem_cycles`) + `DP DMA` RDRAM reads (`rdp_tmem_bytes`).
  Uploading the same texture repeatedly instead of batching by material pays
  this cost every time.
- **Synchronization (`SyncLoad`, `SyncPipe`, `SyncTile`, `SyncFull`)**:
  pipeline drain cycles (`rdp_sync_cycles`). Back-to-back duplicate syncs pay
  diminished drain cost, while syncs after active fill/TMEM work pay full drain.

## Measurement definitions

Each workload runs 240 logical frames **unthrottled**; frame 0 (boot and setup)
is excluded from per-frame means. Time the CPU spends in the idle thread's halt
loop (waiting for the RCP) is not counted as CPU work. The emulator recognizes
that loop from the instruction itself — a branch to its own address inside the
idle symbol's address range, plus its delay slot when that is a `nop` — so
renaming or resizing `thread1_idle`, or moving real work into it, cannot buy
free CPU time: nothing else is ever credited as idle.

- **`est_console_ms` (`console`)** — estimated cost of the frame on a real
  console. SM64 overlaps its units: the CPU builds frame N+1 while the RSP and
  RDP draw frame N, all sharing RDRAM alongside continuous 60 Hz VI scanout. So
  a frame costs as much as its busiest unit: `max(cpu_ms, rsp_ms, rdp_ms, mem_ms)`, where
  - `cpu_ms` = (busy VR4300 cycles + `(4 + 6 × rcp_mb)` × (I-cache misses +
    D-cache misses + D-cache write-backs + uncached accesses)) / 93,750, where
    `rcp_mb` is non-CPU RDRAM traffic in the frame (`SP DMA + DP DMA + DP Draw
    + PI DMA + SI DMA`, in MB);
  - `rsp_ms` = non-halted RSP master clocks (`rsp_cycles - rsp_halted_cycles`) / 187,500
    (ares steps the 62.5 MHz RSP in 187.5 MHz master clocks = 3 master clocks per RSP cycle);
  - `rdp_ms` = RDP cycles / 62,500, including **24 gclk per 2 KB RDRAM row miss**
    across the four 1 MB banks (`rdp_page_miss_cycles`; keeping color and Z
    buffers in distinct 1 MB banks avoids per-span bank thrashing);
  - `mem_ms` = (RDRAM bytes + 60 Hz VI scanout bytes) / 250,000 (250 MB/s
    sustained mixed-master RDRAM throughput).

  `est_fps` = 1000 / `est_console_ms` (uncapped). `est_fps_30hz` is what the
  player sees with SM64's 30 Hz game logic: each frame shows for at least two
  60 Hz fields, so it is at most 30. `frames_under_16ms` is the share of frames
  that would fit a 60 FPS budget. Known limitation: the RDP model is probably
  optimistic (Kaze attributes JRB's frame rate to drawing; the model has JRB
  CPU-bound).
- **`cpu_effective_cycles` (`speed`)** — the CPU term above in VR4300 cycles
  (93.75 MHz; one 60 Hz NTSC field = 1,562,500 cycles).
- **`est_console_p99_ms` (`stutter`)** — the 99th percentile of the same
  per-frame bottleneck `max(cpu_ms, rsp_ms, rdp_ms, mem_ms)`: the worst frames a
  player actually feels, not the average.
- **`rdp_busy` (`rdp`)** — RDP 62.5 MHz `gclk` cycles per frame.
- **`rsp_busy` (`rsp`)** — RSP non-halted cycles per frame.
- **`rdram_bytes` (`traffic`)** — total RDRAM bytes read + written per frame across all bus masters.
- **`footprint_bytes` (`memory`)** — distinct 16-byte RDRAM cachelines touched by any bus master after entry point.

## Physical-console calibration

The console score is a model, not a measurement of display FPS. On the
current public SM64 routes it is predominantly CPU-limited. Validate it on
an NTSC N64 with 4 MB RAM before using it to rank graphics-heavy changes:

1. Use ROMs for vanilla, GCC `-O2`, and Kaze, plus a graphics-focused change
   such as opaque render modes. Play the same recorded inputs on each through
   a controller-replay device. Include collision-heavy, fill-heavy underwater,
   and geometry-heavy scenes. Capture VI scanout and audio from the linked
   `PLAY=1` ROM; count repeated fields, not capture-host FPS.
2. In separate instrumented copies, timestamp CPU work spans with CP0 Count
   (46.875 MHz on NTSC; handle wrap). Timestamp RSP start, yield/resume and
   completion separately from queue wait. Read RDP DPC counters and record
   full-sync completion without resetting the counters while another task
   owns the pipeline. Record overlap rather than adding the three times.
   Buffer samples in RAM and export after the run; check the probe's overhead
   against the uninstrumented capture.
3. Compare medians, p99, and dropped-field rates per route against the
   emulator's predictions. Use separate calibration and validation scenes.
   Keep existing scores fixed until a new model improves out-of-sample
   predictions, then version the model and regrade its reference points.

## Reward

Per profile, the speedup is the geometric mean over workloads of
baseline / candidate. The reward is `max(-1, log2(speedup) / 4)` (2× scores
0.25, 16× scores 1.0, no upper cap); any failed gate scores −1 for every
profile, and a profile whose budget a workload exceeds scores −1 for that
profile. A profile has a **profile budget** on its own metric and a
**cross-subsystem budget** on another metric (a workload may not regress either
one past the budget):

| profile | metric | profile budget | cross-subsystem budget |
|---------|--------|----------------|------------------------|
| `console` | `est_console_ms` | ≤ 5% | `footprint_bytes` ≤ 5% |
| `stutter` | `est_console_p99_ms` | ≤ 5% | `footprint_bytes` ≤ 5% |
| `speed` | `cpu_effective_cycles` | ≤ 5% | `rdp_busy` ≤ 5% |
| `rdp` | `rdp_busy` | ≤ 5% | `cpu_effective_cycles` ≤ 5% |
| `rsp` | `rsp_busy` | ≤ 5% | `cpu_effective_cycles` ≤ 5% |
| `traffic` | `rdram_bytes` | ≤ 5% | `cpu_effective_cycles` ≤ 5% |
| `memory` | `footprint_bytes` | 0% | `cpu_effective_cycles` ≤ 5% |

Reference points on SM64's public routes (console profile): GCC `-O2` alone
1.38×; `r10-kaze-master`, reconstructed techniques from Kaze Emanuar's
public work, 1.67× (1.21× vs `-O2`, 1.65× across all 25 private routes);
`r11-beyond-kaze`, adding our own D-cache layout work, 1.65× (earlier, smaller
base; stacking its D-cache struct reorders onto `r10-kaze-master` reaches 1.70×).
