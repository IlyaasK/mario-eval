#!/usr/bin/env bash
# Supervise a timed 24h agent run in the task container (run on the host, after
# `docker compose up -d` in quickstart/).
#
#   - writes the optimization profile to /task/PROFILE;
#   - runs $AGENT_CMD in the container (as `agent`, cwd /task/game) with TASK.md
#     as the prompt, re-invoking it with a short "continue" prompt whenever it
#     exits early or its log has been silent for --stall-minutes;
#   - pauses the active-work timer cleanly on 5h/rolling quota exhaustion
#     (RESOURCE_EXHAUSTED / 429 / "Resets in XhYmZs" / retry-after-ms) and resumes
#     automatically once quota returns, shifting DEADLINE/NEXT_COMMIT/NEXT_GRADE;
#   - commits /task/game every --commit-every minutes onto refs/mev/checkpoints;
#   - every --grade-every hours and at the end, copies /task/game out and
#     grades it on the host: public routes, plus held-out routes when
#     --heldout DIR is given (the agent never sees those);
#   - saves the game's git history as results/<run>/game.bundle.
#
# Usage:
#   AGENT_CMD='claude -p --dangerously-skip-permissions' quickstart/run-agent.sh --hours 24 --profile console
#   quickstart/run-agent.sh --hours 0.1 --commit-every 2 --grade-every 0.05   # smoke test
#
# Options: --hours H (default 24)  --name RUN
#          --profile console|stutter|speed|rdp|rsp|traffic|memory (default console)
#          --commit-every MIN (30)  --grade-every H (2)  --stall-minutes MIN (30)
#          --heldout DIR (held-out replays; host reference must include them)
# AGENT_CMD may also be set in quickstart/.env.
set -euo pipefail

# Wrap entire supervisor in main() so bash parses the complete file into memory
# at startup; editing run-agent.sh on disk can never corrupt a live 24h run.
main() {
cd "$(dirname "$0")/.."
REPO="$PWD"
QS="$REPO/quickstart"

HOURS=24; GAME="sm64"; RUN=""; PROFILE=console; COMMIT_MIN=30; GRADE_HOURS=2; STALL_MIN=30; HELDOUT=""; RESUME=0
while [ $# -gt 0 ]; do
  case "$1" in
    --hours) HOURS="$2"; shift 2 ;;
    --game)
      [ "${2:-}" = "sm64" ] || { echo "bad --game ${2:-} (mario-eval v4 is sm64 only)" >&2; exit 2; }
      shift 2
      ;;
    --name) RUN="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --commit-every) COMMIT_MIN="$2"; shift 2 ;;
    --grade-every) GRADE_HOURS="$2"; shift 2 ;;
    --stall-minutes) STALL_MIN="$2"; shift 2 ;;
    --heldout) HELDOUT="$(realpath "$2")"; shift 2 ;;
    --resume) RESUME=1; shift ;;
    -h|--help) sed -n '2,28p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$PROFILE" in console|stutter|speed|rdp|rsp|traffic|memory) ;; *) echo "bad --profile $PROFILE (expected console|stutter|speed|rdp|rsp|traffic|memory)" >&2; exit 2 ;; esac
CORPUS="sm64/corpus"
CACHE="cache/sm64-reference"
if [ -z "${AGENT_CMD:-}" ] && [ -f "$QS/.env" ]; then
  AGENT_CMD="$(sed -n 's/^AGENT_CMD=//p' "$QS/.env" | tail -n 1)"
fi
[ -n "${AGENT_CMD:-}" ] || { echo "error: set AGENT_CMD" >&2; exit 2; }

secs() { awk -v x="$1" -v m="$2" 'BEGIN { v = x * m; if (v < 1) v = 1; printf "%d", v }'; }
TOTAL_S=$(secs "$HOURS" 3600); COMMIT_S=$(secs "$COMMIT_MIN" 60)
GRADE_S=$(secs "$GRADE_HOURS" 3600); STALL_S=$(( STALL_MIN * 60 ))
QUOTA_BUFFER_S="${MEV_QUOTA_BUFFER_S:-60}"
QUOTA_DEFAULT_WAIT_S="${MEV_QUOTA_DEFAULT_WAIT_S:-300}"

RUN="${RUN:-run-${GAME}-${PROFILE}-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="$REPO/results/$RUN"
if [ "$RESUME" -eq 0 ] && [ -e "$RUN_DIR" ]; then
  echo "error: $RUN_DIR exists (pass --resume to continue an existing run)" >&2
  exit 1
fi
mkdir -p "$RUN_DIR"
LOG="$RUN_DIR/run.log"

dc() { docker compose --project-directory "$QS" "$@"; }
in_task() { dc exec -T task "$@"; }
log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG" >&2; }
now() { date +%s; }

dc ps --services --filter status=running | grep -qx task || { echo "error: task container not running" >&2; exit 1; }

in_task bash -c "echo $PROFILE > /task/PROFILE"
if [ -n "${MEV_INITIAL_PROMPT:-}" ]; then
  PROMPT="$MEV_INITIAL_PROMPT"
else
  PROMPT="$(in_task cat /task/TASK.md)"$'\n\n'"Your primary profile for this run: $PROFILE (also in /task/PROFILE). You have ${HOURS} hours."
fi

format_remaining() {
  local rem=$(( DEADLINE - $(now) ))
  [ "$rem" -lt 0 ] && rem=0
  local mins=$(( (rem + 59) / 60 ))
  local h=$(( mins / 60 )) m=$(( mins % 60 ))
  if [ "$h" -gt 0 ]; then printf '%dh %02dm' "$h" "$m"; else printf '%dm' "$m"; fi
}

