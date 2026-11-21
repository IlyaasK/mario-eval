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
| **RDP 62.5 MHz hardware cost (`rdp_busy`)** | **yes** | exact scissor-clipped 4-subpixel scanline rasterizer + TMEM + sync cost model (approximate; see below) |
| **RDRAM traffic per bus device (`rdram_bytes`)** | **yes** | CPU I/D/Uncached + SP DMA + PI DMA + SI DMA + **DP DMA** + **DP Draw** |
| **4 MB RDRAM footprint (`footprint_bytes`)** | **yes** | distinct 16-byte lines touched by CPU, DMA, or RDP |
| RDRAM bus contention | modelled, not simulated | the units run deterministically one after another; the CPU is charged 24 cycles per bus transaction for waiting on the shared bus (see `est_console_ms`) |

### RDP cycle & RDRAM cost breakdown (`rdp_busy`, `DP DMA`, `DP Draw`)

Every RDP command emitted to the command buffer is profiled deterministically:
- **Fill / Copy mode (`G_CYC_FILL`, `G_CYC_COPY`)**: 4 pixels per cycle at 16bpp
  (2 pixels/cycle at 32bpp), color write only (`DP Draw` write).
- **1-Cycle vs 2-Cycle mode (`G_CYC_1CYCLE`, `G_CYC_2CYCLE`)**: 1 cycle/pixel in
  1-cycle mode, **2 cycles/pixel** in 2-cycle mode (`rdp_fill_cycles`), plus:
  - `+1 cycle/pixel` + `DP Draw` framebuffer read when `IM_RD` is enabled in `other_modes` (e.g. alpha blending or `AA_OPA_SURF` read-modify-write);
  - `+1 cycle/pixel` + `DP Draw` Z-buffer read (2 B/px) when `Z_CMP` is enabled;
  - `+0.5 cycle/pixel` + `DP Draw` Z-buffer write (2 B/px) when `Z_UPD` is enabled.
- **TMEM uploads (`LoadBlock`, `LoadTile`, `LoadTLUT`)**: `24 + ceil(bytes / 8)`
  cycles (`rdp_tmem_cycles`) + `DP DMA` RDRAM reads (`rdp_tmem_bytes`).
  Uploading the same texture repeatedly instead of batching by material pays
  this cost every time.
- **Synchronization (`SyncLoad`, `SyncPipe`, `SyncTile`, `SyncFull`)**:
  pipeline drain cycles (`rdp_sync_cycles`). Back-to-back duplicate syncs pay
  diminished drain cost, while syncs after active fill/TMEM work pay full drain.

## Measurement definitions

Each workload runs 240 logical frames **unthrottled**; frame 0 (boot and setup)
is excluded from per-frame means. The CPU's idle thread (waiting for the RCP)
is not counted as CPU work.

- **`est_console_ms` (`console`)** — estimated cost of the frame on a real
  console. SM64 overlaps its units: the CPU builds frame N+1 while the RSP and
  RDP draw frame N, all sharing RDRAM. So a frame costs as much as its busiest
  unit: `max(cpu_ms, rsp_ms, rdp_ms, mem_ms)`, where
  - `cpu_ms` = (busy VR4300 cycles + 24 × (I-cache misses + D-cache misses +
    D-cache write-backs + uncached accesses)) / 93,750. The 24-cycle bus
    contention term was fitted to Kaze Emanuar's measurements of vanilla SM64 on
    real hardware (JRB ≈ 20 FPS, DDD ≈ 24, RR ≈ 26; youtu.be/Ca1hHC2EctY at
    3:55); the model gives 20.0, 25.7 and 26.5;
  - `rsp_ms` = non-halted RSP cycles / 62,500; `rdp_ms` = RDP cycles / 62,500;
  - `mem_ms` = RDRAM bytes / 500,000 (500 MB/s peak, a floor).

  `est_fps` = 1000 / `est_console_ms` (uncapped). `est_fps_30hz` is what the
  player sees with SM64's 30 Hz game logic: each frame shows for at least two
  60 Hz fields, so it is at most 30. `frames_under_16ms` is the share of frames
  that would fit a 60 FPS budget. Known limitation: the RDP model is probably
  optimistic (Kaze attributes JRB's frame rate to drawing; the model has JRB
  CPU-bound).
- **`cpu_effective_cycles` (`speed`)** — the CPU term above in VR4300 cycles
  (93.75 MHz; one 60 Hz NTSC field = 1,562,500 cycles).
- **`rdp_busy` (`rdp`)** — RDP 62.5 MHz `gclk` cycles per frame.
- **`rsp_busy` (`rsp`)** — RSP non-halted cycles per frame.
- **`rdram_bytes` (`traffic`)** — total RDRAM bytes read + written per frame across all bus masters.
- **`footprint_bytes` (`memory`)** — distinct 16-byte RDRAM cachelines touched by any bus master after entry point.

## Reward

Per profile, the speedup is the geometric mean over workloads of
baseline / candidate. The reward is `log2(speedup) / 4` (2× scores 0.25, 16×
scores 1.0, no upper cap; a failed gate scores −1), so each doubling is worth
the same.

Reference points on SM64's public routes (console profile): GCC `-O2` alone
1.39×; `r10-kaze-master`, reconstructed techniques from Kaze Emanuar's
public work, 1.67×; `r11-beyond-kaze`, adding our own
D-cache layout work, 1.62× (earlier, smaller build).
