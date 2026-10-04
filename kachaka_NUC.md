# NUC側 作業書 — Robot Core セットアップ再検証

## 背景

NUC (`/home/guch1/ssd_yamaguchi/piper_ros`) 上で `scripts/setup_robot_core.sh` を実行した際、
ビルドエラー・rosdepエラーが多発した。修正はロボット非接続の別PC上で行い、Docker build /
`rosdep install` / `colcon build` が通ることまでは検証済みだが、**実機(Piper CAN, Kobuki USB,
オーディオデバイス)を使う部分はNUC側でしか検証できない**。本書はNUCで行うべき残りの検証手順をまとめる。

対象ブランチ: `fix-humble-dev`

---

## 1. このPC(非接続機)で検証済みの内容

- `docker compose -f docker/docker-compose.robot-core.yml build` — 全イメージビルド成功
  (`cotyaka-piper-robot-core:humble`, `oit-kobuki-ws:humble`)
- Kobuki側 `rosdep install` + `colcon build`(Robot Core閉包 78パッケージ) — 成功
- Piper側 `rosdep install` + `colcon build`(Robot Core閉包 8パッケージ + `mobile_manipulator_description`) — 成功
- 上記は同一コマンドで2回(codex実装時 / 私の独立再検証時)とも再現して成功を確認済み

**検証していないもの**(実機・実環境が必要なため):

- `scripts/install_kobuki_udev.sh`(sudoでのudevルール配置、`/dev/kobuki` 生成)
- `scripts/robot_core.sh preflight / up` の実動作(CAN adapter検出、Kobuki USB検出)
- Piper CANとの実通信、Kobukiとの実通信
- VOICEVOX + オーディオ出力(スピーカー実機)
- `cotyaka-system-monitor` の `expect_piper` / `expect_kobuki` 実挙動
- Nav2 / SLAM Toolbox / urg_node2 の実LiDAR動作

---

## 2. 今回の修正内容(何が変わったか)

### 2.1 rosdep / ビルドエラーの根本原因と修正

1. `cotyaka_bringup` / `cotyaka_system` / `cotyaka_audio` の `package.xml` に、存在しない
   rosdepキー `<buildtool_depend>ament_python</buildtool_depend>` が誤って書かれていた
   → 削除(正しくは `<export><build_type>ament_python</build_type></export>` のみでよい)。
2. `mobile_manipulator_description` が別ワークスペース(`oit_kobuki_ws-main`)にしかない
   `kobuki_description` に依存しており、rosdepの `--from-path` 対象外で未解決になっていた
   → `rosdep install` の `--from-paths` に Kobuki ワークスペースのパスを追加して解決。
3. `detic_onnx_ros2` / `ultralytics` / `ros_tcp_endpoint` はrosdep標準DBに無いサードパーティ依存で、
   いずれも SAM3 / YOLO / Unityシムブリッジ用(=設計上はAlienware側 or シミュレータ用途)。
   → **これらのパッケージはRobot Coreのビルド対象から除外**(後述2.2)。
4. Kobuki側コンテナは Dockerfile ビルド時に `apt list` を消去しているため、`docker compose run`
   のたびにaptキャッシュが空になり `rosdep install` の `apt-get install` が
   `E: Unable to locate package ...` で失敗していた → `rosdep install` 前に明示的に
   `apt-get update` を実行するよう `scripts/setup_robot_core.sh` を修正。

### 2.2 ビルド対象パッケージの絞り込み(アーキテクチャ整合)

`kochaka_architecture_detailed.md` / `kochaka_architecture_summary.md` の方針
(「NUC = Robot Core のみ。LLM/意味的PerceptionはAlienware側」)に従い、NUC向けビルドを
`colcon build --packages-up-to` でRobot Coreに必要な閉包だけに限定した。

- **Piper側**: `cotyaka_bringup`, `cotyaka_system`, `cotyaka_audio` + `mobile_manipulator_description`
  (依存閉包で計9パッケージ)
- **Kobuki側**: `kobuki_node`, `kobuki_description`, `kobuki_safety_controller`, `nav2_bringup`,
  `slam_toolbox`, `urg_node2`(依存閉包で計78パッケージ)

**この結果、SAM3 / YOLO(yolov8_ros) / Detic(piper_flexbe_behaviors) / Unityシムブリッジ
(piper_unity, kobuki_unity) / Gazebo / MuJoCo はこのビルドでは一切生成されない。**
これらを使う開発・検証(Unity連携含む)は、従来通り `docker/docker-compose.yml`
(通常の開発用compose、`docker-compose.robot-core.yml`とは別)側で別途フルビルドすること。

### 2.3 ビルド成果物の出力先変更

従来は `install/`(デフォルト)に出力していたが、Robot Core専用ビルドが通常の開発ビルドと
混在しないよう、`--build-base build/robot_core --install-base install/robot_core` を使うよう変更した。

**これに伴い `docker-compose.robot-core.yml` の起動コマンドは
`install/robot_core/setup.bash` をsourceするよう変更済み。**
`scripts/robot_core.sh` のプリフライトチェック(`install/setup.bash` の存在確認)も
今回あわせて `install/robot_core/setup.bash` を見るように修正した(このチェックは
私が追加で見つけて修正したもので、修正しないと `robot_core.sh up`/`preflight` が
実機を繋いでも「ワークスペース未ビルド」判定で失敗していたはずの箇所)。

手動で `docker exec` する場合や、他のスクリプトからワークスペースをsourceする場合は
**`install/setup.bash` ではなく `install/robot_core/setup.bash` を使うこと。**