is_head_cleanly_verified() {
  in_task python3 - "$START" <<'PY' 2>/dev/null || return 1
import json, pathlib, subprocess, sys
t0 = float(sys.argv[1])
dirty = subprocess.run(["git", "-C", "/task/game", "status", "--porcelain"], capture_output=True, text=True).stdout.strip()
if dirty:
    sys.exit(1)
head = subprocess.run(["git", "-C", "/task/game", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
p = pathlib.Path("/task/.mev-history.jsonl")
if not head or not p.is_file():
    sys.exit(1)
for line in reversed(p.read_text().splitlines()):
    if not line.strip():
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    if d.get("ts", 0) < t0 - 60:
        continue
    if not d.get("fast") and not d.get("git_dirty") and d.get("git_head") and head.startswith(d["git_head"]):
        ok = (d.get("status") == "valid") and bool(d.get("profile_valid", True))
        sys.exit(0 if ok else 1)
sys.exit(1)
PY
}

continue_prompt() {
  local rem_s rem head_info dirty_count last_commit_age check_diag nudge=""
  rem_s=$(( DEADLINE - $(now) ))
  [ "$rem_s" -lt 0 ] && rem_s=0
  rem="$(format_remaining)"
  head_info="$(in_task git -C /task/game log -1 --format='%h (%ar) %s' 2>/dev/null || echo 'unknown')"
  dirty_count="$(in_task bash -c 'git -C /task/game status --porcelain 2>/dev/null | wc -l' 2>/dev/null | tr -d ' ' || echo 0)"
  last_commit_age="$(in_task bash -c 't=$(git -C /task/game log -1 --format=%ct 2>/dev/null || echo 0); echo $(( ($(date +%s) - t) / 60 ))' 2>/dev/null | tr -d ' ' || echo 0)"
  check_diag="$(in_task python3 - "$PROFILE" "$START" <<'PY' 2>/dev/null || true
import json, pathlib, subprocess, sys
profile, t0 = sys.argv[1], float(sys.argv[2])
head = subprocess.run(["git", "-C", "/task/game", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
p = pathlib.Path("/task/.mev-history.jsonl")
if p.is_file():
    recs = []
    for l in p.read_text().splitlines():
        if not l.strip():
            continue
        try:
            d = json.loads(l)
            if d.get("ts", t0) >= t0 - 60:
                recs.append(d)
        except Exception:
            pass
    if recs:
        d = recs[-1]
        sp = d.get("speedups", {}).get(profile, 0)
        vo = d.get("vs_o2_speedups", {}).get(profile, 0)
        st = d.get("status")
        gh = d.get("git_head") or "?"
        tag = " [fast]" if d.get("fast") else ""
        dirty_tag = " [dirty]" if d.get("git_dirty") else ""
        msg = f"status={st}{tag}{dirty_tag} speedup={sp}x vs_o2={vo}x ({gh})"
        fulls = [r for r in recs if not r.get("fast")]
        if d.get("fast") and d.get("status") == "valid" and (not fulls or fulls[-1].get("status") != "valid"):
            msg += " [WARNING: latest plain 'mev check' has NOT passed — run plain 'mev check' to verify clean + PLAY=1 build!]"
        if head and gh != "?" and not head.startswith(gh):
            ahead = subprocess.run(["git", "-C", "/task/game", "rev-list", "--count", f"{gh}..HEAD"], capture_output=True, text=True)
            if ahead.returncode == 0 and ahead.stdout.strip().isdigit() and int(ahead.stdout.strip()) > 0:
                msg += f" [WARNING: HEAD is {ahead.stdout.strip()} commit(s) ahead of last completed check {gh} — run 'mev check' now!]"
        print(msg)
PY
)"
  if [ "$rem_s" -le 900 ]; then
    printf 'Endgame wrap-up (%s remaining on %sh task in /task/TASK.md, profile: %s). Current HEAD: %s (dirty files: %s). Last check: %s. Do NOT start risky new multi-file refactors with %s left: ensure your best working tree in /task/game is clean, committed, and passes plain `mev check` (including PLAY=1 boot smoke), update /task/OPTIMIZATION_LOG.md briefly, and wait for `mev check` to finish.' \
      "$rem" "$HOURS" "$PROFILE" "$head_info" "$dirty_count" "${check_diag:-none yet}" "$rem"
    return
  fi
  if [ "${last_commit_age:-0}" -ge 90 ]; then
    nudge=" You have not landed a new commit in ${last_commit_age}m — avoid prolonged analysis without testing: pick a concrete bottleneck from 'mev profile', edit, verify with 'mev check <course> --fast', and commit or revert in small verified increments."
  fi
  printf 'Continue working on the %sh optimization task in /task/TASK.md (profile: %s; time remaining: %s). Do NOT declare the task complete or end your turn after merely checking git status or running mev check — you still have %s remaining to push the score higher. Current HEAD: %s (dirty files: %s). Last check: %s.%s Consult /task/OPTIMIZATION_LOG.md first so you never repeat tested ideas, verify assumptions directly in Makefile/source rather than trusting stale notes, pick an unexploited bottleneck from `mev profile` or `mev run --all` (compiler/flags, microcode, CPU, cache, RSP, RDP, or memory layout), test multiple concrete hypotheses in the foreground, commit verified wins in /task/game, and always wait for mev check to finish before ending your turn.' \
    "$HOURS" "$PROFILE" "$rem" "$rem" "$head_info" "$dirty_count" "${check_diag:-none yet}" "$nudge"
}

write_manifest() {
  local currently_paused="${1:-0}" resume_epoch="${2:-0}"
  python3 - "$RUN_DIR/run_manifest.json" "$RUN" "$GAME" "$PROFILE" "$HOURS" "$START" "$DEADLINE" "$AGENT_CMD" "${HELDOUT:+1}" "$REPO" "$PAUSED_S" "$QUOTA_PAUSES" "$currently_paused" "$resume_epoch" <<'PY' || true
import json, os, pathlib, subprocess, sys
(out, run, game, profile, hours, start, deadline, agent_cmd, has_heldout, repo,
 paused_s, quota_pauses, cur_paused, resume_epoch) = sys.argv[1:15]
def git_rev(path):
    try:
        return subprocess.check_output(["git", "-C", path, "rev-parse", "HEAD"], stderr=subprocess.DEVNULL, text=True).strip()
    except Exception:
        return None
manifest = {
    "benchmark": "mario-eval",
    "benchmark_git_commit": git_rev(repo),
    "run": run,
    "game": game,
    "primary_profile": profile,
    "hours": float(hours),
    "start_epoch": int(start),
    "deadline_epoch": int(deadline),
    "paused_seconds": int(paused_s),
    "quota_pauses": int(quota_pauses),
    "currently_paused": bool(int(cur_paused)),
    **({"resume_epoch": int(resume_epoch)} if int(cur_paused) and int(resume_epoch) > 0 else {}),
    "agent_cmd": agent_cmd,
    "compose_project": os.environ.get("COMPOSE_PROJECT_NAME", ""),
    "heldout_enabled": bool(has_heldout),
}
p = pathlib.Path(out)
tmp = p.with_suffix(".json.tmp")
tmp.write_text(json.dumps(manifest, indent=2) + "\n")
os.replace(tmp, p)
PY
}

# Snapshot /task/game onto refs/mev/checkpoints using a temporary index so we
# preserve full 30-minute history in game.bundle without ever mutating the
# agent's HEAD, main branch, staging index, or git diff.
commit() {
  in_task bash -c '
    cd /task/game || exit 0
    idx=$(mktemp /tmp/mev-idx.XXXXXX)
    rm -f "$idx"
    trap "rm -f \"$idx\"" EXIT
    parent=$(git rev-parse --verify refs/mev/checkpoints 2>/dev/null || git rev-parse HEAD 2>/dev/null || true)
    [ -n "$parent" ] || exit 0
    GIT_INDEX_FILE="$idx" git read-tree HEAD 2>/dev/null || exit 0
    GIT_INDEX_FILE="$idx" git add -A 2>/dev/null || exit 0
    tree=$(GIT_INDEX_FILE="$idx" git write-tree 2>/dev/null) || exit 0
    parent_tree=$(git rev-parse "${parent}^{tree}" 2>/dev/null || true)
    [ "$tree" = "$parent_tree" ] && exit 0
    c=$(git -c user.name=agent -c user.email=agent@mario-eval commit-tree "$tree" -p "$parent" -m "checkpoint $(date -u +%FT%TZ)" 2>/dev/null) || exit 0
    git update-ref refs/mev/checkpoints "$c" 2>/dev/null || true
  ' || true
}

save_artifacts_fast() {
  dc cp task:/task/.mev-history.jsonl "$RUN_DIR/mev-history.jsonl" >/dev/null 2>&1 || true
  in_task bash -c 'cd /task/game && git bundle create /tmp/game.bundle --all' >/dev/null 2>&1 \
    && dc cp task:/tmp/game.bundle "$RUN_DIR/game.bundle" >/dev/null 2>&1 || true
  in_task bash -c '
    rm -rf /tmp/mev-agy-transcripts
    found=0
    for f in /home/agent/.gemini/antigravity-cli/brain/*/.system_generated/logs/transcript.jsonl; do
      [ -f "$f" ] || continue
      mkdir -p /tmp/mev-agy-transcripts
      cid=$(basename "$(dirname "$(dirname "$(dirname "$f")")")")
      cp -f "$f" "/tmp/mev-agy-transcripts/${cid}.transcript.jsonl" && found=1 || true
    done
    [ "$found" = 1 ]
  ' >/dev/null 2>&1 \
    && mkdir -p "$RUN_DIR/agy-transcripts" \
    && dc cp task:/tmp/mev-agy-transcripts/. "$RUN_DIR/agy-transcripts/" >/dev/null 2>&1 || true
}

extract_commit_tree() {
  local sha="$1" _unused_ref="$2" dst="$3"
  rm -rf "$dst"
  mkdir -p "$dst"
  in_task git -C /task/game archive "$sha" 2>/dev/null | tar -x -C "$dst" 2>/dev/null || return 1
  if in_task test -f /opt/mario-eval/sm64-assets.tar.gz 2>/dev/null; then
    in_task cat /opt/mario-eval/sm64-assets.tar.gz 2>/dev/null | tar -xz --skip-old-files -C "$dst" 2>/dev/null || true
  fi
}

rebuild_trajectory_json() {
  local commits_total="${1:-0}" trailing_unverified="${2:-0}"
  python3 - "$RUN_DIR" "$START" "$GAME" "$PROFILE" "$PAUSED_S" "$commits_total" "$trailing_unverified" "$REPO" <<'PY' || true
import json, os, pathlib, sys

run_dir = pathlib.Path(sys.argv[1])
t0 = float(sys.argv[2])
game = sys.argv[3]
profile = sys.argv[4]
total_paused = float(sys.argv[5])
commits_total = int(sys.argv[6])
trailing_unverified = int(sys.argv[7])
repo_dir = pathlib.Path(sys.argv[8])

existing = {}
tp = run_dir / "trajectory.json"
if tp.is_file():
    try:
        existing = json.loads(tp.read_text())
    except Exception:
        existing = {}

# Compute exact paused seconds before timestamp `ts` from quota-pauses.jsonl
# (with checkpoint snapshot-epoch fallback for older runs).
pause_intervals = []
qp_file = run_dir / "quota-pauses.jsonl"
if qp_file.is_file():
    for line in qp_file.read_text().splitlines():
        if line.strip():
            try:
                iv = json.loads(line)
                pause_intervals.append((float(iv["start"]), float(iv["end"])))
            except Exception:
                pass

pause_pts = [(t0, 0.0)]
for p in sorted(run_dir.glob("checkpoint-*/snapshot-epoch")) + sorted(run_dir.glob("final/snapshot-epoch")):
    try:
        ts_p = float(p.read_text().strip())
        ps_f = p.parent / "paused-seconds"
        ps_v = float(ps_f.read_text().strip()) if ps_f.is_file() else 0.0
        pause_pts.append((ts_p, ps_v))
    except Exception:
        pass
pause_pts.sort()

def paused_at(ts):
    if pause_intervals:
        acc = 0.0
        for s_ep, e_ep in pause_intervals:
            if ts > s_ep:
                acc += max(0.0, min(ts, e_ep) - s_ep)
        return acc
    best_p = 0.0
    for pts, pval in pause_pts:
        if pts <= ts:
            best_p = pval
        else:
            break
    return best_p

checks = []
prior_segment_checks = 0
hist = run_dir / "mev-history.jsonl"
if hist.exists():
    for line in hist.read_text().splitlines():
        if line.strip():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = float(d.get("ts", t0))
            if ts < t0 - 60.0:
                prior_segment_checks += 1
                continue
            d["elapsed_hours"] = round(max(0.0, (ts - t0 - paused_at(ts)) / 3600.0), 4)
            checks.append(d)


def summarize_grade(s):
    secs = (s.get("profiles", {}).get(profile) or {}).get("sections")
    return {
        "status": s.get("status"),
        **({"reason": s["reason"]} if s.get("reason") else {}),
        **({"toolchain": s["toolchain"]} if s.get("toolchain") else {}),
        "rewards": s.get("rewards", {}),
        "speedups": s.get("speedups", {}),
        "cost_saved": s.get("cost_saved", {}),
        "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in s.get("profiles", {}).items()},
        **({"sections": secs} if secs else {}),
        **({"fidelity": s["fidelity"]} if s.get("fidelity") else {}),
        **({"capability_ruler": s["capability_ruler"]} if s.get("capability_ruler") else {}),
        **({"failure_attribution": s["failure_attribution"]} if s.get("failure_attribution") else {}),
        **({"diagnostics": s["diagnostics"]} if s.get("diagnostics") else {}),
    }


checkpoints = []
for p in sorted(run_dir.glob("checkpoint-*/grade/summary.json")) + sorted(run_dir.glob("final/grade/summary.json")):
    cp_dir = p.parent.parent
    name = cp_dir.name
    s = json.loads(p.read_text())
    captured = int((cp_dir / "snapshot-epoch").read_text())
    cp_paused = float((cp_dir / "paused-seconds").read_text()) if (cp_dir / "paused-seconds").is_file() else 0.0
    cp_head = (cp_dir / "git-head").read_text().strip() if (cp_dir / "git-head").is_file() else None
    entry = {
        "name": name,
        "elapsed_hours": round(max(0.0, (captured - t0 - cp_paused) / 3600.0), 4),
        "wall_hours": round(max(0.0, (captured - t0) / 3600.0), 4),
        "paused_seconds": int(cp_paused),
        **({"git_head": cp_head} if cp_head else {}),
        "workload_set": s.get("workload_set"),
        "version": s.get("version"),
        **summarize_grade(s),
    }
    lv_sum = cp_dir / "last-valid-grade" / "summary.json"
    lv_sha = cp_dir / "last-valid-commit"
    if lv_sum.exists():
        ls = json.loads(lv_sum.read_text())
        entry["last_valid"] = {
            "git_head": lv_sha.read_text().strip() if lv_sha.exists() else None,
            **summarize_grade(ls),
        }
    checkpoints.append(entry)

best_valid = None
best_valid_summary = None
def _cp_prof_valid(g_obj):
    return (
        isinstance(g_obj, dict)
        and g_obj.get("status") == "valid"
        and float((g_obj.get("speedups") or {}).get(profile) or 0.0) > 0.0
    )

for cp in checkpoints:
    cands = []
    if _cp_prof_valid(cp):
        cands.append((cp.get("speedups", {}).get(profile, 0.0), {
            "name": cp["name"], "source": "working_tree", "git_head": cp.get("git_head"),
            "elapsed_hours": cp["elapsed_hours"],
            "speedup": cp.get("speedups", {}).get(profile),
            "cost_saved": cp.get("cost_saved", {}).get(profile),
            "vs_o2_speedup": cp.get("vs_o2_speedups", {}).get(profile),
            "reward": cp.get("rewards", {}).get(profile),
        }, cp))
    lv = cp.get("last_valid")
    if _cp_prof_valid(lv):
        cands.append((lv.get("speedups", {}).get(profile, 0.0), {
            "name": cp["name"], "source": "last_valid", "git_head": lv.get("git_head"),
            "elapsed_hours": cp["elapsed_hours"],
            "speedup": lv.get("speedups", {}).get(profile),
            "cost_saved": lv.get("cost_saved", {}).get(profile),
            "vs_o2_speedup": lv.get("vs_o2_speedups", {}).get(profile),
            "reward": lv.get("rewards", {}).get(profile),
        }, lv))
    for sp, rec, src_sum in cands:
        if sp and (best_valid is None or sp > best_valid["speedup"]):
            best_valid = rec
            best_valid_summary = src_sum

bisect_rec = existing.get("bisect_last_valid")
if isinstance(bisect_rec, dict) and bisect_rec.get("status") == "valid" and float(bisect_rec.get("speedup") or 0.0) > 0.0:
    bsp = bisect_rec.get("speedup") or 0.0
    if bsp and (best_valid is None or bsp > (best_valid.get("speedup") or 0.0)):
        best_valid = {
            "name": bisect_rec["name"],
            "source": bisect_rec.get("source", "bisect_last_valid"),
            "git_head": bisect_rec.get("git_head"),
            "elapsed_hours": bisect_rec.get("elapsed_hours"),
            "speedup": bsp,
            "cost_saved": bisect_rec.get("cost_saved"),
            "vs_o2_speedup": bisect_rec.get("vs_o2_speedup"),
            "reward": bisect_rec.get("reward"),
        }
        best_valid_summary = bisect_rec

final_cp = next((c for c in checkpoints if c["name"] == "final"), None)
peak_sp = float((best_valid or {}).get("speedup") or 0.0)
peak_vo2 = (best_valid or {}).get("vs_o2_speedup")
peak_cs = (best_valid or {}).get("cost_saved")
peak_hr = (best_valid or {}).get("elapsed_hours")
gen_ratio = ((best_valid_summary or {}).get("fidelity") or {}).get("generalization_ratio")
peak_valid_pub_sp = ((((best_valid_summary or {}).get("capability_ruler") or {}).get("splits") or {}).get("public") or {}).get("raw_console_speedup")

human_expert_progress = None
if game == "sm64" and peak_cs:
    for kaze_p in (
        repo_dir / "results" / "sm64-trial-calibration" / "r10-kaze-master" / "summary.json",
        repo_dir / "results" / "sm64-calibration" / "r10-kaze-master" / "summary.json",
    ):
        if kaze_p.is_file():
            try:
                kaze_cs = float((json.loads(kaze_p.read_text()).get("cost_saved") or {}).get(profile) or 0.0)
                if kaze_cs > 0.0:
                    human_expert_progress = round(float(peak_cs) / kaze_cs, 4)
                    break
            except Exception:
                pass

final_wt_valid = (final_cp.get("status") == "valid") if final_cp else None
final_wt_sp = float(final_cp.get("speedups", {}).get(profile) or 0.0) if (final_cp and final_wt_valid) else 0.0
retention = round(final_wt_sp / peak_sp, 4) if (final_cp is not None and peak_sp > 0.0) else None

first_valid_hr = None
first_beat_o2_hr = None
fail_counts = {}
valid_cp_count = 0
for cp in checkpoints:
    if cp.get("status") == "valid":
        valid_cp_count += 1
        if first_valid_hr is None:
            first_valid_hr = cp["elapsed_hours"]
        vo2 = cp.get("vs_o2_speedups", {}).get(profile)
        if first_beat_o2_hr is None and vo2 and float(vo2) > 1.01:
            first_beat_o2_hr = cp["elapsed_hours"]
    else:
        cat = (cp.get("failure_attribution") or {}).get("primary_category") or "invalid"
        fail_counts[cat] = fail_counts.get(cat, 0) + 1
        lv = cp.get("last_valid")
        if isinstance(lv, dict) and lv.get("status") == "valid":
            if first_valid_hr is None:
                first_valid_hr = cp["elapsed_hours"]
            vo2 = lv.get("vs_o2_speedups", {}).get(profile)
            if first_beat_o2_hr is None and vo2 and float(vo2) > 1.01:
                first_beat_o2_hr = cp["elapsed_hours"]

full_checks = [c for c in checks if not c.get("fast")]
valid_checks = [c for c in checks if c.get("status") == "valid"]
full_valid_checks = [c for c in valid_checks if not c.get("fast")]
clean_full_valid_checks = [c for c in full_valid_checks if not c.get("git_dirty")]
unique_heads = {c.get("git_head") for c in checks if c.get("git_head")}
unique_roms = {c.get("rom_sha256") for c in checks if c.get("rom_sha256")}
max_pub_sp = max([float(c.get("speedups", {}).get(profile) or 0.0) for c in (full_valid_checks or valid_checks)], default=0.0)

# Compare container 6-course `mev check` speedup against host clean-rebuild 6-course
# public speedup (avoiding 2-course `--fast`, 6-vs-25-route, or peak_sp=0 distortion).
# Note: agents commonly run `mev check` before `git commit` (so git_dirty=True and
# git_head points at the parent commit); when no clean-tree commit SHA matches directly,
# compare max full 6-course container check speedup against max host 6-course public speedup.
def extract_host_pub_sp(g_obj):
    if not isinstance(g_obj, dict):
        return 0.0
    if g_obj.get("status") == "valid":
        sp = (((g_obj.get("capability_ruler") or {}).get("splits") or {}).get("public") or {}).get("raw_console_speedup")
        if sp:
            return float(sp)
        sp = ((g_obj.get("sections") or {}).get("public") or {}).get("speedup")
        if sp:
            return float(sp)
        return float((g_obj.get("speedups") or {}).get(profile) or 0.0)
    return float(((g_obj.get("diagnostics") or {}).get("unverified_public_speedups") or {}).get(profile) or 0.0)

host_grades = []
for cp in checkpoints:
    host_grades.append((cp.get("git_head") or "", extract_host_pub_sp(cp), (cp.get("failure_attribution") or {}).get("primary_category")))
    lv = cp.get("last_valid")
    if isinstance(lv, dict):
        host_grades.append((lv.get("git_head") or "", extract_host_pub_sp(lv), (lv.get("failure_attribution") or {}).get("primary_category")))

matched_repro_gaps = []
for c in clean_full_valid_checks:
    ch = c.get("git_head") or ""
    c_sp = float((c.get("speedups") or {}).get(profile) or 0.0)
    if not ch or c_sp <= 0.0:
        continue
    for gh, h_pub, p_cat in host_grades:
        if gh and (gh.startswith(ch) or ch.startswith(gh)):
            if h_pub > 0.0:
                matched_repro_gaps.append(max(0.0, c_sp - h_pub))
            elif p_cat == "build_failure":
                matched_repro_gaps.append(max(0.0, c_sp - 1.0))

if matched_repro_gaps:
    repro_gap = round(max(matched_repro_gaps), 6)
elif full_valid_checks and host_grades:
    max_full_pub = max([float((c.get("speedups") or {}).get(profile) or 0.0) for c in full_valid_checks], default=0.0)
    max_host_pub = max([h_pub for _, h_pub, _ in host_grades], default=0.0)
    base_host_pub = max_host_pub if max_host_pub > 0.0 else 1.0
    repro_gap = round(max(0.0, max_full_pub - base_host_pub), 6)
else:
    repro_gap = None

agent_logs = sorted(run_dir.glob("agent-*.log"))
agy_transcripts = sorted((run_dir / "agy-transcripts").glob("*.transcript.jsonl")) if (run_dir / "agy-transcripts").is_dir() else []
mev_profile_hits = 0
mev_stress_hits = 0
opt_log_hits = 0
if agy_transcripts:
    for tp_f in agy_transcripts:
        try:
            for line in tp_f.read_text(errors="ignore").splitlines():
                if not line.strip():
                    continue
                rec = json.loads(line)
                if rec.get("type") != "PLANNER_RESPONSE":
                    continue
                for tc in rec.get("tool_calls") or []:
                    arg_blob = json.dumps(tc.get("args") or {})
                    mev_profile_hits += arg_blob.count("mev profile")
                    mev_stress_hits += arg_blob.count("mev stress")
                    opt_log_hits += arg_blob.count("OPTIMIZATION_LOG")
        except Exception:
            pass
else:
    for lp in agent_logs:
        try:
            txt = lp.read_text(errors="ignore")
            mev_profile_hits += txt.count("mev profile")
            mev_stress_hits += txt.count("mev stress")
            opt_log_hits += txt.count("OPTIMIZATION_LOG")
        except Exception:
            pass

final_diag = (final_cp or {}).get("diagnostics") or {}
final_fa = (final_cp or {}).get("failure_attribution")
pub_only_cps = [
    c for c in checkpoints
    if c.get("status") != "valid"
    and (c.get("diagnostics") or {}).get("public_valid") is True
    and (c.get("diagnostics") or {}).get("heldout_valid") is False
]
unv_pub_candidates = [
    float(((c.get("diagnostics") or {}).get("unverified_public_speedups") or {}).get(profile) or 0.0)
    for c in pub_only_cps
]
for c in checkpoints:
    lv = c.get("last_valid")
    if (
        isinstance(lv, dict)
        and lv.get("status") != "valid"
        and (lv.get("diagnostics") or {}).get("public_valid") is True
        and (lv.get("diagnostics") or {}).get("heldout_valid") is False
    ):
        unv_pub_candidates.append(
            float(((lv.get("diagnostics") or {}).get("unverified_public_speedups") or {}).get(profile) or 0.0)
        )
max_unv_pub = max(unv_pub_candidates, default=0.0)
baseline_valid_sp = peak_sp if peak_sp > 0.0 else 1.0
pub_overfit_gap = round(max(0.0, max_unv_pub - baseline_valid_sp), 6) if max_unv_pub > 0.0 else 0.0

observed_modes = []
post_peak_cats = []
post_peak_subs = []
post_peak_primary = None
for cp in checkpoints:
    if cp.get("status") == "valid":
        continue
    fa = cp.get("failure_attribution") or {}
    cats = fa.get("categories") or ([fa["primary_category"]] if fa.get("primary_category") else [])
    subs = fa.get("subcategories") or []
    for m in list(cats) + list(subs):
        if m and m not in observed_modes:
            observed_modes.append(m)
    if peak_hr is None or cp["elapsed_hours"] >= peak_hr:
        if post_peak_primary is None and fa.get("primary_category"):
            post_peak_primary = fa["primary_category"]
        for c_m in cats:
            if c_m and c_m not in post_peak_cats:
                post_peak_cats.append(c_m)
        for s_m in subs:
            if s_m and s_m not in post_peak_subs:
                post_peak_subs.append(s_m)

post_peak_fa = (
    {"primary_category": post_peak_primary, "categories": post_peak_cats, "subcategories": post_peak_subs}
    if post_peak_primary else None
)

run_analytics = {
    "commits_count": max(commits_total, int((bisect_rec or {}).get("commits_total") or 0)),
    "trailing_unverified_commits": trailing_unverified,
    "agent_trace_summary": {
        "invocations": len(agent_logs),
        **({"agy_transcripts": len(agy_transcripts)} if agy_transcripts else {}),
        "quota_pauses": len(pause_intervals),
        "mev_profile_mentions": mev_profile_hits,
        "mev_stress_mentions": mev_stress_hits,
        "optimization_log_mentions": opt_log_hits,
    },
    "public_mev_checks_total": len(checks),
    "public_mev_checks_full": len(full_checks),
    "unique_commits_checked": len(unique_heads),
    "unique_roms_checked": len(unique_roms),
    **({"prior_segment_checks_ignored": prior_segment_checks} if prior_segment_checks else {}),
    "public_mev_checks_valid_rate": round(len(valid_checks) / float(len(checks)), 4) if checks else None,
    "max_public_check_speedup": max_pub_sp if max_pub_sp > 0.0 else None,
    "build_reproducibility_gap": repro_gap,
    "host_checkpoints_total": len(checkpoints),
    "host_checkpoints_valid": valid_cp_count,
    "host_checkpoints_valid_rate": round(valid_cp_count / float(len(checkpoints)), 4) if checkpoints else None,
    "checkpoint_failure_counts": fail_counts,
    "peak_valid_speedup": peak_sp if peak_sp > 0 else None,
    "peak_valid_vs_o2_speedup": peak_vo2,
    "peak_valid_cost_saved": peak_cs,
    **({"peak_valid_public_speedup": peak_valid_pub_sp} if peak_valid_pub_sp is not None else {}),
    **({"human_expert_progress": human_expert_progress} if human_expert_progress is not None else {}),
    **({"generalization_ratio": gen_ratio} if gen_ratio is not None else {}),
    "active_hours_to_first_valid": first_valid_hr,
    "active_hours_to_beat_o2": first_beat_o2_hr,
    "active_hours_at_peak": peak_hr,
    "final_working_tree_valid": final_wt_valid,
    "final_working_tree_speedup": final_wt_sp if final_cp is not None else None,
    "retention_ratio": retention,
    "late_regression_rescued": bool(final_cp is not None and not final_wt_valid and peak_sp > 1.0),
    "public_only_overfit_checkpoints": len(pub_only_cps),
    **({"max_unverified_public_speedup": round(max_unv_pub, 6)} if max_unv_pub > 0.0 else {}),
    "public_overfit_gap": pub_overfit_gap,
    **({"final_routes_passed": final_diag.get("workloads_passed"), "final_routes_total": final_diag.get("workloads_total")}
       if final_cp is not None and final_diag.get("workloads_total") else {}),
    **({"final_sections": final_diag["sections"]} if final_cp is not None and final_diag.get("sections") else {}),
    **({"final_failure_category": final_fa.get("primary_category"), "final_failure_attribution": final_fa}
       if (final_cp is not None and not final_wt_valid and final_fa) else {}),
    **({"post_peak_failure_attribution": post_peak_fa} if post_peak_fa else {}),
    **({"observed_failure_modes": observed_modes} if observed_modes else {}),
}

out_obj = {
    "version": "4.2",
    "run": run_dir.name,
    "game": game,
    "primary_profile": profile,
    "paused_seconds": int(total_paused),
    "best_valid_checkpoint": best_valid,
    **({"bisect_last_valid": bisect_rec} if bisect_rec else {}),
    "run_analytics": run_analytics,
    "mev_checks": checks,
    "host_checkpoints": checkpoints,
}
tmp = tp.with_suffix(".json.tmp")
tmp.write_text(json.dumps(out_obj, indent=1) + "\n")
os.replace(tmp, tp)
PY
}

grade_checkpoint() {
  local name="$1" dir="$RUN_DIR/$1"
  local grade_t0; grade_t0=$(now)
  mkdir -p "$dir"
  commit
  local wt_dirty=""
  wt_dirty="$(in_task git -C /task/game status --porcelain 2>/dev/null || true)"
  rm -rf "$dir/src"
  dc cp task:/task/game "$dir/src" >/dev/null
  rm -rf "$dir/src/.git" "$dir/src/build" "$dir/src/build_"*
  local snap_now; snap_now=$(now)
  printf '%s\n' "$snap_now" > "$dir/snapshot-epoch"
  printf '%s\n' "$PAUSED_S" > "$dir/paused-seconds"
  local cur_head
  cur_head="$(in_task git -C /task/game rev-parse HEAD 2>/dev/null || true)"
  [ -n "$cur_head" ] && printf '%s\n' "$cur_head" > "$dir/git-head"
  local args=() pub_args=()
  if [ -n "$HELDOUT" ]; then args=(--heldout "$HELDOUT"); fi
  if [ "$GAME" = "sm64" ]; then
    args+=(--play-smoke)
    pub_args+=(--play-smoke)
  fi
  "$REPO/scripts/grade.sh" --game "$GAME" "$dir/src" "$dir/grade" "${args[@]}" \
    > "$dir/grade.txt" 2>&1 || true
  save_artifacts_fast

  # Cache clean working-tree grades by full commit SHA so fallback searches
  # across checkpoints never re-compile or re-emulate an already graded commit.
  if [ -z "$wt_dirty" ] && [ -n "$cur_head" ] && [ -f "$dir/grade/summary.json" ]; then
    local head_cache="$RUN_DIR/.graded-commits/$cur_head"
    if [ ! -f "$head_cache/grade/summary.json" ]; then
      mkdir -p "$head_cache"
      cp -rf "$dir/grade" "$head_cache/grade"
      cp -f "$dir/grade.txt" "$head_cache/grade.txt" 2>/dev/null || true
    fi
  fi

  # Zero-oracle fallback rescue: ONLY when the working tree itself failed PUBLIC
  # verification (e.g. snapshot landed mid-edit with a broken build, PLAY=1 failure,
  # or public gate/budget failure — NEVER merely because a public-valid tree failed
  # private held-outs!), select at most ONE rescue commit using strictly public
  # 6-course + PLAY=1 grading, and evaluate held-out routes ONCE on that commit.
  local wt_pub_valid last_valid_commit=""
  wt_pub_valid=$(python3 - "$dir/grade/summary.json" "$PROFILE" <<'PY' 2>/dev/null || echo 0
import json, sys
s = json.load(open(sys.argv[1]))
prof = sys.argv[2]
if s.get("status") == "valid":
    p = (s.get("profiles") or {}).get(prof) or {}
    print("1" if p.get("valid") else "0")
    sys.exit(0)
# If build / integrity / play_runtime failed, public_valid is False.
for g in ("integrity", "build", "play_runtime"):
    gv = (s.get("gates") or {}).get(g)
    if gv and not gv.get("pass", True):
        print("0")
        sys.exit(0)
diag = s.get("diagnostics") or {}
if diag.get("public_valid") is True:
    # Also check public profile regression cap on primary profile
    pub_sp = float(((diag.get("unverified_public_speedups") or {}).get(prof)) or 0.0)
    print("1" if pub_sp > 0.0 else "0")
else:
    print("0")
PY
)
  if [ "$wt_pub_valid" != "1" ]; then
    local raw_cands=""
    if [ -f "$RUN_DIR/mev-history.jsonl" ]; then
      raw_cands=$(python3 - "$RUN_DIR/mev-history.jsonl" "$START" <<'PY' 2>/dev/null || true
import json, sys
t0 = float(sys.argv[2])
tier_clean_full, tier_clean_fast, tier_dirty = [], [], []
for line in open(sys.argv[1]):
    try:
        d = json.loads(line)
        if d.get("ts", t0) < t0 - 60:
            continue
        gh = d.get("git_head")
        if d.get("status") == "valid" and d.get("profile_valid", True) and gh:
            if not d.get("git_dirty"):
                if not d.get("fast"):
                    tier_clean_full.append(gh)
                else:
                    tier_clean_fast.append(gh)
            else:
                tier_dirty.append(gh)
    except Exception:
        pass
ordered = list(reversed(tier_clean_full)) + list(reversed(tier_clean_fast)) + list(reversed(tier_dirty))
seen = []
for h in ordered:
    if not any(h.startswith(s) or s.startswith(h) for s in seen):
        seen.append(h)
print("\n".join(seen[:6]))
PY
)
    fi
    local recent_branch_shas
    recent_branch_shas="$(in_task bash -c '
      cd /task/game || exit 0
      root=$(git rev-list --max-parents=0 HEAD 2>/dev/null | tail -n 1 || true)
      for s in $(git rev-list --max-count=5 HEAD 2>/dev/null); do
        [ -n "$root" ] && [ "$s" = "$root" ] && continue
        echo "$s"
      done
      h=$(git rev-parse HEAD 2>/dev/null || true)
      for b in refs/heads/main refs/heads/master $(git for-each-ref --sort=-committerdate --format="%(refname)" refs/heads/ 2>/dev/null); do
        s=$(git rev-parse --verify "$b" 2>/dev/null || true)
        if [ -n "$s" ] && [ "$s" != "$h" ] && [ "$s" != "$root" ]; then
          echo "$s"
          break
        fi
      done
    ' 2>/dev/null || true)"
    if [ -n "$recent_branch_shas" ]; then
      raw_cands=$(printf '%s\n%s\n' "$recent_branch_shas" "$raw_cands")
    fi

    local skip_head=""
    [ -z "$wt_dirty" ] && skip_head="$cur_head"
    local resolved_cands=()
    local rc full_sha already
    while IFS= read -r rc; do
      [ -n "$rc" ] || continue
      full_sha="$(in_task git -C /task/game rev-parse --verify "${rc}^{commit}" 2>/dev/null || true)"
      [ -n "$full_sha" ] || continue
      [ -n "$skip_head" ] && [ "$full_sha" = "$skip_head" ] && continue
      already=0
      for existing_sha in "${resolved_cands[@]}"; do
        [ "$existing_sha" = "$full_sha" ] && already=1 && break
      done
      [ "$already" = 1 ] && continue
      resolved_cands+=("$full_sha")
      [ "${#resolved_cands[@]}" -ge 3 ] && break
    done <<< "$raw_cands"

    local cand_sha pub_cache cand_pub_ok
    for cand_sha in "${resolved_cands[@]}"; do
      pub_cache="$RUN_DIR/.graded-commits-public/$cand_sha"
      if [ ! -f "$pub_cache/grade/summary.json" ]; then
        if extract_commit_tree "$cand_sha" "$dir/src" "$dir/last-valid-src"; then
          mkdir -p "$pub_cache"
          MEV_REFERENCE_DIR="$REPO/$CACHE" "$REPO/scripts/grade.sh" --game "$GAME" "$dir/last-valid-src" "$pub_cache/grade" "${pub_args[@]}" \
            > "$pub_cache/grade.txt" 2>&1 || true
        fi
        rm -rf "$dir/last-valid-src"
      fi
      [ -f "$pub_cache/grade/summary.json" ] || continue
      cand_pub_ok=$(python3 -c "import json; s=json.load(open('$pub_cache/grade/summary.json')); p=(s.get('profiles') or {}).get('$PROFILE') or {}; print('1' if s.get('status')=='valid' and p.get('valid') else '0')" 2>/dev/null || echo 0)
      if [ "$cand_pub_ok" = "1" ]; then
        last_valid_commit="$cand_sha"
        break
      fi
    done
    if [ -n "$last_valid_commit" ]; then
      local full_cache="$RUN_DIR/.graded-commits/$last_valid_commit"
      if [ ! -f "$full_cache/grade/summary.json" ]; then
        if extract_commit_tree "$last_valid_commit" "$dir/src" "$dir/last-valid-src"; then
          mkdir -p "$full_cache"
          "$REPO/scripts/grade.sh" --game "$GAME" "$dir/last-valid-src" "$full_cache/grade" "${args[@]}" \
            > "$full_cache/grade.txt" 2>&1 || true
        fi
        rm -rf "$dir/last-valid-src"
      fi
      if [ -d "$full_cache/grade" ]; then
        rm -rf "$dir/last-valid-grade"
        cp -rf "$full_cache/grade" "$dir/last-valid-grade"
        cp -f "$full_cache/grade.txt" "$dir/last-valid-grade.txt" 2>/dev/null || true
        printf '%s\n' "$last_valid_commit" > "$dir/last-valid-commit"
      fi
    fi
  fi
  local n_commits trailing_unv
  n_commits="$(in_task bash -c 'cd /task/game && git rev-list --count HEAD 2>/dev/null || echo 1' 2>/dev/null | tr -d ' ' || echo 1)"
  n_commits=$(( ${n_commits:-1} > 0 ? ${n_commits:-1} - 1 : 0 ))
  trailing_unv="$(in_task python3 - "$START" <<'PY' 2>/dev/null || echo 0
import json, pathlib, subprocess, sys
t0 = float(sys.argv[1])
p = pathlib.Path("/task/.mev-history.jsonl")
last_gh = ""
if p.is_file():
    for l in p.read_text().splitlines():
        try:
            d = json.loads(l)
            if d.get("ts", t0) >= t0 - 60 and d.get("git_head"):
                last_gh = d["git_head"]
        except Exception:
            pass
if last_gh:
    r = subprocess.run(["git", "-C", "/task/game", "rev-list", "--count", f"{last_gh}..HEAD"], capture_output=True, text=True)
    if r.returncode == 0 and r.stdout.strip().isdigit():
        print(r.stdout.strip()); sys.exit(0)
print(0)
PY
)"
  # Compensate active-work timers for synchronous host checkpoint grading duration
  # (only during the live loop, before final).
  if [ "$name" != "final" ]; then
    local grade_t1 grade_dt
    grade_t1=$(now)
    grade_dt=$(( grade_t1 - grade_t0 ))
    if [ "$grade_dt" -gt 0 ]; then
      printf '{"start":%d,"end":%d,"seconds":%d,"kind":"host_grade"}\n' "$grade_t0" "$grade_t1" "$grade_dt" >> "$RUN_DIR/quota-pauses.jsonl"
      PAUSED_S=$((PAUSED_S + grade_dt))
      DEADLINE=$((DEADLINE + grade_dt))
      NEXT_COMMIT=$((NEXT_COMMIT + grade_dt))
      NEXT_GRADE=$((NEXT_GRADE + grade_dt))
      write_manifest 0 0
    fi
  fi
  rebuild_trajectory_json "$n_commits" "${trailing_unv:-0}"
  log "checkpoint $name: $(python3 -c "import json;s=json.load(open('$dir/grade/summary.json'));p=s.get('profiles',{}).get('$PROFILE',{});f=s.get('fidelity',{});fa=(s.get('failure_attribution') or {}).get('primary_category');print(s['status'],'cat='+str(fa) if s.get('status')!='valid' else '','reason='+repr(s['reason']) if s.get('status')!='valid' and s.get('reason') else '', 'reward=',p.get('reward'),'speedup=',p.get('speedup'),'cost_saved=',p.get('cost_saved'),'vs_o2=',p.get('vs_o2_speedup'),'fid=',f.get('overall'),'ssim=',f.get('video_ssim'))" 2>/dev/null || echo 'no summary')"
  if [ -f "$dir/last-valid-grade/summary.json" ]; then
    log "checkpoint $name (last valid commit $last_valid_commit): $(python3 -c "import json;s=json.load(open('$dir/last-valid-grade/summary.json'));p=s.get('profiles',{}).get('$PROFILE',{});f=s.get('fidelity',{});print(s['status'],'reason='+repr(s['reason']) if s.get('status')!='valid' and s.get('reason') else '', 'reward=',p.get('reward'),'speedup=',p.get('speedup'),'cost_saved=',p.get('cost_saved'),'vs_o2=',p.get('vs_o2_speedup'),'fid=',f.get('overall'),'ssim=',f.get('video_ssim'))" 2>/dev/null || echo 'no summary')"
  fi
}

# Detect quota/rate-limit exhaustion from the exiting agent invocation log.
# Outputs "<wait_seconds>\t<reason>" if quota exhaustion was hit, else empty.
detect_quota_pause() {
  local logfile="$1" exit_rc="$2" elapsed="$3" prev_streak="$4"
  python3 - "$logfile" "$exit_rc" "$elapsed" "$prev_streak" "$QUOTA_BUFFER_S" "$QUOTA_DEFAULT_WAIT_S" <<'PY' 2>/dev/null || true
import datetime, json, os, pathlib, re, sys, time

log_path = pathlib.Path(sys.argv[1])
exit_rc = int(sys.argv[2])
elapsed = int(sys.argv[3])
prev_streak = int(sys.argv[4])
buf_s = int(sys.argv[5])
default_wait = int(sys.argv[6])

if not log_path.is_file():
    sys.exit(0)

raw = log_path.read_bytes()
tail = raw[-32768:].decode("utf-8", errors="replace")
lines = [l for l in tail.splitlines() if l.strip()]

error_texts = []
for line in lines[-80:]:
    try:
        d = json.loads(line)
        if not isinstance(d, dict):
            continue
        t = d.get("type") or d.get("event")
        res = d.get("result") if isinstance(d.get("result"), dict) else {}
        if t == "error":
            msg = d.get("message") or d.get("error") or json.dumps(d)
            error_texts.append(str(msg))
        elif t == "result" and (
            str(d.get("status") or res.get("status") or "").upper() in ("ERROR", "FAILED")
            or d.get("is_error")
            or res.get("is_error")
            or d.get("error")
            or res.get("error")
        ):
            # Antigravity CLI (`agy --output-format stream-json` -> event="result") & Claude (type="result").
            error_texts.append(json.dumps(d))
        elif t in ("turn.failed", "item.failed") and d.get("error"):
            # OpenAI Codex CLI (`codex exec --json`) emits quota/rate errors as type="turn.failed".
            error_texts.append(json.dumps(d))
        elif t == "final":
            r = d.get("reason")
            if isinstance(r, dict) and r.get("error"):
                error_texts.append(json.dumps(r["error"]))
            elif isinstance(r, str) and ("quota" in r.lower() or "exhausted" in r.lower() or "429" in r):
                error_texts.append(r)
        msg = d.get("message") or d
        if isinstance(msg, dict) and (
            msg.get("stopReason") in ("error", "rate_limit", "quota_exceeded")
            or msg.get("errorStatus") == 429
        ):
            error_texts.append(str(msg.get("errorMessage") or msg.get("stopReason") or json.dumps(msg)))
        if d.get("error"):
            error_texts.append(json.dumps(d["error"]) if isinstance(d["error"], (dict, list)) else str(d["error"]))
    except Exception:
        if exit_rc != 0 or elapsed < 120:
            if re.search(r"RESOURCE_EXHAUSTED|quota|rate.?limit|usage.?limit|queue_exceeded|too_many|429|resets? in|try again in", line, re.I):
                error_texts.append(line)

combined = "\n".join(error_texts)
quota_re = re.compile(
    r"RESOURCE_EXHAUSTED"
    r"|usage_limit_reached"
    r"|(?:token[\s_-]*)?quota[\s_-]*(?:exceeded|exhausted|limit|will reset|resets)"
    r"|rate[\s_-]?limit[\s_-]?(?:exceeded|reached)"
    r"|queue[\s_-]?exceeded"
    r"|usage\s*limit(?:\s*reached|\s*exceeded)?"
    r"|you(?:'ve|\s+have)\s+(?:hit|reached|exceeded)\s+your.*limit"
    r"|too[\s_-]+many[\s_-]+(?:requests|tokens)"
    r"|\"(?:code|errorStatus|status)\"\s*:\s*429\b"
    r"|\bHTTP\s*429\b|\bstatus[:=\s]+429\b|(?:^|\s)429\s+(?:Too Many|Tokens|We're experiencing)",
    re.I,
)
if not combined or not quota_re.search(combined):
    sys.exit(0)

wait_s = None
# 1. Explicit "Resets in Xd Yh Zm Ws" / "try again in 2 days 4 hours" (supports ChatGPT Plus 5h & weekly caps)
m_hms = re.search(
    r"(?:resets?|try again|retry|available|back)\s+(?:in|after)\s+"
    r"(?:(\d+)\s*(?:days|day|d)(?:,\s*|\s+and\s+|\s*))?"
    r"(?:(\d+)\s*(?:hours|hour|hrs|hr|h)(?:,\s*|\s+and\s+|\s*))?"
    r"(?:(\d+)\s*(?:minutes|minute|mins|min|m)(?:,\s*|\s+and\s+|\s*))?"
    r"(?:(\d+)\s*(?:seconds|second|secs|sec|s))?",
    combined,
    re.I,
)
if m_hms and any(m_hms.groups()):
    dy = int(m_hms.group(1) or 0)
    h = int(m_hms.group(2) or 0)
    mn = int(m_hms.group(3) or 0)
    sc = int(m_hms.group(4) or 0)
    parsed = dy * 86400 + h * 3600 + mn * 60 + sc
    if parsed > 0:
        wait_s = parsed + buf_s

# 1b. Structured numeric reset seconds (e.g. Codex `"resets_in_seconds": 14400` or `"resets_at": 1764200000`)
if wait_s is None:
    m_rsec = re.search(r'"(?:resets_in_seconds|reset_seconds)"\s*:\s*(\d+)', combined, re.I)
    if m_rsec and int(m_rsec.group(1)) > 0:
        wait_s = int(m_rsec.group(1)) + buf_s
if wait_s is None:
    m_rat = re.search(r'"(?:resets_at|reset_at)"\s*:\s*(\d{10})\b', combined, re.I)
    if m_rat:
        delta = int(m_rat.group(1)) - int(time.time())
        if 0 < delta <= 8 * 86400:
            wait_s = delta + buf_s

# 2. ISO-8601 reset timestamp (e.g. "quotaResetTimeStamp": "2026-11-25T20:00:00Z")
if wait_s is None:
    m_iso = re.search(
        r"(?:reset(?:Time|Timestamp|At)|quotaResetTimeStamp)[^0-9A-Za-z]*([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2}))",
        combined,
        re.I,
    )
    if m_iso:
        try:
            iso = m_iso.group(1).replace("Z", "+00:00")
            dt = datetime.datetime.fromisoformat(iso)
            delta = int(dt.timestamp() - time.time())
            if 0 < delta <= 8 * 86400:
                wait_s = delta + buf_s
        except Exception:
            pass

# 3a. Millisecond retry headers FIRST (e.g. "retry-after-ms=60000" or "retryDelay": "5000ms")
#     so milliseconds are never misparsed as seconds!
if wait_s is None:
    m_ms = re.search(
        r"(?:retry[-_ ]?after[-_ ]?ms[^0-9]*(\d+)\b|(?:retry[-_ ]?after|retryDelay)[^0-9]*(\d+)\s*ms\b)",
        combined,
        re.I,
    )
    if m_ms:
        ms_val = int(m_ms.group(1) or m_ms.group(2) or 0)
        if ms_val > 0:
            wait_s = max(1, (ms_val + 999) // 1000) + buf_s

# 3b. Retry-After / retryDelay in seconds (e.g. "retryDelay": "180s" or "Retry-After: 60")
if wait_s is None:
    m_sec = re.search(r"(?:retry[-_ ]?after(?![-_ ]?ms)|retryDelay)[^0-9]*(\d+)(?!\s*ms\b)\s*s?\b", combined, re.I)
    if m_sec:
        parsed = int(m_sec.group(1))
        if parsed > 0:
            wait_s = parsed + buf_s

# 4. Fallback progressive probe wait when reset window isn't specified
explicit_reset = (wait_s is not None)
if wait_s is None:
    mult = min(6, 1 << min(prev_streak, 3))
    wait_s = min(1800, default_wait * mult)

explicit_cap = int(os.environ.get("MEV_QUOTA_MAX_WAIT_S", str(7 * 86400)))
max_cap = explicit_cap if explicit_reset else 6 * 3600
wait_s = max(30, min(wait_s, max_cap))
snippet = re.sub(r"\s+", " ", error_texts[-1]).strip()[:160]
print(f"{wait_s}\t{snippet}")
PY
}

sleep_interruptible() {
  local target_end="$1"
  while [ "$(now)" -lt "$target_end" ]; do
    local rem=$(( target_end - $(now) ))
    [ "$rem" -gt 30 ] && rem=30
    [ "$rem" -gt 0 ] && sleep "$rem"
  done
}

AGENT_PID=""; AGENT_LOG=""; AGENT_STARTED=0; AGENT_START_HEAD=""; N=0; RAPID_FAILS=0; FATAL_FAILS=0; NOOP_STREAK=0; QUOTA_STREAK=0; QUOTA_PAUSES=0; PAUSED_S=0; NEXT_FRESH="${MEV_START_FRESH:-0}"
start_agent() {
  N=$((N + 1)); AGENT_LOG="$RUN_DIR/agent-$(printf %03d $N).log"; AGENT_STARTED=$(now)
  AGENT_START_HEAD="$(in_task git -C /task/game rev-parse HEAD 2>/dev/null || true)"
  local fresh="$NEXT_FRESH"; NEXT_FRESH=0
  local prompt="$PROMPT"
  if [ "$N" -gt 1 ]; then
    if [ "$fresh" = "1" ]; then
      prompt="$(in_task cat /task/TASK.md)"$'\n\n'"$(continue_prompt)"
    else
      prompt="$(continue_prompt)"
    fi
  fi
  log "starting agent invocation $N (remaining $(format_remaining), paused_total=${PAUSED_S}s, fresh=$fresh)"
  # Start directly in /task/game (matching TASK.md), update .agent-heartbeat on
  # ANY output line (including reasoning deltas), and drop high-volume delta lines from disk.
  touch "$RUN_DIR/.agent-heartbeat"
  dc exec -T -e "MEV_DEADLINE_EPOCH=$DEADLINE" -e "MEV_FRESH_SESSION=$fresh" task setsid --wait bash -lc \
    "cd /task/game && echo \$\$ > /tmp/mev-agent-pgid; $AGENT_CMD $(printf '%q' "$prompt")" < /dev/null 2>&1 \
    | awk -v hb="$RUN_DIR/.agent-heartbeat" 'NR == 1 || NR % 16 == 0 { printf "" > hb; close(hb) } index($0, "\"type\":\"tool_execution_update\"") == 0 && index($0, "\"type\":\"tool_stream_update\"") == 0 && index($0, "\"type\":\"message_update\"") == 0 && !(index($0, "\"event\":\"step_update\"") > 0 && index($0, "\"state\":\"ACTIVE\"") > 0 && index($0, "\"text_delta\":") > 0) { print; fflush() }' > "$AGENT_LOG" &
  AGENT_PID=$!
}

stop_agent() {
  [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null || true
  in_task bash -c '
    if read -r pgid < /tmp/mev-agent-pgid && [[ $pgid =~ ^[1-9][0-9]+$ ]]; then
      if kill -TERM -- "-$pgid" 2>/dev/null; then
        sleep 2
        kill -KILL -- "-$pgid" 2>/dev/null || true
      fi
    fi
    rm -f /tmp/mev-agent-pgid
  ' 2>/dev/null || true
  wait "$AGENT_PID" 2>/dev/null || true; AGENT_PID=""
}
trap 'stop_agent; commit; save_artifacts_fast; write_manifest 0 0; log "interrupted (saved mev-history.jsonl and game.bundle)"; exit 130' INT TERM

if [ "$RESUME" -eq 1 ] && [ -f "$RUN_DIR/run_manifest.json" ]; then
  read -r START PAUSED_S QUOTA_PAUSES G N < <(python3 - "$RUN_DIR" "$(now)" <<'PY'
import json, pathlib, re, sys
rdir = pathlib.Path(sys.argv[1])
now_ts = int(sys.argv[2])
m = json.loads((rdir / "run_manifest.json").read_text())
start = int(m.get("start_epoch") or now_ts)
paused = int(m.get("paused_seconds") or 0)
qpauses = int(m.get("quota_pauses") or 0)
mtimes = [int(p.stat().st_mtime) for p in list(rdir.glob("agent-*.log")) + [rdir / "mev-history.jsonl", rdir / "run_manifest.json"] if p.exists()]
last_ts = max(mtimes) if mtimes else now_ts
gap = max(0, now_ts - last_ts)
if gap > 5:
    with (rdir / "quota-pauses.jsonl").open("a") as fh:
        fh.write(json.dumps({"start": last_ts, "end": now_ts, "seconds": gap, "kind": "maintenance_pause"}) + "\n")
    paused += gap
cps = [int(m_cp.group(1)) for p in rdir.glob("checkpoint-*") if (m_cp := re.match(r"^checkpoint-(\d+)$", p.name))]
g_max = max(cps) if cps else 0
alogs = [int(m_al.group(1)) for p in rdir.glob("agent-*.log") if (m_al := re.match(r"^agent-(\d+)\.log$", p.name))]
n_max = max(alogs) if alogs else 0
print(f"{start} {paused} {qpauses} {g_max} {n_max}")
PY
)
  DEADLINE=$((START + TOTAL_S + PAUSED_S))
  NEXT_COMMIT=$(( $(now) + COMMIT_S ))
  NEXT_GRADE=$((START + (G + 1) * GRADE_S + PAUSED_S))
  [ "$NEXT_GRADE" -le "$(now)" ] && NEXT_GRADE=$(( $(now) + 60 ))
  log "resuming run $RUN: game=$GAME, ${HOURS}h, profile=$PROFILE, AGENT_CMD: $AGENT_CMD (checkpoint-$((G + 1)) next, remaining $(format_remaining))"
else
  START=$(now); DEADLINE=$((START + TOTAL_S)); NEXT_COMMIT=$((START + COMMIT_S)); NEXT_GRADE=$((START + GRADE_S)); G=0
  log "run $RUN: game=$GAME, ${HOURS}h, profile=$PROFILE, AGENT_CMD: $AGENT_CMD"
fi
write_manifest 0 0
start_agent
while [ "$(now)" -lt "$DEADLINE" ]; do
  sleep 10
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    exit_rc=0; wait "$AGENT_PID" 2>/dev/null || exit_rc=$?
    stop_agent
    if ! dc ps --services --filter status=running 2>/dev/null | grep -qx task; then
      log "task container is no longer running; aborting supervisor loop cleanly"
      break
    fi
    elapsed=$(( $(now) - AGENT_STARTED ))
    stop_reason="$(python3 - "$AGENT_LOG" <<'PY' 2>/dev/null || true
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
if not p.is_file(): sys.exit(0)
reason = ""
for line in p.read_text(errors="replace").splitlines()[-80:]:
    try:
        d = json.loads(line)
        if not isinstance(d, dict):
            continue
        t = d.get("type") or d.get("event")
        res = d.get("result") if isinstance(d.get("result"), dict) else {}
        if t == "final":
            r = d.get("reason")
            if isinstance(r, dict) and r.get("kind"):
                reason = str(r["kind"])
                err = r.get("error")
                if isinstance(err, dict) and err.get("message"):
                    reason += ":" + str(err["message"])[:120]
            elif r:
                reason = str(r)
            continue
        if t == "error" and d.get("message"):
            reason = "error:" + str(d["message"])[:120]
            continue
        if t == "result":
            st = str(d.get("status") or res.get("status") or "").upper()
            if st in ("ERROR", "FAILED") or d.get("is_error") or res.get("is_error"):
                reason = "error:" + str(d.get("error") or res.get("error") or d.get("result") or st)[:120]
            elif res.get("finished_reason") or d.get("stop_reason"):
                reason = str(res.get("finished_reason") or d.get("stop_reason"))
            continue
        msg = d.get("message") or d
        if isinstance(msg, dict) and msg.get("stopReason"):
            reason = str(msg["stopReason"])
            if msg.get("errorMessage"):
                reason += ":" + str(msg["errorMessage"])[:120]
    except Exception:
        pass
print(reason)
PY
)"
    log "agent invocation $N exited (rc=$exit_rc elapsed=${elapsed}s stop=${stop_reason:-unknown})"

    # 1. Check 5h / rolling quota exhaustion BEFORE rapid fails or noop counting.
    quota_info="$(detect_quota_pause "$AGENT_LOG" "$exit_rc" "$elapsed" "$QUOTA_STREAK")"
    if [ -n "$quota_info" ]; then
      IFS=$'\t' read -r q_wait q_reason <<< "$quota_info"
      QUOTA_PAUSES=$((QUOTA_PAUSES + 1))
      QUOTA_STREAK=$((QUOTA_STREAK + 1))
      pause_start=$(now)
      resume_at=$((pause_start + q_wait))
      log "quota exhausted (pause #$QUOTA_PAUSES, streak #$QUOTA_STREAK): pausing active-work timer for ${q_wait}s until $(date -u -d "@$resume_at" +%FT%TZ 2>/dev/null || echo "$resume_at") (reason: $q_reason)"
      commit
      write_manifest 1 "$resume_at"
      sleep_interruptible "$resume_at"
      pause_end=$(now)
      actual_pause=$(( pause_end - pause_start ))
      printf '{"start":%d,"end":%d,"seconds":%d}\n' "$pause_start" "$pause_end" "$actual_pause" >> "$RUN_DIR/quota-pauses.jsonl"
      PAUSED_S=$((PAUSED_S + actual_pause))
      DEADLINE=$((DEADLINE + actual_pause))
      NEXT_COMMIT=$((NEXT_COMMIT + actual_pause))
      NEXT_GRADE=$((NEXT_GRADE + actual_pause))
      RAPID_FAILS=0
      FATAL_FAILS=0
      NOOP_STREAK=0
      write_manifest 0 0
      log "quota pause #$QUOTA_PAUSES finished (slept ${actual_pause}s; total_paused=${PAUSED_S}s; active remaining=$(format_remaining))"
      [ "$(now)" -lt "$DEADLINE" ] && start_agent
      continue
    fi
    QUOTA_STREAK=0

    # 2. Final-10-minute safe lock-in: if <=10m remain and HEAD is clean + passed full `mev check`,
    #    do NOT respawn or wipe context into a risky last-minute edit!
    rem_s=$(( DEADLINE - $(now) ))
    if [ "$rem_s" -le 600 ] && [ "$rem_s" -gt 0 ] && is_head_cleanly_verified; then
      log "endgame lock-in: clean full-verified HEAD confirmed with ${rem_s}s remaining; holding steady until deadline"
      sleep_interruptible "$DEADLINE"
      break
    fi

    cur_head="$(in_task git -C /task/game rev-parse HEAD 2>/dev/null || true)"
    cur_dirty="$(in_task bash -c 'git -C /task/game status --porcelain 2>/dev/null | wc -l' 2>/dev/null | tr -d ' ' || echo 0)"
    if [ "$rem_s" -gt 900 ] && [ "$cur_head" = "$AGENT_START_HEAD" ] && [ "${cur_dirty:-0}" -eq 0 ]; then
      NOOP_STREAK=$((NOOP_STREAK + 1))
      if [ "$NOOP_STREAK" -ge 3 ]; then
        log "agent exited with clean tree and no new commit ($NOOP_STREAK consecutive times); next invocation will start a fresh session"
        NEXT_FRESH=1
        NOOP_STREAK=0
        if [ "$rem_s" -gt 0 ]; then
          sleep $(( rem_s < 15 ? rem_s : 15 ))
        fi
      fi
    else
      NOOP_STREAK=0
    fi

    is_err_stop=0
    [[ "${stop_reason:-}" == error* ]] && is_err_stop=1
    if [ "$elapsed" -lt 60 ] && { [ "$exit_rc" -ne 0 ] || [ "$is_err_stop" -eq 1 ]; }; then
      RAPID_FAILS=$((RAPID_FAILS + 1))
      if tail -c 8192 "$AGENT_LOG" 2>/dev/null | grep -qiE 'Model does not exist|model_not_found|do not have access to it|404[^0-9].*model|invalid_api_key|401[^0-9].*unauthorized'; then
        FATAL_FAILS=$((FATAL_FAILS + 1))
      else
        FATAL_FAILS=0
      fi
      if [ "$FATAL_FAILS" -ge 5 ]; then
        log "aborting restart loop after $FATAL_FAILS consecutive fatal API/model errors (see $AGENT_LOG)"
        break
      fi
      backoff=$(( 30 * (1 << (RAPID_FAILS > 4 ? 4 : RAPID_FAILS - 1)) ))
      [ "$backoff" -gt 300 ] && backoff=300
      rem_s=$(( DEADLINE - $(now) ))
      [ "$backoff" -gt "$rem_s" ] && backoff="$rem_s"
      if [ "$backoff" -gt 0 ]; then
        log "agent failed (rc=$exit_rc stop=${stop_reason:-unknown}) in ${elapsed}s (rapid failure #$RAPID_FAILS); backing off ${backoff}s"
        sleep "$backoff"
      fi
    elif [ "$exit_rc" -eq 0 ] && [ "$elapsed" -lt 60 ]; then
      RAPID_FAILS=0
      FATAL_FAILS=0
      rem_s=$(( DEADLINE - $(now) ))
      if [ "$rem_s" -gt 0 ]; then
        sleep $(( rem_s < 5 ? rem_s : 5 ))
      fi
    else
      RAPID_FAILS=0
      FATAL_FAILS=0
    fi
    [ "$(now)" -lt "$DEADLINE" ] && start_agent
  elif [ "$STALL_S" -gt 0 ]; then
    m_log=$(stat -c %Y "$AGENT_LOG" 2>/dev/null || echo "$AGENT_STARTED")
    m_hb=$(stat -c %Y "$RUN_DIR/.agent-heartbeat" 2>/dev/null || echo "$AGENT_STARTED")
    m=$(( m_hb > m_log ? m_hb : m_log ))
    if [ $(( $(now) - m )) -gt "$STALL_S" ]; then log "agent stalled; restarting"; stop_agent; RAPID_FAILS=0; FATAL_FAILS=0; start_agent; fi
  fi
  if [ "$(now)" -ge "$NEXT_COMMIT" ]; then commit; NEXT_COMMIT=$(( $(now) + COMMIT_S )); fi
  if [ "$(now)" -ge "$NEXT_GRADE" ]; then G=$((G + 1)); grade_checkpoint "checkpoint-$G"; NEXT_GRADE=$(( $(now) + GRADE_S )); fi
done

bisect_last_valid() {
  # Zero-oracle post-run rescue over agent commits ONLY when BOTH final working
  # tree and final/last-valid-commit failed PUBLIC verification (e.g. >3 broken
  # commits at the very end of the run). Search uses strictly public 6-course +
  # PLAY=1 grading (NEVER --heldout!), and evaluates --heldout ONCE on the single
  # public-selected commit.
  [ -n "$HELDOUT" ] || return 0
  local already_have_pub_valid
  already_have_pub_valid=$(python3 - "$RUN_DIR/final" "$PROFILE" <<'PY' 2>/dev/null || echo 0
import json, pathlib, sys
fdir, prof = pathlib.Path(sys.argv[1]), sys.argv[2]
for rel in ("grade/summary.json", "last-valid-grade/summary.json"):
    p = fdir / rel
    if not p.is_file():
        continue
    s = json.loads(p.read_text())
    if s.get("status") == "valid" and ((s.get("profiles") or {}).get(prof) or {}).get("valid"):
        print("1"); sys.exit(0)
    if all((s.get("gates") or {}).get(g, {}).get("pass", True) for g in ("integrity", "build", "play_runtime")):
        if (s.get("diagnostics") or {}).get("public_valid") is True:
            print("1"); sys.exit(0)
print("0")
PY
)
  [ "$already_have_pub_valid" = "1" ] && return 0

  local pub_args=() full_args=(--heldout "$HELDOUT")
  if [ "$GAME" = "sm64" ]; then
    pub_args+=(--play-smoke)
    full_args+=(--play-smoke)
  fi
  local cur_head known_bad=""
  cur_head="$(in_task git -C /task/game rev-parse HEAD 2>/dev/null || true)"
  [ -f "$RUN_DIR/final/last-valid-commit" ] && known_bad=$(cat "$RUN_DIR/final/last-valid-commit" 2>/dev/null || true)

  local best_sha="" best_ts="" best_idx=-1 best_sp="0"
  declare -A TESTED_SHAS=()
  [ -n "$cur_head" ] && TESTED_SHAS["$cur_head"]=1
  if [ -n "$known_bad" ]; then
    local kb_full
    kb_full="$(in_task git -C /task/game rev-parse --verify "$known_bad" 2>/dev/null || true)"
    [ -n "$kb_full" ] && TESTED_SHAS["$kb_full"]=1
  fi

  grade_candidate_sha() {
    local sha="$1" label="$2" c_idx="$3"
    [ -n "$sha" ] || return 1
    [ -n "${TESTED_SHAS[$sha]:-}" ] && return 1
    TESTED_SHAS["$sha"]=1
    local bdir="$RUN_DIR/bisect-tmp"
    extract_commit_tree "$sha" "$RUN_DIR/final/src" "$bdir/src" || { rm -rf "$bdir"; return 1; }
    MEV_REFERENCE_DIR="$REPO/$CACHE" "$REPO/scripts/grade.sh" --game "$GAME" "$bdir/src" "$bdir/grade" "${pub_args[@]}" \
      > "$bdir/grade.txt" 2>&1 || true
    local st p_ok sp
    st=$(python3 -c "import json; print(json.load(open('$bdir/grade/summary.json')).get('status',''))" 2>/dev/null || true)
    p_ok=$(python3 -c "import json; print('1' if ((json.load(open('$bdir/grade/summary.json')).get('profiles') or {}).get('$PROFILE') or {}).get('valid') else '0')" 2>/dev/null || echo 0)
    sp=$(python3 -c "import json; print(json.load(open('$bdir/grade/summary.json')).get('profiles',{}).get('$PROFILE',{}).get('speedup',0) or 0)" 2>/dev/null || echo 0)
    log "bisect-public $label (${sha:0:7}): $st prof_valid=$p_ok pub_speedup=${sp:-0}"
    if [ "$st" = "valid" ] && [ "$p_ok" = "1" ]; then
      if awk -v a="${sp:-0}" -v b="${best_sp:-0}" 'BEGIN { exit !(a > b) }'; then
        best_sha="$sha"
        best_idx="$c_idx"
        best_sp="${sp:-0}"
        best_ts=$(in_task git -C /task/game show -s --format=%ct "$sha" 2>/dev/null || date +%s)
      fi
      rm -rf "$bdir"
      return 0
    fi
    rm -rf "$bdir"
    return 1
  }

  # 1. Check any ungraded local branch tips (e.g. `main` if HEAD was left on an experiment branch).
  mapfile -t BRANCH_TIPS < <(in_task git -C /task/game for-each-ref --sort=-committerdate --format='%(objectname)' refs/heads/ 2>/dev/null || true)
  for tip in "${BRANCH_TIPS[@]}"; do
    grade_candidate_sha "$tip" "branch-tip" 0 || true
  done

  # 2. Gather longest commit history & index map.
  local target_ref="HEAD"
  target_ref="$(in_task bash -c '
    cd /task/game || exit 0
    best_r="HEAD"
    best_n=$(git rev-list --first-parent --count HEAD 2>/dev/null || echo 0)
    for r in $(git for-each-ref --format="%(refname)" refs/heads/ 2>/dev/null); do
      n=$(git rev-list --first-parent --count "$r" 2>/dev/null || echo 0)
      if [ "$n" -gt "$best_n" ]; then best_n="$n"; best_r="$r"; fi
    done
    echo "$best_r"
  ' 2>/dev/null || echo HEAD)"
  mapfile -t COMMITS < <(in_task git -C /task/game rev-list --reverse --first-parent "$target_ref" 2>/dev/null || true)
  local total=${#COMMITS[@]}

  local lo=1
  if [ -f "$RUN_DIR/trajectory.json" ] && [ "$total" -ge 2 ]; then
    local known_good_idx
    known_good_idx=$(python3 - "$RUN_DIR/trajectory.json" "${COMMITS[@]}" <<'PY' 2>/dev/null || true
import json, sys
t = json.loads(open(sys.argv[1]).read())
commits = sys.argv[2:]
best = 0
valid_shas = []
for cp in t.get("host_checkpoints", []):
    if cp.get("status") == "valid" and cp.get("git_head"):
        valid_shas.append(cp["git_head"])
    lv = cp.get("last_valid")
    if isinstance(lv, dict) and lv.get("status") == "valid" and lv.get("git_head"):
        valid_shas.append(lv["git_head"])
for idx, full in enumerate(commits):
    for vs in valid_shas:
        if vs and full.startswith(vs):
            if idx > best:
                best = idx
print(best)
PY
)
    if [[ "$known_good_idx" =~ ^[0-9]+$ ]] && [ "$known_good_idx" -ge 1 ]; then
      lo=$((known_good_idx + 1))
    fi
  fi

  # 3. Probe distinct public-valid commits from mev-history.jsonl (ordered newest-clean-first, up to 6 probes)
  #    so non-monotonic commit histories still find valid islands immediately!
  if [ -f "$RUN_DIR/mev-history.jsonl" ] && [ "$total" -ge 2 ]; then
    mapfile -t HIST_CANDS < <(python3 - "$RUN_DIR/mev-history.jsonl" "$START" "$lo" "${COMMITS[@]}" <<'PY' 2>/dev/null || true
import json, sys
hist_p, t0, lo = sys.argv[1], float(sys.argv[2]), int(sys.argv[3])
commits = sys.argv[4:]
clean_shas, dirty_shas = [], []
for line in reversed(open(hist_p).read().splitlines()):
    try:
        d = json.loads(line)
        if d.get("ts", t0) < t0 - 60 or d.get("status") != "valid" or not d.get("git_head"):
            continue
        gh = d["git_head"]
        for idx in range(len(commits) - 1, lo - 1, -1):
            if commits[idx].startswith(gh):
                pair = f"{idx}:{commits[idx]}"
                if not d.get("git_dirty"):
                    if pair not in clean_shas:
                        clean_shas.append(pair)
                else:
                    if pair not in dirty_shas:
                        dirty_shas.append(pair)
                break
    except Exception:
        pass
for item in (clean_shas + dirty_shas)[:6]:
    print(item)
PY
)
    local found_hist_idx=-1
    for item in "${HIST_CANDS[@]}"; do
      [ -n "$item" ] || continue
      local c_idx="${item%%:*}" c_sha="${item#*:}"
      if grade_candidate_sha "$c_sha" "history[$c_idx/$((total-1))]" "$c_idx"; then
        found_hist_idx="$c_idx"
        break
      fi
    done
    # If we found a valid commit at found_hist_idx, binary-search (found_hist_idx+1 .. hi) for any newer valid commit!
    if [ "$found_hist_idx" -ge 1 ]; then
      lo=$((found_hist_idx + 1))
    fi
  fi

  # 4. Non-monotonic-safe backward exponential probe + binary search on [lo..hi].
  local hi=$((total - 1))
  if [ "$total" -ge 3 ] && [ "$lo" -le "$hi" ]; then
    if [ -z "$best_sha" ]; then
      # Backward exponential scan from hi (hi, hi-1, hi-3, hi-7, ...) to locate a valid anchor
      # without getting fooled by an early broken commit near lo!
      local delta=0 anchor=-1 upper_bad=$((hi + 1))
      while : ; do
        local probe=$(( hi - delta ))
        [ "$probe" -lt "$lo" ] && break
        if grade_candidate_sha "${COMMITS[$probe]}" "probe[$probe/$((total-1))]" "$probe"; then
          anchor="$probe"
          break
        else
          upper_bad="$probe"
        fi
        delta=$(( delta == 0 ? 1 : delta * 2 + 1 ))
      done
      if [ "$anchor" -ge "$lo" ]; then
        lo=$((anchor + 1))
        hi=$((upper_bad - 1))
      fi
    fi

    if [ "$lo" -le "$hi" ]; then
      log "bisect_last_valid: binary-searching commits [$lo..$hi] of $((total - 1)) on $target_ref"
      while [ "$lo" -le "$hi" ]; do
        local mid=$(( (lo + hi) / 2 ))
        if grade_candidate_sha "${COMMITS[$mid]}" "step[$mid/$((total-1))]" "$mid"; then
          lo=$((mid + 1))
        else
          hi=$((mid - 1))
        fi
      done
    fi
  fi

  local commits_net=$(( total > 0 ? total - 1 : 0 ))
  if [ -n "$best_sha" ]; then
    rm -rf "$RUN_DIR/bisect-best" "$RUN_DIR/bisect-tmp"
    if extract_commit_tree "$best_sha" "$RUN_DIR/final/src" "$RUN_DIR/bisect-tmp/src"; then
      mkdir -p "$RUN_DIR/bisect-best"
      "$REPO/scripts/grade.sh" --game "$GAME" "$RUN_DIR/bisect-tmp/src" "$RUN_DIR/bisect-best/grade" "${full_args[@]}" \
        > "$RUN_DIR/bisect-best/grade.txt" 2>&1 || true
      printf '%s\n' "$best_sha" > "$RUN_DIR/bisect-best/commit"
      printf '%s\n' "$best_ts" > "$RUN_DIR/bisect-best/commit-epoch"
      rm -rf "$RUN_DIR/bisect-tmp"
    fi
  fi
  if [ -n "$best_sha" ] && [ -f "$RUN_DIR/bisect-best/grade/summary.json" ]; then
    python3 - "$RUN_DIR" "$START" "$PROFILE" "$best_sha" "$best_ts" "$best_idx" "$commits_net" "$PAUSED_S" <<'PY' || true
import json, os, pathlib, sys
run_dir, t0, profile = pathlib.Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3]
sha, cts, idx, total, paused_s = sys.argv[4], float(sys.argv[5]), int(sys.argv[6]), int(sys.argv[7]), float(sys.argv[8])
s = json.loads((run_dir / "bisect-best" / "grade" / "summary.json").read_text())
tp = run_dir / "trajectory.json"
if not tp.exists():
    sys.exit(0)
t = json.loads(tp.read_text())
p = s.get("profiles", {}).get(profile, {})
paused_before_commit = 0.0
qp_file = run_dir / "quota-pauses.jsonl"
if qp_file.is_file():
    for line in qp_file.read_text().splitlines():
        if line.strip():
            try:
                iv = json.loads(line)
                if cts > float(iv["start"]):
                    paused_before_commit += max(0.0, min(cts, float(iv["end"])) - float(iv["start"]))
            except Exception:
                pass
else:
    pts = [(t0, 0.0)]
    for ep in sorted(run_dir.glob("checkpoint-*/snapshot-epoch")) + sorted(run_dir.glob("final/snapshot-epoch")):
        try:
            ts_p = float(ep.read_text().strip())
            pf = ep.parent / "paused-seconds"
            pts.append((ts_p, float(pf.read_text().strip()) if pf.is_file() else 0.0))
        except Exception:
            pass
    pts.sort()
    for ts_p, pv in pts:
        if ts_p <= cts:
            paused_before_commit = pv
        else:
            break
rec = {
    "name": f"bisect-last-valid ({sha[:7]})",
    "source": "bisect_last_valid",
    "git_head": sha,
    "commit_index": idx,
    "commits_total": total,
    "elapsed_hours": round(max(0.0, (cts - t0 - paused_before_commit) / 3600.0), 4),
    "workload_set": s.get("workload_set"),
    "status": s.get("status"),
    **({"toolchain": s["toolchain"]} if s.get("toolchain") else {}),
    "speedup": p.get("speedup"),
    "cost_saved": p.get("cost_saved"),
    "vs_o2_speedup": p.get("vs_o2_speedup"),
    "reward": p.get("reward"),
    "rewards": s.get("rewards", {}),
    "speedups": s.get("speedups", {}),
    "cost_saved_all": s.get("cost_saved", {}),
    "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in s.get("profiles", {}).items()},
    **({"fidelity": s["fidelity"]} if s.get("fidelity") else {}),
    **({"capability_ruler": s["capability_ruler"]} if s.get("capability_ruler") else {}),
}
t["bisect_last_valid"] = rec
tmp = tp.with_suffix(".json.tmp")
tmp.write_text(json.dumps(t, indent=1) + "\n")
os.replace(tmp, tp)
PY
    rebuild_trajectory_json "$commits_net" "0"
    log "bisect_last_valid winner: ${best_sha:0:7} (commit $best_idx/$commits_net) -> $(python3 -c "import json;s=json.load(open('$RUN_DIR/bisect-best/grade/summary.json'));p=s.get('profiles',{}).get('$PROFILE',{});print('speedup=',p.get('speedup'),'cost_saved=',p.get('cost_saved'),'vs_o2=',p.get('vs_o2_speedup'))" 2>/dev/null)"
  else
    rebuild_trajectory_json "$commits_net" "0"
    log "bisect_last_valid: no valid commit found beyond known checkpoints"
  fi
}

stop_agent
write_manifest 0 0
grade_checkpoint final
bisect_last_valid
save_artifacts_fast
log "done: results in $RUN_DIR"
}

main "$@"
exit $?
