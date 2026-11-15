#!/usr/bin/env python3
"""Build the Mario Eval website (served at https://ilya.as/mario-eval/).

    python3 site/build.py <out_dir>

Reads the committed calibration summaries (results/calibration/*/summary.json)
and the hand-written posts in site/posts/, and writes a static site.
"""
import html
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
CAL = ROOT / "results" / "calibration"
BASE = "/mario-eval"
REPO = "https://github.com/IlyaasK/mario-eval"

# Calibration patches, in presentation order, with what each one tests.
PATCHES = [
    ("r0-unchanged", "Unchanged rebuild", "The baseline must score exactly 0 on every profile."),
    ("r1-o2-ieee", "<code>-O2 -fno-fast-math</code>", "Compiler optimization that keeps IEEE float semantics."),
    ("r2-engine", "View-projection once per frame, terrain heights precomputed",
     "Algorithmic changes at <code>-O0</code> with bit-identical results."),
    ("r3-cde", "Create Dirty Exclusive on the audio block",
     "The VR4300 <code>CACHE</code> trick: claim lines that will be fully overwritten without reading RDRAM."),
    ("r4-memory", "Delete an unused 256 KiB buffer", "A pure RAM saving."),
    ("r5-reassoc", "<code>(P&middot;V)&middot;M</code> instead of <code>P&middot;(V&middot;M)</code>",
     "Same math, different rounding: sub-pixel vertex shifts must pass the video gate."),
    ("r6-sine-table", "Sine table and closed-form triangle wave in the synth",
     "Approximate audio within tolerance."),
    ("i0-o2-fastmath", "<code>-O2</code> with libdragon's default <code>-ffast-math</code>",
     "Faster, but changes floating-point results that feed gameplay."),
    ("i1-mute", "Skip audio synthesis", "Shortcut: remove work the player would notice."),
    ("i2-no-particles", "Skip drawing particles", "Shortcut: remove visible geometry."),
    ("i3-physics", "Two physics substeps instead of four", "Shortcut: change the simulation."),
    ("i4-tamper", "Edit the harness", "Integrity check."),
]
PROFILES = ["speed", "rsp", "traffic", "memory"]
SCENES = ["meadow", "fortress", "storm", "concert"]

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

PIPELINE_SVG = """<svg viewBox="0 0 940 150" role="img" aria-label="Grading pipeline">
  <defs><marker id="arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto">
    <path d="M0 0 L10 5 L0 10 z" fill="currentColor"/></marker></defs>
  <g font-family="IBM Plex Mono, monospace" font-size="13" fill="currentColor">
    <g stroke="currentColor" stroke-width="1.5" fill="none">
      <rect x="4" y="40" width="130" height="64" rx="6"/>
      <rect x="168" y="40" width="130" height="64" rx="6"/>
      <rect x="332" y="40" width="170" height="64" rx="6"/>
      <rect x="536" y="16" width="190" height="112" rx="6"/>
      <rect x="760" y="40" width="176" height="64" rx="6"/>
      <line x1="134" y1="72" x2="166" y2="72" marker-end="url(#arr)"/>
      <line x1="298" y1="72" x2="330" y2="72" marker-end="url(#arr)"/>
      <line x1="502" y1="72" x2="534" y2="72" marker-end="url(#arr)"/>
      <line x1="726" y1="72" x2="758" y2="72" marker-end="url(#arr)"/>
    </g>
    <text x="69" y="68" text-anchor="middle">source</text>
    <text x="69" y="86" text-anchor="middle" opacity="0.7">patch</text>
    <text x="233" y="68" text-anchor="middle">trusted</text>
    <text x="233" y="86" text-anchor="middle">rebuild</text>
    <text x="417" y="64" text-anchor="middle">ares N64</text>
    <text x="417" y="82" text-anchor="middle" opacity="0.7">replays, unthrottled</text>
    <text x="417" y="98" text-anchor="middle" opacity="0.7">interpreter + caches</text>
    <text x="631" y="38" text-anchor="middle">gates</text>
    <text x="631" y="60" text-anchor="middle" opacity="0.7">gameplay: bit-exact</text>
    <text x="631" y="78" text-anchor="middle" opacity="0.7">video, audio: tolerance</text>
    <text x="631" y="96" text-anchor="middle" opacity="0.7">integrity, 4 MB, budgets</text>
    <text x="631" y="116" text-anchor="middle" opacity="0.7">any fail: reward -1</text>
    <text x="848" y="68" text-anchor="middle">reward</text>
    <text x="848" y="86" text-anchor="middle" opacity="0.7">1 - geomean(ratio)</text>
  </g>
</svg>"""


def esc(s):
    return html.escape(str(s))


