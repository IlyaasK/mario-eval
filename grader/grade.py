#!/usr/bin/env python3
"""mario-eval grader.

    python3 -m grader.grade precompute BASELINE_SRC --corpus DIR --cache DIR
    python3 -m grader.grade grade SUBMISSION_SRC --corpus DIR --cache DIR --out DIR
                            [--split public|heldout|all] [--heldout DIR]

A submission is a source tree (a modified copy of workload/). The grader:
  1. checks the protected harness files are unchanged,
  2. rebuilds the ROM itself with the pinned toolchain,
  3. runs every workload under n64run (ares, CPU interpreter, unthrottled),
  4. gates on gameplay (bit-exact), video and audio (tolerances), hardware
     limits and execution, then
  5. measures resource cost against the baseline and emits one reward per
     optimization profile.

summary.json "status" is "valid", "invalid" (the submission failed a gate:
reward -1 for every profile) or "grader_error" (infrastructure failure: no
reward; rerun).
"""
import argparse
import concurrent.futures
import hashlib
import json
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

AUDIO_BYTES_PER_FRAME = 512 * 2 * 2
HW_DEVICES = ["VR4300 ICache", "VR4300 DCache", "VR4300 Uncached", "SP DMA",
              "PI DMA", "SI DMA", "VI DMA", "AI DMA", "DP DMA", "DP Draw"]


class GraderError(Exception):
    """Infrastructure failure: not the submission's fault."""


# --------------------------------------------------------------------- build

def sha256(path):
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def build(src, cfg, log_path):
    """Copy src to a scratch dir, build it, return the ROM path (or None)."""
    work = pathlib.Path(tempfile.mkdtemp(prefix="mev-build-"))
    shutil.copytree(src, work / "src", ignore=shutil.ignore_patterns("build", "*.z64"))
    try:
        proc = subprocess.run(["make", "-j", str(os.cpu_count() or 4)], cwd=work / "src",
                              capture_output=True, text=True, timeout=cfg["build_timeout_s"])
    except subprocess.TimeoutExpired:
        pathlib.Path(log_path).write_text("build timed out\n")
        return None
    pathlib.Path(log_path).write_text(proc.stdout + proc.stderr)
    rom = work / "src" / cfg["rom"]
    if proc.returncode != 0 or not rom.exists():
        return None
    return rom


# ----------------------------------------------------------------------- run

def run_workload(rom, replay, frames, out_dir, max_fields, timeout):
    out_dir = pathlib.Path(out_dir)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    cmd = ["n64run", "--rom", str(rom), "--replay", str(replay), "--out", str(out_dir),
           "--frames", str(frames), "--max-fields", str(max_fields)]
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


