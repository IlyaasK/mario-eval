# `n64run` Counter & Timing Interface

`n64run` executes the target ROM under the `ares` Nintendo 64 interpreter (16 KB I-cache, 8 KB write-back D-cache, RSP scalar+VU pipeline, 62.5 MHz RDP raster/TMEM/page-miss model, and per-device RDRAM bus accounting). Cumulative counters are written at the end of each logical frame `0 .. N-1` in `frames.jsonl` (`N = 240` by default). Frame `0` (boot and level setup) is excluded; per-frame deltas are evaluated across frames `1 .. N-1`:

- **VR4300 CPU (`93.75 MHz`, `93,750` cycles/ms)**:
  - `cpu_busy_cycles = count_ticks - cpu_idle_cycles` (`count_ticks` includes instruction execution plus uncontended cache-fill, write-back, and uncached RDRAM stall cycles; `cpu_idle_cycles` counts only unconditional self-branch + `nop` halt loops inside `thread1_idle`).
  - `bus_events = icache_misses + dcache_misses + dcache_writebacks + uncached_reads + uncached_writes`
  - `rcp_traffic = sum(reads + writes for dev in ("SP DMA", "PI DMA", "SI DMA", "DP DMA", "DP Draw"))`
  - `cpu_effective_cycles = cpu_busy_cycles + (4.0 + 6.0 * (rcp_traffic / 1e6)) * bus_events`
  - `cpu_ms = cpu_effective_cycles / 93,750`
- **RSP (`62.5 MHz`; `rsp_cycles` reported in `187.5 MHz` master clocks = `187,500` units/ms)**:
  - `rsp_busy = rsp_cycles - rsp_halted_cycles` (split by `OSTask.t.type` into `rsp_gfx_cycles` and `rsp_aud_cycles`)
  - `rsp_ms = rsp_busy / 187,500`
- **RDP (`62.5 MHz` `gclk`, `62,500` cycles/ms)**:
  - `dp_traffic = sum(reads + writes for dev in ("DP DMA", "DP Draw"))`
  - `vi_bytes = 2 * fb_w * fb_h * (fb_bpp / 8)` (60 Hz two-field VI scanout per 30 Hz game frame)
  - `other_bus_mb = (rdram_bytes - dp_traffic + vi_bytes) / 1e6`
  - `rdp_effective_cycles = rdp_cycles + (dp_traffic / 32.0) * (3.5 + 2.5 * other_bus_mb)`
  - `rdp_ms = rdp_effective_cycles / 62,500`
- **RDRAM Bus (`250,000` bytes/ms sustained mixed-master throughput)**:
  - `mem_ms = (rdram_bytes + vi_bytes) / 250,000`
- **Console Frame Cost**:
  - `est_console_ms = mean(max(cpu_ms, rsp_ms, rdp_ms, mem_ms))` over frames `1 .. N-1` (`est_fps = 1000 / est_console_ms`)
  - `est_console_p99_ms = percentile_99(max(cpu_ms, rsp_ms, rdp_ms, mem_ms))`

`result.json` additionally reports:
- `footprint_bytes`: distinct 16-byte RDRAM lines touched by any bus master after the ROM entry point (`resetPC`).
- `highest_line` (`highest_byte = (highest_line + 1) * 16`): highest RDRAM byte touched; must not exceed `4,194,304` (`0x00400000`).
- `oob_rdram_accesses`: physical memory accesses in unpopulated RDRAM (`0x00400000 .. 0x03EFFFFF`) or cached `KSEG0`/`KUSEG` CPU accesses outside `4 MB` RDRAM (`paddr >= 0x00400000`, e.g. cached cartridge ROM or RCP MMIO); must be `0`.
- `rdram_dma_coherence_errors`: `DP DMA` / `SP DMA` reads of RDRAM addresses currently holding dirty lines in the 8 KB write-back CPU D-cache (missing `osWritebackDCache` before DMA); must be `0`.
- `sp_dmem_coherence_errors` & `dcache_coherence_errors`: RSP reads of `SP DMEM` bytes loaded from dirty CPU D-cache lines plus `rdram_dma_coherence_errors`; capped at `<= 2.1 * frames`.
- `cache_uncached_ops`: hit/create-dirty-exclusive `CACHE` instructions issued against uncached (`KSEG1`) addresses; must be `0`.
- `cache_cde_unaligned_ops`: `CACHE 0x0d` (`Create_Dirty_Exclusive_D`) instructions issued on non-16-byte-aligned addresses; must be `0`.
- `cache_kseg1_dirty_synonyms`: uncached `KSEG1` RDRAM reads or writes aliasing a valid dirty `KSEG0` line in the CPU D-cache; must be `0`.
- `cpu_fault_exceptions` & `cpu_trap_exceptions`: synchronous VR4300 fault (`TLB*`, `ADE*`, `IBE`, `DBE`, `BP`, `RI`, `OV`, `FPE`, `WATCH`) and `TRAP` (`TEQ`/`TNE`, code `13`) exceptions; both must be `0`.
