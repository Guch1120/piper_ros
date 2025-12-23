import rclpy
from rclpy.action import ActionClient
from rclpy.node import Node
import tf2_ros
from tf2_ros.buffer import Buffer
from tf2_ros.transform_listener import TransformListener
from tf2_ros import TransformException
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, PositionConstraint, OrientationConstraint, BoundingVolume
from shape_msgs.msg import SolidPrimitive
from geometry_msgs.msg import TransformStamped, Pose

class MoveArmClient(Node):
    def __init__(self):
        super().__init__('move_arm_client_tf')
        self._action_client = ActionClient(self, MoveGroup, 'move_action')

        # TFリスナーの初期化
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)

        # ダミーTFを使うかどうかを選択するパラメータ
        self.declare_parameter('use_dummy_tf', False)

    def send_goal(self, tf_stamped):
        """
        tf_stamped: geometry_msgs.msg.TransformStamped
        受け取ったTFの位置・姿勢へアームを移動させる
        """
        # サーバー待機
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('MoveGroup action server not available!')
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

        # TF(Transform) を Pose に変換しておく
        target_pose = Pose()
        target_pose.position.x = tf_stamped.transform.translation.x
        target_pose.position.y = tf_stamped.transform.translation.y
        target_pose.position.z = tf_stamped.transform.translation.z
        target_pose.orientation = tf_stamped.transform.rotation

        constraints = Constraints()

        # --- A. 位置制約 (PositionConstraint) ---
        # 「この空間領域(球)の中にリンク先が入っていればOK」という指定方法
        pc = PositionConstraint()
        pc.header.frame_id = base_frame
        pc.link_name = end_effector_link
        pc.weight = 1.0
        
        # 制約領域（ターゲット位置を中心とした半径1mmの球）
        sphere = SolidPrimitive()
        bv = BoundingVolume()
        sphere.type = SolidPrimitive.SPHERE
        sphere.dimensions = [0.005] # 半径 (m)
        bv.primitives.append(sphere)
        bv.primitive_poses.append(target_pose) # 球の中心＝ターゲット位置
        
        pc.constraint_region = bv
        constraints.position_constraints.append(pc)

        # --- B. 姿勢制約 (OrientationConstraint) ---
        # oc = OrientationConstraint()
        # oc.header.frame_id = base_frame
        # oc.link_name = end_effector_link
        # oc.orientation = target_pose.orientation
        # oc.absolute_x_axis_tolerance = 0.01
        # oc.absolute_y_axis_tolerance = 0.01
        # oc.absolute_z_axis_tolerance = 0.01
        # oc.weight = 1.0
        
        # constraints.orientation_constraints.append(oc)

        # 制約をゴールにセット
        goal_msg.request.goal_constraints.append(constraints)

        # 送信
        self.get_logger().info(f'Sending goal to: {target_pose.position}')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().info('Goal rejected :(')
            return
        self.get_logger().info('Goal accepted! Moving...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        self.get_logger().info(f'Result code: {result.error_code.val}')
        # Success = 1
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    client = MoveArmClient()

    # パラメータからダミーTFを使用するかどうかを取得
    use_dummy_tf = client.get_parameter('use_dummy_tf').get_parameter_value().bool_value

    try:
        if use_dummy_tf:
            client.get_logger().info('Using dummy TF goal.')
            # テスト用のTFデータを作成
            tf_stamped = TransformStamped()
            tf_stamped.header.frame_id = 'base_link' # 基準座標系
            tf_stamped.child_frame_id = 'target_object'
            
            # 例: 前方(x) 0.15m, 高さ(z) 0.2m の位置へ
            tf_stamped.transform.translation.x = 0.15
            tf_stamped.transform.translation.y = 0.0
            tf_stamped.transform.translation.z = 0.2
            
            # 姿勢（クォータニオン）: ここでは単位元（回転なし）
            tf_stamped.transform.rotation.x = 0.0
            tf_stamped.transform.rotation.y = 0.0
            tf_stamped.transform.rotation.z = 0.0
            tf_stamped.transform.rotation.w = 1.0

        else:
            client.get_logger().info('Looking up transform from TF tree...')
            target_frame = 'base_link'      # 基準となる座標系
            source_frame = 'interactive_set'  # 目標物の座標系

            # TFが利用可能になるまで10秒待機し、TFを取得する
            when = rclpy.time.Time() # 最新のTFを取得
            tf_stamped = client.tf_buffer.lookup_transform(
                target_frame,
                source_frame,
                when,
                timeout=rclpy.duration.Duration(seconds=10.0))
            client.get_logger().info(f"Successfully got transform from '{source_frame}' to '{target_frame}'")

        client.send_goal(tf_stamped)
        rclpy.spin(client)

    except TransformException as ex:
        client.get_logger().error(f'Could not get transform: {ex}')
    finally:
        client.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()