#!/bin/bash
set -e

echo "Detic 環境構築スクリプトを開始します。"

# 仮想環境の作成を推奨 (オプション)
# echo "Python仮想環境の作成を推奨します。"
# echo "python3 -m venv venv"
# echo "source venv/bin/activate"
# read -p "仮想環境を有効化したら、Enterキーを押してください..."

# 1. 作業ディレクトリの作成と移動
mkdir -p ./detic
cd ./detic
echo "作業ディレクトリ: $(pwd)"

# 2. Detectron2 のクローンとインストール
echo "Detectron2 をクローンしています..."
git clone git@github.com:facebookresearch/detectron2.git
cd detectron2

echo "PyTorch と Torchvision をインストールしています..."
pip install torch==2.4.1 torchvision

echo "Numpy, SciPy, OpenCV のバージョンを調整しています..."
# 依存関係の競合を防ぐため、特定のバージョンを指定
pip uninstall -y numpy scipy opencv-python opencv-python-headless
pip install numpy==1.22.2
pip install scipy==1.11.4
pip install opencv-python==4.8.1.78

echo "Detectron2 をインストールしています..."
pip install -e .

# インストール確認 (オプション、スクリプト実行中はコメントアウト)
# pip list | grep numpy

cd ..
echo "Detectron2 のインストールが完了しました。"

# 3. Detic のクローンとインストール
echo "Detic をクローンしています (サブモジュール含む)..."
git clone git@github.com:facebookresearch/Detic.git --recurse-submodules
cd Detic

echo "Detic の要求ライブラリをインストールしています..."
pip install -r requirements.txt

echo "Detic のインストールが完了しました。"
echo "環境構築が正常に完了しました。"

# 4. サンプル実行方法 (参考)
# モデルやサンプル画像は別途ダウンロード/配置が必要です。
: '
# モデルのダウンロード (例)
wget https://dl.fbaipublicfiles.com/detic/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth -P models/

# サンプル画像の配置 (例)
# (./models/sample.JPG に画像を配置する)

# デモの実行
python3 demo.py \
    --config-file configs/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.yaml \
    --input ./models/sample.JPG \
    --output out.jpg \
    --vocabulary lvis \
    --opts MODEL.WEIGHTS models/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth
'