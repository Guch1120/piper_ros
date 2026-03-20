# SAM3 高速推論の再現手順

## 前提
- ホストではなく Docker 内で実行する。
- 作業コンテナ名は `sam3-ros2-dev`。
- リポジトリの作業ディレクトリは `/workspace/sam3`。
- 検証データは `data/val2017` を使う。

## コンテナ起動
```bash
docker compose up -d
docker ps --format '{{.Names}}\t{{.Status}}'
```

## 必要ライブラリ
通常の PyTorch / torchvision / onnxruntime-gpu はコンテナイメージに入っている前提。

TensorRT 切り分けを再現したい場合だけ、以下をコンテナ内で実行する。
```bash
docker exec sam3-ros2-dev bash -lc \
  'NVIDIA_TENSORRT_DISABLE_INTERNAL_PIP=1 python3 -m pip install --extra-index-url https://pypi.nvidia.com tensorrt-cu12==10.15.1.29'
docker exec sam3-ros2-dev bash -lc \
  'echo /usr/local/lib/python3.10/dist-packages/tensorrt_libs > /etc/ld.so.conf.d/tensorrt.conf && ldconfig'
```

## 10FPS 到達構成
現時点の有力構成は `resolution=644` と `skip-block-count=4`。

単一クラスの再現実行:
```bash
docker exec sam3-ros2-dev bash -lc '
cd /workspace/sam3 &&
python3 scripts/benchmark_val2017.py \
  --image-dir data/val2017 \
  --prompt person \
  --limit 6 \
  --resolution 644 \
  --selection-resolution 854 \
  --use-autocast \
  --warmup-images 1 \
  --seed 123 \
  --selection-prompt person \
  --selection-min-detections 1 \
  --selection-pool-size 18 \
  --selection-max-trials 256 \
  --skip-block-count 4
'
```

複数クラスの再現確認は、`--prompt` と `--selection-prompt` を同じにして逐次実行する。
```bash
docker exec sam3-ros2-dev bash -lc '
cd /workspace/sam3 &&
python3 scripts/benchmark_val2017.py \
  --image-dir data/val2017 \
  --prompt truck \
  --limit 6 \
  --resolution 644 \
  --selection-resolution 854 \
  --use-autocast \
  --warmup-images 1 \
  --seed 123 \
  --selection-prompt truck \
  --selection-min-detections 1 \
  --selection-pool-size 18 \
  --selection-max-trials 1024 \
  --skip-block-count 4
'
```

## 20FPS 探索の実行
20FPS を狙う場合も、まずは同じ条件のまま `--resolution` だけを変えて比較する。
```bash
docker exec sam3-ros2-dev bash -lc '
cd /workspace/sam3 &&
python3 scripts/benchmark_val2017.py \
  --image-dir data/val2017 \
  --prompt person \
  --limit 6 \
  --resolution 560 \
  --selection-resolution 854 \
  --use-autocast \
  --warmup-images 1 \
  --seed 123 \
  --selection-prompt person \
  --selection-min-detections 1 \
  --selection-pool-size 18 \
  --selection-max-trials 1024 \
  --skip-block-count 4
'
```

現時点の傾向では、`560` までは候補だが、`504` 以下は精度低下が急に大きくなる。

## 結果の見方
- 数値サマリ: `result/benchmark_val2017/<run_name>/summary.json`
- 画像ごとの内訳: `result/benchmark_val2017/<run_name>/per_image.csv`
- 可視化 PNG: `result/benchmark_val2017/<run_name>/visualizations/<prompt>/*.png`

`visualizations` が空なら、その run は `--skip-visualizations` 付きで実行されている。

## よく使う実行
デモ画像 1 枚で動作確認:
```bash
docker exec sam3-ros2-dev bash -lc '
cd /workspace/sam3 &&
python3 run_sam3_groceries.py
'
```

クラス別に評価する場合は `--prompt` と `--selection-prompt` を同じ名前にそろえる。例: `cat`, `bicycle`, `bus`。
ベンチは並列ではなく逐次実行を推奨する。複数同時起動すると GPU/VRAM 負荷で結果がぶれやすい。
