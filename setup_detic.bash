#!/bin/bash
set -e

echo "Detic 環境構築スクリプトを開始します。"

# 1. 作業ディレクトリの作成と移動
if [! -d "./detic" ]; then
    echo "作業ディレクトリ 'detic' を作成しています..."
    mkdir detic
else
    echo "'detic'は既に存在"
fi

cd ./detic
echo "作業ディレクトリ: $(pwd)"

# 2. Detectron2 のクローンとインストール
if [! -d "./detectron2" ]; then
    echo "Detectron2 をクローンしています..."
    git clone git@github.com:Guch1120/detectron2.git.git
else
    echo "Detectron2 ディレクトリは既に存在します。スキップします。"
fi
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
if [! -d "./Detic" ]; then
    echo "Detic をクローンしています (サブモジュール含む)..."
    git clone git@github.com:Guch1120/Detic.git --recurse-submodules 
else
    echo "Detic ディレクトリは既に存在します。スキップします。"
fi
cd Detic

echo "Detic の要求ライブラリをインストールしています..."
pip install -r requirements.txt

echo "Detic のインストールが完了しました。"
echo "環境構築が正常に完了しました。"

if [! -d "./models" ]; then
    echo "モデル保存用ディレクトリ 'models' を作成しています..."
    mkdir models
else
    echo "モデル保存用ディレクトリ 'models' は既に存在します。"
fi
wget https://dl.fbaipublicfiles.com/detic/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth -P models/



# 4. サンプル実行方法 (参考)
# モデルやサンプル画像は別途ダウンロード/配置が必要です。
: '
# モデルのダウンロード (例)

# サンプル画像の配置 (例) なんでもいいから好きなやつをmodels/の中に入れて
# (./models/sample.JPG に画像を配置する)

# デモの実行はこれ． --input のあとのパスがあっているか確認してね
python3 demo.py \
    --config-file configs/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.yaml \
    --input ./models/sample.JPG \
    --output out.jpg \
    --vocabulary lvis \
    --opts MODEL.WEIGHTS models/Detic_LCOCOI21k_CLIP_SwinB_896b32_4x_ft4x_max-size.pth
'

#実行にはsudo chown -R $USER:$USER ./deticが必要