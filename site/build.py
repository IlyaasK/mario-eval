#!/usr/bin/env python3
"""Build the Mario Eval website (served at https://ilya.as/mario-eval/).

    python3 site/build.py <out_dir>

Reads the calibration summaries (results/calibration/*/summary.json and
results/sm64-calibration/*/summary.json when present), optional 24-hour agent
and trial runs (results/agents/*/summary.json + trajectory.json + meta.json),
Pip's Garden public reference frames (cache/reference/runs/*/video.bin.z when
present, never any Nintendo SM64 assets), and the hand-written posts in
site/posts/.
"""
import html
import json
import math
import re
import shutil
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CAL = ROOT / "results" / "calibration"
SM64_CAL = ROOT / "results" / "sm64-calibration"
SM64_TRIAL_CAL = ROOT / "results" / "sm64-trial-calibration"
AGENTS_DIR = ROOT / "results" / "agents"
PIPS_REF_RUNS = ROOT / "cache" / "reference" / "runs"
CLIPS_SRC = SITE / "assets" / "clips"
BASE = "/mario-eval"
REPO = "https://github.com/IlyaasK/mario-eval"

PATCHES = [
    ("r0-unchanged", "Unchanged rebuild", "The baseline must score exactly 0 on every profile."),
    ("r1-o2-ieee", "<code>-O2 -fno-fast-math</code>", "Compiler optimization that keeps IEEE float semantics."),
    ("r2-engine", "View-projection once per frame, terrain heights precomputed",
     "Algorithmic changes at <code>-O0</code> with bit-identical results."),
    ("r3-cde", "Create Dirty Exclusive on the audio block",
     "The VR4300 <code>CACHE 0x0d</code> trick on a 2 KB buffer."),
    ("r4-memory", "Delete an unused 256 KiB buffer", "A pure RAM footprint saving."),
    ("r5-reassoc", "<code>(P&middot;V)&middot;M</code> instead of <code>P&middot;(V&middot;M)</code>",
     "Same math, different rounding: sub-pixel vertex shifts must pass the video gate."),
    ("r6-sine-table", "Sine table and closed-form triangle wave in the synth",
     "Approximate audio within tolerance; 16 KB LUT spills the 8 KB direct-mapped D-cache."),
    ("r7-full-detail", "Always draw Pip at full detail",
     "Accepted visual variant (Kaze's Mario LOD change): passes video against the accepted variant."),
    ("r8-full-detail-shifted", "Always draw Pip at full detail, deleting the distance check",
     "Same accepted visual variant with shifted code/data cache alignment."),
    ("r9-rdp-batch", "1-cycle RDP combiner + material-batched TMEM uploads",
     "Cuts RDP combiner fill cycles and RSP/DP TMEM command overhead without changing pixels."),
    ("i0-o2-fastmath", "<code>-O2</code> with libdragon's default <code>-ffast-math</code>",
     "Faster, but changes floating-point results that feed gameplay."),
    ("i1-mute", "Skip audio synthesis", "Shortcut: remove work the player would notice."),
    ("i2-no-particles", "Skip drawing particles", "Shortcut: remove visible geometry."),
    ("i3-physics", "Two physics substeps instead of four", "Shortcut: change the simulation."),
    ("i4-tamper", "Edit the harness", "Integrity check."),
    ("i5-low-detail", "Always draw Pip at the lowest detail",
     "Unaccepted visual degradation: fewer parts, worse looking."),
]

SM64_PATCHES = [
    ("r0-unchanged", "Unchanged 1996 IDO rebuild",
     "Matching US decompilation baseline scores 0 across the hardware profiles."),
    ("r1-gcc-o2", "Switch to GCC <code>-O2 -fno-fast-math</code>",
     "Compiler-only reference rung for <code>vs_o2_speedup</code>."),
    ("r2-kaze-mtx", "Kaze's in-place <code>mtxf_mul</code> + 32-bit <code>mtxf_to_mtx</code>",
     "Eliminates temporary matrix copy and packs fixed-point halves in 32-bit stores under IDO."),
    ("r3-kaze-full-detail-lod", "Always draw high-poly Mario (<code>actors/mario/geo.inc.c</code>)",
     "Kaze Emanuar's LOD change: verified against the accepted <code>full-detail</code> visual variant."),
    ("r4-kaze-rdp-opa", "Kaze's <code>G_RM_RA_ZB_OPA_SURF</code> reduced-aliasing opaque modes",
     "Drops <code>IM_RD</code> per-pixel framebuffer reads while keeping <code>AA_EN</code> VI silhouette coverage, cutting RDP cycles and <code>DP Draw</code> bus reads."),
    ("r5-double-buffer", "Double-buffer 16bpp framebuffers instead of triple-buffering",
     "Reclaims 153.6 KB (<code>gFramebuffer2</code>) of the 4 MB RDRAM budget."),
    ("r6-kaze-super", "GCC <code>-O2</code> + Kaze matrix math + <code>CACHE 0x0d</code> + skybox cull + double-buffer",
     "Early multi-subsystem N64 optimization rung beating <code>-O2</code> across CPU, RDP, RDRAM traffic, and RAM."),
    ("r7-kaze-icache-trig", "Kaze Rung 1: 16 KB I-cache de-aliasing + 1-ULP polynomial trig + bit-exact 256 B <code>atan2s</code>",
     "Eliminates the <code>0xFC000</code> (<code>63 &times; 16 KB</code>) scene-graph/collision I-cache thrash in <code>sm64.ld</code> and replaces 22.5 KB of D-cache-evicting trig LUTs."),
    ("r8-kaze-collision-objects", "Kaze Rung 2: 3-cache-line <code>struct Surface</code> + Bowser's Sub surface cache + single-floor shadows",
     "Packs XZ + Y bounds into D-cache line 0, caches stationary platform surfaces across frames, and bump-allocates the 240-slot object pool."),
    ("r9-kaze-partial", "Kaze Rung 3 (partial reference): lazy <code>Mtx</code> + fast frustum cull + coin TMEM batch + <code>&minus;304 KB</code> RAM",
     "Full-stack partial Kaze Emanuar reference: defers fixed-point <code>Mtx</code> allocation past frustum cull, batches coin TMEM loads, enables <code>RA_ZB_OPA</code> + <code>CACHE 0x0d</code>, and trims 304 KB of RDRAM."),
    ("r10-kaze-master", "Kaze master reference: reconstructed optimizations from Kaze Emanuar's public work",
     "Based on transcripts, on-screen code and two public code downloads: F3DEX2, no LOD, size-optimised code, vertical culling, billboard-once-per-camera, fused matrices, audio I-cache blocking, Rainbow Ride decoration baked into the level. Not Kaze's own engine."),
    ("r11-beyond-kaze", "Beyond Kaze: r10-style build plus our own cache-layout work",
     "An older Kaze-style build with our own cache-layout experiments: object field ordering, skipped unchanged stores, audio struct reorder, and double buffering. Its score is below the current expert reference."),
    ("i0-gcc-fastmath", "GCC <code>-O2 -ffast-math</code>", "Breaks Mario physics/collision trajectories."),
    ("i1-mute-audio", "Disable audio synthesis (<code>sAudioEnabled = FALSE</code>)", "Caught by the 40 dB audio SNR gate."),
    ("i2-low-poly-mario", "Force low-poly Mario at all distances", "Caught by the video gate."),
    ("i3-half-physics-step", "Two quarter-steps instead of four in <code>mario_step.c</code>", "Caught by the Player Equivalence gameplay gate."),
    ("i4-tamper", "Modify <code>src/game/mev.h</code>", "Caught by the harness integrity gate."),
]

EXPERT_REF = "r10-kaze-master"
PROFILES = ["console", "stutter", "speed", "rdp", "rsp", "traffic", "memory"]

PUBLIC_PIPS_ROUTES = [
    ("meadow", 35, "Meadow", "Terrain heightfield, crystals &amp; shadow decals"),
    ("fortress", 15, "Fortress", "Dense wall/floor collision &amp; patrolling hazards"),
    ("concert", 150, "Concert", "Multi-channel audio synthesis &amp; jump arcs"),
    ("storm", 150, "Storm", "Heavy rain alpha particles &amp; dash trails"),
]

SM64_COURSES = ["bob", "wf", "jrb", "ddd", "bitfs", "rr"]
SM64_COURSE_NAMES = {
    "bob": "Bob-omb Battlefield",
    "wf": "Whomp's Fortress",
    "jrb": "Jolly Roger Bay",
    "ddd": "Dire Dire Docks (Sub)",
    "bitfs": "Bowser in the Fire Sea",
    "rr": "Rainbow Ride",
}
SM64_COURSE_SHORT = {
    "bob": "BoB",
    "wf": "WF",
    "jrb": "JRB",
    "ddd": "DDD Sub",
    "bitfs": "BitFS",
    "rr": "RR",
}

PIP_SVG = """<svg viewBox="0 0 200 220" role="img" aria-label="Pip, a small round robot">
  <line x1="100" y1="44" x2="100" y2="18" stroke="#7b68ee" stroke-width="4" stroke-linecap="round"/>
  <polygon points="100,4 110,16 100,28 90,16" fill="#38bdf8" stroke="#e8e4f4" stroke-width="2.5"/>
  <ellipse cx="100" cy="76" rx="52" ry="38" fill="#252230" stroke="#7b68ee" stroke-width="3.5"/>
  <rect x="62" y="62" width="76" height="28" rx="14" fill="#0a0a0d" stroke="#4a4560" stroke-width="2.5"/>
  <circle cx="84" cy="76" r="6" fill="#2ed573"/>
  <circle cx="116" cy="76" r="6" fill="#2ed573"/>
  <ellipse cx="100" cy="150" rx="62" ry="50" fill="#ffb000" stroke="#e8e4f4" stroke-width="3.5"/>
  <ellipse cx="100" cy="150" rx="26" ry="20" fill="#ffd166" stroke="#1a1820" stroke-width="2.5"/>
  <path d="M40 140 q-22 6 -26 26" fill="none" stroke="#8a849f" stroke-width="6" stroke-linecap="round"/>
  <path d="M160 140 q22 6 26 26" fill="none" stroke="#8a849f" stroke-width="6" stroke-linecap="round"/>
  <ellipse cx="74" cy="204" rx="20" ry="9" fill="#4a4560" stroke="#e8e4f4" stroke-width="2.5"/>
  <ellipse cx="126" cy="204" rx="20" ry="9" fill="#4a4560" stroke="#e8e4f4" stroke-width="2.5"/>
</svg>"""

