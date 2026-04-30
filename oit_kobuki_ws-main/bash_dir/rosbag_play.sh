#!/bin/bash
cd ~/kobuki_ws
export ROS_DOMAIN_ID=12

while : ; do
    echo "------------------------------------------------"
    echo "【バッグ再生】再生したいフォルダ名を入力してください:"
    read bag_name
    if [ -z "$bag_name" ]; then continue; fi

    echo "Press Enter to start ros2 bag play..."
    read imp
    source install/setup.bash
    ros2 bag play "$bag_name" --rate 2.0
done
