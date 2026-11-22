#!/usr/bin/env python3
"""mario-eval grader.

    python3 -m grader.grade precompute BASELINE_SRC --corpus DIR --cache DIR [--o2-patch PATCH]
    python3 -m grader.grade grade SUBMISSION_SRC --corpus DIR --cache DIR --out DIR
                            [--split public|heldout|all] [--heldout DIR]
    python3 -m grader.grade export-public --corpus DIR --cache DIR --out DIR

A submission is a source tree (e.g. Pip's Garden or Super Mario 64). The grader:
  1. checks the protected harness files are unchanged,
  2. rebuilds the ROM itself with the pinned toolchain (and verifies the console
     PLAY=1 build compiles when configured),
  3. runs every workload under n64run (ares, CPU interpreter, unthrottled),
  4. gates on gameplay (bit-exact), video and audio (tolerances), hardware
     limits and execution, then
  5. measures resource cost against the baseline and emits, per optimization
     profile, a log-scaled reward (log2 speedup / reward_log2_scale), the
     speedup (base / cand) and the speedup relative to GCC -O2 (when calibrated).

summary.json "status" is "valid", "invalid" (the submission failed a gate:
reward -1 for every profile) or "grader_error" (infrastructure failure: no
reward; rerun).
"""
import argparse
import concurrent.futures
import hashlib
import json
import itertools
import math
import os
import pathlib
import resource
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zlib

import numpy as np

from grader import contract

HW_DEVICES = ["VR4300 ICache", "VR4300 DCache", "VR4300 Uncached", "SP DMA",
              "PI DMA", "SI DMA", "VI DMA", "AI DMA", "DP DMA", "DP Draw"]
RATIO_KEYS = ("est_console_ms", "est_console_p99_ms", "cpu_effective_cycles", "cpu_busy_cycles", "frame_ticks",
              "frame_ticks_p99", "rdp_busy", "rsp_busy", "rdram_bytes", "footprint_bytes")


class GraderError(Exception):
    """Infrastructure failure: not the submission's fault."""


# --------------------------------------------------------------------- build

def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def _copy_source(src, dst):
    root = str(pathlib.Path(src).resolve())

    def _ignore(cur, names):
        ignored = {n for n in names if n == ".git" or n.endswith((".z64", ".n64", ".v64"))}
        if str(pathlib.Path(cur).resolve()) == root:
            ignored |= {n for n in names if n == "build" or n.startswith("build_")}
        return ignored

    shutil.copytree(src, dst, ignore=_ignore)


_DEFAULT_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"
# Environment a build must not inherit: preload/library shims and interpreter
# hook paths can hijack the compiler, and credentials/proxies would leak from
# the grading environment (and have no use with no network). Everything else
# (e.g. the toolchain's N64_INST, PATH) is kept, because a legitimate build
# needs it.
_BUILD_ENV_DROP = {
    "LD_PRELOAD", "LD_AUDIT", "LD_DEBUG", "LD_LIBRARY_PATH",
    "PYTHONPATH", "PYTHONHOME", "PYTHONSTARTUP", "PYTHONUSERBASE",
    "PERL5LIB", "BASH_ENV", "ENV",
    "HTTP_PROXY", "HTTPS_PROXY", "FTP_PROXY", "ALL_PROXY", "NO_PROXY",
    "http_proxy", "https_proxy", "ftp_proxy", "all_proxy", "no_proxy",
    "GIT_CONFIG_GLOBAL", "GIT_CONFIG_SYSTEM",
}
_BUILD_ENV_SECRET_HINTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "PASSWD")


def _build_env(home, tmp):
    """Environment for the untrusted submission build.

    The build must not inherit anything that can hijack it (LD_PRELOAD,
    PYTHONPATH, ...) or leak the grading environment's credentials, and must
    not share the grader's HOME/TMPDIR; it gets its own inside the scratch
    tree, deleted with it. Toolchain variables (`N64_INST`, `PATH`, ...) are
    kept: a legitimate build needs them.
    """
    env = {k: v for k, v in os.environ.items()
           if k not in _BUILD_ENV_DROP and not any(h in k.upper() for h in _BUILD_ENV_SECRET_HINTS)}
    env.update({
        "PATH": os.environ.get("PATH", _DEFAULT_PATH),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "TMP": str(tmp),
        "TEMP": str(tmp),
        "LANG": "C",
        "LC_ALL": "C",
        "TERM": "dumb",
        "SHELL": "/bin/sh",
    })
    return env


