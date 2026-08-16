# Unity Simulator for コチャカ (Kobuki + カチャカシェルフ + Piper) — 実装計画

## 背景・目的

「コチャカ」= Kobuki(モバイルベース) + カチャカシェルフ(市販の棚) + Piper(6軸アーム) を
組み合わせたモバイルマニピュレータの名称。

Unity をシミュレータとして使用し、実機への移行を見据える。設計思想は既存の
`piper_unity`（[unity_plan.md](./unity_plan.md) 参照）と同じ:
**外部 ROS2 インターフェースを実機と完全に同一のまま維持し、内部実装（CAN 通信 /
車輪駆動）だけを Unity ブリッジに置き換える。** 接続先がシミュレータか実機かの
違いだけにする。

---

## これまでの取り組み（完了済み）

### 1. 結合 URDF 作成

`src/mobile_manipulator_description/` パッケージを新規作成し、以下の構造で結合。

```
base_footprint (kobuki)
  └─ base_link
       └─ kachaka_shelf_link
            └─ kachaka_shelf_top_link  (仮想マウントリンク)
                 └─ piper_base_link    (base_link から名前衝突回避のためリネーム)
                      └─ アームチェーン (link1〜link6, gripper_base, ...)
```

- 実装ファイル: `urdf/mobile_manipulator.urdf.xacro`, `urdf/kachaka_shelf_macro.xacro`
- RViz 上での TF ツリー表示・`robot_state_publisher` でのロード成功を確認済み
  （`launch/view_mobile_manipulator.launch.py`）。

### 2. カチャカシェルフモデル

現物が **2段構成** であることに合わせ、棚板を2枚（lower/upper）に変更。
将来3段に戻す可能性を考慮し、`middle_board_z` のプロパティ定義と
`shelf_board` 呼び出しはコメントアウトで残してあり、ファイルを直接編集すれば
2段⇔3段を切り替えられる（実行時引数化はしない方針）。

棚の寸法・Piper 搭載位置は全て実測前の placeholder（0 や暫定値）。

### 3. kobuki_unity ブリッジパッケージ新規作成

`src/kobuki_sim/kobuki_unity/`（`src/piper_sim/piper_unity/` と対称の配置）。

実機 `kobuki_node`（`oit_kobuki_ws-main`）と全く同じ外部 ROS2 インターフェースを
維持しつつ、内部で Unity と通信するノードとして実装:

- 実機と同一の外部インターフェース:
  - sub `commands/velocity` (`geometry_msgs/Twist`)
  - pub `odom` (`nav_msgs/Odometry`), `joint_states` (`sensor_msgs/JointState`)
  - TF `odom` → `base_footprint`
  - `cmd_vel_timeout_sec = 0.6` のウォッチドッグ
  - `wheel_radius = 0.035 m` / `wheel_separation = 0.23 m` の差動二輪運動学
- 内部ブリッジ（Unity 専用、実機では車輪駆動 CAN 通信に相当）:
  - pub `/kobuki_unity/wheel_cmd` (`JointState`) → Unity へ目標角速度送信
  - sub `/kobuki_unity/wheel_states` (`JointState`) ← Unity から実車輪状態受信

詳細仕様・実装は `kobuki_unity_sim_node.py` の docstring に記載済み。

### 4. mobile_manipulator_description 統合 launch 追加

`launch/view_mobile_manipulator_unity.launch.py` を追加し、以下を一括起動できるように
した:

1. `robot_state_publisher`
2. `kobuki_unity` の launch（`IncludeLaunchDescription`）
3. `rviz2`
4. `joint_state_publisher`（Piper アーム側 joint 埋め用）

### 5. ビルド確認

`setup/piper.bash` の `rosdep install --from-paths` リストに `src/kobuki_sim` を追加。
`colcon build --symlink-install` でワークスペース全体（35パッケージ）のビルド成功を
確認済み。

### 6. ROS2 側ロジックの検証

### 6. ROS2 側ロジックの検証

`/kobuki_unity/wheel_cmd` を受け取って積分し `/kobuki_unity/wheel_states` として返す自動統合テスト
（`src/kobuki_sim/kobuki_unity/test/test_kobuki_unity_integration.py`）を実装し、以下の一連の流れが
正常に動作することを Docker コンテナ内で検証済み:
1. `commands/velocity` (Twist) → 運動学変換 → `/kobuki_unity/wheel_cmd`
2. `/kobuki_unity/wheel_states` → オドメトリ積分 (`odom`) → TF (`odom` → `base_footprint`)
3. `commands/reset_odometry` → オドメトリ原点 $(0, 0, 0)$ リセット（実機 `kobuki_node` と同一）
4. ウォッチドッグタイマー（0.6 秒無通信時のゼロ停止）

### 7. Unity C# スクリプト群の実装（完了）

