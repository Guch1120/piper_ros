# SAM3 with ROS2 - クイックスタートガイド

## Docker環境の起動

### PyTorchバージョンのカスタマイズ

デフォルトでは、RTX 5000番台（Blackwell）などの最新GPUに対応するため、**PyTorch 2.9 (CUDA 12.8対応)** を使用します。
特別な設定なしで `docker compose build` を実行すれば、最新の環境が構築されます。

安定版を使用したい場合は、`DOCKER_SETUP.md` を参照してください。

cudaは12.8,pytorchは2.9.0をインストールしている. \      
参考：https://en.wikipedia.org/wiki/CUDA#GPUs_supported
```bash
# コンテナを起動
cd sam3
docker compose up -d

# コンテナに入る
docker exec -it sam3-ros2-dev bash
```

## 環境の確認

コンテナ内で以下のコマンドを実行して、環境が正しくセットアップされているか確認します：

```bash
# ROS2環境のソース（.bashrcに追加済みだが、新しいシェルの場合は手動で実行）
source /opt/ros/humble/setup.bash

# Python バージョン確認
python3 --version
# 出力: Python 3.10.12

# PyTorch 確認
python3 -c "import torch; print('PyTorch:', torch.__version__); print('CUDA Available:', torch.cuda.is_available())"
# 出力: PyTorch: 2.9.0+cu128
#       CUDA Available: True

# SAM3 確認
python3 -c "import sam3; print('SAM3 Version:', sam3.__version__)"
# 出力: SAM3 Version: 0.1.0

# ROS2 確認
ros2 topic list
# 出力: /parameter_events
    　　/rosout

```

## SAM3の基本的な使い方

### 1. Hugging Face認証

```bash
# Hugging Faceにログイン
hf auth login
# アクセストークンを入力
```

事前に以下を実施してください：
1. https://huggingface.co/settings/tokens でアクセストークンを作成 \
"New token" をクリック 
2. https://huggingface.co/facebook/sam3 でSAM3チェックポイントへのアクセス許可をリクエスト

### サンプルコード
```
python3 run_sam3_groceries.py
```
出力はgroceries_result.png
プログラム内の引数で重要なのは
'''
image_pash : 検出したい画像のパス
input_test : 検出したい物体名
'''

### 2. 画像セグメンテーションの例

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
output = processor.set_text_prompt(state=inference_state, prompt="a dog")

# マスク、バウンディングボックス、スコアを取得
masks, boxes, scores = output["masks"], output["boxes"], output["scores"]
```

### 3. サンプルノートブックの実行

利用可能なサンプル：
- `examples/sam3_image_predictor_example.ipynb` - 画像での使用例
- `examples/sam3_video_predictor_example.ipynb` - ビデオでの使用例
- `examples/sam3_image_batched_inference.ipynb` - バッチ推論の例
- その他、`examples/` ディレクトリに多数のサンプルあり

## ROS2との統合

### ROS2の基本動作確認

```bash
# ROS2環境をソース
source /opt/ros/humble/setup.bash

# デモノードを実行
ros2 run demo_nodes_cpp talker

# 別のターミナルで
ros2 topic echo /chatter
```

### SAM3をROS2ノードとして使用する（今後の実装例）

```python
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
from cv_bridge import CvBridge
from sam3.model_builder import build_sam3_image_model
from sam3.model.sam3_image_processor import Sam3Processor

class SAM3Node(Node):
    def __init__(self):
        super().__init__('sam3_node')
        self.subscription = self.create_subscription(
            Image,
            'image_topic',
            self.image_callback,
            10)
        self.bridge = CvBridge()
        self.model = build_sam3_image_model()
        self.processor = Sam3Processor(self.model)
        
    def image_callback(self, msg):
        # ROS ImageをPIL Imageに変換
        cv_image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='rgb8')
        pil_image = Image.fromarray(cv_image)
        
        # SAM3で推論
        inference_state = self.processor.set_image(pil_image)
        output = self.processor.set_text_prompt(
            state=inference_state, 
            prompt="object to segment"
        )
        
        # 結果を処理...
        self.get_logger().info('Processed image')

def main(args=None):
    rclpy.init(args=args)
    node = SAM3Node()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
```

## コンテナ管理コマンド

```bash
# コンテナの停止
docker compose down

# コンテナの再起動
docker compose restart

# コンテナのログ確認
docker compose logs -f

# イメージの再ビルド（Dockerfileを変更した場合）
docker compose build --no-cache
```

## トラブルシューティング

### GPUが認識されない

```bash
# コンテナ内でGPUを確認
nvidia-smi
```

認識されない場合は、ホストのNVIDIA Docker Runtimeを確認してください。

### CUDA互換性の警告

新しいGPU（RTX 5060 Tiなど）では、CUDAの互換性警告が表示される場合がありますが、基本的な機能は動作します。最新のPyTorchビルドが必要な場合は、PyTorchを最新版に更新してください。

### X11ディスプレイエラー

GUIアプリケーションを使用する場合：

```bash
# ホスト側で実行
xhost +local:docker
```

## 次のステップ

1. **サンプルを試す**: `examples/` ディレクトリのJupyter Notebookを実行
2. **ROS2統合**: SAM3をROS2ノードとして実装
3. **カスタムアプリケーション**: 独自のセグメンテーションアプリケーションを開発

## 参考リンク

- [SAM3公式GitHub](https://github.com/facebookresearch/sam3)
- [ROS2 Humble Documentation](https://docs.ros.org/en/humble/)
- [SAM3論文](https://ai.meta.com/research/publications/sam-3-segment-anything-with-concepts/)
- [Docker Compose Documentation](https://docs.docker.com/compose/)
