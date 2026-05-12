#!/usr/bin/env bash
set -e

# ============================================================
# exec-docker-container.bash
#
# 使い方1: ホスト側でプロジェクト専用Terminatorを起動
#   bash ./docker/scripts/exec-docker-container.bash --terminator
#
# 使い方2: Terminator profileのcustom_commandからコンテナ内でコマンド実行
#   bash ./docker/scripts/exec-docker-container.bash piper-humble-dev "ros2 topic list"
#
# 使い方3: コマンドなしでコンテナに入る
#   bash ./docker/scripts/exec-docker-container.bash piper-humble-dev
# ============================================================


# ------------------------------------------------------------
# このスクリプト自身の場所からプロジェクトルートを求める
# ------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

DOCKER_COMPOSE_PATH="$PROJECT_DIR/docker/docker-compose.yml"
TERMINATOR_CONFIG="$PROJECT_DIR/docker/terminator/config"
TERMINATOR_LAYOUT="${TERMINATOR_LAYOUT:-piper-arm}"

# composeの相対パス、volumeの相対パスを安定させるために
# 必ずプロジェクトルートへ移動してから実行する
cd "$PROJECT_DIR"


# ------------------------------------------------------------
# mode 1: ホスト側でTerminatorを起動する
# ------------------------------------------------------------
if [ "${1:-}" = "--terminator" ]; then
    xhost +local:docker

    if [ ! -f "$DOCKER_COMPOSE_PATH" ]; then
        echo "[ERROR] docker-compose.yml not found: $DOCKER_COMPOSE_PATH"
        exit 1
    fi

    if [ ! -f "$TERMINATOR_CONFIG" ]; then
        echo "[ERROR] terminator config not found: $TERMINATOR_CONFIG"
        echo "Expected: docker/terminator/config"
        exit 1
    fi

    # 必要ならここで複数コンテナを起動する
    # 例:
    # docker compose -f "$DOCKER_COMPOSE_PATH" up -d piper-humble-dev sam3-dev graspgen-ros1

    docker compose -f "$DOCKER_COMPOSE_PATH" up -d piper-humble-dev

    echo "[INFO] launch Terminator on host"
    echo "[INFO] config: $TERMINATOR_CONFIG"
    echo "[INFO] layout: $TERMINATOR_LAYOUT"

    exec terminator -g "$TERMINATOR_CONFIG" -l "$TERMINATOR_LAYOUT"
fi


# ------------------------------------------------------------
# mode 2: 指定コンテナ内でコマンドを実行する
# ------------------------------------------------------------
CONTAINER_NAME="${1:-}"

if [ -z "$CONTAINER_NAME" ]; then
    echo "[ERROR] container name is required"
    echo
    echo "usage:"
    echo "  bash ./docker/scripts/exec-docker-container.bash --terminator"
    echo "  bash ./docker/scripts/exec-docker-container.bash <container_name> [command...]"
    exec bash
fi

shift

if [ $# -eq 0 ]; then
    USER_COMMAND="bash"
else
    USER_COMMAND="$*"
fi

if [ ! -f "$DOCKER_COMPOSE_PATH" ]; then
    echo "[ERROR] docker-compose.yml not found: $DOCKER_COMPOSE_PATH"
    exec bash
fi

if ! docker compose -f "$DOCKER_COMPOSE_PATH" ps "$CONTAINER_NAME" --status running | grep -q "$CONTAINER_NAME"; then
    echo "[INFO] starting container: $CONTAINER_NAME"
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$CONTAINER_NAME"
fi

echo "[INFO] exec into container: $CONTAINER_NAME"
echo "[INFO] command: $USER_COMMAND"

docker compose -f "$DOCKER_COMPOSE_PATH" exec "$CONTAINER_NAME" bash -lc "$USER_COMMAND; exec bash" 