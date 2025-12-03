#!/bin/bash
# rosdepが初期化済みか確認し、未初期化の場合のみ実行
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]; then
    rosdep init
fi
rosdep update

pip install onnxruntime

cd src
if [ ! -d "detic_onnx_ros2" ]; then
    git submodule add git@github.com:Guch1120/detic_onnx_ros2.git
    echo "detic_onnx_ros2 をクローンしました。"
else
    echo "detic_onnx_ros2 は既に存在します。スキップします。"
fi
cd detic_onnx_ros2
rosdep install -iry --from-paths .
cd ../../
colcon build --symlink-install