PIPELINE_SVG = """<svg viewBox="0 0 960 156" role="img" aria-label="Grading pipeline">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
    <path d="M0 0 L10 5 L0 10 z" fill="#7b68ee"/></marker></defs>
  <g font-family="IBM Plex Mono, monospace" font-size="12" fill="#e8e4f4">
    <g stroke="#4a4560" stroke-width="1.5" fill="#0a0a0d">
      <rect x="4" y="42" width="132" height="68" rx="6"/>
      <rect x="168" y="42" width="136" height="68" rx="6"/>
      <rect x="336" y="38" width="176" height="76" rx="6" stroke="#7b68ee"/>
      <rect x="544" y="14" width="202" height="124" rx="6" stroke="#ffb000"/>
      <rect x="778" y="38" width="178" height="76" rx="6" stroke="#2ed573"/>
    </g>
    <g stroke="#7b68ee" stroke-width="1.6">
      <line x1="136" y1="76" x2="166" y2="76" marker-end="url(#arr)"/>
      <line x1="304" y1="76" x2="334" y2="76" marker-end="url(#arr)"/>
      <line x1="512" y1="76" x2="542" y2="76" marker-end="url(#arr)"/>
      <line x1="746" y1="76" x2="776" y2="76" marker-end="url(#arr)"/>
    </g>
    <text x="70" y="70" text-anchor="middle" font-weight="600">source</text>
    <text x="70" y="89" text-anchor="middle" fill="#8a849f">SM64 / Pip</text>
    <text x="236" y="70" text-anchor="middle" font-weight="600">trusted build</text>
    <text x="236" y="89" text-anchor="middle" fill="#8a849f">bench + PLAY=1</text>
    <text x="424" y="63" text-anchor="middle" font-weight="600" fill="#7b68ee">ares N64</text>
    <text x="424" y="81" text-anchor="middle" fill="#8a849f">93.75MHz CPU + I/D$</text>
    <text x="424" y="99" text-anchor="middle" fill="#8a849f">62.5MHz RSP/RDP + Bus</text>
    <text x="645" y="36" text-anchor="middle" font-weight="600" fill="#ffb000">6 gates (6–25 routes)</text>
    <text x="645" y="57" text-anchor="middle" fill="#8a849f">player-equiv / exact</text>
    <text x="645" y="75" text-anchor="middle" fill="#8a849f">video + 40 dB audio</text>
    <text x="645" y="93" text-anchor="middle" fill="#8a849f">integrity + 4 MB RAM</text>
    <text x="645" y="111" text-anchor="middle" fill="#8a849f">cross-budget caps</text>
    <text x="645" y="128" text-anchor="middle" fill="#ff5a63">any fail &rarr; &minus;1.0</text>
    <text x="867" y="64" text-anchor="middle" font-weight="600" fill="#2ed573">console score</text>
    <text x="867" y="82" text-anchor="middle" fill="#8a849f">max(CPU,RSP,RDP,RAM)</text>
    <text x="867" y="100" text-anchor="middle" fill="#8a849f">FPS &amp; vs -O2</text>
  </g>
</svg>"""


def esc(s):
    return html.escape(str(s))


def page(title, body, active="", desc=""):
    nav = [
        ("", "About"),
        ("leaderboard/", "Leaderboard"),
        ("calibration/", "Calibration"),
        ("blog/", "Blog"),
    ]
    links = "".join(
        f'<a href="{BASE}/{href}"{" class=on" if href == active else ""}>{name}</a>' for href, name in nav)
    links += f'<a class="cta" href="{REPO}" target="_blank" rel="noreferrer noopener">GitHub &rarr;</a>'
    desc = desc or "A 24h RLVR environment: super-optimize Super Mario 64 or Pip's Garden on original 4 MB N64 hardware without changing the game."
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#0a0a0d">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/style.css">
</head><body>
<header class="site"><div class="wrap">
  <div class="brand">
    <span class="n64-leds" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
    <a class="logo" href="{BASE}/">MARIO<span>EVAL</span></a>
    <span class="brand-sep" aria-hidden="true">&middot;</span>
    <span class="brand-sub">By <a href="https://ilya.as/">Ilyaas Kapadia</a></span>
  </div>
  <nav class="site">{links}</nav>
