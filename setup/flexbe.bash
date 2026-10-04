#! /bin/bash
set -e  # エラーが発生したら即停止する安全装置

# ワークスペースのルートを基準にする
WS_DIR="/ros2_ws"
cd "$WS_DIR"

echo "--- 1. Checking Repositories ---"
cd src

# flexbe_behavior_engine の確認と追加
if [ ! -d "flexbe_behavior_engine" ]; then
    git submodule add -b humble git@github.com:FlexBE/flexbe_behavior_engine.git 
else
    echo "flexbe_behavior_engine already exists."
fi

# flexbe_app の確認と追加
if [ ! -d "flexbe_app" ]; then
    git submodule add -b humble https://github.com/HSR-OIT/flexbe_app.git
else
    echo "flexbe_app already exists."
fi

# ワークスペースルートに戻る
cd "$WS_DIR"

echo "--- 2. pytest installation ---"
apt update
apt install -y \
  python3-pytest \
  python3-pytest-cov \
  python3-pytest-repeat \
  python3-pytest-rerunfailures

# ---------------------------------------------------------
# pytest plugin の自動ロードを無効化
# ---------------------------------------------------------
# /usr/local 側に pip で入った pytest plugin が、
# Ubuntu/ROS Humble の apt 版 pytest と衝突するのを防ぐ。
PYTEST_EXPORT_LINE='export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1'

# ~/.bashrc に未登録なら追記する
if ! grep -qxF "$PYTEST_EXPORT_LINE" ~/.bashrc; then
    echo "" >> ~/.bashrc
    echo "$PYTEST_EXPORT_LINE" >> ~/.bashrc
    echo "Added PYTEST_DISABLE_PLUGIN_AUTOLOAD to ~/.bashrc"
else
    echo "PYTEST_DISABLE_PLUGIN_AUTOLOAD is already configured in ~/.bashrc"
fi

# この setup スクリプト実行中の colcon build にも効かせる
export PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

# ---------------------------------------------------------
# 2. ビルド処理 (Symlink Install)
# nwjs_installを実行するために、先にパッケージとして認識させる必要がある
# ---------------------------------------------------------
echo "--- 3. Building flexbe_app ---"
colcon build

# ---------------------------------------------------------
# 3. nwjs 自動インストール処理
# ---------------------------------------------------------
echo "--- 4. Installing nwjs ---"

# ビルドした環境を読み込まないと ros2 run が使えないので source する
source install/setup.bash

APP_DIR="src/flexbe_app"

# nwjsフォルダがない場合のみインストールコマンドを実行
if [ ! -d "$APP_DIR/nwjs" ]; then
    echo "nwjs not found. Installing via ros2 run..."    
    # 正規の手順でインストールを実行
    ros2 run flexbe_app nwjs_install
else
    echo "nwjs is already installed. Skipping."
fi

echo "--- Setup Successfully Completed! ---"