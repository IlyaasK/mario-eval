#!/usr/bin/env bash
# Supervise a timed 24h agent run in the task container (run on the host, after
# `docker compose up -d` in quickstart/).
#
#   - writes the optimization profile to /task/PROFILE;
#   - runs $AGENT_CMD in the container (as `agent`, cwd /task) with TASK.md
#     as the prompt, re-invoking it with a short "continue" prompt whenever it
#     exits early or its log has been silent for --stall-minutes;
#   - commits /task/game every --commit-every minutes;
#   - every --grade-every hours and at the end, copies /task/game out and
#     grades it on the host: public routes, plus held-out routes when
#     --heldout DIR is given (the agent never sees those);
#   - saves the game's git history as results/<run>/game.bundle.
#
# Usage:
#   AGENT_CMD='claude -p --dangerously-skip-permissions' quickstart/run-agent.sh --game sm64 --hours 24 --profile speed
#   quickstart/run-agent.sh --hours 0.1 --commit-every 2 --grade-every 0.05   # smoke test
#
# Options: --hours H (default 24)  --game pips-garden|sm64 (default sm64)
#          --name RUN  --profile console|stutter|speed|rdp|rsp|traffic|memory (default console)
#          --commit-every MIN (30)  --grade-every H (2)  --stall-minutes MIN (15)
#          --heldout DIR (held-out replays; host reference must include them)
# AGENT_CMD may also be set in quickstart/.env.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
QS="$REPO/quickstart"

HOURS=24; GAME="sm64"; RUN=""; PROFILE=console; COMMIT_MIN=30; GRADE_HOURS=2; STALL_MIN=15; HELDOUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hours) HOURS="$2"; shift 2 ;;
    --game) GAME="$2"; shift 2 ;;
    --name) RUN="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --commit-every) COMMIT_MIN="$2"; shift 2 ;;
    --grade-every) GRADE_HOURS="$2"; shift 2 ;;
    --stall-minutes) STALL_MIN="$2"; shift 2 ;;
    --heldout) HELDOUT="$(realpath "$2")"; shift 2 ;;
    -h|--help) sed -n '2,25p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$PROFILE" in console|stutter|speed|rdp|rsp|traffic|memory) ;; *) echo "bad --profile $PROFILE (expected console|stutter|speed|rdp|rsp|traffic|memory)" >&2; exit 2 ;; esac
case "$GAME" in
  pips-garden) CORPUS="corpus"; CACHE="cache/reference" ;;
  sm64)        CORPUS="sm64/corpus"; CACHE="cache/sm64-reference" ;;
  *) echo "bad --game $GAME (expected pips-garden|sm64)" >&2; exit 2 ;;
esac
if [ -z "${AGENT_CMD:-}" ] && [ -f "$QS/.env" ]; then
  AGENT_CMD="$(sed -n 's/^AGENT_CMD=//p' "$QS/.env" | tail -n 1)"
fi
[ -n "${AGENT_CMD:-}" ] || { echo "error: set AGENT_CMD" >&2; exit 2; }

secs() { awk -v x="$1" -v m="$2" 'BEGIN { v = x * m; if (v < 1) v = 1; printf "%d", v }'; }
TOTAL_S=$(secs "$HOURS" 3600); COMMIT_S=$(secs "$COMMIT_MIN" 60)
GRADE_S=$(secs "$GRADE_HOURS" 3600); STALL_S=$(( STALL_MIN * 60 ))

RUN="${RUN:-run-${GAME}-${PROFILE}-$(date -u +%Y%m%dT%H%M%SZ)}"
RUN_DIR="$REPO/results/$RUN"
[ -e "$RUN_DIR" ] && { echo "error: $RUN_DIR exists" >&2; exit 1; }
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
CONTINUE_PROMPT="Continue working on the 24h optimization task in /task/TASK.md (profile: $PROFILE). Run 'mev check' to see your current reward, speedup, and vs_o2_speedup, commit working milestones in /task/game, and keep pushing hardware performance further. Check \$MEV_DEADLINE_EPOCH (seconds since epoch) and leave a clean, mev-check-passing tree before the deadline."

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

