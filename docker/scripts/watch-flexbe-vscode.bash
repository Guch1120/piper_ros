#!/usr/bin/env bash
# Host-side watcher. Start/stop with RUN-DOCKER-CONTAINER.bash, not .bashrc.
set -euo pipefail

HOST_ROOT="${1:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
CONTAINER_ROOT="${FLEXBE_CONTAINER_ROOT:-/ros2_ws}"
REQUEST_DIR="${FLEXBE_REQUEST_DIR:-$HOST_ROOT/.flexbe/open-requests}"
POLL_INTERVAL="${FLEXBE_POLL_INTERVAL:-0.5}"

if ! command -v code >/dev/null 2>&1; then
    echo '[flexbe-vscode] code command not found in host PATH' >&2
    exit 1
fi

# Only the logged-in host user should create/control this request directory.
umask 077
if [[ -L "$REQUEST_DIR" ]]; then
    printf '[flexbe-vscode] Refusing symlink request directory: %s\n' "$REQUEST_DIR" >&2
    exit 1
fi
mkdir -p -- "$REQUEST_DIR"
chmod 0700 -- "$REQUEST_DIR"
host_root_real="$(realpath -e -- "$HOST_ROOT")"
printf '[flexbe-vscode] Watching %s\n' "$REQUEST_DIR" >&2

trap 'exit 0' INT TERM

process_request() {
    local req="$1" container_file candidate file

    if [[ -L "$req" ]]; then
        printf '[flexbe-vscode] Rejecting symlink request: %s\n' "$req" >&2
        rm -f -- "$req"
        return 0
    fi
    if ! IFS= read -r container_file < "$req"; then
        printf '[flexbe-vscode] Empty/unreadable request: %s\n' "$req" >&2
        rm -f -- "$req"
        return 0
    fi

    case "$container_file" in
        "$CONTAINER_ROOT"/*) ;;
        *) printf '[flexbe-vscode] Rejecting path outside container root: %s\n' "$container_file" >&2
           rm -f -- "$req"; return 0 ;;
    esac

    candidate="$HOST_ROOT/${container_file#"$CONTAINER_ROOT"/}"
    if ! file="$(realpath -e -- "$candidate")"; then
        printf '[flexbe-vscode] Host file not found: %s\n' "$candidate" >&2
        rm -f -- "$req"; return 0
    fi
    case "$file" in
        "$host_root_real"/*.py) ;;
        *) printf '[flexbe-vscode] Rejecting file outside host root or non-Python file: %s\n' "$file" >&2
           rm -f -- "$req"; return 0 ;;
    esac
    if [[ ! -f "$file" ]]; then
        printf '[flexbe-vscode] Not a regular host file: %s\n' "$file" >&2
        rm -f -- "$req"; return 0
    fi

    if code --reuse-window "$file"; then
        printf '[flexbe-vscode] Opened: %s\n' "$file" >&2
    else
        printf '[flexbe-vscode] Failed to open: %s\n' "$file" >&2
    fi
    rm -f -- "$req"
}

while :; do
    for req in "$REQUEST_DIR"/*.req; do
        [[ -f "$req" || -L "$req" ]] || continue
        # Atomic claim prevents two watcher instances from opening a request twice.
        claimed="$req.processing.$$"
        if mv -- "$req" "$claimed" 2>/dev/null; then
            process_request "$claimed"
        fi
    done
    sleep "$POLL_INTERVAL"
done
