# 実機↔Webシミュレータ テレオペブリッジ (piper_leader_follower_bridge)

実物のPiperアーム（リーダー）の関節状態を、rosbridge経由でWeb版MuJoCoシミュレータ
（フォロワー、React + Three.js + MuJoCo-WASM、別リポジトリ `sirius-mujoco-sim`）へ
リアルタイムに反映するためのブリッジ。

このノードは既存の `piper_single_ctrl_node.py` / `moveit_bridge.py` を一切変更しない、
完全にopt-inの新規ノード。起動しなければ既存の挙動には何も影響しない。

## 起動方法

1台目の端末でrosbridgeを起動する（ポート9090、plain ws://）:

```bash
ros2 launch piper rosbridge_websocket.launch.py
```

2台目の端末で実機ドライバを起動する（既存）:

```bash
ros2 launch piper start_single_piper.launch.py
```

3台目の端末でこのブリッジを起動する（デフォルトは一方向のみ）:

```bash
ros2 launch piper piper_leader_follower_bridge.launch.py
```

双方向テストモードを最初から有効にして起動する場合:

```bash
ros2 launch piper piper_leader_follower_bridge.launch.py bidirectional_enabled:=true
```

Web側は `ws://<ROS側ホスト>:9090` へ接続する（同一PCなら `ws://localhost:9090`）。

## 2つのモード

### 一方向モード（デフォルト、常時有効）

ブリッジ起動中は常にこのモードが動く。実機の関節状態を200Hzで購読し、
`publish_rate_hz`（デフォルト30Hz）へ間引いてWebシミュレータへ配信するだけで、
実機へは一切書き込まない。**ハードウェアへのリスクはゼロ。**

### 双方向テストモード（opt-in、デフォルトOFF）

ROS 2パラメータ `bidirectional_enabled`（bool、デフォルト `false`）で有効化する。
このパラメータは標準の `set_parameters` サービスでいつでも切り替え可能なので、
**Web GUIのチェックボックスは、rosbridgeの `call_service` で
`/piper_leader_follower_bridge/set_parameters` を呼び、
`bidirectional_enabled` を true/false に設定するだけでよい**
（このブリッジ側に専用サービスを追加する必要はない）。

有効時は、Webシミュレータの現在の関節状態（`/sim/piper/joint_state_feedback`）を、
下記の安全条件をすべて満たした場合のみ実機の生コマンドトピック（`joint_ctrl_single`）
へ転送する。**実機側は「有効化されていて、かつ受信したものをそのままCANへ流す」だけの
生パススルーであり、レート制限も平滑化も一切持たない。** そのためこのブリッジ自体が
唯一の安全層になる。

## 安全パラメータ一覧

| パラメータ | デフォルト | 意味・根拠 |
|---|---|---|
| `publish_rate_hz` | `30.0` | 実機200Hzの関節状態をWebへ配信する際の間引きレート。200Hzのままだとブラウザ側WebSocket・描画に無駄な負荷をかけるため間引く。 |
| `bidirectional_enabled` | `false` | 双方向テストモードの有効/無効。Web GUIのチェックボックスがここを切り替える。**必ずOFFがデフォルト。** |
| `heartbeat_timeout_ms` | `500` | `/sim/piper/joint_state_feedback` の受信間隔がこれを超えたら転送を即座に停止し、警告ログを出す。Web側が切断・タブ非表示・ネットワーク断になった場合に実機が「最後の指令のまま暴走・追従し続ける」ことを防ぐ。 |
| `max_step_rad` | `0.05` [rad] | Webから来た目標関節角を、実機の「直近に観測した実角度」（`/joint_states` 由来、指令値ではなく実測値）からこの量までしかクランプして転送しない。1メッセージあたりの移動量に必ず上限がかかる。 |

いずれのパラメータも `ros2 param set /piper_leader_follower_bridge <name> <value>`、
または起動時に `ros2 launch piper piper_leader_follower_bridge.launch.py <name>:=<value>`
で変更できる。

