#!/bin/bash
set -euo pipefail

ROS_DISTRO="humble"

cd /home/kobuki/kobuki_ws
if [ ! -e /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    sudo rosdep init
fi

rosdep update
sudo apt-get update
rosdep install -q -y -r --from-paths src --ignore-src --rosdistro $ROS_DISTRO