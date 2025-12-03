#!/bin/bash
set -e

# SAM3のセットアップスクリプト
# このスクリプトはコンテナ内で実行するか、ホストからコンテナに対して実行してください。

echo "Setting up SAM3..."

cd /ros2_ws/src

# SAM3リポジトリのクローン（存在しない場合のみ）
if [ ! -d "sam3" ]; then
    echo "Cloning SAM3 repository..."
    git clone git@github.com:Guch1120/sam3.git
else
    echo "SAM3 directory already exists. Skipping clone."
fi

# .gitディレクトリの削除（親リポジトリの一部として管理するため）
if [ -d "sam3/.git" ]; then
    echo "Removing .git directory from sam3 to manage as part of piper_ros..."
    rm -rf sam3/.git
    
    # サブモジュールとして登録されていた可能性があるため、インデックスから削除（ファイルは保持）
    # これにより、次回 git add した際に通常のディレクトリとして追加される
    git rm --cached sam3 || true
fi

# SAM3ディレクトリへの移動
cd sam3

# 依存関係のインストール
echo "Installing SAM3 dependencies..."
pip install --upgrade pip setuptools wheel
# sympyとmpmathの競合を解消するために強制再インストール
pip install --ignore-installed sympy mpmath
pip install -e .
pip install -e ".[notebooks,dev,train]"

echo "SAM3 setup complete!"
