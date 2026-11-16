#!/usr/bin/env python3
"""スタンドアロンPiper(sim)側のjoint target受信を確認するプローブ。

`websim_moveit.launch.py`（cotyaka）と対になるテストで、
`trajectory_bridge_standalone.launch.py` が
  - MoveIt互換のaction `/arm_controller/follow_joint_trajectory` を提供し、
  - 転送先が `/sim/piper_standalone/joint_targets`（cotyakaの `/sim/piper/joint_targets` ではない）
であることを確認する。ブラウザ側は別のプロセスなので、ここでは
「actionが受理され、CANCELED/INVALIDを混ぜずSUCCESSFULで返る」ことと
「joint targetが ROS iala名字で届く」ことだけを見る。

使い方:
  ros2 launch piper_websim trajectory_bridge_standalone.launch.py
  python3 test/test_action_probe_standalone.py
"""
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

TARGET_TOPIC = "/sim/piper_standalone/joint_targets"
ACTION_NAME = "/arm_controller/follow_joint_trajectory"


class StandaloneActionProbe(Node):
    def __init__(self):
        super().__init__("piper_standalone_action_probe")
        self.received: list[tuple[list[str], list[float]]] = []
        # 実機bridgeと同じ joint_states を模す。simは joint1..joint8 を返すので、
        # bridgeの _actual() がNaNにならないよう8軸分を流す。
        self.state_pub = self.create_publisher(JointState, "/joint_states", 10)
        self.create_subscription(JointState, TARGET_TOPIC, self._on_target, 10)
        self.client = ActionClient(self, FollowJointTrajectory, ACTION_NAME)
        self.create_timer(0.05, self._publish_state)

    def _publish_state(self):
        message = JointState()
        message.name = ["joint1", "joint2", "joint3", "joint4", "joint5", "joint6", "joint7", "joint8"]
        message.position = [0.0] * 8
        self.state_pub.publish(message)

    def _on_target(self, message):
        if message.name:
            self.received.append((list(message.name), list(message.position)))


def main():
    rclpy.init()
    node = StandaloneActionProbe()
    try:
        if not node.client.wait_for_server(timeout_sec=5.0):
            raise RuntimeError(f"{ACTION_NAME} が起動していません")
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ["joint1", "joint2"]
        point = JointTrajectoryPoint()
        point.positions = [0.4, -0.2]
        point.time_from_start.sec = 1
        goal.trajectory.points = [point]
        send_future = node.client.send_goal_async(goal)
        rclpy.spin_until_future_complete(node, send_future, timeout_sec=5.0)
        handle = send_future.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("trajectory goalが拒否されました")
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(node, result_future, timeout_sec=10.0)
        wrapped = result_future.result()
        if wrapped is None:
            raise RuntimeError("trajectory resultが返りませんでした")
        if wrapped.result.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            raise RuntimeError(f"trajectory resultが失敗しました: {wrapped.result.error_code}")
        if not node.received:
            raise RuntimeError(f"{TARGET_TOPIC} が受信できませんでした")
        print("PIPER_STANDALONE_ACTION_PASS")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
