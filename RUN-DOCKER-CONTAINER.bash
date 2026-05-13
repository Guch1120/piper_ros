#!/usr/bin/env bash

set -e

# ============================================================
# RUN-DOCKER-CONTAINER.bash
#
# ホスト側で実行する。
# 1. プロジェクトルートへ移動
# 2. xhost 設定
# 3. Dockerコンテナ起動
# 4. プロジェクト専用Terminator設定で layout を起動
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

# KILL_ROS_NODES_SCRIPT="./docker/scripts/kill-ros-nodes.bash"
DOCKER_COMPOSE_PATH="./docker/docker-compose.yml"
DOCKER_CONTAINER_NAME="piper-humble-dev"
TERMINATOR_CONFIG=".config/terminator/config"
TERMINATOR_LAYOUT="piper-arm"

echo "[INFO] project dir: $PROJECT_DIR"

xhost +local:docker

if docker compose -f "$DOCKER_COMPOSE_PATH" ps "$DOCKER_CONTAINER_NAME" --status running | grep -q "$DOCKER_CONTAINER_NAME"; then
    echo "[INFO] $DOCKER_CONTAINER_NAME コンテナは既に起動中"
else
    echo "[INFO] $DOCKER_CONTAINER_NAME コンテナを起動"
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$DOCKER_CONTAINER_NAME"
fi

if [ ! -f "$TERMINATOR_CONFIG" ]; then
    echo "[ERROR] Terminator config が見つかりません: $TERMINATOR_CONFIG"
    echo "[ERROR] docker/terminator/config にプロジェクト専用のTerminator設定を置いてください"
    exit 1
fi

echo "[INFO] ホスト側で Terminator を起動します..."
echo "[INFO] config: $TERMINATOR_CONFIG"
echo "[INFO] layout: $TERMINATOR_LAYOUT"

exec terminator -g "$TERMINATOR_CONFIG" -l "$TERMINATOR_LAYOUT"