</div></header>
<main class="wrap">{body}</main>
<footer class="site"><div class="wrap">
Built by <a href="https://ilya.as/">Ilyaas Kapadia</a>, inspired by Mechanize's
<a href="https://gbaeval.com/">GBA Eval</a>. Not affiliated with or endorsed by Nintendo.
No Nintendo code or assets are distributed; Super Mario 64 support requires your own legally obtained ROM.
</div></footer>
</body></html>
"""


def write(out, rel, text):
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _png_chunk(tag, data):
    crc = zlib.crc32(tag + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", crc)


def encode_rgb_png(rgb_bytes, width, height):
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgb_bytes[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def export_pips_frames(out):
    exported = []
    if not PIPS_REF_RUNS.exists():
        return exported
    out_dir = out / "assets" / "frames"
    out_dir.mkdir(parents=True, exist_ok=True)
    w, h = 320, 240
    frame_bytes = w * h * 2
    for route_id, frame_idx, label, caption in PUBLIC_PIPS_ROUTES:
        vpath = PIPS_REF_RUNS / route_id / "video.bin.z"
        if not vpath.exists():
            continue
        blob = zlib.decompress(vpath.read_bytes())
        total_frames = len(blob) // frame_bytes
        if total_frames == 0:
            continue
        idx = min(frame_idx, total_frames - 1)
        fbuf = blob[idx * frame_bytes:(idx + 1) * frame_bytes]
        rgb = bytearray(w * h * 3)
        for p in range(w * h):
            px = (fbuf[2 * p] << 8) | fbuf[2 * p + 1]
            r5 = (px >> 11) & 31
            g5 = (px >> 6) & 31
            b5 = (px >> 1) & 31
            rgb[3 * p] = (r5 << 3) | (r5 >> 2)
            rgb[3 * p + 1] = (g5 << 3) | (g5 >> 2)
            rgb[3 * p + 2] = (b5 << 3) | (b5 >> 2)
        (out_dir / f"{route_id}.png").write_bytes(encode_rgb_png(rgb, w, h))
        exported.append((route_id, label, caption))
    return exported


def load_cal(cal_dir, spec):
    rows = []
    for slug, title, purpose in spec:
        f = cal_dir / slug / "summary.json"
        if f.exists():
            rows.append((slug, title, purpose, json.loads(f.read_text())))
    return rows


def load_agent_runs():
    runs = []
    if not AGENTS_DIR.exists():
        return runs
    for d in sorted(AGENTS_DIR.iterdir()):
        sf = d / "summary.json"
        if not sf.exists():
            continue
        summary = json.loads(sf.read_text())
        meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
        traj = json.loads((d / "trajectory.json").read_text()) if (d / "trajectory.json").exists() else None
        runs.append({
            "slug": d.name,
            "title": meta.get("title", d.name),
            "model": meta.get("model", d.name),
            "kind": meta.get("kind", "agent"),
            "repo_url": meta.get("repo_url", ""),
            "hours": meta.get("hours", 24),
            "notes": meta.get("notes", "24h autonomous agent run"),
            "summary": summary,
            "trajectory": traj,
        })
    return runs


def checkpoint_points(run):
    cohort = run["summary"].get("workload_set")
    if not cohort:
        return []
    samples = []
    for point in (run["trajectory"] or {}).get("host_checkpoints", []):
        speedup = point.get("speedups", {}).get("console", 0)
        if point.get("workload_set") == cohort and point.get("status") == "valid" and speedup > 0:
            samples.append((point["elapsed_hours"], speedup, point.get("name", ""), point.get("vs_o2_speedups", {}).get("console")))
    best = 1.0
    points = []
    for hours, speedup, name, vs_o2 in sorted(samples):
        best = max(best, speedup)
        points.append((hours, best, name, vs_o2))
    return [(0.0, 1.0, "baseline", None), *points] if points else []


def mean_fps(s):
    wls = list(s.get("workloads", {}).values())
    if not wls:
        return None
    vals = []
    for w in wls:
        m = w.get("metrics", {})
        if "est_fps" in m:
            vals.append(float(m["est_fps"]))
        elif "frame_ms" in m and m["frame_ms"] > 0:
            vals.append(1000.0 / float(m["frame_ms"]))
    return sum(vals) / len(vals) if vals else None


def primary_profile(s):
    profs = s.get("profiles", {})
    return profs.get("console") or profs.get("speed") or {}


def reward_cell(s, profile):
    if s["status"] != "valid":
        return '<td class="num neg">&minus;1</td>'
    p = s["profiles"].get(profile)
    if not p:
        return '<td class="num muted">&mdash;</td>'
    if not p["valid"]:
        return f'<td class="num neg" title="{esc(p.get("reason", ""))}">&minus;1*</td>'
    r = p["reward"]
    cls = "pos" if r > 0.0005 else ("neg" if r < -0.0005 else "")
    sp = p.get("speedup")
    tip = f' title="speedup: {sp:.3f}x"' if sp else ""
    return f'<td class="num {cls}"{tip}>{r:+.3f}</td>'


def speedup_cell(s):
    if s["status"] != "valid":
        return '<td class="num muted">&mdash;</td>'
    p = primary_profile(s)
    sp = p.get("speedup")
    vs = p.get("vs_o2_speedup")
    if not sp or not p.get("valid", True):
        return '<td class="num muted">&mdash;</td>'
    tip = f' title="vs -O2: {vs:.3f}x"' if vs else ""
    return f'<td class="num"{tip}>{sp:.2f}&times;</td>'


def fps_cell(s):
    if s["status"] != "valid":
        return '<td class="num muted">&mdash;</td>'
    fps = mean_fps(s)
    if not fps:
        return '<td class="num muted">&mdash;</td>'
    return f'<td class="num">{fps:.1f}</td>'


def failed_gates(s):
    gates = [g for g, v in s.get("gates", {}).items() if not v["pass"]]
    return ", ".join(gates)


def cal_table(rows, compact=False, anchor_prefix=""):
    head = ("".join(f'<th class="num">{p}</th>' for p in PROFILES)
            + '<th class="num">console&times;</th><th class="num">FPS</th>')
    out = ['<div class="table-wrap">',
           f'<table><thead><tr><th>patch</th><th>status</th>{head}<th>caught by</th></tr></thead><tbody>']
    for slug, title, _purpose, s in rows:
        row_cls = []
        if s["status"] != "valid":
            row_cls.append("invalid")
        elif slug == EXPERT_REF:
            row_cls.append("ceiling-row")
        cls = f' class="{" ".join(row_cls)}"' if row_cls else ""
        tag = f'<span class="tag {s["status"]}">{s["status"]}</span>'
        name = f'<a href="{BASE}/calibration/#{anchor_prefix}{slug}">{title}</a>' if compact else title
        out.append(f"<tr{cls}><td>{name}</td><td>{tag}</td>"
                   + "".join(reward_cell(s, p) for p in PROFILES)
                   + speedup_cell(s)
                   + fps_cell(s)
                   + f"<td class=small>{esc(failed_gates(s))}</td></tr>")
    out.append("</tbody></table></div>")
    out.append('<p class="small muted"><b>console</b> is the headline real-hardware frame-time profile '
               '(<code>max(CPU_ms, RSP_ms, RDP_ms, RDRAM_ms)</code> per frame within 4 MB RDRAM). '
               '<b>&minus;1*</b>: valid submission that exceeds that diagnostic profile\'s cross-budget.</p>')
    return "\n".join(out)


def baseline_table(rows):
    base = next((s for slug, *_rest, s in rows if slug == "r0-unchanged"), None)
    if not base:
        return ""
    out = ['<div class="table-wrap"><table><thead><tr><th>workload</th><th class="num">console (ms)</th>'
           '<th class="num">FPS</th><th class="num">CPU (ms)</th><th class="num">RSP (ms)</th>'
           '<th class="num">RDP (ms)</th><th class="num">RDRAM KB</th><th class="num">footprint KiB</th></tr></thead><tbody>']
    for wid, d in base["workloads"].items():
        m = d["metrics"]
        con_ms = m.get("est_console_ms", m["frame_ms"])
        fps = m.get("est_fps", 1000.0 / max(con_ms, 1e-6))
        rdp_ms = m.get("rdp_ms", 0.0)
        rsp_ms = m.get("rsp_ms", 0.0)
        out.append(f"<tr><td>{esc(wid)}</td><td class=num>{con_ms:.1f}</td><td class=num>{fps:.1f}</td>"
                   f"<td class=num>{m['frame_ms']:.1f}</td><td class=num>{rsp_ms:.1f}</td>"
                   f"<td class=num>{rdp_ms:.1f}</td>"
                   f"<td class=num>{m['rdram_bytes'] / 1000:.0f}</td>"
                   f"<td class=num>{m['footprint_bytes'] / 1024:.0f}</td></tr>")
    out.append("</tbody></table></div>")
    return "\n".join(out)


def sm64_bottleneck_svg(sm64_rows):
    by_slug = {slug: s for slug, *_r, s in sm64_rows if s["status"] == "valid"}
    base = by_slug.get("r0-unchanged")
    ceil = by_slug.get(EXPERT_REF) or by_slug.get("r9-kaze-partial")
    if not base or not ceil:
        return ""

    courses = [c for c in SM64_COURSES if c in base["workloads"] and c in ceil["workloads"]]
    if not courses:
        return ""

    max_ms = max(
        max(base["workloads"][c]["metrics"].get("est_console_ms", base["workloads"][c]["metrics"]["frame_ms"]) for c in courses),
        40.0,
    ) * 1.12

    w, row_h, top, left, right = 920, 48, 48, 210, 170
    plot_w = w - left - right
    h = top + len(courses) * row_h + 36

    def x_of(ms):
        return left + (ms / max_ms) * plot_w

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Super Mario 64 per-course console frame time: original IDO baseline vs Kaze master reference">',
        '<g font-family="IBM Plex Mono, monospace" font-size="11.5" fill="#e8e4f4">',
        f'<text x="{left}" y="20" font-weight="600" fill="#e8e4f4">Console frame time per course (ms, lower is faster) &mdash; 1996 IDO vs Kaze master</text>',
    ]

    for tick in [0, 16.67, 33.33, 50]:
        if tick > max_ms:
            continue
        xt = x_of(tick)
        is_30 = abs(tick - 33.33) < 0.1
        is_60 = abs(tick - 16.67) < 0.1
        dash = ' stroke-dasharray="4,3"' if (is_30 or is_60) else ''
        color = "#ffb000" if is_30 else ("#38bdf8" if is_60 else "#2e2a3a")
        lbl = "33.3ms (30fps)" if is_30 else ("16.7ms (60fps)" if is_60 else f"{int(tick)}ms")
        parts.append(f'<line x1="{xt:.1f}" y1="{top - 10}" x2="{xt:.1f}" y2="{h - 24}" stroke="{color}" stroke-width="1" opacity="{0.8 if (is_30 or is_60) else 0.7}"{dash}/>')
        parts.append(f'<text x="{xt:.1f}" y="{h - 8}" text-anchor="middle" font-size="10.5" fill="{color if (is_30 or is_60) else "#8a849f"}">{lbl}</text>')

    for idx, c in enumerate(courses):
        y = top + idx * row_h
        bm = base["workloads"][c]["metrics"]
        cm = ceil["workloads"][c]["metrics"]
        b_ms = bm.get("est_console_ms", bm["frame_ms"])
        c_ms = cm.get("est_console_ms", cm["frame_ms"])
        b_fps = bm.get("est_fps", 1000.0 / b_ms)
        c_fps = cm.get("est_fps", 1000.0 / c_ms)
        c_rdp = cm.get("rdp_ms", 0.0)
        sp = b_ms / max(c_ms, 1e-6)

        parts.append(f'<text x="{left - 12}" y="{y + 15}" text-anchor="end">{esc(SM64_COURSE_NAMES.get(c, c))}</text>')
        parts.append(f'<text x="{left - 12}" y="{y + 30}" text-anchor="end" font-size="10" fill="#8a849f">RDP {c_rdp:.1f}ms</text>')

        bw = (b_ms / max_ms) * plot_w
        cw = (c_ms / max_ms) * plot_w
        parts.append(f'<rect x="{left}" y="{y + 3}" width="{bw:.1f}" height="12" rx="2" fill="#4a4560"/>')
        parts.append(f'<rect x="{left}" y="{y + 19}" width="{cw:.1f}" height="13" rx="2" fill="#2ed573"/>')
        parts.append(f'<text x="{left + bw + 8:.1f}" y="{y + 13}" font-size="10.5" fill="#8a849f">{b_ms:.1f}ms ({b_fps:.1f} fps)</text>')
        parts.append(f'<text x="{left + cw + 8:.1f}" y="{y + 30}" font-size="11" font-weight="600" fill="#2ed573">{c_ms:.1f}ms ({c_fps:.1f} fps, {sp:.2f}&times;)</text>')

    parts.append("</g></svg>")
    return "\n".join(parts)


def trajectory_svg(sm64_rows, agent_runs, chart_id="traj"):
    by_slug = {slug: (title, s) for slug, title, _p, s in sm64_rows if s["status"] == "valid"}
    rungs = [
        ("r0-unchanged", "1996 IDO"),
        ("r2-kaze-mtx", "IDO + Mtx"),
        ("r4-kaze-rdp-opa", "RA_ZB_OPA"),
        ("r1-gcc-o2", "GCC -O2"),
        ("r7-kaze-icache-trig", "R7: I$+Trig"),
        ("r8-kaze-collision-objects", "R8: Collis."),
        ("r9-kaze-partial", "R9: Partial"),
        ("r10-kaze-master", "R10: Kaze"),
        ("r11-beyond-kaze", "R11: Cache"),
    ]
    pts = []
    for slug, label in rungs:
        if slug in by_slug:
            s = by_slug[slug][1]
            sp = primary_profile(s).get("speedup", 1.0)
            fps = mean_fps(s) or 0.0
            pts.append((slug, label, float(sp), float(fps)))

    traj_runs = [(r, points) for r in agent_runs if (points := checkpoint_points(r))]
    if traj_runs:
        cohorts = {r["summary"]["workload_set"] for r, _ in traj_runs}
        assert len(cohorts) == 1, "cannot plot different workload sets on one agent curve"
        cohort = next(iter(cohorts))
        by_slug = {slug: data for slug, data in by_slug.items()
                   if data[1].get("workload_set") == cohort and primary_profile(data[1]).get("valid")}
    w, h, left, right, top, bot = 920, 285, 68, 44, 38, 52
    pw, ph = w - left - right, h - top - bot

    if traj_runs:
        max_y = max(
            [1.30]
            + [primary_profile(data[1])["speedup"] for data in by_slug.values()]
            + [speedup for _, points in traj_runs for _, speedup, _, _ in points]
        ) * 1.05
        min_y = 0.98

        def xy(hr, sp):
            x = left + (min(max(hr, 0.0), 24.0) / 24.0) * pw
            y = top + (1.0 - (sp - min_y) / (max_y - min_y)) * ph
            return x, y

        parts = [
            f'<div class="svg-tip" id="{chart_id}-tip"></div>',
            f'<svg id="{chart_id}" viewBox="0 0 {w} {h}" role="img" aria-label="24-hour optimization scaling curve">',
            '<g font-family="IBM Plex Mono, monospace" font-size="11.5" fill="#e8e4f4">',
            f'<text x="{left}" y="20" font-weight="600">Best valid host-graded console speedup vs wall-clock hours</text>',
        ]
        for tick in [1.0, 1.2, 1.4, 1.6, 1.8]:
            if tick > max_y:
                continue
            _, ty = xy(0, tick)
            parts.append(f'<line x1="{left}" y1="{ty:.1f}" x2="{w - right}" y2="{ty:.1f}" stroke="#2e2a3a" stroke-width="1"/>')
            parts.append(f'<text x="{left - 10}" y="{ty + 4:.1f}" text-anchor="end" font-size="10.5" fill="#8a849f">{tick:.1f}&times;</text>')
        for hr in [0, 4, 8, 12, 16, 20, 24]:
            x, _ = xy(hr, 1.0)
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - bot}" stroke="#2e2a3a" stroke-width="1"/>')
            parts.append(f'<text x="{x:.1f}" y="{h - bot + 20}" text-anchor="middle" font-size="10.5" fill="#8a849f">{hr}h</text>')
        for ref_slug, ref_lbl, col in [("r1-gcc-o2", "GCC -O2", "#ffb000"), (EXPERT_REF, "Kaze master", "#2ed573")]:
            if ref_slug in by_slug:
                rsp = primary_profile(by_slug[ref_slug][1]).get("speedup", 1.0)
                _, ry = xy(0, rsp)
                parts.append(f'<line x1="{left}" y1="{ry:.1f}" x2="{w - right}" y2="{ry:.1f}" stroke="{col}" stroke-dasharray="5,4" stroke-width="1.5"/>')
                parts.append(f'<text x="{w - right - 4}" y="{ry - 6:.1f}" text-anchor="end" fill="{col}" font-size="11">{ref_lbl} ({rsp:.2f}&times;)</text>')

        palette = ["#38bdf8", "#7b68ee", "#ff5a63", "#2ed573"]
        for i, (r, points) in enumerate(traj_runs):
            col = palette[i % len(palette)]
            coords = [xy(hr, speedup) for hr, speedup, _, _ in points]
            poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            parts.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.5" points="{poly}"/>')
            for (hr, sp, cpname, vs_o2), (px, py) in zip(points, coords):
                vo_txt = f" ({vs_o2:.2f}x vs -O2)" if vs_o2 else ""
                tip = f"{r['model']} @ {hr:.1f}h: {sp:.3f}x{vo_txt} [{cpname}]"
                parts.append(f'<circle class="pt" cx="{px:.1f}" cy="{py:.1f}" r="4.5" fill="{col}" stroke="#0a0a0d" stroke-width="1.5" data-tip="{esc(tip)}"/>')
            lx, ly = coords[-1]
            parts.append(f'<text x="{lx + 10:.1f}" y="{ly + 4:.1f}" text-anchor="start" fill="{col}" font-weight="600">{esc(r["model"])} ({points[-1][1]:.2f}&times;)</text>')
        parts.append("</g></svg>")
        parts.append(f"""<script>(function(){{
var svg=document.getElementById("{chart_id}"),tip=document.getElementById("{chart_id}-tip");
if(!svg||!tip)return;
svg.querySelectorAll("circle.pt").forEach(function(c){{
  c.style.cursor="pointer";
  c.addEventListener("mouseenter",function(e){{
    tip.textContent=c.getAttribute("data-tip");tip.style.display="block";
    var box=svg.parentElement.getBoundingClientRect();
    tip.style.left=Math.min(box.width-220,Math.max(8,e.clientX-box.left+12))+"px";
    tip.style.top=Math.max(8,e.clientY-box.top-34)+"px";
  }});
  c.addEventListener("mouseleave",function(){{tip.style.display="none";}});
}});
}})();</script>""")
        return "\n".join(parts)

    if len(pts) < 2:
        return ""

    min_y = 0.98
    max_y = max(p[2] for p in pts) + 0.06

    def xy_idx(i, sp):
        x = left + (i / (len(pts) - 1)) * pw
        y = top + (1.0 - (sp - min_y) / (max_y - min_y)) * ph
        return x, y

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Super Mario 64 hardware optimization ladder">',
        '<g font-family="IBM Plex Mono, monospace" font-size="11" fill="#e8e4f4">',
        f'<text x="{left}" y="20" font-weight="600">Super Mario 64 hardware optimization ladder &mdash; console speedup (6 public courses)</text>',
    ]
    n_ticks = 5
    for t in range(n_ticks + 1):
        val = 1.0 + t * round((max_y - 1.0) / n_ticks, 2)
        if val > max_y:
            continue
        _, y = xy_idx(0, val)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="#2e2a3a" stroke-width="1"/>')
        parts.append(f'<text x="{left - 10}" y="{y + 4:.1f}" text-anchor="end" fill="#8a849f">{val:.2f}&times;</text>')

    coords = [xy_idx(i, p[2]) for i, p in enumerate(pts)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts.append(f'<polyline fill="none" stroke="#7b68ee" stroke-width="2.5" points="{poly}"/>')

    for i, (slug, label, sp, fps) in enumerate(pts):
        x, y = coords[i]
        is_ceil = slug == EXPERT_REF
        is_o2 = slug == "r1-gcc-o2"
        col = "#2ed573" if is_ceil else ("#ffb000" if is_o2 else "#7b68ee")
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5.5 if is_ceil else 4.2}" fill="{col}" stroke="#0a0a0d" stroke-width="1.5"/>')
        dy = -11 if i % 2 == 0 or is_ceil else 17
        anchor = "start" if i == 0 else ("end" if i == len(pts) - 1 else "middle")
        parts.append(f'<text x="{x:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}" fill="{col if (is_ceil or is_o2) else "#e8e4f4"}" font-weight="{"600" if is_ceil else "400"}">{sp:.2f}&times; ({fps:.0f}fps)</text>')
        parts.append(f'<text x="{x:.1f}" y="{h - bot + 20 + (14 if i % 2 == 1 else 0)}" text-anchor="{anchor}" font-size="10.2" fill="#8a849f">{esc(label)}</text>')

    parts.append("</g></svg>")
    return "\n".join(parts)


def telemetry_inspector_html(sm64_rows, agent_runs):
    """Interactive CRT hardware telemetry widget comparing Baseline, GCC -O2, Kaze Master, and Kimi Trial."""
    by_slug = {slug: s for slug, *_r, s in sm64_rows if s["status"] == "valid"}
    candidates = []
    for slug, label, badge, cls in [
        ("r0-unchanged", "1996 IDO -O0", "baseline", ""),
        ("r1-gcc-o2", "GCC -O2", "compiler", ""),
        (EXPERT_REF, "Kaze Master (R10)", "expert ref", "highlight"),
    ]:
        if slug in by_slug:
            candidates.append((label, badge, cls, by_slug[slug]))
    for ar in agent_runs:
        if ar["summary"].get("status") == "valid" and all(c in ar["summary"].get("workloads", {}) for c in SM64_COURSES):
            candidates.append((ar["model"], "trial (25-route valid)" if ar.get("kind") == "trial" else "agent", "trial-card", ar["summary"]))

    if len(candidates) < 2:
        return ""

    data = {}
    for cid in ["all", *SM64_COURSES]:
        rows_c = []
        base_con = None
        for label, badge, cls, s in candidates:
            wls = s["workloads"]
            if cid == "all":
                con = math.exp(sum(math.log(wls[c]["metrics"]["est_console_ms"]) for c in SM64_COURSES) / len(SM64_COURSES))
                cpu = sum(wls[c]["metrics"]["cpu_ms"] for c in SM64_COURSES) / len(SM64_COURSES)
                rsp = sum(wls[c]["metrics"]["rsp_ms"] for c in SM64_COURSES) / len(SM64_COURSES)
                rdp = sum(wls[c]["metrics"]["rdp_ms"] for c in SM64_COURSES) / len(SM64_COURSES)
                mem = sum(wls[c]["metrics"]["mem_ms"] for c in SM64_COURSES) / len(SM64_COURSES)
                fps = sum(wls[c]["metrics"]["est_fps"] for c in SM64_COURSES) / len(SM64_COURSES)
            else:
                m = wls[cid]["metrics"]
                con, cpu, rsp, rdp, mem, fps = m["est_console_ms"], m["cpu_ms"], m["rsp_ms"], m["rdp_ms"], m["mem_ms"], m["est_fps"]
            if base_con is None:
                base_con = con
            dom = max([("cpu", cpu), ("rsp", rsp), ("rdp", rdp), ("mem", mem)], key=lambda x: x[1])[0]
            rows_c.append({
                "label": label, "badge": badge, "cls": cls,
                "con": round(con, 2), "cpu": round(cpu, 2), "rsp": round(rsp, 2),
                "rdp": round(rdp, 2), "mem": round(mem, 2), "fps": round(fps, 1),
                "sp": round(base_con / max(con, 1e-6), 2), "dom": dom,
            })
        data[cid] = rows_c

    pills = ['<button class="pill on" data-course="all">6-Course Summary</button>'] + [
        f'<button class="pill" data-course="{c}">{esc(SM64_COURSE_SHORT[c])}</button>' for c in SM64_COURSES
    ]
    return f"""
