#!/usr/bin/env bash
# Supervise a timed agent run in the task container (run on the host, after
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
#   AGENT_CMD='claude -p --dangerously-skip-permissions' quickstart/run-agent.sh --hours 8 --profile speed
#   quickstart/run-agent.sh --hours 0.1 --commit-every 2 --grade-every 0.05   # smoke test
#
# Options: --hours H (default 8)  --name RUN  --profile speed|rsp|traffic|memory
#          --commit-every MIN (30)  --grade-every H (2)  --stall-minutes MIN (15)
#          --heldout DIR (held-out replays; reference must include them)
# AGENT_CMD may also be set in quickstart/.env.
set -euo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
QS="$REPO/quickstart"

HOURS=8; RUN=""; PROFILE=speed; COMMIT_MIN=30; GRADE_HOURS=2; STALL_MIN=15; HELDOUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --hours) HOURS="$2"; shift 2 ;;
    --name) RUN="$2"; shift 2 ;;
    --profile) PROFILE="$2"; shift 2 ;;
    --commit-every) COMMIT_MIN="$2"; shift 2 ;;
    --grade-every) GRADE_HOURS="$2"; shift 2 ;;
    --stall-minutes) STALL_MIN="$2"; shift 2 ;;
    --heldout) HELDOUT="$(realpath "$2")"; shift 2 ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
case "$PROFILE" in speed|rsp|traffic|memory) ;; *) echo "bad --profile $PROFILE" >&2; exit 2 ;; esac
if [ -z "${AGENT_CMD:-}" ] && [ -f "$QS/.env" ]; then
  AGENT_CMD="$(sed -n 's/^AGENT_CMD=//p' "$QS/.env" | tail -n 1)"
fi
[ -n "${AGENT_CMD:-}" ] || { echo "error: set AGENT_CMD" >&2; exit 2; }

secs() { awk -v x="$1" -v m="$2" 'BEGIN { v = x * m; if (v < 1) v = 1; printf "%d", v }'; }
TOTAL_S=$(secs "$HOURS" 3600); COMMIT_S=$(secs "$COMMIT_MIN" 60)
GRADE_S=$(secs "$GRADE_HOURS" 3600); STALL_S=$(( STALL_MIN * 60 ))

RUN="${RUN:-run-$(date -u +%Y%m%dT%H%M%SZ)}"
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
PROMPT="$(in_task cat /task/TASK.md)"$'\n\n'"Your profile for this run: $PROFILE (also in /task/PROFILE). You have ${HOURS} hours."
CONTINUE_PROMPT="Continue working on the task in /task/TASK.md (profile: $PROFILE). Run 'mev check' to see where you stand, commit your work in /task/game, and keep improving."

commit() {
  in_task bash -c 'cd /task/game && git add -A && git -c user.name=agent -c user.email=agent@mario-eval commit -qm "checkpoint $(date -u +%FT%TZ)" 2>/dev/null || true'
}

grade_checkpoint() {
  local name="$1" dir="$RUN_DIR/$1"
  mkdir -p "$dir"
  commit
  rm -rf "$dir/src"
  dc cp task:/task/game "$dir/src" >/dev/null
  rm -rf "$dir/src/.git" "$dir/src/build"
  local args=() mounts=()
  if [ -n "$HELDOUT" ]; then args=(--split all --heldout /heldout); mounts=(-v "$HELDOUT":/heldout:ro); fi
  docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo:ro -v "$dir/src":/submission:ro \
    -v "$dir":/out "${mounts[@]}" -w /repo mario-eval \
    python3 -m grader.grade grade /submission --corpus corpus --cache cache/reference --out /out/grade "${args[@]}" \
    > "$dir/grade.txt" 2>&1 || true
  log "checkpoint $name: $(python3 -c "import json;s=json.load(open('$dir/grade/summary.json'));print(s['status'], s.get('rewards',{}).get('$PROFILE'))" 2>/dev/null || echo 'no summary')"
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
log "run $RUN: ${HOURS}h, profile $PROFILE, AGENT_CMD: $AGENT_CMD"
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
