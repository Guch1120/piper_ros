#!/bin/bash
cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "------------------------------------------------"
    echo "【データ記録】実験名（フォルダ名）を入力してください:"
    read trial_name
    if [ -z "$trial_name" ]; then continue; fi

    echo "Press Enter to start recording..."
    read imp
    source install/setup.bash
    ros2 bag record -o "$trial_name" /amcl_pose /tf /tf_static /scan /filtered_scan
done
