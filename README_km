## vision
###############
####解決済み###
###############


# いるかどうかわからないので、なしで進んで必要であれば入れる感じで
apt-get update && apt-get install -y libjpeg-dev zlib1g-dev libpng-dev
# /workspace ディレクトリに移動（ros2_ws の外を推奨）
cd /workspace 

# ソースコードをクローン
git clone https://github.com/pytorch/vision.git

# クローンしたディレクトリに移動
cd vision

# バージョン 0.19.1 に切り替える
git checkout v0.19.1

# C++ ビルド専用のディレクトリを作成し、そこに移動
mkdir build-cpp
cd build-cpp

# /workspace/vision/build-cpp ディレクトリで実行
cmake .. \
  -DTorch_DIR=/usr/local/lib/python3.10/dist-packages/torch/share/cmake/Torch \
  -DCMAKE_INSTALL_PREFIX=/usr/local/lib/python3.10/dist-packages/torchvision

# /workspace/vision/build-cpp ディレクトリで実行
make -j$(nproc)

# /workspace/vision/build-cpp ディレクトリで実行
make install




# realsense-rosをインストール
git clone https://github.com/IntelRealSense/realsense-ros.git
cd /ros2_ws
# realsense2_cameraパッケージが依存しているdiagnostic_updaterというROS2パッケージが見つからないため、インストールする
sudo apt update
sudo apt install ros-humble-diagnostic-updater
# ビルドする
colcon build --symlink-install

# realsense-rosの実行
source realsense_ws/install/local_setup.bash 
ros2 launch realsense2_camera rs_launch.py
# topicが出ているか確認
ros2 topic list