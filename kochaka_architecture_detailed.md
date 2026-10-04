# コチャカ アーキテクチャ詳細設計

## 1. システム概要

コチャカは、Kobukiを移動ベース、Piperをマニピュレータとして統合したモバイルマニピュレータとする。

システム全体は、GPUを持たないNUCとGPU搭載Alienwareに分離する。

```text
Alienware
  AI / Perception / Planning
        │
        │ ROS 2
        ▼
NUC
  Robot Core / Motion / Safety
        │
        ├── Kobuki
        └── Piper
```

基本原則は、**NUCだけでロボット本体の制御系が成立し、Alienwareは交換可能な上位知能層として扱うこと**である。

Alienwareが停止しても、NUC側では実機接続、自己位置、Nav2、MoveIt、停止処理、安全監視などを維持できる構造とする。

---

# 2. NUCとAlienwareの役割

## 2.1 NUC：Robot Core

NUCは実ロボットに直接関係する処理を担当する。

### Hardware

- Piper CAN
- Kobuki
- IMU
- 2D LiDAR
- その他Robot I/O

### Robot State

- joint_states
- TF
- odometry
- localization
- hardware state

### Motion

- MoveIt
- Nav2
- local base controller
- arm servo
- mobile manipulation controller

### Execution

- Skill Manager
- Skill Runtime
- Robot Adapter
- command arbitration

### Safety / System

- watchdog
- localization guard
- diagnostics
- system supervisor
- stop / emergency handling

NUCにはLLMを置かず、意味的な行動選択は担当させない。

---

## 2.2 Alienware：AI Layer

AlienwareはGPUを必要とする認識・推論・高位判断を担当する。

### Perception

- Camera入力
- SAM3
- Depth処理
- Object tracking
- Scene Understanding

### Geometry

- TF参照
- camera / base / map座標変換
- object / region geometry
- traversability情報

### Semantic State

低レベルROS状態をGemmaが利用しやすい表現へ変換する。

- 現在エリア
- 最近傍Waypoint
- Navigation状態
- Task進行状態
- Active Skill
- Manipulation状態
- Localization状態
- 認識対象

### AI

- Gemma
- Task Planner
- Skill Scheduler
- 将来のVLA

---

# 3. ROS 2によるPC間連携

NUCとAlienwareはROS 2で通信する。

基本的には同一ROS_DOMAIN_IDを使用し、PCの役割分離をROS Domainでは行わない。

責務の境界は以下で定義する。

- ROS package
- namespace
- Topic / Service / Action
- Skill API

ROS Domainを分離するのは、複数ロボットやシミュレータを同一ネットワークで扱う必要が出た場合に検討する。

---

# 4. Skill実行アーキテクチャ

従来「Skill Executor」と呼んでいた機構は、以下の2層に分離する。

```text
Skill Manager
     ↓
Skill Runtime
```

---

# 5. Skill Manager

Skill Managerは実行管理を担当し、ロボットの低レベル制御は行わない。

## 主な責務

- Skill要求受付
- validate
- precondition確認
- dispatch
- Active Skill管理
- Resource管理
- Skill Compatibility管理
- 並列実行管理
- cancel
- timeout
- feedback
- result
- logging

実行の流れは以下とする。

```text
Skill Request
    ↓
validate
    ↓
precondition
    ↓
resource / compatibility
    ↓
dispatch
    ↓
Skill Runtime
    ↓
feedback / result
```

---

# 6. validate

validateはAI的な推論ではなく、Skill要求の形式検査である。

確認対象は、

- Skill名の存在
- 必須引数
- 引数型
- 値範囲
- timeout
- フォーマット

などとする。

「今実行できるか」ではなく「要求自体が正しいか」を判定する。

---

# 7. dispatch

dispatchはSkill名から対応するSkill Runtimeへ処理を渡すルーティング機構である。

Skill Manager内部にSkill固有の実装を書かず、Registryから実装を取得して実行する構造とする。

---

# 8. CheckSkill

CheckSkillは現時点では保留とする。

理由は以下。

