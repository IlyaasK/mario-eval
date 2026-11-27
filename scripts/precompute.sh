#!/usr/bin/env bash
# Build the Super Mario 64 baseline and record its reference outputs.
# Skips in <0.1s when runner + harness + corpus + replays match the cached stamp
# (pass --force to recompute unconditionally).
#   ./scripts/precompute.sh [--heldout DIR] [--cache DIR] [--force]
set -euo pipefail
main() {
  local REPO HELDOUT="" CACHE="cache/sm64-reference" FORCE=0
  REPO=$(cd "$(dirname "$0")/.." && pwd)
  cd "$REPO"
  while [ $# -gt 0 ]; do
    case "$1" in
      --game)
        [ "${2:-}" = "sm64" ] || { echo "error: mario-eval v4 is Super Mario 64 only" >&2; exit 2; }
        shift 2
        ;;
      --heldout) HELDOUT=$(realpath "$2"); shift 2 ;;
      --cache) CACHE="$2"; shift 2 ;;
      --force) FORCE=1; shift ;;
      *) echo "usage: $0 [--heldout DIR] [--cache DIR] [--force]" >&2; exit 2 ;;
    esac
  done

  local SRC="sm64/decomp" CORPUS="sm64/corpus" CACHE_DIR
  if [[ "$CACHE" = /* ]]; then
    CACHE_DIR="$CACHE"
  else
    CACHE_DIR="$REPO/$CACHE"
  fi

  # Editing TASK.md, grader/*.py, tools/mev.py, grader.json weights, or site/ NEVER invalidates precompute!
  local STAMP_INPUTS=(runner sm64/harness sm64/patches "$CORPUS/replays" "$CORPUS/variants")
  if [ -n "$HELDOUT" ]; then
    STAMP_INPUTS+=("$HELDOUT")
  fi
  local STAMP
  STAMP="$(
    {
      find "${STAMP_INPUTS[@]}" -type f -print0 | LC_ALL=C sort -z | xargs -0 sha256sum
      python3 -c 'import json, pathlib; c = json.loads(pathlib.Path("sm64/corpus/grader.json").read_text()); print(json.dumps({"workloads": c.get("workloads"), "accepted_visual_variants": c.get("accepted_visual_variants"), "o2_reference_patch": c.get("o2_reference_patch")}, sort_keys=True))'
    } | sha256sum | cut -d' ' -f1
  )"

  if [ "$FORCE" -eq 0 ] && [ -f "$CACHE_DIR/index.json" ] && [ -f "$CACHE_DIR/baseline.z64" ] && [ -f "$CACHE_DIR/.precompute.stamp" ] && [ "$(cat "$CACHE_DIR/.precompute.stamp")" = "$STAMP" ]; then
    echo "✓ reference cache up to date ($CACHE_DIR) — skipped in <0.1s (pass --force to rebuild)"
    return 0
  fi

  local ARGS=(--split public) MOUNTS=() CACHE_ARG
  if [ -n "$HELDOUT" ]; then
    MOUNTS+=(-v "$HELDOUT":/heldout:ro)
    ARGS=(--split all --heldout /heldout)
  fi

  rm -rf "$CACHE_DIR"
  mkdir -p "$CACHE_DIR"
  if [[ "$CACHE" = /* ]]; then
    MOUNTS+=(-v "$CACHE_DIR":/cache_out)
    CACHE_ARG="/cache_out"
  else
    CACHE_ARG="$CACHE"
  fi

  docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo "${MOUNTS[@]}" -w /repo mario-eval \
    python3 -m grader.grade precompute "$SRC" --corpus "$CORPUS" --cache "$CACHE_ARG" "${ARGS[@]}"
  printf '%s\n' "$STAMP" > "$CACHE_DIR/.precompute.stamp"
}
main "$@"
