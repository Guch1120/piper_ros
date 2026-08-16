#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Integration test for Kobuki Unity Simulator Bridge (kobuki_unity_sim_node).

Tests:
  1. Forward kinematics: commands/velocity (Twist) -> /kobuki_unity/wheel_cmd (JointState)
  2. Odometry integration & TF: /kobuki_unity/wheel_states -> odom / joint_states / TF
  3. Odometry reset: commands/reset_odometry -> odom position reset to (0,0,0)
  4. Watchdog timer: cmd_vel timeout (0.6s) -> /kobuki_unity/wheel_cmd zeroed
"""

import math
import sys
import time
import unittest

import rclpy
from rclpy.node import Node
from rclpy.executors import SingleThreadedExecutor

from geometry_msgs.msg import Twist
from nav_msgs.msg import Odometry
from sensor_msgs.msg import JointState
from std_msgs.msg import Empty
import tf2_ros

from kobuki_unity.kobuki_unity_sim_node import KobukiUnitySimNode


class KobukiUnityIntegrationTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        rclpy.init()

    @classmethod
    def tearDownClass(cls):
        rclpy.shutdown()

    def setUp(self):
        self.node = KobukiUnitySimNode()
        self.test_helper = Node('test_helper_node')

        # Publishers to test the node
        self.cmd_vel_pub = self.test_helper.create_publisher(Twist, 'commands/velocity', 10)
        self.reset_odom_pub = self.test_helper.create_publisher(Empty, 'commands/reset_odometry', 10)
        self.sim_wheel_states_pub = self.test_helper.create_publisher(JointState, '/kobuki_unity/wheel_states', 10)

        # Subscribers to capture outputs from the node
        self.captured_wheel_cmds = []
        self.captured_odoms = []
        self.captured_joint_states = []

        self.test_helper.create_subscription(
            JointState, '/kobuki_unity/wheel_cmd', lambda m: self.captured_wheel_cmds.append(m), 10)
        self.test_helper.create_subscription(
            Odometry, 'odom', lambda m: self.captured_odoms.append(m), 10)
        self.test_helper.create_subscription(
            JointState, 'joint_states', lambda m: self.captured_joint_states.append(m), 10)

        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.node)
        self.executor.add_node(self.test_helper)
        self.spin_for(0.1)

    def tearDown(self):
        self.executor.shutdown()
        self.node.destroy_node()
        self.test_helper.destroy_node()

    def spin_for(self, duration_sec: float):
        end_time = time.time() + duration_sec
        while time.time() < end_time:
            self.executor.spin_once(timeout_sec=0.01)

    def test_01_velocity_to_wheel_cmd(self):
        """Test differential drive kinematics from Twist to wheel velocities."""
        vx = 0.2  # 0.2 m/s
        wz = 0.5  # 0.5 rad/s
        expected_vr = (2.0 * vx + wz * 0.23) / (2.0 * 0.035)
        expected_vl = (2.0 * vx - wz * 0.23) / (2.0 * 0.035)

        twist = Twist()
        twist.linear.x = vx
        twist.angular.z = wz

        for _ in range(5):
            self.cmd_vel_pub.publish(twist)
            self.spin_for(0.05)

        self.assertTrue(len(self.captured_wheel_cmds) > 0, "Should have received wheel_cmd")
        last_cmd = self.captured_wheel_cmds[-1]
        self.assertEqual(last_cmd.name, ['wheel_left_joint', 'wheel_right_joint'])

        vl = last_cmd.velocity[0]
        vr = last_cmd.velocity[1]
        self.assertAlmostEqual(vl, expected_vl, places=3)
        self.assertAlmostEqual(vr, expected_vr, places=3)
        print(f"[TEST 1 PASS] Kinematics: target vl={vl:.4f}, vr={vr:.4f} matched expected.")

    def test_02_wheel_states_to_odometry(self):
        """Test odometry integration from simulated wheel state updates."""
        # Initial sample at t=0
        js0 = JointState()
        js0.header.stamp = self.node.get_clock().now().to_msg()
        js0.name = ['wheel_left_joint', 'wheel_right_joint']
        js0.position = [0.0, 0.0]
        js0.velocity = [5.0, 5.0]
        self.sim_wheel_states_pub.publish(js0)
        self.spin_for(0.05)

        # Forward motion: rotate both wheels by 10 radians over 0.1s
        # ds = r * (dl + dr) / 2 = 0.035 * (10 + 10) / 2 = 0.35 m
        js1 = JointState()
        js1.header.stamp = self.node.get_clock().now().to_msg()
        js1.name = ['wheel_left_joint', 'wheel_right_joint']
        js1.position = [10.0, 10.0]
        js1.velocity = [5.0, 5.0]
        self.sim_wheel_states_pub.publish(js1)
        self.spin_for(0.1)

        self.assertTrue(len(self.captured_odoms) > 0, "Should have received odom")
        last_odom = self.captured_odoms[-1]
        self.assertAlmostEqual(last_odom.pose.pose.position.x, 0.35, places=2)
        self.assertAlmostEqual(last_odom.pose.pose.position.y, 0.0, places=2)
        print(f"[TEST 2 PASS] Odometry integration: x={last_odom.pose.pose.position.x:.4f} m matched 0.35 m.")

    def test_03_reset_odometry(self):
        """Test commands/reset_odometry resets pose back to origin."""
        # Drive forward first
        js0 = JointState()
        js0.name = ['wheel_left_joint', 'wheel_right_joint']
        js0.position = [0.0, 0.0]
        self.sim_wheel_states_pub.publish(js0)
        self.spin_for(0.05)

        js1 = JointState()
        js1.name = ['wheel_left_joint', 'wheel_right_joint']
        js1.position = [5.0, 5.0]
        self.sim_wheel_states_pub.publish(js1)
        self.spin_for(0.05)

        # Reset odometry
        for _ in range(3):
            self.reset_odom_pub.publish(Empty())
            self.spin_for(0.05)

        last_odom = self.captured_odoms[-1]
        self.assertAlmostEqual(last_odom.pose.pose.position.x, 0.0, places=3)
        self.assertAlmostEqual(last_odom.pose.pose.position.y, 0.0, places=3)
        print(f"[TEST 3 PASS] Reset odometry: pose successfully reset to 0.")

    def test_04_watchdog_timeout(self):
        """Test that if cmd_vel stops, wheel commands are zeroed after timeout."""
        twist = Twist()
        twist.linear.x = 0.3
        self.cmd_vel_pub.publish(twist)
        self.spin_for(0.05)

        # Wait longer than cmd_vel_timeout_sec (0.6s)
        self.spin_for(0.7)

        last_cmd = self.captured_wheel_cmds[-1]
        self.assertAlmostEqual(last_cmd.velocity[0], 0.0, places=4)
        self.assertAlmostEqual(last_cmd.velocity[1], 0.0, places=4)
        print(f"[TEST 4 PASS] Watchdog timer successfully stopped wheels after timeout.")


def main():
    suite = unittest.TestLoader().loadTestsFromTestCase(KobukiUnityIntegrationTest)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)


if __name__ == '__main__':
    main()
