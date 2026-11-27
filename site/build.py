#!/usr/bin/env python3
"""Build the Mario Eval website (served at https://ilya.as/mario-eval/).

    python3 site/build.py <out_dir>

Pages follow Mechanize's gbaeval.com: About (speedup-over-time chart, featured replay), Leaderboard
(ranked cards with per-unit bars), one page per agent run under model/<slug>/, Watch (replay player),
Blog, and Calibration.

Reads the SM64 calibration summaries (results/sm64-calibration/ and results/sm64-trial-calibration/
for references graded on the agents' routes), agent and trial runs (results/agents/<slug>/summary.json
+ trajectory.json + meta.json with title, model, kind, provider, graded, commit, harness, repo_url,
notes), the replay clips in site/assets/clips/ (site/make_clips.py), and the hand-written posts in
site/posts/. Never distributes any Nintendo SM64 code, ROMs, or assets.
"""
import html
from collections import Counter
import json
import math
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
SM64_CAL = ROOT / "results" / "sm64-calibration"
SM64_TRIAL_CAL = ROOT / "results" / "sm64-trial-calibration"
AGENTS_DIR = ROOT / "results" / "agents"
CLIPS_SRC = SITE / "assets" / "clips"
BASE = "/mario-eval"
REPO = "https://github.com/IlyaasK/mario-eval"

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
     "Based on transcripts, on-screen code and public releases: F3DEX2, no LOD + full-detail Mario, cold -Os / hot -O3 I-cache sizing, vertical culling, billboard-once-per-camera, fused 4x3 matrices, sequence_unity audio TU, 1-raycast planar shadows, inline skybox quads, targeted D-cache writebacks, and Rainbow Ride statics baked into the level. Not Kaze's own engine."),
    ("r11-beyond-kaze", "Beyond Kaze: r10-kaze-master plus D-cache layout &amp; conditional-store micro-optimizations",
     "Stacks microarchitectural VR4300 write-back D-cache optimizations directly on top of r10-kaze-master: 16-byte cache-line packing of struct Object members, store-if-changed guards on stationary object transforms/collision fields, and byte-unpacked audio channel flags."),
    ("i0-gcc-fastmath", "GCC <code>-O2 -ffast-math</code>", "Breaks Mario physics/collision trajectories."),
    ("i1-mute-audio", "Disable audio synthesis (<code>sAudioEnabled = FALSE</code>)", "Caught by the 40 dB audio SNR gate."),
    ("i2-low-poly-mario", "Force low-poly Mario at all distances", "Caught by the video gate."),
    ("i3-half-physics-step", "Two quarter-steps instead of four in <code>mario_step.c</code>", "Caught by the Player Equivalence gameplay gate."),
    ("i4-tamper", "Modify <code>src/game/mev.h</code>", "Caught by the harness integrity gate."),
]

EXPERT_REF = "r10-kaze-master"
PROFILES = ["console", "stutter", "speed", "rdp", "rsp", "traffic", "memory"]

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


def esc(s):
    return html.escape(str(s))


NAV = [("", "About"), ("leaderboard/", "Leaderboard"), ("watch/", "Watch"), ("blog/", "Blog")]
AUTHOR = "Ilyaas Kapadia"

# Toggles shared by every page: chart views, interactive chart hover crosshair, leaderboard expansion, tab strips.
SITE_JS = """<script>(function(){
document.querySelectorAll(".chart").forEach(function(c){
  var btns=c.querySelectorAll("[data-view]"),tip=c.querySelector("[data-tip]");
  btns.forEach(function(b){b.addEventListener("click",function(){
    btns.forEach(function(x){x.classList.toggle("on",x===b);});
    c.querySelectorAll("[data-pane]").forEach(function(p){p.hidden=p.getAttribute("data-pane")!==b.getAttribute("data-view");});
    if(tip)tip.textContent="";
  });});
  c.querySelectorAll("svg.speed-chart").forEach(function(svg){
    var xh=svg.querySelector(".xhair"),dot=svg.querySelector(".hdot");
    var pts=svg.querySelectorAll("circle[data-hr]");
    var series=svg.querySelectorAll("[data-series]");
    function hi(slug){
      series.forEach(function(g){g.style.opacity=(!slug||g.getAttribute("data-series")===slug)?"1":"0.22";});
    }
    series.forEach(function(g){
      g.addEventListener("mouseenter",function(){hi(g.getAttribute("data-series"));});
      g.addEventListener("mouseleave",function(){hi(null);});
    });
    svg.addEventListener("mousemove",function(ev){
      if(!pts.length)return;
      var r=svg.getBoundingClientRect(),vb=svg.viewBox.baseVal;
      var mx=(ev.clientX-r.left)/r.width*vb.width;
      var best=null,bd=1e9;
      pts.forEach(function(p){var d=Math.abs(+p.getAttribute("cx")-mx);if(d<bd){bd=d;best=p;}});
      if(best&&bd<45){
        var cx=best.getAttribute("cx"),cy=best.getAttribute("cy");
        if(xh){xh.setAttribute("x1",cx);xh.setAttribute("x2",cx);xh.hidden=false;}
        if(dot){dot.setAttribute("cx",cx);dot.setAttribute("cy",cy);dot.setAttribute("fill",best.getAttribute("fill"));dot.hidden=false;}
        var u=best.getAttribute("data-unit")||"x";
        if(tip)tip.textContent=best.getAttribute("data-name")+" @ "+best.getAttribute("data-hr")+"h: "+best.getAttribute("data-val")+u+" ("+best.getAttribute("data-cp")+")";
      }
    });
    svg.addEventListener("mouseleave",function(){
      if(xh)xh.hidden=true;
      if(dot)dot.hidden=true;
      if(tip)tip.textContent="";
      hi(null);
    });
  });
});
document.querySelectorAll(".lb-exp").forEach(function(b){b.addEventListener("click",function(){
  var d=b.closest(".lb-card").querySelector(".lb-detail");d.hidden=!d.hidden;b.textContent=d.hidden?"Expand":"Collapse";
});});
document.querySelectorAll("[data-tabs]").forEach(function(t){
  var btns=t.querySelectorAll("[data-tab]");
  btns.forEach(function(b){b.addEventListener("click",function(){
    btns.forEach(function(x){x.classList.toggle("on",x===b);});
    document.querySelectorAll("[data-tabpane]").forEach(function(p){p.hidden=p.getAttribute("data-tabpane")!==b.getAttribute("data-tab");});
  });});
});
})();</script>"""


def page(title, body, active="", desc=""):
    links = "".join(
        f'<a href="{BASE}/{href}"{" class=on" if href == active else ""}>{name}</a>' for href, name in NAV)
    links += f'<a class="cta" href="{REPO}" target="_blank" rel="noreferrer noopener">GitHub &rarr;</a>'
    desc = desc or ("AI coding agents get 24 hours to make Super Mario 64 run faster on an original 4 MB "
                    "Nintendo 64 without changing the game.")
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#141318">
<title>{esc(title)}</title>
<meta name="description" content="{esc(desc)}">
<meta property="og:title" content="{esc(title)}"><meta property="og:description" content="{esc(desc)}">
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Press+Start+2P&family=IBM+Plex+Mono:ital,wght@0,400;0,500;0,600;1,400&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{BASE}/style.css">
</head><body>
<header class="site"><div class="bar">
  <div class="brand">
    <a class="logo" href="{BASE}/">Mario Eval</a>
    <span class="sep">&middot;</span><span class="by">BY</span>
    <span class="leds" aria-hidden="true"><i></i><i></i><i></i><i></i></span>
    <a class="org" href="https://ilya.as/">{AUTHOR}</a>
  </div>
  <nav class="site">{links}</nav>
</div></header>
<main>{body}</main>
<footer class="site">
  <div><span>Mario Eval &mdash; by {AUTHOR}</span><span class="sep">&middot;</span>
  <a href="{BASE}/calibration/">Calibration</a><a href="{REPO}">Repo</a><a href="{BASE}/#acknowledgements">Acknowledgements</a></div>
  <p>Not affiliated with or endorsed by Nintendo. No Nintendo code or assets are distributed; running Super Mario 64 requires your own legally obtained ROM.</p>
