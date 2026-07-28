#!/usr/bin/env python3
# -*-coding:utf8-*-
"""Unity simulator bridge for the Kobuki mobile base ("kochaka" = Kobuki + Kachaka shelf).

Mirrors the exact same external ROS2 interface as the real hardware driver
(oit_kobuki_ws-main/src/kobuki_ros/kobuki_node), but replaces the physical
serial link to the Kobuki base with a Unity ArticulationBody/WheelCollider
bridge (topics under /kobuki_unity/...). The only difference from the real
robot should be *where the commands ultimately go* (Unity vs. real hardware) -
topic names, types, QoS, parameter names/defaults and control-loop behaviour
(cmd_vel watchdog, odometry kinematics) are kept identical on purpose.

External-facing ROS2 interface (identical to real kobuki_node, no remap needed):
    Subscribe  commands/velocity   (geometry_msgs/msg/Twist)      QoS depth 10
    Publish    odom                (nav_msgs/msg/Odometry)        queue 50
    Publish    joint_states        (sensor_msgs/msg/JointState)   queue 100
    TF         <odom_frame> -> <base_frame>  (only if publish_tf:=true)

Parameters (defaults mirror
oit_kobuki_ws-main/src/kobuki_ros/kobuki_node/config/kobuki_node_params.yaml):
    cmd_vel_timeout_sec    : 0.6              watchdog: zero wheel cmds if no
                                               commands/velocity for this long
    odom_frame             : 'odom'
    base_frame             : 'base_footprint'
    publish_tf             : True
    wheel_left_joint_name  : 'wheel_left_joint'
    wheel_right_joint_name : 'wheel_right_joint'

Physical constants (from oit_kobuki_ws-main/src/kobuki_core/src/driver/diff_drive.cpp,
class DiffDrive's default member initializers - not exposed as ROS parameters on the
real robot, exposed here as parameters purely for convenience/testability):
    wheel_radius      : 0.035  [m]
    wheel_separation  : 0.23   [m]  ("bias"/wheelbase in diff_drive.cpp)

Unity bridge topics (internal only; the Unity-side C# implementation is out of
scope for this ROS2 package - see the module docstring at the bottom of this
file / the task report for the exact spec Unity needs to satisfy):
    Publish    /kobuki_unity/wheel_cmd     (sensor_msgs/msg/JointState, velocity only)
    Subscribe  /kobuki_unity/wheel_states  (sensor_msgs/msg/JointState, position + velocity)

Note on heading source: the real robot defaults to use_imu_heading:=true (gyro
overrides the wheel-differential heading estimate, see kobuki_node/src/kobuki_ros.cpp
and odometry.cpp). This Unity bridge has no IMU/gyro topic in scope, so heading is
always derived from wheel-differential integration only - equivalent to running the
real node with use_imu_heading:=false. This is the one intentional behavioural
difference from the real robot's default configuration.
"""

import math
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile
from geometry_msgs.msg import Twist, TransformStamped
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from tf2_ros import TransformBroadcaster


