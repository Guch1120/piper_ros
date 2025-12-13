#!/usr/bin/env python3
import rclpy
from rclpy.duration import Duration
from rclpy.time import Time
from geometry_msgs.msg import Pose
from moveit_msgs.srv import GetCartesianPath
from moveit_msgs.action import ExecuteTrajectory
from tf2_ros import TransformException

import math
import copy

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyServiceCaller, ProxyActionClient, ProxyTransformListener, ProxyPublisher

class TrajectoryStrategy:
    """
    軌道生成ロジック（改良版）
    """
    @staticmethod
    def generate_waypoints(start_pose: Pose, target_pose: Pose, mode: str, height: float) -> list:
        waypoints = []
        
        # 線形補間 (Linear)
        if mode == 'linear':
            # シンプルに終点だけ渡す（MoveItに任せるのが一番安全）
            waypoints.append(target_pose)
            
        # 三角形 (Triangle)
        elif mode == 'triangle':
            mid_pose = copy.deepcopy(start_pose)
            mid_pose.position.x = (start_pose.position.x + target_pose.position.x) / 2.0
            mid_pose.position.y = (start_pose.position.y + target_pose.position.y) / 2.0
            mid_pose.position.z = max(start_pose.position.z, target_pose.position.z) + height
            waypoints.append(mid_pose)
            waypoints.append(target_pose)
            
        # 台形 (Trapezoid)
        elif mode == 'trapezoid':
            up_start = copy.deepcopy(start_pose)
            up_start.position.z += height
            waypoints.append(up_start)
            
            up_goal = copy.deepcopy(target_pose)
            up_goal.position.z += height
            waypoints.append(up_goal)
            
            waypoints.append(target_pose)
            
        # 円弧 (Arc)
        elif mode == 'arc':
            # ステップ数を増やして密度を上げる（急激な変化を防ぐ）
            # 20 -> 50
            steps = 50
            for i in range(1, steps + 1):
                t = i / float(steps)
                wp = copy.deepcopy(start_pose)
                
                # 位置補間
                wp.position.x = (1 - t) * start_pose.position.x + t * target_pose.position.x
                wp.position.y = (1 - t) * start_pose.position.y + t * target_pose.position.y
                
                # Z軸 (Sine波)
                linear_z = (1 - t) * start_pose.position.z + t * target_pose.position.z
                arc_z = height * math.sin(math.pi * t)
                wp.position.z = linear_z + arc_z
                
                # 姿勢: ターゲットの姿勢に徐々に近づける（簡易線形補間）
                # MoveItが補間しやすいように、姿勢も少しずつ変化させる
                if i < steps:
                    # 中間は start と target の間の姿勢（簡易）
                    # クォータニオンの厳密な球面補間は重いので、MoveItに任せるため
                    # ここでは位置だけ細かくし、姿勢はターゲット固定または線形
                    # ★安定動作のため、今回は「ターゲット姿勢固定」を採用
                    wp.orientation = target_pose.orientation 
                else:
                    wp.orientation = target_pose.orientation

                waypoints.append(wp)
                
        return waypoints

