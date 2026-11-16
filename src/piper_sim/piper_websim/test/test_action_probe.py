import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint

class ActionProbe(Node):
    def __init__(self):
        super().__init__("cotyaka_action_probe")
        self.publisher = self.create_publisher(JointState, "/joint_states", 10)
        self.client = ActionClient(self, FollowJointTrajectory, "/arm_controller/follow_joint_trajectory")
        self.timer = self.create_timer(0.05, self.publish_state)

    def publish_state(self):
        message = JointState()
        message.name = ["joint1"]
        message.position = [1.0]
        self.publisher.publish(message)

def main():
    rclpy.init()
    node = ActionProbe()
    try:
        if not node.client.wait_for_server(timeout_sec=5.0):
            raise RuntimeError("action serverが起動していません")
        goal = FollowJointTrajectory.Goal()
        goal.trajectory.joint_names = ["joint1"]
        point = JointTrajectoryPoint()
        point.positions = [1.0]
        point.time_from_start.sec = 0
        point.time_from_start.nanosec = 100000000
        goal.trajectory.points = [point]
        send_future = node.client.send_goal_async(goal)
        rclpy.spin_until_future_complete(node, send_future, timeout_sec=5.0)
        handle = send_future.result()
        if handle is None or not handle.accepted:
            raise RuntimeError("trajectory goalが拒否されました")
        result_future = handle.get_result_async()
        rclpy.spin_until_future_complete(node, result_future, timeout_sec=10.0)
        wrapped = result_future.result()
        if wrapped is None or wrapped.result.error_code != FollowJointTrajectory.Result.SUCCESSFUL:
            raise RuntimeError(f"trajectory resultが失敗しました: {wrapped.result.error_code if wrapped else None}")
        print("MOVEIT_ACTION_PASS")
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == "__main__":
    main()
