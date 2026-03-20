#!/bin/bash

# スクリプトがエラーで失敗した場合、直ちに停止する
set -e

# --- 1. Intel RealSense SDK (librealsense) のセットアップ ---

echo "Intel RealSense SDK (librealsense) のセットアップを開始します..."

# 1.1 GPGキーリング用のディレクトリを作成
echo "aptキーリング用ディレクトリを作成します..."
sudo mkdir -p /etc/apt/keyrings

# 1.2 Intel RealSenseのPGPキーを取得し、登録
echo "PGPキーを取得・登録します..."
curl -sSf https://librealsense.intel.com/Debian/librealsense.pgp | sudo tee /etc/apt/keyrings/librealsense.pgp > /dev/null

# 1.3 サーバーをリポジトリリストに登録
echo "aptリポジトリリストを追加します..."
echo "deb [signed-by=/etc/apt/keyrings/librealsense.pgp] https://librealsense.intel.com/Debian/apt-repo $(lsb_release -cs) main" | \
sudo tee /etc/apt/sources.list.d/librealsense.list

# 1.4 パッケージリストを更新
echo "パッケージリストを更新します..."
sudo apt-get update

# 1.5 必要なライブラリをインストール
echo "librealsenseライブラリをインストールします..."
sudo apt-get install -y librealsense2-utils \
                        librealsense2-dev \
                        librealsense2-dbg 

pip install pyrealsense2

echo " Intel RealSense SDK のセットアップが完了しました。"
echo "--------------------------------------------------"


# --- 2. realsense-ros (ROS 2) のセットアップ ---

echo "realsense-ros (ROS 2 Humble) のセットアップを開始します..."

# ROS 2 ワークスペースのパスを定義 (例: $HOME/ros2_ws)
# ROS_WS="$HOME/ros2_ws" #dokcer内の$HOMEはrootだけどdockerfileで作業ディレクトリを/ros2_wsにしてるから作業外にクローンしてしまう．
ROS_WS="/ros2_ws"
ROS_DISTRO="humble" 

echo "ROS 2 ワークスペース: $ROS_WS を準備します..."
mkdir -p "$ROS_WS/src"

# 2.1 realsense-ros をクローン
echo "realsense-ros を $ROS_WS/src にクローンします..."
cd "$ROS_WS/src"
if [ ! -d "realsense-ros" ]; then
  git clone https://github.com/IntelRealSense/realsense-ros.git
else
  echo "realsense-ros ディレクトリは既に存在するため、クローンをスキップします。"
fi

# 2.2 依存関係のインストール (存在確認を追加)
echo "ROS 2 の依存関係 (diagnostic_updater) を確認します..."
PACKAGE_NAME="ros-$ROS_DISTRO-diagnostic-updater"

# dpkg-query でステータスを確認し、"install ok installed" が含まれているかチェック
# 含まれていない場合 (終了ステータスが0以外) のみインストールを実行
if ! dpkg-query -W -f='${Status}' $PACKAGE_NAME 2>/dev/null | grep -q "install ok installed"; then
  echo "$PACKAGE_NAME が見つかりません。インストールします..."
  sudo apt-get update
  sudo apt-get install -y $PACKAGE_NAME \
                        ros-humble-realsense2-camera  #realsense2 rs_launch.pyに必要
else
  echo "$PACKAGE_NAME は既にインストールされています。スキップします。"
fi

# 2.3 ビルド
echo "ワークスペースをビルドします..."
cd "$ROS_WS" # ビルドはワークスペースのルートで行う

# colcon build コマンドを実行するために、ROS 2 の基本環境を source します
if [ -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
  source "/opt/ros/$ROS_DISTRO/setup.bash"
else
  echo "警告: /opt/ros/$ROS_DISTRO/setup.bash が見つかりません。"
  echo "ビルド失敗の可能性があります。ROS 2 環境を先にセットアップしてください。"
fi

colcon build --symlink-install

echo " realsense-ros のセットアップが完了しました。"
echo "--------------------------------------------------"


# --- 3. 完了メッセージと次のステップ ---

echo " すべての環境構築が完了しました。"
echo ""
echo "--- 動作確認 (SDK) ---"
echo "1. RealSenseカメラをPCに接続してください。"
echo "2. 新しいターミナルで 'realsense-viewer' と入力し、カメラが認識されるか確認してください。"
echo ""
echo "--- 実行方法 (ROS 2) ---"
echo "以下のコマンドを新しいターミナルで実行してください:"
echo ""
echo "# 1. ビルドしたワークスペースの環境を読み込みます"
echo "source $ROS_WS/install/local_setup.bash"
echo ""
echo "# 2. RealSenseノードを起動します"
echo "ros2 launch realsense2_camera rs_launch.py"
echo ""
echo "# 3. (別のターミナルを開き、同様に source した後) トピック一覧を確認します"
echo "ros2 topic list"