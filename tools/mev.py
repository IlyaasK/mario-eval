#!/usr/bin/env python3
"""mev: build, run, profile and self-check the target N64 game inside the task container.

  mev build                     build /task/game
  mev run WORKLOAD [--frames N] run one public workload, print cost summary
  mev profile WORKLOAD [--top N] [--frames N]
                                clock-weighted per-function CPU profile
  mev check                     full public grading of /task/game (same grader,
                                same gates, public workloads only)
  mev workloads                 list public workloads

All costs are measured by the emulator (ares N64 model), never by the ROM.
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

GAME = pathlib.Path("/task/game")
CORPUS = pathlib.Path("/opt/mario-eval/corpus")
CACHE = pathlib.Path("/opt/mario-eval/reference")


def sh(cmd, **kw):
    return subprocess.run(cmd, check=False, **kw)


def config():
    return json.loads((CORPUS / "grader.json").read_text())


def build():
    cfg = config()
    jobs = str(os.cpu_count() or 8)
    base_cmd = cfg.get("build_cmd", ["make"])
    cmd = [base_cmd[0], f"-j{jobs}", *base_cmd[1:]] if base_cmd[0] == "make" else list(base_cmd)
    r = sh(cmd, cwd=GAME)
    rom = GAME / cfg["rom"]
    if r.returncode != 0 or not rom.exists():
        sys.exit("build failed")
    return rom


def find_elf(cfg):
    if "elf" in cfg:
        p = GAME / cfg["elf"]
        if p.exists():
            return p
    for p in GAME.rglob("*.elf"):
        return p
    return None


def replay(workload):
    for w in config()["workloads"]:
        if w["id"] == workload:
            return CORPUS / w["replay"]
    sys.exit(f"unknown workload {workload}; try: mev workloads")


def summarize(out_dir, workload):
    sys.path.insert(0, "/opt/mario-eval")
    from grader.grade import load_run, metrics
    result = json.loads((out_dir / "result.json").read_text())
    if result["status"] != "completed":
        print(json.dumps(result, indent=1))
        sys.exit(1)
    run = load_run(out_dir)
    m = metrics(run)
    # Compare against the baseline over the same frames, not its full run.
    ref = load_run(CACHE / "runs" / workload)
    ref["rows"] = ref["rows"][:len(run["rows"])]
    base = metrics(ref)
    rows = [
        ("Est. console frame (ms)", "est_console_ms"),
        ("CPU frame time (ms)", "frame_ms"),
        ("RDP frame time (ms)", "rdp_ms"),
        ("RSP frame time (ms)", "rsp_ms"),
        ("VI fields / frame", "vi_fields_per_frame"),
        ("CPU cycles / frame", "cpu_cycles"),
        ("RDP busy cycles / frame", "rdp_busy"),
        ("RSP busy cycles / frame", "rsp_busy"),
        ("RDRAM bytes / frame", "rdram_bytes"),
        ("D-cache misses / frame", "dcache_misses"),
        ("I-cache misses / frame", "icache_misses"),
        ("TMEM loads / frame", "rdp_tmem_loads"),
        ("TMEM bytes / frame", "rdp_tmem_bytes"),
        ("RDP pixels / frame", "rdp_pixels"),
        ("RDRAM footprint (bytes)*", "footprint_bytes"),
    ]
    print(f"{'':26s} {'yours':>14s} {'baseline':>14s} {'ratio':>8s} {'speedup':>8s}   ({len(run['rows'])} frames)")
    for label, key in rows:
        b = base.get(key)
        ratio = f"{m[key] / b:8.3f}" if b else ""
        sp = f"{b / m[key]:7.2f}x" if (b and m[key]) else ""
        print(f"{label:26s} {m[key]:14.1f} {b if b is not None else float('nan'):14.1f} {ratio} {sp}")
    print("* footprint: yours over this run, baseline over its full run")
    print("\nRDRAM bytes / frame by device:")
    for dev, v in m["rdram_bytes_by_device"].items():
        if v:
            print(f"  {dev:18s} {v:12.0f}")


def run(args, profile=False):
    cfg = config()
    rom = build()
    frames = args.frames or min(120, cfg["frames"])
    out = pathlib.Path(tempfile.mkdtemp(prefix=f"mev-{args.workload}-"))
    cmd = ["n64run", "--rom", str(rom), "--replay", str(replay(args.workload)),
           "--out", str(out / "run"), "--frames", str(frames)]
    if profile:
        cmd += ["--profile", str(out / "samples.txt")]
    r = sh(cmd, stderr=subprocess.PIPE, text=True)
    for line in r.stderr.splitlines():
        if "Stalled compile" not in line:
            print(line, file=sys.stderr)
    if profile:
        elf = find_elf(cfg)
        if elf:
            nm = out / "nm.txt"
            nm.write_text(subprocess.run(["mips64-elf-nm", "-n", "--defined-only", str(elf)],
                                         capture_output=True, text=True).stdout)
            sh([sys.executable, "/opt/mario-eval/tools/symbolize.py", str(out / "samples.txt"), str(nm),
                "--top", str(args.top)])
            print()
    summarize(out / "run", args.workload)
    print(f"\nraw output: {out}/run  (frames.jsonl, video.bin, audio.bin, obs.bin)")


def check(_args):
    out = pathlib.Path(tempfile.mkdtemp(prefix="mev-check-"))
    r = sh([sys.executable, "-m", "grader.grade", "grade", str(GAME), "--corpus", str(CORPUS),
            "--cache", str(CACHE), "--out", str(out)], cwd="/opt/mario-eval")
    summary_path = out / "summary.json"
    if summary_path.exists():
        try:
            s = json.loads(summary_path.read_text())
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
        except Exception:
            pass
    print(f"\nfull report: {summary_path}")
    sys.exit(r.returncode)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    sub.add_parser("workloads")
    sub.add_parser("check")
    for name in ("run", "profile"):
        p = sub.add_parser(name)
        p.add_argument("workload")
        p.add_argument("--frames", type=int, default=0)
        p.add_argument("--top", type=int, default=25)
    args = ap.parse_args()
    if args.cmd == "build":
        print(build())
    elif args.cmd == "workloads":
        for w in config()["workloads"]:
            print(w["id"])
    elif args.cmd == "run":
        run(args)
    elif args.cmd == "profile":
        run(args, profile=True)
    elif args.cmd == "check":
        check(args)


if __name__ == "__main__":
    main()