def _kill_build_group(proc):
    """Kill the build's whole process group, so no leftover background process
    can keep running (and tamper with the grading environment) after it."""
    try:
        os.killpg(proc.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


def _run_build(cmd, cwd, home, tmp, timeout):
    """Run one untrusted build command, isolated as far as the container allows.

    The submission's Makefile runs as the same container user as the grader, so
    it cannot be given a private filesystem view without namespaces (blocked by
    the default container seccomp profile). What it does get: a scrubbed
    environment, its own HOME/TMPDIR, its own session/process group (killed
    afterwards), no core dumps, and the grading container runs with no network.
    Returns (returncode, output, timed_out).
    """
    def child_setup():
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    proc = subprocess.Popen(cmd, cwd=cwd, env=_build_env(home, tmp),
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            start_new_session=True, preexec_fn=child_setup)
    timed_out = False
    out = ""
    try:
        out, _ = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_build_group(proc)
        try:
            out, _ = proc.communicate(timeout=60)
        except Exception:
            out = ""
    _kill_build_group(proc)
    return proc.returncode, out or "", timed_out


def build(src, cfg, log_path, keep_play=False):
    """Build in scratch, retaining only the benchmark ROM, idle ranges and optional PLAY ROM."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="mev-build-"))
    out_rom = work / "built.z64"
    home, tmp = work / "home", work / "tmp"
    try:
        _copy_source(src, work / "src")
        home.mkdir(exist_ok=True)
        tmp.mkdir(exist_ok=True)
        jobs = str(os.cpu_count() or 4)
        base_cmd = cfg.get("build_cmd", ["make"])
        cmd = [base_cmd[0], f"-j{jobs}", *base_cmd[1:]] if base_cmd[0] == "make" else list(base_cmd)
        rc, out, timed_out = _run_build(cmd, work / "src", home, tmp, cfg["build_timeout_s"])
        if timed_out:
            pathlib.Path(log_path).write_text(out + "\nbuild timed out\n")
            shutil.rmtree(work, ignore_errors=True)
            return None, "build timed out"

        logs = [out]
        rom = work / "src" / cfg["rom"]
        if rc != 0 or not rom.exists():
            pathlib.Path(log_path).write_text("".join(logs))
            shutil.rmtree(work, ignore_errors=True)
            return None, "build failed; see build.log"

        shutil.copy2(rom, out_rom)
        # The ELF is only used to scope the idle-time exclusion to the idle
        # function; the emulator credits only a genuine halt loop inside that
        # range, so a doctored ELF buys nothing.
        idle = idle_ranges(work / "src" / cfg["elf"], cfg.get("idle_symbols", [])) if cfg.get("elf") else []
        (work / "built.idle.json").write_text(json.dumps(idle))

        play_cmd = cfg.get("play_build_cmd")
        if play_cmd:
            shutil.rmtree(work / "src" / "build", ignore_errors=True)
            pcmd = [play_cmd[0], f"-j{jobs}", *play_cmd[1:]] if play_cmd[0] == "make" else list(play_cmd)
            prc, pout, ptimeout = _run_build(pcmd, work / "src", home, tmp, cfg["build_timeout_s"])
            logs.append("\n--- play build ---\n" + pout)
            if ptimeout:
                logs.append("\n--- PLAY=1 ROM build timed out ---\n")
                pathlib.Path(log_path).write_text("".join(logs))
                shutil.rmtree(work, ignore_errors=True)
                return None, "PLAY=1 ROM build timed out"
            if prc != 0:
                pathlib.Path(log_path).write_text("".join(logs))
                shutil.rmtree(work, ignore_errors=True)
                return None, "PLAY=1 ROM build failed; see build.log"
            if keep_play:
                playable = work / "src" / cfg["play_rom"]
                if not playable.is_file():
                    pathlib.Path(log_path).write_text("".join(logs))
                    shutil.rmtree(work, ignore_errors=True)
                    return None, "PLAY=1 build did not produce its ROM; see build.log"
                shutil.copyfile(playable, work / "play.z64")

        pathlib.Path(log_path).write_text("".join(logs))
        shutil.rmtree(work / "src", ignore_errors=True)
        return out_rom, None
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


def build_submission(args):
    cfg = json.loads(pathlib.Path(args.config).read_text())
    out = pathlib.Path(args.out)
    if args.play_smoke and not cfg.get("play_rom"):
        raise GraderError("PLAY runtime smoke is not supported for this target")
    rom, error = build(args.source, cfg, out / "build.log", keep_play=args.play_smoke)
    if rom is None:
        (out / "error.txt").write_text(error)
        return
    try:
        for name in ("built.z64", "built.idle.json"):
            shutil.copyfile(rom.parent / name, out / name)
        if args.play_smoke:
            shutil.copyfile(rom.parent / "play.z64", out / "play.z64")
    finally:
        shutil.rmtree(rom.parent, ignore_errors=True)


def load_submission_build(directory):
    for name in ("error.txt", "built.z64", "built.idle.json", "play.z64"):
        p = directory / name
        if p.is_symlink() or (p.exists() and not p.is_file()):
            raise GraderError("invalid build handoff")
    error = directory / "error.txt"
    if error.is_file():
        with error.open(encoding="utf-8", errors="replace") as stream:
            return None, stream.read(256)
    if not all((directory / name).is_file() for name in ("built.z64", "built.idle.json")):
        raise GraderError("missing isolated build output")
    return directory / "built.z64", None


# ------------------------------------------------------- build-time integrity

def _digest(paths):
    """sha256 over the (path, content) of every file the measurement trusts."""
    h = hashlib.sha256()
    for p in paths:
        p = pathlib.Path(p)
        h.update(str(p).encode())
        try:
            h.update(sha256(p).encode())
        except (FileNotFoundError, IsADirectoryError, PermissionError):
            h.update(b"-")
    return h.hexdigest()


def measurement_artifacts(corpus, cache, items):
    """Everything a malicious build could rewrite to change what is scored:
    the emulator, the grader itself, the corpus (config/patches/variants), the
    reference cache and the replays. The grader hashes these before the build
    and again before measuring, so tampering is detected instead of scored."""
    paths = []
    exe = shutil.which("n64run")
    if exe:
        paths.append(exe)
    paths += sorted(str(p) for p in pathlib.Path(__file__).parent.rglob("*.py"))
    corpus = pathlib.Path(corpus)
    paths += sorted(str(p) for p in corpus.rglob("*") if p.is_file())
    cache = pathlib.Path(cache)
    if (cache / "index.json").exists():
        paths.append(str(cache / "index.json"))
    for w in items:
        run = cache / "runs" / w["id"]
        for name in ("obs.bin", "audio.bin", "frames.jsonl", "result.json", "frames.bin", "frames.json"):
            if (run / name).exists():
                paths.append(str(run / name))
        paths += sorted(str(p) for p in run.glob("video*.z"))
        paths.append(str(w["replay"]))
    return _digest(paths)


def idle_ranges(elf, symbols):
    """Address ranges ("lo:hi", hex) of the named idle functions in the ELF.

    CPU time spent executing inside them is time the CPU only waited (for the
    RCP, or for the next frame), and is excluded from CPU busy time.
    """
    if not symbols:
        return []
    proc = subprocess.run(["mips64-elf-nm", "-S", "--defined-only", str(elf)], capture_output=True, text=True)
    found = {}
    for line in proc.stdout.splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[3] in symbols and parts[2] in "tT":
            lo = int(parts[0], 16) & 0xFFFFFFFF
            found[parts[3]] = f"{lo:x}:{lo + int(parts[1], 16):x}"
    missing = [s for s in symbols if s not in found]
    if missing:
        raise GraderError(f"idle symbols not found in {elf}: {missing}")
    return [found[s] for s in symbols]


# ----------------------------------------------------------------------- run

def run_workload(rom, replay, frames, out_dir, max_fields, timeout):
    out_dir = pathlib.Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    # The submission build runs in this container and shares /tmp, and n64run
    # keeps its ares settings/saves there; clear them so a planted ares home
    # cannot influence the emulator.
    for stale in ("/tmp/n64run-home", "/tmp/n64run-saves"):
        shutil.rmtree(stale, ignore_errors=True)
    cmd = ["n64run", "--rom", str(rom), "--replay", str(replay), "--out", str(out_dir),
           "--frames", str(frames), "--max-fields", str(max_fields)]
    idle_file = pathlib.Path(rom).with_suffix(".idle.json")
    for r in (json.loads(idle_file.read_text()) if idle_file.exists() else []):
        cmd += ["--idle-range", r]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"status": "host_timeout"}
    (out_dir / "stderr.txt").write_text("\n".join(
        l for l in proc.stderr.splitlines() if "Stalled compile" not in l))
    result_path = out_dir / "result.json"
    if proc.returncode < 0 or not result_path.exists():
        raise GraderError(f"n64run died (code {proc.returncode}) on {replay}")
    return json.loads(result_path.read_text())


def load_run(out_dir):
    out_dir = pathlib.Path(out_dir)
    rows = [json.loads(l) for l in (out_dir / "frames.jsonl").read_text().splitlines() if l]
    return {
        "rows": rows,
        "result": json.loads((out_dir / "result.json").read_text()),
        "obs": (out_dir / "obs.bin").read_bytes(),
        "audio": (out_dir / "audio.bin").read_bytes(),
        "video_path": out_dir / "video.bin",
    }


# ------------------------------------------------------------------- metrics

def busy_rsp(row):
    return row["rsp_cycles"] - row["rsp_halted_cycles"]


def rdram_bytes(row):
    return sum(sum(row["rdram"].get(d, (0, 0))) for d in HW_DEVICES)


def _delta_mean(rows, key):
    if key not in rows[0]:
        return 0.0
    return float((rows[-1][key] - rows[0][key]) / (len(rows) - 1))


# Clock domains (verified against ares: master clock 187.5 MHz, CPU instruction
# = 2 master clocks, RSP cycle = 3 master clocks).
CPU_CYCLES_PER_MS = 93_750.0      # count_ticks / cpu_idle_cycles: VR4300 cycles (93.75 MHz)
RSP_UNITS_PER_MS = 187_500.0      # rsp_cycles: master clocks (RSP runs at 62.5 MHz)
RDP_CYCLES_PER_MS = 62_500.0      # rdp_cycles: modelled RDP cycles (62.5 MHz)
# Effective sustained mixed-master N64 RDRAM throughput (peak burst is 500 MB/s,
# but mixed CPU cachelines + 2D triangle spans + R/W turnarounds sustain ~250 MB/s).
RDRAM_BYTES_PER_MS = 250_000.0
FIELD_MS = 1000.0 / 60.0
# Bus-coupled CPU contention: ares already charges uncontended cache fills (40/48
# cycles). On real hardware, extra wait cycles per CPU bus transaction rise with
# concurrent RCP RDRAM traffic (SP DMA + DP DMA + DP Draw + PI/SI DMA) plus
# continuous 60 Hz VI scanout. Coupling contention to RCP traffic ensures that
# real bandwidth/fillrate wins (ra-zb-opa, F3DEX2, TMEM batching) reduce CPU
# bus stalls just as on console.
BUS_CONTENTION_BASE_CYCLES = 4.0
BUS_CONTENTION_PER_MB_RCP = 6.0
RCP_BUS_DEVICES = ("SP DMA", "PI DMA", "SI DMA", "DP DMA", "DP Draw")


def rcp_rdram_bytes(row):
    return sum(sum(row["rdram"].get(d, (0, 0))) for d in RCP_BUS_DEVICES)


def metrics(run):
    """Per-frame costs over frames 1..N-1 (frame 0 includes boot and setup).

    The benchmark build runs each frame's stages one after another. On a
    console, SM64 overlaps them: the CPU builds frame N+1 while the RSP and RDP
    draw frame N, all sharing RDRAM alongside continuous 60 Hz VI scanout. So a
    frame's console cost is estimated as the busiest unit: max(CPU, RSP busy,
    RDP busy, RDRAM time at sustained bandwidth). CPU time excludes the idle
    thread (waiting for the RCP) and adds bus-coupled contention per CPU bus
    transaction proportional to concurrent RCP RDRAM traffic. The RDP model
    includes 4-bank x 2 KB RDRAM page-miss cycles (see docs/n64-cost-model.md).
    """
    rows = run["rows"]
    d = lambda key: np.array([b.get(key, 0) - a.get(key, 0) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    ticks = d("count_ticks")
    idle = d("cpu_idle_cycles")
    cpu_busy = ticks - idle
    bus_events = (d("icache_misses") + d("dcache_misses") + d("dcache_writebacks")
                  + d("uncached_reads") + d("uncached_writes"))
    rsp = np.array([busy_rsp(b) - busy_rsp(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    rdp = d("rdp_cycles")
    traffic = np.array([rdram_bytes(b) - rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    rcp_traffic = np.array([rcp_rdram_bytes(b) - rcp_rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    # Continuous 60 Hz VI scanout (two fields per 30 Hz logical frame) is not
    # charged during unthrottled n64run; add its framebuffer read bandwidth here.
    fb_w, fb_h, fb_bpp = rows[0]["fb"]
    vi_bytes_per_frame = float(2 * fb_w * fb_h * (fb_bpp // 8))
    contention_cycles = BUS_CONTENTION_BASE_CYCLES + BUS_CONTENTION_PER_MB_RCP * (rcp_traffic / 1_000_000.0)
    cpu_eff = cpu_busy + contention_cycles * bus_events
    last, first = rows[-1], rows[0]
    per_device = {dev: (sum(last["rdram"].get(dev, (0, 0))) - sum(first["rdram"].get(dev, (0, 0)))) / (len(rows) - 1)
                  for dev in HW_DEVICES}
    cpu_ms_f = cpu_eff / CPU_CYCLES_PER_MS
    rsp_ms_f = rsp / RSP_UNITS_PER_MS
    rdp_ms_f = rdp / RDP_CYCLES_PER_MS
    mem_ms_f = (traffic + vi_bytes_per_frame) / RDRAM_BYTES_PER_MS
    console_ms = np.maximum.reduce([cpu_ms_f, rsp_ms_f, rdp_ms_f, mem_ms_f])
    bottleneck = np.argmax(np.stack([cpu_ms_f, rsp_ms_f, rdp_ms_f, mem_ms_f]), axis=0)
    # Displayed rate with SM64's 30 Hz game logic: a frame is shown on the first
    # video field after it completes, and never sooner than two fields.
    fields = np.maximum(2, np.ceil(console_ms / FIELD_MS - 1e-9))
    est_console_ms = float(console_ms.mean())
    return {
        "frame_ticks": float(ticks.mean()),
        "frame_ticks_p99": float(np.percentile(ticks, 99)),
        "cpu_busy_cycles": float(cpu_busy.mean()),
        "cpu_effective_cycles": float(cpu_eff.mean()),
        "cpu_idle_cycles": float(idle.mean()),
        "frame_ms": float(ticks.mean() / CPU_CYCLES_PER_MS),
        "cpu_ms": float(cpu_ms_f.mean()),
        "cpu_cycles": float(cpu_eff.mean()),
        "rsp_busy": float(rsp.mean()),
        "rsp_ms": float(rsp_ms_f.mean()),
        "rdp_busy": float(rdp.mean()),
        "rdp_ms": float(rdp_ms_f.mean()),
        "mem_ms": float(mem_ms_f.mean()),
        "bottleneck_share": {name: float((bottleneck == i).mean()) for i, name in enumerate(("cpu", "rsp", "rdp", "rdram"))},
        "rdp_fill_cycles": _delta_mean(rows, "rdp_fill_cycles"),
        "rdp_page_miss_cycles": _delta_mean(rows, "rdp_page_miss_cycles"),
        "rdp_rdram_page_misses": _delta_mean(rows, "rdp_rdram_page_misses"),
        "rdp_tmem_cycles": _delta_mean(rows, "rdp_tmem_cycles"),
        "rdp_sync_cycles": _delta_mean(rows, "rdp_sync_cycles"),
        "rdp_triangles": _delta_mean(rows, "rdp_triangles"),
        "rdp_pixels": _delta_mean(rows, "rdp_pixels"),
        "rdp_tmem_loads": _delta_mean(rows, "rdp_tmem_loads"),
        "rdp_tmem_bytes": _delta_mean(rows, "rdp_tmem_bytes"),
        "rdp_syncs": _delta_mean(rows, "rdp_syncs"),
        "est_console_ms": est_console_ms,
        "est_console_p99_ms": float(np.percentile(console_ms, 99)),
        "est_fps": float(1000.0 / max(est_console_ms, 1e-9)),
        "est_fps_30hz": float(60.0 * len(fields) / fields.sum()),
        "frames_over_33ms": float((console_ms > 2 * FIELD_MS).mean()),
        "frames_under_16ms": float((console_ms <= FIELD_MS).mean()),
        "rdram_bytes": float(traffic.mean()),
        "rdram_bytes_by_device": per_device,
        "dcache_misses": _delta_mean(rows, "dcache_misses"),
        "icache_misses": _delta_mean(rows, "icache_misses"),
        "footprint_bytes": run["result"]["footprint_bytes"],
        "highest_byte": (run["result"]["highest_line"] + 1) * 16,
    }


# --------------------------------------------------------------- comparisons

def _max_abs_diff(a, b):
    if isinstance(a, list):
        return max((abs(float(x) - float(y)) for x, y in zip(a, b)), default=0.0)
    return abs(float(a) - float(b))


def compare_obs(ref, cand, frames, schema_name="pips-garden", cfg=None):
    if len(ref) != len(cand):
        return {"pass": False, "frame": 0, "field": "obs_bytes", "ref": len(ref), "cand": len(cand)}
    n = len(ref) // frames
    gcfg = (cfg or {}).get("gameplay", {})
    if gcfg.get("mode", "bit_exact") != "player_equivalence":
        for i in range(frames):
            r, c = ref[i * n:(i + 1) * n], cand[i * n:(i + 1) * n]
            if r != c:
                diff = contract.first_difference(r, c, schema_name)
                return {"pass": False, "frame": i, "field": diff[0], "ref": diff[1], "cand": diff[2]}
        return {"pass": True}

    ref_frames = [contract.decode(ref[i * n:(i + 1) * n], schema_name) for i in range(frames)]
    cand_frames = [contract.decode(cand[i * n:(i + 1) * n], schema_name) for i in range(frames)]
    exact_fields = gcfg.get("exact_fields", ["frame", "level_area"])
    win_fields = gcfg.get("window_exact_fields", ["mario_stats", "mario_action"])
    win = int(gcfg.get("window_frames", 1))
    float_tols = gcfg.get("float_tolerances", {})
    actor_tol = gcfg.get("actor_tolerance")
    actor_radius = float(gcfg.get("actor_radius", float("inf")))
    worst_drift = 0.0

    for i in range(frames):
        rf, cf = ref_frames[i], cand_frames[i]
        for fname in exact_fields:
            if cf.get(fname) != rf.get(fname):
                return {"pass": False, "frame": i, "field": fname, "ref": rf.get(fname), "cand": cf.get(fname)}
        lo, hi = max(0, i - win), min(frames - 1, i + win)
        for fname in win_fields:
            cval = cf.get(fname)
            if not any(cval == ref_frames[j].get(fname) for j in range(lo, hi + 1)):
                return {"pass": False, "frame": i, "field": fname, "ref": rf.get(fname), "cand": cval}
        for fname, tol in float_tols.items():
            d = _max_abs_diff(rf.get(fname, 0.0), cf.get(fname, 0.0))
            if fname == "mario_pos" and d > worst_drift:
                worst_drift = d
            if d > float(tol):
                return {"pass": False, "frame": i, "field": fname, "ref": rf.get(fname), "cand": cf.get(fname),
                        "diff": round(d, 4), "tolerance": tol}
        if actor_tol is not None:
            miss = _unmatched_actor(rf, cf, float(actor_tol), actor_radius)
            if miss is not None:
                return {"pass": False, "frame": i, "field": "actors", "ref": miss, "cand": None,
                        "tolerance": actor_tol, "radius": actor_radius}
    # Final frame stats must match without window slack so coins/health/stars at route end are exact.
    if "mario_stats" in win_fields and cand_frames[-1].get("mario_stats") != ref_frames[-1].get("mario_stats"):
        return {"pass": False, "frame": frames - 1, "field": "mario_stats",
                "ref": ref_frames[-1].get("mario_stats"), "cand": cand_frames[-1].get("mario_stats")}
    return {"pass": True, "max_pos_drift": round(worst_drift, 4)}


def _unmatched_actor(rf, cf, tol, radius):
    """Every reference actor within `radius` of Mario must have a candidate
    actor with the same action/state and a position within `tol`. Actors are
    matched as an unordered set: object-list order is an allocator detail the
    player never sees. Farther actors are not checked, so hibernating distant
    objects stays legal. Returns the first unmatched reference actor, or None.
    The harness records at most len(actor_state) actors in list order; past
    that the two builds may record different subsets, so such frames are only
    checked by actor_count."""
    count = rf.get("actor_count", 0)
    cap = len(rf.get("actor_state", []))
    if count != cf.get("actor_count") or count > cap:
        return None
    rp = np.asarray(rf["actor_pos"][:3 * count], dtype=np.float64).reshape(count, 3)
    cp = np.asarray(cf["actor_pos"][:3 * count], dtype=np.float64).reshape(count, 3)
    rs, cs = rf["actor_state"][:count], cf["actor_state"][:count]
    if rs == cs and np.abs(rp - cp).max(initial=0.0) <= tol:
        return None
    near = np.linalg.norm(rp - np.asarray(rf["mario_pos"], dtype=np.float64), axis=1) <= radius
    close = np.abs(rp[:, None, :] - cp[None, :, :]).max(axis=2) <= tol
    used = np.zeros(count, dtype=bool)
    for a in np.flatnonzero(near):
        for b in np.flatnonzero(close[a] & ~used):
            if cs[b] == rs[a]:
                used[b] = True
                break
        else:
            return {"state": rs[a], "pos": rp[a].tolist()}
    return None


def decode_rgba16(buf, w, h):
    a = np.frombuffer(buf, dtype=">u2").reshape(h, w).astype(np.int16)
    return np.stack([(a >> 11) & 31, (a >> 6) & 31, (a >> 1) & 31], axis=-1)


def decode_rgba32(buf, w, h):
    a = np.frombuffer(buf, dtype=np.uint8).reshape(h, w, 4).astype(np.int16)
    # Scale 8-bit channels onto 5-bit [0..31] units so channel_tolerance applies uniformly.
    return a[:, :, :3] >> 3


def decode_frame(buf, w, h, bpp):
    return decode_rgba32(buf, w, h) if bpp == 32 else decode_rgba16(buf, w, h)


def unmatched(a, b, tol):
    """Pixels of a with no pixel within tol (per channel) in b's 3x3 neighbourhood."""
    h, w, _ = a.shape
    pad = np.pad(b, ((1, 1), (1, 1), (0, 0)), mode="edge")
    best = np.full((h, w), 1 << 14, dtype=np.int16)
    for dy in range(3):
        for dx in range(3):
            d = np.abs(a - pad[dy:dy + h, dx:dx + w]).max(axis=-1)
            np.minimum(best, d, out=best)
    return best > tol


