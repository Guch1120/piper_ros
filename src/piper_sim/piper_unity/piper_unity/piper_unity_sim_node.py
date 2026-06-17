#!/usr/bin/env python3
# -*-coding:utf8-*-
# Unity simulator bridge for Piper robot arm.
# Implements the same ROS2 interface as piper_single_ctrl_moveit_action_node.py
# but replaces CAN bus communication with Unity ArticulationBody bridge topics.

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool
from geometry_msgs.msg import Pose, PoseStamped
from trajectory_msgs.msg import JointTrajectoryPoint
from piper_msgs.msg import PiperStatusMsg, PosCmd
from piper_msgs.srv import Enable
import time
import threading


class PiperUnitySimNode(Node):
    """ROS2 node that mirrors the real Piper hardware interface but drives Unity via TCP bridge."""

    def __init__(self) -> None:
        super().__init__('piper_ctrl_single_node')

        self.declare_parameter('auto_enable', True)
        self.declare_parameter('gripper_exist', True)

        self.auto_enable = self.get_parameter('auto_enable').get_parameter_value().bool_value
        self.gripper_exist = self.get_parameter('gripper_exist').get_parameter_value().bool_value

        self.get_logger().info(f"[Unity sim] auto_enable={self.auto_enable}")
        self.get_logger().info(f"[Unity sim] gripper_exist={self.gripper_exist}")

        self.all_joint_names = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6', 'joint7']

        # Action server state
        self.active_trajectory = None
        self.start_time = None
        self.trajectory_lock = threading.Lock()
        self.current_joint_targets = [0.0] * 7

        # Unity bridge state buffer (filled by /piper_unity/joint_states subscriber)
        self.unity_joint_positions = [0.0] * 7
        self.unity_joint_velocities = [0.0] * 7
        self.unity_joint_efforts = [0.0] * 7
        self.unity_state_lock = threading.Lock()

        self.__enable_flag = False

        # --- External publishers (same as real hardware node) ---
        self.joint_pub = self.create_publisher(JointState, 'joint_states_single', 1)
        self.joint_feedback_pub = self.create_publisher(JointState, 'joint_states_feedback', 1)
        self.joint_ctrl_pub = self.create_publisher(JointState, 'joint_ctrl', 1)
        self.arm_status_pub = self.create_publisher(PiperStatusMsg, 'arm_status', 1)
        self.end_pose_pub = self.create_publisher(Pose, 'end_pose', 1)
        self.end_pose_stamped_pub = self.create_publisher(PoseStamped, 'end_pose_stamped', 1)

        # --- Unity bridge publisher (replaces CAN JointCtrl) ---
        self.unity_cmd_pub = self.create_publisher(JointState, '/piper_unity/joint_cmd', 1)

        # --- Service ---
        self.motor_srv = self.create_service(Enable, 'enable_srv', self.handle_enable_service)

        # --- Action servers ---
        self._action_cb_group = ReentrantCallbackGroup()
        self._action_server_arm = ActionServer(
            self, FollowJointTrajectory, 'arm_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self._action_cb_group,
        )
        self._action_server_gripper = ActionServer(
            self, FollowJointTrajectory, 'gripper_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback,
            callback_group=self._action_cb_group,
        )

        # --- Subscribers ---
        # Unity bridge: receive actual joint positions from Unity physics engine
        self.create_subscription(
            JointState, '/piper_unity/joint_states', self.unity_state_callback, 1)
        # Same topic-based control interface as real hardware
        self.create_subscription(PosCmd, 'pos_cmd', self.pos_callback, 1)
        self.create_subscription(JointState, 'joint_ctrl_single', self.joint_callback, 1)
        self.create_subscription(Bool, 'enable_flag', self.enable_callback, 1)

        # --- Threads and timers ---
        self.publisher_thread = threading.Thread(target=self.publish_thread, daemon=True)
        self.publisher_thread.start()

        self.trajectory_timer = self.create_timer(
            0.01, self.trajectory_timer_callback, callback_group=self._action_cb_group)

    def GetEnableFlag(self):
        return self.__enable_flag

    # --- Unity bridge callback ---
    def unity_state_callback(self, msg: JointState):
        """Receive actual joint positions from Unity (replaces piper.GetArmJointMsgs())."""
        name_to_idx = {name: i for i, name in enumerate(self.all_joint_names)}
        with self.unity_state_lock:
            for k, name in enumerate(msg.name):
                idx = name_to_idx.get(name)
                if idx is None:
                    continue
                if k < len(msg.position):
                    self.unity_joint_positions[idx] = msg.position[k]
                if k < len(msg.velocity):
                    self.unity_joint_velocities[idx] = msg.velocity[k]
                if k < len(msg.effort):
                    self.unity_joint_efforts[idx] = msg.effort[k]

    # --- Action server callbacks ---
    def goal_callback(self, goal_request):
        self.get_logger().info('Received new action goal')
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info('Received cancel request')
        return CancelResponse.ACCEPT

    def _ensure_trajectory_from_current(self, trajectory):
        """Unityの現在状態が軌道開始点と大きくずれている場合、現在状態をt=0の点として先頭に追加する。"""
        if not trajectory.points:
            return trajectory

        joint_names = trajectory.joint_names
        name_to_idx = {n: i for i, n in enumerate(self.all_joint_names)}

        with self.unity_state_lock:
            current_pos = list(self.unity_joint_positions)

        first_point = trajectory.points[0]
        max_dev = 0.0
        for k, name in enumerate(joint_names):
            idx = name_to_idx.get(name)
            if idx is not None and k < len(first_point.positions):
                dev = abs(current_pos[idx] - first_point.positions[k])
                max_dev = max(max_dev, dev)

        if max_dev <= 0.01:
            return trajectory

        # 現在位置を t=0 の点として追加し、既存の点を ramp_time 分だけ後ろにずらす
        ramp_time = max(0.5, max_dev / 1.0)
        self.get_logger().warn(
            f'Trajectory start deviates from Unity state by {max_dev:.4f} rad. '
            f'Prepending current state as t=0 and shifting trajectory by {ramp_time:.2f}s.')

        p0 = JointTrajectoryPoint()
        p0.positions = [
            current_pos[name_to_idx[n]] if n in name_to_idx else 0.0
            for n in joint_names
        ]
        p0.velocities = [0.0] * len(joint_names)
        p0.accelerations = [0.0] * len(joint_names)
        p0.time_from_start = rclpy.duration.Duration(seconds=0.0).to_msg()

        new_points = [p0]
        for p in trajectory.points:
            shifted = JointTrajectoryPoint()
            shifted.positions = list(p.positions)
            shifted.velocities = list(p.velocities) if p.velocities else [0.0] * len(joint_names)
            shifted.accelerations = list(p.accelerations) if p.accelerations else [0.0] * len(joint_names)
            t = p.time_from_start.sec + p.time_from_start.nanosec * 1e-9 + ramp_time
            shifted.time_from_start = rclpy.duration.Duration(seconds=t).to_msg()
            new_points.append(shifted)

        trajectory.points = new_points
        return trajectory

    def execute_callback(self, goal_handle):
        self.get_logger().info('Executing trajectory...')
        trajectory = self._ensure_trajectory_from_current(goal_handle.request.trajectory)
        with self.trajectory_lock:
            self.active_trajectory = trajectory
            self.start_time = self.get_clock().now()

        last_point = self.active_trajectory.points[-1]
        last_point_time = last_point.time_from_start.sec + last_point.time_from_start.nanosec * 1e-9

        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                with self.trajectory_lock:
                    self.active_trajectory = None
                goal_handle.canceled()
                self.get_logger().info('Goal Canceled')
                return FollowJointTrajectory.Result()

            elapsed = (self.get_clock().now() - self.start_time).nanoseconds / 1e9
            if elapsed > last_point_time + 0.1:
                break
            time.sleep(0.05)

        with self.trajectory_lock:
            self.active_trajectory = None

        goal_handle.succeed()
        self.get_logger().info('Goal Succeeded')
        return FollowJointTrajectory.Result()

    def trajectory_timer_callback(self):
        """100 Hz: interpolate trajectory and publish joint commands to Unity."""
        with self.trajectory_lock:
            if self.active_trajectory is None or self.start_time is None:
                return
            if not self.__enable_flag:
                return

            now = self.get_clock().now()
            elapsed_time = (now - self.start_time).nanoseconds / 1e9

            points = self.active_trajectory.points
            joint_names = self.active_trajectory.joint_names
            target_positions = None

            if elapsed_time <= 0:
                target_positions = list(points[0].positions)
            elif elapsed_time >= (points[-1].time_from_start.sec +
                                  points[-1].time_from_start.nanosec * 1e-9):
                target_positions = list(points[-1].positions)
            else:
                for i in range(len(points) - 1):
                    t0 = points[i].time_from_start.sec + points[i].time_from_start.nanosec * 1e-9
                    t1 = points[i+1].time_from_start.sec + points[i+1].time_from_start.nanosec * 1e-9
                    if t0 <= elapsed_time < t1:
                        alpha = (elapsed_time - t0) / (t1 - t0)
                        target_positions = [
                            points[i].positions[j] + alpha * (points[i+1].positions[j] - points[i].positions[j])
                            for j in range(len(joint_names))
                        ]
                        break

            if target_positions is None:
                return

            traj_map = {name: target_positions[k] for k, name in enumerate(joint_names)}

            j1 = traj_map.get('joint1', self.current_joint_targets[0])
            j2 = traj_map.get('joint2', self.current_joint_targets[1])
            j3 = traj_map.get('joint3', self.current_joint_targets[2])
            j4 = traj_map.get('joint4', self.current_joint_targets[3])
            j5 = traj_map.get('joint5', self.current_joint_targets[4])
            j6 = traj_map.get('joint6', self.current_joint_targets[5])
            j7 = traj_map.get('joint7', self.current_joint_targets[6])

            self.current_joint_targets = [j1, j2, j3, j4, j5, j6, j7]

            # Publish joint targets to Unity (radians, no conversion needed)
            cmd = JointState()
            cmd.header.stamp = now.to_msg()
            cmd.name = self.all_joint_names
            cmd.position = [j1, j2, j3, j4, j5, j6, j7]
            self.unity_cmd_pub.publish(cmd)

    # --- Publish thread: forward Unity joint states to ROS standard topics ---
    def publish_thread(self):
        """50 Hz: read Unity joint feedback and publish to /joint_states etc."""
        rate = self.create_rate(50)

        # Unity sim: enable immediately without hardware handshake
        if self.auto_enable:
            self.__enable_flag = True
            self.get_logger().info('[Unity sim] auto_enable: enable_flag set immediately')

        while rclpy.ok():
            with self.unity_state_lock:
                positions = list(self.unity_joint_positions)
                velocities = list(self.unity_joint_velocities)
                efforts = list(self.unity_joint_efforts)

            stamp = self.get_clock().now().to_msg()

            js = JointState()
            js.header.stamp = stamp
            js.name = self.all_joint_names
            js.position = positions
            js.velocity = velocities
            js.effort = efforts

            # joint_states_single is remapped to /joint_states in launch file
            self.joint_pub.publish(js)
            self.joint_feedback_pub.publish(js)

            # joint_ctrl: echo back current targets (same shape as real node)
            jc = JointState()
            jc.header.stamp = stamp
            jc.name = self.all_joint_names
            jc.position = list(self.current_joint_targets)
            self.joint_ctrl_pub.publish(jc)

            # arm_status: dummy idle status (all zeros = no error)
            self.arm_status_pub.publish(PiperStatusMsg())

            # end_pose: zero (FK computation is out of scope)
            self.end_pose_pub.publish(Pose())
            ep_stamped = PoseStamped()
            ep_stamped.header.stamp = stamp
            self.end_pose_stamped_pub.publish(ep_stamped)

            rate.sleep()

    # --- Topic-based control callbacks (same interface as real node) ---
    def pos_callback(self, pos_data):
        """Cartesian position command — not supported in Unity sim (no IK bridge)."""
        self.get_logger().warn(
            'pos_cmd received: Cartesian control is not supported in Unity sim')

    def joint_callback(self, joint_data: JointState):
        """Direct joint command via topic — forward to Unity."""
        if not self.GetEnableFlag():
            return

        cmd = JointState()
        cmd.header.stamp = self.get_clock().now().to_msg()
        cmd.name = list(joint_data.name)
        cmd.position = list(joint_data.position)
        self.unity_cmd_pub.publish(cmd)

        # Update current targets for consistency with trajectory execution
        name_to_idx = {n: i for i, n in enumerate(self.all_joint_names)}
        for k, name in enumerate(joint_data.name):
            idx = name_to_idx.get(name)
            if idx is not None and k < len(joint_data.position):
                self.current_joint_targets[idx] = joint_data.position[k]

    def enable_callback(self, enable_flag: Bool):
        self.get_logger().info(f'[Unity sim] enable_flag: {enable_flag.data}')
        self.__enable_flag = enable_flag.data

    def handle_enable_service(self, req, resp):
        self.get_logger().info(f'[Unity sim] enable_srv: {req.enable_request}')
        self.__enable_flag = req.enable_request
        resp.enable_response = True
        return resp


def main(args=None):
    rclpy.init(args=args)
    node = PiperUnitySimNode()
    executor = MultiThreadedExecutor()
    try:
        rclpy.spin(node, executor=executor)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
