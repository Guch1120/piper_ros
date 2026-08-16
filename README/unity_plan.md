# Unity Simulator for Piper Robot — 実装計画

## 背景・目的

実機の Piper ロボットアームは CAN バス経由で制御される。
本計画では Unity を Gazebo 代替シミュレータとして使用できるよう、
**外部 ROS2 インターフェースを実機と完全に同一のまま**、CAN バス部分を
Unity の ArticulationBody 物理エンジンに置き換える。

実機との切り替えは launch ファイルを変えるだけでよく、アプリ側のコードは変更不要。

---

## リポジトリ構成（関連部分）

```
/home/hsr/piper_ros/src/
  piper/
    piper/
      piper_single_ctrl_moveit_action_node.py  ← 実機制御ノード（参考元）
    launch/
      start_single_moveit_piper_action.launch.py  ← 実機用 launch
  piper_moveit/
    piper_with_gripper_moveit/
      config/
        moveit_controllers.yaml
        ros2_controllers.yaml
      launch/
        piper_real_moveit.launch.py  ← MoveIt2 起動 launch（流用）
  piper_sim/
    piper_gazebo/   ← 既存 Gazebo シミュレータ（参考）
    piper_unity/    ← 今回新規作成

/home/hsr/unity_projects/unity-ros/Assets/
  scripts/
    ArticulatioonJointTest.cs  ← 既存（参考）
    PiperJointController.cs    ← 新規作成
    PiperJointStatePublisher.cs ← 新規作成
  URDF/piper/
    meshes/
      link1.prefab … link7.prefab  ← URDF import 済みのリンクメッシュ

/home/hsr/ROS-TCP-Endpoint/  ← 既設 ROS-Unity TCP ブリッジ（そのまま使用）
```

---

## アーキテクチャ

```
ros2 launch piper_unity start_piper_unity.launch.py
  ├─ [robot_state_publisher]      /joint_states → TF ブロードキャスト
  ├─ [move_group]                 MoveIt2（kinematics, planning）
  ├─ [rviz2]                      可視化
  ├─ [piper_unity_sim_node]       新規: CAN 部分を Unity ブリッジに置換
  │      --- 外部 IF（実機と同一）---------------------------------
  │      Action Server: arm_controller/follow_joint_trajectory
  │      Action Server: gripper_controller/follow_joint_trajectory
  │      pub joint_states_single  (remapping → /joint_states)
  │      pub joint_states_feedback
  │      pub joint_ctrl
  │      pub arm_status
  │      pub end_pose / end_pose_stamped
  │      sub pos_cmd
  │      sub joint_ctrl_single
  │      sub enable_flag
  │      srv enable_srv
  │      --- 内部ブリッジ（Unity 専用, 実機では CAN 通信に相当）-----
  │      pub /piper_unity/joint_cmd    (JointState, rad)  → Unity へ目標値送信
  │      sub /piper_unity/joint_states (JointState, rad)  ← Unity から実位置受信
  └─ [default_server_endpoint]    ROS-TCP-Endpoint (TCP:10000)

              ↕  TCP :10000
  [Unity — Piper.unity シーン]
     PiperJointController.cs      sub /piper_unity/joint_cmd → xDrive.target
     PiperJointStatePublisher.cs  ArticulationBody.jointPosition → pub /piper_unity/joint_states
```

### 内部ブリッジトピックの役割

| トピック | 方向 | 実機での対応 |
|---|---|---|
| `/piper_unity/joint_cmd` | sim_node → Unity | `piper.JointCtrl()` CAN 送信の代替 |
| `/piper_unity/joint_states` | Unity → sim_node | `piper.GetArmJointMsgs()` の代替 |

**アプリケーション開発者はこれらトピックを意識しない。**
外部インターフェースは実機と完全に同一であり、launch ファイルを変えるだけで切り替え可能。

---

## 作成ファイル一覧

### 1. ROS2 パッケージ: `/home/hsr/piper_ros/src/piper_sim/piper_unity/`

```
piper_unity/
├── package.xml
├── setup.py
├── resource/
│   └── piper_unity
├── piper_unity/
│   ├── __init__.py
│   └── piper_unity_sim_node.py
└── launch/
    └── start_piper_unity.launch.py
```

#### `package.xml`

