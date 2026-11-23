#!/usr/bin/env python3
"""Generate 3-panel (Reference | Candidate | Difference) MP4 clips and per-frame
telemetry JSON for the Mario Eval homepage using open-source Pip's Garden.

Zero Nintendo assets are ever touched or exported.
"""
import concurrent.futures
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import zlib

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "site" / "assets" / "clips"
REF_CACHE = ROOT / "cache" / "reference" / "runs"

CLIPS = [
    {
        "id": "r1-o2-storm",
        "slug": "r1-o2-ieee",
        "route": "storm",
        "tab": "Valid · 1.69× faster",
        "title": "Valid optimization (-O2 IEEE) on Storm",
        "badge": "VALID · 1.69×",
        "badge_cls": "valid",
        "caption": "Real hardware speedup (116.8 ms → 68.3 ms on Storm) with zero pixel, gameplay, or audio change. The difference panel stays pitch black across all 240 frames.",
    },
    {
        "id": "r7-lod-meadow",
        "slug": "r7-full-detail",
        "route": "meadow",
        "tab": "Valid Variant · Full-Detail LOD",
        "title": "Accepted visual variant (full-detail Pip) on Meadow",
        "badge": "ACCEPTED VARIANT",
        "badge_cls": "ref",
        "caption": "Mirrors Kaze Emanuar's high-poly Mario LOD change: always draws Pip at full detail. Extra silhouette detail glows vs vanilla, and passes against the accepted visual variant.",
    },
    {
        "id": "i2-particles-storm",
        "slug": "i2-no-particles",
        "route": "storm",
        "tab": "Caught Cheat · No Particles",
        "title": "Rejected shortcut (skip particles) on Storm",
        "badge": "REJECTED · VIDEO",
        "badge_cls": "invalid",
        "caption": "Drops rain & dash particles to shave ~33 ms/frame. Every missing particle lights up red in the difference panel (2.38% bad pixels > 0.20% limit) → reward −1.0.",
    },
    {
        "id": "i3-physics-storm",
        "slug": "i3-physics",
        "route": "storm",
        "tab": "Caught Cheat · Half Physics",
        "title": "Rejected shortcut (2 physics substeps vs 4) on Storm",
        "badge": "REJECTED · GAMEPLAY + VIDEO",
        "badge_cls": "invalid",
        "caption": "Cuts physics substeps in half: Pip drifts off the recorded trajectory within frames, creating a double-image divergence (4.42% bad pixels) → reward −1.0.",
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
    """Per-frame est_console_ms matching grader/grade.py."""
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


def run_candidate(spec, work_root):
    cid = spec["id"]
    slug = spec["slug"]
    route = spec["route"]
    wdir = work_root / cid
    src = wdir / "src"
    shutil.copytree(ROOT / "workload", src, ignore=shutil.ignore_patterns(".git", "build", "*.z64"))
    patch = ROOT / "calibration" / f"{slug}.patch"
    subprocess.run(["patch", "-s", "-p1", "-d", str(src), "-i", str(patch)], check=True)

    run_out = wdir / "run"
    # Build and run the single route inside mario-eval:latest (let n64run create /work/run)
    script = f"""
set -euo pipefail
cd /work/src
make -j$(nproc) >/dev/null
ROM=$(python3 -c 'import json, pathlib; print(json.loads(pathlib.Path("/repo/corpus/grader.json").read_text())["rom"])')
IDLE=$(python3 -c '
import json, pathlib, sys
sys.path.insert(0, "/opt/mario-eval")
from grader.grade import idle_ranges
cfg = json.loads(pathlib.Path("/repo/corpus/grader.json").read_text())
for r in idle_ranges("/work/src/" + cfg["elf"], cfg.get("idle_symbols", [])):
    print("--idle-range " + r)
')
n64run --rom "/work/src/$ROM" --replay /repo/corpus/replays/public/{route}.txt --out /work/run --frames 240 $IDLE >/dev/null
"""
    subprocess.run([
        "docker", "run", "--rm",
        "-u", f"{subprocess.check_output(['id', '-u'], text=True).strip()}:{subprocess.check_output(['id', '-g'], text=True).strip()}",
        "-v", f"{wdir}:/work",
        "-v", f"{ROOT}:/repo:ro",
        "mario-eval:latest", "bash", "-c", script,
    ], check=True)
    return spec, run_out


def encode_clip(spec, cand_run_dir):
    route = spec["route"]
    ref_dir = REF_CACHE / route
    ref_rows = [json.loads(l) for l in (ref_dir / "frames.jsonl").read_text().splitlines() if l]
    cand_rows = [json.loads(l) for l in (cand_run_dir / "frames.jsonl").read_text().splitlines() if l]
    frames = min(len(ref_rows), len(cand_rows))
    w, h, _bpp = ref_rows[0]["fb"]

    ref_raw = zlib.decompress((ref_dir / "video.bin.z").read_bytes())[:frames * w * h * 2]
    cand_raw = (cand_run_dir / "video.bin").read_bytes()[:frames * w * h * 2]

    ref_rgb = decode_rgba16_rgb(ref_raw, frames, w, h)
    cand_rgb = decode_rgba16_rgb(cand_raw, frames, w, h)

    # Compute vivid amplified difference panel (crimson -> amber -> white)
    diff = np.abs(ref_rgb.astype(np.int16) - cand_rgb.astype(np.int16))
    max_d = diff.max(axis=-1)  # 0..255
    diff_pct = [round(float((max_d[i] > 16).mean() * 100.0), 3) for i in range(frames)]

    diff_rgb = np.zeros_like(ref_rgb)
    # Dark slate floor so pitch-black = exact match
    diff_rgb[:, :, 0] = 6
    diff_rgb[:, :, 1] = 6
    diff_rgb[:, :, 2] = 10
    nz = max_d > 0
    # Subtle indigo for tiny 1-2 LSB rounding diffs, vivid red/amber/white for visible diffs
    small = (max_d > 0) & (max_d <= 16)
    big = max_d > 16
    diff_rgb[small, 0] = 90
    diff_rgb[small, 1] = 75
    diff_rgb[small, 2] = 190
    mag = np.clip((max_d[big].astype(np.float32) - 16.0) / 96.0, 0.0, 1.0)
    diff_rgb[big, 0] = 255
    diff_rgb[big, 1] = (48 + mag * 185).astype(np.uint8)
    diff_rgb[big, 2] = (68 + np.maximum(0.0, mag - 0.5) * 340).clip(0, 255).astype(np.uint8)

    # Composite 962 x 240 (1px dark bezel dividers between the 3 screens)
    sep = np.full((frames, h, 1, 3), (46, 42, 58), dtype=np.uint8)
    comp = np.concatenate([ref_rgb, sep, cand_rgb, sep, diff_rgb], axis=2)  # (frames, 240, 962, 3)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    mp4_path = OUT_DIR / f"{spec['id']}.mp4"
    ff = subprocess.Popen([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{comp.shape[2]}x{comp.shape[1]}", "-r", "30",
        "-i", "-",
        "-c:v", "libx264", "-preset", "slow", "-crf", "20",
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
        **spec,
        "video": f"{spec['id']}.mp4",
        "frames": frames,
        "fps": 30,
        "base_mean_ms": round(sum(base_ms) / len(base_ms), 1),
        "cand_mean_ms": round(sum(cand_ms) / len(cand_ms), 1),
        "max_diff_pct": round(max(diff_pct), 2),
        "base_ms": base_ms,
        "cand_ms": cand_ms,
        "diff_pct": diff_pct[1:],  # align with frames 1..239
        "bytes": mp4_path.stat().st_size,
    }


def main():
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="mev-clips-"))
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