def mismatch(a, b, tol):
    """Pixels where a and b disagree beyond tolerance, in either direction."""
    return unmatched(a, b, tol) | unmatched(b, a, tol)


def reference_variants(entry, fallback=()):
    """Which stored video holds each accepted variant for one workload.

    A dict {"combo": stored}, where "" means the combination renders exactly
    like the baseline. Caches written before deduplication stored a plain list
    of variant ids (one video each), either per workload or once for the whole
    cache; both are still read."""
    v = entry.get("variants")
    if isinstance(v, dict):
        return v
    if isinstance(v, list):
        return {name: name for name in v}
    return {name: name for name in fallback}


def _reference_frame_sets(ref_dir, variants, frames, w, h, bpp):
    """Distinct reference frames per frame index: index 0 is the original
    picture, the rest are accepted variants.

    Each distinct picture counts once (a minimum over duplicates is unchanged),
    so grading memory is bounded by the distinct frames rather than one whole
    video per accepted combination, and repeated comparisons are skipped. The
    storage deduplication already collapsed identical combinations; this also
    collapses frames a variant shares with the original or another variant."""
    size = w * h * bpp // 8
    files = [ref_dir / "video.bin.z"] + [ref_dir / f"video.{v}.bin.z"
                                         for v in sorted(set(variants.values()) - {""})]
    seen = [dict() for _ in range(frames)]
    out = [[] for _ in range(frames)]
    for path in files:
        video = zlib.decompress(path.read_bytes())
        for i in range(frames):
            frame = video[i * size:(i + 1) * size]
            key = hashlib.sha1(frame).digest()
            if key not in seen[i]:
                seen[i][key] = True
                out[i].append(frame)
        del video
    return out


