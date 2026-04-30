#!/bin/bash
cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "------------------------------------------------"
    echo "【CSV保存】保存するファイル名（例: yui.csv）を入力してください:"
    read csv_name
    if [ -z "$csv_name" ]; then continue; fi

    echo "Press Enter to start saver node..."
    read imp
    source install/setup.bash
    python3 src/my_analysis_pkg/my_analysis_pkg/save_csv.py --name "$csv_name"
done