```xml
<?xml version="1.0"?>
<package format="3">
  <name>piper_unity</name>
  <version>0.0.0</version>
  <description>Unity simulator bridge for Piper robot arm</description>
  <maintainer email="root@todo.todo">root</maintainer>
  <license>Apache-2.0</license>
  <depend>rclpy</depend>
  <depend>sensor_msgs</depend>
  <depend>std_msgs</depend>
  <depend>geometry_msgs</depend>
  <depend>control_msgs</depend>
  <depend>piper_msgs</depend>
  <exec_depend>moveit_ros_move_group</exec_depend>
  <exec_depend>robot_state_publisher</exec_depend>
  <exec_depend>rviz2</exec_depend>
  <exec_depend>ros_tcp_endpoint</exec_depend>
  <test_depend>ament_copyright</test_depend>
  <test_depend>ament_flake8</test_depend>
  <test_depend>ament_pep257</test_depend>
  <test_depend>python3-pytest</test_depend>
  <export>
    <build_type>ament_python</build_type>
  </export>
</package>
```

#### `setup.py`

```python
from setuptools import find_packages, setup
from glob import glob
import os

package_name = 'piper_unity'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
        (os.path.join('share', package_name, 'launch'), glob('launch/*.py')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='root',
    maintainer_email='root@todo.todo',
    description='Unity simulator bridge for Piper robot arm',
    license='Apache-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'piper_unity_sim = piper_unity.piper_unity_sim_node:main',
        ],
    },
)
```

#### `piper_unity/piper_unity_sim_node.py`

`/home/hsr/piper_ros/src/piper/piper/piper_single_ctrl_moveit_action_node.py` をベースに
CAN 通信をすべて削除し、Unity ブリッジトピックに置き換えたノード。

**削除するもの（実機専用）:**
- `piper_sdk` / `C_PiperInterface` インポートおよびすべての CAN 通信コード
- `ConnectPort()`, `EnableArm()`, `DisableArm()`, `JointCtrl()`, `GripperCtrl()`,
  `GetArmJointMsgs()`, `GetArmHighSpdInfoMsgs()`, `GetArmGripperMsgs()`,
  `GetArmEndPoseMsgs()`, `GetArmJointCtrl()`, `GetArmGripperCtrl()`, `GetArmStatus()`,
  `GetArmLowSpdInfoMsgs()`, `isOk()`, `MotionCtrl_2()` 等
- `can_port` パラメータ

**追加するもの（Unity ブリッジ）:**

```python
# 新規 Publisher（Unity への指令）
self.unity_cmd_pub = self.create_publisher(JointState, '/piper_unity/joint_cmd', 1)

# 新規 Subscriber（Unity からのフィードバック）
self.unity_state_sub = self.create_subscription(
    JointState, '/piper_unity/joint_states', self.unity_state_callback, 1)

# Unity からの関節状態バッファ
self.unity_joint_positions = [0.0] * 7
self.unity_joint_velocities = [0.0] * 7
self.unity_joint_efforts = [0.0] * 7
self.unity_state_lock = threading.Lock()
```

**変更箇所の対応表:**

| 実機コード | Unity シミュレータ代替 |
|---|---|
| `auto_enable` ループ（CAN ハンドシェイク待機） | 即時 `__enable_flag = True` |
| `piper.MotionCtrl_2(...) + piper.JointCtrl(v1..v6)` | `/piper_unity/joint_cmd` に JointState pub（rad 値そのまま） |
| `piper.GripperCtrl(val_g, ...)` | 同じ JointState の joint7 に含める |
| `piper.GetArmJointMsgs()` 等でフィードバック取得 | `/piper_unity/joint_states` 受信バッファから取得 |
| `piper.EndPoseCtrl(...)` (pos_cmd) | ログ警告のみ（今回スコープ外） |
| `piper.EnableArm(7) / DisableArm(7)` | フラグ操作のみ（即時応答） |
| `arm_status` pub（実機ステータス） | PiperStatusMsg() ゼロ値 pub |
| `end_pose` pub（FK 結果） | Pose() / PoseStamped() ゼロ値 pub |
| `piper.isOk()` チェック | 常に True として処理続行 |

