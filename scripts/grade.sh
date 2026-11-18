#!/usr/bin/env bash
# Grade a workload source directory (or extract /task/game from the running task container).
#
# Usage:
#   ./scripts/grade.sh [--game pips-garden|sm64] SUBMISSION_DIR OUT_DIR [extra grader args]
#   ./scripts/grade.sh [--game pips-garden|sm64] --from-container OUT_DIR [extra grader args]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
GAME="pips-garden"
FROM_CONTAINER=0

while [ $# -gt 0 ]; do
  case "$1" in
    --game) GAME="$2"; shift 2 ;;
    --from-container) FROM_CONTAINER=1; shift ;;
    -h|--help) sed -n '2,6p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) break ;;
  esac
done

case "$GAME" in
  pips-garden) CORPUS="corpus"; CACHE="cache/reference" ;;
  sm64)        CORPUS="sm64/corpus"; CACHE="cache/sm64-reference" ;;
  *) echo "unknown --game $GAME" >&2; exit 2 ;;
esac

TMP_EXTRACT=""
cleanup() { [ -n "$TMP_EXTRACT" ] && rm -rf "$TMP_EXTRACT" || true; }
trap cleanup EXIT

if [ "$FROM_CONTAINER" -eq 1 ]; then
  [ $# -ge 1 ] || { echo "usage: $0 [--game GAME] --from-container OUT_DIR [extra grader args]" >&2; exit 2; }
  OUT=$(realpath -m "$1"); shift 1
  TMP_EXTRACT=$(mktemp -d)
  echo "→ extracting /task/game from mario-eval-task ..."
  docker compose --project-directory "$REPO/quickstart" cp task:/task/game "$TMP_EXTRACT/game"
  SUB="$TMP_EXTRACT/game"
else
  [ $# -ge 2 ] || { echo "usage: $0 [--game GAME] SUBMISSION_DIR OUT_DIR [extra grader args]" >&2; exit 2; }
  SUB=$(realpath "$1"); OUT=$(realpath -m "$2"); shift 2
fi

HELDOUT_MOUNTS=()
GRADER_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --heldout)
      HDIR=$(realpath "$2")
      HELDOUT_MOUNTS=(-v "$HDIR":/heldout:ro)
      GRADER_ARGS+=(--split all --heldout /heldout)
      shift 2
      ;;
    *) GRADER_ARGS+=("$1"); shift ;;
  esac
done

mkdir -p "$OUT"
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$REPO":/repo:ro -v "$SUB":/submission:ro -v "$OUT":/out "${HELDOUT_MOUNTS[@]}" \
  -w /repo mario-eval \
  python3 -m grader.grade grade /submission --corpus "$CORPUS" --cache "$CACHE" --out /out "${GRADER_ARGS[@]}"
