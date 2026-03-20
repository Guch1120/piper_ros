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
from moveit_msgs.msg import RobotState
from geometry_msgs.msg import Pose, PoseArray
from trajectory_msgs.msg import JointTrajectoryPoint # 追加
import math
import copy

class TrajectoryStrategy:
    @staticmethod
    def slerp(q1, q2, t):
        norm1 = math.sqrt(q1.x**2 + q1.y**2 + q1.z**2 + q1.w**2)
        norm2 = math.sqrt(q2.x**2 + q2.y**2 + q2.z**2 + q2.w**2)
        dot = (q1.x * q2.x + q1.y * q2.y + q1.z * q2.z + q1.w * q2.w) / (norm1 * norm2)
        if dot < 0.0:
            q2.x, q2.y, q2.z, q2.w = -q2.x, -q2.y, -q2.z, -q2.w
            dot = -dot
        if dot > 0.9995:
            res = copy.deepcopy(q1)
            res.x = q1.x + t * (q2.x - q1.x)
            res.y = q1.y + t * (q2.y - q1.y)
            res.z = q1.z + t * (q2.z - q1.z)
            res.w = q1.w + t * (q2.w - q1.w)
            return res
        theta_0 = math.acos(dot)
        theta = theta_0 * t
        sin_theta = math.sin(theta)
        sin_theta_0 = math.sin(theta_0)
        s0 = math.cos(theta) - dot * sin_theta / sin_theta_0
        s1 = sin_theta / sin_theta_0
        res = copy.deepcopy(q1)
        res.x = s0 * q1.x + s1 * q2.x
        res.y = s0 * q1.y + s1 * q2.y
        res.z = s0 * q1.z + s1 * q2.z
        res.w = s0 * q1.w + s1 * q2.w
        return res

    @staticmethod
    def generate_waypoints(start_pose: Pose, target_pose: Pose, mode: str, height: float) -> list:
        waypoints = []
        # 安全のためステップ数を少し増やす
        steps = 30 
        if mode == 'arc':
            for i in range(1, steps + 1):
                t = i / float(steps)
                wp = copy.deepcopy(start_pose)
                wp.position.x = (1 - t) * start_pose.position.x + t * target_pose.position.x
                wp.position.y = (1 - t) * start_pose.position.y + t * target_pose.position.y
                linear_z = (1 - t) * start_pose.position.z + t * target_pose.position.z
                # sin波で高さを付与
                arc_z = height * math.sin(math.pi * t)
                wp.position.z = linear_z + arc_z
                wp.orientation = TrajectoryStrategy.slerp(start_pose.orientation, target_pose.orientation, t)
                waypoints.append(wp)
        return waypoints

