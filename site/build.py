#!/usr/bin/env python3
"""Build the Mario Eval website (served at https://ilya.as/mario-eval/).

    python3 site/build.py <out_dir>

Reads the calibration summaries (results/calibration/*/summary.json and
results/sm64-calibration/*/summary.json when present), optional 24-hour agent
runs (results/agents/*/summary.json + trajectory.json), Pip's Garden public
reference frames (cache/reference/runs/*/video.bin.z when present, never any
Nintendo SM64 assets), and the hand-written posts in site/posts/.
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
AGENTS_DIR = ROOT / "results" / "agents"
PIPS_REF_RUNS = ROOT / "cache" / "reference" / "runs"
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
     "Matching US decompilation baseline scores 0 across all six hardware profiles."),
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
    ("r9-kaze-ceiling", "Kaze Rung 3 (Reference Ceiling): lazy <code>Mtx</code> + fast frustum cull + coin TMEM batch + <code>&minus;304 KB</code> RAM",
     "Full-stack Kaze Emanuar hardware ceiling: defers fixed-point <code>Mtx</code> allocation past frustum cull, batches coin TMEM loads, enables <code>RA_ZB_OPA</code> + <code>CACHE 0x0d</code>, and trims 304 KB of RDRAM."),
    ("i0-gcc-fastmath", "GCC <code>-O2 -ffast-math</code>", "Breaks Mario physics/collision trajectories."),
    ("i1-mute-audio", "Disable audio synthesis (<code>sAudioEnabled = FALSE</code>)", "Caught by the 40 dB audio SNR gate."),
    ("i2-low-poly-mario", "Force low-poly Mario at all distances", "Caught by the video gate."),
    ("i3-half-physics-step", "Two quarter-steps instead of four in <code>mario_step.c</code>", "Caught by the Player Equivalence gameplay gate."),
    ("i4-tamper", "Modify <code>src/game/mev.h</code>", "Caught by the harness integrity gate."),
]

PROFILES = ["console", "speed", "rdp", "rsp", "traffic", "memory"]

PUBLIC_PIPS_ROUTES = [
    ("meadow", 35, "Meadow", "Terrain heightfield, crystals &amp; shadow decals"),
    ("fortress", 15, "Fortress", "Dense wall/floor collision &amp; patrolling hazards"),
    ("concert", 150, "Concert", "Multi-channel audio synthesis &amp; jump arcs"),
    ("storm", 150, "Storm", "Heavy rain alpha particles &amp; dash trails"),
]

SM64_COURSE_NAMES = {
    "bob": "Bob-omb Battlefield",
    "wf": "Whomp's Fortress",
    "jrb": "Jolly Roger Bay",
    "ddd": "Dire Dire Docks (Sub)",
    "bitfs": "Bowser in the Fire Sea",
    "rr": "Rainbow Ride",
}

PIP_SVG = """<svg viewBox="0 0 200 220" role="img" aria-label="Pip, a small round robot">
  <line x1="100" y1="44" x2="100" y2="18" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
  <polygon points="100,4 110,16 100,28 90,16" fill="#3fb6e8" stroke="currentColor" stroke-width="3"/>
  <ellipse cx="100" cy="76" rx="52" ry="38" fill="#eeeade" stroke="currentColor" stroke-width="4"/>
  <rect x="62" y="62" width="76" height="28" rx="14" fill="#23314f" stroke="currentColor" stroke-width="3"/>
  <circle cx="84" cy="76" r="6" fill="#7fe3ff"/>
  <circle cx="116" cy="76" r="6" fill="#7fe3ff"/>
  <ellipse cx="100" cy="150" rx="62" ry="50" fill="#f2b632" stroke="currentColor" stroke-width="4"/>
  <ellipse cx="100" cy="150" rx="26" ry="20" fill="#f7cf6a" stroke="currentColor" stroke-width="3"/>
  <path d="M40 140 q-22 6 -26 26" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
  <path d="M160 140 q22 6 26 26" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round"/>
  <ellipse cx="74" cy="204" rx="20" ry="9" fill="#5a5a60" stroke="currentColor" stroke-width="3"/>
  <ellipse cx="126" cy="204" rx="20" ry="9" fill="#5a5a60" stroke="currentColor" stroke-width="3"/>
