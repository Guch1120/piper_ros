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
# 5. Terminator終了時にコンテナ内のROS関連プロセスを確認・停止
#
# 注意:
# - コンテナ自体は停止しない
# - docker compose down はしない
# - ROS関連プロセスに Ctrl+C 相当の SIGINT を送る
# - SIGINTで残る場合は SIGTERM を送る
# ============================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$SCRIPT_DIR"
cd "$PROJECT_DIR"

DOCKER_COMPOSE_PATH="$PROJECT_DIR/docker/docker-compose.yml"
DOCKER_CONTAINER_NAME="piper-humble-dev"
TERMINATOR_CONFIG="$PROJECT_DIR/.config/terminator/config"
TERMINATOR_LAYOUT="piper-arm"

export PIPER_PROJECT_DIR="$PROJECT_DIR"

# Ctrl+C と EXIT の両方で cleanup が二重実行されるのを防ぐ
CLEANED_UP=0

cleanup() {
    if [ "$CLEANED_UP" -eq 1 ]; then
        return 0
    fi
    CLEANED_UP=1

    echo
    echo "[INFO] cleanup: Terminator 終了後の処理を開始します"
    echo "[INFO] コンテナは停止しません: $DOCKER_CONTAINER_NAME"

    if ! docker ps --format '{{.Names}}' | grep -qx "$DOCKER_CONTAINER_NAME"; then
        echo "[WARN] $DOCKER_CONTAINER_NAME コンテナは起動していません"
        return 0
    fi

    docker exec "$DOCKER_CONTAINER_NAME" bash -lc '
        set +e

        # pkill -f が cleanup 実行中の bash 自身を巻き込まないようにする
        PATTERN="[r]os2|[r]os1|[r]oscore|[r]osmaster|[r]oslaunch|[l]aunch.py|[r]viz|[r]viz2|[g]azebo|[g]zserver|[g]zclient"

        echo "[INFO] cleanup before:"
        ps aux | grep -E "$PATTERN" | grep -v grep || true

        if ps aux | grep -E "$PATTERN" | grep -v grep >/dev/null; then
            echo
            echo "[INFO] ROS関連プロセスへ SIGINT を送信します"
            pkill -INT -f "$PATTERN" || true

            sleep 2
        else
            echo "[INFO] ROS関連プロセスは見つかりませんでした"
        fi

        echo
        echo "[INFO] cleanup after SIGINT:"
        ps aux | grep -E "$PATTERN" | grep -v grep || true

        if ps aux | grep -E "$PATTERN" | grep -v grep >/dev/null; then
            echo
            echo "[WARN] SIGINT後も残っているROS関連プロセスがあります"
            echo "[WARN] SIGTERM を送信します"

            pkill -TERM -f "$PATTERN" || true

            sleep 2

            echo
            echo "[INFO] cleanup after SIGTERM:"
            ps aux | grep -E "$PATTERN" | grep -v grep || true
        fi

        echo
        echo "[INFO] cleanup finished"
    ' || true
}

on_signal() {
    cleanup
    exit 130
}

trap cleanup EXIT
trap on_signal INT TERM

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

terminator -m -g "$TERMINATOR_CONFIG" -l "$TERMINATOR_LAYOUT"

echo "[INFO] Terminator が終了しました"