grade_checkpoint() {
  local name="$1" dir="$RUN_DIR/$1"
  mkdir -p "$dir"
  commit
  rm -rf "$dir/src"
  dc cp task:/task/game "$dir/src" >/dev/null
  rm -rf "$dir/src/.git" "$dir/src/build" "$dir/src/build_"*
  date +%s > "$dir/snapshot-epoch"
  local args=()
  if [ -n "$HELDOUT" ]; then args=(--heldout "$HELDOUT"); fi
  if [ "$name" = "final" ] && [ "$GAME" = "sm64" ]; then args+=(--play-smoke); fi
  "$REPO/scripts/grade.sh" --game "$GAME" "$dir/src" "$dir/grade" "${args[@]}" \
    > "$dir/grade.txt" 2>&1 || true
  dc cp task:/task/.mev-history.jsonl "$RUN_DIR/mev-history.jsonl" >/dev/null 2>&1 || true
  # If the wall-clock snapshot landed mid-experiment on a broken working tree,
  # also grade the agent's latest mev-check-verified commit so real progress is
  # visible separately from snapshot timing luck (without altering the primary
  # working-tree status).
  local status last_valid_commit=""
  status=$(python3 -c "import json; print(json.load(open('$dir/grade/summary.json')).get('status',''))" 2>/dev/null || true)
  if [ "$status" != "valid" ] && [ -f "$RUN_DIR/mev-history.jsonl" ]; then
    last_valid_commit=$(python3 - "$RUN_DIR/mev-history.jsonl" <<'PY' 2>/dev/null || true
import json, sys
last = ""
for line in open(sys.argv[1]):
    try:
        d = json.loads(line)
        if d.get("status") == "valid" and d.get("git_head"):
            last = d["git_head"]
    except Exception:
        pass
print(last)
PY
)
  fi
  if [ -n "$last_valid_commit" ]; then
    rm -rf "$dir/last-valid-src"
    mkdir -p "$dir/last-valid-src"
    if in_task git -C /task/game archive "$last_valid_commit" 2>/dev/null | tar -x -C "$dir/last-valid-src" 2>/dev/null; then
      # Copy gitignored assets/tools (e.g. extracted SM64 assets & built host tools)
      # from $dir/src without pulling in untracked working-tree files.
      in_task git -C /task/game ls-files -z --others --ignored --exclude-standard 2>/dev/null \
        | python3 -c '
import pathlib, shutil, sys
src, dst = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
for raw in sys.stdin.buffer.read().split(b"\0"):
    if not raw:
        continue
    rel = raw.decode("utf-8", "surrogateescape")
    if rel == "build" or rel.startswith(("build/", "build_")):
        continue
    sp, dp = src / rel, dst / rel
    if sp.is_file() and not dp.exists():
        dp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(sp, dp)
' "$dir/src" "$dir/last-valid-src" || true
      "$REPO/scripts/grade.sh" --game "$GAME" "$dir/last-valid-src" "$dir/last-valid-grade" "${args[@]}" \
        > "$dir/last-valid-grade.txt" 2>&1 || true
      printf '%s\n' "$last_valid_commit" > "$dir/last-valid-commit"
    fi
    rm -rf "$dir/last-valid-src"
  fi
  python3 - "$RUN_DIR" "$START" "$GAME" "$PROFILE" <<'PY' || true
import json, pathlib, sys
run_dir, t0, game, profile = pathlib.Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4]
checks = []
hist = run_dir / "mev-history.jsonl"
if hist.exists():
    for line in hist.read_text().splitlines():
        if line.strip():
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue  # The agent may still be writing the last record.
            d["elapsed_hours"] = round(max(0.0, (d.get("ts", t0) - t0) / 3600.0), 4)
            checks.append(d)
checkpoints = []
for p in sorted(run_dir.glob("checkpoint-*/grade/summary.json")) + sorted(run_dir.glob("final/grade/summary.json")):
    cp_dir = p.parent.parent
    name = cp_dir.name
    s = json.loads(p.read_text())
    captured = int((cp_dir / "snapshot-epoch").read_text())
    entry = {
        "name": name,
        "elapsed_hours": round(max(0.0, (captured - t0) / 3600.0), 4),
        "workload_set": s.get("workload_set"),
        "status": s.get("status"),
        "rewards": s.get("rewards", {}),
        "speedups": s.get("speedups", {}),
        "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in s.get("profiles", {}).items()},
    }
    lv_sum = cp_dir / "last-valid-grade" / "summary.json"
    lv_sha = cp_dir / "last-valid-commit"
    if lv_sum.exists():
        ls = json.loads(lv_sum.read_text())
        entry["last_valid"] = {
            "git_head": lv_sha.read_text().strip() if lv_sha.exists() else None,
            "status": ls.get("status"),
            "rewards": ls.get("rewards", {}),
            "speedups": ls.get("speedups", {}),
            "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in ls.get("profiles", {}).items()},
        }
    checkpoints.append(entry)