</svg>"""

PIPELINE_SVG = """<svg viewBox="0 0 960 156" role="img" aria-label="Grading pipeline">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
    <path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker></defs>
  <g font-family="IBM Plex Mono, monospace" font-size="12.5" fill="currentColor">
    <g stroke="currentColor" stroke-width="1.5" fill="none">
      <rect x="4" y="42" width="132" height="68" rx="6"/>
      <rect x="168" y="42" width="136" height="68" rx="6"/>
      <rect x="336" y="38" width="176" height="76" rx="6"/>
      <rect x="544" y="14" width="202" height="124" rx="6"/>
      <rect x="778" y="38" width="178" height="76" rx="6"/>
      <line x1="136" y1="76" x2="166" y2="76" marker-end="url(#arr)"/>
      <line x1="304" y1="76" x2="334" y2="76" marker-end="url(#arr)"/>
      <line x1="512" y1="76" x2="542" y2="76" marker-end="url(#arr)"/>
      <line x1="746" y1="76" x2="776" y2="76" marker-end="url(#arr)"/>
    </g>
    <text x="70" y="70" text-anchor="middle">source</text>
    <text x="70" y="89" text-anchor="middle" opacity="0.7">SM64 / Pip</text>
    <text x="236" y="70" text-anchor="middle">trusted build</text>
    <text x="236" y="89" text-anchor="middle" opacity="0.7">bench + PLAY=1</text>
    <text x="424" y="63" text-anchor="middle">ares N64</text>
    <text x="424" y="81" text-anchor="middle" opacity="0.7">93.75MHz CPU + I/D$</text>
    <text x="424" y="99" text-anchor="middle" opacity="0.7">62.5MHz RSP/RDP + Bus</text>
    <text x="645" y="36" text-anchor="middle">6 gates (12 courses)</text>
    <text x="645" y="57" text-anchor="middle" opacity="0.7">player-equiv / exact</text>
    <text x="645" y="75" text-anchor="middle" opacity="0.7">video + 40 dB audio</text>
    <text x="645" y="93" text-anchor="middle" opacity="0.7">integrity + 4 MB RAM</text>
    <text x="645" y="111" text-anchor="middle" opacity="0.7">cross-budget caps</text>
    <text x="645" y="128" text-anchor="middle" opacity="0.7">any fail &rarr; &minus;1.0</text>
    <text x="867" y="64" text-anchor="middle">console score</text>
    <text x="867" y="82" text-anchor="middle" opacity="0.7">max(CPU,RSP,RDP)</text>
    <text x="867" y="100" text-anchor="middle" opacity="0.7">FPS &amp; vs -O2</text>
  </g>
</svg>"""


def esc(s):
    return html.escape(str(s))


def page(title, body, active="", desc=""):
    nav = [
        ("", "Overview"),
        ("leaderboard/", "Leaderboard"),
        ("calibration/", "Calibration"),
        ("blog/", "Blog"),
    ]
    links = " ".join(
        f'<a href="{BASE}/{href}"{" class=on" if href == active else ""}>{name}</a>' for href, name in nav)
    links += f' <a href="{REPO}">GitHub</a>'
    desc = desc or "A 24h RLVR environment: super-optimize Super Mario 64 or Pip's Garden on the original 4 MB N64 hardware without changing the game."
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/style.css">
</head><body>
<header class="site"><div class="wrap"><a class="logo" href="{BASE}/">MARIO<span>EVAL</span></a>
<nav class="site">{links}</nav></div></header>
<main class="wrap">{body}</main>
<footer class="site"><div class="wrap">
Built by <a href="https://ilya.as/">Ilyaas Kapadia</a>, modelled on Mechanize's
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
    """Pure-stdlib RGB888 PNG encoder (filter 0 per scanline)."""
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgb_bytes[y * stride:(y + 1) * stride])
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)
    return b"\x89PNG\r\n\x1a\n" + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def export_pips_frames(out):
    """Export a hero frame of each public Pip's Garden route as a 320x240 PNG."""
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
            "hours": meta.get("hours", 24),
            "notes": meta.get("notes", "24h autonomous agent run"),
            "summary": summary,
            "trajectory": traj,
        })
    return runs


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
           f'<table><tr><th>patch</th><th>status</th>{head}<th>caught by</th></tr>']
    for slug, title, _purpose, s in rows:
        row_cls = []
        if s["status"] != "valid":
            row_cls.append("invalid")
        elif slug == "r9-kaze-ceiling":
            row_cls.append("ceiling-row")
        cls = f' class="{" ".join(row_cls)}"' if row_cls else ""
        tag = f'<span class="tag {s["status"]}">{s["status"]}</span>'
        name = f'<a href="{BASE}/calibration/#{anchor_prefix}{slug}">{title}</a>' if compact else title
        out.append(f"<tr{cls}><td>{name}</td><td>{tag}</td>"
                   + "".join(reward_cell(s, p) for p in PROFILES)
                   + speedup_cell(s)
                   + fps_cell(s)
                   + f"<td class=small>{esc(failed_gates(s))}</td></tr>")
    out.append("</table></div>")
    out.append('<p class="small muted">Rewards on public + held-out routes. '
               '<b>console</b> is the headline real-hardware frame-time profile '
               '(<code>max(CPU_ms, RSP_ms, RDP_ms)</code> per frame within 4 MB RDRAM). '
               '<b>&minus;1*</b>: valid submission, but it breaks that diagnostic profile\'s cross-budget '
               '(hover for reason or speedup vs <code>-O2</code>).</p>')
    return "\n".join(out)


