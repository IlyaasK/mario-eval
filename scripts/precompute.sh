#!/usr/bin/env bash
# Build the baseline and record its reference outputs in cache/reference.
#   scripts/precompute.sh                      public workloads
#   scripts/precompute.sh --heldout DIR        public + held-out routes in DIR
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
ARGS=(--split public)
MOUNTS=()
if [ "${1:-}" = "--heldout" ]; then
  MOUNTS=(-v "$(realpath "$2")":/heldout:ro)
  ARGS=(--split all --heldout /heldout)
fi
mkdir -p "$REPO/cache"
docker run --rm -u "$(id -u):$(id -g)" -v "$REPO":/repo "${MOUNTS[@]}" -w /repo mario-eval \
  python3 -m grader.grade precompute workload --corpus corpus --cache cache/reference "${ARGS[@]}"