### 双方向転送が成立する3条件（すべて必須）

1. **有効化 (a)**: 実機が有効化されている（`enable_flag` トピックで追跡）。
   - 注意：これは `piper_single_ctrl_node.py` の `enable_callback` が購読しているのと
     同じfire-and-forgetなトピックを、このブリッジ側でも受信してローカルに
     最後の状態を覚えているだけであり、モータードライバの実ACK（CANの
     `driver_enable_status`）を毎回読み戻しているわけではない。将来、実ACKを
     配信するトピックが追加されたら、そちらを優先するように変更すること。
2. **ハートビート (b)**: `/sim/piper/joint_state_feedback` を
   `heartbeat_timeout_ms` 以内に受信していること。転送はメッセージ受信コールバック内
   でのみ同期的に行われるため、「直近に受信していなければ転送されない」という性質は
   構造上常に成り立つ。ウォッチドッグタイマーはこれとは別に、喪失/復帰の遷移を
   ログへ明示的に警告出力するために存在する。
3. **クランプ (c)**: 各関節の移動量を `max_step_rad` 以内に制限する。基準は
   「直前に転送した指令」ではなく「実機の直近の実測位置」。これにより、
   ハートビート断からの復帰直後などにシムと実機が大きく乖離していても、
   1メッセージあたりの動きは必ず有界になる。

いずれかが満たされない場合、そのメッセージは**転送されずスキップ**され
（クランプは「切り捨てずに丸める」が、条件(a)(b)が不成立の場合は転送自体をしない）、
`throttle_duration_sec=2.0` で警告ログが出る。

## トピック契約

### 実機側（ROS 2、このワークスペース）

| 方向 | トピック | 型 | 説明 |
|---|---|---|---|
| 購読 | `/joint_states` | `sensor_msgs/JointState` | `piper_single_ctrl_node.py` が200Hzで配信する実機の関節角（joint1〜joint6 + gripper、計7要素）。 |
| 購読 | `enable_flag` | `std_msgs/Bool` | 実機の有効化状態をローカル追跡するために購読（上記の注意点を参照）。 |
| 購読（双方向時のみ使用） | `/sim/piper/joint_state_feedback` | `sensor_msgs/JointState` | Webシムの現在の関節状態。ハートビート兼、転送元データ。 |
| 配信 | `/sim/piper/joint_targets` | `sensor_msgs/JointState` | Webシムを駆動する目標関節角（`publish_rate_hz` に間引き済み）。 |
| 配信（双方向時のみ） | `joint_ctrl_single` | `sensor_msgs/JointState` | 実機ドライバの生コマンドトピック。安全条件を全て満たした場合のみ配信。 |

### rosbridge（`rosbridge_websocket.launch.py`）

- ポート `9090`（plain `ws://`）がデフォルト。LAN内利用を想定。
- `wss://`（TLS）が必要になった場合（例：WebフロントエンドをHTTPSで公開する場合、
  ブラウザのmixed-content制約によりwssが必須になる）は、
  - `rosbridge_websocket` 自体が `ssl:=true certfile:=... keyfile:=...` の
    launch引数を持っているのでそれを使うか、
  - 別途TLS終端のリバースプロキシ/サイドカーをこのplain wsポートの前段に置く
  （`sirius-mujoco-sim` 側が採用している `rosbridge_tls`／ポート9091・自己署名証明書
  のコンテナ構成が参考になる）
  必要があるが、**現時点ではどちらも未配線**（`rosbridge_websocket.launch.py` の
  コメント参照）。
- `rosapi_node` も同時に起動する。Web側の「ROS診断」タブが `/rosapi/nodes` /
  `/rosapi/topics` を利用するため。

### Web側（`sirius-mujoco-sim`、別リポジトリ、このワークスペースには存在しない）

