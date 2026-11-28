#!/usr/bin/env python3
"""mev: build, run, profile, stress-test and self-check the target N64 game inside the task container.

  mev build [--clean]           build /task/game (prints ROM sha256, active Makefile config & rebuild status)
  mev run WORKLOAD [--frames N] [--json]
  mev run --all [--frames N] [--json]
                                run one or all public workloads in parallel, print
                                hardware cost breakdown (CPU, RSP Gfx/Aud, RDP modes, RDRAM)
  mev profile WORKLOAD [--top N] [--frames N]
                                per-function CPU profile (excluding idle thread from busy %),
                                function addresses, sizes & I-cache set ranges, D/I-cache misses,
                                data-symbol D-cache miss & writeback attribution, 16 KB I-cache
                                conflicts, and RDP/RDRAM breakdown
  mev check [WORKLOAD ...] [--fast] [--no-play-smoke]
                                full public grading of /task/game (same grader, same gates,
                                including clean build, PLAY=1 console ROM, and PLAY=1 boot
                                smoke by default on SM64). Pass workload IDs (e.g.
                                `mev check jrb`) and/or `--fast` (incremental build, skips
                                PLAY=1) for a ~5s gate-verified loop.
  mev stress [--frames N] [--seed S] [--all-courses]
                                run seeded random-input differential stress tests against
                                baseline.z64 across the 6 public courses (or 18 SM64 courses
                                with --all-courses)
  mev diff REPLAY [--frames N]  run any custom replay file against /task/game and baseline.z64
                                and check execution, hardware, gameplay, video, and audio gates
  mev workloads                 list public workloads
  mev restore-assets            restore extracted SM64 assets offline if deleted

All costs are measured by the emulator (ares N64 model), never by the ROM.
"""
import argparse
import concurrent.futures
import fcntl
import hashlib
import json
import math
import os
import pathlib
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time

GAME = pathlib.Path("/task/game")
CORPUS = pathlib.Path("/opt/mario-eval/corpus")
CACHE = pathlib.Path("/opt/mario-eval/reference")
BUILD_LOCK = pathlib.Path("/tmp/mev-build.lock")
_MAKE_ENV_ALLOW = ("PATH", "N64_INST", "HOME", "TMPDIR", "TMP", "TEMP", "LANG", "LC_ALL", "TERM", "SHELL", "USER")
_STRIPPED_BUILD_VARS = (
    "COMPILER", "GRUCODE", "OPT_FLAGS", "CFLAGS", "EXTRA_CFLAGS", "CPPFLAGS",
    "LDFLAGS", "ASFLAGS", "NON_MATCHING", "AVOID_UB", "MAKEFLAGS", "MFLAGS", "PLAY",
)
_WARNED_ENV = False


def sh(cmd, **kw):
    return subprocess.run(cmd, check=False, **kw)


def _clean_make_env():
    """Strip Make override env vars (COMPILER, GRUCODE, OPT_FLAGS, PLAY, CFLAGS, ...)
    so local `mev` builds match clean host grading, and warn loudly if any were set."""
    global _WARNED_ENV
    stripped = [f"{k}={os.environ[k]}" for k in _STRIPPED_BUILD_VARS if k in os.environ and os.environ[k] != ""]
    if stripped and not _WARNED_ENV:
        _WARNED_ENV = True
        print(
            f"WARNING: ignoring environment override(s) {', '.join(stripped)} — "
            f"host grading builds with clean Make; edit {GAME}/Makefile directly!",
            file=sys.stderr,
        )
    env = {k: os.environ[k] for k in _MAKE_ENV_ALLOW if k in os.environ}
    env.setdefault("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")
    env["LANG"] = "C"
    env["LC_ALL"] = "C"
    return env


def _prune_old_temps(max_age_s=7200, max_keep=4):
    now = time.time()
    keep = set()
    last_link = pathlib.Path("/tmp/mev-last-check")
    if last_link.is_symlink():
        try:
            keep.add(last_link.resolve())
        except OSError:
            pass
    tmp_root = pathlib.Path("/tmp")
    dirs = []
    for p in tmp_root.glob("mev-*"):
        if not p.is_dir() or p.is_symlink():
            continue
        try:
            rp = p.resolve()
            if rp in keep:
                continue
            mt = p.stat().st_mtime
            if now - mt > max_age_s:
                shutil.rmtree(p, ignore_errors=True)
            else:
                dirs.append((mt, p))
        except OSError:
            pass
    dirs.sort(key=lambda x: x[0], reverse=True)
    for _mt, old_p in dirs[max_keep:]:
        shutil.rmtree(old_p, ignore_errors=True)


def config():
    return json.loads((CORPUS / "grader.json").read_text())


def _file_sha(path, length=12):
    if not path.is_file():
        return None
    h = hashlib.sha256(path.read_bytes()).hexdigest()
    return h[:length] if length else h


def _rom_sha(path):
    return _file_sha(path, length=12)


def _build_config_stamp():
    """Combined digest over Makefile, Makefile.split, util.mk, and linker scripts."""
    h = hashlib.sha256()
    found = False
    for rel in ("Makefile", "Makefile.split", "util.mk", "sm64.ld"):
        p = GAME / rel
        if p.is_file():
            found = True
            h.update(rel.encode("utf-8"))
            h.update(p.read_bytes())
    return h.hexdigest() if found else None


def _active_makefile_summary(base_cmd, make_env):
    """Query active COMPILER, GRUCODE, and OPT_FLAGS from SM64 Makefile if supported."""
    if not (GAME / "Makefile").is_file() or not base_cmd or base_cmd[0] != "make":
        return ""
    flags = [a for a in base_cmd[1:] if "=" in a]
    try:
        r = subprocess.run(
            ["make", "-s", *flags, "print-COMPILER", "print-GRUCODE", "print-OPT_FLAGS"],
            cwd=GAME, env=make_env, capture_output=True, text=True, timeout=5,
        )
        if r.returncode != 0:
            return ""
        vals = {}
        for line in (r.stdout + "\n" + r.stderr).splitlines():
            m = re.match(r"^(COMPILER|GRUCODE|OPT_FLAGS)\s+is\s+.*\[(.*)\]", line.strip())
            if m:
                vals[m.group(1)] = m.group(2).strip()
        if not vals:
            return ""
        parts = [f"{k.lower()}={vals[k]}" for k in ("COMPILER", "GRUCODE", "OPT_FLAGS") if k in vals]
        return ", " + " ".join(parts)
    except Exception:
        return ""


