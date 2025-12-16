#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import rclpy
from rclpy.node import Node
from rclpy.action import ActionClient
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint

class CloseGripper(Node):
    def __init__(self):
        super().__init__('close_gripper_node')
        # MoveItの標準アクションサーバー 'move_group' に接続
        self._action_client = ActionClient(self, MoveGroup, 'move_action')

    def send_goal(self):
        goal_msg = MoveGroup.Goal()
        
        # SRDFに基づくグループ名
        goal_msg.request.group_name = 'gripper'
        goal_msg.request.allowed_planning_time = 2.0
        goal_msg.request.max_velocity_scaling_factor = 1.0
        goal_msg.request.max_acceleration_scaling_factor = 1.0
        
        # ジョイント制約の作成 (SRDFのclose状態: joint7 = 0.0)
        constraints = Constraints()
        jc = JointConstraint()
        jc.joint_name = 'joint7'
        jc.position = 0.0  # Close position
        jc.tolerance_above = 0.01
        jc.tolerance_below = 0.01
        jc.weight = 1.0
        constraints.joint_constraints.append(jc)
        goal_msg.request.goal_constraints.append(constraints)

        self.get_logger().info('Waiting for action server...')
        self._action_client.wait_for_server()

        self.get_logger().info('Sending goal to CLOSE gripper...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Goal rejected :(')
            return

        self.get_logger().info('Goal accepted. Waiting for result...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        if result.error_code.val == 1:
            self.get_logger().info('Gripper CLOSED successfully!')
        else:
            self.get_logger().error(f'Failed with error code: {result.error_code.val}')
        
        # 終了
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    action_client = CloseGripper()
    action_client.send_goal()
    rclpy.spin(action_client)

if __name__ == '__main__':
    main()