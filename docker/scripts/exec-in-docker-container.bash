#!/usr/bin/env bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

DOCKER_COMPOSE_PATH="./docker/docker-compose.yml"

CONTAINER_NAME="${1:-}"

if [ -z "$CONTAINER_NAME" ]; then
    echo "[ERROR] container name is required"
    echo "usage:"
    echo "  bash ./docker/scripts/exec-in-docker-container.bash <container_name> [command...]"
    exit 1
fi

shift

if ! docker compose -f "$DOCKER_COMPOSE_PATH" ps "$CONTAINER_NAME" --status running | grep -q "$CONTAINER_NAME"; then
    echo "[INFO] starting container: $CONTAINER_NAME"
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$CONTAINER_NAME"
fi

echo "[INFO] exec into container: $CONTAINER_NAME"
if [ $# -eq 0 ]; then
    echo "[INFO] command: bash"
    echo "----------------------------------------"
    docker compose -f "$DOCKER_COMPOSE_PATH" exec "$CONTAINER_NAME" bash
else
    USER_COMMAND="$*"
    echo "[INFO] command: $USER_COMMAND"
    echo "----------------------------------------"
    docker compose -f "$DOCKER_COMPOSE_PATH" exec "$CONTAINER_NAME" bash -lc "$USER_COMMAND; exec bash"
fi