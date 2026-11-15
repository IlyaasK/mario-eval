#!/usr/bin/env bash
# Build every image, in dependency order:
#   mario-eval-toolchain  libdragon toolchain (pinned)
#   mario-eval-runner     ares + instrumentation patch + n64run (pinned)
#   mario-eval            toolchain + n64run + grader (grading image)
#   mario-eval-task       agent container (adds game source, public corpus,
#                         baseline reference; needs cache/reference, see README)
#   mario-eval-proxy      egress allowlist proxy
set -euo pipefail
cd "$(dirname "$0")/.."
docker build -t mario-eval-toolchain toolchain
docker build -t mario-eval-runner runner
docker build -t mario-eval .
if [ "${1:-}" != "--no-task" ]; then
  [ -f cache/reference/index.json ] || {
    echo "cache/reference missing: run scripts/precompute.sh first" >&2; exit 1; }
  docker build -t mario-eval-task -f quickstart/task/Dockerfile .
  docker build -t mario-eval-proxy quickstart/proxy
fi