def page(title, body, active="", desc=""):
    nav = [("", "Overview"), ("calibration/", "Calibration"), ("blog/", "Blog")]
    links = " ".join(
        f'<a href="{BASE}/{href}"{" class=on" if href == active else ""}>{name}</a>' for href, name in nav)
    links += f' <a href="{REPO}">GitHub</a>'
    desc = desc or "An RLVR environment: make a Nintendo 64 game cheaper to run on the original hardware without changing it."
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


def load_cal():
    rows = []
    for slug, title, purpose in PATCHES:
        f = CAL / slug / "summary.json"
        if f.exists():
            rows.append((slug, title, purpose, json.loads(f.read_text())))
    return rows


def reward_cell(s, profile):
    if s["status"] != "valid":
        return '<td class="num neg">&minus;1</td>'
    p = s["profiles"][profile]
    if not p["valid"]:
        return f'<td class="num neg" title="{esc(p["reason"])}">&minus;1*</td>'
    r = p["reward"]
    cls = "pos" if r > 0.0005 else ("neg" if r < -0.0005 else "")
    return f'<td class="num {cls}">{r:+.3f}</td>'


def failed_gates(s):
    gates = [g for g, v in s.get("gates", {}).items() if not v["pass"]]
    return ", ".join(gates)


def cal_table(rows, compact=False):
    head = "".join(f'<th class="num">{p}</th>' for p in PROFILES)
    out = [f'<table><tr><th>patch</th><th>status</th>{head}<th>caught by</th></tr>']
    for slug, title, _purpose, s in rows:
        cls = "" if s["status"] == "valid" else ' class="invalid"'
        tag = f'<span class="tag {s["status"]}">{s["status"]}</span>'
        name = f'<a href="{BASE}/calibration/#{slug}">{title}</a>' if compact else title
        out.append(f"<tr{cls}><td>{name}</td><td>{tag}</td>"
                   + "".join(reward_cell(s, p) for p in PROFILES)
                   + f"<td class=small>{esc(failed_gates(s))}</td></tr>")
    out.append("</table>")
    out.append('<p class="small muted">Rewards on public + held-out routes. '
               '<b>&minus;1*</b>: valid submission, but it breaks that profile\'s budget '
               '(hover for the reason).</p>')
    return "\n".join(out)


def baseline_table(rows):
    base = next((s for slug, *_rest, s in rows if slug == "r0-unchanged"), None)
    if not base:
        return ""
    out = ['<table><tr><th>workload</th><th class="num">frame (ms)</th><th class="num">VI fields</th>'
           '<th class="num">CPU Mcycles</th><th class="num">RDRAM KB</th><th class="num">footprint KiB</th></tr>']
    for wid, d in base["workloads"].items():
        m = d["metrics"]
        out.append(f"<tr><td>{esc(wid)}</td><td class=num>{m['frame_ms']:.1f}</td>"
                   f"<td class=num>{m['vi_fields_per_frame']:.1f}</td><td class=num>{m['cpu_cycles'] / 1e6:.1f}</td>"
                   f"<td class=num>{m['rdram_bytes'] / 1000:.0f}</td><td class=num>{m['footprint_bytes'] / 1024:.0f}</td></tr>")
    out.append("</table>")
    return "\n".join(out)


def posts():
    items = []
    for f in sorted((SITE / "posts").glob("*.html")):
        text = f.read_text()
        meta = json.loads(re.match(r"<!--(.*?)-->", text, re.S).group(1))
        items.append((f.stem, meta, text.split("-->", 1)[1]))
    return sorted(items, key=lambda x: x[1]["date"], reverse=True)