def compare_video(ref_dir, variants, cand_path, ref_rows, cand_rows, cfg):
    """Every frame must match, as a whole frame within tolerance, either the
    original picture or one of the accepted visual variants, at that frame
    index (preventing half-original / half-variant per-pixel mixing within a
    single frame).

    The reference is the set of distinct frames per index, so an accepted
    visual change present in several combinations costs one comparison.
    """
    if len(ref_rows) != len(cand_rows):
        return {"pass": False, "frame": min(len(ref_rows), len(cand_rows)), "reason": "frame count changed"}
    w, h, bpp = ref_rows[0]["fb"]
    size = w * h * bpp // 8
    tol = cfg["video"]["channel_tolerance"]
    limit = cfg["video"]["max_bad_fraction"]
    refs = _reference_frame_sets(ref_dir, variants, len(ref_rows), w, h, bpp)
    worst = (0.0, -1)
    variant_frames = 0
    failed_frames = 0
    with open(cand_path, "rb") as f:
        for i, row in enumerate(cand_rows):
            if row["fb"] != [w, h, bpp]:
                return {"pass": False, "frame": i, "reason": f"framebuffer format changed to {row['fb']}"}
            cand = f.read(size)
            orig = refs[i][0]
            if cand == orig:
                continue
            if cand in refs[i][1:]:
                variant_frames += 1
                continue
            c = decode_frame(cand, w, h, bpp)
            orig_frac = float(mismatch(c, decode_frame(orig, w, h, bpp), tol).mean())
            frac = orig_frac
            for ref in refs[i][1:]:
                v_frac = float(mismatch(c, decode_frame(ref, w, h, bpp), tol).mean())
                if v_frac < frac:
                    frac = v_frac
            if orig_frac > limit and frac <= limit:
                variant_frames += 1
            failed_frames += frac > limit
            if frac > worst[0]:
                worst = (frac, i)
    ok = worst[0] <= limit
    return {"pass": ok, "worst_bad_fraction": worst[0], "worst_frame": worst[1],
            "max_bad_fraction": limit, "failed_frames": failed_frames, "variant_frames": variant_frames}


