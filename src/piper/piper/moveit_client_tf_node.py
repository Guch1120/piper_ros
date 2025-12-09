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
import math

class MoveArmClient(Node):
    def __init__(self):
        super().__init__('move_arm_client_tf')
        self._action_client = ActionClient(self, MoveGroup, 'move_action')

        # TFバッファとリスナー
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # ★ここが重要：起動直後はTFバッファが空なので、
        # 1.0秒間スピン（受信）させてからメイン処理を開始するタイマーをセット
        self._timer = self.create_timer(1.0, self.on_timer)
        self.processed = False

    def on_timer(self):
        # 一度だけ実行するためタイマーをキャンセル
        self._timer.cancel()
        if self.processed:
            return
        self.processed = True
        
        self.execute_logic()

    def execute_logic(self):
        target_frame = 'base_link'
        source_frame = 'interactive_set'
        
        self.get_logger().info('Looking up transform...')
        
        try:
            # 最新のTFを取得（timeout=0で即時取得しても、すでに1秒待っているので入っているはず）
            # 安全のため少しだけ待つ設定にする
            tf_stamped = self.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                rclpy.time.Time(),
                timeout=rclpy.duration.Duration(seconds=1.0))
                
            self.send_goal(tf_stamped)

        except TransformException as ex:
            self.get_logger().error(f'Could not get transform: {ex}')
            # 失敗したら終了
            rclpy.shutdown()

    def send_goal(self, tf_stamped):
        """
        tf_stamped: geometry_msgs.msg.TransformStamped
        受け取ったTFの位置・姿勢へアームを移動させる
        """
        # サーバー待機
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('MoveGroup action server not available!')
            rclpy.shutdown()
            return

        # 1. ゴールメッセージの作成
        goal_msg = MoveGroup.Goal()
        goal_msg.request.group_name = 'arm' 
        goal_msg.request.allowed_planning_time = 5.0
        goal_msg.request.num_planning_attempts = 10 #試行回数
        
        # 基準となるフレームと、動かしたい先端リンクの名前
        # ※ Piperの場合、先端は 'link6' や 'ctrl_link' など。URDFを確認してね。
        base_frame = tf_stamped.header.frame_id
        end_effector_link = 'link6'

        target_pose = Pose()
        target_pose.position.x = tf_stamped.transform.translation.x
        target_pose.position.y = tf_stamped.transform.translation.y
        target_pose.position.z = tf_stamped.transform.translation.z
        target_pose.orientation = tf_stamped.transform.rotation

        # 距離チェックログ
        dist = math.sqrt(target_pose.position.x**2 + target_pose.position.y**2 + target_pose.position.z**2)
        self.get_logger().info(f'★Target X={target_pose.position.x:.3f}, Y={target_pose.position.y:.3f}, Z={target_pose.position.z:.3f}')
        self.get_logger().info(f'★Distance = {dist:.3f} m')

        constraints = Constraints()

        # 位置制約
        # 「この空間領域(球)の中にリンク先が入っていればOK」という指定方法
        pc = PositionConstraint()
        pc.header.frame_id = base_frame
        pc.link_name = end_effector_link
        pc.weight = 1.0
        sphere = SolidPrimitive()
        # 制約領域（ターゲット位置を中心とした半径1mmの球）
        sphere.type = SolidPrimitive.SPHERE
        sphere.dimensions = [0.02] # 半径2cm
        bv = BoundingVolume()
        bv.primitives.append(sphere)
        bv.primitive_poses.append(target_pose) #球の中心  = ターゲット位置
        pc.constraint_region = bv
        constraints.position_constraints.append(pc)

        # # 姿勢制約
        oc = OrientationConstraint()
        oc.header.frame_id = base_frame
        oc.link_name = end_effector_link
        oc.orientation = target_pose.orientation
        oc.absolute_x_axis_tolerance = 0.5 
        oc.absolute_y_axis_tolerance = 0.5
        oc.absolute_z_axis_tolerance = 0.5
        oc.weight = 1.0
        constraints.orientation_constraints.append(oc)
        #位置をゴールにセット
        goal_msg.request.goal_constraints.append(constraints)

        # 3. 送信！
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
    client = MoveArmClient()
    # ここでspinすることで、タイマーコールバック -> TF受信 -> send_goal が回る
    rclpy.spin(client)

if __name__ == '__main__':
    main()