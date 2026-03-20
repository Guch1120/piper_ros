#!/usr/bin/env python3
# -*-coding:utf8-*-
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from geometry_msgs.msg import Pose, PoseStamped, Point
from std_msgs.msg import Bool, String
from piper_msgs.msg import PiperStatusMsg, PosCmd
from piper_msgs.srv import Enable
import time
import threading
import math
import numpy as np
from scipy.spatial.transform import Rotation as R

# Piper SDK imports
from piper_sdk import *
from piper_sdk import C_PiperInterface
try:
    from piper_sdk.kinematics.piper_fk import C_PiperForwardKinematics
except ImportError:
    # Fallback if path is different (though verified in src)
    import sys
    import os
    sys.path.append(os.path.join(os.path.dirname(__file__), '../../../../piper_sdk'))
    from piper_sdk.kinematics.piper_fk import C_PiperForwardKinematics

class PiperVisualServoNode(Node):
    def __init__(self):
        super().__init__('piper_ctrl_single_visual_servo')
        
        # --- Parameters ---
        self.declare_parameter('can_port', 'can0')
        self.declare_parameter('auto_enable', False)
        self.declare_parameter('gripper_exist', True)
        self.declare_parameter('gripper_val_mutiple', 1)
        # Visual Servo Parameters
        self.declare_parameter('visual_servo_enable', True)
        self.declare_parameter('target_u', 320) # Center X (e.g. 640x480)
        self.declare_parameter('target_v', 240) # Center Y
        self.declare_parameter('gain_x', 0.0001) # Gain from pixel error to Robot X (m/pixel)
        self.declare_parameter('gain_y', 0.0001)
        self.declare_parameter('gain_z', 0.0)    # Usually 0 unless using size for depth

        self.can_port = self.get_parameter('can_port').value
        self.auto_enable = self.get_parameter('auto_enable').value
        self.gripper_exist = self.get_parameter('gripper_exist').value
        self.gripper_val_mutiple = self.get_parameter('gripper_val_mutiple').value
        
        self.vs_enable = self.get_parameter('visual_servo_enable').value
        self.target_u = self.get_parameter('target_u').value
        self.target_v = self.get_parameter('target_v').value
        # Gains
        self.kp_x = self.get_parameter('gain_x').value
        self.kp_y = self.get_parameter('gain_y').value

        # --- SDK Initialization ---
        self.piper = C_PiperInterface(can_name=self.can_port)
        self.piper.ConnectPort()
        self.fk = C_PiperForwardKinematics()

        # --- State ---
        self.__enable_flag = False
        self.active_trajectory = None
        self.start_time = None
        self.trajectory_lock = threading.Lock()
        
        # Current Tracking Info
        self.current_uv = None
        self.last_track_time = 0.0
        self.visual_servo_offset = np.array([0.0, 0.0, 0.0]) # x, y, z (meters)
        self.debug_accumulated_offset = np.array([0.0, 0.0, 0.0]) # Debug integration

        # --- Publishers/Subscribers ---
        self.joint_pub = self.create_publisher(JointState, 'joint_states_single', 1)
        self.joint_feedback_pub = self.create_publisher(JointState, 'joint_states_feedback', 1)
        self.end_pose_pub = self.create_publisher(Pose, 'end_pose', 1)
        self.arm_status_pub = self.create_publisher(PiperStatusMsg, 'arm_status', 1)
        
        # Sam3 Result Subscriber
        self.create_subscription(Point, '/sam3/track_result', self.track_cb, 1)

        # Debug Keyword Subscriber
        self.create_subscription(String, '/debug/keyboard_cmd', self.debug_cb, 10)
        
        # Action Server
        self._action_cb_group = ReentrantCallbackGroup()
        self._action_server = ActionServer(
            self, FollowJointTrajectory, 'arm_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback, 
            cancel_callback=self.cancel_callback, callback_group=self._action_cb_group
        )
        
        # Timer for Trajectory Execution (100Hz)
        self.trajectory_timer = self.create_timer(0.01, self.trajectory_timer_callback, callback_group=self._action_cb_group)
        
        # Publish Thread
        self.pub_thread = threading.Thread(target=self.publish_loop, daemon=True)
        self.pub_thread.start()

    def debug_cb(self, msg):
        """Inject offset based on keyboard command"""
        cmd = msg.data.lower().strip()
        step = 0.005 # 5mm per key press
        
        # Mapping WASD to Robot X/Y (assuming X=Forward, Y=Left)
        # Needs to match user's perspective
        if cmd == 'w':
            self.debug_accumulated_offset[0] += step # +X
            self.get_logger().info("Debug: OFFSET X+ (Forward)")
        elif cmd == 's':
            self.debug_accumulated_offset[0] -= step # -X
            self.get_logger().info("Debug: OFFSET X- (Back)")
        elif cmd == 'a':
            self.debug_accumulated_offset[1] += step # +Y (Left)
            self.get_logger().info("Debug: OFFSET Y+ (Left)")
        elif cmd == 'd':
            self.debug_accumulated_offset[1] -= step # -Y (Right)
            self.get_logger().info("Debug: OFFSET Y- (Right)")
        elif cmd == 'r':
            self.debug_accumulated_offset[:] = 0.0 # Reset
            self.get_logger().info("Debug: OFFSET RESET")

    def track_cb(self, msg: Point):
        """Update current tracking target from SAM3"""
        self.current_uv = (msg.x, msg.y)
        self.last_track_time = time.time()

    def goal_callback(self, goal_request):
        self.get_logger().info('Received Goal')
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info('Canceled Goal')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        self.get_logger().info('Executing...')
        with self.trajectory_lock:
            self.active_trajectory = goal_handle.request.trajectory
            self.start_time = self.get_clock().now()
            # Reset visual servo offsets?
            # Keeping debug offset across goals might be useful for testing, but typically reset.
            # self.visual_servo_offset = np.array([0.0, 0.0, 0.0])
            # self.debug_accumulated_offset = np.array([0.0, 0.0, 0.0]) 

        last_time = self.active_trajectory.points[-1].time_from_start.sec + \
                    self.active_trajectory.points[-1].time_from_start.nanosec * 1e-9
        
        # Wait loop (logic handled in timer, this just keeps action alive)
        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                with self.trajectory_lock:
                    self.active_trajectory = None
                goal_handle.canceled()
                return FollowJointTrajectory.Result()
            
            now = self.get_clock().now()
            elapsed = (now - self.start_time).nanoseconds / 1e9
            
            if elapsed > last_time + 0.5: # +0.5s margin
                break
            time.sleep(0.1)

        with self.trajectory_lock:
            self.active_trajectory = None
        
        goal_handle.succeed()
        return FollowJointTrajectory.Result()

    def trajectory_timer_callback(self):
        with self.trajectory_lock:
            if self.active_trajectory is None or self.start_time is None:
                return

        if not self.__enable_flag:
            return

        now = self.get_clock().now()
        elapsed = (now - self.start_time).nanoseconds / 1e9
        
        points = self.active_trajectory.points
        # 1. Interpolate Joint Position
        current_pt_idx = 0
        for i in range(len(points)-1):
            t1 = points[i+1].time_from_start.sec + points[i+1].time_from_start.nanosec*1e-9
            if elapsed < t1:
                current_pt_idx = i
                break
        else:
            current_pt_idx = len(points) - 2
        
        if current_pt_idx < 0: current_pt_idx = 0

        p0 = points[current_pt_idx]
        p1 = points[current_pt_idx+1]
        t0 = p0.time_from_start.sec + p0.time_from_start.nanosec*1e-9
        t1 = p1.time_from_start.sec + p1.time_from_start.nanosec*1e-9
        
        alpha = 0.0
        if t1 > t0:
            alpha = (elapsed - t0) / (t1 - t0)
        alpha = max(0.0, min(1.0, alpha))
        
        # Map joints
        target_joints_rad = [0.0]*6
        joint_names = self.active_trajectory.joint_names
        
        piper_joints = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6']
        gripper_pos = 0.0
        
        for idx, name in enumerate(joint_names):
            val = p0.positions[idx] + alpha*(p1.positions[idx] - p0.positions[idx])
            if name == 'joint7': # Gripper
                gripper_pos = val
            elif name in piper_joints:
                j_idx = int(name[-1]) - 1 # joint1->0
                if 0 <= j_idx < 6:
                    target_joints_rad[j_idx] = val

        # 2. Forward Kinematics -> Reference Pose (Cartesian)
        fk_res = self.fk.CalFK(target_joints_rad)
        ref_pose = fk_res[5] # Link 6
        ref_xyz_m = np.array(ref_pose[:3]) / 1000.0 # mm -> m
        ref_rpy_deg = np.array(ref_pose[3:])
        
        # 3. Visual Servo Correction
        # Combine real visual servo + debug override
        
        # A. Debug Integration
        # B. Real VS Integration (if enabled)
        if self.vs_enable and self.current_uv is not None:
            if time.time() - self.last_track_time < 0.5:
                du = self.target_u - self.current_uv[0]
                dv = self.target_v - self.current_uv[1]
                step_x = self.kp_x * dv
                step_y = self.kp_y * du 
                self.visual_servo_offset[0] += step_x
                self.visual_servo_offset[1] += step_y
                self.visual_servo_offset = np.clip(self.visual_servo_offset, -0.05, 0.05)
        
        # Combine all offsets
        # Total Offset = PID_VS_Offset + Debug_Keyboard_Offset
        total_offset = self.visual_servo_offset + self.debug_accumulated_offset
        
        # 4. Final Target
        final_xyz_m = ref_xyz_m + total_offset
        
        # Caps for safety (don't go too far from plan)
        # In production maybe clamp distance(final, reference) < 0.1m
        
        cmd_x = int(final_xyz_m[0] * 1_000_000)
        cmd_y = int(final_xyz_m[1] * 1_000_000)
        cmd_z = int(final_xyz_m[2] * 1_000_000)
        
        cmd_rx = int(ref_rpy_deg[0] * 1000)
        cmd_ry = int(ref_rpy_deg[1] * 1000)
        cmd_rz = int(ref_rpy_deg[2] * 1000)
        
        # 5. Send Command
        self.piper.MotionCtrl_2(0x01, 0x01, 100)
        self.piper.EndPoseCtrl(cmd_x, cmd_y, cmd_z, cmd_rx, cmd_ry, cmd_rz)
        
        # Gripper
        g_val = int(abs(gripper_pos) * 1_000_000 * self.gripper_val_mutiple)
        if self.gripper_exist:
            self.piper.GripperCtrl(g_val, 1000, 0x01, 0)

    def publish_loop(self):
        """Maintains connection and publishes status"""
        rate = self.create_rate(50)
        while rclpy.ok():
            if self.auto_enable and not self.__enable_flag:
                self.piper.EnableArm(7)
                self.piper.GripperCtrl(0,1000,0x01,0)
                self.__enable_flag = True
            
            if self.piper.isOk():
                self.publish_arm_state()
            rate.sleep()

    def publish_arm_state(self):
        pass

def main():
    rclpy.init()
    node = PiperVisualServoNode()
    executor = MultiThreadedExecutor()
    rclpy.spin(node, executor=executor)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