Unity 側の ROS-TCP-Connector 連携用 C# スクリプトを `unity/scripts/` に実装済み:
- `KobukiWheelController.cs`: `/kobuki_unity/wheel_cmd` を購読し、左右車輪の `ArticulationBody` の角速度（`targetVelocity`）を制御。
- `KobukiWheelStatePublisher.cs`: 左右車輪の回転角（rad, 連続値）および角速度（rad/s）を `/kobuki_unity/wheel_states` に 50Hz で定期 publish。
- `PiperJointController.cs`: `/piper_unity/joint_cmd` を購読し、アーム 6 軸 + グリッパーの `ArticulationBody` の関節目標位置を制御。
- `PiperJointStatePublisher.cs`: アーム 6 軸 + グリッパーの各関節状態を `/piper_unity/joint_states` に 50Hz で定期 publish。
- `RealSenseCameraPublisher.cs`: Piper アーム先端（`gripper_base` / `camera_color_optical_frame`）の Unity Camera 映像を取得し、実機 RealSense D435i 完全互換トピック（`/camera/camera/color/image_raw`, `/camera/camera/color/camera_info`）を配信。
- `KotyakaSimManager.cs`: 上記各コンポーネントおよび `ROSConnection`（IP/ポート）の初期化を一元管理する統合ヘルパースクリプト。
- `Editor/KotyakaSceneBuilder.cs`: Unity エディタのメニュー「`Kotyaka -> Create Kotyaka Simulation Scene`」から、床・照明・ROS接続・ロボットコンポーネント・RealSenseカメラを一括自動セットアップするエディタ拡張。

### 8. Unity インポート用 URDF アセットの生成（完了）

- `src/mobile_manipulator_description/unity_urdf/mobile_manipulator.urdf` を生成。
- `src/mobile_manipulator_description/scripts/export_unity_urdf.py` により、xacro パラメータ変更後にワンコマンドで Unity 用 URDF を再生成可能。

---

## Unity 側 コチャカ統合シーンのセットアップ手順

### 方法 A: エディタ拡張による自動セットアップ（推奨）
1. `unity/scripts/` 以下のスクリプトを Unity プロジェクトの `Assets/scripts/` にコピー。
2. Unity エディタのメニューバーから **`[Kotyaka] -> [Create Kotyaka Simulation Scene]`** を実行。
3. `Assets/Scenes/KotyakaSimulation.unity` が自動作成され、床面・照明・ROSConnection・ロボット制御・RealSenseハンドカメラが全自動でセットアップされます。

### 方法 B: 手動セットアップ
1. **URDF のインポート**:
   - `src/mobile_manipulator_description/unity_urdf/mobile_manipulator.urdf` を URDF Importer からインポート。
2. **GameObject へのコンポーネント設定**:
   - ロボットルート（または空の GameObject `Kotyaka_Robot`）を作成。
   - `KobukiWheelController`, `KobukiWheelStatePublisher`, `PiperJointController`, `PiperJointStatePublisher`, `KotyakaSimManager` をアタッチ。
   - `gripper_base` 配下の `camera_color_optical_frame` に Unity の `Camera` および `RealSenseCameraPublisher` をアタッチ。

4. **ROS 2 側の起動と Play**:
   ```bash
   # Docker コンテナ内で起動
   source /opt/ros/humble/setup.bash
   source /home/kobuki_ws/install/setup.bash
   source /ros2_ws/install/setup.bash
   ros2 launch mobile_manipulator_description view_mobile_manipulator_unity.launch.py
   ```
   - Unity Editor で Play ボタンを押下。
   - RealSense 画像トピックの受信確認:
     ```bash
     ros2 topic hz /camera/camera/color/image_raw
     ros2 run rqt_image_view rqt_image_view
     ```

---

## 完了タスク・今後の TODO

- [x] Unity 側: kobuki 車輪ブリッジ C# スクリプトの実装 (`KobukiWheelController.cs`, `KobukiWheelStatePublisher.cs`)
- [x] Unity 側: Piper アームブリッジ C# スクリプトの実装 (`PiperJointController.cs`, `PiperJointStatePublisher.cs`)
- [x] Unity 側: RealSense ハンドカメラ画像・カメラ情報配信 C# スクリプトの実装 (`RealSenseCameraPublisher.cs`)
- [x] Unity 側: ワンクリック シーン自動構築エディタ拡張の実装 (`Editor/KotyakaSceneBuilder.cs`)
- [x] Unity 側: コチャカ統合 URDF 生成 (`unity_urdf/mobile_manipulator.urdf`, `export_unity_urdf.py`)
- [x] ROS 2 側: `commands/reset_odometry` サポート追加による実機 `kobuki_node` トピック完全互換の確保
- [x] ROS 2 側: Docker コンテナ内での自動統合テストスイート実装・全件合格検証 (`test_kobuki_unity_integration.py`)
- [ ] Unity 側: 実機寸法の実測値計測および URDF パラメータ反映（※ユーザー側で実施）
- [ ] （将来検討）自律移動・Nav2 / Nav Goal 対応方式の選定

