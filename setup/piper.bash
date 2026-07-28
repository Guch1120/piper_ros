#!/bin/bash
set -e
echo "setuptools のバージョンを 58.2.0 にダウングレードします..."
pip3 install setuptools==58.2.0
if [ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ] ; then
    echo "rosdep の初期化を行います..."
    rosdep init
else
    echo "rosdep は既に初期化されています。スキップします。"
fi


echo "setuptools のバージョンを 58.2.0 にダウングレードします..."
pip3 install setuptools==58.2.0
rosdep update

if [ ! -d src/piper_sdk ]; then
    echo "piper_sdk をクローンします..."
    git submodule add git@github.com:Guch1120/piper_sdk.git src/piper_sdk
else
    echo "piper_sdk は既に存在します。スキップします。"
fi

# ROS-TCP-Endpoint (Unity 連携用) はワークスペースルート直下 (src/ の外) に配置する。
# colcon がワークスペースルートからパッケージを自動検出するため。
# 詳細: README/unity_plan.md の「ROS-TCP-Endpoint 配置変更に関する注記」を参照。
if [ ! -d ROS-TCP-Endpoint ]; then
    echo "ROS-TCP-Endpoint をクローンします..."
    git submodule add -b main-ros2 https://github.com/Unity-Technologies/ROS-TCP-Endpoint.git ROS-TCP-Endpoint
else
    echo "ROS-TCP-Endpoint は既に存在します。スキップします。"
fi


echo "ワークスペース内パッケージの依存関係をインストールします..."
# 注記: この後の `colcon build --symlink-install` はパッケージ指定なし=
# src/ 配下の全パッケージを対象にビルドする。そのため、ここで rosdep に渡す
# --from-paths には「後続の setup/*.bash (flexbe.bash, realsense.bash 等) が
# 個別に apt install する想定のパッケージ」も含めて、rosdep で解決可能な範囲は
# 漏れなく列挙しておく必要がある。
#
# (この行が元々 src/piper* のみだったため、src/realsense-ros が抜けており、
#  realsense2_camera のビルドに必要な ros-humble-diagnostic-updater 等が
#  未インストールのまま colcon build が走って CMake Error で失敗していた。
#  colcon のデフォルト動作では、あるパッケージのビルドが失敗すると同時に
#  ビルド中だった他パッケージも Aborted 扱いになるため、依存関係のない
#  flexbe_core / sam3_bridge 等もこれに巻き込まれて Aborted と表示されていた
#  (flexbe_core, sam3_bridge 単体では正常にビルドできることを確認済み)。)
#
# 以下は意図的に --from-paths から除外している (detic 同様、他の setup/*.bash
# を実行する前の時点では rosdep 解決に失敗するため):
#   - src/detic_onnx_ros2      : setup/detic.bash でのみ手動セットアップされる別系統の
#                                パッケージで、未セットアップ時はディレクトリ自体が
#                                存在しない (setup_all.bash の SCRIPTS 配列にも非対象)。
#   - src/piper_flexbe_behaviors : package.xml が <exec_depend>detic_onnx_ros2</exec_depend>
#                                を持つため、detic 未セットアップ時は rosdep 解決自体が
#                                失敗する (detic を除外している理由と同根)。
#   - src/yolov8_ros           : <exec_depend>ultralytics</exec_depend> が pip 専用パッケージで
#                                rosdep キーが存在しない (別途 pip install が必要、要別対応)。
#   - src/sam3 (sam3_dual_ros) : package.xml の <buildtool_depend>ament_python</buildtool_depend>
#                                に対応する rosdep キーが存在せず解決に失敗する
#                                (sam3_dual_ros 側の package.xml の記述の問題。今回のタスク
#                                範囲外のため未修正)。
#   - src/mobile_manipulator_description : <depend>kobuki_description</depend> は
#                                oit_kobuki_ws-main 側の未リリースパッケージで rosdep
#                                キーが存在しない。
#
# src/kobuki_sim (kobuki_unity: Kobuki 用 Unity ブリッジ、piper_sim/piper_unity と対称の
# 位置) は rclpy/geometry_msgs/sensor_msgs/nav_msgs/tf2_ros/std_msgs/ros_tcp_endpoint のみに
# 依存し、いずれも解決可能 (ros_tcp_endpoint は --ignore-src で ROS-TCP-Endpoint を参照) な
# ため、こちらは --from-paths に含める。
apt-get update
# --ignore-src: piper_sdk や ROS-TCP-Endpoint のようにソースとしてワークスペース内に
# 存在するパッケージは apt での解決を試みずスキップする (開発PCごとの配置差異に対する耐性)
rosdep install -i --from-paths \
    src/piper \
    src/piper_description \
    src/piper_humble \
    src/piper_moveit \
    src/piper_msgs \
    src/piper_sdk \
    src/piper_sim \
    src/kobuki_sim \
    src/cotyaka_flexbe_behaviors \
    src/flexbe_behavior_engine \
    src/flexbe_app \
    src/realsense-ros \
    src/sam3_ros \
    src/sam3_bridge \
    src/sam3_interfaces \
    ROS-TCP-Endpoint \
    --rosdistro humble -y --ignore-src

echo "colcon build を実行します..."
colcon build --symlink-install