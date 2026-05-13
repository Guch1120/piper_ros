#!/usr/bin/env bash
set -e

# ============================================================
# exec-docker-container.bash
#
# Terminatorのcustom_commandから呼ぶ。
#
# 例:
#   bash ./docker/scripts/exec-docker-container.bash piper-humble-dev
#
#   bash ./docker/scripts/exec-docker-container.bash piper-humble-dev \
#     "bash /ros2_ws/run_ros_cmd.sh ros2 topic list"
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

cd "$PROJECT_DIR"

DOCKER_COMPOSE_PATH="./docker/docker-compose.yml"

CONTAINER_NAME="${1:-}"

if [ -z "$CONTAINER_NAME" ]; then
    echo "[ERROR] container name is required"
    echo "usage:"
    echo "  bash ./docker/scripts/exec-docker-container.bash <container_name> [command...]"
    exec bash
fi

shift

if [ $# -eq 0 ]; then
    USER_COMMAND="bash"
else
    USER_COMMAND="$*"
fi

if ! docker compose -f "$DOCKER_COMPOSE_PATH" ps "$CONTAINER_NAME" --status running | grep -q "$CONTAINER_NAME"; then
    echo "[INFO] starting container: $CONTAINER_NAME"
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$CONTAINER_NAME"
fi

echo "[INFO] exec into container: $CONTAINER_NAME"
echo "[INFO] command: $USER_COMMAND"

docker compose -f "$DOCKER_COMPOSE_PATH" exec "$CONTAINER_NAME" bash -lc "$USER_COMMAND; exec bash"