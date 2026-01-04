#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, PositionConstraint, OrientationConstraint, BoundingVolume
from shape_msgs.msg import SolidPrimitive
from geometry_msgs.msg import Pose
import tf2_ros
from rclpy.duration import Duration



class MoveItClientTF(EventState):
    '''
    input keyで受け取ったTFフレームをターゲットとしてMoveItで移動するState。
    '''

    def __init__(self,
                 group_name='arm',
                 end_effector_link='link6',
                 reference_frame='base_link',
                 pos_tolerance=0.01,
                 orient_tolerance=0.01,
                 action_topic='move_action'):

        super().__init__(
            outcomes=['reached', 'failed'],
            input_keys=['target_frame']
        )

        self._group_name = group_name
        self._ee_link = end_effector_link
        self._ref_frame = reference_frame
        self._pos_tol = pos_tolerance
        self._ort_tol = orient_tolerance
        self._topic = action_topic

        # MoveIt Action
        self._client = ProxyActionClient({self._topic: MoveGroup})

        # TF
        self._tf_buffer = None
        self._tf_listener = None

        self._error = False

    def on_enter(self, userdata):
        self._error = False

        # Proxy が保持している node を使う
        node = ProxyActionClient._node

        # TF listener 初期化（1回だけ）
        if self._tf_buffer is None:
            self._tf_buffer = tf2_ros.Buffer()
            self._tf_listener = tf2_ros.TransformListener(
                self._tf_buffer, node
            )

        # Action Server 確認
        if not self._client.is_available(self._topic):
            Logger.logerr('MoveGroup Action Server not available')
            self._error = True
            return

        # デバッグ：受け取っているフレーム名を確認（空白事故・空文字事故を潰す）
        Logger.loginfo(f"[MoveItClientTF] ref='{self._ref_frame}' target='{userdata.target_frame}'")

        # TF取得
        try:
            ok = self._tf_buffer.can_transform(
                self._ref_frame,
                userdata.target_frame,
                rclpy.time.Time(seconds=0),
                timeout=Duration(seconds=1.0)
            )
            if not ok:
                Logger.logerr(f"TF timeout: {self._ref_frame} -> {userdata.target_frame}")
                self._error = True
                return
            t = self._tf_buffer.lookup_transform(
                self._ref_frame,
                userdata.target_frame,
                rclpy.time.Time(seconds=0)
            )
        except Exception as e:
            Logger.logerr(
                f'Could not get transform {self._ref_frame} -> {userdata.target_frame}: {e}'
            )
            self._error = True
            return

        # ===== MoveIt Goal 作成 =====
        goal = MoveGroup.Goal()
        goal.request.group_name = self._group_name
        goal.request.allowed_planning_time = 8.0
        goal.request.num_planning_attempts = 10

        constraints = Constraints()

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
        Logger.loginfo(f'Sending MoveIt goal to TF frame: {userdata.target_frame}')

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
