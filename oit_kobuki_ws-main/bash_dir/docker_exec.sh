#!/bin/bash

set -euo pipefail

if [ "$#" -lt 1 ]; then
    echo "Usage: $0 <script_path_inside_repo> [args...]"
    exit 1
fi

SCRIPT_PATH="$1"
shift || true

if [ -z "${KOBUKI_WS_HOST:-}" ]; then
    echo "KOBUKI_WS_HOST is not set."
    exit 1
fi

cd "$KOBUKI_WS_HOST"

CMD="cd /home/user25/kobuki_ws && bash \"$SCRIPT_PATH\""
for arg in "$@"; do
    printf -v CMD '%s %q' "$CMD" "$arg"
done

docker compose exec -it ros2_humble bash -lc "$CMD"
