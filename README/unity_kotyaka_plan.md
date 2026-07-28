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

実 Unity がまだ無いため、`/kobuki_unity/wheel_cmd` を受け取って積分し
`/kobuki_unity/wheel_states` として返すだけの使い捨てスタンドインスクリプト
（リポジトリ外、スクラッチパッチ的なテスト用）を使って、
Twist → 運動学変換 → オドメトリ積分 → TF の一連の流れが正しいことを確認済み。
ただし **実 Unity との接続では未確認**。

---

## 現状のギャップ・未完了事項

- **Unity 側の kobuki 車輪ブリッジ C# スクリプトが未実装**。
  仕様:
  - `/kobuki_unity/wheel_cmd` (`sensor_msgs/JointState`,
    `name=["wheel_left_joint","wheel_right_joint"]`, `velocity` のみ有効,
    目標角速度 rad/s) を購読して ArticulationBody/WheelCollider の車輪に反映する。
  - `/kobuki_unity/wheel_states`（同じく `JointState`, `position`（連続値、
    エンコーダ相当）+ `velocity`）を数十 Hz 程度の安定した周期で publish する。
  - 符号規則: 正の値 = そのタイヤの回転がロボットを前進させる方向（右手系）。
  - ROS2 側は Unity からの連続的な更新を前提にオドメトリを積分するため、
    更新頻度が低い/不安定だと精度が落ちる点に注意。
- **Unity 側に「コチャカ」統合シーンが未作成**。既存は `Assets/Scenes/Piper.unity`
  という Piper アーム単体のシーンのみ（[unity_plan.md](./unity_plan.md) 参照）。
  kobuki ベース・カチャカシェルフのモデルを追加し、Piper をその上に載せた
  統合シーンをまだ作る必要がある。
- **実 Unity 接続でのエンドツーエンド動作確認が未実施**。ROS2 側のロジック検証は
  スタンドインスクリプトのみで行った段階。
- カチャカシェルフの寸法・Piper 搭載位置
  (`kachaka_shelf_x/y/z/roll/pitch/yaw`, `piper_mount_x/y/z/roll/pitch/yaw`) は
  全て実測前の placeholder（0.0）のままなので、実機の実測後に調整が必要。
- RViz からの Nav Goal 送信・自律移動（Nav2 など）は今回のスコープ外として保留中
  （将来検討）。

---

## 次にやること（TODO）

- [ ] Unity 側: kobuki 車輪ブリッジ C# スクリプトの実装
- [ ] Unity 側: コチャカ統合シーン（kobuki ベース + カチャカシェルフ + Piper）の
      新規作成、ros_tcp_endpoint 接続設定
- [ ] 実 Unity 接続での動作確認: `commands/velocity` での前後左右移動、RViz 上での
      `odom`/`joint_states`/TF の追従確認
- [ ] カチャカシェルフ・Piper 搭載位置の実測・URDF 調整
- [ ] （将来検討）自律移動・Nav Goal 対応方式の選定
