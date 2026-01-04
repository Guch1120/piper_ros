#!/usr/bin/env python3
import rclpy
from rclpy.node import Node
from rclpy.action import ActionServer, CancelResponse, GoalResponse
from rclpy.executors import MultiThreadedExecutor
from control_msgs.action import FollowJointTrajectory
from sensor_msgs.msg import JointState
import threading

class PiperMoveItBridge(Node):
    def __init__(self):
        super().__init__('piper_moveit_bridge')

        # 1. 状態管理変数
        self.current_positions = {
            f'joint{i}': 0.0 for i in range(1, 8)
        }
        self.all_joint_names = [f'joint{i}' for i in range(1, 8)]
        
        # 軌道再生用の変数
        self.active_trajectory = None
        self.start_time = None
        self.lock = threading.Lock() # データの排他制御用

        # 2. 通信設定
        self.create_subscription(JointState, '/joint_states', self.state_callback, 10)
        self.ctrl_pub = self.create_publisher(JointState, 'joint_ctrl_single', 10)

        # 3. アクションサーバー
        self._action_server_arm = ActionServer(
            self, FollowJointTrajectory, 'arm_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback, cancel_callback=self.cancel_callback
        )
        self._action_server_gripper = ActionServer(
            self, FollowJointTrajectory, 'gripper_controller/follow_joint_trajectory',
            self.execute_callback, goal_callback=self.goal_callback, cancel_callback=self.cancel_callback
        )

        # 4. ヌルヌル動かすための100Hzタイマー (0.01s)
        self.control_timer = self.create_timer(0.01, self.timer_callback)

        self.get_logger().info('Piper MoveIt Bridge (Smooth Version) Started!')

    def state_callback(self, msg):
        with self.lock:
            for i, name in enumerate(msg.name):
                if name in self.current_positions:
                    self.current_positions[name] = msg.position[i]

    def goal_callback(self, goal_request):
        return GoalResponse.ACCEPT

    def cancel_callback(self, goal_handle):
        return CancelResponse.ACCEPT

    def timer_callback(self):
        """100Hzで実行され、現在時刻に最適な関節角度を算出して送信する"""
        with self.lock:
            if self.active_trajectory is None or self.start_time is None:
                return

            # 経過時間の計算
            now = self.get_clock().now()
            elapsed_time = (now - self.start_time).nanoseconds / 1e9

            points = self.active_trajectory.points
            joint_names = self.active_trajectory.joint_names

            # 現在の経過時間に対応する区間を探す
            target_positions = None
            
            if elapsed_time <= 0:
                target_positions = points[0].positions
            elif elapsed_time >= (points[-1].time_from_start.sec + points[-1].time_from_start.nanosec * 1e-9):
                target_positions = points[-1].positions
                # 軌道終了フラグ（必要に応じて）
            else:
                # 線形補間ロジック
                for i in range(len(points) - 1):
                    t0 = points[i].time_from_start.sec + points[i].time_from_start.nanosec * 1e-9
                    t1 = points[i+1].time_from_start.sec + points[i+1].time_from_start.nanosec * 1e-9
                    
                    if t0 <= elapsed_time < t1:
                        alpha = (elapsed_time - t0) / (t1 - t0) # 進行度 (0.0~1.0)
                        # 各関節を補間
                        target_positions = []
                        for j in range(len(joint_names)):
                            p0 = points[i].positions[j]
                            p1 = points[i+1].positions[j]
                            interpolated_p = p0 + alpha * (p1 - p0)
                            target_positions.append(interpolated_p)
                        break

            if target_positions is not None:
                # メッセージ構築
                cmd_msg = JointState()
                cmd_msg.header.stamp = now.to_msg()
                cmd_msg.name = self.all_joint_names
                
                final_positions = []
                for j_name in self.all_joint_names:
                    if j_name in joint_names:
                        idx = joint_names.index(j_name)
                        final_positions.append(target_positions[idx])
                    else:
                        final_positions.append(self.current_positions[j_name])
                
                cmd_msg.position = final_positions
                self.ctrl_pub.publish(cmd_msg)

    def execute_callback(self, goal_handle):
        self.get_logger().info('New Trajectory Received')
        
        with self.lock:
            self.active_trajectory = goal_handle.request.trajectory
            self.start_time = self.get_clock().now()

        # 軌道が終了するまで待機（MoveItに完了を伝えるため）
        last_point_time = (self.active_trajectory.points[-1].time_from_start.sec + 
                           self.active_trajectory.points[-1].time_from_start.nanosec * 1e-9)
        
        while rclpy.ok():
            now = self.get_clock().now()
            elapsed = (now - self.start_time).nanoseconds / 1e9
            
            if goal_handle.is_cancel_requested:
                with self.lock:
                    self.active_trajectory = None
                goal_handle.canceled()
                return FollowJointTrajectory.Result()
            
            if elapsed > last_point_time + 0.1: # 余裕を持って終了
                break
            
            time.sleep(0.05) # 監視周期（制御周期ではないので粗くて良い）

        goal_handle.succeed()
        self.get_logger().info('Goal Succeeded')
        return FollowJointTrajectory.Result()

def main(args=None):
    rclpy.init(args=args)
    bridge = PiperMoveItBridge()
    # MultiThreadedExecutor を使うことで、execute_callbackで待機中も
    # タイマーやサブスクリプションが止まらないようにする
    executor = MultiThreadedExecutor()
    rclpy.spin(bridge, executor=executor)
    bridge.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()