def baseline_table(rows):
    base = next((s for slug, *_rest, s in rows if slug == "r0-unchanged"), None)
    if not base:
        return ""
    out = ['<div class="table-wrap"><table><tr><th>workload</th><th class="num">console (ms)</th>'
           '<th class="num">FPS</th><th class="num">CPU (ms)</th><th class="num">RSP (ms)</th>'
           '<th class="num">RDP (ms)</th><th class="num">RDRAM KB</th><th class="num">footprint KiB</th></tr>']
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
    out.append("</table></div>")
    return "\n".join(out)


def sm64_bottleneck_svg(sm64_rows):
    """Render an inline SVG comparing r0-unchanged vs r9-kaze-ceiling per SM64 course."""
    by_slug = {slug: s for slug, *_r, s in sm64_rows if s["status"] == "valid"}
    base = by_slug.get("r0-unchanged")
    ceil = by_slug.get("r9-kaze-ceiling") or by_slug.get("r8-kaze-collision-objects") or by_slug.get("r7-kaze-icache-trig")
    if not base or not ceil:
        return ""

    courses = [c for c in ["bob", "wf", "jrb", "ddd", "bitfs", "rr"] if c in base["workloads"] and c in ceil["workloads"]]
    if not courses:
        return ""

    max_ms = max(
        max(base["workloads"][c]["metrics"].get("est_console_ms", base["workloads"][c]["metrics"]["frame_ms"]) for c in courses),
        40.0,
    ) * 1.08

    w, row_h, top, left, right = 920, 46, 48, 210, 150
    plot_w = w - left - right
    h = top + len(courses) * row_h + 36

    def x_of(ms):
        return left + (ms / max_ms) * plot_w

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Super Mario 64 per-course console frame time: 1996 IDO baseline vs Kaze Reference Ceiling">',
        '<g font-family="IBM Plex Mono, monospace" font-size="12" fill="currentColor">',
        f'<text x="{left}" y="20" font-weight="600">Console frame time per course (ms, lower is faster) &mdash; 1996 IDO -O0 vs Kaze Reference Ceiling</text>',
    ]

    # Grid ticks + 33.3 ms (30 FPS) line
    for tick in [0, 20, 33.33, 50, 75, 100]:
        if tick > max_ms:
            continue
        xt = x_of(tick)
        is_30 = abs(tick - 33.33) < 0.1
        dash = ' stroke-dasharray="4,3"' if is_30 else ' opacity="0.18"'
        color = "#d4a017" if is_30 else "currentColor"
        lbl = "33.3ms (30 FPS)" if is_30 else f"{int(tick)}ms"
        parts.append(f'<line x1="{xt:.1f}" y1="{top - 10}" x2="{xt:.1f}" y2="{h - 24}" stroke="{color}" stroke-width="1"{dash}/>')
        parts.append(f'<text x="{xt:.1f}" y="{h - 8}" text-anchor="middle" font-size="11" opacity="0.75">{lbl}</text>')

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
        parts.append(f'<text x="{left - 12}" y="{y + 30}" text-anchor="end" font-size="10.5" opacity="0.65">RDP {c_rdp:.1f}ms</text>')

        bw = (b_ms / max_ms) * plot_w
        cw = (c_ms / max_ms) * plot_w
        parts.append(f'<rect x="{left}" y="{y + 3}" width="{bw:.1f}" height="12" rx="2" fill="currentColor" opacity="0.28"/>')
        parts.append(f'<rect x="{left}" y="{y + 18}" width="{cw:.1f}" height="13" rx="2" fill="#1f7a3a"/>')
        parts.append(f'<text x="{left + bw + 7:.1f}" y="{y + 13}" font-size="11" opacity="0.75">{b_ms:.1f}ms ({b_fps:.1f} fps)</text>')
        parts.append(f'<text x="{left + cw + 7:.1f}" y="{y + 29}" font-size="11.5" font-weight="600">{c_ms:.1f}ms ({c_fps:.1f} fps, {sp:.2f}&times;)</text>')

    parts.append("</g></svg>")
    return "\n".join(parts)


