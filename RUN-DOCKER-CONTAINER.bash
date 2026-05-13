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
# ============================================================s

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"

cd "$PROJECT_DIR"

DOCKER_COMPOSE_PATH="$PROJECT_DIR/docker/docker-compose.yml"
DOCKER_CONTAINER_NAME="piper-humble-dev"

TERMINATOR_CONFIG="$PROJECT_DIR/.config/terminator/config"
TERMINATOR_LAYOUT="piper-arm"

export PIPER_PROJECT_DIR="$PROJECT_DIR"

echo "[INFO] project dir: $PROJECT_DIR"
echo "[INFO] PIPER_PROJECT_DIR: $PIPER_PROJECT_DIR"
echo "[INFO] terminator config: $TERMINATOR_CONFIG"

xhost +local:docker

if docker compose -f "$DOCKER_COMPOSE_PATH" ps "$DOCKER_CONTAINER_NAME" --status running | grep -q "$DOCKER_CONTAINER_NAME"; then
    echo "[INFO] $DOCKER_CONTAINER_NAME コンテナは既に起動中"
else
    echo "[INFO] $DOCKER_CONTAINER_NAME コンテナを起動"
    docker compose -f "$DOCKER_COMPOSE_PATH" up -d "$DOCKER_CONTAINER_NAME"
fi

if [ ! -f "$TERMINATOR_CONFIG" ]; then
    echo "[ERROR] Terminator config が見つかりません: $TERMINATOR_CONFIG"
    exit 1
fi

if [ ! -f "$PIPER_PROJECT_DIR/docker/scripts/exec-in-docker-container.bash" ]; then
    echo "[ERROR] exec-in-docker-container.bash が見つかりません"
    echo "[ERROR] expected: $PIPER_PROJECT_DIR/docker/scripts/exec-in-docker-container.bash"
    exit 1
fi

echo "[INFO] ホスト側で Terminator を起動します..."
echo "[INFO] layout: $TERMINATOR_LAYOUT"

exec terminator -g "$TERMINATOR_CONFIG" -l "$TERMINATOR_LAYOUT"