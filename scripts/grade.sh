#!/usr/bin/env bash
# grade.sh SUBMISSION_DIR OUT_DIR [extra grader args]
# Grades a workload source tree inside the mario-eval image.
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
SUB=$(realpath "$1"); OUT=$(realpath -m "$2"); shift 2
mkdir -p "$OUT"
docker run --rm -u "$(id -u):$(id -g)" \
  -v "$REPO":/repo:ro -v "$SUB":/submission:ro -v "$OUT":/out \
  -w /repo mario-eval \
  python3 -m grader.grade grade /submission --corpus corpus --cache cache/reference --out /out "$@"
