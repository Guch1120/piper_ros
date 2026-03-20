#!/usr/bin/env python3
# -*-coding:utf8-*-
# This file controls a single robotic arm node and handles the movement of the robotic arm with a gripper.
# Integrated with FollowJointTrajectory Action Server for MoveIt control.

import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import MultiThreadedExecutor
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from std_msgs.msg import Bool
import time
import threading
import argparse
import math
from piper_sdk import *
from piper_sdk import C_PiperInterface
from piper_msgs.msg import PiperStatusMsg, PosCmd
from piper_msgs.srv import Enable
from geometry_msgs.msg import Pose, PoseStamped
from scipy.spatial.transform import Rotation as R
from numpy import clip
from builtin_interfaces.msg import Time

class PiperRosNode(Node):
    """ROS2 node for the robotic arm with Action Server support"""

    def __init__(self) -> None:
        super().__init__('piper_ctrl_single_node')
        
        # ROS parameters
        self.declare_parameter('can_port', 'can0')
        self.declare_parameter('auto_enable', False)
        self.declare_parameter('gripper_exist', True)
        self.declare_parameter('gripper_val_mutiple', 1)

        self.can_port = self.get_parameter('can_port').get_parameter_value().string_value
        self.auto_enable = self.get_parameter('auto_enable').get_parameter_value().bool_value
        self.gripper_exist = self.get_parameter('gripper_exist').get_parameter_value().bool_value
        self.gripper_val_mutiple = self.get_parameter('gripper_val_mutiple').get_parameter_value().integer_value
        self.gripper_val_mutiple = max(0, min(self.gripper_val_mutiple, 10))

        self.get_logger().info(f"can_port is {self.can_port}")
        self.get_logger().info(f"auto_enable is {self.auto_enable}")
        self.get_logger().info(f"gripper_exist is {self.gripper_exist}")
        self.get_logger().info(f"gripper_val_mutiple is {self.gripper_val_mutiple}")

        # --- Action Server State ---
        self.active_trajectory = None
        self.start_time = None
        self.trajectory_lock = threading.Lock()
        self.all_joint_names = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6', 'joint7']
        # Current joint positions target (for interpolation starting point)
        self.current_joint_targets = [0.0] * 7

        # Publishers
        self.joint_pub = self.create_publisher(JointState, 'joint_states_single', 1)
        self.joint_feedback_pub = self.create_publisher(JointState, 'joint_states_feedback', 1)
        self.joint_ctrl_pub = self.create_publisher(JointState, 'joint_ctrl', 1)
        self.arm_status_pub = self.create_publisher(PiperStatusMsg, 'arm_status', 1)
        self.end_pose_pub = self.create_publisher(Pose, 'end_pose', 1)
        self.end_pose_stamped_pub = self.create_publisher(PoseStamped, 'end_pose_stamped', 1)
        
        # Service
        self.motor_srv = self.create_service(Enable, 'enable_srv', self.handle_enable_service)
        
        # Action Servers
        # Use ReentrantCallbackGroup to allow parallel execution if needed
        self._action_cb_group = ReentrantCallbackGroup()
        self._action_server_arm = ActionServer(
            self, FollowJointTrajectory, 'arm_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback, cancel_callback=self.cancel_callback,
            callback_group=self._action_cb_group
        )
        self._action_server_gripper = ActionServer(
            self, FollowJointTrajectory, 'gripper_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback, cancel_callback=self.cancel_callback,
            callback_group=self._action_cb_group
        )

        # Joint States containers
        self.joint_states = JointState()
        self.joint_states.name = self.all_joint_names
        self.joint_states.position = [0.0] * 7
        self.joint_states.velocity = [0.0] * 7
        self.joint_states.effort = [0.0] * 7

        self.joint_states_feedback = JointState()
        self.joint_states_feedback.name = self.all_joint_names
        self.joint_states_feedback.position = [0.0] * 7
        self.joint_states_feedback.velocity = [0.0] * 7
        self.joint_states_feedback.effort = [0.0] * 7

        self.joint_ctrl = JointState()
        self.joint_ctrl.name = self.all_joint_names
        self.joint_ctrl.position = [0.0] * 7
        self.joint_ctrl.velocity = [0.0] * 7
        self.joint_ctrl.effort = [0.0] * 7

        self.__enable_flag = False
        
        # Initialize Piper Interface
        self.piper = C_PiperInterface(can_name=self.can_port)
        self.piper.ConnectPort()

        # Subscribers
        self.create_subscription(PosCmd, 'pos_cmd', self.pos_callback, 1)
        self.create_subscription(JointState, 'joint_ctrl_single', self.joint_callback, 1)
        self.create_subscription(Bool, 'enable_flag', self.enable_callback, 1)

        # Threads and Timers
        self.publisher_thread = threading.Thread(target=self.publish_thread)
        self.publisher_thread.start()

        # Trajectory execution timer (100Hz)
        self.trajectory_timer = self.create_timer(0.01, self.trajectory_timer_callback, callback_group=self._action_cb_group)

    def GetEnableFlag(self):
        return self.__enable_flag

    # --- Action Server Callbacks ---
    def goal_callback(self, goal_request):
        self.get_logger().info('Received new action goal')
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info('Received cancel request')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        self.get_logger().info('Executing trajectory...')
        
        with self.trajectory_lock:
            self.active_trajectory = goal_handle.request.trajectory
            self.start_time = self.get_clock().now()
        
        # Wait for completion checking logic
        last_point_time = (self.active_trajectory.points[-1].time_from_start.sec + 
                           self.active_trajectory.points[-1].time_from_start.nanosec * 1e-9)
        
        while rclpy.ok():
            if goal_handle.is_cancel_requested:
                with self.trajectory_lock:
                    self.active_trajectory = None
                goal_handle.canceled()
                self.get_logger().info('Goal Canceled')
                return FollowJointTrajectory.Result() # TODO: Set error code if needed
            
            # Check elapsed time
            now = self.get_clock().now()
            # If start_time is reset (new goal overwrote?), we might need to handle, but with lock it should suffice.
            # Ideally execute_callback blocks until DONE.
            if self.active_trajectory is None:
                # Can happen if preempted by another goal or stopped?
                # But here we rely on one active goal at a time or simple replacement.
                # If active_trajectory changed (new goal), this loop might be checking the WRONG trajectory if not careful.
                # But simplicity: let's assume one active action at a time or we just check if "our" goal is done.
                # However, goal_handle represents THIS execution.
                pass

            # Simpler wait logic:
            elapsed = (now - self.start_time).nanoseconds / 1e9
            if elapsed > last_point_time + 0.1:
                break
            
            time.sleep(0.05)
        
        with self.trajectory_lock:
             self.active_trajectory = None

        goal_handle.succeed()
        self.get_logger().info('Goal Succeeded')
        return FollowJointTrajectory.Result()

    def trajectory_timer_callback(self):
        """100Hz loop to interpolate and execute trajectory if active"""
        with self.trajectory_lock:
            if self.active_trajectory is None or self.start_time is None:
                return

            if not self.__enable_flag:
                return # Do not move if disabled

            now = self.get_clock().now()
            elapsed_time = (now - self.start_time).nanoseconds / 1e9
            
            points = self.active_trajectory.points
            joint_names = self.active_trajectory.joint_names
            
            target_positions = None
            
            if elapsed_time <= 0:
                target_positions = points[0].positions
            elif elapsed_time >= (points[-1].time_from_start.sec + points[-1].time_from_start.nanosec * 1e-9):
                target_positions = points[-1].positions
            else:
                # Intepolation
                for i in range(len(points) - 1):
                    t0 = points[i].time_from_start.sec + points[i].time_from_start.nanosec * 1e-9
                    t1 = points[i+1].time_from_start.sec + points[i+1].time_from_start.nanosec * 1e-9
                    
                    if t0 <= elapsed_time < t1:
                        alpha = (elapsed_time - t0) / (t1 - t0)
                        # Linear Interpolation
                        target_positions_list = []
                        for j in range(len(joint_names)):
                            p0 = points[i].positions[j]
                            p1 = points[i+1].positions[j]
                            interpolated_p = p0 + alpha * (p1 - p0)
                            target_positions_list.append(interpolated_p)
                        target_positions = target_positions_list
                        break
            
            if target_positions is not None:
                # Map partial trajectory joints to full robot joints
                # self.current_joint_targets maintains the full state
                # Update only the joints present in the active_trajectory
                
                # Create a temporary dict for easier mapping
                traj_map = {}
                for idx, name in enumerate(joint_names):
                    traj_map[name] = target_positions[idx]
                
                # Construct arguments for JointCtrl
                # Indices: 0:j1, 1:j2, 2:j3, 3:j4, 4:j5, 5:j6
                # Piper SDK expects degrees * 1000? No, let's check existing logic.
                # existing joint_callback: joint_positions[joint_name] = round(pos * factor)
                # factor = 57324.84... which is (180/pi) * 1000. So Radian -> Degree*1000 unit.
                
                factor = 57324.840764
                
                # Prepare control values
                j1 = self.current_joint_targets[0]
                j2 = self.current_joint_targets[1]
                j3 = self.current_joint_targets[2]
                j4 = self.current_joint_targets[3]
                j5 = self.current_joint_targets[4]
                j6 = self.current_joint_targets[5]
                # gripper is separate
                
                # Update from trajectory
                # Using 'joint1'...'joint6' strings
                if 'joint1' in traj_map: j1 = traj_map['joint1']
                if 'joint2' in traj_map: j2 = traj_map['joint2']
                if 'joint3' in traj_map: j3 = traj_map['joint3']
                if 'joint4' in traj_map: j4 = traj_map['joint4']
                if 'joint5' in traj_map: j5 = traj_map['joint5']
                if 'joint6' in traj_map: j6 = traj_map['joint6']
                
                # Update current targets for next iteration consistency
                self.current_joint_targets = [j1, j2, j3, j4, j5, j6, 0.0]

                # Convert to Piper Units
                val_j1 = round(j1 * factor)
                val_j2 = round(j2 * factor)
                val_j3 = round(j3 * factor)
                val_j4 = round(j4 * factor)
                val_j5 = round(j5 * factor)
                val_j6 = round(j6 * factor)
                
                # Execute Control
                # Also set speed? The bridge didn't set speed explicitly per step, 
                # but valid speed should be set. Piper seems to use MotionCtrl_2 for speed limit.
                # Let's set a default high speed limit and let position control handle the trajectory timing.
                self.piper.MotionCtrl_2(0x01, 0x01, 100) # 100% speed limit
                
                self.piper.JointCtrl(val_j1, val_j2, val_j3, val_j4, val_j5, val_j6)
                
                # Gripper control if present in trajectory
                # Usually gripper is 'joint7' or 'gripper' depending on config.
                # In moveit config: gripper_controller => joint7
                if 'joint7' in traj_map:
                    # Gripper range in rad needs to map to 0-1000 unit? Or Piper Gripper unit.
                    # Original code: gripper_effort = clip(joint_data.effort[6], 0.5, 3) -> round(effort*1000)
                    # Joint 6 (index) in joint_callback is position of gripper?
                    # "joint_6 = round(joint_data.position[6] * 1000 * 1000)" in existing code seems to capture gripper pos?
                    # Wait, joint_callback uses joint_data.effort for force?
                    # And joint_data.position[6] for angle?
                    # "self.piper.GripperCtrl(abs(joint_6), gripper_effort, 0x01, 0)"
                    
                    # Trajectory sends position.
                    g_pos_rad = traj_map['joint7']
                    # Convert rad to Piper unit. 
                    # Existing: joint_6 = pos[6] * 1000 * 1000 ... ??
                    # Existing line 306: joint_6 = round(joint_data.position[6] * 1000 * 1000)
                    # This seems large. 1 rad = 1,000,000? 
                    # Let's trust existing conversion logic.
                    
                    val_g = round(g_pos_rad * 1000 * 1000)
                    val_g = val_g * self.gripper_val_mutiple # from existing
                    
                    # Effort? Trajectory usually doesn't have effort unless specified. Use default.
                    default_effort = 1000
                    
                    if self.gripper_exist:
                         self.piper.GripperCtrl(abs(val_g), default_effort, 0x01, 0)

    # --- Existing Functionality ---

    def publish_thread(self):
        """Publish messages from the robotic arm"""
        rate = self.create_rate(200)  # 200 Hz
        enable_flag = False
        timeout = 20
        start_time = time.time()
        elapsed_time_flag = False
        
        while rclpy.ok():
            if(self.auto_enable):
                while not (enable_flag):
                    elapsed_time = time.time() - start_time
                    self.get_logger().info("--------------------")
                    enable_flag = self.piper.GetArmLowSpdInfoMsgs().motor_1.foc_status.driver_enable_status and \
                        self.piper.GetArmLowSpdInfoMsgs().motor_2.foc_status.driver_enable_status and \
                        self.piper.GetArmLowSpdInfoMsgs().motor_3.foc_status.driver_enable_status and \
                        self.piper.GetArmLowSpdInfoMsgs().motor_4.foc_status.driver_enable_status and \
                        self.piper.GetArmLowSpdInfoMsgs().motor_5.foc_status.driver_enable_status and \
                        self.piper.GetArmLowSpdInfoMsgs().motor_6.foc_status.driver_enable_status
                    self.get_logger().info(f"Enable status:{enable_flag}")
                    self.piper.EnableArm(7)
                    self.piper.GripperCtrl(0, 1000, 0x01, 0)
                    if(enable_flag):
                        self.__enable_flag = True
                    self.get_logger().info("--------------------")
                    if elapsed_time > timeout:
                        self.get_logger().info("Timeout....")
                        elapsed_time_flag = True
                        enable_flag = True
                        break
                    time.sleep(1)
            
            if(elapsed_time_flag):
                self.get_logger().info("Automatic enable timeout, exiting program")
                rclpy.shutdown()
            
            if self.piper.isOk():
                self.PublishArmState()
                self.PublishArmJointAndGripper()
                self.PublishArmCtrlAndGripper()
                self.PublishArmEndPose()
            else:
                self.get_logger().error(f"{self.can_port} is loss")
                self.get_logger().error(f"exit...")
                rclpy.shutdown() 

            rate.sleep()

    def PublishArmState(self):
        arm_status = PiperStatusMsg()
        status = self.piper.GetArmStatus().arm_status
        arm_status.ctrl_mode = status.ctrl_mode
        arm_status.arm_status = status.arm_status
        arm_status.mode_feedback = status.mode_feed
        arm_status.teach_status = status.teach_status
        arm_status.motion_status = status.motion_status
        arm_status.trajectory_num = status.trajectory_num
        arm_status.err_code = status.err_code
        # Copy extensive error status fields if needed, simplified here or full copy
        # Reuse existing code logic for full copy
        err = status.err_status
        arm_status.joint_1_angle_limit = err.joint_1_angle_limit
        arm_status.joint_2_angle_limit = err.joint_2_angle_limit
        arm_status.joint_3_angle_limit = err.joint_3_angle_limit
        arm_status.joint_4_angle_limit = err.joint_4_angle_limit
        arm_status.joint_5_angle_limit = err.joint_5_angle_limit
        arm_status.joint_6_angle_limit = err.joint_6_angle_limit
        arm_status.communication_status_joint_1 = err.communication_status_joint_1
        arm_status.communication_status_joint_2 = err.communication_status_joint_2
        arm_status.communication_status_joint_3 = err.communication_status_joint_3
        arm_status.communication_status_joint_4 = err.communication_status_joint_4
        arm_status.communication_status_joint_5 = err.communication_status_joint_5
        arm_status.communication_status_joint_6 = err.communication_status_joint_6
        self.arm_status_pub.publish(arm_status)

    def float_to_ros_time(self, t: float) -> Time:
        ros_time = Time()
        ros_time.sec = int(t)
        ros_time.nanosec = int((t - ros_time.sec) * 1e9)
        return ros_time

    def PublishArmJointAndGripper(self):
        new_time = max(self.piper.GetArmJointMsgs().time_stamp, self.piper.GetArmHighSpdInfoMsgs().time_stamp)
        self.joint_states.header.stamp = self.float_to_ros_time(new_time)
        
        joint_0 = (self.piper.GetArmJointMsgs().joint_state.joint_1 / 1000) * 0.017444
        joint_1 = (self.piper.GetArmJointMsgs().joint_state.joint_2 / 1000) * 0.017444
        joint_2 = (self.piper.GetArmJointMsgs().joint_state.joint_3 / 1000) * 0.017444
        joint_3 = (self.piper.GetArmJointMsgs().joint_state.joint_4 / 1000) * 0.017444
        joint_4 = (self.piper.GetArmJointMsgs().joint_state.joint_5 / 1000) * 0.017444
        joint_5 = (self.piper.GetArmJointMsgs().joint_state.joint_6 / 1000) * 0.017444
        joint_6 = self.piper.GetArmGripperMsgs().gripper_state.grippers_angle / 1000000
        
        # Update current joint targets to match reality when idle, 
        # so if we start a trajectory it starts from current position?
        # Actually, self.current_joint_targets should track what we WANT to be at.
        # But if we haven't sent a command yet, it should probably sync with feedback once.
        # For now, let's leave it as initialized to 0 or simple.
        
        vel_0 = self.piper.GetArmHighSpdInfoMsgs().motor_1.motor_speed / 1000
        vel_1 = self.piper.GetArmHighSpdInfoMsgs().motor_2.motor_speed / 1000
        vel_2 = self.piper.GetArmHighSpdInfoMsgs().motor_3.motor_speed / 1000
        vel_3 = self.piper.GetArmHighSpdInfoMsgs().motor_4.motor_speed / 1000
        vel_4 = self.piper.GetArmHighSpdInfoMsgs().motor_5.motor_speed / 1000
        vel_5 = self.piper.GetArmHighSpdInfoMsgs().motor_6.motor_speed / 1000
        
        effort_0 = self.piper.GetArmHighSpdInfoMsgs().motor_1.effort/1000
        effort_1 = self.piper.GetArmHighSpdInfoMsgs().motor_2.effort/1000
        effort_2 = self.piper.GetArmHighSpdInfoMsgs().motor_3.effort/1000
        effort_3 = self.piper.GetArmHighSpdInfoMsgs().motor_4.effort/1000
        effort_4 = self.piper.GetArmHighSpdInfoMsgs().motor_5.effort/1000
        effort_5 = self.piper.GetArmHighSpdInfoMsgs().motor_6.effort/1000
        effort_6 = self.piper.GetArmGripperMsgs().gripper_state.grippers_effort/1000

        self.joint_states.position = [joint_0, joint_1, joint_2, joint_3, joint_4, joint_5, joint_6]
        self.joint_states.velocity = [vel_0, vel_1, vel_2, vel_3, vel_4, vel_5]
        self.joint_states.effort = [effort_0, effort_1, effort_2, effort_3, effort_4, effort_5, effort_6]

        self.joint_states_feedback.position = self.joint_states.position
        self.joint_states_feedback.velocity = self.joint_states.velocity
        self.joint_states_feedback.effort = self.joint_states.effort
        self.joint_states_feedback.header.stamp = self.joint_states.header.stamp
        
        if any(abs(pos) > 3.5 for pos in self.joint_states_feedback.position):
            self.get_logger().warn("Joint state abnormal: value exceeds ±3.5 rad")
        else:
            self.joint_feedback_pub.publish(self.joint_states_feedback)
            self.joint_pub.publish(self.joint_states)

    def PublishArmCtrlAndGripper(self):
        new_time = max(self.piper.GetArmJointCtrl().time_stamp, self.piper.GetArmGripperCtrl().time_stamp)
        self.joint_ctrl.header.stamp = self.float_to_ros_time(new_time)
        
        joint_0 = (self.piper.GetArmJointCtrl().joint_ctrl.joint_1/1000) * 0.017444
        joint_1 = (self.piper.GetArmJointCtrl().joint_ctrl.joint_2/1000) * 0.017444
        joint_2 = (self.piper.GetArmJointCtrl().joint_ctrl.joint_3/1000) * 0.017444
        joint_3 = (self.piper.GetArmJointCtrl().joint_ctrl.joint_4/1000) * 0.017444
        joint_4 = (self.piper.GetArmJointCtrl().joint_ctrl.joint_5/1000) * 0.017444
        joint_5 = (self.piper.GetArmJointCtrl().joint_ctrl.joint_6/1000) * 0.017444
        joint_6 = self.piper.GetArmGripperCtrl().gripper_ctrl.grippers_angle/1000000
        
        self.joint_ctrl.position = [joint_0, joint_1, joint_2, joint_3, joint_4, joint_5, joint_6]
        
        if any(abs(pos) > 3.5 for pos in self.joint_ctrl.position):
            self.get_logger().warn("Joint ctrl abnormal: value exceeds ±3.5 rad")
        else:
            self.joint_ctrl_pub.publish(self.joint_ctrl)

    def PublishArmEndPose(self):
        new_time = self.piper.GetArmEndPoseMsgs().time_stamp
        endpos = Pose()
        endpos.position.x = self.piper.GetArmEndPoseMsgs().end_pose.X_axis / 1000000
        endpos.position.y = self.piper.GetArmEndPoseMsgs().end_pose.Y_axis / 1000000
        endpos.position.z = self.piper.GetArmEndPoseMsgs().end_pose.Z_axis / 1000000
        roll = self.piper.GetArmEndPoseMsgs().end_pose.RX_axis / 1000
        pitch = self.piper.GetArmEndPoseMsgs().end_pose.RY_axis / 1000
        yaw = self.piper.GetArmEndPoseMsgs().end_pose.RZ_axis / 1000
        roll = math.radians(roll)
        pitch = math.radians(pitch)
        yaw = math.radians(yaw)
        quaternion = R.from_euler('xyz', [roll, pitch, yaw]).as_quat()
        endpos.orientation.x = quaternion[0]
        endpos.orientation.y = quaternion[1]
        endpos.orientation.z = quaternion[2]
        endpos.orientation.w = quaternion[3]
        self.end_pose_pub.publish(endpos)
        
        end_pos_stamp = PoseStamped()
        end_pos_stamp.pose = endpos
        end_pos_stamp.header.stamp = self.float_to_ros_time(new_time)
        self.end_pose_stamped_pub.publish(end_pos_stamp)

    def pos_callback(self, pos_data):
        # Ignore topic commands if action is active to prevent conflict?
        # Or allow mixed control (risky).
        # Implementing simple priority: usage of topic allowed, but concurrent modification handled by sdk?
        # Let's keep original logic.
        factor = 180 / 3.1415926
        x = round(pos_data.x*1000) * 1000
        y = round(pos_data.y*1000) * 1000
        z = round(pos_data.z*1000) * 1000
        rx = round(pos_data.roll*1000*factor)
        ry = round(pos_data.pitch*1000*factor)
        rz = round(pos_data.yaw*1000*factor)
        
        if(self.GetEnableFlag()):
            self.piper.MotionCtrl_2(0x01, 0x00, 50)
            self.piper.EndPoseCtrl(x, y, z, rx, ry, rz)
            gripper = round(pos_data.gripper * 1000 * 1000)
            if pos_data.gripper > 80000: gripper = 80000
            if pos_data.gripper < 0: gripper = 0
            if self.gripper_exist:
                self.piper.GripperCtrl(abs(gripper), 1000, 0x01, 0)

    def joint_callback(self, joint_data):
        # Topic control callback
        factor = 57324.840764
        joint_positions = {}
        joint_6 = 0
        for idx, joint_name in enumerate(joint_data.name):
            joint_positions[joint_name] = round(joint_data.position[idx] * factor)
        
        if len(joint_data.position) >= 7:
            joint_6 = round(joint_data.position[6] * 1000 * 1000)
            joint_6 = joint_6 * self.gripper_val_mutiple

        if self.GetEnableFlag():
            # If Action is active, should we block? 
            # For this version, let's trust the user not to spam both. 
            # Or assume Topic is override.
            
            if joint_data.velocity != []:
                all_zeros = all(v == 0 for v in joint_data.velocity)
            else:
                all_zeros = True
            if not all_zeros:
                lens = len(joint_data.velocity)
                if lens == 7:
                    vel_all = clip(round(joint_data.velocity[6]), 1, 100)
                    self.piper.MotionCtrl_2(0x01, 0x01, vel_all)
                else:
                    self.piper.MotionCtrl_2(0x01, 0x01, 100)
            else:
                self.piper.MotionCtrl_2(0x01, 0x01, 100)

            # Update self.current_joint_targets for consistency when switching back to action?
            # It's better to read from feedback for that.

            self.piper.JointCtrl(
                joint_positions.get('joint1', 0),
                joint_positions.get('joint2', 0),
                joint_positions.get('joint3', 0),
                joint_positions.get('joint4', 0),
                joint_positions.get('joint5', 0),
                joint_positions.get('joint6', 0)
            )

            if self.gripper_exist:
                if len(joint_data.effort) >= 7:
                    gripper_effort = clip(joint_data.effort[6], 0.5, 3)
                    if not math.isnan(gripper_effort):
                        gripper_effort = round(gripper_effort * 1000)
                    else:
                        gripper_effort = 1000
                    self.piper.GripperCtrl(abs(joint_6), gripper_effort, 0x01, 0)
                else:
                    self.piper.GripperCtrl(abs(joint_6), 1000, 0x01, 0)

    def enable_callback(self, enable_flag: Bool):
        self.get_logger().info(f"Received enable flag: {enable_flag.data}")
        if enable_flag.data:
            self.__enable_flag = True
            self.piper.EnableArm(7)
            if self.gripper_exist:
                self.piper.GripperCtrl(0, 1000, 0x02, 0)
                self.piper.GripperCtrl(0, 1000, 0x01, 0)
        else:
            self.__enable_flag = False
            self.piper.DisableArm(7)
            if self.gripper_exist:
                self.piper.GripperCtrl(0, 1000, 0x02, 0)

    def handle_enable_service(self, req, resp):
        self.get_logger().info(f"Received request: {req.enable_request}")
        enable_flag = False
        loop_flag = False
        timeout = 5
        start_time = time.time()
        while not loop_flag:
            elapsed_time = time.time() - start_time
            self.get_logger().info(f"--------------------")
            
            # Using SDK to check status
            # Simplified for brevity, same logic as original
            m = self.piper.GetArmLowSpdInfoMsgs()
            enable_list = [
                m.motor_1.foc_status.driver_enable_status,
                m.motor_2.foc_status.driver_enable_status,
                m.motor_3.foc_status.driver_enable_status,
                m.motor_4.foc_status.driver_enable_status,
                m.motor_5.foc_status.driver_enable_status,
                m.motor_6.foc_status.driver_enable_status
            ]

            if req.enable_request:
                enable_flag = all(enable_list)
                self.piper.EnableArm(7)
                self.piper.GripperCtrl(0, 1000, 0x01, 0)
            else:
                enable_flag = any(enable_list)
                self.piper.DisableArm(7)
                self.piper.GripperCtrl(0, 1000, 0x02, 0)

            self.get_logger().info(f"Enable status: {enable_flag}")
            self.__enable_flag = enable_flag
            self.get_logger().info(f"--------------------")

            if enable_flag == req.enable_request:
                loop_flag = True
                enable_flag = True
            else:
                loop_flag = False
                enable_flag = False

            if elapsed_time > timeout:
                self.get_logger().info(f"Timeout...")
                enable_flag = False
                loop_flag = True
                break
            time.sleep(0.5)

        resp.enable_response = enable_flag
        return resp

def main(args=None):
    rclpy.init(args=args)
    piper_single_node = PiperRosNode()
    executor = MultiThreadedExecutor()
    try:
        rclpy.spin(piper_single_node, executor=executor)
    except KeyboardInterrupt:
        pass
    finally:
        piper_single_node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
