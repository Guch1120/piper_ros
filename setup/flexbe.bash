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

# ---------------------------------------------------------
# 2. ビルド処理 (Symlink Install)
# nwjs_installを実行するために、先にパッケージとして認識させる必要がある
# ---------------------------------------------------------
echo "--- 2. Building flexbe_app ---"
# flexbe_app だけを狙い撃ちでビルド（時間短縮）
colcon build --symlink-install --packages-select flexbe_app

# ---------------------------------------------------------
# 3. nwjs 自動インストール処理
# ---------------------------------------------------------
echo "--- 3. Installing nwjs ---"

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