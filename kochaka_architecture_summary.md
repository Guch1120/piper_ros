# コチャカ アーキテクチャ要約

## 基本方針

コチャカは以下の2層に分離する。

- **NUC：Robot Core**
  - Piper / Kobuki の実機制御
  - MoveIt / Nav2
  - TF / 自己位置推定
  - Skill 実行管理
  - Watchdog / Safety / System Supervisor

- **Alienware：AI Layer**
  - SAM3
  - Gemma
  - Scene Understanding
  - Semantic Robot State
  - Task / Skill Planning

NUCとAlienwareはROS 2で接続し、基本的には同一ROS_DOMAIN_IDを使用する。

---

## Skill 実行系

Skill Executorは2層に分離する。

### Skill Manager

Skillの実行管理を担当する。

- Skill要求受付
- validate
- dispatch
- active skill管理
- resource管理
- 並列実行管理
- compatibility判定
- cancel / timeout
- feedback / result

### Skill Runtime

実際のSkillを実装する。

- Base Skill
- Arm Skill
- Gripper Skill
- Perception Skill
- Mobile Manipulation Skill

制御周期そのものはNav2、MoveIt、Servo、各Controllerに任せる。

---

## Skillの実行方針

Gemmaはロボットを直接制御しない。

Gemmaが決めるのは、

- START
- KEEP
- CANCEL

のようなSkillの実行方針までとする。

並列実行の最終判断はNUCのSkill Managerが行う。

単純な並列動作と、Base+Armを密に協調させるMobile Manipulation Skillは分けて扱う。

---

## Navigation

AMR_TOOLKITは実行時Navigationではなく、事前地図とWaypointを編集するオフラインツールとして使う。

```text
AMR_TOOLKIT
  ↓
map / waypoint
  ↓
Waypoint Manager
  ↓
Nav2
  ↓
Kobuki
```

SAM3による地面領域からのサブゴール生成は、既知地図内Navigationでは基本的に不要。

Nav2が経路計画・障害物回避を担当し、SAM3は意味的な走行可能領域や周囲状況の認識に使う。

---

## Localization

自己位置推定のSource of TruthはNUCとする。

```text
map
 ↓
odom
 ↓
base_link
```

- wheel odometry + IMU → EKF → `odom -> base_link`
- static map + 2D LiDAR → AMCL → `map -> odom`

AlienwareはNUCが配信するTFを利用する。

Gemmaには高頻度な生TFではなく、

- 現在エリア
- 最近傍Waypoint
- Navigation状態
- Localization状態

などのSemantic Stateを渡す。

---

## 起動構成

最終的には以下を目指す。

```text
Power ON
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

---

## 推奨パッケージ構成

```text
kochaka_ws/src/
├── kochaka_interfaces/
├── kochaka_description/
├── kochaka_bringup/
├── kochaka_system/
├── kochaka_skill_manager/
├── kochaka_skills/
├── kochaka_robot_adapters/
├── kochaka_navigation/
└── kochaka_manipulation/

kochaka_ai_ws/src/
├── kochaka_perception/
├── kochaka_geometry/
├── kochaka_semantic_state/
├── kochaka_ai/
└── kochaka_skill_client/
```

---

## 現時点で固まっている設計

- NUCとAlienwareをRobot Core / AI Layerに分離する
- Skill Manager / Skill Runtimeの2層構造とする
- Skillは並列実行可能にする
- Base+Arm協調動作は独立したMobile Manipulation Skillとして扱う
- ExecuteSkill ActionをNUCとAlienwareの主要な実行境界とする
- CheckSkillは保留
- AMR_TOOLKITはオフラインWaypoint Editorとして使う
- NavigationはNav2に任せる
- SAM3はNavigationの代替ではなく意味認識に使う
- 自己位置推定の責任はNUCに置く
- GemmaにはSemantic Stateを渡す
