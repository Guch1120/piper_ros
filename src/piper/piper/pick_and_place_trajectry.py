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
from moveit_msgs.msg import RobotTrajectory
from geometry_msgs.msg import Pose
import math
import copy
import numpy as np

class TrajectoryStrategy:
    """軌道生成ロジックを管理するクラス"""
    
    @staticmethod
    def generate_waypoints(start_pose: Pose, target_pose: Pose, mode: str, height: float) -> list:
        """
        start_poseからtarget_poseまでのウェイポイントリストを生成する上位関数
        
        Args:
            start_pose: 現在の手先姿勢
            target_pose: 目標の手先姿勢
            mode: 'trapezoid' (台形), 'triangle' (三角), 'arc' (円弧), 'linear' (直線)
            height: 高さオフセット (m)
        Returns:
            waypoints: Pose[] (start_pose自体は含まないのが一般的)
        """
        waypoints = []

        if mode == 'linear':
            # 単純な直線（経由点なしでゴールのみ）
            waypoints.append(target_pose)

        elif mode == 'triangle':
            # 三角: 中間地点で高さhまで上げる
            mid_pose = copy.deepcopy(start_pose)
            # 位置は中間
            mid_pose.position.x = (start_pose.position.x + target_pose.position.x) / 2.0
            mid_pose.position.y = (start_pose.position.y + target_pose.position.y) / 2.0
            mid_pose.position.z = max(start_pose.position.z, target_pose.position.z) + height
            
            # 姿勢はSlerpが理想だが、ここでは単純化のためStartと同じか線形遷移させる
            # 今回は「中間点」→「ゴール」を追加
            waypoints.append(mid_pose)
            waypoints.append(target_pose)

        elif mode == 'trapezoid':
            # 台形: [Start直上] -> [Goal直上] -> [Goal]
            # 1. Start直上
            up_start = copy.deepcopy(start_pose)
            up_start.position.z += height
            waypoints.append(up_start)
            
            # 2. Goal直上
            up_goal = copy.deepcopy(target_pose)
            up_goal.position.z += height
            # 姿勢をいつ変えるか？「Goal直上」の時点でGoalの姿勢にしておくのが安全（水平移動中に姿勢変更）
            waypoints.append(up_goal)
            
            # 3. Goal
            waypoints.append(target_pose)

        elif mode == 'arc':
            # 円弧: StartとGoalを結ぶ直線を基準に、Sine波でZを持ち上げる
            # 分割数
            steps = 20
            for i in range(1, steps + 1):
                t = i / float(steps) # 0 < t <= 1
                
                # 線形補間ベース
                wp = copy.deepcopy(start_pose)
                wp.position.x = (1 - t) * start_pose.position.x + t * target_pose.position.x
                wp.position.y = (1 - t) * start_pose.position.y + t * target_pose.position.y
                
                # Z軸: 線形補間 + Sine波オフセット
                linear_z = (1 - t) * start_pose.position.z + t * target_pose.position.z
                arc_z = height * math.sin(math.pi * t) # t=0.5で最大
                wp.position.z = linear_z + arc_z
                
                # 姿勢: StartからGoalへ線形補間(簡易) 
                # ※厳密にはQuaternion Slerpが必要だが、CartesianPath計算時にMoveItが補完してくれることを期待して
                # ここではGoalの姿勢を徐々に適用する（あるいはCartesianPathServiceに任せる）
                # 今回は単純に「姿勢はGoalのものを使う」または「Startのものを使う」だと飛ぶので、
                # ウェイポイントではGoalの姿勢を入れておき、MoveItに補間させる
                wp.orientation = target_pose.orientation 
                
                waypoints.append(wp)
        
        return waypoints

class MoveArmClient(Node):
    def __init__(self):
        super().__init__('move_arm_client_tf')
        
        # 1. 軌道実行用アクションクライアント
        self._execute_client = ActionClient(self, ExecuteTrajectory, 'execute_trajectory')
        
        # 2. 軌道計算用サービスクライアント
        self._compute_path_client = self.create_client(GetCartesianPath, 'compute_cartesian_path')
        
        # TFバッファとリスナー
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # 設定
        self.group_name = 'arm'
        self.base_frame = 'base_link'
        self.end_effector_link = 'link6' # 実際のURDFに合わせて変更してください
        
        # 起動待機タイマー
        self._timer = self.create_timer(1.0, self.on_timer)
        self.processed = False

    def on_timer(self):
        self._timer.cancel()
        if self.processed: return
        self.processed = True
        
        # サービスの待機
        if not self._compute_path_client.wait_for_service(timeout_sec=5.0):
            self.get_logger().error('Compute Cartesian Path service not available!')
            return
        
        if not self._execute_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('Execute Trajectory action server not available!')
            return

        self.execute_logic()

    def execute_logic(self):
        # 目標TFフレーム名
        target_tf_name = 'interactive_set'
        
        self.get_logger().info('Looking up transform...')
        try:
            # 1. GoalのTF取得
            target_tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                target_tf_name,
                rclpy.time.Time(),
                timeout=Duration(seconds=1.0))

            # 2. Start (現在の手先) のTF取得
            start_tf = self.tf_buffer.lookup_transform(
                self.base_frame,
                self.end_effector_link,
                rclpy.time.Time())

            # Pose型に変換
            start_pose = self._tf_to_pose(start_tf)
            target_pose = self._tf_to_pose(target_tf)

            # 3. ウェイポイント生成 (ここで軌道タイプを指定)
            # mode: 'linear', 'triangle', 'trapezoid', 'arc'
            waypoints = TrajectoryStrategy.generate_waypoints(
                start_pose, target_pose, mode='trapezoid', height=0.15
            )

            # 4. Cartesian Pathの計算リクエスト
            self.compute_and_execute(start_pose, waypoints)

        except TransformException as ex:
            self.get_logger().error(f'Could not get transform: {ex}')

    def _tf_to_pose(self, tf_stamped):
        p = Pose()
        p.position.x = tf_stamped.transform.translation.x
        p.position.y = tf_stamped.transform.translation.y
        p.position.z = tf_stamped.transform.translation.z
        p.orientation = tf_stamped.transform.rotation
        return p

    def compute_and_execute(self, start_pose, waypoints):
        self.get_logger().info(f'Computing path with {len(waypoints)} waypoints...')
        
        # リクエスト作成
        req = GetCartesianPath.Request()
        req.header.frame_id = self.base_frame
        req.header.stamp = self.get_clock().now().to_msg()
        req.group_name = self.group_name
        req.waypoints = waypoints
        req.max_step = 0.01  # 1cm刻みで補間
        req.jump_threshold = 0.0 # 0.0は無効化 (特異点回避のため設定時は注意)
        req.avoid_collisions = True

        # 非同期でサービスを呼ぶ
        future = self._compute_path_client.call_async(req)
        future.add_done_callback(self.on_path_computed)

    def on_path_computed(self, future):
        try:
            response = future.result()
        except Exception as e:
            self.get_logger().error(f'Service call failed: {e}')
            return

        if response.fraction < 0.9: # 90%以上計算できなければ失敗とみなす
            self.get_logger().warn(f'Path planning incomplete! Fraction: {response.fraction}')
            return
        
        self.get_logger().info(f'Path computed (points: {len(response.solution.joint_trajectory.points)}). Executing...')
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
        # MoveItのエラーコード: 1 = SUCCESS
        if result.error_code.val == 1:
            self.get_logger().info('SUCCESS!')
        else:
            self.get_logger().error(f'FAILED: Error code {result.error_code.val}')
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    client = MoveArmClient()
    rclpy.spin(client)

if __name__ == '__main__':
    main()