def _elf_ram_headroom_summary(elf):
    """Report static SM64 RDRAM pool & engine BSS headroom from ELF symbols so
    agents see main_pool / SEG_ENGINE pressure locally before hitting held-out OOMs."""
    if not elf or not pathlib.Path(elf).is_file():
        return ""
    try:
        r = subprocess.run(["mips64-elf-nm", "--defined-only", str(elf)],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return ""
        syms = {}
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and len(parts[0]) >= 6:
                try:
                    syms[parts[-1]] = int(parts[0], 16) & 0xFFFFFFFF
                except ValueError:
                    pass
        # SM64 US main_pool spans _mainSegmentNoloadEnd .. _engineSegmentStart (or gPoolMem)
        m_end = syms.get("_mainSegmentNoloadEnd") or syms.get("_buffersSegmentNoloadEnd")
        e_start = syms.get("_engineSegmentStart")
        e_end = syms.get("_engineSegmentNoloadEnd")
        fb_start = syms.get("_framebuffersSegmentNoloadStart")
        notes = []
        if m_end and e_start and e_start > m_end:
            gap_kb = (e_start - m_end) / 1024.0
            notes.append(f"pool_gap={gap_kb:.0f}KiB")
        if e_end and fb_start and fb_start >= e_end:
            eng_kb = (fb_start - e_end) / 1024.0
            notes.append(f"engine_bss_slack={eng_kb:.1f}KiB")
            if eng_kb < 1.5:
                notes.append("LOW_ENGINE_BSS_SLACK")
        return (", " + " ".join(notes)) if notes else ""
    except Exception:
        return ""


def find_elf(cfg):
    if "elf" in cfg:
        p = GAME / cfg["elf"]
        if p.exists():
            return p
    for p in GAME.rglob("*.elf"):
        return p
    return None


def _symbolize_pc(elf, pc_hex):
    """Map a hex virtual PC (e.g. '0x802a1234') to 'func+0xoffset' using ELF symbols."""
    if not elf or not pc_hex or not pathlib.Path(elf).is_file():
        return str(pc_hex or "")
    try:
        addr = int(str(pc_hex), 16) & 0xFFFFFFFF
        r = subprocess.run(["mips64-elf-nm", "-n", "-S", "--defined-only", str(elf)],
                           capture_output=True, text=True, timeout=5)
        if r.returncode != 0:
            return str(pc_hex)
        best = None
        for line in r.stdout.splitlines():
            parts = line.split()
            if len(parts) >= 3 and parts[-2] in "tTwW":
                s_addr = int(parts[0], 16) & 0xFFFFFFFF
                s_size = int(parts[1], 16) if len(parts) == 4 else 0
                if s_addr <= addr:
                    best = (s_addr, s_size, parts[-1])
                else:
                    break
        if best is not None:
            s_addr, s_size, name = best
            off = addr - s_addr
            if s_size == 0 or off < max(s_size, 65536):
                return f"{pc_hex} ({name}+0x{off:x})"
    except Exception:
        pass
    return str(pc_hex)


def _max_coherence_errors(cfg, frames):
    hw = cfg.get("hardware", {})
    if "max_dcache_coherence_errors" in hw:
        return int(hw["max_dcache_coherence_errors"])
    if "max_dcache_coherence_errors_per_frame" in hw:
        return int(float(hw["max_dcache_coherence_errors_per_frame"]) * frames)
    return None


def build(clean=False, quiet_stdout=False, clear_last_check_on_fail=False):
    cfg = config()
    sys.path.insert(0, "/opt/mario-eval")
    from grader.grade import audit_submission_integrity
    audit_errs = audit_submission_integrity(GAME, cfg)
    if audit_errs:
        if clear_last_check_on_fail:
            pathlib.Path("/tmp/mev-last-check").unlink(missing_ok=True)
        sys.exit("integrity check failed: " + "; ".join(audit_errs[:3]))

    rom = GAME / cfg["rom"]
    jobs = str(max(1, int(os.environ.get("MEV_JOBS") or os.cpu_count() or 8)))
    base_cmd = cfg.get("build_cmd", ["make"])
    cmd = [base_cmd[0], f"-j{jobs}", *base_cmd[1:]] if base_cmd[0] == "make" else list(base_cmd)
    make_env = _clean_make_env()
    stamp_path = rom.parent / ".mev-build-stamp"
    cfg_sha = _build_config_stamp()

    BUILD_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(BUILD_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        prev_stamp_rom = None
        prev_stamp_cfg = None
        if stamp_path.is_file():
            try:
                st = json.loads(stamp_path.read_text())
                prev_stamp_rom = st.get("rom_sha256")
                prev_stamp_cfg = st.get("makefile_sha256")
            except Exception:
                st = {}
        if not clean and base_cmd[0] == "make" and rom.is_file():
            cur_rom_sha = _rom_sha(rom)
            need_clean_reason = None
            if not stamp_path.is_file():
                need_clean_reason = "ROM was built outside `mev` (no build stamp)"
            elif cfg_sha and prev_stamp_cfg != cfg_sha:
                need_clean_reason = "Makefile / linker config changed since last build"
            elif prev_stamp_rom != cur_rom_sha:
                need_clean_reason = "ROM modified outside `mev` (e.g. CLI `make` override)"
            if need_clean_reason:
                print(f"NOTE: {need_clean_reason}; running clean rebuild to match host grading...", file=sys.stderr)
                clean = True

        pre_clean_sha = _rom_sha(rom) if rom.is_file() else prev_stamp_rom
        if clean and base_cmd[0] == "make":
            sh(["make", "clean"], cwd=GAME, env=make_env,
               stdout=subprocess.DEVNULL if quiet_stdout else sys.stderr, stderr=sys.stderr)
        pre_sha = _rom_sha(rom)
        pre_mtime = rom.stat().st_mtime if rom.is_file() else 0.0
        if quiet_stdout:
            r = sh(cmd, cwd=GAME, env=make_env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if r.returncode != 0 or not rom.exists():
                if clear_last_check_on_fail:
                    pathlib.Path("/tmp/mev-last-check").unlink(missing_ok=True)
                if r.stdout:
                    print(r.stdout, file=sys.stderr, end="")
                sys.exit("build failed")
        else:
            r = sh(cmd, cwd=GAME, env=make_env, stdout=sys.stderr)
            if r.returncode != 0 or not rom.exists():
                if clear_last_check_on_fail:
                    pathlib.Path("/tmp/mev-last-check").unlink(missing_ok=True)
                sys.exit("build failed")
        post_sha = _rom_sha(rom)
        post_mtime = rom.stat().st_mtime
        rebuilt = (pre_sha is None) or (post_sha != pre_sha) or (post_mtime != pre_mtime)
        try:
            stamp_path.write_text(json.dumps({
                "makefile_sha256": cfg_sha,
                "rom_sha256": post_sha,
                "build_cmd": base_cmd,
            }) + "\n")
        except OSError:
            pass
        cfg_desc = _active_makefile_summary(base_cmd, make_env)
        ram_desc = _elf_ram_headroom_summary(find_elf(cfg))
        unchanged_note = ""
        if clean and pre_clean_sha and post_sha == pre_clean_sha and prev_stamp_cfg and cfg_sha != prev_stamp_cfg:
            unchanged_note = "  [WARNING: ROM bytes unchanged vs prior build — check for inactive #ifdef or shadowed Makefile rule!]"
        print(f"ROM sha256: {post_sha} (rebuilt: {'yes' if rebuilt else 'no'}{cfg_desc}{ram_desc}){unchanged_note}", file=sys.stderr)
        return rom


def idle_range_list(cfg):
    elf = find_elf(cfg)
    if not elf:
        print("warning: no ELF in the build tree, so idle time is counted as CPU work; "
              "`mev build` first for numbers that match grading", file=sys.stderr)
        return []
    sys.path.insert(0, "/opt/mario-eval")
    from grader.grade import idle_ranges
    return idle_ranges(elf, cfg.get("idle_symbols", []))


def idle_args(cfg):
    args = []
    for r in idle_range_list(cfg):
        args += ["--idle-range", r]
    return args


def replay(workload):
    for w in config()["workloads"]:
        if w["id"] == workload:
            return CORPUS / w["replay"]
    sys.exit(f"unknown workload {workload}; try: mev workloads")


def print_time_remaining():
    raw = os.environ.get("MEV_DEADLINE_EPOCH", "").strip()
    if not raw:
        return
    try:
        deadline = int(raw)
    except ValueError:
        return
    rem = deadline - int(time.time())
    if rem <= 0:
        print("time remaining: 0m (deadline reached — leave a clean, mev-check-passing tree)")
        return
    hrs, mins = divmod((rem + 59) // 60, 60)
    span = f"{hrs}h {mins:02d}m" if hrs else f"{mins}m"
    note = " — wrap up soon, commit your best passing tree, and verify with plain `mev check`" if rem <= 1200 else ""
    print(f"time remaining: {span}{note}")


def _load_metrics_and_base(out_dir, workload):
    sys.path.insert(0, "/opt/mario-eval")
    from grader.grade import load_run, metrics
    res_file = out_dir / "result.json"
    if not res_file.is_file():
        print(json.dumps({"workload": workload, "status": "runner_timeout_or_error"}, indent=1))
        sys.exit(1)
    result = json.loads(res_file.read_text())
    if result["status"] != "completed":
        print(json.dumps({"workload": workload, **result}, indent=1))
        sys.exit(1)
    run_data = load_run(out_dir)
    m = metrics(run_data)
    ref = load_run(CACHE / "runs" / workload)
    ref["rows"] = ref["rows"][:len(run_data["rows"])]
    base = metrics(ref)
    return result, run_data, m, base


def summarize(out_dir, workload, full_frames=240, as_json=False, cfg=None):
    result, run_data, m, base = _load_metrics_and_base(out_dir, workload)
    frames = len(run_data["rows"])
    if as_json:
        print(json.dumps({"workload": workload, "frames": frames, "metrics": m, "baseline": base}, indent=1))
        return
    if frames != full_frames:
        print(f"NOTE: {frames}-frame quick run — compare only against {frames}-frame runs (`mev check` grades {full_frames} frames).")
    console = [
        ("Est. console ms  [console]", "est_console_ms"),
        ("Est. console p99 ms [stutter]", "est_console_p99_ms"),
        ("CPU ms", "cpu_ms"),
        ("RSP ms", "rsp_ms"),
        ("RDP ms", "rdp_ms"),
        ("RDRAM ms", "mem_ms"),
    ]
    detail = [
        ("Est. FPS (uncapped)", "est_fps"),
        ("CPU effective cycles", "cpu_effective_cycles"),
        ("CPU busy cycles", "cpu_busy_cycles"),
        ("CPU idle cycles", "cpu_idle_cycles"),
        ("RDP busy cycles", "rdp_busy"),
        ("RDP page-miss cycles", "rdp_page_miss_cycles"),
        ("RDP RDRAM page misses", "rdp_rdram_page_misses"),
        ("RSP busy cycles", "rsp_busy"),
        ("RDRAM bytes", "rdram_bytes"),
        ("D-cache misses", "dcache_misses"),
        ("D-cache writebacks", "dcache_writebacks"),
        ("I-cache misses", "icache_misses"),
        ("TMEM loads", "rdp_tmem_loads"),
        ("TMEM bytes", "rdp_tmem_bytes"),
        ("RDP pixels", "rdp_pixels"),
        ("RDP Z-rejected pixels", "rdp_z_rejected_pixels"),
        ("RDRAM footprint bytes*", "footprint_bytes"),
    ]
    print(f"{'':30s} {'yours':>14s} {'baseline':>14s} {'ratio':>8s} {'speedup':>8s}   ({frames} frames)")
    print("  est_console_ms = per-frame max(CPU, RSP, RDP, RDRAM)  (--profile metrics: console, stutter)")
    for label, key in console:
        b = base.get(key)
        ratio = f"{m[key] / b:8.3f}" if b else ""
        sp = f"{b / m[key]:7.2f}x" if (b and m[key]) else ""
        print(f"{label:30s} {m[key]:14.3f} {b if b is not None else float('nan'):14.3f} {ratio} {sp}")

    cpu_cpm = 93_750.0
    ic_ms = (m.get("icache_misses", 0.0) * 48.0) / cpu_cpm
    dc_ms = (m.get("dcache_misses", 0.0) * 40.0) / cpu_cpm
    wb_ms = (m.get("dcache_writebacks", 0.0) * 40.0) / cpu_cpm
    uc_ms = (m.get("uncached_reads", 0.0) * 40.0 + m.get("uncached_writes", 0.0) * 10.0) / cpu_cpm
    bus_ms = m.get("cpu_bus_contention_cycles", 0.0) / cpu_cpm
    insn_ms = max(0.0, m.get("cpu_ms", 0.0) - (ic_ms + dc_ms + wb_ms + uc_ms + bus_ms))
    print(f"  CPU breakdown: insn/other={insn_ms:.2f}ms  I$fill={ic_ms:.2f}ms  D$fill={dc_ms:.2f}ms  "
          f"D$wb={wb_ms:.2f}ms  uncached={uc_ms:.2f}ms  bus_cont={bus_ms:.2f}ms")
    if m.get("rsp_gfx_ms", 0.0) or m.get("rsp_aud_ms", 0.0):
        rsp_other = max(0.0, m.get("rsp_ms", 0.0) - m.get("rsp_gfx_ms", 0.0) - m.get("rsp_aud_ms", 0.0))
        print(f"  RSP breakdown: gfx={m.get('rsp_gfx_ms', 0.0):.2f}ms  aud={m.get('rsp_aud_ms', 0.0):.2f}ms  other={rsp_other:.2f}ms")
    rdp_cpm = 62_500.0
    z_pct = (100.0 * m.get("rdp_z_rejected_pixels", 0.0) / max(m.get("rdp_pixels", 0.0), 1.0))
    print(f"  RDP breakdown: fill={m.get('rdp_fill_cycles',0)/rdp_cpm:.2f}ms "
          f"[overlapping tags: im_rd={m.get('rdp_fill_imrd_cycles',0)/rdp_cpm:.2f}ms "
          f"2cyc={m.get('rdp_fill_2cycle_cycles',0)/rdp_cpm:.2f}ms "
          f"decal={m.get('rdp_fill_decal_cycles',0)/rdp_cpm:.2f}ms "
          f"copy={m.get('rdp_fill_copy_cycles',0)/rdp_cpm:.2f}ms]  "
          f"page_miss={m.get('rdp_page_miss_cycles',0)/rdp_cpm:.2f}ms ({m.get('rdp_rdram_page_misses',0):.0f})  "
          f"tmem={m.get('rdp_tmem_cycles',0)/rdp_cpm:.2f}ms ({m.get('rdp_tmem_loads',0):.0f})  "
          f"sync={m.get('rdp_sync_cycles',0)/rdp_cpm:.2f}ms  "
          f"bus_cont={m.get('rdp_bus_contention_cycles',0)/rdp_cpm:.2f}ms  "
          f"z_rej={z_pct:.1f}%  tris={m.get('rdp_triangles',0):.0f}")
    c_addr, z_addr = m.get("rdp_color_addr", 0), m.get("rdp_z_addr", 0)
    if c_addr or z_addr:
        print(f"  RDRAM buffers: color=0x{c_addr:06x} (bank {(c_addr >> 20) & 3})  Z=0x{z_addr:06x} (bank {(z_addr >> 20) & 3})")
    cfg = cfg or config()
    max_coh = _max_coherence_errors(cfg, frames)
    max_syn = int(cfg.get("hardware", {}).get("max_kseg1_dirty_synonyms", 0))
    coh = m.get("dcache_coherence_errors", 0)
    uc = m.get("cache_uncached_ops", 0)
    ua = m.get("cache_cde_unaligned_ops", 0)
    syn = m.get("cache_kseg1_dirty_synonyms", 0)
    coh_bad = (max_coh is not None and coh > max_coh)
    if coh_bad or uc or ua or syn > max_syn:
        print(f"  WARNING hardware hazards: dcache_coherence_errors={coh}"
              f"{f'/{max_coh}' if max_coh is not None else ''}  "
              f"cache_uncached_ops={uc}  cache_cde_unaligned_ops={ua}  kseg1_dirty_synonyms={syn}")
    print()
    for label, key in detail:
        b = base.get(key)
        ratio = f"{m[key] / b:8.3f}" if b else ""
        sp = f"{b / m[key]:7.2f}x" if (b and m[key]) else ""
        print(f"{label:30s} {m[key]:14.1f} {b if b is not None else float('nan'):14.1f} {ratio} {sp}")
    print("* footprint: yours over this run, baseline over its full run")
    print(f"  VI fields/frame: {result['vi_fields'] / frames:.2f}")
    print("\nRDRAM bytes / frame by device:")
    for dev, v in m["rdram_bytes_by_device"].items():
        if v:
            print(f"  {dev:18s} {v:12.0f}")


def _run_one_n64(rom, w_id, rpath, out_dir, frames, iargs, profile_path=None):
    max_fields = max(1800, int(frames) * 18 + 600)
    wall_timeout = min(300, max(90, int(frames) * 2))
    cmd = ["n64run", "--rom", str(rom), "--replay", str(rpath),
           "--out", str(out_dir), "--frames", str(frames), "--max-fields", str(max_fields)]
    cmd += iargs
    if profile_path is not None:
        cmd += ["--profile", str(profile_path)]
    try:
        r = sh(cmd, stderr=subprocess.PIPE, text=True, timeout=wall_timeout)
        stderr_text = r.stderr or ""
        rc = r.returncode
    except subprocess.TimeoutExpired as exc:
        stderr_text = (exc.stderr.decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or ""))
        print(f"ERROR: n64run timed out after {wall_timeout}s on {w_id} (likely boot/frame hang)", file=sys.stderr)
        rc = 124

    skip_block = 0
    rdram_coh_shown = 0
    rdram_coh_suppressed = 0
    for line in stderr_text.splitlines():
        if "Stalled compile" in line:
            continue
        # Suppress repetitive ares RSP DMEM coherence debug spam (e.g. stock F3DEX2
        # reading 1 scratch word/frame); actual counts are surfaced in hardware gates.
        if "reading from DMEM address 0x" in line and "not cache coherent" in line:
            skip_block = 3
            continue
        if "reading from RDRAM address 0x" in line and "not cache coherent" in line:
            if rdram_coh_shown < 3:
                rdram_coh_shown += 1
                print(line, file=sys.stderr)
            else:
                rdram_coh_suppressed += 1
                skip_block = 3
            continue
        if skip_block > 0 and line.startswith("\t"):
            skip_block -= 1
            continue
        skip_block = 0
        print(line, file=sys.stderr)
    if rdram_coh_suppressed > 0:
        print(
            f"NOTE: suppressed {rdram_coh_suppressed} additional RDRAM D-cache coherence warnings on {w_id}. "
            "Vanilla SM64 has 0 RDRAM coherence errors — non-zero errors mean dirty CPU D-cache lines "
            "(display lists, matrices, vertices, or audio buffers, not just struct SPTask) were not written back before SP/DP DMA.",
            file=sys.stderr,
        )
    return rc


def run_all_workloads(args):
    _prune_old_temps()
    cfg = config()
    rom = build(quiet_stdout=True)
    frames = args.frames or cfg["frames"]
    if frames < 2:
        sys.exit("--frames must be >= 2")
    iargs = idle_args(cfg)
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-all-"))
    pub_wls = [w for w in cfg["workloads"] if w.get("split", "public") == "public"]
    jobs = min(len(pub_wls), max(1, int(os.environ.get("MEV_JOBS") or os.cpu_count() or 8)))

    def _go(w):
        wid = w["id"]
        wdir = out / wid
        _run_one_n64(rom, wid, CORPUS / w["replay"], wdir, frames, iargs)
        return wid, _load_metrics_and_base(wdir, wid)

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = dict(pool.map(_go, pub_wls))

    if args.json:
        payload = {
            "frames": frames,
            "workloads": {wid: {"metrics": m, "baseline": b} for wid, (_res, _rd, m, b) in results.items()},
        }
        print(json.dumps(payload, indent=1))
        return

    if frames != cfg["frames"]:
        print(f"NOTE: {frames}-frame quick run — compare only against {frames}-frame runs (`mev check` grades {cfg['frames']} frames).")
    print(f"All public workloads ({frames} frames; bn = dominant bottleneck; rsp_g/rsp_a = Gfx/Audio RSP ms):")
    print(f"  {'course':8s} {'console':>8s} {'p99':>8s} {'cpu':>8s} {'rsp':>8s} {'rsp_g':>7s} {'rsp_a':>7s} {'rdp':>8s} {'mem':>8s} {'bn':>6s} {'speedup':>8s}")
    ratios = []
    for w in pub_wls:
        wid = w["id"]
        _res, _rd, m, b = results[wid]
        bn_map = m.get("bottleneck_share", {})
        bn = max(bn_map, key=bn_map.get) if bn_map else "-"
        ratio = m["est_console_ms"] / b["est_console_ms"] if b.get("est_console_ms") else 1.0
        ratios.append(ratio)
        print(f"  {wid:8s} {m['est_console_ms']:8.2f} {m['est_console_p99_ms']:8.2f}"
              f" {m['cpu_ms']:8.2f} {m['rsp_ms']:8.2f} {m.get('rsp_gfx_ms', 0.0):7.2f} {m.get('rsp_aud_ms', 0.0):7.2f}"
              f" {m['rdp_ms']:8.2f} {m['mem_ms']:8.2f} {bn:>6s} {1.0 / ratio:7.3f}x")
    geo = math.exp(sum(math.log(max(r, 1e-12)) for r in ratios) / len(ratios))
    print(f"\n  geomean console speedup ({frames}f): {1.0 / geo:.4f}x   raw output: {out}")
    print_time_remaining()


def run(args, profile=False):
    if not profile and getattr(args, "top", 0):
        print("NOTE: `--top` is a `mev profile` option; running `mev profile` so per-function symbol tables are included.", file=sys.stderr)
        profile = True
    if not profile and getattr(args, "all", False):
        if args.workload:
            sys.exit("cannot combine a workload ID with --all")
        run_all_workloads(args)
        return
    if not args.workload:
        sys.exit("specify a workload ID (e.g. `mev run jrb`) or `--all`")
    if args.frames and args.frames < 2:
        sys.exit("--frames must be >= 2")
    _prune_old_temps()
    cfg = config()
    rom = build(quiet_stdout=True)
    frames = args.frames or cfg["frames"]
    out = pathlib.Path(tempfile.mkdtemp(prefix=f"mev-{args.workload}-"))
    iranges = idle_range_list(cfg)
    iargs = []
    for r in iranges:
        iargs += ["--idle-range", r]
    samples_path = (out / "samples.txt") if profile else None
    _run_one_n64(rom, args.workload, replay(args.workload), out / "run", frames, iargs, profile_path=samples_path)

    if profile:
        top_n = getattr(args, "top", 25) or 25
        elf = find_elf(cfg)
        if elf:
            nm = out / "nm.txt"
            nm.write_text(subprocess.run(["mips64-elf-nm", "-n", "-S", "--defined-only", str(elf)],
                                         capture_output=True, text=True).stdout)
            symbolize = "/opt/mario-eval/tools/symbolize.py"
            samples = out / "samples.txt"
            sample_frames = max(1, frames - 1)
            # 1. CPU time by function (excluding idle range from busy denominator)
            if samples.exists() and samples.stat().st_size:
                print(f"CPU busy time by function ({sample_frames} frames, sampled, cache & uncached stalls included):", flush=True)
                cmd = [sys.executable, symbolize, str(samples), str(nm),
                       "--top", str(top_n), "--frames", str(sample_frames), "--with-sizes"]
                for r in iranges:
                    cmd += ["--exclude-range", r]
                sh(cmd)
                print(flush=True)
            sections = [
                (pathlib.Path(str(samples) + ".dmiss"), f"D-cache misses by faulting PC ({sample_frames} frames)", False),
                (pathlib.Path(str(samples) + ".dmissaddr"), f"D-cache misses by data symbol / missed line ({sample_frames} frames)", True),
                (pathlib.Path(str(samples) + ".imiss"), f"I-cache misses by function ({sample_frames} frames)", False),
                (pathlib.Path(str(samples) + ".wb"), f"D-cache writebacks by last writer PC ({sample_frames} frames)", False),
                (pathlib.Path(str(samples) + ".wb"), f"D-cache writebacks by data symbol ({sample_frames} frames)", True),
            ]
            for path, title, by_data in sections:
                if not path.exists() or not path.stat().st_size:
                    continue
                print(title + ":", flush=True)
                cmd = [sys.executable, symbolize, str(path), str(nm),
                       "--top", str(top_n), "--frames", str(sample_frames), "--with-sizes"]
                if by_data:
                    cmd.append("--by-data-symbol")
                sh(cmd)
                print(flush=True)
            imiss = pathlib.Path(str(samples) + ".imiss")
            if imiss.exists() and imiss.stat().st_size:
                print("Top 16 KB I-cache set conflict pairs (same addr mod 0x4000):", flush=True)
                sh([sys.executable, symbolize, str(imiss), str(nm), "--icache-conflicts", "--top", "12"])
                print(flush=True)
    summarize(out / "run", args.workload, full_frames=cfg["frames"], as_json=getattr(args, "json", False), cfg=cfg)
    if not getattr(args, "json", False):
        print(f"\nraw output: {out}/run  (frames.jsonl, video.bin, audio.bin, obs.bin)")
        if profile:
            print(f"profile files: {out}/samples.txt{{,.dmiss,.dmissaddr,.imiss,.wb}}")
        print_time_remaining()


def check(args):
    _prune_old_temps()
    _clean_make_env()
    cfg = config()
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-check-"))
    is_subset = bool(args.workloads)
    partial = is_subset or bool(args.fast)
    prev_summary = None
    last_link = pathlib.Path("/tmp/mev-last-check/summary.json")
    if last_link.is_file():
        try:
            prev_summary = json.loads(last_link.read_text())
        except Exception:
            prev_summary = None

    if args.play_smoke and args.fast:
        sys.exit("--play-smoke cannot be combined with --fast (needs a clean PLAY=1 ROM build)")
    do_play_smoke = bool(cfg.get("play_rom")) and not args.fast and not args.no_play_smoke and (args.play_smoke or not is_subset)

    cmd = [sys.executable, "-m", "grader.grade", "grade", str(GAME), "--corpus", str(CORPUS),
           "--cache", str(CACHE), "--out", str(out)]
    handoff = None
    try:
        if args.fast:
            rom = build(quiet_stdout=True, clear_last_check_on_fail=(not is_subset))
            elf = find_elf(cfg)
            sys.path.insert(0, "/opt/mario-eval")
            from grader.grade import idle_ranges, inspect_elf_metadata, verify_elf_harness
            if cfg.get("elf") and elf:
                elf_err = verify_elf_harness(elf, cfg, src_root=GAME)
                if elf_err:
                    if not is_subset:
                        pathlib.Path("/tmp/mev-last-check").unlink(missing_ok=True)
                    sys.exit(f"fast check aborted: {elf_err}")
            handoff = pathlib.Path(tempfile.mkdtemp(prefix="mev-fast-handoff-"))
            shutil.copy2(rom, handoff / "built.z64")
            idle = idle_ranges(elf, cfg.get("idle_symbols", [])) if (elf and cfg.get("idle_symbols")) else []
            (handoff / "built.idle.json").write_text(json.dumps(idle))
            if elf:
                (handoff / "built.meta.json").write_text(json.dumps(inspect_elf_metadata(elf, src_root=GAME, cfg=cfg)))
            cmd += ["--built", str(handoff)]
        if args.workloads:
            cmd += ["--workloads", ",".join(args.workloads)]
        if do_play_smoke:
            cmd += ["--play-smoke"]
        r = sh(cmd, cwd="/opt/mario-eval", stdout=subprocess.PIPE, text=True)
    finally:
        if handoff is not None:
            shutil.rmtree(handoff, ignore_errors=True)

    summary_path = out / "summary.json"
    s = None
    if summary_path.exists():
        try:
            s = json.loads(summary_path.read_text())
        except Exception:
            s = None
    primary = "console"
    prof_file = pathlib.Path("/task/PROFILE")
    if prof_file.is_file():
        primary = prof_file.read_text().strip() or "console"

    check_ok = False
    if s is not None:
        pinfo_top = s.get("profiles", {}).get(primary)
        check_ok = (
            s.get("status") == "valid"
            and isinstance(pinfo_top, dict)
            and bool(pinfo_top.get("valid"))
        )
    if not is_subset and check_ok:
        last_dir_link = pathlib.Path("/tmp/mev-last-check")
        tmp_link = pathlib.Path(f"/tmp/.mev-last-check.{os.getpid()}")
        try:
            tmp_link.unlink(missing_ok=True)
            tmp_link.symlink_to(out)
            tmp_link.replace(last_dir_link)
        except OSError:
            pass

    if s is not None:
        try:
            git_dirty = bool(subprocess.run(
                ["git", "-C", str(GAME), "status", "--porcelain"],
                capture_output=True, text=True,
            ).stdout.strip())
            if not is_subset:
                head = subprocess.run(["git", "-C", str(GAME), "rev-parse", "--short", "HEAD"],
                                      capture_output=True, text=True).stdout.strip()
                rec = {
                    "ts": round(time.time(), 2),
                    "git_head": head,
                    "git_dirty": git_dirty,
                    "rom_sha256": (s.get("rom_sha256") or "")[:12],
                    "fast": bool(args.fast),
                    "status": s.get("status"),
                    "profile_valid": check_ok,
                    "reason": s.get("reason"),
                    "rewards": s.get("rewards", {}),
                    "speedups": s.get("speedups", {}),
                    "cost_saved": s.get("cost_saved", {}),
                    "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in s.get("profiles", {}).items()},
                    **({"fidelity": s["fidelity"]} if s.get("fidelity") else {}),
                    **({"failure_attribution": s["failure_attribution"]} if s.get("failure_attribution") else {}),
                }
                with open("/task/.mev-history.jsonl", "a") as hf:
                    hf.write(json.dumps(rec) + "\n")

            pinfo = s.get("profiles", {}).get(primary)
            fid = s.get("fidelity") or {}
            if s.get("status") == "valid" and isinstance(pinfo, dict):
                if pinfo.get("valid"):
                    vo2 = pinfo.get("vs_o2_speedup")
                    vo2_s = f"  vs_o2={vo2:.4f}x" if vo2 is not None else ""
                    cs_s = f"  cost_saved={100.0 * pinfo.get('cost_saved', 0):.2f}%" if "cost_saved" in pinfo else ""
                    ssim_s = f"  ssim={fid['video_ssim']:.4f}" if "video_ssim" in fid else ""
                    print(f"Primary profile [{primary}]: PASS  speedup={pinfo.get('speedup', 0):.4f}x{vo2_s}{cs_s}  reward={pinfo.get('reward', 0):+.6f}{ssim_s}")
                    if git_dirty and not partial:
                        print("  NOTE: working tree has uncommitted changes — `git commit` verified milestones so host checkpoints capture them.")
                else:
                    print(f"Primary profile [{primary}]: FAIL  ({pinfo.get('reason', 'budget exceeded')})")
            else:
                reason = s.get("reason") or "failed"
                fid_s = f"  (fidelity={fid.get('overall', 0):.4f}, ssim={fid.get('video_ssim', 0):.4f})" if fid else ""
                print(f"Status: {s.get('status', 'invalid').upper()}  ({reason}){fid_s}")

            if not s.get("gates", {}).get("build", {}).get("pass", True):
                blog = out / "build.log"
                if blog.is_file():
                    lines = blog.read_text(errors="replace").splitlines()
                    err_lines = [l for l in lines if "error:" in l or "fatal error:" in l or "undefined reference" in l]
                    tail = lines[-40:]
                    print(f"\nBuild error tail ({blog}):")
                    if err_lines and len(err_lines) <= 20:
                        for l in err_lines:
                            print("  " + l)
                        print("  --- last 15 lines ---")
                        for l in tail[-15:]:
                            print("  " + l)
                    else:
                        for l in tail:
                            print("  " + l)

            wls = s.get("workloads", {})
            vid_wls = s.get("gates", {}).get("video", {}).get("workloads", {})
            hw_wls = s.get("gates", {}).get("hardware", {}).get("workloads", {})
            prev_wls = (prev_summary or {}).get("workloads", {})
            if wls:
                print("\nPer-course breakdown (ms; bn = bottleneck; vid% = worst pixel diff; ssim = block-SSIM; Δcon vs last check):")
                print(f"  {'course':8s} {'console':>8s} {'p99':>8s} {'cpu':>8s} {'rsp':>8s} {'rdp':>8s} {'mem':>8s} {'bn':>5s} {'speedup':>8s} {'Δcon':>7s} {'vid%':>7s} {'ssim':>6s} {'varF':>5s}")
                for wid, w in wls.items():
                    m = w.get("metrics", {})
                    bn_map = m.get("bottleneck_share", {})
                    bn = max(bn_map, key=bn_map.get) if bn_map else "-"
                    ratio = w.get("ratios", {}).get("est_console_ms", 0)
                    sp = f"{1.0 / ratio:7.3f}x" if ratio else "     n/a"
                    prev_ms = prev_wls.get(wid, {}).get("metrics", {}).get("est_console_ms")
                    cur_ms = m.get("est_console_ms", 0)
                    dcon = f"{100.0 * (cur_ms - prev_ms) / prev_ms:+6.2f}%" if prev_ms else "      -"
                    vw = vid_wls.get(wid, {})
                    vfrac = 100.0 * float(vw.get("worst_bad_fraction", 0.0))
                    vstr = f"{vfrac:6.3f}%" if vfrac > 0 else " 0.000%"
                    sval = vw.get("ssim_score")
                    sstr = f"{float(sval):6.4f}" if sval is not None else "     -"
                    varf = int(vw.get("variant_frames", 0))
                    print(f"  {wid:8s} {cur_ms:8.2f} {m.get('est_console_p99_ms', 0):8.2f}"
                          f" {m.get('cpu_ms', 0):8.2f} {m.get('rsp_ms', 0):8.2f} {m.get('rdp_ms', 0):8.2f}"
                          f" {m.get('mem_ms', 0):8.2f} {bn:>5s} {sp} {dcon} {vstr} {sstr} {varf:5d}")
                drift_wls = [(wid, 100.0 * float(vw.get("worst_bad_fraction", 0.0)))
                             for wid, vw in vid_wls.items() if float(vw.get("worst_bad_fraction", 0.0)) > 0.0002]
                if drift_wls:
                    notes = ", ".join(f"{wid}={pct:.3f}%" for wid, pct in drift_wls)
                    lim_pct = 100.0 * float(cfg.get("video", {}).get("max_bad_fraction", 0.0035))
                    print(f"  NOTE: non-zero pixel drift detected ({notes}; limit {lim_pct:.3f}%) — verify held-out safety before committing!")
                hazards = []
                for wid, hw in hw_wls.items():
                    max_coh = hw.get("max_dcache_coherence_errors")
                    max_syn = int(hw.get("max_kseg1_dirty_synonyms", 0))
                    coh = int(hw.get("dcache_coherence_errors", 0))
                    rcoh = int(hw.get("rdram_dma_coherence_errors", 0))
                    oob = int(hw.get("oob_rdram_accesses", 0))
                    uc = int(hw.get("cache_uncached_ops", 0))
                    ua = int(hw.get("cache_cde_unaligned_ops", 0))
                    syn = int(hw.get("cache_kseg1_dirty_synonyms", 0))
                    if (max_coh is not None and coh > max_coh) or rcoh > 0 or oob > 0 or uc or ua or syn > max_syn or not hw.get("pass", True):
                        hazards.append((wid, coh, max_coh, rcoh, oob, uc, ua, syn))
                if hazards:
                    hstr = ", ".join(
                        f"{w}(coh={c}{f'/{mc}' if mc is not None else ''},rdram_coh={rc},oob={ob},kseg1_cache={u},cde_unaligned={a},kseg1_syn={sn})"
                        for w, c, mc, rc, ob, u, a, sn in hazards
                    )
                    print(f"  WARNING hardware hazards: {hstr}")

            if s.get("status") == "valid" and s.get("profiles"):
                diag_parts = []
                for k, v in s["profiles"].items():
                    if k == primary:
                        continue
                    if v.get("valid"):
                        diag_parts.append(f"{k}={v.get('speedup', 0):.3f}x")
                    else:
                        diag_parts.append(f"{k}=over-budget")
                if diag_parts:
                    print("Diagnostic profiles (non-scoring, do NOT affect primary): " + "  ".join(diag_parts))

            if s.get("status") != "valid":
                elf_sym = find_elf(cfg)
                for gname, gval in s.get("gates", {}).items():
                    if not gval.get("pass", True):
                        if "workloads" not in gval:
                            print(f"\nFailed gate [{gname}]: {json.dumps({k: v for k, v in gval.items() if k != 'pass'})}")
                            continue
                        bad = [(wk, wv) for wk, wv in gval.get("workloads", {}).items() if not wv.get("pass", True)]
                        if bad:
                            print(f"\nFailed gate [{gname}]:")
                            for wk, wv in bad[:6]:
                                wv_disp = dict(wv)
                                if "first_fault_pc" in wv_disp and elf_sym:
                                    wv_disp["first_fault_pc"] = _symbolize_pc(elf_sym, wv_disp["first_fault_pc"])
                                print(f"  {wk}: {json.dumps(wv_disp)}")
        except Exception as exc:
            if r.stdout:
                print(r.stdout, end="")
            print(f"warning: failed to format summary: {exc}", file=sys.stderr)
    elif r.stdout:
        print(r.stdout, end="")

    if partial:
        print(f"\npartial/fast report: {summary_path}  (run plain `mev check` for full clean + PLAY=1 + boot-smoke verification)")
    else:
        print(f"\nfull report: {summary_path} (symlink: /tmp/mev-last-check/summary.json)")
    print_time_remaining()
    sys.exit(r.returncode if r.returncode != 0 else (0 if check_ok else 1))


def _baseline_idle_args():
    b_idle = CACHE / "baseline.idle.json"
    if not b_idle.is_file():
        return []
    out = []
    for r in json.loads(b_idle.read_text()):
        out += ["--idle-range", r]
    return out


def _max_interior_video_diff(cand_video_path, ref_video_path, frames, cfg, tol=5):
    """Max fraction of 3x3-interior pixels differing by > `tol`/31 against baseline.z64.
    Accepted microcode/AA/LOD variants (F3DEX2, RA_ZB_OPA, full-detail, no-lod, rr-statics)
    only shift 1-2px silhouette edges or <=3/31 Gouraud shading (<= 0.08% across 6,240 frames),
    whereas culled/missing translucent or opaque geometry produces contiguous >0.25% interior blocks."""
    import numpy as np
    from grader.grade import decode_frame
    vcfg = cfg.get("video", {})
    w = int(vcfg.get("width", 320))
    h = int(vcfg.get("height", 240))
    bpp = int(vcfg.get("bpp", 16))
    c_raw = cand_video_path.read_bytes()
    r_raw = ref_video_path.read_bytes()
    if not c_raw or not r_raw or frames <= 0:
        return 0.0, -1
    fb = w * h * max(1, bpp // 8)
    nf = min(frames, len(c_raw) // fb, len(r_raw) // fb)
    worst = 0.0
    worst_f = -1
    for i in range(nf):
        cf = decode_frame(c_raw[i * fb:(i + 1) * fb], w, h, bpp)
        rf = decode_frame(r_raw[i * fb:(i + 1) * fb], w, h, bpp)
        m = np.abs(cf.astype(np.int16) - rf.astype(np.int16)).max(axis=-1) > tol
        if float(m.mean()) <= worst:
            continue
        er = m[1:-1, 1:-1].copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                if dx or dy:
                    er &= m[1 + dy:h - 1 + dy, 1 + dx:w - 1 + dx]
        ef = float(er.mean())
        if ef > worst:
            worst = ef
            worst_f = i
    return worst, worst_f


def _eval_differential_pair(label, cand_dir, base_dir, frames, cfg, elf_sym=None):
    """Compare candidate run in cand_dir against baseline.z64 run in base_dir."""
    import zlib
    sys.path.insert(0, "/opt/mario-eval")
    from grader.grade import compare_audio, compare_obs, compare_video, load_run, metrics

    c_res = json.loads((cand_dir / "result.json").read_text()) if (cand_dir / "result.json").is_file() else {"status": "missing"}
    b_res = json.loads((base_dir / "result.json").read_text()) if (base_dir / "result.json").is_file() else {"status": "missing"}
    if b_res.get("status") != "completed":
        return {"pass": False, "label": label, "reason": f"baseline did not complete ({b_res.get('status')})"}

    ex_ok = (
        c_res.get("status") == "completed"
        and int(c_res.get("frames", 0)) == frames
        and int(c_res.get("cpu_fault_exceptions", 0)) == 0
        and int(c_res.get("cpu_trap_exceptions", 0)) == 0
    )
    fault_str = ""
    if c_res.get("first_fault_exc"):
        pc_s = _symbolize_pc(elf_sym, c_res.get("first_fault_pc"))
        fault_str = f"{c_res['first_fault_exc']}@{pc_s}"
    if not ex_ok:
        return {
            "pass": False, "label": label, "status": c_res.get("status", "error"),
            "reason": fault_str or f"status={c_res.get('status')} frames={c_res.get('frames', 0)}/{frames}",
        }

    cand = load_run(cand_dir)
    ref = load_run(base_dir)
    m = metrics(cand)
    base_m = metrics(ref)

    hw_cfg = cfg.get("hardware", {})
    limit_ram = int(hw_cfg.get("rdram_bytes", 4194304))
    max_oob = int(hw_cfg.get("max_oob_rdram_accesses", 0))
    max_rdram_coh = int(hw_cfg.get("max_rdram_dma_coherence_errors", 0))
    max_coh = _max_coherence_errors(cfg, frames)
    max_syn = int(hw_cfg.get("max_kseg1_dirty_synonyms", 0))
    hi = m["highest_byte"]
    oob = int(m.get("oob_rdram_accesses", 0))
    rcoh = int(m.get("rdram_dma_coherence_errors", 0))
    coh = int(m.get("dcache_coherence_errors", 0))
    uc = int(m.get("cache_uncached_ops", 0))
    ua = int(m.get("cache_cde_unaligned_ops", 0))
    syn = int(m.get("cache_kseg1_dirty_synonyms", 0))
    hw_ok = (
        hi <= limit_ram and oob <= max_oob and rcoh <= max_rdram_coh
        and (max_coh is None or coh <= max_coh)
        and uc == 0 and ua == 0 and syn <= max_syn
    )

    gp_cfg = cfg
    # On Rainbow Ride (LEVEL_RR = 15), accepted `rr-statics` bakes 14 yaw-0 decoration objects into static DLs.
    if len(ref["obs"]) >= 8:
        lvl_hi = (int.from_bytes(ref["obs"][4:8], "big") >> 16) & 0xFFFF
        if lvl_hi == 15:
            r_ac = int.from_bytes(ref["obs"][31 * 4:32 * 4], "big")
            c_ac = int.from_bytes(cand["obs"][31 * 4:32 * 4], "big") if len(cand["obs"]) >= 128 else -1
            if r_ac - c_ac == 14:
                exact_no_ac = [f for f in cfg.get("gameplay", {}).get("exact_fields", []) if f != "actor_count"]
                gp_cfg = {**cfg, "gameplay": {**cfg.get("gameplay", {}), "exact_fields": exact_no_ac, "actor_tolerance": None}}
    gp = compare_obs(ref["obs"], cand["obs"], frames, cfg.get("contract", "sm64"), gp_cfg)

    ref_vid_z = base_dir / "video.bin.z"
    if not ref_vid_z.is_file():
        ref_vid_z.write_bytes(zlib.compress((base_dir / "video.bin").read_bytes(), 1))
    vd = compare_video(base_dir, {}, cand["video_path"], ref["rows"], cand["rows"], cfg)
    # Custom/stress replays do not have precomputed variant videos (f3dex2, no-lod, rr-statics),
    # so accept high structural block-SSIM (>= 0.90, worst >= 0.78) ONLY when contiguous 3x3-interior
    # >5/31 pixel error stays within the variant envelope (<= 0.25%; catches culled/missing geometry).
    ssim = float(vd.get("ssim_score", 0.0))
    wssim = float(vd.get("worst_ssim_frame_score", 0.0))
    int_bad, int_frame = (0.0, -1)
    if not bool(vd.get("pass")):
        int_bad, int_frame = _max_interior_video_diff(cand["video_path"], base_dir / "video.bin", frames, cfg, tol=5)
    vd_ok = bool(vd.get("pass")) or (ssim >= 0.90 and wssim >= 0.78 and int_bad <= 0.0025)

    au = compare_audio(ref["audio"], cand["audio"], ref["rows"], cand["rows"], cfg)
    au_ok = bool(au.get("pass"))

    for d in (cand_dir, base_dir):
        for fn in ("video.bin", "video.bin.z", "obs.bin", "audio.bin"):
            (d / fn).unlink(missing_ok=True)

    sp = (base_m["est_console_ms"] / m["est_console_ms"]) if m.get("est_console_ms") else 0.0
    reasons = []
    if not hw_ok:
        reasons.append(f"hw(ram={hi // 1024}KiB,oob={oob},rdram_coh={rcoh},coh={coh},syn={syn})")
    if not gp.get("pass"):
        reasons.append(f"gameplay(f={gp.get('frame')},{gp.get('field')})")
    if not vd_ok:
        if int_bad > 0.0025:
            reasons.append(f"video(missing/corrupt interior geometry: {100*int_bad:.2f}% 3x3 px >5/31 at frame {int_frame}, limit 0.25%; ssim={ssim:.4f})")
        else:
            reasons.append(f"video(ssim={ssim:.4f},bad={100*vd.get('worst_bad_fraction',0):.2f}%)")
    if not au_ok:
        au_desc = au.get("reason") or f"snr={au.get('snr_db')}"
        reasons.append(f"audio({au_desc})")
    return {
        "pass": hw_ok and bool(gp.get("pass")) and vd_ok and au_ok,
        "label": label,
        "speedup": sp,
        "cand_ms": m["est_console_ms"],
        "base_ms": base_m["est_console_ms"],
        "max_ram_kib": hi / 1024.0,
        "oob": oob,
        "rdram_coh": rcoh,
        "sp_coh": int(m.get("sp_dmem_coherence_errors", 0)),
        "vid_pct": 100.0 * float(vd.get("worst_bad_fraction", 0.0)),
        "ssim": ssim,
        "strict_orig_vid": bool(vd.get("pass")),
        "gp": gp,
        "vd": vd,
        "au": au,
        "hw_ok": hw_ok,
        "reasons": reasons,
    }


def diff_replay(args):
    """Run any custom controller replay file against /task/game and baseline.z64."""
    _prune_old_temps()
    rpath = pathlib.Path(args.replay)
    if not rpath.is_file():
        sys.exit(f"replay file not found: {rpath}")
    base_rom = CACHE / "baseline.z64"
    if not base_rom.is_file():
        sys.exit(f"baseline reference ROM missing at {base_rom}")
    cfg = config()
    frames = args.frames or cfg["frames"]
    if frames < 2:
        sys.exit("--frames must be >= 2")
    rom = build(quiet_stdout=True)
    elf_sym = find_elf(cfg)
    c_iargs = idle_args(cfg)
    b_iargs = _baseline_idle_args()
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-diff-"))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            fc = pool.submit(_run_one_n64, rom, "cand", rpath, out / "cand", frames, c_iargs)
            fb = pool.submit(_run_one_n64, base_rom, "baseline", rpath, out / "base", frames, b_iargs)
            fc.result()
            fb.result()
        ev = _eval_differential_pair(rpath.name, out / "cand", out / "base", frames, cfg, elf_sym=elf_sym)
    finally:
        shutil.rmtree(out, ignore_errors=True)

    tag = "PASS" if ev["pass"] else "FAIL"
    if "cand_ms" not in ev:
        print(f"[{tag}] {rpath}: {ev.get('reason', 'execution failed')}")
        print_time_remaining()
        sys.exit(1)
    vnote = "" if ev["strict_orig_vid"] else " (variant-tolerant SSIM check; un-precomputed replay)"
    print(f"[{tag}] {rpath} ({frames} frames): console {ev['base_ms']:.2f}ms -> {ev['cand_ms']:.2f}ms ({ev['speedup']:.3f}x)")
    print(f"  gates: hw={'PASS' if ev['hw_ok'] else 'FAIL'} (ram={ev['max_ram_kib']:.0f}KiB, oob={ev['oob']}, rdram_coh={ev['rdram_coh']})"
          f"  gameplay={'PASS' if ev['gp'].get('pass') else 'FAIL'}"
          f"  video={'PASS' if not any(r.startswith('video') for r in ev['reasons']) else 'FAIL'} (bad={ev['vid_pct']:.3f}%, ssim={ev['ssim']:.4f}){vnote}"
          f"  audio={'PASS' if ev['au'].get('pass') else 'FAIL'}")
    if ev["reasons"]:
        print("  failures: " + ", ".join(ev["reasons"]))
    print_time_remaining()
    sys.exit(0 if ev["pass"] else 1)


def _encode_sm64_boot_pad(level_id, act=1):
    btn = ["S"]
    for bit, ch in ((1, "6"), (2, "4"), (4, "2"), (8, "8"), (16, "B"), (32, "A")):
        if level_id & bit:
            btn.append(ch)
    act_bits = max(0, min(5, act - 1))
    for bit, ch in ((1, "Z"), (2, "L"), (4, "u")):
        if act_bits & bit:
            btn.append(ch)
    return "".join(btn)


_ALL_SM64_COURSES = (
    ("bbh", 4), ("ccm", 5), ("hmc", 7), ("ssl", 8), ("bob", 9),
    ("sl", 10), ("wdw", 11), ("jrb", 12), ("thi", 13), ("ttc", 14),
    ("rr", 15), ("bitdw", 17), ("bitfs", 19), ("bits", 21),
    ("lll", 22), ("ddd", 23), ("wf", 24), ("ttm", 36),
)


def stress(args):
    """Run seeded random-input differential stress replays across SM64 courses against baseline.z64."""
    _prune_old_temps()
    cfg = config()
    frames = args.frames or cfg["frames"]
    if frames < 2:
        sys.exit("--frames must be >= 2")
    rom = build(quiet_stdout=True)
    elf_sym = find_elf(cfg)
    c_iargs = idle_args(cfg)
    b_iargs = _baseline_idle_args()
    base_rom = CACHE / "baseline.z64"
    has_base = base_rom.is_file()
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-stress-"))
    pub_wls = [w for w in cfg["workloads"] if w.get("split", "public") == "public"]
    rng = random.Random(args.seed)
    # Never press START ('S') after frame 0 so the pause menu cannot soft-stall courses.
    buttons_pool = [".", "A", "B", "Z", "AZ", "BZ", "8", "2", "4", "6", "A4", "A6", "R"]

    if getattr(args, "all_courses", False):
        course_targets = [(cname, f"{_encode_sm64_boot_pad(lid, 1)} 0 0", lid in (14, 15, 17, 19, 21, 22, 36))
                          for cname, lid in _ALL_SM64_COURSES]
    else:
        course_targets = []
        for w in pub_wls:
            orig_lines = [l for l in (CORPUS / w["replay"]).read_text().splitlines() if l.strip() and not l.startswith("#")]
            course_targets.append((w["id"], orig_lines[0] if orig_lines else ". 0 0", w["id"] in ("bitfs", "rr")))

    items = []
    for wid, f0_line, narrow in course_targets:
        lines = [f0_line]
        cur_btn, cur_x, cur_y, hold = ".", 0, 0, 0
        ang = rng.uniform(0.0, 2.0 * math.pi)
        for _ in range(1, frames):
            if hold <= 0:
                if narrow:
                    cur_btn = rng.choice([".", "A", "Z", "8", "2", "4", "6"])
                    ang = (ang + math.pi + rng.uniform(-0.45, 0.45)) % (2.0 * math.pi)
                    mag = rng.choice((24, 34, 44))
                    cur_x, cur_y = int(round(mag * math.sin(ang))), int(round(mag * math.cos(ang)))
                    hold = rng.randint(3, 6)
                else:
                    cur_btn = rng.choice(buttons_pool)
                    cur_x = rng.randint(-80, 80)
                    cur_y = rng.randint(-80, 80)
                    hold = rng.randint(4, 14)
            lines.append(f"{cur_btn} {cur_x} {cur_y}")
            hold -= 1
        rpath = out / f"stress-{wid}.txt"
        rpath.write_text("\n".join(lines) + "\n")
        items.append((wid, rpath))

    try:
        jobs = min(len(items) * (2 if has_base else 1), max(1, int(os.environ.get("MEV_JOBS") or os.cpu_count() or 8)))
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
            futs = {}
            for wid, rpath in items:
                futs[("c", wid)] = pool.submit(_run_one_n64, rom, wid, rpath, out / wid / "cand", frames, c_iargs)
                if has_base:
                    futs[("b", wid)] = pool.submit(_run_one_n64, base_rom, f"base-{wid}", rpath, out / wid / "base", frames, b_iargs)
            for f in futs.values():
                f.result()

        ok = True
        print(f"Differential button-mash stress test (seed={args.seed}, {frames} frames across {len(items)} courses):")
        for wid, _rpath in items:
            if has_base:
                ev = _eval_differential_pair(wid, out / wid / "cand", out / wid / "base", frames, cfg, elf_sym=elf_sym)
                if not ev["pass"]:
                    ok = False
                tag = "PASS" if ev["pass"] else "FAIL"
                if "cand_ms" not in ev:
                    print(f"  [{tag}] {wid:8s} {ev.get('reason', 'failed')}")
                else:
                    fail_s = ("  FAIL: " + ", ".join(ev["reasons"])) if ev["reasons"] else ""
                    print(f"  [{tag}] {wid:8s} {ev['base_ms']:6.2f}->{ev['cand_ms']:6.2f}ms ({ev['speedup']:5.2f}x)"
                          f"  ram={ev['max_ram_kib']:4.0f}KiB  oob={ev['oob']}  rdram_coh={ev['rdram_coh']}"
                          f"  ssim={ev['ssim']:.4f}{fail_s}")
            else:
                res = json.loads((out / wid / "cand" / "result.json").read_text())
                good = (res.get("status") == "completed" and int(res.get("oob_rdram_accesses", 0)) == 0)
                if not good:
                    ok = False
                print(f"  [{'PASS' if good else 'FAIL'}] {wid:8s} status={res.get('status')}")
    finally:
        shutil.rmtree(out, ignore_errors=True)
    print_time_remaining()
    sys.exit(0 if ok else 1)


def restore_assets():
    archive = pathlib.Path("/opt/mario-eval/sm64-assets.tar.gz")
    if not archive.is_file():
        sys.exit("No offline SM64 asset archive in this task image.")
    subprocess.run(["tar", "--extract", "--gzip", "--file", str(archive),
                    "--skip-old-files", "--no-same-owner", "--directory", str(GAME)], check=True)
    print("Restored missing SM64 assets offline; existing files were left in place.")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_bld = sub.add_parser("build", help="build /task/game and print ROM sha256 & active Make config")
    p_bld.add_argument("--clean", action="store_true", help="run `make clean` before building")
    sub.add_parser("workloads", help="list the 6 public SM64 course IDs")
    p_chk = sub.add_parser("check", help="grade /task/game on public courses with full or --fast gates")
    p_chk.add_argument("workloads", nargs="*", help="optional subset of public workloads (e.g. bob jrb)")
    p_chk.add_argument("--fast", action="store_true", help="reuse incremental build and skip PLAY=1 rebuild")
    p_chk.add_argument("--play-smoke", action="store_true", help="boot and verify the PLAY=1 console ROM (default on plain `mev check`)")
    p_chk.add_argument("--no-play-smoke", action="store_true", help="skip PLAY=1 boot smoke on full `mev check`")
    p_str = sub.add_parser("stress", help="run differential random-input stress tests against baseline.z64")
    p_str.add_argument("--frames", type=int, default=240, help="frames per course (default: 240)")
    p_str.add_argument("--seed", type=int, default=1337, help="PRNG seed for controller inputs (default: 1337)")
    p_str.add_argument("--all-courses", action="store_true", help="stress-test across 18 SM64 courses instead of only the 6 public courses")
    p_dif = sub.add_parser("diff", help="run custom replay against /task/game and baseline.z64")
    p_dif.add_argument("replay", help="path to controller replay .txt")
    p_dif.add_argument("--frames", type=int, default=0, help="override frame count (default: line count of replay)")
    sub.add_parser("restore-assets", help="restore missing SM64 assets from the offline archive")
    p_run = sub.add_parser("run", help="run one or --all public courses and print hardware cost breakdown")
    p_run.add_argument("workload", nargs="?", default=None, help="public course ID (bob, wf, jrb, ddd, bitfs, rr)")
    p_run.add_argument("--all", action="store_true", help="run all public workloads in parallel")
    p_run.add_argument("--frames", type=int, default=0, help="override frame count (default: workload frames)")
    p_run.add_argument("--top", type=int, default=0, help="include top-N function profile (alias for `mev profile`)")
    p_run.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_prof = sub.add_parser("profile", help="attribute CPU/I-cache/D-cache/RDP/RDRAM hotspots on a course")
    p_prof.add_argument("workload", help="public course ID (bob, wf, jrb, ddd, bitfs, rr)")
    p_prof.add_argument("--frames", type=int, default=0, help="override frame count (default: workload frames)")
    p_prof.add_argument("--top", type=int, default=25, help="number of top functions/symbols to show (default: 25)")
    args = ap.parse_args()
    if args.cmd == "build":
        print(build(clean=args.clean))
    elif args.cmd == "workloads":
        for w in config()["workloads"]:
            print(w["id"])
    elif args.cmd == "run":
        run(args)
    elif args.cmd == "profile":
        run(args, profile=True)
    elif args.cmd == "check":
        check(args)
    elif args.cmd == "stress":
        stress(args)
    elif args.cmd == "diff":
        diff_replay(args)
    elif args.cmd == "restore-assets":
        restore_assets()


if __name__ == "__main__":
    main()
