#!/usr/bin/env python3
"""Generate 3-panel (Reference | Candidate | Difference) MP4 clips and per-frame
telemetry JSON for the Mario Eval homepage using Super Mario 64 public routes.

Captures only rendered gameplay video (MP4) and emulator timing telemetry — no
ROMs, Nintendo source code, or extracted assets are ever written to the site.
"""
import concurrent.futures
import json
import pathlib
import shutil
import subprocess
import tempfile
import zlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "site" / "assets" / "clips"
REF_CACHE = ROOT / "cache" / "sm64-reference" / "runs"
KIMI_BUNDLE = ROOT / "results" / "kimi-k3.1-pro-cerebras-24h-v2-cont" / "game.bundle"

CLIPS = [
    {
        "id": "sm64-kimi-bob",
        "kind": "bundle",
        "commit": "4b54858",
        "slug": "kimi-k3.1-pro (4b54858)",
        "route": "bob",
        "ref_variant": "ra-zb-opa+f3dex2",
        "tab": "Kimi K3.1 Pro · 1.73× (BoB)",
        "title": "Kimi K3.1 Pro Trial (best valid 25-route checkpoint) on Bob-omb Battlefield",
        "badge": "VALID · 1.695× (25 ROUTES)",
        "badge_cls": "valid",
        "caption": "Autonomous Kimi K3.1 Pro trial run (4b54858) on Bob-omb Battlefield: cuts frame time from 30.3 ms → 17.5 ms (57.1 FPS) while matching the accepted F3DEX2 + RA_ZB_OPA visual reference.",
    },
    {
        "id": "sm64-kaze-jrb",
        "kind": "patch",
        "patch": "r10-kaze-master.patch",
        "slug": "r10-kaze-master",
        "route": "jrb",
        "ref_variant": "ra-zb-opa+f3dex2+no-lod",
        "tab": "Kaze Master · 1.72× (JRB)",
        "title": "Kaze Master Reference (R10) on Jolly Roger Bay",
        "badge": "EXPERT REF · 1.68×",
        "badge_cls": "ref",
        "caption": "Reconstructed Kaze Emanuar expert reference on fill-heavy Jolly Roger Bay: cuts console frame time from 38.5 ms → 22.4 ms (44.6 FPS) with zero gameplay drift and pixel-faithful rendering.",
    },
    {
        "id": "sm64-cheat-lowpoly-jrb",
        "kind": "patch",
        "patch": "i2-low-poly-mario.patch",
        "slug": "i2-low-poly-mario",
        "route": "jrb",
        "ref_variant": "",
        "tab": "Caught Cheat · Low-Poly Mario",
        "title": "Rejected shortcut (force low-poly Mario) on Jolly Roger Bay",
        "badge": "REJECTED · VIDEO GATE",
        "badge_cls": "invalid",
        "caption": "Forces Mario's distant low-poly mesh at all distances: Mario's degraded silhouette lights up red in the difference panel (1.42% bad pixels > 0.20% limit) → reward −1.0.",
    },
    {
        "id": "sm64-cheat-physics-bob",
        "kind": "patch",
        "patch": "i3-half-physics-step.patch",
        "slug": "i3-half-physics-step",
        "route": "bob",
        "ref_variant": "",
        "tab": "Caught Cheat · Half Physics",
        "title": "Rejected shortcut (2 quarter-steps vs 4) on Bob-omb Battlefield",
        "badge": "REJECTED · GAMEPLAY + VIDEO",
        "badge_cls": "invalid",
        "caption": "Halves Mario's physics quarter-steps in mario_step.c: Mario diverges completely from the recorded Bob-omb Battlefield trajectory (10.44% bad pixels) → reward −1.0.",
    },
]


def decode_rgba16_rgb(buf, frames, w, h):
    a = np.frombuffer(buf, dtype=">u2").reshape(frames, h, w)
    r5 = (a >> 11) & 31
    g5 = (a >> 6) & 31
    b5 = (a >> 1) & 31
    r = ((r5 << 3) | (r5 >> 2)).astype(np.uint8)
    g = ((g5 << 3) | (g5 >> 2)).astype(np.uint8)
    b = ((b5 << 3) | (b5 >> 2)).astype(np.uint8)
    return np.stack([r, g, b], axis=-1)


