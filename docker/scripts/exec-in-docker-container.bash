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

if [[ "$CONTAINER_NAME" == cotyaka-* ]]; then
    if ! docker ps --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
        echo "[ERROR] $CONTAINER_NAME コンテナは起動していません"
        echo "[ERROR] 自動起動・再起動は行いません。bash scripts/robot_core.sh status で確認してください"
        exit 1
    fi

    echo "[INFO] exec into container: $CONTAINER_NAME"
    if [ $# -eq 0 ]; then
        echo "[INFO] command: bash"
        echo "----------------------------------------"
        docker exec -it "$CONTAINER_NAME" bash
    else
        USER_COMMAND="$*"
        echo "[INFO] command: $USER_COMMAND"
        echo "----------------------------------------"
        docker exec -it "$CONTAINER_NAME" bash -lc "$USER_COMMAND; exec bash"
    fi
    exit 0
fi

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
