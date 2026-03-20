#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
from trajectory_msgs.msg import JointTrajectoryPoint
import time
import math

class PiperMoveItBridge(Node):
    def __init__(self):
        super().__init__('piper_moveit_bridge')

        # 1. 現在の関節角度を覚えておくためのリスナー
        # (片方の腕だけ動かす時、もう片方が0に戻らないようにするため)
        self.current_positions = {
            'joint1': 0.0, 'joint2': 0.0, 'joint3': 0.0,
            'joint4': 0.0, 'joint5': 0.0, 'joint6': 0.0, 'joint7': 0.0
        }
        self.create_subscription(JointState, '/joint_states', self.state_callback, 10)

        # 2. ドライバに命令を送るパブリッシャー
        self.ctrl_pub = self.create_publisher(JointState, 'joint_ctrl_single', 10)

        # 3. MoveItからの命令を受け取るアクションサーバー (Arm用)
        self._action_server_arm = ActionServer(
            self,
            FollowJointTrajectory,
            'arm_controller/follow_joint_trajectory',
            self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback
        )

        # 4. MoveItからの命令を受け取るアクションサーバー (Gripper用)
        self._action_server_gripper = ActionServer(
            self,
            FollowJointTrajectory,
            'gripper_controller/follow_joint_trajectory',
            self.execute_callback,
            goal_callback=self.goal_callback,
            cancel_callback=self.cancel_callback
        )

        self.get_logger().info('Piper MoveIt Bridge Started!')

    def state_callback(self, msg):
        for i, name in enumerate(msg.name):
            if name in self.current_positions:
                self.current_positions[name] = msg.position[i]

    def goal_callback(self, goal_request):
        self.get_logger().info('Received Goal Request')
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        self.get_logger().info('Received Cancel Request')
        return CancelResponse.ACCEPT

    def execute_callback(self, goal_handle):
        self.get_logger().info('Executing goal...')
        goal = goal_handle.request.trajectory
        joint_names = goal.joint_names
        
        # 軌道の開始時刻
        start_time = self.get_clock().now().nanoseconds / 1e9

        # 簡易的な実行ループ (ポイントを順番に送る)
        # 本来はもっと滑らかに補間するべきだが、今回はシンプルに実装
        for point in goal.points:
            # キャンセルチェック
            if goal_handle.is_cancel_requested:
                goal_handle.canceled()
                self.get_logger().info('Goal Canceled')
                return Result()

            # 送信用のメッセージ作成
            cmd_msg = JointState()
            cmd_msg.header.stamp = self.get_clock().now().to_msg()
            
            # 全関節のリスト (MoveItが操作しない関節は現在値を維持)
            all_joints = ['joint1', 'joint2', 'joint3', 'joint4', 'joint5', 'joint6', 'joint7']
            cmd_msg.name = all_joints
            cmd_msg.position = []

            # 目標値の構築
            for j_name in all_joints:
                if j_name in joint_names:
                    # MoveItから指示があった関節
                    idx = joint_names.index(j_name)
                    cmd_msg.position.append(point.positions[idx])
                else:
                    # 指示がない関節は今の場所をキープ
                    cmd_msg.position.append(self.current_positions[j_name])

            # ドライバへ送信
            self.ctrl_pub.publish(cmd_msg)

#===========================================================================================#
#===========================================================================================#
#             注目!!!!!!!!                                                                   #
#             ここがぷるぷるの原因!!!!!!!!                                                      #
#              time.sleepは厳密には一定周期ではない                                              #
#============================================================================================#
#=============================================================================================#
            # 次のポイントまでの時間待機 (簡易実装)
            time_from_start = point.time_from_start.sec + point.time_from_start.nanosec * 1e-9 # 単位を秒に統一
            now = self.get_clock().now().nanoseconds / 1e9 # 現在時刻（秒）
            sleep_time = (start_time + time_from_start) - now
            
            if sleep_time > 0:
                time.sleep(sleep_time)
#===========================================================================================#
#===========================================================================================#
#===========================================================================================#
#===========================================================================================#

        goal_handle.succeed()
        result = FollowJointTrajectory.Result()
        return result

def main(args=None):
    rclpy.init(args=args)
    bridge = PiperMoveItBridge()
    rclpy.spin(bridge)
    bridge.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()