# Cotyaka Robot Core 自動起動

NUC 上でコチャカの Robot Core を自動起動するための構成です。

## 起動シーケンス

```text
systemd
  -> scripts/robot_core.sh preflight
       -> Docker daemon確認
       -> CAN(can0/1Mbps)設定・確認
       -> workspace build済み確認
  -> docker compose
       -> piper-robot-core
       -> kobuki-robot-core
  -> ROS 2 launch (piper-robot-core)
       -> Piper driver
       -> robot_state_publisher
       -> MoveIt move_group
       -> piper_moveit_bridge
       -> system_supervisor (LifecycleNode)
  -> Lifecycle
       unconfigured -> inactive -> active
  -> Supervisor
       BOOTING
       WAITING_PIPER
       WAITING_KOBUKI
       WAITING_ROS_GRAPH
       READY
```

`systemd` の active は「Composeの起動要求が成功した」ことを意味します。ロボット全体が使用可能かどうかの最終判定は `/cotyaka/system_state` を使用します。

## 追加ファイル

- `docker/dockerfile.robot-core`: GPU非搭載NUC向けCPU-only ROS 2 image
- `docker/docker-compose.robot-core.yml`: Piper/Kobuki Robot Core stack
- `src/cotyaka_bringup/`: ROS 2 bringup + Lifecycle Supervisor
- `scripts/setup_robot_core.sh`: 初回build
- `scripts/robot_core.sh`: preflight/start/stop/status/logs
- `systemd/cotyaka-robot-core.service`: OS boot連携
- `systemd/robot-core.env.example`: NUC固有設定
- `scripts/install_robot_core_service.sh`: systemd導入補助

## 前提ディレクトリ

Composeの既存構成に合わせ、Piper workspaceとKobuki workspaceを兄弟ディレクトリとして配置します。

```text
<parent>/
  piper_ros/
  oit_kobuki_ws-main/
```

## 1. 初回セットアップ

`fix-humble-dev` から本構成を含むブランチをcheckout後、NUCで次を実行します。

```bash
cd /path/to/piper_ros
bash scripts/setup_robot_core.sh
```

これはDocker imageのbuild、ROS依存関係の解決、Piper/Cotyaka workspaceとKobuki workspaceの`colcon build`を行います。通常の電源投入時にはbuildしません。

## 2. systemdへ登録

```bash
sudo bash scripts/install_robot_core_service.sh
```

必要なら次を編集します。

```bash
sudo nano /etc/cotyaka/robot-core.env
```

既定値:

```text
ROS_DOMAIN_ID=12
CAN_INTERFACE=can0
CAN_BITRATE=1000000
```

## 3. 手動テスト

自動起動を有効化する前後で、次のコマンドから個別確認できます。

```bash
bash scripts/robot_core.sh preflight
bash scripts/robot_core.sh up
bash scripts/robot_core.sh status
bash scripts/robot_core.sh logs
bash scripts/robot_core.sh down
```

## 4. systemd操作

```bash
sudo systemctl start cotyaka-robot-core
sudo systemctl stop cotyaka-robot-core
sudo systemctl restart cotyaka-robot-core
systemctl status cotyaka-robot-core
journalctl -u cotyaka-robot-core -f
```

`install_robot_core_service.sh` は `systemctl enable` まで行うため、その後のOS起動から自動起動されます。

## 5. ROS側のREADY確認

```bash
docker exec -it cotyaka-piper-robot-core bash -lc \
  'source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && ros2 topic echo /cotyaka/system_state'
```

最終的に次になれば Robot Core READY です。

```text
data: READY
```

Supervisorは現在、次を確認します。

- `/joint_states` が一定時間内に更新されていること
- `/odom` が一定時間内に更新されていること
- `/piper_ctrl_single_node`
- `/move_group`
- `/piper_moveit_bridge`

設定は `src/cotyaka_bringup/config/supervisor.yaml` で変更できます。

## 注意点

### Kobukiのodom topic

Supervisorは現時点で `/odom` を既定値としています。実際のKobuki構成で別topic名を使用している場合は `supervisor.yaml` の `odom_topic` を変更してください。

### Lifecycleの担当範囲

既存のPiper driverやMoveItを無理にLifecycleNodeへ変更していません。`system_supervisor` 自身だけをLifecycle管理し、既存ノードの起動状態とheartbeatを監視してRobot Core全体のREADY gateにします。

### Alienwareとの接続

NUC側Composeの既定 `ROS_DOMAIN_ID` は既存開発構成に合わせて12です。Alienware側も同じDomain IDにすれば同一ROS 2 graphとして通信できます。上位AIは `/cotyaka/system_state == READY` を確認してからSkill要求を出す設計を想定します。