def trajectory_svg(sm64_rows, agent_runs):
    """Render either 24h agent scaling trajectories or the SM64 Kaze optimization rung curve."""
    by_slug = {slug: (title, s) for slug, title, _p, s in sm64_rows if s["status"] == "valid"}
    rungs = [
        ("r0-unchanged", "1996 IDO -O0"),
        ("r2-kaze-mtx", "IDO + Kaze Mtx"),
        ("r4-kaze-rdp-opa", "IDO + RA_ZB_OPA"),
        ("r1-gcc-o2", "GCC -O2"),
        ("r7-kaze-icache-trig", "R7: I$ + 1-ULP Trig"),
        ("r8-kaze-collision-objects", "R8: 3-Line Surf + Sub"),
        ("r9-kaze-ceiling", "R9: Kaze Ceiling"),
    ]
    pts = []
    for slug, label in rungs:
        if slug in by_slug:
            s = by_slug[slug][1]
            sp = primary_profile(s).get("speedup", 1.0)
            fps = mean_fps(s) or 0.0
            pts.append((slug, label, float(sp), float(fps)))

    traj_runs = [r for r in agent_runs if r.get("trajectory") and r["trajectory"].get("points")]
    w, h, left, right, top, bot = 920, 270, 68, 36, 38, 54
    pw, ph = w - left - right, h - top - bot

    if traj_runs:
        max_y = max(
            [1.30]
            + [p[2] for p in pts]
            + [float(pt.get("best_speedup", 1.0)) for r in traj_runs for pt in r["trajectory"]["points"]]
        ) * 1.04
        min_y = 0.98

        def xy(hr, sp):
            x = left + (min(max(hr, 0.0), 24.0) / 24.0) * pw
            y = top + (1.0 - (sp - min_y) / (max_y - min_y)) * ph
            return x, y

        parts = [f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="24-hour optimization scaling curve">',
                 '<g font-family="IBM Plex Mono, monospace" font-size="11.5" fill="currentColor">',
                 f'<text x="{left}" y="20" font-weight="600">24-hour autonomous scaling curve &mdash; best valid console speedup vs wall-clock hours</text>']
        for hr in [0, 4, 8, 12, 16, 20, 24]:
            x, _ = xy(hr, 1.0)
            parts.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{h - bot}" stroke="currentColor" opacity="0.15"/>')
            parts.append(f'<text x="{x:.1f}" y="{h - bot + 18}" text-anchor="middle" opacity="0.75">{hr}h</text>')
        for ref_slug, ref_lbl, col in [("r1-gcc-o2", "GCC -O2", "#d4a017"), ("r9-kaze-ceiling", "Kaze Ceiling", "#1f7a3a")]:
            if ref_slug in by_slug:
                rsp = primary_profile(by_slug[ref_slug][1]).get("speedup", 1.0)
                _, ry = xy(0, rsp)
                parts.append(f'<line x1="{left}" y1="{ry:.1f}" x2="{w - right}" y2="{ry:.1f}" stroke="{col}" stroke-dasharray="5,4" stroke-width="1.5"/>')
                parts.append(f'<text x="{w - right - 4}" y="{ry - 5:.1f}" text-anchor="end" fill="{col}">{ref_lbl} ({rsp:.2f}&times;)</text>')
        palette = ["#1f5fbf", "#c95b1f", "#8e44ad", "#16a085"]
        for i, r in enumerate(traj_runs):
            col = palette[i % len(palette)]
            coords = [xy(pt["elapsed_s"] / 3600.0, max(float(pt.get("best_speedup", 1.0)), 1.0)) for pt in r["trajectory"]["points"]]
            poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
            parts.append(f'<polyline fill="none" stroke="{col}" stroke-width="2.5" points="{poly}"/>')
            lx, ly = coords[-1]
            parts.append(f'<circle cx="{lx:.1f}" cy="{ly:.1f}" r="4" fill="{col}"/>')
            parts.append(f'<text x="{lx - 8:.1f}" y="{ly - 8:.1f}" text-anchor="end" fill="{col}" font-weight="600">{esc(r["model"])}</text>')
        parts.append("</g></svg>")
        return "\n".join(parts)

    if len(pts) < 2:
        return ""

    min_y = 0.98
    max_y = max(p[2] for p in pts) + 0.05

    def xy_idx(i, sp):
        x = left + (i / (len(pts) - 1)) * pw
        y = top + (1.0 - (sp - min_y) / (max_y - min_y)) * ph
        return x, y

    parts = [
        f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="Super Mario 64 hardware optimization ladder">',
        '<g font-family="IBM Plex Mono, monospace" font-size="11.5" fill="currentColor">',
        f'<text x="{left}" y="20" font-weight="600">Super Mario 64 hardware optimization ladder &mdash; console speedup across 12 courses</text>',
    ]
    n_ticks = 5
    for t in range(n_ticks + 1):
        val = 1.0 + t * round((max_y - 1.0) / n_ticks, 2)
        if val > max_y:
            continue
        _, y = xy_idx(0, val)
        parts.append(f'<line x1="{left}" y1="{y:.1f}" x2="{w - right}" y2="{y:.1f}" stroke="currentColor" opacity="0.16"/>')
        parts.append(f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" opacity="0.75">{val:.2f}&times;</text>')

    coords = [xy_idx(i, p[2]) for i, p in enumerate(pts)]
    poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in coords)
    parts.append(f'<polyline fill="none" stroke="#1f5fbf" stroke-width="2.5" points="{poly}"/>')

    for i, (slug, label, sp, fps) in enumerate(pts):
        x, y = coords[i]
        is_ceil = slug == "r9-kaze-ceiling"
        is_o2 = slug == "r1-gcc-o2"
        col = "#1f7a3a" if is_ceil else ("#d4a017" if is_o2 else "#1f5fbf")
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{5 if is_ceil else 4}" fill="{col}"/>')
        dy = -10 if i % 2 == 0 or is_ceil else 16
        anchor = "start" if i == 0 else ("end" if i == len(pts) - 1 else "middle")
        parts.append(f'<text x="{x:.1f}" y="{y + dy:.1f}" text-anchor="{anchor}" font-weight="{"600" if is_ceil else "400"}">{sp:.2f}&times; ({fps:.1f} fps)</text>')
        parts.append(f'<text x="{x:.1f}" y="{h - bot + 20 + (14 if i % 2 == 1 else 0)}" text-anchor="{anchor}" font-size="10.5" opacity="0.8">{esc(label)}</text>')

    parts.append("</g></svg>")
    return "\n".join(parts)


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
            f'<div class="cap"><span class="small">{caption}</span></div>'
            f'</div>'
        )
    return '<div class="frame-grid">' + "".join(cards) + "</div>"


