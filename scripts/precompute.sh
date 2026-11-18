#!/usr/bin/env bash
# Build the baseline and record its reference outputs.
#   scripts/precompute.sh [--game pips-garden|sm64] [--heldout DIR]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
GAME="pips-garden"
HELDOUT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --game) GAME="$2"; shift 2 ;;
    --heldout) HELDOUT=$(realpath "$2"); shift 2 ;;
    *) echo "usage: $0 [--game pips-garden|sm64] [--heldout DIR]" >&2; exit 2 ;;
  esac
done

case "$GAME" in
  pips-garden) SRC="workload"; CORPUS="corpus"; CACHE="cache/reference" ;;
  sm64)        SRC="sm64/decomp"; CORPUS="sm64/corpus"; CACHE="cache/sm64-reference" ;;
  *) echo "unknown --game $GAME (expected pips-garden or sm64)" >&2; exit 2 ;;
esac

ARGS=(--split public)
MOUNTS=()
if [ -n "$HELDOUT" ]; then
  MOUNTS=(-v "$HELDOUT":/heldout:ro)
  ARGS=(--split all --heldout /heldout)
fi
rm -rf "$REPO/$CACHE"
mkdir -p "$REPO/$CACHE"
docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo "${MOUNTS[@]}" -w /repo mario-eval \
  python3 -m grader.grade precompute "$SRC" --corpus "$CORPUS" --cache "$CACHE" "${ARGS[@]}"