</footer>
{SITE_JS}
</body></html>
"""


def write(out, rel, text):
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


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
            "meta": meta,
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
    return f'<td class="num {cls}"{tip}>{r if abs(r) >= 0.0005 else 0.0:+.3f}</td>'


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
            row_cls.append("expert-row")
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


def trajectory_svg(sm64_rows, chart_id="ladder"):
    """Console speedup of each reference rung on the 6 public courses."""
    w, h, left, right, top, bot = 920, 285, 68, 44, 38, 52
    pw, ph = w - left - right, h - top - bot
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
            n_rt = len(ar["summary"].get("workloads", {}))
            b_lbl = f"live ({n_rt}-route valid)" if ar.get("kind") == "live" else (
                f"trial ({n_rt}-route valid)" if ar.get("kind") == "trial" else "agent")
            candidates.append((ar["model"], b_lbl, "trial-card", ar["summary"]))

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


AGENT_KINDS = ("agent", "trial", "live")
REF_SPECS = [
    (EXPERT_REF, "Kaze master reference", "Kaze master", "human",
     "Kaze Emanuar's and ultrasm64's published Super Mario 64 optimizations, reconstructed on the vanilla decompilation."),
    ("r1-gcc-o2", "GCC -O2 (compiler only)", "GCC -O2", "compiler",
     "The unmodified game rebuilt with GCC -O2 -fno-fast-math instead of 1996 IDO; no code changes."),
]
KIND_TAG = {
    "agent": ("agent", "valid"), "trial": ("trial run", "trial"), "live": ("live · in progress", "trial"),
    "human": ("human ref", "valid"), "compiler": ("compiler", "ref"), "baseline": ("baseline", "ref"),
}
REF_COLORS = {"human": "#2ed573", "compiler": "#ffb000", "baseline": "#8a849f"}
AGENT_COLORS = ["#7b68ee", "#38bdf8", "#ff5a63", "#e85d04", "#d946ef", "#facc15", "#14b8a6", "#a3e635"]
# Per-unit speedups shown as bars: the console bottleneck and the four units it is the max of.
BAR_UNITS = [("est_console_ms", "Console"), ("cpu_effective_cycles", "CPU"), ("rsp_busy", "RSP"),
             ("rdp_busy", "RDP"), ("rdram_bytes", "RDRAM bus")]
BAR_UNIT_PROFILES = {
    "est_console_ms": "console",
    "cpu_effective_cycles": "speed",
    "rsp_busy": "rsp",
    "rdp_busy": "rdp",
    "rdram_bytes": "traffic",
}


def geomean(xs):
    return math.exp(sum(math.log(x) for x in xs) / len(xs))


def score_color(sp):
    """gbaeval-style red-to-green ramp over console speedup."""
    for floor, col in ((1.6, "#36c23a"), (1.3, "#a6c13a"), (1.1, "#d6a22c"), (1.0, "#dd6b2c")):
        if sp >= floor - 1e-9:
            return col
    return "#d64545"


def unit_speedups(s):
    wls = list(s.get("workloads", {}).values())
    profs = s.get("profiles", {})
    out = {}
    for key, _ in BAR_UNITS:
        prof = profs.get(BAR_UNIT_PROFILES.get(key, ""))
        if prof and prof.get("speedup") is not None:
            out[key] = float(prof["speedup"])
            continue
        ratios = [w["ratios"][key] for w in wls if w.get("ratios", {}).get(key)]
        if ratios:
            out[key] = 1.0 / geomean(ratios)
    return out


def baseline_fps(s):
    """Mean uncapped FPS of the 1996 build over the routes in s (from each route's ratio)."""
    vals = [1000.0 * w["ratios"]["est_console_ms"] / w["metrics"]["est_console_ms"]
            for w in s.get("workloads", {}).values()]
    return sum(vals) / len(vals) if vals else None


def route_label(wid):
    if wid in SM64_COURSE_NAMES:
        return SM64_COURSE_NAMES[wid]
    code = wid.removeprefix("heldout-")
    if code.startswith("mash-"):
        return f"private &middot; button mash, {esc(code[5:].upper())}"
    return f"private &middot; {esc(code.upper())}"


def dense_step_points(traj, cps):
    """Build a continuous gbaeval-style step series anchored at (0h, 1.0x) and calibrated
    within each verified 26-route host checkpoint interval using verified container mev_checks.
    Never extrapolates unverified public drift above the latest valid host checkpoint."""
    valid_cps = sorted(
        [(float(c["elapsed_hours"]), float(c["speedups"]["console"]), c.get("name", "checkpoint"), c)
         for c in cps if c.get("status") == "valid" and (c.get("speedups") or {}).get("console")],
        key=lambda x: x[0],
    )
    if not valid_cps:
        return []

    raw_checks = [
        c for c in (traj.get("mev_checks") or [])
        if c.get("status") == "valid" and c.get("profile_valid")
        and float((c.get("speedups") or {}).get("console") or 0.0) > 1.0005
    ]
    full_checks = [c for c in raw_checks if not c.get("fast")]

    out = []
    prev_h = 0.0
    best_so_far = 1.0
    for h_cp, sp_cp, name_cp, cp_obj in valid_cps:
        iv_checks = [c for c in full_checks if prev_h < float(c.get("elapsed_hours", 0.0)) < h_cp - 0.02]
        if not iv_checks:
            iv_checks = [c for c in raw_checks if prev_h < float(c.get("elapsed_hours", 0.0)) < h_cp - 0.02]
        iv_checks.sort(key=lambda c: float(c.get("elapsed_hours", 0.0)))

        if iv_checks and sp_cp > best_so_far + 1e-6:
            host_pub = float(
                ((((cp_obj.get("capability_ruler") or {}).get("splits") or {}).get("public") or {}).get("raw_console_speedup")
                 or sp_cp)
            )
            max_pub = max([host_pub] + [float(c["speedups"]["console"]) for c in iv_checks])
            denom = max(max_pub - 1.0, 1e-6)
            for c in iv_checks:
                hr = float(c["elapsed_hours"])
                p_sp = float(c["speedups"]["console"])
                est = 1.0 + (p_sp - 1.0) * ((sp_cp - 1.0) / denom)
                est = min(sp_cp, max(best_so_far, est))
                if est > best_so_far + 0.0025:
                    best_so_far = est
                    gh = (c.get("git_head") or "")[:7]
                    lbl = f"commit {gh}" if gh else "verified check"
                    out.append((hr, round(est, 6), lbl, False))

        best_so_far = max(best_so_far, sp_cp)
        out.append((h_cp, sp_cp, name_cp, True))
        prev_h = h_cp
    return out


def build_board(trial_rows, agent_runs):
    """Every agent run and reference rung graded on the agents' replay set, best first."""
    cohorts = Counter(r["summary"]["workload_set"] for r in agent_runs if r["summary"].get("workload_set"))
    if not cohorts:
        cohorts = Counter(s["workload_set"] for _slug, _t, _p, s in trial_rows if s.get("status") == "valid" and s.get("workload_set"))
    if not cohorts:
        return None
    cohort = cohorts.most_common(1)[0][0]
    entries = []
    color = iter(AGENT_COLORS * 4)
    for r in agent_runs:
        s = r["summary"]
        if s.get("workload_set") != cohort:
            continue
        p = primary_profile(s)
        valid = s["status"] == "valid" and p.get("valid", False)
        traj = r["trajectory"] or {}
        cps = [c for c in traj.get("host_checkpoints", []) if c.get("workload_set") in (cohort, None)]
        points = dense_step_points(traj, cps)
        sp_val = float(p["speedup"]) if valid else 0.0
        cs_val = float(p.get("cost_saved", 1.0 - 1.0 / sp_val)) if (valid and sp_val > 0) else 0.0
        entries.append({
            "slug": r["slug"], "name": r["model"].removesuffix(" (trial)"),
            "short": r["model"].removesuffix(" (trial)"), "kind": r.get("kind", "agent"),
            "org": r["meta"].get("provider", ""), "date": r["meta"].get("graded", ""),
            "commit": r["meta"].get("commit", ""), "harness": r["meta"].get("harness", ""),
            "repo_url": r["repo_url"], "note": r["notes"], "href": f"{BASE}/model/{r['slug']}/",
            "valid": valid, "speedup": sp_val, "cost_saved": cs_val,
            "vs_o2": p.get("vs_o2_speedup") if valid else None, "fps": mean_fps(s) if valid else None,
            "units": unit_speedups(s) if valid else {}, "summary": s, "points": points, "checkpoints": cps,
            "analytics": traj.get("run_analytics") or {},
            "end_h": max([c["elapsed_hours"] for c in cps] + [0.0]), "color": next(color),
        })
    by_slug = {slug: s for slug, _t, _p, s in trial_rows if s.get("workload_set") == cohort}
    gcc = None
    kaze_saved = None
    for slug, name, short, kind, note in REF_SPECS:
        s = by_slug.get(slug)
        if not s or s["status"] != "valid":
            continue
        p = primary_profile(s)
        sp_val = float(p["speedup"])
        cs_val = float(p.get("cost_saved", 1.0 - 1.0 / sp_val))
        entries.append({
            "slug": slug, "name": name, "short": short, "kind": kind, "org": "", "date": "reference",
            "note": note, "href": f"{BASE}/blog/kaze-master-reference/" if kind == "human" else f"{BASE}/calibration/#sm64-{slug}",
            "valid": True, "speedup": sp_val, "cost_saved": cs_val, "vs_o2": p.get("vs_o2_speedup"),
            "fps": mean_fps(s), "units": unit_speedups(s), "summary": s, "points": [], "analytics": {},
        })
        if kind == "compiler":
            gcc = sp_val
        elif kind == "human":
            kaze_saved = cs_val
    sample = entries[0]["summary"]
    entries.append({
        "slug": "r0-unchanged", "name": "1996 retail build (IDO)", "short": "1996 build", "kind": "baseline",
        "org": "", "date": "reference", "note": "The unmodified decompilation, which matches the retail US cartridge.",
        "href": f"{BASE}/calibration/#sm64-r0-unchanged", "valid": True, "speedup": 1.0, "cost_saved": 0.0,
        "vs_o2": (1.0 / gcc) if gcc else None, "fps": baseline_fps(sample),
        "units": {key: 1.0 for key, _ in BAR_UNITS}, "summary": None, "points": [], "analytics": {},
    })
    entries.sort(key=lambda e: (e["valid"], e["speedup"]), reverse=True)
    wids = list(sample.get("workloads", {}))
    public = [w for w in wids if w in SM64_COURSES]
    return {"cohort": cohort, "entries": entries, "gcc": gcc, "kaze_saved": kaze_saved,
            "routes": len(wids), "public": len(public), "private": len(wids) - len(public)}


def speedup_svg(agents, refs, div):
    """Best valid console speedup over wall-clock hours, divided by `div`, with reference lines."""
    W, H, L, R, T, B = 760, 340, 50, 176, 14, 46
    pw, ph = W - L - R, H - T - B
    vals = [1.0 / div] + [e["speedup"] / div for e in refs] + [pt[1] / div for e in agents for pt in e["points"]]
    lo, hi = min(vals), max(vals)
    step = 0.1 if hi - lo <= 0.6 else (0.2 if hi - lo <= 1.4 else 0.5)
    lo = math.floor(round(lo / step, 6)) * step
    hi = math.ceil(round((hi + 0.03) / step, 6)) * step

    def x(hr):
        return L + min(max(hr, 0.0), 24.0) / 24.0 * pw

    def y(v):
        return T + (1.0 - (v - lo) / (hi - lo)) * ph

    out = [f'<svg viewBox="0 0 {W} {H}" class="speed-chart" role="img" aria-label="Console speedup over wall-clock hours">']
    t = lo
    while t <= hi + 1e-9:
        out.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="ax" x="{L - 8}" y="{y(t) + 3:.1f}" text-anchor="end">{t:.1f}&times;</text>')
        t += step
    for hr in (0, 6, 12, 18, 24):
        out.append(f'<text class="ax" x="{x(hr):.1f}" y="{T + ph + 18}" text-anchor="middle">{"0M" if hr == 0 else f"{hr}H"}</text>')
    out.append(f'<text class="ax" x="{L + pw / 2:.1f}" y="{H - 6}" text-anchor="middle">WALL-CLOCK</text>')
    labels = []
    for e in refs:
        v, col = e["speedup"] / div, REF_COLORS[e["kind"]]
        out.append(f'<g class="series" data-series="{esc(e["slug"])}">'
                   f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{col}" stroke-width="1.4" '
                   f'stroke-dasharray="5 4" opacity=".8"><title>{esc(e["name"])}: {v:.3f}&times;</title></line></g>')
        labels.append((y(v), col, f'{e["short"]} {v:.2f}×', e["slug"]))
    base_v = 1.0 / div
    for e in agents:
        col, samples = e["color"], sorted(e["points"], key=lambda pt: pt[0])
        best, steps = base_v, []
        for pt in samples:
            hr, sp = pt[0], pt[1]
            best = max(best, sp / div)
            steps.append((hr, best))
        out.append(f'<g class="series" data-series="{esc(e["slug"])}">')
        d = f"M{x(0.0):.1f},{y(base_v):.1f}" + "".join(f" H{x(hr):.1f} V{y(v):.1f}" for hr, v in steps)
        d += f" H{x(max(e['end_h'], steps[-1][0])):.1f}"
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="miter"/>')
        for pt in samples:
            hr, sp, name = pt[0], pt[1], pt[2]
            is_cp = pt[3] if len(pt) > 3 else True
            rad = "3.7" if is_cp else "2.2"
            sw = "1.5" if is_cp else "1.0"
            out.append(f'<circle cx="{x(hr):.1f}" cy="{y(sp / div):.1f}" r="{rad}" fill="{col}" stroke="#0a0a0d" stroke-width="{sw}" '
                       f'data-hr="{hr:.2f}" data-val="{sp / div:.3f}" data-name="{esc(e["short"])}" data-cp="{esc(name)}">'
                       f'<title>{esc(e["name"])} at {hr:.2f}h: {sp / div:.3f}&times; ({esc(name)})</title></circle>')
        out.append("</g>")
        labels.append((y(steps[-1][1]), col, f'{e["short"]} {steps[-1][1]:.2f}×', e["slug"]))
    labels.sort()
    last = -1e9
    for ly, col, txt, slug in labels:
        ly = max(ly, last + 14)
        last = ly
        out.append(f'<g class="series" data-series="{esc(slug)}">'
                   f'<rect x="{L + pw + 8}" y="{ly - 6:.1f}" width="3" height="11" fill="{col}"/>'
                   f'<text class="lbl" x="{L + pw + 16}" y="{ly + 3.5:.1f}">{esc(txt)}</text></g>')
    out.append(f'<line class="xhair" x1="{L}" x2="{L}" y1="{T}" y2="{T + ph}" hidden/>')
    out.append(f'<circle class="hdot" cx="{L}" cy="{T}" r="5.5" fill="#fff" stroke="#fff" stroke-width="2" hidden style="pointer-events:none"/>')
    out.append("</svg>")
    return "".join(out)


def chart_html(views, title=""):
    """A chart panel with gbaeval-style text toggles between `views` = [(key, label, svg)]."""
    btns = "".join(f'<button type="button" data-view="{k}"{" class=on" if i == 0 else ""}>{lbl}</button>'
                   for i, (k, lbl, _svg) in enumerate(views)) if len(views) > 1 else ""
    panes = "".join(f'<div data-pane="{k}"{"" if i == 0 else " hidden"}>{svg}</div>' for i, (k, _l, svg) in enumerate(views))
    head = f'<div class="chart-head"><span class="chart-title">{title}</span><span class="chart-tip" data-tip></span><div class="toggle">{btns}</div></div>'
    return f'<div class="chart">{head}{panes}</div>'


def cost_saved_svg(agents, refs):
    """Bounded cycle-cost reduction 1 - T_cand / T_1996 in [0%, 100%) over wall-clock hours."""
    W, H, L, R, T, B = 760, 340, 50, 176, 14, 46
    pw, ph = W - L - R, H - T - B
    lo, hi, step = 0.0, 50.0, 10.0
    max_v = max([0.0] + [100.0 * e.get("cost_saved", 0.0) for e in refs]
                + [100.0 * (1.0 - 1.0 / pt[1]) for e in agents for pt in e["points"] if pt[1] > 0])
    if max_v > 47.0:
        hi = min(100.0, math.ceil((max_v + 5.0) / 10.0) * 10.0)

    def x(hr):
        return L + min(max(hr, 0.0), 24.0) / 24.0 * pw

    def y(v):
        return T + (1.0 - (v - lo) / (hi - lo)) * ph

    out = [f'<svg viewBox="0 0 {W} {H}" class="speed-chart" role="img" aria-label="Bounded cycle cost saved (%) over wall-clock hours">']
    t = lo
    while t <= hi + 1e-9:
        out.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="ax" x="{L - 8}" y="{y(t) + 3:.1f}" text-anchor="end">{t:.0f}%</text>')
        t += step
    for hr in (0, 6, 12, 18, 24):
        out.append(f'<text class="ax" x="{x(hr):.1f}" y="{T + ph + 18}" text-anchor="middle">{"0M" if hr == 0 else f"{hr}H"}</text>')
    out.append(f'<text class="ax" x="{L + pw / 2:.1f}" y="{H - 6}" text-anchor="middle">WALL-CLOCK (100% = 0 MS PHYSICAL BOUND)</text>')
    labels = []
    for e in refs:
        v = 100.0 * e.get("cost_saved", 1.0 - 1.0 / e["speedup"])
        col = REF_COLORS[e["kind"]]
        out.append(f'<g class="series" data-series="{esc(e["slug"])}">'
                   f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{col}" stroke-width="1.4" '
                   f'stroke-dasharray="5 4" opacity=".8"><title>{esc(e["name"])}: {v:.1f}% frame time saved</title></line></g>')
        labels.append((y(v), col, f'{e["short"]} {v:.1f}%', e["slug"]))
    for e in agents:
        col, samples = e["color"], sorted(e["points"], key=lambda pt: pt[0])
        best, steps = 0.0, []
        for pt in samples:
            hr, sp = pt[0], pt[1]
            sv = 100.0 * (1.0 - 1.0 / sp) if sp > 0 else 0.0
            best = max(best, sv)
            steps.append((hr, best))
        out.append(f'<g class="series" data-series="{esc(e["slug"])}">')
        d = f"M{x(0.0):.1f},{y(0.0):.1f}" + "".join(f" H{x(hr):.1f} V{y(v):.1f}" for hr, v in steps)
        d += f" H{x(max(e['end_h'], steps[-1][0])):.1f}"
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="miter"/>')
        for pt in samples:
            hr, sp, name = pt[0], pt[1], pt[2]
            is_cp = pt[3] if len(pt) > 3 else True
            rad = "3.7" if is_cp else "2.2"
            sw = "1.5" if is_cp else "1.0"
            sv = 100.0 * (1.0 - 1.0 / sp) if sp > 0 else 0.0
            out.append(f'<circle cx="{x(hr):.1f}" cy="{y(sv):.1f}" r="{rad}" fill="{col}" stroke="#0a0a0d" stroke-width="{sw}" '
                       f'data-hr="{hr:.2f}" data-val="{sv:.1f}" data-unit="%" data-name="{esc(e["short"])}" data-cp="{esc(name)}">'
                       f'<title>{esc(e["name"])} at {hr:.2f}h: {sv:.1f}% saved ({esc(name)})</title></circle>')
        out.append("</g>")
        labels.append((y(steps[-1][1]), col, f'{e["short"]} {steps[-1][1]:.1f}%', e["slug"]))
    labels.sort()
    last = -1e9
    for ly, col, txt, slug in labels:
        ly = max(ly, last + 14)
        last = ly
        out.append(f'<g class="series" data-series="{esc(slug)}">'
                   f'<rect x="{L + pw + 8}" y="{ly - 6:.1f}" width="3" height="11" fill="{col}"/>'
                   f'<text class="lbl" x="{L + pw + 16}" y="{ly + 3.5:.1f}">{esc(txt)}</text></g>')
    out.append(f'<line class="xhair" x1="{L}" x2="{L}" y1="{T}" y2="{T + ph}" hidden/>')
    out.append(f'<circle class="hdot" cx="{L}" cy="{T}" r="5.5" fill="#fff" stroke="#fff" stroke-width="2" hidden style="pointer-events:none"/>')
    out.append("</svg>")
    return "".join(out)


def fps_svg(agents, refs, base_fps):
    """Best valid uncapped console FPS over wall-clock hours, starting at 1996 baseline FPS with a 60 Hz console line."""
    W, H, L, R, T, B = 760, 340, 52, 176, 14, 46
    pw, ph = W - L - R, H - T - B
    b_fps = float(base_fps or 34.0)
    vals = [b_fps, 60.0] + [float(e.get("fps") or (b_fps * e["speedup"])) for e in refs] + [
        b_fps * pt[1] for e in agents for pt in e["points"]
    ]
    lo = math.floor(min(vals) / 5.0) * 5.0
    hi = math.ceil((max(vals) + 2.5) / 10.0) * 10.0
    step = 5.0 if hi - lo <= 35.0 else 10.0

    def x(hr):
        return L + min(max(hr, 0.0), 24.0) / 24.0 * pw

    def y(v):
        return T + (1.0 - (v - lo) / max(hi - lo, 1.0)) * ph

    out = [f'<svg viewBox="0 0 {W} {H}" class="speed-chart" role="img" aria-label="Uncapped N64 FPS over wall-clock hours">']
    t = lo
    while t <= hi + 1e-9:
        out.append(f'<line class="grid" x1="{L}" x2="{L + pw}" y1="{y(t):.1f}" y2="{y(t):.1f}"/>'
                   f'<text class="ax" x="{L - 8}" y="{y(t) + 3:.1f}" text-anchor="end">{t:.0f} fps</text>')
        t += step
    # Highlight the N64's 60 Hz full-refresh threshold
    if lo <= 60.0 <= hi:
        out.append(f'<line x1="{L}" x2="{L + pw}" y1="{y(60.0):.1f}" y2="{y(60.0):.1f}" '
                   f'stroke="#38bdf8" stroke-width="1.3" stroke-dasharray="3 3" opacity=".75">'
                   f'<title>60 FPS (N64 60 Hz NTSC refresh rate, 16.67 ms/frame)</title></line>')
    for hr in (0, 6, 12, 18, 24):
        out.append(f'<text class="ax" x="{x(hr):.1f}" y="{T + ph + 18}" text-anchor="middle">{"0M" if hr == 0 else f"{hr}H"}</text>')
    out.append(f'<text class="ax" x="{L + pw / 2:.1f}" y="{H - 6}" text-anchor="middle">WALL-CLOCK (UNCAPPED N64 CONSOLE FPS)</text>')
    labels = []
    if lo <= 60.0 <= hi:
        labels.append((y(60.0), "#38bdf8", "N64 60Hz (60 fps)", "n64-60hz"))
    for e in refs:
        v = float(e.get("fps") or (b_fps * e["speedup"]))
        col = REF_COLORS[e["kind"]]
        out.append(f'<g class="series" data-series="{esc(e["slug"])}">'
                   f'<line x1="{L}" x2="{L + pw}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="{col}" stroke-width="1.4" '
                   f'stroke-dasharray="5 4" opacity=".8"><title>{esc(e["name"])}: {v:.1f} FPS ({e["speedup"]:.2f}&times;)</title></line></g>')
        labels.append((y(v), col, f'{e["short"]} {v:.0f} fps', e["slug"]))
    for e in agents:
        col, samples = e["color"], sorted(e["points"], key=lambda pt: pt[0])
        scale = (float(e["fps"]) / e["speedup"]) if (e.get("fps") and e.get("speedup")) else b_fps
        best, steps = b_fps, []
        for pt in samples:
            hr, sp = pt[0], pt[1]
            fv = scale * sp
            best = max(best, fv)
            steps.append((hr, best))
        out.append(f'<g class="series" data-series="{esc(e["slug"])}">')
        d = f"M{x(0.0):.1f},{y(b_fps):.1f}" + "".join(f" H{x(hr):.1f} V{y(v):.1f}" for hr, v in steps)
        d += f" H{x(max(e['end_h'], steps[-1][0])):.1f}"
        out.append(f'<path d="{d}" fill="none" stroke="{col}" stroke-width="2.4" stroke-linejoin="miter"/>')
        for pt in samples:
            hr, sp, name = pt[0], pt[1], pt[2]
            is_cp = pt[3] if len(pt) > 3 else True
            rad = "3.7" if is_cp else "2.2"
            sw = "1.5" if is_cp else "1.0"
            fv = scale * sp
            out.append(f'<circle cx="{x(hr):.1f}" cy="{y(fv):.1f}" r="{rad}" fill="{col}" stroke="#0a0a0d" stroke-width="{sw}" '
                       f'data-hr="{hr:.2f}" data-val="{fv:.1f}" data-unit=" FPS" data-name="{esc(e["short"])}" data-cp="{esc(name)}">'
                       f'<title>{esc(e["name"])} at {hr:.2f}h: {fv:.1f} FPS ({sp:.2f}&times;, {esc(name)})</title></circle>')
        out.append("</g>")
        labels.append((y(steps[-1][1]), col, f'{e["short"]} {steps[-1][1]:.0f} fps', e["slug"]))
    labels.sort()
    last = -1e9
    for ly, col, txt, slug in labels:
        ly = max(ly, last + 14)
        last = ly
        out.append(f'<g class="series" data-series="{esc(slug)}">'
                   f'<rect x="{L + pw + 8}" y="{ly - 6:.1f}" width="3" height="11" fill="{col}"/>'
                   f'<text class="lbl" x="{L + pw + 16}" y="{ly + 3.5:.1f}">{esc(txt)}</text></g>')
    out.append(f'<line class="xhair" x1="{L}" x2="{L}" y1="{T}" y2="{T + ph}" hidden/>')
    out.append(f'<circle class="hdot" cx="{L}" cy="{T}" r="5.5" fill="#fff" stroke="#fff" stroke-width="2" hidden style="pointer-events:none"/>')
    out.append("</svg>")
    return "".join(out)


def speedup_chart(board, only=None, title=""):
    agents = [e for e in board["entries"] if e["kind"] in AGENT_KINDS and e["points"] and only in (None, e["slug"])]
    refs = [e for e in board["entries"] if e["kind"] not in AGENT_KINDS and e["valid"]]
    base_entry = next((e for e in board["entries"] if e["kind"] == "baseline"), None)
    base_fps = base_entry["fps"] if base_entry and base_entry.get("fps") else 34.0
    views = [
        ("fps", "Uncapped FPS", fps_svg(agents, refs, base_fps)),
        ("vanilla", "Speedup (×)", speedup_svg(agents, refs, 1.0)),
    ]
    if board["gcc"]:
        views.append(("o2", "vs GCC -O2", speedup_svg(agents, refs, board["gcc"])))
    views.append(("saved", "Cost saved %", cost_saved_svg(agents, refs)))
    return chart_html(views, title)


def bar_pct(sp, top):
    if sp < 1.0:
        return 2.0
    return max(2.0, min(100.0, math.log(sp) / math.log(top) * 100.0))


def unit_bars(units, top):
    rows = []
    for key, lbl in BAR_UNITS:
        v = units.get(key)
        if v is None:
            continue
        rows.append(f'<div class="ubar"><span class="lbl">{lbl}</span><div class="track"><div class="fill" '
                    f'style="width:{bar_pct(v, top):.1f}%;background:{score_color(v)}"></div></div>'
                    f'<span class="val">{v:.2f}&times;</span></div>')
    return '<div class="ubars">' + "".join(rows) + "</div>"


def course_tiles(wls):
    tiles = []
    for c in SM64_COURSES:
        d = wls.get(c)
        if not d:
            continue
        ratio = d["ratios"]["est_console_ms"]
        cand = d["metrics"]["est_console_ms"]
        base, sp = cand / ratio, 1.0 / ratio
        tiles.append(
            f'<div class="ct"><div class="ct-head"><b>{SM64_COURSE_NAMES[c]}</b>'
            f'<span class="ct-badge" style="background:{score_color(sp)}">{sp:.2f}&times;</span></div>'
            f'<div class="ct-row"><span>{base:.1f} &rarr; {cand:.1f} ms</span><span>{1000 / base:.0f} &rarr; {1000 / cand:.0f} fps</span></div>'
            f'<div class="ct-track" title="frame time relative to the 1996 build"><div style="width:{100 * ratio:.1f}%"></div></div></div>')
    return '<div class="ct-grid">' + "".join(tiles) + "</div>"


def routes_table(wls, limit=None):
    rows = sorted(wls.items(), key=lambda kv: kv[1]["ratios"]["est_console_ms"], reverse=True)
    if limit:
        rows = rows[:limit]
    body = "".join(
        f'<tr><td>{route_label(wid)}</td>'
        f'<td class="num">{d["metrics"]["est_console_ms"] / d["ratios"]["est_console_ms"]:.1f} &rarr; {d["metrics"]["est_console_ms"]:.1f} ms</td>'
        f'<td class="num">{d["metrics"]["est_fps"]:.0f}</td>'
        f'<td class="num" style="color:{score_color(1 / d["ratios"]["est_console_ms"])}">{1 / d["ratios"]["est_console_ms"]:.2f}&times;</td></tr>'
        for wid, d in rows)
    return ('<div class="table-wrap"><table><thead><tr><th>route</th><th class="num">frame time</th>'
            f'<th class="num">uncapped fps</th><th class="num">speedup</th></tr></thead><tbody>{body}</tbody></table></div>')


FA_LABELS = {
    "public_to_heldout_overfitting": ("public->held-out overfit", "overfit"),
    "cpu_isa_trap": ("MIPS ISA trap (TEQ)", "trap"),
    "crash_or_hang": ("crash / hang", "trap"),
    "physics_or_state_desync": ("actor / physics desync", "warn"),
    "visual_regression": ("video pixel/SSIM fail", "warn"),
    "audio_regression": ("audio SNR/mel fail", "warn"),
    "console_play_divergence": ("PLAY=1 divergence", "trap"),
    "build_failure": ("compile / link error", "warn"),
    "hardware_safety_violation": ("N64 cache/DMA UB", "trap"),
    "harness_or_integrity_violation": ("#ifndef PLAY glue split", "warn"),
}


def fa_badges_html(fa, max_tags=4, total_routes=26, is_live=False):
    if not fa or not isinstance(fa, dict):
        sfx = "" if is_live else " @ 24h"
        return f'<span class="fa-tag clean">clean ({total_routes}/{total_routes}{sfx})</span>'
    cats = list(fa.get("categories") or [])
    subs = list(fa.get("subcategories") or [])
    # Prioritize architectural root-cause categories first
    priority = [
        "public_to_heldout_overfitting",
        "cpu_isa_trap",
        "crash_or_hang",
        "hardware_safety_violation",
        "console_play_divergence",
        "physics_or_state_desync",
        "visual_regression",
        "audio_regression",
        "harness_or_integrity_violation",
        "build_failure",
    ]
    cats.sort(key=lambda x: priority.index(x) if x in priority else 99)
    tags = []
    for c in cats[:max_tags]:
        lbl, cls = FA_LABELS.get(c, (c.replace("_", " "), ""))
        if c == "crash_or_hang":
            if any("TRAP" in s for s in subs):
                lbl, cls = "MIPS ISA trap (TEQ)", "trap"
            elif any("FPE" in s for s in subs):
                lbl, cls = "VR4300 FPE trap", "trap"
            elif any("ADEL" in s or "ADES" in s for s in subs):
                lbl, cls = "unaligned load/store", "trap"
        elif c == "hardware_safety_violation":
            if "unaligned_cache_cde" in subs:
                lbl = "unaligned CACHE 0x0d"
            elif "kseg1_dirty_synonym" in subs:
                lbl = "KSEG1 dirty synonym"
        elif c == "console_play_divergence":
            if any("dma_coherence" in s for s in subs):
                lbl = "PLAY=1 DMA cache UB"
            elif any("cache_hazard" in s for s in subs):
                lbl = "PLAY=1 cache hazard"
            elif any("no_video" in s for s in subs):
                lbl = "PLAY=1 boot freeze"
        elif c == "physics_or_state_desync" and "gameplay:actors" in subs:
            lbl = "actor desync"
        tags.append(f'<span class="fa-tag {cls}">{esc(lbl)}</span>')
    return '<div class="fa-list">' + "".join(tags) + "</div>"


def agent_diag_strip_html(e, kaze_saved=None):
    if e["kind"] not in AGENT_KINDS or not e.get("analytics"):
        return ""
    a = e["analytics"]
    cs_pct = 100.0 * float(a.get("peak_valid_cost_saved") or e.get("cost_saved") or 0.0)
    kaze_rel = f'{100.0 * cs_pct / (100.0 * kaze_saved):.0f}% of Kaze' if kaze_saved else "physical [0,100%)"

    gen = a.get("generalization_ratio")
    overfit = float(a.get("public_overfit_gap") or 0.0)
    max_pub = a.get("max_unverified_public_speedup")
    if overfit >= 0.05 and max_pub:
        base_sp = e["speedup"] if (e.get("speedup") and e["speedup"] > 0) else 1.0
        gen_val = f'<span class="dv bad">+{overfit:.2f}&times; pub drift</span>'
        gen_sub = f'unverified pub {max_pub:.2f}&times; vs {base_sp:.2f}&times;'
    elif gen is not None:
        cls = "ok" if gen >= 0.96 else "warn"
        gen_val = f'<span class="dv {cls}">{gen:.2f}&times; held/pub</span>'
        gen_sub = "0 public-only overfit checkpoints"
    else:
        gen_val, gen_sub = '<span class="dv">&mdash;</span>', ""

    ret = a.get("retention_ratio")
    pk_hr = a.get("active_hours_at_peak")
    f_pass = a.get("final_routes_passed")
    f_tot = a.get("final_routes_total") or len((e.get("summary") or {}).get("workloads", {})) or 26
    is_live = a.get("final_working_tree_valid") is None or e.get("kind") == "live"
    if is_live:
        vc = a.get("host_checkpoints_valid", 0)
        tc = a.get("host_checkpoints_total", 0)
        ret_val = f'<span class="dv ok">{e.get("end_h", 0.0):.0f}h / 24h live</span>'
        ret_sub = f'{vc}/{tc} host checkpoints valid'
    elif a.get("final_working_tree_valid"):
        ret_val = f'<span class="dv ok">{100.0 * (ret or 1.0):.0f}% retained</span>'
        ret_sub = f'24h tree valid ({f_tot}/{f_tot} routes)'
    else:
        ret_val = '<span class="dv warn">0% @ 24h (rescued)</span>'
        hr_txt = f'peak @ {pk_hr:.1f}h' if pk_hr is not None else "rescued"
        rt_txt = f' &middot; {f_pass}/{f_tot} @ 24h' if f_pass is not None else ""
        ret_sub = f'{hr_txt}{rt_txt}'

    fa = a.get("post_peak_failure_attribution") or a.get("final_failure_attribution")
    return f"""<div class="diag-strip">
  <div class="diag-cell"><span class="dk">Bounded cost saved</span><span class="dv ok">{cs_pct:.1f}%</span><span class="ds">{esc(kaze_rel)}</span></div>
  <div class="diag-cell"><span class="dk">Generalization</span>{gen_val}<span class="ds">{gen_sub}</span></div>
  <div class="diag-cell"><span class="dk">24h tree retention</span>{ret_val}<span class="ds">{ret_sub}</span></div>
  <div class="diag-cell"><span class="dk">Late-run failure modes</span>{fa_badges_html(fa, total_routes=f_tot, is_live=is_live)}</div>
</div>"""


def diagnostic_ruler_table_html(board):
    agents = [e for e in board["entries"] if e["kind"] in AGENT_KINDS and e.get("analytics")]
    if not agents:
        return ""
    kaze_saved = board.get("kaze_saved")
    b_routes = board.get("routes") or 26
    rows = []
    for e in agents:
        a = e["analytics"]
        cs = 100.0 * float(a.get("peak_valid_cost_saved") or e.get("cost_saved") or 0.0)
        kz = f' <span class="muted">({cs / (100.0 * kaze_saved) * 100.0:.0f}% Kaze)</span>' if kaze_saved else ""
        gen = a.get("generalization_ratio")
        gen_s = f'{gen:.3f}&times;' if gen is not None else "&mdash;"
        overfit = float(a.get("public_overfit_gap") or 0.0)
        max_pub = a.get("max_unverified_public_speedup")
        ov_s = (f'<span class="neg">+{overfit:.2f}&times;</span> <span class="muted">({max_pub:.2f}&times; pub)</span>'
                if overfit >= 0.05 and max_pub else '<span class="pos">0.00&times;</span>')
        ft = a.get("final_routes_total") or b_routes
        is_live = a.get("final_working_tree_valid") is None or e.get("kind") == "live"
        if is_live:
            ret_s = f'<span class="pos">live</span> <span class="muted">({e.get("end_h", 0.0):.0f}h / 24h)</span>'
        elif a.get("final_working_tree_valid"):
            ret_s = f'<span class="pos">100%</span> <span class="muted">({ft}/{ft})</span>'
        else:
            fp = a.get("final_routes_passed")
            pk = a.get("active_hours_at_peak")
            pk_s = f'@{pk:.1f}h' if pk is not None else ""
            rt_s = f'{fp}/{ft}' if fp is not None else "build/boot fail"
            ret_s = f'<span class="neg">0%</span> <span class="muted">(rescued {pk_s}, {rt_s} @24h)</span>'
        vc = a.get("host_checkpoints_valid", 0)
        tc = a.get("host_checkpoints_total", 0)
        rows.append(
            f'<tr><td><a href="{e["href"]}"><b>{esc(e["short"])}</b></a></td>'
            f'<td class="num"><b>{e["speedup"]:.3f}&times;</b></td>'
            f'<td class="num">{cs:.1f}%{kz}</td>'
            f'<td class="num">{gen_s}</td>'
            f'<td class="num">{ov_s}</td>'
            f'<td>{ret_s}</td>'
            f'<td class="num">{vc}/{tc}</td>'
            f'<td>{fa_badges_html(a.get("post_peak_failure_attribution") or a.get("final_failure_attribution"), total_routes=ft, is_live=is_live)}</td></tr>'
        )
    return f"""<div class="panel">
<div class="panel-head"><div class="panel-title">Diagnostic ruler &amp; automated failure attribution &middot; zero-transcript signal</div></div>
<p class="small muted">Every metric below is emitted numerically by the v4.1 grader and supervisor without reading agent transcripts:
<b>cost saved</b> bounds frame-time reduction in [0%, 100%), <b>public drift</b> measures unverified public-course speedup gained while failing private held-outs,
<b>24h retention</b> checks whether the final working tree stayed valid vs needing checkpoint rescue, and <b>failure attribution</b> classifies exact post-peak hardware/gate regressions.</p>
<div class="table-wrap"><table><thead><tr>
  <th>model</th><th class="num">verified</th><th class="num">cost saved [0,1)</th><th class="num">held/pub</th>
  <th class="num">pub-only drift</th><th>24h retention</th><th class="num">valid cps</th><th>post-peak failure attribution</th>
</tr></thead><tbody>{"".join(rows)}</tbody></table></div></div>"""


def entry_card(e, rank, top, kaze_saved=None):
    tag, tag_cls = KIND_TAG[e["kind"]]
    name = f'<a href="{e["href"]}">{esc(e["name"])}</a>' if e["href"] else esc(e["name"])
    big = f'{e["speedup"]:.3f}<small>&times;</small>' if e["valid"] else "&minus;1"
    saved_pct = 100.0 * e.get("cost_saved", 1.0 - 1.0 / e["speedup"]) if (e["valid"] and e["speedup"] > 1.0) else 0.0
    saved_lbl = f'<span class="lb-saved">{saved_pct:.1f}% cost saved</span>' if saved_pct > 0 else ""
    sub = [esc(e["org"])] if e.get("org") else []
    if e["valid"] and e["vs_o2"]:
        sub.append(f'{e["vs_o2"]:.2f}&times; vs GCC -O2')
    if e["valid"] and e["speedup"] > 1.0:
        sub.append(f'{saved_pct:.1f}% time saved')
    if e["valid"] and e["fps"]:
        sub.append(f'{e["fps"]:.0f} uncapped FPS')
    tc = (e["summary"] or {}).get("toolchain") if e["summary"] else None
    if isinstance(tc, dict) and tc.get("compiler"):
        sub.append(f'{esc(tc["compiler"])} &middot; {esc(tc.get("ucode", "f3d_old"))}')
    detail = ""
    if e["summary"]:
        wls = e["summary"]["workloads"]
        private = [d["ratios"]["est_console_ms"] for wid, d in wls.items() if wid not in SM64_COURSES]
        priv = (f'<p class="small muted">{len(private)} private routes: {1 / geomean(private):.2f}&times; geometric mean.</p>'
                if private else "")
        detail = (f'<div class="sec-lbl">Public courses</div>{course_tiles(wls)}{priv}'
                  f'<div class="sec-lbl">Slowest routes</div>{routes_table(wls, limit=5)}'
                  + (f'<a class="more" href="{e["href"]}">All routes &amp; checkpoints &rarr;</a>' if e["kind"] in AGENT_KINDS else ""))
    exp = '<button class="lb-exp" type="button">Expand</button>' if detail else ""
    return f"""<div class="lb-card{"" if e["valid"] else " invalid"}">
<div class="lb-score"><span class="rank">#{rank}</span><span class="big">{big}</span>{saved_lbl}</div>
<div class="lb-main">
  <div class="lb-top"><span class="lb-name">{name}</span><span class="tag {tag_cls}">{tag}</span><span class="lb-date">{esc(e["date"])}</span>{exp}</div>
  <div class="lb-sub">{" &middot; ".join(sub)}</div>
  {unit_bars(e["units"], top) if e["valid"] else ""}
  {agent_diag_strip_html(e, kaze_saved=kaze_saved)}
</div>
{f'<div class="lb-detail" hidden>{detail}</div>' if detail else ""}
</div>"""


def board_cards(board):
    top = max([2.0] + [v * 1.08 for e in board["entries"] for v in e["units"].values()])
    kz = board.get("kaze_saved")
    return "".join(entry_card(e, i + 1, top, kaze_saved=kz) for i, e in enumerate(board["entries"]))


PLAYER_JS = """<script>(function(){
var BASE="{BASE}/assets/clips/";
document.querySelectorAll("[data-player]").forEach(function(root){
  var clips=JSON.parse(root.querySelector("script[type='application/json']").textContent);
  var q=function(s){return root.querySelector(s);};
  var vid=q("video"),ctx=[].slice.call(root.querySelectorAll("canvas")).map(function(c){return c.getContext("2d");});
  // The clips are 962x240: 1996 build | candidate | difference with 1px separators.
  // Panels show reference, difference, candidate (gbaeval order).
  var OFF=[0,642,321];
  var stRef=q("[data-stat=ref]"),stDiff=q("[data-stat=diff]"),stCand=q("[data-stat=cand]"),
      candLbl=q("[data-cand]"),title=q("[data-title]"),badge=q("[data-badge]"),cap=q("[data-cap]"),
      scrub=q("input[type=range]"),tl=q("svg.tl"),bp=q("[data-play]"),bs=q("[data-speed]");
  var cur=0,slow=false,head=null;
  function timeline(c){
    if(!tl)return;
    var n=c.base_ms.length,max=Math.max.apply(null,c.base_ms.concat(c.cand_ms))*1.08,p=[];
    var col=c.badge_cls==="invalid"?"#ff5a63":(c.badge_cls==="ref"?"#2ed573":"#7b68ee");
    for(var i=0;i<n;i++){
      var bh=c.base_ms[i]/max*40,ch=c.cand_ms[i]/max*40;
      p.push('<rect x="'+i+'" y="'+(40-bh).toFixed(1)+'" width=".85" height="'+bh.toFixed(1)+'" fill="#38344a"/>');
      p.push('<rect x="'+i+'" y="'+(40-ch).toFixed(1)+'" width=".85" height="'+ch.toFixed(1)+'" fill="'+(c.diff_pct[i]>0.2?"#ff5a63":col)+'"/>');
    }
    p.push('<rect class="head" x="0" y="0" width="1.2" height="40" fill="#fff"/>');
    tl.setAttribute("viewBox","0 0 "+n+" 40");tl.innerHTML=p.join("");head=tl.querySelector(".head");
  }
  function sel(i){
    cur=i;var c=clips[i];
    root.querySelectorAll("[data-clip]").forEach(function(b){b.classList.toggle("on",+b.getAttribute("data-clip")===i);});
    vid.src=BASE+c.video;vid.playbackRate=slow?0.5:1;vid.play().catch(function(){});
    if(candLbl)candLbl.textContent=c.name;
    if(title)title.textContent=c.course+" ("+c.name+")";
    if(badge){badge.textContent=c.badge;badge.className="tag "+c.badge_cls;}
    if(cap)cap.textContent=c.caption;
    if(scrub)scrub.max=c.frames-1;
    if(bp)bp.textContent="Pause";
    timeline(c);
  }
  function draw(){
    var c=clips[cur];
    if(vid.readyState>=2){
      for(var k=0;k<3;k++)ctx[k].drawImage(vid,OFF[k],0,320,240,0,0,320,240);
      var n=c.base_ms.length,f=Math.min(n-1,Math.max(0,Math.floor(vid.currentTime*c.fps)));
      var b=c.base_ms[f],m=c.cand_ms[f],d=c.diff_pct[f];
      stRef.innerHTML="<b>"+b.toFixed(1)+" ms</b> &middot; "+Math.round(1000/b)+" fps";
      stCand.innerHTML="<b>"+m.toFixed(1)+" ms</b> &middot; "+Math.round(1000/m)+" fps &middot; <b class=sp>"+(b/m).toFixed(2)+"&times;</b>";
      stDiff.innerHTML="<b>"+d.toFixed(2)+"%</b> pixels differ";stDiff.classList.toggle("bad",d>0.2);
      if(scrub&&document.activeElement!==scrub)scrub.value=f;
      if(head)head.setAttribute("x",f);
    }
    requestAnimationFrame(draw);
  }
  root.querySelectorAll("[data-clip]").forEach(function(b){b.addEventListener("click",function(){sel(+b.getAttribute("data-clip"));});});
  if(bp)bp.addEventListener("click",function(){if(vid.paused){vid.play();bp.textContent="Pause";}else{vid.pause();bp.textContent="Play";}});
  if(bs)bs.addEventListener("click",function(){slow=!slow;vid.playbackRate=slow?0.5:1;bs.innerHTML=slow?"0.5&times;":"1&times;";});
  if(scrub)scrub.addEventListener("input",function(){vid.currentTime=(+scrub.value+0.5)/clips[cur].fps;});
  if(tl)tl.addEventListener("click",function(e){var r=tl.getBoundingClientRect(),c=clips[cur];
    vid.currentTime=Math.max(0,Math.min(0.999,(e.clientX-r.left)/r.width))*c.frames/c.fps;});
  var m=/[?&]c=(\\d+)/.exec(location.search);
  sel(root.hasAttribute("data-url")&&m&&clips[+m[1]]?+m[1]:0);
  requestAnimationFrame(draw);
});
})();</script>""".replace("{BASE}", BASE)


def clip_course(c):
    return SM64_COURSE_NAMES.get(c["route"], c["route"]).removesuffix(" (Sub)")


def player_html(clips, full=False):
    """Reference | difference | candidate screens drawn from one composite clip, with live frame timing."""
    data = [{**c, "course": clip_course(c)} for c in clips]
    c0 = data[0]
    screens = f"""<div class="screens">
  <div class="screen"><div class="screen-lbl">1996 build (reference)</div><div class="screen-wrap"><canvas width="320" height="240"></canvas></div><div class="screen-stat" data-stat="ref"></div></div>
  <div class="screen"><div class="screen-lbl">Gate Pixel Diff</div><div class="screen-wrap"><canvas width="320" height="240"></canvas></div><div class="screen-stat" data-stat="diff"></div></div>
  <div class="screen"><div class="screen-lbl" data-cand>{esc(c0["name"])}</div><div class="screen-wrap"><canvas width="320" height="240"></canvas></div><div class="screen-stat" data-stat="cand"></div></div>
</div>"""
    blob = json.dumps(data).replace("</", "<\\/")
    tabs = "".join(f'<button type="button" class="pill" data-clip="{i}">{esc(c["name"])} &middot; {esc(SM64_COURSE_SHORT.get(c["route"], c["route"]))}</button>'
                   for i, c in enumerate(data))
    watch_link = f'<a class="mini-btn" href="{BASE}/watch/">Watch all &rarr;</a>' if not full else ""
    return f"""<div class="player{" full" if full else ""}" data-player{" data-url" if full else ""}>
<div class="feature-head"><h2 class="px-h" data-title>{esc(c0["course"])} ({esc(c0["name"])})</h2><span class="tag {c0["badge_cls"]}" data-badge>{esc(c0["badge"])}</span>{watch_link}</div>
<div class="pill-bar">{tabs}</div>
{screens}
<div class="controls"><button type="button" data-play>Pause</button><button type="button" data-speed>1&times;</button>
<input type="range" min="0" max="239" value="0" aria-label="Frame"></div>
<div class="tl-wrap"><div class="tl-hdr"><span>Console frame time per frame: grey = 1996 build, colour = candidate, red = fails video gate</span></div>
<svg class="tl" preserveAspectRatio="none" role="img" aria-label="Per-frame console time"></svg></div>
<p class="cap" data-cap>{esc(c0["caption"])}</p>
<video class="src" muted loop playsinline preload="auto"></video>
<script type="application/json">{blob}</script>
</div>"""


def hw_speedup_visual_html(sm64_rows, board):
    """Interactive N64 speedup & bottleneck visual splitting VR4300 compute vs RDRAM memory stalls + RSP/RDP."""
    cal_by_slug = {slug: s for slug, _t, _p, s in sm64_rows if s.get("status") == "valid"}
    lead = next((e for e in board["entries"] if e["kind"] in AGENT_KINDS and e["valid"]), None)
    specs = [
        ("r0-unchanged", "1996 Retail (IDO -O0)", "baseline", cal_by_slug.get("r0-unchanged")),
        ("r1-gcc-o2", "GCC -O2 (compiler only)", "compiler", cal_by_slug.get("r1-gcc-o2")),
        (EXPERT_REF, "Kaze Human Ref (R10)", "best", cal_by_slug.get(EXPERT_REF)),
    ]
    if lead and lead.get("summary"):
        l_tag = f'({lead["end_h"]:.0f}h live)' if lead.get("kind") == "live" else "(24h)"
        specs.append((lead["slug"], f'{lead["name"]} {l_tag}', "agent", lead["summary"]))
    specs = [x for x in specs if x[3] is not None]
    if len(specs) < 2:
        return ""

    def decompose(m):
        cpu_ms = float(m["cpu_ms"])
        pure_busy_ms = float(m["cpu_busy_cycles"]) / 93750.0
        cont_ms = max(0.0, cpu_ms - pure_busy_ms)
        ic_ms = float(m.get("icache_misses", 0)) * 48.0 / 93750.0
        dc_ms = float(m.get("dcache_misses", 0)) * 40.0 / 93750.0
        wb_ms = float(m.get("dcache_writebacks", 0)) * 40.0 / 93750.0
        stall_ms = min(cpu_ms, ic_ms + dc_ms + wb_ms + cont_ms)
        exec_ms = max(0.0, cpu_ms - stall_ms)
        return {
            "con": round(float(m["est_console_ms"]), 2),
            "cpu": round(cpu_ms, 2),
            "exec": round(exec_ms, 2),
            "stall": round(stall_ms, 2),
            "stall_pct": round(stall_ms / cpu_ms * 100.0, 0) if cpu_ms > 0 else 0,
            "rsp": round(float(m["rsp_ms"]), 2),
            "rdp": round(float(m["rdp_ms"]), 2),
            "has_wb": float(m.get("dcache_writebacks", 0)) > 0,
        }

    courses_payload = {}
    course_keys = ["avg"] + SM64_COURSES
    for ck in course_keys:
        rows_out = []
        base_con = None
        for slug, label, cls, s in specs:
            wls = s["workloads"]
            if ck == "avg":
                ms_list = [decompose(wls[c]["metrics"]) for c in SM64_COURSES if c in wls]
                if not ms_list:
                    continue
                n = len(ms_list)
                d = {k: round(sum(x[k] for x in ms_list) / n, 2) for k in ("con", "cpu", "exec", "stall", "rsp", "rdp")}
                d["stall_pct"] = round(d["stall"] / d["cpu"] * 100.0, 0) if d["cpu"] > 0 else 0
                d["has_wb"] = all(x["has_wb"] for x in ms_list)
            else:
                if ck not in wls:
                    continue
                d = decompose(wls[ck]["metrics"])
            if base_con is None:
                base_con = d["con"]
            sp = base_con / d["con"] if d["con"] > 0 else 1.0
            rows_out.append({
                "label": label, "cls": cls, "sp": round(sp, 2),
                "fps": round(1000.0 / d["con"], 0) if d["con"] > 0 else 0,
                "col": score_color(sp), **d,
            })
        courses_payload[ck] = rows_out

    pills = '<button type="button" class="pill on" data-hwc="avg">6-course avg</button>' + "".join(
        f'<button type="button" class="pill" data-hwc="{c}">{SM64_COURSE_SHORT[c]}</button>' for c in SM64_COURSES
    )
    def _c_pair(ck):
        rs = courses_payload.get(ck, [])
        return (rs[0], next((x for x in rs if x["cls"] == "best"), rs[-1])) if len(rs) >= 2 else (None, None)

    notes = {
        "avg": "Across all 6 courses, <b>~70% of Kaze R10's CPU frame time is the VR4300 stalled waiting on 4 MB RDRAM</b> (I$/D$ misses, writebacks &amp; symmetric RCP bus contention) — pure MIPS compute is only ~5 ms.",
    }
    for ck, desc in (
        ("bob", "On Bob-omb Battlefield, GCC -O2 hits the <b>Fast3D RSP wall</b>; switching to F3DEX2 cuts graphics RSP in half, dropping console frame time from"),
        ("jrb", "Jolly Roger Bay is fill-rate &amp; RDRAM-turnaround heavy: <b>RA_ZB_OPA</b> trims RDP fill + symmetric bus stalls, dropping console frame time from"),
        ("wf", "Whomp's Fortress drops console frame time from"),
        ("ddd", "Dire Dire Docks (Sub) has heavy dynamic collision &amp; water overdraw; cache-friendly surface packing and targeted writebacks cut frame time from"),
        ("bitfs", "Bowser in the Fire Sea drops console frame time from"),
        ("rr", "Rainbow Ride's 14 static decoration pieces + F3DEX2 slash RSP load and drop console frame time from"),
    ):
        b0, bk = _c_pair(ck)
        if b0 and bk:
            notes[ck] = f"{desc} <b>{b0['con']:.1f} ms ({b0['fps']:.0f} FPS) &rarr; {bk['con']:.1f} ms ({bk['fps']:.0f} FPS, {bk['sp']:.2f}&times;)</b>."
    blob = json.dumps({"courses": courses_payload, "notes": notes}).replace("</", "<\\/")
    return f"""<div class="hw-vis" id="hw-vis">
<div class="hw-top">
  <div class="panel-title">Frame time &amp; N64 hardware bottleneck breakdown (ms / frame, lower is faster)</div>
  <div class="pill-bar">{pills}</div>
</div>
<div class="hw-legend">
  <span><i style="background:var(--indigo-lit)"></i>VR4300 Compute (exec)</span>
  <span><i style="background:var(--spark)"></i>RDRAM Cache &amp; Bus Stalls (I$/D$/WB/contention)</span>
  <span><i style="background:var(--amber)"></i>RSP (parallel)</span>
  <span><i style="background:var(--red-soft)"></i>RDP (parallel)</span>
</div>
<div class="hw-ruler" id="hw-ruler"></div>
<div class="hw-rows" id="hw-rows"></div>
<p class="hw-note" id="hw-note"></p>
<script type="application/json" id="hw-data">{blob}</script>
<script>(function(){{
var D=JSON.parse(document.getElementById("hw-data").textContent);
var ruler=document.getElementById("hw-ruler"),box=document.getElementById("hw-rows"),note=document.getElementById("hw-note");
var btns=document.querySelectorAll("#hw-vis [data-hwc]");
function render(k){{
  var rows=D.courses[k]||[];
  var maxMs=Math.max.apply(null,[36].concat(rows.map(function(r){{return Math.max(r.con,r.cpu,r.rsp,r.rdp);}})))*1.06;
  var p16=(16.67/maxMs*100).toFixed(2),p33=(33.33/maxMs*100).toFixed(2);
  ruler.innerHTML='<span class="r60" style="left:'+p16+'%">16.7ms &middot; 60fps</span>'
    +'<span class="r30" style="left:'+p33+'%">33.3ms &middot; 30fps</span>';
  var refHtml='<div class="hw-ref r60" style="left:'+p16+'%"></div><div class="hw-ref r30" style="left:'+p33+'%"></div>';
  box.innerHTML=rows.map(function(r){{
    var we=(r.exec/maxMs*100).toFixed(2),ws=(r.stall/maxMs*100).toFixed(2);
    var wrsp=(r.rsp/maxMs*100).toFixed(2),wrdp=(r.rdp/maxMs*100).toFixed(2);
    var wbHint=r.has_wb?r.stall_pct+"% RAM stall":("&ge;"+r.stall_pct+"% RAM stall");
    return '<div class="hw-row '+r.cls+'">'
      +'<div class="hw-rhead"><span class="hw-rname">'+r.label+'</span>'
      +'<span class="hw-rmeta"><span><b>'+r.con.toFixed(1)+' ms</b> &middot; '+r.fps.toFixed(0)+' fps</span>'
      +'<span class="hw-sp" style="background:'+r.col+'">'+r.sp.toFixed(2)+'&times;</span></span></div>'
      +'<div class="hw-bar-area">'+refHtml
      +'<div class="hw-stack" title="VR4300 compute '+r.exec.toFixed(1)+' ms + RDRAM stalls '+r.stall.toFixed(1)+' ms = CPU '+r.cpu.toFixed(1)+' ms">'
      +'<div class="hw-seg exec" style="width:'+we+'%">'+(r.exec>=4.0?r.exec.toFixed(1)+'ms':'')+'</div>'
      +'<div class="hw-seg stall" style="width:'+ws+'%">'+(r.stall>=5.5?r.stall.toFixed(1)+'ms ('+wbHint+')':'')+'</div>'
      +'</div></div>'
      +'<div class="hw-rcp">'
      +'<div class="hw-mini"><span>RSP</span><div class="t"><div class="f" style="width:'+wrsp+'%;background:var(--amber)"></div></div><span>'+r.rsp.toFixed(1)+' ms</span></div>'
      +'<div class="hw-mini"><span>RDP</span><div class="t"><div class="f" style="width:'+wrdp+'%;background:var(--red-soft)"></div></div><span>'+r.rdp.toFixed(1)+' ms</span></div>'
      +'</div></div>';
  }}).join("");
  note.innerHTML=D.notes[k]||"";
}}
btns.forEach(function(b){{b.addEventListener("click",function(){{
  btns.forEach(function(x){{x.classList.toggle("on",x===b);}});
  render(b.getAttribute("data-hwc"));
}});}});
render("avg");
}})();</script>
</div>"""


def post_cards(post_items):
    return '<div class="post-cards">' + "".join(
        f'<a class="post-card" href="{BASE}/blog/{slug}/"><div class="pc-top"><span class="pc-title">{esc(m["title"])}</span>'
        f'<span class="pc-date">{m["date"]}</span></div><p>{esc(m["summary"])}</p></a>' for slug, m, _ in post_items) + "</div>"


def build_index(out, board, sm64_rows, post_items, clips):
    lead = next((e for e in board["entries"] if e["kind"] in AGENT_KINDS and e["valid"]), None)
    base_fps = next(e["fps"] for e in board["entries"] if e["kind"] == "baseline")
    top = (f'<p class="top-cand">Top candidate: <a href="{lead["href"]}">{esc(lead["name"])}</a> '
           f'<b>{lead["fps"]:.0f} FPS</b> <b>({lead["speedup"]:.3f}&times;)</b></p>') if (lead and lead.get("fps")) else (
           f'<p class="top-cand">Top candidate: <a href="{lead["href"]}">{esc(lead["name"])}</a> '
           f'<b>{lead["speedup"]:.3f}&times;</b></p>' if lead else "")
    featured = player_html(clips, full=False) if clips else ""
    hw_vis = hw_speedup_visual_html(sm64_rows, board)
    body = f"""
<section class="hero">
  <div class="hero-text">
    <h1>Models try to make Super Mario 64 run faster on a real Nintendo 64.</h1>
    <p>We give AI coding agents the C source of Super Mario 64, N64 hardware specs, and 24 hours to make it run as fast as
    possible on an original 4&nbsp;MB console, without changing the game. Every frame is costed on an instrumented N64 emulator
    and checked against the 1996 game.</p>
    <p>The 1996 build runs at about {base_fps:.0f} uncapped frames per second on our routes (well shy of the N64's 60&nbsp;Hz refresh ceiling).
    There is no score cap: agents push console FPS and speedup as high as the 4&nbsp;MB hardware allows.</p>
    {top}
    <div class="hero-btns"><a class="px-btn primary" href="{BASE}/leaderboard/">Leaderboard</a>
    <a class="px-btn" href="{BASE}/watch/">Watch</a><a class="px-btn" href="{BASE}/blog/">Blog</a></div>
  </div>
  <div class="hero-chart">{speedup_chart(board, title="Best valid N64 FPS & speedup over 24h (hover checkpoints)")}</div>
</section>
<div class="col">
{featured}

<div class="sec-head-row"><h2 class="px-h">Where the speedup comes from</h2><a class="mini-btn" href="{BASE}/calibration/">Calibration &rarr;</a></div>
{hw_vis}

<div class="sec-head-row"><h2 class="px-h">Leaderboard</h2><a class="mini-btn" href="{BASE}/leaderboard/">Full leaderboard &rarr;</a></div>
{board_cards(board)}
{diagnostic_ruler_table_html(board)}

<h2 class="px-h">Scoring</h2>
<div class="box">
<p>After 24 hours we rebuild the agent's game from source with our own toolchain and replay recorded controller
input on {board["routes"]} routes: the {board["public"]} public courses the agent can test, plus {board["private"]}
private routes it never sees (other courses and seeded button mashing). A frame costs as much as the busiest of the
console's four units, which run in parallel: <code>max(CPU, RSP, RDP, RDRAM bus)</code>. See
<a href="{BASE}/blog/what-the-emulator-measures/">What the emulator measures</a> and
<a href="{BASE}/blog/calibrating-the-grader/">Calibrating the grader</a>.</p>
<div class="score-sec"><span class="k" style="color:var(--pcb)">Speedup, FPS &amp; RL reward</span><span class="w">score</span>
<p>In Mario Eval v4, the 6 public dev courses carry <b>0% weight</b> in the final score — 100% of the score comes from
unseen private held-out trajectories (75% scripted multi-course/multi-act routes, 25% seeded random-input routes across 18 SM64 worlds).
We report unbounded <b>speedup</b> (<code>1 / geomean(T<sub>cand</sub> / T<sub>1996</sub>)</code>) and <b>uncapped console FPS</b> alongside
log-scaled RL reward (<code>log<sub>2</sub>(speedup) / 4</code>) and bounded <b>cycle cost saved</b>
<code>1 &minus; T<sub>cand</sub> / T<sub>1996</sub> &isin; [0%, 100%)</code>.</p></div>
<div class="score-sec"><span class="k" style="color:var(--spark)">Diagnostic sub-rulers</span><span class="w">telemetry</span>
<p>Every run automatically reports <b>per-route effective speedup</b>, <b>held-out generalization</b>, <b>public-only overfit drift</b>,
<b>24h working-tree retention</b> (<code>final / peak</code>), and <b>numerical failure attribution</b> (VR4300 CPU ISA traps, 4 MB RDRAM OOB, cache/DMA UB, <code>PLAY=1</code> divergence, actor desync, video/audio regressions) without reading transcripts.</p></div>
<div class="score-sec"><span class="k" style="color:var(--amber)">Gameplay</span><span class="w">gate</span>
<p>Mario's position, speed, action and stats, the camera, and every actor within 2000 units match the 1996 game on every frame.</p></div>
<div class="score-sec"><span class="k" style="color:var(--cyan)">Video</span><span class="w">gate</span>
<p>Each frame matches the original picture, or one consistent accepted variant (such as Nintendo's F3DEX2 microcode) across the replay, on 99.8% of pixels within &plusmn;2/31 per channel and &ge; 0.98 single-scale 16&times;16 block-SSIM.</p></div>
<div class="score-sec"><span class="k" style="color:var(--red-soft)">Audio</span><span class="w">gate</span>
<p>At least 40 dB signal-to-noise against the original sound output, or a perceptual 40-band log-mel spectrogram match (&ge; 0.95 cosine similarity on both stereo channels, loudness-guarded) for timing-preserving audio rewrites.</p></div>
<div class="score-sec"><span class="k" style="color:var(--indigo-lit)">Hardware</span><span class="w">gate</span>
<p>Fits in 4 MB of RAM with zero unaligned <code>CACHE 0x0d</code> ops, zero KSEG1 dirty-cache synonyms, coherent SP/DP DMA writebacks, untouched harness/<code>PLAY</code> glue, and a linked <code>PLAY=1</code> retail console ROM that cold-boots with active video and RSP audio. No route may regress &gt; 5%. Failing any gate scores &minus;1.</p></div>
</div>

<h2 class="px-h">How models run</h2>
<div class="box">
<p>Each model gets a Docker container with the Super Mario 64 decompilation (extracted assets, no ROM), the SGI IDO
and GCC MIPS compilers, the instrumented emulator, and a <code>mev</code> tool that builds, runs, profiles and grades
the public courses. It has no internet access beyond its model API. We run each model for 24 hours; the host
commits its work and grades a snapshot on every route every two hours.</p>
<p>See <a href="{BASE}/blog/building-mario-eval/">Building Mario Eval</a> for the container layout and the task statement.</p>
</div>

<h2 class="px-h">Blog</h2>
{post_cards(post_items)}

<h2 class="px-h" id="acknowledgements">Acknowledgements</h2>
<p class="ack">Built by <a href="https://ilya.as/">{AUTHOR}</a>, modelled on Mechanize's <a href="https://gbaeval.com/">GBA Eval</a>.
Human-expert techniques from <a href="https://www.youtube.com/@KazeN64">Kaze Emanuar</a>'s public Super Mario 64 work and
ultrasm64 (FazanaJ, CrashOveride95). Decompilation by the <a href="https://github.com/n64decomp/sm64">n64decomp</a> team;
emulation by <a href="https://ares-emu.net/">ares</a>.</p>
</div>
{PLAYER_JS if featured else ""}
"""
    write(out, "index.html", page("Mario Eval — make Super Mario 64 faster on a real N64", body, active=""))


def ladder_html(sm64_rows):
    """Reference rungs on the 6 public courses, re-rankable by resource profile."""
    by_slug = {slug: (title, s) for slug, title, _p, s in sm64_rows if s["status"] == "valid"}
    order = [
        ("r11-beyond-kaze", "Beyond Kaze (R11)", "R10 plus 16B Object cache-line packing, store-if-changed D-cache guards, and byte-unpacked audio flags."),
        ("r10-kaze-master", "Kaze master reference (R10)", "Kaze Emanuar's and ultrasm64's published techniques, reconstructed across CPU, RSP, RDP, and RDRAM."),
        ("r9-kaze-partial", "Partial Kaze reference (R9)", "I-cache layout, 1-ULP trig, 3-line Surface, Sub cache, lazy Mtx, RA_ZB_OPA, coin batch, −304 KB."),
        ("r8-kaze-collision-objects", "Collision & objects (R8)", "R7 plus cache-line Surface, Bowser's Sub surface cache, single-floor shadows."),
        ("r7-kaze-icache-trig", "I-cache & table-free math (R7)", "16 KB I-cache de-aliasing, polynomial sin/cos, bit-exact atan2s."),
        ("r6-kaze-super", "Early multi-subsystem (R6)", "GCC -O2, Kaze matrix math, CACHE 0x0d, skybox cull, double buffer."),
        ("r1-gcc-o2", "GCC -O2, no code changes (R1)", "Compiler switch only."),
        ("r4-kaze-rdp-opa", "IDO + RA_ZB_OPA render modes (R4)", "Drops per-pixel framebuffer reads on opaque surfaces."),
        ("r2-kaze-mtx", "IDO + Kaze matrix math (R2)", "Stackless mtxf_mul and packed mtxf_to_mtx."),
        ("r0-unchanged", "1996 retail build (R0)", "The unmodified decompilation."),
    ]
    entries = []
    for slug, label, note in order:
        if slug not in by_slug:
            continue
        s = by_slug[slug][1]
        profs = {}
        for p in PROFILES:
            pv = s.get("profiles", {}).get(p, {})
            ok = pv.get("valid", False)
            profs[p] = {"valid": ok, "speedup": round(float(pv.get("speedup", 0.0)), 3) if ok else 0.0,
                        "vs_o2": round(float(pv["vs_o2_speedup"]), 3) if ok and pv.get("vs_o2_speedup") else None}
        entries.append({"name": label, "href": f"{BASE}/calibration/#sm64-{slug}", "note": note,
                        "expert": slug == EXPERT_REF, "fps": round(mean_fps(s) or 0.0, 1), "profiles": profs})
    pills = "".join(f'<button class="pill{" on" if p == "console" else ""}" data-prof="{p}">{p}</button>' for p in PROFILES)
    return f"""<div class="panel-head"><div class="panel-title">Reference ladder &middot; 6 public courses</div><div class="pill-bar" id="lad-prof">{pills}</div></div>
<div class="table-wrap"><table id="lad"><thead><tr><th>entry</th><th class="bar-cell" id="lad-hdr">console speedup</th>
<th class="num">vs GCC -O2</th><th class="num">uncapped FPS</th></tr></thead><tbody></tbody></table></div>
<script>(function(){{
var E={json.dumps(entries)},tb=document.querySelector("#lad tbody"),hdr=document.getElementById("lad-hdr"),
    btns=document.querySelectorAll("#lad-prof .pill");
function render(p){{
  hdr.textContent=p+" speedup";
  var list=E.slice().sort(function(a,b){{var x=a.profiles[p],y=b.profiles[p];
    return x.valid!==y.valid?(y.valid?1:-1):y.speedup-x.speedup;}});
  var max=Math.max.apply(null,list.map(function(e){{return e.profiles[p].speedup;}}).concat([1.25]));
  tb.innerHTML=list.map(function(e){{var v=e.profiles[p];
    var w=v.valid?Math.max(4,v.speedup/max*100):0;
    return '<tr'+(e.expert?' class="expert-row"':'')+'><td><a href="'+e.href+'">'+e.name+'</a><br><span class="small muted">'+e.note+'</span></td>'
      +'<td class="bar-cell"><b>'+(v.valid?v.speedup.toFixed(2)+'&times;':'over budget')+'</b><div class="bar-track"><div class="bar-fill'+(e.expert?' expert':'')+'" style="width:'+w.toFixed(1)+'%"></div></div></td>'
      +'<td class="num">'+(v.vs_o2?v.vs_o2.toFixed(2)+'&times;':'&mdash;')+'</td><td class="num">'+e.fps.toFixed(1)+'</td></tr>';
  }}).join("");
}}
btns.forEach(function(b){{b.addEventListener("click",function(){{
  btns.forEach(function(x){{x.classList.toggle("on",x===b);}});render(b.getAttribute("data-prof"));}});}});
render("console");
}})();</script>"""


def bands_html(sm64_rows):
    by_slug = {slug: s for slug, _t, _p, s in sm64_rows if s["status"] == "valid"}

    def sp(slug):
        return primary_profile(by_slug[slug])["speedup"]

    need = ["r0-unchanged", "r1-gcc-o2", "r7-kaze-icache-trig", "r9-kaze-partial", EXPERT_REF]
    if any(s not in by_slug for s in need):
        return ""
    rows = [
        (1.0, "1.00&times;", "The 1996 game",
         f"The retail build: about {mean_fps(by_slug['r0-unchanged']):.0f} uncapped FPS on the public courses.", "r0-unchanged"),
        (sp("r1-gcc-o2"), f'{sp("r1-gcc-o2"):.2f}&times;', "Compiler only",
         "The same code rebuilt with GCC -O2. Agents are also scored against this.", "r1-gcc-o2"),
        (sp("r9-kaze-partial"), f'{sp("r7-kaze-icache-trig"):.2f}&ndash;{sp("r9-kaze-partial"):.2f}&times;', "Targeted fixes",
         "Table-free trig, I-cache layout, cache-friendly collision, matrix math.", "r9-kaze-partial"),
        (sp(EXPERT_REF), f'{sp(EXPERT_REF):.2f}&times;', "Human expert",
         "Kaze Emanuar-style work across CPU, RSP and RDP: F3DEX2, culling, fused matrices, audio, memory layout.", EXPERT_REF),
        (2.0, f'&gt; {sp(EXPERT_REF):.2f}&times;', "Beyond published work", "No reference yet; the score has no upper bound.", None),
    ]
    body = "".join(
        f'<tr><td><span class="sq" style="background:{score_color(v)}"></span>{rng}</td><td><b>{lbl}</b></td>'
        f'<td class="muted">{desc}</td><td class="num">'
        + (f'<a href="{BASE}/calibration/#sm64-{slug}">Example &rarr;</a>' if slug else "") + "</td></tr>"
        for v, rng, lbl, desc, slug in rows)
    return ('<div class="box"><div class="box-title">What speedups mean <span class="muted">(6 public courses)</span></div>'
            f'<table class="bands">{body}</table></div>')


def build_leaderboard(out, board, sm64_rows, agent_runs):
    body = f"""<div class="col">
<h1 class="px-h">Leaderboard</h1>
<p class="muted">Ranked by console speedup over the 1996 build on {board["routes"]} routes: the {board["public"]} public
courses agents can test plus {board["private"]} private routes they never see. Bars show the console bottleneck and each
unit it is the maximum of. Expand an entry for per-course frame times.</p>
{board_cards(board)}
{diagnostic_ruler_table_html(board)}
<h2 class="px-h">Score over time</h2>
{speedup_chart(board, title=f"Best valid host grade &middot; {board['routes']} routes")}
{bands_html(sm64_rows)}
<h2 class="px-h">Reference ladder</h2>
<p class="muted">Each rung is one known patch on the clean game, graded on the 6 public courses. Switch profiles to rank by a
single unit. Every rung, including the rejected shortcuts, is on the <a href="{BASE}/calibration/">calibration</a> page.</p>
{ladder_html(sm64_rows)}
<div class="chart-box">{trajectory_svg(sm64_rows)}</div>
<div class="chart-box">{sm64_bottleneck_svg(sm64_rows)}</div>
{telemetry_inspector_html(sm64_rows, agent_runs)}
<h2 class="px-h">Run it yourself</h2>
<pre><code># 1. Prepare Super Mario 64 and private held-out trajectories (keep PRIVATE_SEED secret)
./scripts/build-images.sh --no-task
./sm64/setup.sh "/path/to/Super Mario 64 (USA).z64"
python3 sm64/corpus/make_replays.py --heldout /private/replays --heldout-seed "$PRIVATE_SEED"
./scripts/precompute.sh --heldout /private/replays --cache /private/reference
./scripts/precompute.sh
./scripts/build-images.sh
./quickstart/smoke-test.sh

# 2. Launch a 24-hour timed run
docker compose --project-directory quickstart up -d
MEV_REFERENCE_DIR=/private/reference AGENT_CMD='your-agent-command' ./quickstart/run-agent.sh \\
  --hours 24 --profile console --heldout /private/replays</code></pre>
</div>"""
    write(out, "leaderboard/index.html", page("Leaderboard | Mario Eval", body, active="leaderboard/"))


def build_model(out, e, board):
    s = e["summary"]
    wls = s["workloads"]
    top = max([2.0] + [v * 1.08 for v in e["units"].values()])
    valid_cps = sum(1 for c in e["checkpoints"] if c.get("status") == "valid")
    a = e.get("analytics") or {}
    cs_pct = 100.0 * float(a.get("peak_valid_cost_saved") or e.get("cost_saved") or 0.0)
    if a.get("final_working_tree_valid") is None or e.get("kind") == "live":
        ret_lbl = f'live ({e["end_h"]:.0f}h / 24h)'
    else:
        ret_lbl = "100% (valid)" if a.get("final_working_tree_valid") else "0% (rescued)"
    meta = " &middot; ".join(x for x in [esc(e["org"]), f'Graded: {esc(e["date"])}' if e["date"] else "",
                                         f'commit: {esc(e["commit"])}' if e["commit"] else "",
                                         f'harness: {esc(e["harness"])}' if e["harness"] else ""] if x)
    links = (f'<a href="{esc(e["repo_url"])}">Source &amp; transcript &rarr;</a>' if e["repo_url"] else "") + \
        f'<a href="{BASE}/leaderboard/">Compare with other entries &rarr;</a>'
    cp_rows = []
    for c in e["checkpoints"]:
        ok = c.get("status") == "valid"
        sp = (c.get("speedups") or {}).get("console")
        cs = (c.get("cost_saved") or {}).get("console")
        if cs is None and ok and sp and sp > 0:
            cs = 1.0 - 1.0 / sp
        diag = c.get("diagnostics") or {}
        unv_pub = (diag.get("unverified_public_speedups") or {}).get("console")
        wt = diag.get("workloads_total") or len(wls) or 26
        if ok:
            routes_txt = f"{wt}/{wt}"
            pub_txt = f'{unv_pub:.2f}&times;' if unv_pub else "&mdash;"
            fa_html = '<span class="fa-tag clean">valid</span>'
        else:
            wp = diag.get("workloads_passed")
            routes_txt = f"{wp}/{wt}" if wp is not None else f"0/{wt}"
            pub_txt = f'{unv_pub:.2f}&times;' if unv_pub else "&mdash;"
            fa_html = fa_badges_html(c.get("failure_attribution"), total_routes=wt)
        cp_rows.append(
            f'<tr class="{"" if ok else "invalid"}"><td>{esc(c.get("name", ""))}</td><td class="num">{c["elapsed_hours"]:.1f}h</td>'
            f'<td><span class="tag {"valid" if ok else "invalid"}">{esc(c.get("status"))}</span></td>'
            f'<td class="num">{(f"{sp:.3f}&times;" if ok and sp else "&mdash;")}</td>'
            f'<td class="num">{(f"{100.0 * cs:.1f}%" if ok and cs else "&mdash;")}</td>'
            f'<td class="num">{pub_txt}</td>'
            f'<td class="num">{routes_txt}</td>'
            f'<td>{fa_html}</td></tr>'
        )
    cp_rows_html = "".join(cp_rows)
    body = f"""<div class="col">
<a class="back" href="{BASE}/leaderboard/">&larr; Leaderboard</a>
<div class="model-head">
  <div><h1 class="px-h">{esc(e["name"])}</h1><div class="model-meta">{meta}</div>
  <div class="model-stats"><div><span>Wall clock</span><b>{e["end_h"]:.1f}h</b></div>
  <div><span>Checkpoints</span><b>{valid_cps}/{len(e["checkpoints"])} valid</b></div>
  <div><span>Cost saved</span><b>{cs_pct:.1f}%</b></div>
  <div><span>24h retention</span><b>{ret_lbl}</b></div></div></div>
  <div class="model-score"><span>Console speedup</span><b style="color:{score_color(e["speedup"])}">{e["speedup"]:.3f}<small>&times;</small></b>
  <span>{f'{e["vs_o2"]:.2f}&times; vs GCC -O2 &middot; {cs_pct:.1f}% saved' if e["vs_o2"] else ""}</span><div class="model-links">{links}</div></div>
</div>
<div class="tabs" data-tabs><button type="button" class="on" data-tab="overview">Overview</button>
<button type="button" data-tab="routes">Routes <span class="muted">{len(wls)}</span></button>
<button type="button" data-tab="checkpoints">Checkpoints <span class="muted">{len(e["checkpoints"])}</span></button></div>
<div data-tabpane="overview">
<div class="box"><div class="box-title">About this candidate</div><p>{esc(e["note"])}</p>{agent_diag_strip_html(e, kaze_saved=board.get("kaze_saved"))}</div>
{speedup_chart(board, only=e["slug"], title="Score trajectory")}
<div class="box"><div class="box-title">Units</div>{unit_bars(e["units"], top)}
<p class="small muted">Speedup of each unit's busy time over the 1996 build (geometric mean over routes). The console
score follows the busiest unit in each frame.</p></div>
<h2 class="px-h">Public courses</h2>{course_tiles(wls)}
</div>
<div data-tabpane="routes" hidden>{routes_table(wls)}</div>
<div data-tabpane="checkpoints" hidden><div class="table-wrap"><table><thead><tr><th>checkpoint</th><th class="num">elapsed</th>
<th>status</th><th class="num">speedup</th><th class="num">saved</th><th class="num">pub 6</th><th class="num">routes</th><th>failure attribution</th></tr></thead><tbody>{cp_rows_html}</tbody></table></div>
<p class="small muted">Host grades on all {len(wls)} routes. Invalid checkpoints preserve unverified public speedup, passed route counts, and deterministic failure attribution.</p></div>
</div>"""
    write(out, f"model/{e['slug']}/index.html", page(f'{e["name"]} | Mario Eval', body, active="leaderboard/"))


def build_watch(out, clips):
    if not clips:
        return
    body = f"""<div class="col">
<h1 class="px-h">Watch</h1>
<p class="muted">Each replay feeds the same recorded controller input to the 1996 build and to a candidate on the
instrumented emulator. The middle screen shows pixels that differ by more than &plusmn;2/31 per channel; the readouts
show each frame's console time. The last two are shortcuts the grader rejects.</p>
{player_html(clips, full=True)}
</div>
{PLAYER_JS}"""
    write(out, "watch/index.html", page("Watch | Mario Eval", body, active="watch/"))


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
                                     f"fail on frame {x['worst_frame']} (limit 0.35%)</li>")
                    elif "logmel_score" in x:
                        snr_part = f"SNR {x['snr_db']:.1f} dB, " if x.get("snr_db") is not None else ""
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: {snr_part}log-mel {x['logmel_score']:.3f} "
                                     f"(min frame {x.get('worst_logmel_frame_score', 0):.3f}, RMS ratio {x.get('rms_ratio', 0):.2f})</li>")
                    elif x.get("snr_db") is not None:
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: SNR {x['snr_db']:.1f} dB (limit 40 dB)</li>")
                    else:
                        items.append(f"<li><b>{g}</b> on {esc(wid)}: {esc(x.get('reason', x.get('status')))}</li>")
            detail.append("<ul class=small>" + "".join(items[:8]) + "</ul>")
        link = "" if slug == "r0-unchanged" else f' &middot; <a href="{REPO}/blob/main/{patch_dir}/{slug}.patch">patch</a>'
        sections.append(f'<h2 id="{anchor_prefix}{slug}">{title} <span class="tag {s["status"]}">{s["status"]}</span></h2>'
                        f'<p class="muted">{purpose}{link}</p>' + "\n".join(detail))
    return "".join(sections)