<div class="panel" id="telem-panel">
  <div class="panel-head">
    <div class="panel-title">N64 Hardware Bottleneck Inspector (ares cycle/cache/RDP model)</div>
    <div class="pill-bar">{"".join(pills)}</div>
  </div>
  <p class="small muted" style="margin-bottom:4px">Click any Super Mario 64 course to inspect how optimization shifts the limiting hardware unit between the 93.75 MHz VR4300 CPU, 62.5 MHz RSP, 62.5 MHz RDP, and 4 MB RDRAM bus. Highlighted bar = active bottleneck.</p>
  <div class="telem-grid" id="telem-grid"></div>
</div>
<script>(function(){{
var DATA={json.dumps(data)};
var grid=document.getElementById("telem-grid");
var btns=document.querySelectorAll("#telem-panel .pill");
function render(cid){{
  var items=DATA[cid]||[];
  var maxMs=Math.max.apply(null,items.map(function(x){{return Math.max(x.con,x.cpu,x.rsp,x.rdp,x.mem);}}).concat([20]));
  grid.innerHTML=items.map(function(x){{
    function row(k,lbl,v){{
      var pct=Math.min(100,(v/maxMs)*100).toFixed(1);
      return '<div class="meter-row'+(x.dom===k?' dom':'')+'"><span class="meter-lbl">'+lbl+'</span>'
        +'<div class="meter-bg"><div class="meter-bar '+k+'" style="width:'+pct+'%"></div></div>'
        +'<span class="meter-val">'+v.toFixed(1)+'ms</span></div>';
    }}
    return '<div class="telem-card '+x.cls+'">'
      +'<div class="telem-top"><span class="telem-name">'+x.label+'</span><span class="telem-fps">'+x.fps.toFixed(1)+' fps</span></div>'
      +'<div class="telem-sub">'+x.badge+' &middot; <b>'+x.sp.toFixed(2)+'&times;</b> ('+x.con.toFixed(1)+' ms)</div>'
      +row("cpu","CPU",x.cpu)+row("rsp","RSP",x.rsp)+row("rdp","RDP",x.rdp)+row("mem","RAM",x.mem)
      +'</div>';
  }}).join("");
}}
btns.forEach(function(b){{
  b.addEventListener("click",function(){{
    btns.forEach(function(x){{x.classList.remove("on");}});
    b.classList.add("on");
    render(b.getAttribute("data-course"));
  }});
}});
render("all");
}})();</script>
"""


def posts():
    items = []
    for f in sorted((SITE / "posts").glob("*.html")):
        text = f.read_text()
        meta = json.loads(re.match(r"<!--(.*?)-->", text, re.S).group(1))
        items.append((f.stem, meta, text.split("-->", 1)[1]))
    return sorted(items, key=lambda x: x[1]["date"], reverse=True)


def pips_gallery_html(exported_frames, rows):
    if not exported_frames:
        return ""
    base = next((s for slug, *_r, s in rows if slug == "r0-unchanged"), None)
    cards = []
    for route_id, label, caption in exported_frames:
        fps_txt = ""
        if base and route_id in base.get("workloads", {}):
            m = base["workloads"][route_id]["metrics"]
            fps = m.get("est_fps", 1000.0 / m["frame_ms"])
            fps_txt = f"{fps:.1f} fps"
        cards.append(
            f'<div class="frame-card">'
            f'<img src="{BASE}/assets/frames/{route_id}.png" width="320" height="240" alt="Pip\'s Garden {esc(label)} route frame" loading="lazy">'
            f'<div class="cap"><b>{esc(label)}</b><span>{esc(fps_txt)}</span></div>'
            f'<div class="cap desc"><span>{caption}</span></div>'
            f'</div>'
        )
    return '<div class="frame-grid">' + "".join(cards) + "</div>"


def trial_section_html(agent_runs, sm64_rows, trial_rows, chart_id="trial-traj"):
    trial_runs = [ar for ar in agent_runs if ar.get("kind") == "trial"]
    if not trial_runs:
        return ""
    t_rows = [
        '<div class="prose"><h2>Trial runs (harness &amp; grader bring-up)</h2>'
        '<p>Bring-up runs used to stress-test the v2 hardware cost model, profiler, and 25-route held-out split '
        'and iron out bugs. Kept separate from standardized leaderboard entries because the environment evolved mid-run.</p></div>',
        '<div class="table-wrap"><table><thead>'
        '<tr><th>trial run</th><th>type</th><th class="num">routes</th>'
        '<th class="num">best valid&times;</th><th class="num">console</th>'
        '<th class="num">vs -O2</th><th class="num">mean FPS</th><th class="num">attempt repo</th></tr></thead><tbody>',
    ]
    for ar in trial_runs:
        s = ar["summary"]
        p = primary_profile(s)
        valid = s["status"] == "valid" and p.get("valid", True)
        sp = float(p.get("speedup", 0.0)) if valid else 0.0
        rew = float(p.get("reward", -1.0))
        vs_o2 = p.get("vs_o2_speedup")
        fps = (mean_fps(s) or 0.0) if valid else 0.0
        n_routes = len(s.get("workloads", {}))
        repo_link = f'<a href="{esc(ar["repo_url"])}" target="_blank" rel="noreferrer noopener">GitHub &rarr;</a>' if ar.get("repo_url") else "&mdash;"
        nm = f'<a href="{esc(ar["repo_url"])}" target="_blank" rel="noreferrer noopener"><b>{esc(ar["title"])}</b></a>' if ar.get("repo_url") else f'<b>{esc(ar["title"])}</b>'
        sp_txt = f'{sp:.2f}&times;' if valid else "invalid"
        vs_txt = f'{vs_o2:.2f}&times;' if (valid and vs_o2) else "&mdash;"
        rew_txt = f'{rew:+.3f}' if valid else "&minus;1.000"
        fps_txt = f'{fps:.1f}' if valid else "&mdash;"
        t_rows.append(
            f'<tr class="trial-row"><td>{nm} ({esc(ar["hours"])}h)<br><span class="small muted">{esc(ar["notes"])}</span></td>'
            f'<td><span class="tag trial">trial</span></td>'
            f'<td class="num">{n_routes}</td>'
            f'<td class="num pos"><b>{sp_txt}</b></td>'
            f'<td class="num {"pos" if rew > 0.0005 else ""}">{rew_txt}</td>'
            f'<td class="num">{vs_txt}</td>'
            f'<td class="num">{fps_txt}</td>'
            f'<td class="num">{repo_link}</td></tr>'
        )
    t_rows.append("</tbody></table></div>")

    cohorts = {}
    for run in trial_runs:
        if checkpoint_points(run):
            cohorts.setdefault(run["summary"]["workload_set"], []).append(run)
    for cohort, runs in cohorts.items():
        refs = [row for row in [*sm64_rows, *trial_rows] if row[3].get("workload_set") == cohort]
        count = max(len(run["summary"].get("workloads", {})) for run in runs)
        t_rows.append(f'<div class="chart-box"><div class="panel-title" style="margin-bottom:8px">Trial run checkpoints ({count} routes &mdash; hover points for details)</div>'
                      + trajectory_svg(refs, runs, chart_id=chart_id) + '</div>')
    return "\n".join(t_rows)


def export_clips(out):
    """Copy pre-rendered Super Mario 64 3-panel comparison clips into out/assets/clips/."""
    meta_path = CLIPS_SRC / "clips.json"
    dst = out / "assets" / "clips"
    if dst.exists():
        shutil.rmtree(dst)
    if not meta_path.is_file():
        return []
    clips = json.loads(meta_path.read_text())
    dst.mkdir(parents=True, exist_ok=True)
    kept = []
    for c in clips:
        src_mp4 = CLIPS_SRC / c["video"]
        if src_mp4.is_file():
            shutil.copy2(src_mp4, dst / c["video"])
            kept.append(c)
    return kept


def comparison_monitor_html(clips):
    """Interactive 3-panel (Reference | Candidate | Difference) CRT monitor widget."""
    if not clips:
        return ""
    tabs = "".join(
        f'<button class="pill{" on" if i == 0 else ""}" data-idx="{i}">{esc(c["tab"])}</button>'
        for i, c in enumerate(clips)
    )
    c0 = clips[0]
    return f"""