class KobukiUnitySimNode(Node):
    """ROS2 node that mirrors the real kobuki_node hardware interface but drives Unity."""

    def __init__(self) -> None:
        # Same node name as the real hardware driver (rclcpp::Node("kobuki", ...)
        # in kobuki_node/src/kobuki_ros.cpp) so this node is a drop-in replacement.
        super().__init__('kobuki')

        # --- Parameters (mirror kobuki_node_params.yaml) ---
        self.declare_parameter('cmd_vel_timeout_sec', 0.6)
        self.declare_parameter('odom_frame', 'odom')
        self.declare_parameter('base_frame', 'base_footprint')
        self.declare_parameter('publish_tf', True)
        self.declare_parameter('wheel_left_joint_name', 'wheel_left_joint')
        self.declare_parameter('wheel_right_joint_name', 'wheel_right_joint')
        # Physical constants: kobuki_core diff_drive.cpp DiffDrive::DiffDrive()
        self.declare_parameter('wheel_radius', 0.035)      # [m]
        self.declare_parameter('wheel_separation', 0.23)   # [m] ("bias" in diff_drive.cpp)
        # 20 Hz control-loop / watchdog rate. The real driver's equivalent
        # watchdog timer (KobukiRos::update()) runs at 100 ms (10 Hz); the
        # exact rate is an implementation detail, only the 0.6 s timeout
        # duration needs to match.
        self.declare_parameter('control_rate_hz', 20.0)

        self.cmd_vel_timeout_sec = float(self.get_parameter('cmd_vel_timeout_sec').value)
        self.odom_frame = str(self.get_parameter('odom_frame').value)
        self.base_frame = str(self.get_parameter('base_frame').value)
        self.publish_tf_enabled = bool(self.get_parameter('publish_tf').value)
        self.wheel_left_joint_name = str(self.get_parameter('wheel_left_joint_name').value)
        self.wheel_right_joint_name = str(self.get_parameter('wheel_right_joint_name').value)
        self.wheel_radius = float(self.get_parameter('wheel_radius').value)
        self.wheel_separation = float(self.get_parameter('wheel_separation').value)
        control_rate_hz = float(self.get_parameter('control_rate_hz').value)

        self.get_logger().info(
            f"[Unity sim] cmd_vel_timeout_sec={self.cmd_vel_timeout_sec}, "
            f"odom_frame={self.odom_frame}, base_frame={self.base_frame}, "
            f"publish_tf={self.publish_tf_enabled}, "
            f"wheel_radius={self.wheel_radius}, wheel_separation={self.wheel_separation}")

        # --- cmd_vel state (protected by lock; control timer reads/zeros it) ---
        self._cmd_lock = threading.Lock()
        self._cmd_vx = 0.0
        self._cmd_wz = 0.0
        self._last_cmd_time = self.get_clock().now()
        self._cmd_timed_out = False  # for one-shot warning log, mirrors real node

        # --- Odometry integration state ---
        self._odom_lock = threading.Lock()
        self._pose_x = 0.0
        self._pose_y = 0.0
        self._pose_theta = 0.0
        self._prev_wheel_left_pos = None
        self._prev_wheel_right_pos = None
        self._prev_wheel_time = None

        # --- Publishers: identical external interface to real hardware ---
        self.odom_pub = self.create_publisher(Odometry, 'odom', 50)
        self.joint_state_pub = self.create_publisher(JointState, 'joint_states', 100)

        # --- Subscriber: identical external interface to real hardware ---
        self.create_subscription(
            Twist, 'commands/velocity', self._cmd_vel_callback, QoSProfile(depth=10))

        # --- Unity bridge publisher/subscriber (internal, not part of the real HW interface) ---
        self.wheel_cmd_pub = self.create_publisher(JointState, '/kobuki_unity/wheel_cmd', 10)
        self.create_subscription(
            JointState, '/kobuki_unity/wheel_states', self._wheel_states_callback, 10)

        self.tf_broadcaster = TransformBroadcaster(self)

        self.create_timer(1.0 / control_rate_hz, self._control_timer_callback)

    # ------------------------------------------------------------------
    # commands/velocity (identical topic/type/QoS to real kobuki_node)
    # ------------------------------------------------------------------
    def _cmd_vel_callback(self, msg: Twist) -> None:
        with self._cmd_lock:
            self._cmd_vx = msg.linear.x
            self._cmd_wz = msg.angular.z
            self._last_cmd_time = self.get_clock().now()
            self._cmd_timed_out = False

    def _control_timer_callback(self) -> None:
        """Apply the cmd_vel watchdog and forward wheel velocity targets to Unity.

        Mirrors KobukiRos::update() in kobuki_ros.cpp: if commands/velocity hasn't
        been received for more than cmd_vel_timeout_sec, zero the wheel velocities
        and log a one-shot warning (repeated exactly once per timeout episode).
        """
        now = self.get_clock().now()
        with self._cmd_lock:
            elapsed = (now - self._last_cmd_time).nanoseconds / 1e9
            timed_out = elapsed > self.cmd_vel_timeout_sec
            if timed_out:
                if not self._cmd_timed_out:
                    self.get_logger().warn(
                        "Incoming velocity commands not received for more than "
                        f"{self.cmd_vel_timeout_sec:.2f} seconds -> zero'ing velocity commands")
                    self._cmd_timed_out = True
                vx, wz = 0.0, 0.0
            else:
                vx, wz = self._cmd_vx, self._cmd_wz

        # Differential-drive kinematics (kobuki_core diff_drive.cpp
        # DifferentialDriveKinematics::baseToWheelVelocities):
        #   right = (2*v + w*L) / (2*R) ; left = (2*v - w*L) / (2*R)
        r = self.wheel_radius
        wheel_base = self.wheel_separation
        wheel_right_vel = (2.0 * vx + wz * wheel_base) / (2.0 * r)
        wheel_left_vel = (2.0 * vx - wz * wheel_base) / (2.0 * r)

        cmd = JointState()
        cmd.header.stamp = now.to_msg()
        cmd.name = [self.wheel_left_joint_name, self.wheel_right_joint_name]
        cmd.velocity = [wheel_left_vel, wheel_right_vel]
        self.wheel_cmd_pub.publish(cmd)

    # ------------------------------------------------------------------
    # /kobuki_unity/wheel_states <- Unity (actual simulated wheel motion)
    # ------------------------------------------------------------------
    def _wheel_states_callback(self, msg: JointState) -> None:
        name_to_idx = {n: i for i, n in enumerate(msg.name)}
        li = name_to_idx.get(self.wheel_left_joint_name)
        ri = name_to_idx.get(self.wheel_right_joint_name)
        if li is None or ri is None:
            self.get_logger().warn(
                f"/kobuki_unity/wheel_states missing '{self.wheel_left_joint_name}' or "
                f"'{self.wheel_right_joint_name}' in JointState.name; ignoring message")
            return

        left_pos = msg.position[li] if li < len(msg.position) else 0.0
        right_pos = msg.position[ri] if ri < len(msg.position) else 0.0
        left_vel = msg.velocity[li] if li < len(msg.velocity) else 0.0
        right_vel = msg.velocity[ri] if ri < len(msg.velocity) else 0.0

        now = self.get_clock().now()
        stamp = now.to_msg()

        # joint_states: forward Unity's actual wheel state as-is
        # (identical topic name/type to real hardware).
        js = JointState()
        js.header.stamp = stamp
        js.name = [self.wheel_left_joint_name, self.wheel_right_joint_name]
        js.position = [left_pos, right_pos]
        js.velocity = [left_vel, right_vel]
        self.joint_state_pub.publish(js)

        # Odometry integration - same formulas as kobuki_node odometry.cpp /
        # ecl::mobile_robot::DifferentialDriveKinematics:
        #   ds     = R * (dl + dr) / 2
        #   dtheta = R * (dr - dl) / L
        #   x     += ds * cos(theta)   (uses the *previous* heading, matching
        #   y     += ds * sin(theta)    ecl::extend_pose's Euler-style update)
        #   theta  = wrap(theta + dtheta)
        with self._odom_lock:
            if self._prev_wheel_left_pos is None:
                # First sample: nothing to differentiate yet.
                self._prev_wheel_left_pos = left_pos
                self._prev_wheel_right_pos = right_pos
                self._prev_wheel_time = now
                return

            dt = (now - self._prev_wheel_time).nanoseconds / 1e9
            dl = left_pos - self._prev_wheel_left_pos
            dr = right_pos - self._prev_wheel_right_pos
            self._prev_wheel_left_pos = left_pos
            self._prev_wheel_right_pos = right_pos
            self._prev_wheel_time = now

            if dt <= 0.0:
                return

            r = self.wheel_radius
            wheel_base = self.wheel_separation
            ds = r * (dl + dr) / 2.0
            dtheta = r * (dr - dl) / wheel_base

            theta_prev = self._pose_theta
            self._pose_x += ds * math.cos(theta_prev)
            self._pose_y += ds * math.sin(theta_prev)
            self._pose_theta = self._wrap_angle(theta_prev + dtheta)

            x, y, theta = self._pose_x, self._pose_y, self._pose_theta
            vx = ds / dt
            wz = dtheta / dt

        # Yaw-only quaternion (roll = pitch = 0, matches tf2::Quaternion::setRPY(0,0,theta)).
        qz = math.sin(theta / 2.0)
        qw = math.cos(theta / 2.0)

        odom = Odometry()
        odom.header.stamp = stamp
        odom.header.frame_id = self.odom_frame
        odom.child_frame_id = self.base_frame
        odom.pose.pose.position.x = x
        odom.pose.pose.position.y = y
        odom.pose.pose.position.z = 0.0
        odom.pose.pose.orientation.z = qz
        odom.pose.pose.orientation.w = qw
        odom.twist.twist.linear.x = vx
        odom.twist.twist.angular.z = wz
        # Pose covariance mirrors kobuki_node odometry.cpp Odometry::getOdometry().
        # Yaw covariance uses the use_imu_heading:=false branch (0.2) since this
        # Unity bridge has no IMU input (see module docstring NOTE above).
        odom.pose.covariance[0] = 0.1
        odom.pose.covariance[7] = 0.1
        odom.pose.covariance[35] = 0.2
        odom.pose.covariance[14] = 1e10
        odom.pose.covariance[21] = 1e10
        odom.pose.covariance[28] = 1e10
        self.odom_pub.publish(odom)

        if self.publish_tf_enabled:
            t = TransformStamped()
            t.header.stamp = stamp
            t.header.frame_id = self.odom_frame
            t.child_frame_id = self.base_frame
            t.transform.translation.x = x
            t.transform.translation.y = y
            t.transform.translation.z = 0.0
            t.transform.rotation.z = qz
            t.transform.rotation.w = qw
            self.tf_broadcaster.sendTransform(t)

    @staticmethod
    def _wrap_angle(angle: float) -> float:
        return math.atan2(math.sin(angle), math.cos(angle))


def main(args=None):
    rclpy.init(args=args)
    node = KobukiUnitySimNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
