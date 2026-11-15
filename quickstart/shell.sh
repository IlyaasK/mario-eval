#!/usr/bin/env bash
# Interactive shell (or one-shot command) in the task container, as `agent`.
cd "$(dirname "$0")"
if [ $# -eq 0 ]; then
  exec docker compose exec task bash
fi
exec docker compose exec -T task "$@"
