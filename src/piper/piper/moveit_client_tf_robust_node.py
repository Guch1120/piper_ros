#!/usr/bin/env python3
import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener
from tf2_ros import TransformException
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, PositionConstraint, OrientationConstraint, BoundingVolume
from shape_msgs.msg import SolidPrimitive
from geometry_msgs.msg import TransformStamped, Pose
from scipy.spatial.transform import Rotation as R
import numpy as np
import math
import time

class MoveArmClientRobust(Node):
    def __init__(self):
        super().__init__('move_arm_client_tf_robust')
        self._action_client = ActionClient(self, MoveGroup, 'move_action')

        # TF Buffer & Listener
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # Parameters
        self.declare_parameter('samples', 30) # Number of samples for averaging
        self.declare_parameter('sample_interval', 0.05) # Interval between samples
        self.declare_parameter('position_tolerance', 0.005) # 5mm
        self.declare_parameter('orientation_tolerance', 0.05) # ~3 degrees

        self.samples = self.get_parameter('samples').value
        self.sample_interval = self.get_parameter('sample_interval').value
        self.pos_tol = self.get_parameter('position_tolerance').value
        self.ori_tol = self.get_parameter('orientation_tolerance').value

        # Timer to start execution after buffer fills
        self._timer = self.create_timer(1.0, self.on_timer)
        self.processed = False

    def on_timer(self):
        self._timer.cancel()
        if self.processed:
            return
        self.processed = True
        self.execute_logic()

    def get_stable_transform(self, target_frame, source_frame):
        """
        Collects multiple TF frames and returns the average position and rotation.
        """
        positions = []
        rotations = [] # Quaternions [x, y, z, w]

        self.get_logger().info(f'Collecting {self.samples} samples for averaging...')
        
        for i in range(self.samples):
            try:
                # Get latest transform
                tf_stamped = self.tf_buffer.lookup_transform(
                    target_frame,
                    source_frame,
                    rclpy.time.Time())
                
                t = tf_stamped.transform.translation
                r = tf_stamped.transform.rotation
                
                positions.append([t.x, t.y, t.z])
                rotations.append([r.x, r.y, r.z, r.w])
                
            except TransformException as ex:
                self.get_logger().warn(f'Sample {i} failed: {ex}')
            
            time.sleep(self.sample_interval)

        if not positions:
            return None, None

        # 1. Average Position
        pos_avg = np.mean(positions, axis=0)

        # 2. Average Rotation (using vector averaging for quaternions, sufficient for small noise)
        # For higher accuracy, we could use eigenvectors, but mean + normalize is good for clustering.
        # Ensure w is positive for all to avoid canceling out antipodal quaternions (q and -q are same rotation)
        # But here assuming tracking is stable, signs should be consistent.
        # Let's use scipy for "mean" if possible, but scipy doesn't have simple mean for Rotations object in all versions.
        # Simple averaging:
        quats = np.array(rotations)
        # Align quaternions to match the first one (if dot product is negative, flip sign)
        ref_q = quats[0]
        for i in range(1, len(quats)):
            if np.dot(quats[i], ref_q) < 0:
                quats[i] = -quats[i]
        
        quat_avg = np.mean(quats, axis=0)
        # Normalize
        norm = np.linalg.norm(quat_avg)
        if norm > 0:
            quat_avg = quat_avg / norm
        else:
            quat_avg = ref_q # Fallback

        return pos_avg, quat_avg

    def execute_logic(self):
        target_frame = 'base_link'
        source_frame = 'interactive_set'
        
        self.get_logger().info('Looking up stable transform...')
        
        pos, quat = self.get_stable_transform(target_frame, source_frame)
        
        if pos is None:
             self.get_logger().error('Could not get any valid transforms!')
             rclpy.shutdown()
             return

        # Prepare Pose
        target_pose = Pose()
        target_pose.position.x = pos[0]
        target_pose.position.y = pos[1]
        target_pose.position.z = pos[2]
        target_pose.orientation.x = quat[0]
        target_pose.orientation.y = quat[1]
        target_pose.orientation.z = quat[2]
        target_pose.orientation.w = quat[3]
        
        self.get_logger().info(f'★ Averaged Target: {pos}')
        self.send_goal(target_pose, target_frame)

    def send_goal(self, target_pose, base_frame):
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('MoveGroup action server not available!')
            rclpy.shutdown()
            return

        goal_msg = MoveGroup.Goal()
        goal_msg.request.group_name = 'arm' 
        goal_msg.request.allowed_planning_time = 5.0
        goal_msg.request.num_planning_attempts = 10 
        
        end_effector_link = 'link6'

        # Constraints
        constraints = Constraints()

        # Position Constraint
        pc = PositionConstraint()
        pc.header.frame_id = base_frame
        pc.link_name = end_effector_link
        pc.weight = 1.0
        sphere = SolidPrimitive()
        sphere.type = SolidPrimitive.SPHERE
        sphere.dimensions = [self.pos_tol] # Uses configured tolerance
        bv = BoundingVolume()
        bv.primitives.append(sphere)
        bv.primitive_poses.append(target_pose)
        pc.constraint_region = bv
        constraints.position_constraints.append(pc)

        # Orientation Constraint
        oc = OrientationConstraint()
        oc.header.frame_id = base_frame
        oc.link_name = end_effector_link
        oc.orientation = target_pose.orientation
        oc.absolute_x_axis_tolerance = self.ori_tol
        oc.absolute_y_axis_tolerance = self.ori_tol
        oc.absolute_z_axis_tolerance = self.ori_tol
        oc.weight = 1.0
        constraints.orientation_constraints.append(oc)

        goal_msg.request.goal_constraints.append(constraints)

        self.get_logger().info('Sending goal...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Goal rejected!')
            rclpy.shutdown()
            return
        self.get_logger().info('Goal accepted! Moving...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        if result.error_code.val == 1:
            self.get_logger().info('SUCCESS!')
        else:
            self.get_logger().error(f'FAILED: Error code {result.error_code.val}')
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    client = MoveArmClientRobust()
    rclpy.spin(client)

if __name__ == '__main__':
    main()