- NUCにLLMが存在しない
- 意味的なSkill ScoreをNUCで生成する必要がない
- 実行開始時にもprecondition確認が必要
- NavigationではNav2 Planner等の既存機能で事前評価可能

したがって基本形は、

```text
ExecuteSkill
  ↓
validate
  ↓
precondition
  ↓
execute
```

とする。

複数Skill候補をAlienwareが比較する必要が生じた場合に、別途事前評価APIを検討する。

---

# 9. ExecuteSkill.action

NUCとAlienwareの主要なSkill実行境界としてROS 2 Actionを利用する。

Actionを使う理由は、Skillが長時間処理だからである。

Actionでは、

- Goal
- Feedback
- Result
- Cancel

を扱える。

ExecuteSkill自体がロボットを制御するのではなく、**AlienwareとNUCの間の実行契約**として扱う。

---

# 10. Skill Runtime

Skill Runtimeには実際のSkill処理を実装する。

Skill Manager自身は制御周期を持たない。

高周期処理は、

- Nav2 Controller
- MoveIt
- MoveIt Servo
- Visual Servo
- custom controller

などへ委譲する。

---

# 11. Skill分類

## Component Skill

単一の主要Resourceを利用するSkill。

Resourceの基本単位は以下とする。

- base
- arm
- gripper
- perception

## Parallel-capable Skill

異なるResourceを使い、互いに干渉しない場合は並列実行できる。

## Coordinated Skill

BaseとArmなど複数Resourceを1つの制御ループ内で協調使用する。

Mobile Manipulationでは、このCoordinated Skillを独立したSkillとして扱う。

---

# 12. Resource Manager

Skill Manager内部にResource Managerを持つ。

管理対象は、

- base
- arm
- gripper
- perception

を基本とする。

ただしResourceが重複しなければ必ず並列可能、とはしない。

そこで、

```text
Resource ownership
+
Skill compatibility
```

の両方を管理する。

---

# 13. Skill Compatibility

モバイルマニピュレータでは、BaseとArmが別Resourceでも組み合わせによっては危険となる。

そのためSkill間のCompatibility Policyを持つ。

Skill Managerは、

- Resource競合
- Skill同士のCompatibility
- Robot state
- Safety state

を確認して並列実行可否を決定する。

---

# 14. 継続的Skill Scheduling

GemmaによるSkill選択を単純な逐次実行には限定しない。

```text
Skill A
 ↓
終了
 ↓
Gemma
 ↓
Skill B
```

ではなく、現在実行中のSkill集合に対して、

- START
- KEEP
- CANCEL

を定期的に判断する。

Gemmaが推論している間も、NUC上のNav2、MoveIt、Servoなどは独立して実行を継続する。

最終的な並列実行許可はGemmaではなくSkill Managerが判断する。

---

# 15. Base制御

Baseは用途別に複数の制御系を持つ。

- Global Navigation
- Local Relative Motion
- Manipulation Servo
- Teleoperation

これらが同時にKobukiへ競合指令を出さないよう、Base Command Arbiterを設ける。

---

# 16. Arm制御

Piperにも同様に制御入口を整理する。

想定される上位系は、

- MoveIt trajectory
- MoveIt Servo
- Visual Servo
- Teleoperation
- 将来VLA

など。

各機構が直接無秩序にPiperへ命令を送らず、Arm Adapter / Arm Command Interfaceを経由させる。

---

# 17. Robot Adapter

Skill Runtimeとハードウェア固有APIの間にRobot Adapterを置く。

```text
Skill Runtime
    ↓
Robot Adapter
    ├── Base Interface
    ├── Arm Interface
    ├── Gripper Interface
    └── Sensor Interface
    ↓
Kobuki / Piper
```

Skill側ではPiper固有CAN、Kobuki固有Topicなどを直接扱わない。

これにより将来的にHSR等へ展開する際、ハードウェア固有部分を差し替えやすくする。

---

# 18. Navigation

AMR_TOOLKITはRuntime Navigation stackではなく、事前地図とWaypointを編集するオフラインツールとして利用する。