- 既存で `/sim/piper/joint_targets`（`sensor_msgs/msg/JointState`）を購読し、
  シム側6軸+グリッパを駆動する実装が既にある。
- `/sim/piper/joint_state_feedback` は本タスクで新規に定義した契約であり、
  **Web側にはまだ実装されていない可能性が高い**（別リポジトリのため未確認）。
  双方向モードを実際に使うには、Web側でシムの現在関節角を周期的に
  この名前・型で配信する実装を追加する必要がある。
- Web GUIのチェックボックス実装は、rosbridgeの `call_service` で
  `/piper_leader_follower_bridge/set_parameters`
  （`rcl_interfaces/srv/SetParameters`）を呼び、`bidirectional_enabled` を
  設定するだけでよい。

## 関節名マッピングに関する未確認事項

`piper_single_ctrl_node.py` は `joint1`〜`joint6` + `gripper`（計7要素）という名前で
関節状態を配信・受信する。Webシム側の期待する名前・順序は
`sirius-mujoco-sim/src/robots/cotyaka/runtime/Runtime.ts` の `armJointIndex()` 関数が
決めているが、**このワークスペースには存在せず直接確認できていない**。
同リポジトリの `cotyaka/docs/ros_interface.md` には
「joint1〜joint8へ名前で適用」という記述があり、グリッパーが単一の `gripper` ではなく
`joint7`/`joint8` のような2関節名で表現されている可能性がある（未確認）。

`piper_leader_follower_bridge.py` 内の `JOINT_NAME_MAP` 辞書
（キーは実機側の名前で固定、値のみ変更可）に、確認が取れ次第マッピングを追記すること。
現状はキー=バリューの恒等写像。

## 設計根拠

Web調査（このリポジトリ内には一次資料なし、実装時点の調査結果）に基づく設計判断：

- **なぜソフトウェアブリッジなのか**：AgileXの `piper_sdk` はCANレベルの
  `MasterSlaveConfig` で物理的な実機同士のマスター/スレーブ構成をサポートするが、
  これは両者が実機であることが前提であり、片方がシミュレータである本ケースには
  適用できない。よって本タスクのようなソフトウェアブリッジが妥当な構成となる。
- **ステップ毎クランプ（`max_step_rad`）**：このPiperアーム向けのLeRobot統合
  `lerobot_robot_piper` は、リーダー/フォロワーのテレオペ実装において
  「1ステップあたりの関節移動量を制限する設定可能な安全上限」を持つ。
  本ブリッジの `max_step_rad` クランプはこのパターンを踏襲したもの。
- **一般的なトピックインターフェース（将来のVRテレオペ対応）**：AgileX自身が
  公開しているQuest 3 VRテレオペ統合（roboticscenter.aiで外部公開されている資料）は、
  「外部コントローラ → Pythonブリッジ → piper_sdk → CAN」という構成で、
  約50Hzで状態をサンプリングし、保守的なゲイン/スケールから開始して関節角を
  監視しながら徐々に上げていくことを推奨している。これは「外部コントローラ
  （＝本タスクではrosbridge接続のWebシム、将来的にはVRヘッドセット）→本ブリッジ→
  piper_sdk→CAN」という構成がAgileX自身の推奨する統合形状そのものであることを示す。
  そのため本ブリッジのトピック（`/sim/piper/joint_targets`,
  `/sim/piper/joint_state_feedback`）は特定クライアントに依存しない汎用的な設計とし、
  将来VR駆動のクライアントが同じトピックへそのまま接続できるようにしてある。

## 未実施・今後の課題

- 実機・Webシム双方を実際に接続した往復動作確認は未実施（本タスクは実装のみ）。
- Web側の `/sim/piper/joint_state_feedback` 配信実装、およびGUIチェックボックスの
  実装は別リポジトリの作業として未着手。
- `enable_flag` のローカル追跡を実ACK読み戻しへ置き換える改善は未実施。
- VRヘッドセット連携は本タスクの対象外（トピック互換性のみ考慮）。
