# Cotyaka 自動起動 / Robot Core / System Monitor / Audio

NUC 上でコチャカを電源投入後に自動起動するための構成です。

## 設計方針

Robot Core、監視、音声を分離します。

```text
systemd
  -> host bootstrap (scripts/robot_core.sh)
       -> Docker確認
       -> Piper接続確認
       -> Kobuki接続確認
       -> 今回起動する hardware core を決定
  -> Docker Compose
       -> cotyaka-voicevox       (常時: CPU TTS engine)
       -> cotyaka-audio          (常時: ROS audio I/O + ALSA)
       -> cotyaka-system-monitor (常時: Lifecycle monitor)
       -> piper-robot-core       (Piper検出時のみ)
       -> kobuki-robot-core      (Kobuki検出時のみ)
```

接続されていないロボットを故障扱いして起動全体を失敗させません。

- Piper + Kobuki 接続: 両方起動
- Piper のみ接続: Piper のみ起動
- Kobuki のみ接続: Kobuki のみ起動
- どちらも未接続: VOICEVOX + Audio + System Monitor のみ起動

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

KobukiのFTDI USB serialにudev ruleを適用して `/dev/kobuki` を作り、その存在を接続条件にします。

初回セットアップでは `scripts/install_kobuki_udev.sh` が `udev/60-kobuki.rules` を `/etc/udev/rules.d/60-kobuki.rules` に導入します。手動実行もできます。

```bash
bash scripts/install_kobuki_udev.sh
ls -l /dev/kobuki
```

USB cableが既に接続されていてsymlinkが作られない場合は、一度抜き差ししてください。

```text
KOBUKI_DEVICE=/dev/kobuki
```

`/dev/kobuki` が無い一方で `/dev/ttyUSB*` が存在すると、`robot_core.sh probe` はudev未設定の可能性を警告します。

## System Monitor

System Monitorは Robot Core から分離された `cotyaka-system-monitor` コンテナで常時起動します。Lifecycleは `unconfigured -> inactive -> active` です。

状態topic:

```text
/cotyaka/system_state
```

`std_msgs/String` 内にJSONを格納します。状態は `STARTING`, `READY_FULL`, `READY_PIPER_ONLY`, `READY_KOBUKI_ONLY`, `NO_ROBOT`, `DEGRADED` です。

Piperは `/joint_states` と Piper/MoveIt/bridge のROS graphを監視し、Kobukiは現段階では `/odom` の更新を監視します。

## Audio / VOICEVOX

音声系はRobot Coreから独立しています。

```text
ROS topic
   -> cotyaka-audio
        -> fixed WAV cache
        -> VOICEVOX HTTP API (cache miss / arbitrary TTS)
   -> aplay / ALSA
   -> speaker
```

VOICEVOXは公式CPU Docker image `voicevox/voicevox_engine:cpu-latest` を `cotyaka-voicevox` として起動します。HTTP APIはホストloopbackの `127.0.0.1:50021` にだけ公開します。

### 固定通知

Topic:

```text
/cotyaka/audio/play_fixed
```

定型key:

```text
startup_full
startup_piper_only
startup_kobuki_only
startup_no_robot
```

本文は `audio/config/startup_messages.json` で管理します。録音ファイルは不要です。

最初にkeyが要求されたときVOICEVOXでWAVを生成し、次へ保存します。

```text
audio/cache/startup_full.wav
audio/cache/startup_piper_only.wav
audio/cache/startup_kobuki_only.wav
audio/cache/startup_no_robot.wav
```

2回目以降はVOICEVOXで再合成せず、cacheを即再生します。文面やVOICEVOX話者を変えた場合は該当cacheを削除すると再生成されます。

### 任意TTS

Topic:

```text
/cotyaka/audio/speak
```

例:

```bash
ros2 topic pub --once /cotyaka/audio/speak std_msgs/msg/String \
  "data: '動作確認を開始します'"
```

VOICEVOXの `/audio_query` と `/synthesis` を使用してリアルタイムにWAVを生成し、`aplay` で再生します。gTTS / espeak-ngは使用しません。

話者・話速・ALSA deviceは `/etc/cotyaka/robot-core.env` で変更できます。

```text
VOICEVOX_SPEAKER_ID=1
VOICEVOX_SPEED_SCALE=1.0
COTYAKA_AUDIO_DEVICE=default
```

利用可能なVOICEVOX style idは、Engine起動後に次で確認できます。

```bash
curl http://127.0.0.1:50021/speakers
```

System MonitorはREADYになった時点で一度だけ固定通知keyを送ります。Audio/VOICEVOX failureはRobot Coreの停止条件にはしません。

## 初回セットアップ

```bash
bash scripts/setup_robot_core.sh
```

この処理で以下を行います。

- Kobuki udev rule導入
- VOICEVOX CPU image pull
- Robot Core / System Monitor / Audio image build
- Piper/Cotyaka ROS workspace build
- Kobuki ROS workspace build

`/dev/kobuki` がまだ無い場合はKobuki USB cableを抜き差しして確認してください。

## 手動確認

```bash
bash scripts/robot_core.sh probe
bash scripts/robot_core.sh up
bash scripts/robot_core.sh status
bash scripts/robot_core.sh logs
bash scripts/robot_core.sh down
```

音声だけ確認する場合:

```bash
docker compose -f docker/docker-compose.robot-core.yml up -d cotyaka-voicevox cotyaka-audio
source /opt/ros/humble/setup.bash
ros2 topic pub --once /cotyaka/audio/speak std_msgs/msg/String "data: '音声テストです'"
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
3. udev適用後に `/dev/kobuki -> /dev/ttyUSB*` が生成されるか
4. Kobuki odometry topicが `/odom` か
5. NUCのスピーカでDockerから `aplay` / ALSA (`/dev/snd`) が再生できるか
6. 使用するVOICEVOX speaker/style idとその利用条件