<div class="monitor" id="cmp-monitor">
  <div class="monitor-head">
    <div class="panel-title">Live Super Mario 64 Gate Replay &mdash; 1996 Baseline vs Candidate vs Difference</div>
    <span class="tag {esc(c0["badge_cls"])}" id="cmp-badge">{esc(c0["badge"])}</span>
  </div>
  <div class="pill-bar" id="cmp-tabs" style="margin-bottom:12px">{tabs}</div>
  <div class="monitor-screen">
    <video id="cmp-vid" src="{BASE}/assets/clips/{esc(c0["video"])}" autoplay muted loop playsinline preload="metadata"></video>
    <div class="screen-labels">
      <span>1996 Retail US Baseline</span>
      <span id="cmp-cand-lbl">Candidate ({esc(c0["slug"])})</span>
      <span>Gate Pixel Difference</span>
    </div>
  </div>
  <div class="monitor-controls">
    <button type="button" id="cmp-play">Pause</button>
    <button type="button" id="cmp-speed">1&times;</button>
    <input class="monitor-scrub" id="cmp-scrub" type="range" min="0" max="{c0["frames"] - 1}" value="0" aria-label="Frame scrubber">
    <span class="monitor-readout" id="cmp-readout">frame <b>000</b>/{c0["frames"]} &middot; <b>{c0["base_mean_ms"]:.1f}ms</b> &rarr; <b>{c0["cand_mean_ms"]:.1f}ms</b></span>
  </div>
  <div class="timeline-wrap">
    <div class="timeline-hdr">
      <span>Per-frame console ms (dim = 1996 baseline, bright = candidate; red = pixel diff &gt; 0.2%)</span>
      <span id="cmp-tl-stat">click timeline to seek</span>
    </div>
    <svg id="cmp-tl" viewBox="0 0 239 44" preserveAspectRatio="none" role="img" aria-label="Per-frame console timing and diff timeline"></svg>
  </div>
  <div class="monitor-cap">
    <span id="cmp-cap">{esc(c0["caption"])}</span>
    <span class="small muted">Captured directly from <code>ares</code> N64 on public Super Mario 64 routes (240 frames @ 30 fps)</span>
  </div>