**publish_thread の変更:**
```python
def publish_thread(self):
    rate = self.create_rate(50)  # 50 Hz
    if self.auto_enable:
        self.__enable_flag = True
    while rclpy.ok():
        with self.unity_state_lock:
            positions = list(self.unity_joint_positions)
            velocities = list(self.unity_joint_velocities)
            efforts = list(self.unity_joint_efforts)
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = self.all_joint_names
        js.position = positions
        js.velocity = velocities
        js.effort = efforts
        self.joint_pub.publish(js)           # joint_states_single (→ /joint_states)
        self.joint_feedback_pub.publish(js)  # joint_states_feedback
        self.arm_status_pub.publish(PiperStatusMsg())
        self.end_pose_pub.publish(Pose())
        self.end_pose_stamped_pub.publish(PoseStamped())
        rate.sleep()
```

**trajectory_timer_callback の変更（制御部分のみ）:**
```python
# JointCtrl の代わりに /piper_unity/joint_cmd を publish
cmd = JointState()
cmd.header.stamp = self.get_clock().now().to_msg()
cmd.name = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6', 'joint7']
cmd.position = [j1, j2, j3, j4, j5, j6, g_pos_rad]  # ラジアンのまま（変換不要）
self.unity_cmd_pub.publish(cmd)
```

#### `launch/start_piper_unity.launch.py`

`piper_real_moveit.launch.py` と `start_single_moveit_piper_action.launch.py` を 1 ファイルに統合し、
ROS-TCP-Endpoint ノードを追加。

起動するノード:
1. `robot_state_publisher` — URDF + /joint_states → TF
2. `move_group` — MoveIt2（`use_sim_time=False`）
3. `rviz2` — moveit.rviz 設定
4. `piper_unity_sim` — name=`piper_ctrl_single_node`（実機と同名で互換性確保）、remapping: `joint_states_single` → `/joint_states`
5. `default_server_endpoint` — ROS_IP=0.0.0.0, ROS_TCP_PORT=10000

MoveIt 設定は `MoveItConfigsBuilder("piper", package_name="piper_with_gripper_moveit")` を流用。

---

### 2. Unity C# スクリプト

#### `/home/hsr/unity_projects/unity-ros/Assets/scripts/PiperJointController.cs`

ROS から `/piper_unity/joint_cmd` (JointStateMsg) を受信し、ArticulationBody の xDrive.target を更新。

```csharp
using System.Collections.Generic;
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;

public class PiperJointController : MonoBehaviour
{
    [Header("Joint Bodies (joint1 to joint7 の順)")]
    public ArticulationBody[] joints;  // Inspector で link1〜link7 をアサイン

    [Header("Drive Settings")]
    public float stiffness = 100000f;
    public float damping = 10000f;
    public float forceLimit = 10000f;

    private ROSConnection ros;
    private const string TopicName = "/piper_unity/joint_cmd";

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.Subscribe<JointStateMsg>(TopicName, OnJointCmd);
        ApplyDriveSettings();
    }

    void OnJointCmd(JointStateMsg msg)
    {
        var nameToIndex = new Dictionary<string, int>();
        for (int i = 0; i < joints.Length; i++)
            nameToIndex[$"joint{i + 1}"] = i;

        for (int k = 0; k < msg.name.Length && k < msg.position.Length; k++)
        {
            if (!nameToIndex.TryGetValue(msg.name[k], out int idx)) continue;
            if (idx >= joints.Length || joints[idx] == null) continue;

            var body = joints[idx];
            var drive = body.xDrive;

            // revolute: rad → deg, prismatic (joint7 gripper): m のまま
            if (body.jointType == ArticulationJointType.RevoluteJoint)
                drive.target = (float)(msg.position[k] * Mathf.Rad2Deg);
            else
                drive.target = (float)msg.position[k];

            body.xDrive = drive;
        }
    }

    void ApplyDriveSettings()
    {
        foreach (var body in joints)
        {
            if (body == null) continue;
            var drive = body.xDrive;
            drive.stiffness = stiffness;
            drive.damping = damping;
            drive.forceLimit = forceLimit;
            body.xDrive = drive;
        }
    }
}
```

#### `/home/hsr/unity_projects/unity-ros/Assets/scripts/PiperJointStatePublisher.cs`

ArticulationBody の関節状態を `/piper_unity/joint_states` (JointStateMsg) として ROS へ送信。

