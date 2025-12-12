#!/bin/bash
set -e

service dbus start
echo "DBus service started"

source /opt/ros/humble/setup.bash

function on_signal_interrupt() {
    ros2 node list | grep -v '/_ros2cli' | xargs -r ros2 node kill
    echo "コンテナ内のROSノードを終了しました。"
}
trap on_signal_interrupt EXIT

# HOME を使わず絶対パスにする（重要）
TERMINATOR_LAYOUT_FILE="/ros2_ws/.config/terminator/terminator_layout"

if [ ! -f "$TERMINATOR_LAYOUT_FILE" ]; then
    echo "Error: Terminator レイアウト設定ファイル $TERMINATOR_LAYOUT_FILE が存在しません。" 1>&2
    echo "\"layout=sam3\" または \"layout=piper-arm\" を記述した $TERMINATOR_LAYOUT_FILE を作成してください。" 1>&2
    exit 1
fi

source "$TERMINATOR_LAYOUT_FILE"

if [ -z "$layout" ]; then
    echo "Error: $TERMINATOR_LAYOUT_FILE 内に layout が定義されていません。" 1>&2
    exit 1
fi

if [ "$layout" != "sam3" ] && [ "$layout" != "piper-arm" ]; then
    echo "Error: layout=\"$layout\" は許可されていません。" 1>&2
    echo "許可されているレイアウト: sam3, piper-arm" 1>&2
    exit 1
fi

echo "Using Terminator layout: $layout"

terminator -m -l "$layout"
