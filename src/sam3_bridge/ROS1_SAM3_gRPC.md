# ROS1 × SAM3 gRPC 連携

[! CAUITON]
> HSR-OITにあるcatkin下からもってきたものである。
> grpc_bridge.pyとobject_name_bridge.launchのみros2 humble対応させている

## 1.sam3の起動手順

### 1-1. sam3のサーバを起動する
```bash
# sam3側のコンテナで行う
cd grps_sam3-dev
python3 sam3_server.py 
```

### 1-2. HSRでsam3推論のlaunchを起動する
```bash
cd catkin_ws
source devel/setup.bash
roslaunch sam3_bridge bridge.launch 
```

#### sam3のプロンプトの変更方法(セグメント対象)
1. `bridge.launch`を開く(HSRコンテナ側)
```bash
cd ~/HSR/catkin_ws/src/sam3_bridge/launch/
nano bridge.launch
# <param name="prompt" value="plate" /> : valueの値を変更する
```

### 1-3. rvizでの確認方法
1. コンテナの左下のターミナルをクリックしてrvizを起動する

2. dislpayのaddでtopicを追加する
```
/sam/mask     :白黒マスク
/sam/overlay  :セグメント結果を元画像に上書き
```



## システム概要

HSRコンテナ（ROS1 / Python3.8）とSAM3コンテナ（Python3.10 / GPU）をgRPCで連携し、
カメラ画像をリアルタイムでセグメンテーションするシステム。

---

## コンテナ構成

| 項目 | HSRコンテナ | SAM3コンテナ |
|------|------------|-------------|
| Python | 3.8 | 3.10+ |
| ROS | ROS1 Noetic | なし |
| ネットワーク | --network=host | --network=host |
| GPU | なし | --gpus all |
| gRPC役割 | クライアント | サーバー（port: 50051） |

---

## アルゴリズムフロー

```
【HSRコンテナ】                              【SAM3コンテナ】

/hsrb/head_rgbd_sensor
/rgb/image_rect_color
        |
        | subscribe
        ↓
callback()
  └ すぐ返る（ブロックしない）
        |
        | Queue.put(frame)
        | ※古いフレームは破棄（maxsize=1）
        ↓
Workerスレッド
  └ Queue.get() → 最新フレーム取得
        |
        ↓
JPEG圧縮・リサイズ
  └ quality=75 / 640×480上限
        |
        |──── gRPC SegmentImage() ────────→ gRPCサーバー受信
        |                                         |
        |                                    画像デコード
        |                                    (JPEG → numpy)
        |                                         |
        |                                         ↓
        |                                    SAM3推論
        |                                    set_image()
        |                                    set_text_prompt()
        |                                         |
        |                                         ↓
        |                                    オーバーレイ生成
        |                                    mask + JPEG overlay
        |                                         |
        |←──── MaskResponse(mask, overlay) ───────|
        |
        ↓
タイムアウト判定（timeout=2.0秒）
  ├ 超過 → フレームをスキップ
  └ 成功 ↓
        |
        ↓
/sam/mask publish    （mono8：白黒マスク）
/sam/overlay publish （bgr8：カラーオーバーレイ）
```

---

## 非同期Queue設計

callbackとgRPC通信を分離することでリアルタイム性を確保する。

```
ROSスレッド（軽い）         Queue          Workerスレッド（重い）
      |                     |                     |
  callback()                |                     |
      |    put(最新frame)    |                     |
      |─────────────────→  [frame]                |
      |                     |    get()            |
      ↓                     |─────────────────→  |
  すぐ返る                  |               JPEG圧縮
（655msを待たない）          |               gRPC送信（~655ms）
      |                     |               mask publish
  次のframe受信             |                     |
      |    put(最新frame)    |               次のframe待ち
      |─────────────────→  [frame]                |
      ↓                     |─────────────────→  |
  すぐ返る                  |               gRPC送信...
```

### Queueサイズ=1の意味