</div>
<script>(function(){{
var CLIPS={json.dumps(clips)};
var BASE="{BASE}/assets/clips/";
var vid=document.getElementById("cmp-vid"),
    tabs=document.querySelectorAll("#cmp-tabs .pill"),
    badge=document.getElementById("cmp-badge"),
    candLbl=document.getElementById("cmp-cand-lbl"),
    cap=document.getElementById("cmp-cap"),
    btnPlay=document.getElementById("cmp-play"),
    btnSpd=document.getElementById("cmp-speed"),
    scrub=document.getElementById("cmp-scrub"),
    readout=document.getElementById("cmp-readout"),
    tlSvg=document.getElementById("cmp-tl"),
    tlStat=document.getElementById("cmp-tl-stat");
var cur=0, slow=false, playhead=null;

function drawTimeline(c){{
  var n=c.base_ms.length;
  var maxMs=Math.max.apply(null,c.base_ms.concat(c.cand_ms).concat([40]))*1.08;
  var col=c.badge_cls==="invalid"?"#ff5a63":(c.badge_cls==="ref"?"#7b68ee":"#2ed573");
  var parts=[];
  for(var i=0;i<n;i++){{
    var bh=(c.base_ms[i]/maxMs)*40;
    var ch=(c.cand_ms[i]/maxMs)*40;
    parts.push('<rect x="'+i+'" y="'+(44-bh).toFixed(1)+'" width="0.85" height="'+bh.toFixed(1)+'" fill="#38344a"/>');
    var barCol=(c.diff_pct[i]>0.2 && c.badge_cls==="invalid")?"#ff5a63":col;
    parts.push('<rect x="'+i+'" y="'+(44-ch).toFixed(1)+'" width="0.85" height="'+ch.toFixed(1)+'" fill="'+barCol+'" opacity="0.88"/>');
  }}
  parts.push('<rect id="cmp-head" x="0" y="0" width="1.4" height="44" fill="#ffffff" opacity="0.9"/>');
  tlSvg.setAttribute("viewBox","0 0 "+n+" 44");
  tlSvg.innerHTML=parts.join("");
  playhead=document.getElementById("cmp-head");
}}

function selectClip(idx){{
  cur=idx;
  var c=CLIPS[idx];
  tabs.forEach(function(b,i){{b.classList.toggle("on",i===idx);}});
  badge.textContent=c.badge;
  badge.className="tag "+c.badge_cls;
  candLbl.textContent="Candidate ("+c.slug+")";
  cap.textContent=c.caption;
  scrub.max=c.frames-1;
  vid.src=BASE+c.video;
  vid.playbackRate=slow?0.5:1.0;
  vid.play().catch(function(){{}});
  btnPlay.textContent="Pause";
  drawTimeline(c);
}}

function tick(){{
  var c=CLIPS[cur];
  if(c && vid.duration>0){{
    var f=Math.min(c.frames-1,Math.max(0,Math.floor(vid.currentTime*c.fps)));
    var fi=Math.min(c.base_ms.length-1,Math.max(0,f-1));
    if(document.activeElement!==scrub) scrub.value=f;
    if(playhead) playhead.setAttribute("x",fi);
    var bms=c.base_ms[fi], cms=c.cand_ms[fi], dp=c.diff_pct[fi];
    readout.innerHTML="frame <b>"+String(f).padStart(3,"0")+"</b>/"+c.frames+" &middot; <b>"+bms.toFixed(1)+"ms</b> &rarr; <b>"+cms.toFixed(1)+"ms</b>";
    tlStat.textContent="diff: "+dp.toFixed(2)+"% px";
  }}
  requestAnimationFrame(tick);
}}

tabs.forEach(function(b){{
  b.addEventListener("click",function(){{selectClip(parseInt(b.getAttribute("data-idx"),10));}});
}});
btnPlay.addEventListener("click",function(){{
  if(vid.paused){{vid.play();btnPlay.textContent="Pause";}}
  else{{vid.pause();btnPlay.textContent="Play";}}
}});
btnSpd.addEventListener("click",function(){{
  slow=!slow; vid.playbackRate=slow?0.5:1.0; btnSpd.innerHTML=slow?"0.5&times;":"1&times;";
}});
scrub.addEventListener("input",function(){{
  var c=CLIPS[cur]; vid.currentTime=parseInt(scrub.value,10)/c.fps;
}});
tlSvg.addEventListener("click",function(e){{
  var c=CLIPS[cur], r=tlSvg.getBoundingClientRect();
  var frac=Math.max(0,Math.min(1,(e.clientX-r.left)/r.width));
  vid.currentTime=frac*(c.frames/c.fps);
}});
drawTimeline(CLIPS[0]);
requestAnimationFrame(tick);
}})();</script>
"""


def build_index(out, rows, sm64_rows, trial_rows, agent_runs, post_items, exported_frames, clips):
    post_links = "".join(
        f'<li><a href="{BASE}/blog/{slug}/"><b>{esc(m["title"])}</b></a><span class="date">{m["date"]}</span><br>'
        f'<span class="small muted">{esc(m["summary"])}</span></li>' for slug, m, _ in post_items)

    sm64_by_slug = {slug: s for slug, *_r, s in sm64_rows if s["status"] == "valid"}
    ceil_kpi = ""
    if EXPERT_REF in sm64_by_slug and "r0-unchanged" in sm64_by_slug:
        r0 = sm64_by_slug["r0-unchanged"]
        r1 = sm64_by_slug.get("r1-gcc-o2", r0)
        r10 = sm64_by_slug[EXPERT_REF]
        r0_fps = mean_fps(r0) or 0.0
        r10_fps = mean_fps(r10) or 0.0
        r10_sp = primary_profile(r10).get("speedup", 1.0)
        r1_sp = primary_profile(r1).get("speedup", 1.0)
        trial_best = next((ar for ar in agent_runs if ar.get("kind") == "trial" and ar["summary"].get("status") == "valid"), None)
        trial_kpi = ""
        if trial_best:
            tsp = primary_profile(trial_best["summary"]).get("speedup", 0.0)
            trial_kpi = f'<div class="kpi"><div class="val amber">{tsp:.2f}&times;</div><div class="lbl">Kimi K3.1 Pro trial best valid (25 routes, beats Kaze 1.65&times;)</div></div>'
        ceil_kpi = f"""
<div class="kpis">
  <div class="kpi"><div class="val">{r0_fps:.0f} &rarr; {r10_fps:.0f} FPS</div><div class="lbl">uncapped console throughput (1000 / est. console ms): 1996 IDO vs Kaze master</div></div>
  <div class="kpi"><div class="val indigo">{r1_sp:.2f}&times;</div><div class="lbl">GCC -O2 compiler-only baseline (zero C edits)</div></div>
  <div class="kpi"><div class="val pcb">{r10_sp:.2f}&times;</div><div class="lbl">Kaze master reference (6 public courses; 1.65&times; on 25 routes)</div></div>
  {trial_kpi}
</div>
"""

    inspector = telemetry_inspector_html(sm64_rows, agent_runs)
    monitor = comparison_monitor_html(clips)
    trial_sec = trial_section_html(agent_runs, sm64_rows, trial_rows, chart_id="home-trial-traj")
    gallery = pips_gallery_html(exported_frames, rows)

    body = f"""