def compare_audio(ref, cand, ref_rows, cand_rows, cfg):
    au_bytes = ref_rows[0]["au_len"]
    for i, row in enumerate(cand_rows):
        if row["au_len"] != au_bytes:
            return {"pass": False, "frame": i, "reason": f"audio bytes/frame {row['au_len']} != {au_bytes}"}
    a = np.frombuffer(ref, dtype=">i2").astype(np.float64)
    b = np.frombuffer(cand, dtype=">i2").astype(np.float64)
    if a.shape != b.shape:
        return {"pass": False, "reason": "audio length differs"}
    err = a - b
    snr = math.inf if not err.any() else 10 * math.log10(max((a * a).sum(), 1.0) / (err * err).sum())
    acfg = cfg["audio"]
    per = au_bytes // 2
    worst = (math.inf, -1)
    for i in range(len(a) // per):
        fa, fb = a[i * per:(i + 1) * per], b[i * per:(i + 1) * per]
        rms = math.sqrt((fa * fa).mean())
        if rms <= acfg["silence_rms"]:
            if np.abs(fb).max() > acfg["silence_max_abs"]:
                return {"pass": False, "frame": i, "reason": "sound where the baseline is silent", "snr_db": snr}
            continue
        e = fa - fb
        if e.any():
            fsnr = 10 * math.log10((fa * fa).sum() / (e * e).sum())
            if fsnr < worst[0]:
                worst = (fsnr, i)
    ok = snr >= acfg["min_snr_db"] and worst[0] >= acfg["min_frame_snr_db"]
    return {"pass": ok, "snr_db": snr, "worst_frame_snr_db": worst[0], "worst_frame": worst[1],
            "min_snr_db": acfg["min_snr_db"], "min_frame_snr_db": acfg["min_frame_snr_db"]}


# ------------------------------------------------------------------- corpus

def workloads(corpus, cfg, split, heldout_dir):
    items = []
    if split in ("public", "all"):
        items += [dict(w, replay=str(pathlib.Path(corpus) / w["replay"]))
                  for w in cfg["workloads"] if w["split"] == "public"]
    if split in ("heldout", "all"):
        if not heldout_dir:
            raise GraderError("held-out split requested but --heldout not given")
        for p in sorted(pathlib.Path(heldout_dir).glob("*.txt")):
            items.append({"id": f"heldout-{p.stem}", "split": "heldout", "replay": str(p)})
    return items


def run_all(rom, items, frames, out_dir, max_fields, timeout):
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(4, len(items))) as pool:
        futures = {w["id"]: pool.submit(run_workload, rom, w["replay"], frames,
                                        pathlib.Path(out_dir) / w["id"], max_fields(w["id"]), timeout)
                   for w in items}
        return {k: f.result() for k, f in futures.items()}


# ---------------------------------------------------------------- precompute

def patched_copy(source, patch_files):
    """Copy source to a scratch dir and apply one or more patches in order."""
    if isinstance(patch_files, (str, pathlib.Path)):
        patch_files = [patch_files]
    work = pathlib.Path(tempfile.mkdtemp(prefix="mev-variant-"))
    _copy_source(source, work / "src")
    for patch_file in patch_files:
        proc = subprocess.run(["patch", "-s", "-p1", "-i", str(patch_file)], cwd=work / "src",
                              capture_output=True, text=True)
        if proc.returncode != 0:
            shutil.rmtree(work, ignore_errors=True)
            raise GraderError(f"patch {patch_file} does not apply: {proc.stdout}{proc.stderr}")
    return work


def essential_atoms(atoms):
    """The atoms of a combination that actually change its rendering.

    An atom may declare `subsumed_by`: other atoms whose change already
    includes its effect, so the combination renders exactly like the same one
    without it. `full-detail` only forces Mario's high-polygon model, and
    `no-lod` removes every level-of-detail switch (Mario's included), so
    `full-detail+no-lod` is `no-lod` frame for frame, on every route (checked
    against every precomputed combination). Dropping such atoms means those
    combinations are never built, stored or compared twice."""
    keep = list(atoms)
    while True:
        ids = {v["id"] for v in keep}
        reduced = [v for v in keep if not (ids - {v["id"]}) & set(v.get("subsumed_by", []))]
        if len(reduced) == len(keep):
            return keep
        keep = reduced


def variant_combinations(cfg):
    """Every distinct non-empty combination of the atomic accepted visual changes.

    The video gate matches each frame as a whole against one reference, so a
    submission that uses several accepted changes needs a reference with
    exactly that combination. Combinations another combination already renders
    identically are skipped (see essential_atoms), and an atom may list the
    "workloads" it can change (e.g. one course's scenery); elsewhere the
    combination looks exactly like the combination without it. Smaller
    combinations come first. Returns [(id, [atom, ...]), ...]."""
    atoms = cfg.get("accepted_visual_variants", [])
    out, seen = [], set()
    for r in range(1, len(atoms) + 1):
        for combo in itertools.combinations(atoms, r):
            essential = essential_atoms(combo)
            vid = "+".join(v["id"] for v in essential)
            if not vid or vid in seen:
                continue
            seen.add(vid)
            out.append((vid, essential))
    return out


