import math
import time
from typing import Optional
import rclpy
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.node import Node
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from rclpy.task import Future
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectory, JointTrajectoryPoint

class TrajectoryBridge(Node):
    """MoveItの軌道をブラウザへ転送し、軌道時間の完了を返す。"""

    def __init__(self):
        super().__init__("piper_websim")
        self.declare_parameter("trajectory_topic", "/sim/piper/trajectory")
        self.declare_parameter("joint_target_topic", "/sim/piper/joint_targets")
        self.declare_parameter("joint_state_topic", "/joint_states")
        self.declare_parameter("action_name", "/arm_controller/follow_joint_trajectory")
        self._sleep_group = ReentrantCallbackGroup()
        self.target_publisher = self.create_publisher(JointState, self.get_parameter("joint_target_topic").value, 10)
        self.trajectory_publisher = self.create_publisher(JointTrajectory, self.get_parameter("trajectory_topic").value, 10)
        self.state_subscription = self.create_subscription(JointState, self.get_parameter("joint_state_topic").value, self._on_state, 10)
        self.declare_parameter("gripper_action_name", "/gripper_controller/follow_joint_trajectory")
        self.action_server = ActionServer(self, FollowJointTrajectory, self.get_parameter("action_name").value, execute_callback=self._execute, goal_callback=self._goal, cancel_callback=self._cancel)
        # MoveItのgripper_controller（joint7）も同じ経路でWebへ転送する。
        self.gripper_action_server = ActionServer(self, FollowJointTrajectory, self.get_parameter("gripper_action_name").value, execute_callback=self._execute, goal_callback=self._goal, cancel_callback=self._cancel)
        self.current_state: dict[str, float] = {}
        self.active_target: Optional[JointTrajectory] = None
        self._last_target: Optional[JointState] = None
        self.create_timer(0.1, self._republish_target)

    def _republish_target(self):
        if self._last_target is not None:
            self.target_publisher.publish(self._last_target)

    def _on_state(self, message: JointState):
        self.current_state.update({name: position for name, position in zip(message.name, message.position)})

    def _goal(self, _request):
        return GoalResponse.ACCEPT

    def _cancel(self, _goal_handle):
        self.active_target = None
        return CancelResponse.ACCEPT

    def _execute(self, goal_handle):
        trajectory = self._normalize_trajectory(goal_handle.request.trajectory)
        if not trajectory.joint_names or not trajectory.points:
            goal_handle.abort()
            return FollowJointTrajectory.Result(error_code=FollowJointTrajectory.Result.INVALID_GOAL)
        trajectory.header.stamp = self.get_clock().now().to_msg()
        self.active_target = trajectory
        self.trajectory_publisher.publish(trajectory)
        start = self.get_clock().now()
        try:
            while rclpy.ok() and not goal_handle.is_cancel_requested:
                elapsed = (self.get_clock().now() - start).nanoseconds / 1e9
                point = self._interpolate(trajectory, elapsed)
                message = JointState()
                message.header.stamp = self.get_clock().now().to_msg()
                message.name = list(trajectory.joint_names)
                message.position = list(point.positions)
                self._last_target = message
                self.target_publisher.publish(message)
                feedback = FollowJointTrajectory.Feedback()
                feedback.joint_names = list(trajectory.joint_names)
                feedback.actual = self._actual(trajectory.joint_names)
                feedback.desired = point
                goal_handle.publish_feedback(feedback)
                if elapsed >= self._duration(trajectory):
                    # ブラウザ側のjoint_states遅延に左右されず、軌道時間の完了をアクション完了とする。
                    goal_handle.succeed()
                    return FollowJointTrajectory.Result(error_code=FollowJointTrajectory.Result.SUCCESSFUL)
                time.sleep(0.02)
            goal_handle.canceled()
            # cancel済みの軌道をSUCCESSFULで返すとMoveItが到達済みと誤認し、次の計画が
            # 途中の姿勢から始まってしまう。中断はCANCELEDで返す。
            return FollowJointTrajectory.Result(error_code=FollowJointTrajectory.Result.CANCELED)
        finally:
            self.active_target = None

    @staticmethod
    def _normalize_trajectory(trajectory):
        # 一部の簡易MoveIt構成では全点のtime_from_startが0になるため、単調時刻を補う。
        if not trajectory.points:
            return trajectory
        duration = trajectory.points[-1].time_from_start.sec + trajectory.points[-1].time_from_start.nanosec / 1e9
        if duration > 0:
            return trajectory
        normalized = JointTrajectory()
        normalized.header = trajectory.header
        normalized.joint_names = list(trajectory.joint_names)
        count = len(trajectory.points)
        for index, source in enumerate(trajectory.points):
            point = JointTrajectoryPoint()
            point.positions = list(source.positions)
            point.velocities = list(source.velocities)
            point.accelerations = list(source.accelerations)
            point.effort = list(source.effort)
            seconds = 1.0 * index / max(1, count - 1)
            point.time_from_start.sec = int(seconds)
            point.time_from_start.nanosec = int(round((seconds - int(seconds)) * 1e9))
            normalized.points.append(point)
        return normalized

    @staticmethod
    def _duration(trajectory):
        point = trajectory.points[-1]
        return point.time_from_start.sec + point.time_from_start.nanosec / 1e9

    def _interpolate(self, trajectory, elapsed):
        if elapsed <= 0:
            return trajectory.points[0]
        for left, right in zip(trajectory.points, trajectory.points[1:]):
            left_time = left.time_from_start.sec + left.time_from_start.nanosec / 1e9
            right_time = right.time_from_start.sec + right.time_from_start.nanosec / 1e9
            if elapsed <= right_time:
                alpha = (elapsed - left_time) / max(1e-9, right_time - left_time)
                point = JointTrajectoryPoint()
                point.positions = [a + (b - a) * alpha for a, b in zip(left.positions, right.positions)]
                return point
        return trajectory.points[-1]

    def _actual(self, names):
        point = JointTrajectoryPoint()
        point.positions = [self.current_state.get(name, math.nan) for name in names]
        return point

    def _within_tolerance(self, names, positions, tolerance=0.02):
        return all(math.isfinite(self.current_state.get(name, math.nan)) and abs(self.current_state[name] - target) <= tolerance for name, target in zip(names, positions))

def main(args=None):
    rclpy.init(args=args)
    node = TrajectoryBridge()
    executor = MultiThreadedExecutor(num_threads=2)
    executor.add_node(node)
    try:
        executor.spin()
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.shutdown()