class MoveArmCartesianState(EventState):
    """
    TF座標を取得し、MoveItでデカルト軌道を計算・実行するステート。
    """

    def __init__(self, group_name='arm', base_frame='base_link', target_frame='interactive_set', 
                 end_effector='link6', mode='arc', height=0.15):
        super(MoveArmCartesianState, self).__init__(outcomes=['succeeded', 'failed'])
        
        self._group_name = group_name
        self._base_frame = base_frame
        self._target_frame = target_frame
        self._end_effector = end_effector
        self._mode = mode
        self._height = height

        # ノード取得ハック
        self._node = None
        if ProxyPublisher._node is not None:
            self._node = ProxyPublisher._node
        
        if self._node is not None:
             if ProxyServiceCaller._node is None: ProxyServiceCaller._node = self._node
             if ProxyActionClient._node is None: ProxyActionClient._node = self._node
             if ProxyTransformListener._node is None: ProxyTransformListener._node = self._node

        self._srv_topic = 'compute_cartesian_path'
        self._action_topic = 'execute_trajectory'
        
        self._service_client = ProxyServiceCaller({self._srv_topic: GetCartesianPath})
        self._action_client = ProxyActionClient({self._action_topic: ExecuteTrajectory})
        self._tf_listener = ProxyTransformListener()

        self._step = 0 
        self._failed = False

    def on_enter(self, userdata):
        Logger.loginfo(f"Enter MoveArmCartesianState (Mode: {self._mode})")
        self._step = 0
        self._failed = False
        
        if self._node is None:
            self._failed = True
            return

        if not self._service_client.is_available(self._srv_topic):
            Logger.logwarn(f"Service {self._srv_topic} not available yet.")
            self._failed = True

    def execute(self, userdata):
        if self._failed:
            return 'failed'

        # --- Step 0: TF取得 & 計画リクエスト ---
        if self._step == 0:
            try:
                # TF取得
                if not self._tf_listener.buffer.can_transform(self._base_frame, self._target_frame, Time()):
                    return 

                target_tf = self._tf_listener.buffer.lookup_transform(
                    self._base_frame, self._target_frame, Time())
                
                start_tf = self._tf_listener.buffer.lookup_transform(
                    self._base_frame, self._end_effector, Time())

                Logger.loginfo("Transforms found. Planning...")
                
                start_pose = self._tf_to_pose(start_tf)
                target_pose = self._tf_to_pose(target_tf)

                # ウェイポイント生成
                waypoints = TrajectoryStrategy.generate_waypoints(
                    start_pose, target_pose, mode=self._mode, height=self._height
                )

                # 【重要】現在のロボット位置を始点に追加 (連続性確保)
                waypoints.insert(0, start_pose)

                # リクエスト設定 (緩和設定)
                req = GetCartesianPath.Request()
                req.header.frame_id = self._base_frame
                req.header.stamp = Time(seconds=0).to_msg()
                req.group_name = self._group_name
                req.waypoints = waypoints
                
                # eef_step: 細かすぎると計算不能、粗すぎると直線になる
                # 0.01 (1cm) -> 0.02 (2cm) に緩和して計算しやすくする
                req.max_step = 0.02 
                
                # jump_threshold: 0.0はチェック無効だが、あえて少し入れてみることも手
                # ここでは無効(0.0)のままにする
                req.jump_threshold = 0.0 
                
                req.avoid_collisions = True

                self._service_client.call_async(self._srv_topic, req)
                self._step = 1

            except Exception as ex:
                Logger.logerr(f"Setup Error: {ex}")
                self._failed = True
                return 'failed'

        # --- Step 1: 計画結果待機 ---
        elif self._step == 1:
            if self._service_client.done(self._srv_topic):
                try:
                    result = self._service_client.result(self._srv_topic)
                    
                    # 閾値を少し下げる (Arcなどは完全な100%になりにくい場合があるため)
                    # 0.9 (90%) 以上なら実行を許可する
                    if result.fraction < 0.9:
                        Logger.logwarn(f"Plan failed. Fraction: {result.fraction}")
                        self._failed = True
                        return 'failed'
                    
                    Logger.loginfo(f"Path computed (Fraction: {result.fraction}). Executing...")
                    
                    goal = ExecuteTrajectory.Goal()
                    goal.trajectory = result.solution
                    self._action_client.send_goal(self._action_topic, goal)
                    self._step = 2

                except Exception as e:
                    Logger.logerr(f"Service result error: {e}")
                    self._failed = True
                    return 'failed'

        # --- Step 2: 実行結果待機 ---
        elif self._step == 2:
            if self._action_client.has_result(self._action_topic):
                result = self._action_client.get_result(self._action_topic)
                if result.error_code.val == 1:
                    Logger.loginfo("SUCCESS!")
                    return 'succeeded'
                else:
                    Logger.logerr(f"FAILED: Error code {result.error_code.val}")
                    return 'failed'

        return 

    def on_exit(self, userdata):
        if self._step == 2 and not self._action_client.has_result(self._action_topic):
            self._action_client.cancel(self._action_topic)

    def _tf_to_pose(self, tf_stamped):
        p = Pose()
        p.position.x = tf_stamped.transform.translation.x
        p.position.y = tf_stamped.transform.translation.y
        p.position.z = tf_stamped.transform.translation.z
        p.orientation = tf_stamped.transform.rotation
        return p