(run_dir / "trajectory.json").write_text(json.dumps({
    "run": run_dir.name, "game": game, "primary_profile": profile,
    "mev_checks": checks, "host_checkpoints": checkpoints,
}, indent=1))
PY
  log "checkpoint $name: $(python3 -c "import json;s=json.load(open('$dir/grade/summary.json'));p=s.get('profiles',{}).get('$PROFILE',{});print(s['status'],'reward=',p.get('reward'),'speedup=',p.get('speedup'),'vs_o2=',p.get('vs_o2_speedup'))" 2>/dev/null || echo 'no summary')"
  if [ -f "$dir/last-valid-grade/summary.json" ]; then
    log "checkpoint $name (last valid commit $last_valid_commit): $(python3 -c "import json;s=json.load(open('$dir/last-valid-grade/summary.json'));p=s.get('profiles',{}).get('$PROFILE',{});print(s['status'],'reward=',p.get('reward'),'speedup=',p.get('speedup'),'vs_o2=',p.get('vs_o2_speedup'))" 2>/dev/null || echo 'no summary')"
  fi
}

AGENT_PID=""; AGENT_LOG=""; AGENT_STARTED=0; N=0
start_agent() {
  N=$((N + 1)); AGENT_LOG="$RUN_DIR/agent-$(printf %03d $N).log"; AGENT_STARTED=$(now)
  local prompt="$PROMPT"; [ "$N" -gt 1 ] && prompt="$CONTINUE_PROMPT"
  log "starting agent invocation $N"
  # Drop omp's high-volume streaming delta lines (`tool_execution_update` and
  # `message_update` balloon logs to 100-800 MB) while preserving every full
  # message (`message_start`/`message_end`), tool call, and tool result.
  dc exec -T -e "MEV_DEADLINE_EPOCH=$DEADLINE" task setsid --wait bash -lc \
    "echo \$\$ > /tmp/mev-agent-pgid; $AGENT_CMD $(printf '%q' "$prompt")" 2>&1 \
    | awk 'index($0, "\"type\":\"tool_execution_update\"") == 0 && index($0, "\"type\":\"message_update\"") == 0 { print; fflush() }' > "$AGENT_LOG" &
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
trap 'stop_agent; commit; log "interrupted"; exit 130' INT TERM

START=$(now); DEADLINE=$((START + TOTAL_S)); NEXT_COMMIT=$((START + COMMIT_S)); NEXT_GRADE=$((START + GRADE_S)); G=0
log "run $RUN: game=$GAME, ${HOURS}h, profile=$PROFILE, AGENT_CMD: $AGENT_CMD"
start_agent
while [ "$(now)" -lt "$DEADLINE" ]; do
  sleep 10
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
    stop_agent
    [ $(( $(now) - AGENT_STARTED )) -lt 60 ] && sleep 30
    [ "$(now)" -lt "$DEADLINE" ] && start_agent
  elif [ "$STALL_S" -gt 0 ]; then
    m=$(stat -c %Y "$AGENT_LOG" 2>/dev/null || echo "$AGENT_STARTED")
    if [ $(( $(now) - m )) -gt "$STALL_S" ]; then log "agent stalled; restarting"; stop_agent; start_agent; fi
  fi
  if [ "$(now)" -ge "$NEXT_COMMIT" ]; then commit; NEXT_COMMIT=$(( $(now) + COMMIT_S )); fi
  if [ "$(now)" -ge "$NEXT_GRADE" ]; then G=$((G + 1)); grade_checkpoint "checkpoint-$G"; NEXT_GRADE=$(( $(now) + GRADE_S )); fi
done
stop_agent
grade_checkpoint final
in_task bash -c 'cd /task/game && git bundle create /tmp/game.bundle --all' >/dev/null 2>&1 && dc cp task:/tmp/game.bundle "$RUN_DIR/game.bundle" >/dev/null || true
log "done: results in $RUN_DIR"
