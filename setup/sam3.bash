#!/bin/bash
set -e

# SAM3のセットアップスクリプト
# このスクリプトはコンテナ内で実行するか、ホストからコンテナに対して実行してください。

echo "Setting up SAM3..."

cd /ros2_ws/src/sam3

# 依存関係のインストール
echo "Installing SAM3 dependencies..."
pip install --upgrade pip setuptools wheel
# sympyとmpmathの競合を解消するために強制再インストール
pip install --ignore-installed sympy mpmath
pip install -e .
pip install -e ".[dev]"
pip install grpcio grpcio-tools

echo "SAM3 setup complete!"
