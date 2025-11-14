#!/bin/bash
set -e

rosdep update

echo "Piper関連パッケージの依存関係をインストールします (detic_onnx_ros2 は除外)..."

apt-get update
# --from-paths で detic 以外のパッケージディレクトリを個別に指定する
rosdep install -i --from-paths \
    src/piper \
    src/piper_description \
    src/piper_humble \
    src/piper_moveit \
    src/piper_msgs \
    src/piper_sdk \
    src/piper_sim \
    --rosdistro humble -y

echo "colcon build を実行します..."
colcon build --symlink-install