def effective_variant(atoms, workload):
    """Id of the combination that renders this workload identically to `atoms`
    (the atoms that can change it), or None for the unmodified baseline.
    Held-out routes may visit any course, so every atom counts for them."""
    def affects(v):
        return "workloads" not in v or workload["split"] != "public" or workload["id"] in v["workloads"]
    # Drop the atoms that cannot change this workload first: subsumption only
    # holds between atoms that are both part of the combination here.
    return "+".join(v["id"] for v in essential_atoms([v for v in atoms if affects(v)])) or None


def precompute(args):
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    cache = pathlib.Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rom, err = build(args.source, cfg, cache / "build.log")
    if rom is None:
        raise GraderError(f"baseline failed to build ({err}); see build.log")
    try:
        items = workloads(args.corpus, cfg, args.split, args.heldout)
        generous = lambda _id: cfg["frames"] * 600 + 2400
        results = run_all(rom, items, cfg["frames"], cache / "runs", generous, cfg["run_timeout_s"])
        index = {
            "rom_sha256": sha256(rom),
            "contract": cfg.get("contract", "pips-garden"),
            "protected": {},
            "workloads": {},
            "variants": [],
        }
        for f in cfg["protected_files"]:
            index["protected"][f] = sha256(pathlib.Path(args.source) / f)
        for w in items:
            res = results[w["id"]]
            if res.get("status") != "completed":
                raise GraderError(f"baseline did not complete {w['id']}: {res}")
            run_dir = cache / "runs" / w["id"]
            video = (run_dir / "video.bin").read_bytes()
            (run_dir / "video.bin.z").write_bytes(zlib.compress(video, 6))
            (run_dir / "video.bin").unlink()
            index["workloads"][w["id"]] = {
                "split": w["split"],
                "replay_sha256": sha256(w["replay"]),
                "vi_fields": res["vi_fields"],
                "metrics": metrics(load_run(run_dir)),
            }
    finally:
        shutil.rmtree(rom.parent, ignore_errors=True)

    # Accepted visual variants: the baseline with each distinct combination of
    # the listed visual changes applied. Each must leave gameplay bit-exact and
    # audio within the audio gate (a microcode swap shifts RSP task timing,
    # which can move a few samples by a few LSBs); only its video is kept, as an
    # extra reference for the video gate. A combination whose video is
    # byte-identical to one already stored is recorded as an alias of it
    # (video_alias) instead of being written again, and the gate compares
    # against distinct frames only, so storage and grading memory both shrink.
    video_alias = {w["id"]: {} for w in items}   # -> {variant id: stored variant id or "" (baseline)}
    video_seen = {}                              # (workload, sha1 of the video) -> stored variant id or ""
    for w in items:
        raw = zlib.decompress((cache / "runs" / w["id"] / "video.bin.z").read_bytes())
        video_seen[(w["id"], hashlib.sha1(raw).hexdigest())] = ""
    stored_variants = set()

    for variant_id, atoms in variant_combinations(cfg):
        own = []
        for w in items:
            same = effective_variant(atoms, w)
            if same == variant_id:
                own.append(w)
            else:
                # Renders like a smaller combination here; alias its stored video.
                video_alias[w["id"]][variant_id] = video_alias[w["id"]].get(same or "", same or "")
        if not own:
            continue
        vwork = patched_copy(args.source, [(corpus / v["patch"]).resolve() for v in atoms])
        vrom = None
        try:
            vrom, verr = build(vwork / "src", cfg, cache / f"build-{variant_id}.log")
            if vrom is None:
                raise GraderError(f"variant {variant_id} failed to build: {verr}")
            vdir = cache / "variant-runs" / variant_id
            vres = run_all(vrom, own, cfg["frames"], vdir, generous, cfg["run_timeout_s"])
            for w in own:
                wid = w["id"]
                if vres[wid].get("status") != "completed":
                    raise GraderError(f"variant {variant_id} did not complete {wid}")
                base_run, var_run = load_run(cache / "runs" / wid), load_run(vdir / wid)
                if base_run["obs"] != var_run["obs"]:
                    raise GraderError(f"variant {variant_id} changes gameplay on {wid}; "
                                      "an accepted visual change must be visual only")
                au = compare_audio(base_run["audio"], var_run["audio"], base_run["rows"], var_run["rows"], cfg)
                if not au["pass"]:
                    raise GraderError(f"variant {variant_id} changes audio on {wid}: {au}")
                if base_run["audio"] != var_run["audio"]:
                    print(f"variant {variant_id} {wid}: audio SNR {au['snr_db']:.1f} dB", file=sys.stderr)
                video = (vdir / wid / "video.bin").read_bytes()
                digest = hashlib.sha1(video).hexdigest()
                if (wid, digest) in video_seen:
                    video_alias[wid][variant_id] = video_seen[(wid, digest)]
                else:
                    (cache / "runs" / wid / f"video.{variant_id}.bin.z").write_bytes(zlib.compress(video, 6))
                    video_seen[(wid, digest)] = variant_id
                    video_alias[wid][variant_id] = variant_id
                    stored_variants.add(variant_id)
            shutil.rmtree(vdir, ignore_errors=True)
        finally:
            if vrom is not None:
                shutil.rmtree(vrom.parent, ignore_errors=True)
            shutil.rmtree(vwork, ignore_errors=True)

    index["variants"] = sorted(stored_variants)
    for w in items:
        index["workloads"][w["id"]]["variants"] = video_alias[w["id"]]

    # Optional GCC -O2 (IEEE) reference calibration, so summary.json can report
    # both speedup vs vanilla (-O0 / IDO) and speedup beyond compiler flags.
    o2_patch = args.o2_patch or cfg.get("o2_reference_patch")
    if o2_patch:
        pfile = pathlib.Path(o2_patch)
        if not pfile.is_absolute():
            pfile = (corpus / pfile).resolve()
        if pfile.exists():
            owork = patched_copy(args.source, pfile)
            orom = None
            try:
                orom, oerr = build(owork / "src", cfg, cache / "build-o2-ref.log")
                if orom is None:
                    raise GraderError(f"o2 reference patch failed to build: {oerr}")
                odir = cache / "o2-runs"
                ores = run_all(orom, items, cfg["frames"], odir, generous, cfg["run_timeout_s"])
                o2_metrics = {}
                for w in items:
                    if ores[w["id"]].get("status") != "completed":
                        raise GraderError(f"o2 reference did not complete {w['id']}")
                    o2_metrics[w["id"]] = metrics(load_run(odir / w["id"]))
                shutil.rmtree(odir, ignore_errors=True)
                index["o2_reference"] = o2_metrics
            finally:
                if orom is not None:
                    shutil.rmtree(orom.parent, ignore_errors=True)
                shutil.rmtree(owork, ignore_errors=True)

    (cache / "index.json").write_text(json.dumps(index, indent=1))
    print(json.dumps({k: round(v["metrics"]["est_console_ms"], 2) for k, v in index["workloads"].items()}, indent=1))
    print("accepted visual variants:", index["variants"])
    if "o2_reference" in index:
        print("recorded GCC -O2 reference metrics")


