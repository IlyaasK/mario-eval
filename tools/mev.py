#!/usr/bin/env python3
"""mev: build, run, profile, stress-test and self-check the target N64 game inside the task container.

  mev build [--clean]           build /task/game (prints ROM sha256 & rebuild status)
  mev run WORKLOAD [--frames N] [--json]
  mev run --all [--frames N] [--json]
                                run one or all public workloads in parallel, print
                                hardware cost breakdown (CPU, RSP Gfx/Aud, RDP modes, RDRAM)
  mev profile WORKLOAD [--top N] [--frames N]
                                per-function CPU profile (excluding idle thread from busy %),
                                function sizes & I-cache lines, D/I-cache misses, data-symbol
                                D-cache miss & writeback attribution, 16 KB I-cache conflicts,
                                and RDP/RDRAM breakdown
  mev check [WORKLOAD ...] [--fast] [--play-smoke]
                                full public grading of /task/game (same grader, same gates).
                                Pass workload IDs (e.g. `mev check jrb`) and/or `--fast`
                                (incremental build, skips PLAY=1) for a ~5s gate-verified loop.
                                Pass `--play-smoke` to boot and verify the PLAY=1 console ROM.
  mev stress [--frames N] [--seed S]
                                run local seeded button-mash stress tests (checks completion,
                                4 MB RAM, D-cache DMA coherence, and KSEG1 CACHE safety)
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
import shutil
import subprocess
import sys
import tempfile
import time

GAME = pathlib.Path("/task/game")
CORPUS = pathlib.Path("/opt/mario-eval/corpus")
CACHE = pathlib.Path("/opt/mario-eval/reference")
BUILD_LOCK = pathlib.Path("/tmp/mev-build.lock")


def sh(cmd, **kw):
    return subprocess.run(cmd, check=False, **kw)


def config():
    return json.loads((CORPUS / "grader.json").read_text())


def _rom_sha(path):
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def find_elf(cfg):
    if "elf" in cfg:
        p = GAME / cfg["elf"]
        if p.exists():
            return p
    for p in GAME.rglob("*.elf"):
        return p
    return None


def build(clean=False, quiet_stdout=False):
    cfg = config()
    rom = GAME / cfg["rom"]
    jobs = str(os.cpu_count() or 8)
    base_cmd = cfg.get("build_cmd", ["make"])
    cmd = [base_cmd[0], f"-j{jobs}", *base_cmd[1:]] if base_cmd[0] == "make" else list(base_cmd)

    BUILD_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with open(BUILD_LOCK, "w") as lockf:
        fcntl.flock(lockf, fcntl.LOCK_EX)
        if clean and base_cmd[0] == "make":
            sh(["make", "clean"], cwd=GAME, stdout=subprocess.DEVNULL if quiet_stdout else sys.stderr, stderr=sys.stderr)
        pre_sha = _rom_sha(rom)
        pre_mtime = rom.stat().st_mtime if rom.is_file() else 0.0
        if quiet_stdout:
            r = sh(cmd, cwd=GAME, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if r.returncode != 0 or not rom.exists():
                if r.stdout:
                    print(r.stdout, file=sys.stderr, end="")
                sys.exit("build failed")
        else:
            r = sh(cmd, cwd=GAME, stdout=sys.stderr)
            if r.returncode != 0 or not rom.exists():
                sys.exit("build failed")
        post_sha = _rom_sha(rom)
        post_mtime = rom.stat().st_mtime
        rebuilt = (pre_sha is None) or (post_sha != pre_sha) or (post_mtime != pre_mtime)

        makefile = GAME / "Makefile"
        elf = find_elf(cfg)
        if makefile.is_file() and elf and elf.is_file() and makefile.stat().st_mtime > elf.stat().st_mtime + 1.0:
            print("WARNING: Makefile is newer than built ELF — if you changed COMPILER, GRUCODE, or OPT_FLAGS, run `mev build --clean`!",
                  file=sys.stderr)
        print(f"ROM sha256: {post_sha} (rebuilt: {'yes' if rebuilt else 'no'})", file=sys.stderr)
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
    result = json.loads((out_dir / "result.json").read_text())
    if result["status"] != "completed":
        print(json.dumps(result, indent=1))
        sys.exit(1)
    run_data = load_run(out_dir)
    m = metrics(run_data)
    ref = load_run(CACHE / "runs" / workload)
    ref["rows"] = ref["rows"][:len(run_data["rows"])]
    base = metrics(ref)
    return result, run_data, m, base


def summarize(out_dir, workload, full_frames=240, as_json=False):
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
          f"(im_rd={m.get('rdp_fill_imrd_cycles',0)/rdp_cpm:.2f}ms "
          f"2cyc={m.get('rdp_fill_2cycle_cycles',0)/rdp_cpm:.2f}ms "
          f"decal={m.get('rdp_fill_decal_cycles',0)/rdp_cpm:.2f}ms "
          f"copy={m.get('rdp_fill_copy_cycles',0)/rdp_cpm:.2f}ms)  "
          f"page_miss={m.get('rdp_page_miss_cycles',0)/rdp_cpm:.2f}ms ({m.get('rdp_rdram_page_misses',0):.0f})  "
          f"tmem={m.get('rdp_tmem_cycles',0)/rdp_cpm:.2f}ms ({m.get('rdp_tmem_loads',0):.0f})  "
          f"sync={m.get('rdp_sync_cycles',0)/rdp_cpm:.2f}ms  "
          f"z_rej={z_pct:.1f}%  tris={m.get('rdp_triangles',0):.0f}")
    c_addr, z_addr = m.get("rdp_color_addr", 0), m.get("rdp_z_addr", 0)
    if c_addr or z_addr:
        print(f"  RDRAM buffers: color=0x{c_addr:06x} (bank {(c_addr >> 20) & 3})  Z=0x{z_addr:06x} (bank {(z_addr >> 20) & 3})")
    if m.get("dcache_coherence_errors", 0) or m.get("cache_uncached_ops", 0) or m.get("cache_cde_unaligned_ops", 0):
        print(f"  WARNING hardware hazards: dcache_coherence_errors={m.get('dcache_coherence_errors', 0)}  "
              f"cache_uncached_ops={m.get('cache_uncached_ops', 0)}  "
              f"cache_cde_unaligned_ops={m.get('cache_cde_unaligned_ops', 0)}")
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
    cmd = ["n64run", "--rom", str(rom), "--replay", str(rpath),
           "--out", str(out_dir), "--frames", str(frames)]
    cmd += iargs
    if profile_path is not None:
        cmd += ["--profile", str(profile_path)]
    r = sh(cmd, stderr=subprocess.PIPE, text=True)
    for line in r.stderr.splitlines():
        if "Stalled compile" not in line:
            print(line, file=sys.stderr)
    return r.returncode


def run_all_workloads(args):
    cfg = config()
    rom = build(quiet_stdout=True)
    frames = args.frames or min(120, cfg["frames"])
    iargs = idle_args(cfg)
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-all-"))
    pub_wls = [w for w in cfg["workloads"] if w.get("split", "public") == "public"]
    jobs = min(len(pub_wls), os.cpu_count() or 8)

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
    print(f"All public workloads ({frames} frames; bn = dominant bottleneck):")
    print(f"  {'course':8s} {'console':>8s} {'p99':>8s} {'cpu':>8s} {'rsp':>8s} {'rdp':>8s} {'mem':>8s} {'bn':>6s} {'speedup':>8s}")
    ratios = []
    for w in pub_wls:
        wid = w["id"]
        _res, _rd, m, b = results[wid]
        bn_map = m.get("bottleneck_share", {})
        bn = max(bn_map, key=bn_map.get) if bn_map else "-"
        ratio = m["est_console_ms"] / b["est_console_ms"] if b.get("est_console_ms") else 1.0
        ratios.append(ratio)
        print(f"  {wid:8s} {m['est_console_ms']:8.2f} {m['est_console_p99_ms']:8.2f}"
              f" {m['cpu_ms']:8.2f} {m['rsp_ms']:8.2f} {m['rdp_ms']:8.2f}"
              f" {m['mem_ms']:8.2f} {bn:>6s} {1.0 / ratio:7.3f}x")
    geo = math.exp(sum(math.log(max(r, 1e-12)) for r in ratios) / len(ratios))
    print(f"\n  geomean console speedup ({frames}f): {1.0 / geo:.4f}x   raw output: {out}")
    print_time_remaining()


def run(args, profile=False):
    if not profile and getattr(args, "all", False):
        run_all_workloads(args)
        return
    if not args.workload:
        sys.exit("specify a workload ID (e.g. `mev run jrb`) or `--all`")
    cfg = config()
    rom = build(quiet_stdout=True)
    frames = args.frames or min(120, cfg["frames"])
    out = pathlib.Path(tempfile.mkdtemp(prefix=f"mev-{args.workload}-"))
    iranges = idle_range_list(cfg)
    iargs = []
    for r in iranges:
        iargs += ["--idle-range", r]
    samples_path = (out / "samples.txt") if profile else None
    _run_one_n64(rom, args.workload, replay(args.workload), out / "run", frames, iargs, profile_path=samples_path)

    if profile:
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
                       "--top", str(args.top), "--frames", str(sample_frames), "--with-sizes"]
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
                       "--top", str(args.top), "--frames", str(sample_frames), "--with-sizes"]
                if by_data:
                    cmd.append("--by-data-symbol")
                sh(cmd)
                print(flush=True)
            imiss = pathlib.Path(str(samples) + ".imiss")
            if imiss.exists() and imiss.stat().st_size:
                print("Top 16 KB I-cache set conflict pairs (same addr mod 0x4000):", flush=True)
                sh([sys.executable, symbolize, str(imiss), str(nm), "--icache-conflicts", "--top", "12"])
                print(flush=True)
    summarize(out / "run", args.workload, full_frames=cfg["frames"], as_json=getattr(args, "json", False))
    if not getattr(args, "json", False):
        print(f"\nraw output: {out}/run  (frames.jsonl, video.bin, audio.bin, obs.bin)")
        if profile:
            print(f"profile files: {out}/samples.txt{{,.dmiss,.dmissaddr,.imiss,.wb}}")
        print_time_remaining()


def check(args):
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-check-"))
    partial = bool(args.workloads) or bool(args.fast)
    prev_summary = None
    last_link = pathlib.Path("/tmp/mev-last-check/summary.json")
    if last_link.is_file():
        try:
            prev_summary = json.loads(last_link.read_text())
        except Exception:
            prev_summary = None

    cmd = [sys.executable, "-m", "grader.grade", "grade", str(GAME), "--corpus", str(CORPUS),
           "--cache", str(CACHE), "--out", str(out)]
    if args.play_smoke and args.fast:
        sys.exit("--play-smoke cannot be combined with --fast (needs a clean PLAY=1 ROM build)")
    handoff = None
    try:
        if args.fast:
            cfg = config()
            rom = build(quiet_stdout=True)
            handoff = pathlib.Path(tempfile.mkdtemp(prefix="mev-fast-handoff-"))
            shutil.copy2(rom, handoff / "built.z64")
            elf = find_elf(cfg)
            sys.path.insert(0, "/opt/mario-eval")
            from grader.grade import idle_ranges
            idle = idle_ranges(elf, cfg.get("idle_symbols", [])) if (elf and cfg.get("idle_symbols")) else []
            (handoff / "built.idle.json").write_text(json.dumps(idle))
            cmd += ["--built", str(handoff)]
        if args.workloads:
            cmd += ["--workloads", ",".join(args.workloads)]
        if args.play_smoke:
            cmd += ["--play-smoke"]
        r = sh(cmd, cwd="/opt/mario-eval")
    finally:
        if handoff is not None:
            shutil.rmtree(handoff, ignore_errors=True)
    summary_path = out / "summary.json"
    if not partial:
        last_dir_link = pathlib.Path("/tmp/mev-last-check")
        tmp_link = pathlib.Path(f"/tmp/.mev-last-check.{os.getpid()}")
        try:
            tmp_link.unlink(missing_ok=True)
            tmp_link.symlink_to(out)
            tmp_link.replace(last_dir_link)
        except OSError:
            pass
    if summary_path.exists():
        try:
            s = json.loads(summary_path.read_text())
            if not partial:
                head = subprocess.run(["git", "-C", str(GAME), "rev-parse", "--short", "HEAD"],
                                      capture_output=True, text=True).stdout.strip()
                rec = {
                    "ts": round(time.time(), 2),
                    "git_head": head,
                    "status": s.get("status"),
                    "reason": s.get("reason"),
                    "rewards": s.get("rewards", {}),
                    "speedups": s.get("speedups", {}),
                    "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in s.get("profiles", {}).items()},
                }
                with open("/task/.mev-history.jsonl", "a") as hf:
                    hf.write(json.dumps(rec) + "\n")

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
                print("\nPer-course breakdown (ms; bn = bottleneck; vid% = worst pixel diff; Δcon vs last check):")
                print(f"  {'course':8s} {'console':>8s} {'p99':>8s} {'cpu':>8s} {'rsp':>8s} {'rdp':>8s} {'mem':>8s} {'bn':>5s} {'speedup':>8s} {'Δcon':>7s} {'vid%':>7s} {'varF':>5s}")
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
                    varf = int(vw.get("variant_frames", 0))
                    print(f"  {wid:8s} {cur_ms:8.2f} {m.get('est_console_p99_ms', 0):8.2f}"
                          f" {m.get('cpu_ms', 0):8.2f} {m.get('rsp_ms', 0):8.2f} {m.get('rdp_ms', 0):8.2f}"
                          f" {m.get('mem_ms', 0):8.2f} {bn:>5s} {sp} {dcon} {vstr} {varf:5d}")
                # Flag any non-zero near-threshold video drift or hardware hazards
                drift_wls = [(wid, 100.0 * float(vw.get("worst_bad_fraction", 0.0)))
                             for wid, vw in vid_wls.items() if float(vw.get("worst_bad_fraction", 0.0)) > 0.0002]
                if drift_wls:
                    notes = ", ".join(f"{wid}={pct:.3f}%" for wid, pct in drift_wls)
                    print(f"  NOTE: non-zero pixel drift detected ({notes}; limit 0.200%) — verify held-out safety before committing!")
                hazards = [(wid, hw.get("dcache_coherence_errors", 0), hw.get("cache_uncached_ops", 0), hw.get("cache_cde_unaligned_ops", 0))
                           for wid, hw in hw_wls.items()
                           if hw.get("dcache_coherence_errors", 0) or hw.get("cache_uncached_ops", 0) or hw.get("cache_cde_unaligned_ops", 0)]
                if hazards:
                    hstr = ", ".join(f"{w}(coh={c},kseg1_cache={u},cde_unaligned={a})" for w, c, u, a in hazards)
                    print(f"  WARNING hardware hazards: {hstr}")
            primary = "console"
            prof_file = pathlib.Path("/task/PROFILE")
            if prof_file.is_file():
                primary = prof_file.read_text().strip() or "console"
            pinfo = s.get("profiles", {}).get(primary)
            if s.get("status") == "valid" and isinstance(pinfo, dict):
                if pinfo.get("valid"):
                    vo2 = pinfo.get("vs_o2_speedup")
                    vo2_s = f"  vs_o2={vo2:.4f}x" if vo2 is not None else ""
                    print(f"\nPrimary profile [{primary}]: PASS  speedup={pinfo.get('speedup', 0):.4f}x{vo2_s}  reward={pinfo.get('reward', 0):+.6f}")
                    other_fail = [k for k, v in s.get("profiles", {}).items() if k != primary and not v.get("valid", True)]
                    if other_fail:
                        print(f"  (Informational: other profiles {other_fail} exceeded their own budgets — this does NOT affect `{primary}`.)")
                else:
                    print(f"\nPrimary profile [{primary}]: FAIL  ({pinfo.get('reason', 'budget exceeded')})")
            if s.get("status") != "valid":
                for gname, gval in s.get("gates", {}).items():
                    if not gval.get("pass", True):
                        bad = [(wk, wv) for wk, wv in gval.get("workloads", {}).items() if not wv.get("pass", True)]
                        if bad:
                            print(f"\nFailed gate [{gname}]:")
                            for wk, wv in bad[:6]:
                                print(f"  {wk}: {json.dumps(wv)}")
        except Exception:
            pass
    if partial:
        print(f"\npartial/fast report: {summary_path}  (run plain `mev check` for full clean + PLAY=1 verification)")
    else:
        print(f"\nfull report: {summary_path} (symlink: /tmp/mev-last-check/summary.json)")
    print_time_remaining()
    sys.exit(r.returncode)


def stress(args):
    """Run local seeded button-mash stress replays across public courses to catch
    generalization crashes, RAM overflows, D-cache coherence bugs, and KSEG1 CACHE ops."""
    cfg = config()
    rom = build(quiet_stdout=True)
    frames = args.frames or 180
    iargs = idle_args(cfg)
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-stress-"))
    pub_wls = [w for w in cfg["workloads"] if w.get("split", "public") == "public"]
    rng = random.Random(args.seed)
    buttons_pool = [".", "A", "B", "Z", "AZ", "BZ", "8", "2", "4", "6", "A4", "A6", "R"]

    items = []
    for w in pub_wls:
        wid = w["id"]
        orig_lines = [l for l in (CORPUS / w["replay"]).read_text().splitlines() if l.strip() and not l.startswith("#")]
        # Keep frame 0 boot course selector intact, randomize subsequent frames in bursts
        lines = [orig_lines[0] if orig_lines else ". 0 0"]
        cur_btn, cur_x, cur_y, hold = ".", 0, 0, 0
        for _ in range(1, frames):
            if hold <= 0:
                cur_btn = rng.choice(buttons_pool)
                cur_x = rng.randint(-80, 80)
                cur_y = rng.randint(-80, 80)
                hold = rng.randint(4, 18)
            lines.append(f"{cur_btn} {cur_x} {cur_y}")
            hold -= 1
        rpath = out / f"stress-{wid}.txt"
        rpath.write_text("\n".join(lines) + "\n")
        items.append((wid, rpath))

    def _run_one(item):
        wid, rpath = item
        wdir = out / wid
        _run_one_n64(rom, wid, rpath, wdir, frames, iargs)
        res = json.loads((wdir / "result.json").read_text()) if (wdir / "result.json").is_file() else {"status": "missing"}
        return wid, res

    jobs = min(len(items), os.cpu_count() or 8)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, jobs)) as pool:
        results = list(pool.map(_run_one, items))

    limit_ram = cfg["hardware"]["rdram_bytes"]
    ok = True
    print(f"Local button-mash stress test (seed={args.seed}, {frames} frames across {len(items)} courses):")
    for wid, res in results:
        st = res.get("status", "error")
        hi = (res.get("highest_line", -1) + 1) * 16
        coh = int(res.get("dcache_coherence_errors", 0))
        uc = int(res.get("cache_uncached_ops", 0))
        ua = int(res.get("cache_cde_unaligned_ops", 0))
        good = (st == "completed" and hi <= limit_ram and uc == 0 and ua == 0)
        if not good:
            ok = False
        tag = "PASS" if good else "FAIL"
        print(f"  [{tag}] {wid:8s} status={st}  max_ram={hi/1024:.0f}KiB  kseg1_cache={uc}  cde_unaligned={ua}  dma_coh_warn={coh}")
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
    p_bld = sub.add_parser("build")
    p_bld.add_argument("--clean", action="store_true", help="run `make clean` before building")
    sub.add_parser("workloads")
    p_chk = sub.add_parser("check")
    p_chk.add_argument("workloads", nargs="*", help="optional subset of public workloads (e.g. bob jrb)")
    p_chk.add_argument("--fast", action="store_true", help="reuse incremental build and skip PLAY=1 rebuild")
    p_chk.add_argument("--play-smoke", action="store_true", help="boot and verify the PLAY=1 console ROM")
    p_str = sub.add_parser("stress")
    p_str.add_argument("--frames", type=int, default=180)
    p_str.add_argument("--seed", type=int, default=1337)
    sub.add_parser("restore-assets", help="restore missing SM64 assets from the offline archive")
    p_run = sub.add_parser("run")
    p_run.add_argument("workload", nargs="?", default=None)
    p_run.add_argument("--all", action="store_true", help="run all public workloads in parallel")
    p_run.add_argument("--frames", type=int, default=0)
    p_run.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    p_prof = sub.add_parser("profile")
    p_prof.add_argument("workload")
    p_prof.add_argument("--frames", type=int, default=0)
    p_prof.add_argument("--top", type=int, default=25)
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
    elif args.cmd == "restore-assets":
        restore_assets()


if __name__ == "__main__":
    main()