def build_index(out, rows, post_items):
    post_links = "".join(
        f'<li><a href="{BASE}/blog/{slug}/">{esc(m["title"])}</a> <span class=date>{m["date"]}</span><br>'
        f'<span class="small muted">{esc(m["summary"])}</span></li>' for slug, m, _ in post_items)
    body = f"""
<div class="hero"><div>
<h1>Make a Nintendo 64 game cheaper to run. Don't change it.</h1>
<p class="lede">Mario Eval is a reinforcement-learning-with-verifiable-rewards environment. An agent gets the
source of an N64 game, a toolchain, an emulator and a profiler, and has to cut what the game costs on the
original hardware &mdash; CPU time, RSP time, memory traffic or RAM &mdash; while every frame of gameplay,
picture and sound stays the same. The reward comes from measurements, not from a judge.</p>
</div>{PIP_SVG}</div>

<div class="status"><b>Status:</b> the environment, grader and agent container are built and calibrated on
<b>Pip's Garden</b>, an original stand-in game written for this eval (the robot above). Super Mario 64
plugs into the same harness once a legally dumped ROM is supplied; see
<a href="{BASE}/blog/road-to-super-mario-64/">the road to Super Mario 64</a>. No models have been run yet.</div>

<h2>How a submission is graded</h2>
<div class="diagram">{PIPELINE_SVG}</div>
<p>The grader rebuilds the submitted source with a pinned toolchain, then runs it in
<a href="https://ares-emu.net/">ares</a> (CPU interpreter, so the VR4300's instruction and data caches apply to
every instruction) with a small instrumentation patch. Recorded controller inputs are fed per <em>logical</em>
game frame, and the game runs unthrottled, so a faster build plays exactly the same game. Every cost is counted
by the emulator; nothing the ROM says about itself is trusted.</p>

<div class="cards">
<div class="card"><h3>speed</h3><p>CPU time per frame (COUNT ticks), including every cache stall.</p></div>
<div class="card"><h3>rsp</h3><p>Vector-coprocessor busy cycles per frame.</p></div>
<div class="card"><h3>traffic</h3><p>RDRAM bytes moved per frame by every bus device.</p></div>
<div class="card"><h3>memory</h3><p>Distinct RDRAM bytes the game touches after boot.</p></div>
</div>
<p>A task names one profile. Reward = 1 &minus; the geometric mean over workloads of candidate cost / baseline
cost, clipped to [&minus;1, 1]: halving the cost scores 0.5. A submission that fails any gate scores &minus;1 on
every profile, however fast it is. Non-speed profiles also carry a frame-time budget, so RAM can't be bought with
time.</p>

<h3>What must not change</h3>
<ul>
<li><b>Gameplay</b>: the observation record (player, camera, enemies, gems, RNG state, ...) must match the original
<em>bit for bit</em> on all 240 frames of every route.</li>
<li><b>Video</b>: a pixel passes if a pixel within one pixel of it in the original frame is within 2/31 per channel;
a frame fails above 0.2% failing pixels. Sub-pixel edge shifts pass; missing objects don't.</li>
<li><b>Audio</b>: &ge; 40 dB SNR overall, &ge; 20 dB on every non-silent frame.</li>
<li><b>Harness and hardware</b>: the harness files are byte-identical; the game fits a 4 MB console.</li>
</ul>

<h2>Calibration</h2>
<p>Before trusting a grader with RL, it has to rank known patches correctly. These twelve were graded on four public
and four held-out routes; the <a href="{BASE}/calibration/">calibration page</a> has every number.</p>
{cal_table(rows, compact=True)}

<h2>The baseline</h2>
<p>Pip's Garden is correct and written the way many 1990s console games were: built at <code>-O0</code>, with
redundant math, a direct-mapped cache it ignores, and memory it doesn't need. On the modelled N64 it takes:</p>
{baseline_table(rows)}
<p class="small muted">One NTSC video field is 16.7 ms; a game that wants 30 fps has two.</p>

<h2>Writing</h2>
<ul class="post-list">{post_links}</ul>

<h2>Run it</h2>
<pre><code>git clone {REPO} && cd mario-eval
scripts/build-images.sh --no-task          # toolchain, ares + n64run, grader
scripts/precompute.sh                      # baseline reference
scripts/grade.sh path/to/your/game out/    # grade a source tree
scripts/build-images.sh && cd quickstart && docker compose up -d   # agent container</code></pre>
"""
    write(out, "index.html", page("Mario Eval: make an N64 game cheaper to run", body))


def build_calibration(out, rows):
    sections = []
    for slug, title, purpose, s in rows:
        detail = []
        if s["status"] == "valid":
            detail.append('<table><tr><th>workload</th><th class=num>frame time</th><th class=num>RSP</th>'
                          '<th class=num>RDRAM traffic</th><th class=num>footprint</th></tr>')
            for wid, d in s["workloads"].items():
                r = d["ratios"]
                detail.append(f"<tr><td>{esc(wid)}</td>" + "".join(
                    f"<td class=num>{r[k]:.3f}</td>" for k in ("frame_ticks", "rsp_busy", "rdram_bytes", "footprint_bytes"))
                    + "</tr>")
            detail.append("</table><p class='small muted'>Ratios to the baseline (lower is better).</p>")
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
        link = "" if slug == "r0-unchanged" else f' &middot; <a href="{REPO}/blob/main/calibration/{slug}.patch">patch</a>'
        sections.append(f'<h2 id="{slug}">{title} <span class="tag {s["status"]}">{s["status"]}</span></h2>'
                        f'<p class="muted">{purpose}{link}</p>' + "\n".join(detail))
    body = f"""<div class="prose"><h1>Calibration</h1>
<p>Each patch is applied to the baseline source and graded exactly like a submission, on four public and four
held-out routes (240 frames each). The emulator is deterministic, so every difference below is real.</p></div>
{cal_table(rows)}
{''.join(sections)}"""
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
    rows = load_cal()
    post_items = posts()
    build_index(out, rows, post_items)
    build_calibration(out, rows)
    build_blog(out, post_items)
    print(f"wrote {out}: {len(rows)} calibration entries, {len(post_items)} posts")


if __name__ == "__main__":
    main()
