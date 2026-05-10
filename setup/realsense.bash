#!/bin/bash
set -euo pipefail

echo "Intel RealSense SDK (librealsense) のセットアップを開始します..."

KEYRING_DIR="/etc/apt/keyrings"
KEYRING_PATH="$KEYRING_DIR/librealsense.gpg"
LIST_PATH="/etc/apt/sources.list.d/librealsense.list"
REPO_URL="https://librealsense.intel.com/Debian/apt-repo"
REPO_CODENAME="$(lsb_release -cs)"
REPO_KEY_ID="FB0B24895113F120"
REPO_KEYSERVER="keyserver.ubuntu.com"

echo "aptキーリング用ディレクトリを作成します..."
mkdir -p "$KEYRING_DIR"

echo "GnuPGホームを準備します..."
mkdir -p "$HOME/.gnupg"
chmod 700 "$HOME/.gnupg"

echo "既存のlibrealsense設定を削除します..."
rm -f "$LIST_PATH"
rm -f "$KEYRING_PATH"
rm -f /tmp/realsense-temp.gpg

echo "壊れた ffmpeg-next PPA があれば無効化します..."
rm -f /etc/apt/sources.list.d/*ffmpeg-next*.list || true

echo "apt 基本ツールの更新・導入を行います..."
apt-get update
apt-get install -y gnupg dirmngr ca-certificates lsb-release curl software-properties-common

echo "RealSense Debian repository の公開鍵を取得・登録します..."
gpg --batch --yes --no-default-keyring \
    --keyring /tmp/realsense-temp.gpg \
    --keyserver "$REPO_KEYSERVER" \
    --recv-keys "$REPO_KEY_ID"

gpg --batch --yes --no-default-keyring \
    --keyring /tmp/realsense-temp.gpg \
    --export "$REPO_KEY_ID" \
    | gpg --dearmor -o "$KEYRING_PATH"

chmod a+r "$KEYRING_PATH"
rm -f /tmp/realsense-temp.gpg

echo "登録された鍵を確認します..."
gpg --show-keys "$KEYRING_PATH"

echo "aptリポジトリリストを追加します..."
echo "deb [signed-by=$KEYRING_PATH] $REPO_URL $REPO_CODENAME main" > "$LIST_PATH"

echo "パッケージリストを更新します..."
apt-get update

echo "librealsenseライブラリをインストールします..."
apt-get install -y \
    librealsense2-utils \
    librealsense2-dev \
    librealsense2-dbg

echo "pyrealsense2 をインストールします..."
python3 -m pip install --upgrade pip
python3 -m pip install pyrealsense2

echo "Intel RealSense SDK のセットアップが完了しました。"
echo "--------------------------------------------------"

ROS_DISTRO="humble"
if [ ! -f "/opt/ros/$ROS_DISTRO/setup.bash" ]; then
    echo "ROS 2 $ROS_DISTRO はこのコンテナ/環境に入っていないため、SDK / pyrealsense2 のみセットアップしました。"
    echo "ROS 連携が必要な場合は ROS 環境でこのスクリプトを実行してください。"
    echo "--------------------------------------------------"
    exit 0
fi

echo "realsense-ros (ROS 2 $ROS_DISTRO) のセットアップを開始します..."
ROS_WS="/ros2_ws"
PACKAGE_NAME="ros-$ROS_DISTRO-diagnostic-updater"
REALSENSE_ROS_PACKAGE="ros-$ROS_DISTRO-realsense2-camera"

echo "ROS 2 ワークスペース: $ROS_WS を準備します..."
mkdir -p "$ROS_WS/src"

echo "realsense-ros を $ROS_WS/src にクローンします..."
cd "$ROS_WS/src"
if [ ! -d "realsense-ros" ]; then
    git clone https://github.com/IntelRealSense/realsense-ros.git
else
    echo "realsense-ros ディレクトリは既に存在するため、クローンをスキップします。"
fi

echo "ROS 2 の依存関係を確認します..."
if ! dpkg-query -W -f='${Status}' "$PACKAGE_NAME" 2>/dev/null | grep -q "install ok installed"; then
    echo "$PACKAGE_NAME が見つかりません。インストールします..."
    apt-get update
    apt-get install -y \
        "$PACKAGE_NAME" \
        "$REALSENSE_ROS_PACKAGE"
else
    echo "$PACKAGE_NAME は既にインストールされています。スキップします。"
fi

echo "ワークスペースをビルドします..."
cd "$ROS_WS"
source "/opt/ros/$ROS_DISTRO/setup.bash"
colcon build --symlink-install

echo "realsense-ros のセットアップが完了しました。"
echo "--------------------------------------------------"

echo "すべての環境構築が完了しました。"
echo ""
echo "--- 動作確認 (SDK) ---"
echo "1. RealSenseカメラをPCに接続してください。"
echo "2. 新しいターミナルで 'realsense-viewer' と入力し、カメラが認識されるか確認してください。"
echo ""
echo "--- 実行方法 (ROS 2) ---"
echo "source $ROS_WS/install/local_setup.bash"
echo "ros2 launch realsense2_camera rs_launch.py"
echo "ros2 topic list"