```csharp
using UnityEngine;
using Unity.Robotics.ROSTCPConnector;
using RosMessageTypes.Sensor;
using RosMessageTypes.Std;

public class PiperJointStatePublisher : MonoBehaviour
{
    [Header("Joint Bodies (joint1 to joint7 の順)")]
    public ArticulationBody[] joints;  // Inspector で link1〜link7 をアサイン

    [Header("Publish Rate (Hz)")]
    public float publishHz = 50f;

    private ROSConnection ros;
    private const string TopicName = "/piper_unity/joint_states";
    private static readonly string[] JointNames =
        { "joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7" };

    void Start()
    {
        ros = ROSConnection.GetOrCreateInstance();
        ros.RegisterPublisher<JointStateMsg>(TopicName);
        InvokeRepeating(nameof(PublishJointStates), 0f, 1f / publishHz);
    }

    void PublishJointStates()
    {
        int n = Mathf.Min(joints.Length, JointNames.Length);
        double[] positions = new double[n];
        double[] velocities = new double[n];
        double[] efforts = new double[n];

        for (int i = 0; i < n; i++)
        {
            if (joints[i] == null || joints[i].dofCount == 0) continue;
            // revolute: rad, prismatic: m
            positions[i] = joints[i].jointPosition[0];
            velocities[i] = joints[i].jointVelocity[0];
            efforts[i] = joints[i].jointForce[0];
        }

        var msg = new JointStateMsg
        {
            header = new HeaderMsg
            {
                stamp = new RosMessageTypes.BuiltinInterfaces.TimeMsg
                {
                    sec = (int)Time.realtimeSinceStartup,
                    nanosec = (uint)((Time.realtimeSinceStartup % 1f) * 1e9)
                },
                frame_id = ""
            },
            name = JointNames[..n],
            position = positions,
            velocity = velocities,
            effort = efforts
        };

        ros.Publish(TopicName, msg);
    }
}
```

---

## Unity シーン設定手順

1. Unity Editor で `Assets/Scenes/Piper.unity` を開く
2. URDF import 済みのロボット GameObject の子 `link1`〜`link7` の ArticulationBody を確認
3. 空の GameObject `PiperROS` を作成
4. `PiperJointController.cs` をアタッチ → `Joints` に link1〜link7 の ArticulationBody を順にアサイン
5. `PiperJointStatePublisher.cs` をアタッチ → 同様に `Joints` をアサイン
6. ROSConnection 設定: `ROS IP = 127.0.0.1`, `Port = 10000`

---

## ROS-TCP-Endpoint 配置変更に関する注記

- 移動前: /home/hsr/ROS-TCP-Endpoint/
- 移動後: /home/hsr/piper_ros/ROS-TCP-Endpoint/
- Docker コンテナ内では /ros2_ws/ROS-TCP-Endpoint/ としてマウントされる（piper_ros 統合ワークスペースの一部）
- launch ファイルへのコード変更は不要。colcon がワークスペースルートからパッケージを自動検出する
- 注意: /ros2_ws/ROS-TCP-Endpoint/install/setup.bash は source しないこと。ワークスペースレベルの /ros2_ws/install/setup.bash を使用すること
- ROS-TCP-Endpoint/build/ および ROS-TCP-Endpoint/install/ 内の旧スタンドアロンビルド成果物は使用しない

---

### ビルドと起動手順

#### Docker コンテナ起動

```bash
# ホスト側: コンテナを起動
cd /home/hsr/piper_ros/docker
docker compose up -d piper-humble-dev
```

#### ROS2 ビルド（コンテナ内）

```bash
# コンテナに入る
docker exec -it piper-humble-dev bash

# コンテナ内 (ワークスペースは /ros2_ws)
source /opt/ros/humble/setup.bash
cd /ros2_ws
colcon build --packages-select ros_tcp_endpoint piper_unity
source install/setup.bash
```

#### 起動（コンテナ内）

```bash
# コンテナ内で実行
source /opt/ros/humble/setup.bash
source /ros2_ws/install/setup.bash
ros2 launch piper_unity start_piper_unity.launch.py

# Unity Editor: Piper.unity → Play
```

---

## 実機との切り替え

| 環境 | コマンド |
|---|---|
| 実機 | ホストから: `docker exec -it piper-humble-dev bash -c "source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && ros2 launch piper start_single_moveit_piper_action.launch.py"` + `docker exec -it piper-humble-dev bash -c "source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && ros2 launch piper_with_gripper_moveit piper_real_moveit.launch.py"`<br>コンテナ内から: `source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && ros2 launch piper start_single_moveit_piper_action.launch.py` + `ros2 launch piper_with_gripper_moveit piper_real_moveit.launch.py` |
| Unity シミュレータ | ホストから: `docker exec -it piper-humble-dev bash -c "source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && ros2 launch piper_unity start_piper_unity.launch.py"` + Unity Play<br>コンテナ内から: `source /opt/ros/humble/setup.bash && source /ros2_ws/install/setup.bash && ros2 launch piper_unity start_piper_unity.launch.py` + Unity Play |