def build_index(out, rows, sm64_rows, agent_runs, post_items, exported_frames):
    post_links = "".join(
        f'<li><a href="{BASE}/blog/{slug}/">{esc(m["title"])}</a> <span class=date>{m["date"]}</span><br>'
        f'<span class="small muted">{esc(m["summary"])}</span></li>' for slug, m, _ in post_items)

    sm64_by_slug = {slug: s for slug, *_r, s in sm64_rows if s["status"] == "valid"}
    ceil_kpi = ""
    if "r9-kaze-ceiling" in sm64_by_slug and "r0-unchanged" in sm64_by_slug:
        r0 = sm64_by_slug["r0-unchanged"]
        r1 = sm64_by_slug.get("r1-gcc-o2", r0)
        r9 = sm64_by_slug["r9-kaze-ceiling"]
        r0_fps = mean_fps(r0) or 0.0
        r9_fps = mean_fps(r9) or 0.0
        r9_sp = primary_profile(r9).get("speedup", 1.0)
        r1_sp = primary_profile(r1).get("speedup", 1.0)
        ceil_kpi = f"""
<div class="kpis">
  <div class="kpi"><div class="val">12 courses</div><div class="lbl">6 public + 6 private held-out SM64 routes</div></div>
  <div class="kpi"><div class="val">{r0_fps:.1f} &rarr; {r9_fps:.1f} FPS</div><div class="lbl">1996 IDO -O0 vs Kaze Reference Ceiling</div></div>
  <div class="kpi"><div class="val">{r1_sp:.2f}&times;</div><div class="lbl">GCC -O2 compiler-only speedup</div></div>
  <div class="kpi"><div class="val accent">{r9_sp:.2f}&times;</div><div class="lbl">Kaze Reference Ceiling (<a href="{BASE}/leaderboard/">Leaderboard</a>)</div></div>
</div>
"""

    sm64_sec = ""
    if sm64_rows:
        chart = sm64_bottleneck_svg(sm64_rows)
        chart_html = f'<div class="chart-box">{chart}</div>' if chart else ""
        sm64_sec = f"""
<h2>Super Mario 64 calibration &amp; Kaze Reference Ceiling</h2>
<p>Calibrated on the US decompilation across <b>12 courses</b> (6 public: Bob-omb Battlefield, Whomp's Fortress,
Jolly Roger Bay, Dire Dire Docks Area 2 / Bowser's Sub, Bowser in the Fire Sea, and Rainbow Ride; plus 6 held-out
courses and alternate trajectories), from the untouched 1996 IDO <code>-O0</code> ROM up to a 3-rung
<a href="{BASE}/blog/kaze-ceiling-on-super-mario-64/">Kaze Emanuar hardware ceiling</a>:</p>
{chart_html}
{cal_table(sm64_rows, compact=True, anchor_prefix="sm64-")}
<h3>Super Mario 64 baseline (1996 IDO <code>-O0</code>)</h3>
{baseline_table(sm64_rows)}
"""

    gallery = pips_gallery_html(exported_frames, rows)
    body = f"""
<div class="hero"><div>
<h1>Make a Nintendo 64 game cheaper to run. Don't change it.</h1>
<p class="lede">Mario Eval is a 24-hour reinforcement-learning-with-verifiable-rewards environment modelled on
<a href="https://gbaeval.com/">GBA Eval</a>. An agent gets the C decompilation of <b>Super Mario 64</b> (or the
open-source <b>Pip's Garden</b> game), pinned N64 compilers, an instrumented cycle/cache/RDP-accurate <code>ares</code>
emulator and a profiler, and must speed up real 4 MB console execution while keeping gameplay, picture, and 40 dB audio
faithful.</p>
</div>{PIP_SVG}</div>

<div class="status"><b>v2.0 Ready:</b> 12-course <b>Super Mario 64</b> suite + 8-route <b>Pip's Garden</b> suite,
headline <b>console</b> frame-time profile (<code>max(CPU, RSP, RDP)</code>), Player Equivalence + Hyrum's Law gates,
24-hour trajectory telemetry, and verified <b>Kaze Emanuar Reference Ceiling</b> rungs.</div>

{ceil_kpi}

<h2>How a submission is graded</h2>
<div class="diagram">{PIPELINE_SVG}</div>

<div class="cards">
<div class="card primary"><h3>console <span>headline</span></h3><p>Per-frame <code>max(CPU_ms, RSP_ms, RDP_ms)</code> within 4 MB RDRAM &mdash; true N64 frame rate.</p></div>
<div class="card"><h3>speed <span>diagnostic</span></h3><p>93.75 MHz VR4300 CPU time per frame (COUNT ticks), including 16 KB I$ / 8 KB D$ stalls.</p></div>
<div class="card"><h3>rdp <span>diagnostic</span></h3><p>62.5 MHz RDP combiner, Z/blend RMW, TMEM upload &amp; pipe-sync cycles.</p></div>
<div class="card"><h3>rsp <span>diagnostic</span></h3><p>62.5 MHz RSP Fast3D + ABI1 audio microcode busy cycles per frame.</p></div>
<div class="card"><h3>traffic <span>diagnostic</span></h3><p>RDRAM bytes moved per frame across CPU caches, SP, DP, PI &amp; SI DMA.</p></div>
<div class="card"><h3>memory <span>diagnostic</span></h3><p>Distinct 16-byte RDRAM lines touched after boot (hard 4,194,304 B ceiling).</p></div>
</div>

{sm64_sec}

<h2>Pip's Garden calibration (zero-ROM open-source game)</h2>
<p>Pip's Garden ships complete in-repo (<code>workload/</code>) so anyone can run the full 24-hour harness without an
external ROM:</p>
{gallery}
{cal_table(rows, compact=True)}

<h3>Pip's Garden baseline</h3>
{baseline_table(rows)}

<h2>Writing</h2>
<ul class="post-list">{post_links}</ul>
"""
    write(out, "index.html", page("Mario Eval: super-optimize an N64 game on real hardware", body))


