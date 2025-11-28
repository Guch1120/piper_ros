#!/bin/bash
set -e

echo "Detic 環境構築スクリプトを開始します。"

# SSH known_hosts に github.com を追加
echo "SSH known_hosts に github.com を追加しています..."
mkdir -p /root/.ssh
ssh-keyscan github.com >> /root/.ssh/known_hosts
chmod 644 /root/.ssh/known_hosts


# 1. 作業ディレクトリの作成と移動
if [ ! -d "./detic" ]; then
    echo "作業ディレクトリ 'detic' を作成しています..."
    mkdir detic
else
    echo "'detic'は既に存在"
fi

cd ./detic
echo "作業ディレクトリ: $(pwd)"

# 2. Detectron2 のクローンとインストール
if [ ! -d "./detectron2" ]; then
    echo "Detectron2 をクローンしています..."
    git submodule add git@github.com:Guch1120/detectron2.git
else
    echo "Detectron2 ディレクトリは既に存在します。スキップします。"
fi
cd detectron2

echo "PyTorch と Torchvision をインストールしています..."
pip install torch==2.4.1 torchvision

echo "Numpy, SciPy, OpenCV のバージョンを調整しています..."
pip uninstall -y numpy scipy opencv-python opencv-python-headless
pip install numpy==1.22.2
pip install scipy==1.11.4
pip install opencv-python==4.8.1.78

echo "Detectron2 をインストールしています..."
pip install -e .

cd ..
echo "Detectron2 のインストールが完了しました。"

# 3. Detic のクローンとインストール
if [ ! -d "./Detic" ]; then
    echo "Detic をクローンしています (サブモジュール含む)..."
    git submodule add git@github.com:Guch1120/Detic.git  
else
    echo "Detic ディレクトリは既に存在します。スキップします。"
fi
cd Detic

echo "Detic の要求ライブラリをインストールしています..."
pip install -r requirements.txt

echo "Detic のインストールが完了しました。"
echo "環境構築が正常に完了しました。"

if [ ! -d "./models" ]; then
    echo "モデル保存用ディレクトリ 'models' を作成しています..."
    mkdir models
else
    echo "モデル保存用ディレクトリ 'models' は既に存在します。"
fi
wget https://dl.fbaipublicfiles.com/detic/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth -P models/

#ここからdetic_onnx_rosのセットアップ
cd /ros2_ws/src
echo "detic_onnx_rosのセットアップを開始します..."
if [ ! -d "./detic_onnx_ros2" ]; then
    git submodule add git@github.com:Guch1120/detic_onnx_ros2.git 
else
    echo "detic_onnx_ros2 ディレクトリは既に存在します。スキップします。"
fi
cd detic_onnx_ros2
rosdep init
rosdep update
rosdep install -iry --from-paths .
cd ../../
colcon build --symlink-install