```
Worker処理中（655ms）に複数フレームが届いた場合：

時刻  0ms : frameA → Queue投入 [A]
時刻100ms : frameB → Aを捨てBを投入 [B]  ← 古いフレームを破棄
時刻200ms : frameC → Bを捨てCを投入 [C]  ← 常に最新を保持
時刻655ms : Worker完了 → Cを取り出して処理

→ 常に最新フレームだけを処理する（遅延が蓄積しない）
```

---

## パフォーマンス設定

| パラメータ | 値 | 説明 |
|-----------|-----|------|
| `jpeg_quality` | 75 | JPEG圧縮品質 |
| `max_width` | 640 | 送信画像の最大幅 |
| `max_height` | 480 | 送信画像の最大高さ |
| `grpc_timeout` | 2.0秒 | gRPCタイムアウト |
| `sam3_resolution` | 256〜504px | SAM3推論解像度 |
| Queue `maxsize` | 1 | 常に最新フレームのみ保持 |

---

## ROSトピック

| トピック名 | 型 | 方向 | 説明 |
|-----------|-----|------|------|
| `/hsrb/head_rgbd_sensor/rgb/image_rect_color` | `sensor_msgs/Image` | 入力 | ヘッドカメラ画像 |
| `/sam/mask` | `sensor_msgs/Image` | 出力 | 白黒マスク（mono8） |
| `/sam/overlay` | `sensor_msgs/Image` | 出力 | カラーオーバーレイ（bgr8） |

---

## gRPCインターフェース

```protobuf
syntax = "proto3";
package seg;

service SegmentService {
  rpc SegmentImage (ImageRequest) returns (MaskResponse);
}

message ImageRequest {
  bytes  image   = 1;  // JPEG圧縮済み画像
  int32  width   = 2;
  int32  height  = 3;
  string prompt  = 4;  // 検出対象（例："person", "plate"）
}

message MaskResponse {
  bytes  mask          = 1;  // uint8マスク（0 or 1）
  int32  width         = 2;
  int32  height        = 3;
  int32  num_objects   = 4;  // 検出オブジェクト数
  float  inference_ms  = 5;  // 推論時間（ms）
  bytes  overlay_image = 6;  // JPEG圧縮済みオーバーレイ画像
}
```

---

## 統計・モニタリング

### HSR側（10秒ごと）

```
[Bridge] 統計 | 受信:3583 破棄:3467 送信成功:83 失敗:31
```

| 項目 | 説明 |
|------|------|
| 受信 | callbackでフレームを受信した総数 |
| 破棄 | Queueが満杯で破棄したフレーム数 |
| 送信成功 | gRPCで正常に推論結果を受け取った数 |
| 失敗 | タイムアウトなどでスキップした数 |

### SAM3側（10秒ごと）

```
[SAM3] 推論Hz: 0.50 Hz (5フレーム / 10.0秒)
```

### RVizでの確認

```bash
# マスク確認（白黒）
# RViz → Add → By topic → /sam/mask → Image

# オーバーレイ確認（カラー）
# RViz → Add → By topic → /sam/overlay → Image

# Hzのリアルタイム確認
rostopic hz /sam/mask
rostopic hz /sam/overlay
```

---

## ファイル構成

```
catkin_ws/src/sam3_bridge/
├── launch/
│   └── bridge.launch           # launchファイル
├── scripts/
│   ├── grpc_bridge.py          # ROSノード（非同期Queue設計）
│   ├── segment_overlay.proto   # protoファイル
│   ├── segment_overlay_pb2.py  # 自動生成
│   └── segment_overlay_pb2_grpc.py  # 自動生成

/workspace/grps_sam3-dev/
├── sam3_server.py              # gRPCサーバー（SAM3推論）
├── segment_overlay.proto       # protoファイル（HSRと共通）
├── segment_overlay_pb2.py      # 自動生成
└── segment_overlay_pb2_grpc.py # 自動生成
```

---