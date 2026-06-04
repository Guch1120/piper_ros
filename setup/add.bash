#!/bin/bash
set -e

echo "────────────────────────────────""
echo "add not installed by Dockerfile"
echo "────────────────────────────────""

apt install -y ros-humble-tf-transformations


# tf_transformations 本体をインストール
apt install -y ros-humble-tf-transformations

# apt で入る transforms3d 0.3.1 は numpy 1.24+ と相性が悪い
# numpy は変更せず、pip 版 transforms3d 0.4.2 を /usr/local 側に上書き配置する
python3 -m pip install --ignore-installed --no-deps transforms3d==0.4.2

echo "────────────────────────────────"
echo "Check import"
echo "────────────────────────────────"

python3 -c "import transforms3d; print('transforms3d version:', transforms3d.__version__); print('transforms3d path:', transforms3d.__file__)"
python3 -c "import tf_transformations; print('tf_transformations: ok')"

echo "────────────────────────────────"
echo "Done"
echo "────────────────────────────────"