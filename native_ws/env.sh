#!/bin/bash
# Kotyaka simulator: native (non-Docker) ROS2 Humble environment for this host.
#
# piper_ros/install is built inside a Docker container ("/ros2_ws") and its
# package.xml symlinks point into that container's filesystem, so it cannot be
# sourced natively. This overlay workspace (native_ws) instead builds the
# handful of packages needed to run the Unity simulator bridges directly on
# the host: kobuki_unity, ros_tcp_endpoint, piper_unity.
#
# slam_toolbox (from oit_kobuki_ws-main, which IS natively built) needs
# libceres.so.2 / libglog.so.0 / libgflags / libcxsparse / libspqr, which are
# not installed system-wide (no sudo available in this environment). They were
# extracted without root via `apt download <pkg> && dpkg-deb -x` into
# ~/.local/lib/kotyaka-native-deps and are added to LD_LIBRARY_PATH below.
#
# Usage: source this file, then run kobuki_unity_sim / ROS-TCP-Endpoint /
# slam_toolbox / nav2 launches as usual.

source /opt/ros/humble/setup.bash
source /home/guch1/ssd_yamaguchi/piper_ros/native_ws/install/setup.bash
source /home/guch1/ssd_yamaguchi/oit_kobuki_ws-main/install/setup.bash

export LD_LIBRARY_PATH="/home/guch1/.local/lib/kotyaka-native-deps:${LD_LIBRARY_PATH}"