def frame_console_ms(rows):
    HW = ["VR4300 ICache", "VR4300 DCache", "VR4300 Uncached", "SP DMA",
          "PI DMA", "SI DMA", "VI DMA", "AI DMA", "DP DMA", "DP Draw"]
    RCP = ("SP DMA", "PI DMA", "SI DMA", "DP DMA", "DP Draw")
    fb_w, fb_h, fb_bpp = rows[0]["fb"]
    vi_bytes = float(2 * fb_w * fb_h * (fb_bpp // 8))
    out = []
    for a, b in zip(rows, rows[1:]):
        cpu_busy = (b["count_ticks"] - a["count_ticks"]) - (b.get("cpu_idle_cycles", 0) - a.get("cpu_idle_cycles", 0))
        bus_ev = sum(b.get(k, 0) - a.get(k, 0) for k in ("icache_misses", "dcache_misses", "dcache_writebacks", "uncached_reads", "uncached_writes"))
        rcp_b = sum(sum(b["rdram"].get(d, (0, 0))) - sum(a["rdram"].get(d, (0, 0))) for d in RCP)
        tot_b = sum(sum(b["rdram"].get(d, (0, 0))) - sum(a["rdram"].get(d, (0, 0))) for d in HW)
        cpu_ms = (cpu_busy + (4.0 + 6.0 * (rcp_b / 1e6)) * bus_ev) / 93_750.0
        rsp_ms = ((b["rsp_cycles"] - b["rsp_halted_cycles"]) - (a["rsp_cycles"] - a["rsp_halted_cycles"])) / 187_500.0
        rdp_ms = (b.get("rdp_cycles", 0) - a.get("rdp_cycles", 0)) / 62_500.0
        mem_ms = (tot_b + vi_bytes) / 250_000.0
        out.append(round(max(cpu_ms, rsp_ms, rdp_ms, mem_ms), 2))
    return out


def copy_sm64_assets(dst):
    ignored = subprocess.check_output(
        ["git", "-C", str(ROOT / "sm64/decomp"), "ls-files", "-z", "--others", "--ignored", "--exclude-standard"]
    )
    for raw in ignored.split(b"\0"):
        if not raw:
            continue
        rel = raw.decode("utf-8", "surrogateescape")
        if rel == "build" or rel.startswith(("build/", "build_")):
            continue
        sp, dp = ROOT / "sm64/decomp" / rel, dst / rel
        if sp.is_file() and not dp.exists():
            dp.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dp)


def run_candidate(spec, work_root):
    cid = spec["id"]
    route = spec["route"]
    wdir = work_root / cid
    src = wdir / "src"
    if spec["kind"] == "bundle":
        repo_tmp = wdir / "repo"
        subprocess.run(["git", "clone", "-q", str(KIMI_BUNDLE), str(repo_tmp)], check=True)
        src.mkdir(parents=True)
        arch = subprocess.Popen(["git", "-C", str(repo_tmp), "archive", spec["commit"]], stdout=subprocess.PIPE)
        subprocess.run(["tar", "-x", "-C", str(src)], stdin=arch.stdout, check=True)
        arch.wait()
        copy_sm64_assets(src)
        shutil.rmtree(repo_tmp, ignore_errors=True)
    else:
        shutil.copytree(ROOT / "sm64/decomp", src, ignore=shutil.ignore_patterns(".git", "build", "build_*", "*.z64"))
        patch = ROOT / "sm64/calibration" / spec["patch"]
        subprocess.run(["patch", "-s", "-p1", "-d", str(src), "-i", str(patch)], check=True)

    run_out = wdir / "run"
    uid = subprocess.check_output(["id", "-u"], text=True).strip()
    gid = subprocess.check_output(["id", "-g"], text=True).strip()
    script = f"""
set -euo pipefail
cd /work/src
make -j$(nproc) VERSION=us COMPARE=0 NOEXTRACT=1 >/dev/null
IDLE=$(python3 -c '
import json, pathlib, sys
sys.path.insert(0, "/opt/mario-eval")
from grader.grade import idle_ranges
cfg = json.loads(pathlib.Path("/repo/sm64/corpus/grader.json").read_text())
for r in idle_ranges("/work/src/" + cfg["elf"], cfg.get("idle_symbols", [])):
    print("--idle-range " + r)
')
n64run --rom /work/src/build/us/sm64.us.z64 --replay /repo/sm64/corpus/replays/public/{route}.txt --out /work/run --frames 240 $IDLE >/dev/null
"""
    subprocess.run([
        "docker", "run", "--rm",
        "-u", f"{uid}:{gid}",
        "-v", f"{wdir}:/work",
        "-v", f"{ROOT}:/repo:ro",
        "mario-eval:latest", "bash", "-c", script,
    ], check=True)
    return spec, run_out


def resolve_ref_video_path(route, ref_variant):
    ref_dir = REF_CACHE / route
    if not ref_variant:
        return ref_dir / "video.bin.z"
    idx = json.loads((ROOT / "cache/sm64-reference/index.json").read_text())
    vmap = idx["workloads"][route].get("variants", {})
    stored = vmap.get(ref_variant, ref_variant)
    cand = ref_dir / f"video.{stored}.bin.z" if stored else ref_dir / "video.bin.z"
    return cand if cand.is_file() else (ref_dir / "video.bin.z")


def encode_clip(spec, cand_run_dir):
    route = spec["route"]
    ref_dir = REF_CACHE / route
    ref_rows = [json.loads(l) for l in (ref_dir / "frames.jsonl").read_text().splitlines() if l]
    cand_rows = [json.loads(l) for l in (cand_run_dir / "frames.jsonl").read_text().splitlines() if l]
    frames = min(len(ref_rows), len(cand_rows))
    w, h, _bpp = ref_rows[0]["fb"]

    # Left panel: always the original 1996 retail US baseline video
    orig_raw = zlib.decompress((ref_dir / "video.bin.z").read_bytes())[:frames * w * h * 2]
    # Diff reference: exact accepted variant video for valid variant builds, or baseline for cheats
    diff_ref_path = resolve_ref_video_path(route, spec.get("ref_variant", ""))
    diff_ref_raw = zlib.decompress(diff_ref_path.read_bytes())[:frames * w * h * 2]
    cand_raw = (cand_run_dir / "video.bin").read_bytes()[:frames * w * h * 2]

    orig_rgb = decode_rgba16_rgb(orig_raw, frames, w, h)
    diff_ref_rgb = decode_rgba16_rgb(diff_ref_raw, frames, w, h)
    cand_rgb = decode_rgba16_rgb(cand_raw, frames, w, h)

    # Compute vivid amplified difference panel against the grader's reference
    diff = np.abs(diff_ref_rgb.astype(np.int16) - cand_rgb.astype(np.int16))
    max_d = diff.max(axis=-1)
    diff_pct = [round(float((max_d[i] > 16).mean() * 100.0), 3) for i in range(frames)]

    diff_rgb = np.zeros_like(orig_rgb)
    diff_rgb[:, :, 0] = 6
    diff_rgb[:, :, 1] = 6
    diff_rgb[:, :, 2] = 10
    small = (max_d > 0) & (max_d <= 16)
    big = max_d > 16
    diff_rgb[small, 0] = 72
    diff_rgb[small, 1] = 62
    diff_rgb[small, 2] = 165
    mag = np.clip((max_d[big].astype(np.float32) - 16.0) / 88.0, 0.0, 1.0)
    diff_rgb[big, 0] = 255
    diff_rgb[big, 1] = (46 + mag * 188).astype(np.uint8)
    diff_rgb[big, 2] = (64 + np.maximum(0.0, mag - 0.45) * 340).clip(0, 255).astype(np.uint8)

    sep = np.full((frames, h, 1, 3), (46, 42, 58), dtype=np.uint8)
    comp = np.concatenate([orig_rgb, sep, cand_rgb, sep, diff_rgb], axis=2)  # (frames, 240, 962, 3)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mp4_path = OUT_DIR / f"{spec['id']}.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{comp.shape[2]}x{comp.shape[1]}", "-r", "30",
        "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart",
        str(mp4_path),
    ], stdin=subprocess.PIPE)
    ff.stdin.write(comp.tobytes())
    ff.stdin.close()
    rc = ff.wait()
    if rc != 0:
        raise RuntimeError(f"ffmpeg failed ({rc}) on {spec['id']}")

    base_ms = frame_console_ms(ref_rows[:frames])
    cand_ms = frame_console_ms(cand_rows[:frames])
    return {
        "id": spec["id"],
        "slug": spec["slug"],
        "route": route,
        "tab": spec["tab"],
        "title": spec["title"],
        "badge": spec["badge"],
        "badge_cls": spec["badge_cls"],
        "caption": spec["caption"],
        "video": f"{spec['id']}.mp4",
        "frames": frames,
        "fps": 30,
        "base_mean_ms": round(sum(base_ms) / len(base_ms), 1),
        "cand_mean_ms": round(sum(cand_ms) / len(cand_ms), 1),
        "max_diff_pct": round(max(diff_pct), 2),
        "base_ms": base_ms,
        "cand_ms": cand_ms,
        "diff_pct": diff_pct[1:],
        "bytes": mp4_path.stat().st_size,
    }


def main():
    # Clean old clips before generating the SM64 set
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mev-sm64-clips-"))
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=len(CLIPS)) as pool:
            runs = list(pool.map(lambda sp: run_candidate(sp, tmp), CLIPS))
        meta = []
        for spec, rdir in runs:
            info = encode_clip(spec, rdir)
            print(f"encoded {info['video']}: {info['bytes']/1024:.0f} KiB  "
                  f"base={info['base_mean_ms']}ms cand={info['cand_mean_ms']}ms max_diff={info['max_diff_pct']}%")
            meta.append(info)
        (OUT_DIR / "clips.json").write_text(json.dumps(meta, indent=1) + "\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    main()