def build_calibration(out, sm64_rows):
    sm64_part = ""
    if sm64_rows:
        sm64_part = (
            '<h2 class="px-h">Super Mario 64 &middot; 6 public dev courses</h2>'
            + cal_table(sm64_rows, anchor_prefix="sm64-")
            + '<h3>Baseline (1996 IDO)</h3>'
            + baseline_table(sm64_rows)
            + render_sections(sm64_rows, "sm64/calibration", anchor_prefix="sm64-")
        )
    body = f"""<div class="col wide"><h1 class="px-h">Calibration</h1>
<p class="muted">Each patch is applied to a clean Super Mario 64 decompilation tree and graded like a submission: known hardware
speedups must pass and score monotonically, while known shortcuts (<code>-ffast-math</code>, muted audio, low-poly Mario,
halved physics steps, harness tampering) must be rejected.</p>
{sm64_part}</div>"""
    write(out, "calibration/index.html", page("Calibration | Mario Eval", body, active="calibration/"))


def build_blog(out, post_items):
    write(out, "blog/index.html", page("Blog | Mario Eval",
                                       f'<div class="col"><h1 class="px-h">Blog</h1>{post_cards(post_items)}</div>', active="blog/"))
    for slug, m, text in post_items:
        body = (f'<article class="col prose"><a class="back" href="{BASE}/blog/">&larr; Blog</a><h1 class="px-h">{esc(m["title"])}</h1>'
                f'<p class="meta">{AUTHOR.upper()} &middot; {m["date"]}</p>'
                f'{text.replace("{BASE}", BASE).replace("{REPO}", REPO)}</article>')
        write(out, f"blog/{slug}/index.html", page(f'{m["title"]} | Mario Eval', body, active="blog/", desc=m["summary"]))


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = Path(sys.argv[1])
    out.mkdir(parents=True, exist_ok=True)
    shutil.copy(SITE / "style.css", out / "style.css")
    clips = export_clips(out)
    sm64_rows = load_cal(SM64_CAL, SM64_PATCHES)
    trial_rows = load_cal(SM64_TRIAL_CAL, SM64_PATCHES)
    agent_runs = load_agent_runs()
    post_items = posts()
    board = build_board(trial_rows or sm64_rows, agent_runs)
    if board is None:
        sys.exit("no agent or reference runs with a workload_set under results/")
    build_index(out, board, sm64_rows, post_items, clips)
    build_leaderboard(out, board, sm64_rows, agent_runs)
    for e in board["entries"]:
        if e["kind"] in AGENT_KINDS and e["valid"]:
            build_model(out, e, board)
    build_watch(out, clips)
    build_calibration(out, sm64_rows)
    build_blog(out, post_items)
    print(f"wrote {out}: {len(sm64_rows)} sm64 entries, {len(agent_runs)} agent runs, {len(clips)} clips, {len(post_items)} posts")


if __name__ == "__main__":
    main()
