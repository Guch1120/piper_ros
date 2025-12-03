#!/bin/bash
set -e

# ROS2環境のセットアップ
source /opt/ros/${ROS_DISTRO}/setup.bash

# 引数が渡された場合は実行、なければbashを起動
if [ "$#" -eq 0 ]; then
    exec /bin/bash
else
    exec "$@"
fi