def export_public(args):
    """Stage a strictly public-only copy of cache/reference for the agent container."""
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    src_cache = pathlib.Path(args.cache)
    dst_cache = pathlib.Path(args.out)
    if dst_cache.exists():
        shutil.rmtree(dst_cache)
    (dst_cache / "runs").mkdir(parents=True, exist_ok=True)

    index = json.loads((src_cache / "index.json").read_text())
    pub_ids = {w["id"] for w in cfg["workloads"] if w["split"] == "public"}
    missing = sorted(pub_ids - set(index["workloads"]))
    if missing:
        raise GraderError(f"missing public workloads in cache: {missing}")

    out_index = {
        "rom_sha256": index["rom_sha256"],
        "contract": index.get("contract", cfg.get("contract", "pips-garden")),
        "protected": index["protected"],
        "workloads": {wid: index["workloads"][wid] for wid in sorted(pub_ids)},
        "variants": index.get("variants", []),
    }
    if "o2_reference" in index:
        out_index["o2_reference"] = {wid: index["o2_reference"][wid]
                                     for wid in sorted(pub_ids) if wid in index["o2_reference"]}
    for wid in sorted(pub_ids):
        shutil.copytree(src_cache / "runs" / wid, dst_cache / "runs" / wid)
    (dst_cache / "index.json").write_text(json.dumps(out_index, indent=1))


# --------------------------------------------------------------------- grade

def failure_details(gates):
    failures = []
    for name, gate in gates.items():
        if gate["pass"]:
            continue
        if "workloads" not in gate:
            failures.append({"gate": name, **{k: v for k, v in gate.items() if k != "pass"}})
            continue
        for workload, result in gate["workloads"].items():
            if not result["pass"]:
                failures.append({"gate": name, "workload": workload,
                                 **{k: None if isinstance(v, float) and not math.isfinite(v) else v
                                    for k, v in result.items() if k not in ("pass", "host_seconds")}})
    return failures


def play_runtime_smoke(rom, out, timeout):
    """Compare idle and controller-driven execution of the same linked PLAY ROM."""
    fields = 1200
    out.mkdir(parents=True, exist_ok=True)
    replay = out / "controller.txt"
    replay.write_text("".join(
        ("." if i < 120 else "S" if i % 120 < 50 else "A" if i % 120 < 100 else ".") + " 0 0\n"
        for i in range(fields)
    ))
    results = {}
    for mode, extra in (("idle", []), ("controller", ["--replay", str(replay)])):
        path = pathlib.Path(tempfile.mkdtemp(prefix=f"{mode}-", dir=out))
        # Let n64run create its output directory; nall rewrites existing paths.
        capture = path / "capture"
        cmd = ["n64run", "--rom", str(rom), "--out", str(capture), "--play-fields", str(fields), *extra]
        with (path / "stderr.txt").open("w") as errors:
            try:
                run = subprocess.run(cmd, stderr=errors, timeout=timeout)
            except subprocess.TimeoutExpired:
                return {"pass": False, "status": "host_timeout", "scenario": mode}
        report = capture / "result.json"
        result = json.loads(report.read_text()) if report.is_file() else {"status": "runner_error"}
        results[mode] = result
        if run.returncode or result["status"] != "completed" or result.get("vi_fields") != fields:
            return {"pass": False, "status": result["status"], "scenario": mode,
                    "returncode": run.returncode, "scenarios": results}
    different = results["idle"]["play_final_video_hash"] != results["controller"]["play_final_video_hash"]
    return {"pass": different, "status": "completed" if different else "no_controller_response",
            "scenarios": results}


