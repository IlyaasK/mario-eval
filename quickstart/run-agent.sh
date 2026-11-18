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
#          --name RUN  --profile console|speed|rdp|rsp|traffic|memory (default console)
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
case "$PROFILE" in console|speed|rdp|rsp|traffic|memory) ;; *) echo "bad --profile $PROFILE (expected console|speed|rdp|rsp|traffic|memory)" >&2; exit 2 ;; esac
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
PROMPT="$(in_task cat /task/TASK.md)"$'\n\n'"Your primary profile for this run: $PROFILE (also in /task/PROFILE). You have ${HOURS} hours."
CONTINUE_PROMPT="Continue working on the 24h optimization task in /task/TASK.md (profile: $PROFILE). Run 'mev check' to see your current reward, speedup, and vs_o2_speedup, commit working milestones in /task/game, and keep pushing hardware performance further."

commit() {
  in_task bash -c 'cd /task/game && git add -A && git -c user.name=agent -c user.email=agent@mario-eval commit -qm "checkpoint $(date -u +%FT%TZ)" 2>/dev/null || true'
}

grade_checkpoint() {
  local name="$1" dir="$RUN_DIR/$1"
  mkdir -p "$dir"
  commit
  rm -rf "$dir/src"
  dc cp task:/task/game "$dir/src" >/dev/null
  rm -rf "$dir/src/.git" "$dir/src/build" "$dir/src/build_"*
  local args=() mounts=()
  if [ -n "$HELDOUT" ]; then args=(--split all --heldout /heldout); mounts=(-v "$HELDOUT":/heldout:ro); fi
  docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo:ro -v "$dir/src":/submission:ro \
    -v "$dir":/out "${mounts[@]}" -w /repo mario-eval \
    python3 -m grader.grade grade /submission --corpus "$CORPUS" --cache "$CACHE" --out /out/grade "${args[@]}" \
    > "$dir/grade.txt" 2>&1 || true
  dc cp task:/task/.mev-history.jsonl "$RUN_DIR/mev-history.jsonl" >/dev/null 2>&1 || true
  python3 - "$RUN_DIR" "$START" "$GAME" "$PROFILE" <<'PY' || true
import glob, json, os, pathlib, sys
run_dir, t0, game, profile = pathlib.Path(sys.argv[1]), float(sys.argv[2]), sys.argv[3], sys.argv[4]
checks = []
hist = run_dir / "mev-history.jsonl"
if hist.exists():
    for line in hist.read_text().splitlines():
        if line.strip():
            d = json.loads(line)
            d["elapsed_hours"] = round(max(0.0, (d.get("ts", t0) - t0) / 3600.0), 4)
            checks.append(d)
checkpoints = []
for p in sorted(run_dir.glob("checkpoint-*/grade/summary.json")) + sorted(run_dir.glob("final/grade/summary.json")):
    name = p.parent.parent.name
    s = json.loads(p.read_text())
    mtime = p.stat().st_mtime
    checkpoints.append({
        "name": name,
        "elapsed_hours": round(max(0.0, (mtime - t0) / 3600.0), 4),
        "status": s.get("status"),
        "rewards": s.get("rewards", {}),
        "speedups": s.get("speedups", {}),
        "vs_o2_speedups": {k: v.get("vs_o2_speedup") for k, v in s.get("profiles", {}).items()},
    })
(run_dir / "trajectory.json").write_text(json.dumps({
    "run": run_dir.name, "game": game, "primary_profile": profile,
    "mev_checks": checks, "host_checkpoints": checkpoints,
}, indent=1))
PY
  log "checkpoint $name: $(python3 -c "import json;s=json.load(open('$dir/grade/summary.json'));p=s.get('profiles',{}).get('$PROFILE',{});print(s['status'],'reward=',p.get('reward'),'speedup=',p.get('speedup'),'vs_o2=',p.get('vs_o2_speedup'))" 2>/dev/null || echo 'no summary')"
}

AGENT_PID=""; AGENT_LOG=""; AGENT_STARTED=0; N=0
start_agent() {
  N=$((N + 1)); AGENT_LOG="$RUN_DIR/agent-$(printf %03d $N).log"; AGENT_STARTED=$(now)
  local prompt="$PROMPT"; [ "$N" -gt 1 ] && prompt="$CONTINUE_PROMPT"
  log "starting agent invocation $N"
  dc exec -T task bash -lc "$AGENT_CMD $(printf '%q' "$prompt")" > "$AGENT_LOG" 2>&1 &
  AGENT_PID=$!
}
stop_agent() {
  [ -n "$AGENT_PID" ] && kill "$AGENT_PID" 2>/dev/null || true
  in_task pkill -u agent -f -- "${AGENT_CMD%% *}" 2>/dev/null || true
  wait "$AGENT_PID" 2>/dev/null || true; AGENT_PID=""
}
trap 'stop_agent; commit; log "interrupted"; exit 130' INT TERM

START=$(now); DEADLINE=$((START + TOTAL_S)); NEXT_COMMIT=$((START + COMMIT_S)); NEXT_GRADE=$((START + GRADE_S)); G=0
log "run $RUN: game=$GAME, ${HOURS}h, profile=$PROFILE, AGENT_CMD: $AGENT_CMD"
start_agent
while [ "$(now)" -lt "$DEADLINE" ]; do
  sleep 10
  if ! kill -0 "$AGENT_PID" 2>/dev/null; then
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