アプリケーションコード（MoveIt2 クライアント等）は変更不要。

---

## 検証方法

```bash
# 1. 関節フィードバック確認
ros2 topic echo /joint_states

# 2. Action テスト
ros2 action send_goal /arm_controller/follow_joint_trajectory \
  control_msgs/action/FollowJointTrajectory \
  "{trajectory: {joint_names: [joint1,joint2,joint3,joint4,joint5,joint6], \
    points: [{positions: [0.0,0.3,0.0,0.0,0.0,0.0], time_from_start: {sec: 2}}]}}"

# 3. Enable 確認
ros2 topic pub --once /enable_flag std_msgs/msg/Bool '{data: true}'

# 4. 内部ブリッジ確認（デバッグ用）
ros2 topic echo /piper_unity/joint_cmd
ros2 topic echo /piper_unity/joint_states
```

---

# コチャカ (Kobuki + カチャカシェルフ + Piper + RealSense) 統合シミュレータ

## 1. 統合アーキテクチャとブリッジノードの役割

### なぜブリッジノードが必要なのか？（ROS-TCP-Endpoint だけでは足りない理由）

- **ROS-TCP-Endpoint**:
  - Unity と ROS 2 間で TCP 接続（ポート 10000）を張り、ROS メッセージをシリアライズ/デシリアライズして素通しする「ネットワーク土管」。
  - 制御の論理（運動学やオドメトリ計算、Action サーバー等）は持たない。
- **Kobuki ブリッジノード (`kobuki_unity_sim_node.py`)**:
  - **役割**: 実機 Kobuki のマイコン・モータドライバの振る舞いを完全に再現。
  - **動作**: 上位ノード（Nav2 やテレオペ）からの `commands/velocity` (`Twist`: $v_x, \omega_z$) を受信 $\rightarrow$ 差動二輪運動学から左右車輪の目標角速度を計算して `/kobuki_unity/wheel_cmd` を Unity に送信。
  - 逆に Unity の車輪回転角 `/kobuki_unity/wheel_states` を受信 $\rightarrow$ 累積回転からオドメトリ `/odom` および TF (`odom` $\rightarrow$ `base_footprint`) を計算して配信。`commands/reset_odometry` にも完全対応。
- **Piper ブリッジノード (`piper_unity_sim_node.py`)**:
  - **役割**: 実機 Piper の CAN バス制御と FollowJointTrajectory Action サーバーを再現。
  - **動作**: MoveIt 2 からの関節軌道目標を受信して `/piper_unity/joint_cmd` を Unity へ送信。Unity から返る実関節角 `/piper_unity/joint_states` を上位の `/joint_states` や Action フィードバックとして配信。
- **RealSense カメラ パブリッシャー (`RealSenseCameraPublisher.cs`)**:
  - **役割**: Piper アーム先端（`gripper_base` / `camera_color_optical_frame`）の Unity カメラ映像を取得し、実機 RealSense D435i 完全互換トピックを配信。
  - **カラー画像**: `/camera/camera/color/image_raw` (`rgb8`), `/camera/camera/color/camera_info`
  - **深度画像**: `/camera/camera/aligned_depth_to_color/image_raw` (`16UC1`, 単位: mm), `/camera/camera/aligned_depth_to_color/camera_info`
  - **Display 2 出力**: Game ビューの Display 2 にリアルタイム描画しつつ、ROS 2 へも画像/深度を同時配信。

---

## 2. 起動 launch ファイル (`view_mobile_manipulator_unity.launch.py`) の詳細

```text
ros2 launch mobile_manipulator_description view_mobile_manipulator_unity.launch.py
  ├─ [default_server_endpoint]      ROS-TCP-Endpoint (TCP: 10000)
  ├─ [kobuki_unity_sim_node]        Kobuki 運動学・オドメトリ・TF・リセット
  ├─ [piper_unity_sim_node]         Piper MoveIt2 アクションサーバー・JointState
  ├─ [robot_state_publisher]        コチャカ合成 URDF から全 TF ツリーをブロードキャスト
  └─ [rviz2]                        コチャカ 3D モデル・TF・オドメトリ表示
```

