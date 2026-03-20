# SAM3 with ROS2 - Docker環境構築ガイド

このガイドでは、SAM3をROS2 Humble環境で使用するためのDocker環境の構築方法を説明します。

> [!NOTE]
> このDocker環境は、ROS2 Humbleとの互換性のためPython 3.10を使用します。SAM3のREADME.mdではPython 3.12を推奨していますが、pyproject.tomlでは3.8以上が要件となっているため、Python 3.10でも正常に動作します。

## 前提条件

- Docker Engine 20.10以上
- Docker Compose V2以上
- NVIDIA Docker Runtime（GPU使用の場合）
- NVIDIA Driver 525以上（CUDA 12.6に対応）

### NVIDIA Docker Runtimeのインストール確認

```bash
# NVIDIA Docker Runtimeがインストールされているか確認
docker run --rm --gpus all nvidia/cuda:12.6.0-base-ubuntu22.04 nvidia-smi
```

インストールされていない場合は、以下を実行してください：

```bash
# NVIDIA Container Toolkitのインストール
distribution=$(. /etc/os-release;echo $ID$VERSION_ID)
curl -s -L https://nvidia.github.io/nvidia-docker/gpgkey | sudo apt-key add -
curl -s -L https://nvidia.github.io/nvidia-docker/$distribution/nvidia-docker.list | sudo tee /etc/apt/sources.list.d/nvidia-docker.list

sudo apt-get update
sudo apt-get install -y nvidia-container-toolkit
sudo systemctl restart docker
```

## Docker環境の構築手順

### 1. Dockerイメージのビルド

プロジェクトのルートディレクトリで以下のコマンドを実行します：

```bash
cd /home/guch1/ssd_yamaguchi/sam3
docker compose build
```

ビルドには10-20分程度かかる場合があります。

### PyTorchバージョンのカスタマイズ

デフォルトでは、RTX 5000番台などの最新GPUに対応するため、**PyTorch 2.9 (CUDA 12.8対応)** を使用します。
これは安定版リリースであり、`docker compose build` で自動的にインストールされます。

古いバージョン（例: 2.7.0）を使用したい場合は、以下のようにビルド引数を指定してください：

```bash
# PyTorch 2.7.0 (CUDA 12.6) を使用する場合
docker compose build --build-arg PYTORCH_VERSION=2.7.0 --build-arg PYTORCH_INDEX_URL=https://download.pytorch.org/whl/cu126
```

`docker-compose.yml` の `args` セクションを編集することでも変更可能です。

### 2. コンテナの起動

```bash
# バックグラウンドで起動
docker compose up -d

# フォアグラウンドで起動（ログを確認したい場合）
docker compose up
```

### 3. コンテナへの接続

```bash
# コンテナに入る
docker compose exec sam3-ros2 bash
```

または

```bash
# 新しいターミナルでコンテナに入る
docker exec -it sam3-ros2-dev bash
```

## SAM3の使用方法

### 1. Hugging Faceの認証

SAM3のチェックポイントをダウンロードするには、Hugging Faceの認証が必要です：
```bash
# Hugging Faceにログイン
hf auth login
# アクセストークンを入力
```


アクセストークンを入力してください。トークンは以下から取得できます：
https://huggingface.co/settings/tokens

また、SAM3チェックポイントへのアクセス許可をリクエストしてください：
https://huggingface.co/facebook/sam3

### 2. 基本的な使用例

#### 画像セグメンテーション

```python
import torch
from PIL import Image
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor

# モデルの読み込み
model = build_sam3_image_model()
processor = Sam3Processor(model)

# 画像の読み込み
image = Image.open("path/to/your/image.jpg")
inference_state = processor.set_image(image)

# テキストプロンプトでセグメンテーション
output = processor.set_text_prompt(state=inference_state, prompt="a cat")

# マスク、バウンディングボックス、スコアを取得
masks, boxes, scores = output["masks"], output["boxes"], output["scores"]
```


### 3. ROS2との統合

ROS2環境が既にセットアップされています：

```bash
# ROS2のディストリビューション確認
echo $ROS_DISTRO
# 出力: humble

# ROS2のトピック一覧
ros2 topic list

# ROS2ノードの実行例
ros2 run demo_nodes_cpp talker
```

## コンテナの管理

### コンテナの停止

```bash
docker compose down
```

### コンテナの再起動

```bash
docker compose restart
```

### コンテナのログ確認

```bash
docker compose logs -f
```

### イメージの再ビルド

```bash
# キャッシュを使わずに再ビルド
docker compose build --no-cache
```

## トラブルシューティング

### GPU が認識されない

```bash
# コンテナ内でGPUが認識されているか確認
nvidia-smi
```

認識されない場合は、NVIDIA Docker Runtimeが正しくインストールされているか確認してください。

### X11ディスプレイエラー

GUIアプリケーションを使用する場合：

```bash
# ホスト側で実行
xhost +local:docker
```


## 開発環境の設定

### コードフォーマット

```bash
# コンテナ内で実行
cd /workspace/sam3
ufmt format .
```

### テストの実行

```bash
# コンテナ内で実行
pytest
```

## 次のステップ

1. [examples/](examples/)ディレクトリのノートブックを試す
2. ROS2ノードを作成してSAM3を統合する
3. カスタムデータセットでSAM3を評価する

## 参考リンク

- [SAM3公式GitHub](https://github.com/facebookresearch/sam3)
- [ROS2 Humbleドキュメント](https://docs.ros.org/en/humble/)
- [SAM3論文](https://ai.meta.com/research/publications/sam-3-segment-anything-with-concepts/)
