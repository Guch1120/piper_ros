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

class MoveItClientTfRobust(Node):
    '''
    MoveItに引き渡すTFがRealseneのDepth精度の問題で位置ズレがあるため,平均を取って安定化させるノード
    変数名：
    target_frame: 基準フレーム (例: 'base_link')
    source_frame: 目標物フレーム (例: 'interactive_set')
    pos_tol: 位置許容誤差 (m)
    ori_tol: 姿勢許容誤差 (rad)
    samples: 平均化に使用するサンプル数
    sample_interval: サンプリング間隔（秒）
    '''
    def __init__(self):
        super().__init__('moveit_client_tf_robust')
        self._action_client = ActionClient(self, MoveGroup, 'move_action')

        # TFバッファとリスナーの初期化
        self.tf_buffer = Buffer()
        self.tf_listener = TransformListener(self.tf_buffer, self)
        
        # パラメータ設定
        self.declare_parameter('samples', 30) # 平均化に使用するサンプル数
        self.declare_parameter('sample_interval', 0.05) # サンプリング間隔（秒）
        self.declare_parameter('position_tolerance', 0.005) # 位置許容誤差 5mm
        self.declare_parameter('orientation_tolerance', 0.05) # 姿勢許容誤差 ~3度

        self.samples = self.get_parameter('samples').value
        self.sample_interval = self.get_parameter('sample_interval').value
        self.pos_tol = self.get_parameter('position_tolerance').value
        self.ori_tol = self.get_parameter('orientation_tolerance').value

        # TFバッファが充填されるのを待ってから実行を開始するためのタイマー
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
        複数のTFフレームを収集し、位置と回転の平均値を計算して返します。
        ノイズ除去によりターゲット精度を向上させます。
        """
        positions = []
        rotations = [] # クォータニオン [x, y, z, w]

        self.get_logger().info(f'{self.samples} サンプルを収集して平均化を開始します...')
        
        for i in range(self.samples):
            try:
                # 最新のTF（座標変換）を取得
                tf_stamped = self.tf_buffer.lookup_transform(
                    target_frame,
                    source_frame,
                    rclpy.time.Time())
                
                t = tf_stamped.transform.translation
                r = tf_stamped.transform.rotation
                
                positions.append([t.x, t.y, t.z])
                rotations.append([r.x, r.y, r.z, r.w])
                
            except TransformException as ex:
                self.get_logger().warn(f'サンプル {i} の取得に失敗: {ex}')
            
            time.sleep(self.sample_interval)

        if not positions:
            return None, None

        # 1. 位置の平均計算
        pos_avg = np.mean(positions, axis=0)

        # 2. 回転の平均計算（クォータニオンのベクトル平均）
        # ノイズが小さい場合、単純なベクトル平均と正規化で十分クラスタリング可能。
        # クォータニオンの対掌性（q と -q は同じ回転を表す）による相殺を防ぐため、符号を揃える。
        
        quats = np.array(rotations)
        # 最初のクォータニオンを基準に符号を合わせる（内積が負なら反転）
        ref_q = quats[0]
        for i in range(1, len(quats)):
            if np.dot(quats[i], ref_q) < 0:
                quats[i] = -quats[i]
        
        quat_avg = np.mean(quats, axis=0)
        # 正規化（長さが0より大きい場合）
        norm = np.linalg.norm(quat_avg)
        if norm > 0:
            quat_avg = quat_avg / norm
        else:
            quat_avg = ref_q # フォールバック

        return pos_avg, quat_avg

    def execute_logic(self):
        target_frame = 'base_link'      # 基準フレーム
        source_frame = 'interactive_set' # 目標物フレーム（ARマーカーなど）
        
        self.get_logger().info('安定したTF変換を探索中...')
        
        pos, quat = self.get_stable_transform(target_frame, source_frame)
        
        if pos is None:
             self.get_logger().error('有効なTF変換を取得できませんでした！')
             rclpy.shutdown()
             return

        # Pose（姿勢）メッセージの作成
        target_pose = Pose()
        target_pose.position.x = pos[0]
        target_pose.position.y = pos[1]
        target_pose.position.z = pos[2]
        target_pose.orientation.x = quat[0]
        target_pose.orientation.y = quat[1]
        target_pose.orientation.z = quat[2]
        target_pose.orientation.w = quat[3]
        
        self.get_logger().info(f'★ 平均化されたターゲット位置: {pos}')
        self.send_goal(target_pose, target_frame)

    def send_goal(self, target_pose, base_frame):
        # アクションサーバーの待機
        if not self._action_client.wait_for_server(timeout_sec=5.0):
            self.get_logger().error('MoveGroupアクションサーバーが見つかりません！')
            rclpy.shutdown()
            return

        goal_msg = MoveGroup.Goal()
        goal_msg.request.group_name = 'arm'  # 操作するグループ名
        goal_msg.request.allowed_planning_time = 5.0
        goal_msg.request.num_planning_attempts = 10 
        
        end_effector_link = 'link6' # エンドエフェクタのリンク名

        # MoveItで決められる制約（Constraints）の設定
        constraints = Constraints()

        # 位置制約 (Position Constraint)
        pc = PositionConstraint()
        pc.header.frame_id = base_frame
        pc.link_name = end_effector_link
        pc.weight = 1.0
        sphere = SolidPrimitive()
        sphere.type = SolidPrimitive.SPHERE
        sphere.dimensions = [self.pos_tol] # パラメータで設定した許容誤差を使用
        bv = BoundingVolume()
        bv.primitives.append(sphere)
        bv.primitive_poses.append(target_pose)
        pc.constraint_region = bv
        constraints.position_constraints.append(pc)

        # 姿勢（回転）制約 (Orientation Constraint)
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

        self.get_logger().info('ゴールを送信中...')
        self._send_goal_future = self._action_client.send_goal_async(goal_msg)
        self._send_goal_future.add_done_callback(self.goal_response_callback)

    def goal_response_callback(self, future):
        goal_handle = future.result()
        if not goal_handle.accepted:
            self.get_logger().error('ゴールが拒否されました！')
            rclpy.shutdown()
            return
        self.get_logger().info('ゴールが承認されました！移動を開始します...')
        self._get_result_future = goal_handle.get_result_async()
        self._get_result_future.add_done_callback(self.get_result_callback)

    def get_result_callback(self, future):
        result = future.result().result
        if result.error_code.val == 1: # 1 = SUCCESS
            self.get_logger().info('成功しました！ (SUCCESS)')
        else:
            self.get_logger().error(f'失敗しました: エラーコード {result.error_code.val}')
        rclpy.shutdown()

def main(args=None):
    rclpy.init(args=args)
    client = MoveItClientTfRobust()
    rclpy.spin(client)

if __name__ == '__main__':
    main()