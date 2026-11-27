#!/usr/bin/env bash
# Grade a Super Mario 64 source directory (or extract /task/game from the task container).
# PLAY=1 build + cold-boot runtime smoke is enabled by default (pass --no-play-smoke to skip).
#
# Usage:
#   ./scripts/grade.sh SUBMISSION_DIR OUT_DIR [--heldout DIR] [--no-play-smoke] [extra grader args]
#   ./scripts/grade.sh --from-container OUT_DIR [--heldout DIR] [--no-play-smoke] [extra grader args]
set -euo pipefail
REPO=$(cd "$(dirname "$0")/.." && pwd)
FROM_CONTAINER=0

while [ $# -gt 0 ]; do
  case "$1" in
    --game)
      [ "${2:-}" = "sm64" ] || { echo "error: mario-eval v4 is Super Mario 64 only" >&2; exit 2; }
      shift 2
      ;;
    --from-container) FROM_CONTAINER=1; shift ;;
    -h|--help) sed -n '2,7p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) break ;;
  esac
done

CORPUS="sm64/corpus"
CACHE="cache/sm64-reference"

CACHE_MOUNTS=()
if [ -n "${MEV_REFERENCE_DIR:-}" ]; then
  CACHE_MOUNTS=(--mount "type=bind,src=$(realpath "$MEV_REFERENCE_DIR"),dst=/reference,readonly")
  CACHE=/reference
fi

TMP_EXTRACT=""
cleanup() { [ -n "$TMP_EXTRACT" ] && rm -rf "$TMP_EXTRACT" || true; }
trap cleanup EXIT

if [ "$FROM_CONTAINER" -eq 1 ]; then
  [ $# -ge 1 ] || { echo "usage: $0 --from-container OUT_DIR [extra grader args]" >&2; exit 2; }
  OUT=$(realpath -m "$1"); shift 1
  TMP_EXTRACT=$(mktemp -d)
  echo "→ extracting /task/game from mario-eval-task ..."
  docker compose --project-directory "$REPO/quickstart" cp task:/task/game "$TMP_EXTRACT/game"
  SUB="$TMP_EXTRACT/game"
else
  [ $# -ge 2 ] || { echo "usage: $0 SUBMISSION_DIR OUT_DIR [extra grader args]" >&2; exit 2; }
  SUB=$(realpath "$1"); OUT=$(realpath -m "$2"); shift 2
fi

HELDOUT_MOUNTS=()
GRADER_ARGS=()
PLAY_SMOKE=1
while [ $# -gt 0 ]; do
  case "$1" in
    --heldout)
      HDIR=$(realpath "$2")
      HELDOUT_MOUNTS=(-v "$HDIR":/heldout:ro)
      GRADER_ARGS+=(--split all --heldout /heldout)
      shift 2
      ;;
    --play-smoke) PLAY_SMOKE=1; shift ;;
    --no-play-smoke) PLAY_SMOKE=0; shift ;;
    *) GRADER_ARGS+=("$1"); shift ;;
  esac
done

BUILD_ARGS=()
if [ "$PLAY_SMOKE" -eq 1 ]; then
  BUILD_ARGS+=(--play-smoke)
  GRADER_ARGS+=(--play-smoke)
fi

ENV_ARGS=()
if [ -n "${MEV_JOBS:-}" ]; then
  ENV_ARGS=(-e "MEV_JOBS=$MEV_JOBS")
fi

mkdir -p "$OUT"
# The build container never receives grader inputs, held-out replays or the
# reference cache. Measurement runs only after the build container exits.
BUILD=$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/mev-submission.XXXXXX")
HANDOFF_SAFE=$(mktemp -d "${XDG_CACHE_HOME:-$HOME/.cache}/mev-handoff.XXXXXX")
chmod 0700 "$BUILD" "$HANDOFF_SAFE"
trap 'rm -rf "$BUILD" "$HANDOFF_SAFE"; cleanup' EXIT
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  -u "$(id -u):$(id -g)" "${ENV_ARGS[@]}" -v "$SUB":/submission:ro \
  -v "$REPO/$CORPUS/grader.json":/build-config.json:ro -v "$BUILD":/handoff \
  mario-eval python3 -m grader.grade build /submission --config /build-config.json --out /handoff "${BUILD_ARGS[@]}"
for f in error.txt built.z64 built.idle.json built.meta.json play.z64 build.log; do
  if [ -f "$BUILD/$f" ] && [ ! -L "$BUILD/$f" ]; then
    cp --remove-destination "$BUILD/$f" "$HANDOFF_SAFE/$f"
    chmod 0444 "$HANDOFF_SAFE/$f"
  fi
done
if [ -f "$HANDOFF_SAFE/build.log" ]; then
  cp --remove-destination "$HANDOFF_SAFE/build.log" "$OUT/build.log"
fi
docker run --rm --network none --cap-drop ALL --security-opt no-new-privileges \
  -u "$(id -u):$(id -g)" "${ENV_ARGS[@]}" \
  -v "$REPO":/repo:ro -v "$SUB":/submission:ro -v "$OUT":/out \
  -v "$HANDOFF_SAFE":/handoff:ro "${CACHE_MOUNTS[@]}" "${HELDOUT_MOUNTS[@]}" \
  -w /repo mario-eval \
  python3 -m grader.grade grade /submission --built /handoff --corpus "$CORPUS" --cache "$CACHE" --out /out "${GRADER_ARGS[@]}"
