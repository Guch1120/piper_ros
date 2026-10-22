#!/usr/bin/env bash
# FlexBE App (ROS 2 Humble): enqueue a state/behavior file for host VS Code.
# FlexBE editor setting: bash /ros2_ws/docker/scripts/open-in-host-vscode.bash $FILE
set -euo pipefail

CONTAINER_ROOT="${FLEXBE_CONTAINER_ROOT:-/ros2_ws}"
REQUEST_DIR="${FLEXBE_REQUEST_DIR:-$CONTAINER_ROOT/.flexbe/open-requests}"

if (( $# != 1 )); then
    printf '[flexbe-vscode] Usage: %s /absolute/path/to/source.py\n' "$0" >&2
    exit 2
fi

if [[ ! -d "$REQUEST_DIR" || -L "$REQUEST_DIR" ]]; then
    printf '[flexbe-vscode] Missing or unsafe request directory: %s\n' "$REQUEST_DIR" >&2
    exit 1
fi

root="$(realpath -e -- "$CONTAINER_ROOT")" || exit 1
file="$(realpath -e -- "$1")" || {
    printf '[flexbe-vscode] Source does not exist: %s\n' "$1" >&2
    exit 1
}

case "$file" in
    "$root"/*.py) ;;
    *) printf '[flexbe-vscode] Refusing file outside workspace or non-Python file: %s\n' "$file" >&2
       exit 1 ;;
esac
[[ -f "$file" ]] || { printf '[flexbe-vscode] Not a regular file: %s\n' "$file" >&2; exit 1; }

# Same-directory atomic rename means the watcher never observes partial content.
# mktemp uses 0600, so change to 0644 for the host user to read Docker-root files.
tmp="$(mktemp "$REQUEST_DIR/.pending.XXXXXXXXXX")"
trap 'rm -f -- "$tmp"' EXIT
printf '%s\n' "$file" > "$tmp"
chmod 0644 -- "$tmp"
request="$REQUEST_DIR/request-$(date +%s%N)-$$-$RANDOM.req"
mv -- "$tmp" "$request"