<div class="hero">
  <div>
    <div class="eyebrow"><span class="dot"></span>N64 4 MB Hardware RLVR Benchmark</div>
    <h1>Super-optimize an N64 game. Don't change it.</h1>
    <p class="lede">An AI coding agent gets the C decompilation of <b>Super Mario 64</b> (or the open-source <b>Pip's Garden</b>), pinned N64 compilers, an instrumented cycle/cache/RDP-accurate <code>ares</code> emulator, and 24 hours to make original 4 MB console execution faster while preserving gameplay, picture, and 40 dB audio.</p>
    <div class="hero-links">
      <a class="btn primary" href="{BASE}/leaderboard/">View Leaderboard &rarr;</a>
      <a class="btn" href="{BASE}/calibration/">Calibration Suite</a>
      <a class="btn" href="{REPO}" target="_blank" rel="noreferrer noopener">Source on GitHub</a>
    </div>
  </div>
  {PIP_SVG}
</div>

{ceil_kpi}

{monitor}

{trial_sec}

{inspector}

<h2>How a submission is graded</h2>
<div class="diagram">{PIPELINE_SVG}</div>

<div class="cards">
  <div class="card primary"><h3>console <span>headline</span></h3><p>Per-frame <code>max(CPU_ms, RSP_ms, RDP_ms, RDRAM_ms)</code> within 4 MB RDRAM &mdash; true console frame time.</p></div>
  <div class="card"><h3>speed <span>diagnostic</span></h3><p>93.75 MHz VR4300 CPU cycles per frame, including 16 KB I$ / 8 KB D$ stalls and RCP bus contention.</p></div>
  <div class="card"><h3>rdp <span>diagnostic</span></h3><p>62.5 MHz RDP combiner, early-Z rejection, 4-bank 2 KB RDRAM row misses, TMEM loads &amp; syncs.</p></div>
  <div class="card"><h3>rsp <span>diagnostic</span></h3><p>62.5 MHz RSP Fast3D graphics &amp; ABI1 audio microcode busy cycles per frame.</p></div>
  <div class="card"><h3>traffic <span>diagnostic</span></h3><p>RDRAM bytes moved per frame across CPU caches, SP, DP, PI, SI &amp; 60 Hz VI scanout.</p></div>
  <div class="card"><h3>memory <span>diagnostic</span></h3><p>Distinct 16-byte RDRAM lines touched after boot (hard 4,194,304 B retail ceiling).</p></div>
</div>

<h2>Pip's Garden (open-source zero-ROM target)</h2>
<p class="muted">Ships complete in-repo (<code>workload/</code>) so anyone can run the full 24-hour harness without an external ROM:</p>
{gallery}

<h2>Writing</h2>
<ul class="post-list">{post_links}</ul>
"""
    write(out, "index.html", page("Mario Eval — Super-optimize an N64 game on real hardware", body, active=""))


def build_leaderboard(out, sm64_rows, trial_rows, agent_runs):
    sm64_valid = [(slug, title, purpose, s) for slug, title, purpose, s in sm64_rows if s["status"] == "valid"]
    by_slug = {slug: (title, purpose, s) for slug, title, purpose, s in sm64_valid}

    ref_order = [
        ("r11-beyond-kaze", "Beyond Kaze (R11)", "ref",
         "Earlier Kaze-style build with additional D-cache experiments; scores below the current expert reference"),
        ("r10-kaze-master", "Kaze master reference (R10)", "ceiling",
         "Reconstructed techniques from Kaze Emanuar's public work, checked against the vanilla game"),
        ("r9-kaze-partial", "Partial Kaze reference (R9)", "ref",
         "I-cache + 1-ULP trig + 3-line Surface + Sub cache + lazy Mtx + RA_ZB_OPA + coin batch + -304 KB"),
        ("r8-kaze-collision-objects", "Kaze Rung 2: Collision & Objects (R8)", "ref",
         "R7 + 3-cache-line struct Surface + Bowser's Sub stationary surface cache + single-floor shadows + watermark pool"),
        ("r7-kaze-icache-trig", "Kaze Rung 1: I-Cache & Table-Free Math (R7)", "ref",
         "sm64.ld 16 KB I-cache de-aliasing + 1-ULP polynomial sins/coss + bit-exact 256 B atan2s + IEEE random_float"),
        ("r6-kaze-super", "Early Multi-Subsystem Rung (R6)", "ref",
         "GCC -O2 + Kaze matrix math + CACHE 0x0d + skybox cull + double-buffer"),
        ("r1-gcc-o2", "Compiler Only: GCC -O2 -fno-fast-math (R1)", "compiler",
         "Zero C edits: switch Makefile from 1996 IDO -O0 to modern mips64-elf-gcc -O2"),
        ("r4-kaze-rdp-opa", "IDO -O0 + G_RM_RA_ZB_OPA_SURF (R4)", "ref",
         "Drop per-pixel IM_RD framebuffer reads on opaque surfaces under original IDO compiler"),
        ("r2-kaze-mtx", "IDO -O0 + Kaze Matrix Math (R2)", "ref",
         "Stackless mtxf_mul + packed 32-bit mtxf_to_mtx under original IDO compiler"),
        ("r0-unchanged", "1996 Retail US Baseline (IDO -O0)", "ref",
         "Unmodified n64decomp/sm64 matching the 8 MB retail US cartridge"),
    ]

    entries = []
    base_foot = None
    if "r0-unchanged" in by_slug:
        w0 = list(by_slug["r0-unchanged"][2]["workloads"].values())
        base_foot = sum(x["metrics"]["footprint_bytes"] for x in w0) / len(w0)

    def _entry_profiles(s):
        out_p = {}
        for p in PROFILES:
            pv = s.get("profiles", {}).get(p, {})
            ok = s["status"] == "valid" and pv.get("valid", False)
            out_p[p] = {
                "valid": ok,
                "speedup": round(float(pv.get("speedup", 0.0)), 3) if ok else 0.0,
                "reward": round(float(pv.get("reward", -1.0)), 4) if ok else -1.0,
                "vs_o2": round(float(pv["vs_o2_speedup"]), 3) if (ok and pv.get("vs_o2_speedup")) else None,
            }
        return out_p

    for slug, label, kind, note in ref_order:
        if slug not in by_slug:
            continue
        s = by_slug[slug][2]
        p = primary_profile(s)
        wls = list(s["workloads"].values())
        foot = sum(x["metrics"]["footprint_bytes"] for x in wls) / len(wls)
        entries.append({
            "name": label,
            "href": f"{BASE}/calibration/#sm64-{slug}",
            "kind": kind,
            "note": note,
            "reward": float(p.get("reward", 0.0)),
            "speedup": float(p.get("speedup", 1.0)),
            "vs_o2": p.get("vs_o2_speedup"),
            "fps": round(mean_fps(s) or 0.0, 1),
            "traffic_x": round(float(s["profiles"].get("traffic", {}).get("speedup", 1.0)), 2),
            "ram_saved_kb": round(((base_foot - foot) / 1024.0), 0) if base_foot else 0.0,
            "valid": s["status"] == "valid" and p.get("valid", True),
            "profiles": _entry_profiles(s),
        })

    public_set = by_slug.get("r0-unchanged", (None, None, {}))[2].get("workload_set")
    for ar in agent_runs:
        if ar.get("kind") == "trial":
            continue
        if not public_set or ar["summary"].get("workload_set") != public_set:
            continue
        s = ar["summary"]
        p = primary_profile(s)
        valid = s["status"] == "valid" and p.get("valid", True)
        wls = list(s.get("workloads", {}).values())
        foot = (sum(x["metrics"]["footprint_bytes"] for x in wls) / len(wls)) if wls else (base_foot or 0.0)
        entries.append({
            "name": f"{ar['title']} ({ar['hours']}h)",
            "href": ar.get("repo_url", ""),
            "kind": "agent",
            "note": ar["notes"],
            "reward": float(p.get("reward", -1.0)),
            "speedup": float(p.get("speedup", 0.0)) if valid else 0.0,
            "vs_o2": p.get("vs_o2_speedup"),
            "fps": round((mean_fps(s) or 0.0), 1) if valid else 0.0,
            "traffic_x": round(float(s["profiles"].get("traffic", {}).get("speedup", 0.0)), 2) if valid else 0.0,
            "ram_saved_kb": round(((base_foot - foot) / 1024.0), 0) if (base_foot and valid) else 0.0,
            "valid": valid,
            "profiles": _entry_profiles(s),
        })

    entries.sort(key=lambda e: (1 if e["valid"] else 0, e["speedup"]), reverse=True)
    max_sp = max([e["speedup"] for e in entries if e["valid"]] + [1.25])

    prof_pills = "".join(
        f'<button class="pill{" on" if p == "console" else ""}" data-prof="{p}">{p}</button>' for p in PROFILES
    )
    rows_html = [
        '<div class="panel-head" style="margin-top:16px"><div class="panel-title">Super Mario 64 Reference Ladder (6 public courses)</div>'
        f'<div class="pill-bar" id="lb-prof-bar">{prof_pills}</div></div>',
        '<div class="table-wrap"><table id="lb-table"><thead>',
        '<tr><th>entry</th><th>type</th><th class="bar-cell" id="lb-sp-hdr">console speedup</th>'
        '<th class="num" id="lb-rew-hdr">console</th><th class="num">vs -O2</th><th class="num">mean FPS</th>'
        '<th class="num">bus&times;</th><th class="num">RAM &Delta;</th></tr></thead><tbody>',
    ]
    for e in entries:
        nm = f'<a href="{e["href"]}">{esc(e["name"])}</a>' if e["href"] else f'<b>{esc(e["name"])}</b>'
        tag_cls = "valid" if e["kind"] == "ceiling" else ("ref" if e["kind"] in ("ref", "compiler") else ("valid" if e["valid"] else "invalid"))
        pct = 0.0 if not e["valid"] else max(6.0, min(100.0, (e["speedup"] / max_sp) * 100.0))
        bar_cls = "ceiling" if e["kind"] == "ceiling" else ("compiler" if e["kind"] == "compiler" else "")
        sp_txt = f'{e["speedup"]:.2f}&times;' if e["valid"] else "invalid"
        vs_txt = f'{e["vs_o2"]:.2f}&times;' if (e["valid"] and e["vs_o2"]) else "&mdash;"
        rew_txt = f'{e["reward"]:+.3f}' if e["valid"] else "&minus;1.000"
        fps_txt = f'{e["fps"]:.1f}' if e["valid"] else "&mdash;"
        traf_txt = f'{e["traffic_x"]:.2f}&times;' if e["valid"] else "&mdash;"
        ram_txt = f'{-e["ram_saved_kb"]:+.0f} KiB' if (e["valid"] and abs(e["ram_saved_kb"]) >= 1.0) else "0 KiB"
        rows_html.append(
            f'<tr{" class=ceiling-row" if e["kind"] == "ceiling" else ""}>'
            f'<td>{nm}<br><span class="small muted">{esc(e["note"])}</span></td>'
            f'<td><span class="tag {tag_cls}">{esc(e["kind"])}</span></td>'
            f'<td class="bar-cell"><b>{sp_txt}</b><div class="bar-track"><div class="bar-fill {bar_cls}" style="width:{pct:.1f}%"></div></div></td>'
            f'<td class="num {"pos" if e["reward"] > 0.0005 else ""}">{rew_txt}</td>'
            f'<td class="num">{vs_txt}</td>'
            f'<td class="num">{fps_txt}</td>'
            f'<td class="num">{traf_txt}</td>'
            f'<td class="num">{ram_txt}</td>'
            f'</tr>'
        )
    rows_html.append("</tbody></table></div>")

    lb_script = f"""<script>(function(){{
var ENTRIES={json.dumps(entries)};
var tbody=document.querySelector("#lb-table tbody");
var spHdr=document.getElementById("lb-sp-hdr"),rewHdr=document.getElementById("lb-rew-hdr");
var btns=document.querySelectorAll("#lb-prof-bar .pill");
function esc(s){{return String(s).replace(/[&<>"]/g,function(c){{return{{"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}}[c];}});}}
function render(prof){{
  spHdr.textContent=prof+" speedup";rewHdr.textContent=prof;
  var list=ENTRIES.slice().sort(function(a,b){{
    var pa=a.profiles[prof]||{{valid:false,speedup:0}},pb=b.profiles[prof]||{{valid:false,speedup:0}};
    if(pa.valid!==pb.valid)return pb.valid?1:-1;
    return pb.speedup-pa.speedup;
  }});
  var maxSp=Math.max.apply(null,list.map(function(e){{var p=e.profiles[prof];return p&&p.valid?p.speedup:0;}}).concat([1.25]));
  tbody.innerHTML=list.map(function(e){{
    var p=e.profiles[prof]||{{valid:false,speedup:0,reward:-1,vs_o2:null}};
    var nm=e.href?'<a href="'+e.href+'">'+esc(e.name)+'</a>':'<b>'+esc(e.name)+'</b>';
    var tagCls=e.kind==="ceiling"?"valid":(e.kind==="ref"||e.kind==="compiler"?"ref":(p.valid?"valid":"invalid"));
    var barCls=e.kind==="ceiling"?"ceiling":(e.kind==="compiler"?"compiler":"");
    var pct=p.valid?Math.max(6,Math.min(100,(p.speedup/maxSp)*100)):0;
    var spTxt=p.valid?p.speedup.toFixed(2)+"&times;":"over budget";
    var vsTxt=(p.valid&&p.vs_o2)?p.vs_o2.toFixed(2)+"&times;":"&mdash;";
    var rewTxt=p.valid?(p.reward>=0?"+":"")+p.reward.toFixed(3):"&minus;1.000";
    var ramTxt=Math.abs(e.ram_saved_kb)>=1?(-e.ram_saved_kb>0?"+":"")+(-e.ram_saved_kb).toFixed(0)+" KiB":"0 KiB";
    return '<tr'+(e.kind==="ceiling"?' class="ceiling-row"':'')+(p.valid?'':' class="invalid"')+'>'
      +'<td>'+nm+'<br><span class="small muted">'+esc(e.note)+'</span></td>'
      +'<td><span class="tag '+tagCls+'">'+esc(e.kind)+'</span></td>'
      +'<td class="bar-cell"><b>'+spTxt+'</b><div class="bar-track"><div class="bar-fill '+barCls+'" style="width:'+pct.toFixed(1)+'%"></div></div></td>'
      +'<td class="num '+(p.valid&&p.reward>0.0005?'pos':(p.valid?'':'neg'))+'">'+rewTxt+'</td>'
      +'<td class="num">'+vsTxt+'</td>'
      +'<td class="num">'+(e.valid?e.fps.toFixed(1):"&mdash;")+'</td>'
      +'<td class="num">'+(e.valid?e.traffic_x.toFixed(2)+"&times;":"&mdash;")+'</td>'
      +'<td class="num">'+ramTxt+'</td></tr>';
  }}).join("");
}}
btns.forEach(function(b){{
  b.addEventListener("click",function(){{
    btns.forEach(function(x){{x.classList.remove("on");}});
    b.classList.add("on");
    render(b.getAttribute("data-prof"));
  }});
}});
}})();</script>"""

    trial_html = trial_section_html(agent_runs, sm64_rows, trial_rows, chart_id="lb-trial-traj")

    charts = [f'<div class="chart-box">{trajectory_svg(sm64_rows, [], chart_id="ladder")}</div>']
    std_cohorts = {}
    for run in agent_runs:
        if run.get("kind") == "trial":
            continue
        if checkpoint_points(run):
            std_cohorts.setdefault(run["summary"]["workload_set"], []).append(run)
    for idx, (cohort, runs) in enumerate(std_cohorts.items()):
        refs = [row for row in [*sm64_rows, *trial_rows] if row[3].get("workload_set") == cohort]
        count = max(len(run["summary"].get("workloads", {})) for run in runs)
        charts.append(f'<div class="chart-box"><div class="panel-title" style="margin-bottom:8px">Agent checkpoints ({count} routes)</div>'
                      + trajectory_svg(refs, runs, chart_id=f"std-traj-{idx}") + '</div>')
    b_svg = sm64_bottleneck_svg(sm64_rows)
    b_box = f'<div class="chart-box">{b_svg}</div>' if b_svg else ""

    body = f"""
