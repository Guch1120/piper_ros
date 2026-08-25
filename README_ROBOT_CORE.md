# Cotyaka 自動起動 / Robot Core / System Monitor / Audio

NUC 上でコチャカを電源投入後に自動起動するための構成です。

## 設計方針

Robot Core と監視系を分離します。

```text
systemd
  -> host bootstrap (scripts/robot_core.sh)
       -> Docker確認
       -> Piper接続確認
       -> Kobuki接続確認
       -> 今回起動する hardware core を決定
  -> Docker Compose
       -> cotyaka-audio          (常時)
       -> cotyaka-system-monitor (常時)
       -> piper-robot-core       (Piper検出時のみ)
       -> kobuki-robot-core      (Kobuki検出時のみ)
  -> ROS 2
       -> System Monitor は LifecycleNode として独立監視
       -> Robot Core は監視ノードを含まない
```

接続されていないロボットを故障扱いして起動全体を失敗させません。

- Piper + Kobuki 接続: 両方起動
- Piper のみ接続: Piper のみ起動
- Kobuki のみ接続: Kobuki のみ起動
- どちらも未接続: Audio + System Monitor のみ起動

## 接続判定

### Piper

Linux上のCAN interfaceを確認し、`can_activate.sh` で `can0 / 1 Mbps` を設定した後、デフォルトでは `candump` でCAN frameを1つ確認します。

```text
PIPER_PROBE_MODE=can-traffic
```

CAN adapterの存在だけを接続扱いにしたい場合は `/etc/cotyaka/robot-core.env` で次に変更できます。

```text
PIPER_PROBE_MODE=adapter
```

### Kobuki

Kobukiのudev ruleによる `/dev/kobuki` の存在を確認します。別pathなら設定を変更します。

```text
KOBUKI_DEVICE=/dev/kobuki
```

## System Monitor

System Monitorは `piper-robot-core` から分離された `cotyaka-system-monitor` コンテナで常時起動します。Lifecycleは `unconfigured -> inactive -> active` です。

状態topic:

```text
/cotyaka/system_state
```

`std_msgs/String` 内にJSONを格納します。状態は `STARTING`, `READY_FULL`, `READY_PIPER_ONLY`, `READY_KOBUKI_ONLY`, `NO_ROBOT`, `DEGRADED` です。

Piperは `/joint_states` と Piper/MoveIt/bridge のROS graphを監視し、Kobukiは現段階では `/odom` の更新を監視します。

## Audio container

`cotyaka-audio` は起動時に常に立ち上げ、Robot Coreとは独立させます。音声出力は2経路です。

### 固定MP3

Topic:

```text
/cotyaka/audio/play_mp3
```

定型keyは `startup_full`, `startup_piper_only`, `startup_kobuki_only`, `startup_no_robot` です。MP3は次に配置します。

```text
audio/assets/startup_full.mp3
audio/assets/startup_piper_only.mp3
audio/assets/startup_kobuki_only.mp3
audio/assets/startup_no_robot.mp3
```

固定MP3が存在する場合はTTSより優先します。

### TTS

Topic:

```text
/cotyaka/audio/speak
```

任意文を `std_msgs/String` で送信します。

```bash
ros2 topic pub --once /cotyaka/audio/speak std_msgs/msg/String "data: '動作確認を開始します'"
```

TTSはgTTSを第一経路として使用し、利用できない場合は`espeak-ng`日本語音声へフォールバックします。固定MP3が未配置の場合も起動通知はTTSへフォールバックします。

System MonitorがREADYになった時点で一度だけ起動状態を告知します。Audio failureはRobot Coreの停止条件にはしません。

## 初回セットアップ

```bash
bash scripts/setup_robot_core.sh
```

Robot Core, System Monitor, Audio imageと各ROS workspaceを構築します。

## 手動確認

```bash
bash scripts/robot_core.sh probe
bash scripts/robot_core.sh up
bash scripts/robot_core.sh status
bash scripts/robot_core.sh logs
bash scripts/robot_core.sh down
```

## systemd

```bash
sudo bash scripts/install_robot_core_service.sh
```

設定は `/etc/cotyaka/robot-core.env` に保存されます。

```bash
systemctl status cotyaka-robot-core
journalctl -u cotyaka-robot-core -f
```

systemdの`active`はbootstrap/Compose起動完了を表します。実際に使用可能なRobot Coreは `/cotyaka/system_state` を参照します。

## 実機確認が必要な点

1. Piperがドライバ起動前からCAN feedback frameを流すか
2. `PIPER_PROBE_TIMEOUT_SEC=2` が適切か
3. Kobukiのudev symlinkが `/dev/kobuki` か
4. Kobuki odometry topicが `/odom` か
5. NUCのスピーカでDockerからALSA (`/dev/snd`) が再生できるか
6. 固定MP3実ファイルを `audio/assets/` に配置する
