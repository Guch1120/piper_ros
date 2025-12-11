#!/usr/bin/env python3
import rclpy
from flexbe_core import EventState, Logger
from flexbe_core.proxy import ProxyActionClient
from moveit_msgs.action import MoveGroup
from moveit_msgs.msg import Constraints, JointConstraint

class MoveItJointClientParamState(EventState):
    '''
    MoveItを使用して、パラメータで指定された固定の関節角度へ移動するState。

    -- group_name    string  操作するグループ名 (例: 'arm')
    -- joint_names   list    関節名のリスト (例: ['joint1', 'joint2', ...])
    -- target_joints list    目標角度のリスト (joint_namesの順序に対応) [rad, rad, ...]
    -- tolerance     float   目標角度への許容誤差 (rad)
    -- action_topic  string  MoveGroupのアクション名

    <= reached       目標に到達した
    <= failed        移動失敗
    '''

    def __init__(self, group_name='arm', joint_names=[], target_joints=[], tolerance=0.01, action_topic='move_action'):
        super(MoveItJointClientParamState, self).__init__(outcomes=['reached', 'failed'])
        self._group_name = group_name
        self._joint_names = joint_names
        self._target_joints = target_joints
        self._tolerance = tolerance
        self._topic = action_topic
        self._client = ProxyActionClient({self._topic: MoveGroup})
        self._error = False

    def on_enter(self, userdata):
        self._error = False
        
        # Action Serverの確認
        if not self._client.is_available(self._topic):
            Logger.logerr(f'Action Server {self._topic} not available')
            self._error = True
            return

        # パラメータチェック
        if len(self._target_joints) != len(self._joint_names):
            Logger.logerr(f'Length mismatch: target_joints({len(self._target_joints)}) vs joint_names({len(self._joint_names)})')
            self._error = True
            return

        # ゴール作成
        goal = MoveGroup.Goal()
        goal.request.group_name = self._group_name
        goal.request.allowed_planning_time = 5.0
        
        constraints = Constraints()
        for i, name in enumerate(self._joint_names):
            jc = JointConstraint()
            jc.joint_name = name
            jc.position = float(self._target_joints[i])
            jc.tolerance_above = self._tolerance
            jc.tolerance_below = self._tolerance
            jc.weight = 1.0
            constraints.joint_constraints.append(jc)
            
        goal.request.goal_constraints.append(constraints)

        # 送信
        try:
            self._client.send_goal(self._topic, goal)
            Logger.loginfo(f'Sent MoveGroup goal (Param): {self._target_joints}')
        except Exception as e:
            Logger.logerr(f'Failed to send goal: {e}')
            self._error = True

    def execute(self, userdata):
        if self._error:
            return 'failed'

        if self._client.has_result(self._topic):
            result = self._client.get_result(self._topic)
            if result.error_code.val == 1: # SUCCESS
                return 'reached'
            else:
                Logger.logwarn(f'MoveIt failed with error code: {result.error_code.val}')
                return 'failed'