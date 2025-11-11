#!/bin/bash
set -e

service dbus start
echo "DBus service started"
#コンテナを起動し続ける

source /opt/ros/humble/setup.bash
function on_signal_interrupt() {
    ros2 node list | grep -v '/_ros2cli' | xargs -r ros2 node kill
    echo "コンテナ内のROSノードを終了しました。"
}
trap on_signal_interrupt EXIT

terminator -m -l  piper-arm 