役割は、

- PGM / YAML地図
- Waypoint
- Waypoint属性
- 座標変換
- YAML出力

など。

Runtimeは、

```text
AMR_TOOLKIT
    ↓
map / waypoint files
    ↓
Waypoint Manager
    ↓
Nav2
    ↓
Kobuki
```

とする。

---

# 19. Waypoint Manager

AMR_TOOLKITとNav2 / AIの間にWaypoint Managerを置く。

責務は、

- Waypoint YAML読み込み
- Waypoint ID管理
- map座標管理
- semantic attribute管理
- Nav2向けPose生成
- AI向けSemantic Location生成

である。

AMR_TOOLKITで作成したWaypointは、実行時にはWaypoint Managerが管理する。

---

# 20. SAM3とNavigation

既知地図内でNav2を利用する場合、SAM3で地面領域を検出してサブゴールを連続生成する構成は基本形にはしない。

理由は、Nav2が、

- Global Path Planning
- Local Path Tracking
- Obstacle Avoidance

を担当するためである。

SAM3はNavigationの代替ではなく、

- Ground Recognition
- Traversability
- Object Recognition
- Human / Scene Understanding

などのSemantic Perceptionに利用する。

必要になれば将来的にSAM3の結果をNav2 CostmapやSemantic Costとして反映する。

---

# 21. Localization

自己位置推定のSource of TruthはNUCとする。

基本TFは、

```text
map
 ↓
odom
 ↓
base_link
```

とする。

## Local Odometry

```text
Kobuki wheel odometry
+
IMU
 ↓
robot_localization EKF
 ↓
odom -> base_link
```

## Global Localization

```text
static map
+
2D LiDAR
 ↓
AMCL
 ↓
map -> odom
```

---

# 22. 動的障害物への対策

2D LiDARを論理的に、

```text
Localization
Navigation
```

の2用途へ分ける。

Localization側では静的環境との整合性を重視する。

Navigation側では人や動的物体も障害物として扱う。

Localization Guardを設け、

- GOOD
- DEGRADED
- LOST

などの状態を管理し、自己位置が信頼できない場合はNavigationを抑制または停止する。

---

# 23. 自己位置をどこまで認識させるか

自己位置を**推定する責任はNUCのみ**とする。

ただし利用可能範囲は階層化する。

## NUC Localization

完全なTF / Poseを保持する。

## NUC Skill Runtime

Navigation、Manipulation、Geometryのため正確なTFを利用する。

## Alienware Geometry

NUCが発行したTFを参照し、Camera / Object / Map座標変換に使用する。

## Gemma

通常は生の高周期TFではなくSemantic Stateを受け取る。

Semantic Stateには、

- 現在エリア
- 最近傍Waypoint
- Navigation状態
- Localization状態
- Task Progress

などを含める。

---

# 24. System Supervisor

Skill Managerとは別にSystem Supervisorを置く。

監視対象は、

- Piper CAN
- Kobuki
- Nav2
- MoveIt
- Localization
- Skill Manager
- Alienware heartbeat
- ROS node health

など。

Robot全体の状態を、

- BOOTING
- WAITING_HARDWARE
- ROBOT_READY
- WAITING_AI
- READY
- DEGRADED
- FAULT

のように管理する。

---

# 25. 起動アーキテクチャ

最終的にはHSRのような自動起動を目指す。

```text
Power ON
 ↓
Ubuntu
 ↓
systemd
 ↓
Docker Compose
 ↓
ROS 2 Launch
 ↓
System Supervisor
 ↓
KOCHAKA READY
```

責務は、

- systemd：OSレベル起動
- Docker Compose：Container管理
- ROS 2 Launch：ROS Node起動
- System Supervisor：Robot状態管理

に分離する。

---

# 26. 推奨ディレクトリ構成

## NUC側