<div class="prose">
<h1>Leaderboard</h1>
<p>Reference rungs are graded across <b>6 public Super Mario 64 courses</b> (240 frames each) on an instrumented
<code>ares</code> N64 console model (93.75 MHz VR4300 + 16 KB I$ / 8 KB D$, 62.5 MHz RSP &amp; RDP, 4 MB RDRAM).
Switch resource profiles below to re-rank by <code>console</code>, <code>stutter</code>, <code>speed</code>,
<code>rdp</code>, <code>rsp</code>, <code>traffic</code>, or <code>memory</code>. The human-expert yardstick is the
<a href="{BASE}/blog/kaze-master-reference/">Kaze master reference</a>.</p>
</div>

{"".join(rows_html)}
{lb_script}

{trial_html}

{"".join(charts)}
{b_box}

<div class="prose">
<h2>Run a 24-hour agent evaluation</h2>
<p><code>mev check</code> grades public routes for agent feedback (~29s clean). The host supervisor writes
<code>trajectory.json</code> with separate private held-out checkpoints. Do not publish private replays.</p>
<pre><code># 1. Prepare the game and private controller inputs (set PRIVATE_SEED)
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
python3 sm64/corpus/make_replays.py --heldout /private/replays --mash-seed "$PRIVATE_SEED"
./scripts/build-images.sh --game sm64 --no-task
./scripts/precompute.sh --game sm64 --heldout /private/replays
./scripts/build-images.sh --game sm64
./quickstart/smoke-test.sh --game sm64

# 2. Launch a 24-hour timed run
docker compose --project-directory quickstart up -d
AGENT_CMD='your-agent-command' ./quickstart/run-agent.sh --game sm64 \\
  --hours 24 --profile console --heldout /private/replays</code></pre>
</div>
"""
    write(out, "leaderboard/index.html",
          page("Leaderboard | Mario Eval", body, active="leaderboard/"))


def render_sections(rows, patch_dir, anchor_prefix=""):
    sections = []
    metric_keys = [
        ("est_console_ms", "console"),
        ("frame_ticks", "CPU"),
        ("rdp_busy", "RDP"),
        ("rsp_busy", "RSP"),
        ("rdram_bytes", "RDRAM"),
        ("footprint_bytes", "footprint"),
    ]
    for slug, title, purpose, s in rows:
        detail = []
        if s["status"] == "valid":
            hdr = "".join(f"<th class=num>{lbl}</th>" for _, lbl in metric_keys) + "<th class=num>FPS</th>"
            detail.append(f'<div class="table-wrap"><table><thead><tr><th>workload</th>{hdr}</tr></thead><tbody>')
            for wid, d in s["workloads"].items():
                r = d["ratios"]
                m = d["metrics"]
                fps = m.get("est_fps", 1000.0 / max(m.get("est_console_ms", m["frame_ms"]), 1e-6))
                cells = []
                for k, _ in metric_keys:
                    val = r.get(k, r.get("frame_ticks", 1.0) if k == "est_console_ms" else 1.0)
                    cells.append(f"<td class=num>{val:.3f}</td>")
                cells.append(f"<td class=num>{fps:.1f}</td>")
                detail.append(f"<tr><td>{esc(wid)}</td>" + "".join(cells) + "</tr>")
            detail.append("</tbody></table></div><p class='small muted'>Ratios to baseline (lower is better), plus estimated real-hardware FPS.</p>")
            notes = [f"<li><b>{p}</b>: {esc(v['reason'])}</li>" for p, v in s["profiles"].items() if not v["valid"]]
            if notes:
                detail.append("<ul class=small>" + "".join(notes) + "</ul>")
        else:
            items = []
            for g, v in s["gates"].items():
                if v["pass"]:
                    continue
                if "modified" in v:
                    items.append(f"<li><b>{g}</b>: modified {esc(', '.join(v['modified']))}</li>")
                    continue
                if "play_build" in v and not v["play_build"]:
                    items.append(f"<li><b>{g}</b>: PLAY=1 console build failed</li>")
                    continue
                for wid, x in v.get("workloads", {}).items():
                    if x.get("pass"):
                        continue
                    if "field" in x:
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: frame {x['frame']}, <code>{esc(x['field'])}</code> "
                                     f"= {esc(x['cand'])} (original {esc(x['ref'])})</li>")
                    elif "worst_bad_fraction" in x:
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: {100 * x['worst_bad_fraction']:.2f}% of pixels "
                                     f"fail on frame {x['worst_frame']} (limit 0.20%)</li>")
                    elif "snr_db" in x:
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: SNR {x['snr_db']:.1f} dB (limit 40 dB)</li>")
                    else:
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: {esc(x.get('reason', x.get('status')))}</li>")
            detail.append("<ul class=small>" + "".join(items[:8]) + "</ul>")
        link = "" if slug == "r0-unchanged" else f' &middot; <a href="{REPO}/blob/main/{patch_dir}/{slug}.patch">patch</a>'
        sections.append(f'<h2 id="{anchor_prefix}{slug}">{title} <span class="tag {s["status"]}">{s["status"]}</span></h2>'
                        f'<p class="muted">{purpose}{link}</p>' + "\n".join(detail))
    return "".join(sections)


def build_calibration(out, rows, sm64_rows):
    sm64_part = ""
    if sm64_rows:
        sm64_part = (
            '<h2>Super Mario 64 (US, 6 courses)</h2>'
            + cal_table(sm64_rows, anchor_prefix="sm64-")
            + '<h3>Baseline (1996 IDO <code>-O0</code>)</h3>'
            + baseline_table(sm64_rows)
            + render_sections(sm64_rows, "sm64/calibration", anchor_prefix="sm64-")
            + "<hr>"
        )
    body = f"""<div class="prose"><h1>Calibration</h1>
<p>Each patch is applied to a clean baseline. The tables report the six public SM64 routes and
eight Pip's Garden routes (240 frames each). The headline profile is <code>console</code>;
<code>stutter</code> reports the p99 frame cost alongside five resource-specific profiles.</p></div>
{sm64_part}
<h2>Pip's Garden (8 routes)</h2>
{cal_table(rows)}
<h3>Pip's Garden baseline</h3>
{baseline_table(rows)}
{render_sections(rows, "calibration")}"""
    write(out, "calibration/index.html", page("Calibration | Mario Eval", body, active="calibration/"))


def build_blog(out, post_items):
    lis = "".join(
        f'<li><a href="{BASE}/blog/{slug}/"><b>{esc(m["title"])}</b></a><span class="date">{m["date"]}</span><br>'
        f'<span class="small muted">{esc(m["summary"])}</span></li>' for slug, m, _ in post_items)
    write(out, "blog/index.html", page("Blog | Mario Eval", f'<div class="prose"><h1>Blog</h1><ul class="post-list">{lis}</ul></div>', active="blog/"))
    for slug, m, text in post_items:
        body = (f'<article class="prose"><h1>{esc(m["title"])}</h1><p class="meta">{m["date"]}</p>'
                f'{text.replace("{BASE}", BASE).replace("{REPO}", REPO)}</article>')
        write(out, f"blog/{slug}/index.html", page(f'{m["title"]} | Mario Eval', body, active="blog/", desc=m["summary"]))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(SITE / "style.css", out / "style.css")
    exported_frames = export_pips_frames(out)
    clips = export_clips(out)
    rows = load_cal(CAL, PATCHES)
    sm64_rows = load_cal(SM64_CAL, SM64_PATCHES)
    trial_rows = load_cal(SM64_TRIAL_CAL, SM64_PATCHES)
    agent_runs = load_agent_runs()
    post_items = posts()
    build_index(out, rows, sm64_rows, trial_rows, agent_runs, post_items, exported_frames, clips)
    build_leaderboard(out, sm64_rows, trial_rows, agent_runs)
    build_calibration(out, rows, sm64_rows)
    build_blog(out, post_items)
    print(f"wrote {out}: {len(rows)} pips entries, {len(sm64_rows)} sm64 entries, "
          f"{len(agent_runs)} agent runs, {len(exported_frames)} png frames, {len(clips)} clips, {len(post_items)} posts")


if __name__ == "__main__":
    main()