class MoveArmClient(Node):
    def __init__(self):
        super().__init__('move_arm_client_tf')
        
        self._execute_client = ActionClient(self, ExecuteTrajectory, 'execute_trajectory')
        self._compute_path_client = self.create_client(GetCartesianPath, 'compute_cartesian_path')
        
        self._debug_pub = self.create_publisher(PoseArray, '/debug_waypoints', 10)
        
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        self.group_name = 'arm' # piper_arm などの場合もあるのでsrdfを確認
        self.base_frame = 'base_link'
        self.end_effector_link = 'link6'
        
        self._timer = self.create_timer(1.0, self.on_timer)

    def on_timer(self):
        if not self._compute_path_client.service_is_ready():
            self.get_logger().warn('Waiting for Compute Cartesian Path service...')
            return
        if not self._execute_client.server_is_ready():
            self.get_logger().warn('Waiting for Execute Trajectory action server...')
            return

        target_tf_name = 'interactive_set'
        try:
            target_tf = self.tf_buffer.lookup_transform(self.base_frame, target_tf_name, rclpy.time.Time())
            start_tf = self.tf_buffer.lookup_transform(self.base_frame, self.end_effector_link, rclpy.time.Time())

            self.get_logger().info('Transform found! Starting execution...')
            self._timer.cancel()
            self.execute_logic(start_tf, target_tf)

        except TransformException as ex:
            self.get_logger().info(f'Waiting for transform... ({ex})')
            return

    def execute_logic(self, start_tf, target_tf):
        start_pose = self._tf_to_pose(start_tf)
        target_pose = self._tf_to_pose(target_tf)

        # ウェイポイント生成 (アーチ軌道)
        waypoints = TrajectoryStrategy.generate_waypoints(
            start_pose, target_pose, mode='arc', height=0.05
        )
        
        self.publish_debug_waypoints(waypoints)
        self.compute_and_execute(start_pose, waypoints)

    def _tf_to_pose(self, tf_stamped):
        p = Pose()
        p.position.x = tf_stamped.transform.translation.x
        p.position.y = tf_stamped.transform.translation.y
        p.position.z = tf_stamped.transform.translation.z
        p.orientation = tf_stamped.transform.rotation
        return p

    def publish_debug_waypoints(self, waypoints):
        msg = PoseArray()
        msg.header.frame_id = self.base_frame
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.poses = waypoints
        self._debug_pub.publish(msg)
        self.get_logger().info(f'Published {len(waypoints)} waypoints to /debug_waypoints')

    def compute_and_execute(self, start_pose, waypoints):
            self.get_logger().info(f'Computing path with {len(waypoints)} waypoints...')
            
            req = GetCartesianPath.Request()
            req.header.frame_id = self.base_frame
            req.header.stamp = self.get_clock().now().to_msg()
            req.group_name = self.group_name
            
            # 【修正】リンク名を空文字列にする（自動判定させる）
            # 特定のリンクを指定してエラーが出る場合、空にしてグループのデフォルト先端を使わせるのが定石です
            req.link_name = ""  
            
            req.start_state = RobotState() 
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

        if response.error_code.val != 1:
            self.get_logger().error(f'Cartesian Path failed with error code: {response.error_code.val}')
            return

        if response.fraction < 0.9:
            self.get_logger().warn(f'Path planning incomplete! Fraction: {response.fraction}')
            # 部分的でも実行したい場合は続行、厳密ならここで return
            
        self.get_logger().info(f'Path computed (fraction: {response.fraction}). adding time parameterization...')
        
        # ★ここが重要：時間パラメータの追加★
        trajectory_with_time = self.add_time_parameterization(response.solution)
        
        self.send_trajectory(trajectory_with_time)

    def add_time_parameterization(self, trajectory):
        """
        MoveItのCartesianPathは時間情報(time_from_start)が空の場合があるため、
        簡易的に等速運動として時間を割り当てる。
        """
        # 目標関節角速度 (rad/s) - 安全のためゆっくりめ
        target_joint_velocity = 0.5 
        min_dt = 0.05 # 最小時間ステップ (s)

        points = trajectory.joint_trajectory.points
        if not points:
            return trajectory

        # 始点の時間を0に
        points[0].time_from_start = Duration(seconds=0, nanoseconds=0).to_msg()
        
        current_time = 0.0
        
        for i in range(1, len(points)):
            prev_pos = points[i-1].positions
            curr_pos = points[i].positions
            
            # 各関節の中で最大の移動量を計算
            max_diff = 0.0
            for j in range(len(curr_pos)):
                diff = abs(curr_pos[j] - prev_pos[j])
                if diff > max_diff:
                    max_diff = diff
            
            # 時間 = 距離 / 速度
            dt = max_diff / target_joint_velocity
            
            # あまりに時間が短いとコントローラが追従できないため下限を設ける
            if dt < min_dt:
                dt = min_dt
                
            current_time += dt
            
            # Durationに変換してセット
            sec = int(current_time)
            nanosec = int((current_time - sec) * 1e9)
            points[i].time_from_start = Duration(seconds=sec, nanoseconds=nanosec).to_msg()
            
            # 速度・加速度情報は空にしておくと、コントローラ側で補間される場合が多い
            # または明示的に計算して入れる必要があるが、まずは位置+時間で試行する
            points[i].velocities = []
            points[i].accelerations = []
            points[i].effort = []

        return trajectory

    def send_trajectory(self, trajectory):
        self.get_logger().info('Sending trajectory to action server...')
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