#!/bin/bash
cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "------------------------------------------------"
    echo "【グラフ表示】解析するCSVファイル名を入力してください:"
    read csv_name
    if [ -z "$csv_name" ]; then continue; fi

    echo "Press Enter to plot results..."
    read imp
    source install/setup.bash
    python3 src/my_analysis_pkg/my_analysis_pkg/plot_results.py --name "$csv_name"
done
