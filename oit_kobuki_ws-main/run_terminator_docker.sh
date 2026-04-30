#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

DOCKER_COMPOSE_PATH="$SCRIPT_DIR/docker-compose.yml"
DOCKER_SERVICE_NAME="ros2_humble"
ON_ENTER_CONTAINER_SCRIPT="/home/kobuki/kobuki_ws/docker/scripts/initialize-kobuki-container.bash"

usage() {
    cat <<'EOF'
Usage: ./RUN-KOBUKI-CONTAINER.bash [--build]

  --build   Build the Docker image before starting the container
EOF
}

DO_BUILD=0
while [ "$#" -gt 0 ]; do
    case "$1" in
        --build)
            DO_BUILD=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage
            exit 1
            ;;
    esac
done

cd "$SCRIPT_DIR"

if command -v xhost >/dev/null 2>&1; then
    xhost +local:docker >/dev/null 2>&1 || true
fi

if [ -z "${XAUTHORITY:-}" ] && [ -f "$HOME/.Xauthority" ]; then
    export XAUTHORITY="$HOME/.Xauthority"
fi
export DISPLAY="${DISPLAY:-:0}"

if [ "$DO_BUILD" -eq 1 ]; then
    if docker ps -a --format '{{.Names}}' | grep -qx "$DOCKER_SERVICE_NAME"; then
        echo "Stopping $DOCKER_SERVICE_NAME for rebuild..."
        docker compose down
    fi
    docker compose -f "$DOCKER_COMPOSE_PATH" build --no-cache "$DOCKER_SERVICE_NAME"
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$DOCKER_SERVICE_NAME"
    docker compose -f "$DOCKER_COMPOSE_PATH" exec "$DOCKER_SERVICE_NAME" bash first_init_env.bash
fi

if docker compose -f "$DOCKER_COMPOSE_PATH" ps --status running | grep -q "$DOCKER_SERVICE_NAME"; then
    echo "$DOCKER_SERVICE_NAME is already running."
else
    echo "Starting $DOCKER_SERVICE_NAME ..."
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$DOCKER_SERVICE_NAME"
fi

echo "Launching Terminator inside container..."
exec docker compose -f "$DOCKER_COMPOSE_PATH" exec -it \
    "$DOCKER_SERVICE_NAME" \
    bash "$ON_ENTER_CONTAINER_SCRIPT"