def grade(args):
    t0 = time.time()
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    if args.play_smoke and not cfg.get("play_rom"):
        raise GraderError("PLAY runtime smoke is not supported for this target")
    cache = pathlib.Path(args.cache)
    index = json.loads((cache / "index.json").read_text())
    schema_name = cfg.get("contract", index.get("contract", "pips-garden"))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {
        "version": cfg["version"],
        "target": cfg.get("target", schema_name),
        "gates": {},
        "workloads": {},
        "rewards": {},
        "speedups": {},
    }

    def finish(status, reason=None):
        summary["status"] = status
        if reason:
            summary["reason"] = reason
        if status == "invalid":
            summary["failures"] = failure_details(summary["gates"])
            summary["rewards"] = {p: -1.0 for p in cfg["profiles"]}
            summary["speedups"] = {p: 0.0 for p in cfg["profiles"]}
        summary["grader_seconds"] = round(time.time() - t0, 1)
        (out / "summary.json").write_text(json.dumps(summary, indent=1))
        return summary

    # 1. integrity
    changed = [f for f in cfg["protected_files"]
               if not (pathlib.Path(args.source) / f).exists()
               or sha256(pathlib.Path(args.source) / f) != index["protected"][f]]
    summary["gates"]["integrity"] = {"pass": not changed, "modified": changed}
    if changed:
        return finish("invalid", f"protected files modified: {changed}")

    # 2. build. Private measurements require a separate build container.
    # Public local checks can build in-process with an artifact integrity check.
    isolated = args.built is not None
    if not isolated and (args.split != "public" or args.heldout):
        raise GraderError("held-out grading requires an isolated build; use scripts/grade.sh")
    items = workloads(args.corpus, cfg, args.split, args.heldout)
    missing = [w["id"] for w in items if w["id"] not in index["workloads"]]
    if missing:
        raise GraderError(f"no baseline reference for {missing}; run precompute with this split")
    replay_hashes = {w["id"]: sha256(w["replay"]) for w in items}
    mismatches = [wid for wid, digest in replay_hashes.items()
                  if index["workloads"][wid]["replay_sha256"] != digest]
    if mismatches:
        raise GraderError(f"replay differs from the baseline reference: {mismatches}")
    summary["workload_set"] = hashlib.sha256(
        json.dumps(replay_hashes, sort_keys=True).encode()
    ).hexdigest()
    trusted = None if isolated else measurement_artifacts(args.corpus, cache, items)
    if isolated:
        rom, build_err = load_submission_build(pathlib.Path(args.built))
    else:
        rom, build_err = build(args.source, cfg, out / "build.log", keep_play=args.play_smoke)
    if isolated and rom is not None and args.play_smoke and not (rom.parent / "play.z64").is_file():
        raise GraderError("PLAY=1 ROM missing from build handoff")
    summary["gates"]["build"] = {"pass": rom is not None, **({"reason": build_err} if build_err else {})}
    if rom is None:
        return finish("invalid", build_err or "build failed; see build.log")
    if not isolated and measurement_artifacts(args.corpus, cache, items) != trusted:
        raise GraderError("the submission's build modified grading artifacts "
                          "(the emulator, the grader, the corpus, the reference cache or the replays)")
    try:
        summary["rom_sha256"] = sha256(rom)
        summary["rom_bytes"] = rom.stat().st_size
        if args.play_smoke:
            result = play_runtime_smoke(rom.parent / "play.z64", out / "play-smoke", cfg["run_timeout_s"])
            summary["gates"]["play_runtime"] = result
            if not result["pass"]:
                return finish("invalid", f"PLAY=1 runtime smoke failed: {result['status']}")

        # 3. run
        budget = lambda wid: int(index["workloads"][wid]["vi_fields"] * cfg["max_fields_factor"]) + 600
        results = run_all(rom, items, cfg["frames"], out / "runs", budget, cfg["run_timeout_s"])
    finally:
        if not isolated:
            shutil.rmtree(rom.parent, ignore_errors=True)

    execution, gameplay, video, audio, hardware = {}, {}, {}, {}, {}
    for w in items:
        wid, res = w["id"], results[w["id"]]
        execution[wid] = {"pass": res.get("status") == "completed", **res}
        if not execution[wid]["pass"]:
            continue
        cand = load_run(out / "runs" / wid)
        ref_dir = cache / "runs" / wid
        ref = load_run(ref_dir)
        gameplay[wid] = compare_obs(ref["obs"], cand["obs"], cfg["frames"], schema_name, cfg)
        video[wid] = compare_video(ref_dir, reference_variants(index["workloads"][wid], index.get("variants", [])),
                                   cand["video_path"], ref["rows"], cand["rows"], cfg)
        audio[wid] = compare_audio(ref["audio"], cand["audio"], ref["rows"], cand["rows"], cfg)
        m = metrics(cand)
        hardware[wid] = {"pass": m["highest_byte"] <= cfg["hardware"]["rdram_bytes"],
                         "highest_byte": m["highest_byte"], "limit_bytes": cfg["hardware"]["rdram_bytes"]}
        base = index["workloads"][wid]["metrics"]
        summary["workloads"][wid] = {
            "metrics": m,
            "ratios": {k: (m[k] / base[k] if base.get(k) else 1.0) for k in RATIO_KEYS},
        }
        (out / "runs" / wid / "video.bin").unlink()

    for name, table in (("execution", execution), ("gameplay", gameplay), ("video", video),
                        ("audio", audio), ("hardware", hardware)):
        summary["gates"][name] = {"pass": len(table) == len(items) and all(v["pass"] for v in table.values()),
                                  "workloads": table}
    failed = [g for g, v in summary["gates"].items() if not v["pass"]]
    if failed:
        return finish("invalid", f"failed gates: {failed}")

    # 4. rewards and unbounded/log speedups, one per profile
    speed_ratios = [summary["workloads"][w["id"]]["ratios"]["cpu_effective_cycles"] for w in items]
    rdp_ratios = [summary["workloads"][w["id"]]["ratios"]["rdp_busy"] for w in items]
    footprint_ratios = [summary["workloads"][w["id"]]["ratios"]["footprint_bytes"] for w in items]
    o2_ref = index.get("o2_reference", {})

    for profile, pcfg in cfg["profiles"].items():
        metric_key = pcfg["metric"]
        ratios = [summary["workloads"][w["id"]]["ratios"][metric_key] for w in items]
        geo = math.exp(sum(math.log(max(r, 1e-12)) for r in ratios) / len(ratios))
        entry = {"metric": metric_key, "geomean_ratio": geo}
        worst = max(ratios)
        worst_id = items[ratios.index(worst)]["id"]
        if worst > 1.0 + pcfg["max_workload_regression"] + 1e-12:
            entry.update(valid=False, reason=f"{metric_key} regressed {100 * (worst - 1):.3g}% on {worst_id} "
                                             f"(limit {100 * pcfg['max_workload_regression']:g}%)")
        elif "speed_budget" in pcfg and max(speed_ratios) > 1.0 + pcfg["speed_budget"] + 1e-12:
            slow_id = items[speed_ratios.index(max(speed_ratios))]["id"]
            entry.update(valid=False, reason=f"frame time regressed {100 * (max(speed_ratios) - 1):.3g}% on {slow_id} "
                                             f"(budget {100 * pcfg['speed_budget']:g}%)")
        elif "rdp_budget" in pcfg and max(rdp_ratios) > 1.0 + pcfg["rdp_budget"] + 1e-12:
            rdp_id = items[rdp_ratios.index(max(rdp_ratios))]["id"]
            entry.update(valid=False, reason=f"rdp_busy regressed {100 * (max(rdp_ratios) - 1):.3g}% on {rdp_id} "
                                             f"(budget {100 * pcfg['rdp_budget']:g}%)")
        elif "footprint_budget" in pcfg and max(footprint_ratios) > 1.0 + pcfg["footprint_budget"] + 1e-12:
            mem_id = items[footprint_ratios.index(max(footprint_ratios))]["id"]
            entry.update(valid=False, reason=f"footprint_bytes regressed {100 * (max(footprint_ratios) - 1):.3g}% on {mem_id} "
                                             f"(budget {100 * pcfg['footprint_budget']:g}%)")
        else:
            entry.update(valid=True)

        # Reward is log-scaled so that 2x, 4x and 8x stay clearly apart:
        # log2(speedup) / reward_log2_scale (default 4, so 16x scores 1.0).
        # Not capped above; any failed gate or budget scores -1.
        scale = cfg.get("reward_log2_scale", 4.0)
        entry["speedup"] = round(1.0 / geo, 6) if entry["valid"] and geo > 0 else 0.0
        entry["log2_speedup"] = round(-math.log2(geo), 6) if entry["valid"] and geo > 0 else None
        entry["reward"] = max(-1.0, entry["log2_speedup"] / scale) if entry["valid"] else -1.0

        if o2_ref and all(w["id"] in o2_ref for w in items):
            o2_ratios = [
                (summary["workloads"][w["id"]]["metrics"][metric_key] / o2_ref[w["id"]][metric_key]
                 if o2_ref[w["id"]].get(metric_key) else 1.0)
                for w in items
            ]
            o2_geo = math.exp(sum(math.log(max(r, 1e-12)) for r in o2_ratios) / len(o2_ratios))
            entry["vs_o2_ratio"] = o2_geo
            entry["vs_o2_speedup"] = round(1.0 / o2_geo, 6) if entry["valid"] and o2_geo > 0 else 0.0

        summary["rewards"][profile] = entry["reward"]
        summary["speedups"][profile] = entry["speedup"]
        summary.setdefault("profiles", {})[profile] = entry
    return finish("valid")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_pre = sub.add_parser("precompute")
    p_pre.add_argument("source")
    p_pre.add_argument("--corpus", required=True)
    p_pre.add_argument("--cache", required=True)
    p_pre.add_argument("--split", default="public", choices=["public", "heldout", "all"])
    p_pre.add_argument("--heldout")
    p_pre.add_argument("--o2-patch")

    p_build = sub.add_parser("build")
    p_build.add_argument("source")
    p_build.add_argument("--config", required=True)
    p_build.add_argument("--out", required=True)
    p_build.add_argument("--play-smoke", action="store_true", help="retain the linked PLAY=1 ROM")

    p_grd = sub.add_parser("grade")
    p_grd.add_argument("source")
    p_grd.add_argument("--corpus", required=True)
    p_grd.add_argument("--cache", required=True)
    p_grd.add_argument("--split", default="public", choices=["public", "heldout", "all"])
    p_grd.add_argument("--heldout")
    p_grd.add_argument("--out", required=True)
    p_grd.add_argument("--built", help="isolated build handoff directory")
    p_grd.add_argument("--play-smoke", action="store_true", help="require the PLAY=1 ROM to boot and render")

    p_exp = sub.add_parser("export-public")
    p_exp.add_argument("--corpus", required=True)
    p_exp.add_argument("--cache", required=True)
    p_exp.add_argument("--out", required=True)

    args = ap.parse_args()
    try:
        if args.cmd == "precompute":
            precompute(args)
        elif args.cmd == "build":
            build_submission(args)
        elif args.cmd == "export-public":
            export_public(args)
        else:
            s = grade(args)
            print(json.dumps({
                "status": s["status"],
                "reason": s.get("reason"),
                **({"failures": s["failures"]} if s.get("failures") else {}),
                "rewards": s["rewards"],
                "speedups": s.get("speedups"),
            }, indent=1))
    except GraderError as e:
        print(json.dumps({"status": "grader_error", "reason": str(e)}), file=sys.stderr)
        if args.cmd == "grade":
            pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
            (pathlib.Path(args.out) / "summary.json").write_text(
                json.dumps({"status": "grader_error", "reason": str(e)}, indent=1))
        sys.exit(3)


if __name__ == "__main__":
    main()
