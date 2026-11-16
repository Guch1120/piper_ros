"""MoveItのFollowJointTrajectoryをスタンドアロンPiper（`?robot=piper`）のWeb simへ転送する。

cotyaka用（`websim_moveit.launch.py`内で起動）と**同じノード**（`trajectory_bridge.py`）を、
別ノード名・別simトピックで起動するためのlaunch。ソースは共有しているのでsim側の修正は1箇所。

変更点:
  - ノード名を`piper_websim`から`piper_standalone_sim_bridge`に変える。
  - configを`config/bridge_piper_standalone.yaml`にして、転送先を
    `/sim/piper_standalone/joint_targets`（cotyaka側は`/sim/piper/joint_targets`）に向ける。

action名（`/arm_controller`・`/gripper_controller`）は**cotyaka版と共通のまま**。
piper単体で運用するのが前提なので分離する必要がなく、MoveItの
`moveit_controllers.yaml`も`piper_ros`側の実機経路（`moveit_bridge.py` 等、action名を
ハードコード）も一切変更しなくてよい。

## 運用制約: cotyaka版とは同時に起動しないこと
action名が共通なので、両方を起動すると同一action名に2ノードが登録され、ROS 2は片方だけを
アクションサーバとして報告する（`ros2 action info` が "Action servers: 1"）。このとき
もう片方はノード一覧から消え、**MoveItの軌道が別のロボットへ流れる**。

実測（両コンテナを同時に起動した場合）:
  - `/arm_controller/follow_joint_trajectory` は後起動側のノードだけを報告し、
    先起動側のノードは不可視になる。
  - 後起動側をstopすると先起動側へ復帰（恒久的な破損ではなくshadowing）。

piper単体で動かす運用なら問題にならない。cotyakaと同時に動かす必要がある場合は、
MoveItのcontroller設定と本ノードのaction名を同時に改名する必要がある。
"""
import os

import yaml
from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


NODE_NAME = 'piper_standalone_sim_bridge'


def generate_launch_description():
    share = get_package_share_directory('piper_websim')
    parameters = os.path.join(share, 'config', 'bridge_piper_standalone.yaml')
    # ROS 2のYAMLパラメータはルートキーがノード名に厳密に一致しないと黙って無視され、
    # ノードはデフォルト値（= cotyaka用の`/sim/piper/joint_targets`）で立ち上がる。
    # ブラウザ側は接続に気づけないので、ここで起動時に落とす。
    with open(parameters) as handle:
        root = yaml.safe_load(handle) or {}
    if NODE_NAME not in root:
        raise RuntimeError(
            f"{parameters} のルートキーが '{NODE_NAME}' ではありません（実際: {list(root)}）。"
            " ノード名とYAMLのルートキーは一致させる必要があります。"
        )
    return LaunchDescription([
        Node(
            package='piper_websim',
            executable='trajectory_bridge',
            name=NODE_NAME,
            output='screen',
            parameters=[parameters],
        ),
    ])
