#!/bin/bash

# スクリプトがエラーで失敗した場合、直ちに停止する
set -e

echo "Intel RealSense SDK (librealsense) のセットアップを開始します..."

# 1. GPGキーリング用のディレクトリを作成
echo "aptキーリング用ディレクトリを作成します..."
sudo mkdir -p /etc/apt/keyrings

# 2. Intel RealSenseのPGPキーを取得し、登録
echo "PGPキーを取得・登録します..."
curl -sSf https://librealsense.intel.com/Debian/librealsense.pgp | sudo tee /etc/apt/keyrings/librealsense.pgp > /dev/null

# 3. サーバーをリポジトリリストに登録
echo "aptリポジトリリストを追加します..."
echo "deb [signed-by=/etc/apt/keyrings/librealsense.pgp] https://librealsense.intel.com/Debian/apt-repo $(lsb_release -cs) main" | \
sudo tee /etc/apt/sources.list.d/librealsense.list

# 4. パッケージリストを更新 (リポジトリ追加を反映させるため)
echo "パッケージリストを更新します..."
sudo apt-get update

# 5. 必要なライブラリをインストール
# -y オプションを追加し、インストールの確認を自動で「yes」にします
echo "librealsenseライブラリをインストールします..."
sudo apt-get install -y librealsense2-dkms \
                        librealsense2-utils \
                        librealsense2-dev \
                        librealsense2-dbg

echo "✅ Intel RealSense SDK のセットアップが完了しました。"
echo "Realsenseカメラを接続し、'realsense-viewer' コマンドで動作確認をしてください。"

#動作確認
echo "realsense-viewerで動作確認をしてください。"