def build_leaderboard(out, rows, sm64_rows, agent_runs):
    sm64_valid = [(slug, title, purpose, s) for slug, title, purpose, s in sm64_rows if s["status"] == "valid"]
    by_slug = {slug: (title, purpose, s) for slug, title, purpose, s in sm64_valid}

    ref_order = [
        ("r9-kaze-ceiling", "Kaze Reference Ceiling (R9)", "ceiling",
         "Expert N64 engineering ceiling (I-cache + 1-ULP trig + 3-line Surface + Sub cache + lazy Mtx + RA_ZB_OPA + coin batch + -304 KB)"),
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

    for slug, label, kind, note in ref_order:
        if slug not in by_slug:
            continue
        s = by_slug[slug][2]
        p = primary_profile(s)
        sp = float(p.get("speedup", 1.0))
        rew = float(p.get("reward", 0.0))
        vs_o2 = p.get("vs_o2_speedup")
        fps = mean_fps(s) or 0.0
        traf = s["profiles"].get("traffic", {}).get("speedup", 1.0)
        wls = list(s["workloads"].values())
        foot = sum(x["metrics"]["footprint_bytes"] for x in wls) / len(wls)
        ram_saved_kb = ((base_foot - foot) / 1024.0) if base_foot else 0.0
        entries.append({
            "name": label,
            "href": f"{BASE}/calibration/#sm64-{slug}",
            "kind": kind,
            "note": note,
            "reward": rew,
            "speedup": sp,
            "vs_o2": vs_o2,
            "fps": fps,
            "traffic_x": traf,
            "ram_saved_kb": ram_saved_kb,
            "valid": s["status"] == "valid" and p.get("valid", True),
        })

    for ar in agent_runs:
        s = ar["summary"]
        p = primary_profile(s)
        valid = s["status"] == "valid" and p.get("valid", True)
        sp = float(p.get("speedup", 0.0)) if valid else 0.0
        rew = float(p.get("reward", -1.0))
        fps = (mean_fps(s) or 0.0) if valid else 0.0
        traf = s["profiles"].get("traffic", {}).get("speedup", 0.0) if valid else 0.0
        wls = list(s.get("workloads", {}).values())
        foot = (sum(x["metrics"]["footprint_bytes"] for x in wls) / len(wls)) if wls else (base_foot or 0.0)
        ram_saved_kb = ((base_foot - foot) / 1024.0) if (base_foot and valid) else 0.0
        entries.append({
            "name": f"{ar['title']} ({ar['hours']}h)",
            "href": "",
            "kind": "agent",
            "note": ar["notes"],
            "reward": rew,
            "speedup": sp,
            "vs_o2": p.get("vs_o2_speedup"),
            "fps": fps,
            "traffic_x": traf,
            "ram_saved_kb": ram_saved_kb,
            "valid": valid,
        })

    entries.sort(key=lambda e: (1 if e["valid"] else 0, e["speedup"]), reverse=True)
    max_sp = max([e["speedup"] for e in entries if e["valid"]] + [1.25])

    rows_html = [
        '<div class="table-wrap"><table>',
        '<tr><th>entry</th><th>type</th><th class="bar-cell">console speedup</th>'
        '<th class="num">console</th><th class="num">vs -O2</th><th class="num">mean FPS</th>'
        '<th class="num">bus&times;</th><th class="num">RAM &Delta;</th></tr>',
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
    rows_html.append("</table></div>")

    t_svg = trajectory_svg(sm64_rows, agent_runs)
    b_svg = sm64_bottleneck_svg(sm64_rows)
    t_box = f'<div class="chart-box">{t_svg}</div>' if t_svg else ""
    b_box = f'<div class="chart-box">{b_svg}</div>' if b_svg else ""

    body = f"""
<div class="prose">
<h1>Leaderboard &amp; Reference Ceiling</h1>
<p>Every submission is graded on <b>12 Super Mario 64 courses</b> (6 public + 6 private held-out, 240 frames each) on
an instrumented <code>ares</code> N64 console model (93.75 MHz VR4300 + 16 KB I$ / 8 KB D$, 62.5 MHz RSP &amp; RDP,
4 MB RDRAM). To calibrate how much headroom exists above a naive <code>-O2</code> recompile, we engineered a 3-rung
<a href="{BASE}/blog/kaze-ceiling-on-super-mario-64/">Kaze Emanuar Reference Ceiling</a> under the exact same gates and
toolchain given to 24-hour agents.</p>
</div>

{"".join(rows_html)}

{t_box}
{b_box}

<div class="prose">
<h2>Run a 24-hour agent evaluation</h2>
<p>Agent runs record every inner-loop <code>mev profile</code> milestone to <code>/task/.mev-history.jsonl</code> and
emit <code>results/&lt;run&gt;/trajectory.json</code> automatically when graded. Copy any finished run directory into
<code>results/agents/&lt;slug&gt;/</code> and rebuild the site to plot its 24-hour scaling curve above.</p>
<pre><code># 1. Supply your legally dumped US Super Mario 64 .z64 ROM (never committed or shipped)
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
./scripts/build-images.sh --game sm64
./scripts/precompute.sh --game sm64

# 2. Verify container isolation, build, profiler, and grader end-to-end
./quickstart/smoke-test.sh --game sm64

# 3. Launch a 24h isolated agent run + held-out grading + trajectory extraction
./quickstart/run-agent.sh --game sm64 claude</code></pre>
</div>
"""
    write(out, "leaderboard/index.html",
          page("Leaderboard & Kaze Ceiling | Mario Eval", body, active="leaderboard/"))


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
            detail.append(f'<div class="table-wrap"><table><tr><th>workload</th>{hdr}</tr>')
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
            detail.append("</table></div><p class='small muted'>Ratios to the baseline (lower is better), plus estimated real-hardware FPS.</p>")
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
            '<h2>Super Mario 64 (US, 12 courses)</h2>'
            + cal_table(sm64_rows, anchor_prefix="sm64-")
            + render_sections(sm64_rows, "sm64/calibration", anchor_prefix="sm64-")
            + "<hr>"
        )
    body = f"""<div class="prose"><h1>Calibration</h1>
<p>Each patch is applied to a clean copy of the baseline source and graded across public + private held-out routes
(12 courses on Super Mario 64; 8 routes on Pip's Garden, 240 frames each) across all six N64 hardware profiles
(headline <code>console</code> plus diagnostic <code>speed</code>, <code>rdp</code>, <code>rsp</code>,
<code>traffic</code>, and <code>memory</code>).</p></div>
{sm64_part}
<h2>Pip's Garden (8 routes)</h2>
{cal_table(rows)}
{render_sections(rows, "calibration")}"""
    write(out, "calibration/index.html", page("Calibration | Mario Eval", body, active="calibration/"))


def build_blog(out, post_items):
    lis = "".join(
        f'<li><a href="{BASE}/blog/{slug}/">{esc(m["title"])}</a> <span class=date>{m["date"]}</span><br>'
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
    rows = load_cal(CAL, PATCHES)
    sm64_rows = load_cal(SM64_CAL, SM64_PATCHES)
    agent_runs = load_agent_runs()
    post_items = posts()
    build_index(out, rows, sm64_rows, agent_runs, post_items, exported_frames)
    build_leaderboard(out, rows, sm64_rows, agent_runs)
    build_calibration(out, rows, sm64_rows)
    build_blog(out, post_items)
    print(f"wrote {out}: {len(rows)} pips entries, {len(sm64_rows)} sm64 entries, "
          f"{len(agent_runs)} agent runs, {len(exported_frames)} png frames, {len(post_items)} posts")


if __name__ == "__main__":
    main()
