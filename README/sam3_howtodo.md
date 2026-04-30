# SAM3 ROS1/ROS2 起動メモ

このメモは、`sam3` の高速化版を ROS1 / ROS2 から起動するための最小手順と、topic/frame 名の対応関係をまとめたものです。

## 直接起動

### ROS2

```bash
docker exec piper-humble-dev bash -lc '
cd /ros2_ws/src/sam3 &&
sam3-dual-ros --backend ros2   --image-topic /camera/camera/color/image_raw   --prompt-topic /sam3/request   --annotated-topic /sam3/debug_image   --masks-topic /sam3/masks   --boxes-topic /sam3/boxes   --scores-topic /sam3/scores'
```

### ROS1

```bash
docker exec piper-humble-dev bash -lc '
cd /ros2_ws/src/sam3 &&
sam3-dual-ros --backend ros1   --image-topic /camera/camera/color/image_raw   --prompt-topic /sam3/request   --annotated-topic /sam3/debug_image   --masks-topic /sam3/masks   --boxes-topic /sam3/boxes   --scores-topic /sam3/scores'
```

### 自動判定

```bash
docker exec piper-humble-dev bash -lc '
cd /ros2_ws/src/sam3 &&
sam3-dual-ros --backend auto'
```

## launch 起動

### ROS2 launch

```bash
docker exec piper-humble-dev bash -lc '
cd /ros2_ws/src/sam3 &&
ros2 launch sam3_dual_ros sam3.launch.py   image_topic:=/camera/camera/color/image_raw   prompt_topic:=/sam3/request   annotated_topic:=/sam3/debug_image   masks_topic:=/sam3/masks   boxes_topic:=/sam3/boxes   scores_topic:=/sam3/scores'
```

### ROS1 launch

```bash
docker exec piper-humble-dev bash -lc '
cd /ros2_ws/src/sam3 &&
```

## 対応表

| 設定項目 | 役割 | 設定場所 |
|---|---|---|
| `--backend` | ROS1 / ROS2 / 自動判定を切り替える | `sam3_ros/cli.py` |
| `--node-name` | ノード名 | `sam3_dual_ros/cli.py` / launch 引数 |
| `--checkpoint-path` | チェックポイントの明示指定 | `sam3_ros/cli.py` / launch 引数 |
| `--device` | 推論デバイス | `sam3_ros/cli.py` / launch 引数 |
| `--resolution` | 推論解像度 | `sam3_ros/cli.py` / launch 引数 |
| `--text-prompt` | テキストプロンプト | `sam3_ros/cli.py` / launch 引数 |
| `--image-topic` | 入力画像 topic | `sam3_ros/cli.py` / launch 引数 |
| `--prompt-topic` | 推論要求を受ける topic | `sam3_ros/cli.py` / launch 引数 |
| `--annotated-topic` | アノテーション済み画像の出力先 | `sam3_ros/cli.py` / launch 引数 |
| `--masks-topic` | マスク出力先 | `sam3_ros/cli.py` / launch 引数 |
| `--boxes-topic` | bbox 出力先 | `sam3_ros/cli.py` / launch 引数 |
| `--scores-topic` | スコア出力先 | `sam3_ros/cli.py` / launch 引数 |
| `--frame-id` | TF / 座標系名 | `sam3_ros/cli.py` / launch 引数 |
| `--input-encoding` | 画像 encoding | `sam3_ros/cli.py` / launch 引数 |
| `--queue-size` | subscriber / publisher のキューサイズ | `sam3_ros/cli.py` / launch 引数 |
| `--keep-all-frames` | 忙しいときにフレームを捨てるか | `sam3_ros/cli.py` |

## 反映の順番

1. `sam3_ros/config.py` のデフォルト値を現場の topic / frame 名に合わせる
2. 起動時に CLI または launch 引数で上書きする
3. ROS1 なら `sam3_dual_ros/launch/sam3.launch`、ROS2 なら `sam3_dual_ros/launch/sam3.launch.py` を使う

## 補足

- `sam3_dual_ros` は既存の `sam3_ros` と名前を分けた別エントリです。
- launch ファイルは `sam3-dual-ros` の CLI を呼ぶだけなので、中身の推論ロジックは同じです。
- `--backend auto` は `ROS_VERSION` を優先し、未設定なら ROS2 を先に試してから ROS1 を試す best-effort 判定です。環境が曖昧なら `ros1` / `ros2` を明示する方が安全です。
- ROS1 launch の XML はテンプレートです。ROS1 側で実際に使うなら、`rospy` と `sam3-dual-ros` が使える ROS1 環境に載せてください。
- 既存の `sam3_ros` 側の固定 topic 名を流用してもよいです。
