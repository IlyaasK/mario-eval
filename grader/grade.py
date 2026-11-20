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
import shutil
import subprocess
import sys
import tempfile
import time
import zlib

import numpy as np

from grader import contract

HW_DEVICES = ["VR4300 ICache", "VR4300 DCache", "VR4300 Uncached", "SP DMA",
              "PI DMA", "SI DMA", "VI DMA", "AI DMA", "DP DMA", "DP Draw"]
RATIO_KEYS = ("est_console_ms", "cpu_effective_cycles", "cpu_busy_cycles", "frame_ticks", "frame_ticks_p99", "rdp_busy", "rsp_busy",
              "rdram_bytes", "footprint_bytes")


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


def build(src, cfg, log_path):
    """Copy src to a scratch dir, build it (plus optional play_build_cmd), return (rom_bytes_path, reason)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="mev-build-"))
    out_rom = work / "built.z64"
    try:
        _copy_source(src, work / "src")
        jobs = str(os.cpu_count() or 4)
        base_cmd = cfg.get("build_cmd", ["make"])
        cmd = [base_cmd[0], f"-j{jobs}", *base_cmd[1:]] if base_cmd[0] == "make" else list(base_cmd)
        try:
            proc = subprocess.run(cmd, cwd=work / "src", capture_output=True, text=True,
                                  timeout=cfg["build_timeout_s"])
        except subprocess.TimeoutExpired:
            pathlib.Path(log_path).write_text("build timed out\n")
            shutil.rmtree(work, ignore_errors=True)
            return None, "build timed out"

        logs = [proc.stdout + proc.stderr]
        rom = work / "src" / cfg["rom"]
        if proc.returncode != 0 or not rom.exists():
            pathlib.Path(log_path).write_text("".join(logs))
            shutil.rmtree(work, ignore_errors=True)
            return None, "build failed; see build.log"

        shutil.copy2(rom, out_rom)
        idle = idle_ranges(work / "src" / cfg["elf"], cfg.get("idle_symbols", [])) if cfg.get("elf") else []
        (work / "built.idle.json").write_text(json.dumps(idle))

        play_cmd = cfg.get("play_build_cmd")
        if play_cmd:
            shutil.rmtree(work / "src" / "build", ignore_errors=True)
            pcmd = [play_cmd[0], f"-j{jobs}", *play_cmd[1:]] if play_cmd[0] == "make" else list(play_cmd)
            try:
                pproc = subprocess.run(pcmd, cwd=work / "src", capture_output=True, text=True,
                                       timeout=cfg["build_timeout_s"])
            except subprocess.TimeoutExpired:
                logs.append("\n--- play build timed out ---\n")
                pathlib.Path(log_path).write_text("".join(logs))
                shutil.rmtree(work, ignore_errors=True)
                return None, "console PLAY=1 build timed out"
            logs.append("\n--- play build ---\n" + pproc.stdout + pproc.stderr)
            if pproc.returncode != 0:
                pathlib.Path(log_path).write_text("".join(logs))
                shutil.rmtree(work, ignore_errors=True)
                return None, "console PLAY=1 build failed; see build.log"

        pathlib.Path(log_path).write_text("".join(logs))
        shutil.rmtree(work / "src", ignore_errors=True)
        return out_rom, None
    except Exception:
        shutil.rmtree(work, ignore_errors=True)
        raise


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
RDRAM_BYTES_PER_MS = 500_000.0    # RDRAM peak, 500 MB/s: a floor on any frame's bus time
FIELD_MS = 1000.0 / 60.0
# Extra CPU cycles charged per cache miss or write-back for waiting on the
# shared RDRAM bus while the RSP/RDP use it. ares charges an uncontended
# 40-48 cycles; Kaze Emanuar measures ~40-60 on a quiet bus and "hundreds" on
# a busy one. Fitted (one constant, displayed FPS) to his console measurements
# of vanilla SM64: JRB 19.9-20.5, DDD 23.7-24.1, RR 25.9-26.8 FPS
# (youtu.be/Ca1hHC2EctY @3:55); the model gives 20.0, 25.7, 26.5.
BUS_CONTENTION_CYCLES = 24.0


def metrics(run):
    """Per-frame costs over frames 1..N-1 (frame 0 includes boot and setup).

    The benchmark build runs each frame's stages one after another. On a
    console, SM64 overlaps them: the CPU builds frame N+1 while the RSP and RDP
    draw frame N, all sharing RDRAM. So a frame's console cost is estimated as
    the busiest unit: max(CPU, RSP busy, RDP busy, RDRAM time at peak
    bandwidth). CPU time excludes the idle thread (waiting for the RCP) and
    adds BUS_CONTENTION_CYCLES per cache miss/write-back. The RDP model is
    approximate (see docs/n64-cost-model.md).
    """
    rows = run["rows"]
    d = lambda key: np.array([b.get(key, 0) - a.get(key, 0) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    ticks = d("count_ticks")
    idle = d("cpu_idle_cycles")
    cpu_busy = ticks - idle
    bus_events = d("icache_misses") + d("dcache_misses") + d("dcache_writebacks")
    cpu_eff = cpu_busy + BUS_CONTENTION_CYCLES * bus_events
    rsp = np.array([busy_rsp(b) - busy_rsp(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    rdp = d("rdp_cycles")
    traffic = np.array([rdram_bytes(b) - rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    last, first = rows[-1], rows[0]
    per_device = {dev: (sum(last["rdram"].get(dev, (0, 0))) - sum(first["rdram"].get(dev, (0, 0)))) / (len(rows) - 1)
                  for dev in HW_DEVICES}
    cpu_ms_f = cpu_eff / CPU_CYCLES_PER_MS
    rsp_ms_f = rsp / RSP_UNITS_PER_MS
    rdp_ms_f = rdp / RDP_CYCLES_PER_MS
    mem_ms_f = traffic / RDRAM_BYTES_PER_MS
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
    # Final frame stats must match without window slack so coins/health/stars at route end are exact.
    if "mario_stats" in win_fields and cand_frames[-1].get("mario_stats") != ref_frames[-1].get("mario_stats"):
        return {"pass": False, "frame": frames - 1, "field": "mario_stats",
                "ref": ref_frames[-1].get("mario_stats"), "cand": cand_frames[-1].get("mario_stats")}
    return {"pass": True, "max_pos_drift": round(worst_drift, 4)}


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


def compare_video(ref_videos, cand_path, ref_rows, cand_rows, cfg):
    """ref_videos[0] is the original; the rest are accepted visual variants.

    Each frame must match, as a whole frame within tolerance, either the
    original picture or one of the accepted visual variants (preventing
    half-original / half-variant per-pixel mixing within a single frame).
    """
    w, h, bpp = ref_rows[0]["fb"]
    size = w * h * bpp // 8
    tol = cfg["video"]["channel_tolerance"]
    limit = cfg["video"]["max_bad_fraction"]
    worst = (0.0, -1)
    variant_frames = 0
    with open(cand_path, "rb") as f:
        for i, row in enumerate(cand_rows):
            if row["fb"] != [w, h, bpp]:
                return {"pass": False, "frame": i, "reason": f"framebuffer format changed to {row['fb']}"}
            cand = f.read(size)
            refs = [v[i * size:(i + 1) * size] for v in ref_videos]
            if cand == refs[0]:
                continue
            if cand in refs[1:]:
                variant_frames += 1
                continue
            c = decode_frame(cand, w, h, bpp)
            orig_frac = float(mismatch(c, decode_frame(refs[0], w, h, bpp), tol).mean())
            frac = orig_frac
            for ref in refs[1:]:
                v_frac = float(mismatch(c, decode_frame(ref, w, h, bpp), tol).mean())
                if v_frac < frac:
                    frac = v_frac
            if orig_frac > limit and frac <= limit:
                variant_frames += 1
            if frac > worst[0]:
                worst = (frac, i)
    ok = worst[0] <= limit
    return {"pass": ok, "worst_bad_fraction": worst[0], "worst_frame": worst[1], "variant_frames": variant_frames}


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
    return {"pass": ok, "snr_db": snr, "worst_frame_snr_db": worst[0], "worst_frame": worst[1]}


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


def variant_combinations(cfg):
    """Every non-empty combination of the atomic accepted visual changes.

    The video gate matches each frame as a whole against one reference, so a
    submission that uses several accepted changes needs a reference with
    exactly that combination. Returns [(id, [patch, ...]), ...]."""
    atoms = cfg.get("accepted_visual_variants", [])
    out = []
    for r in range(1, len(atoms) + 1):
        for combo in itertools.combinations(atoms, r):
            out.append(("+".join(v["id"] for v in combo), [v["patch"] for v in combo]))
    return out


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

    # Accepted visual variants: the baseline with each combination of the
    # listed visual changes applied. Each must leave gameplay bit-exact and
    # audio within the audio gate (a microcode swap shifts RSP task timing,
    # which can move a few samples by a few LSBs); only its video is kept, as
    # an extra reference for the video gate.
    for variant_id, patches in variant_combinations(cfg):
        variant = {"id": variant_id}
        vwork = patched_copy(args.source, [(corpus / p).resolve() for p in patches])
        vrom = None
        try:
            vrom, verr = build(vwork / "src", cfg, cache / f"build-{variant['id']}.log")
            if vrom is None:
                raise GraderError(f"variant {variant['id']} failed to build: {verr}")
            vdir = cache / "variant-runs" / variant["id"]
            vres = run_all(vrom, items, cfg["frames"], vdir, generous, cfg["run_timeout_s"])
            for w in items:
                if vres[w["id"]].get("status") != "completed":
                    raise GraderError(f"variant {variant['id']} did not complete {w['id']}")
                base_run, var_run = load_run(cache / "runs" / w["id"]), load_run(vdir / w["id"])
                if base_run["obs"] != var_run["obs"]:
                    raise GraderError(f"variant {variant['id']} changes gameplay on {w['id']}; "
                                      "an accepted visual change must be visual only")
                au = compare_audio(base_run["audio"], var_run["audio"], base_run["rows"], var_run["rows"], cfg)
                if not au["pass"]:
                    raise GraderError(f"variant {variant['id']} changes audio on {w['id']}: {au}")
                if base_run["audio"] != var_run["audio"]:
                    print(f"variant {variant['id']} {w['id']}: audio SNR {au['snr_db']:.1f} dB", file=sys.stderr)
                video = (vdir / w["id"] / "video.bin").read_bytes()
                (cache / "runs" / w["id"] / f"video.{variant['id']}.bin.z").write_bytes(zlib.compress(video, 6))
            shutil.rmtree(vdir, ignore_errors=True)
            index["variants"].append(variant["id"])
        finally:
            if vrom is not None:
                shutil.rmtree(vrom.parent, ignore_errors=True)
            shutil.rmtree(vwork, ignore_errors=True)

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

def grade(args):
    t0 = time.time()
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
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

    # 2. build
    rom, build_err = build(args.source, cfg, out / "build.log")
    summary["gates"]["build"] = {"pass": rom is not None, **({"reason": build_err} if build_err else {})}
    if rom is None:
        return finish("invalid", build_err or "build failed; see build.log")
    try:
        summary["rom_sha256"] = sha256(rom)
        summary["rom_bytes"] = rom.stat().st_size

        # 3. run
        items = workloads(args.corpus, cfg, args.split, args.heldout)
        missing = [w["id"] for w in items if w["id"] not in index["workloads"]]
        if missing:
            raise GraderError(f"no baseline reference for {missing}; run precompute with this split")
        budget = lambda wid: int(index["workloads"][wid]["vi_fields"] * cfg["max_fields_factor"]) + 600
        results = run_all(rom, items, cfg["frames"], out / "runs", budget, cfg["run_timeout_s"])
    finally:
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
        ref_videos = [zlib.decompress((ref_dir / "video.bin.z").read_bytes())]
        ref_videos += [zlib.decompress((ref_dir / f"video.{v}.bin.z").read_bytes()) for v in index.get("variants", [])]
        gameplay[wid] = compare_obs(ref["obs"], cand["obs"], cfg["frames"], schema_name, cfg)
        video[wid] = compare_video(ref_videos, cand["video_path"], ref["rows"], cand["rows"], cfg)
        audio[wid] = compare_audio(ref["audio"], cand["audio"], ref["rows"], cand["rows"], cfg)
        m = metrics(cand)
        hardware[wid] = {"pass": m["highest_byte"] <= cfg["hardware"]["rdram_bytes"],
                         "highest_byte": m["highest_byte"]}
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

    p_grd = sub.add_parser("grade")
    p_grd.add_argument("source")
    p_grd.add_argument("--corpus", required=True)
    p_grd.add_argument("--cache", required=True)
    p_grd.add_argument("--split", default="public", choices=["public", "heldout", "all"])
    p_grd.add_argument("--heldout")
    p_grd.add_argument("--out", required=True)

    p_exp = sub.add_parser("export-public")
    p_exp.add_argument("--corpus", required=True)
    p_exp.add_argument("--cache", required=True)
    p_exp.add_argument("--out", required=True)

    args = ap.parse_args()
    try:
        if args.cmd == "precompute":
            precompute(args)
        elif args.cmd == "export-public":
            export_public(args)
        else:
            s = grade(args)
            print(json.dumps({
                "status": s["status"],
                "reason": s.get("reason"),
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