### 2.4 変更ファイル一覧

```
docker/docker-compose.robot-core.yml
scripts/setup_robot_core.sh
scripts/robot_core.sh
src/cotyaka_audio/package.xml
src/cotyaka_bringup/package.xml
src/cotyaka_system/package.xml
src/kobuki_sim/kobuki_unity/package.xml
src/mobile_manipulator_description/package.xml
src/piper_description/package.xml
README/unity_kotyaka_plan.md
README/unity_plan.md
```

---

## 3. NUCで実施する手順

### 3.1 事前準備

```bash
cd ~/ssd_yamaguchi/piper_ros   # 実際のパスに読み替え
git fetch origin
git checkout fix-humble-dev
git pull origin fix-humble-dev
```

古い `install/` `build/` `log/` が中途半端な状態(rootオーナーの残骸など)で残っている場合は、
念のため退避してからクリーンにしておくと安全:

```bash
sudo rm -rf install build log
```

(`.gitignore` 対象なので削除して問題ない。)

### 3.2 セットアップスクリプト実行

```bash
bash scripts/setup_robot_core.sh
```

- 冒頭でudevルール導入のため **sudoパスワード入力を求められる**(このPCでは未検証の箇所)。
- Kobuki側 → Piper側の順でビルドが走る(今回の修正でこの順序になった。Piper側が
  Kobukiワークスペースの `install/robot_core/setup.bash` をsourceするため)。
- 最後まで **exit codeなしで完走すること** を確認する。
- 途中で `E: Unable to locate package` や `Cannot locate rosdep definition` が出た場合は
  regression なので、ログを保存してから報告すること。

### 3.3 udev / デバイス確認

```bash
ls -l /dev/kobuki                      # シンボリックリンクが張られているか
bash scripts/install_kobuki_udev.sh    # 未実施 or 再確認したい場合
```

Kobukiを一度抜き差しして `/dev/kobuki` が生成されるか確認。

### 3.4 起動・プリフライト確認

```bash
bash scripts/robot_core.sh preflight
bash scripts/robot_core.sh probe        # Piper(CAN)/Kobuki検出状況を個別確認
bash scripts/robot_core.sh up
bash scripts/robot_core.sh status
bash scripts/robot_core.sh logs         # 各コンテナのログをtail
```

確認ポイント:

- `probe` で `piper=true kobuki=true`(実機接続済みの場合)になっているか
- `cotyaka-piper-robot-core` / `cotyaka-kobuki-robot-core` コンテナが `Up` のまま落ちないか
- `docker compose -f docker/docker-compose.robot-core.yml logs piper-robot-core` に
  CAN通信エラーが出ていないか
- `docker compose -f docker/docker-compose.robot-core.yml logs kobuki-robot-core` に
  Kobukiとの接続エラーが出ていないか

### 3.5 ROS 2側の疎通確認

コンテナはhostネットワークで動くので、NUC上で直接:

```bash
source /opt/ros/humble/setup.bash
ros2 topic list
ros2 topic echo /joint_states --once
ros2 topic echo /odom --once
ros2 run tf2_ros tf2_echo map base_link     # AMCL等が起動していれば
```

`cotyaka_bringup`(Piper系)と `kobuki_node`(Kobuki系)双方のトピック・TFが
出ていることを確認する。

### 3.6 音声(VOICEVOX)確認

```bash
docker compose -f docker/docker-compose.robot-core.yml logs cotyaka-voicevox
docker compose -f docker/docker-compose.robot-core.yml logs cotyaka-audio
```

起動メッセージ音声が実際にスピーカーから再生されるか確認。`COTYAKA_AUDIO_DEVICE` の値が
実機のオーディオデバイス名と一致しているか要確認(`/etc/cotyaka/robot-core.env` を使っている
場合はそちらを編集)。

### 3.7 systemd常駐化(必要な場合のみ)

すでに `cotyaka-robot-core.service` を導入済みの場合、上記手順で問題ないことを確認してから:

```bash
sudo systemctl restart cotyaka-robot-core
sudo systemctl status cotyaka-robot-core
```

`install_robot_core_service.sh` は再実行不要(内容の変更なし)。

---

## 4. 既知の非対象・注意点

- SAM3 / YOLO / Detic / Unityシム / Gazebo / MuJoCo はこのRobot Coreビルドには含まれない。
  Unity連携等の開発は `docker/docker-compose.yml`(別ファイル)側で従来通り作業すること。
  こちらは今回変更していない。
- `docker/docker-compose.yml` 側は `/home/kobuki_ws`(旧パス)のままで、
  `docker-compose.robot-core.yml` 側は `/home/kobuki/kobuki_ws`(新パス)に統一済み。
  この2つは別ファイル・別用途なので混同しないこと。
- `detic_onnx_ros2` / `ultralytics` / `ros_tcp_endpoint` に対するローカルrosdepルールは
  意図的に追加していない(Robot Core対象から外したため)。将来Alienware側や別ワークスペースで
  これらをビルドする際は、別途rosdepルール追加 or pipインストールの検討が必要。

---

## 5. 問題が起きた場合

- 該当コミット(このドキュメントと同時にpushされたもの)まで `git log` で確認できる。
- 打ち消す場合は該当コミットを `git revert` するか、`fix-humble-dev` の1つ前の状態
  (`git log --oneline` で本コミットの直前)に戻すこと。
- ビルドログは `build/robot_core/log/` や `--log-base log/robot_core` 配下、
  もしくは `docker compose run` の標準出力をファイルに保存して共有すると調査が早い。
