import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
from rclpy.duration import Duration
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener
from tf2_ros import TransformException

# MoveIt / Geometry Messages
from moveit_msgs.srv import GetCartesianPath
from moveit_msgs.action import ExecuteTrajectory
from geometry_msgs.msg import Pose
import math
import copy

class TrajectoryStrategy:
    """軌道生成ロジック（変更なし）"""
    @staticmethod
    def generate_waypoints(start_pose: Pose, target_pose: Pose, mode: str, height: float) -> list:
        waypoints = []
        if mode == 'linear':
            waypoints.append(target_pose)
        elif mode == 'triangle':
            mid_pose = copy.deepcopy(start_pose)
            mid_pose.position.x = (start_pose.position.x + target_pose.position.x) / 2.0
            mid_pose.position.y = (start_pose.position.y + target_pose.position.y) / 2.0
            mid_pose.position.z = max(start_pose.position.z, target_pose.position.z) + height
            waypoints.append(mid_pose)
            waypoints.append(target_pose)
        elif mode == 'trapezoid':
            up_start = copy.deepcopy(start_pose)
            up_start.position.z += height
            waypoints.append(up_start)
            up_goal = copy.deepcopy(target_pose)
            up_goal.position.z += height
            waypoints.append(up_goal)
            waypoints.append(target_pose)
        elif mode == 'arc':
            steps = 20
            for i in range(1, steps + 1):
                t = i / float(steps)
                wp = copy.deepcopy(start_pose)
                wp.position.x = (1 - t) * start_pose.position.x + t * target_pose.position.x
                wp.position.y = (1 - t) * start_pose.position.y + t * target_pose.position.y
                linear_z = (1 - t) * start_pose.position.z + t * target_pose.position.z
                arc_z = height * math.sin(math.pi * t)
                wp.position.z = linear_z + arc_z
                wp.orientation = target_pose.orientation 
                waypoints.append(wp)
        return waypoints

class MoveArmClient(Node):
    def __init__(self):
        super().__init__('move_arm_client_tf')
        
        self._execute_client = ActionClient(self, ExecuteTrajectory, 'execute_trajectory')
        self._compute_path_client = self.create_client(GetCartesianPath, 'compute_cartesian_path')
        
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        self.group_name = 'arm'
        self.base_frame = 'base_link'
        self.end_effector_link = 'link6'
        
        # タイマーは「1.0秒ごとにチェックする」役割にします
        self._timer = self.create_timer(1.0, self.on_timer)

    def on_timer(self):
        """
        この関数は1秒ごとに呼び出されます。
        準備が整っていない場合は return して次の呼び出しを待ちます（ノンブロッキング）。
        """
        # 1. サービスの確認
        if not self._compute_path_client.service_is_ready():
            self.get_logger().warn('Waiting for Compute Cartesian Path service...')
            return
        
        if not self._execute_client.server_is_ready():
            self.get_logger().warn('Waiting for Execute Trajectory action server...')
            return

        # 2. TFの確認
        target_tf_name = 'interactive_set'
        try:
            # TFがあるかチェック (Time() = 最新/0.0)
            target_tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                target_tf_name,
                rclpy.time.Time())

            start_tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.end_effector_link,
                rclpy.time.Time())

            # --- ここまで到達できれば準備完了 ---
            self.get_logger().info('Transform found! Starting execution...')
            
            # 重要: 準備できたのでタイマーを止める（これ以上呼ばれないようにする）
            self._timer.cancel()
            
            # ロジック実行
            self.execute_logic(start_tf, target_tf)

        except TransformException as ex:
            # まだTFがない場合はログを出して return (次のタイマー呼び出しを待つ)
            self.get_logger().info(f'Waiting for transform... ({ex})')
            return

    def execute_logic(self, start_tf, target_tf):
        # 取得済みのTFを使ってPoseに変換
        start_pose = self._tf_to_pose(start_tf)
        target_pose = self._tf_to_pose(target_tf)

        waypoints = TrajectoryStrategy.generate_waypoints(
            start_pose, target_pose, mode='arc', height=0.15
        )
        self.compute_and_execute(start_pose, waypoints)

    def _tf_to_pose(self, tf_stamped):
        p = Pose()
        p.position.x = tf_stamped.transform.translation.x
        p.position.y = tf_stamped.transform.translation.y
        p.position.z = tf_stamped.transform.translation.z
        p.orientation = tf_stamped.transform.rotation
        return p

    def compute_and_execute(self, start_pose, waypoints):
        self.get_logger().info(f'Computing path with {len(waypoints)} waypoints...')
        
        req = GetCartesianPath.Request()
        req.header.frame_id = self.base_frame
        req.header.stamp = self.get_clock().now().to_msg()
        req.group_name = self.group_name
        req.waypoints = waypoints
        req.max_step = 0.01
        req.jump_threshold = 0.0
        req.avoid_collisions = True

        future = self._compute_path_client.call_async(req)
        future.add_done_callback(self.on_path_computed)

    def on_path_computed(self, future):
        try:
            response = future.result()
        except Exception as e:
            self.get_logger().error(f'Service call failed: {e}')
            return

        if response.fraction < 0.9:
            self.get_logger().warn(f'Path planning incomplete! Fraction: {response.fraction}')
            return
        
        self.get_logger().info(f'Path computed. Executing...')
        self.send_trajectory(response.solution)

    def send_trajectory(self, trajectory):
        goal_msg = ExecuteTrajectory.Goal()
        goal_msg.trajectory = trajectory
        
        self._send_goal_future = self._execute_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('Goal rejected!')
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
        # 完了したら終了
        # rclpy.shutdown() # spin()を使っている場合はこれを呼ぶと全体が落ちるので注意。通常はそのまま待機でOK

def main(args=None):
    rclpy.init(args=args)
    client = MoveArmClient()
    try:
        rclpy.spin(client)
    except KeyboardInterrupt:
        pass
    finally:
        client.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()