def metrics(run):
    """Per-frame costs over frames 1..N-1 (frame 0 includes boot and setup)."""
    rows = run["rows"]
    ticks = np.array([b["count_ticks"] - a["count_ticks"] for a, b in zip(rows, rows[1:])], dtype=np.float64)
    rsp = np.array([busy_rsp(b) - busy_rsp(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    traffic = np.array([rdram_bytes(b) - rdram_bytes(a) for a, b in zip(rows, rows[1:])], dtype=np.float64)
    last, first = rows[-1], rows[0]
    per_device = {d: (sum(last["rdram"].get(d, (0, 0))) - sum(first["rdram"].get(d, (0, 0)))) / (len(rows) - 1)
                  for d in HW_DEVICES}
    return {
        "frame_ticks": float(ticks.mean()),
        "frame_ticks_p99": float(np.percentile(ticks, 99)),
        "frame_ms": float(ticks.mean() / 46875.0),
        "vi_fields_per_frame": float(ticks.mean() / 781250.0),
        "cpu_cycles": float(ticks.mean() * 2),
        "rsp_busy": float(rsp.mean()),
        "rdram_bytes": float(traffic.mean()),
        "rdram_bytes_by_device": per_device,
        "dcache_misses": (last["dcache_misses"] - first["dcache_misses"]) / (len(rows) - 1),
        "icache_misses": (last["icache_misses"] - first["icache_misses"]) / (len(rows) - 1),
        "footprint_bytes": run["result"]["footprint_bytes"],
        "highest_byte": (run["result"]["highest_line"] + 1) * 16,
    }


# --------------------------------------------------------------- comparisons

def compare_obs(ref, cand, frames):
    n = contract.SIZE
    for i in range(frames):
        r, c = ref[i * n:(i + 1) * n], cand[i * n:(i + 1) * n]
        if r != c:
            diff = contract.first_difference(r, c)
            return {"pass": False, "frame": i, "field": diff[0], "ref": diff[1], "cand": diff[2]}
    return {"pass": True}


def decode_rgba16(buf, w, h):
    a = np.frombuffer(buf, dtype=">u2").reshape(h, w).astype(np.int16)
    return np.stack([(a >> 11) & 31, (a >> 6) & 31, (a >> 1) & 31], axis=-1)


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


def compare_video(ref_video, cand_path, rows, cfg):
    w, h, bpp = rows[0]["fb"]
    size = w * h * bpp // 8
    worst = (0.0, -1)
    with open(cand_path, "rb") as f:
        for i, row in enumerate(rows):
            if row["fb"] != [w, h, bpp]:
                return {"pass": False, "frame": i, "reason": f"framebuffer format changed to {row['fb']}"}
            cand = f.read(size)
            ref = ref_video[i * size:(i + 1) * size]
            if cand == ref:
                continue
            a, b = decode_rgba16(ref, w, h), decode_rgba16(cand, w, h)
            tol = cfg["video"]["channel_tolerance"]
            bad = unmatched(b, a, tol) | unmatched(a, b, tol)
            frac = float(bad.mean())
            if frac > worst[0]:
                worst = (frac, i)
    ok = worst[0] <= cfg["video"]["max_bad_fraction"]
    return {"pass": ok, "worst_bad_fraction": worst[0], "worst_frame": worst[1]}


def compare_audio(ref, cand, cfg):
    a = np.frombuffer(ref, dtype=">i2").astype(np.float64)
    b = np.frombuffer(cand, dtype=">i2").astype(np.float64)
    if a.shape != b.shape:
        return {"pass": False, "reason": "audio length differs"}
    err = a - b
    snr = math.inf if not err.any() else 10 * math.log10(max((a * a).sum(), 1.0) / (err * err).sum())
    acfg = cfg["audio"]
    per = AUDIO_BYTES_PER_FRAME // 2
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

def precompute(args):
    cfg = json.loads((pathlib.Path(args.corpus) / "grader.json").read_text())
    cache = pathlib.Path(args.cache)
    cache.mkdir(parents=True, exist_ok=True)
    rom = build(args.source, cfg, cache / "build.log")
    if rom is None:
        raise GraderError("baseline failed to build; see build.log")
    items = workloads(args.corpus, cfg, args.split, args.heldout)
    generous = lambda _id: cfg["frames"] * 600
    results = run_all(rom, items, cfg["frames"], cache / "runs", generous, cfg["run_timeout_s"])
    index = {"rom_sha256": sha256(rom), "protected": {}, "workloads": {}}
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
        index["workloads"][w["id"]] = {"replay_sha256": sha256(w["replay"]),
                                       "vi_fields": res["vi_fields"],
                                       "metrics": metrics(load_run(run_dir))}
    (cache / "index.json").write_text(json.dumps(index, indent=1))
    print(json.dumps({k: v["metrics"]["vi_fields_per_frame"] for k, v in index["workloads"].items()}, indent=1))


# --------------------------------------------------------------------- grade

def grade(args):
    t0 = time.time()
    corpus = pathlib.Path(args.corpus)
    cfg = json.loads((corpus / "grader.json").read_text())
    cache = pathlib.Path(args.cache)
    index = json.loads((cache / "index.json").read_text())
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    summary = {"version": cfg["version"], "gates": {}, "workloads": {}, "rewards": {}}

    def finish(status, reason=None):
        summary["status"] = status
        if reason:
            summary["reason"] = reason
        if status == "invalid":
            summary["rewards"] = {p: -1.0 for p in cfg["profiles"]}
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
    rom = build(args.source, cfg, out / "build.log")
    summary["gates"]["build"] = {"pass": rom is not None}
    if rom is None:
        return finish("invalid", "build failed; see build.log")
    summary["rom_sha256"] = sha256(rom)
    summary["rom_bytes"] = rom.stat().st_size

    # 3. run
    items = workloads(args.corpus, cfg, args.split, args.heldout)
    missing = [w["id"] for w in items if w["id"] not in index["workloads"]]
    if missing:
        raise GraderError(f"no baseline reference for {missing}; run precompute with this split")
    budget = lambda wid: int(index["workloads"][wid]["vi_fields"] * cfg["max_fields_factor"]) + 600
    results = run_all(rom, items, cfg["frames"], out / "runs", budget, cfg["run_timeout_s"])

    execution, gameplay, video, audio, hardware = {}, {}, {}, {}, {}
    for w in items:
        wid, res = w["id"], results[w["id"]]
        execution[wid] = {"pass": res.get("status") == "completed", **res}
        if not execution[wid]["pass"]:
            continue
        cand = load_run(out / "runs" / wid)
        ref_dir = cache / "runs" / wid
        ref = load_run(ref_dir)
        ref_video = zlib.decompress((ref_dir / "video.bin.z").read_bytes())
        gameplay[wid] = compare_obs(ref["obs"], cand["obs"], cfg["frames"])
        video[wid] = compare_video(ref_video, cand["video_path"], cand["rows"], cfg)
        audio[wid] = compare_audio(ref["audio"], cand["audio"], cfg)
        m = metrics(cand)
        hardware[wid] = {"pass": m["highest_byte"] <= cfg["hardware"]["rdram_bytes"],
                         "highest_byte": m["highest_byte"]}
        base = index["workloads"][wid]["metrics"]
        summary["workloads"][wid] = {
            "metrics": m,
            "ratios": {k: (m[k] / base[k] if base[k] else 1.0)
                       for k in ("frame_ticks", "frame_ticks_p99", "rsp_busy", "rdram_bytes", "footprint_bytes")},
        }
        (out / "runs" / wid / "video.bin").unlink()

    for name, table in (("execution", execution), ("gameplay", gameplay), ("video", video),
                        ("audio", audio), ("hardware", hardware)):
        summary["gates"][name] = {"pass": len(table) == len(items) and all(v["pass"] for v in table.values()),
                                  "workloads": table}
    failed = [g for g, v in summary["gates"].items() if not v["pass"]]
    if failed:
        return finish("invalid", f"failed gates: {failed}")

    # 4. rewards, one per profile
    speed_ratios = [summary["workloads"][w["id"]]["ratios"]["frame_ticks"] for w in items]
    for profile, pcfg in cfg["profiles"].items():
        ratios = [summary["workloads"][w["id"]]["ratios"][pcfg["metric"]] for w in items]
        geo = math.exp(sum(math.log(r) for r in ratios) / len(ratios))
        entry = {"metric": pcfg["metric"], "geomean_ratio": geo}
        worst = max(ratios)
        worst_id = items[ratios.index(worst)]["id"]
        if worst > 1.0 + pcfg["max_workload_regression"] + 1e-12:
            entry.update(valid=False, reason=f"{pcfg['metric']} regressed {100 * (worst - 1):.3g}% on {worst_id} "
                                             f"(limit {100 * pcfg['max_workload_regression']:g}%)")
        elif "speed_budget" in pcfg and max(speed_ratios) > 1.0 + pcfg["speed_budget"]:
            slow_id = items[speed_ratios.index(max(speed_ratios))]["id"]
            entry.update(valid=False, reason=f"frame time regressed {100 * (max(speed_ratios) - 1):.3g}% on {slow_id} "
                                             f"(budget {100 * pcfg['speed_budget']:g}%)")
        else:
            entry.update(valid=True)
        entry["reward"] = max(-1.0, min(1.0, 1.0 - geo)) if entry["valid"] else -1.0
        summary["rewards"][profile] = entry["reward"]
        summary.setdefault("profiles", {})[profile] = entry
    return finish("valid")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("precompute", "grade"):
        p = sub.add_parser(name)
        p.add_argument("source")
        p.add_argument("--corpus", required=True)
        p.add_argument("--cache", required=True)
        p.add_argument("--split", default="public", choices=["public", "heldout", "all"])
        p.add_argument("--heldout")
        if name == "grade":
            p.add_argument("--out", required=True)
    args = ap.parse_args()
    try:
        if args.cmd == "precompute":
            precompute(args)
        else:
            s = grade(args)
            print(json.dumps({"status": s["status"], "reason": s.get("reason"), "rewards": s["rewards"]}, indent=1))
    except GraderError as e:
        print(json.dumps({"status": "grader_error", "reason": str(e)}), file=sys.stderr)
        if args.cmd == "grade":
            pathlib.Path(args.out).mkdir(parents=True, exist_ok=True)
            (pathlib.Path(args.out) / "summary.json").write_text(
                json.dumps({"status": "grader_error", "reason": str(e)}, indent=1))
        sys.exit(3)


if __name__ == "__main__":
    main()
