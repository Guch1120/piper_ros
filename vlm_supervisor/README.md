# VLM Supervisor × FlexBE

FlexBE の Nominal execution を維持したまま、VLM を上位の状況判断層として追加する。
仕様全体 (Phase 1〜6) は設計書を参照。ここでは実装状況と確認手順だけを書く。

## 実装状況

| Phase | 内容 | 状態 |
|---|---|---|
| 1 | ROS Topics → Observation | 実装済み (`ros2/observation_adapter.py`, `core/observation.py`) |
| 2 | FlexBE → FlexBEContext | 実装済み (`ros2/flexbe_adapter.py`, `core/flexbe_context.py`) |
| 3 | SupervisorInput / snapshot | 実装済み (`core/snapshot.py`, `tools/show_snapshot.py`) |
| 4 | iPhone VLM 通信 | 実装済み (`core/iphone_client.py`, `tools/check_iphone.py`) — 実機 iPhone では未確認 |
| 5 | Shadow Mode | 実装済み (`vlm.enabled: true`)。記録のみで、FlexBE には介入しない |
| 6 | Intervention / Recovery | データ構造だけ (`skill_registry.py`, `recovery_planner.py`, `behavior_orchestrator.py`) |
| ROS1 | Noetic adapter | 未実装 (stub だけ) |

`core/` は ROS に依存しない (rclpy / sensor_msgs を import しない)。ホストの Python だけでテストできる:

```bash
cd ~/yamaguchi/piper_ros && python3 -m pytest vlm_supervisor/tests -q
```

## 起動

colcon build は不要。`piper_ros` (コンテナ内では `/ros2_ws`) を PYTHONPATH に入れて module として実行する。

```bash
# piper-humble-dev コンテナ内
bash /ros2_ws/vlm_supervisor/scripts/run_ros2.sh
# rosbag 再生時
bash /ros2_ws/vlm_supervisor/scripts/run_ros2.sh --ros-args -p use_sim_time:=true
# 別の設定ファイル
SUPERVISOR_CONFIG=/ros2_ws/vlm_supervisor/config/xxx.yaml TOPICS_CONFIG=... bash /ros2_ws/vlm_supervisor/scripts/run_ros2.sh
```

Service:

```bash
ros2 service call /vlm_supervisor/save_snapshot std_srvs/srv/Trigger   # 今の SupervisorInput を保存
ros2 service call /vlm_supervisor/evaluate_now  std_srvs/srv/Trigger   # 保存 + VLM 評価 (vlm.enabled 時)
```

## ログ (エラー時・実行時の共有)

起動ごとに `vlm_supervisor/logs/<YYYYmmdd_HHMMSS>/` が作られ、`logs/latest` が最新の run を指す。
このディレクトリはホストからも見えるので、**「logs/latest を見て」または run 名を伝えれば** Claude が直接読める。

| ファイル | 内容 |
|---|---|
| `console.log` | node の標準出力/エラー全部 (traceback もここ) |
| `env.txt` / `run_info.json` | ROS_DOMAIN_ID・RMW・git rev・使った設定の全文 |
| `supervisor.log` | 主要ログ (購読 topic、FlexBE event、VLM 結果、エラー) |
| `observations.jsonl` | 1秒ごとの各入力の受信数・age・エラー + FlexBE 状態 |
| `events.jsonl` | FlexBE event (behavior 開始/終了、state 進入、outcome、structure 受信) |
| `vlm.jsonl` | VLM の health・評価結果 (prompt、応答テキスト、parse 結果、latency) |
| `snapshots/<seq>_<rostime>_<trigger>/` | `snapshot.json`, `image.jpg`, `state_entry_image.jpg`, `metadata.json`(, `vlm_result.json`) |

ROS graph と FlexBE interface の調査結果は次のコマンドで `logs/ros_env_<date>/` に保存される
(behavior の実行中に走らせると status/heartbeat の実例も取れる):

```bash
bash /ros2_ws/vlm_supervisor/scripts/collect_ros_env.sh
```

コンテナ (root) で作られたログは umask 000 なので、ホストのユーザーでも消せる。

---

## Phase 1: ROS Topics → Observation

`config/supervisor.yaml` は既定で `flexbe.enabled: false`, `vlm.enabled: false`。

1. カメラ・アームを起動する。
2. `collect_ros_env.sh` で topic 名と型を確認し、必要なら `config/topics.yaml` を直す
   (既定: `/camera/camera/color/image_raw`, `/joint_states`, tf `base_link->link6`, `base_link->camera_color_optical_frame`)。
3. `run_ros2.sh` を起動する。5秒ごとに次の行が出る:
   `[obs] image=n42/age0.08s joint_state=n300/age0.01s tf/base_link->link6=n25/age0.00s ...`
   - `NONE` は未受信。括弧内は最後のエラー (tf の LookupException 等)
4. `save_snapshot` を呼び、`snapshots/*/image.jpg` と `metadata.json` を確認する。
5. topic を止めても node が落ちないこと、age が伸びることを確認する。
6. rosbag: `ros2 bag play <bag> --clock` と `use_sim_time:=true` で同じように snapshot が取れることを確認する。

stale 閾値は `observations.jsonl` の age を見てから `stale_thresholds` に設定する。

SAM3 の結果は `topics.yaml` の `objects` で有効化する
(Point / PointStamped / PoseArray / PoseStamped / Int32MultiArray / JSON String に対応)。

