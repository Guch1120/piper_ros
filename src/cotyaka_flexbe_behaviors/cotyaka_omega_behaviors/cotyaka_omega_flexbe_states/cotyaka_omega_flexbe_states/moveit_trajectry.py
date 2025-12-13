#!/usr/bin/env python3
import rclpy
from rclpy.duration import Duration
from rclpy.time import Time
from geometry_msgs.msg import Pose, Quaternion
from moveit_msgs.srv import GetCartesianPath
from moveit_msgs.action import ExecuteTrajectory
from tf2_ros import TransformException

import math
import copy

from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyServiceCaller, ProxyActionClient, ProxyTransformListener, ProxyPublisher

class TrajectoryStrategy:
    """
    軌道生成ロジック（Slerp強化版）
    """
    @staticmethod
    def slerp(q1, q2, t):
        """Quaternionの球面線形補間(Slerp) - 堅牢版"""
        # 正規化（計算誤差対策）
        n1 = math.sqrt(q1.x**2 + q1.y**2 + q1.z**2 + q1.w**2)
        n2 = math.sqrt(q2.x**2 + q2.y**2 + q2.z**2 + q2.w**2)
        
        # ゼロ除算回避
        if n1 < 1e-6 or n2 < 1e-6: return q2

        x1, y1, z1, w1 = q1.x/n1, q1.y/n1, q1.z/n1, q1.w/n1
        x2, y2, z2, w2 = q2.x/n2, q2.y/n2, q2.z/n2, q2.w/n2

        dot = x1*x2 + y1*y2 + z1*z2 + w1*w2

        # 最短経路（逆回転防止）
        if dot < 0.0:
            x2, y2, z2, w2 = -x2, -y2, -z2, -w2
            dot = -dot

        # ほぼ同じ向きなら線形補間（計算安定化）
        if dot > 0.9995:
            res = Quaternion()
            res.x = x1 + t*(x2-x1)
            res.y = y1 + t*(y2-y1)
            res.z = z1 + t*(z2-z1)
            res.w = w1 + t*(w2-w1)
            # 結果も正規化
            rn = math.sqrt(res.x**2 + res.y**2 + res.z**2 + res.w**2)
            if rn > 0:
                res.x, res.y, res.z, res.w = res.x/rn, res.y/rn, res.z/rn, res.w/rn
            return res

        theta_0 = math.acos(min(max(dot, -1.0), 1.0)) # 誤差で1.0を超えないようにクリップ
        sin_theta_0 = math.sin(theta_0)
        
        theta = theta_0 * t
        sin_theta = math.sin(theta)
        
        s1 = math.cos(theta) - dot * sin_theta / sin_theta_0
        s2 = sin_theta / sin_theta_0
        
        res = Quaternion()
        res.x = s1*x1 + s2*x2
        res.y = s1*y1 + s2*y2
        res.z = s1*z1 + s2*z2
        res.w = s1*w1 + s2*w2
        return res

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
            mid_pose.orientation = TrajectoryStrategy.slerp(start_pose.orientation, target_pose.orientation, 0.5)
            waypoints.append(mid_pose)
            waypoints.append(target_pose)
        elif mode == 'trapezoid':
            up_start = copy.deepcopy(start_pose)
            up_start.position.z += height
            waypoints.append(up_start)
            up_goal = copy.deepcopy(target_pose)
            up_goal.position.z += height
            up_goal.orientation = target_pose.orientation # 降りる直前に向きを変える
            waypoints.append(up_goal)
            waypoints.append(target_pose)
        elif mode == 'arc':
            steps = 20
            for i in range(1, steps + 1):
                t = i / float(steps)
                wp = copy.deepcopy(start_pose)
                # 位置計算
                wp.position.x = (1 - t) * start_pose.position.x + t * target_pose.position.x
                wp.position.y = (1 - t) * start_pose.position.y + t * target_pose.position.y
                linear_z = (1 - t) * start_pose.position.z + t * target_pose.position.z
                arc_z = height * math.sin(math.pi * t)
                wp.position.z = linear_z + arc_z
                
                # 【重要】Slerpで滑らかに補間 (Fraction 0.07対策)
                wp.orientation = TrajectoryStrategy.slerp(start_pose.orientation, target_pose.orientation, t)
                
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
                # Time(0)で最新取得 (Fraction 0.0対策)
                if not self._tf_listener.buffer.can_transform(self._base_frame, self._target_frame, Time(seconds=0)):
                    return 

                target_tf = self._tf_listener.buffer.lookup_transform(
                    self._base_frame, self._target_frame, Time(seconds=0))
                
                start_tf = self._tf_listener.buffer.lookup_transform(
                    self._base_frame, self._end_effector, Time(seconds=0))

                Logger.loginfo("Transforms found. Planning...")
                
                start_pose = self._tf_to_pose(start_tf)
                target_pose = self._tf_to_pose(target_tf)

                # ウェイポイント生成 (Slerp有効)
                waypoints = TrajectoryStrategy.generate_waypoints(
                    start_pose, target_pose, mode=self._mode, height=self._height
                )

                # 【必須】現在地を始点に挿入 (Fraction 0.0対策)
                waypoints.insert(0, start_pose)

                # リクエスト作成
                req = GetCartesianPath.Request()
                req.header.frame_id = self._base_frame
                req.header.stamp = Time(seconds=0).to_msg() # 最新時刻固定

                req.group_name = self._group_name
                req.waypoints = waypoints
                
                # 計算負荷緩和のため少し大きく設定 (1cm -> 2cm)
                req.max_step = 0.02
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