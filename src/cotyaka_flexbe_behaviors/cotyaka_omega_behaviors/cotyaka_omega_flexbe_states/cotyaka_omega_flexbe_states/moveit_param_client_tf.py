#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient, ProxyTransformListener
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, PositionConstraint, OrientationConstraint, BoundingVolume
from shape_msgs.msg import SolidPrimitive
from geometry_msgs.msg import Pose

class MoveItTfClientParamState(EventState):
    '''
    パラメータで指定されたTFフレームをターゲットとしてMoveIt(IK)で移動するState。
    
    -- group_name       string  操作するグループ名 (例: 'arm')
    -- end_effector_link string 先端リンク名 (例: 'link6')
    -- reference_frame  string  座標の基準フレーム (例: 'base_link')
    -- target_frame     string  目標とするTFフレーム名 (例: 'home_position')
    -- pos_tolerance    float   位置許容誤差 (m)
    -- orient_tolerance float   姿勢許容誤差 (rad)
    -- action_topic     string  MoveGroupのアクション名

    <= reached          到達
    <= failed           失敗
    '''

    def __init__(self, group_name='arm', end_effector_link='link6', reference_frame='base_link', 
                 target_frame='interactive_set', pos_tolerance=0.01, orient_tolerance=0.01, action_topic='move_action'):
        super(MoveItTfClientParamState, self).__init__(outcomes=['reached', 'failed'])
        self._group_name = group_name
        self._ee_link = end_effector_link
        self._ref_frame = reference_frame
        self._target_frame = target_frame
        self._pos_tol = pos_tolerance
        self._ort_tol = orient_tolerance
        self._topic = action_topic
        
        self._client = ProxyActionClient({self._topic: MoveGroup})
        self._tf_listener = ProxyTransformListener()
        self._error = False

    def on_enter(self, userdata):
        self._error = False
        
        if not self._client.is_available(self._topic):
            Logger.logerr('MoveGroup Action Server not available')
            self._error = True
            return

        # TF取得 (基準フレーム -> ターゲットフレーム)
        try:
            t = self._tf_listener.listener().lookup_transform(
                self._ref_frame, self._target_frame, rclpy.time.Time())
        except Exception as e:
            Logger.logerr(f'Could not get transform {self._ref_frame} -> {self._target_frame}: {e}')
            self._error = True
            return

        # ゴール作成
        goal = MoveGroup.Goal()
        goal.request.group_name = self._group_name
        goal.request.allowed_planning_time = 8.0
        goal.request.num_planning_attempts = 10

        constraints = Constraints()
        
        # 1. 位置制約
        pc = PositionConstraint()
        pc.header.frame_id = self._ref_frame
        pc.link_name = self._ee_link
        pc.weight = 1.0
        
        sphere = SolidPrimitive()
        sphere.type = SolidPrimitive.SPHERE
        sphere.dimensions = [self._pos_tol] 
        
        bv = BoundingVolume()
        bv.primitives.append(sphere)
        
        target_pose = Pose()
        target_pose.position.x = t.transform.translation.x
        target_pose.position.y = t.transform.translation.y
        target_pose.position.z = t.transform.translation.z
        target_pose.orientation = t.transform.rotation
        
        bv.primitive_poses.append(target_pose)
        pc.constraint_region = bv
        constraints.position_constraints.append(pc)

        # 2. 姿勢制約
        oc = OrientationConstraint()
        oc.header.frame_id = self._ref_frame
        oc.link_name = self._ee_link
        oc.orientation = target_pose.orientation
        oc.absolute_x_axis_tolerance = self._ort_tol
        oc.absolute_y_axis_tolerance = self._ort_tol
        oc.absolute_z_axis_tolerance = self._ort_tol
        oc.weight = 1.0
        constraints.orientation_constraints.append(oc)

        goal.request.goal_constraints.append(constraints)

        self._client.send_goal(self._topic, goal)
        Logger.loginfo(f'Sending goal to TF (Param): {self._target_frame}')

    def execute(self, userdata):
        if self._error:
            return 'failed'
            
        if self._client.has_result(self._topic):
            result = self._client.get_result(self._topic)
            if result.error_code.val == 1:
                return 'reached'
            else:
                Logger.logwarn(f'MoveIt error code: {result.error_code.val}')
                return 'failed'