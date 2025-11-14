#!/bin/bash

rosdep init 
rosdep update

cd src
git submodule add git@github.com:Guch1120/detic_onnx_ros2.git 
cd detic_onnx_ros2
rosdep install -iry --from-paths .
cd ../../
colcon build --symlink-install