```text
kochaka_ws/
└── src/
    ├── kochaka_interfaces/
    ├── kochaka_description/
    ├── kochaka_bringup/
    ├── kochaka_system/
    │   ├── system_supervisor/
    │   ├── watchdog/
    │   ├── diagnostics/
    │   └── localization_guard/
    ├── kochaka_skill_manager/
    │   ├── skill_manager/
    │   ├── registry/
    │   ├── validator/
    │   ├── dispatcher/
    │   ├── resource_manager/
    │   ├── compatibility_manager/
    │   └── execution_state/
    ├── kochaka_skills/
    │   ├── base/
    │   ├── arm/
    │   ├── gripper/
    │   ├── perception/
    │   └── mobile_manipulation/
    ├── kochaka_robot_adapters/
    │   ├── base/
    │   ├── arm/
    │   ├── gripper/
    │   └── sensors/
    ├── kochaka_navigation/
    │   ├── nav2/
    │   ├── waypoint_manager/
    │   ├── localization/
    │   └── command_arbiter/
    └── kochaka_manipulation/
        ├── moveit/
        ├── servo/
        └── controllers/
```

## Alienware側

```text
kochaka_ai_ws/
└── src/
    ├── kochaka_perception/
    │   ├── sam3/
    │   ├── depth/
    │   ├── tracking/
    │   └── scene_understanding/
    ├── kochaka_geometry/
    │   ├── tf_client/
    │   ├── object_geometry/
    │   └── traversability/
    ├── kochaka_semantic_state/
    │   ├── robot_state/
    │   ├── scene_state/
    │   └── waypoint_semantics/
    ├── kochaka_ai/
    │   ├── gemma/
    │   ├── task_planner/
    │   ├── skill_scheduler/
    │   └── state_monitor/
    └── kochaka_skill_client/
        ├── execute_skill_client/
        └── skill_state_client/
```

---

# 27. ディレクトリ分離の意図

各packageの責務を以下のように分離する。

- `kochaka_interfaces`
  - NUC / Alienware間を含む共通ROS Interface

- `kochaka_skill_manager`
  - Skillの実行管理

- `kochaka_skills`
  - Skillの具体的な動作定義

- `kochaka_robot_adapters`
  - 実機固有API吸収

- `kochaka_navigation`
  - Nav2 / Localization / Base Control

- `kochaka_manipulation`
  - MoveIt / Servo / Manipulation Control

- `kochaka_system`
  - Robot全体状態と安全監視

- `kochaka_perception`
  - GPU認識

- `kochaka_geometry`
  - TFを利用した幾何処理

- `kochaka_semantic_state`
  - LLM向け状態抽象化

- `kochaka_ai`
  - GemmaとTask / Skill Planning

---

# 28. 現時点で固まっている方針

- NUCをRobot Core、AlienwareをAI Layerとする
- NUCとAlienwareはROS 2で連携する
- Skill ExecutorをSkill Manager / Skill Runtimeに二層化する
- Skillは並列実行可能な構造にする
- 並列実行可否はGemmaではなくNUCが判断する
- Base+Arm協調動作はMobile Manipulation Skillとして扱う
- ExecuteSkill Actionを主要な実行境界とする
- CheckSkillは保留する
- Robot Adapterでハードウェア固有APIを吸収する
- AMR_TOOLKITはオフラインMap / Waypoint Editorとして利用する
- Runtime NavigationはNav2に任せる
- SAM3による連続サブゴール生成は基本構成から外す
- SAM3はSemantic Perceptionに利用する
- 自己位置推定の責任はNUCに集約する
- AlienwareはNUCのTFを利用する
- GemmaにはSemantic Stateを渡す
- System SupervisorとSkill Managerを分離する
- 最終的にPower ONからRobot Readyまで自動化する

---

# 29. 今後決める事項

- ExecuteSkill.actionの具体的IDL
- Skill Registryの形式
- Resource Managerの詳細
- Skill Compatibility記述方式
- Skillのqueue / reject / preempt規則
- Active Skill Stateの形式
- Gemma Skill Schedulerの出力Schema
- Mobile Manipulation Skillの粒度
- SAM3結果をNav2へ統合するか
- Localization Guardの詳細
- CheckSkill相当APIを追加するか