## Phase 2: FlexBE → FlexBEContext

`flexbe.enabled: true` にする。購読するもの (flexbe_behavior_engine 2.3.5 のソースで確認済み):

| 情報 | ソース |
|---|---|
| Behavior 開始/終了・id | `/flexbe/status` (BEStatus) |
| Behavior 名 | `/flexbe/log` の "Onboard Behavior Engine starting [名前 : id]" |
| 現在 State | `/flexbe/heartbeat` (1Hz, adler32(path) を structure と照合) / `/flexbe/behavior_update` (GUI mirror) / outcome から次 State を推定 |
| Graph・transition | `/flexbe/mirror/structure` (ContainerStructure) |
| outcome | `/flexbe/debug/current_state` ("path > outcome") |
| userdata | `/get_user_data` service (State 進入時に取得) |
| behavior 入力 | `/flexbe/start_behavior` の input_keys/values |

注意点:
- **supervisor は behavior 開始より前に起動しておく**。structure は behavior 開始時にしか publish されないため。
- `/flexbe/debug/current_state` は state の ROS control が有効な時 (GUI の mirror が接続している時) だけ出る。
  GUI 無しだと outcome が取れず、現在 State は heartbeat (1Hz) だけになる。
- GUI 無しで behavior を起動し structure が取れない場合は `request_structure_if_missing: true` にする
  (GUI の実行中に要求を送ると mirror が structure を再処理するため、既定は false)。
- `get_user_data` を呼ぶたびに、onboard の端末へ userdata 全体が出力される (FlexBE 側の仕様)。

確認: GUI から behavior を実行し、console に `[flexbe] BEHAVIOR_STARTED`, `STATE_ENTERED`, `STATE_OUTCOME` が出て、
`snapshots/*_STATE_OUTCOME_*/` に active state・graph・userdata が入っていること。

```bash
cd ~/yamaguchi/piper_ros
python3 -m vlm_supervisor.tools.show_snapshot vlm_supervisor/logs/latest/snapshots/00003_*
```

## Phase 3: SupervisorInput / snapshot

`snapshot.on_events` の event ごとに (`event_delay_sec` 後に) 保存される。周期保存は `period_sec`。
State 進入時の画像を `state_entry_image.jpg` として持つので、前後比較ができる。
判断基準は「`show_snapshot` の出力と画像だけを見て、人間が状況を判断できるか」。足りない情報があれば追加する。

## Phase 4: iPhone VLM 通信 (ROS 不要)

現在の iPhone アプリ (`Local_LLM_by_using_MobilePhone`) は OpenAI 互換の `/v1/chat/completions` を持つので、
既定はその API を使う (`vlm.api: openai_chat`、画像は data URL)。
専用の `POST /v1/supervisor/evaluate` (multipart: context.json + image) 用の client (`api: supervisor`) も用意してあるが、
アプリ側は未実装。

```bash
# 1. USB 転送 (別ターミナルで動かしたままにする)
bash ~/yamaguchi/Local_LLM_by_using_MobilePhone/scripts/iphone/proxy.sh 8080 8080
# 2. API key (表示はされない)
source ~/yamaguchi/Local_LLM_by_using_MobilePhone/scripts/iphone/get_api_key.sh && export VLM_API_KEY="$API_KEY"
# 3. 疎通確認
cd ~/yamaguchi/piper_ros
python3 -m vlm_supervisor.tools.check_iphone --image vlm_supervisor/logs/latest/snapshots/00001_*/image.jpg
# 4. 保存済み snapshot を評価 (--dry-run で prompt だけ表示、--client mock で iPhone 無し)
python3 -m vlm_supervisor.tools.evaluate_snapshot vlm_supervisor/logs/latest/snapshots/* --client iphone --out eval.jsonl
```

画像入力には iPhone 側で mmproj 付きの GGUF モデル (llama.cpp backend) が読み込まれている必要がある。
コンテナから node で iPhone を使う場合は `network_mode: host` なので `127.0.0.1:8080` にそのまま届く。
`VLM_API_KEY` はコンテナ内の環境変数として渡すこと (ログには出さない)。

## Phase 5: Shadow Mode

`vlm.enabled: true`, `vlm.client: iphone` (先に `mock` で流れを確認するとよい)。
`evaluate_on_events` (既定は STATE_OUTCOME) の snapshot を評価し、`vlm.jsonl` と各 snapshot の `vlm_result.json` に
FlexBE の outcome と VLM の assessment を並べて記録する。iPhone は1件ずつしか処理できないので、評価中に来た依頼は捨てる
(`drop_if_busy`)。捨てた件数も `vlm.jsonl` に残る。

State の目的は `state_descriptions` に1行で書く (成功条件は書かない)。

## ディレクトリ

```text
core/        ROS非依存 (models, observation, flexbe_context, snapshot, prompt_builder,
             decision_parser, iphone_client, supervisor, run_logger, skill_registry, recovery_planner)
ros2/        supervisor_node, observation_adapter, flexbe_adapter, behavior_orchestrator(stub)
ros1/        stub
config/      topics.yaml, supervisor.yaml
scripts/     run_ros2.sh, collect_ros_env.sh
tools/       check_iphone, evaluate_snapshot, show_snapshot (ROS 不要)
tests/       pytest (core と HTTP client)
logs/        実行ログ (git 管理外)
```