---

## 3. 動作確認・検証手順 (Step 0 〜 Step 4)

### Step 0: 事前確認（Unity エディタ）
1. Unity Project ビューで `mobile_manipulator.urdf` を右クリック $\rightarrow$ `[Import Robot from Selected URDF]`。
   - **Select Axis Type: `Y Axis`** （※メッシュが Y-up 基準のため）
   - **Select Convex Decomposer: `Unity`**
2. Hierarchy 上の `mobile_manipulator` を選択し、上部メニュー **`[Kotyaka] -> [Setup Components on Selected Robot]`** を実行。
   - 車輪制御・アーム制御・RealSense カメラ・統合マネージャーが全自動でアサインされます。
3. シーンを保存 (`Ctrl + S`)。

### Step 1: 統合ブリッジ起動と Unity の Play
```bash
# Docker コンテナ内で実行
source /opt/ros/humble/setup.bash
source /home/kobuki_ws/install/setup.bash
source /ros2_ws/install/setup.bash

ros2 launch mobile_manipulator_description view_mobile_manipulator_unity.launch.py
```
- Unity Editor で **Play (再生 ▶)** ボタンを押下（左上に `ROS connected` 表示）。

### Step 2: ROS 2 コマンドによる走行・トピック通信確認
```bash
# 1. 台車の遠隔走行 (前進 0.2 m/s, 旋回 0.3 rad/s)
ros2 topic pub /commands/velocity geometry_msgs/msg/Twist "{linear: {x: 0.2, y: 0.0, z: 0.0}, angular: {x: 0.0, y: 0.0, z: 0.3}}" -r 10

# 2. オドメトリの確認
ros2 topic echo /odom

# 3. TF ツリーの確認 (base_footprint からカメラ先端まで一本で結合)
ros2 run tf2_ros tf2_echo odom camera_color_optical_frame

# 4. RealSense カメラ映像の受信確認
ros2 run rqt_image_view rqt_image_view /camera/camera/color/image_raw
```

### Step 3: MoveIt 2 によるアーム制御確認
```bash
# MoveIt 2 Action で Piper アームを目標軌道へ駆動
ros2 action send_goal /arm_controller/follow_joint_trajectory control_msgs/action/FollowJointTrajectory "{
  trajectory: {
    joint_names: ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6'],
    points: [
      { positions: [0.2, 0.3, -0.4, 0.2, 0.5, 0.0], time_from_start: { sec: 2, nanosec: 0 } },
      { positions: [0.0, 0.0, 0.0, 0.0, 0.0, 0.0], time_from_start: { sec: 5, nanosec: 0 } }
    ]
  }
}"
```

### Step 4: 地図作成 (SLAM)・自己位置推定・Nav2 自律移動
1. **自己位置推定・SLAM**:
   - オドメトリ (`/odom`) + TF (`odom` $\rightarrow$ `base_footprint`) はすでに完成済み。
   - `slam_toolbox` または `cartographer` に `/scan` (LiDAR または Depth 画像変換) を入力して地図作成 (`/map`)。
2. **Nav2 自律移動**:
   - `nav2_bringup` を起動し、RViz 上で `2D Pose Estimate` と `Nav2 Goal` を指定して自律走行。

---

## 4. 別の開発 PC への移行・セットアップ手順

別の PC で作業する場合のセットアップ手順：
1. **リポジトリのクローン・配置**:
   - `piper_ros` および `oit_kobuki_ws-main` を配置。
2. **Docker コンテナ起動**:
   ```bash
   cd ~/piper_ros
   ./RUN-DOCKER-CONTAINER.bash
   ```
3. **Unity プロジェクトの準備**:
   - Unity 6 (6000.4.x) または Unity 2021.3+ で `unity-ros` プロジェクトを開く。
   - `Assets/scripts/Kotyaka/` に C# スクリプト群、`Assets/URDF/mobile_manipulator/` に URDF と各メッシュ（`kobuki_description`, `piper_description`, `realsense2_description`）が配置されていることを確認。
4. **URDF のインポート**:
   - `mobile_manipulator.urdf` を `Axis: Y Axis`, `Convex Decomposer: Unity` でインポート。
   - ロボットを選択して `[Kotyaka] -> [Setup Components on Selected Robot]` を実行。

